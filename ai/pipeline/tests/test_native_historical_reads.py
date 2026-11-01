"""Sealed old-source synthetic archives read by the installed current pipeline."""
from __future__ import annotations

import base64
import copy
import fcntl
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from zoop_ai_pipeline import extraction_replay as analysis
from zoop_ai_pipeline.extraction import Extractor, Fixtures, Sources, Store, upstream_digest
from zoop_ai_pipeline.extraction_contracts import ExtractionFailure, Submit, canonical, digest
from zoop_ai_pipeline.ingestion_contracts import Authority
from zoop_ai_pipeline.live_runtime import LiveRuntime
from zoop_ai_pipeline.native_read_contracts import validate_s2_historical_read
from zoop_ai_pipeline.relation import Engine, Fixtures as RelationFixtures, Store as RelationStore
from zoop_ai_pipeline.relation_contracts import Review, Submit as RelationSubmit

GOLDEN = Path(__file__).parent / "fixtures/native_historical/golden.json"
PIPELINE = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN.read_text())


def restore(root, files):
    root.mkdir()
    for name, entry in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(entry["base64"]))
        path.chmod(entry["mode"])
    return root


@pytest.fixture
def archive(tmp_path, golden):
    return restore(tmp_path / "archive", golden["replay"]["files"])


def inventory(root):
    return {str(p.relative_to(root)): (p.stat().st_mode & 0o777, hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
            for p in [root, *root.rglob("*")]}


def source(root):
    return Sources(root / "ingestion", Authority(root / "sources.json"))


def row(root, ledger, job):
    db = sqlite3.connect(f"file:{root / ledger / (ledger + '.sqlite3')}?mode=ro&immutable=1", uri=True)
    db.row_factory = sqlite3.Row
    try:
        return dict(db.execute("SELECT * FROM jobs WHERE job_id=?", (job,)).fetchone())
    finally:
        db.close()


def change_job(root, ledger, job, **columns):
    """Tamper only with a freshly restored authored archive, never the golden fixture."""
    db = sqlite3.connect(root / ledger / (ledger + ".sqlite3"))
    try:
        db.execute("DROP TRIGGER immutable_jobs_input")
        for key, value in columns.items():
            assert key in {"binding", "request", "input_digest", "replay_hash", "state"}
            db.execute(f"UPDATE jobs SET {key}=? WHERE job_id=?", (value, job))
        db.commit()
    finally:
        db.close()


def inspect(root, ledger, job):
    store = Store(root / ledger, root / "ingestion", existing=True) if ledger == "extraction" else RelationStore(
        root / ledger, root / "extraction", root / "ingestion", existing=True)
    try:
        owner = Extractor(store, source(root)) if ledger == "extraction" else Engine(store, source(root), root / "extraction", root / "ingestion")
        return owner.inspect(job)
    finally:
        store.close()


def cli(root, ledger, command, request, *, initial=False, state_dir=None):
    module = {"extraction": "extraction_cli", "relation": "relation_cli", "handoff": "handoff_cli", "graph": "graph_projection_cli"}[ledger]
    guard = ("import sys,runpy\n"
             "def deny(event,args):\n"
             " if event in {'socket.connect','socket.getaddrinfo','socket.gethostbyname','socket.bind'}: raise RuntimeError('network forbidden')\n"
             "sys.addaudithook(deny)\n"
             f"runpy.run_module('zoop_ai_pipeline.{module}',run_name='__main__')\n")
    argv = [sys.executable, "-c", guard, command, "--state-dir", str(root / ledger if state_dir is None else state_dir)]
    if command != "recover":
        argv += ["--ingestion-state-dir", str(root / "ingestion"), "--sources", str(root / "sources.json")]
        if ledger in {"relation", "handoff", "graph"}:
            argv += ["--extraction-state-dir", str(root / "extraction")]
        if ledger in {"handoff", "graph"}:
            argv += ["--relation-state-dir", str(root / "relation")]
            for name in (("canonical", "decisions", "bindings") if ledger == "handoff" else ("canonical",)):
                argv += ["--" + name, str(root / (name + ".json"))]
    if initial:
        argv.append("--initial-only")
    done = subprocess.run(argv, input=canonical(request).encode(), capture_output=True, cwd=PIPELINE, timeout=60,
                          env={"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"})
    assert done.stderr == b"", done.stderr
    return done.returncode, json.loads(done.stdout)


def forbidden(*args, **kwargs):
    raise AssertionError("Historical delivery reached runtime construction or execution")


def assert_frozen_export(result, expected, started, finished):
    assert {k: v for k, v in result.items() if k != "delivery"} == {k: v for k, v in expected.items() if k != "delivery"}
    delivery, frozen = result["delivery"], expected["delivery"]
    assert set(delivery) == set(frozen)
    assert {k: v for k, v in delivery.items() if k != "checkedAt"} == {k: v for k, v in frozen.items() if k != "checkedAt"}
    assert delivery["status"] == "current"
    checked = datetime.fromisoformat(delivery["checkedAt"])
    assert checked.tzinfo is not None and started <= checked <= finished


def test_sealed_replay_bindings_candidates_and_bundle_are_byte_equivalent(archive, golden, monkeypatch):
    monkeypatch.setattr(LiveRuntime, "from_binding", forbidden)
    monkeypatch.setattr(LiveRuntime, "from_env", forbidden)
    before = inventory(archive)
    for key, expected in golden["replay"]["results"].items():
        actual = inspect(archive, "extraction", expected["jobId"])
        assert actual == expected
        assert upstream_digest(actual) == golden["replay"]["upstreamDigests"][key]
    for job, expected in golden["replay"]["relations"].items():
        assert inspect(archive, "relation", job) == {k: v for k, v in expected.items() if k != "fixtures"}
    started = datetime.now(timezone.utc)
    code, result = cli(archive, "handoff", "export", {"schemaVersion": "zoop-ai-handoff-1", "handoffId": "h1"})
    assert code == 0
    assert_frozen_export(result, golden["replay"]["export"], started, datetime.now(timezone.utc))
    assert hashlib.sha256(canonical(result["bundle"]).encode()).hexdigest() == result["receipt"]["bundleDigest"]
    assert inventory(archive) == before


def test_sealed_live_results_use_frozen_metadata_without_runtime(tmp_path, golden, monkeypatch):
    root = restore(tmp_path / "live", golden["live"]["files"])
    monkeypatch.setattr(LiveRuntime, "from_binding", forbidden)
    monkeypatch.setattr(LiveRuntime, "from_env", forbidden)
    before = inventory(root)
    result = inspect(root, "extraction", "historical-live")
    assert result == golden["live"]["result"]
    assert upstream_digest(result) == golden["live"]["upstreamDigest"]
    assert inspect(root, "relation", "historical-live-relation") == golden["live"]["relation"]
    assert inventory(root) == before


@pytest.mark.parametrize("index", [0, 1])
def test_old_language_and_snapshot_preimages_are_not_current_builders(golden, index):
    case = golden["preimages"][index]
    request = Submit.model_validate(case["request"])
    validate_s2_historical_read(case["row"], request, case["exports"])
    member = request.snapshot.events[0].members[0]
    projected = analysis.article(case["exports"][digest(member.observation.wire())], True)
    assert projected.language in {"und", "en"}
    with pytest.raises(ExtractionFailure, match="snapshot_member_invalid"):
        analysis.member_mention(member.mention, projected, analysis.company_names(request.catalogue))
    with pytest.raises(ExtractionFailure, match="snapshot_member_invalid"):
        analysis.member_mention(member.mention, projected.model_copy(update={"language": "ko"}), analysis.company_names(request.catalogue))
    wrong = copy.deepcopy(case["exports"])
    wrong[next(iter(wrong))]["locatorMetadata"]["mappingHash"] = "f" * 64
    with pytest.raises(ExtractionFailure, match="document_binding_changed"):
        validate_s2_historical_read(case["row"], request, wrong)


@pytest.mark.parametrize("ledger,job,edit", [
    ("extraction", "s2-a", "unknown-version"), ("extraction", "s2-a", "mixed-mode"),
    ("extraction", "s2-a", "fingerprint"), ("extraction", "s2-a", "request"),
    ("extraction", "s2-a", "input"), ("extraction", "s2-a", "fixture"),
    ("extraction", "s2-a", "document"), ("extraction", "s2-a", "extra-key"),
    ("relation", "rel-a", "country-context"), ("relation", "rel-a", "policy2-missing-context"),
    ("relation", "rel-a", "unknown-version"), ("relation", "rel-a", "extra-key"),
    ("relation", "rel-a", "upstream"), ("relation", "rel-a", "input"), ("relation", "rel-a", "mixed-mode"),
])
def test_malformed_or_mixed_contracts_fail_closed(archive, ledger, job, edit):
    stored = row(archive, ledger, job)
    binding = json.loads(stored["binding"])
    changes = {}
    if edit == "unknown-version":
        binding["adapter" if ledger == "extraction" else "versions"]["version" if ledger == "extraction" else "policy"] = "unknown"
    elif edit == "mixed-mode":
        binding["live" if ledger == "extraction" else "runtime"] = {}
    elif edit == "fingerprint":
        binding["adapter"]["fingerprint"] = "f" * 64
    elif edit == "extra-key":
        (binding if ledger == "extraction" else binding["versions"])["unexpected"] = None
    elif edit == "request":
        request = json.loads(stored["request"])
        request["promptVersion"] = "changed"
        changes["request"] = canonical(request)
    elif edit == "input":
        changes["input_digest"] = "f" * 64
    elif edit == "fixture":
        changes["replay_hash"] = "f" * 64
    elif edit == "document":
        binding["documents"][binding["incoming"]]["sourceHash"] = "f" * 64
    elif edit == "country-context":
        binding["versions"]["countryContext"] = None
    elif edit == "policy2-missing-context":
        binding["versions"]["policy"] = "zoop-relation-policy-2"
    else:
        binding["upstream"]["digest"] = "f" * 64
    change_job(archive, ledger, job, binding=canonical(binding), **changes)
    before = inventory(archive)
    assert inspect(archive, ledger, job)["delivery"]["status"] == "withheld"
    assert inventory(archive) == before


@pytest.mark.parametrize("field", ["identity", "bindingDigest", "analysisVersion", "runtime-field", "mode"])
def test_live_metadata_tampering_is_refused(tmp_path, golden, field):
    root = restore(tmp_path / "live", golden["live"]["files"])
    binding = json.loads(row(root, "extraction", "historical-live")["binding"])
    live = binding["live"]
    if field == "identity":
        live["runtime"]["identity"] = "f" * 64
    elif field == "runtime-field":
        live["runtime"]["generation"]["model"] = "changed"
    elif field == "mode":
        binding["adapter"]["version"] = "zoop-extraction-native-replay-1"
    else:
        live[field] = "f" * 64
    change_job(root, "extraction", "historical-live", binding=canonical(binding))
    assert inspect(root, "extraction", "historical-live")["delivery"]["status"] == "withheld"


@pytest.mark.parametrize("grant_change,code", [
    ({"enabled": False}, "source_unauthorized"), ({"allowedOperations": ["store", "quote-display"]}, "source_unauthorized"),
    ({"allowedOperations": ["read", "store"]}, "source_unauthorized"), ({"revision": "changed"}, "grant_revision_changed"),
])
def test_historical_exports_recheck_current_authority(archive, grant_change, code):
    path = archive / "sources.json"
    registry = json.loads(path.read_text())
    registry["sources"][0]["grant"].update(grant_change)
    path.write_text(canonical(registry))
    before = inventory(archive)
    for ledger, job in (("extraction", "s2-a"), ("relation", "rel-a")):
        assert inspect(archive, ledger, job)["delivery"] == {"status": "withheld", "code": code}
    exit_code, result = cli(archive, "handoff", "export", {"schemaVersion": "zoop-ai-handoff-1", "handoffId": "h1"})
    assert exit_code == 2 and result["delivery"]["status"] == "withheld"
    assert inventory(archive) == before


@pytest.mark.parametrize("ledger,job,schema,command", [
    (ledger, job, schema, command)
    for ledger, job, schema in (("extraction", "s2-a", "zoop-extraction-s2-2"), ("relation", "rel-a", "zoop-relation-s3"))
    for command in ("run", "submit", "resume", "initial", "cancel", *(("review",) if ledger == "relation" else ()))
])
def test_historical_mutations_refuse_before_writer_side_effects(archive, ledger, job, schema, command):
    stored = row(archive, ledger, job)
    request = json.loads(stored["request"]) if command in {"run", "submit"} else {"schemaVersion": schema, "jobId": job}
    if command == "review":
        request.update(relationCandidateId="rc-" + "a" * 64, decision="allow", expectedRevision=1, reviewer="synthetic-reviewer", note="authored")
    for path in archive.rglob("*"):
        path.chmod(0o550 if path.is_dir() else 0o440)
    before = inventory(archive)
    try:
        code, result = cli(archive, ledger, "resume" if command == "initial" else command, request, initial=command == "initial")
        assert (code, result["error"]["code"]) == (2, "analysis_contract_changed")
        assert inventory(archive) == before
    finally:
        for path in archive.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)


def test_current_analysis_and_new_handoff_refuse_historical_sources(archive, golden):
    before = inventory(archive)
    store = Store(archive / "extraction", archive / "ingestion", existing=True)
    try:
        with pytest.raises(ExtractionFailure, match="analysis_contract_changed"):
            Extractor(store, source(archive)).export_for_analysis("s2-a")
    finally:
        store.close()
    request = json.loads(row(archive, "relation", "rel-a")["request"])
    request["jobId"] = "new-relation"
    assert cli(archive, "relation", "submit", request)[1]["error"]["code"] == "analysis_contract_changed"
    manifest = copy.deepcopy(golden["replay"]["manifest"])
    manifest["handoffId"] = "new-handoff"
    assert cli(archive, "handoff", "freeze", manifest)[1]["error"]["code"] == "analysis_contract_changed"
    assert inventory(archive) == before


@pytest.mark.parametrize("state", ["queued", "stopped", "cancelled"])
def test_nonready_historical_records_are_metadata_only(archive, state):
    for ledger, job, content in (("extraction", "s2-a", "eventCandidates"), ("relation", "rel-a", "relations")):
        change_job(archive, ledger, job, state=state)
        result = inspect(archive, ledger, job)
        assert result["delivery"]["status"] == "withheld" and content not in result


@pytest.mark.parametrize("ledger,job,schema", [("extraction", "s2-a", "zoop-extraction-s2-2"), ("relation", "rel-a", "zoop-relation-s3")])
def test_cli_inspect_is_readonly_and_refuses_busy_or_hot_wal(archive, ledger, job, schema):
    before = inventory(archive)
    assert cli(archive, ledger, "inspect", {"schemaVersion": schema, "jobId": job})[0] == 0
    assert inventory(archive) == before
    with (archive / ledger / (ledger + ".lock")).open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = cli(archive, ledger, "inspect", {"schemaVersion": schema, "jobId": job})[1]
        assert result["error"]["code"] == ledger + "_busy"
    wal = archive / ledger / (ledger + ".sqlite3-wal")
    wal.write_bytes(b"authored hot WAL refusal")
    before = inventory(archive)
    result = cli(archive, ledger, "inspect", {"schemaVersion": schema, "jobId": job})[1]
    assert result["error"]["code"] == ledger + "_recovery_required"
    assert inventory(archive) == before


@pytest.mark.parametrize("drift", ["operator", "review"])
def test_frozen_handoff_keeps_operator_and_review_gates(archive, drift):
    if drift == "operator":
        with (archive / "canonical.json").open("ab") as stream:
            stream.write(b"\n")
    else:
        db = sqlite3.connect(archive / "relation/relation.sqlite3")
        try:
            target = db.execute("SELECT relation_candidate_id,MAX(seq) FROM relation_events WHERE job_id='rel-a' AND kind='review'").fetchone()
            payload = {"decision": "reject", "reviewer": "synthetic-reviewer", "note": "authored drift", "expectedRevision": target[1], "effect": "excluded"}
            db.execute("INSERT INTO relation_events VALUES(?,?,?,?,?,?)", ("rel-a", target[0], target[1] + 1, "review", canonical(payload), "2026-10-31T00:00:00+00:00"))
            db.commit()
        finally:
            db.close()
    before = inventory(archive)
    code, result = cli(archive, "handoff", "export", {"schemaVersion": "zoop-ai-handoff-1", "handoffId": "h1"})
    assert code == 2 and result["delivery"]["status"] == "withheld"
    assert inventory(archive) == before


def test_historical_owner_methods_refuse_before_transactions(archive, monkeypatch):
    before = inventory(archive)
    monkeypatch.setattr(LiveRuntime, "from_binding", forbidden)
    monkeypatch.setattr(LiveRuntime, "from_env", forbidden)
    extraction = Store(archive / "extraction", archive / "ingestion", existing=True)
    relation = RelationStore(archive / "relation", archive / "extraction", archive / "ingestion", existing=True)
    try:
        ex = Extractor(extraction, source(archive))
        rel = Engine(relation, source(archive), archive / "extraction", archive / "ingestion")
        ex_request = Submit.model_validate_json(row(archive, "extraction", "s2-a")["request"])
        rel_request = RelationSubmit.model_validate_json(row(archive, "relation", "rel-a")["request"])
        review = Review.model_validate({"schemaVersion": "zoop-relation-s3", "jobId": "rel-a", "relationCandidateId": "rc-" + "a" * 64,
                                       "decision": "allow", "expectedRevision": 1, "reviewer": "synthetic-reviewer", "note": "authored"})
        mutations = (lambda: ex.freeze(ex_request, Fixtures(None, None)), lambda: ex.run(ex_request, Fixtures(None, None)),
                     lambda: ex.resume("s2-a", Fixtures(None, None), initial_only=True), lambda: ex.cancel("s2-a"),
                     lambda: rel.freeze(rel_request), lambda: rel.run(rel_request, RelationFixtures(None, None)),
                     lambda: rel.resume("rel-a", RelationFixtures(None, None), initial_only=True),
                     lambda: rel.cancel("rel-a"), lambda: rel.review(review))
        for mutate in mutations:
            with pytest.raises(ExtractionFailure, match="analysis_contract_changed"):
                mutate()
    finally:
        extraction.close()
        relation.close()
    assert inventory(archive) == before


def test_changed_exact_observation_is_not_replaced_by_another_observation(archive):
    stored = row(archive, "extraction", "s2-a")
    request = json.loads(stored["request"])
    request["incoming"]["ordinal"] += 100
    change_job(archive, "extraction", "s2-a", request=canonical(request),
               input_digest=digest({"request": request, "replayFixtureHash": stored["replay_hash"]}))
    result = inspect(archive, "extraction", "s2-a")
    assert result["delivery"] == {"status": "withheld", "code": "observation_not_found"}


@pytest.mark.parametrize("command", ["freeze", "project", "recover"])
def test_historical_graph_mutations_refuse_before_writer_or_neo4j(archive, command):
    request = {"schemaVersion": "zoop-graph-projection-1", "versionId": "historical-graph"}
    if command == "freeze":
        request["versionId"] = "new-historical-graph"
        request["relation"] = {"jobId": "rel-a", "inputDigest": row(archive, "relation", "rel-a")["input_digest"]}
    before = inventory(archive)
    code, result = cli(archive, "graph", command, request)
    assert (code, result["error"]["code"]) == (2, "analysis_contract_changed")
    assert inventory(archive) == before


def test_changed_upstream_result_is_withheld_by_existing_digest_owner(archive):
    db = sqlite3.connect(archive / "extraction/extraction.sqlite3")
    try:
        db.execute("DROP TRIGGER immutable_event_candidates_update")
        event_id, payload = db.execute("SELECT event_candidate_id,payload FROM event_candidates WHERE job_id='s2-a' LIMIT 1").fetchone()
        changed = json.loads(payload)
        changed["mention"]["title"] = "synthetic tampered result"
        db.execute("UPDATE event_candidates SET payload=? WHERE event_candidate_id=?", (canonical(changed), event_id))
        db.commit()
    finally:
        db.close()
    assert inspect(archive, "relation", "rel-a")["delivery"] == {"status": "withheld", "code": "upstream_changed"}
    code, result = cli(archive, "handoff", "export", {"schemaVersion": "zoop-ai-handoff-1", "handoffId": "h1"})
    assert code == 2 and result["delivery"]["status"] == "withheld"


def test_historical_bundle_reads_on_readonly_filesystem(archive, golden):
    for path in archive.rglob("*"):
        path.chmod(0o550 if path.is_dir() else 0o440)
    before = inventory(archive)
    try:
        started = datetime.now(timezone.utc)
        code, result = cli(archive, "handoff", "export", {"schemaVersion": "zoop-ai-handoff-1", "handoffId": "h1"})
        assert code == 0
        assert_frozen_export(result, golden["replay"]["export"], started, datetime.now(timezone.utc))
        assert inventory(archive) == before
    finally:
        for path in archive.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)


@pytest.mark.parametrize("ledger", ["extraction", "relation"])
def test_current_hot_wal_recovery_has_no_lifetime_copy_cap_and_history_stays_immutable(archive, tmp_path, monkeypatch, ledger):
    import contextlib
    import io
    from scripts.relation_smoke import build_world
    from zoop_ai_pipeline import extraction_cli, ingestion_contracts, relation_cli
    from zoop_ai_pipeline.extraction import mutation_job, open_job_inspection

    world = build_world(tmp_path / "current")
    root, job = world.kit.root, "wal-only-target"
    schema = "zoop-extraction-s2-2" if ledger == "extraction" else "zoop-relation-s3"
    store_type = Store if ledger == "extraction" else RelationStore
    upstreams = (root / "ingestion",) if ledger == "extraction" else (root / "extraction", root / "ingestion")
    if ledger == "relation":
        RelationStore(root / ledger, *upstreams).close()
    request = (world.kit.submit(job, world.refs["main"], [world.snapshot]) if ledger == "extraction"
               else world.kit.rsubmit(job, world.s2))
    historical = row(archive, ledger, "s2-a" if ledger == "extraction" else "rel-a")
    unsupported = {**historical, "job_id": "unsupported-target"}
    binding = json.loads(unsupported["binding"])
    if ledger == "extraction":
        binding["adapter"]["version"] = "zoop-extraction-native-replay-unknown"
    else:
        binding["versions"]["policy"] = "zoop-relation-policy-unknown"
    unsupported["binding"] = canonical(binding)
    freeze_and_crash = """
import json, os, sys
from pathlib import Path
from zoop_ai_pipeline.extraction import Extractor, Fixtures, Sources, Store
from zoop_ai_pipeline.extraction_contracts import Submit
from zoop_ai_pipeline.ingestion_contracts import Authority
from zoop_ai_pipeline.relation import Engine, Store as RelationStore
from zoop_ai_pipeline.relation_contracts import Submit as RelationSubmit
root, ledger, replay = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
source = Sources(root / "ingestion", Authority(root / "sources.json"))
payload = json.load(sys.stdin)
request = payload["request"]
if ledger == "extraction":
    store = Store(root / ledger, root / "ingestion")
    Extractor(store, source).freeze(Submit.model_validate(request), Fixtures(replay.read_bytes(), None))
else:
    store = RelationStore(root / ledger, root / "extraction", root / "ingestion")
    Engine(store, source, root / "extraction", root / "ingestion").freeze(RelationSubmit.model_validate(request))
for row in payload["otherRows"]:
    store.db.execute("INSERT INTO jobs(" + ",".join(row) + ") VALUES(" + ",".join("?" for _ in row) + ")", tuple(row.values()))
os._exit(0)
"""
    child = subprocess.run([sys.executable, "-c", freeze_and_crash, str(root), ledger, str(world.s2_replay)],
                           input=canonical({"request": request, "otherRows": [historical, unsupported]}).encode(),
                           capture_output=True, cwd=PIPELINE, timeout=60,
                           env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"})
    assert child.returncode == 0 and child.stderr == b"", child.stderr
    database = root / ledger / (ledger + ".sqlite3")
    wal = database.with_name(database.name + "-wal")
    assert wal.stat().st_size > 0
    checkpoint = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        assert checkpoint.execute("SELECT COUNT(*) FROM jobs WHERE job_id=?", (job,)).fetchone()[0] == 0
    finally:
        checkpoint.close()

    # Scale the former 128 MiB helper limit down; real DB and WAL files both exceed it.
    monkeypatch.setattr(ingestion_contracts, "MAX_LEDGER_COPY", 1)
    before = inventory(root)
    recovered = mutation_job(store_type, root / ledger, *upstreams, job_id=job, ledger=ledger)
    assert recovered["job_id"] == job and recovered["state"] == "queued"
    assert inventory(root) == before
    selector = {"schemaVersion": schema, "jobId": job}
    code, inspected = cli(root, ledger, "inspect", selector)
    assert code == 0 and inspected["state"] == "queued" and inspected["calls"] == []
    assert inventory(root) == before
    for target in (historical["job_id"], unsupported["job_id"]):
        code, refused = cli(root, ledger, "inspect", {**selector, "jobId": target})
        assert (code, refused["error"]["code"]) == (2, ledger + "_recovery_required")
        assert inventory(root) == before
    reader = open_job_inspection(store_type, root / ledger, *upstreams, job_id=job, ledger=ledger)
    try:
        with (root / ledger / (ledger + ".lock")).open("rb") as lock:
            with pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.db.execute("UPDATE jobs SET state='cancelled' WHERE job_id=?", (job,))
    finally:
        reader.close()
    assert inventory(root) == before

    def invoke(directory, target, command, replay=None):
        argv = ["zoop-ai-" + ledger, command, "--state-dir", str(directory / ledger),
                "--ingestion-state-dir", str(directory / "ingestion"), "--sources", str(directory / "sources.json")]
        if ledger == "relation":
            argv += ["--extraction-state-dir", str(directory / "extraction")]
        if replay is not None:
            argv += ["--replay", str(replay)]
        output = io.StringIO()
        with io.TextIOWrapper(io.BytesIO(canonical({"schemaVersion": schema, "jobId": target}).encode())) as incoming:
            with monkeypatch.context() as patch, contextlib.redirect_stdout(output):
                patch.setattr(sys, "argv", argv)
                patch.setattr(sys, "stdin", incoming)
                code = (extraction_cli if ledger == "extraction" else relation_cli).main()
        return code, json.loads(output.getvalue())

    command = "resume" if ledger == "extraction" else "cancel"
    code, result = invoke(root, job, command, world.s2_replay if ledger == "extraction" else None)
    assert code == (0 if ledger == "extraction" else 2)
    assert result["state"] == ("ready" if ledger == "extraction" else "cancelled")
    assert result["usage"]["providerCalls"] == 0
    again = invoke(root, job, command)[1]
    assert again["calls"] == result["calls"] and again["state"] == result["state"]

    historical_job = "s2-a" if ledger == "extraction" else "rel-a"
    historical_db = archive / ledger / (ledger + ".sqlite3")
    leave_wal = ("import os,sqlite3,sys\n"
                 "db=sqlite3.connect(sys.argv[1]); db.execute('PRAGMA journal_mode=WAL')\n"
                 "db.execute('UPDATE jobs SET updated_at=? WHERE job_id=?',('2088-01-01T00:00:00+00:00',sys.argv[2]))\n"
                 "db.commit(); os._exit(0)\n")
    child = subprocess.run([sys.executable, "-c", leave_wal, str(historical_db), historical_job], capture_output=True, timeout=60,
                           env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"})
    assert child.returncode == 0 and child.stderr == b"", child.stderr
    assert historical_db.with_name(historical_db.name + "-wal").stat().st_size > 0
    for path in (archive / ledger).iterdir():
        path.chmod(0o440)
    (archive / ledger).chmod(0o550)
    before = inventory(archive)
    try:
        code, result = invoke(archive, historical_job, "inspect")
        assert (code, result["error"]["code"]) == (2, ledger + "_recovery_required")
        code, result = invoke(archive, historical_job, command)
        assert (code, result["error"]["code"]) == (2, "analysis_contract_changed")
        assert inventory(archive) == before
    finally:
        (archive / ledger).chmod(0o700)
        for path in (archive / ledger).iterdir():
            path.chmod(0o600)


@pytest.mark.parametrize("ledger,schema", [("extraction", "zoop-extraction-s2-2"), ("relation", "zoop-relation-s3")])
def test_cli_inspection_distinguishes_pristine_job_absence_from_partial_state(archive, tmp_path, ledger, schema):
    state_dir = tmp_path / "fresh-native-state"
    selector = {"schemaVersion": schema, "jobId": "first-service-job"}

    def probe(expected):
        before = inventory(tmp_path)
        code, result = cli(archive, ledger, "inspect", selector, state_dir=state_dir)
        assert (code, result) == (2, {"schemaVersion": schema, "error": {"code": expected}})
        assert inventory(tmp_path) == before

    probe("job_not_found")
    state_dir.mkdir(mode=0o750)
    probe("job_not_found")
    (state_dir / (ledger + ".lock")).touch(mode=0o640)
    probe(ledger + "_state_missing")
    (state_dir / (ledger + ".sqlite3")).write_bytes(b"authored corrupt ledger")
    probe(ledger + "_state_invalid")


@pytest.mark.parametrize("ledger", ["extraction", "relation"])
@pytest.mark.parametrize("boundary", ["unknown", "receipt", "stage"])
def test_current_crash_inspection_preserves_wal_and_explicit_resume_receipts(tmp_path, ledger, boundary):
    from scripts.relation_smoke import build_world, relation_reply

    world = build_world(tmp_path / "current")
    kit, job = world.kit, "interrupted-job"
    root = kit.root
    if ledger == "extraction":
        selector = kit.job_selector(job)
        runner, stage, content = kit.run, "extract", "eventCandidates"
        runner("submit", kit.submit(job, world.refs["main"]), replay=world.s2_replay)
        replay = world.s2_replay
    else:
        selector = kit.rsel(job)
        runner, stage, content = kit.rel, "relation", "relations"
        pending = runner("run", kit.rsubmit(job, world.s2))
        assert pending["failure"]["code"] == "producer_replay_required"
        replay = kit.fixture("producer", "empty-relations", [
            ("relation", pending["failure"]["detail"]["requestDigest"], relation_reply([]))])
    crash = "stage:" + stage if boundary == "stage" else boundary
    runner("resume", selector, replay=replay, crash=crash, expected=75)
    directory = root / ledger
    assert (directory / (ledger + ".sqlite3-wal")).stat().st_size > 0
    modes = {path: path.stat().st_mode & 0o777 for path in [directory, *directory.iterdir()]}
    for path in modes:
        path.chmod(0o550 if path.is_dir() else 0o440)
    before = inventory(root)
    try:
        with pytest.raises(ExtractionFailure, match=ledger + "_recovery_required"):
            if ledger == "extraction":
                Store(directory, root / "ingestion", existing=True)
            else:
                RelationStore(directory, root / "extraction", root / "ingestion", existing=True)
        with (directory / (ledger + ".lock")).open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            code, busy = cli(root, ledger, "inspect", selector)
            assert (code, busy["error"]["code"]) == (2, ledger + "_busy")
        code, interrupted = cli(root, ledger, "inspect", selector)
        assert code == 0 and interrupted["state"] == "running"
        assert interrupted["stages"][stage]["state"] == ("complete" if boundary == "stage" else "pending")
        assert interrupted["usage"]["replayCalls"] == int(boundary != "unknown")
        assert interrupted["usage"]["startedWithoutReceipt"] == int(boundary == "unknown")
        assert len(interrupted["calls"]) == 1
        assert cli(root, ledger, "inspect", selector) == (code, interrupted)
        assert inventory(root) == before

        registry = kit.registry_path.read_bytes()
        authority = json.loads(registry)
        authority["sources"][0]["grant"]["enabled"] = False
        kit.registry_path.write_text(canonical(authority))
        try:
            revoked_before = inventory(root)
            code, revoked = cli(root, ledger, "inspect", selector)
            assert code == 2 and revoked["delivery"] == {"status": "withheld", "code": "source_unauthorized"}
            assert content not in revoked and revoked["calls"] == interrupted["calls"]
            assert inventory(root) == revoked_before
        finally:
            kit.registry_path.write_bytes(registry)
        assert inventory(root) == before
    finally:
        for path, mode in modes.items():
            path.chmod(mode)

    settled = runner("resume", selector)
    assert settled["state"] == ("reconciling" if boundary == "unknown" else "ready")
    assert settled["usage"] == interrupted["usage"]
    assert len(settled["calls"]) == 1
    assert settled["calls"][0]["responseDigest"] == interrupted["calls"][0]["responseDigest"]
    if boundary == "unknown":
        assert settled["failure"]["code"] == "replay_response_unknown"
        assert settled["resumeMode"] == "reconcile_only"
    assert runner("resume", selector) == settled
