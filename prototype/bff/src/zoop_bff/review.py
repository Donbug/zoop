"""Admin review decisions (requirement 76) and their overlay on an inspect()-shaped payload.

The PoC ledger is never edited. A decision is a record in the BFF state directory; the user-facing
dataset is built from ``apply_reviews(active graph version, effective decisions)``.

* ``reject`` (candidate or relation) removes it from the published view immediately.
* ``allow`` of a HOLD candidate builds a public issue from the candidate's own mention, articles,
  relations and evidence, and marks it ``zoop_approval`` (shown as "관리자 승인").
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .audit import Clock
from .statedb import StateDb, dumps, utc_iso

TargetType = Literal["candidate", "relation"]
Verdict = Literal["allow", "reject"]
APPROVAL_LABEL = "관리자 승인"


@dataclass(frozen=True)
class Decision:
    id: int
    target_type: TargetType
    target_id: str
    decision: Verdict
    reason: str
    admin_id: str
    admin_email: str
    at: str
    origin: Literal["admin", "snapshot-migration"]
    payload: dict[str, Any] | None = None


def _decision(row: Any) -> Decision:
    return Decision(
        id=row["id"],
        target_type=row["target_type"],
        target_id=row["target_id"],
        decision=row["decision"],
        reason=row["reason"],
        admin_id=row["admin_id"],
        admin_email=row["admin_email"],
        at=row["at"],
        origin=row["origin"],
        payload=json.loads(row["payload"]) if row["payload"] else None,
    )


class ReviewStore:
    def __init__(self, db: StateDb, clock: Clock):
        self._db = db
        self._clock = clock

    def revision(self) -> int:
        row = self._db.one("SELECT COALESCE(MAX(id),0) AS r FROM review_decisions")
        return int(row["r"]) if row else 0

    def effective(self) -> list[Decision]:
        rows = self._db.query(
            "SELECT * FROM review_decisions WHERE id IN "
            "(SELECT MAX(id) FROM review_decisions GROUP BY target_type, target_id) ORDER BY id"
        )
        return [_decision(r) for r in rows]

    def current(self, target_type: str, target_id: str) -> Decision | None:
        row = self._db.one(
            "SELECT * FROM review_decisions WHERE target_type=? AND target_id=? ORDER BY id DESC LIMIT 1",
            (target_type, target_id),
        )
        return _decision(row) if row else None

    def history(self, target_type: str, target_id: str) -> list[Decision]:
        rows = self._db.query(
            "SELECT * FROM review_decisions WHERE target_type=? AND target_id=? ORDER BY id DESC",
            (target_type, target_id),
        )
        return [_decision(r) for r in rows]

    def record(
        self,
        target_type: TargetType,
        target_id: str,
        decision: Verdict,
        reason: str,
        *,
        admin_id: str,
        admin_email: str,
        payload: dict[str, Any] | None = None,
        origin: Literal["admin", "snapshot-migration"] = "admin",
        at: str | None = None,
    ) -> tuple[Decision, bool]:
        """(decision, idempotent). A repeat of the effective decision writes nothing."""
        with self._db.transaction() as conn:
            current = self.current(target_type, target_id)
            if current is not None and current.decision == decision:
                return current, True
            cursor = conn.execute(
                "INSERT INTO review_decisions(target_type,target_id,decision,reason,admin_id,admin_email,at,origin,payload)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    target_type,
                    target_id,
                    decision,
                    reason,
                    admin_id,
                    admin_email,
                    at or utc_iso(self._clock.now()),
                    origin,
                    dumps(payload) if payload is not None else None,
                ),
            )
            row = conn.execute("SELECT * FROM review_decisions WHERE id=?", (cursor.lastrowid,)).fetchone()
        return _decision(row), False

    def migrate_exclusions(self, entries: Iterable[Mapping[str, Any]], at: str) -> int:
        """Seed snapshot ``review_exclusions`` as relation rejections (initial review records)."""
        migrated = 0
        for entry in entries:
            relation_id = entry.get("relation_id") if isinstance(entry, Mapping) else None
            reason = entry.get("reason") if isinstance(entry, Mapping) else None
            if not isinstance(relation_id, str) or not relation_id:
                continue
            _, idempotent = self.record(
                "relation",
                relation_id,
                "reject",
                reason if isinstance(reason, str) and reason else "스냅샷 review_exclusions에서 이관",
                admin_id="system-snapshot",
                admin_email="snapshot-migration",
                origin="snapshot-migration",
                at=at,
            )
            migrated += 0 if idempotent else 1
        return migrated


# --------------------------------------------------------------------------- overlay


def _source_support(articles: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        from investmate.storage import PostgresRepository

        return PostgresRepository._source_support(articles)  # PoC lineage counting, no I/O
    except Exception:  # bodies absent (inspect without evidence): counts only, never guessed
        ids = [a["article_id"] for a in articles]
        return {
            "article_count": len(ids),
            "known_lineage_count": None,
            "unknown_lineage_articles": [],
            "independent_source_count": None,
            "duplicate_groups": [],
        }


def _strip_unapproved_fields(mention: dict[str, Any], outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    result = dict(mention)
    for outcome in outcomes:
        if outcome.get("decision") != "ALLOW":
            result.pop(outcome.get("field", ""), None)
    return result


def has_quote(row: Mapping[str, Any]) -> bool:
    """A candidate may be allowed only when its own mention cites at least one non-empty quote."""
    evidence = (row.get("candidate") or {}).get("mention", {}).get("evidence") or []
    return any(isinstance(e, dict) and str(e.get("quote") or "").strip() for e in evidence)


def candidate_mention_ids(payload: Mapping[str, Any]) -> dict[str, str]:
    """candidate_id -> mention_id, from published field decisions and the audit rows."""
    mapping: dict[str, str] = {}
    for issue in payload.get("issues") or []:
        for fd in issue.get("field_decisions") or []:
            if fd.get("candidate_id") and fd.get("mention_id"):
                mapping[fd["candidate_id"]] = fd["mention_id"]
    for row in payload.get("candidates") or []:
        cand = row.get("candidate") or {}
        mention = cand.get("mention") or {}
        if cand.get("candidate_id") and mention.get("mention_id"):
            mapping.setdefault(cand["candidate_id"], mention["mention_id"])
    return mapping


def published_candidate_ids(payload: Mapping[str, Any]) -> set[str]:
    return {c for issue in payload.get("issues") or [] for c in issue.get("candidate_ids") or []}


def published_relation_ids(payload: Mapping[str, Any]) -> set[str]:
    return {
        r["relation_id"]
        for issue in payload.get("issues") or []
        for r in issue.get("relations") or []
        if "relation_id" in r
    }


def apply_reviews(payload: dict[str, Any], decisions: Iterable[Decision]) -> dict[str, Any]:
    """Return ``payload`` with effective admin decisions applied (never mutates the input)."""
    effective = list(decisions)
    if not effective:
        return payload
    rejected_candidates = {d.target_id for d in effective if d.target_type == "candidate" and d.decision == "reject"}
    rejected_relations = {d.target_id for d in effective if d.target_type == "relation" and d.decision == "reject"}
    allowed_candidates = [d for d in effective if d.target_type == "candidate" and d.decision == "allow" and d.payload]
    allowed_relations = [d for d in effective if d.target_type == "relation" and d.decision == "allow" and d.payload]
    mention_of = candidate_mention_ids(payload)

    out = dict(payload)
    issues: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for original in payload.get("issues") or []:
        issue = _without_rejected(original, rejected_candidates, rejected_relations, mention_of)
        if issue is not None:
            issues[issue["issue_id"]] = issue
            order.append(issue["issue_id"])

    admin_candidate_ids: set[str] = set()
    for d in allowed_candidates:
        row = d.payload or {}
        cid = (row.get("candidate") or {}).get("candidate_id")
        if not cid or any(cid in i.get("candidate_ids", []) for i in issues.values()):
            continue  # already published by the PoC
        issue_id = row["candidate"]["issue_id"]
        if issue_id not in issues:
            order.append(issue_id)
        issues[issue_id] = _with_admin_candidate(issues.get(issue_id), row, rejected_relations)
        admin_candidate_ids.add(cid)

    for d in allowed_relations:
        spec = d.payload or {}
        relation, issue_id = spec.get("relation"), spec.get("issue_id")
        if issue_id not in issues or not isinstance(relation, dict) or not relation.get("evidence"):
            continue
        if relation["relation_id"] in {r["relation_id"] for r in issues[issue_id].get("relations", [])}:
            continue
        issue = copy.copy(issues[issue_id])
        issue["relations"] = [*issue.get("relations", []), {**relation, "candidate_ids": []}]
        approval = dict(issue.get("zoop_approval") or _approval(scope="relation"))
        approval["relation_ids"] = [*approval.get("relation_ids", []), relation["relation_id"]]
        issue["zoop_approval"] = approval
        issues[issue_id] = issue

    out["issues"] = [issues[i] for i in order]
    if admin_candidate_ids:  # the audit row says HOLD; the admin decision supersedes it for gating
        out["candidates"] = [
            row
            for row in payload.get("candidates") or []
            if (row.get("candidate") or {}).get("candidate_id") not in admin_candidate_ids
        ]
    return out


def _approval(*, scope: str) -> dict[str, Any]:
    return {
        "source": "admin-review",
        "label": APPROVAL_LABEL,
        "scope": scope,
        "candidate_ids": [],
        "relation_ids": [],
    }


def _without_rejected(
    issue: dict[str, Any],
    rejected_candidates: set[str],
    rejected_relations: set[str],
    mention_of: Mapping[str, str],
) -> dict[str, Any] | None:
    cids = issue.get("candidate_ids") or []
    drop = [c for c in cids if c in rejected_candidates]
    relations = issue.get("relations") or []
    touched = bool(drop) or any(r.get("relation_id") in rejected_relations for r in relations)
    if not touched:
        return issue
    keep_cids = [c for c in cids if c not in rejected_candidates]
    kept_mentions = {mention_of[c] for c in keep_cids if c in mention_of}
    dropped_mentions = {mention_of[c] for c in drop if c in mention_of} - kept_mentions
    mentions = [m for m in issue.get("mentions") or [] if m.get("mention_id") not in dropped_mentions]
    if drop and not keep_cids:
        return None  # every candidate behind the issue was rejected
    if drop and not mentions:
        return None
    kept_relations = []
    for r in relations:
        if r.get("relation_id") in rejected_relations:
            continue
        owners = r.get("candidate_ids") or []
        if owners and all(o in rejected_candidates for o in owners):
            continue
        kept_relations.append(r)
    referenced = {m.get("article_id") for m in mentions}
    referenced |= {r["source"] for r in kept_relations if r.get("relation_type") in ("REPORTS", "PROVIDES_BACKGROUND")}
    articles = [a for a in issue.get("articles") or [] if a.get("article_id") in referenced]
    result = dict(issue)
    result.update(
        mentions=mentions,
        relations=kept_relations,
        articles=articles,
        candidate_ids=keep_cids,
        field_decisions=[
            fd for fd in issue.get("field_decisions") or [] if fd.get("candidate_id") not in rejected_candidates
        ],
        source_support=_source_support(articles),
    )
    return result


def _with_admin_candidate(
    base: dict[str, Any] | None, row: Mapping[str, Any], rejected_relations: set[str]
) -> dict[str, Any]:
    candidate = row["candidate"]
    outcomes = (row.get("validation") or {}).get("field_verdicts") or []
    mention = _strip_unapproved_fields(candidate["mention"], outcomes)
    issue = dict(base) if base else {
        "issue_id": candidate["issue_id"],
        "mentions": [],
        "articles": [],
        "relations": [],
        "candidate_ids": [],
        "field_decisions": [],
    }
    cid = candidate["candidate_id"]
    if mention["mention_id"] not in {m.get("mention_id") for m in issue["mentions"]}:
        issue["mentions"] = [*issue["mentions"], mention]
    have_articles = {a.get("article_id") for a in issue["articles"]}
    issue["articles"] = [*issue["articles"], *(a for a in candidate.get("articles") or [] if a["article_id"] not in have_articles)]
    relations = {r["relation_id"]: r for r in issue["relations"]}
    for r in candidate.get("relations") or []:
        if r["relation_id"] in rejected_relations or not r.get("evidence"):
            continue
        if r["relation_id"] in relations:
            owners = relations[r["relation_id"]].get("candidate_ids", [])
            relations[r["relation_id"]] = {**relations[r["relation_id"]], "candidate_ids": [*owners, cid]}
        else:
            relations[r["relation_id"]] = {**r, "candidate_ids": [cid]}
    issue["relations"] = list(relations.values())
    issue["candidate_ids"] = [*issue.get("candidate_ids", []), cid]
    issue["field_decisions"] = [
        *issue.get("field_decisions", []),
        {"candidate_id": cid, "mention_id": mention["mention_id"], "outcomes": outcomes},
    ]
    issue["source_support"] = _source_support(issue["articles"])
    approval = dict(issue.get("zoop_approval") or _approval(scope="issue"))
    approval["candidate_ids"] = [*approval.get("candidate_ids", []), cid]
    issue["zoop_approval"] = approval
    return issue
