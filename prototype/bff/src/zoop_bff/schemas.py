"""Pydantic request/response models. JSON is camelCase; Python attributes are snake_case."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

TimePrecision = Literal["year", "month", "day", "datetime", "unknown"]
DatasetKind = Literal["approved-live", "approved-snapshot", "synthetic-preview"]
GraphRelationType = Literal["INVOLVES", "STRUCTURALLY_RELATED_TO", "FOLLOWS", "SHARES_ISSUE"]


class CamelModel(BaseModel):
    # Every response field is always serialized, so the output schema must list it as required.
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        json_schema_serialization_defaults_required=True,
    )


class Metadata(CamelModel):
    dataset_kind: DatasetKind
    source: str
    as_of: str
    source_mode: Literal["snapshot", "mock"]
    synthetic: bool
    generated_by: str | None = Field(
        default=None, description="Set when the BFF (not the PoC) produced the content."
    )
    graph_version: str | None = Field(
        default=None,
        description="Id of the active published graph version the data came from (null for BFF mock content).",
    )


class Unavailable(CamelModel):
    status: Literal["unavailable"] = "unavailable"
    reason: str


# ---- errors


class ErrorBody(CamelModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(CamelModel):
    error: ErrorBody


# ---- health


class SourceHealth(CamelModel):
    mode: Literal["snapshot"]
    label: str
    connected: bool
    error: ErrorBody | None = None


class HealthCounts(CamelModel):
    issues: int
    companies: int
    approved_edges: int
    derived_edges: int
    evidence: int


class HealthResponse(CamelModel):
    status: Literal["ok", "degraded", "unavailable"]
    source: SourceHealth
    dataset_kind: DatasetKind | None = None
    as_of: str | None = None
    graph_version: str | None = None
    counts: HealthCounts | None = None
    source_errors: list[str] = []
    warnings: list[str] = []


# ---- auth / settings / portfolio (BFF mock)


class LoginRequest(CamelModel):
    # Defaults let the server answer a missing field with a per-field message (422 login_invalid).
    email: str = ""
    password: str = ""


class SignupRequest(CamelModel):
    """Every field is validated by the server (422 ``signup_invalid`` with ``details.fields``)."""

    email: str = ""
    password: str = ""
    display_name: str = ""
    agreements: list[str] = Field(default=[], description="Ids of the terms the user agreed to.")


class TermOut(CamelModel):
    id: str
    title: str
    required: bool
    body_available: bool = Field(description="False: the terms text is not written yet.")


class TermsResponse(CamelModel):
    items: list[TermOut]


class SocialProviderOut(CamelModel):
    id: str
    label: str
    development: bool = Field(description="True for the development-only mock provider.")


class SocialProvidersResponse(CamelModel):
    items: list[SocialProviderOut]


class MockIdpConsent(CamelModel):
    state: str
    redirect_uri: str
    email: str = ""
    display_name: str = ""


class MockIdpRedirect(CamelModel):
    redirect_to: str


class TutorialUpdate(CamelModel):
    completed: bool


class UserInfo(CamelModel):
    id: str
    email: str
    display_name: str


class SetupState(CamelModel):
    """Guests: ``completed`` is always false (they have no settings); ``tutorialCompleted`` is kept on the
    guest session only."""

    completed: bool
    tutorial_completed: bool


class SessionResponse(CamelModel):
    authenticated: bool
    kind: Literal["anonymous", "guest", "member"]
    user: UserInfo | None = None
    setup: SetupState | None = None
    metadata: Metadata


class SettingsUpdate(CamelModel):
    """Unset fields keep their stored value; ``version`` must equal the stored version unless the request
    changes nothing (a resent request is answered with the stored settings)."""

    version: int
    mode: Literal["assets", "watchlist"] | None = None
    watchlist_ids: list[str] | None = None
    tutorial_completed: bool | None = None
    completed: bool | None = None
    investor: bool | None = Field(default=None, description="Answer to 'do you invest in stocks now?'")


class SettingsResponse(CamelModel):
    mode: Literal["assets", "watchlist"]
    watchlist_ids: list[str]
    tutorial_completed: bool
    completed: bool
    investor: bool | None = Field(description="null until the member answers the onboarding question.")
    version: int
    metadata: Metadata


class RecommendedCompany(CamelModel):
    company: CompanySummary
    reason: str


class RecommendationResponse(CamelModel):
    """Ranked by approved issue count; industry/theme recommendations do not exist (no producer)."""

    basis: Literal["approved_issue_count"]
    items: list[RecommendedCompany]
    metadata: Metadata


class PortfolioConnectRequest(CamelModel):
    mock_portfolio_id: str


class MockPortfolioOption(CamelModel):
    id: str
    label: str
    holdings_count: int


class MockPortfolioListResponse(CamelModel):
    items: list[MockPortfolioOption]
    metadata: Metadata


class ConnectionInfo(CamelModel):
    id: str
    mock_portfolio_id: str
    label: str
    connected_at: str
    status: Literal["connected"] = "connected"


class ConnectionResponse(ConnectionInfo):
    holdings_count: int
    metadata: Metadata


class HoldingOut(CamelModel):
    company_id: str
    name: str
    ticker: str | None
    quantity: float
    avg_price: float
    avg_price_currency: str | None = Field(
        description="Currency of avgPrice; null when unknown (connections stored before it was recorded)."
    )
    cost_basis: float
    weight: float = Field(description="cost_basis / total cost basis; NOT market-value weight")
    market_value: Unavailable


class PortfolioResponse(CamelModel):
    connected: bool
    connection: ConnectionInfo | None
    holdings: list[HoldingOut]
    weight_basis: Literal["cost"] = "cost"
    valuation: Unavailable
    as_of: str | None
    metadata: Metadata


# ---- graph


class GraphNode(CamelModel):
    id: str
    kind: Literal["company", "issue"]
    label: str
    is_focus: bool = False
    holding: bool = False
    watch: bool = False
    brand_color: str | None = Field(
        default=None, description="Company brand color `#RRGGBB` from the catalog; null for issues or when unset."
    )
    logo_url: str | None = Field(
        default=None, description="Same-origin path of the company logo (`/logos/<file>`); null for issues or when unset."
    )
    event_time: str | None = None
    time_precision: TimePrecision | None = None
    action: str | None = None
    target: str | None = None
    evidence_count: int | None = Field(
        default=None,
        description="Issue nodes: number of evidence ids of the issue (length of `GET /api/events/{id}` evidenceIds); null for companies.",
    )


class GraphEdge(CamelModel):
    id: str
    source: str
    target: str
    relation_type: GraphRelationType
    role: str | None = None
    summary: str = Field(description="Short Korean noun phrase for the edge label, derived from approved data only.")
    assertion_status: str | None = None
    derived: bool
    via: list[str] = Field(default_factory=list, description="Shared issue ids; derived edges only")
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="Evidence ids of the approved relations behind the edge (same as `GET /api/graph/edges/{id}` evidenceIds); empty for derived edges.",
    )


class GraphMetadata(Metadata):
    mode: Literal["all", "personal"]
    truncated: bool
    empty_reason: str | None = None
    focus_company_ids: list[str]
    depth: int | None = Field(description="Requested hop count; null when omitted (whole connected component).")
    limit: int


class GraphResponse(CamelModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    metadata: GraphMetadata


class EndpointRef(CamelModel):
    id: str
    kind: Literal["company", "issue"]
    label: str


class BasisOut(CamelModel):
    edge_id: str
    relation_type: str
    source_url: str | None
    verified_at: str | None
    valid_from: str | None
    valid_until: str | None
    countries: list[str]


class Verification(CamelModel):
    status: Literal["ALLOW", "not_applicable"]
    note: str | None = None


class ViaIssue(CamelModel):
    id: str
    title: str
    event_time: str | None
    time_precision: TimePrecision
    evidence_ids: list[str]


class EdgeDetail(CamelModel):
    id: str
    relation_type: GraphRelationType
    derived: bool
    directed: bool
    source: EndpointRef
    target: EndpointRef
    role: str | None
    summary: str = Field(description="Same short Korean noun phrase as the graph edge label.")
    roles: list[str]
    assertion_status: str | None
    evidence_ids: list[str]
    basis: list[BasisOut]
    relation_ids: list[str]
    verification: Verification
    via: list[ViaIssue]
    explanation: str | None
    metadata: Metadata


# ---- companies


class CompanySummary(CamelModel):
    id: str
    name: str
    ticker: str | None
    aliases: list[str]
    sector: str | None
    brand_color: str | None = Field(description="Company brand color `#RRGGBB`; null when the catalog has none.")
    logo_url: str | None = Field(description="Same-origin logo path (`/logos/<file>`); null when the catalog has none.")
    issue_count: int


class CompanyListResponse(CamelModel):
    items: list[CompanySummary]
    metadata: Metadata


class CompanyIssueRef(CamelModel):
    issue_id: str
    title: str
    event_time: str | None
    time_precision: TimePrecision
    role: str | None
    assertion_status: str | None
    evidence_count: int
    basis: list[BasisOut] = []


class CompanyDetail(CamelModel):
    id: str
    name: str
    ticker: str | None
    aliases: list[str]
    sector: str | None
    brand_color: str | None = Field(description="Company brand color `#RRGGBB`; null when the catalog has none.")
    logo_url: str | None = Field(description="Same-origin logo path (`/logos/<file>`); null when the catalog has none.")
    direct_issues: list[CompanyIssueRef]
    structural_issues: list[CompanyIssueRef]
    summary: Unavailable
    holding: bool | None = Field(description="null unless a member session is present")
    watch: bool | None = Field(description="null unless a member session is present")
    metadata: Metadata


QuoteReasonCode = Literal[
    "not_connected", "unsupported_symbol", "no_data", "auth_failed", "temporary_failure", "format_changed"
]


class QuoteSourceOut(CamelModel):
    provider: Literal["toss", "yahoo", "naver"]
    name: str
    official: bool = Field(description="false for the unofficial keyless public endpoint")
    delay_note: str | None = Field(description="Set when quotes from this source may be delayed.")
    symbol: str = Field(description="Provider symbol the values were fetched with (e.g. `005930.KS`).")
    url: str | None = Field(description="Provider page for the symbol to cross-check, when known.")


class QuoteValues(CamelModel):
    currency: str
    price: float
    as_of: str | None = Field(description="Provider time of the price (ISO 8601 with offset); null when not given.")
    previous_close: float | None
    change: float | None = Field(description="price - previousClose")
    change_rate: float | None = Field(description="(price - previousClose) / previousClose, a fraction")
    day_high: float | None
    day_low: float | None
    volume: float | None
    fifty_two_week_high: float | None
    fifty_two_week_low: float | None
    market_cap: float | None = Field(description="Only when computable from the provider (price x sharesOutstanding).")
    shares_outstanding: float | None
    derived: list[str] = Field(
        description="camelCase fields the BFF computed from provider data rather than received as-is."
    )


class CompanyQuote(CamelModel):
    status: Literal["available"] = "available"
    company_id: str
    source: QuoteSourceOut
    quote: QuoteValues


class CompanyQuoteUnavailable(CamelModel):
    status: Literal["unavailable"] = "unavailable"
    company_id: str
    reason_code: QuoteReasonCode = Field(
        description="not_connected: provider off or keys missing; unsupported_symbol; no_data: provider has nothing; "
        "auth_failed; temporary_failure: timeout, network, 429 or 5xx (retry later)."
    )
    reason: str


QuoteResponse = Annotated[CompanyQuote | CompanyQuoteUnavailable, Field(discriminator="status")]


class PricePoint(CamelModel):
    time: str = Field(description="Bar time (ISO 8601 with the exchange offset).")
    open: float
    high: float
    low: float
    close: float
    volume: float | None


class PriceSeries(CamelModel):
    status: Literal["available"] = "available"
    company_id: str
    period: Literal["1d", "1m", "1y"]
    source: QuoteSourceOut
    currency: str
    interval: str = Field(description="Bar size: `1m`/`5m` for the latest session (1d), `1d` otherwise.")
    points: list[PricePoint] = Field(description="Oldest first.")


class PriceSeriesUnavailable(CamelModel):
    status: Literal["unavailable"] = "unavailable"
    company_id: str
    period: Literal["1d", "1m", "1y"]
    reason_code: QuoteReasonCode
    reason: str


PriceResponse = Annotated[PriceSeries | PriceSeriesUnavailable, Field(discriminator="status")]


class MetricOut(CamelModel):
    code: Literal["marketValue", "per", "eps", "pbr", "bps", "dividendYieldRatio", "dividend", "foreignRate"]
    label: str
    value: str = Field(description="As the source formats it (e.g. `1,609조 1,882억`, `12.35배`); never computed here.")
    basis: str | None = Field(description="The source's reference period for this value (e.g. `2026.06.`), when given.")


class CompanyMetrics(CamelModel):
    status: Literal["available"] = "available"
    company_id: str
    source: QuoteSourceOut
    as_of: str | None = Field(description="Source time of the page the values came from; null when not given.")
    items: list[MetricOut]


class CompanyMetricsUnavailable(CamelModel):
    status: Literal["unavailable"] = "unavailable"
    company_id: str
    reason_code: QuoteReasonCode
    reason: str


MetricsResponse = Annotated[CompanyMetrics | CompanyMetricsUnavailable, Field(discriminator="status")]


class DocumentEventRef(CamelModel):
    event_id: str
    title: str
    relation_type: Literal["REPORTS", "PROVIDES_BACKGROUND"] | None


class DocumentQuote(CamelModel):
    evidence_id: str
    quote: str
    quote_verified: bool | None


class CompanyDocument(CamelModel):
    id: str = Field(description="Article id")
    title: str | None
    publisher: str | None
    url: str | None = Field(description="Original article link; null when the source gives none")
    published_at: str | None
    synthetic: bool
    events: list[DocumentEventRef] = Field(description="This company's approved events the article supports")
    quotes: list[DocumentQuote] = Field(description="Stored evidence quotes from this article for those events")


class CompanyDocumentsResponse(CamelModel):
    items: list[CompanyDocument] = Field(description="Distinct articles, newest publication first; undated last")
    metadata: Metadata


# ---- events


class EventSummary(CamelModel):
    id: str
    title: str
    action: str | None
    target: str | None
    event_time: str | None
    time_precision: TimePrecision
    period: str | None
    company_ids: list[str]
    article_count: int
    reported_at: str | None = Field(
        description="Latest publication time among the event's articles; never used as the event time"
    )


class EventListMetadata(Metadata):
    total: int
    excluded_unknown_time: int = Field(
        description="Events without an approved event time left out of `items` by from/to"
    )
    latest_event_time: str | None = Field(
        default=None, description="Newest approved event time in the company/all scope, ignoring from/to"
    )
    latest_reported_at: str | None = Field(
        default=None, description="Newest article publication in the same scope, ignoring from/to"
    )


class EventListResponse(CamelModel):
    items: list[EventSummary]
    unknown_time_items: list[EventSummary] = Field(
        default_factory=list,
        description="With from/to: events without an approved event time whose reportedAt (KST date) falls "
        "in the range, newest report first. Without from/to they are in `items` and this is empty.",
    )
    metadata: EventListMetadata


class ParticipantOut(CamelModel):
    company_id: str | None
    name: str
    role: str | None
    role_unconfirmed: bool


class MentionOut(CamelModel):
    mention_id: str
    article_id: str
    title: str
    action: str
    target: str | None
    event_time: str | None
    time_precision: TimePrecision
    period: str | None
    assertion_status: str
    participants: list[ParticipantOut]
    evidence_ids: list[str]
    background: bool


class ArticleOut(CamelModel):
    id: str
    title: str | None
    publisher: str | None
    url: str | None
    published_at: str | None
    synthetic: bool
    relation_type: Literal["REPORTS", "PROVIDES_BACKGROUND"] | None


class RelationOut(CamelModel):
    id: str
    edge_id: str | None = Field(description="Graph edge id; null for article-to-issue relations")
    relation_type: str
    source: str
    target: str
    role: str | None
    role_unconfirmed: bool
    assertion_status: str | None
    evidence_ids: list[str]


class CompanyLink(CamelModel):
    id: str
    name: str
    role: str | None
    role_unconfirmed: bool = Field(description="The role text was left out because the PoC could not confirm it (rule R1)")
    relation_type: Literal["INVOLVES", "STRUCTURALLY_RELATED_TO"]


class SourceSupportOut(CamelModel):
    article_count: int
    known_lineage_count: int | None
    unknown_lineage_articles: list[str]
    independent_source_count: int | None
    duplicate_groups: list[list[str]]


class FieldOutcomeOut(CamelModel):
    field: str
    decision: str
    reason: str | None


class FieldDecisionOut(CamelModel):
    candidate_id: str | None
    mention_id: str | None
    outcomes: list[FieldOutcomeOut]


class FollowRef(CamelModel):
    id: str
    title: str
    event_time: str | None
    time_precision: TimePrecision


class Follows(CamelModel):
    previous: list[FollowRef]
    next: list[FollowRef]


class ApprovalOut(CamelModel):
    source: Literal["admin-review", "review-rule"]
    label: str = Field(description="Shown instead of PoC-validated provenance: '관리자 승인' or '자동 검수 규칙'")
    scope: str
    rule_id: str | None = Field(
        description="Publication rule that put content on the graph (e.g. 'R1@2'); also set when an admin approval and a rule meet in one event"
    )


class EventDetail(CamelModel):
    id: str
    title: str
    event_time: str | None
    time_precision: TimePrecision
    period: str | None
    mentions: list[MentionOut]
    articles: list[ArticleOut]
    relations: list[RelationOut]
    companies: list[CompanyLink]
    source_support: SourceSupportOut
    field_decisions: list[FieldDecisionOut]
    evidence_ids: list[str]
    follows: Follows
    approval: ApprovalOut | None = Field(
        description="Set only when an admin review (not the PoC validation alone) put content on the graph"
    )
    summary: Unavailable
    metadata: Metadata


class EvidenceArticle(CamelModel):
    title: str | None
    publisher: str | None
    url: str | None
    published_at: str | None
    synthetic: bool


class EvidenceResponse(CamelModel):
    id: str
    quote: str
    start: int
    end: int
    article_id: str
    article_version: str
    article: EvidenceArticle | None
    quote_verified: bool | None = Field(
        description="PoC Evidence.matches() against the article body; null when no body is available"
    )
    event_ids: list[str]
    metadata: Metadata


# ---- briefings


class BriefingItem(CamelModel):
    event_id: str
    title: str
    event_time: str | None
    time_precision: TimePrecision
    companies: list[CompanyLink]
    evidence_count: int
    source_support: SourceSupportOut
    matched_company_ids: list[str] = Field(
        description="Always empty: the published briefing is the same for everyone (no personalization)"
    )
    rank: int = Field(description="1-based position inside the round")
    reason: str = Field(description="Rule-based selection reason (no importance or direction claim)")
    evidence_ids: list[str]
    summary: Unavailable


class BriefingSchedule(CamelModel):
    morning: str
    evening: str
    confirmed: bool


class BriefingSelection(CamelModel):
    basis: Literal["market"]
    reason: str | None = None


class BriefingMetadata(Metadata):
    schedule: BriefingSchedule
    selection: BriefingSelection


class BriefingWindow(CamelModel):
    start: str | None = Field(description="null = the first round of the service (no lower bound)")
    end: str = Field(description="Data cut-off = the round's scheduled time (KST)")
    open_start: bool


class BriefingNotice(CamelModel):
    kind: Literal["not_ready", "failed", "suspended"]
    message: str
    reason: str | None = Field(description="Admin-written reason, only for suspended rounds")
    at: str | None


class BriefingCorrection(CamelModel):
    id: int
    event_id: str | None
    original: str | None = Field(description="The published text of the corrected item, kept as published")
    corrected: str
    reason: str
    created_at: str


class BriefingReferences(CamelModel):
    event_ids: list[str]
    evidence_ids: list[str]
    company_ids: list[str]


class BriefingResponse(CamelModel):
    id: str
    date: str
    edition: Literal["morning", "evening"]
    status: Literal["published", "not_ready", "generating", "failed", "suspended"]
    scheduled_at: str
    published_at: str | None
    data_window: BriefingWindow | None
    data_as_of: str | None
    graph_version: str | None
    items: list[BriefingItem]
    market_summary: Unavailable
    market_variables: Unavailable
    empty_reason: Literal["no_issues_in_window"] | None
    corrections: list[BriefingCorrection]
    notice: BriefingNotice | None
    references: BriefingReferences
    metadata: BriefingMetadata


class BriefingRoundRef(CamelModel):
    id: str
    date: str
    edition: Literal["morning", "evening"]
    status: Literal["published", "suspended"]
    published_at: str | None


class BriefingRoundsResponse(CamelModel):
    items: list[BriefingRoundRef]


class BriefingEvaluationResponse(Unavailable):
    briefing_id: str
    metadata: Metadata


# ---- chat


class ChatSessionRequest(CamelModel):
    context_ids: list[str] = Field(default_factory=list, max_length=20)


class ChatSessionResponse(CamelModel):
    id: str
    context_ids: list[str]
    created_at: str
    metadata: Metadata


class ChatMessageRequest(CamelModel):
    question: str = Field(min_length=1, max_length=1000)
    context_ids: list[str] | None = Field(default=None, max_length=20)


class GraphTarget(CamelModel):
    id: str
    kind: Literal["company", "issue", "edge"]


class Citation(CamelModel):
    evidence_id: str
    quote: str
    article_title: str | None
    publisher: str | None
    url: str | None


class ChatMessageResponse(CamelModel):
    session_id: str
    message_id: str
    question: str
    status: Literal["answered", "insufficient_evidence"]
    answer: str
    reason: str | None = None
    context_ids: list[str]
    sources: list[str]
    citations: list[Citation]
    graph_targets: list[GraphTarget]
    metadata: Metadata
