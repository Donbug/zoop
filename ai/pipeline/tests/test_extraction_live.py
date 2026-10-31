"""Live S2 behavior through the REAL native live runtime (request building, shared budget, receipt, strict decode) against an authored provider simulator.

The simulator is a deterministic stand-in for the HTTP peer only; it is not an AI and these tests make no network call and no paid call. They pin the
contract of the live path: truthful provenance, a frozen runtime binding, per-document model-send rights at reserve/send/receipt, one request per call slot,
a durable raw receipt before parsing, reconciling (never resending) after an unknown outcome, and recovery from stored receipts without environment or key.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3

import httpx
import pytest
from pydantic import ValidationError

from scripts.extraction_smoke import (FAKE_KEYS, LIVE_ENV_NAMES, Q3, Q3B, LiveWorld, chat_reply, loopback_smoke, simulate, simulator_env)
from zoop_ai_pipeline import extraction_replay as analysis
from zoop_ai_pipeline.extraction import Extractor, Fixtures, LiveAccess, Sources, Store
from zoop_ai_pipeline.extraction_contracts import ExtractionFailure, ObservationRef, Provenance, Submit
from zoop_ai_pipeline.ingestion_contracts import Authority, IngestionFailure
from zoop_ai_pipeline.live_budget import Budget, nano_from_usd
from zoop_ai_pipeline.live_runtime import LiveRuntime

NONE = Fixtures(None, None)


class Provider:
    """In-process HTTP peer of the live runtime. `mode`: ok | timeout | http500 | garbage | ungrounded. `after` runs while the reply is produced."""

    def __init__(self):
        self.requests, self.auth, self.mode, self.after = [], [], "ok", None

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        self.auth.append(request.headers.get("authorization"))
        if self.mode == "timeout":
            raise httpx.ReadTimeout("simulated provider silence")
        if self.mode == "http500":
            return httpx.Response(500, json={"error": {"message": "simulated"}})
        if self.mode == "garbage":
            return httpx.Response(200, json=chat_reply("this is not json"))
        reply = simulate(body)
        if self.mode == "ungrounded":
            answer = json.loads(reply["choices"][0]["message"]["content"])
            answer["mentions"][0]["evidence"][0]["segmentId"] = "q-unknown"
            reply = chat_reply(json.dumps(answer, ensure_ascii=False))
        if self.after is not None:
            self.after()
        return httpx.Response(200, json=reply)

    def access(self, **wrap) -> LiveAccess:
        def from_env(need_send=False):
            runtime = LiveRuntime.from_env(need_send=need_send, transport=httpx.MockTransport(self.handler))
            return wrap["sender"](runtime) if need_send and "sender" in wrap else runtime
        return LiveAccess(from_env=from_env)


def boom(*args, **kwargs):
    raise AssertionError("the live runtime/environment must not be touched here")


NO_LIVE = LiveAccess(from_env=boom, from_binding=boom)


@pytest.fixture
def lw(tmp_path, monkeypatch):
    env = simulator_env("https://api.openai.com/v1", tmp_path / "budget")
    for name in LIVE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    world = LiveWorld(tmp_path / "world", env)
    world.provider = Provider()
    world.budget = Budget(tmp_path / "budget", nano_from_usd(env["ZOOP_AI_PIPELINE_LIVE_MAX_USD"]), int(env["ZOOP_AI_PIPELINE_LIVE_MAX_CALLS"]))
    return world


class SpySources(Sources):
    """Records every export together with the model-send check it carried (None for the ordinary read + quote-display export)."""

    def __init__(self, *args):
        super().__init__(*args)
        self.exports = []

    def export(self, ref, *, send=None):
        self.exports.append((ref.document_id, send))
        return super().export(ref, send=send)


@contextlib.contextmanager
def session(w, live, *, spy=False):
    store = Store(w.kit.root / "extraction", w.kit.root / "ingestion")
    try:
        sources = (SpySources if spy else Sources)(w.kit.root / "ingestion", Authority(w.kit.registry_path))
        yield Extractor(store, sources, live)
    finally:
        store.close()


def go(w, live, job, *, snapshot=True, topic=True, initial_only=False, spy=False):
    """Freeze + resume one live job in a fresh process-equivalent session (new Authority/registry read)."""
    with session(w, live, spy=spy) as ex:
        request = Submit.model_validate(w.request(job, snapshot=snapshot, topic=topic))
        ex.freeze(request, NONE)
        return ex.resume(job, NONE, initial_only=initial_only)


def resume(w, live, job, **options):
    with session(w, live) as ex:
        return ex.resume(job, NONE, **options)


def stored_calls(w):
    db = sqlite3.connect(w.kit.root / "extraction" / "extraction.sqlite3")
    try:
        return db.execute("SELECT stage,state,verdict,response FROM calls ORDER BY started_at,attempt_id").fetchall()
    finally:
        db.close()


def dispatch_marks(w):
    db = sqlite3.connect(w.kit.root / "extraction" / "extraction.sqlite3")
    try:
        return {row[0] for row in db.execute("SELECT key FROM meta WHERE key LIKE 'initial-dispatch:%'")}
    finally:
        db.close()


def job_ids(w):
    db = sqlite3.connect(w.kit.root / "extraction" / "extraction.sqlite3")
    try:
        return {row[0] for row in db.execute("SELECT job_id FROM jobs")}
    finally:
        db.close()


def ledger(w):
    db = sqlite3.connect(f"file:{w.kit.root / 'extraction' / 'extraction.sqlite3'}?mode=ro&immutable=1", uri=True)
    try:
        return hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()
    finally:
        db.close()


def set_operations(w, operations, **grant_changes):
    grant = w.kit.registry["sources"][0]["grant"]
    grant["allowedOperations"] = list(operations)
    grant.update(grant_changes)
    w.kit.save_registry()


FULL = ["read", "store", "quote-display", "model-send"]


# ------------------------------------------------------------------------------------------------ provenance / authority

def test_provenance_pairs_execution_mode_with_recording_kind_and_the_replay_wire_is_unchanged():
    replay = {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"}
    live = {"sourceKind": "actual", "executionMode": "live", "recordingKind": "provider"}
    assert Provenance.model_validate(replay).wire() == replay and Provenance.model_validate(live).wire() == live
    for bad in ({**replay, "recordingKind": "provider"}, {**live, "recordingKind": "authored-test"}, {**live, "executionMode": "other"}):
        with pytest.raises(ValidationError):
            Provenance.model_validate(bad)


def test_model_send_authority_needs_operation_purpose_and_recipient_and_infers_nothing(lw, tmp_path):
    runtime, path = lw.runtime, lw.kit.registry_path
    purpose, recipient = runtime.purpose("extract"), runtime.recipient("extract")
    ordinary = ("read", "quote-display")
    assert Authority(path).check("synthetic-source", "body", ordinary, purpose=purpose, recipient=recipient)[0].source_id == "synthetic-source"
    with pytest.raises(ValueError):
        Authority(path).check("synthetic-source", "body", ordinary, purpose=purpose)

    def denied(code, **kwargs):
        with pytest.raises(IngestionFailure) as raised:
            Authority(path).check("synthetic-source", "body", ordinary, **kwargs)
        assert raised.value.code == code

    denied("source_purpose_or_recipient_denied", purpose="pipeline:other", recipient=recipient)
    denied("source_purpose_or_recipient_denied", purpose=purpose, recipient="openai-compatible:other")
    set_operations(lw, FULL, recipients=[])
    denied("source_purpose_or_recipient_denied", purpose=purpose, recipient=recipient)  # an empty list authorizes nothing
    set_operations(lw, ["read", "store", "quote-display"], recipients=[recipient])
    denied("source_operation_denied", purpose=purpose, recipient=recipient)
    assert Authority(path).check("synthetic-source", "body", ordinary)  # replay/ingestion never needed model-send
    set_operations(lw, FULL, recipients=[recipient], enabled=False)
    denied("source_unauthorized", purpose=purpose, recipient=recipient)
    set_operations(lw, FULL, recipients=[recipient], enabled=True)

    registry = json.loads(path.read_text())
    source = registry["sources"][0]
    for name in ("Naver_Search", "naver-developers-search"):
        other = {**registry, "sources": [{**source, "sourceId": name, "grant": {**source["grant"], "sourceId": name}}]}
        copy = tmp_path / f"{name}.json"
        copy.write_text(json.dumps(other))
        assert Authority(copy).check(name, "body", ordinary)  # still readable
        with pytest.raises(IngestionFailure) as raised:
            Authority(copy).check(name, "body", ordinary, purpose=purpose, recipient=recipient)
        assert raised.value.code == "naver_search_ai_prohibited"


def test_sources_authorize_model_send_is_the_per_document_check_other_stages_use(lw):
    runtime = lw.runtime
    sources = Sources(lw.kit.root / "ingestion", Authority(lw.kit.registry_path))
    ref = ObservationRef.model_validate({k: lw.a1[k] for k in ("roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion")})
    assert sources.authorize_model_send(ref, runtime.purpose("compare"), runtime.recipient("compare")) is None
    with pytest.raises(ExtractionFailure, match="source_purpose_or_recipient_denied"):
        sources.authorize_model_send(ref, "pipeline:relation", runtime.recipient("compare"))


# ------------------------------------------------------------------------------------------------ the live job

def test_live_job_extracts_compares_and_groups_through_the_runtime_with_per_document_rights(lw):
    w, p = lw, lw.provider
    out = go(w, p.access(), "job-main", spy=False)
    runtime = w.runtime
    assert out["state"] == "ready" and out["provenance"] == {"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"}
    assert [json.loads(b["messages"][1]["content"])["stage"] for b in p.requests] == ["extract", "compare", "topic"]
    assert p.auth == ["Bearer " + FAKE_KEYS["ZOOP_AI_API_KEY"]] * 3 and all(b["model"] == "gpt-6-luna" and b["reasoning_effort"] == "high" for b in p.requests)

    # Delivered facts: grounded, never approved, exact citations, replay-shaped result with a live binding and truthful usage.
    candidate = out["eventCandidates"][0]
    assert candidate["approved"] is False and candidate["state"] == "candidate" and candidate["disposition"]["status"] == "same-event-candidate"
    assert len(candidate["comparisons"][0]["citations"]) == 2 and len(out["topicCandidates"]) == 1 and out["topicCandidates"][0]["approved"] is False
    texts = w.documents()
    for citation in candidate["citations"] + candidate["comparisons"][0]["citations"] + out["topicCandidates"][0]["citations"]:
        assert texts[(citation["documentId"], citation["documentVersion"])][citation["start"]:citation["end"]] == citation["quote"]
    live = out["binding"]["live"]
    assert "replay" not in out["binding"] and live["runtime"] == runtime.binding() and live["bindingDigest"] == runtime.binding()["identity"]
    assert out["binding"]["adapter"]["version"] == "zoop-extraction-native-live-2"
    usage = out["usage"]
    assert (usage["executionMode"], usage["providerCalls"], usage["receivedCalls"], usage["startedWithoutReceipt"], usage["unsentCalls"], usage["replayCalls"]) == ("live", 3, 3, 0, 0, 0)
    assert (usage["inputTokens"], usage["outputTokens"], usage["reasoningTokens"], usage["paidModelCalls"]) == (3600, 900, 360, 3)
    assert usage["estimatedUsd"] is not None and float(usage["estimatedUsd"]) > 0 and float(usage["chargedUsd"]) > 0
    assert [(c["stage"], c["state"], c["httpStatus"], c["recipient"], c["purpose"]) for c in out["calls"]] == [
        (s, "received", 200, runtime.recipient(s), runtime.purpose(s)) for s in ("extract", "compare", "topic")]
    snapshot = w.budget.snapshot()
    assert snapshot["calls"] == 3 and snapshot["states"] == {"settled": 3}, "every call was settled against the shared budget"

    # The outbound payloads are sanitized projections of exactly the documents that are sent for that stage.
    users = [b["messages"][1]["content"] for b in p.requests]
    extract, compare, topic = users
    for text in users:
        assert not any(leak in text for leak in ("example.invalid", "allow_model_send", "publisher", "origin_id", "withdrawn", "operator-grant", "synthetic"))
    assert Q3B in extract and Q3 not in extract, "extract sends only the incoming document"
    assert Q3 in compare and Q3B in compare and Q3 in topic, "compare and topic send the snapshot member's text too"

    # inspect / export / a repeated resume need no runtime, environment or key, and never call the provider again.
    with session(w, NO_LIVE) as ex:
        assert ex.inspect("job-main") == out
        submit, delivered = ex.export("job-main")
        assert delivered == out and submit.provenance.execution_mode == "live"
        assert ex.resume("job-main", NONE) == out
    assert len(p.requests) == 3


def test_every_sent_document_is_authorized_for_that_stage_purpose_and_recipient(lw):
    w, p = lw, lw.provider
    with session(w, p.access(), spy=True) as ex:
        ex.freeze(Submit.model_validate(w.request("job-spy")), NONE)
        assert ex.resume("job-spy", NONE)["state"] == "ready"
        checks = [(doc, send) for doc, send in ex.sources.exports if send is not None]
    runtime = w.runtime
    by_stage = {s: {doc for doc, send in checks if send == (runtime.purpose(s), runtime.recipient(s))} for s in ("extract", "compare", "topic")}
    assert by_stage["extract"] == {w.a2["documentId"]}, "only the incoming document is sent for extraction"
    assert by_stage["compare"] == by_stage["topic"] == {w.a1["documentId"], w.a2["documentId"]}, "the snapshot member's source needs model-send too"
    assert {send for _, send in checks} == {(runtime.purpose(s), runtime.recipient(s)) for s in ("extract", "compare", "topic")}


def test_live_freeze_binds_the_exact_runtime_and_refuses_fixtures_and_drift(lw, monkeypatch):
    w, p = lw, lw.provider
    request = Submit.model_validate(w.request("job-freeze"))
    with session(w, p.access()) as ex:
        with pytest.raises(ExtractionFailure, match="fixture_not_allowed"):
            ex.freeze(request, Fixtures(b"{}", None))
        ex.freeze(request, NONE)
        queued = ex.inspect("job-freeze")
        ex.freeze(request, NONE)
        assert ex.inspect("job-freeze") == queued
    assert queued["state"] == "queued" and queued["calls"] == [] and queued["usage"]["providerCalls"] == 0 and p.requests == []
    assert queued["binding"]["live"]["runtime"] == w.runtime.binding() and queued["binding"]["live"]["promptVersion"] == request.prompt_version
    assert queued["binding"]["live"]["analysisVersion"] == "live-" + w.runtime.binding()["identity"]
    stages = queued["binding"]["live"]["runtime"]["stages"]
    assert all(stages[s]["promptVersion"] and stages[s]["schemaDigest"] for s in ("extract", "compare", "topic"))
    with session(w, p.access()) as ex:
        with pytest.raises(ExtractionFailure, match="fixture_not_allowed"):
            ex.resume("job-freeze", Fixtures(b"{}", None))

    monkeypatch.setenv("ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT", "low")
    with session(w, p.access()) as ex:
        with pytest.raises(ExtractionFailure, match="job_input_conflict"):
            ex.freeze(request, NONE)
        stopped = ex.resume("job-freeze", NONE)
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "live_config_changed" and stopped["calls"] == [] and p.requests == []
    monkeypatch.delenv("ZOOP_AI_PIPELINE_LIVE_ENABLED")
    with session(w, p.access()) as ex:
        with pytest.raises(ExtractionFailure, match="live_not_enabled"):
            ex.freeze(Submit.model_validate(w.request("job-ungated")), NONE)
    assert "job-ungated" not in job_ids(w)


# ------------------------------------------------------------------------------------------------ rights and fence

def test_model_send_denial_before_reserve_stops_with_no_call_and_a_later_grant_resumes_it(lw):
    w, p = lw, lw.provider
    with session(w, p.access()) as ex:
        ex.freeze(Submit.model_validate(w.request("job-rights", snapshot=False, topic=False)), NONE)
    grant = w.kit.registry["sources"][0]["grant"]
    recipients = grant["recipients"]
    set_operations(w, ["read", "store", "quote-display"])
    denied = resume(w, p.access(), "job-rights")
    assert denied["state"] == "stopped" and denied["failure"]["code"] == "source_operation_denied" and denied["calls"] == [] and p.requests == []
    set_operations(w, FULL, recipients=[])
    assert resume(w, p.access(), "job-rights")["failure"]["code"] == "source_purpose_or_recipient_denied" and p.requests == []
    set_operations(w, FULL, recipients=recipients)
    done = resume(w, p.access(), "job-rights")
    assert done["state"] == "ready" and len(p.requests) == 1


def test_a_rights_change_between_reservation_and_send_sends_nothing_and_the_slot_stays_unsent(lw):
    w, p = lw, lw.provider

    class Flip:
        """The real runtime, except the registry changes right before the real send, i.e. after the budget reservation and inside the window `authorize` guards."""

        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def send(self, prepared, *, attempt_id, authorize):
            set_operations(w, ["read", "store", "quote-display"])
            return self.inner.send(prepared, attempt_id=attempt_id, authorize=authorize)

    out = go(w, p.access(sender=Flip), "job-window", snapshot=False, topic=False)
    assert out["state"] == "stopped" and out["failure"]["code"] == "registry_changed" and p.requests == []
    assert [(c["state"], c["verdict"]) for c in out["calls"]] == [("unsent", "registry_changed")]
    assert (out["usage"]["providerCalls"], out["usage"]["unsentCalls"], out["usage"]["startedWithoutReceipt"]) == (0, 1, 0)
    assert w.budget.snapshot()["calls"] == 0 and w.budget.snapshot()["chargedUsd"] == "0.000000000", "a refusal before the send releases the reservation"
    set_operations(w, FULL)
    again = resume(w, p.access(), "job-window")
    assert again["state"] == "stopped" and again["failure"]["code"] == "registry_changed" and p.requests == [], "a refused call slot is terminal: start a new job"


def test_rights_changing_after_the_receipt_withholds_delivery_but_the_stored_receipt_still_completes_the_job(lw):
    w, p = lw, lw.provider
    p.after = lambda: set_operations(w, ["read", "store", "quote-display"])
    out = go(w, p.access(), "job-after", snapshot=False, topic=False)
    p.after = None
    assert out["state"] == "stopped" and out["failure"]["code"] == "registry_changed" and len(p.requests) == 1
    assert [(c["state"], c["verdict"]) for c in out["calls"]] == [("received", None)], "the receipt is stored even though delivery is withheld"
    assert out["delivery"] == {"status": "withheld", "code": "registry_changed"} and "eventCandidates" not in out, "nothing is delivered after the rights vanished"
    assert json.loads(stored_calls(w)[0][3])["http"]["status"] == 200
    set_operations(w, FULL)
    done = resume(w, p.access(), "job-after")
    assert done["state"] == "ready" and len(p.requests) == 1 and len(done["eventCandidates"]) == 1, "the stored receipt is reused, never re-requested"


# ------------------------------------------------------------------------------------------------ outcomes

def test_provider_silence_is_reconciling_never_resent_and_its_usage_is_unknown(lw):
    w, p = lw, lw.provider
    p.mode = "timeout"
    out = go(w, p.access(), "job-silent", snapshot=False, topic=False)
    p.mode = "ok"
    assert out["state"] == "reconciling" and out["resumeMode"] == "reconcile_only" and out["failure"] == {"code": "live_response_unknown"} and len(p.requests) == 1
    assert [(c["state"], c["httpStatus"], c["usage"]) for c in out["calls"]] == [("started", None, None)]
    usage = out["usage"]
    assert (usage["providerCalls"], usage["startedWithoutReceipt"], usage["receivedCalls"]) == (1, 1, 0)
    assert usage["estimatedUsd"] is None and usage["chargedUsd"] is None and usage["inputTokens"] is None, "unknown is null, never zero"
    snapshot = w.budget.snapshot()
    assert snapshot["calls"] == 1 and snapshot["states"] == {"reserved": 1} and snapshot["chargedUsd"] != "0.000000000", "the reservation stays charged"
    before = ledger(w)
    assert resume(w, p.access(), "job-silent") == out and ledger(w) == before and len(p.requests) == 1
    with session(w, p.access()) as ex:
        cancelled = ex.cancel("job-silent")
    assert cancelled["state"] == "cancelled" and len(p.requests) == 1


@pytest.mark.parametrize("mode,code", [("garbage", "live_reply_not_json"), ("http500", "live_http_500"), ("ungrounded", "live_citation_reference_unknown")])
def test_an_unusable_reply_stays_a_durable_failed_receipt_and_is_never_repaired(lw, mode, code):
    w, p = lw, lw.provider
    p.mode = mode
    job = "job-" + mode
    out = go(w, p.access(), job, snapshot=False, topic=False)
    p.mode = "ok"
    assert out["state"] == "stopped" and out["failure"]["code"] == code and out["eventCandidates"] == []
    assert [(c["state"], c["verdict"], c["httpStatus"]) for c in out["calls"]] == [("received", code, 500 if mode == "http500" else 200)]
    stage, state, verdict, response = stored_calls(w)[-1]
    assert (stage, state, verdict) == ("extract", "received", code) and json.loads(response)["http"]["bodyText"], "the raw reply is stored before it was judged"
    assert len(p.requests) == 1 and w.budget.snapshot()["calls"] == 1
    before = stored_calls(w)
    assert resume(w, p.access(), job) == out and stored_calls(w) == before and len(p.requests) == 1


def test_stored_receipt_recovery_needs_neither_the_environment_nor_a_key_and_a_drifted_environment_cannot_send(lw, monkeypatch):
    w, p = lw, lw.provider
    original = analysis.parse_extraction

    def die(*args, **kwargs):
        monkeypatch.setattr(analysis, "parse_extraction", original)
        raise RuntimeError("the process died after the receipt was stored")

    monkeypatch.setattr(analysis, "parse_extraction", die)
    with pytest.raises(RuntimeError):
        go(w, p.access(), "job-recover", topic=False)
    assert [(row[0], row[1], row[2]) for row in stored_calls(w)] == [("extract", "received", None)] and len(p.requests) == 1

    saved = {name: os.environ[name] for name in LIVE_ENV_NAMES if name in os.environ}
    for name in LIVE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    # No gate, no key, no budget: the extract receipt decodes from the job's own frozen binding; the next stage needs a send and is refused before any reservation.
    gone = resume(w, LiveAccess(), "job-recover")
    assert gone["stages"]["extract"]["state"] == "complete" and gone["failure"]["code"] == "live_not_enabled" and len(p.requests) == 1
    assert len(gone["eventCandidates"]) == 1 and [c["stage"] for c in gone["calls"]] == ["extract"]

    for name, value in {**saved, "ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT": "low"}.items():
        monkeypatch.setenv(name, value)
    drifted = resume(w, p.access(), "job-recover")
    assert drifted["failure"]["code"] == "live_config_changed" and len(p.requests) == 1 and [c["stage"] for c in drifted["calls"]] == ["extract"]
    monkeypatch.setenv("ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT", saved["ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT"])
    finished = resume(w, p.access(), "job-recover")
    assert finished["state"] == "ready" and len(p.requests) == 2 and [c["stage"] for c in finished["calls"]] == ["extract", "compare"]


# ------------------------------------------------------------------------------------------------ dispatch / replay isolation

def test_the_automatic_dispatch_is_taken_once_atomically_and_explicit_recovery_is_separate(lw):
    w, p = lw, lw.provider
    with session(w, p.access()) as ex:
        ex.freeze(Submit.model_validate(w.request("job-once", snapshot=False, topic=False)), NONE)
        ex.freeze(Submit.model_validate(w.request("job-seen", snapshot=False, topic=False)), NONE)
        ex.freeze(Submit.model_validate(w.request("job-plain", snapshot=False, topic=False)), NONE)
    first = resume(w, p.access(), "job-once", initial_only=True)
    assert first["state"] == "ready" and len(p.requests) == 1
    before = ledger(w)
    with pytest.raises(ExtractionFailure, match="initial_dispatch_taken"):
        resume(w, p.access(), "job-once", initial_only=True)
    assert ledger(w) == before and len(p.requests) == 1, "a refused dispatch writes nothing"
    assert dispatch_marks(w) == {"initial-dispatch:job-once"}

    # A stopped job (rights denied at the first automatic dispatch) is never auto-dispatched again; the operator's plain resume is.
    set_operations(w, ["read", "store", "quote-display"])
    stopped = resume(w, p.access(), "job-seen", initial_only=True)
    assert stopped["failure"]["code"] == "source_operation_denied" and len(p.requests) == 1
    set_operations(w, FULL)
    with pytest.raises(ExtractionFailure, match="initial_dispatch_taken"):
        resume(w, p.access(), "job-seen", initial_only=True)
    assert len(p.requests) == 1 and resume(w, p.access(), "job-seen")["state"] == "ready" and len(p.requests) == 2

    # An operator who already ran the job leaves nothing for the automatic dispatch.
    assert resume(w, p.access(), "job-plain")["state"] == "ready"
    with pytest.raises(ExtractionFailure, match="initial_dispatch_taken"):
        resume(w, p.access(), "job-plain", initial_only=True)
    assert len(p.requests) == 3


def test_a_replay_job_never_reads_the_live_runtime_or_environment(lw):
    w, kit = lw, lw.kit
    article = kit.article(w.a2)
    mention = kit.mention(article, "m-replay", [kit.evidence(article, Q3B)])
    replay = kit.replay("replay-only").extract(article, [mention]).write()
    request = Submit.model_validate(kit.submit("job-replay", w.a2))
    with session(w, NO_LIVE) as ex:
        ex.freeze(request, Fixtures(replay.read_bytes(), None))
        done = ex.resume("job-replay", Fixtures(replay.read_bytes(), None))
        assert ex.resume("job-replay", NONE, initial_only=False) == done
    assert done["state"] == "ready" and done["usage"] == {"executionMode": "replay", "replayCalls": 1, "startedWithoutReceipt": 0, "providerCalls": 0,
                                                          "paidModelCalls": 0, "creatorJobId": "job-replay"}
    assert "live" not in done["binding"] and done["binding"]["adapter"]["version"] == "zoop-extraction-native-replay-1"
    assert set(done["calls"][0]) == {"stage", "state", "requestDigest", "fixtureHash", "responseDigest", "verdict"}


def test_the_loopback_cli_smoke_exercises_the_live_path_through_real_processes(tmp_path):
    report = loopback_smoke(tmp_path)
    assert report["status"] == "passed" and report["paidModelCalls"] == 0
    assert report["s2"]["state"] == "ready" and report["s3"]["state"] == "ready" and report["s3"]["delivery"] == "current"
