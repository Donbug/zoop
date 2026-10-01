"""Audit trail (who, when, what, why) and the injectable clock every admin service shares."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from .statedb import StateDb, dumps, utc_iso


class Clock:
    """Wall clock with an offset hook so tests can move time without sleeping."""

    def __init__(self) -> None:
        self.offset = timedelta(0)

    def now(self) -> datetime:
        return datetime.now(UTC) + self.offset

    def advance(self, seconds: float) -> None:
        self.offset += timedelta(seconds=seconds)

    def travel_to(self, moment: datetime) -> None:
        """Make ``now()`` read ``moment`` (and keep ticking); for tests and demos."""
        self.offset = moment - datetime.now(UTC)


@dataclass(frozen=True)
class Actor:
    kind: Literal["admin", "system"]
    id: str
    email: str | None = None


SYSTEM_SCHEDULER = Actor("system", "scheduler")
SYSTEM_STARTUP = Actor("system", "startup")
SYSTEM_JOB_RUNNER = Actor("system", "job-runner")

Outcome = Literal["ok", "denied", "failed"]


class AuditLog:
    def __init__(self, db: StateDb, clock: Clock):
        self._db = db
        self._clock = clock

    def record(
        self,
        actor: Actor,
        action: str,
        target_type: str,
        target_id: str | None = None,
        *,
        reason: str | None = None,
        outcome: Outcome = "ok",
        detail: dict[str, Any] | None = None,
    ) -> int:
        cursor = self._db.execute(
            "INSERT INTO audit_log(at,actor_kind,actor_id,actor_email,action,target_type,target_id,reason,outcome,detail)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                utc_iso(self._clock.now()),
                actor.kind,
                actor.id,
                actor.email,
                action,
                target_type,
                target_id,
                reason,
                outcome,
                dumps(detail or {}),
            ),
        )
        return int(cursor.lastrowid or 0)

    def page(
        self,
        *,
        action: str | None = None,
        actor: str | None = None,
        target_type: str | None = None,
        q: str | None = None,
        limit: int = 50,
        cursor: int | None = None,
    ) -> tuple[list[dict[str, Any]], int | None]:
        clauses, params = ["1=1"], []
        if action:
            clauses.append("action LIKE ?")
            params.append(action.replace("%", "") + "%")
        if actor:
            clauses.append("(actor_id = ? OR actor_email = ?)")
            params += [actor, actor]
        if target_type:
            clauses.append("target_type = ?")
            params.append(target_type)
        if q:
            like = f"%{q}%"
            clauses.append("(target_id LIKE ? OR reason LIKE ? OR actor_email LIKE ? OR action LIKE ?)")
            params += [like, like, like, like]
        if cursor is not None:
            clauses.append("id < ?")
            params.append(cursor)
        rows = self._db.query(
            f"SELECT * FROM audit_log WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ?",
            [*params, limit + 1],
        )
        more = len(rows) > limit
        rows = rows[:limit]
        items = [
            {
                "id": r["id"],
                "at": r["at"],
                "actor_kind": r["actor_kind"],
                "actor_id": r["actor_id"],
                "actor_email": r["actor_email"],
                "action": r["action"],
                "target_type": r["target_type"],
                "target_id": r["target_id"],
                "reason": r["reason"],
                "outcome": r["outcome"],
                "detail": json.loads(r["detail"]),
            }
            for r in rows
        ]
        return items, (rows[-1]["id"] if more and rows else None)

    def count_since(self, since: datetime) -> int:
        row = self._db.one("SELECT COUNT(*) AS n FROM audit_log WHERE at >= ?", (utc_iso(since),))
        return int(row["n"]) if row else 0
