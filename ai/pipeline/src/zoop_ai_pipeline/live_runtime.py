"""Live (paid) provider runtime shared by the native S2 and S3 pipelines: real request builders, one-shot HTTP transport,
frozen configuration, shared USD/call budget and strict answer decoding.

Seven stages, two providers (the stage decides the provider; nothing is inferred from an endpoint or a model name):

* `extract`, `compare`, `topic`, `relation`, `impact`: OpenAI-compatible `chat/completions`, `gpt-6-luna` at a pinned reasoning
  effort, strict `json_schema` structured output (`live_prompts`).
* `verify-relation`, `verify-impact`: native TypeSafe Jev `POST /systemone`, model `jev-1.14.0`, an independent verifier that
  answers typed Choice questions about exact quotes (`live_jev`).

A `Family` (`live_family`) is one frozen stage set with its own binding `version`: PIPELINE (the seven stages above, the default; its
binding, prepared requests and receipts are byte-identical to before families existed) and ISSUE_SUMMARY (`issue-summary` on
`gpt-6-luna`, `verify-issue-summary` on Jev; `issue_summary_prompts`, `issue_summary_jev`). Stages never cross families, the budget
directory and keys are shared, and `from_binding` picks the family from the binding's `version`.

The optional `overnight-funded-v1` profile adds two account buckets and a fixed execution window under a NEW binding/receipt
version. It supports exact pinned Luna/Standard or OpenCode Go DeepSeek/JSON-object generation; both retain native Jev.
Unfunded families, prepared requests and receipts retain their historical interpretation.

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
import re
import sys
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from . import issue_summary_jev, issue_summary_prompts, live_jev, live_prompts
from . import direct_deepseek, fallback_decision, live_funding
from .live_budget import Budget, BudgetError, nano_from_usd, usd
from .live_family import Family, Verifier
from .relation_contracts import canonical, digest

VERSION = "zoop-live-runtime-1"
PREPARED = "zoop-live-prepared-1"
RECEIPT = "zoop-live-receipt-1"
FUNDED_SUFFIX = "-funded-1"
FUNDED_PREPARED = "zoop-live-prepared-2"
FUNDED_RECEIPT = "zoop-live-receipt-2"
SET_FUNDED_SUFFIX = "-funded-2"
FINISH_FUNDED_SUFFIX = "-funded-3"
SET_FUNDED_PREPARED = "zoop-live-prepared-3"
SET_FUNDED_RECEIPT = "zoop-live-receipt-3"
CHAIN_RECEIPT = "zoop-live-chain-receipt-1"

GENERATION_STAGES = ("extract", "compare", "topic", "relation", "impact")
VERIFY_STAGES = ("verify-relation", "verify-impact")
STAGES = GENERATION_STAGES + VERIFY_STAGES

# A family is one frozen stage set with its own binding `version`. PIPELINE is the default and its binding/prepare/receipt bytes are
# unchanged by the family mechanism; every other family has stages no other family has, so a stage never crosses families.
PIPELINE = Family(VERSION, live_prompts.SPECS, Verifier(
    live_jev.API, live_jev.MODEL, live_jev.ADAPTER_REVISION, live_jev.identity, live_jev.policy, "zoop-jev-pipeline-",
    {"verify-relation": live_jev.build_relation_request, "verify-impact": live_jev.build_impact_request},
    {"verify-relation": live_jev.interpret_relation, "verify-impact": live_jev.interpret_impact}))
ISSUE_SUMMARY = Family("zoop-issue-summary-runtime-1", issue_summary_prompts.SPECS, issue_summary_jev.VERIFIER)
FAMILIES = {PIPELINE.version: PIPELINE, ISSUE_SUMMARY.version: ISSUE_SUMMARY}
FAMILY_NAMES = {"pipeline": PIPELINE, "issue-summary": ISSUE_SUMMARY}

GATE = "ZOOP_AI_PIPELINE_LIVE_ENABLED"
MODEL_VAR = "ZOOP_AI_PIPELINE_LIVE_MODEL"
EFFORT_VAR = "ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT"
MAX_OUTPUT_VAR = "ZOOP_AI_PIPELINE_LIVE_MAX_OUTPUT_TOKENS"
TIMEOUT_VAR = "ZOOP_AI_PIPELINE_LIVE_TIMEOUT_SECONDS"
BUDGET_DIR_VAR = "ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR"
MAX_USD_VAR = "ZOOP_AI_PIPELINE_LIVE_MAX_USD"
MAX_CALLS_VAR = "ZOOP_AI_PIPELINE_LIVE_MAX_CALLS"
PROFILE_VAR = "ZOOP_AI_PIPELINE_LIVE_PROFILE"
RUN_ID_VAR = "ZOOP_AI_PIPELINE_LIVE_RUN_ID"
NOT_AFTER_VAR = "ZOOP_AI_PIPELINE_LIVE_NOT_AFTER"
SHARED_MAX_VAR = "ZOOP_AI_PIPELINE_LIVE_SHARED_MAX_USD"
PERSONAL_MAX_VAR = "ZOOP_AI_PIPELINE_LIVE_PERSONAL_MAX_USD"
ADMIT_FROM_VAR = "ZOOP_AI_PIPELINE_LIVE_ADMIT_FROM"
ADMIT_UNTIL_VAR = "ZOOP_AI_PIPELINE_LIVE_ADMIT_UNTIL"
SET_ID_VAR = "ZOOP_AI_PIPELINE_LIVE_SET_ID"
FINISH_BY_VAR = live_funding.FINISH_BY_ENV
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

# Separate pricing identity: historical bindings continue using PRICING verbatim.
FUNDED_PRICING = {**PRICING, "asOf": "2026-10-27", "tier": "conservative-long-and-go-peak",
                  "sources": [*PRICING["sources"], "https://opencode.ai/v2/docs/console/go/",
                              "https://developers.openai.com/api/docs/models/gpt-6-luna"],
                  live_funding.GO_MODEL: {"input": 300, "output": 1200}}
SET_PRICING = {**PRICING, "asOf": "2026-10-28", "tier": "conservative-long-cache-write-and-direct-deepseek-peak",
               "revision": "zoop-set-pricing-cache-write-1",
               "sources": [*PRICING["sources"], *direct_deepseek.PRICING["sources"]],
               # Standard long context: uncached .20, cached .02, 30m write .25,
               # 12h write .50 USD/M. Charge total input ONCE at the highest
               # category rate; neither missing breakdown nor unknown retention
               # creates a discount or an additional write charge.
               MODEL: {"input": 500, "output": 750, "uncachedInput": 200, "cachedInput": 20,
                       "cacheWrite30m": 250, "cacheWrite12h": 500,
                       "inputChargePolicy": "highest-standard-category-on-total-input-once"},
               direct_deepseek.MODEL: direct_deepseek.PRICING_NANO}

_KINDS = {
    "unavailable": {"live_response_unknown"},
    "invalid": {"live_reply_not_json", "live_answers_invalid", "live_model_mismatch", "live_output_truncated", "live_receipt_invalid",
                "live_response_oversize", "live_payload_invalid"},
    "refused": {"live_model_refusal"},
    "budget": {"live_budget_exhausted_usd", "live_budget_exhausted_calls", "live_budget_attempt_duplicate", "live_budget_ceiling_increase",
               "live_budget_unavailable", "live_budget_exhausted_shared", "live_budget_exhausted_personal",
               "live_budget_policy_mismatch", "live_budget_deadline", "live_budget_deadline_increase",
               "live_budget_verification_blocked"},
}


class LiveFailure(Exception):
    """A live-path failure. `code` is stable and never embeds a URL, key or response body. `uncertain` is True only when a request
    may have reached the provider and no response was seen. `kind` classifies for callers: `unavailable` (provider or network
    answered no or nothing), `invalid` (the model/provider content violates a contract), `refused` (an explicit model refusal),
    `budget`, or `config` (everything decided before a send)."""

    def __init__(self, code: str, uncertain: bool = False, receipt: dict | None = None):
        self.code, self.uncertain, self.receipt = code, uncertain, receipt
        self.kind = ("unavailable" if code.startswith("live_http_") else
                     next((kind for kind, codes in _KINDS.items() if code in codes), "config"))
        super().__init__(code)


def physical_attempts(receipt: dict) -> list[dict]:
    """Physical provider work, never logical job count; historical receipts remain one attempt."""
    if receipt.get("format") != CHAIN_RECEIPT:
        return [{"attemptId": receipt.get("attemptId"), "state": "received", "receipt": receipt, "error": None}]
    rows = receipt.get("physicalAttempts")
    if (not isinstance(rows, list) or not 1 <= len(rows) <= 2
            or any(not isinstance(row, dict) or row.get("state") not in {"received", "released", "unknown"}
                   or not isinstance(row.get("attemptId"), str) for row in rows)):
        raise LiveFailure("live_receipt_invalid")
    return rows


def _physical_id(logical_id: str, ordinal: int) -> str:
    return "physical-" + digest({"logicalAttemptId": logical_id, "ordinal": ordinal})


def _sum_usd(values) -> str:
    return format(sum((Decimal(value) for value in values), Decimal(0)), ".9f")


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
        if reported.get("cacheWriteTokens") is not None and reported["cacheWriteTokens"] > reported["inputTokens"]:
            return "cache_write_exceeds_input"
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


def _cache_write_usage(raw: Any) -> tuple[int | None, str | None]:
    """Observe the counter only; an absent retention/breakdown is never zero or free."""
    block = raw.get("usage") if isinstance(raw, dict) else None
    details = block.get("prompt_tokens_details") if isinstance(block, dict) else None
    if not isinstance(details, dict) or "cache_write_tokens" not in details:
        return None, None
    count = details["cache_write_tokens"]
    if type(count) is not int or not 0 <= count <= live_jev.MAX_REPORTED_TOKENS:
        return None, "cache_write_usage_invalid"
    return count, None


class LiveRuntime:
    """Immutable frozen live configuration plus the one-shot transport. Build with `from_env` (may send) or `from_binding`
    (decode/prepare only)."""

    def __init__(self, *, model: str, effort: str, max_output: int, timeout: int, openai_url: str, jev_url: str, jev_model: str,
                 budget_identity: str, send: dict[str, Any] | None, send_code: str, family: Family = PIPELINE,
                 funding: dict | None = None, finish_by: str | None = None):
        try:
            self._funding = live_funding.validate_policy(funding) if funding is not None else None
        except ValueError:
            raise LiveFailure("live_funding_config_invalid") from None
        self._set_funding = live_funding.is_set_policy(self._funding)
        try:
            self._finish = live_funding.finish_policy(finish_by) if finish_by is not None else None
            if self._finish and not self._set_funding:
                raise ValueError
        except ValueError:
            raise LiveFailure("live_finish_policy_invalid") from None
        self._prepared_format = SET_FUNDED_PREPARED if self._set_funding else FUNDED_PREPARED if self._funding else PREPARED
        self._receipt_format = SET_FUNDED_RECEIPT if self._set_funding else FUNDED_RECEIPT if self._funding else RECEIPT
        self._direct = self._set_funding and model == direct_deepseek.MODEL
        self._chain = self._set_funding and model == MODEL
        go = bool(self._funding) and not self._set_funding and model == live_funding.GO_MODEL
        if model != MODEL and not go and not self._direct:
            raise LiveFailure("live_model_unsupported")
        if (go and effort != "provider-default") or (not go and effort not in EFFORTS):
            raise LiveFailure("live_reasoning_effort_invalid")
        if jev_model != family.verifier.model:
            raise LiveFailure("live_jev_model_unsupported")
        if not 1_000 <= max_output <= 100_000 or not 10 <= timeout <= 900:
            raise LiveFailure("live_limit_invalid")
        if not isinstance(budget_identity, str) or len(budget_identity) != 64 or any(c not in "0123456789abcdef" for c in budget_identity):
            raise LiveFailure("live_budget_config_invalid")
        self._family = family
        self._model, self._effort, self._max_output, self._timeout = model, effort, max_output, timeout
        self._openai_url, self._jev_url = _base_url(openai_url), _base_url(jev_url)
        self._send, self._send_code, self._budget_identity_value = send, send_code, budget_identity
        if self._funding:
            expected_url = direct_deepseek.BASE_URL if self._direct else live_funding.GO_URL if go else DEFAULT_OPENAI_URL
            if self._openai_url != expected_url or self._jev_url != DEFAULT_JEV_URL:
                raise LiveFailure("live_endpoint_invalid")
            if (not go and effort != "high") or timeout > 300:
                raise LiveFailure("live_limit_invalid")
        self._pricing = SET_PRICING if self._set_funding else FUNDED_PRICING if self._funding else PRICING
        self._binding = self._build_binding()
        self._identity = self._binding["identity"]

    def __repr__(self) -> str:
        return f"LiveRuntime(identity={self._identity[:16]})"

    # ------------------------------------------------------------ construction ------------------------------------------

    @classmethod
    def from_env(cls, *, need_send: bool = False, transport: httpx.BaseTransport | None = None, family: Family = PIPELINE) -> LiveRuntime:
        """Validate the explicit live gate and configuration from this process's environment only; no network, no file, no dotenv.
        Mandatory and non-secret: the budget DIRECTORY (`ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR`, absolute) is required here and pinned into
        the binding (nothing is created). The capped set profile also requires MAX_USD, SHARED_MAX_USD and PERSONAL_MAX_USD
        at freeze time; these exact amounts are immutable binding inputs. Keys and MAX_CALLS remain send-only, as do the
        historical profiles' ceilings. `need_send=True` checks send settings up front. `transport` is a test seam. `family`
        selects the stage set (default PIPELINE, whose binding is unchanged); the environment variables are the same for every family."""
        env = os.environ
        if env.get(GATE) != "1":
            raise LiveFailure("live_not_enabled")
        directory = env.get(BUDGET_DIR_VAR, "")
        identity = cls._budget_identity(directory)  # the budget directory is pinned at freeze time; it is never created here
        profile = env.get(PROFILE_VAR, "").strip()
        if profile not in ("", live_funding.PROFILE, live_funding.CAPPED_PROFILE):
            raise LiveFailure("live_profile_unsupported")
        try:
            funding = (live_funding.capped_set_funding_policy(
                env.get(RUN_ID_VAR, ""), env.get(ADMIT_FROM_VAR, ""), env.get(ADMIT_UNTIL_VAR, ""),
                *live_funding.funding_amounts({"totalMaxUsd": env.get(MAX_USD_VAR), "sharedMaxUsd": env.get(SHARED_MAX_VAR),
                                              "personalMaxUsd": env.get(PERSONAL_MAX_VAR)}))
                if profile == live_funding.CAPPED_PROFILE else
                live_funding.funding_policy(env.get(RUN_ID_VAR, ""), env.get(NOT_AFTER_VAR, "")) if profile else None)
        except ValueError:
            raise LiveFailure("live_funding_config_invalid") from None
        if funding and env.get(MODEL_VAR, "").strip() == live_funding.GO_MODEL and not env.get(MAX_OUTPUT_VAR):
            raise LiveFailure("live_limit_invalid")
        finish_by = env.get(FINISH_BY_VAR) if profile == live_funding.CAPPED_PROFILE else None
        if profile == live_funding.CAPPED_PROFILE and finish_by is None:
            raise LiveFailure("live_finish_policy_required")
        send = cls._env_send(env, transport, directory, funding, finish_by)
        if need_send and any(send["problems"].values()):
            raise LiveFailure(next(code for code in send["problems"].values() if code))
        return cls(model=env.get(MODEL_VAR, "").strip(), effort=env.get(EFFORT_VAR, "").strip(),
                   max_output=_positive_int(env.get(MAX_OUTPUT_VAR) or str(DEFAULT_MAX_OUTPUT), 0, 10**9, "live_limit_invalid"),
                   timeout=_positive_int(env.get(TIMEOUT_VAR) or str(DEFAULT_TIMEOUT), 0, 10**9, "live_limit_invalid"),
                   openai_url=env.get(OPENAI_URL_VAR, "").strip() or DEFAULT_OPENAI_URL,
                   jev_url=env.get(JEV_URL_VAR, "").strip() or DEFAULT_JEV_URL, jev_model=env.get(JEV_MODEL_VAR, "").strip(),
                   budget_identity=identity, send={**send, "directory": directory}, send_code="live_send_unavailable", family=family,
                   funding=funding, finish_by=finish_by)

    @staticmethod
    def _budget_identity(directory: str) -> str:
        """Canonical identity of a budget directory: the hash of its validated absolute realpath (symlinks resolved, nothing created)."""
        if not directory or "\0" in directory or not os.path.isabs(directory):
            raise LiveFailure("live_budget_config_invalid")
        return digest({"realpath": os.path.realpath(directory)})

    @staticmethod
    def _env_send(env: Any, transport: httpx.BaseTransport | None, directory: str, funding: dict | None = None,
                  finish_by: str | None = None) -> dict[str, Any]:
        """Send settings; capped policies already pin the exact monetary ceilings at freeze time."""
        problems: dict[str, str | None] = {"budget": None, "openai": None, "typesafe": None}
        budget = None
        try:
            try:
                max_nano = nano_from_usd(env.get(MAX_USD_VAR, ""))
            except ValueError:
                raise LiveFailure("live_budget_config_invalid") from None
            caps = None
            if funding and funding["version"] == live_funding.CAPPED_POLICY_VERSION:
                max_nano, caps = funding["totalMaxNanoUsd"], funding["bucketMaxNanoUsd"]
            elif funding:
                try:
                    caps = {name: (0 if env.get(var) == "0" else nano_from_usd(env.get(var, "10")))
                            for name, var in (("shared", SHARED_MAX_VAR), ("personal", PERSONAL_MAX_VAR))}
                except ValueError:
                    raise LiveFailure("live_funding_config_invalid") from None
            budget = Budget(Path(os.path.realpath(directory)), max_nano,
                            _positive_int(env.get(MAX_CALLS_VAR, ""), 1, 100_000, "live_budget_config_invalid"),
                            funding=funding, bucket_caps=caps, finish_by=finish_by)
        except (LiveFailure, BudgetError) as exc:
            problems["budget"] = exc.code
        keys: dict[str, str | None] = {}
        generation_key = direct_deepseek.KEY_VAR if env.get(MODEL_VAR) == direct_deepseek.MODEL else OPENAI_KEY_VAR
        for name, var, code in (("openai", generation_key, "live_api_key_required"), ("typesafe", JEV_KEY_VAR, "live_typesafe_key_required")):
            try:
                keys[name] = _token(env.get(var), code)
            except LiveFailure as exc:
                keys[name], problems[name] = None, exc.code
        if live_funding.is_set_policy(funding) and not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", env.get(SET_ID_VAR, "")):
            problems["budget"] = problems["budget"] or "live_set_not_admitted"
        try:
            deepseek_key, deepseek_problem = _token(env.get(direct_deepseek.KEY_VAR), "live_deepseek_key_required"), None
        except LiveFailure as exc:
            deepseek_key, deepseek_problem = None, exc.code
        return {"budget": budget, "transport": transport, "openaiKey": keys["openai"], "jevKey": keys["typesafe"],
                "problems": problems, "setId": env.get(SET_ID_VAR),
                "sendBefore": env.get(live_funding.SEND_BEFORE_ENV),
                "deepseekKey": deepseek_key, "deepseekProblem": deepseek_problem}

    @classmethod
    def from_binding(cls, binding: dict) -> LiveRuntime:
        """Env-less runtime rebuilt from a frozen binding, for decoding stored receipts and preparing requests. Refuses a binding
        that this code would not itself produce (forged, or frozen by different code). It can never send. The binding's `version`
        selects the family; an unknown version is a mismatch."""
        try:
            version = binding["version"]
            suffix = next((suffix for suffix in (FUNDED_SUFFIX, SET_FUNDED_SUFFIX, FINISH_FUNDED_SUFFIX) if version.endswith(suffix)), "")
            funded = bool(suffix)
            family = FAMILIES[version.removesuffix(suffix) if funded else version]
            generation, verifier = binding["generation"], binding["verifier"]
            runtime = cls(model=generation["model"], effort=generation["reasoningEffort"], max_output=generation["maxOutputTokens"],
                          timeout=DEFAULT_TIMEOUT, openai_url=generation["endpoint"], jev_url=verifier["endpoint"],
                          jev_model=verifier["model"], budget_identity=binding["budget"]["directoryIdentity"], send=None,
                          send_code="live_send_unavailable", family=family, funding=binding["funding"] if funded else None,
                          finish_by=binding["finishPolicy"]["finishBy"] if suffix == FINISH_FUNDED_SUFFIX else None)
        except (KeyError, TypeError, AttributeError, LiveFailure):
            raise LiveFailure("live_binding_mismatch") from None
        if runtime.binding() != binding:
            raise LiveFailure("live_binding_mismatch")
        return runtime

    # ------------------------------------------------------------ frozen identity ---------------------------------------

    @property
    def family(self) -> Family:
        return self._family

    def _funding_entry(self, stage: str) -> dict[str, str]:
        role = ("personal-typesafe" if stage in self._family.verify_stages else
                "personal-deepseek" if self._direct else "personal-opencode" if self._model == live_funding.GO_MODEL else "shared-openai")
        return {"accountRole": role, "bucket": self._funding["roles"][role]["bucket"],
                "policyIdentity": digest(self._funding)}

    def _fallback_runtime(self):
        send = None
        if self._send is not None:
            send = {**self._send, "openaiKey": self._send["deepseekKey"],
                    "problems": {**self._send["problems"], "openai": self._send["deepseekProblem"]}}
        return LiveRuntime(model=direct_deepseek.MODEL, effort="high", max_output=self._max_output,
                           timeout=self._timeout, openai_url=direct_deepseek.BASE_URL, jev_url=self._jev_url,
                           jev_model=self._family.verifier.model, budget_identity=self._budget_identity_value,
                           send=send, send_code=self._send_code, family=self._family, funding=self._funding,
                           finish_by=self._finish["finishBy"] if self._finish else None)

    def fallback_recipient(self, stage: str) -> str | None:
        if self._chain and stage in self._family.generation_stages:
            return self._funding["roles"]["personal-deepseek"]["recipient"]
        return None

    def _rate(self, provider: str) -> tuple[int, int]:
        rate = self._pricing[self._family.verifier.model if provider == "typesafe-native" else self._model]
        return rate["input"], rate["output"]

    def _stage_entry(self, stage: str) -> dict[str, Any]:
        family = self._family
        if stage in family.generation_stages:
            spec = family.generation[stage]
            return {"purpose": f"pipeline:{stage}", "recipient": "openai-compatible:" + digest({"endpoint": self._openai_url}),
                    "provider": "openai-compatible", "promptVersion": spec.prompt_version, "schemaDigest": spec.schema_digest,
                    "maxOutputTokens": self._max_output}
        verifier = family.verifier
        return {"purpose": f"pipeline:{stage}", "recipient": "typesafe-native:" + digest({"api": verifier.api, "endpoint": self._jev_url}),
                "provider": "typesafe-native", "promptVersion": verifier.prompt_prefix + verifier.identity()[:16],
                "questionsDigest": verifier.identity(), "maxOutputTokens": None}

    def _build_binding(self) -> dict[str, Any]:
        family, verifier = self._family, self._family.verifier
        body = {"version": family.version,
                "generation": {"provider": "openai-compatible", "api": "chat.completions", "endpoint": self._openai_url,
                               "endpointRevision": digest({"endpoint": self._openai_url}), "model": self._model,
                               "reasoningEffort": self._effort, "maxOutputTokens": self._max_output},
                "verifier": {"provider": "typesafe-native", "api": verifier.api, "endpoint": self._jev_url,
                             "endpointRevision": digest({"api": verifier.api, "endpoint": self._jev_url}), "model": verifier.model,
                             "adapterRevision": verifier.revision, "adapterIdentity": verifier.identity(), "policy": verifier.policy()},
                "stages": {stage: self._stage_entry(stage) for stage in family.stages},
                "pricing": PRICING,
                "budget": {"scope": "directory", "directoryIdentity": self._budget_identity_value, "unit": "nanoUsd"},
                "limits": {"maxRequestBytes": MAX_REQUEST_BYTES, "maxVerifierRequestBytes": MAX_VERIFIER_REQUEST_BYTES,
                           "maxResponseBytes": MAX_RESPONSE_BYTES, "inputOverheadTokens": INPUT_OVERHEAD_TOKENS}}
        if self._funding:
            body["version"] = family.version + (FINISH_FUNDED_SUFFIX if self._finish else SET_FUNDED_SUFFIX if self._set_funding else FUNDED_SUFFIX)
            body["funding"] = self._funding
            body["pricing"] = self._pricing
            if self._finish:
                body["finishPolicy"] = self._finish
            go = self._model == live_funding.GO_MODEL
            body["generation"].update(profile="opencode-go-json-object-1" if go else "openai-luna-funded-1",
                                      responseFormat="json_object" if go else "json_schema",
                                      outputCapParameter="max_tokens" if go else "max_completion_tokens",
                                      reportedModelAliases=[], userAgent=live_funding.USER_AGENT)
            if not go and not self._direct:
                body["generation"]["serviceTier"] = "default"
            if go:
                body["generation"]["session"] = "zoop-" + digest({"runId": self._funding["runId"],
                    "budget": self._budget_identity_value, "family": family.version, "model": self._model})
            if self._direct:
                body["generation"].update(direct_deepseek.binding_metadata(self._effort))
            if self._chain:
                body["generation"]["fallback"] = {"version": fallback_decision.VERSION, "maxPhysicalAttempts": 2,
                                                   "binding": self._fallback_runtime().binding()}
            for stage, entry in body["stages"].items():
                entry["funding"] = self._funding_entry(stage)
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
        if stage not in self._family.stages:
            raise LiveFailure("live_stage_unsupported")
        return self._binding["stages"][stage]

    # ------------------------------------------------------------ prepare (pure) ----------------------------------------

    def _questions(self, stage: str, body: Any) -> int:
        """Number of questions a Jev request carries (1 for a chat request). Jev's billing of the shared `state` is not documented as
        once per request, so the reservation assumes the whole request is billed once PER question."""
        return max(1, len(body["questions"])) if stage in self._family.verify_stages else 1

    def _worst_case(self, stage: str, request_bytes: int, questions: int) -> dict[str, int | str]:
        provider = self._entry(stage)["provider"]
        rate_in, rate_out = self._rate(provider)
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
            if stage in self._family.generation_stages:
                spec = self._family.generation[stage]
                body = {"model": self._model, "messages": spec.messages(payload),
                        "response_format": {"type": "json_schema", "json_schema": {"name": spec.schema_name, "strict": True, "schema": spec.schema}},
                        "max_completion_tokens": self._max_output, "reasoning_effort": self._effort}
                if self._funding and self._model == live_funding.GO_MODEL:
                    # The provider documents max_tokens and JSON-object mode, not strict JSON-schema mode.
                    # Schema is trusted instruction text; the user's projected data remains a separate message.
                    body = {"model": self._model, "messages": spec.messages(payload), "max_tokens": self._max_output,
                            "response_format": {"type": "json_object"}}
                    body["messages"][0]["content"] += "\nRequired JSON response schema:\n" + canonical(spec.schema)
                elif self._direct:
                    body = direct_deepseek.build_body(spec.messages(payload), spec.schema, self._max_output, self._effort)
                elif self._funding:
                    body["service_tier"] = "default"  # explicit Standard pricing, never the project's implicit auto/Fast setting
                path, limit, schema_digest = "chat/completions", MAX_REQUEST_BYTES, entry["schemaDigest"]
            else:
                body, expect = self._family.verifier.build[stage](payload, self._family.verifier.model)
                path, limit, schema_digest = "systemone", MAX_VERIFIER_REQUEST_BYTES, entry["questionsDigest"]
            size = len(canonical(body).encode("utf-8"))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise LiveFailure("live_payload_invalid") from None
        if size > limit:
            raise LiveFailure("live_request_too_large")
        prepared = {"format": self._prepared_format, "stage": stage, "provider": entry["provider"], "purpose": entry["purpose"],
                    "recipient": entry["recipient"], "path": path, "body": body, "requestDigest": digest(body), "requestBytes": size,
                    "bindingIdentity": self._identity, "promptVersion": entry["promptVersion"], "schemaDigest": schema_digest,
                    "expect": expect, "reservation": self._worst_case(stage, size, self._questions(stage, body))}
        if self._chain and stage in self._family.generation_stages:
            prepared["fallback"] = self._fallback_runtime().prepare(stage, payload)
        return {**prepared, "digest": digest(prepared)}

    def _check_prepared(self, prepared: Any) -> dict[str, Any]:
        try:
            stage = prepared["stage"]
            entry = self._entry(stage)
            body = prepared["body"]
            size = len(canonical(body).encode("utf-8"))
            rest = {k: v for k, v in prepared.items() if k != "digest"}
            sound = (prepared["format"] == self._prepared_format
                     and prepared["digest"] == digest(rest) and prepared["requestDigest"] == digest(body)
                     and prepared["requestBytes"] == size and prepared["bindingIdentity"] == self._identity
                     and prepared["provider"] == entry["provider"] and prepared["recipient"] == entry["recipient"]
                     and prepared["purpose"] == entry["purpose"] and prepared["reservation"] == self._worst_case(stage, size, self._questions(stage, body))
                     and prepared["path"] == ("chat/completions" if stage in self._family.generation_stages else "systemone"))
            if self._funding:
                if stage in self._family.generation_stages:
                    go = self._model == live_funding.GO_MODEL
                    spec = self._family.generation[stage]
                    if self._direct:
                        sound &= direct_deepseek.body_matches(body, spec.system, spec.schema, self._max_output, self._effort)
                    else:
                        expected_system = spec.system + ("\nRequired JSON response schema:\n" + canonical(spec.schema) if go else "")
                        expected_format = ({"type": "json_object"} if go else
                                           {"type": "json_schema", "json_schema": {"name": spec.schema_name, "strict": True, "schema": spec.schema}})
                        cap_key = "max_tokens" if go else "max_completion_tokens"
                        sound &= (set(body) == ({"model", "messages", "response_format", cap_key} | (set() if go else {"reasoning_effort", "service_tier"}))
                                  and body["model"] == self._model and body[cap_key] == self._max_output
                                  and body["response_format"] == expected_format
                                  and len(body["messages"]) == 2
                                  and body["messages"][0] == {"role": "system", "content": expected_system}
                                  and body["messages"][1]["role"] == "user"
                                  and (go or (body["reasoning_effort"] == self._effort and body["service_tier"] == "default")))
                    if self._chain:
                        fallback = self._fallback_runtime()._check_prepared(prepared["fallback"])
                        sound &= fallback["body"]["messages"][1] == body["messages"][1]
                else:
                    sound &= body["model"] == self._family.verifier.model
        except (KeyError, IndexError, TypeError, AttributeError):
            raise LiveFailure("live_prepared_invalid") from None
        if not sound:
            raise LiveFailure("live_binding_mismatch" if isinstance(prepared, dict) and prepared.get("bindingIdentity") != self._identity
                              else "live_prepared_invalid")
        return prepared

    # ------------------------------------------------------------ send (one request) ------------------------------------

    def _chain_receipt(self, prepared, logical_id, attempts, winner):
        sent = [row for row in attempts if row["state"] != "released"]
        usage = {key: (sum(row["receipt"]["usage"][key] for row in sent)
                       if all(row["receipt"] is not None and row["receipt"]["usage"].get(key) is not None for row in sent) else None)
                 for key in _no_usage()}
        costs = [(row["receipt"]["cost"] if row["receipt"] else row["cost"]) for row in attempts]
        estimated = [cost.get("estimatedUsd") for cost in costs]
        winner_receipt = next((row["receipt"] for row in attempts if row["attemptId"] == winner), None)
        return {"format": CHAIN_RECEIPT, "attemptId": logical_id, "logicalAttemptId": logical_id,
                "stage": prepared["stage"], "requestDigest": prepared["requestDigest"], "bindingIdentity": self._identity,
                "prepared": prepared, "admittedSet": {"setId": self._send["setId"]} if self._send else None,
                "physicalAttempts": attempts, "winnerAttemptId": winner,
                "model": {"requested": self._model, "reported": winner_receipt["model"]["reported"] if winner_receipt else None},
                "usage": usage,
                "cost": {"currency": "USD", "tier": self._pricing["tier"],
                         "usageKnown": all(cost.get("usageKnown") for cost in costs),
                         "settled": all(row["state"] == "released" or cost.get("settled") for row, cost in zip(attempts, costs)),
                         "estimatedUsd": _sum_usd(estimated) if all(value is not None for value in estimated) else None,
                         "chargedUsd": _sum_usd(cost["chargedUsd"] for cost in costs),
                         "reservedUsd": _sum_usd(cost["reservedUsd"] for cost in costs)}}

    def send(self, prepared: dict, *, attempt_id: str, authorize: Callable[[], None],
             authorize_fallback: Callable[[], None] | None = None) -> dict[str, Any]:
        prepared = self._check_prepared(prepared)
        if not self._chain or prepared["stage"] not in self._family.generation_stages:
            return self._send_once(prepared, attempt_id=attempt_id, authorize=authorize)
        if self._send is None:
            raise LiveFailure(self._send_code)
        if self._budget_identity(self._send["directory"]) != self._budget_identity_value:
            raise LiveFailure("live_config_changed")
        if not isinstance(attempt_id, str) or not 1 <= len(attempt_id) <= 200:
            raise LiveFailure("live_prepared_invalid")
        if self._send["problems"]["budget"]:
            raise LiveFailure(self._send["problems"]["budget"])
        budget = self._send["budget"]
        try:
            budget.begin_invocation(attempt_id, self._send["setId"], prepared["stage"], prepared["digest"], self._identity)
        except BudgetError as exc:
            raise LiveFailure(exc.code) from None
        winner = None
        for ordinal, runtime, request, callback in (
                (1, self, prepared, authorize),
                (2, self._fallback_runtime(), prepared["fallback"], authorize_fallback)):
            physical_id = _physical_id(attempt_id, ordinal)
            profile = runtime._funding_entry(prepared["stage"])["accountRole"]
            try:
                budget.begin_provider_attempt(attempt_id, physical_id, ordinal, profile, request["requestDigest"])
            except BudgetError as exc:
                attempts = budget.provider_attempts(attempt_id)
                partial = self._chain_receipt(prepared, attempt_id, attempts, None) if attempts else None
                raise LiveFailure(exc.code, receipt=partial) from None
            receipt, error = None, None
            try:
                if callback is None:
                    raise LiveFailure("live_fallback_authorization_required")
                receipt = runtime._send_once(request, attempt_id=physical_id, authorize=callback)
                runtime._decode(prepared["stage"], receipt)
            except Exception as exc:
                code = getattr(exc, "code", "live_source_authorization_failed")
                error = {"code": code, "uncertain": bool(getattr(exc, "uncertain", False))}
            decision = fallback_decision.eligible_failure(
                provider="openai" if ordinal == 1 else "deepseek",
                code=error["code"] if error else None, receipt=receipt,
                pre_send=receipt is None and not (error or {}).get("uncertain", False),
                uncertain=(error or {}).get("uncertain", False))
            unknown = decision.action == "indeterminate"
            if unknown and error is not None:
                error["uncertain"] = True
            state = "unknown" if unknown else "received" if receipt is not None else "released"
            try:
                budget.record_provider_attempt(physical_id, state, receipt, error)
            except BudgetError as exc:
                raise LiveFailure(exc.code, uncertain=True) from None
            if decision.action == "success":
                winner = physical_id
            if ordinal == 1 and decision.action == "fallback":
                continue
            envelope = self._chain_receipt(prepared, attempt_id, budget.provider_attempts(attempt_id), winner)
            if unknown:
                raise LiveFailure("live_response_unknown", uncertain=True, receipt=envelope)
            return envelope
        raise LiveFailure("live_chain_invalid")

    def _decode_chain(self, stage, receipt):
        try:
            if not self._chain or stage not in self._family.generation_stages:
                raise LiveFailure("live_receipt_invalid")
            prepared = self._check_prepared(receipt["prepared"])
            if (receipt["stage"] != stage or receipt["bindingIdentity"] != self._identity
                    or receipt["attemptId"] != receipt["logicalAttemptId"] or prepared["stage"] != stage
                    or receipt["requestDigest"] != prepared["requestDigest"]):
                raise LiveFailure("live_receipt_invalid")
            rows = physical_attempts(receipt)
            fallback = self._fallback_runtime()
            for ordinal, row in enumerate(rows, 1):
                runtime = self if ordinal == 1 else fallback
                request = prepared if ordinal == 1 else prepared["fallback"]
                if row["attemptId"] != _physical_id(receipt["logicalAttemptId"], ordinal):
                    raise LiveFailure("live_receipt_invalid")
                if (row["profile"] != runtime._funding_entry(stage)["accountRole"]
                        or row["funding"] != runtime._funding_entry(stage)
                        or row["recipient"] != runtime.recipient(stage) or row["stage"] != stage
                        or row["requestDigest"] != request["requestDigest"]):
                    raise LiveFailure("live_receipt_invalid")
                if row["receipt"]:
                    leaf, _ = runtime._receipt(stage, row["receipt"])
                    if (leaf["attemptId"] != row["attemptId"] or leaf["requestDigest"] != request["requestDigest"]
                            or leaf["admittedSet"] != receipt["admittedSet"]):
                        raise LiveFailure("live_receipt_invalid")
                if ordinal == 2:
                    prior = rows[0]
                    decision = fallback_decision.eligible_failure(provider="openai",
                        code=(prior["error"] or {}).get("code"), receipt=prior["receipt"],
                        pre_send=prior["state"] == "released", uncertain=(prior["error"] or {}).get("uncertain", False))
                    if decision.action != "fallback":
                        raise LiveFailure("live_receipt_invalid")
            expected = self._chain_receipt(prepared, receipt["logicalAttemptId"], rows, receipt["winnerAttemptId"])
            if any(receipt.get(key) != expected[key] for key in ("usage", "cost", "model")):
                raise LiveFailure("live_receipt_invalid")
            if any(row["state"] == "unknown" for row in rows):
                if receipt["winnerAttemptId"] is not None:
                    raise LiveFailure("live_receipt_invalid")
                raise LiveFailure("live_response_unknown", uncertain=True)
            winner = receipt["winnerAttemptId"]
            if winner is None:
                error = rows[-1]["error"] or {}
                raise LiveFailure(error.get("code", "live_receipt_invalid"), uncertain=error.get("uncertain", False))
            if winner != rows[-1]["attemptId"] or rows[-1]["state"] != "received" or rows[-1]["error"]:
                raise LiveFailure("live_receipt_invalid")
            return (self if len(rows) == 1 else fallback)._decode(stage, rows[-1]["receipt"])
        except (KeyError, TypeError, ValueError, IndexError):
            raise LiveFailure("live_receipt_invalid") from None

    def _send_once(self, prepared: dict, *, attempt_id: str, authorize: Callable[[], None]) -> dict[str, Any]:
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
        try:
            if self._finish:
                live_funding.require_send_window(self._timeout, self._finish["sendBefore"])
            live_funding.require_send_window(self._timeout, self._send["sendBefore"])
        except ValueError as exc:
            raise LiveFailure(str(exc)) from None
        budget: Budget = self._send["budget"]
        try:
            budget.reserve(attempt_id, stage, prepared["recipient"], prepared["requestDigest"], prepared["reservation"]["worstCaseNanoUsd"],
                           **({"account_role": self._funding_entry(stage)["accountRole"]} if self._funding else {}),
                           **({"set_id": self._send["setId"]} if self._set_funding else {}))
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
        transport_timing: dict[str, Any] = {}
        try:
            status, content_type, raw_bytes, truncated = self._post(
                base, prepared["path"], key, canonical(prepared["body"]).encode("utf-8"),
                **({"before_send": lambda: budget.check_send(attempt_id), "timing": transport_timing} if self._funding else {}))
        except BudgetError as exc:  # deadline/policy recheck is before client.stream: provably unsent
            try:
                budget.release(attempt_id)
            except BudgetError:
                pass
            raise LiveFailure(exc.code) from None
        except Exception:  # once the request may have left the process every failure is an unknown outcome
            raise LiveFailure("live_response_unknown", uncertain=True) from None
        text = raw_bytes.decode("utf-8", errors="replace")
        reserved = prepared["reservation"]["worstCaseNanoUsd"]
        # From here on the response is in hand and MUST come back as a raw receipt whatever its content: nothing below may raise.
        raw = _parse(text, truncated)
        try:
            reported = direct_deepseek.usage(raw) if self._direct and provider == "openai-compatible" else _usage(raw, provider)
        except Exception:
            reported = _no_usage()
        cache_write_error = None
        if self._set_funding and self._model == MODEL and provider == "openai-compatible":
            reported["cacheWriteTokens"], cache_write_error = _cache_write_usage(raw)
        actual, rejected = None, cache_write_error
        model = raw["model"][:200] if isinstance(raw, dict) and isinstance(raw.get("model"), str) else None
        service_tier = raw.get("service_tier") if isinstance(raw, dict) else None
        standard = bool(self._funding) and provider == "openai-compatible" and self._model == MODEL
        if standard and service_tier not in (None, "default"):
            rejected = "service_tier_mismatch"
        # Only a 2xx response with fully reported usage may settle below the worst case; a non-2xx stays at it whatever its body says.
        if rejected is None and 200 <= status < 300 and reported["inputTokens"] is not None and reported["outputTokens"] is not None:
            model_ok = direct_deepseek.model_matches(model) if self._direct and provider == "openai-compatible" else model == prepared["body"]["model"]
            rejected = ("model_mismatch" if self._funding and not model_ok else
                        _usage_over_bound(reported, prepared["reservation"], provider))
            if rejected is None and self._direct and provider == "openai-compatible":
                rejected = direct_deepseek.usage_rejection(raw)
            if rejected is None:
                rate_in, rate_out = self._rate(provider)
                actual = reported["inputTokens"] * rate_in + reported["outputTokens"] * rate_out
        try:
            charged, settled = budget.settle(attempt_id, actual), True
        except Exception:  # incl. an overflow or a database failure: the worst-case charge simply stays and the receipt says so
            charged, settled = reserved, False
        # `usage` keeps what the provider reported, even when it is rejected as implausible (`cost.usageRejected`), so nothing is hidden.
        receipt = {"format": self._receipt_format, "stage": stage, "attemptId": attempt_id, "recipient": prepared["recipient"], "purpose": prepared["purpose"],
                "bindingIdentity": self._identity, "requestDigest": prepared["requestDigest"],
                "http": {"status": status, "contentType": content_type[:200] if content_type else None,
                         "bodySha256": hashlib.sha256(raw_bytes).hexdigest(), "bodyText": text, "truncated": truncated},
                "model": {"requested": prepared["body"]["model"], "reported": model}, "usage": reported,
                "cost": {"currency": "USD", "tier": self._pricing["tier"], "usageKnown": actual is not None, "usageRejected": rejected,
                         "settled": settled, "estimatedUsd": usd(actual) if actual is not None else None, "chargedUsd": usd(charged),
                         "reservedUsd": usd(reserved)},
                "expect": prepared["expect"]}
        if self._funding:
            receipt["funding"] = self._funding_entry(stage)
            if self._set_funding:
                receipt["admittedSet"] = {"setId": self._send["setId"]}
            receipt["timing"] = transport_timing
            receipt["cost"]["basis"] = ("go-nominal-allowance-upper-estimate"
                                        if receipt["funding"]["accountRole"] == "personal-opencode" else "billable-usd-estimate")
            receipt["cost"]["providerReported"] = live_funding.provider_cost(raw)
            receipt["cost"]["serviceTier"] = {"requested": "default" if standard else None,
                                               "reported": service_tier if service_tier in ("auto", "default", "flex", "fast", "priority") else None}
            if self._direct and provider == "openai-compatible":
                receipt["model"].update(direct_deepseek.model_provenance(model))
        return receipt

    def _post(self, base: str, path: str, key: str, body: bytes, *,
              before_send: Callable[[], None] | None = None, timing: dict | None = None) -> tuple[int, str | None, bytes, bool]:
        deadline = time.monotonic() + self._timeout
        headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json", "Accept": "application/json"}
        if self._funding:
            headers["User-Agent"] = live_funding.USER_AGENT
            if base == live_funding.GO_URL:
                headers["x-opencode-session"] = self._binding["generation"]["session"]
        with httpx.Client(base_url=base + "/", timeout=httpx.Timeout(self._timeout), headers=headers, follow_redirects=False,
                          trust_env=False, transport=self._send["transport"]) as client:
            if before_send:
                before_send()
            try:
                if self._finish:
                    live_funding.require_send_window(self._timeout, self._finish["sendBefore"])
                live_funding.require_send_window(self._timeout, self._send["sendBefore"])
            except ValueError as exc:
                raise BudgetError(str(exc)) from None
            started = time.monotonic_ns() if timing is not None else None
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
                if timing is not None:
                    timing.update(durationMs=(time.monotonic_ns() - started) / 1_000_000, provenance="http-transport-monotonic")
                return response.status_code, response.headers.get("content-type"), b"".join(chunks), truncated

    # ------------------------------------------------------------ decode (pure, receipt only) ---------------------------

    def _receipt(self, stage: str, receipt: Any) -> tuple[dict, dict]:
        try:
            if stage not in self._family.stages or receipt["format"] != self._receipt_format or receipt["stage"] != stage:
                raise LiveFailure("live_receipt_invalid")
            http = receipt["http"]
            if type(http["status"]) is not int or not isinstance(http["bodyText"], str) or not isinstance(receipt["model"]["requested"], str):
                raise LiveFailure("live_receipt_invalid")
            if self._funding and (receipt["bindingIdentity"] != self._identity or receipt["funding"] != self._funding_entry(stage)
                                 or receipt["recipient"] != self.recipient(stage) or receipt["purpose"] != self.purpose(stage)):
                raise LiveFailure("live_receipt_invalid")
        except (KeyError, TypeError):
            raise LiveFailure("live_receipt_invalid") from None
        return receipt, http

    def _decode(self, stage: str, receipt: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if isinstance(receipt, dict) and receipt.get("format") == CHAIN_RECEIPT:
            return self._decode_chain(stage, receipt)
        receipt, http = self._receipt(stage, receipt)
        if not 200 <= http["status"] < 300:
            raise LiveFailure(f"live_http_{http['status']}")
        if http.get("truncated") is True:
            raise LiveFailure("live_response_oversize")
        if self._funding:
            expected_model = self._family.verifier.model if stage in self._family.verify_stages else self._model
            model_ok = (direct_deepseek.model_matches(receipt["model"].get("reported"))
                        if self._direct and stage in self._family.generation_stages else receipt["model"].get("reported") == expected_model)
            if receipt["model"]["requested"] != expected_model or not model_ok:
                raise LiveFailure("live_model_mismatch")
        cost = receipt.get("cost")
        if isinstance(cost, dict) and (cost.get("settled") is False or cost.get("usageRejected")):  # accounting unrecorded or provider usage implausible
            raise LiveFailure("live_receipt_invalid")
        try:
            raw = json.loads(http["bodyText"])
        except (ValueError, RecursionError, MemoryError):
            raise LiveFailure("live_reply_not_json") from None
        if self._funding and (not isinstance(raw, dict) or not (
                direct_deepseek.model_matches(raw.get("model")) if self._direct and stage in self._family.generation_stages else raw.get("model") == expected_model)):
            raise LiveFailure("live_model_mismatch")
        if self._direct and stage in self._family.generation_stages:
            try:
                return direct_deepseek.decode_answer(raw, self._family.generation[stage].schema), []
            except direct_deepseek.DeepSeekFailure as exc:
                raise LiveFailure(exc.code) from None
        if stage in self._family.verify_stages:
            try:
                expect = receipt["expect"]
                interpret = self._family.verifier.interpret[stage]
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
            if self._funding and choice.get("finish_reason") != "stop":
                raise LiveFailure("live_answers_invalid")
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
        if self._funding:
            try:
                valid = live_funding.schema_matches(answer, self._family.generation[stage].schema)
            except (KeyError, TypeError, ValueError, RecursionError):
                valid = False
            if not valid:
                raise LiveFailure("live_answers_invalid")
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
    """`python -m zoop_ai_pipeline.live_runtime binding|check [pipeline|issue-summary]`: offline, no network, no file, keys only as
    presence booleans. `binding` validates the non-secret configuration; `check` additionally requires the budget variables and both
    keys. The optional family defaults to `pipeline`."""
    args = sys.argv[1:] if argv is None else argv
    if not 1 <= len(args) <= 2 or args[0] not in {"binding", "check"} or (len(args) == 2 and args[1] not in FAMILY_NAMES):
        print("usage: python -m zoop_ai_pipeline.live_runtime binding|check [pipeline|issue-summary]", file=sys.stderr)
        return 2
    try:
        runtime = LiveRuntime.from_env(need_send=args[0] == "check", family=FAMILY_NAMES[args[1]] if len(args) == 2 else PIPELINE)
    except LiveFailure as exc:
        print(canonical({"ok": False, "error": exc.code, "kind": exc.kind}))
        return 2
    binding = runtime.binding()
    stages = runtime.family.stages
    print(canonical({"ok": True, "check": args[0] == "check", "binding": binding, "identity": binding["identity"],
                     "recipients": {s: runtime.recipient(s) for s in stages}, "purposes": {s: runtime.purpose(s) for s in stages},
                     "keysPresent": {"openai": bool(os.environ.get(OPENAI_KEY_VAR)), "typesafe": bool(os.environ.get(JEV_KEY_VAR))},
                     "network": "none"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
