"""The chatbot model stage door without a child process: the exit-code interpretation and the stage service with a scripted process.

Configuration (all or nothing, child environments) and the real HTTP route with a stand-in `zoop-ai-chat` are in `test_chat_http.py`; the real
installed worker CLI is covered by `ai/worker/tests/test_chat_stages.py`.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from zoop_ai_service.chat_stages import PROBE_DEADLINE, STAGE_DEADLINE, ChatStages, interpret, interpret_probe
from zoop_ai_service.chat_wire import ChatStageRequest
from zoop_ai_service.config import ChatConfig, ServiceConfig
from zoop_ai_service.jobs import ApiError, Observation
from zoop_ai_service.runtime import Outcome


def config(tmp_path: Path, *, replay: bool = True) -> ServiceConfig:
    chat = ChatConfig(command=tmp_path / "zoop-ai-chat", state_dir=tmp_path / "chat", grants_path=tmp_path / "grants.json",
                      replay_path=tmp_path / "replay.json" if replay else None, live_available=False, child_env={})
    return ServiceConfig(principals=(), state_dir=tmp_path / "service", worker_state_dir=tmp_path / "worker", worker_command=tmp_path / "zoop-ai",
                         grants_path=tmp_path / "s1-grants.json", replay_path=None, port=8797, live_available=False, child_env={}, chat=chat)


def request(stage: str = "chat-router", *, mode: str = "replay", invocation: str = "job-00000001:1:router") -> ChatStageRequest:
    return ChatStageRequest.model_validate({"schemaVersion": "zoop-ai-chat-3", "invocationId": invocation, "stage": stage, "mode": mode,
                                            "input": {"turns": [{"text": "q"}]}})


RECEIPT = {"provider": "authored-replay", "providerRevision": "authored-replay-1", "model": "authored-synthetic-chat-router",
           "promptVersion": "zoop-jev-chat-router-0", "executionMode": "replay",
           "usage": {"inputTokens": None, "outputTokens": None, "cachedTokens": None, "reasoningTokens": None},
           "sentAt": "2026-10-23T00:00:00+00:00", "receivedAt": "2026-10-23T00:00:01+00:00"}


def result(invocation: str, stage: str = "chat-router", status: str = "succeeded", **extra: Any) -> dict[str, Any]:
    body = {"schemaVersion": "zoop-ai-chat-3", "invocationId": invocation, "stage": stage, "status": status,
            "answer": {"requirements": []} if status == "succeeded" else None,
            "failure": None if status == "succeeded" else {"code": "source_grant_denied", "sent": False, "unknown": False},
            "receipt": dict(RECEIPT) if status == "succeeded" else None}
    body.update(extra)
    return body


class Scripted:
    """Records what the stage service asked of the process and answers the scripted outcome."""

    def __init__(self, outcome=None, *, probe_outcome=None):
        self.calls: list[tuple[dict[str, Any], float]] = []
        self.probe_calls: list[float] = []
        self.outcome = outcome
        self.probe_outcome = probe_outcome
        self.hold: threading.Event | None = None

    def invoke(self, payload: dict[str, Any], deadline: float) -> Outcome:
        self.calls.append((payload, deadline))
        if self.hold is not None:
            self.hold.wait(5)
        if callable(self.outcome):
            return self.outcome(payload)
        return self.outcome

    def probe(self, deadline: float) -> Outcome:
        self.probe_calls.append(deadline)
        return self.probe_outcome


# ---- interpretation ----------------------------------------------------------------------------------------------------

def test_exit_codes_map_to_outcomes_and_anything_unexpected_is_abnormal():
    ok = json.dumps(result("p:job-00000001")).encode()
    failed = json.dumps(result("p:job-00000001", status="failed")).encode()
    assert interpret(0, ok).kind == "result"
    assert interpret(2, failed).kind == "result"
    assert interpret(64, b'{"error":"request_invalid"}') == Outcome("error", code="request_invalid", exit_code=64)
    for code, raw in [(2, ok), (0, failed), (1, ok), (64, b'{"error":"Bad Code"}'), (64, b'{"error":"x","more":1}'), (0, b"not json"),
                      (0, json.dumps({**result("p:x"), "schemaVersion": "zoop-ai-s1-1"}).encode()), (0, b"[]")]:
        assert interpret(code, raw).kind == "abnormal", (code, raw)


def test_probe_exit_codes_map_only_the_closed_health_envelope():
    reachable = b'{"schemaVersion":"zoop-ai-chat-3","mcp":"reachable"}'
    unreachable = b'{"schemaVersion":"zoop-ai-chat-3","mcp":"unreachable","reason":"mcp_timeout"}'
    assert interpret_probe(0, reachable).kind == "result"
    assert interpret_probe(2, unreachable).kind == "result"
    assert interpret_probe(64, b'{"error":"mcp_server_url_invalid"}') == Outcome(
        "error", code="mcp_server_url_invalid", exit_code=64)
    for code, raw in [(2, reachable), (0, unreachable), (1, reachable), (64, b'{"error":"Bad Code"}'),
                      (0, b'{"schemaVersion":"other","mcp":"reachable"}'), (0, b"[]"), (0, b"not json")]:
        assert interpret_probe(code, raw).kind == "abnormal", (code, raw)


# ---- the stage service ---------------------------------------------------------------------------------------------------

def test_the_child_sees_a_principal_bound_id_and_the_caller_gets_its_own_back(tmp_path):
    process = Scripted(lambda payload: Outcome("result", result=result(payload["invocationId"]), exit_code=0))
    stages = ChatStages(config(tmp_path), process)
    status, answer = stages.invoke("app", "chat-router", request(), Observation())
    sent, deadline = process.calls[0]
    assert sent["invocationId"] == "app:job-00000001:1:router" and deadline == STAGE_DEADLINE["chat-router"]
    assert status == 200 and answer.invocation_id == "job-00000001:1:router" and answer.status == "succeeded"


def test_a_stage_failure_is_a_200_outcome_not_a_transport_error(tmp_path):
    process = Scripted(lambda payload: Outcome("result", result=result(payload["invocationId"], status="failed"), exit_code=2))
    status, answer = ChatStages(config(tmp_path), process).invoke("app", "chat-router", request(), Observation())
    assert status == 200 and answer.failure.code == "source_grant_denied" and answer.failure.sent is False


def test_requests_that_cannot_run_start_no_child(tmp_path):
    process = Scripted()
    stages = ChatStages(config(tmp_path, replay=False), process)
    for stage, body, status, code in [("chat-answer", request(), 422, "invalid_request"),
                                      ("chat-router", request(), 409, "execution_unavailable")]:
        with pytest.raises(ApiError) as caught:
            stages.invoke("app", stage, body, Observation())
        assert (caught.value.status, caught.value.code) == (status, code)
    assert process.calls == []


@pytest.mark.parametrize("binding", [None, {}, {"invocationId": "another-job.1.verify"}])
def test_foreign_or_missing_verification_binding_starts_no_child(tmp_path, binding):
    process = Scripted()
    req = request("chat-verification").model_copy(update={"input": {"requestBinding": binding}})
    with pytest.raises(ApiError) as caught:
        ChatStages(config(tmp_path), process).invoke("app", "chat-verification", req, Observation())
    assert (caught.value.status, caught.value.code) == (422, "invalid_request")
    assert process.calls == []


def test_verification_binding_survives_principal_namespacing(tmp_path):
    req = request("chat-verification")
    binding = {"invocationId": req.invocation_id, "graphVersionId": "gv-new", "asOf": None}
    payload = {"requestBinding": binding, "sections": [], "citations": []}
    req = req.model_copy(update={"input": payload})
    process = Scripted(lambda sent: Outcome("result", result=result(sent["invocationId"], stage="chat-verification",
                        answer={"sections": []}), exit_code=0))
    status, answer = ChatStages(config(tmp_path), process).invoke("app", "chat-verification", req, Observation())
    assert status == 200 and answer.invocation_id == req.invocation_id
    assert process.calls[0][0]["invocationId"] == "app:" + req.invocation_id
    assert process.calls[0][0]["input"] == payload


@pytest.mark.parametrize("outcome,status,code", [
    (Outcome("timeout"), 504, "stage_outcome_unknown"),
    (Outcome("abnormal", exit_code=-9), 502, "stage_outcome_unknown"),
    (Outcome("unavailable"), 503, "runtime_unavailable"),
    (Outcome("unavailable", exit_code=0, started=True), 502, "stage_outcome_unknown"),
    (Outcome("unavailable", started=True), 502, "stage_outcome_unknown"),
    (Outcome("error", code="request_invalid", exit_code=64), 422, "invalid_request"),
    (Outcome("error", code="grant_registry_invalid", exit_code=64), 503, "service_configuration_invalid"),
    (Outcome("error", code="something_else", exit_code=64), 502, "stage_outcome_unknown"),
])
def test_a_child_that_may_have_sent_is_never_reported_as_not_sent(tmp_path, outcome, status, code):
    stages = ChatStages(config(tmp_path), Scripted(outcome))
    with pytest.raises(ApiError) as caught:
        stages.invoke("app", "chat-router", request(), Observation())
    assert (caught.value.status, caught.value.code) == (status, code)


def test_a_result_for_another_stage_or_an_unreadable_one_is_unknown(tmp_path):
    for bad in (lambda p: Outcome("result", result=result(p["invocationId"], stage="chat-answer"), exit_code=0),
                lambda p: Outcome("result", result={**result(p["invocationId"]), "status": "maybe"}, exit_code=0)):
        with pytest.raises(ApiError) as caught:
            ChatStages(config(tmp_path), Scripted(bad)).invoke("app", "chat-router", request(), Observation())
        assert caught.value.status == 502 and caught.value.code == "stage_outcome_unknown"


UNKNOWN_SENT = {"code": "provider_response_unknown", "sent": True, "unknown": True}


@pytest.mark.parametrize("change", [
    lambda r: r.update(invocationId="job-00000001:1:router"),                    # the caller's id without the principal prefix
    lambda r: r.update(invocationId="app:job-99999999:1:router"),                # another invocation
    lambda r: r.pop("invocationId"),
    lambda r: r["receipt"].update(executionMode="live"),                         # not the requested mode
    lambda r: r.update(receipt=None),                                            # a success without a receipt
    lambda r: r.update(failure=dict(UNKNOWN_SENT)),                              # a success with a failure
    lambda r: r.update(answer=None),
    lambda r: r.update(answer={"requirements": [], "debug": "x"}),               # an unknown key in the answer
    lambda r: r.update(answer={"requirements": [{"requirementId": "r1", "types": {"Q09": 0.5}, "capabilities": {},
                                                 "prohibitedAdvice": 0.0, "dependsOn": None}]}),
    lambda r: r.update(answer={"sections": [], "insufficientRequirementIds": [], "graphTargetIds": []}),  # another stage's answer
    lambda r: r.update(status="failed", answer=None, failure={"code": "x", "sent": False, "unknown": True}),  # unknown but not sent
    lambda r: r.update(status="failed", answer=None, failure={"code": "x", "sent": True, "unknown": False}, receipt=None),
    lambda r: r.update(status="failed", failure={"code": "x", "sent": False, "unknown": False}),  # a failure that carries an answer
])
def test_a_child_result_that_does_not_belong_to_the_request_or_contradicts_itself_is_unknown(tmp_path, change):
    def answer(payload):
        body = result(payload["invocationId"])
        change(body)
        return Outcome("result", result=body, exit_code=0)
    with pytest.raises(ApiError) as caught:
        ChatStages(config(tmp_path), Scripted(answer)).invoke("app", "chat-router", request(), Observation())
    assert (caught.value.status, caught.value.code) == (502, "stage_outcome_unknown")


def test_a_consistent_failed_result_with_a_receipt_passes_and_keeps_its_fate(tmp_path):
    def answer(payload):
        return Outcome("result", result=result(payload["invocationId"], status="failed", failure=dict(UNKNOWN_SENT),
                                                receipt=dict(RECEIPT)), exit_code=2)
    status, body = ChatStages(config(tmp_path), Scripted(answer)).invoke("app", "chat-router", request(), Observation())
    assert status == 200 and body.failure.unknown and body.receipt.execution_mode == "replay"
    assert body.invocation_id == "job-00000001:1:router"


# ---- the MCP preflight ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("health", [
    {"schemaVersion": "zoop-ai-chat-3", "mcp": "reachable"},
    {"schemaVersion": "zoop-ai-chat-3", "mcp": "unreachable", "reason": "mcp_connect_failed"},
])
def test_a_probe_relays_a_closed_health_answer_without_a_stage_invocation(tmp_path, health):
    process = Scripted(probe_outcome=Outcome("result", result=health, exit_code=0 if health["mcp"] == "reachable" else 2))
    seen = Observation()
    answer = ChatStages(config(tmp_path), process).probe_mcp(seen)
    expected = {**health, "reason": health.get("reason")}
    assert answer.wire() == expected and process.probe_calls == [PROBE_DEADLINE] and process.calls == []
    assert seen.runtime == [{"command": "probe-mcp", "kind": "result", "exit": process.probe_outcome.exit_code, "code": None}]


@pytest.mark.parametrize("outcome,status,code", [
    (Outcome("result", result={"schemaVersion": "zoop-ai-chat-3", "mcp": "unreachable"}, exit_code=2), 502, "probe_failed"),
    (Outcome("error", code="mcp_server_url_required", exit_code=64), 503, "service_configuration_invalid"),
    (Outcome("timeout"), 504, "probe_failed"),
    (Outcome("abnormal", exit_code=-9), 502, "probe_failed"),
    (Outcome("unavailable"), 503, "runtime_unavailable"),
    (Outcome("unavailable", started=True), 502, "probe_failed"),
])
def test_a_probe_failure_is_not_misreported_as_health(tmp_path, outcome, status, code):
    with pytest.raises(ApiError) as caught:
        ChatStages(config(tmp_path), Scripted(probe_outcome=outcome)).probe_mcp(Observation())
    assert (caught.value.status, caught.value.code) == (status, code)


HELD = {"responseId": "resp_1", "status": "approval_required", "answer": None, "mcpCalls": [],
        "approvalRequests": [{"approvalRequestId": "mcpr_1", "toolName": "company_read", "arguments": {"targets": ["KRX:000660"]}}]}
FINAL = {"responseId": "resp_2", "status": "completed", "approvalRequests": [], "mcpCalls": [{"toolName": "company_read", "failed": False}],
         "answer": {"sections": [], "insufficientRequirementIds": ["r1"], "graphTargetIds": []}}


@pytest.mark.parametrize("step", [HELD, FINAL])
def test_an_agent_step_is_relayed_with_its_own_deadline(tmp_path, step):
    process = Scripted(lambda p: Outcome("result", result=result(p["invocationId"], stage="chat-agent", answer=step), exit_code=0))
    status, body = ChatStages(config(tmp_path), process).invoke("app", "chat-agent", request("chat-agent"), Observation())
    assert status == 200 and body.answer.status == step["status"] and process.calls[0][1] == STAGE_DEADLINE["chat-agent"] == 33.0


@pytest.mark.parametrize("step", [
    {**HELD, "approvalRequests": []},                                            # held without requests
    {**HELD, "answer": FINAL["answer"]},                                         # held with an answer
    {**FINAL, "answer": None},                                                   # completed without an answer
    {**FINAL, "approvalRequests": HELD["approvalRequests"]},                     # completed with held calls
    {**HELD, "approvalRequests": [{**HELD["approvalRequests"][0], "toolName": "company.read"}]},
    {**HELD, "approved": True},                                                  # an unknown key
])
def test_a_self_contradicting_agent_step_is_never_a_200(tmp_path, step):
    process = Scripted(lambda p: Outcome("result", result=result(p["invocationId"], stage="chat-agent", answer=step), exit_code=0))
    with pytest.raises(ApiError) as caught:
        ChatStages(config(tmp_path), process).invoke("app", "chat-agent", request("chat-agent"), Observation())
    assert (caught.value.status, caught.value.code) == (502, "stage_outcome_unknown")


def test_no_slot_within_the_wait_is_busy_and_starts_nothing(tmp_path):
    process = Scripted(lambda payload: Outcome("result", result=result(payload["invocationId"]), exit_code=0))
    process.hold = threading.Event()
    stages = ChatStages(config(tmp_path), process, slots=1, slot_wait=0.1)
    first = threading.Thread(target=stages.invoke, args=("app", "chat-router", request(), Observation()))
    first.start()
    try:
        while not process.calls:
            pass
        with pytest.raises(ApiError) as caught:
            stages.invoke("app", "chat-router", request(invocation="job-00000002:1:router"), Observation())
        assert (caught.value.status, caught.value.code) == (503, "service_busy")
        assert len(process.calls) == 1
    finally:
        process.hold.set()
        first.join()


def test_a_probe_answers_while_every_stage_slot_is_held(tmp_path):
    # An agent step holding the only stage slot must not make a reachable MCP server look unproven.
    reachable = Outcome("result", result={"schemaVersion": "zoop-ai-chat-3", "mcp": "reachable"}, exit_code=0)
    process = Scripted(lambda payload: Outcome("result", result=result(payload["invocationId"]), exit_code=0),
                       probe_outcome=reachable)
    process.hold = threading.Event()
    stages = ChatStages(config(tmp_path), process, slots=1, slot_wait=0.1)
    first = threading.Thread(target=stages.invoke, args=("app", "chat-router", request(), Observation()))
    first.start()
    try:
        while not process.calls:
            pass
        assert stages.probe_mcp(Observation()).mcp == "reachable"
    finally:
        process.hold.set()
        first.join()
