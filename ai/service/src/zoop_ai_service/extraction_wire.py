"""Wire models of the S2 extraction-job family (`zoop-ai-internal-extraction-1`) and the allowlisted projection of a `zoop-ai-extract` result.

Same three kinds of model as the S3 family (`relation_wire.py`), sharing none of its schema:
  * `Rel` models (extra forbidden) are what this service emits and what the generated OpenAPI documents;
  * `Request` models (strict, extra forbidden) validate the one body a caller may send: only a job id and the digest of an operator-approved request;
  * `Rt` / `Ec` projections (strict, extra ignored) parse a `zoop-ai-extract inspect` payload. Each field the service relays is named exactly once, so
    a key the pipeline adds later (artifact ids, raw/mapping hashes, locator ids, fixture and request digests, the grant snapshot, the stored
    binding) is dropped instead of leaking, and a missing or mistyped required field fails closed. `Rt` is the content-free status view; `Ec` is read
    only after every delivery gate passed. Text the replay model produced and that no exact source citation backs (the mention's own evidence list,
    a comparison's own evidence list) is not relayed: the verified `citations` are.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .relation_wire import (HASH_PATTERN, JOB_ID_PATTERN, PAIRS, ExecutionMode, Next, Projection, RecordingKind, Rel, Request,  # noqa: F401 (next_action is re-exported)
                            ResumeMode, State, next_action)
from .wire import ErrorBody, Safe

SCHEMA = "zoop-ai-internal-extraction-1"
RUNTIME_SCHEMA = "zoop-extraction-s2-2"
RETRYABLE = frozenset({"runtime_unavailable", "runtime_busy", "service_busy", "queue_full", "service_configuration_invalid"})
DispatchOutcome = Literal["exited", "busy", "runtime_error", "transport_unknown", "runtime_unavailable", "service_restarted", "cancelled"]



# ---- the one request a caller may send --------------------------------------------------------------------------------

class ExtractionSubmit(Request):
    """The S2 submit reference. It names a request the operator preapproved for this principal; it carries no snapshot, catalogue, observation,
    path, fixture or live mode, and the pipeline's `Submit` body is never accepted from a caller."""
    schema_version: Literal["zoop-extraction-s2-2"]
    job_id: str = Field(pattern=JOB_ID_PATTERN, description="Equals the Idempotency-Key. The server-owned approval is looked up by this principal and job id.")
    approved_request_digest: str = Field(pattern=HASH_PATTERN, description="SHA-256 of the canonical JSON of the operator-approved S2 request. It must be the digest the operator listed for this principal and job id.")


# ---- status (content-free) ---------------------------------------------------------------------------------------------

class ExtractionProvenance(Rel):
    source_kind: Literal["synthetic", "actual"]
    execution_mode: ExecutionMode
    recording_kind: RecordingKind


class ExtractionApproval(Rel):
    approved_request_digest: str


class ExtractionUsage(Rel):
    """Accounting. `providerCalls` counts calls transmitted or possibly transmitted (a started call without receipt included), `receivedCalls` the
    ones a reply was stored for, `unsentCalls` the ones definitively NOT sent. A replay job reports 0/null for the live-only fields."""
    replay_calls: int
    started_without_receipt: int
    provider_calls: int
    paid_model_calls: int
    received_calls: int
    unsent_calls: int
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    estimated_usd: str | None
    charged_usd: str | None


class ExtractionFailure(Rel):
    code: Safe


class ExtractionStage(Rel):
    stage: Literal["extract", "compare", "topic"]
    state: Literal["pending", "complete"]


class ExtractionDelivery(Rel):
    state: Literal["available", "withheld"]
    reason: Safe | None = None


class ExtractionDispatch(Rel):
    state: Literal["pending", "in_flight", "idle"]
    dispatch_count: int
    last_outcome: DispatchOutcome | None
    last_runtime_code: Safe | None
    updated_at: str


class ExtractionJobStatus(Rel):
    schema_version: Literal["zoop-ai-internal-extraction-1"] = SCHEMA
    job_id: str
    input_digest: str
    approval: ExtractionApproval
    provenance: ExtractionProvenance
    state: State
    phase: Safe
    resume_mode: ResumeMode
    failure: ExtractionFailure | None
    usage: ExtractionUsage
    stages: list[ExtractionStage]
    delivery: ExtractionDelivery
    dispatch: ExtractionDispatch
    next: Next
    accepted_at: str
    observed_at: str


class ExtractionReceipt(Rel):
    """Per-call accounting metadata: no request/response digest, fixture hash or content."""
    stage: Safe
    state: Safe
    verdict: Safe | None


# ---- the pipeline `inspect` payload, status part -------------------------------------------------------------------------

class RtFailure(Projection):
    code: Safe  # `detail` is dropped: it can carry request digests or counters


class RtUsage(Projection):
    replay_calls: int
    started_without_receipt: int
    provider_calls: int
    paid_model_calls: int
    received_calls: int = 0
    unsent_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    estimated_usd: str | None = None
    charged_usd: str | None = None


class RtCall(Projection):
    stage: Safe
    state: Safe
    verdict: Safe | None
    fixture_hash: str | None = None  # a replay call's answering fixture bytes, read inside the service only; a live call has none


class RtStage(Projection):
    state: Literal["pending", "complete"]


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


class RtLive(Projection):
    binding_digest: str = Field(pattern=HASH_PATTERN)  # the frozen live runtime binding's identity (secret-free)


class RtBinding(Projection):
    live: RtLive | None = None                         # live jobs only


class ExtractionView(Projection):
    schema_version: Literal["zoop-extraction-s2-2"]
    job_id: str
    input_digest: str
    state: State
    phase: Safe
    resume_mode: ResumeMode
    failure: RtFailure | None
    provenance: RtProvenance
    binding: RtBinding | None = None
    stages: dict[str, RtStage]
    usage: RtUsage
    calls: list[RtCall]
    delivery: RtDelivery


# ---- the pipeline `inspect` payload, content part (read only when delivery is current and every service gate passed) ------

class EcCitation(Projection):
    """An exact, source-mapped quote. The artifact id, raw locator ids and source segment table the pipeline also stores are not relayed."""
    evidence_id: str
    document_id: str
    document_version: str
    start: int
    end: int
    quote: str
    offset_unit: Literal["unicode_code_point"]


class EcDocument(Projection):
    """The immutable document identity. The raw-bytes version the pipeline also stores is not relayed."""
    document_id: str
    document_version: str


class EcParticipant(Projection):
    company_id: str | None = None
    name: str
    role: str


class EcMention(Projection):
    """The replay model's mention. Its own evidence list is not relayed (the candidate's verified `citations` are)."""
    mention_id: str
    title: str
    event_type: str
    action: str
    target: str | None = None
    event_time: str | None = None
    period: str | None = None
    assertion_status: Literal["occurred", "announced", "planned", "forecast", "cancelled", "unknown"]
    participants: list[EcParticipant]
    keywords: list[str] = Field(default_factory=list)
    background: bool = False
    countries: list[str] = Field(default_factory=list)


Relation = Literal["SAME", "DIFFERENT", "FOLLOWS", "CONFLICT", "HOLD"]


class EcOriginal(Projection):
    relation: Relation
    reason: str


class EcEffective(Projection):
    relation: Relation
    reason: str
    rule: Safe | None = None


class EcComparison(Projection):
    event_candidate_id: str
    target_event_id: str
    target_revision: str
    original: EcOriginal
    effective: EcEffective
    citations: list[EcCitation]


class EcDisposition(Projection):
    status: Safe
    reason: Safe
    target_event_id: str | None
    same_targets: list[str]
    follows: list[str]
    held_by: list[str]
    compared_events: int


class EcEventCandidate(Projection):
    event_candidate_id: str
    mention_candidate_id: str
    local_mention_id: str
    document: EcDocument
    state: Literal["candidate", "rejected"]
    reason: Safe | None
    approved: Literal[False]
    mention: EcMention
    citations: list[EcCitation]
    comparisons: list[EcComparison]
    disposition: EcDisposition | None


class EcTopicMember(Projection):
    kind: Literal["event-candidate", "snapshot-event"]
    ref: str
    revision: str | None


class EcTopicCandidate(Projection):
    topic_candidate_id: str
    status: Safe
    approved: Literal[False]
    producer_version: Safe
    label: str
    criteria: str
    rationale: str
    members: list[EcTopicMember]
    citations: list[EcCitation]


class EcEventCounts(Projection):
    total: int
    candidate: int
    rejected: int


class EcCounts(Projection):
    documents: int
    snapshot_events: int
    event_candidates: EcEventCounts
    comparisons: int
    effective_relations: dict[str, int]
    dispositions: dict[str, int]
    topic_candidates: int


class ExtractionJobContent(Projection):
    """The delivered candidates of one ready job. Nothing here is approved: `approved` is false on every candidate."""
    job_id: str
    input_digest: str
    counts: EcCounts
    event_candidates: list[EcEventCandidate]
    topic_candidates: list[EcTopicCandidate]


class ExtractionResultEnvelope(Rel):
    schema_version: Literal["zoop-ai-internal-extraction-1"] = SCHEMA
    status: ExtractionJobStatus
    delivery: ExtractionDelivery
    job: ExtractionJobContent | None
    receipts: list[ExtractionReceipt]


class ExtractionErrorEnvelope(Rel):
    schema_version: Literal["zoop-ai-internal-extraction-1"] = SCHEMA
    error: ErrorBody
    status: ExtractionJobStatus | None = None
