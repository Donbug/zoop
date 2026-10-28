"""One chatbot model stage per invocation: configuration, grants, the invocation ledger, the provider call and its receipt.

Rules (ZOOP-AIG-001 6.3.2-6.3.3, design summary 5.1):

- One request per invocation and no retry or fallback. The ledger in `chat.sqlite3` makes an invocation idempotent: the same
  `invocationId` with the same input returns the stored outcome without sending again; a request that left this process and whose
  outcome was not stored is `unknown` and is never sent again (the provider may have processed and charged it).
- Live calls need `ZOOP_AI_CHAT_LIVE_ENABLED=1` and a positive `ZOOP_AI_CHAT_MAX_CALLS`, a ceiling shared by all chat stages
  and separate from the S1 and pipeline gates. Without them nothing is sent. Replay never touches the network.
- Every quoted span must be allowed by the operator chat grant registry: an enabled grant with known rights, `model-send`, the
  stage as purpose and the exact recipient (`authored-replay`, or `<provider>:<revision>` live). Otherwise nothing is sent.
- Each stage has its own client timeout (router 4 s, answer 25 s, verification 6 s, agent step 30 s); a timeout after sending
  is `unknown`.
- The models are pinned like the pipeline's: Luna `gpt-6-luna` at reasoning effort `high` for `chat-answer` and `medium` for
  `chat-agent`, Jev `jev-1.14.0`. The model that answered must be the pinned one (a Luna answer may name a `gpt-6-luna-...`
  snapshot) and is what the receipt records.
- An agent step (`chat-agent`) is one Responses request, so the same ledger rules hold per step: the application gives every
  step its own invocation id. Its MCP grant token is excluded from every identity and redacted from the stored raw answer.
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
from .chat_contracts import (CHAT_SCHEMA_VERSION, AgentInput, AnswerInput, ChatAnswer, ChatGrantRegistry, Receipt,
                             RouterInput, StageFailure, StageRequest, StageResult, Usage, VerificationInput)
from .contracts import canonical, digest
from .provider import DEFAULT_BASE_URL, NATIVE_DEFAULT_BASE_URL, ProviderError, native_revision, validate_base_url

# An agent step includes the MCP calls the provider makes after an approval; the application bounds the whole run (35 s).
STAGE_TIMEOUT = {"chat-router": 4.0, "chat-answer": 25.0, "chat-verification": 6.0, "chat-agent": 30.0}
LUNA_STAGES = {"chat-answer": (chat_luna, "ZOOP_AI_CHAT_ANSWER_MODEL", "ZOOP_AI_CHAT_ANSWER_REASONING_EFFORT"),
               "chat-agent": (chat_agent, "ZOOP_AI_CHAT_AGENT_MODEL", "ZOOP_AI_CHAT_AGENT_REASONING_EFFORT")}
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

    def recipient(self) -> str:
        return self.provider if self.mode == "replay" else f"{self.provider}:{self.provider_revision}"

    def wire(self) -> dict[str, Any]:
        return {"provider": self.provider, "providerRevision": self.provider_revision, "model": self.model,
                "reasoningEffort": self.reasoning_effort, "promptVersion": self.prompt_version}


def _prompt_version(stage: str) -> str:
    if stage in LUNA_STAGES:
        return LUNA_STAGES[stage][0].prompt_version()
    return chat_jev.prompt_version(stage)


def stage_config(stage: str, mode: str, env: dict[str, str] | None = None) -> ChatStageConfig:
    env = os.environ if env is None else env
    if mode == "replay":
        return ChatStageConfig(REPLAY, "authored-replay-1", "authored-synthetic-" + stage, None, _prompt_version(stage), mode)
    if stage in LUNA_STAGES:
        module, model_key, effort_key = LUNA_STAGES[stage]
        base = env.get("ZOOP_AI_BASE_URL", "").strip() or DEFAULT_BASE_URL
        validate_base_url(base)
        model = env.get(model_key, "").strip()
        if not model:
            raise ProviderError("stage_model_required")
        if model != module.MODEL:
            raise ProviderError("answer_model_unsupported")
        effort = env.get(effort_key, "").strip() or module.REASONING_EFFORT
        if effort != module.REASONING_EFFORT:
            raise ProviderError("reasoning_effort_unsupported")
        return ChatStageConfig(LUNA, digest({"endpoint": base}), model, effort, _prompt_version(stage), mode)
    base = env.get("TYPESAFE_BASE_URL", "").strip() or NATIVE_DEFAULT_BASE_URL
    validate_base_url(base)
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
    return digest({"schemaVersion": CHAT_SCHEMA_VERSION, "stage": request.stage, "input": _identified_input(request),
                   "config": config.wire()})


def request_digest(request: StageRequest) -> str:
    """What the caller asked under an invocation id, without the configuration: a later configuration change (gate, key, model
    setting) never makes a stored invocation look new or conflicting."""
    return digest({"schemaVersion": CHAT_SCHEMA_VERSION, "stage": request.stage, "mode": request.mode,
                   "input": _identified_input(request)})


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
            return StageResult.model_validate_json(result)
        if status == "sent":
            # Claimed and possibly sent; its outcome was never stored: never send again.
            return _failed(request, "provider_response_unknown", sent=True, unknown=True,
                           receipt=None if receipt is None else Receipt.model_validate_json(receipt))
        return None

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
    return StageResult(schema_version=CHAT_SCHEMA_VERSION, invocation_id=request.invocation_id, stage=request.stage,
                       status="failed", answer=None, failure=StageFailure(code=code, sent=sent, unknown=unknown),
                       receipt=receipt)


def _no_usage() -> Usage:
    return Usage(input_tokens=None, output_tokens=None, cached_tokens=None, reasoning_tokens=None)


def provider_body(request: StageRequest, config: ChatStageConfig) -> tuple[str, dict[str, Any]]:
    """The endpoint path and exact request body a live stage sends."""
    parsed = request.parsed()
    if request.stage == "chat-answer":
        return "chat/completions", chat_luna.build_request(parsed, config.model, config.reasoning_effort)
    if request.stage == "chat-agent":
        return "responses", chat_agent.build_request(parsed, config.model, config.reasoning_effort)
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

    def preflight(self, request: StageRequest, config: ChatStageConfig) -> None:
        key = self._endpoint(config)[1]
        if not key:
            raise ProviderError("provider_key_required")
        # A key with whitespace or control characters (e.g. a trailing space in an env file) cannot travel in a header: the HTTP
        # client refuses it locally, which would look like an unknown fate. Refuse it here, before anything is reserved.
        if any(ord(char) < 33 or ord(char) > 126 for char in key):
            raise ProviderError("provider_key_invalid")

    def send(self, request: StageRequest, config: ChatStageConfig) -> Any:
        base, key = self._endpoint(config)
        path, body = provider_body(request, config)
        with httpx.Client(base_url=base.rstrip("/") + "/", timeout=STAGE_TIMEOUT[request.stage],
                          headers={"Authorization": "Bearer " + key}, follow_redirects=False,
                          transport=self.transport) as client:
            try:
                response = client.post(path, json=body)
            except httpx.TransportError:
                raise ProviderError("provider_response_unknown", uncertain=True) from None
        if not 200 <= response.status_code < 300:
            raise ProviderError("provider_option_unsupported" if response.status_code == 400
                                else f"provider_http_{response.status_code}")
        try:
            return response.json()
        except ValueError:
            return {"responseText": response.text, "httpStatus": response.status_code}


class ReplaySender:
    """Authored fixture matched by the exact request identity. Nothing leaves the process."""

    def __init__(self, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schemaVersion") != CHAT_SCHEMA_VERSION or data.get("recordingKind") != "authored-test":
            raise ProviderError("replay_fixture_invalid")
        self.entries = {entry["inputDigest"]: entry for entry in data["responses"]}

    def _entry(self, request: StageRequest, config: ChatStageConfig) -> dict[str, Any]:
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
    if stage == "chat-agent":
        return Usage(input_tokens=_count(block, "input_tokens"), output_tokens=_count(block, "output_tokens"),
                     cached_tokens=_count(_details(block, "input_tokens_details"), "cached_tokens"),
                     reasoning_tokens=_count(_details(block, "output_tokens_details"), "reasoning_tokens"))
    return Usage(input_tokens=_count(block, "prompt_tokens"), output_tokens=_count(block, "completion_tokens"),
                 cached_tokens=_count(_details(block, "prompt_tokens_details"), "cached_tokens"),
                 reasoning_tokens=_count(_details(block, "completion_tokens_details"), "reasoning_tokens"))


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
    try:
        message = raw["choices"][0]["message"]
        content = message.get("content")
    except (KeyError, IndexError, TypeError, AttributeError):
        raise ValueError("answer_response_invalid") from None
    if message.get("refusal") or not isinstance(content, str):
        raise ValueError("answer_refused")
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
            config = stage_config(request.stage, request.mode, env)
            ceiling = live_ceiling(env) if request.mode == "live" else None
            identity = request_identity(request, config)
            check_grants(request, config.recipient(), registry)
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
        except ValueError as invalid:
            result = _failed(request, str(invalid), sent=True, unknown=False, receipt=receipt)
        except Exception:  # noqa: BLE001 - any other interpretation error keeps the stored raw answer as a definite failure
            result = _failed(request, "provider_response_invalid", sent=True, unknown=False, receipt=receipt)
        else:
            result = StageResult(schema_version=CHAT_SCHEMA_VERSION, invocation_id=request.invocation_id,
                                 stage=request.stage, status="succeeded", answer=answer, failure=None, receipt=receipt)
        ledger.finish(result)
        return result
    finally:
        ledger.close()
