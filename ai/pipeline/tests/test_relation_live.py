"""Offline live-path behavior of the S3 engine: ordering, durable receipts, unknown/refused/lost-reply handling, rights, drift and final approval.

A FAKE runtime with the exact LiveRuntime contract stands in for the provider transport (no network, no key, no model). Its replies are the authored
replay replies of a reference replay job, so the live path must reproduce the replay candidates, ids and verdicts exactly. The real prompts, Jev
adapter and budget ledger are the LiveTransport owner's tests; the real Luna/Jev run is Main's only.
"""
from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from scripts.relation_smoke import GOOD, SUP, build_world, co, converge, find, impact_item, proposal, world_cite
from zoop_ai_pipeline import relation, live_jev
from tests.test_extraction_live import ChainPeer, chain_cli, chain_receipts, chain_world
from zoop_ai_pipeline.extraction_contracts import ExtractionFailure, Provenance
from zoop_ai_pipeline.live_runtime import LiveFailure
from zoop_ai_pipeline.relation import Engine
from zoop_ai_pipeline.relation_contracts import digest

LIVE = {"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"}
STAGES = ("relation", "verify-relation", "impact", "verify-impact")
PURPOSES = [f"pipeline:{stage}" for stage in STAGES]
RECIPIENTS = ("fake:gen", "fake:jev")
BINDING = {"version": "fake-live-1", "identity": "f" * 64}


@pytest.fixture
def world(tmp_path):
    return build_world(tmp_path / "owned")


def c(w, text):
    return world_cite(w, "main", text)


def database(w):
    import sqlite3
    db = sqlite3.connect(w.kit.root / "relation" / "relation.sqlite3")
    db.row_factory = sqlite3.Row
    return db


def make_runtime(replies):
    """(runtime class, state). `state.behavior(prepared)` may answer 'unknown' (lost reply), 'refuse' (refused before sending) or None."""
    state = SimpleNamespace(replies=replies, sends=[], requests=[], behavior=None, after_send=None, binding=dict(BINDING), authorized=0)

    class Fake:
        def __init__(self, need_send: bool):
            self.need_send = need_send

        @classmethod
        def from_binding(cls, binding):
            if binding != state.binding:
                raise LiveFailure("live_binding_mismatch")
            return cls(False)

        def binding(self):
            return dict(state.binding)

        def accepts(self, binding):
            return binding == state.binding

        def purpose(self, stage):
            return f"pipeline:{stage}"

        def recipient(self, stage):
            return "fake:jev" if stage.startswith("verify") else "fake:gen"

        def fallback_recipient(self, stage):
            return None

        def prepare(self, stage, payload):
            return {"stage": stage, "digest": digest({k: v for k, v in payload.items() if k != "citationSources"}), "payload": payload}

        def send(self, prepared, *, attempt_id, authorize):
            if not self.need_send:
                raise LiveFailure("live_send_unavailable")
            authorize()
            state.authorized += 1
            action = state.behavior(prepared) if state.behavior else None
            if action == "refuse":
                raise LiveFailure("live_budget_exhausted_usd")
            state.sends.append((prepared["stage"], attempt_id))
            state.requests.append(prepared)
            if action == "unknown":
                raise LiveFailure("live_response_unknown", uncertain=True)
            reply = state.replies.get((prepared["stage"], prepared["digest"]))
            if prepared["stage"] in {"relation", "impact"} and reply is not None:
                from tests.live_support import reference_answer
                reply = reference_answer(prepared["stage"], prepared["payload"], reply)
            if state.after_send:
                state.after_send()
            return {"format": "fake-receipt", "stage": prepared["stage"], "attemptId": attempt_id,
                    "reply": None if action == "unavailable" else {"bogus": 1} if action == "invalid" else reply}

        def answer(self, stage, receipt):
            if receipt["reply"] is None:
                raise LiveFailure("live_http_503")
            return receipt["reply"]

    return Fake, state


def go_live(w, monkeypatch, *, replies=None, send=True):
    """Make the replay world's S2 upstream look live and register the model-send authority for the fake runtime."""
    runtime, state = make_runtime(replies or {})
    monkeypatch.setattr(relation, "LiveRuntime", runtime)
    original = Engine._upstream

    def live_upstream(self, job_id):
        submit, result = original(self, job_id)
        return submit.model_copy(update={"provenance": Provenance.model_validate(LIVE)}), result

    monkeypatch.setattr(Engine, "_upstream", live_upstream)
    allow_send(w, send)
    return runtime, state, (lambda need_send: runtime(need_send))


def allow_send(w, send=True):
    grant = w.kit.registry["sources"][0]["grant"]
    grant["allowedOperations"] = ["read", "store", "quote-display", *(["model-send"] if send else [])]
    grant["purposes"], grant["recipients"] = list(PURPOSES), list(RECIPIENTS)
    w.kit.save_registry()


def live_request(w, job):
    return {**w.kit.rsubmit(job, w.s2), "provenance": LIVE}


def reference(w):
    """A replay reference job and its authored replies keyed like the live request digests."""
    props = [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)], product="fine"),
             proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)], product="scope-hold")]
    out = converge(w, "ref", props, verify=lambda r: {"scope": "insufficient"} if r["productScope"] == "scope-hold" else None,
                   impacts=lambda r: [impact_item("SYNTH-1", "positive", [c(w, GOOD)], [])], effects=lambda i: {GOOD: "positive"})
    replies = {(stage, key): response for records in out["fixtures"] for stage, key, response in records}
    return out, replies


def test_the_live_path_reproduces_the_replay_candidates_with_durable_receipts_and_no_fixture(world, monkeypatch):
    w = world
    ref, replies = reference(w)
    runtime, state, factory = go_live(w, monkeypatch, replies=replies)
    out = w.kit.rel_job("run", live_request(w, "lv"), runtime_factory=factory)
    assert out["state"] == "ready" and out["provenance"] == LIVE and out["binding"]["runtime"] == BINDING
    assert [r["relationCandidateId"] for r in out["relations"]] == [r["relationCandidateId"] for r in ref["relations"]]
    strip = lambda e: {**e, "approvalBasis": {k: v for k, v in e["approvalBasis"].items() if k != "decidedAt"} if e["approvalBasis"] else None}  # noqa: E731
    assert [strip(r["eligibility"]) for r in out["relations"]] == [strip(r["eligibility"]) for r in ref["relations"]]
    assert out["counts"] == ref["counts"]
    assert sorted((x["stage"], x["requestDigest"]) for x in out["calls"]) == sorted((x["stage"], x["requestDigest"]) for x in ref["calls"])
    calls = len(ref["calls"])
    assert out["usage"] == {"executionMode": "live", "replayCalls": 0, "startedWithoutReceipt": 0, "providerCalls": calls, "modelCalls": calls, "creatorJobId": "lv"}
    assert len(state.sends) == state.authorized == calls
    assert {x["fixtureHash"] for x in out["calls"]} == {digest(BINDING)} and all(x["state"] == "received" for x in out["calls"])
    db = database(w)
    stored = db.execute("SELECT response FROM calls WHERE job_id='lv' LIMIT 1").fetchone()[0]
    db.close()
    assert '"attemptId"' in stored  # the raw receipt envelope is what is persisted
    again = w.kit.rel_job("resume", w.kit.rsel("lv"))
    assert again == out and len(state.sends) == calls  # a finished job resends nothing


def test_future_topic_relation_passes_both_selected_passages_to_the_verifier(world, monkeypatch):
    w = world
    item = proposal("RELATES_TO_TOPIC", co("SYNTH-3"), {"kind": "topic", "ref": w.tp}, [c(w, SUP), c(w, GOOD)], product="배터리 부품")
    item["reason"] = "GENERATOR-PROSE-IS-NOT-EVIDENCE"
    authored = converge(w, "topic-ref", [item])
    replies = {(stage, key): response for records in authored["fixtures"] for stage, key, response in records}
    _, state, factory = go_live(w, monkeypatch, replies=replies)
    out = w.kit.rel_job("run", live_request(w, "topic-live"), runtime_factory=factory)
    assert out["state"] == "ready" and out["counts"]["eligibility"]["eligible"] == 1
    payload = next(p["payload"] for p in state.requests if p["stage"] == "verify-relation")
    body, expect = live_jev.build_relation_request(payload, live_jev.MODEL)
    assert {q["text"] for q in body["state"]["quotes"]} == {SUP, GOOD}
    assert all(set(c["quoteIds"]) == {q["quoteId"] for q in payload["quotes"]} for c in expect["claims"])
    assert item["reason"] not in str(body) and w.art["b"].body not in str(body)


def test_a_live_job_never_accepts_replay_fixtures_and_needs_a_runtime(world, monkeypatch):
    w = world
    _, replies = reference(w)
    runtime, state, factory = go_live(w, monkeypatch, replies=replies)
    with pytest.raises(ExtractionFailure, match="live_runtime_unavailable"):
        w.kit.rel_job("submit", live_request(w, "lv0"))
    w.kit.rel_job("submit", live_request(w, "lv"), runtime_factory=factory)
    with pytest.raises(ExtractionFailure, match="fixture_not_allowed"):
        w.kit.rel_job("resume", w.kit.rsel("lv"), replay=w.kit.fixture("producer", "p", []), runtime_factory=factory)
    assert state.sends == []


def test_every_sent_document_needs_current_model_send_authority_before_any_reservation(world, monkeypatch):
    w = world
    _, replies = reference(w)
    runtime, state, factory = go_live(w, monkeypatch, replies=replies, send=False)
    out = w.kit.rel_job("run", live_request(w, "lv"), runtime_factory=factory)
    assert out["state"] == "stopped" and out["failure"]["code"] == "source_operation_denied" and out["calls"] == [] and state.sends == []
    allow_send(w)
    done = w.kit.rel_job("resume", w.kit.rsel("lv"), runtime_factory=factory)
    assert done["state"] == "ready" and len(state.sends) == done["usage"]["providerCalls"]


def test_binding_drift_refuses_every_call_and_the_frozen_binding_is_never_replaced(world, monkeypatch):
    w = world
    _, replies = reference(w)
    runtime, state, factory = go_live(w, monkeypatch, replies=replies)
    queued = w.kit.rel_job("submit", live_request(w, "lv"), runtime_factory=factory)
    assert queued["state"] == "queued" and queued["binding"]["runtime"] == BINDING and queued["calls"] == []
    state.binding = {**BINDING, "version": "fake-live-2"}
    stopped = w.kit.rel_job("resume", w.kit.rsel("lv"), runtime_factory=factory)
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "live_config_changed" and stopped["calls"] == [] and state.sends == []
    assert w.kit.rel_job("inspect", w.kit.rsel("lv"))["binding"]["runtime"] == BINDING


def test_a_refusal_before_sending_is_not_an_unknown_call_and_a_later_resume_rearms_one_new_attempt(world, monkeypatch):
    w = world
    ref, replies = reference(w)
    runtime, state, factory = go_live(w, monkeypatch, replies=replies)
    state.behavior = lambda prepared: "refuse" if prepared["stage"] == "relation" else None
    stopped = w.kit.rel_job("run", live_request(w, "lv"), runtime_factory=factory)
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "live_budget_exhausted_usd" and state.sends == []
    assert [(x["stage"], x["state"], x["verdict"]) for x in stopped["calls"]] == [("relation", "refused", "live_budget_exhausted_usd")]
    assert stopped["usage"]["startedWithoutReceipt"] == 0 and stopped["usage"]["providerCalls"] == 0
    state.behavior = None
    done = w.kit.rel_job("resume", w.kit.rsel("lv"), runtime_factory=factory)
    assert done["state"] == "ready" and sum(x["stage"] == "relation" for x in done["calls"]) == 1 and len(state.sends) == len(ref["calls"])
    db = database(w)
    assert db.execute("SELECT COUNT(*) FROM stages WHERE stage='refusal'").fetchone()[0] == 1  # the refusal stays recorded as history
    db.close()


def test_a_lost_reply_is_unknown_never_resent_and_blocks_the_initial_dispatch_gate(world, monkeypatch):
    w = world
    _, replies = reference(w)
    runtime, state, factory = go_live(w, monkeypatch, replies=replies)
    state.behavior = lambda prepared: "unknown"
    lost = w.kit.rel_job("run", live_request(w, "lv"), runtime_factory=factory)
    assert lost["state"] == "reconciling" and lost["resumeMode"] == "reconcile_only" and lost["failure"] == {"code": "live_response_unknown"} and len(state.sends) == 1
    assert [(x["stage"], x["state"]) for x in lost["calls"]] == [("relation", "started")] and lost["usage"]["startedWithoutReceipt"] == 1 and lost["usage"]["providerCalls"] == 1  # an unknown outcome is conservatively a provider call
    assert lost["usage"]["modelCalls"] == 1 and lost["usage"]["providerCalls"] - lost["usage"]["startedWithoutReceipt"] == 0  # ...but it is not a receipt
    state.behavior = None
    with pytest.raises(ExtractionFailure, match="initial_dispatch_taken"):
        w.kit.rel_job("resume", w.kit.rsel("lv"), runtime_factory=factory, initial_only=True)
    reconciling = w.kit.rel_job("resume", w.kit.rsel("lv"), runtime_factory=factory)
    assert reconciling["state"] == "reconciling" and reconciling["failure"]["code"] == "live_response_unknown" and reconciling["resumeMode"] == "reconcile_only"
    assert len(state.sends) == 1  # nothing was resent, and nothing is ever repaired by calling the model again


def test_the_first_initial_only_dispatch_runs_and_a_repeat_has_no_effect(world, monkeypatch):
    w = world
    ref, replies = reference(w)
    runtime, state, factory = go_live(w, monkeypatch, replies=replies)
    w.kit.rel_job("submit", live_request(w, "lv"), runtime_factory=factory)
    first = w.kit.rel_job("resume", w.kit.rsel("lv"), runtime_factory=factory, initial_only=True)
    assert first["state"] == "ready" and len(state.sends) == len(ref["calls"])
    with pytest.raises(ExtractionFailure, match="initial_dispatch_taken"):
        w.kit.rel_job("resume", w.kit.rsel("lv"), runtime_factory=factory, initial_only=True)
    assert w.kit.rel_job("inspect", w.kit.rsel("lv")) == first and len(state.sends) == len(ref["calls"])


def test_rights_lost_after_a_receipt_keep_a_valid_receipt_commit_nothing_and_recover_without_a_new_call(world, monkeypatch):
    w = world
    _, replies = reference(w)
    runtime, state, factory = go_live(w, monkeypatch, replies=replies)

    def revoke():
        allow_send(w, False)

    state.after_send = revoke
    stopped = w.kit.rel_job("run", live_request(w, "lv"), runtime_factory=factory)
    state.after_send = None
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "registry_changed" and stopped["delivery"]["status"] == "withheld"
    db = database(w)
    # The replay reference job ("ref") shares this ledger: every assertion is scoped to the live job.
    assert [r["state"] for r in db.execute("SELECT state FROM calls WHERE job_id='lv'").fetchall()] == ["received"]
    assert db.execute("SELECT COUNT(*) FROM relation_candidates WHERE job_id='lv'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM relation_events WHERE job_id='lv'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM stages WHERE job_id='lv' AND stage NOT IN ('dispatch','refusal')").fetchone()[0] == 0
    db.close()
    denied = w.kit.rel_job("resume", w.kit.rsel("lv"), runtime_factory=factory)
    assert denied["failure"]["code"] == "source_operation_denied" and len(state.sends) == 1  # the saved receipt is not delivered without the authority either
    allow_send(w)
    done = w.kit.rel_job("resume", w.kit.rsel("lv"), runtime_factory=factory)
    assert done["state"] == "ready" and sum(1 for s, _ in state.sends if s == "relation") == 1


@pytest.mark.parametrize("failure", ["unavailable", "invalid"])
def test_a_technical_verifier_failure_is_no_judgment_never_a_hold_a_human_can_approve_and_never_an_automatic_verdict(world, monkeypatch, failure):
    w = world
    _, replies = reference(w)
    runtime, state, factory = go_live(w, monkeypatch, replies=replies)
    state.behavior = lambda prepared: failure if prepared["stage"] == "verify-relation" else None
    out = w.kit.rel_job("run", live_request(w, "lv"), runtime_factory=factory)
    code = "live_http_503" if failure == "unavailable" else "verifier_reply_invalid"
    assert out["state"] == "stopped" and out["failure"]["code"] == "verification_unavailable"
    assert sorted(c["code"] for c in out["failure"]["detail"]["calls"]) == [code, code] and {c["stage"] for c in out["failure"]["detail"]["calls"]} == {"verify-relation"}
    assert out["counts"]["eligibility"] == {"pending": 2, "eligible": 0, "hold": 0, "reject": 0}
    assert all(r["history"] == [] and r["eligibility"]["status"] == "pending" and r["eligibility"]["approvalBasis"] is None for r in out["relations"])
    assert all(x["state"] == "received" and x["verdict"] == code for x in out["calls"] if x["stage"] == "verify-relation")  # the raw receipt stays durable and unusable
    db = database(w)
    assert db.execute("SELECT COUNT(*) FROM relation_events WHERE job_id='lv'").fetchone()[0] == 0  # no automatic verdict of any kind
    db.close()
    sends = len(state.sends)
    for relation_ in out["relations"]:
        for decision in ("allow", "reject"):
            # A pending candidate has revision 0 (the wire demands >= 1) and is not a HOLD: no human decision can be recorded for it at any revision.
            with pytest.raises(ExtractionFailure, match="review_revision_conflict") as info:
                w.kit.rel_job("review", {**w.kit.rsel("lv"), "relationCandidateId": relation_["relationCandidateId"], "decision": decision, "reviewer": "operator-a",
                                         "note": "provider was down", "expectedRevision": 1})
            assert info.value.detail == {"currentRevision": 0}
    state.behavior = None
    again = w.kit.rel_job("resume", w.kit.rsel("lv"), runtime_factory=factory)
    assert again["state"] == "stopped" and again["failure"] == out["failure"] and len(state.sends) == sends  # the failed receipt is never repaired by another call


def test_a_valid_interpreted_hold_from_the_live_verifier_can_still_be_approved_by_a_human_with_no_model(world, monkeypatch):
    w = world
    _, replies = reference(w)
    runtime, state, factory = go_live(w, monkeypatch, replies=replies)
    out = w.kit.rel_job("run", live_request(w, "lv"), runtime_factory=factory)
    held = find(out, "SUPPLIES", productScope="scope-hold")
    assert out["state"] == "ready" and held["eligibility"]["status"] == "hold" and held["history"][0]["verifier"] == "called"
    sends = len(state.sends)
    approved = w.kit.rel_job("review", {**w.kit.rsel("lv"), "relationCandidateId": held["relationCandidateId"], "decision": "allow", "reviewer": "operator-a",
                                        "note": "semantic judgment was insufficient; evidence reviewed", "expectedRevision": 1})  # no runtime factory: a review never reads keys
    item = find(approved, "SUPPLIES", productScope="scope-hold")
    assert item["eligibility"]["status"] == "eligible" and item["eligibility"]["approvalBasis"]["kind"] == "operator-final-approval"
    assert item["history"][0] == held["history"][0] and len(state.sends) == sends and approved["calls"] == out["calls"]


def test_a_technical_impact_verifier_failure_writes_no_impact_judgment_and_leaves_the_relation_eligible(world, monkeypatch):
    w = world
    _, replies = reference(w)
    runtime, state, factory = go_live(w, monkeypatch, replies=replies)
    state.behavior = lambda prepared: "unavailable" if prepared["stage"] == "verify-impact" else None
    out = w.kit.rel_job("run", live_request(w, "lv"), runtime_factory=factory)
    assert out["state"] == "stopped" and out["failure"]["code"] == "verification_unavailable"
    assert [c["stage"] for c in out["failure"]["detail"]["calls"]] == ["verify-impact"] and out["failure"]["detail"]["calls"][0]["code"] == "live_http_503"
    fine = find(out, "SUPPLIES", productScope="fine")
    assert fine["eligibility"]["status"] == "eligible" and fine["eligibility"]["approvalBasis"]["kind"] == "automatic-verifier"
    assert [i["verdict"] for i in fine["impact"]["candidates"]] == [None] and out["counts"]["impactLabels"] == {"positive": 0, "negative": 0, "mixed": 0, "undetermined": 0}


def test_a_review_is_refused_while_a_live_call_for_that_relation_is_unknown(world, monkeypatch):
    w = world
    _, replies = reference(w)
    runtime, state, factory = go_live(w, monkeypatch, replies=replies)
    out = w.kit.rel_job("run", live_request(w, "lv"), runtime_factory=factory)
    held = find(out, "SUPPLIES", productScope="scope-hold")
    db = database(w)
    db.execute("INSERT INTO calls(attempt_id,job_id,stage,ref,request_digest,fixture_hash,state,started_at) VALUES(?,?,?,?,?,?,'started',?)",
               ("attempt-lost", "lv", "impact", held["relationCandidateId"], "a" * 64, digest(BINDING), "2026-10-21T00:00:00+00:00"))
    db.commit()
    db.close()
    request = {**w.kit.rsel("lv"), "relationCandidateId": held["relationCandidateId"], "decision": "allow", "reviewer": "operator-a", "note": "n", "expectedRevision": 1}
    with pytest.raises(ExtractionFailure, match="review_call_in_flight"):
        w.kit.rel_job("review", request)
    assert find(w.kit.rel_job("review", {**request, "decision": "reject"}), "SUPPLIES", productScope="scope-hold")["eligibility"]["status"] == "reject"



# ---------------------------------------------------------------- two independently granted sources -------------------

SOURCE_B = "synthetic-source-b"


def build_two_source_world(root):
    """Like `relation_smoke.build_world`, but the snapshot-event member B is ingested from its OWN source (`synthetic-source-b`) with its OWN grant, so the
    real Authority/Sources gate (not a mock) decides per source. Relations can quote only A while event/topic names derive from B."""
    import copy
    import json as _json
    from scripts.extraction_smoke import PROMPT, page, topic_replay, topic_response
    from scripts.ingestion_smoke import json_bytes
    from scripts.relation_smoke import EVT, MAIN_TEXT, QB, RelKit
    kit = RelKit(root)
    registry_b = copy.deepcopy(kit.registry["sources"][0])
    registry_b["sourceId"], registry_b["grant"]["sourceId"], registry_b["grant"]["grantId"] = SOURCE_B, SOURCE_B, "operator-grant-b"
    kit.registry["sources"].append(registry_b)
    kit.save_registry()
    (main,) = kit.ingest("docs", [{"supplier": "supplier-main", "html": page(*MAIN_TEXT)}])
    items = [{**kit.item("c0", "supplier-b", "https://example.invalid/b/0", ref="d0"), "publishedAt": None}]
    manifest = kit.manifest("docsb", [items], bodies={"d0": page(QB, "착공은 2026년 11월 예정이다.")})
    data = _json.loads(manifest.read_bytes())
    data["sourceId"] = SOURCE_B
    manifest.write_bytes(json_bytes(data))
    done = kit.cli("run", {**kit.request(manifest, "round-docsb", 0), "sourceId": SOURCE_B}, state="ingestion", manifest=manifest)
    assert done["state"] == "complete" and done["counts"]["textReady"] == 1, done
    other = {"roundId": "round-docsb", "sourceId": SOURCE_B, **{k: done["documentRefs"][0][k] for k in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")}}
    art = {"main": kit.article(main), "b": kit.article(other)}
    mention = {**kit.mention(art["main"], "m-main", [kit.evidence(art["main"], EVT)]), "countries": []}
    mention_b = kit.mention(art["b"], "m-b", [kit.evidence(art["b"], QB)], period="2026Q4", title="합성 공장 착공", action="공장 착공 알림")
    snapshot = kit.event("event-1", [(other, mention_b)])
    replay = kit.replay("s2").extract(art["main"], [mention]).compare(mention, "event-1", [(other, art["b"], mention_b)], art["main"], "DIFFERENT", "다른 사건", []).write()
    request = kit.submit("s2-job", main, [snapshot], topic=True)
    pending = kit.job("run", request, replay=replay)
    evc = pending["eventCandidates"][0]["eventCandidateId"]
    world = SimpleNamespace(kit=kit, refs={"main": main, "b": other}, art=art, evc=evc, event="event-1", s2_replay=replay, snapshot=snapshot)
    topic = topic_replay(kit, "s2-topic", {pending["failure"]["detail"]["topicRequestDigest"]: topic_response([{
        "label": "합성기업 계약과 공장", "criteria": "같은 기업의 서로 다른 사업 사건", "rationale": "authored replay",
        "members": [{"kind": "event-candidate", "ref": evc}, {"kind": "snapshot-event", "ref": "event-1"}],
        "citations": [world_cite(world, "main", EVT), world_cite(world, "b", QB)]}])})
    ready = kit.job("resume", kit.job_selector("s2-job"), topic=topic)
    assert ready["state"] == "ready", ready
    world.s2 = ready
    return world


@pytest.mark.parametrize("lacking,denied_stage,sent_before", [
    ("purpose", "verify-relation", {"relation"}), ("purpose", "impact", {"relation", "verify-relation"}),
    ("purpose", "verify-impact", {"relation", "verify-relation", "impact"}),
    ("recipient", "verify-relation", {"relation"})])  # the Jev recipient covers both verify stages: lacking it denies the first one reached
def test_the_real_gate_denies_a_stage_when_a_separately_granted_bound_source_lacks_its_purpose_or_recipient(tmp_path, monkeypatch, lacking, denied_stage, sent_before):
    """A and B are different sources with different grants. Every relation quotes only A, but the producer and verifier payloads carry names derived from
    B's snapshot event. B authorizes generation (and the earlier stages) but not the denied stage's purpose or recipient: the REAL Authority/Sources gate
    refuses before any S3 `calls` row or provider request exists for that stage."""
    w = build_two_source_world(tmp_path / "owned")
    _, replies = reference(w)
    runtime, state, factory = go_live(w, monkeypatch, replies=replies)
    grant_b = next(s for s in w.kit.registry["sources"] if s["sourceId"] == SOURCE_B)["grant"]
    grant_b["allowedOperations"] = ["read", "store", "quote-display", "model-send"]
    grant_b["purposes"] = [p for p in PURPOSES if not (lacking == "purpose" and p == f"pipeline:{denied_stage}")]
    grant_b["recipients"] = [r for r in RECIPIENTS if not (lacking == "recipient" and r == "fake:jev")]
    w.kit.save_registry()
    out = w.kit.rel_job("run", live_request(w, "lv"), runtime_factory=factory)
    assert out["state"] == "stopped" and out["failure"]["code"] == "source_purpose_or_recipient_denied"
    assert {s for s, _ in state.sends} == sent_before and denied_stage not in {s for s, _ in state.sends}
    assert all(x["stage"] != denied_stage for x in out["calls"])
    db = database(w)
    assert db.execute("SELECT COUNT(*) FROM calls WHERE job_id='lv' AND stage=?", (denied_stage,)).fetchone()[0] == 0
    db.close()
    grant_b["purposes"], grant_b["recipients"] = list(PURPOSES), list(RECIPIENTS)  # once B grants it, the same job continues with no repair of anything
    w.kit.save_registry()
    done = w.kit.rel_job("resume", w.kit.rsel("lv"), runtime_factory=factory)
    assert done["state"] == "ready" and denied_stage in {s for s, _ in state.sends}


def native_relation_request(upstream, job="native-s3"):
    return {"schemaVersion": "zoop-relation-s3", "jobId": job, "provenance": upstream["provenance"],
            "upstream": {"jobId": upstream["jobId"], "inputDigest": upstream["inputDigest"]}}


@pytest.mark.parametrize("outcome", ["success", "denied", "unknown", "all-errors"])
def test_native_relation_chain_cli_accounts_each_role_without_replaying_paid_upstream(tmp_path, monkeypatch, outcome):
    w = chain_world(tmp_path, monkeypatch, fallback_grant=outcome != "denied")
    with ChainPeer() as peer:
        upstream = chain_cli(w, peer, "run", w.request("upstream", snapshot=False, topic=False))
        assert upstream["state"] == "ready"
        upstream_saved = chain_receipts(w)
        before = w.budget.snapshot()
        peer.behavior["openai", "relation"] = "invalid"
        if outcome in {"unknown", "all-errors"}:
            peer.behavior["deepseek", "relation"] = "unknown" if outcome == "unknown" else "invalid"
        out = chain_cli(w, peer, "run", native_relation_request(upstream), family="relation")
        assert out["state"] == {"success": "ready", "denied": "stopped", "unknown": "reconciling", "all-errors": "stopped"}[outcome]
        assert sum(stage == "extract" for _, stage, _ in peer.requests) == 1
        assert chain_receipts(w) == upstream_saved
        rows = chain_receipts(w, "relation")
        envelope = json.loads(next(r[3] for r in rows if r[0] == "relation"))
        assert envelope["attemptId"] == envelope["logicalAttemptId"] == rows[0][1]
        assert envelope["physicalAttempts"][0]["state"] == "received"
        assert len(out["calls"][0]["physicalAttempts"]) == 2
        usage = out["usage"]
        if outcome == "success":
            assert [(role, stage) for role, stage, _ in peer.requests] == [
                ("openai", "extract"), ("openai", "relation"), ("deepseek", "relation"),
                ("typesafe", "verify-relation"), ("openai", "impact")]
            assert len(out["calls"]) == 3
            assert usage["providerCalls"] == usage["modelCalls"] == usage["receivedCalls"] == 4
            assert (usage["inputTokens"], usage["outputTokens"]) == (4600, 900)
            assert out["counts"]["eligibility"]["eligible"] == 1
            receipts = [json.loads(row[3]) for row in rows]
            leaves = [p["receipt"] for r in receipts if "physicalAttempts" in r for p in r["physicalAttempts"]]
            leaves += [r for r in receipts if "physicalAttempts" not in r]
            assert {r["funding"]["accountRole"] for r in leaves} == {"shared-openai", "personal-deepseek", "personal-typesafe"}
            for field in ("estimatedUsd", "chargedUsd"):
                assert Decimal(usage[field]) == sum(Decimal(r["cost"][field]) for r in leaves)
            after = w.budget.snapshot()
            for bucket in ("shared", "personal"):
                assert Decimal(after["buckets"][bucket]["chargedUsd"]) - Decimal(before["buckets"][bucket]["chargedUsd"]) == sum(
                    Decimal(r["cost"]["chargedUsd"]) for r in leaves if r["funding"]["bucket"] == bucket)
        else:
            assert out["stages"]["relation"]["state"] == "pending" and out["relations"] == []
            assert usage["providerCalls"] == (1 if outcome == "denied" else 2)
            assert usage["receivedCalls"] == (2 if outcome == "all-errors" else 1)
            assert usage["startedWithoutReceipt"] == (1 if outcome == "unknown" else 0)
            if outcome == "unknown":
                assert rows[0][2] == out["calls"][0]["state"] == "started"
                assert out["resumeMode"] == "reconcile_only" and out["failure"]["code"] == "live_response_unknown"
                assert usage["inputTokens"] is None and usage["chargedUsd"] is None
                assert w.budget.snapshot()["states"]["reserved"] == 1
            if outcome == "denied":
                assert out["failure"]["code"] == "source_purpose_or_recipient_denied"
                assert all(role != "deepseek" for role, _, _ in peer.requests)
        count = len(peer.requests)
        again = chain_cli(w, peer, "resume", {"schemaVersion": "zoop-relation-s3", "jobId": "native-s3"}, family="relation", live=False)
        assert again["state"] == out["state"] and again["usage"] == usage
        assert len(peer.requests) == count and chain_receipts(w, "relation") == rows and chain_receipts(w) == upstream_saved


def test_native_relation_chain_cli_saved_winner_recovery_sends_no_generation_again(tmp_path, monkeypatch):
    w = chain_world(tmp_path, monkeypatch)
    hook = """
from zoop_ai_pipeline.relation import Engine
receive = Engine._receive
def crash(self, attempt, raw):
    receive(self, attempt, raw)
    if raw['stage'] == 'relation':
        os._exit(75)
Engine._receive = crash
"""
    with ChainPeer() as peer:
        upstream = chain_cli(w, peer, "run", w.request("upstream", snapshot=False, topic=False))
        peer.behavior["openai", "relation"] = "invalid"
        chain_cli(w, peer, "run", native_relation_request(upstream), family="relation", hook=hook, expected=75)
        saved = chain_receipts(w, "relation")
        assert len(saved) == 1
        selector = {"schemaVersion": "zoop-relation-s3", "jobId": "native-s3"}
        no_env = chain_cli(w, peer, "resume", selector, family="relation", live=False)
        assert no_env["stages"]["relation"]["state"] == "complete" and len(no_env["relations"]) == 1
        assert no_env["failure"]["code"] == "live_not_enabled"
        assert chain_receipts(w, "relation") == saved
        out = chain_cli(w, peer, "resume", selector, family="relation")
        assert out["state"] == "ready"
        assert [(role, stage) for role, stage, _ in peer.requests].count(("openai", "relation")) == 1
        assert [(role, stage) for role, stage, _ in peer.requests].count(("deepseek", "relation")) == 1


@pytest.mark.parametrize("field", ["attemptId", "logicalAttemptId", "stage", "requestDigest", "bindingIdentity"])
def test_native_relation_chain_cli_rejects_wrong_outer_invocation(tmp_path, monkeypatch, field):
    w = chain_world(tmp_path, monkeypatch)
    hook = f"""
from zoop_ai_pipeline.live_runtime import LiveRuntime
send = LiveRuntime.send
def wrong(self, *args, **kwargs):
    result = send(self, *args, **kwargs)
    if result.get('format') == 'zoop-live-chain-receipt-1':
        result = {{**result, {field!r}: 'other'}}
    return result
LiveRuntime.send = wrong
"""
    with ChainPeer() as peer:
        upstream = chain_cli(w, peer, "run", w.request("upstream", snapshot=False, topic=False))
        out = chain_cli(w, peer, "run", native_relation_request(upstream), family="relation", hook=hook)
        assert out["state"] == "stopped" and out["failure"]["code"] == "receipt_binding_mismatch"
        assert out["stages"]["relation"]["state"] == "pending" and out["relations"] == []
        assert len(peer.requests) == 2
