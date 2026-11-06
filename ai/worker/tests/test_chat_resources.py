"""Resource permits exercised at the real invocation/ledger and CLI boundaries with synthetic provider responses."""
from __future__ import annotations

import copy
import io
import json
import sqlite3

import httpx
import pytest

from zoop_ai import chat_cli, chat_resources
from zoop_ai.chat_contracts import ChatGrantRegistry, StageRequest
from zoop_ai.chat_runtime import ChatLedger, LiveSender, ReplaySender, invoke, request_digest, stage_config
from zoop_ai.contracts import canonical, digest
from chat_resource_support import PUBLIC, configured_chat, resources
import test_chat_agent as agent

LIVE = {**PUBLIC, "ZOOP_AI_CHAT_LIVE_ENABLED": "1", "ZOOP_AI_CHAT_MAX_CALLS": "40", "ZOOP_AI_API_KEY": "synthetic-resource-key"}
INPUT = {"turns": [{"text": "HBM의 작동 원리를 자세히 설명해줘"}], "branches": [
    {"requirementId": "r1", "label": "HBM 원리", "general": True, "noneFound": False, "items": [], "evidence": []}], "maxCitations": 20}
ANSWER = {"sections": [{"basis": "general_knowledge", "text": "메모리의 구조와 원리를 설명한다. " * 200,
                        "requirementIds": ["r1"], "evidenceIds": []}], "insufficientRequirementIds": [], "graphTargetIds": []}


def packet(stage="chat-answer", **changes):
    payload = copy.deepcopy(INPUT) if stage == "chat-answer" else agent.agent_input()
    value = {"schemaVersion": "zoop-ai-chat-6", "invocationId": "resource-job-1:stage", "stage": stage,
             "mode": "live", "input": payload, "resources": resources(stage, **changes)}
    return StageRequest.model_validate(value)


def raw_answer(stage="chat-answer", output=50000, reasoning=36000):
    answer = ANSWER if stage == "chat-answer" else agent.answer()
    raw = agent.final_response(answer)
    raw["usage"] = {"input_tokens": 10000, "output_tokens": output,
                    "output_tokens_details": {"reasoning_tokens": reasoning}}
    return raw


def execute(req, tmp_path, raw, env=None, registry=None):
    calls = []
    def send(request):
        calls.append(json.loads(request.content))
        if isinstance(raw, Exception):
            raise raw
        return httpx.Response(200, json=raw)
    actual_env = LIVE if env is None else env
    result = invoke(req, state_dir=tmp_path, registry=registry,
                    sender=LiveSender(actual_env, httpx.MockTransport(send)), env=actual_env)
    return result, calls


@pytest.mark.parametrize("stage", ["chat-answer", "chat-agent"])
@pytest.mark.parametrize("effort,total", [(value, 64000) for value in chat_resources.EFFORTS] + [("high", 128000)])
def test_resolved_effort_and_output_allocation_reaches_responses_and_accepts_visible_budget(tmp_path, stage, effort, total):
    req = packet(stage, reasoningEffort=effort, maxOutputTokens=total)
    raw = raw_answer(stage)
    result, calls = execute(req, tmp_path, raw)
    assert result.status == "succeeded", result
    body, = calls
    assert body["reasoning"] == {"effort": effort} and body["max_output_tokens"] == total
    assert result.receipt.usage.output_tokens == 50000 and result.receipt.usage.reasoning_tokens == 36000
    assert result.resource_binding == req.binding()
    if stage == "chat-answer":
        assert body["store"] is False and "tools" not in body
        assert len(result.answer["sections"][0]["text"]) > 2000
    else:
        assert body["store"] is True and body["tools"][0]["require_approval"] == "always"


@pytest.mark.parametrize("stage", ["chat-answer", "chat-agent"])
@pytest.mark.parametrize("case,code", [("visible", "output_budget_exceeded"), ("incomplete", "output_budget_exceeded"),
                                      ("missing", "provider_usage_invalid"), ("inconsistent", "provider_usage_invalid"),
                                      ("refusal", "answer_refused")])
def test_received_failures_keep_raw_receipts_and_are_never_sent_again(tmp_path, stage, case, code):
    raw = raw_answer(stage)
    if case == "visible":
        raw["usage"]["output_tokens_details"]["reasoning_tokens"] = 33000
    elif case == "incomplete":
        raw.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
    elif case == "missing":
        raw["usage"].pop("output_tokens_details")
    elif case == "inconsistent":
        raw["usage"]["output_tokens_details"]["reasoning_tokens"] = 50001
    else:
        raw["output"] = [{"type": "message", "content": [{"type": "refusal", "refusal": "refused"}]}]
    req = packet(stage)
    result, calls = execute(req, tmp_path, raw)
    assert result.failure.code == code and result.failure.sent and not result.failure.unknown
    assert result.receipt is not None and len(calls) == 1
    if case == "missing":
        assert result.receipt.usage.reasoning_tokens is None
    with sqlite3.connect(tmp_path / "chat.sqlite3") as db:
        stored, receipt = db.execute("SELECT raw,receipt FROM chat_invocations").fetchone()
        assert json.loads(stored) == raw and json.loads(receipt)["receivedAt"] is not None
    repeated, sent = execute(req, tmp_path, raw, env={})
    assert repeated.wire() == result.wire() and sent == []


@pytest.mark.parametrize("case,code", [("allocation", "chat_resource_policy_invalid"),
                                      ("fingerprint", "chat_runtime_contract_mismatch"),
                                      ("legacy", "chat_legacy_effort_configuration")])
def test_resource_refusals_echo_requested_binding_before_transport(tmp_path, case, code):
    req = packet()
    value = req.wire()
    env = dict(LIVE)
    if case == "allocation":
        value["resources"]["providerTimeoutMs"] -= 1
    elif case == "fingerprint":
        value["resources"]["runtimeFingerprint"] = "0" * 64
        identity = {key: val for key, val in value["resources"].items() if key != "allocationDigest"}
        value["resources"]["allocationDigest"] = digest({"schemaVersion": "zoop-chat-resource-allocation-1", "stage": req.stage,
                                                        "mode": req.mode, "resources": identity})
    else:
        env["ZOOP_AI_CHAT_ANSWER_REASONING_EFFORT"] = "high"
    req = StageRequest.model_validate(value)
    result, calls = execute(req, tmp_path, raw_answer(), env)
    assert result.failure.code == code and not result.failure.sent and not result.failure.unknown
    assert result.resource_binding == req.binding() and calls == []
    with sqlite3.connect(tmp_path / "chat.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM chat_invocations").fetchone()[0] == 0


def test_unknown_outcome_holds_the_ledger_wide_fuse_and_allocation_identity(tmp_path):
    req = packet()
    unknown, calls = execute(req, tmp_path, httpx.ReadTimeout("synthetic"))
    assert unknown.failure.unknown and unknown.failure.sent and len(calls) == 1
    repeated, sent = execute(req, tmp_path, raw_answer(), env={})
    assert repeated.wire() == unknown.wire() and sent == []
    changed = req.wire()
    changed["resources"] = resources("chat-answer", maxOutputTokens=128000)
    conflict, sent = execute(StageRequest.model_validate(changed), tmp_path, raw_answer())
    assert conflict.failure.code == "invocation_conflict" and not conflict.failure.sent and sent == []
    fresh = req.model_copy(update={"invocation_id": "resource-job-2:stage"})
    fused, sent = execute(fresh, tmp_path, raw_answer(), env={**LIVE, "ZOOP_AI_CHAT_MAX_CALLS": "1"})
    assert fused.failure.code == "chat_budget_exhausted" and not fused.failure.sent and sent == []


def test_delivery_contract_cutover_refuses_continuation_and_preserves_exact_history(tmp_path, monkeypatch):
    with monkeypatch.context() as old:
        old.setattr(agent.chat_agent, "PROMPT_REVISION", "zoop-chat-agent-resource-1")
        old.setattr(agent.chat_agent, "MCP_DELIVERY",
                    {**agent.chat_agent.MCP_DELIVERY, "schemaVersion": "chat-tool/v1", "serverVersion": "1"})
        first = agent.request(agent.agent_input())
        recorded, sends = execute(first, tmp_path,
                                  agent.approval_response(("mcpr_1", "company_read",
                                                           {"targets": ["KRX:000660"], "requirementIds": ["r1"]})))
    assert recorded.status == "succeeded" and len(sends) == 1
    with sqlite3.connect(tmp_path / "chat.sqlite3") as db:
        before = db.execute("SELECT * FROM chat_invocations").fetchall()
    follow = agent.request(agent.agent_input(continuation=agent.continuation(("mcpr_1", True))),
                           invocation="job-1:a1:agent-2")
    refused, sends = execute(follow, tmp_path, agent.final_response(agent.answer()))
    assert refused.failure.code == "chat_runtime_contract_mismatch" and not refused.failure.sent and sends == []
    repeated, sends = execute(first, tmp_path, agent.final_response(agent.answer()), env={})
    assert repeated.wire() == recorded.wire() and sends == []
    with sqlite3.connect(tmp_path / "chat.sqlite3") as db:
        assert db.execute("SELECT * FROM chat_invocations").fetchall() == before


def test_schema5_history_is_ledger_first_exact_and_fresh_work_is_refused(tmp_path):
    old = StageRequest.model_validate({"schemaVersion": "zoop-ai-chat-5", "invocationId": "historical-job:answer",
                                      "stage": "chat-answer", "mode": "replay", "input": INPUT})
    outcome = {"schemaVersion": "zoop-ai-chat-5", "invocationId": old.invocation_id, "stage": old.stage,
               "status": "failed", "answer": None, "failure": {"code": "provider_response_unknown", "sent": True, "unknown": True},
               "receipt": {"provider": "authored-replay", "providerRevision": "authored-replay-1", "model": "authored-synthetic-chat-answer",
                           "promptVersion": "historical-prompt", "executionMode": "replay", "usage": {"inputTokens": None,
                           "outputTokens": None, "cachedTokens": None, "reasoningTokens": None},
                           "sentAt": "2026-11-01T00:00:00+00:00", "receivedAt": None}}
    serialized = json.dumps(outcome, ensure_ascii=False, indent=1)
    ledger = ChatLedger(tmp_path)
    ledger.db.execute("INSERT INTO chat_invocations (invocation_id,stage,mode,input_digest,status,result,raw,created_at,updated_at,request_digest,receipt) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (old.invocation_id, old.stage, old.mode, "historical-identity", "unknown", serialized, "historical-raw",
                       "historical-created", "historical-updated", request_digest(old), canonical(outcome["receipt"])))
    before = ledger.db.execute("SELECT * FROM chat_invocations").fetchall()
    ledger.close()
    stored = invoke(old, state_dir=tmp_path, registry=None, sender=ReplaySender(None), env={})
    assert stored.wire() == outcome
    fresh = invoke(old.model_copy(update={"invocation_id": "historical-job:fresh"}), state_dir=tmp_path,
                   registry=None, sender=ReplaySender(None), env={})
    assert fresh.failure.code == "chat_runtime_contract_mismatch" and not fresh.failure.sent
    collision = packet().model_copy(update={"invocation_id": old.invocation_id})
    rejected, calls = execute(collision, tmp_path, raw_answer())
    assert rejected.failure.code == "invocation_conflict" and not rejected.failure.sent and calls == []
    with sqlite3.connect(tmp_path / "chat.sqlite3") as db:
        assert db.execute("SELECT * FROM chat_invocations").fetchall() == before


def test_capability_cli_is_content_free_and_fingerprints_only_runtime(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("must not be read"))
    assert chat_cli.main(["capabilities"]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["runtimeFingerprint"] == digest(value["runtime"])
    assert list(tmp_path.iterdir()) == []
    changed = chat_resources.capabilities({**PUBLIC, "ZOOP_AI_API_KEY": "synthetic-key", "ZOOP_AI_CHAT_MAX_CALLS": "3"})
    assert changed["runtimeFingerprint"] == value["runtimeFingerprint"]
    assert changed["configurationErrors"]["chat-answer"] is None
    assert "synthetic-key" not in canonical(changed)


def test_direct_only_runtime_admits_answers_without_an_agent_endpoint(tmp_path):
    env = {key: value for key, value in LIVE.items() if key != "ZOOP_AI_CHAT_MCP_SERVER_URL"}
    manifest = chat_resources.capabilities(env)
    assert manifest["configurationErrors"]["chat-agent"] == "mcp_server_url_required"
    assert manifest["runtime"]["stages"]["chat-agent"]["mcpServerRevision"] is None
    assert manifest["configurationErrors"]["chat-answer"] is None
    req = packet(env=env)
    result, calls = execute(req, tmp_path, raw_answer(), env)
    assert result.status == "succeeded" and result.answer == ANSWER and len(calls) == 1


def test_shared_korean_quotes_fit_expanded_context_without_a_utf8_byte_cap(tmp_path):
    quotes = [{"evidenceId": "ev-" + f"{index:064x}", "sourceId": "synthetic-korean",
               "quote": "가" * 1999 + chr(0xAC00 + index)} for index in range(20)]
    payload = {"turns": [{"text": "자료별 핵심을 정리해줘"}], "maxCitations": 20,
               "branches": [{"requirementId": f"r{index}", "label": f"자료 {index}", "general": False,
                             "noneFound": False, "items": [], "evidence": quotes} for index in range(1, 7)]}
    req = packet().model_copy(update={"input": payload})
    assert len(canonical(req.parsed().wire()).encode("utf-8")) > 720000
    assert req.resources.luna.max_input_tokens == 512000
    answer = {"sections": [{"basis": "evidence_grounded", "text": "합성 자료의 첫 번째 인용문을 확인했다.",
                            "requirementIds": ["r1"], "evidenceIds": [quotes[0]["evidenceId"]]}],
              "insufficientRequirementIds": [f"r{index}" for index in range(2, 7)], "graphTargetIds": []}
    registry = ChatGrantRegistry.model_validate({"schemaVersion": "zoop-ai-chat-1", "grants": [{
        "grantId": "synthetic-korean", "revision": "1", "sourceId": "synthetic-korean", "enabled": True, "rights": "known",
        "allowedOperations": ["model-send"], "recipients": [stage_config("chat-answer", "live", LIVE).recipient()],
        "purposes": ["chat-answer"], "evidence": ["synthetic"], "expiresAt": None}]})
    result, calls = execute(req, tmp_path, agent.final_response(answer), registry=registry)
    assert result.status == "succeeded" and result.answer == answer
    sent = json.loads(calls[0]["input"][0]["content"])
    assert [len(branch["evidence"]) for branch in sent["branches"]] == [20] * 6
