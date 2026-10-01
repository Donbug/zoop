from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query

from ..deps import Admin, State, require_admin
from ..errors import ApiError
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


@router.get("/feedback/summary", response_model=FeedbackSummary)
def feedback_summary(state: State, window: StatsWindow = "7d") -> FeedbackSummary:
    """Likes and dislikes per AI feature with a daily trend. Ratios below ``minSample`` votes are null."""
    return state.insights.feedback.summary(window)


@router.get("/feedback/dislikes", response_model=DislikePage)
def dislikes(
    state: State,
    window: StatsWindow = "7d",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Cursor = None,
) -> DislikePage:
    """Dislikes, newest first, with the (masked) reason and the voter's pseudonym."""
    return state.insights.feedback.dislikes(window, limit, _offset(cursor), optional_dataset(state))


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
