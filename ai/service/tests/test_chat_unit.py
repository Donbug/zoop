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

from zoop_ai_service.chat_stages import STAGE_DEADLINE, ChatStages, interpret
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
    return ChatStageRequest.model_validate({"schemaVersion": "zoop-ai-chat-1", "invocationId": invocation, "stage": stage, "mode": mode,
                                            "input": {"turns": [{"text": "q"}]}})


def result(invocation: str, stage: str = "chat-router", status: str = "succeeded", **extra: Any) -> dict[str, Any]:
    body = {"schemaVersion": "zoop-ai-chat-1", "invocationId": invocation, "stage": stage, "status": status,
            "answer": {"requirements": []} if status == "succeeded" else None,
            "failure": None if status == "succeeded" else {"code": "source_grant_denied", "sent": False, "unknown": False},
            "receipt": None}
    body.update(extra)
    return body


class Scripted:
    """Records what the stage service asked of the process and answers the scripted outcome."""

    def __init__(self, outcome=None):
        self.calls: list[tuple[dict[str, Any], float]] = []
        self.outcome = outcome
        self.hold: threading.Event | None = None

    def invoke(self, payload: dict[str, Any], deadline: float) -> Outcome:
        self.calls.append((payload, deadline))
        if self.hold is not None:
            self.hold.wait(5)
        if callable(self.outcome):
            return self.outcome(payload)
        return self.outcome


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


@pytest.mark.parametrize("outcome,status,code", [
    (Outcome("timeout"), 504, "stage_outcome_unknown"),
    (Outcome("abnormal", exit_code=-9), 502, "stage_outcome_unknown"),
    (Outcome("unavailable"), 503, "runtime_unavailable"),
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
