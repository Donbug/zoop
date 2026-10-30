"""The chatbot model stage door over a REAL service process (uvicorn on 127.0.0.1) and a test-owned stand-in for `zoop-ai-chat`, plus its all-or-nothing
configuration. The stand-in records the argv, stdin and environment the service gave it and answers what a test scripted, so this proves the transport
(fixed argv, the chat child environment and where the keys go, auth, envelope validation, principal binding, status mapping). The real worker CLI is in
`ai/worker/tests/test_chat_stages.py`."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from support import Workspace
from zoop_ai_service.config import ConfigError, load

URL = "/internal/v1/chat-stages/chat-router"
PROBE_URL = "/internal/v1/chat-mcp-health"
STUB = '''#!__PYTHON__
import json, os, sys
ROOT = __ROOT__
raw = sys.stdin.read()
with open(ROOT + "/calls.jsonl", "a") as handle:
    handle.write(json.dumps({"argv": sys.argv[1:], "stdin": raw, "env": dict(os.environ)}) + "\\n")
behavior = json.load(open(ROOT + "/behavior.json"))
out = behavior["output"]
if isinstance(out, dict) and "invocationId" in out:
    out["invocationId"] = json.loads(raw)["invocationId"]
print(json.dumps(out))
sys.exit(behavior.get("exit", 0))
'''


class ChatStub:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.command = root / "zoop-ai-chat"
        self.command.write_text(STUB.replace("__PYTHON__", sys.executable).replace("__ROOT__", repr(str(root))), encoding="utf-8")
        os.chmod(self.command, 0o755)
        self.state = root / "chat-state"
        self.grants = root / "chat-grants.json"
        self.grants.write_text(json.dumps({"schemaVersion": "zoop-ai-chat-1", "grants": []}), encoding="utf-8")
        self.replay = root / "chat-replay.json"
        self.replay.write_text(json.dumps({"schemaVersion": "zoop-ai-chat-3", "recordingKind": "authored-test", "responses": []}), encoding="utf-8")
        self.answer(succeeded())

    def answer(self, output: Any, exit_code: int = 0) -> None:
        (self.root / "behavior.json").write_text(json.dumps({"output": output, "exit": exit_code}), encoding="utf-8")

    def env(self, **extra: str) -> dict[str, str]:
        return {"ZOOP_AI_SERVICE_CHAT_COMMAND": str(self.command), "ZOOP_AI_CHAT_STATE_DIR": str(self.state),
                "ZOOP_AI_SERVICE_CHAT_GRANTS": str(self.grants), "ZOOP_AI_SERVICE_CHAT_REPLAY": str(self.replay), **extra}

    def calls(self) -> list[dict[str, Any]]:
        path = self.root / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


RECEIPT = {"provider": "authored-replay", "providerRevision": "authored-replay-1", "model": "authored-synthetic-chat-router",
           "promptVersion": "zoop-jev-chat-router-0", "executionMode": "replay",
           "usage": {"inputTokens": None, "outputTokens": None, "cachedTokens": None, "reasoningTokens": None},
           "sentAt": "2026-10-23T00:00:00+00:00", "receivedAt": "2026-10-23T00:00:01+00:00"}


def succeeded(status: str = "succeeded") -> dict[str, Any]:
    return {"schemaVersion": "zoop-ai-chat-3", "invocationId": "x", "stage": "chat-router", "status": status,
            "answer": {"requirements": []} if status == "succeeded" else None,
            "failure": None if status == "succeeded" else {"code": "chat_live_disabled", "sent": False, "unknown": False},
            "receipt": dict(RECEIPT) if status == "succeeded" else None}


def body(invocation: str = "job-00000001:1:chat-router", **change: Any) -> dict[str, Any]:
    value = {"schemaVersion": "zoop-ai-chat-3", "invocationId": invocation, "stage": "chat-router", "mode": "replay",
             "input": {"turns": [{"text": "HBM이 뭐야?"}]}}
    value.update(change)
    return value


# ---- configuration ---------------------------------------------------------------------------------------------------------

def test_the_group_is_all_or_nothing_and_the_keys_reach_only_an_open_chat_child(tmp_path):
    ws = Workspace(tmp_path / "ws")
    stub = ChatStub(tmp_path / "chat")
    assert load(ws.env()).chat is None
    with pytest.raises(ConfigError) as incomplete:
        load(ws.env(ZOOP_AI_SERVICE_CHAT_COMMAND=str(stub.command)))
    assert incomplete.value.reason == "chat_group_incomplete"

    keys = {"ZOOP_AI_API_KEY": "luna-key-synthetic-000000000000", "TYPESAFE_API_KEY": "jev-key-synthetic-0000000000000",
            "ZOOP_AI_CHAT_ANSWER_MODEL": "gpt-6-luna", "ZOOP_AI_CHAT_JEV_MODEL": "jev-1.14.0",
            "ZOOP_AI_CHAT_AGENT_MODEL": "gpt-6-luna", "ZOOP_AI_CHAT_AGENT_REASONING_EFFORT": "medium",
            "ZOOP_AI_CHAT_MCP_SERVER_URL": "https://api.zoop.example/mcp"}
    closed = load(ws.env(**stub.env(**keys))).chat
    assert closed is not None and not closed.live_available
    assert "ZOOP_AI_API_KEY" not in closed.child_env and "TYPESAFE_API_KEY" not in closed.child_env
    assert closed.child_env["ZOOP_AI_CHAT_ANSWER_MODEL"] == "gpt-6-luna"
    assert closed.child_env["ZOOP_AI_CHAT_AGENT_MODEL"] == "gpt-6-luna"
    assert closed.child_env["ZOOP_AI_CHAT_AGENT_REASONING_EFFORT"] == "medium"
    assert closed.child_env["ZOOP_AI_CHAT_MCP_SERVER_URL"] == "https://api.zoop.example/mcp"

    config = load(ws.env(**stub.env(**keys, ZOOP_AI_CHAT_LIVE_ENABLED="1", ZOOP_AI_CHAT_MAX_CALLS="3")))
    assert config.chat.live_available and config.chat.child_env["TYPESAFE_API_KEY"] == keys["TYPESAFE_API_KEY"]
    # No other child gets them: the S1 child keeps its own environment without the S1 live gate.
    assert "TYPESAFE_API_KEY" not in config.child_env and "ZOOP_AI_CHAT_LIVE_ENABLED" not in config.child_env


def test_the_chat_ledger_root_and_files_must_be_private_and_are_never_repaired(tmp_path):
    ws = Workspace(tmp_path / "ws")
    stub = ChatStub(tmp_path / "chat")
    stub.state.mkdir(mode=0o700)
    os.chmod(stub.state, 0o750)
    with pytest.raises(ConfigError) as shared:
        load(ws.env(**stub.env()))
    assert (shared.value.field, shared.value.reason) == ("ZOOP_AI_CHAT_STATE_DIR", "state_dir_not_private")
    assert stub.state.stat().st_mode & 0o777 == 0o750, "an existing root is refused, not chmod-ed"

    os.chmod(stub.state, 0o700)
    ledger = stub.state / "chat.sqlite3"
    ledger.write_bytes(b"")
    os.chmod(ledger, 0o644)
    with pytest.raises(ConfigError) as readable:
        load(ws.env(**stub.env()))
    assert readable.value.reason == "ledger_not_private"
    os.chmod(ledger, 0o600)
    assert load(ws.env(**stub.env())).chat is not None

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    link = tmp_path / "linked-state"
    link.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ConfigError) as linked:
        load(ws.env(**stub.env(ZOOP_AI_CHAT_STATE_DIR=str(link))))
    # A symlinked root is refused by the path check before the privacy check (which also looks at the link itself, never its target).
    assert (linked.value.field, linked.value.reason) == ("ZOOP_AI_CHAT_STATE_DIR", "symlinked_component")


def test_bad_chat_settings_refuse_to_start(tmp_path):
    ws = Workspace(tmp_path / "ws")
    stub = ChatStub(tmp_path / "chat")
    stub.grants.write_text(json.dumps({"schemaVersion": "zoop-ai-s1-1", "grants": []}), encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load(ws.env(**stub.env()))
    assert (caught.value.field, caught.value.reason) == ("ZOOP_AI_SERVICE_CHAT_GRANTS", "schema_invalid")
    stub.grants.write_text(json.dumps({"schemaVersion": "zoop-ai-chat-1", "grants": []}), encoding="utf-8")
    with pytest.raises(ConfigError) as overlap:
        load(ws.env(**stub.env(ZOOP_AI_CHAT_STATE_DIR=str(ws.state / "chat"))))
    assert overlap.value.reason == "chat_roots_overlap"
    with pytest.raises(ConfigError) as ceiling:
        load(ws.env(**stub.env(ZOOP_AI_CHAT_MAX_CALLS="many")))
    assert ceiling.value.field == "ZOOP_AI_CHAT_MAX_CALLS"


# ---- HTTP --------------------------------------------------------------------------------------------------------------------

def test_without_the_group_the_route_answers_409_after_authentication(start):
    service = start()
    assert service.request("POST", URL, as_="chatter", body=body(), headers={"Idempotency-Key": body()["invocationId"]}).status_code == 409
    assert service.request("POST", URL, as_=None, body=body()).status_code == 401
    assert service.request("POST", URL, as_="reader", body=body()).status_code == 403
    assert service.request("GET", PROBE_URL, as_="chatter").status_code == 409
    assert service.request("GET", PROBE_URL, as_=None).status_code == 401
    assert service.request("GET", PROBE_URL, as_="reader").status_code == 403


def test_the_content_free_probe_runs_with_fixed_argv_and_returns_reachability(tmp_path, start):
    ws = Workspace(tmp_path / "ws")
    stub = ChatStub(tmp_path / "chat")
    service = start(workspace=ws, env=stub.env())

    stub.answer({"schemaVersion": "zoop-ai-chat-3", "mcp": "reachable"})
    reachable = service.request("GET", PROBE_URL, as_="chatter")
    assert reachable.status_code == 200 and reachable.json() == {"schemaVersion": "zoop-ai-chat-3", "mcp": "reachable", "reason": None}
    call = stub.calls()[0]
    assert call["argv"] == ["probe-mcp"] and json.loads(call["stdin"]) == {}
    assert "ZOOP_AI_API_KEY" not in call["env"] and "TYPESAFE_API_KEY" not in call["env"]

    stub.answer({"schemaVersion": "zoop-ai-chat-3", "mcp": "unreachable", "reason": "mcp_timeout"}, exit_code=2)
    unreachable = service.request("GET", PROBE_URL, as_="chatter")
    assert unreachable.status_code == 200 and unreachable.json()["reason"] == "mcp_timeout"

    unexpected = service.request("GET", PROBE_URL + "?extra=1", as_="chatter")
    assert unexpected.status_code == 422 and len(stub.calls()) == 2


def test_probe_configuration_and_abnormal_results_are_transport_errors(tmp_path, start):
    ws = Workspace(tmp_path / "ws")
    stub = ChatStub(tmp_path / "chat")
    service = start(workspace=ws, env=stub.env())

    stub.answer({"error": "mcp_server_url_invalid"}, exit_code=64)
    configured = service.request("GET", PROBE_URL, as_="chatter")
    assert configured.status_code == 503 and configured.json()["error"]["code"] == "service_configuration_invalid"
    assert configured.json()["error"]["runtimeCode"] == "mcp_server_url_invalid"

    stub.answer({"schemaVersion": "zoop-ai-chat-3", "mcp": "unreachable"}, exit_code=2)
    invalid = service.request("GET", PROBE_URL, as_="chatter")
    assert invalid.status_code == 502 and invalid.json()["error"]["code"] == "probe_failed"


def test_a_stage_runs_once_with_fixed_argv_a_bound_id_and_the_chat_environment(tmp_path, start):
    ws = Workspace(tmp_path / "ws")
    stub = ChatStub(tmp_path / "chat")
    service = start(workspace=ws, env=stub.env())
    key = body()["invocationId"]
    answered = service.request("POST", URL, as_="chatter", body=body(), headers={"Idempotency-Key": key})
    assert answered.status_code == 200, answered.text
    assert answered.json()["invocationId"] == key and answered.json()["status"] == "succeeded"
    call = stub.calls()[0]
    assert call["argv"] == ["invoke", "--state-dir", str(stub.state), "--grants", str(stub.grants), "--replay", str(stub.replay)]
    assert json.loads(call["stdin"])["invocationId"] == f"chatter:{key}"
    assert "ZOOP_AI_API_KEY" not in call["env"] and "TYPESAFE_API_KEY" not in call["env"]

    stub.answer(succeeded("failed"), exit_code=2)
    failed = service.request("POST", URL, as_="chatter", body=body("job-00000002:1:chat-router"),
                             headers={"Idempotency-Key": "job-00000002:1:chat-router"})
    assert failed.status_code == 200 and failed.json()["failure"]["code"] == "chat_live_disabled"


def test_envelope_key_and_stage_mismatches_never_start_a_child(tmp_path, start):
    ws = Workspace(tmp_path / "ws")
    stub = ChatStub(tmp_path / "chat")
    service = start(workspace=ws, env=stub.env())
    key = body()["invocationId"]
    cases = [(URL, body(), {"Idempotency-Key": "other-key-0001"}),
             (URL, {**body(), "extra": 1}, {"Idempotency-Key": key}),
             ("/internal/v1/chat-stages/chat-answer", body(), {"Idempotency-Key": key}),
             ("/internal/v1/chat-stages/chat-unknown", body(), {"Idempotency-Key": key})]
    for url, payload, headers in cases:
        assert service.request("POST", url, as_="chatter", body=payload, headers=headers).status_code == 422, (url, payload)
    assert stub.calls() == []


def test_output_over_the_cap_after_the_child_ran_is_unknown_not_unavailable(tmp_path, start):
    ws = Workspace(tmp_path / "ws")
    stub = ChatStub(tmp_path / "chat")
    service = start(workspace=ws, env=stub.env())
    stub.answer("x" * (16 * 1024 * 1024 + 16))
    key = body()["invocationId"]
    over = service.request("POST", URL, as_="chatter", body=body(), headers={"Idempotency-Key": key})
    assert over.status_code == 502 and over.json()["error"]["code"] == "stage_outcome_unknown"
    assert len(stub.calls()) == 1


def test_a_relabelled_or_self_contradicting_child_result_is_never_a_200(tmp_path, start):
    ws = Workspace(tmp_path / "ws")
    stub = ChatStub(tmp_path / "chat")
    service = start(workspace=ws, env=stub.env())
    for i, change in enumerate(({"receipt": None}, {"answer": {"requirements": [], "debug": "x"}})):
        stub.answer({**succeeded(), **change})
        key = f"job-0000010{i}:1:chat-router"
        refused = service.request("POST", URL, as_="chatter", body=body(key), headers={"Idempotency-Key": key})
        assert refused.status_code == 502 and refused.json()["error"]["code"] == "stage_outcome_unknown"


def test_an_abnormal_child_is_an_unknown_outcome_never_a_not_sent_one(tmp_path, start):
    ws = Workspace(tmp_path / "ws")
    stub = ChatStub(tmp_path / "chat")
    service = start(workspace=ws, env=stub.env())
    stub.answer("garbage", exit_code=1)
    key = body()["invocationId"]
    unknown = service.request("POST", URL, as_="chatter", body=body(), headers={"Idempotency-Key": key})
    assert unknown.status_code == 502 and unknown.json()["error"]["code"] == "stage_outcome_unknown"


@pytest.mark.parametrize("root_name", ["ZOOP_AI_HANDOFF_EXPOSURE_STATE_DIR", "ZOOP_AI_HANDOFF_EXPOSURE_EXTRACTION_STATE_DIR",
                                      "ZOOP_AI_HANDOFF_EXPOSURE_INGESTION_STATE_DIR"])
@pytest.mark.parametrize("placement", ["same", "child", "parent"])
def test_chat_cannot_overlap_exposure_roots_without_an_ordinary_handoff(tmp_path, root_name, placement):
    from exposure_support import exposure_env, workspace

    ws = workspace(tmp_path / "ws")
    stub = ChatStub(tmp_path / "chat")
    operator_root = tmp_path / "operator" / "ledger"
    operator_root.mkdir(parents=True, mode=0o700)
    chat_root = {"same": operator_root, "child": operator_root / "chat", "parent": operator_root.parent}[placement]
    env = ws.env(**{**exposure_env(ws, only=True), **stub.env(), root_name: str(operator_root),
                   "ZOOP_AI_CHAT_STATE_DIR": str(chat_root)})
    before = sorted(operator_root.rglob("*"))
    with pytest.raises(ConfigError) as caught:
        load(env)
    assert (caught.value.field, caught.value.reason) == ("ZOOP_AI_CHAT_STATE_DIR", "chat_roots_overlap")
    assert sorted(operator_root.rglob("*")) == before and not stub.state.exists()


def test_chat_and_pipeline_live_settings_never_reach_the_exposure_child(tmp_path, start):
    from exposure_support import URL as exposure_url, exposure_env, query, report, workspace
    from test_handoff_http import BASE_KEYS, OS_ADDED, operator_state

    ws = workspace(tmp_path / "ws", with_relation=True)
    stub = ChatStub(tmp_path / "chat")
    settings = {"ZOOP_AI_CHAT_LIVE_ENABLED": "1", "ZOOP_AI_CHAT_MAX_CALLS": "2",
                "ZOOP_AI_API_KEY": "synthetic-chat-key", "TYPESAFE_API_KEY": "synthetic-jev-key",
                "ZOOP_AI_CHAT_ANSWER_MODEL": "gpt-6-luna", "ZOOP_AI_CHAT_JEV_MODEL": "jev-1.14.0",
                "ZOOP_AI_SERVICE_PIPELINE_LIVE": "1", "ZOOP_AI_PIPELINE_LIVE_ENABLED": "1",
                "ZOOP_AI_PIPELINE_LIVE_MODEL": "gpt-6-luna", "ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT": "high",
                "TYPESAFE_VALIDATION_MODEL": "jev-1.14.0", "ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR": str(tmp_path / "budget"),
                "ZOOP_AI_PIPELINE_LIVE_MAX_USD": "1", "ZOOP_AI_PIPELINE_LIVE_MAX_CALLS": "2"}
    service = start(workspace=ws, env={**exposure_env(ws, only=True), **stub.env(**settings)})
    before = operator_state(ws)
    assert service.request("POST", exposure_url, as_="chatter", body=query()).status_code == 403
    key = body()["invocationId"]
    assert service.request("POST", URL, as_="viewer", body=body(), headers={"Idempotency-Key": key}).status_code == 403
    assert ws.calls() == stub.calls() == []
    exposed = service.request("POST", exposure_url, body=query())
    assert exposed.status_code == 200 and exposed.json()["report"] == report()
    answer = service.request("POST", URL, as_="chatter", body=body(), headers={"Idempotency-Key": key})
    assert answer.status_code == 200 and answer.json()["invocationId"] == key
    exposure_call, = ws.calls()
    chat_call, = stub.calls()
    assert set(exposure_call["env"]) <= BASE_KEYS | OS_ADDED | {"ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"}
    for name in ("ZOOP_AI_API_KEY", "TYPESAFE_API_KEY", "ZOOP_AI_CHAT_LIVE_ENABLED"):
        assert chat_call["env"][name] == settings[name]
    assert "ZOOP_AI_PIPELINE_LIVE_ENABLED" not in chat_call["env"]
    assert operator_state(ws) == before


def test_shared_runner_overflow_keeps_exposure_retryable_but_chat_unknown(tmp_path, start):
    from exposure_support import URL as exposure_url, exposure_env, query, report, workspace
    from zoop_ai_service.runtime import MAX_STDOUT

    ws = workspace(tmp_path / "ws")
    stub = ChatStub(tmp_path / "chat")
    service = start(workspace=ws, env={**exposure_env(ws, only=True), **stub.env()})
    ws.script({"mode": "raw", "raw": "x" * (MAX_STDOUT + 1), "exit": 0})
    stub.answer("x" * (MAX_STDOUT + 1))
    exposed = service.request("POST", exposure_url, body=query())
    assert exposed.status_code == 503 and exposed.json()["error"]["code"] == "runtime_unavailable"
    assert exposed.json()["error"]["retryable"] is True and exposed.headers["retry-after"] == "2"
    key = body()["invocationId"]
    unknown = service.request("POST", URL, as_="chatter", body=body(), headers={"Idempotency-Key": key})
    assert unknown.status_code == 502 and unknown.json()["error"]["code"] == "stage_outcome_unknown"
    assert unknown.json()["error"]["retryable"] is False and "retry-after" not in unknown.headers
    assert len(ws.calls()) == len(stub.calls()) == 1
    ws.script({"output": report()})
    assert service.request("POST", exposure_url, body=query()).status_code == 200
    assert len(ws.calls()) == 2 and len(stub.calls()) == 1
