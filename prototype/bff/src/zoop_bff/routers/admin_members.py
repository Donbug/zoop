from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query

from ..admin_schemas import ReasonRequest
from ..deps import Admin, State, require_admin
from ..errors import ApiError
from ..insights_schemas import MemberDetail, MemberList, MemberStatusResult
from . import ADMIN_ERROR_RESPONSES

router = APIRouter(
    prefix="/api/admin/members",
    tags=["admin-members"],
    dependencies=[Depends(require_admin)],
    responses=ADMIN_ERROR_RESPONSES,
)

MemberId = Annotated[str, Path(max_length=20, description="Pseudonymous member id, e.g. M-3FA9C2D1")]


@router.get("", response_model=MemberList)
def members(
    state: State,
    status: Literal["active", "blocked"] | None = None,
    q: Annotated[str | None, Query(max_length=100, description="Matches the pseudonymous id or the masked e-mail")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(description="Offset returned as nextCursor")] = None,
) -> MemberList:
    """Members under pseudonymous ids with masked e-mail, sign-up method, times, activity and status.

    The demo administrator is an admin account, not a member, and never appears here.
    """
    if cursor is not None and not cursor.isdigit():
        raise ApiError(422, "invalid_cursor", "cursor가 올바르지 않습니다.")
    return state.insights.members.page(status=status, q=q, limit=limit, offset=int(cursor or 0))


@router.get("/{member_id}", response_model=MemberDetail)
def member(member_id: MemberId, state: State) -> MemberDetail:
    return state.insights.members.detail(member_id)


@router.post("/{member_id}/block", response_model=MemberStatusResult)
def block(member_id: MemberId, body: ReasonRequest, state: State, admin: Admin) -> MemberStatusResult:
    """Block a member: every open session ends now, the next request of an open tab is refused with
    ``member_blocked`` and login is refused. Needs a reason (audited); repeating the call is a no-op
    (``changed: false``, no second audit entry)."""
    return state.insights.members.set_status(member_id, "blocked", body.reason, admin.actor)


@router.post("/{member_id}/unblock", response_model=MemberStatusResult)
def unblock(member_id: MemberId, body: ReasonRequest, state: State, admin: Admin) -> MemberStatusResult:
    """Lift a block (reason required, audited, idempotent). The member can log in again."""
    return state.insights.members.set_status(member_id, "active", body.reason, admin.actor)
