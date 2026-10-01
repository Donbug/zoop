"""Pydantic models for the ``/api/admin`` surface (camelCase JSON, every field required)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, StrictBool, StrictInt

from .schemas import (
    BriefingItem,
    BriefingMetadata,
    BriefingReferences,
    BriefingWindow,
    CamelModel,
)

Reason = Annotated[str, Field(min_length=1, max_length=500)]


# ---- auth


class AdminInfo(CamelModel):
    id: str
    email: str
    display_name: str
    role: Literal["admin"]


class AdminLoginRequest(CamelModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


class AdminSession(CamelModel):
    authenticated: bool
    expired: bool
    expired_reason: Literal["idle", "absolute"] | None
    admin: AdminInfo | None
    expires_at: str | None
    idle_expires_at: str | None
    idle_timeout_seconds: int
    absolute_timeout_seconds: int


class ReasonRequest(CamelModel):
    reason: Reason


# ---- pipeline / candidates


class ErrorInfo(CamelModel):
    code: str
    message: str


class ReviewDecisionOut(CamelModel):
    id: int
    target_type: Literal["candidate", "relation"]
    target_id: str
    decision: Literal["allow", "reject"]
    reason: str
    admin_email: str
    decided_at: str
    revision: int
    origin: Literal["admin", "snapshot-migration"]


class CandidateCompany(CamelModel):
    company_id: str | None
    name: str
    role: str


class CandidateRule(CamelModel):
    """A candidate a publication rule covers: whether it is on the user graph through the rule, and what it leaves out."""

    rule_id: str
    applied: bool
    not_applied_reason: Literal["admin_decision", "rule_disabled", "not_published"] | None
    withheld_participants: list[int] = Field(description="Indexes into the candidate's mention participants whose role is left out")
    withheld_relations: list[str] = Field(description="Relation ids whose role is left out")
    dropped_relations: list[str] = Field(
        description="Relation ids the rule does not publish at all (a FOLLOWS whose follow-side event did not occur yet)"
    )


class CandidateRow(CamelModel):
    candidate_id: str
    issue_id: str
    status: Literal["ALLOW", "HOLD", "REJECT"]
    active: bool
    policy_version: str
    title: str
    action: str
    target: str | None
    event_time: str | None
    companies: list[CandidateCompany]
    relation_types: list[str]
    evidence_count: int
    reasons: list[str]
    on_user_graph: bool
    decision: ReviewDecisionOut | None
    rule: CandidateRule | None


class CandidateList(CamelModel):
    items: list[CandidateRow]
    next_cursor: str | None
    counts: dict[str, int]
    as_of: str


class CandidateMention(CamelModel):
    mention_id: str
    title: str
    action: str
    target: str | None
    event_time: str | None
    period: str | None
    assertion_status: str | None
    background: bool
    countries: list[str]
    keywords: list[str]
    participants: list[CandidateCompany]


class CandidateArticle(CamelModel):
    article_id: str
    title: str | None
    publisher: str | None
    url: str | None
    published_at: str | None
    synthetic: bool


class CandidateEvidence(CamelModel):
    article_id: str
    article_version: str
    start: int
    end: int
    quote: str
    article_title: str | None
    url: str | None


class CandidateRelation(CamelModel):
    relation_id: str
    relation_type: str
    source: str
    target: str
    role: str | None
    assertion_status: str | None
    evidence_count: int
    on_user_graph: bool
    decision: ReviewDecisionOut | None


class VerdictOut(CamelModel):
    target: str
    decision: str
    reason: str


class FieldVerdictOut(CamelModel):
    field: str
    decision: str
    reason: str


class ObservationOut(CamelModel):
    target: str
    check: str
    choice: str
    confidence: float | None
    probabilities: dict[str, float]


class VerificationOut(CamelModel):
    provider: str | None
    model: str | None
    verifier_version: str | None
    decision_policy: dict[str, float] | None
    verdicts: list[VerdictOut]
    field_verdicts: list[FieldVerdictOut]
    observations: list[ObservationOut]


class CandidateDetail(CandidateRow):
    mention: CandidateMention
    articles: list[CandidateArticle]
    evidence: list[CandidateEvidence]
    relations: list[CandidateRelation]
    verification: VerificationOut
    invalidation_reason: str | None
    history: list[ReviewDecisionOut]


class DecisionRequest(CamelModel):
    decision: Literal["allow", "reject"]
    reason: Reason
    relation_id: str | None = Field(default=None, max_length=200)


class DecisionResponse(CamelModel):
    decision: ReviewDecisionOut
    idempotent: bool
    on_user_graph: bool
    graph_version: str
    review_revision: int


class RuleChangeOut(CamelModel):
    id: int
    enabled: bool
    reason: str
    admin_email: str
    changed_at: str


class ReviewRuleOut(CamelModel):
    """A publication rule (``review_rules.py``); the id carries its version, e.g. ``R1@2``."""

    id: str
    title: str
    summary: str
    enabled: bool
    default_enabled: bool
    changed_at: str | None
    changed_by: str | None
    reason: str | None
    eligible: int = Field(description="HOLD candidates of the active version the rule covers (ignoring the switch and admin decisions)")
    published_candidates: int
    published_events: int
    history: list[RuleChangeOut]


class RuleList(CamelModel):
    items: list[ReviewRuleOut]
    as_of: str


class RuleSwitchRequest(CamelModel):
    enabled: StrictBool
    reason: Reason


class RuleSwitchResponse(CamelModel):
    rule: ReviewRuleOut
    idempotent: bool
    review_revision: int


class Neo4jStatus(CamelModel):
    status: Literal["reachable", "unreachable"]
    issues_in_ledger: int
    issues_projected: int | None
    missing_issue_ids: list[str]
    stale_issue_ids: list[str]
    error: ErrorInfo | None


class GraphDbStatus(CamelModel):
    status: Literal["reflected", "pending", "mismatch", "unavailable"]
    pending_jobs: int | None
    oldest_pending_at: str | None
    last_completed_at: str | None
    neo4j: Neo4jStatus | None = Field(alias="neo4j")
    checked_at: str


class UsageOut(CamelModel):
    calls: int
    replay_calls: int = 0
    input_tokens: int
    output_tokens: int
    elapsed_seconds: float
    estimated_cost: float | None


class PastRun(CamelModel):
    run_id: str | None
    label: str
    policy_group: Literal["strict-web", "relaxed-no-web", "admin-job"]
    source: Literal["ledger-db", "document", "job-runner"]
    # null = the documented figure does not state it (document rows only)
    processed: int | None
    approved: int | None
    held: int | None
    rejected: int | None
    pending: int | None
    error_count: int | None
    usage: UsageOut


class PolicyInfo(CamelModel):
    version: str | None
    decision_policy: dict[str, float] | None
    web_verification: bool
    validation_model: str | None


class LedgerRef(CamelModel):
    database: str
    checked_at: str


class CandidateCounts(CamelModel):
    """Active candidates by PoC status; ``inactive`` are candidates the PoC no longer counts (policy change, withdrawal)."""

    total: int
    active: int
    inactive: int
    allow: int
    hold: int
    reject: int


class IssueCounts(CamelModel):
    approved: int
    relations: int
    articles: int


class ReviewCounts(CamelModel):
    revision: int
    decisions: int
    allowed: int
    rejected: int
    hold_pending_review: int
    rule_candidates: int = Field(description="Candidates on the user graph through a publication rule right now")
    rule_events: int = Field(description="Events on the user graph that exist only because of a publication rule")


class PublicationState(CamelModel):
    active_version_id: str | None
    ledger_matches_active: bool
    issues_only_in_ledger: list[str]
    issues_only_in_active: list[str]


class Overview(CamelModel):
    as_of: str
    ledger: LedgerRef
    policy: PolicyInfo
    candidates: CandidateCounts
    issues: IssueCounts
    review: ReviewCounts
    projection: GraphDbStatus
    publication: PublicationState
    runs: list[PastRun]


# ---- graph versions


class GraphDbVersionState(CamelModel):
    status: Literal["reflected", "pending", "unknown"]
    pending_jobs_at_creation: int | None
    note: str | None


class GraphVersionOut(CamelModel):
    id: str
    sequence: int
    kind: Literal["seed", "ledger"]
    created_at: str
    created_by: str
    reason: str | None
    source_label: str
    policy_version: str | None
    issue_count: int
    relation_count: int
    article_count: int
    candidate_count: int | None
    synthetic: bool
    sha256: str
    bytes: int
    active: bool
    activated_at: str | None
    graph_db: GraphDbVersionState


class ActivationOut(CamelModel):
    version_id: str
    previous_version_id: str | None
    at: str
    admin_email: str
    reason: str | None
    action: Literal["publish", "activate", "seed"]


class GraphVersionList(CamelModel):
    active_version_id: str | None
    items: list[GraphVersionOut]
    activations: list[ActivationOut]


class PublishResponse(CamelModel):
    version: GraphVersionOut
    previous_active_version_id: str | None


class ActivateResponse(CamelModel):
    active_version_id: str
    previous_active_version_id: str | None
    idempotent: bool


# ---- jobs


class LedgerCounts(CamelModel):
    captured_at: str
    candidates: dict[str, int]
    issues: int
    relations: int
    pending_projections: int | None


class RunReport(CamelModel):
    run_id: str | None
    processed: int
    skipped: int
    approved: int
    held: int
    rejected: int
    pending: int
    error_count: int
    errors: list[dict[str, Any]]
    elapsed_seconds: float
    execution_mode: str | None
    usage: UsageOut


class FlushResult(CamelModel):
    completed_projection_jobs: int


class JobError(CamelModel):
    code: str
    message: str


class JobOut(CamelModel):
    id: str
    kind: Literal["flush-graph", "retry-model-errors", "ingest-run"]
    dataset: str | None
    label: str
    paid: bool
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    reason: str
    requested_by: str
    requested_at: str
    started_at: str | None
    finished_at: str | None
    duration_seconds: float | None
    exit_code: int | None
    max_model_calls: int | None
    command: list[str]
    retry_of: str | None
    cancel_requested: bool
    recovered: bool
    retryable: bool
    report: RunReport | None
    flush: FlushResult | None
    error: JobError | None
    ledger_before: LedgerCounts | None
    ledger_after: LedgerCounts | None
    log_tail: list[str] | None


class JobLock(CamelModel):
    locked: bool
    job_id: str | None
    reason: str | None


class JobLimits(CamelModel):
    default_max_model_calls: int
    max_model_calls: int


class PolicyCheck(CamelModel):
    expected: str | None
    active: str | None
    match: bool | None
    checked_at: str
    error: str | None


class SandboxInfo(CamelModel):
    ready: bool
    path: str
    problems: list[str]
    policy: PolicyCheck | None
    datasets: list[str]  # ingest-run input files available in the sandbox (zoop-expansion/datasets/*.jsonl)


class JobList(CamelModel):
    items: list[JobOut]
    active: JobOut | None
    lock: JobLock
    limits: JobLimits
    sandbox: SandboxInfo


class JobCreate(CamelModel):
    kind: Literal["flush-graph", "retry-model-errors", "ingest-run"]
    dataset: str | None = None  # ingest-run only: article JSONL file name in the sandbox
    reason: Reason
    max_model_calls: StrictInt | None = None
    confirm_paid: StrictBool | None = None  # only a JSON true confirms a billable run


class JobRetry(CamelModel):
    reason: Reason
    max_model_calls: StrictInt | None = None
    confirm_paid: StrictBool | None = None


class JobCreated(CamelModel):
    job: JobOut
    deduplicated: bool


# ---- AI usage


class LatencyOut(CamelModel):
    avg: float
    p95: float
    max: float


class FeatureUsage(CamelModel):
    model_calls: int | None
    input_tokens: int | None
    output_tokens: int | None


class FeatureCost(CamelModel):
    status: Literal["unavailable", "estimated"]
    actual: float | None
    estimated: float | None
    currency: str | None
    reason: str


class RecentError(CamelModel):
    at: str
    code: str | None
    message: str | None


class AiFeature(CamelModel):
    feature: Literal["chatbot", "news-analysis", "briefing"]
    label: str
    engine: str
    model_backed: bool
    requests: int
    succeeded: int
    failed: int
    latency_ms: LatencyOut | None
    usage: FeatureUsage
    cost: FeatureCost
    source: Literal["measured", "job-runner", "ledger-db", "document"]
    recent_errors: list[RecentError]
    note: str


class AiUsageResponse(CamelModel):
    as_of: str
    window: Literal["24h", "7d", "30d", "all"]
    features: list[AiFeature]
    past_runs: list[PastRun]
    cost: FeatureCost


# ---- briefings (admin)


class StageOut(CamelModel):
    status: Literal["pending", "running", "done", "failed", "skipped"]
    at: str | None


class StagesOut(CamelModel):
    generate: StageOut
    verify: StageOut
    publish: StageOut


class DataWindow(CamelModel):
    start: str | None
    end: str
    open_start: bool


class SuspensionOut(CamelModel):
    reason: str
    at: str
    admin_email: str


class CorrectionOut(CamelModel):
    id: int
    seq: int
    event_id: str | None
    original: str | None
    corrected: str
    reason: str
    created_at: str
    admin_email: str


class RoundOut(CamelModel):
    id: str
    date: str
    edition: Literal["morning", "evening"]
    scheduled_at: str
    data_window: DataWindow
    status: Literal["scheduled", "missing", "generating", "verifying", "published", "failed", "suspended"]
    stages: StagesOut
    failure_reason: str | None
    generated_at: str | None
    published_at: str | None
    graph_version: str | None
    review_revision: int | None
    item_count: int | None
    trigger: Literal["scheduler", "admin"] | None
    attempts: int
    delayed: bool
    correction_count: int
    suspension: SuspensionOut | None
    reprocessable: bool
    blocked_reason: str | None


class AttemptOut(CamelModel):
    n: int
    trigger: Literal["scheduler", "admin"]
    started_at: str
    finished_at: str | None
    status: str
    failure_reason: str | None
    admin_email: str | None


class RoundSchedule(CamelModel):
    morning: str
    evening: str
    timezone: str


class RoundList(CamelModel):
    items: list[RoundOut]
    schedule: RoundSchedule


class BriefingPayload(CamelModel):
    """The immutable published original of a round (what users saw before any correction)."""

    id: str
    date: str
    edition: Literal["morning", "evening"]
    scheduled_at: str
    generated_at: str
    data_window: BriefingWindow
    graph_version: str | None
    review_revision: int
    rule_revision: int | None = Field(
        default=None,
        description="Publication-rule log revision at publication; null for rounds published before it was recorded",
    )
    items: list[BriefingItem]
    references: BriefingReferences
    empty_reason: Literal["no_issues_in_window"] | None
    selected_from: int
    metadata: BriefingMetadata


class RoundDetail(RoundOut):
    published: BriefingPayload | None
    corrections: list[CorrectionOut]
    attempts_log: list[AttemptOut]


class CorrectionRequest(CamelModel):
    event_id: str | None = Field(default=None, max_length=200)
    corrected_text: str = Field(min_length=1, max_length=1000)
    reason: Reason


class SuspensionRequest(CamelModel):
    action: Literal["suspend", "resume"]
    reason: Reason

class DashboardLedger(CamelModel):
    status: Literal["connected", "unavailable"]
    error: ErrorInfo | None


class DashboardGraph(CamelModel):
    active_version_id: str | None
    activated_at: str | None
    version_count: int
    active_version: GraphVersionOut | None
    review_revision: int
    review_decisions: int
    rules: list[ReviewRuleOut]
    graph_db: GraphDbStatus | None


class DashboardCandidates(CamelModel):
    allow: int
    hold: int
    reject: int
    inactive: int
    hold_pending_review: int


class DashboardJobs(CamelModel):
    running: int
    queued: int
    failed24h: int = Field(alias="failed24h")
    active: JobOut | None
    recent: list[JobOut]


class DashboardAiFeature(CamelModel):
    feature: str
    label: str
    requests: int
    failed: int


class DashboardAi(CamelModel):
    window: str
    requests: int
    succeeded: int
    failed: int
    features: list[DashboardAiFeature]


class DashboardBriefings(CamelModel):
    latest: list[RoundOut]
    delayed_or_failed: int


class DashboardMembers(CamelModel):
    registered: int
    active_member_sessions: int
    active_guest_sessions: int
    source: Literal["bff-mock"]


class DashboardAudit(CamelModel):
    last24h: int = Field(alias="last24h")


class Dashboard(CamelModel):
    generated_at: str
    ledger: DashboardLedger
    graph: DashboardGraph
    candidates: DashboardCandidates | None
    jobs: DashboardJobs
    ai: DashboardAi
    briefings: DashboardBriefings
    members: DashboardMembers
    audit: DashboardAudit


class AuditEntry(CamelModel):
    id: int
    at: str
    actor_kind: Literal["admin", "system"]
    actor_id: str
    actor_email: str | None
    action: str
    target_type: str
    target_id: str | None
    reason: str | None
    outcome: Literal["ok", "denied", "failed"]
    detail: dict[str, Any]


class AuditPage(CamelModel):
    items: list[AuditEntry]
    next_cursor: str | None


