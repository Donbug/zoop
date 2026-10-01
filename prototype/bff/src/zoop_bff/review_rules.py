"""Publication rules over the PoC's HOLD candidates (requirement 76).

A rule never edits the PoC ledger or a stored graph version. It is evaluated at read time on the
``candidates`` audit rows of whichever version is active (``review.apply_reviews``), so a version
published later is covered the same way, and switching a rule off takes its content off again.

R1 "역할 문구 미확인은 역할만 빼고 게시": the PoC verifier checks every participant's role
(``participant_role:N``, "performed the exact claimed action role, preserving direction") and every
relation's ``role`` independently. Most HOLD candidates fail only there while the event itself, its
company involvement and its quotes pass. R1 publishes such a candidate and leaves the unconfirmed role
text empty; it never fills it with another value. The PoC's own handling of optional fields
(event_time, period, countries) is unchanged: a field that did not pass is dropped, the rest is published.

R1@2 (R1@1 published every relation the candidate carried): a FOLLOWS relation is published only when the
follow-side event, the candidate's own mention, has ``assertion_status`` "occurred". The PoC's ``sequence``
check passed plans and forecasts as follow-ups too (all 7 such PoC-approved pairs in the expanded ledger were
rejected on manual review: a plan is not a later development that has happened), while both occurred pairs
read fine; see docs/evidence/review-policy.md.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from investmate.domain import Article, Evidence
from pydantic import ValidationError

from .audit import Clock
from .statedb import StateDb, utc_iso

RULE_R1 = "R1@2"
RULE_LABEL = "자동 검수 규칙"

# jev.parse_response: "Support or contradiction probability requires review: <check>, <check>" (+ numeric notes).
_REVIEW_PREFIX = "Support or contradiction probability requires review: "
_DIAGNOSTICS = " Numerical diagnostics: "
_PARTICIPANT_ROLE = re.compile(r"participant_role:(\d+)")


@dataclass(frozen=True)
class RuleDef:
    id: str
    title: str
    summary: str
    default_enabled: bool


RULES: dict[str, RuleDef] = {
    RULE_R1: RuleDef(
        id=RULE_R1,
        title="역할 문구 미확인은 역할만 빼고 게시",
        summary=(
            "보류 사유가 참여자·관계의 역할 문구 검사뿐이고 거부 판정이 없으며 원문 인용이 모두 있는 후보를 "
            "사건으로 게시합니다. 확인되지 않은 역할 문구는 비워 두고 다른 값으로 채우지 않습니다. "
            "이미 일어난 사건(발생)이 아니면 앞선 사건의 후속(FOLLOWS)으로 잇지 않습니다."
        ),
        default_enabled=True,
    )
}


@dataclass(frozen=True)
class RuleEffect:
    """What R1 leaves out of a candidate it publishes.

    ``participants``: indexes into ``mention.participants`` whose role is left empty; ``relations``: ids of
    relations whose role is left empty; ``dropped``: ids of relations R1 does not publish at all.
    """

    participants: tuple[int, ...]
    relations: tuple[str, ...]
    dropped: tuple[str, ...]


def _held_checks(reason: str) -> list[str] | None:
    """The checks named by a HOLD verdict reason, ``None`` for any other reason (web evidence, withheld field, ...)."""
    if not reason.startswith(_REVIEW_PREFIX):
        return None
    names = reason[len(_REVIEW_PREFIX) :].split(_DIAGNOSTICS, 1)[0].rstrip(".")
    checks = [name.strip() for name in names.split(",")]
    return checks if all(checks) else None


def _cites(evidence: Any) -> bool:
    return isinstance(evidence, list) and any(
        isinstance(e, Mapping) and str(e.get("quote") or "").strip() for e in evidence
    )


def _quotes_match(evidence: Sequence[Mapping[str, Any]], articles: Sequence[Article]) -> bool:
    """Every quote is the exact slice of a cited article body (PoC ``Evidence.matches``); no body = unverified."""
    for item in evidence:
        try:
            quote = Evidence.model_validate(item)
        except ValidationError:
            return False
        if not any(quote.matches(article) for article in articles):
            return False
    return True


def r1_effect(row: Mapping[str, Any]) -> RuleEffect | None:
    """R1 on one ``inspect()`` candidate row: what it leaves out, or ``None`` when R1 does not apply.

    Applies only when the candidate is active and HOLD, no verdict (or field verdict) is REJECT, every
    non-ALLOW verdict is caused by role checks alone (issue: ``participant_role:N``, relation: ``role``),
    and the mention and every relation cite quotes that match their article text.
    """
    if not row.get("active") or row.get("status") != "HOLD":
        return None
    candidate, validation = row.get("candidate"), row.get("validation")
    if not isinstance(candidate, Mapping) or not isinstance(validation, Mapping):
        return None
    mention = candidate.get("mention")
    verdicts = validation.get("verdicts")
    if not isinstance(mention, Mapping) or not isinstance(verdicts, list):
        return None
    participants = mention.get("participants") or []
    relations = [r for r in candidate.get("relations") or [] if isinstance(r, Mapping)]
    relation_ids = {r.get("relation_id") for r in relations}
    if any(isinstance(f, Mapping) and f.get("decision") == "REJECT" for f in validation.get("field_verdicts") or []):
        return None

    held_participants: set[int] = set()
    held_relations: set[str] = set()
    issue_held = False
    for verdict in verdicts:
        if not isinstance(verdict, Mapping) or verdict.get("decision") == "ALLOW":
            continue
        if verdict.get("decision") != "HOLD":
            return None  # REJECT (or anything unknown) is never overridden
        checks = _held_checks(str(verdict.get("reason") or ""))
        target = verdict.get("target")
        if not checks:
            return None
        if target == "issue":
            for check in checks:
                match = _PARTICIPANT_ROLE.fullmatch(check)
                if match is None or int(match[1]) >= len(participants):
                    return None
                held_participants.add(int(match[1]))
            issue_held = True
        elif target in relation_ids:
            if checks != ["role"]:
                return None
            held_relations.add(target)
        else:
            return None
    if not issue_held:
        return None  # the PoC status is the issue verdict; a HOLD without one is not understood

    if not relations or not _cites(mention.get("evidence")) or not all(_cites(r.get("evidence")) for r in relations):
        return None
    articles: list[Article] = []
    for raw in candidate.get("articles") or []:
        try:
            articles.append(Article.model_validate(raw))
        except ValidationError:
            continue
    if not _quotes_match(mention["evidence"], articles) or not all(_quotes_match(r["evidence"], articles) for r in relations):
        return None
    dropped = tuple(
        sorted(
            r["relation_id"]
            for r in relations
            if r.get("relation_type") == "FOLLOWS" and mention.get("assertion_status") != "occurred"
        )
    )
    return RuleEffect(tuple(sorted(held_participants)), tuple(sorted(held_relations)), dropped)


@dataclass(frozen=True)
class RuleChange:
    id: int
    rule_id: str
    enabled: bool
    reason: str
    admin_id: str
    admin_email: str
    at: str


def _change(row: Any) -> RuleChange:
    return RuleChange(
        id=row["id"],
        rule_id=row["rule_id"],
        enabled=bool(row["enabled"]),
        reason=row["reason"],
        admin_id=row["admin_id"],
        admin_email=row["admin_email"],
        at=row["at"],
    )


class RuleStore:
    """Append-only on/off history per rule; the newest row is the state, no row means the rule's default."""

    def __init__(self, db: StateDb, clock: Clock):
        self._db = db
        self._clock = clock

    def revision(self) -> int:
        row = self._db.one("SELECT COALESCE(MAX(id),0) AS r FROM review_rule_changes")
        return int(row["r"]) if row else 0

    def revision_at(self, moment: str) -> int:
        """The revision the log had at ``moment`` (a ``utc_iso`` string): for rounds published before they recorded theirs."""
        row = self._db.one("SELECT COALESCE(MAX(id),0) AS r FROM review_rule_changes WHERE at <= ?", (moment,))
        return int(row["r"]) if row else 0

    def current(self, rule_id: str, upto: int | None = None) -> RuleChange | None:
        row = self._db.one(
            "SELECT * FROM review_rule_changes WHERE rule_id=? AND id<=? ORDER BY id DESC LIMIT 1",
            (rule_id, 2**62 if upto is None else upto),
        )
        return _change(row) if row else None

    def enabled(self, rule_id: str, upto: int | None = None) -> bool:
        change = self.current(rule_id, upto)
        return RULES[rule_id].default_enabled if change is None else change.enabled

    def enabled_ids(self, upto: int | None = None) -> frozenset[str]:
        return frozenset(rule_id for rule_id in RULES if self.enabled(rule_id, upto))

    def history(self, rule_id: str) -> list[RuleChange]:
        rows = self._db.query("SELECT * FROM review_rule_changes WHERE rule_id=? ORDER BY id DESC", (rule_id,))
        return [_change(r) for r in rows]

    def switch(
        self, rule_id: str, enabled: bool, reason: str, *, admin_id: str, admin_email: str
    ) -> tuple[RuleChange | None, bool]:
        """(newest change, idempotent). Asking for the state the rule is already in writes nothing."""
        with self._db.transaction() as conn:
            if self.enabled(rule_id) == enabled:
                return self.current(rule_id), True
            cursor = conn.execute(
                "INSERT INTO review_rule_changes(rule_id,enabled,reason,admin_id,admin_email,at) VALUES (?,?,?,?,?,?)",
                (rule_id, int(enabled), reason, admin_id, admin_email, utc_iso(self._clock.now())),
            )
            row = conn.execute("SELECT * FROM review_rule_changes WHERE id=?", (cursor.lastrowid,)).fetchone()
        return _change(row), False
