"""Live (paid) provider runtime shared by the native S2 and S3 pipelines: real request builders, one-shot HTTP transport,
frozen configuration, shared USD/call budget and strict answer decoding.

Seven stages, two providers (the stage decides the provider; nothing is inferred from an endpoint or a model name):

* `extract`, `compare`, `topic`, `relation`, `impact`: OpenAI-compatible `chat/completions`, `gpt-6-luna` at a pinned reasoning
  effort, strict `json_schema` structured output (`live_prompts`).
* `verify-relation`, `verify-impact`: native TypeSafe Jev `POST /systemone`, model `jev-1.14.0`, an independent verifier that
  answers typed Choice questions about exact quotes (`live_jev`).

Ordering contract of the owner (S2/S3): `prepare` (pure) -> owner rechecks rights -> owner reserves its own durable attempt ->
`send(prepared, attempt_id=..., authorize=...)` -> owner persists the returned receipt BEFORE `answer(stage, receipt)` decodes it.
`send` reserves the shared budget, calls `authorize()` immediately before the socket, sends exactly once (no retry, no redirect, no
proxy from the environment) and returns a receipt for ANY HTTP response, including a non-2xx or malformed one. Only a transport
error or timeout raises `LiveFailure(uncertain=True)`: the budget reservation then stays charged. Nothing in this module reads a
`.env`, a grant, a ledger or a document, and no secret ever appears in a binding, a prepared request, a receipt or an error.

`answer` and `usage` decode purely from the receipt (it embeds the decode context), so a stored receipt is recoverable without
keys and with a drifted environment; `accepts(binding)` is the separate "may a NEW call still use this frozen configuration" test.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from . import live_jev, live_prompts
from .live_budget import Budget, BudgetError, nano_from_usd, usd
from .relation_contracts import canonical, digest

VERSION = "zoop-live-runtime-1"
PREPARED = "zoop-live-prepared-1"
RECEIPT = "zoop-live-receipt-1"

GENERATION_STAGES = ("extract", "compare", "topic", "relation", "impact")
VERIFY_STAGES = ("verify-relation", "verify-impact")
STAGES = GENERATION_STAGES + VERIFY_STAGES

GATE = "ZOOP_AI_PIPELINE_LIVE_ENABLED"
MODEL_VAR = "ZOOP_AI_PIPELINE_LIVE_MODEL"
EFFORT_VAR = "ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT"
MAX_OUTPUT_VAR = "ZOOP_AI_PIPELINE_LIVE_MAX_OUTPUT_TOKENS"
TIMEOUT_VAR = "ZOOP_AI_PIPELINE_LIVE_TIMEOUT_SECONDS"
BUDGET_DIR_VAR = "ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR"
MAX_USD_VAR = "ZOOP_AI_PIPELINE_LIVE_MAX_USD"
MAX_CALLS_VAR = "ZOOP_AI_PIPELINE_LIVE_MAX_CALLS"
OPENAI_URL_VAR, OPENAI_KEY_VAR = "ZOOP_AI_BASE_URL", "ZOOP_AI_API_KEY"
JEV_URL_VAR, JEV_KEY_VAR, JEV_MODEL_VAR = "TYPESAFE_BASE_URL", "TYPESAFE_API_KEY", "TYPESAFE_VALIDATION_MODEL"

MODEL = "gpt-6-luna"
EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")  # gpt-6-luna has no `minimal`
DEFAULT_OPENAI_URL = "https://api.openai.com/v1"
DEFAULT_JEV_URL = "https://api.typesafe.ai/v1"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEFAULT_MAX_OUTPUT, DEFAULT_TIMEOUT = 24_000, 300

MAX_REQUEST_BYTES = 300_000
MAX_VERIFIER_REQUEST_BYTES = 150_000
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
INPUT_OVERHEAD_TOKENS = 1024  # chat framing and structured-output preamble on top of one token per request byte (an upper bound)

# nano-USD per token. Source: https://developers.openai.com/api/docs/pricing (gpt-6-luna standard, read 2026-10-21: input 0.10 /
# output 0.50 USD per 1M up to 272k tokens, 0.20 / 0.75 above) and https://docs.typesafe.ai/models.md (jev-1.14 input 0.042 USD
# per 1M, output free). Budget reservations and settlements ALWAYS use the conservative long-context luna rates, never the cached
# or short-context discount, so a cost is an upper estimate and never a guarantee of the provider's bill.
PRICING = {"asOf": "2026-10-21", "unit": "nanoUsdPerToken", "tier": "conservative-long",
           "sources": ["https://developers.openai.com/api/docs/pricing", "https://docs.typesafe.ai/models.md"],
           "gpt-6-luna": {"input": 200, "output": 750}, "jev-1.14.0": {"input": 42, "output": 0}}

_KINDS = {
    "unavailable": {"live_response_unknown"},
    "invalid": {"live_reply_not_json", "live_answers_invalid", "live_model_mismatch", "live_output_truncated", "live_receipt_invalid",
                "live_response_oversize", "live_payload_invalid"},
    "refused": {"live_model_refusal"},
    "budget": {"live_budget_exhausted_usd", "live_budget_exhausted_calls", "live_budget_attempt_duplicate", "live_budget_ceiling_increase",
               "live_budget_unavailable"},
}


class LiveFailure(Exception):
    """A live-path failure. `code` is stable and never embeds a URL, key or response body. `uncertain` is True only when a request
    may have reached the provider and no response was seen. `kind` classifies for callers: `unavailable` (provider or network
    answered no or nothing), `invalid` (the model/provider content violates a contract), `refused` (an explicit model refusal),
    `budget`, or `config` (everything decided before a send)."""

    def __init__(self, code: str, uncertain: bool = False):
        self.code, self.uncertain = code, uncertain
        self.kind = ("unavailable" if code.startswith("live_http_") else
                     next((kind for kind, codes in _KINDS.items() if code in codes), "config"))
        super().__init__(code)


# ---------------------------------------------------------------- configuration helpers --------------------------------

def _base_url(value: str) -> str:
    """The one endpoint rule: https (http only to loopback), no userinfo/query/fragment, no `/systemone` suffix."""
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL:
        raise LiveFailure("live_endpoint_invalid") from None
    if (url.scheme != "https" and not (url.scheme == "http" and url.host in LOOPBACK_HOSTS)) or url.userinfo or url.query or url.fragment \
            or not url.host or url.path.rstrip("/").endswith("/systemone"):
        raise LiveFailure("live_endpoint_invalid")
    return str(url).rstrip("/")


def _positive_int(text: str, low: int, high: int, code: str) -> int:
    if not text.isascii() or not text.isdigit() or not low <= int(text) <= high:
        raise LiveFailure(code)
    return int(text)


def _token(value: str | None, code: str) -> str:
    if not value or not value.isascii() or not value.isprintable() or " " in value:
        raise LiveFailure(code)
    return value


def _usage_over_bound(reported: dict[str, int | None], reservation: dict[str, Any], provider: str) -> str | None:
    """Why a reported usage cannot be a true measurement of THIS request, or None. A provider cannot have read more input than the
    request's conservative bound, produced more output than `max_completion_tokens`, or cached/reasoned beyond those totals; such a
    block is third-party noise, never a settlement. (Jev's output is unpriced and has no request cap, so only its input is bounded.)"""
    input_bound, output_max = reservation["inputTokensUpperBound"], reservation["outputTokensMax"]
    if reported["inputTokens"] > input_bound:
        return "input_exceeds_bound"
    if provider == "openai-compatible":
        if reported["outputTokens"] > output_max:
            return "output_exceeds_bound"
        if reported["cachedTokens"] is not None and reported["cachedTokens"] > reported["inputTokens"]:
            return "cached_exceeds_input"
        if reported["reasoningTokens"] is not None and reported["reasoningTokens"] > reported["outputTokens"]:
            return "reasoning_exceeds_output"
    return None


def _no_usage() -> dict[str, int | None]:
    return {"inputTokens": None, "outputTokens": None, "cachedTokens": None, "reasoningTokens": None}


def _parse(text: str, truncated: bool) -> Any:
    """The response body as JSON, or None when it is cut or not JSON (including pathological nesting). Never raises."""
    if truncated:
        return None
    try:
        return json.loads(text)
    except (ValueError, RecursionError, MemoryError):
        return None


def _usage(raw: Any, provider: str) -> dict[str, int | None]:
    """Reported token counts, or all unknown. A count must be an int within [0, MAX_REPORTED_TOKENS]; anything else (a bool, a
    float, a negative, an absurd value) makes the whole block unknown so the worst-case charge is kept, never a huge or odd number."""
    if provider == "typesafe-native":
        return live_jev.usage(raw)
    block = raw.get("usage") if isinstance(raw, dict) else None
    if not isinstance(block, dict):
        return _no_usage()
    details = block.get("prompt_tokens_details") if isinstance(block.get("prompt_tokens_details"), dict) else {}
    completion = block.get("completion_tokens_details") if isinstance(block.get("completion_tokens_details"), dict) else {}
    reported = {"inputTokens": block.get("prompt_tokens"), "outputTokens": block.get("completion_tokens"),
                "cachedTokens": details.get("cached_tokens"), "reasoningTokens": completion.get("reasoning_tokens")}
    if any(v is not None and (isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= live_jev.MAX_REPORTED_TOKENS) for v in reported.values()):
        return _no_usage()
    return reported


def _rates(provider: str) -> tuple[int, int]:
    rate = PRICING["jev-1.14.0" if provider == "typesafe-native" else MODEL]
    return rate["input"], rate["output"]


class LiveRuntime:
    """Immutable frozen live configuration plus the one-shot transport. Build with `from_env` (may send) or `from_binding`
    (decode/prepare only)."""

    def __init__(self, *, model: str, effort: str, max_output: int, timeout: int, openai_url: str, jev_url: str, jev_model: str,
                 budget_identity: str, send: dict[str, Any] | None, send_code: str):
        if model != MODEL:
            raise LiveFailure("live_model_unsupported")
        if effort not in EFFORTS:
            raise LiveFailure("live_reasoning_effort_invalid")
        if jev_model != live_jev.MODEL:
            raise LiveFailure("live_jev_model_unsupported")
        if not 1_000 <= max_output <= 100_000 or not 10 <= timeout <= 900:
            raise LiveFailure("live_limit_invalid")
        if not isinstance(budget_identity, str) or len(budget_identity) != 64 or any(c not in "0123456789abcdef" for c in budget_identity):
            raise LiveFailure("live_budget_config_invalid")
        self._model, self._effort, self._max_output, self._timeout = model, effort, max_output, timeout
        self._openai_url, self._jev_url = _base_url(openai_url), _base_url(jev_url)
        self._send, self._send_code, self._budget_identity_value = send, send_code, budget_identity
        self._binding = self._build_binding()
        self._identity = self._binding["identity"]

    def __repr__(self) -> str:
        return f"LiveRuntime(identity={self._identity[:16]})"

    # ------------------------------------------------------------ construction ------------------------------------------

    @classmethod
    def from_env(cls, *, need_send: bool = False, transport: httpx.BaseTransport | None = None) -> LiveRuntime:
        """Validate the explicit live gate and configuration from this process's environment only; no network, no file, no dotenv.
        Mandatory and non-secret: the budget DIRECTORY (`ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR`, absolute) is required here and pinned into
        the binding (nothing is created). Send-only: the keys and the ceilings (`MAX_USD`, `MAX_CALLS`) are NOT needed to freeze,
        `accepts`, `prepare` or `answer`; they are required only by `send`, which fails before any reservation or socket when one is
        missing. `need_send=True` makes that check up front (the operator `check` command). `transport` is a test seam."""
        env = os.environ
        if env.get(GATE) != "1":
            raise LiveFailure("live_not_enabled")
        directory = env.get(BUDGET_DIR_VAR, "")
        identity = cls._budget_identity(directory)  # the budget directory is pinned at freeze time; it is never created here
        send = cls._env_send(env, transport, directory)
        if need_send and any(send["problems"].values()):
            raise LiveFailure(next(code for code in send["problems"].values() if code))
        return cls(model=env.get(MODEL_VAR, "").strip(), effort=env.get(EFFORT_VAR, "").strip(),
                   max_output=_positive_int(env.get(MAX_OUTPUT_VAR) or str(DEFAULT_MAX_OUTPUT), 0, 10**9, "live_limit_invalid"),
                   timeout=_positive_int(env.get(TIMEOUT_VAR) or str(DEFAULT_TIMEOUT), 0, 10**9, "live_limit_invalid"),
                   openai_url=env.get(OPENAI_URL_VAR, "").strip() or DEFAULT_OPENAI_URL,
                   jev_url=env.get(JEV_URL_VAR, "").strip() or DEFAULT_JEV_URL, jev_model=env.get(JEV_MODEL_VAR, "").strip(),
                   budget_identity=identity, send={**send, "directory": directory}, send_code="live_send_unavailable")

    @staticmethod
    def _budget_identity(directory: str) -> str:
        """Canonical identity of a budget directory: the hash of its validated absolute realpath (symlinks resolved, nothing created)."""
        if not directory or "\0" in directory or not os.path.isabs(directory):
            raise LiveFailure("live_budget_config_invalid")
        return digest({"realpath": os.path.realpath(directory)})

    @staticmethod
    def _env_send(env: Any, transport: httpx.BaseTransport | None, directory: str) -> dict[str, Any]:
        """Send-time settings: the budget ceilings and the two keys, each with the code `send` raises when it is missing or malformed.
        The directory itself is pinned by the binding; only its ceilings are send-time."""
        problems: dict[str, str | None] = {"budget": None, "openai": None, "typesafe": None}
        budget = None
        try:
            try:
                max_nano = nano_from_usd(env.get(MAX_USD_VAR, ""))
            except ValueError:
                raise LiveFailure("live_budget_config_invalid") from None
            budget = Budget(Path(os.path.realpath(directory)), max_nano,
                            _positive_int(env.get(MAX_CALLS_VAR, ""), 1, 100_000, "live_budget_config_invalid"))
        except LiveFailure as exc:
            problems["budget"] = exc.code
        keys: dict[str, str | None] = {}
        for name, var, code in (("openai", OPENAI_KEY_VAR, "live_api_key_required"), ("typesafe", JEV_KEY_VAR, "live_typesafe_key_required")):
            try:
                keys[name] = _token(env.get(var), code)
            except LiveFailure as exc:
                keys[name], problems[name] = None, exc.code
        return {"budget": budget, "transport": transport, "openaiKey": keys["openai"], "jevKey": keys["typesafe"], "problems": problems}

    @classmethod
    def from_binding(cls, binding: dict) -> LiveRuntime:
        """Env-less runtime rebuilt from a frozen binding, for decoding stored receipts and preparing requests. Refuses a binding
        that this code would not itself produce (forged, or frozen by different code). It can never send."""
        try:
            generation, verifier = binding["generation"], binding["verifier"]
            runtime = cls(model=generation["model"], effort=generation["reasoningEffort"], max_output=generation["maxOutputTokens"],
                          timeout=DEFAULT_TIMEOUT, openai_url=generation["endpoint"], jev_url=verifier["endpoint"],
                          jev_model=verifier["model"], budget_identity=binding["budget"]["directoryIdentity"], send=None,
                          send_code="live_send_unavailable")
        except (KeyError, TypeError, LiveFailure):
            raise LiveFailure("live_binding_mismatch") from None
        if runtime.binding() != binding:
            raise LiveFailure("live_binding_mismatch")
        return runtime

    # ------------------------------------------------------------ frozen identity ---------------------------------------

    def _stage_entry(self, stage: str) -> dict[str, Any]:
        if stage in GENERATION_STAGES:
            spec = live_prompts.SPECS[stage]
            return {"purpose": f"pipeline:{stage}", "recipient": "openai-compatible:" + digest({"endpoint": self._openai_url}),
                    "provider": "openai-compatible", "promptVersion": spec.prompt_version, "schemaDigest": spec.schema_digest,
                    "maxOutputTokens": self._max_output}
        return {"purpose": f"pipeline:{stage}", "recipient": "typesafe-native:" + digest({"api": live_jev.API, "endpoint": self._jev_url}),
                "provider": "typesafe-native", "promptVersion": "zoop-jev-pipeline-" + live_jev.identity()[:16],
                "questionsDigest": live_jev.identity(), "maxOutputTokens": None}

    def _build_binding(self) -> dict[str, Any]:
        body = {"version": VERSION,
                "generation": {"provider": "openai-compatible", "api": "chat.completions", "endpoint": self._openai_url,
                               "endpointRevision": digest({"endpoint": self._openai_url}), "model": self._model,
                               "reasoningEffort": self._effort, "maxOutputTokens": self._max_output},
                "verifier": {"provider": "typesafe-native", "api": live_jev.API, "endpoint": self._jev_url,
                             "endpointRevision": digest({"api": live_jev.API, "endpoint": self._jev_url}), "model": live_jev.MODEL,
                             "adapterRevision": live_jev.ADAPTER_REVISION, "adapterIdentity": live_jev.identity(),
                             "policy": live_jev.policy()},
                "stages": {stage: self._stage_entry(stage) for stage in STAGES},
                "pricing": PRICING,
                "budget": {"scope": "directory", "directoryIdentity": self._budget_identity_value, "unit": "nanoUsd"},
                "limits": {"maxRequestBytes": MAX_REQUEST_BYTES, "maxVerifierRequestBytes": MAX_VERIFIER_REQUEST_BYTES,
                           "maxResponseBytes": MAX_RESPONSE_BYTES, "inputOverheadTokens": INPUT_OVERHEAD_TOKENS}}
        return {**body, "identity": digest(body)}

    def binding(self) -> dict[str, Any]:
        """Complete secret-free canonical frozen configuration. It pins the budget DIRECTORY identity (hash of its realpath), so a
        frozen job can never run against another budget. Ceilings (USD/calls) and timeout are excluded: they may only be lowered."""
        return json.loads(canonical(self._binding))

    def accepts(self, binding: dict) -> bool:
        """True only when a NEW call under `binding` would use exactly the configuration this process now has."""
        return isinstance(binding, dict) and binding == self._binding

    def recipient(self, stage: str) -> str:
        return self._entry(stage)["recipient"]

    def purpose(self, stage: str) -> str:
        return self._entry(stage)["purpose"]

    def _entry(self, stage: str) -> dict[str, Any]:
        if stage not in STAGES:
            raise LiveFailure("live_stage_unsupported")
        return self._binding["stages"][stage]

    # ------------------------------------------------------------ prepare (pure) ----------------------------------------

    @staticmethod
    def _questions(stage: str, body: Any) -> int:
        """Number of questions a Jev request carries (1 for a chat request). Jev's billing of the shared `state` is not documented as
        once per request, so the reservation assumes the whole request is billed once PER question."""
        return max(1, len(body["questions"])) if stage in VERIFY_STAGES else 1

    def _worst_case(self, stage: str, request_bytes: int, questions: int) -> dict[str, int | str]:
        provider = self._entry(stage)["provider"]
        rate_in, rate_out = _rates(provider)
        input_bound = request_bytes * questions + INPUT_OVERHEAD_TOKENS  # a token is at least one byte, so bytes bound the token count
        output_max = self._max_output if provider == "openai-compatible" else 0
        nano = input_bound * rate_in + output_max * rate_out
        return {"inputTokensUpperBound": input_bound, "outputTokensMax": output_max, "worstCaseNanoUsd": nano, "worstCaseUsd": usd(nano)}

    def prepare(self, stage: str, payload: dict) -> dict[str, Any]:
        """Pure: the exact provider request for a native stage preimage, with deterministic metadata. No HTTP, no budget write."""
        entry = self._entry(stage)
        if not isinstance(payload, dict):
            raise LiveFailure("live_payload_invalid")
        expect = None
        try:
            if stage in GENERATION_STAGES:
                spec = live_prompts.SPECS[stage]
                body = {"model": self._model, "messages": spec.messages(payload),
                        "response_format": {"type": "json_schema", "json_schema": {"name": spec.schema_name, "strict": True, "schema": spec.schema}},
                        "max_completion_tokens": self._max_output, "reasoning_effort": self._effort}
                path, limit, schema_digest = "chat/completions", MAX_REQUEST_BYTES, entry["schemaDigest"]
            else:
                build = live_jev.build_relation_request if stage == "verify-relation" else live_jev.build_impact_request
                body, expect = build(payload, live_jev.MODEL)
                path, limit, schema_digest = "systemone", MAX_VERIFIER_REQUEST_BYTES, entry["questionsDigest"]
            size = len(canonical(body).encode("utf-8"))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise LiveFailure("live_payload_invalid") from None
        if size > limit:
            raise LiveFailure("live_request_too_large")
        prepared = {"format": PREPARED, "stage": stage, "provider": entry["provider"], "purpose": entry["purpose"],
                    "recipient": entry["recipient"], "path": path, "body": body, "requestDigest": digest(body), "requestBytes": size,
                    "bindingIdentity": self._identity, "promptVersion": entry["promptVersion"], "schemaDigest": schema_digest,
                    "expect": expect, "reservation": self._worst_case(stage, size, self._questions(stage, body))}
        return {**prepared, "digest": digest(prepared)}

    def _check_prepared(self, prepared: Any) -> dict[str, Any]:
        try:
            stage = prepared["stage"]
            entry = self._entry(stage)
            body = prepared["body"]
            size = len(canonical(body).encode("utf-8"))
            rest = {k: v for k, v in prepared.items() if k != "digest"}
            sound = (prepared["format"] == PREPARED and prepared["digest"] == digest(rest) and prepared["requestDigest"] == digest(body)
                     and prepared["requestBytes"] == size and prepared["bindingIdentity"] == self._identity
                     and prepared["provider"] == entry["provider"] and prepared["recipient"] == entry["recipient"]
                     and prepared["purpose"] == entry["purpose"] and prepared["reservation"] == self._worst_case(stage, size, self._questions(stage, body))
                     and prepared["path"] == ("chat/completions" if stage in GENERATION_STAGES else "systemone"))
        except (KeyError, TypeError, AttributeError):
            raise LiveFailure("live_prepared_invalid") from None
        if not sound:
            raise LiveFailure("live_binding_mismatch" if isinstance(prepared, dict) and prepared.get("bindingIdentity") != self._identity
                              else "live_prepared_invalid")
        return prepared

    # ------------------------------------------------------------ send (one request) ------------------------------------

    def send(self, prepared: dict, *, attempt_id: str, authorize: Callable[[], None]) -> dict[str, Any]:
        """Reserve the shared budget, authorize, send ONCE, settle reported usage and return the receipt envelope.

        The owner has already reserved `attempt_id` durably in its own ledger. A refusal before the socket (budget, `authorize`)
        raises with nothing sent and the budget reservation released; an exception from `authorize` propagates unchanged. A
        transport error or timeout raises `LiveFailure('live_response_unknown', uncertain=True)` and keeps the reservation charged."""
        prepared = self._check_prepared(prepared)
        if self._send is None:
            raise LiveFailure(self._send_code)
        if self._budget_identity(self._send["directory"]) != self._budget_identity_value:  # a re-pointed path is a different budget
            raise LiveFailure("live_config_changed")
        if not isinstance(attempt_id, str) or not 1 <= len(attempt_id) <= 200:
            raise LiveFailure("live_prepared_invalid")
        stage, provider = prepared["stage"], prepared["provider"]
        problems = self._send["problems"]
        missing = problems["budget"] or problems["openai" if provider == "openai-compatible" else "typesafe"]
        if missing:  # definite, before any reservation or socket
            raise LiveFailure(missing)
        budget: Budget = self._send["budget"]
        try:
            budget.reserve(attempt_id, stage, prepared["recipient"], prepared["requestDigest"], prepared["reservation"]["worstCaseNanoUsd"])
        except BudgetError as exc:
            raise LiveFailure(exc.code) from None
        try:
            authorize()
        except BaseException:
            try:
                budget.release(attempt_id)
            except BudgetError:
                pass  # the reservation stays charged: conservative, and nothing was sent
            raise
        base = self._openai_url if provider == "openai-compatible" else self._jev_url
        key = self._send["openaiKey"] if provider == "openai-compatible" else self._send["jevKey"]
        try:
            status, content_type, raw_bytes, truncated = self._post(base, prepared["path"], key, canonical(prepared["body"]).encode("utf-8"))
        except Exception:  # once the request may have left the process every failure is an unknown outcome
            raise LiveFailure("live_response_unknown", uncertain=True) from None
        text = raw_bytes.decode("utf-8", errors="replace")
        reserved = prepared["reservation"]["worstCaseNanoUsd"]
        # From here on the response is in hand and MUST come back as a raw receipt whatever its content: nothing below may raise.
        raw = _parse(text, truncated)
        try:
            reported = _usage(raw, provider)
        except Exception:
            reported = _no_usage()
        actual, rejected = None, None
        # Only a 2xx response with fully reported usage may settle below the worst case; a non-2xx stays at it whatever its body says.
        if 200 <= status < 300 and reported["inputTokens"] is not None and reported["outputTokens"] is not None:
            rejected = _usage_over_bound(reported, prepared["reservation"], provider)
            if rejected is None:
                rate_in, rate_out = _rates(provider)
                actual = reported["inputTokens"] * rate_in + reported["outputTokens"] * rate_out
        try:
            charged, settled = budget.settle(attempt_id, actual), True
        except Exception:  # incl. an overflow or a database failure: the worst-case charge simply stays and the receipt says so
            charged, settled = reserved, False
        model = raw["model"][:200] if isinstance(raw, dict) and isinstance(raw.get("model"), str) else None
        # `usage` keeps what the provider reported, even when it is rejected as implausible (`cost.usageRejected`), so nothing is hidden.
        return {"format": RECEIPT, "stage": stage, "attemptId": attempt_id, "recipient": prepared["recipient"], "purpose": prepared["purpose"],
                "bindingIdentity": self._identity, "requestDigest": prepared["requestDigest"],
                "http": {"status": status, "contentType": content_type[:200] if content_type else None,
                         "bodySha256": hashlib.sha256(raw_bytes).hexdigest(), "bodyText": text, "truncated": truncated},
                "model": {"requested": prepared["body"]["model"], "reported": model}, "usage": reported,
                "cost": {"currency": "USD", "tier": PRICING["tier"], "usageKnown": actual is not None, "usageRejected": rejected,
                         "settled": settled, "estimatedUsd": usd(actual) if actual is not None else None, "chargedUsd": usd(charged),
                         "reservedUsd": usd(reserved)},
                "expect": prepared["expect"]}

    def _post(self, base: str, path: str, key: str, body: bytes) -> tuple[int, str | None, bytes, bool]:
        deadline = time.monotonic() + self._timeout
        headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json", "Accept": "application/json"}
        with httpx.Client(base_url=base + "/", timeout=httpx.Timeout(self._timeout), headers=headers, follow_redirects=False,
                          trust_env=False, transport=self._send["transport"]) as client:
            with client.stream("POST", path, content=body) as response:
                chunks: list[bytes] = []
                size, truncated = 0, False
                for chunk in response.iter_bytes():
                    if time.monotonic() > deadline:
                        raise httpx.ReadTimeout("deadline")
                    if size + len(chunk) > MAX_RESPONSE_BYTES:
                        chunks.append(chunk[: MAX_RESPONSE_BYTES - size])
                        truncated = True
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                return response.status_code, response.headers.get("content-type"), b"".join(chunks), truncated

    # ------------------------------------------------------------ decode (pure, receipt only) ---------------------------

    @staticmethod
    def _receipt(stage: str, receipt: Any) -> tuple[dict, dict]:
        try:
            if stage not in STAGES or receipt["format"] != RECEIPT or receipt["stage"] != stage:
                raise LiveFailure("live_receipt_invalid")
            http = receipt["http"]
            if type(http["status"]) is not int or not isinstance(http["bodyText"], str) or not isinstance(receipt["model"]["requested"], str):
                raise LiveFailure("live_receipt_invalid")
        except (KeyError, TypeError):
            raise LiveFailure("live_receipt_invalid") from None
        return receipt, http

    @staticmethod
    def _decode(stage: str, receipt: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        receipt, http = LiveRuntime._receipt(stage, receipt)
        if not 200 <= http["status"] < 300:
            raise LiveFailure(f"live_http_{http['status']}")
        if http.get("truncated") is True:
            raise LiveFailure("live_response_oversize")
        cost = receipt.get("cost")
        if isinstance(cost, dict) and (cost.get("settled") is False or cost.get("usageRejected")):  # accounting unrecorded or provider usage implausible
            raise LiveFailure("live_receipt_invalid")
        try:
            raw = json.loads(http["bodyText"])
        except (ValueError, RecursionError, MemoryError):
            raise LiveFailure("live_reply_not_json") from None
        if stage in VERIFY_STAGES:
            try:
                expect = receipt["expect"]
                interpret = live_jev.interpret_relation if stage == "verify-relation" else live_jev.interpret_impact
                if expect["kind"] != stage:
                    raise LiveFailure("live_receipt_invalid")
                return interpret(raw, expect, receipt["model"]["requested"])
            except (KeyError, TypeError, IndexError):
                raise LiveFailure("live_receipt_invalid") from None
            except ValueError as exc:
                raise LiveFailure(str(exc) if str(exc) in {"live_answers_invalid", "live_model_mismatch"} else "live_answers_invalid") from None
        try:
            choice = raw["choices"][0]
            message = choice["message"]
            if message.get("refusal") or choice.get("finish_reason") == "content_filter":
                raise LiveFailure("live_model_refusal")
            if choice.get("finish_reason") == "length":
                raise LiveFailure("live_output_truncated")
            content = message["content"]
        except (KeyError, IndexError, TypeError, AttributeError):
            raise LiveFailure("live_answers_invalid") from None
        if not isinstance(content, str):
            raise LiveFailure("live_answers_invalid")
        try:
            answer = json.loads(content)
        except (ValueError, RecursionError, MemoryError):
            raise LiveFailure("live_reply_not_json") from None
        if not isinstance(answer, dict):
            raise LiveFailure("live_reply_not_json")
        return answer, []

    def answer(self, stage: str, receipt: dict) -> dict[str, Any]:
        """Pure strict decode of a stored receipt into the stage's native response JSON. Raises LiveFailure (never uncertain) for a
        non-2xx, an oversize, a refusal, a truncation, a non-JSON reply or a Jev answer that breaks the question contract. Output
        of the generation stages is the decoded JSON untouched; Jev stages go through the explicit question/rubric policy."""
        return self._decode(stage, receipt)[0]

    def audit(self, stage: str, receipt: dict) -> list[dict[str, Any]]:
        """Per-question Jev distributions, confidences and the generated policy notes for the owner's audit record ([] for the
        generation stages). Same strict decode as `answer`."""
        return self._decode(stage, receipt)[1]

    def usage(self, receipt: dict) -> dict[str, Any]:
        """Model-reported model/tokens and the estimated and charged USD from the receipt; null where unknown, never fabricated."""
        try:
            counts = receipt["usage"]
            cost = receipt["cost"]
            return {"model": receipt["model"]["reported"], "inputTokens": counts["inputTokens"], "outputTokens": counts["outputTokens"],
                    "cachedTokens": counts["cachedTokens"], "reasoningTokens": counts["reasoningTokens"],
                    "estimatedUsd": cost["estimatedUsd"], "chargedUsd": cost["chargedUsd"], "usageKnown": cost["usageKnown"]}
        except (KeyError, TypeError):
            raise LiveFailure("live_receipt_invalid") from None


# ---------------------------------------------------------------- offline operator CLI -----------------------------------

def main(argv: list[str] | None = None) -> int:
    """`python -m zoop_ai_pipeline.live_runtime binding|check`: offline, no network, no file, keys only as presence booleans.
    `binding` validates the non-secret configuration; `check` additionally requires the budget variables and both keys."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in {"binding", "check"}:
        print("usage: python -m zoop_ai_pipeline.live_runtime binding|check", file=sys.stderr)
        return 2
    try:
        runtime = LiveRuntime.from_env(need_send=args[0] == "check")
    except LiveFailure as exc:
        print(canonical({"ok": False, "error": exc.code, "kind": exc.kind}))
        return 2
    binding = runtime.binding()
    print(canonical({"ok": True, "check": args[0] == "check", "binding": binding, "identity": binding["identity"],
                     "recipients": {s: runtime.recipient(s) for s in STAGES}, "purposes": {s: runtime.purpose(s) for s in STAGES},
                     "keysPresent": {"openai": bool(os.environ.get(OPENAI_KEY_VAR)), "typesafe": bool(os.environ.get(JEV_KEY_VAR))},
                     "network": "none"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
