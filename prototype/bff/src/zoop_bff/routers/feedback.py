from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response

from ..accounts import Principal
from ..briefing_rounds import parse_round_id
from ..deps import Session, State
from ..errors import ApiError
from ..insights_schemas import FeedbackFeature, FeedbackItem, FeedbackList, FeedbackVote
from . import ERROR_RESPONSES

router = APIRouter(prefix="/api/feedback", tags=["feedback"], responses=ERROR_RESPONSES)


def _check_target(state: State, principal: Principal, feature: str, target_id: str) -> None:
    """The target must exist, and a chatbot answer can only be rated by the person who asked."""
    if feature == "chatbot_answer":
        row = state.admin.db.one(
            "SELECT s.owner_id AS owner FROM chat_messages m JOIN chat_sessions s ON s.id=m.session_id WHERE m.id=?",
            (target_id,),
        )
        if row is None:
            raise ApiError(404, "feedback_target_not_found", "평가할 답변을 찾을 수 없습니다.")
        if row["owner"] != principal.principal_id:
            raise ApiError(403, "forbidden", "다른 사용자의 답변은 평가할 수 없습니다.")
        return
    round_id, _, event_id = target_id.partition("/")
    parsed = parse_round_id(round_id)
    if parsed is None or (feature == "briefing_round") != (not event_id):
        raise ApiError(404, "feedback_target_not_found", "평가할 브리핑을 찾을 수 없습니다.")
    briefing = state.admin.briefings.public(*parsed)
    if briefing.status != "published" or (event_id and event_id not in {i.event_id for i in briefing.items}):
        raise ApiError(404, "feedback_target_not_found", "발행된 브리핑에서만 평가할 수 있습니다.")


@router.get("", response_model=FeedbackList)
def my_feedback(
    principal: Session,
    state: State,
    feature: FeedbackFeature,
    target_ids: Annotated[str, Query(alias="targetIds", min_length=1, max_length=2000, description="Comma separated")],
) -> FeedbackList:
    """The caller's own votes on the given targets (empty list when none)."""
    subject = state.insights.keys.subject(principal.kind, principal.principal_id)
    ids = list(dict.fromkeys(t for t in target_ids.split(",") if t))[:50]
    return FeedbackList(items=state.insights.feedback.mine(subject, feature, ids))


@router.put("", response_model=FeedbackItem)
def vote(body: FeedbackVote, principal: Session, state: State) -> FeedbackItem:
    """Like or dislike an AI output: one vote per person and target. Sending the other value switches the vote,
    the same value again changes nothing. ``reason`` (optional, max 200 chars) only goes with a dislike."""
    _check_target(state, principal, body.feature, body.target_id)
    subject = state.insights.keys.subject(principal.kind, principal.principal_id)
    return state.insights.feedback.set_vote(subject, body.feature, body.target_id, body.value, body.reason)


@router.delete("", status_code=204, response_class=Response)
def cancel(
    principal: Session,
    state: State,
    feature: FeedbackFeature,
    target_id: Annotated[str, Query(alias="targetId", min_length=1, max_length=160)],
) -> Response:
    """Take the vote back. Idempotent: 204 even when there was no vote."""
    subject = state.insights.keys.subject(principal.kind, principal.principal_id)
    state.insights.feedback.cancel(subject, feature, target_id)
    return Response(status_code=204)
