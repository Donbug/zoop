from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from ..dataset import ARTICLE_LINKS, COMPANY_LINKS, CompanyRec, Dataset, IssueRec, edge_id, sort_recent, time_precision
from ..deps import OptionalPrincipal, State
from ..errors import ApiError, not_found
from ..market_data import Source
from ..graph import edge_detail, select_graph
from ..summaries import role_display
from ..schemas import (
    ApprovalOut,
    ArticleOut,
    CompanyDetail,
    CompanyQuote,
    CompanyQuoteUnavailable,
    CompanyDocument,
    CompanyDocumentsResponse,
    CompanyIssueRef,
    CompanyListResponse,
    CompanySummary,
    DocumentEventRef,
    DocumentQuote,
    EdgeDetail,
    EventDetail,
    EventListMetadata,
    EventListResponse,
    EvidenceArticle,
    EvidenceResponse,
    FieldDecisionOut,
    FieldOutcomeOut,
    Follows,
    GraphMetadata,
    GraphResponse,
    MentionOut,
    ParticipantOut,
    PricePoint,
    PriceResponse,
    PriceSeries,
    PriceSeriesUnavailable,
    QuoteResponse,
    QuoteSourceOut,
    QuoteValues,
    CompanyMetrics,
    CompanyMetricsUnavailable,
    MetricOut,
    MetricsResponse,
    RelationOut,
)
from ..views import (
    SUMMARY_UNAVAILABLE,
    basis_out,
    company_links,
    event_summary,
    follow_ref,
    meta,
    source_support_out,
    unavailable,
    user_holding_ids,
)
from . import ERROR_RESPONSES

router = APIRouter(prefix="/api", tags=["market"], responses=ERROR_RESPONSES)

RoundQuery = Annotated[
    str | None,
    Query(
        alias="round",
        description="Briefing round id (e.g. brf-2026-09-17-morning): read the graph as it stood when that round was "
        "published. Never falls back to the newest graph; see GET /api/briefings/{id}/graph.",
    ),
]


def _require_company(ds: Dataset, company_id: str) -> None:
    if company_id not in ds.companies:
        raise not_found("company_not_found", "기업을 찾을 수 없습니다.")


# --------------------------------------------------------------------------- graph


@router.get("/graph", response_model=GraphResponse)
def get_graph(
    state: State,
    principal: OptionalPrincipal,
    mode: Literal["all", "personal"] = "all",
    company_id: str | None = Query(default=None, alias="companyId"),
    depth: int | None = Query(
        default=None, ge=1, le=6, description="Hops from the focus; omit for the whole connected component."
    ),
    limit: int = Query(default=500, ge=1, le=1000, description="Maximum node count; newest events first."),
    round_id: RoundQuery = None,
) -> GraphResponse:
    """Approved issue-company graph. ``companyId`` re-centres either mode on that company.

    ``all`` is the public market-wide graph. ``personal`` needs a member session (guest 403,
    none 401) and centres on the session user's holdings plus watchlist (watchlist only when
    nothing is held; ``emptyReason: no_personal_stocks`` when both are empty). Company nodes carry
    ``holding``/``watch`` for members in both modes. Without ``depth`` an ego graph holds the whole
    connected component of its focus, up to ``limit`` nodes (``metadata.truncated``).
    """
    user = principal.user if principal else None
    if mode == "personal":
        if principal is None:
            raise ApiError(401, "unauthenticated", "로그인이 필요합니다.")
        if user is None:
            raise ApiError(403, "guest_forbidden", "비회원은 개인화 그래프를 사용할 수 없습니다. 전체 그래프만 볼 수 있습니다.")
    if round_id is not None and mode == "personal":
        raise ApiError(422, "round_all_only", "회차 기준 그래프는 전체 지도만 볼 수 있습니다.")
    ds = state.dataset(round_id)
    if company_id is not None:
        _require_company(ds, company_id)
    holding_ids = user_holding_ids(ds, user) if user else []
    watch_ids = list(user.watchlist_ids) if user else []

    focus: list[str] | None
    empty_reason: str | None = None
    if mode == "personal":
        personal_ids = list(dict.fromkeys([*holding_ids, *watch_ids]))
        focus = [company_id] if company_id else personal_ids
        if not personal_ids:
            empty_reason = "no_personal_stocks"
    else:
        focus = [company_id] if company_id else None

    base = meta(ds).model_dump()
    if empty_reason:
        selection_nodes, selection_edges, truncated = [], [], False
        focus_ids: list[str] = []
    else:
        selection = select_graph(
            ds, focus=focus, depth=depth, limit=limit, holding_ids=holding_ids, watch_ids=watch_ids
        )
        selection_nodes, selection_edges, truncated = selection.nodes, selection.edges, selection.truncated
        focus_ids = list(focus or [])
        if not selection_edges:
            empty_reason = "no_approved_issues" if focus is None else "no_related_issues"
    return GraphResponse(
        nodes=selection_nodes,
        edges=selection_edges,
        metadata=GraphMetadata(
            **base,
            mode=mode,
            truncated=truncated,
            empty_reason=empty_reason,
            focus_company_ids=focus_ids,
            depth=depth,
            limit=limit,
        ),
    )


@router.get("/graph/edges/{id}", response_model=EdgeDetail)
def get_edge(edge_id: Annotated[str, Path(alias="id")], state: State, round_id: RoundQuery = None) -> EdgeDetail:
    return edge_detail(state.dataset(round_id), edge_id)


# --------------------------------------------------------------------------- companies


def _search_rank(company: CompanyRec, needle: str) -> int | None:
    """FS011-01 order: 0 code exact (ticker or id, with or without its market prefix), 1 name exact
    (name or alias), 2 partial match on any of them; ``None`` when nothing matches."""
    codes = {company.id.lower(), company.id.rsplit(":", 1)[-1].lower(), (company.ticker or "").lower()} - {""}
    names = {company.name.lower(), *(a.lower() for a in company.aliases)}
    if needle in codes:
        return 0
    if needle in names:
        return 1
    if any(needle in text for text in (*codes, *names)):
        return 2
    return None


@router.get("/companies", response_model=CompanyListResponse)
def search_companies(
    state: State,
    q: str | None = Query(default=None, description="Name, alias, ticker or id; empty lists every company by name"),
) -> CompanyListResponse:
    """Supported companies (FS011-01). With ``q`` (trimmed, case-insensitive): exact code matches first, then
    exact name matches, then partial matches; ties by name, then id. No business cap on the number of results."""
    ds = state.provider.get()
    needle = (q or "").strip().lower()
    ranked = [(rank, c) for c in ds.companies.values() if (rank := _search_rank(c, needle) if needle else 0) is not None]
    ranked.sort(key=lambda pair: (pair[0], pair[1].name, pair[1].id))
    matches = [c for _, c in ranked]
    return CompanyListResponse(
        items=[
            CompanySummary(
                id=c.id,
                name=c.name,
                ticker=c.ticker,
                aliases=list(c.aliases),
                sector=c.sector,
                brand_color=c.brand_color,
                logo_url=c.logo_url,
                issue_count=len(ds.issues_of_company(c.id)),
            )
            for c in matches
        ],
        metadata=meta(ds),
    )


def _issue_refs(ds: Dataset, company_id: str, relation_type: str) -> list[CompanyIssueRef]:
    edges = {e.source: e for e in ds.company_edges.get(company_id, ()) if e.relation_type == relation_type}
    return [
        CompanyIssueRef(
            issue_id=issue.id,
            title=issue.title,
            event_time=issue.event_time,
            time_precision=issue.time_precision,
            role=role_display(edges[issue.id].role),
            assertion_status=edges[issue.id].assertion_status,
            evidence_count=len(edges[issue.id].evidence_ids),
            basis=[basis_out(b) for b in edges[issue.id].basis],
        )
        for issue in sort_recent([ds.issues[i] for i in edges])
    ]


@router.get("/companies/{id}", response_model=CompanyDetail)
def get_company(
    company_id: Annotated[str, Path(alias="id")], state: State, principal: OptionalPrincipal, round_id: RoundQuery = None
) -> CompanyDetail:
    ds = state.dataset(round_id)
    _require_company(ds, company_id)
    company = ds.companies[company_id]
    user = principal.user if principal else None
    return CompanyDetail(
        id=company.id,
        name=company.name,
        ticker=company.ticker,
        aliases=list(company.aliases),
        sector=company.sector,
        brand_color=company.brand_color,
        logo_url=company.logo_url,
        direct_issues=_issue_refs(ds, company_id, "INVOLVES"),
        structural_issues=_issue_refs(ds, company_id, "STRUCTURALLY_RELATED_TO"),
        summary=unavailable(SUMMARY_UNAVAILABLE),
        holding=company_id in user_holding_ids(ds, user) if user else None,
        watch=company_id in user.watchlist_ids if user else None,
        metadata=meta(ds),
    )


@router.get("/companies/{id}/quote", response_model=QuoteResponse)
def get_quote(company_id: Annotated[str, Path(alias="id")], state: State) -> CompanyQuote | CompanyQuoteUnavailable:
    """Current price and indicators from the configured quote provider, with source and as-of time.

    Separate from ``/companies/{id}`` so a slow or failing quote never blocks the company overview.
    Missing values stay null; ``quote.derived`` lists values the BFF computed (e.g. market cap)."""
    _require_company(state.provider.get(), company_id)
    result = state.market.quote(company_id)
    if result.quote is None or result.source is None:
        return CompanyQuoteUnavailable(company_id=company_id, reason_code=result.code, reason=result.reason)
    q = result.quote
    return CompanyQuote(
        company_id=company_id,
        source=_source_out(result.source),
        quote=QuoteValues(
            currency=q.currency,
            price=q.price,
            as_of=q.as_of.isoformat() if q.as_of else None,
            previous_close=q.previous_close,
            change=q.change,
            change_rate=q.change_rate,
            day_high=q.day_high,
            day_low=q.day_low,
            volume=q.volume,
            fifty_two_week_high=q.fifty_two_week_high,
            fifty_two_week_low=q.fifty_two_week_low,
            market_cap=q.market_cap,
            shares_outstanding=q.shares_outstanding,
            derived=list(q.derived),
        ),
    )


@router.get("/companies/{id}/metrics", response_model=MetricsResponse)
def get_metrics(company_id: Annotated[str, Path(alias="id")], state: State) -> CompanyMetrics | CompanyMetricsUnavailable:
    """General indicators (시가총액·PER·PBR·EPS·배당·외국인 소진율) from a separate public source, passed through as
    given with each value's reference period. Independent of the price provider: a failure here leaves quotes alone."""
    _require_company(state.provider.get(), company_id)
    result = state.market.metrics(company_id)
    if result.metrics is None or result.source is None:
        return CompanyMetricsUnavailable(company_id=company_id, reason_code=result.code, reason=result.reason)
    return CompanyMetrics(
        company_id=company_id,
        source=_source_out(result.source),
        as_of=result.metrics.as_of.isoformat() if result.metrics.as_of else None,
        items=[MetricOut(code=m.code, label=m.label, value=m.value, basis=m.basis) for m in result.metrics.items],
    )


# --------------------------------------------------------------------------- common detail range (FS040)

_BOUND_HELP = "KST date (YYYY-MM-DD, the whole day) or date-time (an offset-less value is read as KST)"
RangeFrom = Annotated[str | None, Query(alias="from", description=f"Range start, inclusive: {_BOUND_HELP}")]
RangeTo = Annotated[str | None, Query(description=f"Range end, inclusive: {_BOUND_HELP}")]


class _Range:
    """The range the company detail screen asks the chart and the timeline for: one KST end instant (the query
    time) and a calendar start. A bound given as a bare date covers that whole KST day."""

    def __init__(self, start: datetime | None, end: datetime | None):
        self.start = start
        self.end = end

    @classmethod
    def parse(cls, start: str | None, end: str | None) -> _Range:
        window = cls(cls._bound(start, "from", end_of_day=False), cls._bound(end, "to", end_of_day=True))
        if window.start and window.end and window.start > window.end:
            raise ApiError(422, "invalid_range", "from은 to보다 늦을 수 없습니다.")
        return window

    @staticmethod
    def _bound(value: str | None, name: str, *, end_of_day: bool) -> datetime | None:
        if not value:
            return None
        try:
            if len(value) == 10:
                day = date.fromisoformat(value)
                return datetime.combine(day, time.max if end_of_day else time.min, tzinfo=_KST)
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ApiError(422, "invalid_range", f"{name}는 날짜 또는 날짜·시각이어야 합니다.") from None
        return moment if moment.tzinfo else moment.replace(tzinfo=_KST)

    @property
    def bounded(self) -> bool:
        return self.start is not None or self.end is not None

    def contains(self, moment: date | datetime, *, day_only: bool = False) -> bool:
        """``day_only`` compares KST days, for a value whose time is unknown (an event day, a daily price bar)."""
        if day_only:
            day = moment.astimezone(_KST).date() if isinstance(moment, datetime) else moment
            return (not self.start or day >= self.start.astimezone(_KST).date()) and self.not_after(day)
        return (not self.start or moment >= self.start) and self.not_after(moment)  # type: ignore[operator]

    def not_after(self, moment: date | datetime) -> bool:
        if self.end is None:
            return True
        if isinstance(moment, datetime):
            return moment <= self.end
        return moment <= self.end.astimezone(_KST).date()



@router.get("/companies/{id}/prices", response_model=PriceResponse)
def get_prices(
    company_id: Annotated[str, Path(alias="id")],
    state: State,
    period: Literal["1d", "1m", "1y"] = "1m",
    from_: RangeFrom = None,
    to: RangeTo = None,
) -> PriceSeries | PriceSeriesUnavailable:
    """Price chart for the same periods as the event timeline: the latest session's intraday bars (1d),
    or daily bars from the timeline's period start (1m, 1y).

    With ``from``/``to`` (the timeline's common KST range, FS040) only bars inside it are returned: intraday bars
    by their time, daily bars by their KST day. A closed market leaves a gap; no price is ever filled in, so a
    range without any session (a holiday ``1d``) is ``no_data``."""
    _require_company(state.provider.get(), company_id)
    window = _Range.parse(from_, to)
    result = state.market.series(company_id, period)
    if result.series is None or result.source is None:
        return PriceSeriesUnavailable(
            company_id=company_id, period=period, reason_code=result.code, reason=result.reason
        )
    series = result.series
    daily = series.interval == "1d"
    bars = [b for b in series.bars if window.contains(b.time, day_only=daily)]
    if not bars:
        return PriceSeriesUnavailable(
            company_id=company_id, period=period, reason_code="no_data", reason="이 기간에는 거래된 시세가 없어요(휴장일 등)."
        )
    return PriceSeries(
        company_id=company_id,
        period=period,
        source=_source_out(result.source),
        currency=series.currency,
        interval=series.interval,
        points=[
            PricePoint(time=b.time.isoformat(), open=b.open, high=b.high, low=b.low, close=b.close, volume=b.volume)
            for b in bars
        ],
    )


def _source_out(source: Source) -> QuoteSourceOut:
    return QuoteSourceOut(
        provider=source.provider,
        name=source.name,
        official=source.official,
        delay_note=source.delay_note,
        symbol=source.symbol,
        url=source.url,
    )


@router.get("/companies/{id}/documents", response_model=CompanyDocumentsResponse)
def get_company_documents(company_id: Annotated[str, Path(alias="id")], state: State) -> CompanyDocumentsResponse:
    """Distinct source articles behind this company's approved events, newest publication first.

    Each article lists the events it supports and the stored evidence quotes it contributed, so the
    source and quote stay visible even when the original link is missing or unreachable.
    """
    ds = state.provider.get()
    _require_company(ds, company_id)
    docs: dict[str, CompanyDocument] = {}
    for issue in sort_recent(ds.issues_of_company(company_id)):
        for article_id in issue.article_ids:
            rec = ds.article_for(article_id)
            if rec is None:
                continue
            doc = docs.get(article_id)
            if doc is None:
                doc = docs[article_id] = CompanyDocument(
                    id=rec.id,
                    title=rec.title,
                    publisher=rec.publisher,
                    url=rec.url,
                    published_at=rec.published_at,
                    synthetic=rec.synthetic,
                    events=[],
                    quotes=[],
                )
            doc.events.append(
                DocumentEventRef(
                    event_id=issue.id,
                    title=issue.title,
                    relation_type=issue.article_relation.get(article_id),  # type: ignore[arg-type]
                )
            )
            known = {q.evidence_id for q in doc.quotes}
            for evidence_id in issue.evidence_ids:
                ev = ds.evidence.get(evidence_id)
                if ev is not None and ev.article_id == article_id and ev.id not in known:
                    known.add(ev.id)
                    doc.quotes.append(DocumentQuote(evidence_id=ev.id, quote=ev.quote, quote_verified=ev.quote_verified))
    items = sorted(docs.values(), key=lambda d: d.id)
    items.sort(key=lambda d: _reported_sort_key(d.published_at), reverse=True)
    return CompanyDocumentsResponse(items=items, metadata=meta(ds))


# --------------------------------------------------------------------------- events


@router.get("/events", response_model=EventListResponse)
def list_events(
    state: State,
    company_id: str | None = Query(default=None, alias="companyId"),
    from_: RangeFrom = None,
    to: RangeTo = None,
) -> EventListResponse:
    """Approved issues, newest event first.

    ``from``/``to`` are a KST date (whole day) or date-time; the detail screen sends the same range as its price
    chart, ending at the query time (FS040), so an event scheduled after ``to`` is not listed. With a range
    (D05): an issue whose event day is known matches by that day (a day without a time stays on that day,
    shown as time unknown); an issue whose event day is unknown (no time, or only a month or year) never matches
    by its event time and is listed apart in ``unknownTimeItems`` when its latest article publication
    (``reportedAt``) falls in the range. The publication time only decides the range; it never becomes the
    event time.
    """
    ds = state.provider.get()
    window = _Range.parse(from_, to)
    if company_id is not None:
        _require_company(ds, company_id)
        issues = ds.issues_of_company(company_id)
    else:
        issues = list(ds.issues.values())
    scope = sort_recent(issues)
    latest_event = next((i.event_time for i in scope if (when := _event_day_or_time(i)) and window.not_after(when)), None)
    latest_report = max((i.latest_published_at for i in scope if i.latest_published_at), key=_reported_sort_key, default=None)
    excluded = 0
    undated: list[IssueRec] = []
    if window.bounded:
        kept = []
        for issue in issues:
            when = _event_day_or_time(issue)
            if when is None:
                excluded += 1
                reported = _reported(issue.latest_published_at)
                if reported and window.contains(reported):
                    undated.append(issue)
            elif window.contains(when, day_only=not isinstance(when, datetime)):
                kept.append(issue)
        issues = kept
    ordered = sort_recent(issues)
    undated.sort(key=lambda i: i.id)
    undated.sort(key=lambda i: _reported_sort_key(i.latest_published_at), reverse=True)
    return EventListResponse(
        items=[event_summary(i) for i in ordered],
        unknown_time_items=[event_summary(i) for i in undated],
        metadata=EventListMetadata(
            **meta(ds).model_dump(),
            total=len(ordered),
            excluded_unknown_time=excluded,
            latest_event_time=latest_event,
            latest_reported_at=latest_report,
        ),
    )


def _event_day_or_time(issue: IssueRec) -> date | datetime | None:
    """The event's KST moment (time known) or day (only the day known); ``None`` when not even the day is known."""
    precision = time_precision(issue.event_time)
    if precision == "datetime":
        return _reported(issue.event_time)
    if precision == "day":
        return date.fromisoformat(issue.event_time[:10])  # type: ignore[index]
    return None


_KST = timezone(timedelta(hours=9))


def _reported(value: str | None) -> datetime | None:
    """Article publication time; a value without an offset is read as KST (same rule as briefings)."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_KST)


def _reported_sort_key(value: str | None) -> float:
    moment = _reported(value)
    return moment.timestamp() if moment else float("-inf")


@router.get("/events/{id}", response_model=EventDetail)
def get_event(issue_id: Annotated[str, Path(alias="id")], state: State, round_id: RoundQuery = None) -> EventDetail:
    ds = state.dataset(round_id)
    issue = ds.issues.get(issue_id)
    if issue is None:
        raise not_found("event_not_found", "사건을 찾을 수 없습니다.")
    articles = []
    for article_id in issue.article_ids:
        rec = ds.article_for(article_id)
        if rec is not None:
            articles.append(
                ArticleOut(
                    id=rec.id,
                    title=rec.title,
                    publisher=rec.publisher,
                    url=rec.url,
                    published_at=rec.published_at,
                    synthetic=rec.synthetic,
                    relation_type=issue.article_relation.get(article_id),  # type: ignore[arg-type]
                )
            )
    relations = []
    for r in issue.relations:
        graph_visible = (
            (r.relation_type in COMPANY_LINKS and r.source == issue.id)
            or (r.relation_type == "FOLLOWS" and r.source == issue.id and r.target in ds.issues)
        )
        article_link = r.relation_type in ARTICLE_LINKS and r.target == issue.id
        if not (graph_visible or article_link):
            continue
        relations.append(
            RelationOut(
                id=r.relation_id,
                edge_id=edge_id(r.relation_type, r.source, r.target) if graph_visible else None,
                relation_type=r.relation_type,
                source=r.source,
                target=r.target,
                role=r.role,
                role_unconfirmed=r.role_unconfirmed,
                assertion_status=r.assertion_status,
                evidence_ids=list(r.evidence_ids),
            )
        )
    return EventDetail(
        id=issue.id,
        title=issue.title,
        event_time=issue.event_time,
        time_precision=issue.time_precision,
        period=issue.period,
        mentions=[
            MentionOut(
                mention_id=m.mention_id,
                article_id=m.article_id,
                title=m.title,
                action=m.action,
                target=m.target,
                event_time=m.event_time,
                time_precision=m.time_precision,
                period=m.period,
                assertion_status=m.assertion_status,
                participants=[
                    ParticipantOut(company_id=p.company_id, name=p.name, role=p.role, role_unconfirmed=p.role_unconfirmed)
                    for p in m.participants
                ],
                evidence_ids=list(m.evidence_ids),
                background=m.background,
            )
            for m in issue.mentions
        ],
        articles=articles,
        relations=relations,
        companies=company_links(ds, issue),
        source_support=source_support_out(issue),
        field_decisions=[
            FieldDecisionOut(
                candidate_id=fd.candidate_id,
                mention_id=fd.mention_id,
                outcomes=[FieldOutcomeOut(field=o.field, decision=o.decision, reason=o.reason) for o in fd.outcomes],
            )
            for fd in issue.field_decisions
        ],
        evidence_ids=list(issue.evidence_ids),
        follows=Follows(
            previous=[follow_ref(ds, i) for i in ds.follows_previous.get(issue.id, ())],
            next=[follow_ref(ds, i) for i in ds.follows_next.get(issue.id, ())],
        ),
        approval=ApprovalOut(
            source=issue.approval.source,  # type: ignore[arg-type]
            label=issue.approval.label,
            scope=issue.approval.scope,
            rule_id=issue.approval.rule_id,
        )
        if issue.approval
        else None,
        summary=unavailable(SUMMARY_UNAVAILABLE),
        metadata=meta(ds),
    )


# --------------------------------------------------------------------------- evidence


@router.get("/evidence/{id}", response_model=EvidenceResponse)
def get_evidence(evidence_id: Annotated[str, Path(alias="id")], state: State, round_id: RoundQuery = None) -> EvidenceResponse:
    ds = state.dataset(round_id)
    ev = ds.evidence.get(evidence_id)
    if ev is None:
        raise not_found("evidence_not_found", "근거를 찾을 수 없습니다.")
    article = ds.article_for(ev.article_id, ev.article_version)
    return EvidenceResponse(
        id=ev.id,
        quote=ev.quote,
        start=ev.start,
        end=ev.end,
        article_id=ev.article_id,
        article_version=ev.article_version,
        article=EvidenceArticle(
            title=article.title,
            publisher=article.publisher,
            url=article.url,
            published_at=article.published_at,
            synthetic=article.synthetic,
        )
        if article
        else None,
        quote_verified=ev.quote_verified,
        event_ids=list(ds.evidence_issues.get(ev.id, ())),
        metadata=meta(ds),
    )
