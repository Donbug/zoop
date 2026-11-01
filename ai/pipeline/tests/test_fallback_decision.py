"""Pure decisions preserve original evidence; runtime integration owns physical sends."""
from __future__ import annotations

import copy
import json

import pytest

from zoop_ai_pipeline.fallback_decision import Action, FailureClass, eligible_failure
from zoop_ai_pipeline.relation_contracts import digest


def receipt(status=200, *, body=None):
    raw = body if body is not None else {
        "model": "gpt-6-luna", "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}]}
    return {"attemptId": "original-attempt", "bindingIdentity": "a" * 64, "requestDigest": "b" * 64,
            "model": {"requested": "gpt-6-luna", "reported": raw.get("model") if isinstance(raw, dict) else None},
            "http": {"status": status, "bodyText": json.dumps(raw), "truncated": False},
            "cost": {"settled": True, "usageRejected": None, "chargedUsd": "0.004000000", "reservedUsd": "0.030000000"},
            "admittedSet": {"setId": "same-finite-set"}}


def decide(code, **options):
    return eligible_failure(provider="openai", code=code, **options)


def test_success_never_requests_a_second_provider():
    result = decide(None, receipt=receipt())
    assert result.action is Action.SUCCESS
    assert result.failure_class is FailureClass.NONE


@pytest.mark.parametrize("code", ["live_api_key_required", "live_budget_exhausted_shared"])
def test_known_presend_failures_allow_distinct_fallback(code):
    result = decide(code, pre_send=True)
    assert result.action is Action.FALLBACK
    assert result.reason == code and len(result.evidence_digest) == 64


@pytest.mark.parametrize("status", [401, 402, 429, 500, 503])
def test_complete_recoverable_provider_failure_is_eligible_and_original_is_untouched(status):
    original = receipt(status, body={"error": {"code": "server_error"}})
    before = copy.deepcopy(original)
    result = decide(f"live_http_{status}", receipt=original)
    assert result.action is Action.FALLBACK
    assert original == before
    assert result.evidence_digest == digest({"provider": "openai", "phase": "received", "code": f"live_http_{status}", "receipt": before})
    assert result.record()["action"] == "fallback"


@pytest.mark.parametrize("code", ["live_reply_not_json", "live_answers_invalid", "live_output_truncated"])
def test_received_invalid_primary_is_preserved_including_cost_and_binding(code):
    original = receipt(body={"choices": [{"message": {"content": "invalid"}, "finish_reason": "stop"}]})
    before = copy.deepcopy(original)
    assert decide(code, receipt=original).action is Action.FALLBACK
    assert original == before
    changed = copy.deepcopy(original)
    changed["cost"]["chargedUsd"] = "0"
    assert decide(code, receipt=changed).evidence_digest != decide(code, receipt=original).evidence_digest


@pytest.mark.parametrize("code", [None, "live_answers_invalid", "live_api_key_required", "live_budget_exhausted_shared"])
def test_unknown_transport_dominates_every_claimed_known_outcome(code):
    assert decide(code, uncertain=True, pre_send=True, receipt=receipt()).action is Action.INDETERMINATE


@pytest.mark.parametrize("code", ["live_response_unknown", "provider_response_unknown", "live_provider_incomplete"])
def test_unknown_completion_never_allows_fallback(code):
    assert decide(code, receipt=receipt()).action is Action.INDETERMINATE


@pytest.mark.parametrize("status", [408, 502, 504])
def test_gateway_and_timeout_status_do_not_prove_upstream_completion(status):
    assert decide(f"live_http_{status}", receipt=receipt(status)).action is Action.INDETERMINATE


@pytest.mark.parametrize("code", ["source_policy_denied", "source_permission_denied", "permission_denied", "policy_denied",
                                   "live_model_refusal", "citation_invalid", "grounding_invalid", "unexpected_new_error"])
def test_source_refusal_and_native_application_failures_never_fallback(code):
    assert decide(code, receipt=receipt()).action is Action.BLOCKED
    assert decide(code, pre_send=True).action is Action.BLOCKED


@pytest.mark.parametrize("body", [
    {"choices": [{"finish_reason": "content_filter", "message": {"content": ""}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": "", "refusal": "declined"}}]},
    {"error": {"code": "content_policy_violation"}},
    {"error": {"type": "permission_denied"}},
])
def test_refusal_evidence_cannot_be_relabelled_as_invalid_output(body):
    assert decide("live_answers_invalid", receipt=receipt(body=body)).action is Action.BLOCKED
    assert decide("live_http_500", receipt=receipt(500, body=body)).action is Action.BLOCKED


@pytest.mark.parametrize("status", [400, 403, 404, 422, 501])
def test_other_http_failures_are_not_blanket_retried(status):
    assert decide(f"live_http_{status}", receipt=receipt(status)).action is Action.BLOCKED


@pytest.mark.parametrize("code", ["live_budget_exhausted", "live_budget_exhausted_personal", "live_budget_verification_blocked",
                                   "live_set_work_exhausted", "live_set_not_admitted", "live_binding_mismatch", "live_config_changed"])
def test_other_budget_admission_and_configuration_denials_do_not_route_around_authority(code):
    assert decide(code, pre_send=True).action is Action.BLOCKED


def test_deepseek_401_is_a_known_terminal_stop_not_another_fallback():
    original = receipt(401, body={"error": {"code": "invalid_api_key"}})
    original["model"]["requested"] = "deepseek-flash"
    result = eligible_failure(provider="deepseek", code="live_http_401", receipt=original)
    assert result.action is Action.BLOCKED
    assert result.failure_class is FailureClass.PROVIDER_AUTH
    assert result.reason == "live_http_401"
    assert decide("live_http_401", receipt=original).action is Action.BLOCKED


def test_missing_receipt_unsettled_ledger_and_partial_capture_do_not_allow_successor():
    assert decide("live_answers_invalid").action is Action.INDETERMINATE
    original = receipt()
    original["cost"]["settled"] = False
    assert decide("live_answers_invalid", receipt=original).action is Action.INDETERMINATE
    original["cost"]["settled"] = True
    original["http"]["truncated"] = True
    assert decide("live_response_oversize", receipt=original).action is Action.INDETERMINATE


def test_status_code_and_phase_conflicts_are_not_eligible():
    assert decide("live_http_503", receipt=receipt(401)).action is Action.BLOCKED
    assert decide("live_api_key_required", pre_send=True, receipt=receipt()).action is Action.BLOCKED
    assert decide(None, receipt=receipt(503)).action is Action.BLOCKED
    original = receipt()
    original["cost"]["usageRejected"] = "model_mismatch"
    assert decide("live_answers_invalid", receipt=original).action is Action.BLOCKED
