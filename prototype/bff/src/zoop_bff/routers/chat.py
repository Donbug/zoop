from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Response

from ..deps import Session, State
from ..schemas import (
    ChatConversation,
    ChatCurrentResponse,
    ChatJob,
    ChatJobRequest,
    ChatSessionResponse,
)
from . import ERROR_RESPONSES

router = APIRouter(prefix="/api/chat", tags=["chat"], responses=ERROR_RESPONSES)

_ID = r"^[A-Za-z0-9_-]{8,64}$"
SessionId = Annotated[str, Path(alias="id", pattern=_ID, description="Conversation id made by the client")]
JobId = Annotated[str, Path(alias="job_id", pattern=_ID, description="Job id made by the client (idempotency key)")]


@router.put(
    "/sessions/{id}",
    response_model=ChatSessionResponse,
    status_code=201,
    responses={200: {"model": ChatSessionResponse, "description": "The conversation already existed (a resent request)."}},
)
def create_session(session_id: SessionId, principal: Session, state: State, response: Response) -> ChatSessionResponse:
    """Start a conversation (a new one never inherits the earlier one's questions or selection).

    Members only (a guest gets 403). The client chooses the id, so resending after a lost response returns the same
    conversation instead of making a second one.
    """
    session, created = state.chats.create_session(principal, session_id)
    if not created:
        response.status_code = 200
    return session


@router.get("/sessions/current", response_model=ChatCurrentResponse)
def current_conversation(principal: Session, state: State) -> ChatCurrentResponse:
    """The member's newest conversation with its jobs and saved results (`conversation: null` when there is none).

    This is how a closed panel, another page or a reload finds the conversation again.
    """
    return ChatCurrentResponse(conversation=state.chats.current(principal))


@router.get("/sessions/{id}", response_model=ChatConversation)
def get_conversation(session_id: SessionId, principal: Session, state: State) -> ChatConversation:
    """One conversation of the signed-in member: every job in order, with the saved result of the completed ones."""
    return state.chats.conversation(principal, session_id)


@router.post(
    "/sessions/{id}/jobs",
    response_model=ChatJob,
    status_code=202,
    responses={200: {"model": ChatJob, "description": "This job id was accepted before: its stored state or result."}},
)
def submit_job(session_id: SessionId, body: ChatJobRequest, principal: Session, state: State, response: Response) -> ChatJob:
    """Ask a question. The first request with a new job id freezes the question, selection, period and the KST day;
    the answer is produced in the background -- read it with `GET /api/chat/jobs/{jobId}`.

    * the same job id with the same body returns the stored job (200), it never asks twice;
    * the same job id with another body is 409 `chat_job_conflict` and changes nothing;
    * a conversation with a queued/running job refuses a new job id: 409 `chat_session_busy`.
    """
    job, accepted = state.chats.submit(principal, session_id, body)
    if not accepted:
        response.status_code = 200
    return job


@router.get("/jobs/{job_id}", response_model=ChatJob)
def get_job(job_id: JobId, principal: Session, state: State) -> ChatJob:
    """Status and, once completed, the saved result of a job. 404 means the server looked and has no such job;
    a failing read is a 5xx and must not be taken for 'unregistered'."""
    return state.chats.job(principal, job_id)


@router.post(
    "/jobs/{job_id}/retry",
    response_model=ChatJob,
    status_code=202,
    responses={200: {"model": ChatJob, "description": "Nothing to retry: the job is running or completed."}},
)
def retry_job(job_id: JobId, principal: Session, state: State, response: Response) -> ChatJob:
    """Retry a failed job *only where allowed*: a confirmed temporary failure runs again with the frozen context; a
    failed save of a kept verified result is saved again without asking the engine. A failed validation, a lost
    result or an unclassified error is 409 `chat_job_not_retryable` -- send a new question instead."""
    job, started = state.chats.retry(principal, job_id)
    if not started:
        response.status_code = 200
    return job


@router.post("/jobs/{job_id}/cancel", response_model=ChatJob)
def cancel_job(job_id: JobId, principal: Session, state: State) -> ChatJob:
    """Cancel a queued/running job. Closing the panel or starting a new conversation never cancels."""
    return state.chats.cancel(principal, job_id)
