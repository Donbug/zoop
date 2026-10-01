from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from ..deps import State, require_admin
from ..insights_schemas import InsightCompanyDetail, InsightCompanyRanking, InsightsOverview, StatsSummary, StatsWindow
from . import ADMIN_ERROR_RESPONSES

router = APIRouter(
    prefix="/api/admin/insights",
    tags=["admin-insights"],
    dependencies=[Depends(require_admin)],
    responses=ADMIN_ERROR_RESPONSES,
)


@router.get("/overview", response_model=InsightsOverview)
def overview(state: State) -> InsightsOverview:
    """Seven-day headline figures for the dashboard card."""
    return state.insights.stats.overview(state.accounts.members())


@router.get("/summary", response_model=StatsSummary)
def summary(state: State, window: StatsWindow = "7d") -> StatsSummary:
    """Usage figures with their definitions, a daily trend and per-round briefing reads.

    A ratio is ``null`` (``sampleHidden``) when its denominator is below ``minSample``; the counts remain.
    """
    return state.insights.stats.summary(window, state.accounts.members())


@router.get("/companies", response_model=InsightCompanyRanking)
def companies(state: State, window: StatsWindow = "7d") -> InsightCompanyRanking:
    """Companies ranked by node views: watch-list members, virtual holders, node views, edge selections, AI questions."""
    return state.insights.stats.companies(window, state.accounts.members(), state.provider.get())


@router.get("/companies/{company_id}", response_model=InsightCompanyDetail)
def company(company_id: Annotated[str, Path(max_length=100)], state: State, window: StatsWindow = "7d") -> InsightCompanyDetail:
    """Daily trend of one company's node views, edge/issue selections and AI questions."""
    return state.insights.stats.company(window, company_id, state.accounts.members(), state.provider.get())
