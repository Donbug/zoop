from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from ..briefing_rounds import GENERATED_BY, parse_round_id
from ..deps import State
from ..errors import not_found
from ..schemas import BriefingEvaluationResponse, BriefingGraphBasis, BriefingResponse, BriefingRoundsResponse
from ..views import mock_meta
from . import ERROR_RESPONSES

router = APIRouter(prefix="/api/briefings", tags=["briefings"], responses=ERROR_RESPONSES)


@router.get("", response_model=BriefingResponse)
def get_briefing(
    state: State,
    date_: Annotated[date | None, Query(alias="date", description="Publication date (KST). Default: the latest round")] = None,
    edition: Literal["morning", "evening"] | None = None,
) -> BriefingResponse:
    """A published commute-briefing round (07:40 morning / 18:10 evening KST), the same for everyone.

    At most three key issues chosen by rule from the round's data window; the round is never padded.
    A round that is not ready, failed, suspended or corrected says so in ``status``/``notice``/
    ``corrections`` instead of an error. No prediction, probability or good/bad-news field exists.
    """
    state.admin.briefings.count_view()
    return state.admin.briefings.public(date_, edition)


@router.get("/rounds", response_model=BriefingRoundsResponse)
def get_rounds(state: State, limit: Annotated[int, Query(ge=1, le=100)] = 30) -> BriefingRoundsResponse:
    """Rounds a user can open (published or suspended), newest first: the date and edition picker."""
    return state.admin.briefings.public_rounds(limit)


@router.get("/{id}/graph", response_model=BriefingGraphBasis)
def get_graph_basis(briefing_id: Annotated[str, Path(alias="id")], state: State) -> BriefingGraphBasis:
    """What the round's relationship graph is anchored to, and whether it can be shown (FS032).

    ``available``: the round was published and its publication-time graph can be rebuilt; read it with
    ``round=<id>`` on ``/api/graph``, ``/api/graph/edges/{id}``, ``/api/events/{id}``, ``/api/evidence/{id}``
    and ``/api/companies/{id}``. Later reviews, rule switches and graph versions never change it.
    ``suspended`` / ``not_published`` / ``unavailable`` (the version or its evidence is gone): a notice, no graph;
    the newest graph is never shown in its place. An unknown round id is a 404.
    """
    return state.admin.briefing_graphs.basis(briefing_id)


@router.get("/{id}/evaluations", response_model=BriefingEvaluationResponse)
def get_evaluations(briefing_id: Annotated[str, Path(alias="id")]) -> BriefingEvaluationResponse:
    """Prediction evaluation is undecided (evidence README, unresolved items): always unavailable."""
    if parse_round_id(briefing_id) is None:
        raise not_found("briefing_not_found", "브리핑을 찾을 수 없습니다.")
    return BriefingEvaluationResponse(
        reason="예측 평가 정책 미정",
        briefing_id=briefing_id,
        metadata=mock_meta(GENERATED_BY),
    )
