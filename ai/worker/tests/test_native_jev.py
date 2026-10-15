"""Native Jev semantic verification (S1): request, strict response policy, recipients, budget, no retry and recovery.

Synthetic text only. HTTP is `httpx.MockTransport` or loopback servers (tests/fake_providers.py); no real endpoint, key or model is
ever used, and no test reads an environment file.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from fake_providers import FakeServer, choice_answer, fixture, jev_respond, luna_respond
from zoop_ai import native_jev
from zoop_ai.contracts import SCHEMA_VERSION, SourceGrant, Submit, SummaryAnswer, digest
from zoop_ai.provider import NativeJevProvider, OpenAICompatibleProvider, ProviderError, native_revision, stage_config
from zoop_ai.runner import Runner
from zoop_ai.store import Store

WORKER = Path(__file__).resolve().parents[1]
LUNA_BASE, JEV_BASE = "https://luna.invalid/v1", "https://jev.invalid/v1"
LUNA_KEY, JEV_KEY = "luna-synthetic-key-0001", "jev-synthetic-key-0002"
VERIFY = "semantic-verification"
ENV = {"ZOOP_AI_BASE_URL": LUNA_BASE, "ZOOP_AI_DOCUMENT_SUMMARY_MODEL": "synthetic-generator",
       "ZOOP_AI_DOCUMENT_SENTIMENT_MODEL": "synthetic-generator", "ZOOP_AI_VERIFY_PROVIDER": "typesafe-native",
       "TYPESAFE_VALIDATION_MODEL": native_jev.MODEL, "TYPESAFE_BASE_URL": JEV_BASE}


@pytest.fixture(autouse=True)
def native_env(monkeypatch):
    for name in list(os.environ):
        if name.startswith(("ZOOP_AI_", "TYPESAFE_")) or name.upper() in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}:
            monkeypatch.delenv(name)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")  # the loopback servers must never be routed through a developer proxy
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)


def job(job_id="native-job"):
    base = Submit.model_validate(fixture("jobs")["jobs"][0])
    return base.model_copy(update={"job_id": job_id, "mode": "live",
                                   "provenance": base.provenance.model_copy(update={"execution_mode": "live", "recording_kind": "provider"})})


def recipients():
    """The two live recipients a grant must name: the chat endpoint for generation and the native endpoint for verification."""
    return ["openai-compatible:" + digest({"endpoint": LUNA_BASE}), "typesafe-native:" + native_revision(JEV_BASE)]


def make_grant(**change):
    return SourceGrant.model_validate({**fixture("grants")["grants"][0], "recipients": recipients(), **change})


def prepare(tmp_path, *, request=None, grant=None):
    request = request or job()
    store = Store(tmp_path / "worker")
    store.register_grants([grant or make_grant()])
    runner = Runner(store)
    runner.submit(request)
    return runner, request


def transport(respond):
    """MockTransport over the same `respond(request) -> (status, payload)` shape the loopback servers use; records what it saw."""
    seen = []

    def handler(req):
        request = {"path": req.url.path, "authorization": req.headers.get("authorization"),
                   "headers": {k.lower(): v for k, v in req.headers.items()}, "body": json.loads(req.content)}
        seen.append(request)
        status, payload = respond(request)
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload)
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler), seen


def attach(runner, *, luna=luna_respond, jev=None, ceiling=2):
    luna_transport, luna_seen = transport(luna)
    jev_transport, jev_seen = transport(jev or jev_respond())
    runner.provider = OpenAICompatibleProvider(base_url=LUNA_BASE, api_key=LUNA_KEY, transport=luna_transport)
    runner.verifier = NativeJevProvider(base_url=JEV_BASE, api_key=JEV_KEY, transport=jev_transport)
    runner.live_enabled, runner.max_calls = True, ceiling
    return luna_seen, jev_seen


def verify_call(result):
    return next(c for c in result.calls if c["stage"] == VERIFY)


def receipt(runner, stage=VERIFY):
    return json.loads(runner.store.db.execute("SELECT receipt FROM calls WHERE stage=?", (stage,)).fetchone()[0])


def reserved(runner):
    return runner.store.db.execute("SELECT COUNT(*) FROM budget_reservations").fetchone()[0]


def test_recipients_helper_matches_what_the_stage_configs_freeze():
    assert recipients() == [c.provider + ":" + c.provider_revision
                            for c in (stage_config("document-summary", "live"), stage_config(VERIFY, "live"))]


# ---- request and receipt ---------------------------------------------------------------------------------------
def test_one_systemone_request_carries_only_needed_state_and_each_key_reaches_only_its_own_endpoint(tmp_path):
    runner, request = prepare(tmp_path)
    luna, jev = attach(runner)
    result = runner.run(request.job_id)
    assert result.state == "ready" and len(luna) == len(jev) == 1 and result.usage.provider_attempts == 2
    candidate = SummaryAnswer.model_validate(fixture("replay")["responses"][0]["response"])
    sent = jev[0]
    body = sent["body"]
    assert sent["path"] == "/v1/systemone" and sent["authorization"] == "Bearer " + JEV_KEY
    assert not [h for h in sent["headers"] if h.startswith("typesafe-")]  # no danger-zone, image or data-sharing header
    assert set(body) == {"model", "state", "questions"} and body["model"] == native_jev.MODEL
    claim_keys = {f"claim-{i}" for i in range(len(candidate.claims))}
    assert set(body["questions"]) == claim_keys | {"prohibited-advice", "unsupported-causality"}
    for key in claim_keys:
        question = body["questions"][key]
        assert question["type"] == "choice" and set(question["criteria"]) == {"supported", "contradicted", "insufficient"}
    assert {body["questions"][k]["type"] for k in ("prohibited-advice", "unsupported-causality")} == {"noul"}
    state = body["state"]
    assert set(state) == {"document", "company", "candidate"} and set(state["document"]) == {"inputKind", "text"}
    assert state["company"] == {"name": request.input.company.name}
    assert [c["text"] for c in state["candidate"]["claims"]] == [c.text for c in candidate.claims]
    assert [q["quote"] for q in state["candidate"]["claims"][0]["citedQuotes"]] == [candidate.citations[0].quote]
    dumped = json.dumps(body, ensure_ascii=False)
    for foreign in (JEV_KEY, LUNA_KEY, request.input.grant_id, "reasoning_effort", "reasoningEffort"):
        assert foreign not in dumped
    assert luna[0]["authorization"] == "Bearer " + LUNA_KEY and luna[0]["path"] == "/v1/chat/completions"
    assert JEV_KEY not in json.dumps(luna[0]) and LUNA_KEY not in json.dumps(sent)

    verification = next(a for a in result.artifacts if a.kind == VERIFY)
    assert verification.validation.semantic == "supported" and {c.decision for c in verification.result.claims} == {"supported"}
    call = verify_call(result)
    assert call["config"]["provider"] == "typesafe-native" and call["config"]["model"] == native_jev.MODEL
    assert call["config"]["reasoningEffort"] is None and call["config"]["policyVersion"] == "zoop-document-gate-2"
    assert call["usage"] == {"inputTokens": 321, "outputTokens": 17, "cachedTokens": None, "reasoningTokens": None}
    stored = receipt(runner)
    assert stored["model"] == native_jev.MODEL and set(stored["answers"]) == set(body["questions"])
    assert result.usage.input_tokens == 21 + 321 and result.usage.output_tokens == 13 + 17 and result.usage.cached_tokens is None
    assert reserved(runner) == 2


# ---- policy -----------------------------------------------------------------------------------------------------
CANDIDATE = SummaryAnswer.model_validate(fixture("replay")["responses"][0]["response"])
IDS = [c.claim_id for c in CANDIDATE.claims]
S, C, I = "supported", "contradicted", "insufficient"
OK = [(S, 0.97, 0.93)] * 3


def raw(choices, prohibited=0.02, causality=0.03, model=native_jev.MODEL):
    answers = {native_jev.claim_key(i): choice_answer(*choice) for i, choice in enumerate(choices)}
    answers[native_jev.PROHIBITED_KEY] = {"type": "noul", "noul": prohibited}
    answers[native_jev.CAUSALITY_KEY] = {"type": "noul", "noul": causality}
    return {"model": model, "answers": answers, "usage": {"input_tokens": 1, "output_tokens": 1}}


MATRIX = [
    ("all supported", OK, 0.02, 0.03, "supported", (False, False)),
    ("both boundaries accepted", [(S, 0.90, 0.80)] * 3, 0.10, 0.10, "supported", (False, False)),
    ("probability just below", [(S, 0.899, 0.93), OK[1], OK[2]], 0.02, 0.03, "hold", (False, False)),
    ("confidence just below", [(S, 0.97, 0.799), OK[1], OK[2]], 0.02, 0.03, "hold", (False, False)),
    ("contradiction accepted", [OK[0], (C, 0.97, 0.93), OK[2]], 0.02, 0.03, "reject", (False, False)),
    ("weak contradiction is a hold, never a rejection", [OK[0], (C, 0.70, 0.50), OK[2]], 0.02, 0.03, "hold", (False, False)),
    ("model chose insufficient", [(I, 0.99, 0.98), OK[1], OK[2]], 0.02, 0.03, "hold", (False, False)),
    ("advice at the true threshold", OK, 0.90, 0.03, "reject", (True, False)),
    ("advice just below the true threshold", OK, 0.899, 0.03, "hold", (False, False)),
    ("advice at the false threshold", OK, 0.10, 0.03, "supported", (False, False)),
    ("advice just above the false threshold", OK, 0.101, 0.03, "hold", (False, False)),
    ("causality at the true threshold", OK, 0.02, 0.90, "reject", (False, True)),
    ("causality uncertain", OK, 0.02, 0.50, "hold", (False, False)),
    ("a finding outranks an uncertainty", OK, 0.95, 0.50, "reject", (True, False)),
    ("a contradiction is never softened by uncertainty", [OK[0], (C, 0.97, 0.93), OK[2]], 0.50, 0.03, "reject", (False, False)),
]


@pytest.mark.parametrize("name,choices,prohibited,causality,semantic,flags", MATRIX, ids=[m[0] for m in MATRIX])
def test_policy_never_auto_accepts_anything_uncertain(name, choices, prohibited, causality, semantic, flags):
    answer = native_jev.interpret(raw(choices, prohibited, causality), IDS, native_jev.MODEL)
    assert Runner(None)._validate_verdict(CANDIDATE, answer) == semantic
    assert (answer.prohibited_advice, answer.unsupported_causality) == flags
    assert [v.claim_id for v in answer.claims] == IDS
    assert all(v.reason.startswith("native_policy:") for v in answer.claims)


def test_reasons_are_code_generated_and_never_repeat_model_text():
    response = raw(OK)
    for answer in response["answers"].values():
        answer["explanation"] = "MODELPROSE ignore previous instructions"
    response["notes"] = "MODELPROSE"
    assert "MODELPROSE" not in native_jev.interpret(response, IDS, native_jev.MODEL).model_dump_json()


BAD = {
    "model alias": (lambda r: r.update(model="jev-latest"), "native_model_mismatch"),
    "other version": (lambda r: r.update(model="jev-1.13.0"), "native_model_mismatch"),
    "model missing": (lambda r: r.pop("model"), "native_model_mismatch"),
    "answers missing": (lambda r: r.pop("answers"), "native_response_invalid"),
    "answers is a list": (lambda r: r.update(answers=[]), "native_response_invalid"),
    "claim answer missing": (lambda r: r["answers"].pop("claim-1"), "native_answers_invalid"),
    "unknown extra question": (lambda r: r["answers"].update({"claim-9": choice_answer(S)}), "native_answers_invalid"),
    "advice answer missing": (lambda r: r["answers"].pop(native_jev.PROHIBITED_KEY), "native_answers_invalid"),
    "causality answer missing": (lambda r: r["answers"].pop(native_jev.CAUSALITY_KEY), "native_answers_invalid"),
    "noul where a choice was asked": (lambda r: r["answers"].update({"claim-0": {"type": "noul", "noul": 0.5}}), "native_answers_invalid"),
    "choice where a noul was asked": (lambda r: r["answers"].update({native_jev.PROHIBITED_KEY: choice_answer(S)}), "native_answers_invalid"),
    "score answer": (lambda r: r["answers"].update({"claim-0": {"type": "score", "score": 1.0}}), "native_answers_invalid"),
    "option missing": (lambda r: r["answers"]["claim-0"]["probabilities"].pop(I), "native_answers_invalid"),
    "option extra": (lambda r: r["answers"]["claim-0"]["probabilities"].update(other=0.0), "native_answers_invalid"),
    "sum too large": (lambda r: r["answers"]["claim-0"]["probabilities"].update({S: 0.5, C: 0.5, I: 0.5}), "native_answers_invalid"),
    "sum too small": (lambda r: r["answers"]["claim-0"]["probabilities"].update({S: 0.1, C: 0.1, I: 0.1}), "native_answers_invalid"),
    "probability nan": (lambda r: r["answers"]["claim-0"]["probabilities"].update({S: float("nan")}), "native_answers_invalid"),
    "probability infinite": (lambda r: r["answers"]["claim-0"]["probabilities"].update({S: float("inf")}), "native_answers_invalid"),
    "probability bool": (lambda r: r["answers"]["claim-0"]["probabilities"].update({S: True}), "native_answers_invalid"),
    "probability negative": (lambda r: r["answers"]["claim-0"]["probabilities"].update({S: -0.1}), "native_answers_invalid"),
    "probability text": (lambda r: r["answers"]["claim-0"]["probabilities"].update({S: "0.97"}), "native_answers_invalid"),
    "choice is not the argmax": (lambda r: r["answers"]["claim-0"].update(choice=I), "native_answers_invalid"),
    "choice unhashable": (lambda r: r["answers"]["claim-0"].update(choice=[S]), "native_answers_invalid"),
    "choice unknown": (lambda r: r["answers"]["claim-0"].update(choice="maybe"), "native_answers_invalid"),
    "choice missing": (lambda r: r["answers"]["claim-0"].pop("choice"), "native_answers_invalid"),
    "confidence missing": (lambda r: r["answers"]["claim-0"].pop("confidence"), "native_answers_invalid"),
    "confidence above one": (lambda r: r["answers"]["claim-0"].update(confidence=1.2), "native_answers_invalid"),
    "confidence text": (lambda r: r["answers"]["claim-0"].update(confidence="0.9"), "native_answers_invalid"),
    "confidence nan": (lambda r: r["answers"]["claim-0"].update(confidence=float("nan")), "native_answers_invalid"),
    "noul above one": (lambda r: r["answers"][native_jev.PROHIBITED_KEY].update(noul=1.2), "native_answers_invalid"),
    "noul text": (lambda r: r["answers"][native_jev.PROHIBITED_KEY].update(noul="0.5"), "native_answers_invalid"),
    "noul bool": (lambda r: r["answers"][native_jev.CAUSALITY_KEY].update(noul=True), "native_answers_invalid"),
    "noul missing": (lambda r: r["answers"][native_jev.CAUSALITY_KEY].pop("noul"), "native_answers_invalid"),
}


@pytest.mark.parametrize("change,code", BAD.values(), ids=BAD.keys())
def test_response_validation_is_strict_about_model_coverage_types_and_distributions(change, code):
    response = raw(OK)
    change(response)
    with pytest.raises(ValueError, match=code):
        native_jev.interpret(response, IDS, native_jev.MODEL)


def test_a_body_that_is_not_an_object_is_invalid():
    for body in ([], "text", None, 7):
        with pytest.raises(ValueError, match="native_response_invalid"):
            native_jev.interpret(body, IDS, native_jev.MODEL)


def mutated(change):
    response = raw(OK)
    change(response)
    return response


CASES = [
    ("wrong model", mutated(BAD["model alias"][0]), "native_model_mismatch", None),
    ("missing answer", mutated(BAD["claim answer missing"][0]), "native_answers_invalid", None),
    ("bad distribution", mutated(BAD["sum too large"][0]), "native_answers_invalid", None),
    ("not json", b"<html>gateway</html>", "native_response_invalid", {"responseText": "<html>gateway</html>", "httpStatus": 200}),
    ("json list", [1, 2, 3], "native_response_invalid", {"responseValue": [1, 2, 3], "httpStatus": 200}),
    ("empty object", {}, "native_response_invalid", None),
]


@pytest.mark.parametrize("name,payload,code,expected", CASES, ids=[c[0] for c in CASES])
def test_a_malformed_response_is_a_durable_receipt_fails_closed_and_is_never_retried(tmp_path, name, payload, code, expected):
    runner, request = prepare(tmp_path)
    luna, jev = attach(runner, jev=lambda req: (200, payload))
    result = runner.run(request.job_id)
    assert result.state == "failed" and result.failure.code == code and result.failure.stage == VERIFY
    assert result.artifacts == [] and result.resume_mode == "none"
    call = verify_call(result)
    assert call["state"] == "failed" and call["error"] == code and call["receivedAt"] is not None
    assert receipt(runner) == (expected if expected is not None else payload)
    assert len(luna) == len(jev) == 1
    assert runner.run(request.job_id).state == "failed" and runner.resume(request.job_id).state == "failed" and len(jev) == 1
    # A job row lost after the failure was recorded (the call row keeps its failed state and code) is refused the same way again.
    runner.store.db.execute("UPDATE jobs SET state='running',phase='outgoingcall.started',failure=NULL,resume_mode='unsent_only' WHERE job_id=?",
                            (request.job_id,))
    again = runner.resume(request.job_id)
    assert again.state == "failed" and again.failure.code == code and len(jev) == 1 and len(luna) == 1
    runner.store.close()


def test_a_kill_right_after_the_receipt_commit_still_leaves_the_exact_refusal_durable_and_sends_nothing(tmp_path, monkeypatch):
    payload, code = mutated(BAD["model alias"][0]), "native_model_mismatch"
    runner, request = prepare(tmp_path)
    luna, jev = attach(runner, jev=lambda req: (200, payload))
    receive = runner.store.receive

    def killed_after_the_verification_receipt_commit(attempt_id, reply, duration_ms):
        receive(attempt_id, reply, duration_ms)  # the receipt transaction is committed ...
        stage = runner.store.db.execute("SELECT stage FROM calls WHERE attempt_id=?", (attempt_id,)).fetchone()[0]
        if stage == VERIFY:  # (the generation receipt before it is stored normally)
            raise Interrupted()  # ... and the process dies before anything else can be written

    monkeypatch.setattr(runner.store, "receive", killed_after_the_verification_receipt_commit)
    with pytest.raises(Interrupted):
        runner.run(request.job_id)
    monkeypatch.setattr(runner.store, "receive", receive)
    state, error, content = runner.store.db.execute("SELECT state, error, content FROM calls WHERE stage=?", (VERIFY,)).fetchone()
    assert (state, error, content) == ("failed", code, "")  # the refusal is durable with the receipt, not in a later write
    assert receipt(runner) == payload and len(luna) == len(jev) == 1
    # A fresh process with no provider and no key recovers the same precise code and sends nothing.
    recovered = Runner(runner.store).resume(request.job_id)
    assert recovered.state == "failed" and recovered.failure.code == code and recovered.failure.stage == VERIFY
    assert len(luna) == len(jev) == 1 and verify_call(recovered)["error"] == code
    runner.store.close()


@pytest.mark.parametrize("status", [401, 429, 500, 529, 307])
def test_http_failures_are_definite_unretried_and_keep_the_generation_receipt(tmp_path, status):
    runner, request = prepare(tmp_path)
    luna, jev = attach(runner, jev=lambda req: (status, {"error": "SYNTHETIC-PROVIDER-ERROR-BODY"}))
    result = runner.run(request.job_id)
    assert result.state == "failed" and result.failure.code == f"provider_http_{status}" and result.failure.stage == VERIFY
    call = verify_call(result)
    assert call["state"] == "failed" and call["error"] == f"provider_http_{status}" and call["receivedAt"] is None
    assert len(luna) == len(jev) == 1 and result.artifacts == []
    assert runner.resume(request.job_id).state == "failed" and runner.run(request.job_id).state == "failed" and len(jev) == 1
    assert runner.store.db.execute("SELECT COUNT(*) FROM calls WHERE stage='document-summary' AND receipt IS NOT NULL").fetchone()[0] == 1
    assert "SYNTHETIC-PROVIDER-ERROR-BODY" not in json.dumps(result.wire(), ensure_ascii=False)
    runner.store.close()


def test_a_lost_native_response_is_unknown_and_never_resent(tmp_path):
    def lose(request):
        raise httpx.ReadTimeout("synthetic timeout")

    runner, request = prepare(tmp_path)
    luna, jev = attach(runner, jev=lose)
    result = runner.run(request.job_id)
    assert result.state == "reconciling" and result.failure.code == "provider_response_unknown" and verify_call(result)["state"] == "unknown"
    assert runner.run(request.job_id).state == "reconciling" and runner.resume(request.job_id).state == "reconciling"
    assert len(luna) == len(jev) == 1 and reserved(runner) == 2
    runner.store.close()


# ---- recipients and revocation ---------------------------------------------------------------------------------
GRANT_CASES = {
    "native recipient not granted": lambda r: {"recipients": [r[0]]},
    "generation recipient not granted": lambda r: {"recipients": [r[1]]},
    "protocol names only": lambda r: {"recipients": ["openai-compatible", "typesafe-native"]},
    "verification purpose not granted": lambda r: {"purposes": ["document-summary"]},
}


@pytest.mark.parametrize("change", GRANT_CASES.values(), ids=GRANT_CASES.keys())
def test_each_stage_needs_its_own_recipient_and_purpose_before_anything_is_sent(tmp_path, change):
    runner, request = prepare(tmp_path, grant=make_grant(**change(recipients())))
    luna, jev = attach(runner)
    result = runner.run(request.job_id)
    assert result.state == "failed" and result.failure.code == "source_purpose_or_recipient_denied"
    assert luna == [] and jev == [] and result.calls == [] and reserved(runner) == 0
    runner.store.close()


def revoke(runner):
    runner.store.register_grants([make_grant(enabled=False, revision="grant-revoked-2")])


def test_revocation_between_stages_never_reaches_the_verifier(tmp_path):
    runner, request = prepare(tmp_path)

    def generate_then_revoke(req):
        revoke(runner)
        return luna_respond(req)

    luna, jev = attach(runner, luna=generate_then_revoke)
    result = runner.run(request.job_id)
    assert result.state == "failed" and result.failure.code == "source_rights_unknown_or_denied" and result.failure.stage == VERIFY
    assert len(luna) == 1 and jev == [] and result.usage.provider_attempts == 1
    runner.store.close()


def test_revocation_while_the_native_call_is_in_flight_keeps_the_receipt_but_never_makes_the_generation_eligible(tmp_path):
    runner, request = prepare(tmp_path)

    def answer_then_revoked(req):
        revoke(runner)
        return jev_respond()(req)

    luna, jev = attach(runner, jev=answer_then_revoked)
    result = runner.run(request.job_id)
    assert result.state == "failed" and result.failure.code == "source_rights_unknown_or_denied"
    assert len(jev) == 1 and receipt(runner)["model"] == native_jev.MODEL
    assert [a.kind for a in result.artifacts] == [VERIFY]  # the generation artifact is never made
    runner.store.close()


# ---- budget -----------------------------------------------------------------------------------------------------
def test_a_failed_native_call_still_counts_against_the_one_ceiling(tmp_path):
    runner, request = prepare(tmp_path)
    luna, jev = attach(runner, jev=lambda req: (500, {}), ceiling=2)
    assert runner.run(request.job_id).failure.code == "provider_http_500" and reserved(runner) == 2
    other = request.model_copy(update={"job_id": "native-second"})
    runner.submit(other)
    blocked = runner.run(other.job_id)
    assert blocked.failure.code == "global_budget_exhausted" and len(luna) == 1 and reserved(runner) == 2
    runner.store.close()


def test_a_ceiling_of_one_pays_for_generation_only_and_the_verifier_is_never_called(tmp_path):
    runner, request = prepare(tmp_path)
    luna, jev = attach(runner, ceiling=1)
    result = runner.run(request.job_id)
    assert result.failure.code == "global_budget_exhausted" and result.failure.stage == VERIFY and result.resume_mode == "unsent_only"
    assert len(luna) == 1 and jev == [] and reserved(runner) == 1
    runner.store.close()


# ---- identity, cache and frozen configuration -----------------------------------------------------------------
def test_identity_binds_endpoint_thresholds_rubric_and_the_chosen_verifier(tmp_path, monkeypatch):
    runner, request = prepare(tmp_path)

    def digest_with(job_id):
        return runner.submit(request.model_copy(update={"job_id": job_id})).input_digest

    base = runner.get(request.job_id).input_digest
    assert digest_with("same-input") == base
    original = native_jev.prompt_version()
    with monkeypatch.context() as m:
        m.setenv("TYPESAFE_BASE_URL", "https://other-jev.invalid/v1")
        endpoint = digest_with("other-endpoint")
    with monkeypatch.context() as m:
        m.setattr(native_jev, "CHOICE_PROBABILITY", 0.95)
        assert native_jev.prompt_version() != original
        threshold = digest_with("other-threshold")
    with monkeypatch.context() as m:
        m.setattr(native_jev, "NOUL_FALSE", 0.05)
        noul = digest_with("other-noul")
    with monkeypatch.context() as m:
        m.setattr(native_jev, "TASK", native_jev.TASK + " Extra rule.")
        rubric = digest_with("other-rubric")
    with monkeypatch.context() as m:
        m.delenv("ZOOP_AI_VERIFY_PROVIDER")
        m.setenv("ZOOP_AI_VERIFY_MODEL", "synthetic-verifier")
        assert stage_config(VERIFY, "live").provider == "openai-compatible"  # chat stays the default verifier
        chat = digest_with("chat-verifier")
    assert len({base, endpoint, threshold, noul, rubric, chat}) == 6
    # The same input under the same identity is one cache entry; a changed threshold is a different one.
    assert runner.store.db.execute("SELECT COUNT(*) FROM cache WHERE input_digest IN (?,?)", (threshold, noul)).fetchone()[0] == 0
    runner.store.close()


@pytest.mark.parametrize("name,value,code", [
    ("TYPESAFE_VALIDATION_MODEL", "jev-latest", "native_model_unsupported"),
    ("TYPESAFE_VALIDATION_MODEL", "jev-preview", "native_model_unsupported"),
    ("TYPESAFE_VALIDATION_MODEL", "jev-1.13.0", "native_model_unsupported"),
    ("TYPESAFE_VALIDATION_MODEL", "", "stage_model_required"),
    ("ZOOP_AI_VERIFY_MODEL", "gpt-6-luna", "native_verify_stale_model_setting"),
    ("ZOOP_AI_VERIFY_REASONING_EFFORT", "high", "native_verify_stale_effort_setting"),
    ("ZOOP_AI_VERIFY_PROVIDER", "typesafe", "provider_unsupported"),
])
def test_native_configuration_fails_closed_at_submit_and_leaves_replay_and_other_stages_alone(tmp_path, monkeypatch, name, value, code):
    monkeypatch.setenv(name, value)
    with pytest.raises(ProviderError) as caught:
        stage_config(VERIFY, "live")
    assert caught.value.code == code
    assert stage_config(VERIFY, "replay").provider == "authored-replay" and stage_config(VERIFY, "replay").provider_revision == "authored-replay-1"
    assert stage_config("document-summary", "live").provider == "openai-compatible"
    runner = Runner(Store(tmp_path / "worker"))
    with pytest.raises(ProviderError) as refused:
        runner.submit(job())
    assert refused.value.code == code
    runner.store.close()


def test_the_frozen_configuration_decides_the_route_not_todays_environment(tmp_path, monkeypatch):
    runner, request = prepare(tmp_path)  # frozen: chat generation, native verification
    luna, jev = attach(runner)
    monkeypatch.delenv("ZOOP_AI_VERIFY_PROVIDER")
    monkeypatch.setenv("ZOOP_AI_VERIFY_MODEL", "synthetic-verifier")  # the environment now says: chat verifier
    result = runner.run(request.job_id)
    assert result.state == "ready" and len(jev) == 1
    assert [r["body"]["response_format"]["json_schema"]["name"] for r in luna] == ["document_summary"]
    runner.store.close()


def test_a_chat_frozen_job_is_never_sent_to_the_native_provider_and_nothing_is_paid_first(tmp_path, monkeypatch):
    monkeypatch.delenv("ZOOP_AI_VERIFY_PROVIDER")
    monkeypatch.setenv("ZOOP_AI_VERIFY_MODEL", "synthetic-verifier")
    runner, request = prepare(tmp_path)  # frozen: chat generation, chat verification
    luna, jev = attach(runner)  # ... but the native client is what is attached for verification
    result = runner.run(request.job_id)
    assert result.failure.code == "provider_configuration_changed"
    assert luna == [] and jev == [] and result.calls == [] and reserved(runner) == 0
    runner.store.close()


@pytest.mark.parametrize("drift", ["threshold", "rubric"])
def test_a_policy_change_after_submit_is_a_configuration_change_checked_before_generation_is_paid(tmp_path, monkeypatch, drift):
    runner, request = prepare(tmp_path)
    luna, jev = attach(runner)
    if drift == "threshold":
        monkeypatch.setattr(native_jev, "CHOICE_CONFIDENCE", 0.85)
    else:
        monkeypatch.setattr(native_jev, "CLAIM_QUESTION", native_jev.CLAIM_QUESTION + " Be brief.")
    result = runner.run(request.job_id)
    assert result.failure.code == "provider_configuration_changed" and luna == [] and jev == [] and reserved(runner) == 0
    runner.store.close()


def test_a_stored_native_receipt_is_recovered_without_any_provider(tmp_path, monkeypatch):
    runner, request = prepare(tmp_path)
    luna, jev = attach(runner)
    save = runner.store.save_artifact

    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic disk failure")

    monkeypatch.setattr(runner.store, "save_artifact", unavailable)
    before = runner.run(request.job_id)
    assert before.state == "persisting" and before.resume_mode == "save_only" and len(luna) == len(jev) == 1
    monkeypatch.setattr(runner.store, "save_artifact", save)
    after = Runner(runner.store).resume(request.job_id)  # no provider, no verifier, no key
    assert after.state == "ready" and len(luna) == len(jev) == 1 and after.usage.provider_attempts == 2
    assert Runner(runner.store).resume(request.job_id).artifact_ids == after.artifact_ids
    runner.store.close()


def test_the_native_client_refuses_cleartext_remote_endpoints_missing_keys_and_foreign_stages():
    with pytest.raises(ProviderError) as cleartext:
        NativeJevProvider(base_url="http://jev.example.test/v1", api_key=JEV_KEY)
    assert cleartext.value.code == "provider_requires_https"
    with pytest.raises(ProviderError) as keyless:
        NativeJevProvider(base_url=JEV_BASE, api_key="")
    assert keyless.value.code == "provider_key_required"
    NativeJevProvider(base_url="http://127.0.0.1:9/v1", api_key=JEV_KEY).close()
    provider = NativeJevProvider(base_url=JEV_BASE, api_key=JEV_KEY)
    assert provider.client.follow_redirects is False and not [h for h in provider.client.headers if h.lower().startswith("typesafe-")]
    config = stage_config(VERIFY, "live")
    with pytest.raises(ProviderError) as stage:
        provider.complete("document-summary", {}, config)
    assert stage.value.code == "native_stage_unsupported"
    with pytest.raises(ProviderError) as shape:
        provider.complete(VERIFY, {}, config)
    assert shape.value.code == "native_request_invalid" and provider.calls == 0
    provider.close()


# ---- the real CLI process against two loopback providers -------------------------------------------------------
@pytest.fixture
def servers():
    luna, jev = FakeServer(luna_respond), FakeServer(jev_respond())
    yield luna, jev
    luna.close()
    jev.close()


def cli_env(luna, jev, *, native=True, luna_key=LUNA_KEY, jev_key=JEV_KEY):
    """A complete, explicit child environment: nothing of this process's environment reaches the CLI."""
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(WORKER / "src"), "PYTHONDONTWRITEBYTECODE": "1",
           "ZOOP_AI_LIVE_ENABLED": "1", "ZOOP_AI_GLOBAL_MAX_CALLS": "10", "ZOOP_AI_BASE_URL": luna.base,
           "ZOOP_AI_DOCUMENT_SUMMARY_MODEL": "synthetic-generator", "ZOOP_AI_DOCUMENT_SENTIMENT_MODEL": "synthetic-generator"}
    if luna_key:
        env["ZOOP_AI_API_KEY"] = luna_key
    if native:
        env.update(ZOOP_AI_VERIFY_PROVIDER="typesafe-native", TYPESAFE_VALIDATION_MODEL=native_jev.MODEL, TYPESAFE_BASE_URL=jev.base)
        if jev_key:
            env["TYPESAFE_API_KEY"] = jev_key
    else:
        env["ZOOP_AI_VERIFY_MODEL"] = "synthetic-verifier"
    return env


def write_grants(tmp_path, luna, jev):
    grant = {**fixture("grants")["grants"][0],
             "recipients": ["openai-compatible:" + digest({"endpoint": luna.base}), "typesafe-native:" + native_revision(jev.base)]}
    path = tmp_path / "grants.json"
    path.write_text(json.dumps({"schemaVersion": SCHEMA_VERSION, "grants": [grant]}))
    return path


def cli(tmp_path, grants, command, data, env):
    done = subprocess.run([sys.executable, "-m", "zoop_ai.cli", command, "--state-dir", str(tmp_path / "ledger"), "--grants", str(grants)],
                          input=json.dumps(data, ensure_ascii=False), env=env, capture_output=True, text=True, timeout=60)
    return done.returncode, json.loads(done.stdout)


def ref(job_id):
    return {"schemaVersion": SCHEMA_VERSION, "jobId": job_id}


class Interrupted(BaseException):
    """A runtime process dying between two stages (not an Exception: nothing in the runner may absorb it)."""


def interrupted_after_generation(tmp_path, monkeypatch, luna, jev, grants, job_id):
    """Leave a registered live job where a process killed between stages would: a durable generation receipt, verification unsent."""
    for name, value in cli_env(luna, jev).items():
        if name.startswith(("ZOOP_AI_", "TYPESAFE_")):
            monkeypatch.setenv(name, value)
    store = Store(tmp_path / "ledger")
    store.register_grants([SourceGrant.model_validate(json.loads(grants.read_text())["grants"][0])])

    class Cut(Runner):
        def _call(self, request, stage, payload, config, fence):
            if stage == VERIFY:
                raise Interrupted()
            return super()._call(request, stage, payload, config, fence)

    chat = OpenAICompatibleProvider(base_url=luna.base, api_key=LUNA_KEY)
    native = NativeJevProvider(base_url=jev.base, api_key=JEV_KEY)
    runner = Cut(store, chat, verifier=native, live_enabled=True, max_calls=10)
    runner.submit(job(job_id))
    with pytest.raises(Interrupted):
        runner.run(job_id)
    chat.close()
    native.close()
    store.close()


def test_cli_routes_each_stage_to_its_own_endpoint_with_its_own_key_and_reads_back_without_keys(tmp_path, servers):
    luna, jev = servers
    grants, env = write_grants(tmp_path, luna, jev), cli_env(luna, jev)
    assert cli(tmp_path, grants, "submit", job("cli-native").wire(), env)[0] == 0
    code, result = cli(tmp_path, grants, "run", ref("cli-native"), env)
    assert code == 0 and result["state"] == "ready" and result["usage"]["providerAttempts"] == 2
    assert [r["path"] for r in luna.requests] == ["/v1/chat/completions"] and [r["path"] for r in jev.requests] == ["/v1/systemone"]
    assert luna.requests[0]["authorization"] == "Bearer " + LUNA_KEY and jev.requests[0]["authorization"] == "Bearer " + JEV_KEY
    assert JEV_KEY not in json.dumps(luna.requests) and LUNA_KEY not in json.dumps(jev.requests)
    call = next(c for c in result["calls"] if c["stage"] == VERIFY)
    assert call["config"]["provider"] == "typesafe-native" and call["usage"]["inputTokens"] == 321 and call["usage"]["outputTokens"] == 17
    no_keys = {k: v for k, v in env.items() if not k.endswith("_KEY")}
    code, again = cli(tmp_path, grants, "resume", ref("cli-native"), no_keys)
    assert code == 0 and again["artifactIds"] == result["artifactIds"] and len(luna.requests) == len(jev.requests) == 1


def test_cli_needs_only_the_key_of_the_stage_that_is_still_missing(tmp_path, servers, monkeypatch):
    luna, jev = servers
    grants, env = write_grants(tmp_path, luna, jev), cli_env(luna, jev)
    interrupted_after_generation(tmp_path, monkeypatch, luna, jev, grants, "cli-missing-key")
    assert len(luna.requests) == 1 and jev.requests == []
    # Only the generation key is present: the unsent verification needs the Jev key, so nothing is built and nothing is sent.
    code, refused = cli(tmp_path, grants, "run", ref("cli-missing-key"), {k: v for k, v in env.items() if k != "TYPESAFE_API_KEY"})
    assert code == 2 and refused["error"]["code"] == "provider_key_required" and jev.requests == []
    # Only the Jev key is present: generation is already a receipt, so its key is never needed.
    code, done = cli(tmp_path, grants, "run", ref("cli-missing-key"), {k: v for k, v in env.items() if k != "ZOOP_AI_API_KEY"})
    assert code == 0 and done["state"] == "ready" and done["usage"]["providerAttempts"] == 2
    assert len(luna.requests) == 1 and len(jev.requests) == 1


def test_cli_builds_clients_from_the_frozen_configuration_and_never_reroutes_a_stored_job(tmp_path, servers):
    luna, jev = servers
    grants = write_grants(tmp_path, luna, jev)
    assert cli(tmp_path, grants, "submit", job("frozen-native").wire(), cli_env(luna, jev))[0] == 0
    # Today's environment says chat verification and carries no Jev key: the stored job must not silently go to the chat verifier.
    code, refused = cli(tmp_path, grants, "run", ref("frozen-native"), cli_env(luna, jev, native=False))
    assert code == 2 and refused["error"]["code"] == "provider_key_required" and luna.requests == [] and jev.requests == []
    code, done = cli(tmp_path, grants, "run", ref("frozen-native"), cli_env(luna, jev))
    assert code == 0 and done["state"] == "ready" and len(luna.requests) == 1 and len(jev.requests) == 1

    assert cli(tmp_path, grants, "submit", job("frozen-chat").wire(), cli_env(luna, jev, native=False))[0] == 0
    # The reverse: a chat-frozen job stays on the chat verifier even though the environment now selects Jev.
    code, done = cli(tmp_path, grants, "run", ref("frozen-chat"), cli_env(luna, jev))
    assert code == 0 and done["state"] == "ready" and len(jev.requests) == 1
    assert [r["body"]["response_format"]["json_schema"]["name"] for r in luna.requests[1:]] == ["document_summary", "semantic_verification"]
