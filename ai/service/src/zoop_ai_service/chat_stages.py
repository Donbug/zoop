"""The chatbot model stage door: one synchronous `zoop-ai-chat invoke` per request. Blocking: callers run `invoke` in a worker thread.

The same child rules as every other door (`runtime.WorkerProcess`): fixed argv of server-owned paths, request data only through an anonymous stdin
file, a fixed minimal environment (the chat group's own), stderr discarded, its own session. What this door adds:

  * the invocation id is the caller's; the child sees it prefixed with the principal (`<principal>:<id>`), so two principals never share a ledger row.
    The child's result is checked as it came (exactly that prefixed id, the stage, the requested mode in the receipt, the stage's closed answer model
    and the outcome invariants) and only then answered with the caller's id; any mismatch is `stage_outcome_unknown`, never a relabelled 200;
  * a child that exits 0 or 2 with a `zoop-ai-chat-1` result is a 200 whatever the stage outcome (`status=failed` carries the stage failure and
    whether anything was sent); exit 64 is the runtime refusing the request or its own configuration;
  * a deadline (the stage limit plus a small margin) or an abnormal end means the runtime may have sent: 504/502 `stage_outcome_unknown`, which the
    caller must never resend. Only a child that provably never started sent nothing: 503 `runtime_unavailable`. An `unavailable` outcome after the
    child started (output over the cap, an I/O error reading it) is unknown too;
  * at most four children at once; a request that cannot get a slot within one second is 503 `service_busy` and nothing was started.
"""
from __future__ import annotations

import json
import threading
from typing import Any

from pydantic import ValidationError

from .config import ServiceConfig
from .jobs import ApiError, Observation
from .runtime import CODE, Deadlines, Outcome, WorkerProcess
from .chat_wire import ANSWERS, CHAT_SCHEMA, INVOCATION_ID, ChatMcpHealth, ChatStageRequest, ChatStageResult

SLOTS = 4
SLOT_WAIT = 1.0
# The worker's own client timeout per stage plus process start and ledger writes.
STAGE_DEADLINE = {"chat-router": 4.0 + 3.0, "chat-answer": 25.0 + 3.0, "chat-verification": 6.0 + 3.0, "chat-agent": 30.0 + 3.0}
# The probe's own 3 s client timeout plus process start.
PROBE_DEADLINE = 3.0 + 2.0
# Exit-64 codes of the probe: the operator's MCP server URL setting.
PROBE_CONFIG_CODES = frozenset({"mcp_server_url_required", "mcp_server_url_invalid"})
# Exit-64 codes that are the caller's fault, and those that are the server's configuration.
REQUEST_CODES = frozenset({"request_invalid"})
CONFIG_CODES = frozenset({"state_dir_invalid", "grant_registry_invalid", "replay_fixture_invalid", "replay_fixture_required"})


def interpret(code: int, raw: bytes) -> Outcome:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return Outcome("abnormal", exit_code=code)
    if not isinstance(value, dict):
        return Outcome("abnormal", exit_code=code)
    if code == 64:
        name = value.get("error")
        if set(value) != {"error"} or not isinstance(name, str) or not CODE.fullmatch(name):
            return Outcome("abnormal", exit_code=code)
        return Outcome("error", code=name, exit_code=64)
    if code not in (0, 2) or value.get("schemaVersion") != CHAT_SCHEMA or value.get("status") != ("succeeded" if code == 0 else "failed"):
        return Outcome("abnormal", exit_code=code)
    return Outcome("result", result=value, exit_code=code)


def interpret_probe(code: int, raw: bytes) -> Outcome:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return Outcome("abnormal", exit_code=code)
    if not isinstance(value, dict):
        return Outcome("abnormal", exit_code=code)
    if code == 64:
        name = value.get("error")
        if set(value) != {"error"} or not isinstance(name, str) or not CODE.fullmatch(name):
            return Outcome("abnormal", exit_code=code)
        return Outcome("error", code=name, exit_code=64)
    if code not in (0, 2) or value.get("schemaVersion") != CHAT_SCHEMA or value.get("mcp") != ("reachable" if code == 0 else "unreachable"):
        return Outcome("abnormal", exit_code=code)
    return Outcome("result", result=value, exit_code=code)


def consistent(result: ChatStageResult, invocation_id: str, stage: str, mode: str) -> bool:
    """The child's result belongs to exactly this request and its outcome fields agree with each other."""
    if result.invocation_id != invocation_id or result.stage != stage:
        return False
    failure, receipt = result.failure, result.receipt
    if receipt is not None and receipt.execution_mode != mode:
        return False
    if result.status == "succeeded":
        return isinstance(result.answer, ANSWERS[stage]) and failure is None and receipt is not None
    if result.answer is not None or failure is None or (failure.unknown and not failure.sent):
        return False
    return failure.sent == (receipt is not None)


class ChatProcess:
    def __init__(self, config: ServiceConfig, deadlines: Deadlines = Deadlines()):
        assert config.chat is not None
        self._chat = config.chat
        self._runner = WorkerProcess(config, deadlines, env=config.chat.child_env)

    def invoke(self, payload: dict[str, Any], deadline: float) -> Outcome:
        chat = self._chat
        argv = [str(chat.command), "invoke", "--state-dir", str(chat.state_dir), "--grants", str(chat.grants_path)]
        if chat.replay_path is not None:
            argv += ["--replay", str(chat.replay_path)]
        return self._runner.execute(argv, payload, deadline, interpret=interpret)

    def probe(self, deadline: float) -> Outcome:
        return self._runner.execute([str(self._chat.command), "probe-mcp"], {}, deadline, interpret=interpret_probe)


class ChatStages:
    def __init__(self, config: ServiceConfig, process: ChatProcess, *, slots: int = SLOTS, slot_wait: float = SLOT_WAIT):
        assert config.chat is not None
        self._chat, self._process = config.chat, process
        self._slots, self._slot_wait = threading.BoundedSemaphore(slots), slot_wait

    def invoke(self, principal: str, stage: str, request: ChatStageRequest, seen: Observation) -> tuple[int, ChatStageResult]:
        if request.stage != stage:
            raise ApiError(422, "invalid_request", field="stage")
        if not INVOCATION_ID.fullmatch(request.invocation_id):
            raise ApiError(422, "invalid_request", field="invocationId")
        if request.mode == "replay" and self._chat.replay_path is None:
            raise ApiError(409, "execution_unavailable")
        payload = {**request.wire(), "invocationId": f"{principal}:{request.invocation_id}"}
        if not self._slots.acquire(timeout=self._slot_wait):
            raise ApiError(503, "service_busy", retry_after=1)
        try:
            outcome = self._process.invoke(payload, STAGE_DEADLINE[stage])
        finally:
            self._slots.release()
        seen.runtime.append({"command": "invoke", "kind": outcome.kind, "exit": outcome.exit_code, "code": outcome.code})
        if outcome.kind == "result":
            try:
                result = ChatStageResult.model_validate(outcome.result)
            except ValidationError:
                raise ApiError(502, "stage_outcome_unknown") from None
            if not consistent(result, payload["invocationId"], stage, request.mode):
                raise ApiError(502, "stage_outcome_unknown")
            return 200, result.model_copy(update={"invocation_id": request.invocation_id})
        if outcome.kind == "error":
            if outcome.code in REQUEST_CODES:
                raise ApiError(422, "invalid_request", runtime_code=outcome.code)
            if outcome.code in CONFIG_CODES:
                raise ApiError(503, "service_configuration_invalid", runtime_code=outcome.code, retry_after=5)
            raise ApiError(502, "stage_outcome_unknown", runtime_code=outcome.code)
        if outcome.kind == "unavailable" and not outcome.started:
            raise ApiError(503, "runtime_unavailable", retry_after=2)
        # A deadline, a signal or unreadable output: the child may have sent the request. Never resend it.
        raise ApiError(504 if outcome.kind == "timeout" else 502, "stage_outcome_unknown")

    def probe_mcp(self, seen: Observation) -> ChatMcpHealth:
        """The MCP server's reachability as the installed runtime probes it. It sends no grant, runs nothing and calls no model, so it shares
        no ledger; a probe that cannot run, or whose child ends abnormally, is an error and never a health answer."""
        if not self._slots.acquire(timeout=self._slot_wait):
            raise ApiError(503, "service_busy", retry_after=1)
        try:
            outcome = self._process.probe(PROBE_DEADLINE)
        finally:
            self._slots.release()
        seen.runtime.append({"command": "probe-mcp", "kind": outcome.kind, "exit": outcome.exit_code, "code": outcome.code})
        if outcome.kind == "result":
            try:
                return ChatMcpHealth.model_validate(outcome.result)
            except ValidationError:
                raise ApiError(502, "probe_failed") from None
        if outcome.kind == "error" and outcome.code in PROBE_CONFIG_CODES:
            raise ApiError(503, "service_configuration_invalid", runtime_code=outcome.code, retry_after=5)
        if outcome.kind == "unavailable" and not outcome.started:
            raise ApiError(503, "runtime_unavailable", retry_after=2)
        raise ApiError(504 if outcome.kind == "timeout" else 502, "probe_failed")
