from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from ..admin_schemas import (
    CorrectionOut,
    CorrectionRequest,
    ReasonRequest,
    RoundDetail,
    RoundList,
    RoundOut,
    SuspensionRequest,
)
from ..deps import Admin, State, require_admin
from . import ADMIN_ERROR_RESPONSES

router = APIRouter(
    prefix="/api/admin/briefings",
    tags=["admin-briefings"],
    dependencies=[Depends(require_admin)],
    responses=ADMIN_ERROR_RESPONSES,
)

RoundId = Annotated[str, Path(max_length=40)]


@router.get("", response_model=RoundList)
def list_rounds(
    state: State,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> RoundList:
    """Rounds newest first (default: the last 14 days), including scheduled and missing ones."""
    return state.admin.briefings.rounds(from_, to)


@router.get("/{round_id}", response_model=RoundDetail)
def get_round(round_id: RoundId, state: State) -> RoundDetail:
    return state.admin.briefings.detail(round_id)


@router.post("/{round_id}/reprocess", response_model=RoundOut, status_code=202)
def reprocess(round_id: RoundId, body: ReasonRequest, state: State, admin: Admin) -> RoundOut:
    """Generate a missing or failed round again. A published round is never replaced (409)."""
    return state.admin.briefings.reprocess(round_id, admin.actor, body.reason)


@router.post("/{round_id}/corrections", response_model=CorrectionOut, status_code=201)
def add_correction(round_id: RoundId, body: CorrectionRequest, state: State, admin: Admin) -> CorrectionOut:
    """Append a correction beside the published text (original, correction, reason and time stay separate)."""
    return state.admin.briefings.add_correction(
        round_id, admin.actor, event_id=body.event_id, corrected=body.corrected_text, reason=body.reason
    )


@router.post("/{round_id}/suspension", response_model=RoundOut)
def set_suspension(round_id: RoundId, body: SuspensionRequest, state: State, admin: Admin) -> RoundOut:
    """Suspend or resume serving a published round. The reason is shown to users as written."""
    return state.admin.briefings.set_suspension(round_id, admin.actor, action=body.action, reason=body.reason)

