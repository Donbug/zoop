from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from ..chat import GENERATED_BY, compose_answer, resolve_all
from ..insights_common import companies_of
from ..deps import Session, State
from ..schemas import (
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSessionRequest,
    ChatSessionResponse,
)
from ..views import meta
from . import ERROR_RESPONSES

router = APIRouter(prefix="/api/chat", tags=["chat"], responses=ERROR_RESPONSES)


@router.post("/sessions", response_model=ChatSessionResponse, status_code=201)
def create_session(body: ChatSessionRequest, principal: Session, state: State) -> ChatSessionResponse:
    """Needs a member or guest session; a conversation is only readable by its creator."""
    ds = state.provider.get()
    resolve_all(ds, body.context_ids)  # 422 on unknown ids
    session = state.chats.create(principal.principal_id, principal.kind, list(dict.fromkeys(body.context_ids)))
    return ChatSessionResponse(
        id=session.id,
        context_ids=session.context_ids,
        created_at=session.created_at,
        metadata=meta(ds, GENERATED_BY),
    )


@router.post("/sessions/{id}/messages", response_model=ChatMessageResponse)
def post_message(
    session_id: Annotated[str, Path(alias="id")],
    body: ChatMessageRequest,
    principal: Session,
    state: State,
) -> ChatMessageResponse:
    """Example answer (no LLM): quotes of approved evidence linked to the context nodes.

    Uses the request's ``contextIds`` when given (non-empty), otherwise the session's.
    """
    with state.admin.usage.measure("chatbot"):
        session = state.chats.owned(session_id, principal.principal_id)
        ds = state.provider.get()
        context_ids = list(dict.fromkeys(body.context_ids or session.context_ids))
        contexts = resolve_all(ds, context_ids)
        answer = compose_answer(ds, body.question, contexts)
        company_ids = list(dict.fromkeys(c for context_id in context_ids for c in companies_of(ds, context_id)))
        message_id = state.chats.record_exchange(session, body.question, answer, context_ids, company_ids)
        return ChatMessageResponse(
            session_id=session.id,
            message_id=message_id,
            question=body.question,
            status=answer.status,  # type: ignore[arg-type]
            answer=answer.text,
            reason=answer.reason,
            context_ids=context_ids,
            sources=list(answer.evidence_ids),
            citations=list(answer.citations),
            graph_targets=list(answer.targets),
            metadata=meta(ds, GENERATED_BY),
        )
