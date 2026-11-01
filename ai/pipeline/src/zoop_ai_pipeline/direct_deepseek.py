"""Pure direct DeepSeek chat adapter; the live runtime owns transport, authorization and the shared budget.

Official API/pricing read 2026-10-28. JSON mode is not schema enforcement: the
native structural/domain validators still run after a complete provider reply.
No OpenCode endpoint, session header, implicit key lookup or retry exists here.
"""
from __future__ import annotations

import json
from typing import Any

from .relation_contracts import canonical

BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-flash"
MODEL_REVISION = "DeepSeek-V4.1-Flash-1017"
KEY_VAR = "DEEPSEEK_API_KEY"
PROFILE = "deepseek-direct-json-object-1"
USER_AGENT = "zoop-data-pipeline/1.0"
EFFORTS = ("none", "low", "high", "max")
MAX_OUTPUT = 393_216
MAX_REPORTED_TOKENS = 1_000_000_000
PRICING_NANO = {"input": 300, "output": 1200, "cachedInput": 6}
PRICING = {
    "asOf": "2026-10-28", "unit": "nanoUsdPerToken", "tier": "conservative-peak-no-cache-discount",
    "sources": ["https://api-docs.deepseek.com/quick_start/pricing"],
    MODEL: PRICING_NANO,
}
CONTRACT_SOURCES = (
    "https://api-docs.deepseek.com/",
    "https://api-docs.deepseek.com/api/create-chat-completion",
    "https://api-docs.deepseek.com/guides/json_mode",
    "https://api-docs.deepseek.com/quick_start/error_codes",
)


class DeepSeekFailure(ValueError):
    """Stable, body/key-free adapter error; never transport evidence."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def expected_system(system: str, schema: dict) -> str:
    return system + "\nReturn only a JSON object matching this required JSON response schema:\n" + canonical(schema)


def build_body(messages: list[dict[str, str]], schema: dict, max_output: int, effort: str = "high") -> dict[str, Any]:
    """Adapt exactly the pipeline's system/user projection, without mutating it.

    Native effort values only: unsupported OpenAI effort aliases are not silently
    mapped. max_tokens includes reasoning; no temperature/service_tier/SDK defaults.
    """
    if effort not in EFFORTS:
        raise DeepSeekFailure("live_effort_unsupported")
    if type(max_output) is not int or not 1 <= max_output <= MAX_OUTPUT:
        raise DeepSeekFailure("live_limit_invalid")
    if (not isinstance(schema, dict) or schema.get("type") != "object"
            or not isinstance(messages, list) or len(messages) != 2
            or any(not isinstance(message, dict) or set(message) != {"role", "content"}
                   or not isinstance(message["content"], str) for message in messages)
            or [message["role"] for message in messages] != ["system", "user"]):
        raise DeepSeekFailure("live_prepared_invalid")
    return {
        "model": MODEL,
        "messages": [{"role": "system", "content": expected_system(messages[0]["content"], schema)},
                     {"role": "user", "content": messages[1]["content"]}],
        "response_format": {"type": "json_object"}, "max_tokens": max_output,
        "thinking": {"type": "disabled" if effort == "none" else "enabled"},
        "reasoning_effort": effort, "stream": False,
    }


def body_matches(body: Any, system: str, schema: dict, max_output: int, effort: str) -> bool:
    """Validate the frozen wire shape; the caller independently checks its request digest."""
    try:
        if not isinstance(body, dict) or not isinstance(body["messages"][1]["content"], str):
            return False
        expected = build_body([{"role": "system", "content": system},
                               {"role": "user", "content": body["messages"][1]["content"]}], schema, max_output, effort)
        return canonical(body) == canonical(expected)
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def model_matches(reported: Any) -> bool:
    """Only the documented request alias or exact documented revision; no guessed aliases."""
    return isinstance(reported, str) and reported in (MODEL, MODEL_REVISION)


def model_provenance(reported: Any) -> dict[str, Any]:
    """An alias-only response is not proof that the provider reported its dated revision."""
    return {"requested": MODEL, "reported": reported if isinstance(reported, str) else None,
            "documentedRevision": MODEL_REVISION, "documentedRevisionAsOf": "2026-10-28",
            "documentedRevisionSource": CONTRACT_SOURCES[0], "reportedModelAccepted": model_matches(reported)}


def binding_metadata(effort: str) -> dict[str, Any]:
    if effort not in EFFORTS:
        raise DeepSeekFailure("live_effort_unsupported")
    return {"profile": PROFILE, "responseFormat": "json_object", "outputCapParameter": "max_tokens",
            "reportedModelAliases": [MODEL_REVISION], "documentedModelRevision": MODEL_REVISION,
            "thinking": "disabled" if effort == "none" else "enabled", "userAgent": USER_AGENT,
            "apiContractSources": list(CONTRACT_SOURCES)}


def _count(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= MAX_REPORTED_TOKENS else None


def usage(raw: Any) -> dict[str, int | None]:
    """Keep reported counts only; cache misses are not additional input tokens."""
    block = raw.get("usage") if isinstance(raw, dict) else None
    block = block if isinstance(block, dict) else {}
    details = block.get("prompt_tokens_details")
    details = details if isinstance(details, dict) else {}
    completion = block.get("completion_tokens_details")
    completion = completion if isinstance(completion, dict) else {}
    return {"inputTokens": _count(block.get("prompt_tokens")), "outputTokens": _count(block.get("completion_tokens")),
            "cachedTokens": _count(block.get("prompt_cache_hit_tokens", details.get("cached_tokens"))),
            "reasoningTokens": _count(completion.get("reasoning_tokens"))}


def usage_rejection(raw: Any) -> str | None:
    """Reject impossible reports before settling lower than the reservation.

    Optional breakdowns may be absent, but malformed, contradictory, or partly
    supplied cache splits cannot create a discount or mask an accounting error.
    """
    block = raw.get("usage") if isinstance(raw, dict) else None
    if not isinstance(block, dict):
        return "usage_missing"
    counts = usage(raw)
    input_tokens, output_tokens = counts["inputTokens"], counts["outputTokens"]
    if input_tokens is None or output_tokens is None:
        return "usage_invalid"
    for name, total in (("prompt_tokens_details", input_tokens), ("completion_tokens_details", output_tokens)):
        if name in block:
            details = block[name]
            if not isinstance(details, dict):
                return "usage_invalid"
            key = "cached_tokens" if name == "prompt_tokens_details" else "reasoning_tokens"
            if key in details and (_count(details[key]) is None or details[key] > total):
                return "usage_invalid"
    if "total_tokens" in block and (_count(block["total_tokens"]) is None or block["total_tokens"] != input_tokens + output_tokens):
        return "usage_invalid"
    if "prompt_cache_hit_tokens" in block or "prompt_cache_miss_tokens" in block:
        hit, miss = _count(block.get("prompt_cache_hit_tokens")), _count(block.get("prompt_cache_miss_tokens"))
        if hit is None or miss is None or hit + miss != input_tokens:
            return "usage_invalid"
        details = block.get("prompt_tokens_details", {})
        if "cached_tokens" in details and details["cached_tokens"] != hit:
            return "usage_invalid"
    return None


def estimate_nano(raw: Any) -> int | None:
    """Conservative peak list-price estimate, not an invoice or ledger settlement.

    Do not add reasoning tokens again: they are included in completion_tokens.
    No inference from wall-clock off-peak windows or undocumented monetary fields.
    """
    if not isinstance(raw, dict) or not model_matches(raw.get("model")) or usage_rejection(raw):
        return None
    counts = usage(raw)
    return counts["inputTokens"] * PRICING_NANO["input"] + counts["outputTokens"] * PRICING_NANO["output"]


def decode_answer(raw: Any, schema: dict) -> dict[str, Any]:
    """Interpret only a fully received 2xx envelope, then enforce the existing schema subset.

    HTTP/truncation/settlement checks belong to the runtime before this call.
    Native owners still apply their richer domain and citation validators.
    """
    # Local import avoids a cycle when the funding-policy module imports this adapter's constants.
    from .live_funding import schema_matches

    if not isinstance(raw, dict) or not model_matches(raw.get("model")):
        raise DeepSeekFailure("live_model_mismatch")
    try:
        choices = raw["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise DeepSeekFailure("live_answers_invalid")
        choice = choices[0]
        message = choice["message"]
        if message.get("refusal") or choice.get("finish_reason") == "content_filter":
            raise DeepSeekFailure("live_model_refusal")
        if choice.get("finish_reason") == "length":
            raise DeepSeekFailure("live_output_truncated")
        if choice.get("finish_reason") in ("aborted", "insufficient_system_resource"):
            raise DeepSeekFailure("live_provider_incomplete")
        if (choice.get("finish_reason") != "stop" or message.get("role") != "assistant"
                or message.get("tool_calls") or not isinstance(message["content"], str)):
            raise DeepSeekFailure("live_answers_invalid")
        content = message["content"]
    except (KeyError, IndexError, TypeError, AttributeError):
        raise DeepSeekFailure("live_answers_invalid") from None
    try:
        answer = json.loads(content)
    except (ValueError, RecursionError):
        raise DeepSeekFailure("live_reply_not_json") from None
    try:
        valid = isinstance(answer, dict) and schema_matches(answer, schema)
    except (KeyError, TypeError, ValueError, RecursionError):
        valid = False
    if not valid:
        raise DeepSeekFailure("live_answers_invalid")
    return answer
