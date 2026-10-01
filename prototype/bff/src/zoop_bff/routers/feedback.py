from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ..briefing_rounds import parse_round_id
from ..deps import Member, State
from ..errors import ApiError
from ..insights_schemas import FeedbackFeature, FeedbackItem, FeedbackList, FeedbackVote
from . import ERROR_RESPONSES

router = APIRouter(prefix="/api/feedback", tags=["feedback"], responses=ERROR_RESPONSES)


def _current_version(state: State, member_id: str, feature: str, target_id: str) -> str | None:
    """The target must exist and be visible to the member; returns its current result version.

    A chatbot answer can only be rated by the member who asked and never changes (no version). A briefing
    round or key issue must be published; its version is the graph version the round was published on."""
    if feature == "chatbot_answer":
        row = state.admin.db.one(
            "SELECT s.owner_id AS owner FROM chat_messages m JOIN chat_sessions s ON s.id=m.session_id WHERE m.id=?",
            (target_id,),
        )
        if row is None:
            raise ApiError(404, "feedback_target_not_found", "평가할 답변을 찾을 수 없습니다.")
        if row["owner"] != member_id:
            raise ApiError(403, "forbidden", "다른 사용자의 답변은 평가할 수 없습니다.")
        return None
    round_id, _, event_id = target_id.partition("/")
    parsed = parse_round_id(round_id)
    if parsed is None or (feature == "briefing_round") != (not event_id):
        raise ApiError(404, "feedback_target_not_found", "평가할 브리핑을 찾을 수 없습니다.")
    briefing = state.admin.briefings.public(*parsed)
    if briefing.status != "published" or (event_id and event_id not in {i.event_id for i in briefing.items}):
        raise ApiError(404, "feedback_target_not_found", "발행된 브리핑에서만 평가할 수 있습니다.")
    return briefing.graph_version


@router.get("", response_model=FeedbackList)
def my_feedback(
    user: Member,
    state: State,
    feature: FeedbackFeature,
    target_ids: Annotated[str, Query(alias="targetIds", min_length=1, max_length=2000, description="Comma separated")],
) -> FeedbackList:
    """The member's own current ratings on the given targets (no item = no rating). Guests get 403."""
    subject = state.insights.keys.subject("member", user.id)
    ids = list(dict.fromkeys(t for t in target_ids.split(",") if t))[:50]
    return FeedbackList(items=state.insights.feedback.mine(subject, feature, ids))


@router.put("", response_model=FeedbackItem)
def rate(body: FeedbackVote, user: Member, state: State) -> FeedbackItem:
    """Set the member's rating to the wanted final state: ``up``, ``down`` or ``none`` (take it back).

    Members only (guest 403, no session 401). Resending the same request keeps the same state, so a retry
    after a lost response never toggles. ``targetVersion``, when sent, must match the result's current
    version (409 ``feedback_target_changed``). ``reason`` (optional, max 200 chars) only goes with a dislike."""
    version = _current_version(state, user.id, body.feature, body.target_id)
    if body.target_version is not None and body.target_version != version:
        raise ApiError(409, "feedback_target_changed", "평가하려던 결과가 바뀌었습니다. 화면을 새로 고친 뒤 다시 평가해 주세요.")
    subject = state.insights.keys.subject("member", user.id)
    return state.insights.feedback.set_rating(subject, body.feature, body.target_id, version, body.value, body.reason)
