"""Member management for administrators (requirement 78).

Members are listed under pseudonymous ids (``M-XXXXXXXX``) with a masked e-mail address; the real id, the
e-mail address and the display name never leave this module. Blocking and unblocking need a reason, are
idempotent and are audited; blocking also ends the member's open sessions (``AccountStore.set_status``).
"""

from __future__ import annotations

from collections import Counter
from typing import Literal

from .accounts import AccountStore, UserState
from .audit import Actor, AuditLog, Clock
from .errors import ApiError
from .insights_common import SubjectKeys
from .insights_schemas import (
    MemberAction,
    MemberActivity,
    MemberCounts,
    MemberDetail,
    MemberList,
    MemberRow,
    MemberStatusResult,
)
from .statedb import StateDb

Status = Literal["active", "blocked"]


def mask_email(email: str) -> str:
    """``demo@zoop.local`` -> ``d***@zoop.local``."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else f"{local[:1]}***"


class MemberAdminService:
    def __init__(self, db: StateDb, clock: Clock, keys: SubjectKeys, audit: AuditLog, accounts: AccountStore):
        self._db = db
        self._clock = clock
        self._keys = keys
        self._audit = audit
        self._accounts = accounts

    def pseudonym(self, member: UserState) -> str:
        return self._keys.pseudonym("member", member.id)

    def _find(self, pseudonym: str) -> UserState:
        for member in self._accounts.members():
            if self.pseudonym(member) == pseudonym:
                return member
        raise ApiError(404, "member_not_found", "회원을 찾을 수 없습니다.")

    def _activity(self) -> dict[str, Counter[str]]:
        stats: dict[str, Counter[str]] = {}
        for r in self._db.query(
            "SELECT subject, type, COUNT(*) AS n FROM telemetry_events WHERE subject_kind='member'"
            " AND type IN ('graph_node_select','graph_edge_select','briefing_view') GROUP BY subject, type"
        ):
            counter = stats.setdefault(r["subject"], Counter())
            counter["graph" if r["type"] != "briefing_view" else "briefing"] += r["n"]
        for r in self._db.query(
            "SELECT s.owner_id AS owner, COUNT(*) AS n FROM chat_messages m JOIN chat_sessions s ON s.id=m.session_id"
            " WHERE s.owner_kind='member' GROUP BY s.owner_id"
        ):
            stats.setdefault(r["owner"], Counter())["ai"] += r["n"]
        return stats

    def _row(self, member: UserState, sessions: dict[str, int], activity: dict[str, Counter[str]]) -> MemberRow:
        mine = activity.get(member.id, Counter())
        return MemberRow(
            id=self.pseudonym(member),
            email_masked=mask_email(member.email),
            signup_method=member.signup_method,
            created_at=member.created_at,
            last_active_at=member.last_active_at,
            status=member.status,
            activity=MemberActivity(
                sessions=sessions.get(member.id, 0),
                graph_selections=mine["graph"],
                ai_questions=mine["ai"],
                briefing_views=mine["briefing"],
            ),
        )

    def page(self, *, status: Status | None, q: str | None, limit: int, offset: int) -> MemberList:
        members = self._accounts.members()
        sessions, activity = self._accounts.session_counts(), self._activity()
        rows = [self._row(m, sessions, activity) for m in members]
        rows.sort(key=lambda r: (r.created_at, r.id), reverse=True)
        counts = MemberCounts(
            all=len(rows),
            active=sum(1 for r in rows if r.status == "active"),
            blocked=sum(1 for r in rows if r.status == "blocked"),
        )
        if status:
            rows = [r for r in rows if r.status == status]
        needle = (q or "").strip().lower()
        if needle:
            rows = [r for r in rows if needle in r.id.lower() or needle in r.email_masked.lower()]
        page = rows[offset : offset + limit]
        return MemberList(items=page, next_cursor=str(offset + limit) if offset + limit < len(rows) else None, counts=counts)

    def detail(self, pseudonym: str) -> MemberDetail:
        member = self._find(pseudonym)
        votes = {
            r["value"]: r["n"]
            for r in self._db.query(
                "SELECT value, COUNT(*) AS n FROM feedback WHERE subject_kind='member' AND subject=? GROUP BY value",
                (member.id,),
            )
        }
        history = [
            MemberAction(at=r["at"], action=r["action"], reason=r["reason"], admin_email=r["actor_email"])
            for r in self._db.query(
                "SELECT at, action, reason, actor_email FROM audit_log WHERE target_type='member' AND target_id=?"
                " AND action IN ('member.block','member.unblock') ORDER BY id DESC LIMIT 20",
                (pseudonym,),
            )
        ]
        return MemberDetail(
            member=self._row(member, self._accounts.session_counts(), self._activity()),
            onboarding_completed=member.completed,
            tutorial_completed=member.tutorial_completed,
            watchlist_count=len(member.watchlist_ids),
            holding_count=len(member.connection.holdings) if member.connection else 0,
            account_connected=member.connection is not None,
            feedback_up=votes.get("up", 0),
            feedback_down=votes.get("down", 0),
            history=history,
        )

    def set_status(self, pseudonym: str, status: Status, reason: str, admin: Actor) -> MemberStatusResult:
        """Block or unblock. A repeated call changes nothing and writes no second audit entry."""
        reason = reason.strip()
        if not reason:
            raise ApiError(422, "reason_required", "사유를 입력해 주세요.")
        member = self._find(pseudonym)
        with self._db.transaction():  # the status change and its audit entry stand or fall together
            changed = self._accounts.set_status(member.id, status)
            if changed:
                self._audit.record(
                    admin,
                    "member.block" if status == "blocked" else "member.unblock",
                    "member",
                    pseudonym,
                    reason=reason,
                )
        return MemberStatusResult(changed=changed, detail=self.detail(pseudonym))
