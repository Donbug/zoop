"""Pure OpenAI -> direct DeepSeek decision; never sends, reserves, releases, or retries.

The caller must durably journal the primary evidence before scheduling at most one
new physical attempt/profile under the SAME logical invocation and admitted set.
A decision is not source permission, budget capacity, or admission authority.
Complete provider/format failures only: native grounding/application validation is
not eligible. Historical jobs, providers, receipts and charges remain unchanged.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from .direct_deepseek import MODEL, MODEL_REVISION
from .relation_contracts import digest

VERSION = "zoop-openai-deepseek-fallback-1"


class Action(StrEnum):
    SUCCESS = "success"
    FALLBACK = "fallback"
    BLOCKED = "blocked"
    INDETERMINATE = "indeterminate"


class Phase(StrEnum):
    PRE_SEND = "pre-send"
    RECEIVED = "received"
    UNKNOWN = "unknown"


class FailureClass(StrEnum):
    NONE = "none"
    PRE_SEND_CREDENTIAL = "pre-send-credential-unavailable"
    SHARED_BUDGET = "shared-budget-exhausted"
    PROVIDER_AUTH = "provider-authentication"
    PROVIDER_BALANCE = "provider-balance"
    PROVIDER_CAPACITY = "provider-capacity"
    RECEIVED_INVALID = "received-invalid-output"
    REFUSAL = "content-refusal"
    PERMISSION = "source-policy-permission"
    UNKNOWN = "unknown-completion"
    ACCOUNTING = "accounting-indeterminate"
    INTEGRITY = "evidence-integrity"
    UNCLASSIFIED = "not-allowlisted"


@dataclass(frozen=True)
class FailureEvidence:
    provider: Literal["openai", "deepseek"]
    phase: Phase
    code: str | None
    receipt: dict[str, Any] | None = None


@dataclass(frozen=True)
class FallbackDecision:
    action: Action
    failure_class: FailureClass
    reason: str
    evidence_digest: str

    def record(self) -> dict[str, str]:
        return {"version": VERSION, "action": self.action.value, "failureClass": self.failure_class.value,
                "reason": self.reason, "evidenceDigest": self.evidence_digest}


PRE_SEND_ELIGIBLE = {
    "live_api_key_required": FailureClass.PRE_SEND_CREDENTIAL,
    "live_budget_exhausted_shared": FailureClass.SHARED_BUDGET,
}
RECEIVED_ELIGIBLE = frozenset({"live_reply_not_json", "live_answers_invalid", "live_output_truncated"})
HTTP_ELIGIBLE = {401: FailureClass.PROVIDER_AUTH, 402: FailureClass.PROVIDER_BALANCE,
                 429: FailureClass.PROVIDER_CAPACITY, 500: FailureClass.PROVIDER_CAPACITY,
                 503: FailureClass.PROVIDER_CAPACITY}
UNKNOWN_CODES = frozenset({"live_response_unknown", "provider_response_unknown", "live_provider_incomplete"})
DENIAL_CODES = frozenset({
    "live_model_refusal", "content_filter", "content_policy_violation", "safety_violation",
    "permission_denied", "insufficient_permissions", "access_denied", "forbidden",
    "source_denied", "source_permission_denied", "source_policy_denied", "policy_denied",
})


def _raw(receipt: dict) -> Any:
    try:
        return json.loads(receipt["http"]["bodyText"])
    except (KeyError, TypeError, ValueError, RecursionError):
        return None


def _refused(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    error = raw.get("error")
    if isinstance(error, dict) and any(isinstance(error.get(key), str) and error[key] in DENIAL_CODES for key in ("code", "type")):
        return True
    choices = raw.get("choices")
    return isinstance(choices, list) and any(
        isinstance(choice, dict) and (choice.get("finish_reason") == "content_filter"
        or isinstance(choice.get("message"), dict) and bool(choice["message"].get("refusal")))
        for choice in choices)


def classify(evidence: FailureEvidence) -> FallbackDecision:
    """Fail closed on missing/contradictory evidence; eligible does not mean authorized.

    RECEIVED with code=None means the owning runtime has successfully decoded the
    receipt. It does not mean a bare HTTP 2xx is a valid analysis. Any supplied
    receipt is retained by its digest; this function never rewrites its charges.
    """
    identity = digest({"provider": evidence.provider, "phase": evidence.phase,
                       "code": evidence.code, "receipt": evidence.receipt})

    def decision(action: Action, category: FailureClass, reason: str) -> FallbackDecision:
        return FallbackDecision(action, category, reason, identity)

    if evidence.phase == Phase.UNKNOWN or evidence.code in UNKNOWN_CODES:
        return decision(Action.INDETERMINATE, FailureClass.UNKNOWN, "primary_completion_unknown")
    if evidence.provider not in ("openai", "deepseek"):
        return decision(Action.BLOCKED, FailureClass.INTEGRITY, "provider_not_supported")
    if evidence.code in DENIAL_CODES:
        return decision(Action.BLOCKED, FailureClass.REFUSAL if evidence.code == "live_model_refusal" else FailureClass.PERMISSION,
                        "source_policy_permission_or_refusal")
    if evidence.phase == Phase.PRE_SEND:
        if evidence.receipt is not None:
            return decision(Action.BLOCKED, FailureClass.INTEGRITY, "presend_receipt_conflict")
        category = PRE_SEND_ELIGIBLE.get(evidence.code)
        if evidence.provider == "openai" and category is not None:
            return decision(Action.FALLBACK, category, evidence.code)
        return decision(Action.BLOCKED, category or FailureClass.UNCLASSIFIED, evidence.code or "presend_outcome_missing")
    if evidence.phase != Phase.RECEIVED or not isinstance(evidence.receipt, dict):
        return decision(Action.INDETERMINATE, FailureClass.UNKNOWN, "received_evidence_missing")
    receipt = evidence.receipt
    http, cost = receipt.get("http"), receipt.get("cost")
    if (not isinstance(http, dict) or type(http.get("status")) is not int
            or not 100 <= http["status"] <= 599 or not isinstance(http.get("bodyText"), str)
            or type(http.get("truncated")) is not bool):
        return decision(Action.INDETERMINATE, FailureClass.INTEGRITY, "received_evidence_invalid")
    raw = _raw(receipt)
    if _refused(raw):
        return decision(Action.BLOCKED, FailureClass.REFUSAL, "provider_refusal")
    if http["status"] in (403, 404):
        return decision(Action.BLOCKED, FailureClass.PERMISSION, "provider_permission_or_route_denied")
    if http["truncated"] or http["status"] in (408, 502, 504):
        return decision(Action.INDETERMINATE, FailureClass.UNKNOWN, "provider_completion_not_proven")
    if not isinstance(cost, dict) or cost.get("settled") is not True:
        return decision(Action.INDETERMINATE, FailureClass.ACCOUNTING, "primary_accounting_not_settled")
    if cost.get("usageRejected"):
        return decision(Action.BLOCKED, FailureClass.INTEGRITY, "primary_usage_rejected")
    model = receipt.get("model")
    if evidence.provider == "openai" and isinstance(model, dict) and model.get("requested") in (MODEL, MODEL_REVISION):
        return decision(Action.BLOCKED, FailureClass.INTEGRITY, "provider_evidence_mismatch")
    if evidence.code is None:
        if 200 <= http["status"] < 300:
            return decision(Action.SUCCESS, FailureClass.NONE, "primary_success")
        return decision(Action.BLOCKED, FailureClass.INTEGRITY, "success_status_conflict")
    # DeepSeek is terminal even on a known failure; never route it back to OpenAI.
    if evidence.provider == "deepseek":
        return decision(Action.BLOCKED, HTTP_ELIGIBLE.get(http["status"], FailureClass.UNCLASSIFIED), evidence.code)
    if evidence.code == f"live_http_{http['status']}" and http["status"] in HTTP_ELIGIBLE:
        return decision(Action.FALLBACK, HTTP_ELIGIBLE[http["status"]], evidence.code)
    if 200 <= http["status"] < 300 and evidence.code in RECEIVED_ELIGIBLE:
        return decision(Action.FALLBACK, FailureClass.RECEIVED_INVALID, evidence.code)
    return decision(Action.BLOCKED, FailureClass.UNCLASSIFIED, evidence.code)


def eligible_failure(*, provider: Literal["openai", "deepseek"], code: str | None, receipt: dict | None = None,
                     pre_send: bool = False, uncertain: bool = False) -> FallbackDecision:
    """Runtime seam: uncertainty dominates every purported known error/success."""
    phase = Phase.UNKNOWN if uncertain else Phase.PRE_SEND if pre_send else Phase.RECEIVED
    return classify(FailureEvidence(provider, phase, code, receipt))
