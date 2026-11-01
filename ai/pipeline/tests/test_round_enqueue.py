"""Round -> S2 registration (`zoop-ai-extract enqueue-round`): planner, identity, authority, ledger preflight and partial-failure behavior.

Real ingestion rounds come from the actual ingestion CLI; the extractor, ledger, stores and authority are the real code, run in process (the
actual `enqueue-round` process is exercised at the end). The planner is pure and is also checked on synthetic refs. No network, model or provider
call is made, and registration never executes a job.
"""
from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from scripts.extraction_smoke import CATALOGUE, LIVE_ENV_NAMES, PROMPT, Q3, SECRET_NAMES, Kit, Replay, page, simulator_env
from tests.legacy_ledger import copy_as_legacy
from zoop_ai_pipeline.extraction import Extractor, Fixtures, Sources, Store
from zoop_ai_pipeline.extraction_contracts import ENQUEUE_FORMAT, SCHEMA, EnqueueRound, ExtractionFailure, ObservationRef, Submit, digest, enqueue_job_id
from zoop_ai_pipeline.extraction_enqueue import enqueue_round, plan
from zoop_ai_pipeline.ingestion import Ingestor
from zoop_ai_pipeline.ingestion import Store as IngestionStore
from zoop_ai_pipeline.ingestion_contracts import Authority, IngestionFailure

SOURCE = "synthetic-source"
OK_BODY = page("합성기업은 일반 사업 소식을 알렸다.", "세부 내용은 후속 공시에 담겼다.")
BASE_BODY = page(Q3, "계약 상대는 합성상대다.")
BAD_BODY = b"not a PDF"


def V(char: str) -> str:
    return char * 64


# ---------------------------------------------------------------- helpers ------------------------------------------

def url(name: str, supplier: str) -> str:
    return f"https://example.invalid/{name}/{supplier}"


def ingest_round(kit: Kit, name: str, batches: list[list[dict]], bodies: dict, *, slot: str | None = None) -> tuple[str, dict]:
    """A real (multi-page) ingestion round through the actual ingestion CLI. Every completed page advances the scope checkpoint by one."""
    manifest = kit.manifest(name, batches, bodies=bodies, coverage=slot)
    rid = f"round-{name}"
    result = kit.cli("run", kit.request(manifest, rid, kit.rounds, {"from": slot, "through": slot} if slot else None), state="ingestion", manifest=manifest)
    kit.rounds += len(batches)
    assert result["state"] == "complete", result
    return rid, result


def simple_round(kit: Kit, name: str, suppliers: list[str], body: bytes = OK_BODY, *, slot: str | None = None) -> tuple[str, dict]:
    return ingest_round(kit, name, [[kit.item(f"c{i}", s, url(name, s)) for i, s in enumerate(suppliers)]], {"html": body}, slot=slot)


def make_round(kit: Kit, name: str) -> str:
    """zero: no candidate; held: one unparseable PDF; prepared: one document."""
    if name == "zero":
        return ingest_round(kit, "zero", [[]], {"html": OK_BODY})[0]
    if name == "held":
        return ingest_round(kit, "held", [[kit.item("c0", "supplier-h", url("held", "h"), ref="bad", media="application/pdf")]], {"html": OK_BODY, "bad": BAD_BODY})[0]
    return simple_round(kit, "prepared", ["supplier-p"])[0]


def candidates(kit: Kit, rid: str) -> list[tuple]:
    """The ingestion ledger's own candidate rows: an oracle that does not use the planner."""
    path = kit.root / "ingestion" / "ingestion.sqlite3"
    db = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    try:
        return db.execute("SELECT page,ordinal,document,raw_version,version,hold,ambiguity FROM candidates WHERE round=? AND source=? ORDER BY page,ordinal", (rid, SOURCE)).fetchall()
    finally:
        db.close()


def observation(rid: str, row: tuple) -> dict:
    return {"roundId": rid, "sourceId": SOURCE, "page": row[0], "ordinal": row[1], "documentId": row[2], "rawVersion": row[3], "documentVersion": row[4]}


def job_ids(kit: Kit, rid: str, label: str = "batch-1") -> list[str]:
    return [enqueue_job_id(label, ObservationRef.model_validate(observation(rid, row))) for row in candidates(kit, rid) if row[4] is not None]


def tree(directory: Path) -> dict:
    """Bytes, mode and mtime of every file plus the directory itself."""
    found = {p.name: (stat.S_IMODE(p.stat().st_mode), p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(directory.iterdir())}
    return found | {".": (stat.S_IMODE(directory.stat().st_mode), directory.stat().st_mtime_ns)}


def ledger(kit: Kit) -> tuple[list, int]:
    """Every job row (digest, state, phase, binding) and the number of calls, read without any side effect."""
    path = kit.root / "extraction" / "extraction.sqlite3"
    if not path.exists():
        return [], 0
    db = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    try:
        return (db.execute("SELECT job_id,input_digest,state,phase,binding FROM jobs ORDER BY job_id").fetchall(), db.execute("SELECT COUNT(*) FROM calls").fetchone()[0])
    finally:
        db.close()


def no_ledger(kit: Kit) -> bool:
    return not (kit.root / "extraction").exists()


def descriptor(rid: str, enqueue_id: str = "batch-1", *, events=(), prompt: str = PROMPT, catalogue: dict | None = None, topic: bool = False,
               source_kind: str = "synthetic", mode: str = "replay") -> dict:
    return {"schemaVersion": SCHEMA, "enqueueId": enqueue_id, "roundId": rid, "sourceId": SOURCE,
            "provenance": {"sourceKind": source_kind, "executionMode": mode, "recordingKind": "authored-test" if mode == "replay" else "provider"},
            "promptVersion": prompt, "catalogue": catalogue or CATALOGUE, "snapshot": {"revision": "snapshot-1", "events": list(events)},
            "topic": {"producerVersion": "zoop-topic-replay-producer-1"} if topic else None}


def enqueue(kit: Kit, body: dict, replay: Path | None = None, live=None):
    request = EnqueueRound.model_validate(body)
    fixtures = Fixtures(replay.read_bytes() if replay else None, None)
    return enqueue_round(request, fixtures, kit.root / "extraction", kit.root / "ingestion", kit.registry_path, live)


def registrations(report: dict) -> list[str]:
    return [job["registration"] for job in report["jobs"]]


def hook_freeze(monkeypatch, at: int, effect) -> list[str]:
    """Run `effect` just before the `at`-th (1-based) freeze of this process and then let that freeze proceed. Returns the job ids frozen so far."""
    original, seen = Extractor.freeze, []

    def freeze(self, request, fixtures):
        seen.append(request.job_id)
        if len(seen) == at:
            effect()
        return original(self, request, fixtures)

    monkeypatch.setattr(Extractor, "freeze", freeze)
    return seen


@pytest.fixture
def world(tmp_path):
    kit = Kit(tmp_path / "owned")
    rid, _ = simple_round(kit, "base", ["supplier-snap"], BASE_BODY)
    base = observation(rid, candidates(kit, rid)[0])
    article = kit.article(base)
    event = kit.event("event-snap", [(base, kit.mention(article, "m-snap", [kit.evidence(article, Q3)]))])
    return SimpleNamespace(kit=kit, base=base, event=event, replay=kit.replay("r").write())


# ---------------------------------------------------------------- wire and identity ---------------------------------

def test_enqueue_round_wire_requires_every_key_and_a_bounded_label():
    body = descriptor("round-x", "label-1")
    EnqueueRound.model_validate(body)
    EnqueueRound.model_validate({**body, "topic": {"producerVersion": "zoop-topic-replay-producer-1"}})
    EnqueueRound.model_validate({**body, "enqueueId": "a" * 120})
    assert len(body) == 9
    for key in body:
        with pytest.raises(ValidationError):
            EnqueueRound.model_validate({k: v for k, v in body.items() if k != key})
    for label in ("", "a" * 121, "a/b", "a b", "é", "a:b"):
        with pytest.raises(ValidationError):
            EnqueueRound.model_validate({**body, "enqueueId": label})
    for broken in ({"extra": 1}, {"schemaVersion": "zoop-extraction-s2-1"}):
        with pytest.raises(ValidationError):
            EnqueueRound.model_validate({**body, **broken})


def test_job_id_is_a_digest_of_the_label_and_the_exact_observation_only():
    wire = {"roundId": "round-x", "sourceId": SOURCE, "page": 2, "ordinal": 5, "documentId": "doc-1", "rawVersion": V("a"), "documentVersion": V("b")}
    ref = ObservationRef.model_validate(wire)
    assert ref.wire() == wire
    job_id = enqueue_job_id("label-1", ref)
    assert ENQUEUE_FORMAT == "zoop-round-enqueue-1" and len(job_id) == 68
    assert job_id == "s2r-" + digest({"format": ENQUEUE_FORMAT, "enqueueId": "label-1", "observation": wire})
    assert enqueue_job_id("label-2", ref) != job_id
    for key, value in {"roundId": "round-y", "sourceId": "other", "page": 3, "ordinal": 6, "documentId": "doc-2", "rawVersion": V("c"), "documentVersion": V("d")}.items():
        assert enqueue_job_id("label-1", ObservationRef.model_validate({**wire, key: value})) != job_id
    # No descriptor field enters the id: it only changes the frozen input (and therefore conflicts), never the identity.
    plain = EnqueueRound.model_validate(descriptor("round-x", "label-1"))
    other = EnqueueRound.model_validate(descriptor("round-x", "label-1", prompt="p2", topic=True, source_kind="actual", catalogue={**CATALOGUE, "revision": "c2"}, events=[snapshot_event()]))
    assert plain.submit(ref).job_id == other.submit(ref).job_id == job_id
    assert plain.submit(ref).wire() != other.submit(ref).wire()
    assert Submit.model_validate(plain.submit(ref).wire()).wire() == plain.submit(ref).wire()


def snapshot_event(version: str = V("d")) -> dict:
    member = {"roundId": "round-base", "sourceId": SOURCE, "page": 0, "ordinal": 0, "documentId": "doc-snap", "rawVersion": V("c"), "documentVersion": version}
    return {"eventId": "event-1", "revision": "rev-1", "members": [{"observation": member, "mention": {}}]}


# ---------------------------------------------------------------- planner (pure) -----------------------------------

def ref_of(page_no: int, ordinal: int, *, version=None, hold=None, ambiguity=None, error=None, failure=None, document: str = "doc-1") -> dict:
    return {"page": page_no, "ordinal": ordinal, "documentId": document, "rawVersion": V("b"), "documentVersion": version, "hold": hold, "error": error,
            "ambiguity": ambiguity, "failure": failure}


def head_of(refs: list[dict], *, state: str = "complete", unfinished: int = 0, discovered: int | None = None) -> dict:
    return {"state": state, "inputDigest": V("1"), "provenance": "authored_control", "completion": "nonzero-discovery",
            "counts": {"unfinished": unfinished, "discoveredCandidates": len(refs) if discovered is None else discovered}}


def bare(*events: dict) -> EnqueueRound:
    return EnqueueRound.model_validate(descriptor("round-x", "plan-1", events=list(events)))


def test_plan_derives_every_prepared_id_before_applying_the_first_matching_skip():
    snap = V("d")
    refs = [ref_of(0, 0, hold="pdf_invalid", ambiguity="source_identity_ambiguous"),            # held wins over ambiguous
            ref_of(0, 1, version=V("e"), ambiguity="source_identity_ambiguous"),                # prepared, ambiguous
            ref_of(0, 2, version=snap, ambiguity="source_identity_ambiguous", document="doc-2"),  # ambiguous wins over in_snapshot
            ref_of(0, 3, version=snap, document="doc-3"),                                       # in_snapshot
            ref_of(0, 4, version=V("f"), document="doc-4"),                                     # kept
            ref_of(0, 5, version=V("f"), document="doc-4"),                                     # same document id and version as ordinal 4
            ref_of(1, 0, version=V("f"), document="doc-5")]                                     # same version, other document: kept
    entries = plan(bare(snapshot_event(snap)), head_of(refs), refs)
    kept = enqueue_job_id("plan-1", entries[4].ref)
    assert [(e.page, e.ordinal, e.skip) for e in entries] == [
        (0, 0, ("held", "pdf_invalid")), (0, 1, ("ambiguous", "source_identity_ambiguous")), (0, 2, ("ambiguous", "source_identity_ambiguous")),
        (0, 3, ("in_snapshot", None)), (0, 4, None), (0, 5, ("duplicate_in_round", kept)), (1, 0, None)]
    # Every prepared observation has its id, filtered or not; only a held one (no document version) has none.
    assert [e.submit is not None for e in entries] == [False, True, True, True, True, True, True]
    assert all(e.submit.job_id == enqueue_job_id("plan-1", e.ref) for e in entries if e.ref is not None)
    assert [e.version for e in entries] == [None, V("e"), snap, snap, V("f"), V("f"), V("f")]


@pytest.mark.parametrize("state", ["running", "incomplete"])
def test_plan_refuses_an_unfinished_round(state):
    refs = [ref_of(0, 0, version=V("e"))]
    with pytest.raises(ExtractionFailure) as refused:
        plan(bare(), head_of(refs, state=state), refs)
    assert refused.value.code == "round_not_complete"


OK_REF = ref_of(0, 0, version=V("e"))


@pytest.mark.parametrize("refs,options", [
    ([OK_REF], {"unfinished": 1}),
    ([OK_REF], {"discovered": 2}),
    ([ref_of(0, 1, version=V("e")), ref_of(0, 0, version=V("f"))], {}),                    # decreasing
    ([ref_of(0, 0, version=V("e")), ref_of(0, 0, version=V("f"))], {}),                    # repeated
    ([ref_of(0, 1, version=V("e")), ref_of(0, 0, version=V("f")), ref_of(1, 0, version=V("a"))], {}),
    ([{**OK_REF, "error": "discovery_item_invalid"}], {}),
    ([{**OK_REF, "failure": {"code": "persistence_or_input_failed"}}], {}),
    ([ref_of(0, 0)], {}),                                                                     # neither held nor prepared
    ([{**OK_REF, "documentId": None}], {}),
    ([{**OK_REF, "rawVersion": None}], {}),
    ([ref_of(0, 0, version="not-a-version")], {}),
])
def test_plan_refuses_refs_a_complete_round_cannot_have(refs, options):
    with pytest.raises(ExtractionFailure) as refused:
        plan(bare(), head_of(refs, **options), refs)
    assert refused.value.code == "round_refs_inconsistent"


# ---------------------------------------------------------------- the whole round ----------------------------------

def test_enqueue_registers_one_queued_job_per_observation_and_a_handwritten_submit_is_the_same_job(world):
    kit = world.kit
    rid, ingested = simple_round(kit, "docs", ["supplier-a", "supplier-b"])
    body = descriptor(rid, events=[world.event])
    before = tree(kit.root / "ingestion")
    report, code = enqueue(kit, body, world.replay)
    rows = candidates(kit, rid)
    ids = job_ids(kit, rid)
    assert code == 0 and tree(kit.root / "ingestion") == before
    assert report == {
        "schemaVersion": SCHEMA, "enqueueId": "batch-1",
        "round": {"roundId": rid, "sourceId": SOURCE, "inputDigest": ingested["inputDigest"], "provenance": "authored_control", "completion": "nonzero-discovery"},
        "outcome": "complete",
        "jobs": [{"jobId": ids[i], "page": 0, "ordinal": i, "documentId": rows[i][2], "rawVersion": rows[i][3], "documentVersion": rows[i][4], "registration": "registered"} for i in range(2)],
        "skipped": [], "counts": {"refs": 2, "jobs": 2, "registered": 2, "existing": 0, "failed": 0, "notAttempted": 0, "skipped": 0}, "error": None}
    stored, calls = ledger(kit)
    assert [(row[0], row[2], row[3]) for row in stored] == sorted((job_id, "queued", "extract") for job_id in ids) and calls == 0
    assert all(json.loads(row[4])["replay"]["fixtureHash"] == hashlib.sha256(world.replay.read_bytes()).hexdigest() for row in stored)
    # The same job as an ordinary submit: same content freezes nothing new, and a changed one would conflict.
    submit = EnqueueRound.model_validate(body).submit(ObservationRef.model_validate(observation(rid, rows[0])))
    assert kit.job("submit", submit.wire(), replay=world.replay)["state"] == "queued" and ledger(kit) == (stored, 0)


def test_a_large_multi_page_round_plans_every_page_and_registers_exactly_the_planned_jobs(world):
    kit = world.kit
    kinds = {3: "held", 150: "held", 7: "ambiguous", 20: "dup", 120: "dup", 205: "snap"}
    items = []
    for i in range(210):
        kind = kinds.get(i, "ok")
        if kind == "held":
            items.append(kit.item(f"c{i}", f"supplier-{i}", url("many", str(i)), ref="bad", media="application/pdf"))
        elif kind == "ambiguous":
            items.append(kit.item(f"c{i}", "supplier-amb", url("base", "supplier-snap")))      # a different supplier on a URL already owned by supplier-snap
        elif kind == "dup":
            items.append(kit.item(f"c{i}", "supplier-dup", url("many", str(i))))
        elif kind == "snap":
            items.append(kit.item(f"c{i}", "supplier-snap", url("many", str(i)), ref="snap"))  # byte-identical to the snapshot member's document
        else:
            items.append(kit.item(f"c{i}", f"supplier-{i}", url("many", str(i))))
    rid, ingested = ingest_round(kit, "many", [items[:100], items[100:200], items[200:]], {"html": OK_BODY, "bad": BAD_BODY, "snap": BASE_BODY})
    assert ingested["counts"]["discoveredCandidates"] == 210 and ingested["counts"]["held"] == 2
    rows = candidates(kit, rid)
    assert rows[205][4] == world.base["documentVersion"]     # the snapshot case really is the snapshot member's version
    assert rows[7][6] == "source_identity_ambiguous" and rows[7][4] is not None
    by_key = {(row[0], row[1]): job_id for row, job_id in zip(rows, [enqueue_job_id("batch-big", ObservationRef.model_validate(observation(rid, r))) if r[4] else None for r in rows])}
    body = descriptor(rid, "batch-big", events=[world.event])
    before = tree(kit.root / "ingestion")
    report, code = enqueue(kit, body, world.replay)
    assert code == 0 and report["outcome"] == "complete" and tree(kit.root / "ingestion") == before
    assert report["counts"] == {"refs": 210, "jobs": 205, "registered": 205, "existing": 0, "failed": 0, "notAttempted": 0, "skipped": 5}
    assert [(s["page"], s["ordinal"], s["code"]) for s in report["skipped"]] == [
        (0, 3, "held"), (0, 7, "ambiguous"), (1, 20, "duplicate_in_round"), (1, 50, "held"), (2, 5, "in_snapshot")]
    details = {(s["page"], s["ordinal"]): s["detail"] for s in report["skipped"]}
    assert isinstance(details[(0, 3)], str) and details[(0, 7)] == "source_identity_ambiguous"
    assert details[(1, 20)] == by_key[(0, 20)] and details[(2, 5)] is None
    assert [s["documentVersion"] for s in report["skipped"]] == [None, rows[7][4], rows[120][4], None, rows[205][4]]
    jobs = report["jobs"]
    assert [(j["page"], j["ordinal"]) for j in jobs] == sorted((j["page"], j["ordinal"]) for j in jobs) and {j["page"] for j in jobs} == {0, 1, 2}
    assert all(j["jobId"] == by_key[(j["page"], j["ordinal"])] and len(j["jobId"]) == 68 for j in jobs)
    stored, calls = ledger(kit)
    assert {row[0] for row in stored} == {j["jobId"] for j in jobs} and {row[2] for row in stored} == {"queued"} and calls == 0
    # Identical rerun: every job exists and no row changes.
    again, code = enqueue(kit, body, world.replay)
    assert code == 0 and again["counts"] == {**report["counts"], "registered": 0, "existing": 205} and ledger(kit) == (stored, 0)


# ---------------------------------------------------------------- identity and conflicts ---------------------------

def test_an_identical_rerun_is_all_existing_and_changes_no_row(world):
    kit = world.kit
    rid, _ = simple_round(kit, "docs", ["supplier-a", "supplier-b"])
    body = descriptor(rid, events=[world.event])
    first, _ = enqueue(kit, body, world.replay)
    before = ledger(kit)
    again, code = enqueue(kit, body, world.replay)
    assert code == 0 and registrations(again) == ["existing", "existing"] and [j["jobId"] for j in again["jobs"]] == [j["jobId"] for j in first["jobs"]]
    assert again["counts"] == {"refs": 2, "jobs": 2, "registered": 0, "existing": 2, "failed": 0, "notAttempted": 0, "skipped": 0} and ledger(kit) == before


def changed(w, name: str):
    kit = w.kit
    if name == "prompt":
        return {"prompt": "other-prompt"}, Replay(kit, "p-prompt", prompt="other-prompt").write()
    if name == "catalogue":
        return {"catalogue": {**CATALOGUE, "revision": "catalogue-2"}}, w.replay
    if name == "topic":
        return {"topic": True}, w.replay
    if name == "provenance":
        return {"source_kind": "actual"}, Replay(kit, "p-actual", synthetic=False).write()
    if name == "replay-bytes":
        other = Replay(kit, "p-bytes")
        other.doc["analysisVersion"] = "authored-analysis-2"
        return {}, other.write()
    return {"events": []}, w.replay


@pytest.mark.parametrize("name", ["prompt", "catalogue", "topic", "provenance", "replay-bytes", "snapshot"])
def test_a_changed_descriptor_or_replay_for_the_same_label_conflicts_and_writes_nothing(world, name):
    kit = world.kit
    rid, _ = simple_round(kit, "docs", ["supplier-a", "supplier-b"])
    enqueue(kit, descriptor(rid, events=[world.event]), world.replay)
    before = ledger(kit)
    options, replay = changed(world, name)
    with pytest.raises(ExtractionFailure) as refused:
        enqueue(kit, descriptor(rid, **{"events": [world.event], **options}), replay)
    assert refused.value.code == "job_input_conflict" and ledger(kit) == before


def test_a_new_label_is_a_new_analysis_and_leaves_the_old_jobs_alone(world):
    kit = world.kit
    rid, _ = simple_round(kit, "docs", ["supplier-a", "supplier-b"])
    first, _ = enqueue(kit, descriptor(rid, "batch-1", events=[world.event]), world.replay)
    old = ledger(kit)[0]
    second, code = enqueue(kit, descriptor(rid, "batch-2", events=[world.event], catalogue={**CATALOGUE, "revision": "catalogue-2"}), world.replay)
    assert code == 0 and registrations(second) == ["registered", "registered"]
    assert not {j["jobId"] for j in first["jobs"]} & {j["jobId"] for j in second["jobs"]}
    rows = ledger(kit)[0]
    assert len(rows) == 4 and [row for row in rows if row[0] in {j["jobId"] for j in first["jobs"]}] == old


def test_the_same_label_on_another_round_is_independent(world):
    kit = world.kit
    first_round, _ = simple_round(kit, "first", ["supplier-a", "supplier-b"])
    second_round, _ = simple_round(kit, "second", ["supplier-a", "supplier-b"])   # the very same documents and versions, another round
    assert [r[4] for r in candidates(kit, first_round)] == [r[4] for r in candidates(kit, second_round)]
    first, _ = enqueue(kit, descriptor(first_round, events=[world.event]), world.replay)
    second, code = enqueue(kit, descriptor(second_round, events=[world.event]), world.replay)
    assert code == 0 and registrations(second) == ["registered", "registered"]
    assert not {j["jobId"] for j in first["jobs"]} & {j["jobId"] for j in second["jobs"]} and len(ledger(kit)[0]) == 4


@pytest.mark.parametrize("suppliers", [["supplier-snap"], ["supplier-snap", "supplier-x"]])
def test_a_snapshot_that_filters_previously_registered_refs_cannot_hide_their_old_binding(world, suppliers):
    """The first run registered every observation under an empty snapshot; the new snapshot makes the snapshot member's document `in_snapshot`
    (all or some of the round). Filtering must not let a different input pass: the existing binding is checked for every prepared id."""
    kit = world.kit
    rid, _ = simple_round(kit, "pair", suppliers, BASE_BODY)
    assert candidates(kit, rid)[0][4] == world.base["documentVersion"]
    first, _ = enqueue(kit, descriptor(rid, events=[]), world.replay)
    assert registrations(first) == ["registered"] * len(suppliers)
    before, files = ledger(kit), tree(kit.root / "extraction")
    with pytest.raises(ExtractionFailure) as refused:
        enqueue(kit, descriptor(rid, events=[world.event]), world.replay)
    assert refused.value.code == "job_input_conflict" and ledger(kit) == before
    if len(suppliers) == 1:   # every prepared ref is filtered: the ledger is only opened read-only, byte for byte unchanged
        assert tree(kit.root / "extraction") == files


def test_an_existing_job_of_a_filtered_observation_with_the_same_input_is_a_plan_conflict(world):
    """A hand-made submit of an id this enqueue would never register (an ambiguous observation) is refused, even with the equal descriptor."""
    kit = world.kit
    rid, _ = ingest_round(kit, "amb", [[kit.item("c0", "supplier-amb", url("base", "supplier-snap")), kit.item("c1", "supplier-ok", url("amb", "ok"))]], {"html": OK_BODY})
    rows = candidates(kit, rid)
    assert rows[0][6] == "source_identity_ambiguous" and rows[0][4] is not None and rows[1][6] is None
    body = descriptor(rid, events=[world.event])
    submit = EnqueueRound.model_validate(body).submit(ObservationRef.model_validate(observation(rid, rows[0])))
    kit.job("submit", submit.wire(), replay=world.replay)
    before = ledger(kit)
    assert [row[0] for row in before[0]] == [submit.job_id]
    with pytest.raises(ExtractionFailure) as refused:
        enqueue(kit, body, world.replay)
    assert refused.value.code == "enqueue_plan_conflict" and ledger(kit) == before


def test_a_legacy_binding_at_a_planned_id_refuses_before_its_fixture_is_compared(world):
    kit = world.kit
    rid, _ = simple_round(kit, "docs", ["supplier-a", "supplier-b"])
    first, _ = enqueue(kit, descriptor(rid, "batch-1", events=[world.event]), world.replay)
    planned = job_ids(kit, rid, "batch-2")[0]
    copy_as_legacy(kit.root, first["jobs"][0]["jobId"], planned, state="queued", children=False)
    before = ledger(kit)
    other = Replay(kit, "p-legacy")
    other.doc["analysisVersion"] = "authored-analysis-2"     # different fixture bytes: still the legacy refusal, not an input conflict
    with pytest.raises(ExtractionFailure) as refused:
        enqueue(kit, descriptor(rid, "batch-2", events=[world.event]), other.write())
    assert refused.value.code == "analysis_contract_changed" and ledger(kit) == before and len(before[0]) == 3


def test_a_first_run_that_froze_nothing_leaves_no_binding_so_another_descriptor_is_allowed(world, monkeypatch):
    kit = world.kit
    rid, _ = simple_round(kit, "docs", ["supplier-a"])

    def broken(self, ref, *, send=None):
        raise ExtractionFailure("source_unauthorized")

    with monkeypatch.context() as patched:
        patched.setattr(Sources, "export", broken)
        with pytest.raises(ExtractionFailure) as refused:
            enqueue(kit, descriptor(rid, events=[world.event]), world.replay)
    assert refused.value.code == "source_unauthorized" and ledger(kit)[0] == []
    report, code = enqueue(kit, descriptor(rid, events=[world.event], catalogue={**CATALOGUE, "revision": "catalogue-2"}), world.replay)
    assert code == 0 and registrations(report) == ["registered"]


# ---------------------------------------------------------------- authority ----------------------------------------

AUTHORITY = [
    ("zero", {"enabled": False}, "source_unauthorized"),
    ("zero", {"allowedOperations": ["quote-display"]}, "source_unauthorized"),
    ("zero", {"allowedOperations": ["read", "store"]}, None),
    ("held", {"allowedOperations": ["read", "quote-display"]}, "source_unauthorized"),
    ("held", {"allowedOperations": ["read", "store"]}, None),
    ("held", {"rights": "unknown"}, "source_unauthorized"),
    ("prepared", {"allowedOperations": ["read", "store"]}, "source_unauthorized"),
    ("prepared", {"allowedOperations": ["read", "quote-display"]}, "source_unauthorized"),
    ("prepared", {"expiresAt": "2020-01-01T00:00:00+00:00"}, "source_unauthorized"),
]


@pytest.mark.parametrize("name,grant,code", AUTHORITY)
def test_the_current_grant_is_checked_before_any_round_data_even_for_zero_or_held_rounds(world, name, grant, code):
    """Authority errors carry no round or skipped metadata. Zero and all-held rounds need read + store only; a prepared one also quote-display."""
    kit = world.kit
    rid = make_round(kit, name)
    kit.registry["sources"][0]["grant"].update(grant)
    kit.save_registry()
    body = descriptor(rid, events=[world.event])
    if code:
        with pytest.raises(IngestionFailure) as refused:
            enqueue(kit, body, world.replay)
        assert refused.value.code == code
    else:
        report, status = enqueue(kit, body, world.replay)
        assert status == 0 and report["outcome"] == "complete" and report["counts"]["registered"] == 0 and report["counts"]["refs"] == (0 if name == "zero" else 1)
        assert [s["code"] for s in report["skipped"]] == ([] if name == "zero" else ["held"])
    assert no_ledger(kit)


def test_a_changed_saved_scope_configuration_is_refused(world):
    kit = world.kit
    rid = make_round(kit, "prepared")
    kit.registry["sources"][0]["scopes"][0]["selection"] = "a different source slice"
    kit.save_registry()
    with pytest.raises(IngestionFailure) as refused:
        enqueue(kit, descriptor(rid, events=[world.event]), world.replay)
    assert refused.value.code == "scope_configuration_conflict" and no_ledger(kit)


def test_an_unknown_round_is_not_found_before_authorization(world):
    kit = world.kit
    kit.registry["sources"][0]["grant"]["enabled"] = False
    kit.save_registry()
    with pytest.raises(IngestionFailure) as refused:
        enqueue(kit, descriptor("round-none"), world.replay)
    assert refused.value.code == "round_not_found" and no_ledger(kit)


@pytest.mark.parametrize("name", ["zero", "prepared"])
def test_a_registry_edited_after_the_round_was_read_reports_only_the_code(world, monkeypatch, name):
    kit = world.kit
    rid = make_round(kit, name)
    original = Ingestor.result

    def edited(self, *args, **kwargs):
        found = original(self, *args, **kwargs)
        kit.registry["revision"] = "operator-2"
        kit.save_registry()
        return found

    monkeypatch.setattr(Ingestor, "result", edited)
    body = descriptor(rid, events=[world.event])
    if name == "prepared":
        with pytest.raises(IngestionFailure) as refused:
            enqueue(kit, body, world.replay)
        assert refused.value.code == "registry_changed"
    else:   # no further authorization is needed before the report, so the final recheck is what catches it
        assert enqueue(kit, body, world.replay) == ({"schemaVersion": SCHEMA, "error": {"code": "registry_changed", "partialRegistration": False}}, 2)
    assert no_ledger(kit)


def test_a_zero_or_held_only_round_is_reported_with_no_extraction_directory(world):
    kit = world.kit
    zero, held = make_round(kit, "zero"), make_round(kit, "held")
    before = tree(kit.root / "ingestion")
    report, code = enqueue(kit, descriptor(zero, events=[world.event]), world.replay)
    assert code == 0 and report["round"]["completion"] == "source-zero" and report["counts"] == {"refs": 0, "jobs": 0, "registered": 0, "existing": 0, "failed": 0, "notAttempted": 0, "skipped": 0}
    report, code = enqueue(kit, descriptor(held, events=[world.event]), world.replay)
    assert code == 0 and report["counts"]["skipped"] == 1 and report["skipped"][0]["code"] == "held" and report["skipped"][0]["documentVersion"] is None
    assert no_ledger(kit) and tree(kit.root / "ingestion") == before


def test_an_unfinished_round_is_refused(world):
    kit = world.kit
    manifest = kit.manifest("failed", [[]], statuses=["failed"])
    assert kit.cli("run", kit.request(manifest, "round-failed", kit.rounds), state="ingestion", manifest=manifest)["state"] == "incomplete"
    with pytest.raises(ExtractionFailure) as refused:
        enqueue(kit, descriptor("round-failed"), world.replay)
    assert refused.value.code == "round_not_complete" and no_ledger(kit)


# ---------------------------------------------------------------- inputs validated even for zero jobs --------------

def test_the_replay_header_is_validated_even_when_the_round_has_no_job(world):
    kit = world.kit
    rid = make_round(kit, "zero")
    body = descriptor(rid)

    def invalid(name: str, content: dict) -> Path:
        path = kit.root / f"{name}.replay.json"
        path.write_bytes(json.dumps(content).encode())
        return path

    header = json.loads(world.replay.read_bytes())
    for replay, code in ((None, "replay_fixture_required"),
                         (invalid("format", {**header, "format": "other"}), "replay_fixture_invalid"),
                         (invalid("records", {**header, "records": "no"}), "replay_fixture_invalid"),
                         (invalid("synthetic", {**header, "synthetic": False}), "replay_provenance_conflict"),
                         (invalid("prompt", {**header, "promptVersion": "other"}), "replay_prompt_version_conflict")):
        with pytest.raises(ExtractionFailure) as refused:
            enqueue(kit, body, replay)
        assert refused.value.code == code
    (kit.root / "notjson.replay.json").write_bytes(b"{not json")
    with pytest.raises(ExtractionFailure) as refused:
        enqueue(kit, body, kit.root / "notjson.replay.json")
    assert refused.value.code == "replay_fixture_invalid" and no_ledger(kit)


def test_a_live_enqueue_without_the_gate_is_refused_even_for_zero_jobs_and_takes_no_fixture(world, monkeypatch):
    kit = world.kit
    for name in LIVE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    body = descriptor(make_round(kit, "zero"), mode="live", prompt="live-label")
    with pytest.raises(ExtractionFailure) as refused:
        enqueue(kit, body)
    assert refused.value.code == "live_not_enabled"
    with pytest.raises(ExtractionFailure) as refused:
        enqueue(kit, body, world.replay)
    assert refused.value.code == "fixture_not_allowed" and no_ledger(kit)


def test_a_live_enqueue_freezes_the_secret_free_runtime_without_key_network_or_budget(world, monkeypatch, tmp_path):
    kit = world.kit
    rid, _ = simple_round(kit, "live", ["supplier-a", "supplier-b"])
    budget = tmp_path / "budget"
    for name in LIVE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    for name, value in simulator_env("https://api.openai.com/v1", budget).items():
        if name not in SECRET_NAMES:
            monkeypatch.setenv(name, value)

    def refuse(*args, **kwargs):
        raise AssertionError("network attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    body = descriptor(rid, "live-1", events=[world.event], mode="live", prompt="live-label")
    report, code = enqueue(kit, body)
    assert code == 0 and registrations(report) == ["registered", "registered"] and not budget.exists()
    stored, calls = ledger(kit)
    assert calls == 0 and {row[2] for row in stored} == {"queued"}
    assert all("live" in json.loads(row[4]) and "replay" not in json.loads(row[4]) for row in stored)
    again, code = enqueue(kit, body)
    assert code == 0 and registrations(again) == ["existing", "existing"] and ledger(kit) == (stored, 0)
    monkeypatch.setenv("ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR", str(tmp_path / "budget-2"))   # another runtime identity: the frozen jobs conflict, nothing is written
    with pytest.raises(ExtractionFailure) as refused:
        enqueue(kit, body)
    assert refused.value.code == "job_input_conflict" and ledger(kit) == (stored, 0) and not (tmp_path / "budget-2").exists()


# ---------------------------------------------------------------- ledger and ingestion access ----------------------

def test_every_prepared_ref_filtered_and_no_ledger_creates_no_directory(world):
    kit = world.kit
    rid, _ = simple_round(kit, "snaponly", ["supplier-snap"], BASE_BODY)
    before = tree(kit.root / "ingestion")
    report, code = enqueue(kit, descriptor(rid, events=[world.event]), world.replay)
    assert code == 0 and [s["code"] for s in report["skipped"]] == ["in_snapshot"] and report["jobs"] == [] and no_ledger(kit)
    assert tree(kit.root / "ingestion") == before


def test_a_busy_writer_or_unrecovered_wal_refuses_a_read_only_preflight(world):
    kit = world.kit
    rid, _ = simple_round(kit, "snaponly", ["supplier-snap"], BASE_BODY)
    Store(kit.root / "extraction", kit.root / "ingestion").close()
    body = descriptor(rid, events=[world.event])
    writer = Store(kit.root / "extraction", kit.root / "ingestion")
    try:
        with pytest.raises(ExtractionFailure) as refused:
            enqueue(kit, body, world.replay)
        assert refused.value.code == "extraction_busy"
    finally:
        writer.close()
    assert enqueue(kit, body, world.replay)[1] == 0
    (kit.root / "extraction" / "extraction.sqlite3-wal").write_bytes(b"committed but unrecovered")
    with pytest.raises(ExtractionFailure) as refused:
        enqueue(kit, body, world.replay)
    assert refused.value.code == "extraction_recovery_required"


def test_a_busy_or_unrecovered_ingestion_ledger_refuses(world):
    kit = world.kit
    rid = make_round(kit, "prepared")
    body = descriptor(rid, events=[world.event])
    writer = IngestionStore(kit.root / "ingestion")
    try:
        with pytest.raises(IngestionFailure) as refused:
            enqueue(kit, body, world.replay)
        assert refused.value.code == "ingestion_busy"
    finally:
        writer.close()
    (kit.root / "ingestion" / "ingestion.sqlite3-wal").write_bytes(b"committed but unrecovered")
    with pytest.raises(IngestionFailure) as refused:
        enqueue(kit, body, world.replay)
    assert refused.value.code == "ingestion_recovery_required" and no_ledger(kit)


def test_admission_reports_new_or_existing_without_writing_and_works_read_only(world):
    kit = world.kit
    rid, _ = simple_round(kit, "docs", ["supplier-a"])
    submit = Submit.model_validate(kit.submit("job-a", observation(rid, candidates(kit, rid)[0]), [world.event]))
    fixtures = Fixtures(world.replay.read_bytes(), None)
    other = Replay(kit, "p-adm")
    other.doc["analysisVersion"] = "authored-analysis-2"
    changed_fixtures = Fixtures(other.write().read_bytes(), None)
    store = Store(kit.root / "extraction", kit.root / "ingestion")
    try:
        extractor = Extractor(store, Sources(kit.root / "ingestion", Authority(kit.registry_path)))
        assert extractor.admission(submit, fixtures) == "new" and store.one("SELECT COUNT(*) n FROM jobs")["n"] == 0
        extractor.freeze(submit, fixtures)
        assert extractor.admission(submit, fixtures) == "existing"
    finally:
        store.close()
    files = tree(kit.root / "extraction")
    store = Store(kit.root / "extraction", kit.root / "ingestion", existing=True)
    try:
        extractor = Extractor(store, Sources(kit.root / "ingestion", Authority(kit.registry_path)))
        assert extractor.admission(submit, fixtures) == "existing"
        with pytest.raises(ExtractionFailure) as refused:
            extractor.admission(submit, changed_fixtures)
        assert refused.value.code == "job_input_conflict"
    finally:
        store.close()
    assert tree(kit.root / "extraction") == files


# ---------------------------------------------------------------- partial failure and recovery ---------------------

def four(kit: Kit, world) -> tuple[str, dict]:
    rid, _ = simple_round(kit, "four", ["supplier-a", "supplier-b", "supplier-c", "supplier-d"])
    return rid, descriptor(rid, events=[world.event])


@pytest.mark.parametrize("at,partial", [(1, False), (2, True), (4, True)])
def test_rights_revoked_mid_batch_report_only_the_code_and_a_rerun_registers_the_rest(world, monkeypatch, at, partial):
    kit = world.kit
    grant = kit.registry["sources"][0]["grant"]
    rid, body = four(kit, world)

    def revoke():
        grant["enabled"] = False
        kit.save_registry()

    hook_freeze(monkeypatch, at, revoke)
    result = enqueue(kit, body, world.replay)
    assert result == ({"schemaVersion": SCHEMA, "error": {"code": "registry_changed", "partialRegistration": partial}}, 2)
    assert "s2r-" not in json.dumps(result) and len(ledger(kit)[0]) == at - 1
    grant["enabled"] = True
    kit.save_registry()
    report, code = enqueue(kit, body, world.replay)
    assert code == 0 and registrations(report) == ["existing"] * (at - 1) + ["registered"] * (5 - at)


@pytest.mark.parametrize("failure,code", [
    (ExtractionFailure("document_binding_changed"), "document_binding_changed"),
    (sqlite3.OperationalError("disk I/O error"), "persistence_failed"),
    (OSError("secret path /tmp/x"), "persistence_failed"),
    (RuntimeError("secret detail"), "extraction_internal_failure"),
])
def test_a_non_authority_failure_stops_the_batch_without_rollback_or_retry_and_is_reported_honestly(world, monkeypatch, failure, code):
    kit = world.kit
    rid, body = four(kit, world)

    def fail():
        raise failure

    seen = hook_freeze(monkeypatch, 2, fail)
    report, status = enqueue(kit, body, world.replay)
    assert status == 2 and report["outcome"] == "incomplete" and report["error"] == {"code": code} and "secret" not in json.dumps(report)
    assert registrations(report) == ["registered", "failed", "not-attempted", "not-attempted"]
    assert report["counts"] == {"refs": 4, "jobs": 4, "registered": 1, "existing": 0, "failed": 1, "notAttempted": 2, "skipped": 0}
    assert len(seen) == 2 and [row[0] for row in ledger(kit)[0]] == [report["jobs"][0]["jobId"]]   # no retry, nothing after the failure was attempted, no rollback
    again, status = enqueue(kit, body, world.replay)
    assert status == 0 and registrations(again) == ["existing", "registered", "registered", "registered"]


def test_a_process_killed_after_some_freezes_leaves_a_prefix_and_the_rerun_registers_the_exact_remainder(world, monkeypatch):
    kit = world.kit
    rid, body = four(kit, world)

    def kill():
        raise KeyboardInterrupt

    hook_freeze(monkeypatch, 3, kill)
    with pytest.raises(KeyboardInterrupt):
        enqueue(kit, body, world.replay)
    assert [row[0] for row in ledger(kit)[0]] == sorted(job_ids(kit, rid)[:2])
    report, code = enqueue(kit, body, world.replay)
    assert code == 0 and registrations(report) == ["existing", "existing", "registered", "registered"]
    assert [row[0] for row in ledger(kit)[0]] == sorted(job_ids(kit, rid))


def test_registered_jobs_resume_explicitly_to_ready_and_leave_ingestion_unchanged(world):
    kit = world.kit
    rid, _ = simple_round(kit, "resume", ["supplier-r"], BASE_BODY)
    ref = observation(rid, candidates(kit, rid)[0])
    article = kit.article(ref)
    replay = kit.replay("resume").extract(article, [kit.mention(article, "m-r", [kit.evidence(article, Q3)])]).write()
    report, code = enqueue(kit, descriptor(rid, "resume-1"), replay)
    job_id = report["jobs"][0]["jobId"]
    assert code == 0 and ledger(kit)[0][0][2] == "queued"
    before = tree(kit.root / "ingestion")
    done = kit.job("resume", kit.job_selector(job_id), replay=replay)
    assert done["state"] == "ready" and done["usage"]["replayCalls"] == 1
    assert tree(kit.root / "ingestion") == before and ledger(kit)[0][0][2] == "ready"


# ---------------------------------------------------------------- the actual process ------------------------------

def error_body(code: str) -> dict:
    return {"schemaVersion": SCHEMA, "error": {"code": code}}


def test_the_cli_registers_without_executing_and_refuses_with_the_ordinary_error_body(world):
    kit = world.kit
    rid, _ = simple_round(kit, "cli", ["supplier-a", "supplier-b"])
    body = descriptor(rid, "cli-1", events=[world.event])
    out = kit.run("enqueue-round", body, replay=world.replay, forbid_execution=True)
    assert out["outcome"] == "complete" and out["counts"]["registered"] == 2 and out["error"] is None
    stored = ledger(kit)
    assert [row[2] for row in stored[0]] == ["queued", "queued"] and stored[1] == 0
    again = kit.run("enqueue-round", body, replay=world.replay, forbid_execution=True)
    assert again["counts"]["existing"] == 2 and ledger(kit) == stored
    assert kit.run("enqueue-round", body, expected=2) == error_body("replay_fixture_required")
    assert kit.run("enqueue-round", body, replay=world.replay, topic=world.replay, expected=2) == error_body("fixture_not_allowed")
    assert kit.run("enqueue-round", body, replay=world.replay, extra=("--initial-only",), expected=2) == error_body("initial_only_not_allowed")
    live = {**body, "provenance": {"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"}}
    assert kit.run("enqueue-round", live, replay=world.replay, expected=2) == error_body("fixture_not_allowed")
    assert kit.run("enqueue-round", {**body, "extra": 1}, replay=world.replay, expected=2) == error_body("input_or_configuration_invalid")
    assert kit.run("enqueue-round", descriptor("round-none"), replay=world.replay, expected=2) == error_body("round_not_found")
    assert ledger(kit) == stored


# ---------------------------------------------------------------- partial extraction state fails closed -------------

DAMAGE = {
    "lock removed": lambda d: (d / "extraction.lock").unlink(),
    "database removed": lambda d: (d / "extraction.sqlite3").unlink(),
    "lock removed, hot wal": lambda d: ((d / "extraction.lock").unlink(), (d / "extraction.sqlite3-wal").write_bytes(b"committed but unrecovered")),
}


@pytest.mark.parametrize("damage", list(DAMAGE))
def test_a_partial_extraction_state_is_refused_not_read_as_no_prior_jobs(world, damage):
    """Every prepared ref is `in_snapshot`, so only the read-only ledger preflight can notice the job registered under the OTHER snapshot. A ledger whose
    lock or database is gone is damaged state, not an absent one: reading it as 'no prior jobs' would let the changed snapshot through and skip the
    conflict (or a hot WAL). It must be refused, and nothing may be created, repaired or written."""
    kit = world.kit
    rid, _ = simple_round(kit, "snaponly", ["supplier-snap"], BASE_BODY)
    assert kit.run("enqueue-round", descriptor(rid, events=[]), replay=world.replay)["counts"]["registered"] == 1
    changed = descriptor(rid, events=[world.event])
    assert kit.run("enqueue-round", changed, replay=world.replay, expected=2) == error_body("job_input_conflict")   # the intact ledger refuses the change
    directory = kit.root / "extraction"
    DAMAGE[damage](directory)
    before = (tree(directory), tree(kit.root / "ingestion"))
    assert kit.run("enqueue-round", changed, replay=world.replay, expected=2) == error_body("extraction_state_missing")
    assert (tree(directory), tree(kit.root / "ingestion")) == before


def test_a_foreign_or_nonempty_extraction_directory_is_not_an_absent_ledger(world):
    kit = world.kit
    rid, _ = simple_round(kit, "snaponly", ["supplier-snap"], BASE_BODY)
    directory = kit.root / "extraction"
    directory.mkdir(mode=0o700)
    (directory / "foreign.txt").write_text("not an extraction ledger")
    before = (tree(directory), tree(kit.root / "ingestion"))
    refused = kit.run("enqueue-round", descriptor(rid, events=[world.event]), replay=world.replay, expected=2)
    assert set(refused) == {"schemaVersion", "error"} and refused["error"]["code"] in {"extraction_state_missing", "state_namespace_conflict"}
    assert (tree(directory), tree(kit.root / "ingestion")) == before


@pytest.mark.parametrize("empty_directory", [False, True])
def test_a_genuinely_absent_or_empty_extraction_state_still_means_no_prior_jobs(world, empty_directory):
    kit = world.kit
    rid, _ = simple_round(kit, "snaponly", ["supplier-snap"], BASE_BODY)
    directory = kit.root / "extraction"
    if empty_directory:
        directory.mkdir(mode=0o700)
    before = tree(kit.root / "ingestion")
    out = kit.run("enqueue-round", descriptor(rid, events=[world.event]), replay=world.replay)
    assert out["jobs"] == [] and [s["code"] for s in out["skipped"]] == ["in_snapshot"] and tree(kit.root / "ingestion") == before
    assert list(directory.iterdir()) == [] if empty_directory else not directory.exists()


# ---------------------------------------------------------------- a failing ledger close after committed jobs -------

def failing_close(failure: Exception, after=lambda: None):
    """A `Store.close` that really closes (so the lock is released and the WAL is checkpointed) and only then fails, like a late I/O error."""
    original = Store.close

    def close(self):
        original(self)
        after()
        raise failure

    return close


@pytest.mark.parametrize("failure,code", [
    (OSError("secret path /tmp/x"), "persistence_failed"),
    (sqlite3.OperationalError("secret disk error"), "persistence_failed"),
    (RuntimeError("secret detail"), "extraction_internal_failure"),   # an unexpected close error is sanitized to the generic code
])
def test_a_ledger_close_failure_after_committed_jobs_is_an_honest_incomplete_report(world, monkeypatch, failure, code):
    """The four jobs are durably committed before the close fails: the failure must surface as the report's error with the real registered counts,
    never as a generic error body that hides the committed prefix."""
    kit = world.kit
    rid, body = four(kit, world)
    with monkeypatch.context() as patched:
        patched.setattr(Store, "close", failing_close(failure))
        report, status = enqueue(kit, body, world.replay)
    assert status == 2 and report["outcome"] == "incomplete" and report["error"] == {"code": code} and "secret" not in json.dumps(report)
    assert registrations(report) == ["registered"] * 4
    assert report["counts"] == {"refs": 4, "jobs": 4, "registered": 4, "existing": 0, "failed": 0, "notAttempted": 0, "skipped": 0}
    assert [row[0] for row in ledger(kit)[0]] == sorted(job_ids(kit, rid))
    again, status = enqueue(kit, body, world.replay)
    assert status == 0 and registrations(again) == ["existing"] * 4


def test_a_ledger_close_failure_does_not_bypass_the_final_authority_check(world, monkeypatch):
    """Rights revoked by the time the close fails: still only the code and `partialRegistration`, no job ids, no report."""
    kit = world.kit
    grant = kit.registry["sources"][0]["grant"]
    rid, body = four(kit, world)

    def revoke():
        grant["enabled"] = False
        kit.save_registry()

    with monkeypatch.context() as patched:
        patched.setattr(Store, "close", failing_close(OSError("secret path /tmp/x"), revoke))
        result = enqueue(kit, body, world.replay)
    assert result == ({"schemaVersion": SCHEMA, "error": {"code": "registry_changed", "partialRegistration": True}}, 2)
    assert "s2r-" not in json.dumps(result) and "secret" not in json.dumps(result)
    assert [row[0] for row in ledger(kit)[0]] == sorted(job_ids(kit, rid))
    grant["enabled"] = True
    kit.save_registry()
    again, status = enqueue(kit, body, world.replay)
    assert status == 0 and registrations(again) == ["existing"] * 4


def test_a_ledger_close_failure_never_masks_a_preflight_refusal(world, monkeypatch):
    kit = world.kit
    rid, _ = simple_round(kit, "docs", ["supplier-a", "supplier-b"])
    enqueue(kit, descriptor(rid, events=[world.event]), world.replay)
    before = ledger(kit)
    with monkeypatch.context() as patched:
        patched.setattr(Store, "close", failing_close(OSError("secret path /tmp/x")))
        with pytest.raises(ExtractionFailure) as refused:
            enqueue(kit, descriptor(rid, events=[]), world.replay)   # another snapshot for the same label: `job_input_conflict` before any write
    assert refused.value.code == "job_input_conflict" and ledger(kit) == before
