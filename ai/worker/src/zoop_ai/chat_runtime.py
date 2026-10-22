"""One chatbot model stage per invocation: configuration, grants, the invocation ledger, the provider call and its receipt.

Rules (ZOOP-AIG-001 6.3.2-6.3.3, design summary 5.1):

- One request per invocation and no retry or fallback. The ledger in `chat.sqlite3` makes an invocation idempotent: the same
  `invocationId` with the same input returns the stored outcome without sending again; a request that left this process and whose
  outcome was not stored is `unknown` and is never sent again (the provider may have processed and charged it).
- Live calls need `ZOOP_AI_CHAT_LIVE_ENABLED=1` and a positive `ZOOP_AI_CHAT_MAX_CALLS`, a ceiling shared by all chat stages
  and separate from the S1 and pipeline gates. Without them nothing is sent. Replay never touches the network.
- Every quoted span must be allowed by the operator chat grant registry: an enabled grant with known rights, `model-send`, the
  stage as purpose and the exact recipient (`authored-replay`, or `<provider>:<revision>` live). Otherwise nothing is sent.
- Each stage has its own client timeout (router 4 s, answer 25 s, verification 6 s); a timeout after sending is `unknown`.
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

from . import chat_jev, chat_luna
from .chat_contracts import (CHAT_SCHEMA_VERSION, AnswerInput, ChatAnswer, ChatGrantRegistry, Receipt, RouterInput,
                             StageFailure, StageRequest, StageResult, Usage, VerificationInput)
from .contracts import canonical, digest
from .provider import DEFAULT_BASE_URL, EFFORTS, NATIVE_DEFAULT_BASE_URL, ProviderError, native_revision, validate_base_url

STAGE_TIMEOUT = {"chat-router": 4.0, "chat-answer": 25.0, "chat-verification": 6.0}
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
    return chat_luna.prompt_version() if stage == "chat-answer" else chat_jev.prompt_version(stage)


def stage_config(stage: str, mode: str, env: dict[str, str] | None = None) -> ChatStageConfig:
    env = os.environ if env is None else env
    if mode == "replay":
        return ChatStageConfig(REPLAY, "authored-replay-1", "authored-synthetic-" + stage, None, _prompt_version(stage), mode)
    if stage == "chat-answer":
        base = env.get("ZOOP_AI_BASE_URL", "").strip() or DEFAULT_BASE_URL
        validate_base_url(base)
        model = env.get("ZOOP_AI_CHAT_ANSWER_MODEL", "").strip()
        if not model:
            raise ProviderError("stage_model_required")
        effort = env.get("ZOOP_AI_CHAT_ANSWER_REASONING_EFFORT", "").strip() or None
        if effort is not None and effort not in EFFORTS:
            raise ProviderError("reasoning_effort_invalid")
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


def request_identity(request: StageRequest, config: ChatStageConfig) -> str:
    return digest({"schemaVersion": CHAT_SCHEMA_VERSION, "stage": request.stage, "input": request.parsed().wire(),
                   "config": config.wire()})


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


def check_grants(request: StageRequest, config: ChatStageConfig, registry: ChatGrantRegistry | None) -> None:
    quotes = request.quotes()
    if not quotes:
        return
    if registry is None:
        raise ProviderError("source_grant_required")
    now = datetime.now(UTC)
    recipient = config.recipient()
    for quote in quotes:
        allowed = any(
            g.source_id == quote.source_id and g.enabled and g.rights == "known" and "model-send" in g.allowed_operations
            and request.stage in g.purposes and recipient in g.recipients
            and (g.expires_at is None or datetime.fromisoformat(g.expires_at) > now)
            for g in registry.grants)
        if not allowed:
            raise ProviderError("source_grant_denied")


class ChatLedger:
    """`chat.sqlite3`: one row per invocation. `reserved` was never sent; `sent` left the process and is `unknown` if found again."""

    def __init__(self, state_dir: Path):
        self.db = sqlite3.connect(state_dir / "chat.sqlite3", isolation_level=None, timeout=5)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS chat_invocations (
            invocation_id TEXT PRIMARY KEY, stage TEXT NOT NULL, mode TEXT NOT NULL, input_digest TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('reserved','sent','succeeded','failed','unknown')),
            result TEXT, raw TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")

    def close(self) -> None:
        self.db.close()

    def begin(self, request: StageRequest, identity: str, ceiling: int | None) -> StageResult | None:
        """Claims the invocation for sending, or returns its stored outcome. Raises ProviderError for a conflict or budget."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT input_digest, status, result FROM chat_invocations WHERE invocation_id=?",
                                  (request.invocation_id,)).fetchone()
            if row is not None:
                if row[0] != identity:
                    raise ProviderError("invocation_conflict")
                if row[1] in ("succeeded", "failed", "unknown"):
                    return StageResult.model_validate_json(row[2])
                if row[1] == "sent":
                    # A previous process sent it and never stored the outcome: never send again.
                    result = _failed(request, "provider_response_unknown", sent=True, unknown=True, receipt=None)
                    self.db.execute("UPDATE chat_invocations SET status='unknown', result=?, updated_at=? WHERE invocation_id=?",
                                    (canonical(result.wire()), _now(), request.invocation_id))
                    return result
            if ceiling is not None:
                used = self.db.execute("SELECT count(*) FROM chat_invocations WHERE mode='live' AND status<>'reserved'"
                                       ).fetchone()[0]
                if used >= ceiling:
                    raise ProviderError("chat_budget_exhausted")
            if row is None:
                self.db.execute("INSERT INTO chat_invocations VALUES (?,?,?,?, 'reserved', NULL, NULL, ?, ?)",
                                (request.invocation_id, request.stage, request.mode, identity, _now(), _now()))
            self.db.execute("COMMIT")
            return None
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def mark_sent(self, invocation_id: str) -> None:
        self.db.execute("UPDATE chat_invocations SET status='sent', updated_at=? WHERE invocation_id=? AND status='reserved'",
                        (_now(), invocation_id))

    def finish(self, result: StageResult, raw: Any) -> None:
        status = "succeeded" if result.status == "succeeded" else "unknown" if result.failure and result.failure.unknown \
            else "failed"
        self.db.execute("UPDATE chat_invocations SET status=?, result=?, raw=?, updated_at=? WHERE invocation_id=?",
                        (status, canonical(result.wire()), None if raw is None else canonical(raw), _now(),
                         result.invocation_id))


def _failed(request: StageRequest, code: str, *, sent: bool, unknown: bool, receipt: Receipt | None) -> StageResult:
    return StageResult(schema_version=CHAT_SCHEMA_VERSION, invocation_id=request.invocation_id, stage=request.stage,
                       status="failed", answer=None, failure=StageFailure(code=code, sent=sent, unknown=unknown),
                       receipt=receipt)


@dataclass
class Reply:
    raw: Any
    usage: Usage


def _no_usage() -> Usage:
    return Usage(input_tokens=None, output_tokens=None, cached_tokens=None, reasoning_tokens=None)


def provider_body(request: StageRequest, config: ChatStageConfig) -> tuple[str, dict[str, Any]]:
    """The endpoint path and exact request body a live stage sends."""
    parsed = request.parsed()
    if request.stage == "chat-answer":
        return "chat/completions", chat_luna.build_request(parsed, config.model, config.reasoning_effort)
    if request.stage == "chat-router":
        return "systemone", chat_jev.build_router_request(parsed, config.model)
    return "systemone", chat_jev.build_verification_request(parsed, config.model)


class LiveSender:
    """Real HTTP: one POST, no retry, no redirect. Non-2xx is a definite failure; a transport error leaves the fate unknown."""

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
        if not self._endpoint(config)[1]:
            raise ProviderError("provider_key_required")

    def send(self, request: StageRequest, config: ChatStageConfig) -> Reply:
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
            raw = response.json()
        except ValueError:
            raw = {"responseText": response.text, "httpStatus": response.status_code}
        return Reply(raw, _usage(raw, config.provider))


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

    def send(self, request: StageRequest, config: ChatStageConfig) -> Reply:
        entry = self._entry(request, config)
        if "error" in entry:
            raise ProviderError(entry["error"], uncertain=entry.get("uncertain", False))
        return Reply(entry["response"], _no_usage())


def _usage(raw: Any, provider: str) -> Usage:
    block = raw.get("usage") if isinstance(raw, dict) else None
    if not isinstance(block, dict):
        return _no_usage()
    if provider == JEV:
        values = (block.get("input_tokens"), block.get("output_tokens"), None, None)
    else:
        values = (block.get("prompt_tokens"), block.get("completion_tokens"),
                  (block.get("prompt_tokens_details") or {}).get("cached_tokens"),
                  (block.get("completion_tokens_details") or {}).get("reasoning_tokens"))
    if any(v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0) for v in values):
        return _no_usage()
    return Usage(input_tokens=values[0], output_tokens=values[1], cached_tokens=values[2], reasoning_tokens=values[3])


def interpret(request: StageRequest, config: ChatStageConfig, raw: Any) -> dict[str, Any]:
    """The typed answer of a received response, or ValueError with a stable code (the raw response stays the receipt)."""
    parsed = request.parsed()
    if request.stage == "chat-router":
        return chat_jev.interpret_router(raw, parsed, config.model).wire()
    if request.stage == "chat-verification":
        return chat_jev.interpret_verification(raw, parsed, config.model).wire()
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


def invoke(request: StageRequest, *, state_dir: Path, registry: ChatGrantRegistry | None,
           sender: LiveSender | ReplaySender,
           env: dict[str, str] | None = None) -> StageResult:
    """Runs one stage. Never raises for provider or policy outcomes: they become a failed StageResult."""
    ledger = ChatLedger(state_dir)
    try:
        try:
            config = stage_config(request.stage, request.mode, env)
            ceiling = live_ceiling(env) if request.mode == "live" else None
            identity = request_identity(request, config)
            check_grants(request, config, registry)
            sender.preflight(request, config)
        except ProviderError as refused:
            return _failed(request, refused.code, sent=False, unknown=False, receipt=None)
        try:
            stored = ledger.begin(request, identity, ceiling)
        except ProviderError as refused:
            return _failed(request, refused.code, sent=False, unknown=False, receipt=None)
        if stored is not None:
            return stored

        sent_at = _now()
        ledger.mark_sent(request.invocation_id)
        receipt = Receipt(provider=config.provider, provider_revision=config.provider_revision, model=config.model,
                          prompt_version=config.prompt_version, execution_mode=request.mode, usage=_no_usage(),
                          sent_at=sent_at, received_at=None)
        try:
            reply = sender.send(request, config)
        except ProviderError as error:
            result = _failed(request, error.code, sent=True, unknown=error.uncertain, receipt=receipt)
            ledger.finish(result, None)
            return result

        receipt = receipt.model_copy(update={"usage": reply.usage, "received_at": _now()})
        try:
            answer = interpret(request, config, reply.raw)
        except ValueError as invalid:
            result = _failed(request, str(invalid), sent=True, unknown=False, receipt=receipt)
        else:
            result = StageResult(schema_version=CHAT_SCHEMA_VERSION, invocation_id=request.invocation_id,
                                 stage=request.stage, status="succeeded", answer=answer, failure=None, receipt=receipt)
        ledger.finish(result, reply.raw)
        return result
    finally:
        ledger.close()
