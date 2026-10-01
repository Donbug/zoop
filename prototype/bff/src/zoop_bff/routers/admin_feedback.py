from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query

from ..deps import Admin, State, require_admin
from ..errors import ApiError
from ..feedback import Period
from ..insights_schemas import DislikePage, FeedbackSummary, StatsWindow, TranscriptDetail, TranscriptPage
from . import ADMIN_ERROR_RESPONSES
from .telemetry import optional_dataset

router = APIRouter(
    prefix="/api/admin",
    tags=["admin-feedback"],
    dependencies=[Depends(require_admin)],
    responses=ADMIN_ERROR_RESPONSES,
)

Cursor = Annotated[str | None, Query(description="Offset returned as nextCursor")]


def _offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not cursor.isdigit():
        raise ApiError(422, "invalid_cursor", "cursor가 올바르지 않습니다.")
    return int(cursor)


Day = Annotated[date | None, Query(description="KST day (inclusive) of the rating's last valid change; overrides window")]


def _period(state: State, window: str, start: date | None, end: date | None) -> Period:
    if start and end and start > end:
        raise ApiError(422, "invalid_range", "시작일은 종료일보다 늦을 수 없습니다.")
    return state.insights.feedback.period(window, start, end)


@router.get("/feedback/summary", response_model=FeedbackSummary)
def feedback_summary(state: State, window: StatsWindow = "all", start: Day = None, end: Day = None) -> FeedbackSummary:
    """Current (not taken back) likes and dislikes per AI feature with a daily trend, filtered by the KST day
    of each rating's last valid change: a preset ``window`` (default: everything kept) or ``start``/``end``.
    Ratios below ``minSample`` votes are null; with no rating at all there is no ratio either."""
    return state.insights.feedback.summary(_period(state, window, start, end))


@router.get("/feedback/dislikes", response_model=DislikePage)
def dislikes(
    state: State,
    window: StatsWindow = "all",
    start: Day = None,
    end: Day = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Cursor = None,
) -> DislikePage:
    """Current dislikes, newest change first, with the (masked) reason and the voter's pseudonym."""
    return state.insights.feedback.dislikes(_period(state, window, start, end), limit, _offset(cursor), optional_dataset(state))


@router.get("/transcripts", response_model=TranscriptPage)
def transcripts(
    state: State,
    only: Annotated[Literal["all", "disliked"], Query(description="disliked: conversations with a disliked answer")] = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Cursor = None,
) -> TranscriptPage:
    """AI conversations, newest first. Users appear under pseudonyms and every text is masked."""
    return state.insights.transcripts.page(disliked_only=only == "disliked", limit=limit, offset=_offset(cursor))


@router.get("/transcripts/{session_id}", response_model=TranscriptDetail)
def transcript(session_id: Annotated[str, Path(max_length=64)], state: State, admin: Admin) -> TranscriptDetail:
    """One conversation, personal data masked at read time (the stored original is untouched).

    Opening a transcript is recorded in the audit log (``transcript.view``).
    """
    return state.insights.transcripts.detail(session_id, optional_dataset(state), admin.actor)
