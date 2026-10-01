from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from ..dataset import ARTICLE_LINKS, COMPANY_LINKS, Dataset, IssueRec, edge_id, event_interval, sort_recent
from ..deps import OptionalPrincipal, State
from ..errors import ApiError, not_found
from ..graph import edge_detail, select_graph
from ..schemas import (
    ApprovalOut,
    ArticleOut,
    CompanyDetail,
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
    PriceResponse,
    RelationOut,
)
from ..views import (
    PRICE_UNAVAILABLE,
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
    ds = state.provider.get()
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
def get_edge(edge_id: Annotated[str, Path(alias="id")], state: State) -> EdgeDetail:
    return edge_detail(state.provider.get(), edge_id)


# --------------------------------------------------------------------------- companies


@router.get("/companies", response_model=CompanyListResponse)
def search_companies(
    state: State,
    q: str | None = Query(default=None, description="Substring of id, name, ticker or alias"),
    limit: int = Query(default=50, ge=1, le=200),
) -> CompanyListResponse:
    """Not in spec v0.2 section 8; added for watchlist selection (FR: choose up to 3 companies)."""
    ds = state.provider.get()
    needle = (q or "").strip().lower()
    matches = [
        c
        for c in ds.companies.values()
        if not needle
        or any(needle in text.lower() for text in (c.id, c.name, c.ticker or "", *c.aliases))
    ]
    matches.sort(key=lambda c: (not c.name.lower().startswith(needle), c.name, c.id))
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
            for c in matches[:limit]
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
            role=edges[issue.id].role,
            assertion_status=edges[issue.id].assertion_status,
            evidence_count=len(edges[issue.id].evidence_ids),
            basis=[basis_out(b) for b in edges[issue.id].basis],
        )
        for issue in sort_recent([ds.issues[i] for i in edges])
    ]


@router.get("/companies/{id}", response_model=CompanyDetail)
def get_company(
    company_id: Annotated[str, Path(alias="id")], state: State, principal: OptionalPrincipal
) -> CompanyDetail:
    ds = state.provider.get()
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
        price=unavailable(PRICE_UNAVAILABLE),
        holding=company_id in user_holding_ids(ds, user) if user else None,
        watch=company_id in user.watchlist_ids if user else None,
        metadata=meta(ds),
    )


@router.get("/companies/{id}/prices", response_model=PriceResponse)
def get_prices(
    company_id: Annotated[str, Path(alias="id")],
    state: State,
    period: Literal["1d", "1m", "1y"] = "1m",
) -> PriceResponse:
    ds = state.provider.get()
    _require_company(ds, company_id)
    return PriceResponse(
        reason=PRICE_UNAVAILABLE, company_id=company_id, period=period, metadata=meta(ds)
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
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
) -> EventListResponse:
    """Approved issues, newest event first. Issues without an approved event time never match from/to.

    With from/to those undated issues are listed apart in ``unknownTimeItems`` when their latest article
    publication (``reportedAt``, KST date) falls in the range. The publication time is a grouping key
    only; it never becomes the event time.
    """
    ds = state.provider.get()
    if from_ and to and from_ > to:
        raise ApiError(422, "invalid_range", "from은 to보다 늦을 수 없습니다.")
    if company_id is not None:
        _require_company(ds, company_id)
        issues = ds.issues_of_company(company_id)
    else:
        issues = list(ds.issues.values())
    scope = sort_recent(issues)
    latest_event = next((i.event_time for i in scope if event_interval(i.event_time) is not None), None)
    latest_report = max((i.latest_published_at for i in scope if i.latest_published_at), key=_reported_sort_key, default=None)
    excluded = 0
    undated: list[IssueRec] = []
    if from_ or to:
        kept = []
        for issue in issues:
            interval = event_interval(issue.event_time)
            if interval is None:
                excluded += 1
                reported = _kst_date(issue.latest_published_at)
                if reported and (not from_ or reported >= from_) and (not to or reported <= to):
                    undated.append(issue)
            elif (not from_ or interval[1] >= from_.isoformat()) and (not to or interval[0] <= to.isoformat()):
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


def _kst_date(value: str | None) -> date | None:
    moment = _reported(value)
    return moment.astimezone(_KST).date() if moment else None


def _reported_sort_key(value: str | None) -> float:
    moment = _reported(value)
    return moment.timestamp() if moment else float("-inf")


@router.get("/events/{id}", response_model=EventDetail)
def get_event(issue_id: Annotated[str, Path(alias="id")], state: State) -> EventDetail:
    ds = state.provider.get()
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
                    ParticipantOut(company_id=p.company_id, name=p.name, role=p.role)
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
        approval=ApprovalOut(source="admin-review", label=issue.approval.label, scope=issue.approval.scope)
        if issue.approval
        else None,
        summary=unavailable(SUMMARY_UNAVAILABLE),
        metadata=meta(ds),
    )


# --------------------------------------------------------------------------- evidence


@router.get("/evidence/{id}", response_model=EvidenceResponse)
def get_evidence(evidence_id: Annotated[str, Path(alias="id")], state: State) -> EvidenceResponse:
    ds = state.provider.get()
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
