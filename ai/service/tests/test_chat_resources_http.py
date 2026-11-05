"""Capability authentication and resource-bound reply validation through the real FastAPI HTTP server."""
import copy

import pytest

from chat_resource_fixtures import FIXTURE, allocation
from support import Workspace
from test_chat_http import ChatStub, URL, body, succeeded
from test_chat_unit import Scripted, config, request, result
from zoop_ai_service.chat_stages import ChatStages
from zoop_ai_service.jobs import Observation
from zoop_ai_service.runtime import Outcome
from zoop_ai_service.wire import ErrorEnvelope

CAPABILITIES = "/internal/v1/chat-runtime-capabilities"


def test_capabilities_require_existing_scope_and_start_only_content_free_command(tmp_path, start):
    ws = Workspace(tmp_path / "ws")
    stub = ChatStub(tmp_path / "chat")
    stub.answer(FIXTURE["capabilities"])
    service = start(workspace=ws, env=stub.env())
    assert service.request("GET", CAPABILITIES, as_=None).status_code == 401
    assert service.request("GET", CAPABILITIES, as_="reader").status_code == 403
    assert service.request("GET", CAPABILITIES + "?job=private", as_="chatter").status_code == 422
    assert service.request("GET", CAPABILITIES, as_="chatter", headers={"Idempotency-Key": "unexpected"}).status_code == 422
    assert stub.calls() == []
    response = service.request("GET", CAPABILITIES, as_="chatter")
    assert response.status_code == 200 and response.json() == FIXTURE["capabilities"]
    call, = stub.calls()
    assert call["argv"] == ["capabilities"] and call["stdin"] == "{}"
    assert list(stub.state.iterdir()) == []


@pytest.mark.parametrize("corruption", ["digest", "time", "extra", "stage"])
def test_incompatible_installed_capabilities_are_configuration_errors(tmp_path, start, corruption):
    ws = Workspace(tmp_path / "ws")
    stub = ChatStub(tmp_path / "chat")
    value = copy.deepcopy(FIXTURE["capabilities"])
    if corruption == "digest":
        value["runtimeFingerprint"] = "0" * 64
    elif corruption == "time":
        value["runtime"]["timeModel"]["workerProcessMarginMs"] = 3000
    elif corruption == "extra":
        value["runtime"]["extra"] = "unexpected"
    else:
        value["runtime"]["stages"]["chat-answer"]["api"] = "systemone"
    stub.answer(value)
    service = start(workspace=ws, env=stub.env())
    response = service.request("GET", CAPABILITIES, as_="chatter")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_configuration_invalid"
    assert response.json()["error"]["runtimeCode"] == "chat_runtime_contract_mismatch"


@pytest.mark.parametrize("corruption", ["unequal", "missing", "malformed", "old-schema"])
def test_an_invalid_resource_binding_is_explicitly_unknown_over_http(tmp_path, start, corruption):
    ws = Workspace(tmp_path / "ws")
    stub = ChatStub(tmp_path / "chat")
    value = succeeded()
    if corruption == "unequal":
        value["resourceBinding"]["allocationDigest"] = "0" * 64
    elif corruption == "missing":
        value.pop("resourceBinding")
    elif corruption == "malformed":
        value["resourceBinding"]["allocationDigest"] = "invalid"
    else:
        value["schemaVersion"] = "zoop-ai-chat-5"
    stub.answer(value)
    service = start(workspace=ws, env=stub.env())
    payload = body(input={"turns": [{"text": "HBM이 뭐야?"}], "requirements": [
        {"requirementId": "r1", "text": "HBM이 뭐야?", "explicit": True}], "capabilities": []})
    response = service.request("POST", URL, as_="chatter", body=payload, headers={"Idempotency-Key": payload["invocationId"]})
    assert response.status_code == 502 and response.json()["error"]["code"] == "stage_outcome_unknown"
    error = response.json()["error"]
    assert error["runtimeCode"] == "chat_resource_binding_mismatch" and error["retryable"] is False
    ErrorEnvelope.model_validate(response.json())


@pytest.mark.parametrize("stage,deadline", [("chat-router", 20.0), ("chat-verification", 50.0),
                                           ("chat-answer", 605.0), ("chat-agent", 605.0)])
def test_stage_child_deadlines_derive_from_the_dispatched_permit(tmp_path, stage, deadline):
    req = request(stage)
    if stage == "chat-verification":
        req = req.model_copy(update={"input": {"requestBinding": {"invocationId": req.invocation_id}}})
    process = Scripted(lambda payload: Outcome("result", result=result(payload["invocationId"], stage=stage, status="failed"), exit_code=2))
    status, reply = ChatStages(config(tmp_path), process).invoke("app", stage, req, Observation())
    assert status == 200 and reply.failure.sent is False
    assert process.calls[0][1] == deadline
    assert process.calls[0][0]["resources"] == allocation(stage)["resources"]
