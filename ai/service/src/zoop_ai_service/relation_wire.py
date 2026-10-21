"""Wire models of the S3 relation-job family (`zoop-ai-internal-relation-1`) and the allowlisted projection of a pipeline result.

Three kinds of model live here, mirroring `wire.py` for S1 without sharing its schema or state machine:
  * `Rel` models (extra forbidden) are what this service emits and what the generated OpenAPI documents;
  * `Request` models (strict, extra forbidden) validate the one body a caller may send;
  * `Rt` / `Rc` projections (strict, extra ignored) parse a `zoop-ai-relation inspect` payload. Each field the service relays is
    named exactly once, so a key the pipeline adds later (artifact ids, raw/mapping hashes, fixture and request digests, free-text
    reviewer notes, claim and quote tables, a grant snapshot) is dropped instead of leaking, and a missing or mistyped required
    field fails closed. `Rt` is the content-free status view; `Rc` is read only after every delivery gate passed.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from .wire import ErrorBody, Reviewer, Safe

SCHEMA = "zoop-ai-internal-relation-1"
RUNTIME_SCHEMA = "zoop-relation-s3"
JOB_ID_PATTERN = r"^[A-Za-z0-9_.-]{1,120}$"
UPSTREAM_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,200}$"
HASH_PATTERN = r"^[a-f0-9]{64}$"
RELATION_ID_PATTERN = r"^rc-[a-f0-9]{64}$"
EXPECTED_REVISION_PATTERN = r"^[1-9][0-9]{0,8}$"  # a relation's event-chain revision as a decimal string; the pipeline's own minimum is 1
SOURCE_REVISION_PATTERN = r"^(0|[1-9][0-9]{0,8})$"  # what a result reports: a candidate with no event yet is revision 0

STATES = ("queued", "running", "reconciling", "stopped", "ready", "cancelled")
RESUME_MODES = ("none", "resume", "reconcile_only")
NEXT_ACTIONS = ("wait", "fetch_result", "operator_reconcile", "recover", "none")
DISPATCH_STATES = ("pending", "in_flight", "idle")
DISPATCH_OUTCOMES = ("exited", "busy", "runtime_error", "transport_unknown", "runtime_unavailable", "service_restarted", "cancelled")
RETRYABLE = frozenset({"runtime_unavailable", "runtime_busy", "service_busy", "queue_full", "service_configuration_invalid", "review_unconfirmed"})

State = Literal["queued", "running", "reconciling", "stopped", "ready", "cancelled"]
ResumeMode = Literal["none", "resume", "reconcile_only"]
Next = Literal["wait", "fetch_result", "operator_reconcile", "recover", "none"]
DispatchOutcome = Literal["exited", "busy", "runtime_error", "transport_unknown", "runtime_unavailable", "service_restarted", "cancelled"]
Decision = Literal["allow", "reject"]
OperationNext = Literal["retry_review", "none"]
RevalidationState = Literal["not_requested", "verified", "superseded", "contract_changed"]
ExecutionMode = Literal["replay", "live"]
RecordingKind = Literal["authored-test", "provider"]
PAIRS = {("replay", "authored-test"), ("live", "provider")}


class Rel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    def wire(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class Request(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid", strict=True)

    def wire(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class Projection(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore", strict=True)

    def wire(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


# ---- the one request a caller may send --------------------------------------------------------------------------------

class RelationProvenance(Request):
    source_kind: Literal["synthetic", "actual"]
    execution_mode: ExecutionMode
    recording_kind: RecordingKind

    @model_validator(mode="after")
    def pair(self) -> RelationProvenance:
        if (self.execution_mode, self.recording_kind) not in PAIRS:
            raise ValueError("executionMode and recordingKind disagree")
        return self


class RelationUpstream(Request):
    job_id: str = Field(pattern=UPSTREAM_ID_PATTERN, description="An operator-prepared S2 extraction job. It must be listed for the calling principal in the server-owned allowlist.")
    input_digest: str = Field(pattern=HASH_PATTERN)


class RelationSubmit(Request):
    """The S3 `Submit` contract (`zoop-relation-s3`). Fixtures, registries and paths cannot be named. `executionMode: live` is accepted only for an upstream the operator listed as live-approved."""
    schema_version: Literal["zoop-relation-s3"]
    job_id: str = Field(pattern=JOB_ID_PATTERN, description="Equals the Idempotency-Key.")
    provenance: RelationProvenance
    upstream: RelationUpstream


class RelationReview(Request):
    """One review decision on one relation candidate. The path names the job and the Idempotency-Key is the stable operation id. The reviewer
    is the authenticated principal and cannot be sent; nothing here is the application's own review revision."""
    relation_candidate_id: str = Field(pattern=RELATION_ID_PATTERN)
    expected_source_version: str = Field(pattern=HASH_PATTERN, description="The job's `sourceVersion`: its `inputDigest`, as read from the result or status.")
    expected_source_revision: str = Field(pattern=EXPECTED_REVISION_PATTERN, description="The relation's `sourceRevision` as read from the result: the runtime's event-chain revision as a decimal string. Never the application's own revision.")
    decision: Decision


# ---- status (content-free) ---------------------------------------------------------------------------------------------

class RelationUsage(Rel):
    replay_calls: int
    started_without_receipt: int
    provider_calls: int
    model_calls: int


class RelationFailure(Rel):
    code: Safe


class RelationDelivery(Rel):
    state: Literal["available", "withheld"]
    reason: Safe | None = None


class RelationDispatch(Rel):
    state: Literal["pending", "in_flight", "idle"]
    dispatch_count: int
    last_outcome: Literal["exited", "busy", "runtime_error", "transport_unknown", "runtime_unavailable", "service_restarted", "cancelled"] | None
    last_runtime_code: Safe | None
    updated_at: str


class RelationJobStatus(Rel):
    schema_version: Literal["zoop-ai-internal-relation-1"] = SCHEMA
    job_id: str
    input_digest: str
    provenance: RelationProvenance
    upstream: RelationUpstream
    state: State
    phase: Safe
    resume_mode: ResumeMode
    failure: RelationFailure | None
    usage: RelationUsage
    delivery: RelationDelivery
    dispatch: RelationDispatch
    next: Next
    accepted_at: str
    observed_at: str


class RelationReviewPhase(Rel):
    """Acceptance: whether the decision is recorded in the AI relation ledger. `unconfirmed` means the request was reserved but the service has no
    proof yet that the event was appended; retry the same request (same key and body) to reconcile it."""
    state: Literal["unconfirmed", "applied"]
    resulting_source_revision: str | None
    recorded_at: str | None


class RelationRevalidationPhase(Rel):
    """Legacy only. A final approval (`allow`) or exclusion (`reject`) requests no revalidation (`not_requested`). The two other states describe an
    operation recorded under the earlier contract, where an `allow` asked for an automatic re-check: `verified`/`superseded` are what its stored
    history settled, `contract_changed` that it never settled and never will (nothing is dispatched or resent)."""
    state: RevalidationState
    dispatch_count: int
    last_outcome: DispatchOutcome | None
    last_runtime_code: Safe | None
    verdict: Literal["eligible", "hold", "reject"] | None
    resulting_source_revision: str | None
    updated_at: str | None


class RelationPublicationPhase(Rel):
    """Publication is never done by this service: the relation stays unpublished whatever the verdict says."""
    state: Literal["not_published"] = "not_published"


class RelationOperationStatus(Rel):
    """One review operation, identified exactly by the caller's Idempotency-Key. Content-free; read from the service ledger."""
    schema_version: Literal["zoop-ai-internal-relation-1"] = SCHEMA
    operation_id: str
    job_id: str
    relation_candidate_id: str
    decision: Decision
    reviewer: str
    expected_source_version: str
    expected_source_revision: str
    review: RelationReviewPhase
    revalidation: RelationRevalidationPhase
    publication: RelationPublicationPhase
    next: OperationNext
    limitation: Literal["review_contract_changed"] | None
    accepted_at: str
    observed_at: str


class RelationReceipt(Rel):
    """Per-call accounting metadata: no request/response digest, fixture identity or content."""
    stage: Safe
    state: Safe
    verdict: Safe | None


# ---- the pipeline `inspect` payload, status part -------------------------------------------------------------------------

class RtUpstream(Projection):
    job_id: str
    input_digest: str


class RtRuntime(Projection):
    identity: str = Field(pattern=HASH_PATTERN)   # the frozen live runtime binding's identity (sha256 of its canonical form, secret-free)


class RtBinding(Projection):
    upstream: RtUpstream
    runtime: RtRuntime | None = None              # live jobs only; replay bindings carry none


class RtFailure(Projection):
    code: Safe  # `detail` is dropped: it can carry request digests or counters, never anything a caller needs


class RtUsage(Projection):
    replay_calls: int
    started_without_receipt: int
    provider_calls: int
    model_calls: int


class RtCall(Projection):
    stage: Safe
    state: Safe
    verdict: Safe | None


class RtDelivery(Projection):
    status: Literal["current", "withheld"]
    code: Safe | None = None


class RtProvenance(Projection):
    source_kind: Literal["synthetic", "actual"]
    execution_mode: ExecutionMode
    recording_kind: RecordingKind

    @model_validator(mode="after")
    def pair(self) -> RtProvenance:
        if (self.execution_mode, self.recording_kind) not in PAIRS:
            raise ValueError("executionMode and recordingKind disagree")
        return self


class RelationView(Projection):
    schema_version: Literal["zoop-relation-s3"]
    job_id: str
    input_digest: str
    state: State
    phase: Safe
    resume_mode: ResumeMode
    failure: RtFailure | None
    provenance: RtProvenance
    binding: RtBinding
    usage: RtUsage
    calls: list[RtCall]
    delivery: RtDelivery


# ---- the pipeline `inspect` payload, event-chain part: read INSIDE the service only, to prove what the chain holds. Never emitted. ----

class RtAttempt(Projection):
    kind: str


class RtEvent(Projection):
    """One append-only chain entry. `reviewer` and `note` are free text; they are compared with the operation marker and never relayed."""
    seq: int
    kind: Literal["verdict", "review"]
    created_at: str
    eligibility: str | None = None
    decision: Decision | None = None
    reviewer: str | None = None
    note: str | None = None
    expected_revision: int | None = None
    effect: str | None = None
    attempt: RtAttempt | None = None


class RtChainEligibility(Projection):
    status: Literal["pending", "eligible", "hold", "reject"]
    revision: int
    review_pending: bool


class RtChainRelation(Projection):
    relation_candidate_id: str
    eligibility: RtChainEligibility
    history: list[RtEvent]


class RelationChain(Projection):
    job_id: str
    input_digest: str
    relations: list[RtChainRelation]


# ---- the pipeline `inspect` payload, content part (read only when delivery is current and every service gate passed) -------

class RcEndpoint(Projection):
    kind: Literal["company", "event", "topic"]
    ref: str


class RcCitation(Projection):
    document_id: str
    document_version: str
    start: int
    end: int
    quote: str | None = None
    error: Safe | None = None

    @model_validator(mode="after")
    def unverified_text_is_not_relayed(self) -> RcCitation:
        if self.error is not None:
            self.quote = None  # an invalid citation carries generator text that was never matched to the source
        elif self.quote is None:
            raise ValueError("verified citation without its quote")
        return self


class RcReason(Projection):
    code: Safe
    at: Safe | None = None
    detail: Safe | None = None


class RcValidity(Projection):
    from_: str | None = Field(alias="from")
    until: str | None
    from_status: Safe
    until_status: Safe
    citations: list[RcCitation]


class RcStep(Projection):
    type: Safe
    subject: RcEndpoint
    object: RcEndpoint
    citations: list[RcCitation]


class RcContext(Projection):
    market: Safe
    check: Safe
    known_countries: list[str]


class RcPrecheck(Projection):
    state: Safe
    reasons: list[RcReason]


class RcApprovalBasis(Projection):
    """Why a relation is `eligible`: the automatic verifier's verdict or the operator's final approval, with the deciding chain event."""
    kind: Literal["automatic-verifier", "operator-final-approval"]
    revision: int
    reviewer: Reviewer | None
    decided_at: str


class RcEligibility(Projection):
    status: Literal["pending", "eligible", "hold", "reject"]
    reasons: list[RcReason]
    revision: int
    review_pending: bool
    approval_basis: RcApprovalBasis | None


class RcEvent(Projection):
    """One append-only chain entry. Reviewer and note are free text from operator CLI reviews and are never relayed."""
    seq: int
    kind: Literal["verdict", "review"]
    created_at: str
    eligibility: Safe | None = None
    reasons: list[RcReason] = Field(default_factory=list)
    decision: Literal["allow", "reject"] | None = None
    effect: Safe | None = None


class RcProposal(Projection):
    direction: Literal["positive", "negative", "mixed", "undetermined"]
    reason: str
    limitations: str | None
    supporting: list[RcCitation]
    opposing: list[RcCitation]


class RcImpactVerdict(Projection):
    status: Safe
    label: Safe | None
    reasons: list[RcReason]
    target_verdict: Safe | None
    verifier: Safe


class RcImpact(Projection):
    impact_candidate_id: str
    relation_candidate_id: str
    impacted_company_id: str
    proposal: RcProposal
    precheck: RcPrecheck
    verdict: RcImpactVerdict | None
    agreement: bool | None


class RcImpactSummary(Projection):
    status: Safe
    label_note: str
    candidates: list[RcImpact]


class RcRelation(Projection):
    relation_candidate_id: str = Field(pattern=RELATION_ID_PATTERN)
    source_version: str = Field(description="The runtime job's `inputDigest`: send it back as `expectedSourceVersion`. Immutable for the job.")
    source_revision: str = Field(pattern=SOURCE_REVISION_PATTERN, description="This relation's runtime event-chain revision (the same number as `eligibility.revision`, as a decimal string): send it back as `expectedSourceRevision`. Not the application's review revision.")
    type: Safe
    direction: Safe | None
    subject: RcEndpoint
    object: RcEndpoint
    reordered: bool
    connection: Literal["direct", "indirect"]
    business_scope: str | None
    product_scope: str | None
    validity: RcValidity
    countries: list[str]
    context: RcContext
    citations: list[RcCitation]
    path: list[RcStep]
    generator_reasons: list[str]
    proposal_count: int
    precheck: RcPrecheck
    approved: Literal[False]
    eligibility: RcEligibility
    history: list[RcEvent]
    impact: RcImpactSummary

    @model_validator(mode="after")
    def source_revision_is_the_chain_revision(self) -> RcRelation:
        if self.source_revision != str(self.eligibility.revision):
            raise ValueError("source revision disagrees with the eligibility revision")
        return self


class RcEligibilityCounts(Projection):
    pending: int
    eligible: int
    hold: int
    reject: int


class RcLabelCounts(Projection):
    positive: int
    negative: int
    mixed: int
    undetermined: int


class RcCounts(Projection):
    relations: int
    eligibility: RcEligibilityCounts
    impact_labels: RcLabelCounts
    impact_candidates: int


class RelationJobContent(Projection):
    """The delivered candidates of one ready job. `approved` is always false: `eligible` is the automatic evidence gate, not publication."""
    job_id: str
    input_digest: str
    counts: RcCounts
    relations: list[RcRelation]


def with_source_identity(raw: dict[str, Any]) -> dict[str, Any]:
    """The pipeline payload plus the identity a review must quote back. `sourceVersion` is the job's `inputDigest` (immutable per job);
    `sourceRevision` is each relation's event count, the runtime's own optimistic-concurrency token, as a decimal string. Both are derived
    from fields the pipeline already reports, never from the application's revision."""
    return {**raw, "relations": [{**relation, "sourceVersion": raw["inputDigest"], "sourceRevision": str(relation["eligibility"]["revision"])}
                                 for relation in raw["relations"]]}


class RelationResultEnvelope(Rel):
    schema_version: Literal["zoop-ai-internal-relation-1"] = SCHEMA
    status: RelationJobStatus
    delivery: RelationDelivery
    job: RelationJobContent | None
    receipts: list[RelationReceipt]


class RelationErrorEnvelope(Rel):
    schema_version: Literal["zoop-ai-internal-relation-1"] = SCHEMA
    error: ErrorBody
    status: RelationJobStatus | None = None
    operation: RelationOperationStatus | None = None


def next_action(state: str, dispatch_state: str) -> str:
    """Pure and ordered: what the caller should do next."""
    if dispatch_state in ("pending", "in_flight"):
        return "wait"
    if state == "ready":
        return "fetch_result"
    if state == "reconciling":
        return "operator_reconcile"
    if state == "cancelled":
        return "none"
    return "recover"
