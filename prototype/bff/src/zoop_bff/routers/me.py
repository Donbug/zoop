from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from ..accounts import Connection, UserState
from ..dataset import Dataset, MockPortfolioRec
from ..deps import Member, State
from ..errors import ApiError
from ..market_data import MarketData, QuoteResult
from ..schemas import (
    CompanySummary,
    ConnectionInfo,
    ConnectionResponse,
    HoldingOut,
    HoldingQuote,
    MockCash,
    MockHoldingOut,
    MockPortfolioListResponse,
    MockPortfolioOption,
    MockProfileResponse,
    PortfolioConnectRequest,
    PortfolioResponse,
    PortfolioValuation,
    RecommendationResponse,
    RecommendedCompany,
    SettingsResponse,
    SettingsUpdate,
    WatchUpdate,
    Unavailable,
    WeightUnavailableCode,
)
from ..views import meta, mock_meta
from . import ERROR_RESPONSES

router = APIRouter(prefix="/api", tags=["me"], responses=ERROR_RESPONSES)
SETTINGS_BY = "bff-mock-settings"
PORTFOLIO_BY = "bff-mock-portfolio"
WEIGHT_UNAVAILABLE: dict[WeightUnavailableCode, str] = {
    "missing_price": "주가를 받지 못한 종목이 있어 비중을 계산할 수 없어요.",
    "mixed_currency": "보유 종목의 시세 통화가 서로 달라요. 환율로 바꾸지 않아 합계와 비중을 계산하지 않았어요.",
    "zero_total": "평가금액 합계가 0이라 비중을 계산할 수 없어요.",
}


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


@router.put("/me/watchlist/{id}", response_model=SettingsResponse)
def put_watch(
    company_id: Annotated[str, Path(alias="id", min_length=1, max_length=120)],
    body: WatchUpdate,
    user: Member,
    state: State,
) -> SettingsResponse:
    """FS027 single toggle from the sidebar or a company node: the press itself is the save request.

    Sends the wanted final state (``watched``) instead of the settings ``version``: a resent or concurrent
    toggle is idempotent (no duplicate entry, no 409 to reload), and a toggle never overwrites another
    company's change made elsewhere. Members only (guest 403). Adding an unknown company is 404; taking out
    a company that is not watched changes nothing. Holdings are separate, so a held company stays a holding
    node in the personal graph after it leaves the watchlist. No limit on the number of companies."""
    if body.watched:
        known = {*state.provider.get().companies, *state.admin.graphs.published_company_ids()}
        if company_id not in known:
            raise ApiError(404, "company_not_found", "관심 종목에 넣을 기업을 찾을 수 없습니다.")
    state.accounts.set_watched(user, company_id, body.watched)
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
    """Project mock profiles that can be connected (FS062). Not a brokerage account: no credentials are asked."""
    ds = state.provider.get()
    return MockPortfolioListResponse(
        items=[
            MockPortfolioOption(id=p.id, label=p.label, account_id=p.account_id, holdings_count=len(p.holdings))
            for p in ds.mock_portfolios.values()
        ],
        metadata=mock_meta(PORTFOLIO_BY),
    )


def _mock_profile(ds: Dataset, profile_id: str) -> MockPortfolioRec:
    profile = ds.mock_portfolios.get(profile_id)
    if profile is None:
        raise ApiError(
            404,
            "mock_portfolio_not_found",
            "연결할 수 있는 가상 계좌가 아닙니다.",
            {"available": sorted(ds.mock_portfolios)},
        )
    return profile


def _cash(amount: float | None, currency: str | None) -> MockCash | None:
    return MockCash(amount=amount, currency=currency) if amount is not None and currency is not None else None


@router.get("/portfolio/mock-portfolios/{id}", response_model=MockProfileResponse)
def get_mock_portfolio(
    profile_id: Annotated[str, Path(alias="id")], user: Member, state: State
) -> MockProfileResponse:
    """One mock profile: account id, cash and holdings of that same profile. An unknown id is 404, never an
    empty account; a profile with no holdings is a normal account with ``holdings: []``."""
    ds = state.provider.get()
    profile = _mock_profile(ds, profile_id)
    return MockProfileResponse(
        id=profile.id,
        label=profile.label,
        account_id=profile.account_id,
        cash=_cash(profile.cash, profile.cash_currency),
        as_of=profile.as_of,
        holdings=[
            MockHoldingOut(
                company_id=h.company_id,
                name=ds.companies[h.company_id].name if h.company_id in ds.companies else h.company_id,
                quantity=h.quantity,
                avg_price=h.avg_price,
                avg_price_currency=h.currency,
            )
            for h in profile.holdings
        ],
        metadata=mock_meta(PORTFOLIO_BY, profile.as_of),
    )


def _connection_info(conn: Connection) -> ConnectionInfo:
    return ConnectionInfo(
        id=conn.id,
        mock_portfolio_id=conn.mock_portfolio_id,
        label=conn.label,
        connected_at=conn.connected_at,
        account_id=conn.account_id,
        cash=_cash(conn.cash, conn.cash_currency),
    )


@router.post(
    "/portfolio/connections", response_model=ConnectionResponse, status_code=201
)
def connect_portfolio(
    body: PortfolioConnectRequest, user: Member, state: State, response: Response
) -> ConnectionResponse:
    """201 on a new connection. Resending the request for the already connected profile returns that
    connection with 200 (no second connection); a different profile while connected is 409."""
    profile = _mock_profile(state.provider.get(), body.mock_portfolio_id)
    conn, created = state.accounts.connect(user, profile)
    if not created:
        response.status_code = 200
    return ConnectionResponse(
        **_connection_info(conn).model_dump(),
        holdings_count=len(conn.holdings),
        metadata=mock_meta(PORTFOLIO_BY, conn.mock_as_of),
    )


def _read_quotes(market: MarketData, company_ids: list[str]) -> dict[str, QuoteResult]:
    """All prices of one valuation, read together (cached up to ~30 s by MarketData)."""
    if not company_ids:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(company_ids))) as pool:
        return dict(zip(company_ids, pool.map(market.quote, company_ids), strict=True))


@router.get("/portfolio", response_model=PortfolioResponse)
def get_portfolio(user: Member, state: State) -> PortfolioResponse:
    """Holdings of the connected virtual account (FS039·FS054). Quantity and average price are the mock values;
    market value = quantity x the price read at ``valuation.calculatedAt``; weight = market value / total stock
    market value (cash excluded). A missing price, prices in different currencies (no exchange rate is
    assumed) or a zero total make every weight null with a reason, never 0."""
    conn = user.connection
    if conn is None:
        return PortfolioResponse(
            connected=False,
            connection=None,
            holdings=[],
            mock_as_of=None,
            valuation=None,
            metadata=mock_meta(PORTFOLIO_BY),
        )
    ds = state.provider.get()
    calculated_at = datetime.now(UTC).isoformat(timespec="seconds")
    quotes = _read_quotes(state.market, list(dict.fromkeys(h.company_id for h in conn.holdings)))

    values: list[tuple[float, str] | None] = []
    for h in conn.holdings:
        q = quotes[h.company_id].quote
        values.append((h.quantity * q.price, q.currency) if q else None)
    currencies = {v[1] for v in values if v}
    code: WeightUnavailableCode | None = None
    total: float | None = None
    if any(v is None for v in values):
        code = "missing_price"
    elif len(currencies) > 1:
        code = "mixed_currency"
    else:
        total = sum(v[0] for v in values if v)
        if total == 0:
            code = "zero_total"

    holdings = []
    for h, value in zip(conn.holdings, values, strict=True):
        result = quotes[h.company_id]
        company = ds.companies.get(h.company_id)
        quote: HoldingQuote | Unavailable
        if result.quote and result.source:
            quote = HoldingQuote(
                price=result.quote.price,
                currency=result.quote.currency,
                as_of=result.quote.as_of.isoformat() if result.quote.as_of else None,
                source_name=result.source.name,
            )
        else:
            quote = Unavailable(reason=result.reason or "주가를 받지 못했어요.")
        holdings.append(
            HoldingOut(
                company_id=h.company_id,
                name=company.name if company else h.company_id,
                ticker=company.ticker if company else None,
                quantity=h.quantity,
                avg_price=h.avg_price,
                avg_price_currency=h.currency,
                quote=quote,
                market_value=round(value[0], 6) if value else None,
                weight=round(value[0] / total, 6) if value and code is None and total else None,
            )
        )
    return PortfolioResponse(
        connected=True,
        connection=_connection_info(conn),
        holdings=holdings,
        mock_as_of=conn.mock_as_of,
        valuation=PortfolioValuation(
            calculated_at=calculated_at,
            currency=next(iter(currencies)) if total is not None and currencies else None,
            total_market_value=round(total, 6) if total is not None else None,
            weight_status="unavailable" if code else "available",
            weight_unavailable_code=code,
            weight_unavailable_reason=WEIGHT_UNAVAILABLE[code] if code else None,
        ),
        metadata=mock_meta(PORTFOLIO_BY, conn.mock_as_of),
    )


@router.delete("/portfolio/connections/{id}", status_code=204, response_class=Response)
def disconnect_portfolio(
    connection_id: Annotated[str, Path(alias="id")], user: Member, state: State
) -> Response:
    state.accounts.disconnect(user, connection_id)
    return Response(status_code=204)
