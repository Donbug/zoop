from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from ..accounts import UserState
from ..deps import Member, State
from ..errors import ApiError
from ..schemas import (
    CompanySummary,
    ConnectionInfo,
    ConnectionResponse,
    HoldingOut,
    MockPortfolioListResponse,
    MockPortfolioOption,
    PortfolioConnectRequest,
    PortfolioResponse,
    RecommendationResponse,
    RecommendedCompany,
    SettingsResponse,
    SettingsUpdate,
    Unavailable,
)
from ..views import meta, mock_meta
from . import ERROR_RESPONSES

router = APIRouter(prefix="/api", tags=["me"], responses=ERROR_RESPONSES)
SETTINGS_BY = "bff-mock-settings"
PORTFOLIO_BY = "bff-mock-portfolio"
VALUATION_UNAVAILABLE = "시세 공급자가 없어 평가금액을 계산할 수 없습니다. 비중은 매입금액 기준입니다."


def settings_response(user: UserState) -> SettingsResponse:
    return SettingsResponse(
        mode=user.mode,
        watchlist_ids=list(user.watchlist_ids),
        tutorial_completed=user.tutorial_completed,
        completed=user.completed,
        investor=user.investor,
        version=user.version,
        metadata=mock_meta(SETTINGS_BY),
    )


@router.get("/me/settings", response_model=SettingsResponse)
def get_settings(user: Member) -> SettingsResponse:
    return settings_response(user)


@router.put("/me/settings", response_model=SettingsResponse)
def put_settings(body: SettingsUpdate, user: Member, state: State) -> SettingsResponse:
    """No watchlist limit; unknown or duplicate ids 422; stale ``version`` 409 unless the request changes
    nothing. ``completed`` needs neither a watchlist nor an account (an empty setup opens the market graph)."""
    # Known companies never depend on which graph version is active: the catalog and the active data,
    # every registered version, and what this member already saved.
    known = {
        *state.provider.get().companies,
        *state.admin.graphs.published_company_ids(),
        *user.watchlist_ids,
    }
    state.accounts.update_settings(
        user,
        version=body.version,
        mode=body.mode,
        watchlist_ids=body.watchlist_ids,
        tutorial_completed=body.tutorial_completed,
        completed=body.completed,
        investor=body.investor,
        known_companies=known,
    )
    return settings_response(user)


@router.get("/me/recommendations", response_model=RecommendationResponse)
def recommendations(
    user: Member, state: State, limit: int = Query(default=8, ge=1, le=30)
) -> RecommendationResponse:
    """Companies with the most approved issues in the active graph (the only basis the data supports;
    industry and theme recommendations have no producer). Companies already on the watchlist are skipped."""
    ds = state.provider.get()
    ranked = sorted(
        (
            (len(ds.issues_of_company(c.id)), c)
            for c in ds.companies.values()
            if c.id not in user.watchlist_ids
        ),
        key=lambda pair: (-pair[0], pair[1].name, pair[1].id),
    )
    items = [
        RecommendedCompany(
            company=CompanySummary(
                id=c.id,
                name=c.name,
                ticker=c.ticker,
                aliases=list(c.aliases),
                sector=c.sector,
                brand_color=c.brand_color,
                logo_url=c.logo_url,
                issue_count=count,
            ),
            reason=f"승인된 사건 {count}건",
        )
        for count, c in ranked[:limit]
        if count > 0
    ]
    return RecommendationResponse(basis="approved_issue_count", items=items, metadata=meta(ds))


@router.get("/portfolio/mock-portfolios", response_model=MockPortfolioListResponse)
def list_mock_portfolios(user: Member, state: State) -> MockPortfolioListResponse:
    """Virtual accounts that can be connected. Not in spec v0.2 section 8; the UI needs the ids."""
    ds = state.provider.get()
    return MockPortfolioListResponse(
        items=[
            MockPortfolioOption(id=p.id, label=p.label, holdings_count=len(p.holdings))
            for p in ds.mock_portfolios.values()
        ],
        metadata=mock_meta(PORTFOLIO_BY),
    )


@router.post(
    "/portfolio/connections", response_model=ConnectionResponse, status_code=201
)
def connect_portfolio(
    body: PortfolioConnectRequest, user: Member, state: State, response: Response
) -> ConnectionResponse:
    """201 on a new connection. Resending the request for the already connected profile returns that
    connection with 200 (no second connection); a different profile while connected is 409."""
    ds = state.provider.get()
    portfolio = ds.mock_portfolios.get(body.mock_portfolio_id)
    if portfolio is None:
        raise ApiError(
            404,
            "mock_portfolio_not_found",
            "연결할 수 있는 가상 계좌가 아닙니다.",
            {"available": sorted(ds.mock_portfolios)},
        )
    conn, created = state.accounts.connect(user, portfolio.id, portfolio.label, portfolio.holdings)
    if not created:
        response.status_code = 200
    return ConnectionResponse(
        id=conn.id,
        mock_portfolio_id=conn.mock_portfolio_id,
        label=conn.label,
        connected_at=conn.connected_at,
        holdings_count=len(conn.holdings),
        metadata=mock_meta(PORTFOLIO_BY, conn.connected_at),
    )


@router.get("/portfolio", response_model=PortfolioResponse)
def get_portfolio(user: Member, state: State) -> PortfolioResponse:
    """Holdings of the connected virtual account. No quotes exist, so weights are cost-basis weights."""
    conn = user.connection
    if conn is None:
        return PortfolioResponse(
            connected=False,
            connection=None,
            holdings=[],
            valuation=Unavailable(reason=VALUATION_UNAVAILABLE),
            as_of=None,
            metadata=mock_meta(PORTFOLIO_BY),
        )
    ds = state.provider.get()
    total = sum(h.quantity * h.avg_price for h in conn.holdings)
    holdings = []
    for h in conn.holdings:
        cost = h.quantity * h.avg_price
        company = ds.companies.get(h.company_id)
        holdings.append(
            HoldingOut(
                company_id=h.company_id,
                name=company.name if company else h.company_id,
                ticker=company.ticker if company else None,
                quantity=h.quantity,
                avg_price=h.avg_price,
                cost_basis=cost,
                weight=round(cost / total, 6) if total else 0.0,
                market_value=Unavailable(reason="시세 공급자가 없습니다."),
            )
        )
    return PortfolioResponse(
        connected=True,
        connection=ConnectionInfo(
            id=conn.id,
            mock_portfolio_id=conn.mock_portfolio_id,
            label=conn.label,
            connected_at=conn.connected_at,
        ),
        holdings=holdings,
        valuation=Unavailable(reason=VALUATION_UNAVAILABLE),
        as_of=conn.connected_at,
        metadata=mock_meta(PORTFOLIO_BY, conn.connected_at),
    )


@router.delete("/portfolio/connections/{id}", status_code=204, response_class=Response)
def disconnect_portfolio(
    connection_id: Annotated[str, Path(alias="id")], user: Member, state: State
) -> Response:
    state.accounts.disconnect(user, connection_id)
    return Response(status_code=204)
