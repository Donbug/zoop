"""One chatbot model stage per invocation: configuration, grants, the invocation ledger, the provider call and its receipt.

Rules (ZOOP-AIG-001 6.3.2-6.3.3, design summary 5.1):

- One request per invocation and no retry or fallback. The ledger in `chat.sqlite3` makes an invocation idempotent: the same
  `invocationId` with the same input returns the stored outcome without sending again; a request that left this process and whose
  outcome was not stored is `unknown` and is never sent again (the provider may have processed and charged it).
- Live calls need `ZOOP_AI_CHAT_LIVE_ENABLED=1` and a positive `ZOOP_AI_CHAT_MAX_CALLS`, a ceiling shared by all chat stages
  and separate from the S1 and pipeline gates. Without them nothing is sent. Replay never touches the network.
- Every quoted span must be allowed by the operator chat grant registry: an enabled grant with known rights, `model-send`, the
  stage as purpose and the exact recipient (`authored-replay`, or `<provider>:<revision>` live). Otherwise nothing is sent.
- Timeouts, effort and output limits are the invocation's immutable Java-owned resource allocation.
- Both Luna stages use Responses; every fresh stage validates the installed runtime fingerprint before claiming a send.
- An agent step (`chat-agent`) is one Responses request, so the same ledger rules hold per step: the application gives every
  step its own invocation id. Its MCP grant token is excluded from every identity and redacted from the stored raw answer.
  Its tool results reach the provider from the application's MCP server, which checks their send grants for the recipient
  the step names; a step is sent only when that is this stage's own recipient (`mcp_recipient_mismatch` otherwise).
- Order of one invocation: the ledger first (a known invocation answers from its record, whatever the gate or keys are now),
  then the gate, grants and sender for a new one, then one atomic claim with the live ceiling, the send, the raw answer stored,
  and only then usage and answer interpretation. Any interpretation failure keeps the raw answer as a definite failure.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from . import chat_agent, chat_jev, chat_luna
from .chat_contracts import (CHAT_SCHEMA_VERSION, INPUT_BUDGET_EXCEEDED, OUTPUT_BUDGET_EXCEEDED,
                             AgentInput, AnswerInput, ChatAnswer, ChatGrantRegistry, Receipt,
                             RouterInput, StageFailure, StageRequest, StageResult, Usage, VerificationInput, estimated_tokens)
from .contracts import canonical, digest
from .provider import DEFAULT_BASE_URL, NATIVE_DEFAULT_BASE_URL, ProviderError, native_revision

from . import chat_resources
LUNA_STAGES = {"chat-answer": (chat_luna, "ZOOP_AI_CHAT_ANSWER_MODEL"),
               "chat-agent": (chat_agent, "ZOOP_AI_CHAT_AGENT_MODEL")}
LUNA = "openai-compatible"
JEV = "typesafe-native"
REPLAY = "authored-replay"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class ChatStageConfig:
    provider: str
    provider_revision: str
    model: str
    reasoning_effort: str | None
    prompt_version: str
    mode: str
    # A live agent step's ZOOP MCP server: the operator's canonical URL (`ZOOP_AI_CHAT_MCP_SERVER_URL`); None otherwise.
    mcp_server_url: str | None = None

    def recipient(self) -> str:
        return self.provider if self.mode == "replay" else f"{self.provider}:{self.provider_revision}"

    def wire(self) -> dict[str, Any]:
        wire = {"provider": self.provider, "providerRevision": self.provider_revision, "model": self.model,
                "reasoningEffort": self.reasoning_effort, "promptVersion": self.prompt_version}
        if self.mcp_server_url is not None:
            wire["mcpServerUrl"] = self.mcp_server_url
        return wire


def _prompt_version(stage: str) -> str:
    if stage in LUNA_STAGES:
        return LUNA_STAGES[stage][0].prompt_version()
    return chat_jev.prompt_version(stage)


def stage_config(stage: str, mode: str, env: dict[str, str] | None = None) -> ChatStageConfig:
    env = os.environ if env is None else env
    if mode == "replay":
        return ChatStageConfig(REPLAY, "authored-replay-1", "authored-synthetic-" + stage, None, _prompt_version(stage), mode)
    if stage in LUNA_STAGES:
        module, model_key = LUNA_STAGES[stage]
        if any(key in env for key in ("ZOOP_AI_CHAT_ANSWER_REASONING_EFFORT", "ZOOP_AI_CHAT_AGENT_REASONING_EFFORT")):
            raise ProviderError("chat_legacy_effort_configuration")
        base = env.get("ZOOP_AI_BASE_URL", "").strip() or DEFAULT_BASE_URL
        chat_resources.validate_endpoint(base)
        model = env.get(model_key, "").strip()
        if not model:
            raise ProviderError("stage_model_required")
        if model != module.MODEL:
            raise ProviderError("answer_model_unsupported")
        effort = None
        server = None
        if stage == "chat-agent":
            # The only host a run's grant may reach: set by the operator, never taken from a request.
            configured = env.get("ZOOP_AI_CHAT_MCP_SERVER_URL", "").strip()
            if not configured:
                raise ProviderError("mcp_server_url_required")
            try:
                server = chat_agent.server_url(configured)
            except ValueError:
                raise ProviderError("mcp_server_url_invalid") from None
        return ChatStageConfig(LUNA, digest({"endpoint": base}), model, effort, _prompt_version(stage), mode, server)
    base = env.get("TYPESAFE_BASE_URL", "").strip() or NATIVE_DEFAULT_BASE_URL
    chat_resources.validate_endpoint(base)
    if "/systemone" in base:
        raise ProviderError("native_base_url_includes_endpoint_path")
    model = env.get("ZOOP_AI_CHAT_JEV_MODEL", "").strip()
    if not model:
        raise ProviderError("stage_model_required")
    if model != chat_jev.MODEL:
        raise ProviderError("native_model_unsupported")
    return ChatStageConfig(JEV, native_revision(base), model, None, _prompt_version(stage), mode)


def _identified_input(request: StageRequest) -> dict[str, Any]:
    """The input as identities see it: an agent step's MCP grant token is replaced, so no digest is derived from a credential and
    a replay fixture does not depend on a per-run token."""
    parsed = request.parsed()
    return chat_agent.identity_input(parsed) if isinstance(parsed, AgentInput) else parsed.wire()


def request_identity(request: StageRequest, config: ChatStageConfig) -> str:
    """What the provider is asked: the input and the frozen stage configuration. It keys the authored replay fixture."""
    value = {"schemaVersion": request.schema_version, "stage": request.stage, "input": _identified_input(request),
             "config": config.wire()}
    if request.resources is not None:
        value.update(mode=request.mode, resources=request.resources.wire())
    return digest(value)


def request_digest(request: StageRequest) -> str:
    """What the caller asked under an invocation id, without the configuration: a later configuration change (gate, key, model
    setting) never makes a stored invocation look new or conflicting."""
    value = {"schemaVersion": request.schema_version, "stage": request.stage, "mode": request.mode,
             "input": _identified_input(request)}
    if request.resources is not None:
        value["resources"] = request.resources.wire()
    return digest(value)


def live_ceiling(env: dict[str, str] | None = None) -> int:
    """The live call ceiling, or raises `chat_live_disabled` when live chat is not explicitly opened."""
    env = os.environ if env is None else env
    if env.get("ZOOP_AI_CHAT_LIVE_ENABLED") != "1":
        raise ProviderError("chat_live_disabled")
    try:
        ceiling = int(env.get("ZOOP_AI_CHAT_MAX_CALLS", ""))
    except ValueError:
        raise ProviderError("chat_live_disabled") from None
    if ceiling <= 0:
        raise ProviderError("chat_live_disabled")
    return ceiling


def check_grants(request: StageRequest, recipient: str, registry: ChatGrantRegistry | None) -> None:
    quotes = request.quotes()
    if not quotes:
        return
    if registry is None:
        raise ProviderError("source_grant_required")
    now = datetime.now(UTC)
    for quote in quotes:
        allowed = any(
            g.source_id == quote.source_id and g.enabled and g.rights == "known" and "model-send" in g.allowed_operations
            and request.stage in g.purposes and recipient in g.recipients
            and (g.expires_at is None or datetime.fromisoformat(g.expires_at) > now)
            for g in registry.grants)
        if not allowed:
            raise ProviderError("source_grant_denied")


def check_recipient(request: StageRequest, recipient: str) -> None:
    """An agent step goes only to the recipient the application checked its MCP results' send grants for."""
    parsed = request.parsed()
    if isinstance(parsed, AgentInput) and parsed.mcp.recipient != recipient:
        raise ProviderError("mcp_recipient_mismatch")


class ChatLedger:
    """`chat.sqlite3`: one row per invocation, written before anything leaves the process.

    `claim` decides in one IMMEDIATE transaction who sends: the row is inserted as `sent` together with its pre-send receipt, and
    the live ceiling counts every live row, so neither a second process with the same invocation id nor a different id can send
    past it. Only the claimer sends. The raw provider answer is stored (`received`) before it is interpreted; `finish` stores the
    outcome. A `sent` row whose outcome was never stored (the process stopped after claiming, while waiting, or after receiving)
    is answered as `unknown` and never sent again. `reserved` is only read, from ledgers written by an earlier version: it was never
    sent and is claimed like a new invocation.
    """

    def __init__(self, state_dir: Path):
        path = state_dir / "chat.sqlite3"
        # Private from the first byte: SQLite gives its -wal/-shm files the database file's mode, and the service refuses a ledger
        # that others can read. An existing file keeps its mode (and is then refused there), a symlink is never followed.
        os.close(os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600))
        self.db = sqlite3.connect(path, isolation_level=None, timeout=5)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS chat_invocations (
            invocation_id TEXT PRIMARY KEY, stage TEXT NOT NULL, mode TEXT NOT NULL, input_digest TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('reserved','sent','succeeded','failed','unknown')),
            result TEXT, raw TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(chat_invocations)")}
        for column in ("request_digest", "receipt"):
            if column not in columns:
                self.db.execute(f"ALTER TABLE chat_invocations ADD COLUMN {column} TEXT")

    def close(self) -> None:
        self.db.close()

    def stored(self, request: StageRequest) -> StageResult | None:
        """The outcome already recorded for this invocation id, before any current gate, key or grant is consulted. Raises
        `invocation_conflict` when the id was used for another request."""
        row = self.db.execute("SELECT request_digest, status, result, receipt FROM chat_invocations WHERE invocation_id=?",
                              (request.invocation_id,)).fetchone()
        return None if row is None else self._outcome(request, row)

    @staticmethod
    def _outcome(request: StageRequest, row: tuple) -> StageResult | None:
        recorded, status, result, receipt = row
        if recorded is not None and recorded != request_digest(request):
            raise ProviderError("invocation_conflict")
        if status in ("succeeded", "failed", "unknown"):
            outcome = StageResult.model_validate_json(result)
            if outcome.schema_version != request.schema_version:
                raise ProviderError("invocation_conflict")
            return outcome
        if status == "sent":
            # Claimed and possibly sent; its outcome was never stored: never send again.
            return _failed(request, "provider_response_unknown", sent=True, unknown=True,
                           receipt=None if receipt is None else Receipt.model_validate_json(receipt))
        return None

    def prior_context(self, request: StageRequest, payload: AgentInput) -> int:
        continuation = payload.continuation
        if continuation is None:
            return 0
        rows = self.db.execute(
            "SELECT invocation_id,result FROM chat_invocations WHERE stage='chat-agent' AND mode=? AND status='succeeded' "
            "AND json_extract(result,'$.schemaVersion')=? AND json_extract(result,'$.answer.responseId')=?",
            (request.mode, CHAT_SCHEMA_VERSION, continuation.previous_response_id)).fetchall()
        principal = request.invocation_id.partition(":")[0] if ":" in request.invocation_id else ""
        for invocation, encoded in rows:
            previous_principal = invocation.partition(":")[0] if ":" in invocation else ""
            if previous_principal != principal:
                continue
            previous = StageResult.model_validate_json(encoded)
            if previous.answer.get("status") != "approval_required" or previous.receipt is None:
                continue
            if (previous.resource_binding.policy_digest != request.resources.policy_digest
                    or previous.resource_binding.runtime_fingerprint != request.resources.runtime_fingerprint):
                raise ProviderError("chat_runtime_contract_mismatch")
            known = {item["approvalRequestId"] for item in previous.answer["approvalRequests"]}
            if any(item.approval_request_id not in known for item in continuation.decisions):
                raise ProviderError("agent_context_unavailable")
            usage = previous.receipt.usage
            if usage.input_tokens is None or usage.output_tokens is None:
                raise ProviderError("agent_context_unavailable")
            # Full MCP callbacks contain the structured envelope and its JSON text; the negotiated reserve covers both.
            return usage.input_tokens + usage.output_tokens + sum(item.approve for item in continuation.decisions) * 296448
        raise ProviderError("agent_context_unavailable")

    def claim(self, request: StageRequest, identity: str, ceiling: int | None, receipt: Receipt) -> StageResult | None:
        """Takes the right to send, or returns the outcome another claimer recorded meanwhile. Raises `chat_budget_exhausted`
        or `invocation_conflict` without claiming."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT request_digest, status, result, receipt FROM chat_invocations WHERE invocation_id=?",
                                  (request.invocation_id,)).fetchone()
            if row is not None:
                outcome = self._outcome(request, row)
                if outcome is not None:
                    self.db.execute("COMMIT")
                    return outcome
            if ceiling is not None:
                used = self.db.execute("SELECT count(*) FROM chat_invocations WHERE mode='live' AND status<>'reserved'"
                                       ).fetchone()[0]
                if used >= ceiling:
                    raise ProviderError("chat_budget_exhausted")
            self.db.execute("""INSERT INTO chat_invocations (invocation_id, stage, mode, input_digest, status, result, raw,
                                   created_at, updated_at, request_digest, receipt)
                               VALUES (?,?,?,?, 'sent', NULL, NULL, ?, ?, ?, ?)
                               ON CONFLICT(invocation_id) DO UPDATE SET status='sent', input_digest=excluded.input_digest,
                                   request_digest=excluded.request_digest, receipt=excluded.receipt, updated_at=excluded.updated_at
                               WHERE chat_invocations.status='reserved'""",
                            (request.invocation_id, request.stage, request.mode, identity, _now(), _now(),
                             request_digest(request), canonical(receipt.wire())))
            self.db.execute("COMMIT")
            return None
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def received(self, invocation_id: str, raw: Any) -> None:
        """Keeps the provider's raw answer durably before it is interpreted, without any echoed MCP credential."""
        self.db.execute("UPDATE chat_invocations SET raw=?, updated_at=? WHERE invocation_id=? AND status='sent'",
                        (canonical(chat_agent.redact(raw)), _now(), invocation_id))

    def finish(self, result: StageResult) -> None:
        status = "succeeded" if result.status == "succeeded" else "unknown" if result.failure and result.failure.unknown \
            else "failed"
        self.db.execute("UPDATE chat_invocations SET status=?, result=?, receipt=?, updated_at=? WHERE invocation_id=? "
                        "AND status='sent'",
                        (status, canonical(result.wire()), None if result.receipt is None else canonical(result.receipt.wire()),
                         _now(), result.invocation_id))


def _failed(request: StageRequest, code: str, *, sent: bool, unknown: bool, receipt: Receipt | None) -> StageResult:
    return StageResult(schema_version=request.schema_version, invocation_id=request.invocation_id, stage=request.stage,
                       status="failed", answer=None, failure=StageFailure(code=code, sent=sent, unknown=unknown),
                       receipt=receipt, resource_binding=request.binding())


def _no_usage() -> Usage:
    return Usage(input_tokens=None, output_tokens=None, cached_tokens=None, reasoning_tokens=None)


def provider_body(request: StageRequest, config: ChatStageConfig) -> tuple[str, dict[str, Any]]:
    """The endpoint path and exact request body a live stage sends."""
    parsed = request.parsed()
    if request.stage == "chat-answer":
        body = chat_luna.build_request(parsed, config.model, request.resources.luna)
        chat_resources.check_fixed_material(request.stage, body)
        return "responses", body
    if request.stage == "chat-agent":
        if config.mcp_server_url is None:
            raise ProviderError("mcp_server_url_required")
        body = chat_agent.build_request(parsed, config.model, request.resources.luna, config.mcp_server_url)
        chat_resources.check_fixed_material(request.stage, body)
        return "responses", body
    if request.stage == "chat-router":
        return "systemone", chat_jev.build_router_request(parsed, config.model)
    return "systemone", chat_jev.build_verification_request(parsed, config.model)


class LiveSender:
    """Real HTTP: one POST, no retry, no redirect. Non-2xx is a definite failure; a transport error leaves the fate unknown.
    It returns the raw answer only: nothing is interpreted before the ledger has stored it."""

    def __init__(self, env: dict[str, str] | None = None, transport: httpx.BaseTransport | None = None):
        self.env = os.environ if env is None else env
        self.transport = transport

    def _endpoint(self, config: ChatStageConfig) -> tuple[str, str]:
        if config.provider == LUNA:
            return (self.env.get("ZOOP_AI_BASE_URL", "").strip() or DEFAULT_BASE_URL,
                    self.env.get("ZOOP_AI_API_KEY", ""))
        return (self.env.get("TYPESAFE_BASE_URL", "").strip() or NATIVE_DEFAULT_BASE_URL,
                self.env.get("TYPESAFE_API_KEY", ""))

    def preflight(self, request: StageRequest | None, config: ChatStageConfig) -> None:
        key = self._endpoint(config)[1]
        if not key:
            raise ProviderError("provider_key_required")
        # A key with whitespace or control characters (e.g. a trailing space in an env file) cannot travel in a header: the HTTP
        # client refuses it locally, which would look like an unknown fate. Refuse it here, before anything is reserved.
        if any(ord(char) < 33 or ord(char) > 126 for char in key):
            raise ProviderError("provider_key_invalid")
        if request is not None:
            provider_body(request, config)

    def send(self, request: StageRequest, config: ChatStageConfig) -> Any:
        base, key = self._endpoint(config)
        path, body = provider_body(request, config)
        with httpx.Client(base_url=base.rstrip("/") + "/", timeout=request.resources.provider_timeout_ms / 1000,
                          headers={"Authorization": "Bearer " + key}, follow_redirects=False,
                          transport=self.transport) as client:
            try:
                response = client.post(path, json=body)
            except httpx.TransportError:
                raise ProviderError("provider_response_unknown", uncertain=True) from None
        if not 200 <= response.status_code < 300:
            if response.status_code == 424 and request.stage == "chat-agent":
                # The provider could not reach the ZOOP MCP server (it could not list its tools): the connection failure
                # the application counts for its circuit. Shape per the provider documentation; confirmed in the live spike.
                raise ProviderError(chat_agent.MCP_UNREACHABLE)
            raise ProviderError("provider_option_unsupported" if response.status_code == 400
                                else f"provider_http_{response.status_code}")
        try:
            return response.json()
        except ValueError:
            return {"responseText": response.text, "httpStatus": response.status_code}


class ReplaySender:
    """Authored fixture matched by the exact request identity. Nothing leaves the process."""

    def __init__(self, path: Path | None):
        self.path = path
        self.entries: dict[str, Any] | None = None

    def _entry(self, request: StageRequest, config: ChatStageConfig) -> dict[str, Any]:
        if self.entries is None:
            try:
                if self.path is None:
                    raise ProviderError("replay_fixture_required")
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("schemaVersion") != CHAT_SCHEMA_VERSION or data.get("recordingKind") != "authored-test":
                    raise ProviderError("replay_fixture_invalid")
                self.entries = {entry["inputDigest"]: entry for entry in data["responses"]}
            except (OSError, ValueError, KeyError, TypeError):
                raise ProviderError("replay_fixture_invalid") from None
        entry = self.entries.get(request_identity(request, config))
        if entry is None or entry.get("stage") != request.stage:
            raise ProviderError("replay_input_mismatch")
        return entry

    def preflight(self, request: StageRequest, config: ChatStageConfig) -> None:
        self._entry(request, config)

    def send(self, request: StageRequest, config: ChatStageConfig) -> Any:
        entry = self._entry(request, config)
        if "error" in entry:
            raise ProviderError(entry["error"], uncertain=entry.get("uncertain", False))
        return entry["response"]


def _count(block: dict[str, Any], name: str) -> int | None:
    value = block.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("provider_usage_invalid")
    return value


def _details(block: dict[str, Any], name: str) -> dict[str, Any]:
    value = block.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("provider_usage_invalid")
    return value


def usage_of(raw: Any, provider: str, stage: str | None = None) -> Usage:
    """Reported token counts. No usage block is no counts; a block of the wrong shape is a ValueError, never another error. An
    agent step reports the Responses usage of the whole step (its reasoning and MCP round trips included)."""
    block = raw.get("usage") if isinstance(raw, dict) else None
    if block is None:
        return _no_usage()
    if not isinstance(block, dict):
        raise ValueError("provider_usage_invalid")
    if provider == JEV:
        return Usage(input_tokens=_count(block, "input_tokens"), output_tokens=_count(block, "output_tokens"),
                     cached_tokens=None, reasoning_tokens=None)
    return Usage(input_tokens=_count(block, "input_tokens"), output_tokens=_count(block, "output_tokens"),
                 cached_tokens=_count(_details(block, "input_tokens_details"), "cached_tokens"),
                 reasoning_tokens=_count(_details(block, "output_tokens_details"), "reasoning_tokens"))


def responded_model(raw: Any, config: ChatStageConfig) -> str:
    """The model that answered, which the receipt records. It must be the configured model, or for an OpenAI-compatible answer
    a dated or named snapshot of it (`<model>-...`); anything else is a model mismatch."""
    model = raw.get("model") if isinstance(raw, dict) else None
    if not isinstance(model, str) or not model:
        raise ValueError("provider_model_missing")
    if model == config.model or (config.provider == LUNA and model.startswith(config.model + "-") and len(model) <= 200):
        return model
    raise ValueError("provider_model_mismatch")


def interpret(request: StageRequest, config: ChatStageConfig, raw: Any) -> dict[str, Any]:
    """The typed answer of a received response, or ValueError with a stable code (the raw response stays the receipt)."""
    parsed = request.parsed()
    if request.stage == "chat-router":
        return chat_jev.interpret_router(raw, parsed, config.model).wire()
    if request.stage == "chat-verification":
        return chat_jev.interpret_verification(raw, parsed, config.model).wire()
    if request.stage == "chat-agent":
        return chat_agent.interpret(raw, parsed).wire()
    return _interpret_answer(raw, parsed)


def _interpret_answer(raw: Any, payload: AnswerInput) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("answer_response_invalid")
    if raw.get("status") == "incomplete":
        details = raw.get("incomplete_details")
        raise ValueError(OUTPUT_BUDGET_EXCEEDED if isinstance(details, dict) and details.get("reason") == "max_output_tokens"
                         else "answer_incomplete")
    if raw.get("status") != "completed" or not isinstance(raw.get("output"), list):
        raise ValueError("answer_response_invalid")
    texts = []
    for item in raw["output"]:
        if not isinstance(item, dict):
            raise ValueError("answer_response_invalid")
        if item.get("type") == "reasoning":
            continue
        if item.get("type") != "message" or not isinstance(item.get("content"), list):
            raise ValueError("answer_response_invalid")
        for part in item["content"]:
            if not isinstance(part, dict):
                raise ValueError("answer_response_invalid")
            if part.get("type") == "refusal":
                raise ValueError("answer_refused")
            if part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                raise ValueError("answer_response_invalid")
            texts.append(part["text"])
    if len(texts) != 1:
        raise ValueError("answer_response_invalid")
    content = texts[0]
    try:
        answer = ChatAnswer.model_validate_json(content)
    except ValidationError:
        raise ValueError("answer_schema_invalid") from None
    branches = {b.requirement_id: b for b in payload.branches}
    cited: set[str] = set()
    for section in answer.sections:
        if not set(section.requirement_ids) <= set(branches):
            raise ValueError("answer_requirement_unknown")
        allowed = {q.evidence_id for r in section.requirement_ids for q in branches[r].evidence}
        if not set(section.evidence_ids) <= allowed:
            raise ValueError("answer_evidence_unknown")
        cited |= set(section.evidence_ids)
    if not set(answer.insufficient_requirement_ids) <= set(branches) or len(cited) > payload.max_citations:
        raise ValueError("answer_budget_invalid")
    return answer.wire()


def check_input_budget(request: StageRequest, ledger: ChatLedger) -> None:
    """Admission uses current-call input, not cumulative billed input across agent continuations."""
    if request.resources is None or request.resources.luna is None:
        return
    estimated = estimated_tokens(canonical(_identified_input(request))) + chat_resources.adapter(request.stage)["fixedInputOverheadBytes"]
    parsed = request.parsed()
    if isinstance(parsed, AgentInput):
        estimated += ledger.prior_context(request, parsed)
    if estimated > request.resources.luna.max_input_tokens:
        raise ProviderError(INPUT_BUDGET_EXCEEDED)


def check_answer_tokens(answer: dict[str, Any], usage: Usage, request: StageRequest) -> None:
    if request.stage not in LUNA_STAGES:
        return
    if (usage.input_tokens is None or usage.output_tokens is None or usage.reasoning_tokens is None
            or usage.reasoning_tokens > usage.output_tokens
            or (usage.cached_tokens is not None and usage.cached_tokens > usage.input_tokens)):
        raise ValueError("provider_usage_invalid")
    limits = request.resources.luna
    if usage.input_tokens > limits.max_input_tokens:
        raise ValueError(INPUT_BUDGET_EXCEEDED)
    if usage.output_tokens > limits.max_output_tokens:
        raise ValueError(OUTPUT_BUDGET_EXCEEDED)
    if answer.get("status") == "approval_required":
        if request.resources.finalizing:
            raise ValueError("agent_finalization_required")
        return
    final = answer.get("answer", answer)
    if (usage.output_tokens - usage.reasoning_tokens > limits.max_visible_output_tokens
            or sum(len(section["text"]) for section in final["sections"]) > limits.generated_text_max_chars):
        raise ValueError(OUTPUT_BUDGET_EXCEEDED)


def _recipient(receipt: Receipt) -> str:
    return receipt.provider if receipt.execution_mode == "replay" else f"{receipt.provider}:{receipt.provider_revision}"


def _as_stored(request: StageRequest, stored: StageResult, registry: ChatGrantRegistry | None) -> StageResult:
    """A stored outcome as it may be shown now. It is never turned into a request that was not sent; a stored answer whose
    quoted sources lost their grant since is withheld (`source_grant_withdrawn`) with its receipt, without sending again."""
    if stored.status != "succeeded" or stored.receipt is None:
        return stored
    try:
        check_grants(request, _recipient(stored.receipt), registry)
    except ProviderError:
        return _failed(request, "source_grant_withdrawn", sent=True, unknown=False, receipt=stored.receipt)
    return stored


def invoke(request: StageRequest, *, state_dir: Path, registry: ChatGrantRegistry | None,
           sender: LiveSender | ReplaySender,
           env: dict[str, str] | None = None) -> StageResult:
    """Runs one stage. Never raises for provider or policy outcomes: they become a failed StageResult.

    The ledger is read first: an invocation that was already claimed answers from its record whatever the gate, keys or
    configuration are now. Only a new invocation is checked against the gate, grants and sender and then claimed."""
    ledger = ChatLedger(state_dir)
    try:
        try:
            stored = ledger.stored(request)
        except ProviderError as conflict:
            return _failed(request, conflict.code, sent=False, unknown=False, receipt=None)
        if stored is not None:
            return _as_stored(request, stored, registry)
        try:
            chat_resources.validate(request, env)
            config = stage_config(request.stage, request.mode, env)
            ceiling = live_ceiling(env) if request.mode == "live" else None
            identity = request_identity(request, config)
            check_grants(request, config.recipient(), registry)
            check_recipient(request, config.recipient())
            check_input_budget(request, ledger)
            sender.preflight(request, config)
        except ProviderError as refused:
            return _failed(request, refused.code, sent=False, unknown=False, receipt=None)

        receipt = Receipt(provider=config.provider, provider_revision=config.provider_revision, model=config.model,
                          prompt_version=config.prompt_version, execution_mode=request.mode, usage=_no_usage(),
                          sent_at=_now(), received_at=None)
        try:
            stored = ledger.claim(request, identity, ceiling, receipt)
        except ProviderError as refused:
            return _failed(request, refused.code, sent=False, unknown=False, receipt=None)
        if stored is not None:
            return _as_stored(request, stored, registry)

        try:
            raw = sender.send(request, config)
        except ProviderError as error:
            result = _failed(request, error.code, sent=True, unknown=error.uncertain, receipt=receipt)
            ledger.finish(result)
            return result

        ledger.received(request.invocation_id, raw)
        receipt = receipt.model_copy(update={"received_at": _now()})
        try:
            receipt = receipt.model_copy(update={"usage": usage_of(raw, config.provider, request.stage),
                                                 "model": responded_model(raw, config)})
            answer = interpret(request, config, raw)
            check_answer_tokens(answer, receipt.usage, request)
        except ValueError as invalid:
            result = _failed(request, str(invalid), sent=True, unknown=False, receipt=receipt)
        except Exception:  # noqa: BLE001 - any other interpretation error keeps the stored raw answer as a definite failure
            result = _failed(request, "provider_response_invalid", sent=True, unknown=False, receipt=receipt)
        else:
            result = StageResult(schema_version=request.schema_version, invocation_id=request.invocation_id,
                                 stage=request.stage, status="succeeded", answer=answer, failure=None, receipt=receipt,
                                 resource_binding=request.binding())
        ledger.finish(result)
        return result
    finally:
        ledger.close()
