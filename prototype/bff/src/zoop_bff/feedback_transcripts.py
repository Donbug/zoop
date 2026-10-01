"""AI conversation transcripts for administrators (requirement 75).

The stored text is the original; masking (``masking.Masker``) is applied on every read, so what an
administrator gets never contains an e-mail address, phone/card/account/resident number, or the writer's own
name. Opening a transcript is itself an audited action (``transcript.view``). Users are shown by pseudonym.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from .accounts import AccountStore
from .audit import Actor, AuditLog, Clock
from .chat import resolve_context
from .dataset import Dataset
from .errors import ApiError
from .feedback import FeedbackService
from .insights_common import SubjectKeys
from .insights_schemas import (
    MaskingReport,
    TranscriptDetail,
    TranscriptFeedback,
    TranscriptMessage,
    TranscriptPage,
    TranscriptSummary,
)
from .masking import RULES, Masker, merge
from .statedb import StateDb


class TranscriptService:
    def __init__(self, db: StateDb, clock: Clock, keys: SubjectKeys, audit: AuditLog, accounts: AccountStore, feedback: FeedbackService):
        self._db = db
        self._clock = clock
        self._keys = keys
        self._audit = audit
        self._accounts = accounts
        self._feedback = feedback

    def _masker(self, owner_kind: str, owner_id: str) -> Masker:
        return self._feedback.masker_for_member(owner_id if owner_kind == "member" else None)

    def _pseudonym(self, owner_kind: str, owner_id: str) -> str:
        subject = self._keys.subject(owner_kind, owner_id)  # type: ignore[arg-type]
        return self._keys.pseudonym(subject.kind, subject.id)

    def page(self, *, disliked_only: bool, limit: int, offset: int) -> TranscriptPage:
        where = "(s.messages > 0 OR EXISTS (SELECT 1 FROM chat_jobs j WHERE j.session_id=s.id))"
        if disliked_only:
            where += (
                " AND EXISTS (SELECT 1 FROM chat_messages m JOIN feedback f ON f.feature='chatbot_answer'"
                " AND f.target_id=m.id AND f.value='down' WHERE m.session_id=s.id)"
            )
        total = int(self._db.one(f"SELECT COUNT(*) AS n FROM chat_sessions s WHERE {where}")["n"])  # type: ignore[index]
        rows = self._db.query(
            f"SELECT s.id, s.owner_id, s.owner_kind, s.created_at,"
            " COALESCE((SELECT MAX(at) FROM chat_messages m WHERE m.session_id=s.id),"
            " (SELECT MAX(updated_at) FROM chat_jobs j WHERE j.session_id=s.id)) AS last_at,"
            " COALESCE((SELECT question FROM chat_messages m WHERE m.session_id=s.id ORDER BY seq LIMIT 1),"
            " (SELECT json_extract(request, '$.question') FROM chat_jobs j WHERE j.session_id=s.id ORDER BY seq LIMIT 1)) AS first_question,"
            f" s.messages FROM chat_sessions s WHERE {where} ORDER BY last_at DESC, s.id LIMIT ? OFFSET ?",
            (limit, offset),
        )
        votes: dict[str, list[int]] = {}
        if rows:
            marks = ",".join("?" for _ in rows)
            for v in self._db.query(
                "SELECT m.session_id AS session_id, f.value AS value, COUNT(*) AS n FROM feedback f"
                " JOIN chat_messages m ON m.id=f.target_id WHERE f.feature='chatbot_answer'"
                f" AND m.session_id IN ({marks}) GROUP BY m.session_id, f.value",
                [r["id"] for r in rows],
            ):
                votes.setdefault(v["session_id"], [0, 0])[0 if v["value"] == "up" else 1] = v["n"]
        items = []
        for r in rows:
            preview = self._masker(r["owner_kind"], r["owner_id"]).mask(r["first_question"] or "")[0]
            up, down = votes.get(r["id"], [0, 0])
            items.append(
                TranscriptSummary(
                    id=r["id"],
                    user=self._pseudonym(r["owner_kind"], r["owner_id"]),
                    user_kind=r["owner_kind"],
                    started_at=r["created_at"],
                    last_at=r["last_at"],
                    messages=r["messages"],
                    preview=preview if len(preview) <= 80 else preview[:79] + "…",
                    up=up,
                    down=down,
                )
            )
        return TranscriptPage(items=items, next_cursor=str(offset + limit) if offset + limit < total else None, total=total)

    def detail(self, session_id: str, ds: Dataset | None, admin: Actor) -> TranscriptDetail:
        session = self._db.one("SELECT * FROM chat_sessions WHERE id=?", (session_id,))
        if session is None:
            raise ApiError(404, "transcript_not_found", "대화록을 찾을 수 없습니다.")
        masker = self._masker(session["owner_kind"], session["owner_id"])
        rows = self._db.query("SELECT * FROM chat_messages WHERE session_id=? ORDER BY seq", (session_id,))
        votes = self._feedback.message_votes([r["id"] for r in rows], masker)
        counters: list[Counter[str]] = []

        def masked(text: str) -> str:
            out, counts = masker.mask(text)
            counters.append(counts)
            return out

        messages = []
        for r in rows:
            up, down, reasons = votes.get(r["id"], (0, 0, []))
            messages.append(
                TranscriptMessage(
                    id=r["id"],
                    seq=r["seq"],
                    at=r["at"],
                    question=masked(r["question"]),
                    answer=masked(r["answer"]),
                    status=r["status"],
                    reason=r["reason"],
                    context_labels=self._labels(ds, json.loads(r["context_ids"])),
                    citation_count=r["citation_count"],
                    feedback=TranscriptFeedback(up=up, down=down, reasons=reasons),
                )
            )
        # Questions that never produced a saved answer (failed, cancelled, still running) belong to the record too.
        for job in self._db.query("SELECT * FROM chat_jobs WHERE session_id=? AND status != 'completed' ORDER BY seq", (session_id,)):
            request = json.loads(job["request"])
            messages.append(
                TranscriptMessage(
                    id=job["id"],
                    seq=job["seq"],
                    at=job["updated_at"],
                    question=masked(request["question"]),
                    answer="",
                    status=job["status"],
                    reason=job["failure_reason"] or job["failure"],
                    context_labels=[c["label"] for c in request["contexts"]],
                    citation_count=0,
                    feedback=TranscriptFeedback(up=0, down=0, reasons=[]),
                )
            )
        messages.sort(key=lambda m: m.seq)
        user = self._pseudonym(session["owner_kind"], session["owner_id"])
        report = MaskingReport(rules=RULES, counts=merge(counters))
        self._audit.record(
            admin,
            "transcript.view",
            "chat-session",
            session_id,
            detail={"user": user, "messages": len(messages), "masked": report.counts},
        )
        return TranscriptDetail(
            id=session["id"],
            user=user,
            user_kind=session["owner_kind"],
            started_at=session["created_at"],
            messages=messages,
            masking=report,
        )

    @staticmethod
    def _labels(ds: Dataset | None, context_ids: list[str]) -> list[str]:
        labels: list[str] = []
        for context_id in context_ids:
            node: Any = resolve_context(ds, context_id) if ds else None
            labels.append(node.label if node else context_id)
        return labels
