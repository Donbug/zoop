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


class WatchUpdate(CamelModel):
    """FS027 single toggle: whether the company should end up in the watchlist (a resend changes nothing)."""

    model_config = ConfigDict(extra="forbid")

    watched: bool



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


class MockCash(CamelModel):
    """예수금 of a mock profile. The field holding it is null when the mock does not provide it (not 0)."""

    amount: float
    currency: str


class MockPortfolioOption(CamelModel):
    id: str
    label: str
    account_id: str
    holdings_count: int


class MockPortfolioListResponse(CamelModel):
    items: list[MockPortfolioOption]
    metadata: Metadata


class MockHoldingOut(CamelModel):
    company_id: str
    name: str
    quantity: float
    avg_price: float
    avg_price_currency: str | None


class MockProfileResponse(CamelModel):
    """FS062: one project mock profile with its account id, cash and holdings (no real brokerage account)."""

    id: str
    label: str
    account_id: str
    cash: MockCash | None = Field(description="null when the mock does not provide cash; 0 is a real 0")
    as_of: str | None = Field(description="As-of time of the mock values when the mock gives one")
    holdings: list[MockHoldingOut]
    metadata: Metadata


class ConnectionInfo(CamelModel):
    id: str
    mock_portfolio_id: str
    label: str
    connected_at: str
    account_id: str | None = Field(description="null for connections stored before the account id was recorded")
    cash: MockCash | None = Field(description="null when not provided; 0 is a real 0")
    status: Literal["connected"] = "connected"


class ConnectionResponse(ConnectionInfo):
    holdings_count: int
    metadata: Metadata


class HoldingQuote(CamelModel):
    status: Literal["available"] = "available"
    price: float
    currency: str
    as_of: str | None = Field(description="Provider time of the price")
    source_name: str


class HoldingOut(CamelModel):
    company_id: str
    name: str
    ticker: str | None
    quantity: float = Field(description="Mock quantity")
    avg_price: float = Field(description="Mock average purchase price")
    avg_price_currency: str | None = Field(
        description="Currency of avgPrice; null when unknown (connections stored before it was recorded)."
    )
    quote: HoldingQuote | Unavailable = Field(description="Price read at valuation.calculatedAt")
    market_value: float | None = Field(
        description="quantity x quote.price in quote.currency; null when the price is unavailable (never 0)"
    )
    weight: float | None = Field(
        description="marketValue / total stock market value (cash excluded), 0..1; null when it cannot be "
        "calculated (see valuation.weightUnavailableCode)"
    )


WeightUnavailableCode = Literal["missing_price", "mixed_currency", "zero_total"]


class PortfolioValuation(CamelModel):
    """FS054: market values and weights computed by the BFF from prices read at one calculation time."""

    calculated_at: str = Field(description="Calculation time (when the prices were read); distinct from mockAsOf")
    currency: str | None = Field(description="Currency of totalMarketValue; null when it cannot be summed")
    total_market_value: float | None = Field(description="Sum of holding market values, cash excluded")
    weight_status: Literal["available", "unavailable"]
    weight_unavailable_code: WeightUnavailableCode | None
    weight_unavailable_reason: str | None


class PortfolioResponse(CamelModel):
    connected: bool
    connection: ConnectionInfo | None
    holdings: list[HoldingOut]
    mock_as_of: str | None = Field(description="As-of time of the mock quantities, prices and cash")
    valuation: PortfolioValuation | None = Field(description="null when no account is connected")
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
    reported_at: str | None = Field(
        default=None,
        description="KST time of the newest article behind the issue (the time it entered the round's data window); only "
        "the date (YYYY-MM-DD) when the article carries no time. null on rounds published before it was stored.",
    )


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


# ---- briefing market indicators (FS031, FS033, FS035)

IndicatorStatus = Literal["ok", "delayed", "unavailable", "failed"]
IndicatorReasonCode = Literal[
    "not_connected", "unsupported_symbol", "no_data", "auth_failed", "temporary_failure", "format_changed", "internal"
]


class IndicatorBaseline(CamelModel):
    value: float
    date: str = Field(description="KST date of the previous trading day the change is measured against")
    at: str | None = Field(description="Exact observation time when the baseline is an intraday value (the rate); null for a daily close")


class MarketIndicator(CamelModel):
    """One indicator as it stood when the round was generated. ``status`` separates what each card may claim:
    ``ok`` and ``delayed`` carry a value (``delayed`` = the newest value the source had is older than the round expects),
    ``unavailable`` = the source answered but has no value for this point in time (or is not connected),
    ``failed`` = the request itself failed (network, rate limit, unknown format)."""

    id: Literal["kospi", "kosdaq", "usdkrw"]
    label: str
    unit: Literal["pt", "KRW"]
    status: IndicatorStatus
    value: float | None
    value_kind: Literal["close", "latest"] | None = Field(description="close = the session's closing value; latest = the last observation before the cut-off")
    observed_date: str | None = Field(description="KST date of the value actually used")
    observed_at: str | None = Field(description="KST time of the value actually used; null for a daily close")
    baseline: IndicatorBaseline | None
    change: float | None = Field(description="value - baseline.value, computed by the BFF from the two observed values")
    change_rate: float | None = Field(description="change / baseline.value as a fraction (0.0123 = +1.23%)")
    source: QuoteSourceOut | None
    reason_code: IndicatorReasonCode | None
    reason: str | None


class MarketVariables(CamelModel):
    """The three market indicators stored with a published round; never changed after publication."""

    status: Literal["available"] = "available"
    reference_at: str = Field(description="The round's scheduled time (KST)")
    rate_cutoff_at: str = Field(description="Latest time an observation could have (morning 07:40, evening 18:05, KST)")
    collected_at: str = Field(description="When the BFF asked the source (UTC)")
    indicators: list[MarketIndicator]


MarketVariablesOut = Annotated[MarketVariables | Unavailable, Field(discriminator="status")]


class SinceMorningItem(CamelModel):
    event_id: str
    title: str
    event_time: str | None
    time_precision: TimePrecision
    reported_at: str | None = Field(description="As on the key issue: KST time, only the date when the article has no time, null when not stored")
    company_names: list[str] = Field(description="Names of the companies linked to the issue when its round was published (from the stored key issue)")
    change: Literal["new", "continuing", "dropped"] = Field(
        description="new = not among the morning round's key issues; continuing = in both rounds (new evidence since the morning "
        "put it in this round's window); dropped = only in the morning round"
    )
    rank: int | None = Field(description="Rank in this round; null when dropped")
    morning_rank: int | None = Field(description="Rank in the morning round; null when new")
    evidence_count: int | None = Field(description="Evidence in this round; null when dropped")
    morning_evidence_count: int | None = Field(description="Evidence in the morning round; null when new")


class SinceMorning(CamelModel):
    """Key issues of an evening round compared with the same day's published morning round, oldest first."""

    status: Literal["available"] = "available"
    morning_round_id: str
    morning_published_at: str | None
    morning_data_as_of: str
    items: list[SinceMorningItem]


SinceMorningOut = Annotated[SinceMorning | Unavailable, Field(discriminator="status")]


class BriefingResponse(CamelModel):
    id: str
    date: str
    edition: Literal["morning", "evening"]
    status: Literal["published", "not_ready", "generating", "failed", "suspended"]
    scheduled_at: str
    published_at: str | None
    generated_at: str | None = Field(description="When the BFF built the round (UTC); null until it is published")
    data_window: BriefingWindow | None
    data_as_of: str | None
    graph_version: str | None
    items: list[BriefingItem]
    market_summary: Unavailable = Field(description="No producer exists (prose summary), so always unavailable")
    market_variables: MarketVariablesOut = Field(
        description="KOSPI, KOSDAQ and USD/KRW stored with the published round; unavailable (with the reason) when the round has none"
    )
    since_morning: SinceMorningOut | None = Field(
        description="Evening rounds only: key issues compared with the same day's published morning round; null for morning rounds"
    )
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


class BriefingGraphBasis(CamelModel):
    """What a briefing's relationship graph is anchored to (FS032): the graph as it stood when the round was published.

    ``/api/graph?round=<id>`` and the node, edge, event, evidence and company reads that take the same ``round``
    answer from that state, never from the newest graph. Any status but ``available`` has no graph to read.
    """

    round_id: str
    date: str
    edition: Literal["morning", "evening"]
    status: Literal["available", "suspended", "unavailable", "not_published"]
    message: str | None = Field(description="User-facing notice for every status but available")
    reason: str | None = Field(description="Admin-written reason, only for suspended rounds")
    published_at: str | None
    data_as_of: str | None = Field(
        description="End of the round's data window (KST): the reference time of the relations and evidence shown"
    )
    graph_version: str | None = Field(description="Graph version the round was published from")
    key_issue_ids: list[str] = Field(description="The round's key issues in rank order; empty unless available")
    company_ids: list[str] = Field(description="Companies related to those issues; empty unless available")
    correction_count: int = Field(description="Corrections registered beside the published original")


class BriefingEvaluationResponse(Unavailable):
    briefing_id: str
    metadata: Metadata


# ---- chat


ChatOutcome = Literal["answered", "clarification", "guidance", "insufficient_evidence"]
ChatStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
ChatFailureKind = Literal["validation_failed", "save_failed", "result_lost", "transient", "permission_denied", "internal"]
_ISO_DATE = r"^\d{4}-\d{2}-\d{2}$"


class ChatPeriod(CamelModel):
    start: str = Field(pattern=_ISO_DATE, description="Inclusive KST calendar day (ISO date)")
    end: str = Field(pattern=_ISO_DATE)


class ChatContextRequest(CamelModel):
    """What the member had selected when asking: graph targets, optional evidence references and period."""

    context_ids: list[str] = Field(default_factory=list, max_length=20, description="Company, issue, edge or evidence ids")
    evidence_ids: list[str] = Field(default_factory=list, max_length=50, description="Narrows the evidence to these references")
    period: ChatPeriod | None = Field(default=None, description="Explicit period of the selection; the question's own period wins")


class ChatJobRequest(CamelModel):
    job_id: str = Field(
        pattern=r"^[A-Za-z0-9_-]{8,64}$",
        description="Client-made idempotency key of this question (not a request-trace id). Resending it never asks twice.",
    )
    question: str = Field(min_length=1, max_length=1000)
    context: ChatContextRequest = Field(default_factory=ChatContextRequest)


class ChatSessionResponse(CamelModel):
    id: str
    created_at: str
    jobs: int


class GraphTarget(CamelModel):
    id: str
    kind: Literal["company", "issue", "edge"]


class Citation(CamelModel):
    evidence_id: str
    quote: str
    article_id: str
    article_version: str
    start: int
    end: int
    article_title: str | None
    publisher: str | None
    published_at: str | None
    url: str | None


class ChatContextItem(CamelModel):
    id: str
    kind: Literal["company", "issue", "edge", "evidence"]
    label: str


class ChatFrozenContext(CamelModel):
    """The selection frozen when the question was first received."""

    items: list[ChatContextItem]
    evidence_count: int
    period: ChatPeriod | None


class ChatFailure(CamelModel):
    kind: ChatFailureKind
    reason: str | None
    message: str
    retry: Literal["rerun", "save_only"] | None = Field(
        description="What 'retry' would do: rerun the same job with its frozen context, or only save the kept verified result. null = not allowed."
    )


class ChatAppliedItem(CamelModel):
    id: str
    label: str


class ChatAppliedPeriod(CamelModel):
    start: str
    end: str
    basis: Literal["question", "context", "evidence"] = Field(
        description="question/context: asked for; evidence: no period asked, this is the publication span of the cited articles"
    )
    expression: str | None = Field(description="The words of the question the period came from")


class ChatApplied(CamelModel):
    """What the answer was actually built on."""

    companies: list[ChatAppliedItem]
    issues: list[ChatAppliedItem]
    period: ChatAppliedPeriod | None
    graph_version: str | None
    data_as_of: str
    question_overrode_context: bool = Field(description="The question named other targets than the selection, so the question won")


class ChatChoice(CamelModel):
    id: str
    label: str


class ChatAction(CamelModel):
    kind: Literal["set_watchlist"]
    label: str


class ChatResult(CamelModel):
    outcome: ChatOutcome
    message_id: str
    answer: str
    reason: str | None = None
    sources: list[str]
    citations: list[Citation]
    graph_targets: list[GraphTarget]
    applied: ChatApplied
    choices: list[ChatChoice] = Field(description="clarification: companies the member can pick (each becomes a new question)")
    action: ChatAction | None = Field(description="guidance: what the member can do to meet the missing condition")
    metadata: Metadata


class ChatJob(CamelModel):
    id: str
    session_id: str
    seq: int
    question: str
    status: ChatStatus
    outcome: ChatOutcome | None
    asked_at: str = Field(description="UTC time the question was first received; relative dates are read against its KST day")
    context: ChatFrozenContext
    failure: ChatFailure | None
    result: ChatResult | None = Field(description="Only a saved result; null until the job is completed")
    runs: int = Field(description="Executions started so far (a retry starts another)")
    created_at: str
    updated_at: str
    finished_at: str | None


class ChatConversation(CamelModel):
    session: ChatSessionResponse
    jobs: list[ChatJob]


class ChatCurrentResponse(CamelModel):
    conversation: ChatConversation | None
