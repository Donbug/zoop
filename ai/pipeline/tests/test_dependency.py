"""Offline S4 dependents report: which stored S2/S3 jobs and candidates rest on a changed document/source/grant.

The ledgers are REAL: actual ingestion subprocess, S2 extraction and S3 relation/impact built through the owners' own seams from authored HTML
and authored replay (no network, model or original PoC state, no claim about AI quality). Expectations come from the authored world and the owners'
delivered results, never from an echo of the reader under test. Mutating scenarios work on private copies of the ledgers.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from scripts import dependency_smoke as ds
from scripts.dependency_smoke import build, by, dep, document, grant, labels, listed, query, same_request_other_binding, source
from scripts.extraction_smoke import page
from scripts.ingestion_smoke import json_bytes
from scripts.relation_smoke import MAIN_TEXT, build_world, tree
from zoop_ai_pipeline import dependency_cli, relation
from zoop_ai_pipeline.dependency_contracts import MAX_COMMAND, SCHEMA
from zoop_ai_pipeline.extraction import Extractor, Fixtures, Sources
from zoop_ai_pipeline.extraction import Store as ExtractionStore
from zoop_ai_pipeline.extraction_contracts import LEDGER_VERSION, Submit
from zoop_ai_pipeline.ingestion import Ingestor
from zoop_ai_pipeline.ingestion import Store as IngestionStore
from zoop_ai_pipeline.ingestion_contracts import Authority
from zoop_ai_pipeline.relation import Store as RelationStore
from zoop_ai_pipeline.relation import upstream_digest

LISTS = ("snapshotEvents", "eventCandidates", "comparisons", "topicCandidates")
# Every key a report may carry: identities, coordinates, states and codes. No text-bearing key exists in it.
KEYS = frozenset({
    "schemaVersion", "changed", "kind", "documentId", "documentVersion", "rawVersion", "sourceId", "grantId", "revision", "identity", "bound", "recordedInIngestion",
    "basis", "consistency", "notCovered", "extraction", "relation", "ledgerVersion", "scannedJobs", "jobs", "unresolved", "jobId", "inputDigest", "state", "phase",
    "failureCode", "matchedDocuments", "role", "roundId", "page", "ordinal", "grant", "jobScope", "boundDocuments", "snapshotEvents", "eventCandidates", "comparisons",
    "topicCandidates", "eventId", "reasons", "code", "targetEventId", "eventCandidateId", "targetRevision", "topicCandidateId", "ref", "at",
    "upstream", "relationCandidates", "impactCandidates", "relationCandidateId", "relationKey", "eligibility", "impactCandidateId", "verdictStatus", "counts",
    "unresolvedJobs", "effect", "usage", "providerCalls", "modelCalls"})


# ---------------------------------------------------------------- fixtures and runners ---------------------------------

@pytest.fixture(scope="module")
def shared(tmp_path_factory):
    """One real world, never mutated by a test: two S2 jobs (ready, and stopped-then-cancelled) and two S3 jobs (ready, stopped)."""
    return build(tmp_path_factory.mktemp("zoop-s4") / "owned")


@pytest.fixture
def world(tmp_path):
    return build_world(tmp_path / "owned")


@pytest.fixture
def ledgers(shared, tmp_path):
    """A private copy of the three built ledgers for scenarios that corrupt, lock or otherwise change them."""
    root = tmp_path / "ledgers"
    root.mkdir()
    for name in ds.LEDGERS:
        shutil.copytree(shared.kit.root / name, root / name)
    return root


def fresh(root: Path, tmp_path: Path, tag: str) -> Path:
    target = tmp_path / tag
    shutil.copytree(root, target)
    return target


def snapshot(root: Path) -> dict:
    return {name: tree(root / name) for name in ds.LEDGERS}


def invoke(root: Path, request, *, ingestion: str = "ingestion", extraction: str = "extraction", relation_dir: str | None = "relation", expected: int = 0):
    """The real CLI entrypoint in-process: argv and stdin in, exactly one canonical JSON line out."""
    raw = request if isinstance(request, bytes) else json_bytes(request)
    argv = ["zoop-ai-dependents", "--ingestion-state-dir", str(root / ingestion), "--extraction-state-dir", str(root / extraction)]
    if relation_dir:
        argv += ["--relation-state-dir", str(root / relation_dir)]
    out = io.StringIO()
    with mock.patch.object(sys, "argv", argv), mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw))), contextlib.redirect_stdout(out):
        code = dependency_cli.main()
    text = out.getvalue()
    assert code == expected, text
    assert text.endswith("\n") and text.count("\n") == 1, text
    return json.loads(text), text


def refused(report: dict, code: str, detail: dict | None = None) -> None:
    assert report == {"schemaVersion": SCHEMA, "error": {"code": code, **({"detail": detail} if detail else {})}}


def cite(at: str, ref: dict) -> dict:
    return {"code": "cites", "at": at, "documentId": ref["documentId"], "documentVersion": ref["documentVersion"]}


def identity(ref: dict) -> dict:
    return {"documentId": ref["documentId"], "documentVersion": ref["documentVersion"]}


def matched(ref: dict, role: str, revision: str = "rights-1") -> dict:
    return {"role": role, "roundId": ref["roundId"], "sourceId": ref["sourceId"], "page": ref["page"], "ordinal": ref["ordinal"], "documentId": ref["documentId"],
            "rawVersion": ref["rawVersion"], "documentVersion": ref["documentVersion"], "grant": {"grantId": "operator-grant", "revision": revision}}


def keys_of(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys_of(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys_of(v)}
    return set()


# ---------------------------------------------------------------- traversal across the three ledgers --------------------

def test_snapshot_member_seed_reaches_event_comparison_topic_and_only_the_relations_routed_through_it(shared):
    w, ids, b = shared, labels(shared), shared.refs["b"]
    report, _ = invoke(w.kit.root, document(b))
    assert report["identity"] == {"bound": True, "recordedInIngestion": True} and report["changed"] == document(b)["changed"]
    jobs = report["extraction"]["jobs"]
    assert report["extraction"]["ledgerVersion"] == LEDGER_VERSION and report["extraction"]["scannedJobs"] == 2 and [j["jobId"] for j in jobs] == ["s2-cancel", "s2-job"]
    job = by(jobs, "jobId", "s2-job")
    assert job["matchedDocuments"] == [matched(b, "snapshot-member")]
    assert job["snapshotEvents"] == [{"eventId": "event-1", "revision": "rev-1", "reasons": [{"code": "member_document", **identity(b)}]}]
    # The extracted candidate is NOT extracted from b: it was only compared against the event b belongs to.
    assert job["eventCandidates"] == [{"eventCandidateId": w.evc, "state": "candidate", "reasons": [{"code": "disposition_input", "targetEventId": "event-1"}]}]
    assert job["comparisons"] == [{"eventCandidateId": w.evc, "targetEventId": "event-1", "targetRevision": "rev-1", "reasons": [{"code": "target_event_member"}]}]
    assert job["topicCandidates"] == [{"topicCandidateId": w.tp, "reasons": [{"code": "member_event", "kind": "snapshot-event", "ref": "event-1"}, {"code": "cites", **identity(b)}]}]
    assert job["jobScope"] == {"boundDocuments": 2, "snapshotEvents": 1, "eventCandidates": 1, "comparisons": 1, "topicCandidates": 1}

    rel = by(report["relation"]["jobs"], "jobId", "rel-main")
    assert rel["upstream"] == {"jobId": "s2-job", "inputDigest": w.s2["inputDigest"]} and rel["reasons"] == [{"code": "upstream"}] and report["relation"]["unresolved"] == []
    # Only the event endpoint and the topic endpoint route to b. Relations that merely cite the incoming document, the event candidate endpoint and an event
    # ID spelled as a topic are all absent, though the whole job is in scope.
    assert {r["relationCandidateId"]: (r["eligibility"], r["reasons"]) for r in rel["relationCandidates"]} == {
        ids["event"]: ("eligible", [{"code": "endpoint_event", "role": "object", "ref": "event-1"}, cite("citations", b)]),
        ids["topic"]: ("eligible", [{"code": "endpoint_topic", "role": "object", "ref": w.tp}])}
    assert listed(rel, ids) == {"event", "topic"}
    assert rel["impactCandidates"] == [{"impactCandidateId": rel["impactCandidates"][0]["impactCandidateId"], "relationCandidateId": ids["event"], "verdictStatus": "verified",
                                        "reasons": [{"code": "relation", "relationCandidateId": ids["event"]}, cite("supporting", b)]}]
    assert rel["jobScope"] == {"relationCandidates": 9, "impactCandidates": 2}
    owner = {r["relationCandidateId"]: r["relationKey"] for r in w.rel["relations"]}
    assert all(r["relationKey"] == owner[r["relationCandidateId"]] for r in rel["relationCandidates"])


def test_incoming_document_seed_reaches_extracted_candidates_comparisons_topics_relations_and_impacts(shared):
    w, ids, main = shared, labels(shared), shared.refs["main"]
    report, _ = invoke(w.kit.root, document(main))
    job = by(report["extraction"]["jobs"], "jobId", "s2-job")
    assert job["matchedDocuments"] == [matched(main, "incoming")] and job["snapshotEvents"] == []
    assert job["eventCandidates"] == [{"eventCandidateId": w.evc, "state": "candidate", "reasons": [{"code": "extracted_from"}]}]
    assert job["comparisons"] == [{"eventCandidateId": w.evc, "targetEventId": "event-1", "targetRevision": "rev-1", "reasons": [{"code": "incoming_document"}]}]
    assert job["topicCandidates"] == [{"topicCandidateId": w.tp, "reasons": [{"code": "member_event", "kind": "event-candidate", "ref": w.evc}, {"code": "cites", **identity(main)}]}]

    rel = by(report["relation"]["jobs"], "jobId", "rel-main")
    assert {r["relationCandidateId"]: (r["eligibility"], r["reasons"]) for r in rel["relationCandidates"]} == {
        ids["battery"]: ("eligible", [cite("citations", main)]),
        ids["two-hop"]: ("eligible", [cite("step:1", main), cite("step:2", main)]),
        ids["invest"]: ("eligible", [cite("citations", main), cite("validity", main)]),
        ids["topic"]: ("eligible", [{"code": "endpoint_topic", "role": "object", "ref": w.tp}, cite("citations", main)]),
        ids["alias"]: ("reject", [cite("citations", main)]),   # a topic endpoint spelling an event ID is not an event dependency
        ids["candidate"]: ("eligible", [{"code": "endpoint_event", "role": "object", "ref": w.evc}, cite("citations", main)]),
        ids["reversed"]: ("hold", [cite("citations", main)]),
        ids["forged"]: ("reject", [cite("citations", main)])}   # a failed citation still names its document
    assert ids["event"] not in {r["relationCandidateId"] for r in rel["relationCandidates"]}
    assert [(i["relationCandidateId"], i["verdictStatus"], i["reasons"]) for i in rel["impactCandidates"]] == [
        (ids["battery"], "verified", [{"code": "relation", "relationCandidateId": ids["battery"]}, cite("supporting", main), cite("opposing", main)])]


def test_source_and_grant_seeds_list_every_artifact_of_each_affected_job_and_agree_with_the_owners_totals(shared):
    k = shared.kit
    reports = [invoke(k.root, request)[0] for request in (source(), grant())]
    assert reports[0]["extraction"] == reports[1]["extraction"] and reports[0]["relation"] == reports[1]["relation"]
    report = reports[0]
    assert report["identity"] == {"bound": True, "recordedInIngestion": True}
    for job in report["extraction"]["jobs"]:
        owner = k.job("inspect", k.job_selector(job["jobId"]))["counts"]
        assert job["jobScope"] == {"boundDocuments": owner["documents"], "snapshotEvents": owner["snapshotEvents"], "eventCandidates": owner["eventCandidates"]["total"],
                                   "comparisons": owner["comparisons"], "topicCandidates": owner["topicCandidates"]}
        assert {n: len(job[n]) for n in LISTS} == {n: job["jobScope"][n] for n in LISTS} and len(job["matchedDocuments"]) == job["jobScope"]["boundDocuments"] == 2
        assert sorted(m["role"] for m in job["matchedDocuments"]) == ["incoming", "snapshot-member"]
    for job in report["relation"]["jobs"]:
        owner = k.rel_job("inspect", k.rsel(job["jobId"]))["counts"]
        assert job["jobScope"] == {"relationCandidates": owner["relations"], "impactCandidates": owner["impactCandidates"]}
        assert len(job["relationCandidates"]) == owner["relations"] and len(job["impactCandidates"]) == owner["impactCandidates"]


def test_stopped_and_cancelled_jobs_are_reported_with_their_ledger_state_and_whole_job_scope(shared):
    report, _ = invoke(shared.kit.root, document(shared.refs["main"]))
    cancelled, ready = by(report["extraction"]["jobs"], "jobId", "s2-cancel"), by(report["extraction"]["jobs"], "jobId", "s2-job")
    assert (cancelled["state"], cancelled["phase"], cancelled["failureCode"]) == ("cancelled", "cancelled", "topic_replay_required")
    assert cancelled["jobScope"] == {"boundDocuments": 2, "snapshotEvents": 1, "eventCandidates": 1, "comparisons": 1, "topicCandidates": 0} and cancelled["topicCandidates"] == []
    assert cancelled["eventCandidates"][0]["reasons"] == [{"code": "extracted_from"}]
    assert (ready["state"], ready["phase"], ready["failureCode"]) == ("ready", "complete", None)
    stopped = by(report["relation"]["jobs"], "jobId", "rel-stopped")
    assert (stopped["state"], stopped["phase"], stopped["failureCode"]) == ("stopped", "relation", "producer_replay_required")
    assert stopped["jobScope"] == {"relationCandidates": 0, "impactCandidates": 0} and stopped["relationCandidates"] == [] and stopped["impactCandidates"] == []


def test_omitting_the_relation_ledger_reports_null_never_an_empty_result(shared):
    full, _ = invoke(shared.kit.root, document(shared.refs["b"]))
    bare, _ = invoke(shared.kit.root, document(shared.refs["b"]), relation_dir=None)
    assert full["relation"] is not None and bare["relation"] is None and bare["counts"]["relation"] is None
    assert bare["extraction"] == full["extraction"] and "unscanned-relation-ledgers" in bare["notCovered"]


# ---------------------------------------------------------------- what the identity means -------------------------------

def test_document_id_matches_every_bound_version_but_an_exact_unbound_version_is_a_confirmed_empty(world):
    k, main = world.kit, world.refs["main"]
    (changed,) = k.ingest("docs2", [{"supplier": "supplier-main", "html": page(*MAIN_TEXT, "추가된 문단이다.")}])
    assert changed["documentId"] == main["documentId"] and changed["documentVersion"] != main["documentVersion"] and changed["rawVersion"] != main["rawVersion"]
    run = lambda request, **kw: invoke(k.root, request, relation_dir=None, **kw)  # noqa: E731

    every, _ = run(document(main, version=False))
    assert every["identity"] == {"bound": True, "recordedInIngestion": True}
    assert {m["documentVersion"] for j in every["extraction"]["jobs"] for m in j["matchedDocuments"]} == {main["documentVersion"]}
    assert run(document(main))[0]["extraction"]["jobs"] == every["extraction"]["jobs"] and run(document(main, version=False, raw=True))[0]["identity"]["bound"] is True

    for unbound in (document(changed), document(changed, version=False, raw=True), document(changed, raw=True)):
        empty, _ = run(unbound)
        assert empty["identity"] == {"bound": False, "recordedInIngestion": True}
        assert empty["extraction"] == {"ledgerVersion": LEDGER_VERSION, "scannedJobs": 1, "jobs": []} and empty["relation"] is None
        assert empty["counts"] == {"extraction": {"jobs": 0, "matchedDocuments": 0, "snapshotEvents": 0, "eventCandidates": 0, "comparisons": 0, "topicCandidates": 0}, "relation": None}


def test_unknown_or_mismatched_identities_are_refused_instead_of_reported_empty(world):
    k, main, b = world.kit, world.refs["main"], world.refs["b"]
    (changed,) = k.ingest("docs2", [{"supplier": "supplier-main", "html": page(*MAIN_TEXT, "추가된 문단이다.")}])
    pair = lambda document_id, version, raw: query({"kind": "document", "documentId": document_id, "documentVersion": version, "rawVersion": raw})  # noqa: E731
    for request in (document({**main, "documentId": "doc-unknown"}),
                    pair(main["documentId"], b["documentVersion"], None),                  # a real version of another document
                    pair(main["documentId"], None, b["rawVersion"]),
                    pair(main["documentId"], changed["documentVersion"], main["rawVersion"]),   # real version with another version's raw
                    source("other-source"), grant("other-grant"), grant(revision="rights-9")):
        refused(invoke(k.root, request, relation_dir=None, expected=2)[0], "changed_identity_unknown")


def test_grant_seed_matches_frozen_revisions_not_the_current_registry(world):
    k, main = world.kit, world.refs["main"]
    k.registry["sources"][0]["grant"]["revision"] = "rights-2"
    k.save_registry()
    assert k.job("run", k.submit("s2-job-r2", main, [world.snapshot], topic=False), replay=world.s2_replay)["state"] == "ready"
    run = lambda revision: invoke(k.root, grant(revision=revision), relation_dir=None)  # noqa: E731

    first, second, every = run("rights-1"), run("rights-2"), run(None)
    assert [j["jobId"] for j in first[0]["extraction"]["jobs"]] == ["s2-job"] and [j["jobId"] for j in second[0]["extraction"]["jobs"]] == ["s2-job-r2"]
    assert [j["jobId"] for j in every[0]["extraction"]["jobs"]] == ["s2-job", "s2-job-r2"]
    assert {m["grant"]["revision"] for j in first[0]["extraction"]["jobs"] for m in j["matchedDocuments"]} == {"rights-1"}
    # Bound evidence is enough: ingestion only froze the registry that was current when its round was registered.
    assert first[0]["identity"] == every[0]["identity"] == {"bound": True, "recordedInIngestion": True} and second[0]["identity"] == {"bound": True, "recordedInIngestion": False}
    assert k.job("inspect", k.job_selector("s2-job"))["delivery"]["status"] == "withheld"

    k.registry["sources"][0]["grant"]["enabled"] = False
    k.save_registry()
    assert k.job("inspect", k.job_selector("s2-job-r2"))["delivery"] == {"status": "withheld", "code": "source_unauthorized"}
    assert [run("rights-1")[1], run("rights-2")[1], run(None)[1]] == [first[1], second[1], every[1]]
    k.registry["sources"] = []
    k.save_registry()
    assert k.job("inspect", k.job_selector("s2-job-r2"))["delivery"]["status"] == "withheld"
    assert [run("rights-1")[1], run("rights-2")[1], run(None)[1]] == [first[1], second[1], every[1]]


def test_report_never_touches_authority_or_delivery_paths(shared, monkeypatch):
    root, main = shared.kit.root, shared.refs["main"]
    expected = invoke(root, document(main))[1]

    def forbidden(*args, **kwargs):
        raise AssertionError("authority or delivery path used")

    for owner, names in ((Authority, ("__init__", "check", "fixture")), (Ingestor, ("run", "resume", "inspect", "export")), (Sources, ("export", "resolve")),
                         (Extractor, ("run", "resume", "inspect", "export", "result", "_context", "_verify")),
                         (relation.Engine, ("run", "resume", "inspect", "result", "_context", "_upstream", "_verify"))):
        for name in names:
            monkeypatch.setattr(owner, name, forbidden)
    assert invoke(root, document(main))[1] == expected


# ---------------------------------------------------------------- identity-only, deterministic, read-only ----------------

def test_report_is_identity_only_and_byte_deterministic(shared):
    root, main, b = shared.kit.root, shared.refs["main"], shared.refs["b"]
    for request in (document(main), document(b), source(), grant()):
        report, text = invoke(root, request)
        assert text == invoke(root, request)[1]
        assert keys_of(report) <= KEYS, keys_of(report) - KEYS
        assert not any(private in text for private in ds.PRIVATE) and str(root) not in text and not re.search(r"[가-힣]", text)
        assert report["usage"] == {"providerCalls": 0, "modelCalls": 0} and report["effect"].startswith("report only")
        assert {"s1-worker", "application-state", "published-briefings", "graphdb", "unscanned-extraction-ledgers"} <= set(report["notCovered"])


def test_report_leaves_every_ledger_byte_mode_and_mtime_identical_even_when_they_are_read_only(ledgers, shared):
    for name in ds.LEDGERS:
        os.chmod(ledgers / name, 0o750)
        os.chmod(ledgers / name / f"{name}.lock", 0o640)
        os.chmod(ledgers / name / f"{name}.sqlite3", 0o440)
    before = snapshot(ledgers)
    for request in (document(shared.refs["main"]), document(shared.refs["b"]), source(), grant()):
        invoke(ledgers, request)
        refused(invoke(ledgers, document({**shared.refs["b"], "documentId": "doc-unknown"}), expected=2)[0], "changed_identity_unknown")
    assert snapshot(ledgers) == before
    assert all(sorted(p.name for p in (ledgers / name).iterdir()) == [f"{name}.lock", f"{name}.sqlite3"] for name in ds.LEDGERS)


def test_cli_process_runs_under_a_network_and_write_audit_hook_and_matches_the_in_process_report(shared, ledgers):
    before = snapshot(ledgers)
    request = document(shared.refs["main"])
    assert dep(ledgers, request, raw=True) == invoke(ledgers, request)[1]
    refused(dep(ledgers, document({**shared.refs["main"], "documentId": "doc-unknown"}), expected=2), "changed_identity_unknown")
    assert snapshot(ledgers) == before


def test_the_audit_hook_used_for_process_checks_really_aborts_network_use_and_writes(tmp_path):
    probes = [("import socket\nsocket.getaddrinfo('example.invalid', 80)", "network attempted"), (f"open({str(tmp_path / 'x')!r}, 'w')", "write attempted"),
              (f"os.chmod({str(tmp_path)!r}, 0o700)", "write attempted"), (f"os.mkdir({str(tmp_path / 'd')!r})", "write attempted"),
              (f"os.open({str(tmp_path / 'y')!r}, os.O_CREAT | os.O_RDWR)", "write attempted")]
    for code, message in probes:
        child = subprocess.run([sys.executable, "-c", ds.guard_source(tmp_path) + code], capture_output=True, text=True)
        assert child.returncode != 0 and message in child.stderr, (code, child.stderr)
    assert list(tmp_path.iterdir()) == []
    ok = subprocess.run([sys.executable, "-c", ds.guard_source(tmp_path) + "print(len(os.listdir(STATE)), open(os.devnull).read() == '')"], capture_output=True, text=True)
    assert ok.returncode == 0 and ok.stdout.split() == ["0", "True"], ok.stderr   # reads and listings are not mistaken for writes


def test_no_database_pipeline_graph_or_network_modules_are_loaded_by_the_dependents_command(shared):
    code = ("import sys\nfrom zoop_ai_pipeline import dependency_cli\nprint([m for m in sys.modules if m.startswith(('investmate.storage', 'investmate.pipeline', 'investmate.graph', "
            "'psycopg', 'neo4j', 'zoop_bff', 'zoop_ai.', 'socket', 'httpx', 'requests'))] + (['zoop_ai'] if 'zoop_ai' in sys.modules else []))")
    child = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, cwd=shared.kit.root, env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PATH": "/usr/bin:/bin"})
    assert child.returncode == 0 and "investmate.pipeline" not in child.stdout and "zoop_bff" not in child.stdout and "neo4j" not in child.stdout, child.stderr + child.stdout


# ---------------------------------------------------------------- fail closed ------------------------------------------

@pytest.mark.parametrize("ledger", ds.LEDGERS)
def test_missing_garbage_hot_or_busy_ledgers_fail_closed_instead_of_empty(shared, ledgers, tmp_path, ledger):
    request = document(shared.refs["main"])
    refused(invoke(ledgers, request, expected=2, **{{"relation": "relation_dir"}.get(ledger, ledger): "absent"})[0], f"{ledger}_state_missing")
    assert not (ledgers / "absent").exists()

    work = fresh(ledgers, tmp_path, "garbage")
    (work / ledger / f"{ledger}.sqlite3").write_bytes(b"not a database " * 40)
    before = snapshot(work)
    refused(invoke(work, request, expected=2)[0], f"{ledger}_state_invalid")
    assert snapshot(work) == before

    work = fresh(ledgers, tmp_path, "hot")
    (work / ledger / f"{ledger}.sqlite3-wal").write_bytes(b"hot")
    before = snapshot(work)
    refused(invoke(work, request, expected=2)[0], f"{ledger}_recovery_required")
    assert snapshot(work) == before

    work = fresh(ledgers, tmp_path, "busy")
    writer = {"ingestion": lambda: IngestionStore(work / "ingestion"), "extraction": lambda: ExtractionStore(work / "extraction", work / "ingestion"),
              "relation": lambda: RelationStore(work / "relation", work / "extraction", work / "ingestion")}[ledger]()
    try:
        refused(invoke(work, request, expected=2)[0], f"{ledger}_busy")
    finally:
        writer.close()
    assert invoke(work, request)[0]["identity"]["bound"] is True


@pytest.mark.parametrize("ledger", ["extraction", "relation"])
def test_unknown_or_absent_ledger_version_is_refused_naming_the_ledger(shared, ledgers, ledger):
    path = ledgers / ledger / f"{ledger}.sqlite3"
    for statement in ("UPDATE meta SET value='future-ledger-9'", "DELETE FROM meta"):
        db = sqlite3.connect(path)
        for trigger in ("immutable_meta_update", "immutable_meta_delete"):
            db.execute(f"DROP TRIGGER IF EXISTS {trigger}")
        db.execute(statement)
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.close()
        refused(invoke(ledgers, document(shared.refs["main"]), expected=2)[0], "ledger_version_unknown", {"ledger": ledger})


def test_overlapping_mixed_or_linked_ledger_roots_are_refused_naming_the_ledger(shared, ledgers):
    request = document(shared.refs["main"])
    refused(invoke(ledgers, request, relation_dir="extraction", expected=2)[0], "state_namespace_conflict", {"ledger": "relation"})
    refused(invoke(ledgers, request, extraction="ingestion", expected=2)[0], "state_namespace_conflict", {"ledger": "extraction"})
    (ledgers / "link").symlink_to(ledgers / "extraction")
    refused(invoke(ledgers, request, extraction="link", expected=2)[0], "state_namespace_invalid", {"ledger": "extraction"})
    (ledgers / "extraction" / "notes.txt").write_text("not a ledger file")
    refused(invoke(ledgers, request, expected=2)[0], "state_namespace_conflict", {"ledger": "extraction"})


def test_a_malformed_stored_row_fails_the_whole_report_with_no_partial_output(shared, ledgers, tmp_path):
    def edit(root: Path, name: str, *statements: tuple):
        db = sqlite3.connect(root / name / f"{name}.sqlite3")
        for sql, args in statements:
            db.execute(sql, args)
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.close()

    main, b = shared.refs["main"], shared.refs["b"]
    # INSERT (the immutability triggers only block UPDATE/DELETE): a job whose frozen request/binding cannot be parsed, unrelated to the seed.
    work = fresh(ledgers, tmp_path, "extraction-row")
    edit(work, "extraction", ("INSERT INTO jobs(job_id,input_digest,request,binding,replay_hash,state,phase,resume_mode,created_at,updated_at) "
                              "VALUES('zz-bad','d','{}','{}','h','ready','complete','none','t','t')", ()))
    for request in (document(main), source(), grant()):
        refused(invoke(work, request, expected=2)[0], "dependency_record_invalid", {"ledger": "extraction", "jobId": "zz-bad"})

    work = fresh(ledgers, tmp_path, "relation-row")
    edit(work, "relation", ("INSERT INTO relation_candidates VALUES('rel-main','rc-broken','key','{}')", ()))
    for request in (document(main), document(b)):
        refused(invoke(work, request, expected=2)[0], "dependency_record_invalid", {"ledger": "relation", "jobId": "rel-main"})
    assert invoke(work, document(main), relation_dir=None)[0]["identity"]["bound"] is True   # the relation ledger is only read when asked for

    # A registry snapshot that is gone or unreadable cannot prove a grant is absent; document seeds never need it.
    for tag, statements in (("blob-missing", [("UPDATE rounds SET registry_hash=?", ("0" * 64,))]),
                            ("blob-garbage", [("INSERT INTO blobs VALUES(?, x'6e6f74')", ("f" * 64,)), ("UPDATE rounds SET registry_hash=?", ("f" * 64,))])):
        work = fresh(ledgers, tmp_path, tag)
        edit(work, "ingestion", *statements)
        refused(invoke(work, grant(), expected=2)[0], "dependency_record_invalid", {"ledger": "ingestion"})
        assert invoke(work, document(main))[0]["identity"]["bound"] is True


def test_relation_jobs_with_an_unscanned_or_different_upstream_are_listed_unresolved_never_dropped(shared, ledgers):
    main = shared.refs["main"]
    ExtractionStore(ledgers / "extraction-empty", ledgers / "ingestion").close()
    report, _ = invoke(ledgers, document(main), extraction="extraction-empty")
    assert report["identity"] == {"bound": False, "recordedInIngestion": True}
    assert report["extraction"] == {"ledgerVersion": LEDGER_VERSION, "scannedJobs": 0, "jobs": []} and report["relation"]["jobs"] == []
    assert [(u["jobId"], u["state"], u["code"], u["upstream"]["jobId"]) for u in report["relation"]["unresolved"]] == [
        ("rel-main", "ready", "upstream_not_in_scanned_ledger", "s2-job"), ("rel-stopped", "stopped", "upstream_not_in_scanned_ledger", "s2-job")]
    assert report["counts"]["relation"] == {"jobs": 0, "unresolvedJobs": 2, "relationCandidates": 0, "impactCandidates": 0}

    # Same job ID, other input (no topic requested): the relation jobs pinned the original digest and must not be silently joined to it.
    store = ExtractionStore(ledgers / "extraction-other", ledgers / "ingestion")
    try:
        other = Extractor(store, Sources(ledgers / "ingestion", Authority(shared.kit.registry_path))).run(
            Submit.model_validate(shared.kit.submit("s2-job", main, [shared.snapshot], topic=False)), Fixtures(shared.s2_replay.read_bytes(), None))
    finally:
        store.close()
    assert other["state"] == "ready" and other["inputDigest"] != shared.s2["inputDigest"]
    report, _ = invoke(ledgers, document(main), extraction="extraction-other")
    assert [j["inputDigest"] for j in report["extraction"]["jobs"]] == [other["inputDigest"]] and report["relation"]["jobs"] == []
    assert [(u["jobId"], u["code"]) for u in report["relation"]["unresolved"]] == [("rel-main", "upstream_input_mismatch"), ("rel-stopped", "upstream_input_mismatch")]


def test_every_opened_ledger_stays_locked_until_the_report_is_written(shared, ledgers, monkeypatch):
    probed = []
    original = relation.dependents
    writers = {"ingestion": lambda: IngestionStore(ledgers / "ingestion"), "extraction": lambda: ExtractionStore(ledgers / "extraction", ledgers / "ingestion"),
               "relation": lambda: RelationStore(ledgers / "relation", ledgers / "extraction", ledgers / "ingestion")}

    def probe(store, index):
        for name, open_writer in writers.items():
            with pytest.raises(Exception, match=f"{name}_busy"):
                open_writer()
            probed.append(name)
        return original(store, index)

    monkeypatch.setattr(relation, "dependents", probe)
    report, _ = invoke(ledgers, document(shared.refs["main"]))
    assert probed == ["ingestion", "extraction", "relation"] and report["identity"]["bound"] is True
    for open_writer in writers.values():
        open_writer().close()   # every shared lock was released with the report


def test_relation_store_existing_mode_is_read_only_with_a_shared_lock_and_never_creates_state(ledgers):
    root, upstream = ledgers / "relation", (ledgers / "extraction", ledgers / "ingestion")
    os.chmod(root, 0o750)
    os.chmod(root / "relation.lock", 0o640)
    os.chmod(root / "relation.sqlite3", 0o440)
    before = tree(root)
    reader = RelationStore(root, *upstream, existing=True)
    try:
        assert [r["job_id"] for r in reader.all("SELECT job_id FROM jobs ORDER BY job_id")] == ["rel-main", "rel-stopped"]
        with pytest.raises(sqlite3.OperationalError):
            reader.db.execute("DELETE FROM jobs")
        with pytest.raises(sqlite3.OperationalError):
            reader.db.execute("CREATE TABLE intruder(x)")
        RelationStore(root, *upstream, existing=True).close()   # shared readers coexist
    finally:
        reader.close()
    assert tree(root) == before and sorted(before) == [".", "relation.lock", "relation.sqlite3"]
    with pytest.raises(Exception, match="relation_state_missing"):
        RelationStore(ledgers / "not-created", *upstream, existing=True)
    assert not (ledgers / "not-created").exists()
    os.chmod(root, 0o700)
    os.chmod(root / "relation.lock", 0o600)
    os.chmod(root / "relation.sqlite3", 0o600)
    reader = RelationStore(root, *upstream, existing=True)
    try:
        with pytest.raises(Exception, match="relation_busy"):
            RelationStore(root, *upstream)   # a writer cannot start while a reader is active
    finally:
        reader.close()
    writer = RelationStore(root, *upstream)
    try:
        with pytest.raises(Exception, match="relation_busy"):
            RelationStore(root, *upstream, existing=True)
    finally:
        writer.close()


# ---------------------------------------------------------------- wire and bounds --------------------------------------

DOCUMENT = {"kind": "document", "documentId": "doc-x", "documentVersion": None, "rawVersion": None}


@pytest.mark.parametrize("request_", [
    {"schemaVersion": "zoop-dependency-s3", "changed": DOCUMENT},
    {"schemaVersion": SCHEMA, "changed": DOCUMENT, "extra": 1},
    {"schemaVersion": SCHEMA},
    {"schemaVersion": SCHEMA, "changed": None},
    {"schemaVersion": SCHEMA, "changed": {"kind": "document", "documentId": "doc-x"}},   # nullable keys are required, not defaulted
    {"schemaVersion": SCHEMA, "changed": {**DOCUMENT, "extra": 1}},
    {"schemaVersion": SCHEMA, "changed": {**DOCUMENT, "documentVersion": "abc"}},
    {"schemaVersion": SCHEMA, "changed": {**DOCUMENT, "documentVersion": "A" * 64}},
    {"schemaVersion": SCHEMA, "changed": {**DOCUMENT, "rawVersion": "0" * 63}},
    {"schemaVersion": SCHEMA, "changed": {"kind": "company", "companyId": "x"}},
    {"schemaVersion": SCHEMA, "changed": {"kind": "source"}},
    {"schemaVersion": SCHEMA, "changed": {"kind": "source", "sourceId": ""}},
    {"schemaVersion": SCHEMA, "changed": {"kind": "source", "sourceId": "s" * 201}},
    {"schemaVersion": SCHEMA, "changed": {"kind": "grant", "grantId": "g"}},                  # revision is required-nullable
    {"schemaVersion": SCHEMA, "changed": {"kind": "grant", "grantId": "g", "revision": ""}},
    {"schemaVersion": SCHEMA, "changed": {"kind": "grant", "grantId": 7, "revision": None}},
    [], 7, "text", b"{", b"\xff", b""])
def test_wire_is_closed_versioned_and_strict(shared, request_):
    report, _ = invoke(shared.kit.root, request_ if isinstance(request_, bytes) else json_bytes(request_), expected=2)
    refused(report, "input_or_configuration_invalid")


def test_stdin_is_bounded_at_the_command_limit(shared):
    exact = json_bytes({"schemaVersion": SCHEMA, "changed": {**DOCUMENT, "documentId": "doc-unknown"}})
    exact += b" " * (MAX_COMMAND - len(exact))
    refused(invoke(shared.kit.root, exact, expected=2)[0], "changed_identity_unknown")   # accepted and evaluated, not a size error
    refused(invoke(shared.kit.root, exact + b" ", expected=2)[0], "command_input_limit")


def test_report_limit_fails_closed_without_truncation(shared, monkeypatch):
    root = shared.kit.root
    report, _ = invoke(root, source())
    entries = sum(sum(group.values()) for group in report["counts"].values() if group)
    assert entries > 10
    monkeypatch.setattr(dependency_cli, "MAX_REPORT_ENTRIES", entries)
    assert invoke(root, source())[0] == report
    monkeypatch.setattr(dependency_cli, "MAX_REPORT_ENTRIES", entries - 1)
    refused(invoke(root, source(), expected=2)[0], "dependency_report_limit", {"entries": entries, "limit": entries - 1})


# ---------------------------------------------------------------- review regressions: frozen upstream binding, malformed containers ----------

MISMATCH = "upstream_binding_mismatch"


def test_same_job_and_input_digest_under_another_frozen_grant_revision_is_unresolved_not_omitted_or_misattributed(shared, ledgers):
    main = shared.refs["main"]
    other = same_request_other_binding(shared, ledgers, "extraction-r2", revision="rights-2", finish=True)
    assert other["state"] == "ready" and {d["grant"]["revision"] for d in other["binding"]["documents"].values()} == {"rights-2"}
    assert {d["grant"]["revision"] for d in shared.s2["binding"]["documents"].values()} == {"rights-1"}
    # S3 pinned the digest of the r1 projection (binding + candidates); the r2 job's projection differs although job ID and inputDigest are equal.
    assert shared.rel["binding"]["upstream"]["digest"] != upstream_digest(other)
    pinned = {"jobId": "s2-job", "inputDigest": shared.s2["inputDigest"]}

    # Positive control: against the extraction ledger the S3 jobs were really built from, the same grant seed lists them.
    control, _ = invoke(ledgers, grant(revision="rights-1"))
    assert [j["jobId"] for j in control["relation"]["jobs"]] == ["rel-main", "rel-stopped"] and control["relation"]["unresolved"] == []

    for request, bound, revisions in ((grant(revision="rights-1"), False, set()), (grant(revision="rights-2"), True, {"rights-2"}),
                                      (grant(), True, {"rights-2"}), (document(main), True, {"rights-2"}), (source(), True, {"rights-2"})):
        report, _ = invoke(ledgers, request, extraction="extraction-r2")
        assert report["identity"]["bound"] is bound and report["extraction"]["scannedJobs"] == 1
        assert {m["grant"]["revision"] for j in report["extraction"]["jobs"] for m in j["matchedDocuments"]} == revisions
        # Never omitted (r1 seed: no affected S2 entry) and never attributed to the r2 job (r2 seeds): both S3 jobs are explicitly unresolved.
        assert report["relation"]["jobs"] == [], request
        assert [(u["jobId"], u["code"], u["upstream"]) for u in report["relation"]["unresolved"]] == [("rel-main", MISMATCH, pinned), ("rel-stopped", MISMATCH, pinned)], request
        assert report["counts"]["relation"] == {"jobs": 0, "unresolvedJobs": 2, "relationCandidates": 0, "impactCandidates": 0}


def test_a_scanned_upstream_that_is_not_the_ready_job_s3_was_built_from_is_unresolved_not_attributed(shared, ledgers):
    # Same Submit and replay, but stopped at the topic stage: the equal inputDigest does not make it the ready upstream an S3 job can only originate from.
    stopped = same_request_other_binding(shared, ledgers, "extraction-stopped", revision=None, finish=False)
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "topic_replay_required"
    pinned = {"jobId": "s2-job", "inputDigest": shared.s2["inputDigest"]}
    for request in (document(shared.refs["main"]), document(shared.refs["b"]), source(), grant()):
        report, _ = invoke(ledgers, request, extraction="extraction-stopped")
        assert report["identity"]["bound"] is True and report["relation"]["jobs"] == [], request
        assert [(u["jobId"], u["code"], u["upstream"]) for u in report["relation"]["unresolved"]] == [("rel-main", MISMATCH, pinned), ("rel-stopped", MISMATCH, pinned)], request


def mutate(root: Path, name: str, *statements: tuple) -> None:
    """Crafted rows through a plain connection: INSERT is not blocked by the owners' immutability triggers (they block UPDATE/DELETE)."""
    db = sqlite3.connect(root / name / f"{name}.sqlite3")
    for sql, args in statements:
        db.execute(sql, args)
    db.commit()
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.close()


def relation_row(key: str, **override) -> tuple:
    """A company-to-company relation of rel-main with no endpoint dependency, so only a citation/path container could make it a dependency."""
    payload = {"relationKey": "key-" + key, "subject": {"kind": "company", "ref": "SYNTH-1"}, "object": {"kind": "company", "ref": "SYNTH-3"},
               "citations": [], "validity": {"citations": []}, "path": [], **override}
    return "INSERT INTO relation_candidates VALUES('rel-main',?,?,?)", ("rc-" + key, payload["relationKey"], json.dumps(payload))


def impact_row(key: str, parent: str, **proposal) -> tuple:
    payload = {"impactCandidateId": "ic-" + key, "relationCandidateId": parent, "proposal": {"supporting": [], "opposing": [], **proposal}}
    return "INSERT INTO impact_candidates VALUES('rel-main',?,?,?)", ("ic-" + key, parent, json.dumps(payload))


def comparison_row(candidate: str, key: str, **override) -> tuple:
    payload = {"eventCandidateId": candidate, "targetEventId": "event-" + key, "targetRevision": "rev-1", "citations": [], **override}
    return "INSERT INTO comparisons VALUES('s2-job',?,?,?)", (candidate, "event-" + key, json.dumps(payload))


def topic_row(key: str, **override) -> tuple:
    payload = {"topicCandidateId": "tp-" + key, "members": [], "citations": [], **override}
    return "INSERT INTO topic_candidates VALUES('s2-job',?,?)", ("tp-" + key, json.dumps(payload))


# name -> (ledger, jobId, row builder(shared, ids)). Each row is iterable-but-invalid in a dependency-bearing container; against seed `main` the
# surrounding record would otherwise be silently read as having no dependency (or as depending only through another reason).
MALFORMED = {
    "relation citations {}": ("relation", "rel-main", lambda w, ids: relation_row("a", citations={})),
    "relation citations ''": ("relation", "rel-main", lambda w, ids: relation_row("b", citations="")),
    "relation validity citations {}": ("relation", "rel-main", lambda w, ids: relation_row("c", validity={"citations": {}})),
    "relation path {}": ("relation", "rel-main", lambda w, ids: relation_row("d", path={})),
    "relation path ''": ("relation", "rel-main", lambda w, ids: relation_row("e", path="")),
    "relation step citations {}": ("relation", "rel-main", lambda w, ids: relation_row("f", path=[{"citations": {}}])),
    "impact supporting {}": ("relation", "rel-main", lambda w, ids: impact_row("g", ids["battery"], supporting={})),
    "impact opposing ''": ("relation", "rel-main", lambda w, ids: impact_row("h", ids["battery"], opposing="")),
    "comparison citations {}": ("extraction", "s2-job", lambda w, ids: comparison_row(w.evc, "i", citations={})),
    "topic members {}": ("extraction", "s2-job", lambda w, ids: topic_row("j", members={})),
    "topic members ''": ("extraction", "s2-job", lambda w, ids: topic_row("k", members="")),
    "topic citations {}": ("extraction", "s2-job", lambda w, ids: topic_row("l", citations={})),
}


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_malformed_dependency_containers_fail_the_whole_report_instead_of_reading_as_empty(shared, ledgers, case):
    ledger, job, build_row = MALFORMED[case]
    mutate(ledgers, ledger, build_row(shared, labels(shared)))
    refused(invoke(ledgers, document(shared.refs["main"]), expected=2)[0], "dependency_record_invalid", {"ledger": ledger, "jobId": job})


def test_valid_empty_dependency_containers_remain_accepted_and_only_count_toward_the_job_scope(shared, ledgers):
    main = shared.refs["main"]
    baseline, _ = invoke(ledgers, document(main))
    mutate(ledgers, "relation", relation_row("empty"))
    report, _ = invoke(ledgers, document(main))
    before, after = by(baseline["relation"]["jobs"], "jobId", "rel-main"), by(report["relation"]["jobs"], "jobId", "rel-main")
    assert after["relationCandidates"] == before["relationCandidates"] and after["impactCandidates"] == before["impactCandidates"]
    assert after["jobScope"] == {"relationCandidates": before["jobScope"]["relationCandidates"] + 1, "impactCandidates": before["jobScope"]["impactCandidates"]}
