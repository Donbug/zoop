"""Pydantic models for event collection, votes and the admin statistics/feedback/member surfaces (camelCase JSON)."""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import ConfigDict, Field, model_validator

from .briefing_rounds import parse_round_id
from .schemas import CamelModel

ID_PATTERN = r"^[A-Za-z0-9._:/\-]+$"
VIEW_ID_PATTERN = r"^[A-Za-z0-9\-]{8,40}$"
MAX_BATCH = 20
MAX_REASON = 200

EventType = Literal["screen_view", "graph_node_select", "graph_edge_select", "briefing_view", "briefing_issue_open"]
EVENT_TYPES: tuple[str, ...] = get_args(EventType)
Screen = Literal["main", "briefing"]
FeedbackFeature = Literal["chatbot_answer", "briefing_round", "briefing_issue"]
FEEDBACK_FEATURES: tuple[str, ...] = get_args(FeedbackFeature)
FEATURE_LABEL = {
    "chatbot_answer": "AI 챗봇 답변",
    "briefing_round": "브리핑 회차",
    "briefing_issue": "브리핑 핵심 이슈",
}
StatsWindow = Literal["7d", "30d", "all"]


# ---- user side: events and votes


class TelemetryEvent(CamelModel):
    """One user action. Only these fields exist; anything else (e-mail, free text) is rejected."""

    model_config = ConfigDict(extra="forbid")

    type: EventType
    screen: Screen | None = None
    target_id: str | None = Field(default=None, min_length=1, max_length=100, pattern=ID_PATTERN)
    round_id: str | None = Field(default=None, max_length=40)
    view_id: str | None = Field(default=None, pattern=VIEW_ID_PATTERN)

    @model_validator(mode="after")
    def _shape(self) -> TelemetryEvent:
        def need(*names: str) -> None:
            missing = [n for n in names if getattr(self, n) is None]
            if missing:
                raise ValueError(f"{self.type} needs {', '.join(missing)}")

        if self.type == "screen_view":
            need("screen", "view_id")
        elif self.type in ("graph_node_select", "graph_edge_select"):
            need("target_id")
        elif self.type == "briefing_view":
            need("target_id")
        else:  # briefing_issue_open
            need("target_id", "round_id")
        if self.type in ("briefing_view",) and self.target_id and parse_round_id(self.target_id) is None:
            raise ValueError("briefing_view targetId must be a briefing round id")
        if self.round_id is not None and parse_round_id(self.round_id) is None:
            raise ValueError("roundId must be a briefing round id")
        return self


class TelemetryBatch(CamelModel):
    model_config = ConfigDict(extra="forbid")

    events: list[TelemetryEvent] = Field(min_length=1, max_length=MAX_BATCH)


class TelemetryAccepted(CamelModel):
    accepted: int


class FeedbackVote(CamelModel):
    model_config = ConfigDict(extra="forbid")

    feature: FeedbackFeature
    target_id: str = Field(min_length=1, max_length=160, pattern=ID_PATTERN)
    value: Literal["up", "down"]
    reason: str | None = Field(default=None, max_length=MAX_REASON, description="Optional, only with a dislike")

    @model_validator(mode="after")
    def _reason_only_for_down(self) -> FeedbackVote:
        if self.reason is not None:
            self.reason = self.reason.strip() or None
        if self.reason is not None and self.value != "down":
            raise ValueError("reason is only accepted with a dislike")
        return self


class FeedbackItem(CamelModel):
    feature: FeedbackFeature
    target_id: str
    value: Literal["up", "down"]
    reason: str | None


class FeedbackList(CamelModel):
    items: list[FeedbackItem]


# ---- admin: statistics (requirement 74)


class StatsMetric(CamelModel):
    key: str
    group: Literal["usage", "interest", "ai"]
    label: str
    kind: Literal["count", "ratio"]
    unit: str = Field(description="Unit of the count, or of numerator and denominator")
    definition: str = Field(description="How the figure is computed, shown next to it")
    count: int | None = Field(description="kind=count")
    numerator: int | None = Field(description="kind=ratio")
    denominator: int | None = Field(description="kind=ratio")
    rate: float | None = Field(description="0..1; null for counts and for ratios below the sample threshold")
    sample_hidden: bool = Field(description="True when the denominator is below minSample, so only counts are shown")


class DailyActivity(CamelModel):
    date: str = Field(description="KST calendar day")
    active_users: int
    node_selections: int
    edge_selections: int
    briefing_views: int
    ai_questions: int


class RoundStat(CamelModel):
    round_id: str
    date: str
    edition: Literal["morning", "evening"]
    views: int
    viewers: int
    issue_opens: int
    likes: int
    dislikes: int


class StatsSummary(CamelModel):
    window: StatsWindow
    as_of: str
    since: str | None
    min_sample: int
    members_scope: str = Field(description="Which members the onboarding figure covers")
    metrics: list[StatsMetric]
    trend: list[DailyActivity]
    rounds: list[RoundStat]


class CompanyStatRow(CamelModel):
    company_id: str
    name: str
    ticker: str | None
    watchlist_members: int
    holding_members: int
    node_views: int
    edge_selections: int
    ai_questions: int


class InsightCompanyRanking(CamelModel):
    window: StatsWindow
    as_of: str
    total_companies: int
    items: list[CompanyStatRow]
    holdings_note: str


class CompanySeriesPoint(CamelModel):
    date: str
    node_views: int
    edge_selections: int
    issue_selections: int
    ai_questions: int


class InsightCompanyDetail(CamelModel):
    window: StatsWindow
    as_of: str
    company_id: str
    name: str
    ticker: str | None
    in_catalog: bool
    watchlist_members: int
    holding_members: int
    node_views: int
    edge_selections: int
    issue_selections: int
    ai_questions: int
    viewers: int
    min_sample: int
    series: list[CompanySeriesPoint]
    note: str


class OverviewFeedback(CamelModel):
    up: int
    down: int
    rate: float | None
    sample_hidden: bool


class OverviewMembers(CamelModel):
    registered: int
    active: int
    blocked: int


class InsightsOverview(CamelModel):
    window: Literal["7d"]
    as_of: str
    min_sample: int
    metrics: list[StatsMetric]
    feedback: OverviewFeedback
    members: OverviewMembers


# ---- admin: preference (requirement 75)


class FeedbackDay(CamelModel):
    date: str
    up: int
    down: int
    rate: float | None


class FeedbackFeatureStat(CamelModel):
    feature: FeedbackFeature
    label: str
    up: int
    down: int
    total: int
    rate: float | None
    sample_hidden: bool
    days: list[FeedbackDay]


class UnsupportedFeedbackFeature(CamelModel):
    feature: str
    label: str
    reason: str


class FeedbackSummary(CamelModel):
    window: StatsWindow
    as_of: str
    min_sample: int
    features: list[FeedbackFeatureStat]
    unsupported: list[UnsupportedFeedbackFeature]
    basis: str


class DislikeRow(CamelModel):
    at: str
    feature: FeedbackFeature
    feature_label: str
    target_id: str
    target_label: str
    reason: str | None
    voter: str = Field(description="Pseudonymous id")
    session_id: str | None = Field(description="Chat session of a chatbot answer, for opening its transcript")


class DislikePage(CamelModel):
    items: list[DislikeRow]
    next_cursor: str | None
    total: int


class TranscriptSummary(CamelModel):
    id: str
    user: str = Field(description="Pseudonymous id")
    user_kind: Literal["member", "guest"]
    started_at: str
    last_at: str
    messages: int
    preview: str = Field(description="First question, masked")
    up: int
    down: int


class TranscriptPage(CamelModel):
    items: list[TranscriptSummary]
    next_cursor: str | None
    total: int


class TranscriptFeedback(CamelModel):
    up: int
    down: int
    reasons: list[str]


class TranscriptMessage(CamelModel):
    id: str
    seq: int
    at: str
    question: str
    answer: str
    status: str
    reason: str | None
    context_labels: list[str]
    citation_count: int
    feedback: TranscriptFeedback


class MaskingReport(CamelModel):
    rules: list[str]
    counts: dict[str, int] = Field(description="Replacements made in this response, per kind")


class TranscriptDetail(CamelModel):
    id: str
    user: str
    user_kind: Literal["member", "guest"]
    started_at: str
    messages: list[TranscriptMessage]
    masking: MaskingReport


# ---- admin: members (requirement 78)


class MemberActivity(CamelModel):
    sessions: int
    graph_selections: int
    ai_questions: int
    briefing_views: int


class MemberRow(CamelModel):
    id: str = Field(description="Pseudonymous id")
    email_masked: str
    signup_method: str
    created_at: str
    last_active_at: str | None
    status: Literal["active", "blocked"]
    activity: MemberActivity


class MemberCounts(CamelModel):
    all: int
    active: int
    blocked: int


class MemberList(CamelModel):
    items: list[MemberRow]
    next_cursor: str | None
    counts: MemberCounts


class MemberAction(CamelModel):
    at: str
    action: Literal["member.block", "member.unblock"]
    reason: str | None
    admin_email: str | None


class MemberDetail(CamelModel):
    member: MemberRow
    onboarding_completed: bool
    tutorial_completed: bool
    watchlist_count: int
    holding_count: int
    account_connected: bool
    feedback_up: int
    feedback_down: int
    history: list[MemberAction]


class MemberStatusResult(CamelModel):
    changed: bool = Field(description="False when the member already had that status (the call is idempotent)")
    detail: MemberDetail
