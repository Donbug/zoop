"""Chatbot agent step (`chat-agent`): the Luna Responses request with the ZOOP MCP tool, approval requests, continuations, the
final answer, the token's redaction and the ledger. No network: live steps go to an in-process `httpx.MockTransport`."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from zoop_ai import chat_agent
from zoop_ai.chat_contracts import AgentInput, StageRequest
from zoop_ai.chat_runtime import LiveSender, ReplaySender, invoke, request_digest, request_identity, stage_config
from zoop_ai.provider import ProviderError

EV1 = "ev-" + "1" * 64
TOKEN = "zmcp1.k1.eyJqb2IiOiJqb2ItMSJ9.c2lnbmF0dXJlLXN5bnRoZXRpYw"
URL = "https://api.zoop.example/mcp"
LIVE = {"ZOOP_AI_CHAT_LIVE_ENABLED": "1", "ZOOP_AI_CHAT_MAX_CALLS": "5", "ZOOP_AI_API_KEY": "luna-key-synthetic",
        "ZOOP_AI_CHAT_AGENT_MODEL": "gpt-6-luna", "ZOOP_AI_CHAT_MCP_SERVER_URL": URL}
# The recipient the application checked the MCP results' send grants for: the live agent stage's own.
RECIPIENT = stage_config("chat-agent", "live", LIVE).recipient()


def agent_input(**change: Any) -> dict[str, Any]:
    payload = {"turns": [{"text": "SK하이닉스와 삼성전자의 관계와 HBM이 뭔지 알려줘"}],
               "requirements": [{"requirementId": "r1", "label": "SK하이닉스와 삼성전자의 관계", "general": False,
                                 "targets": ["KRX:000660", "KRX:005930"]},
                                {"requirementId": "r2", "label": "HBM — 개념 설명", "general": True}],
               "mcp": {"authorization": TOKEN, "allowedTools": ["company_read", "graph_path_read"], "recipient": RECIPIENT},
               "maxCitations": 20}
    payload.update(change)
    return payload


def continuation(*decisions: tuple[str, bool], previous: str = "resp_1") -> dict[str, Any]:
    return {"previousResponseId": previous,
            "decisions": [{"approvalRequestId": rid, "approve": ok} for rid, ok in decisions]}


def request(payload: dict[str, Any], *, mode: str = "live", invocation: str = "job-1:a1:agent-1") -> StageRequest:
    return StageRequest.model_validate({"schemaVersion": "zoop-ai-chat-2", "invocationId": invocation, "stage": "chat-agent",
                                        "mode": mode, "input": payload})


def approval_response(*requests: tuple[str, str, dict[str, Any]], echo_token: bool = True) -> dict[str, Any]:
    output: list[dict[str, Any]] = [
        {"type": "mcp_list_tools", "id": "mcpl_1", "server_label": "zoop", "tools": []},
        {"type": "reasoning", "id": "rs_1", "summary": []}]
    output += [{"type": "mcp_approval_request", "id": rid, "server_label": "zoop", "name": name,
                "arguments": json.dumps(args)} for rid, name, args in requests]
    raw = {"id": "resp_1", "object": "response", "status": "completed", "model": "gpt-6-luna-2026-09-01", "output": output,
           "usage": {"input_tokens": 900, "output_tokens": 60, "input_tokens_details": {"cached_tokens": 0},
                     "output_tokens_details": {"reasoning_tokens": 40}}}
    if echo_token:
        raw["tools"] = [{"type": "mcp", "server_label": "zoop", "server_url": URL, "authorization": TOKEN,
                         "require_approval": "always"}]
    return raw


def final_response(answer: dict[str, Any], *, calls: list[dict[str, Any]] | None = None, status: str = "completed",
                   response_id: str = "resp_2") -> dict[str, Any]:
    output = list(calls or [])
    output.append({"type": "message", "id": "msg_1", "role": "assistant",
                   "content": [{"type": "output_text", "text": json.dumps(answer, ensure_ascii=False)}]})
    return {"id": response_id, "object": "response", "status": status, "model": "gpt-6-luna", "output": output,
            "usage": {"input_tokens": 2400, "output_tokens": 300, "output_tokens_details": {"reasoning_tokens": 120}}}


def answer(**change: Any) -> dict[str, Any]:
    value = {"sections": [{"basis": "evidence_grounded", "text": "SK하이닉스는 삼성전자와 HBM 공급 관계로 이어진다.",
                           "requirementIds": ["r1"], "evidenceIds": [EV1]},
                          {"basis": "general_knowledge", "text": "HBM은 고대역폭 메모리다.", "requirementIds": ["r2"],
                           "evidenceIds": []}],
             "insufficientRequirementIds": [], "graphTargetIds": ["KRX:000660"]}
    value.update(change)
    return value


class Endpoint:
    def __init__(self, *responses: Any):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any], str]] = []

    def transport(self) -> httpx.MockTransport:
        def handle(req: httpx.Request) -> httpx.Response:
            self.calls.append((req.url.path, json.loads(req.content), req.headers.get("authorization", "")))
            reply = self.responses.pop(0)
            return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)
        return httpx.MockTransport(handle)


def run(req: StageRequest, tmp: Path, endpoint: Endpoint | None = None, env: dict[str, str] | None = None):
    env = LIVE if env is None else env
    return invoke(req, state_dir=tmp, registry=None, sender=LiveSender(env, endpoint.transport() if endpoint else None),
                  env=env)


# ---- request -----------------------------------------------------------------------------------------------------------------

def test_the_first_step_sends_the_question_with_the_zoop_mcp_tool_held_for_approval():
    body = chat_agent.build_request(AgentInput.model_validate(agent_input()), "gpt-6-luna", "medium", URL)
    assert body["model"] == "gpt-6-luna" and body["store"] is True and body["reasoning"] == {"effort": "medium"}
    assert body["max_output_tokens"] == 8000
    assert body["instructions"] == chat_agent.PROMPT and "previous_response_id" not in body
    # The official remote MCP authentication: the raw grant in the tool's own `authorization`, no headers, no scheme prefix.
    assert body["tools"] == [{"type": "mcp", "server_label": "zoop", "server_url": URL, "authorization": TOKEN,
                              "allowed_tools": ["company_read", "graph_path_read"], "require_approval": "always"}]
    assert body["text"]["format"]["type"] == "json_schema" and body["text"]["format"]["strict"] is True
    question = json.loads(body["input"][0]["content"])
    assert body["input"][0]["role"] == "user"
    assert [r["requirementId"] for r in question["requirements"]] == ["r1", "r2"] and question["maxCitations"] == 20
    assert question["requirements"][0]["targets"] == ["KRX:000660", "KRX:005930"] and question["requirements"][1]["targets"] == []
    assert TOKEN not in body["input"][0]["content"]


def test_a_continuation_resumes_the_stored_response_with_only_the_applications_decisions():
    payload = AgentInput.model_validate(agent_input(continuation=continuation(("mcpr_1", True), ("mcpr_2", False))))
    body = chat_agent.build_request(payload, "gpt-6-luna", "medium", URL)
    assert body["previous_response_id"] == "resp_1" and body["store"] is True
    assert body["input"] == [{"type": "mcp_approval_response", "approval_request_id": "mcpr_1", "approve": True},
                             {"type": "mcp_approval_response", "approval_request_id": "mcpr_2", "approve": False}]
    # Instructions, tools with their authorization and format are sent again: a continuation does not inherit them.
    assert body["tools"][0]["require_approval"] == "always" and body["instructions"] == chat_agent.PROMPT
    assert body["tools"][0]["authorization"] == TOKEN and body["tools"][0]["server_url"] == URL


@pytest.mark.parametrize("change", [
    # A caller never names the server: the URL is the operator's setting.
    {"mcp": {"serverUrl": "https://attacker.example/mcp", "authorization": TOKEN, "allowedTools": ["company_read"],
             "recipient": RECIPIENT}},
    {"mcp": {"authorization": "short", "allowedTools": ["company_read"], "recipient": RECIPIENT}},
    {"mcp": {"authorization": TOKEN, "allowedTools": [], "recipient": RECIPIENT}},
    {"mcp": {"authorization": TOKEN, "allowedTools": ["company.read"], "recipient": RECIPIENT}},
    {"mcp": {"authorization": TOKEN, "allowedTools": ["a", "a"], "recipient": RECIPIENT}},
    # The recipient the application checked the results for is required, and is a recipient name.
    {"mcp": {"authorization": TOKEN, "allowedTools": ["company_read"]}},
    {"mcp": {"authorization": TOKEN, "allowedTools": ["company_read"], "recipient": "openai compatible"}},
    {"continuation": {"previousResponseId": "resp_1", "decisions": []}},
    {"continuation": continuation(("mcpr_1", True), ("mcpr_1", False))},
    {"requirements": [{"requirementId": "r1", "label": "a", "general": False},
                      {"requirementId": "r1", "label": "b", "general": False}]},
    {"requirements": [{"requirementId": "r1", "label": "a", "general": False, "targets": ["KRX 000660"]}]},
])
def test_an_invalid_step_input_is_refused(change):
    with pytest.raises(ValueError):
        AgentInput.model_validate(agent_input(**change))


def test_the_grant_token_never_enters_an_identity():
    first = request(agent_input())
    other_token = request(agent_input(mcp={**agent_input()["mcp"], "authorization": TOKEN + "x"}))
    other_tools = request(agent_input(mcp={**agent_input()["mcp"], "allowedTools": ["company_read"]}))
    config = stage_config("chat-agent", "replay")
    assert request_identity(first, config) == request_identity(other_token, config)
    assert request_digest(first) == request_digest(other_token)
    assert request_identity(first, config) != request_identity(other_tools, config)


# ---- live steps --------------------------------------------------------------------------------------------------------------

def test_a_step_that_stops_at_approval_requests_relays_them_and_never_stores_the_token(tmp_path):
    endpoint = Endpoint(approval_response(("mcpr_1", "company_read", {"targets": ["KRX:000660"]}),
                                          ("mcpr_2", "graph_path_read", {"targets": ["KRX:000660", "KRX:005930"]})))
    result = run(request(agent_input()), tmp_path, endpoint)

    assert result.status == "succeeded", result
    step = result.answer
    assert step["status"] == "approval_required" and step["responseId"] == "resp_1" and step["answer"] is None
    assert step["approvalRequests"] == [
        {"approvalRequestId": "mcpr_1", "toolName": "company_read", "arguments": {"targets": ["KRX:000660"]}},
        {"approvalRequestId": "mcpr_2", "toolName": "graph_path_read", "arguments": {"targets": ["KRX:000660", "KRX:005930"]}}]
    path, body, authorization = endpoint.calls[0]
    assert path.endswith("/responses") and authorization == "Bearer luna-key-synthetic"
    assert body["tools"][0]["authorization"] == TOKEN and body["tools"][0]["server_url"] == URL
    assert result.receipt.model == "gpt-6-luna-2026-09-01" and result.receipt.usage.reasoning_tokens == 40
    assert result.receipt.usage.input_tokens == 900 and result.receipt.usage.cached_tokens == 0

    stored = sqlite3.connect(tmp_path / "chat.sqlite3").execute("SELECT raw, result, request_digest FROM chat_invocations")
    assert all(TOKEN not in (column or "") for row in stored for column in row)


def test_a_provider_that_could_not_reach_the_mcp_server_is_mcp_unreachable(tmp_path):
    for ledger in ("a", "b", "c"):
        (tmp_path / ledger).mkdir()
    # The provider's 424 (it could not list the server's tools): a definite failure the application counts for its circuit.
    refused = run(request(agent_input()), tmp_path / "a", Endpoint(httpx.Response(
        424, json={"error": {"message": "Error retrieving tool list from MCP server: 'zoop'", "type": "external_connector_error"}})))
    assert refused.status == "failed" and refused.failure.code == "mcp_unreachable"
    assert refused.failure.sent is True and refused.failure.unknown is False

    # A tool listing that failed inside a response: the provider never reached the tools either.
    failed_listing = {"id": "resp_1", "object": "response", "status": "completed", "model": "gpt-6-luna",
                      "output": [{"type": "mcp_list_tools", "id": "mcpl_1", "server_label": "zoop", "tools": [],
                                  "error": "Error retrieving tool list from MCP server"}],
                      "usage": {"input_tokens": 100, "output_tokens": 0}}
    listed = run(request(agent_input()), tmp_path / "b", Endpoint(failed_listing))
    assert listed.status == "failed" and listed.failure.code == "mcp_unreachable"

    # Another provider error stays what it was: only a failed connection counts.
    other = run(request(agent_input()), tmp_path / "c", Endpoint(httpx.Response(500, json={"error": {}})))
    assert other.failure.code == "provider_http_500"


def test_a_continuation_step_ends_with_the_final_answer_and_the_calls_the_provider_made(tmp_path):
    calls = [{"type": "mcp_call", "id": "mcp_1", "server_label": "zoop", "name": "company_read",
              "arguments": "{\"targets\":[\"KRX:000660\"]}", "output": "{}", "error": None},
             {"type": "mcp_call", "id": "mcp_2", "server_label": "zoop", "name": "graph_path_read",
              "arguments": "{}", "output": None, "error": "call_not_approved"}]
    endpoint = Endpoint(final_response(answer(), calls=calls))
    result = run(request(agent_input(continuation=continuation(("mcpr_1", True), ("mcpr_2", False))),
                         invocation="job-1:a1:agent-2"), tmp_path, endpoint)

    assert result.status == "succeeded", result
    step = result.answer
    assert step["status"] == "completed" and step["responseId"] == "resp_2" and step["approvalRequests"] == []
    assert step["answer"]["sections"][0]["evidenceIds"] == [EV1]
    assert step["mcpCalls"] == [{"toolName": "company_read", "failed": False}, {"toolName": "graph_path_read", "failed": True}]
    assert endpoint.calls[0][1]["previous_response_id"] == "resp_1"


@pytest.mark.parametrize("raw, code", [
    (approval_response(("mcpr_1", "portfolio_scope_read", {})), "agent_tool_not_allowed"),
    ({**approval_response(), "output": [{"type": "mcp_approval_request", "id": "mcpr_1", "server_label": "other",
                                         "name": "company_read", "arguments": "{}"}]}, "agent_server_unknown"),
    ({**approval_response(), "output": [{"type": "web_search_call", "id": "ws_1"}]}, "agent_output_unexpected"),
    ({**approval_response(), "output": [{"type": "mcp_approval_request", "id": "mcpr_1", "server_label": "zoop",
                                         "name": "company_read", "arguments": "[1]"}]}, "agent_arguments_invalid"),
    (final_response(answer(), status="incomplete"), "agent_incomplete"),
    ({**final_response(answer(), status="incomplete"), "incomplete_details": {"reason": "max_output_tokens"}},
     "output_budget_exceeded"),
    ({**final_response(answer()), "usage": {"input_tokens": 100, "output_tokens": 3001,
                                            "output_tokens_details": {"reasoning_tokens": 1000}}}, "output_budget_exceeded"),
    (final_response(answer(sections=[{"basis": "general_knowledge", "text": "x", "requirementIds": ["r9"],
                                      "evidenceIds": []}])), "answer_requirement_unknown"),
    (final_response({"sections": "nope"}), "answer_schema_invalid"),
    ({**final_response(answer()), "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]},
     "answer_refused"),
    ({**approval_response(("mcpr_1", "company_read", {})),
      "output": approval_response(("mcpr_1", "company_read", {}))["output"] + final_response(answer())["output"]},
     "agent_response_invalid"),
    ({**final_response(answer()), "id": "bad id"}, "agent_response_invalid"),
])
def test_a_step_the_runtime_does_not_understand_is_a_definite_failure_after_sending(tmp_path, raw, code):
    result = run(request(agent_input()), tmp_path, Endpoint(raw))
    assert result.status == "failed" and result.failure.code == code
    assert result.failure.sent and not result.failure.unknown


def test_the_citation_budget_holds_for_the_final_answer(tmp_path):
    result = run(request(agent_input(maxCitations=0)), tmp_path, Endpoint(final_response(answer())))
    assert result.failure.code == "answer_budget_invalid"


def test_a_step_is_sent_once_and_the_same_id_with_other_decisions_is_a_conflict(tmp_path):
    endpoint = Endpoint(final_response(answer()))
    payload = agent_input(continuation=continuation(("mcpr_1", True)))
    first = run(request(payload), tmp_path, endpoint)
    again = run(request(payload), tmp_path, Endpoint())
    other = run(request(agent_input(continuation=continuation(("mcpr_1", False)))), tmp_path, Endpoint())
    assert first.status == again.status == "succeeded" and len(endpoint.calls) == 1
    assert other.failure.code == "invocation_conflict" and not other.failure.sent


def test_a_timeout_after_sending_is_unknown_and_never_resent(tmp_path):
    class Timeout(httpx.BaseTransport):
        def handle_request(self, request):
            raise httpx.ReadTimeout("synthetic")

    result = invoke(request(agent_input()), state_dir=tmp_path, registry=None, sender=LiveSender(LIVE, Timeout()), env=LIVE)
    assert result.failure.code == "provider_response_unknown" and result.failure.unknown
    again = run(request(agent_input()), tmp_path, Endpoint())
    assert again.failure.unknown


@pytest.mark.parametrize("env, code", [
    ({**LIVE, "ZOOP_AI_CHAT_AGENT_MODEL": ""}, "stage_model_required"),
    ({**LIVE, "ZOOP_AI_CHAT_AGENT_MODEL": "gpt-6"}, "answer_model_unsupported"),
    ({**LIVE, "ZOOP_AI_CHAT_AGENT_REASONING_EFFORT": "high"}, "reasoning_effort_unsupported"),
    ({k: v for k, v in LIVE.items() if k != "ZOOP_AI_CHAT_LIVE_ENABLED"}, "chat_live_disabled"),
])
def test_live_agent_configuration_is_pinned_and_gated(tmp_path, env, code):
    endpoint = Endpoint()
    result = run(request(agent_input()), tmp_path, endpoint, env)
    assert result.failure.code == code and not result.failure.sent and not endpoint.calls


def test_the_agent_configuration_pins_luna_at_medium():
    config = stage_config("chat-agent", "live", LIVE)
    assert (config.provider, config.model, config.reasoning_effort) == ("openai-compatible", "gpt-6-luna", "medium")
    with pytest.raises(ProviderError):
        stage_config("chat-agent", "live", {**LIVE, "ZOOP_AI_CHAT_AGENT_MODEL": "gpt-5"})


# ---- replay ------------------------------------------------------------------------------------------------------------------

def test_an_authored_replay_step_matches_its_input_whatever_the_token(tmp_path):
    config = stage_config("chat-agent", "replay")
    fixture = tmp_path / "replay.json"
    fixture.write_text(json.dumps({"schemaVersion": "zoop-ai-chat-2", "recordingKind": "authored-test", "responses": [
        {"stage": "chat-agent", "inputDigest": request_identity(request(agent_input(mcp={**agent_input()["mcp"], "recipient": "authored-replay"}),
                                                mode="replay"), config),
         "response": {**approval_response(("mcpr_1", "company_read", {"targets": ["KRX:000660"]})),
                      "model": "authored-synthetic-chat-agent"}}]}), encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    rotated = agent_input(mcp={**agent_input()["mcp"], "authorization": TOKEN + "rotated", "recipient": "authored-replay"})
    result = invoke(request(rotated, mode="replay"), state_dir=state, registry=None, sender=ReplaySender(fixture))
    assert result.status == "succeeded" and result.answer["approvalRequests"][0]["approvalRequestId"] == "mcpr_1"
    assert result.receipt.execution_mode == "replay"


@pytest.mark.parametrize("mode,named", [
    # The application checked its results for another endpoint's recipient than this runtime would send to.
    ("live", "openai-compatible:" + "0" * 64),
    ("live", "authored-replay"),
    ("replay", RECIPIENT),
])
def test_a_step_for_another_recipient_than_the_stages_own_is_never_sent(tmp_path, mode, named):
    endpoint = Endpoint()
    payload = agent_input(mcp={**agent_input()["mcp"], "recipient": named})
    if mode == "live":
        result = run(request(payload), tmp_path, endpoint)
    else:
        fixture = tmp_path / "replay.json"
        fixture.write_text(json.dumps({"schemaVersion": "zoop-ai-chat-2", "recordingKind": "authored-test",
                                       "responses": []}), encoding="utf-8")
        result = invoke(request(payload, mode="replay"), state_dir=tmp_path, registry=None, sender=ReplaySender(fixture))
    assert result.status == "failed" and result.failure.code == "mcp_recipient_mismatch"
    assert result.failure.sent is False and result.receipt is None
    assert endpoint.calls == []


def test_the_recipient_is_checked_here_and_never_sent_to_the_provider():
    body = chat_agent.build_request(AgentInput.model_validate(agent_input()), "gpt-6-luna", "medium", URL)
    assert RECIPIENT not in json.dumps(body)


def test_redaction_keeps_everything_but_echoed_credentials():
    raw = approval_response(("mcpr_1", "company_read", {}))
    kept = chat_agent.redact(raw)
    assert kept["tools"][0]["authorization"] == chat_agent.REDACTED and kept["output"] == raw["output"]
    assert raw["tools"][0]["authorization"] == TOKEN, "the original is not changed"
    assert chat_agent.redact({"choices": []}) == {"choices": []}


@pytest.mark.parametrize("url", [
    "http://api.zoop.example/mcp", "https://user:pw@api.zoop.example/mcp", "https://api.zoop.example@attacker.example/mcp",
    "https://api.zoop.example/mcp?next=https://attacker.example", "https://api.zoop.example/mcp#x",
    "https://api.zoop.example:8443/mcp", "https://api.zoop.example", "https:///mcp", "https://api.zoop.example/m cp", "",
])
def test_only_a_plain_https_operator_url_is_a_server_url(url):
    with pytest.raises(ValueError):
        chat_agent.server_url(url)


def test_the_server_url_is_canonical():
    assert chat_agent.server_url(" HTTPS://API.Zoop.Example:443/mcp ") == "https://api.zoop.example/mcp"


@pytest.mark.parametrize("env, code", [
    ({k: v for k, v in LIVE.items() if k != "ZOOP_AI_CHAT_MCP_SERVER_URL"}, "mcp_server_url_required"),
    ({**LIVE, "ZOOP_AI_CHAT_MCP_SERVER_URL": "https://attacker.example/mcp?x=1"}, "mcp_server_url_invalid"),
])
def test_a_live_step_without_a_valid_operator_url_sends_nothing(tmp_path, env, code):
    endpoint = Endpoint()
    result = run(request(agent_input()), tmp_path, endpoint, env)
    assert result.failure.code == code and not result.failure.sent and not endpoint.calls


def test_the_operator_url_is_part_of_the_live_configuration():
    config = stage_config("chat-agent", "live", LIVE)
    assert config.mcp_server_url == URL and config.wire()["mcpServerUrl"] == URL
    assert "mcpServerUrl" not in stage_config("chat-answer", "live", {**LIVE, "ZOOP_AI_CHAT_ANSWER_MODEL": "gpt-6-luna"}).wire()
    assert stage_config("chat-agent", "replay").mcp_server_url is None
