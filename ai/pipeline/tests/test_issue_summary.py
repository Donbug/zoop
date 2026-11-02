"""Issue summary job ledger over an authored world: replay lifecycle, deterministic refusals, duplicate identity, changed basis, rights and the live path
through a fake transport only (no network, no key, no model). The planner seam is a hand-written world; expectations are written out by hand."""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from tests.live_support import JEV_KEY, OPENAI_KEY, Fake, choice, environment, json_response, openai_reply
from zoop_ai_pipeline import issue_summary as isum
from zoop_ai_pipeline import issue_summary_cli as cli
from zoop_ai_pipeline import issue_summary_contracts as c
from zoop_ai_pipeline import issue_summary_jev as jev
from zoop_ai_pipeline import issue_summary_prompts as prompts
from zoop_ai_pipeline import live_runtime as live
from zoop_ai_pipeline.extraction_contracts import ExtractionFailure
from zoop_ai_pipeline.handoff_contracts import app_evidence_id, text_sha256
from zoop_ai_pipeline.live_runtime import ISSUE_SUMMARY, LiveRuntime
from zoop_ai_pipeline.relation_contracts import canonical, digest

REPLAY, LIVE = ("replay", "authored-test"), ("live", "provider")
TITLE = "고유제목표지 합성 계약"
S1 = "합성기업은 2026년 3분기 공급 계약을 발표했다."
S2 = "계약 상대는 합성부품이다."
S3 = "합성부품은 이전에 시험 생산을 마쳤다."
CLAIM1 = "합성기업은 2026년 3분기 공급 계약을 발표했으며 계약 상대는 합성부품이다."
CLAIM2 = "합성부품은 이전에 시험 생산을 마쳤다."


def h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


MANIFEST = {"schemaVersion": "zoop-ai-handoff-1", "handoffId": "handoff-test-1", "sourceKind": "synthetic", "policyVersion": "zoop-public-projection-policy-2",
            "sources": [{"relation": {"jobId": "rel-a", "inputDigest": h("rel")}, "upstream": {"jobId": "s2-a", "inputDigest": h("s2"), "digest": h("up")},
                         "reviewDigest": h("review")}],
            "files": {"canonical": h("canonical"), "decisions": h("decisions"), "bindings": h("bindings")}}
REQUEST = {"schemaVersion": "zoop-issue-summary-1", "jobId": "isum-1", "issueId": "issue:one", "mode": "replay", "manifest": MANIFEST}


def submit(**changes) -> isum.Submit:
    return isum.Submit.model_validate({**REQUEST, **changes})


class Crash(BaseException):
    """A process that dies at a seam: nothing after it runs, the engine's own handlers (which catch Exception) never see it."""


class Sources:
    """The model-send authority the planner hands out: records every check and refuses on demand."""

    def __init__(self):
        self.log, self.denied, self.denied_purposes = [], None, set()

    def authorize_model_send(self, ref, purpose, recipient):
        self.log.append((ref, purpose, recipient))
        if self.denied or purpose in self.denied_purposes:
            raise ExtractionFailure(self.denied or "source_purpose_or_recipient_denied")


class World:
    """One public issue over one article: sentences[:-1] are reported by mention m1, the last one is a background (past-context) mention m2. `plan` is the
    handoff's `plan_summary_input` seam: a fresh value object per call (deep copies), so a test changes the world by editing the attributes below."""

    def __init__(self, sentences=(S1, S2, S3), execution=REPLAY):
        self.text = " ".join(sentences)
        self.sentences, self.execution, self.source_kind, self.fail, self.hook = list(sentences), execution, "synthetic", None, None
        self.sources, self.plans = Sources(), 0
        self.article, self.version, self.document_version = "doc-" + h("article"), h("article-version"), h("document-version")
        self.evidence = {}
        for sentence in self.sentences:
            start = self.text.index(sentence)
            ident = app_evidence_id(self.article, self.version, start, start + len(sentence))
            self.evidence[ident] = {"id": ident, "articleId": self.article, "articleVersion": self.version, "start": start, "end": start + len(sentence),
                                    "quoteSha256": text_sha256(sentence)}
        ids = list(self.evidence)
        self.articles = {(self.article, self.version): {"articleId": self.article, "articleVersion": self.version, "documentId": "doc-1",
                                                        "documentVersion": self.document_version, "textSha256": text_sha256(self.text)}}
        self.issue = {"id": "issue:one", "title": TITLE, "fieldVerdicts": [],
                      "mentions": [{"mentionId": "m1", "background": False, "evidenceIds": ids[:-1]}, {"mentionId": "m2", "background": True, "evidenceIds": ids[-1:]}]}

    def ev(self, sentence: str) -> str:
        return next(i for i, e in self.evidence.items() if self.text[e["start"]:e["end"]] == sentence)

    def planned(self, handoff_id: str = "handoff-test-1"):
        """The planner's value object, built without side effects (authoring a fixture never counts as a plan)."""
        return SimpleNamespace(handoff_id=handoff_id, issue=copy.deepcopy(self.issue), evidence=copy.deepcopy(self.evidence), articles=copy.deepcopy(self.articles),
                               execution=self.execution, source_kind=self.source_kind,
                               documents={("doc-1", self.document_version): (("ref-1", {"document": {"text": self.text}}),)}, sources=self.sources)

    def plan(self, manifest, issue_id):
        self.plans += 1
        if self.hook:
            self.hook()
        if self.fail:
            raise ExtractionFailure(self.fail)
        if issue_id != self.issue["id"]:
            raise ExtractionFailure("issue_not_public")
        return self.planned(manifest.handoff_id)

    def basis(self) -> dict:
        planned = self.planned()
        return c.summary_basis(planned.issue, planned.evidence, planned.articles)

    def payload(self) -> dict:
        basis = self.basis()
        return isum.producer_payload(basis, {q["evidenceId"]: self.text[q["start"]:q["end"]] for q in basis["quotes"]})

    def label(self, sentence: str) -> str:
        return next(f"q{n + 1}" for n, q in enumerate(self.payload()["quotes"]) if q["text"] == sentence)


def reply_of(world: World) -> dict:
    """The model reply an author writes: two claims citing the quotes by their positional labels."""
    return {"claims": [{"text": CLAIM1, "quoteIds": [world.label(S1), world.label(S2)]}, {"text": CLAIM2, "quoteIds": [world.label(S3)]}]}


def answer_of(decisions=("supported", "supported"), advice="absent", causality="absent", framing="absent") -> dict:
    return {"claims": [{"claimId": f"c{n + 1}", "decision": d, "reason": "authored"} for n, d in enumerate(decisions)],
            "prohibitedAdvice": advice, "unsupportedCausality": causality, "backgroundAsCurrent": framing}


def author(world: World, reply=None, answer=..., *, synthetic: bool = True) -> bytes:
    """An authored replay fixture: each record keyed by the digest of the exact native payload it answers (`answer=None`: no verifier record)."""
    payload, reply = world.payload(), reply or reply_of(world)
    records = [{"stage": "issue-summary", "requestDigest": digest(payload), "response": reply}]
    answer = answer_of() if answer is ... else answer
    if answer is not None:
        claims = prompts.claims_from(reply, payload)
        records.append({"stage": "verify-issue-summary", "requestDigest": digest(isum.verifier_payload(payload, claims)), "response": answer})
    return json.dumps({"format": "zoop-issue-summary-fixture-1", "synthetic": synthetic, "recordingKind": "authored-test", "records": records}, ensure_ascii=False).encode()


@pytest.fixture
def stores():
    opened = []
    yield opened
    for store in opened:
        store.close()


def engine_for(tmp_path: Path, stores: list, world: World, factory=None, name: str = "state") -> isum.Engine:
    store = isum.Store(tmp_path / name)
    stores.append(store)
    return isum.Engine(store, world.plan, factory)


def reopen(tmp_path: Path, stores: list, world: World, factory=None, name: str = "state") -> isum.Engine:
    for store in stores:
        store.close()
    return engine_for(tmp_path, stores, world, factory, name)


def rows(engine: isum.Engine) -> dict:
    return {t: engine.store.one(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in ("jobs", "calls", "results", "refusals")}


def code_of(call) -> str:
    with pytest.raises(ExtractionFailure) as caught:
        call()
    return caught.value.code


def snapshot(root: Path) -> dict:
    return {p.name: (p.stat().st_size, p.stat().st_mtime_ns, h(p.read_bytes().decode("latin-1"))) for p in sorted(root.iterdir())}


# ======================================================================================================== replay =====================

def test_submit_freezes_the_exact_input_without_any_call_or_execution(tmp_path, stores):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    engine.freeze(submit())
    out = engine.inspect("isum-1")
    assert out["state"] == "queued" and out["phase"] == "produce" and out["failure"] is None and out["result"] is None and out["calls"] == []
    assert out["usage"] == {"executionMode": "replay", "replayCalls": 0, "startedWithoutReceipt": 0, "providerCalls": 0, "modelCalls": 0, "creatorJobId": "isum-1"}
    assert out["issueId"] == "issue:one" and out["provenance"] == {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"}
    assert out["basis"] == {"digest": c.basis_digest(world.basis()), "quotes": 3, "articles": 1} and world.sources.log == []
    assert rows(engine) == {"jobs": 1, "calls": 0, "results": 0, "refusals": 0}


def test_a_replay_run_is_available_with_every_value_pinned_and_a_second_run_changes_nothing(tmp_path, stores):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    raw = author(world)
    out = engine.run(submit(), isum.Fixtures(raw))
    assert out["state"] == "ready" and out["phase"] == "complete" and out["failure"] is None
    assert out["usage"] == {"executionMode": "replay", "replayCalls": 2, "startedWithoutReceipt": 0, "providerCalls": 0, "modelCalls": 0, "creatorJobId": "isum-1"}
    assert [(call["stage"], call["state"], call["fixtureHash"]) for call in out["calls"]] == [("issue-summary", "received", h(raw.decode())),
                                                                                              ("verify-issue-summary", "received", h(raw.decode()))]
    summary = out["result"]["summary"]
    e1, e2, e3 = world.ev(S1), world.ev(S2), world.ev(S3)
    assert out["result"]["outcome"] == "available" and summary["status"] == "available" and summary["language"] == "ko"
    assert summary["text"] == CLAIM1 + "\n" + CLAIM2
    assert summary["claims"] == [{"claimId": "c1", "text": CLAIM1, "evidenceIds": sorted([e1, e2])}, {"claimId": "c2", "text": CLAIM2, "evidenceIds": [e3]}]
    assert summary["evidenceIds"] == sorted([e1, e2, e3])
    spec, payload = prompts.SPECS["issue-summary"], world.payload()
    claims = prompts.claims_from(reply_of(world), payload)
    assert summary["producer"] == {"kind": "authored-replay", "model": None, "reasoningEffort": None, "promptVersion": spec.prompt_version,
                                   "schemaDigest": spec.schema_digest, "runtimeIdentity": h(raw.decode())}
    assert summary["verifier"] == {"kind": "authored-replay", "model": None, "adapterIdentity": jev.identity(), "requestDigest": digest(isum.verifier_payload(payload, claims))}
    assert summary["source"]["jobId"] == "isum-1" and summary["source"]["inputDigest"] == out["inputDigest"] and summary["source"]["basisDigest"] == c.basis_digest(world.basis())
    assert summary["source"]["resultDigest"] == out["result"]["resultDigest"]
    c.check_summary(world.issue, summary, world.basis(), REPLAY)           # the bundle validator accepts exactly this value
    assert world.sources.log == [] and sorted(call["requestDigest"] for call in out["calls"]) == sorted([digest(payload), digest(isum.verifier_payload(payload, claims))])
    # A finished job is not executed again: no fixture, no new call row. Showing it costs exactly one fresh read-only proof of the sources and the basis.
    plans = world.plans
    assert engine.resume("isum-1", isum.Fixtures(None)) == out and world.plans == plans + 1 and rows(engine)["calls"] == 2


def test_load_result_is_a_read_only_view_of_exactly_the_bundle_summary(tmp_path, stores):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    out = engine.run(submit(), isum.Fixtures(author(world)))
    stores[0].close()
    root = tmp_path / "state"
    before = snapshot(root)
    found = isum.load_result(root, job_id="isum-1")
    assert snapshot(root) == before
    assert found == isum.ReadyResult("isum-1", out["inputDigest"], out["result"]["resultDigest"], "issue:one", REPLAY, "synthetic", out["result"]["summary"])
    assert code_of(lambda: isum.load_result(root, job_id="nope")) == "issue_summary_not_found"
    assert code_of(lambda: isum.load_result(tmp_path / "absent", job_id="isum-1")) == "issue_summary_state_missing"
    assert code_of(lambda: isum.load_result(root, tmp_path, job_id="isum-1")) == "state_namespace_conflict"      # a source root that contains it is refused
    held = isum.Store(root)
    stores.append(held)
    assert code_of(lambda: isum.load_result(root, job_id="isum-1")) == "issue_summary_busy"                    # a live writer is never read around


def test_a_ready_result_is_shown_only_while_current_source_rights_and_the_frozen_basis_prove(tmp_path, stores):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    done = engine.run(submit(), isum.Fixtures(author(world)))
    assert done["delivery"]["status"] == "current" and done["result"]["summary"]["status"] == "available"
    calls = rows(engine)["calls"]
    for code, break_it, mend_it in (
            ("source_unauthorized", lambda: setattr(world, "fail", "source_unauthorized"), lambda: setattr(world, "fail", None)),
            ("issue_summary_basis_changed", lambda: world.issue.update(title="다른 제목"), lambda: world.issue.update(title=TITLE)),
            ("issue_temporal_review_pending", lambda: world.issue.update(fieldVerdicts=[{"field": "period", "decision": "HOLD"}]), lambda: world.issue.update(fieldVerdicts=[]))):
        break_it()
        for hidden in (engine.inspect("isum-1"), engine.resume("isum-1", isum.Fixtures(None))):
            # `ready` is not deliverable by itself: identity, state and usage stay, the content does not.
            assert hidden["state"] == "ready" and hidden["delivery"] == {"status": "withheld", "code": code} and hidden["result"] is None, code
            assert (hidden["jobId"], hidden["inputDigest"], hidden["issueId"], hidden["usage"], hidden["basis"]) == (done["jobId"], done["inputDigest"], done["issueId"],
                                                                                                               done["usage"], done["basis"])
            assert CLAIM1 not in json.dumps(hidden, ensure_ascii=False) and done["result"]["resultDigest"] not in json.dumps(hidden)
        mend_it()
        assert engine.inspect("isum-1") == done and rows(engine)["calls"] == calls           # restored: the same immutable result, and nothing was called
    # The handoff's own reader is a ledger reader: it never withholds, the handoff proves rights and basis itself.
    world.fail = "source_unauthorized"
    stores[0].close()
    assert isum.load_result(tmp_path / "state", job_id="isum-1").summary == done["result"]["summary"]


def test_a_writer_never_recreates_a_partial_ledger(tmp_path):
    for n, names in enumerate((["issue-summary.lock"], ["issue-summary.sqlite3"], ["issue-summary.sqlite3-wal"], ["issue-summary.lock", "issue-summary.sqlite3-wal"],
                               ["issue-summary.lock", "issue-summary.sqlite3-shm"])):
        root = tmp_path / f"partial-{n}"
        root.mkdir()
        for name in names:
            (root / name).write_bytes(b"")
        assert code_of(lambda: isum.Store(root)) == "issue_summary_state_partial" and sorted(p.name for p in root.iterdir()) == sorted(names)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("not ours")
    assert code_of(lambda: isum.Store(foreign)) == "state_namespace_conflict" and [p.name for p in foreign.iterdir()] == ["notes.txt"]
    for fresh in (tmp_path / "absent", tmp_path / "empty"):
        if fresh.name == "empty":
            fresh.mkdir()
        isum.Store(fresh).close()                                  # only an absent path or an empty directory is a new ledger
        assert {p.name for p in fresh.iterdir()} >= {"issue-summary.sqlite3", "issue-summary.lock"}
        isum.Store(fresh).close()                                  # and a complete one reopens
    # An established ledger proves itself before anything is written: an empty or foreign database is never initialised as new history.
    for n, (setup, code) in enumerate(((lambda db: None, "issue_summary_state_invalid"),
                                       (lambda db: db.execute("CREATE TABLE foreign_table(x)"), "issue_summary_state_invalid"),
                                       (lambda db: (db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"), db.execute("INSERT INTO meta VALUES('ledger','other')")),
                                        "issue_summary_ledger_unknown"))):
        root = tmp_path / f"foreign-db-{n}"
        root.mkdir()
        (root / "issue-summary.lock").write_bytes(b"")
        database = sqlite3.connect(root / "issue-summary.sqlite3", isolation_level=None)
        setup(database)
        database.close()
        (root / "issue-summary.sqlite3").touch()                    # a connection that wrote nothing leaves no file: the empty database exists on purpose
        before = {p.name: p.read_bytes() for p in root.iterdir()}
        assert code_of(lambda: isum.Store(root)) == code and {p.name: p.read_bytes() for p in root.iterdir()} == before


@pytest.mark.parametrize("name,answer,outcome", [
    ("a claim is insufficient", answer_of(("supported", "insufficient")), "verifier-hold"),
    ("advice is uncertain", answer_of(advice="uncertain"), "verifier-hold"),
    ("causality is uncertain", answer_of(causality="uncertain"), "verifier-hold"),
    ("framing is uncertain", answer_of(framing="uncertain"), "verifier-hold"),
    ("a claim is contradicted", answer_of(("contradicted", "supported")), "verifier-reject"),
    ("advice is present", answer_of(advice="present"), "verifier-reject"),
    ("causality is present", answer_of(causality="present"), "verifier-reject"),
    ("a background quote is framed as current", answer_of(framing="present"), "verifier-reject"),
    ("a reject outranks a hold", answer_of(("insufficient", "contradicted")), "verifier-reject")])
def test_a_negative_verification_is_a_ready_withheld_result_pinned_to_the_job_never_an_empty_summary(tmp_path, stores, name, answer, outcome):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    out = engine.run(submit(), isum.Fixtures(author(world, answer=answer)))
    assert out["state"] == "ready" and out["result"]["outcome"] == outcome and out["usage"]["replayCalls"] == 2, name
    summary = out["result"]["summary"]
    assert summary == {"status": "unavailable", "code": outcome, "source": {"jobId": "isum-1", "inputDigest": out["inputDigest"], "basisDigest": c.basis_digest(world.basis()),
                                                                          "resultDigest": c.result_digest("isum-1", out["inputDigest"], c.basis_digest(world.basis()),
                                                                                                         {"status": "unavailable", "code": outcome})}}
    c.check_summary(world.issue, summary, world.basis(), REPLAY)
    assert "text" not in summary and "claims" not in summary


@pytest.mark.parametrize("reply", [
    {"claims": [{"text": CLAIM2, "quoteIds": ["q1"]}] * 6},
    {"claims": [{"text": "Synthetic English only.", "quoteIds": ["q1"]}]},
    {"claims": [{"text": CLAIM2, "quoteIds": ["q9"]}]},
    {"claims": [{"text": CLAIM2, "quoteIds": []}]},
    {"claims": [{"text": CLAIM2, "quoteIds": ["q1"]}], "note": "extra key"},
    {"claims": []}])
def test_an_invalid_producer_reply_is_a_ready_producer_invalid_result_and_the_verifier_is_never_asked(tmp_path, stores, reply):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    out = engine.run(submit(), isum.Fixtures(author(world, reply=reply, answer=None)))
    assert out["state"] == "ready" and out["result"]["outcome"] == "producer-invalid" and [c_["stage"] for c_ in out["calls"]] == ["issue-summary"]
    assert out["calls"][0]["verdict"] == "producer-invalid" and out["usage"]["replayCalls"] == 1
    c.check_summary(world.issue, out["result"]["summary"], world.basis(), REPLAY)


def test_a_missing_or_foreign_fixture_stops_the_job_without_a_result_and_the_stored_call_is_reused(tmp_path, stores):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    out = engine.run(submit(), isum.Fixtures(None))
    assert out["state"] == "stopped" and out["failure"]["code"] == "replay_fixture_required" and out["calls"] == [] and out["result"] is None
    foreign = engine.resume("isum-1", isum.Fixtures(author(world, synthetic=False)))
    assert foreign["state"] == "stopped" and foreign["failure"]["code"] == "replay_provenance_conflict" and foreign["calls"] == []
    partial = engine.resume("isum-1", isum.Fixtures(author(world, answer=None)))
    assert partial["state"] == "stopped" and partial["failure"]["code"] == "replay_fixture_missing" and partial["failure"]["detail"]["stage"] == "verify-issue-summary"
    assert [c_["stage"] for c_ in partial["calls"]] == ["issue-summary"] and partial["result"] is None
    done = engine.resume("isum-1", isum.Fixtures(author(world)))
    assert done["state"] == "ready" and done["usage"]["replayCalls"] == 2 and rows(engine)["calls"] == 2
    assert code_of(lambda: isum.Fixtures(b'{"format": "wrong"}')) == "issue_summary_fixture_invalid"


def test_a_verifier_answer_that_is_not_the_asked_shape_fails_the_job_terminally(tmp_path, stores):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    bad = {"claims": [{"claimId": "c1", "decision": "supported", "reason": "x"}], "prohibitedAdvice": "absent", "unsupportedCausality": "absent", "backgroundAsCurrent": "absent"}
    out = engine.run(submit(), isum.Fixtures(author(world, answer=bad)))
    assert out["state"] == "failed" and out["failure"] == {"code": "verification_unavailable", "detail": {"stage": "verify-issue-summary", "code": "verifier_reply_invalid"}}
    assert out["result"] is None and out["calls"][1]["verdict"] == "verifier_reply_invalid"
    assert engine.resume("isum-1", isum.Fixtures(author(world))) == out         # terminal: a corrected fixture does not repair a consumed call


# ============================================================================================ deterministic refusals ==================

@pytest.mark.parametrize("decision", ["HOLD", "REJECT"])
def test_a_held_time_verdict_is_refused_before_any_row_or_call(tmp_path, stores, decision):
    world = World()
    good = author(world)
    world.issue["fieldVerdicts"] = [{"field": "period", "decision": decision}]
    engine = engine_for(tmp_path, stores, world, factory=lambda need_send: pytest.fail("a refused submit never builds a runtime"))
    assert code_of(lambda: engine.freeze(submit())) == "issue_temporal_review_pending"
    assert code_of(lambda: engine.run(submit(), isum.Fixtures(good))) == "issue_temporal_review_pending"
    live_request = submit(mode="live")
    assert code_of(lambda: engine.freeze(live_request)) == "issue_temporal_review_pending"
    assert rows(engine) == {"jobs": 0, "calls": 0, "results": 0, "refusals": 0} and world.sources.log == []


def test_an_allowed_verdict_does_not_block_and_a_later_hold_stops_the_job_before_any_call(tmp_path, stores):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    world.issue["fieldVerdicts"] = [{"field": "eventTime", "decision": "ALLOW"}]
    engine.freeze(submit())
    good = author(world)
    world.issue["fieldVerdicts"] = [{"field": "eventTime", "decision": "HOLD"}]
    held = engine.resume("isum-1", isum.Fixtures(good))
    assert held["state"] == "stopped" and held["failure"]["code"] == "issue_temporal_review_pending" and held["calls"] == [] and rows(engine)["results"] == 0
    world.issue["fieldVerdicts"] = [{"field": "eventTime", "decision": "ALLOW"}]
    assert engine.resume("isum-1", isum.Fixtures(good))["state"] == "ready"


def test_more_than_sixty_quotes_is_refused_and_exactly_sixty_is_accepted(tmp_path, stores):
    many = [f"문장{n:02d}: 합성 공급 계약을 설명한다." for n in range(61)]
    big = World(many)
    engine = engine_for(tmp_path, stores, big)
    assert code_of(lambda: engine.freeze(submit())) == "issue_summary_input_too_large" and rows(engine)["jobs"] == 0
    exact = World(many[:60])
    engine = reopen(tmp_path, stores, exact, name="state-sixty")
    engine.freeze(submit())
    assert engine.inspect("isum-1")["basis"]["quotes"] == 60 and engine.inspect("isum-1")["state"] == "queued"


@pytest.mark.parametrize("execution,mode", [(LIVE, "replay"), (REPLAY, "live")])
def test_the_requested_mode_must_be_the_mode_the_sources_really_ran(tmp_path, stores, execution, mode):
    world = World(execution=execution)
    engine = engine_for(tmp_path, stores, world, factory=lambda need_send: pytest.fail("no runtime for a refused mode"))
    assert code_of(lambda: engine.freeze(submit(mode=mode))) == "provenance_mode_conflict" and rows(engine)["jobs"] == 0


@pytest.mark.parametrize("planner_code", ["operator_file_pin_mismatch", "review_revision_changed", "upstream_changed", "decisions_invalid", "issue_not_public",
                                          "source_unauthorized"])
def test_a_pin_the_planner_cannot_prove_is_refused_with_its_code_and_writes_nothing(tmp_path, stores, planner_code):
    world = World()
    world.fail = planner_code
    engine = engine_for(tmp_path, stores, world)
    assert code_of(lambda: engine.freeze(submit())) == planner_code and rows(engine) == {"jobs": 0, "calls": 0, "results": 0, "refusals": 0}


# ======================================================================================================= identity =====================

def test_the_same_request_is_idempotent_without_reading_anything_and_another_request_under_its_id_conflicts(tmp_path, stores):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    engine.freeze(submit())
    plans, world.fail = world.plans, "source_unauthorized"
    engine.freeze(submit())                                                  # an existing job is never re-read: even a broken world does not matter
    assert world.plans == plans and rows(engine)["jobs"] == 1
    other = submit(manifest={**MANIFEST, "handoffId": "handoff-test-2"})
    assert code_of(lambda: engine.freeze(other)) == "job_input_conflict" and rows(engine)["jobs"] == 1
    assert code_of(lambda: engine.freeze(submit(mode="live"))) == "job_input_conflict"


def test_a_second_job_over_the_exact_same_input_is_refused_until_the_first_has_failed(tmp_path, stores):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    engine.freeze(submit())
    twin = submit(jobId="isum-2")
    with pytest.raises(ExtractionFailure) as caught:
        engine.freeze(twin)
    assert caught.value.code == "issue_summary_input_duplicate" and caught.value.detail == {"jobId": "isum-1"} and rows(engine)["jobs"] == 1
    engine.run(submit(), isum.Fixtures(author(world)))                      # ready: the result is reused by pinning it, never produced twice
    assert code_of(lambda: engine.freeze(twin)) == "issue_summary_input_duplicate"
    # A FAILED job (a consumed call without a usable judgment) does not hold its input: a new job is an explicit new run.
    other = World()
    engine = reopen(tmp_path, stores, other, name="state-failed")
    bad = {"claims": [], "prohibitedAdvice": "absent", "unsupportedCausality": "absent", "backgroundAsCurrent": "absent"}
    assert engine.run(submit(), isum.Fixtures(author(other, answer=bad)))["state"] == "failed"
    done = engine.run(twin, isum.Fixtures(author(other)))
    assert done["state"] == "ready" and rows(engine)["jobs"] == 2
    assert done["inputDigest"] == engine.inspect("isum-1")["inputDigest"]




def test_a_job_bound_to_a_stale_manifest_is_released_by_cancel_so_a_new_job_can_take_its_input(tmp_path, stores):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    engine.freeze(submit())
    world.fail = "operator_file_pin_mismatch"             # an unrelated operator file moved: the job is bound to the manifest it was submitted with
    stale = engine.resume("isum-1", isum.Fixtures(author(World())))
    assert stale["state"] == "stopped" and stale["failure"]["code"] == "operator_file_pin_mismatch"
    world.fail = None
    replacement = submit(jobId="isum-2", manifest={**MANIFEST, "files": {**MANIFEST["files"], "decisions": h("decisions-2")}})
    assert code_of(lambda: engine.freeze(replacement)) == "issue_summary_input_duplicate"           # a stopped job still holds its input ...
    plans = world.plans
    cancelled = engine.cancel("isum-1")
    assert cancelled["state"] == "failed" and cancelled["failure"] == {"code": "job_cancelled"} and cancelled["result"] is None and world.plans == plans
    done = engine.run(replacement, isum.Fixtures(author(world)))                                      # ... until it is cancelled
    assert done["state"] == "ready" and done["inputDigest"] == stale["inputDigest"] and rows(engine)["jobs"] == 2
    assert code_of(lambda: engine.cancel("isum-1")) == "job_already_terminal" and code_of(lambda: engine.cancel("isum-2")) == "job_already_terminal"
    assert code_of(lambda: engine.cancel("nope")) == "job_not_found"
    assert engine.resume("isum-1", isum.Fixtures(None)) == cancelled and engine.inspect("isum-1")["state"] == "failed"
    stores[0].close()
    assert code_of(lambda: isum.load_result(tmp_path / "state", job_id="isum-1")) == "issue_summary_not_ready"


# ====================================================================================================== changed basis ================

@pytest.mark.parametrize("edit", [
    lambda w: w.issue.update(title="다른 제목"),
    lambda w: w.issue["mentions"][1].update(background=False),
    lambda w: w.issue["mentions"][0].update(evidenceIds=w.issue["mentions"][0]["evidenceIds"][1:]),
    lambda w: w.issue["mentions"].append({"mentionId": "m3", "background": False, "evidenceIds": [w.ev(S3)]})])
def test_a_changed_basis_stops_the_job_before_any_call_and_restoring_it_resumes(tmp_path, stores, edit):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    engine.freeze(submit())
    fixture = isum.Fixtures(author(world))
    original = copy.deepcopy(world.issue)
    edit(world)                      # title, a quote's context, a dropped quote, a quote that becomes a report quote: every one changes the pinned basis
    stopped = engine.resume("isum-1", fixture)
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "issue_summary_basis_changed" and stopped["calls"] == [] and rows(engine)["results"] == 0
    world.issue = original
    assert engine.resume("isum-1", fixture)["state"] == "ready"


def test_a_source_text_that_no_longer_matches_the_pinned_hashes_is_refused(tmp_path, stores):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    engine.freeze(submit())
    fixture = isum.Fixtures(author(world))
    world.text = world.text.replace("2026년", "2027년")
    stopped = engine.resume("isum-1", fixture)
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "issue_summary_quote_mismatch"
    assert stopped["calls"] == []


def test_a_job_binding_frozen_by_different_code_is_refused(tmp_path, stores, monkeypatch):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    engine.freeze(submit())
    monkeypatch.setattr(jev, "identity", lambda: h("a different verifier adapter"))
    stopped = engine.resume("isum-1", isum.Fixtures(author(world)))
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "job_binding_changed" and stopped["calls"] == []


def test_a_hand_edited_ledger_is_refused_by_every_reader(tmp_path, stores):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    out = engine.run(submit(), isum.Fixtures(author(world)))
    stores[0].close()
    database = tmp_path / "state" / "issue-summary.sqlite3"
    edited = sqlite3.connect(database, isolation_level=None)
    edited.execute("DROP TRIGGER immutable_results_update")
    edited.execute("UPDATE results SET body=? WHERE job_id='isum-1'", (canonical({"status": "available", "text": "forged"}),))
    edited.close()
    assert code_of(lambda: isum.load_result(tmp_path / "state", job_id="isum-1")) == "issue_summary_state_invalid"
    reader = isum.Store(tmp_path / "state", mode="read")
    stores.append(reader)
    assert code_of(lambda: isum.Engine(reader, None).inspect("isum-1")) == "issue_summary_state_invalid" and out["state"] == "ready"


@pytest.mark.parametrize("statement", [
    "UPDATE results SET outcome='verifier-hold'", "DELETE FROM results", "UPDATE meta SET value='x'", "DELETE FROM calls", "UPDATE calls SET request_digest='x'",
    "UPDATE calls SET response='{}'", "UPDATE jobs SET input_digest='x'", "UPDATE jobs SET binding='x'", "UPDATE jobs SET request='x'", "DELETE FROM jobs",
    "UPDATE jobs SET state='queued'", "UPDATE jobs SET failure='x'"])
def test_the_ledger_refuses_every_rewrite_of_a_finished_job(tmp_path, stores, statement):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    engine.run(submit(), isum.Fixtures(author(world)))
    with pytest.raises(sqlite3.DatabaseError, match="immutable|terminal"):
        engine.store.db.execute(statement)


# ======================================================================================================= rights ======================

def test_a_revoked_source_stops_a_replay_job_before_it_records_anything_and_restoring_it_resumes(tmp_path, stores):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    engine.freeze(submit())
    fixture = isum.Fixtures(author(world))
    world.fail = "source_unauthorized"
    stopped = engine.resume("isum-1", fixture)
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "source_unauthorized" and stopped["calls"] == [] and stopped["result"] is None
    world.fail = None
    assert engine.resume("isum-1", fixture)["state"] == "ready"


def test_a_source_revoked_before_completion_leaves_no_result_and_the_stored_responses_finish_it_without_a_fixture(tmp_path, stores):
    world = World()
    engine = engine_for(tmp_path, stores, world)
    engine.freeze(submit())
    world.hook = lambda: setattr(world, "fail", "source_unauthorized") if rows(engine)["calls"] == 2 else None
    stopped = engine.resume("isum-1", isum.Fixtures(author(world)))
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "source_unauthorized" and stopped["result"] is None
    assert rows(engine) == {"jobs": 1, "calls": 2, "results": 0, "refusals": 0}
    world.hook, world.fail = None, None
    done = engine.resume("isum-1", isum.Fixtures(None))
    assert done["state"] == "ready" and done["usage"]["replayCalls"] == 2 and rows(engine)["calls"] == 2


# ========================================================================================================= live ======================

class Provider:
    """The fake provider: answers the generation (chat) and verification (Jev) wires; `chat`/`jev` override the outcome of one wire."""

    def __init__(self, world: World, winners: dict | None = None, on_chat=None):
        self.world, self.winners, self.on_chat, self.chat, self.jev, self.on_jev = world, winners or {}, on_chat, None, None, None

    def __call__(self, request: httpx.Request):
        body = json.loads(request.content)
        if request.url.path.endswith("/chat/completions"):
            if self.on_chat:
                self.on_chat()
            if self.chat is not None:
                return self.chat(request)
            quotes = json.loads(body["messages"][1]["content"])["input"]["quotes"]
            label = {q["text"]: q["id"] for q in quotes}
            return json_response(openai_reply({"claims": [{"text": CLAIM1, "quoteIds": [label[S1], label[S2]]}, {"text": CLAIM2, "quoteIds": [label[S3]]}]}))
        if self.jev is not None:
            return self.jev(request)
        if self.on_jev:
            self.on_jev()
        answers = {key: choice(self.winners.get(key, "supported" if "supported" in list(q["criteria"]) else "absent"), list(q["criteria"]))
                   for key, q in body["questions"].items()}
        return json_response({"model": "jev-1.14.0", "answers": answers, "usage": {"input_tokens": 1000, "output_tokens": 0}})


def live_setup(monkeypatch, tmp_path, stores, provider_for=None, **env):
    environment(monkeypatch, tmp_path, **env)
    world = World(execution=LIVE)
    provider = (provider_for or Provider)(world)
    fake = Fake(provider)
    factory = lambda need_send: LiveRuntime.from_env(need_send=need_send, transport=fake.transport, family=ISSUE_SUMMARY)  # noqa: E731
    return world, provider, fake, engine_for(tmp_path, stores, world, factory), factory


LIVE_REQUEST = {"mode": "live"}


def test_a_live_job_freezes_with_no_call_then_runs_two_calls_with_rights_for_every_document(monkeypatch, tmp_path, stores):
    world, provider, fake, engine, factory = live_setup(monkeypatch, tmp_path, stores)
    engine.freeze(submit(**LIVE_REQUEST))
    queued = engine.inspect("isum-1")
    assert queued["state"] == "queued" and fake.requests == [] and queued["usage"]["executionMode"] == "live" and world.sources.log == []
    runtime = LiveRuntime.from_env(need_send=False, family=ISSUE_SUMMARY)
    assert json.loads(engine.store.one("SELECT binding FROM jobs")["binding"])["runtime"] == runtime.binding()
    out = engine.resume("isum-1", isum.Fixtures(None))
    assert out["state"] == "ready" and out["result"]["outcome"] == "available" and len(fake.requests) == 2
    assert [r.url.path.rsplit("/", 1)[-1] for r in fake.requests] == ["completions", "systemone"]
    assert fake.requests[0].headers["Authorization"] == "Bearer " + OPENAI_KEY and fake.requests[1].headers["Authorization"] == "Bearer " + JEV_KEY
    assert out["usage"]["providerCalls"] == 2 and out["usage"]["modelCalls"] == 2 and out["usage"]["replayCalls"] == 0 and all("cost" in call for call in out["calls"])
    summary = out["result"]["summary"]
    assert summary["producer"] == {"kind": "provider", "model": "gpt-6-luna", "reasoningEffort": "high", "promptVersion": prompts.SPECS["issue-summary"].prompt_version,
                                   "schemaDigest": prompts.SPECS["issue-summary"].schema_digest, "runtimeIdentity": runtime.binding()["identity"]}
    assert summary["verifier"] == {"kind": "independent-verifier", "model": "jev-1.14.0", "adapterIdentity": jev.identity(),
                                   "requestDigest": digest(json.loads(fake.requests[1].content))}
    c.check_summary(world.issue, summary, world.basis(), LIVE)
    # Rights were checked for the document under BOTH purposes and their own recipients, before each send and again after each reply.
    purposes = {(purpose, recipient) for _, purpose, recipient in world.sources.log}
    assert purposes == {("pipeline:issue-summary", runtime.recipient("issue-summary")), ("pipeline:verify-issue-summary", runtime.recipient("verify-issue-summary"))}
    assert [p for _, p, _ in world.sources.log].count("pipeline:issue-summary") >= 3
    # Only the title and the quotes leave the process: no internal id; the verifier never sees the title.
    chat, verify = fake.requests[0].content.decode(), fake.requests[1].content.decode()
    assert TITLE in chat and all(s in chat for s in (S1, S2, S3)) and TITLE not in verify
    for sent in (chat, verify):
        assert not any(token in sent for token in (*world.evidence, "doc-1", "isum-1", "issue:one", world.article, world.version, world.document_version))
    assert engine.resume("isum-1", isum.Fixtures(None)) == out and len(fake.requests) == 2


def test_the_raw_receipt_is_stored_before_anything_decodes_it(monkeypatch, tmp_path, stores):
    world, provider, fake, engine, factory = live_setup(monkeypatch, tmp_path, stores)
    decoded, seen = [], {}
    answer = LiveRuntime.answer
    monkeypatch.setattr(LiveRuntime, "answer", lambda self, stage, receipt: decoded.append(stage) or answer(self, stage, receipt))

    def spy(self, stage):
        row = self.store.one("SELECT state, response IS NOT NULL AS has, response_digest FROM calls WHERE stage=?", (stage,))
        seen[stage] = (row["state"], row["has"], row["response_digest"] is not None, list(decoded))

    monkeypatch.setattr(isum.Engine, "_after_receipt", spy)
    out = engine.run(submit(**LIVE_REQUEST), isum.Fixtures(None))
    assert out["state"] == "ready"
    assert seen == {"issue-summary": ("received", 1, True, []), "verify-issue-summary": ("received", 1, True, ["issue-summary"])}


def test_a_process_death_after_the_receipt_is_recovered_from_the_stored_receipt_with_no_resend(monkeypatch, tmp_path, stores):
    world, provider, fake, engine, factory = live_setup(monkeypatch, tmp_path, stores)

    def die(self, stage):
        raise Crash

    monkeypatch.setattr(isum.Engine, "_after_receipt", die)
    with pytest.raises(Crash):
        engine.run(submit(**LIVE_REQUEST), isum.Fixtures(None))
    assert len(fake.requests) == 1
    monkeypatch.undo()
    environment(monkeypatch, tmp_path)
    engine = reopen(tmp_path, stores, world, factory)
    assert engine.store.one("SELECT state FROM calls")["state"] == "received"
    out = engine.resume("isum-1", isum.Fixtures(None))
    assert out["state"] == "ready" and out["result"]["outcome"] == "available"
    assert len(fake.requests) == 2 and [r.url.path.rsplit("/", 1)[-1] for r in fake.requests] == ["completions", "systemone"]


@pytest.mark.parametrize("seam", ["reserve", "silence"])
def test_a_started_call_without_a_receipt_is_unknown_and_never_resent(monkeypatch, tmp_path, stores, seam):
    world, provider, fake, engine, factory = live_setup(monkeypatch, tmp_path, stores)
    if seam == "silence":
        provider.chat = lambda request: httpx.ReadTimeout("no reply")
        out = engine.run(submit(**LIVE_REQUEST), isum.Fixtures(None))
        assert out["state"] == "failed" and out["failure"] == {"code": "provider_outcome_unknown"} and len(fake.requests) == 1
        assert out["usage"]["startedWithoutReceipt"] == 1 and out["usage"]["providerCalls"] == 1 and out["calls"][0]["state"] == "started" and out["result"] is None
        provider.chat = None
        assert engine.resume("isum-1", isum.Fixtures(None)) == out and len(fake.requests) == 1
    else:
        def die(self, stage):
            raise Crash

        monkeypatch.setattr(isum.Engine, "_after_reserve", die)
        with pytest.raises(Crash):
            engine.run(submit(**LIVE_REQUEST), isum.Fixtures(None))
        monkeypatch.undo()
        environment(monkeypatch, tmp_path)
        engine = reopen(tmp_path, stores, world, factory)
        out = engine.resume("isum-1", isum.Fixtures(None))
        assert out["state"] == "failed" and out["failure"] == {"code": "provider_outcome_unknown"} and fake.requests == []     # "may have been sent": never sent again
        assert out["usage"]["startedWithoutReceipt"] == 1
    again = reopen(tmp_path, stores, world, factory).resume("isum-1", isum.Fixtures(None))
    assert again["state"] == "failed" and again["failure"] == {"code": "provider_outcome_unknown"} and len(fake.requests) == (1 if seam == "silence" else 0)



def test_a_failed_job_cannot_be_frozen_into_a_handoff(tmp_path, stores, monkeypatch):
    world, provider, fake, engine, factory = live_setup(monkeypatch, tmp_path, stores)
    provider.chat = lambda request: httpx.ReadTimeout("no reply")
    assert engine.run(submit(**LIVE_REQUEST), isum.Fixtures(None))["state"] == "failed"
    stores[0].close()
    assert code_of(lambda: isum.load_result(tmp_path / "state", job_id="isum-1")) == "issue_summary_not_ready"


def test_missing_model_send_rights_mean_no_send_and_no_reservation(monkeypatch, tmp_path, stores):
    world, provider, fake, engine, factory = live_setup(monkeypatch, tmp_path, stores)
    engine.freeze(submit(**LIVE_REQUEST))
    world.sources.denied = "source_purpose_or_recipient_denied"
    out = engine.resume("isum-1", isum.Fixtures(None))
    assert out["state"] == "stopped" and out["failure"]["code"] == "source_purpose_or_recipient_denied" and fake.requests == [] and out["calls"] == []
    assert world.sources.log[0][1] == "pipeline:issue-summary"
    world.sources.denied = None
    assert engine.resume("isum-1", isum.Fixtures(None))["state"] == "ready" and len(fake.requests) == 2


def test_rights_missing_for_the_verifier_purpose_stop_between_the_two_calls_and_the_generation_is_never_resent(monkeypatch, tmp_path, stores):
    world, provider, fake, engine, factory = live_setup(monkeypatch, tmp_path, stores)
    world.sources.denied_purposes = {"pipeline:verify-issue-summary"}
    stopped = engine.run(submit(**LIVE_REQUEST), isum.Fixtures(None))
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "source_purpose_or_recipient_denied" and len(fake.requests) == 1
    assert [c_["stage"] for c_ in stopped["calls"]] == ["issue-summary"] and stopped["phase"] == "verify"
    world.sources.denied_purposes = set()
    done = engine.resume("isum-1", isum.Fixtures(None))
    assert done["state"] == "ready" and [r.url.path.rsplit("/", 1)[-1] for r in fake.requests] == ["completions", "systemone"]


def test_rights_revoked_while_the_provider_answers_keep_the_receipt_but_the_reply_is_not_used(monkeypatch, tmp_path, stores):
    world, provider, fake, engine, factory = live_setup(monkeypatch, tmp_path, stores)
    provider.on_chat = lambda: setattr(world.sources, "denied", "source_unauthorized")
    stopped = engine.run(submit(**LIVE_REQUEST), isum.Fixtures(None))
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "source_unauthorized" and stopped["result"] is None and len(fake.requests) == 1
    assert [(c_["stage"], c_["state"]) for c_ in stopped["calls"]] == [("issue-summary", "received")]
    provider.on_chat, world.sources.denied = None, None
    done = engine.resume("isum-1", isum.Fixtures(None))
    assert done["state"] == "ready" and [r.url.path.rsplit("/", 1)[-1] for r in fake.requests] == ["completions", "systemone"]




def test_generation_rights_revoked_while_the_verifier_answers_block_the_result_and_both_stages_are_checked_last(monkeypatch, tmp_path, stores):
    world, provider, fake, engine, factory = live_setup(monkeypatch, tmp_path, stores)
    provider.on_jev = lambda: setattr(world.sources, "denied_purposes", {"pipeline:issue-summary"})
    stopped = engine.run(submit(**LIVE_REQUEST), isum.Fixtures(None))
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "source_purpose_or_recipient_denied" and stopped["result"] is None and len(fake.requests) == 2
    assert [(c_["stage"], c_["state"]) for c_ in stopped["calls"]] == [("issue-summary", "received"), ("verify-issue-summary", "received")] and rows(engine)["results"] == 0
    provider.on_jev, world.sources.denied_purposes = None, set()
    done = engine.resume("isum-1", isum.Fixtures(None))
    assert done["state"] == "ready" and len(fake.requests) == 2           # both receipts are reused: nothing is sent again


def test_model_send_rights_revoked_after_a_successful_run_do_not_withhold_the_stored_result(monkeypatch, tmp_path, stores):
    world, provider, fake, engine, factory = live_setup(monkeypatch, tmp_path, stores)
    out = engine.run(submit(**LIVE_REQUEST), isum.Fixtures(None))
    assert out["state"] == "ready" and out["delivery"]["status"] == "current" and len(fake.requests) == 2
    checked = len(world.sources.log)
    world.sources.denied, world.sources.denied_purposes = "source_purpose_or_recipient_denied", {"pipeline:issue-summary", "pipeline:verify-issue-summary"}
    # Model-send rights gate the send, the reply and the completion; reading an immutable result needs the source READ/quote rights and the frozen basis only.
    assert engine.inspect("isum-1") == out and engine.resume("isum-1", isum.Fixtures(None)) == out
    assert len(world.sources.log) == checked and len(fake.requests) == 2
    world.fail = "source_unauthorized"                                       # read rights gone: withheld, still no call
    hidden = engine.inspect("isum-1")
    assert hidden["state"] == "ready" and hidden["delivery"] == {"status": "withheld", "code": "source_unauthorized"} and hidden["result"] is None and len(fake.requests) == 2


def test_an_exhausted_budget_never_opens_a_socket_and_is_recorded_as_a_refusal(monkeypatch, tmp_path, stores):
    world, provider, fake, engine, factory = live_setup(monkeypatch, tmp_path, stores, **{live.MAX_CALLS_VAR: "1"})
    out = engine.run(submit(**LIVE_REQUEST), isum.Fixtures(None))
    assert out["state"] == "stopped" and out["failure"]["code"] == "live_budget_exhausted_calls" and len(fake.requests) == 1
    assert [(c_["stage"], c_["state"], c_["verdict"]) for c_ in out["calls"]] == [("issue-summary", "received", None), ("verify-issue-summary", "refused", "live_budget_exhausted_calls")]
    assert out["usage"]["startedWithoutReceipt"] == 0 and out["usage"]["providerCalls"] == 1


def test_a_changed_live_configuration_cannot_resume_a_frozen_job(monkeypatch, tmp_path, stores):
    world, provider, fake, engine, factory = live_setup(monkeypatch, tmp_path, stores)
    engine.freeze(submit(**LIVE_REQUEST))
    environment(monkeypatch, tmp_path, **{live.EFFORT_VAR: "low"})
    out = engine.resume("isum-1", isum.Fixtures(None))
    assert out["state"] == "stopped" and out["failure"]["code"] == "live_config_changed" and fake.requests == []


def test_a_live_job_takes_no_fixture_and_a_ledger_never_holds_a_key(monkeypatch, tmp_path, stores):
    world, provider, fake, engine, factory = live_setup(monkeypatch, tmp_path, stores)
    engine.freeze(submit(**LIVE_REQUEST))
    assert code_of(lambda: engine.resume("isum-1", isum.Fixtures(author(world)))) == "fixture_not_allowed" and fake.requests == []
    engine.resume("isum-1", isum.Fixtures(None))
    engine.store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    for path in sorted((tmp_path / "state").iterdir()):
        assert OPENAI_KEY.encode() not in path.read_bytes() and JEV_KEY.encode() not in path.read_bytes(), path.name


def test_a_live_submit_needs_the_live_gate_and_fits_the_request_limit_before_any_row_exists(monkeypatch, tmp_path, stores):
    world, provider, fake, engine, factory = live_setup(monkeypatch, tmp_path, stores)
    monkeypatch.delenv(live.GATE)
    assert code_of(lambda: engine.freeze(submit(**LIVE_REQUEST))) == "live_not_enabled" and rows(engine)["jobs"] == 0
    environment(monkeypatch, tmp_path)
    huge = World(["가" * 120_000, "나다라 짧은 문장이다."], execution=LIVE)
    other = reopen(tmp_path, stores, huge, factory, name="state-huge")
    assert code_of(lambda: other.freeze(submit(**LIVE_REQUEST))) == "issue_summary_input_too_large" and rows(other)["jobs"] == 0 and fake.requests == []


@pytest.mark.parametrize("which,make,outcome,failure", [
    ("chat", lambda request: json_response(openai_reply("this is not json")), "producer-invalid", None),
    ("chat", lambda request: json_response(openai_reply("", refusal="declined")), "producer-invalid", None),
    ("chat", lambda request: json_response(openai_reply({"claims": []}, finish="length")), "producer-invalid", None),
    ("chat", lambda request: json_response({"error": "simulated"}, 500), None, "live_http_500"),
    ("jev", lambda request: json_response({"model": "jev-1.14.0", "answers": {}}), None, "verification_unavailable"),
    ("jev", lambda request: json_response({"error": "simulated"}, 503), None, "verification_unavailable")])
def test_an_unusable_receipt_is_a_permanent_outcome_and_another_call_never_repairs_it(monkeypatch, tmp_path, stores, which, make, outcome, failure):
    world, provider, fake, engine, factory = live_setup(monkeypatch, tmp_path, stores)
    setattr(provider, which, make)
    out = engine.run(submit(**LIVE_REQUEST), isum.Fixtures(None))
    if outcome:
        assert out["state"] == "ready" and out["result"]["outcome"] == outcome and len(fake.requests) == 1          # the verifier is never asked about an invalid producer
        c.check_summary(world.issue, out["result"]["summary"], world.basis(), LIVE)
    else:
        assert out["state"] == "failed" and out["failure"]["code"] == failure and out["result"] is None
    sent = len(fake.requests)
    setattr(provider, which, None)
    assert engine.resume("isum-1", isum.Fixtures(None)) == out and len(fake.requests) == sent


def test_live_verifier_decisions_map_to_the_same_outcomes_as_replay(monkeypatch, tmp_path, stores):
    world, provider, fake, engine, factory = live_setup(monkeypatch, tmp_path, stores)
    provider.winners = {"claim-1": "insufficient"}
    hold = engine.run(submit(**LIVE_REQUEST), isum.Fixtures(None))
    assert hold["state"] == "ready" and hold["result"]["outcome"] == "verifier-hold" and len(fake.requests) == 2
    provider.winners = {"claim-0": "contradicted"}
    second = engine_for(tmp_path, stores, world, factory, name="state-2")            # the same input is a duplicate inside one ledger: another ledger, another run
    reject = second.run(submit(**LIVE_REQUEST), isum.Fixtures(None))
    assert reject["state"] == "ready" and reject["result"]["outcome"] == "verifier-reject" and len(fake.requests) == 4


# ========================================================================================================== cli =====================

def run_cli(monkeypatch, capsys, argv: list[str], stdin: bytes = b"") -> tuple[int, dict]:
    monkeypatch.setattr(sys, "argv", ["zoop-ai-issue-summary", *argv])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=SimpleNamespace(read=lambda n=-1: stdin[:n] if n >= 0 else stdin)))
    status = cli.main()
    return status, json.loads(capsys.readouterr().out)


def test_the_cli_offline_binding_is_keyless_and_the_family_has_exactly_two_stages(monkeypatch, tmp_path, capsys):
    environment(monkeypatch, tmp_path, **{live.OPENAI_KEY_VAR: None, live.JEV_KEY_VAR: None})
    status, out = run_cli(monkeypatch, capsys, ["live-binding"])
    assert status == 0 and out["schemaVersion"] == "zoop-issue-summary-1" and out["bindingDigest"] == digest(out["binding"])
    assert out["binding"]["version"] == "zoop-issue-summary-runtime-1" and set(out["binding"]["stages"]) == {"issue-summary", "verify-issue-summary"}
    assert OPENAI_KEY not in json.dumps(out) and JEV_KEY not in json.dumps(out)
    status, out = run_cli(monkeypatch, capsys, ["live-binding", "--state-dir", str(tmp_path / "s")])
    assert status == 2 and out["error"]["code"] == "input_or_configuration_invalid"


def source_flags(root: Path) -> list[str]:
    return ["--relation-state-dir", str(root / "r"), "--extraction-state-dir", str(root / "e"), "--ingestion-state-dir", str(root / "i"), "--sources", str(root / "s.json"),
            "--canonical", str(root / "c.json"), "--decisions", str(root / "d.json"), "--bindings", str(root / "b.json")]


def test_the_cli_refuses_inconsistent_arguments_before_touching_anything(monkeypatch, tmp_path, capsys):
    selector = json.dumps({"schemaVersion": "zoop-issue-summary-1", "jobId": "isum-1"}).encode()
    flags, state = source_flags(tmp_path), str(tmp_path / "absent")
    status, out = run_cli(monkeypatch, capsys, ["inspect", "--state-dir", str(tmp_path / "s"), "--sources", str(tmp_path / "x")], selector)
    assert status == 2 and out["error"]["code"] == "input_or_configuration_invalid"                 # a partial set of source flags
    status, out = run_cli(monkeypatch, capsys, ["inspect", "--state-dir", state], selector)
    assert status == 2 and out["error"]["code"] == "input_or_configuration_invalid"                 # readers are sourced too: the result is shown only while the sources prove
    status, out = run_cli(monkeypatch, capsys, ["submit", "--state-dir", str(tmp_path / "s")], json.dumps(REQUEST).encode())
    assert status == 2 and out["error"]["code"] == "input_or_configuration_invalid"
    status, out = run_cli(monkeypatch, capsys, ["inspect", "--state-dir", state, *flags, "--fixture", str(tmp_path / "f")], selector)
    assert status == 2 and out["error"]["code"] == "fixture_not_allowed"
    status, out = run_cli(monkeypatch, capsys, ["inspect", "--state-dir", state, *flags], selector)
    assert status == 2 and out["error"]["code"] == "issue_summary_state_missing" and not (tmp_path / "absent").exists()
    status, out = run_cli(monkeypatch, capsys, ["export", "--state-dir", state, *flags], b'{"schemaVersion": "wrong"}')
    assert status == 2 and out["error"]["code"] == "input_or_configuration_invalid"
    status, out = run_cli(monkeypatch, capsys, ["cancel", "--state-dir", state, "--sources", str(tmp_path / "x")], selector)
    assert status == 2 and out["error"]["code"] == "input_or_configuration_invalid"
    status, out = run_cli(monkeypatch, capsys, ["cancel", "--state-dir", state], selector)
    assert status == 2 and out["error"]["code"] == "issue_summary_state_missing" and not (tmp_path / "absent").exists()       # a writer that never creates a ledger
