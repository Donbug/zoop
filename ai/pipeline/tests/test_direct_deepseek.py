"""Offline direct API contract tests; no credentials, HTTP, or provider SDK required."""
from __future__ import annotations

import copy

import pytest

from tests.live_support import openai_reply
from zoop_ai_pipeline import direct_deepseek as ds

SCHEMA = {"type": "object", "properties": {"mentions": {"type": "array", "items": {"type": "string"}}},
          "required": ["mentions"], "additionalProperties": False}
MESSAGES = [{"role": "system", "content": "Extract grounded mentions."}, {"role": "user", "content": "Synthetic article."}]


def response(*, model=ds.MODEL, content=None, **options):
    return openai_reply({"mentions": []} if content is None else content, model=model, **options)


@pytest.mark.parametrize("effort", ds.EFFORTS)
def test_direct_payload_is_exact_and_does_not_reuse_openai_or_go_options(effort):
    original = copy.deepcopy(MESSAGES)
    body = ds.build_body(MESSAGES, SCHEMA, 24000, effort)
    assert body == {
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": ds.expected_system(MESSAGES[0]["content"], SCHEMA)}, MESSAGES[1]],
        "response_format": {"type": "json_object"}, "max_tokens": 24000,
        "thinking": {"type": "disabled" if effort == "none" else "enabled"},
        "reasoning_effort": effort, "stream": False,
    }
    assert MESSAGES == original
    assert ds.body_matches(body, MESSAGES[0]["content"], SCHEMA, 24000, effort)
    assert ds.BASE_URL == "https://api.deepseek.com" and ds.KEY_VAR == "DEEPSEEK_API_KEY"
    assert "JSON" in body["messages"][0]["content"]
    assert ds.binding_metadata(effort)["profile"] == "deepseek-direct-json-object-1"


@pytest.mark.parametrize("extra", [{"service_tier": "default"}, {"max_completion_tokens": 24000}, {"stream": 0},
                                   {"response_format": {"type": "json_schema"}}, {"max_tokens": True}])
def test_frozen_body_rejects_provider_drift(extra):
    body = ds.build_body(MESSAGES, SCHEMA, 24000)
    body.update(extra)
    assert not ds.body_matches(body, MESSAGES[0]["content"], SCHEMA, 24000, "high")


@pytest.mark.parametrize("effort", ["medium", "xhigh", "minimal", "provider-default", ""])
def test_effort_is_explicit_not_silently_remapped(effort):
    with pytest.raises(ds.DeepSeekFailure, match="live_effort_unsupported"):
        ds.build_body(MESSAGES, SCHEMA, 24000, effort)


@pytest.mark.parametrize("limit", [0, -1, 393217, True, "24000"])
def test_output_bound_is_provider_specific(limit):
    with pytest.raises(ds.DeepSeekFailure, match="live_limit_invalid"):
        ds.build_body(MESSAGES, SCHEMA, limit)


@pytest.mark.parametrize("reported", [ds.MODEL, ds.MODEL_REVISION])
def test_requested_alias_and_reported_model_are_separate_from_documented_revision(reported):
    provenance = ds.model_provenance(reported)
    assert provenance["requested"] == "deepseek-flash"
    assert provenance["reported"] == reported
    assert provenance["documentedRevision"] == "DeepSeek-V4.1-Flash-1017"
    assert provenance["reportedModelAccepted"] is True
    assert ds.decode_answer(response(model=reported), SCHEMA) == {"mentions": []}


@pytest.mark.parametrize("reported", [None, "deepseek-v4.1-flash", "deepseek-v4-flash", "deepseek-v4-pro", "DeepSeek-V4.1-Flash"])
def test_unreported_or_unpinned_model_is_not_invented(reported):
    assert not ds.model_matches(reported)
    assert ds.model_provenance(reported)["reported"] == reported
    with pytest.raises(ds.DeepSeekFailure, match="live_model_mismatch"):
        ds.decode_answer(response(model=reported), SCHEMA)


def test_usage_cache_split_reasoning_and_peak_cost_provenance():
    raw = response(usage={"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500,
                          "prompt_cache_hit_tokens": 700, "prompt_cache_miss_tokens": 300,
                          "prompt_tokens_details": {"cached_tokens": 700},
                          "completion_tokens_details": {"reasoning_tokens": 300},
                          "cost": 0, "opencode": {"billing_source": "free"}})
    assert ds.usage(raw) == {"inputTokens": 1000, "outputTokens": 500, "cachedTokens": 700, "reasoningTokens": 300}
    assert ds.usage_rejection(raw) is None
    assert ds.estimate_nano(raw) == 900000  # whole input at peak; reasoning already included in output
    assert ds.PRICING["tier"] == "conservative-peak-no-cache-discount"
    assert ds.PRICING["asOf"] == "2026-10-28"
    assert ds.PRICING["sources"] == ["https://api-docs.deepseek.com/quick_start/pricing"]


@pytest.mark.parametrize("usage", [
    {"prompt_tokens": True, "completion_tokens": 1},
    {"prompt_tokens": 10, "completion_tokens": -1},
    {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 99},
    {"prompt_tokens": 10, "completion_tokens": 20, "prompt_cache_hit_tokens": 8},
    {"prompt_tokens": 10, "completion_tokens": 20, "prompt_cache_hit_tokens": 8, "prompt_cache_miss_tokens": 3},
    {"prompt_tokens": 10, "completion_tokens": 20, "prompt_cache_hit_tokens": 8, "prompt_cache_miss_tokens": 2,
     "prompt_tokens_details": {"cached_tokens": 7}},
    {"prompt_tokens": 10, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 11}},
    {"prompt_tokens": 10, "completion_tokens": 20, "completion_tokens_details": {"reasoning_tokens": 21}},
    {"prompt_tokens": 10, "completion_tokens": 20, "completion_tokens_details": None},
])
def test_invalid_usage_never_creates_lower_cost(usage):
    raw = response(usage=usage)
    assert ds.usage_rejection(raw) == "usage_invalid"
    assert ds.estimate_nano(raw) is None


def test_missing_usage_is_unknown_not_zero():
    raw = response(usage=None)
    assert ds.usage(raw) == dict.fromkeys(("inputTokens", "outputTokens", "cachedTokens", "reasoningTokens"))
    assert ds.usage_rejection(raw) == "usage_missing"
    assert ds.estimate_nano(raw) is None


@pytest.mark.parametrize("content,finish,refusal,code", [
    ("", "stop", None, "live_reply_not_json"),
    ("not json", "stop", None, "live_reply_not_json"),
    ({"mentions": [1]}, "stop", None, "live_answers_invalid"),
    ({"mentions": [], "extra": 1}, "stop", None, "live_answers_invalid"),
    ({"mentions": []}, "length", None, "live_output_truncated"),
    ({"mentions": []}, "content_filter", None, "live_model_refusal"),
    ({"mentions": []}, "stop", "declined", "live_model_refusal"),
    ({"mentions": []}, "aborted", None, "live_provider_incomplete"),
    ({"mentions": []}, "insufficient_system_resource", None, "live_provider_incomplete"),
    ({"mentions": []}, "tool_calls", None, "live_answers_invalid"),
])
def test_received_invalid_and_refusal_remain_distinct(content, finish, refusal, code):
    raw = response(content=content, finish=finish, refusal=refusal)
    original = copy.deepcopy(raw)
    with pytest.raises(ds.DeepSeekFailure, match=code):
        ds.decode_answer(raw, SCHEMA)
    assert raw == original
