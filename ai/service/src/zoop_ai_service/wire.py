"""HTTP wire models and the pure rules that build them from runtime output. No process, database or clock access.

Two kinds of model live here:
  * `Wire` models (extra forbidden) are what this service emits and what the generated OpenAPI documents.
  * `View` models (extra ignored) parse a runtime `get` payload. Each field the service relays is named exactly once, so a key
    the runtime adds later is dropped instead of leaking, and a missing key fails closed as an invalid runtime output.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, model_validator
from pydantic.alias_generators import to_camel

SCHEMA = "zoop-ai-internal-1"
KINDS = ("document-summary", "document-sentiment", "semantic-verification", "briefing-outlook")
DOCUMENT_KINDS = ("document-summary", "document-sentiment")
JOB_STATES = ("queued", "running", "reconciling", "persisting", "ready", "failed", "cancelled")
RESUME_MODES = ("none", "validate_only", "save_only", "unsent_only", "reconcile_only")
NEXT_ACTIONS = ("wait", "fetch_result", "operator_reconcile", "recover", "none")
DISPATCH_STATES = ("pending", "in_flight", "idle")
DISPATCH_OUTCOMES = ("exited", "busy", "runtime_error", "transport_unknown", "runtime_unavailable",
                     "service_restarted", "cancelled", "needs_recover")
_SAFE = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
RETRYABLE = frozenset({"runtime_unavailable", "service_busy", "queue_full", "service_configuration_invalid"})

JobState = Literal["queued", "running", "reconciling", "persisting", "ready", "failed", "cancelled"]
ResumeMode = Literal["none", "validate_only", "save_only", "unsent_only", "reconcile_only"]
Kind = Literal["document-summary", "document-sentiment", "semantic-verification", "briefing-outlook"]
Next = Literal["wait", "fetch_result", "operator_reconcile", "recover", "none"]


def _safe(value: str) -> str:
    """Runtime free text is relayed only when it is a short machine code; anything else is replaced, never echoed."""
    return value if _SAFE.fullmatch(value) else "redacted"


Safe = Annotated[str, AfterValidator(_safe)]


def _reviewer(value: str) -> str:
    """The approving principal's name as the S3 review wire carries it: bounded, non-blank free text. It is data, never an identifier pattern, so it is
    relayed exactly (not redacted, not normalised); only an empty/blank or over-long value is invalid."""
    if not value.strip() or len(value) > 200:
        raise ValueError("reviewer must be non-blank and at most 200 characters")
    return value


Reviewer = Annotated[str, AfterValidator(_reviewer)]


class Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    def wire(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class View(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    def wire(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class Usage(Wire):
    provider_attempts: int
    replay_calls: int
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    reasoning_tokens: int | None
    cost: float | None


class Failure(Wire):
    code: Safe
    stage: Kind | None


class Dispatch(Wire):
    state: Literal["pending", "in_flight", "idle"]
    command: Literal["run", "resume"] | None
    dispatch_count: int
    last_outcome: Literal["exited", "busy", "runtime_error", "transport_unknown", "runtime_unavailable",
                          "service_restarted", "cancelled", "needs_recover"] | None
    last_runtime_code: str | None
    updated_at: str


class JobStatus(Wire):
    schema_version: Literal["zoop-ai-internal-1"] = SCHEMA
    job_id: str
    kind: Kind
    mode: Literal["replay", "live"]
    input_digest: str
    state: JobState
    phase: Safe
    resume_mode: ResumeMode
    failure: Failure | None
    artifact_ids: list[str]
    usage: Usage
    unreceipted_attempts: int
    dispatch: Dispatch
    next: Next
    accepted_at: str
    observed_at: str


class ErrorBody(Wire):
    code: str
    retryable: bool
    request_id: str
    runtime_code: str | None = None
    field: str | None = None


class ErrorEnvelope(Wire):
    schema_version: Literal["zoop-ai-internal-1"] = SCHEMA
    error: ErrorBody
    status: JobStatus | None = None


class UsageView(View):
    provider_attempts: int
    replay_calls: int
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    reasoning_tokens: int | None
    cost: float | None


class CallUsage(View):
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    reasoning_tokens: int | None


class CallConfig(View):
    provider: str
    provider_revision: str
    model: str
    reasoning_effort: str | None
    prompt_version: str
    schema_version: str
    policy_version: str


class CallReceipt(View):
    """Per-attempt accounting metadata. It carries no provider receipt, response content, request payload or fixture identity."""
    attempt_id: str
    stage: Kind
    state: Literal["started", "received", "validated", "failed", "unknown"]
    mode: Literal["replay", "live"]
    started_at: str
    received_at: str | None
    input_digest: str
    config: CallConfig
    usage: CallUsage | None
    error: Safe | None
    duration_ms: float | None


class GrantView(View):
    grant_id: str
    revision: str
    source_id: str
    enabled: bool
    rights: Literal["known", "unknown", "denied"]
    allowed_operations: list[str]
    recipients: list[str]
    purposes: list[str]
    evidence: list[str]
    expires_at: str | None


class FailureView(View):
    code: Safe
    stage: Kind | None


class Nested(BaseModel):
    """Strict projection of one runtime contract type: required fields are type-checked without coercion and any field the
    contract does not define (a private or newer protocol field) is dropped. Mirrors `zoop_ai.contracts` by field name and
    requiredness (tests compare them); the service never imports the runtime package."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore", strict=True)


Label = Literal["positive", "negative", "mixed", "undetermined"]
InputKind = Literal["body", "summary"]


class ProvenanceView(Nested):
    source_kind: Literal["synthetic", "actual"]
    execution_mode: Literal["replay", "live"]
    recording_kind: Literal["authored-test", "provider"]


class RawLocatorView(Nested):
    locator_id: str
    start: int
    end: int


class DocumentView(Nested):
    document_id: str
    document_version: str
    source_id: str
    text_artifact_id: str
    input_kind: InputKind
    cleaner_version: str
    text: str
    source_hash: str
    raw_locators: list[RawLocatorView]


class CompanyView(Nested):
    company_id: str
    name: str


class EvidenceRefView(Nested):
    evidence_id: str
    document_id: str
    document_version: str
    text_artifact_id: str
    offset_unit: Literal["unicode_code_point"]
    start: int
    end: int
    quote: str
    input_kind: InputKind
    raw_locator_ids: list[str]


class ClaimView(Nested):
    claim_id: str
    text: str
    assertion_kind: Literal["fact", "interpretation", "limitation"]
    evidence_ids: list[str]


class SummaryView(Nested):
    text: str
    claims: list[ClaimView]
    citations: list[EvidenceRefView]
    limitations: list[str]


class SentimentView(Nested):
    label: Label
    rationale: str
    claims: list[ClaimView]
    citations: list[EvidenceRefView]
    limitations: list[str]


class ClaimVerdictView(Nested):
    claim_id: str
    decision: Literal["supported", "contradicted", "insufficient"]
    reason: str


class VerificationView(Nested):
    claims: list[ClaimVerdictView]
    prohibited_advice: bool
    unsupported_causality: bool


class OutlookAnswerView(Nested):
    label: Label
    rationale: str
    issue_ids: list[str]


class JobInputView(Nested):
    document: DocumentView
    company: CompanyView
    grant_id: str
    grant_revision: str
    candidate: SummaryView | SentimentView | None


class OutlookIssueView(Nested):
    event_id: str
    title: str
    event_time: str | None
    companies: list[dict[str, Any]]  # a legitimate domain map of the round, relayed as the contract defines it


class OutlookInputView(Nested):
    round_id: str
    scheduled_at: str
    graph_version: str
    review_revision: int
    rule_revision: int
    issues: list[OutlookIssueView]
    document_sentiments: list[dict[str, Any]]
    market_variables: dict[str, Any]
    source_id: str
    grant_id: str
    grant_revision: str


class SubmitView(Nested):
    schema_version: Literal["zoop-ai-s1-1"]
    job_id: str
    kind: Kind
    input: JobInputView | OutlookInputView
    mode: Literal["replay", "live"]
    provenance: ProvenanceView

    @model_validator(mode="after")
    def kind_matches_input(self) -> SubmitView:
        if (self.kind == "briefing-outlook") != isinstance(self.input, OutlookInputView):
            raise ValueError("input does not match kind")
        return self


class ValidationView(Nested):
    exact: bool
    semantic: Literal["supported", "hold", "reject"] | None
    eligible: bool
    reason: str | None


class ArtifactView(Nested):
    schema_version: Literal["zoop-ai-s1-1"]
    artifact_id: str
    kind: Kind
    result_version: str
    job_id: str
    attempt_id: str
    input_digest: str
    source_refs: list[DocumentView]
    dependency_refs: list[str]
    model_config_revision: str
    prompt_version: str
    policy_version: str
    produced_at: str
    provenance: ProvenanceView
    company_id: str | None
    grant_id: str
    grant_revision: str
    claims: list[ClaimView]
    validation: ValidationView
    result: SummaryView | SentimentView | VerificationView | OutlookAnswerView


class JobView(View):
    """The allowlisted shape of a runtime `get` payload, projected field by field down to the leaves. Nothing outside the
    published contract survives, and a missing or mistyped required field fails closed. `input` and `artifacts` reach a caller
    only after the current-grant check."""
    schema_version: Literal["zoop-ai-s1-1"]
    job_id: str
    input_digest: str
    state: JobState
    phase: Safe
    attempt_id: str | None
    artifact_ids: list[str]
    artifacts: list[ArtifactView]
    failure: FailureView | None
    resume_mode: ResumeMode
    usage: UsageView
    grant: GrantView | None
    input: SubmitView
    calls: list[CallReceipt]


class Delivery(Wire):
    state: Literal["available", "withheld"]
    reason: str | None = None


class ResultEnvelope(Wire):
    schema_version: Literal["zoop-ai-internal-1"] = SCHEMA
    status: JobStatus
    delivery: Delivery
    job: dict[str, Any] | None
    receipts: list[CallReceipt]


def next_action(state: str, resume_mode: str, dispatch_state: str) -> str:
    """Pure and ordered: what the caller should do next."""
    if dispatch_state in ("pending", "in_flight"):
        return "wait"
    if state == "ready":
        return "fetch_result"
    if state == "reconciling":
        return "operator_reconcile"
    if state == "cancelled" or (state == "failed" and resume_mode == "none"):
        return "none"
    return "recover"


def required_stages(kind: str) -> tuple[str, ...]:
    return (kind,) if kind in ("semantic-verification", "briefing-outlook") else (kind, "semantic-verification")


def unreceipted_attempts(view: JobView) -> int:
    """Attempts whose outcome the runtime never recorded. A cache hit made no call of its own: its `calls` are the creator's."""
    if view.phase == "artifact.cache_hit":
        return 0
    return sum(call.state in ("started", "unknown") for call in view.calls)


def receipts_complete(view: JobView) -> bool:
    """True only when every stage this job needs already has a stored receipt and nothing is stuck.

    This mirrors the runtime CLI's own rule for building a provider client at all: when it holds, `run`/`resume` can only
    persist saved receipts and cannot send anything.
    """
    if view.phase == "artifact.cache_hit" or any(call.state in ("started", "unknown", "failed") for call in view.calls):
        return False
    received = {call.stage for call in view.calls if call.state in ("received", "validated")}
    return set(required_stages(view.input.kind)) <= received


def continuation_would_send(view: JobView) -> bool:
    """True when running or resuming this job now would send a stage that no one has authorized since it was interrupted.

    Some stage already has a stored receipt, a needed stage has none, and nothing (a started, unknown or failed attempt) stops the
    runtime CLI from building a provider client. That is exactly the window between two stages. A job that never sent anything
    (no calls) is the original, accepted intent and is not this case; a job with a started/unknown attempt only reconciles.
    """
    if any(call.state in ("started", "unknown", "failed") for call in view.calls):
        return False
    received = {call.stage for call in view.calls if call.state in ("received", "validated")}
    return bool(received) and not set(required_stages(view.input.kind)) <= received
