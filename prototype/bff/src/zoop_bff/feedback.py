"""Like/dislike on AI output (requirement 75).

One voter has at most one vote per target (``feedback`` primary key). A vote can be switched or taken
back; a dislike may carry a short reason. Targets are the chatbot's answers, a published briefing round and
one of its key issues. News summaries have no producer in this prototype, so no vote target exists for them.
Administrators see counts, trends and reasons only with pseudonymous voter ids and masked text.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any, Literal

from .accounts import AccountStore
from .audit import Clock
from .briefing_rounds import parse_round_id
from .dataset import Dataset
from .insights_common import MIN_SAMPLE, SubjectKeys, Subject, day_range, kst_day, ratio, since_iso
from .insights_schemas import (
    FEATURE_LABEL,
    DislikePage,
    DislikeRow,
    FeedbackDay,
    FeedbackFeatureStat,
    FeedbackItem,
    FeedbackSummary,
    UnsupportedFeedbackFeature,
)
from .masking import Masker
from .statedb import StateDb, utc_iso

EDITION_LABEL = {"morning": "출근", "evening": "퇴근"}
UNSUPPORTED = [
    UnsupportedFeedbackFeature(
        feature="news_summary",
        label="뉴스 요약",
        reason="뉴스 요약을 만드는 기능이 아직 없어 평가할 대상이 없습니다.",
    )
]
BASIS = (
    "표본이 적은 비율은 숨기고 건수만 보여 줍니다. 한 사람이 같은 대상에 남길 수 있는 표는 1개이고, "
    "표를 바꾸면 바꾼 날짜 기준으로 다시 셉니다."
)


def issue_target(round_id: str, event_id: str) -> str:
    return f"{round_id}/{event_id}"


class FeedbackService:
    def __init__(self, db: StateDb, clock: Clock, keys: SubjectKeys, accounts: AccountStore):
        self._db = db
        self._clock = clock
        self._keys = keys
        self._accounts = accounts

    # ---- voting (user side)
    def set_vote(
        self, subject: Subject, feature: str, target_id: str, value: Literal["up", "down"], reason: str | None
    ) -> FeedbackItem:
        """Create or switch the voter's vote. Repeating the same vote changes nothing (idempotent)."""
        now = utc_iso(self._clock.now())
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT value, reason FROM feedback WHERE feature=? AND target_id=? AND subject=?",
                (feature, target_id, subject.id),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO feedback(feature,target_id,subject,subject_kind,value,reason,created_at,updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (feature, target_id, subject.id, subject.kind, value, reason, now, now),
                )
            elif row["value"] != value or row["reason"] != reason:
                conn.execute(
                    "UPDATE feedback SET value=?, reason=?, updated_at=? WHERE feature=? AND target_id=? AND subject=?",
                    (value, reason, now, feature, target_id, subject.id),
                )
        return FeedbackItem(feature=feature, target_id=target_id, value=value, reason=reason)  # type: ignore[arg-type]

    def cancel(self, subject: Subject, feature: str, target_id: str) -> bool:
        """Take the vote back. ``False`` when there was none."""
        cursor = self._db.execute(
            "DELETE FROM feedback WHERE feature=? AND target_id=? AND subject=?", (feature, target_id, subject.id)
        )
        return cursor.rowcount > 0

    def mine(self, subject: Subject, feature: str, target_ids: Sequence[str]) -> list[FeedbackItem]:
        if not target_ids:
            return []
        marks = ",".join("?" for _ in target_ids)
        rows = self._db.query(
            f"SELECT feature,target_id,value,reason FROM feedback WHERE subject=? AND feature=? AND target_id IN ({marks})",
            [subject.id, feature, *target_ids],
        )
        return [FeedbackItem(feature=r["feature"], target_id=r["target_id"], value=r["value"], reason=r["reason"]) for r in rows]

    # ---- reading (admin side)
    def summary(self, window: str) -> FeedbackSummary:
        since = since_iso(window, self._clock)
        rows = self._db.query(
            "SELECT feature, value, updated_at FROM feedback" + (" WHERE updated_at >= ?" if since else ""),
            (since,) if since else (),
        )
        days = day_range(window, self._clock, min((r["updated_at"] for r in rows), default=None))
        per_day: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
        for r in rows:
            per_day[r["feature"]][kst_day(r["updated_at"])][r["value"]] += 1
        features = []
        for feature, label in FEATURE_LABEL.items():
            up = sum(c["up"] for c in per_day[feature].values())
            down = sum(c["down"] for c in per_day[feature].values())
            features.append(
                FeedbackFeatureStat(
                    feature=feature,  # type: ignore[arg-type]
                    label=label,
                    up=up,
                    down=down,
                    total=up + down,
                    rate=ratio(up, up + down),
                    sample_hidden=up + down < MIN_SAMPLE,
                    days=[
                        FeedbackDay(
                            date=day,
                            up=per_day[feature][day]["up"],
                            down=per_day[feature][day]["down"],
                            rate=ratio(per_day[feature][day]["up"], per_day[feature][day]["up"] + per_day[feature][day]["down"]),
                        )
                        for day in days
                    ],
                )
            )
        return FeedbackSummary(
            window=window,  # type: ignore[arg-type]
            as_of=utc_iso(self._clock.now()),
            min_sample=MIN_SAMPLE,
            features=features,
            unsupported=UNSUPPORTED,
            basis=BASIS,
        )

    def totals(self, window: str, features: Sequence[str]) -> tuple[int, int]:
        """(likes, dislikes) over the given features in the window."""
        since = since_iso(window, self._clock)
        marks = ",".join("?" for _ in features)
        rows = self._db.query(
            f"SELECT value, COUNT(*) AS n FROM feedback WHERE feature IN ({marks})"
            + (" AND updated_at >= ?" if since else "")
            + " GROUP BY value",
            [*features, *([since] if since else [])],
        )
        counts = {r["value"]: r["n"] for r in rows}
        return counts.get("up", 0), counts.get("down", 0)

    def round_votes(self, since: str | None) -> dict[str, tuple[int, int]]:
        """(likes, dislikes) per briefing round id (round votes and votes on its issues together)."""
        rows = self._db.query(
            "SELECT feature, target_id, value FROM feedback WHERE feature IN ('briefing_round','briefing_issue')"
            + (" AND updated_at >= ?" if since else ""),
            (since,) if since else (),
        )
        out: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for r in rows:
            out[r["target_id"].split("/", 1)[0]][0 if r["value"] == "up" else 1] += 1
        return {k: (v[0], v[1]) for k, v in out.items()}

    def message_votes(self, message_ids: Sequence[str], masker: Masker) -> dict[str, tuple[int, int, list[str]]]:
        if not message_ids:
            return {}
        marks = ",".join("?" for _ in message_ids)
        rows = self._db.query(
            f"SELECT target_id, value, reason FROM feedback WHERE feature='chatbot_answer' AND target_id IN ({marks})"
            " ORDER BY updated_at",
            list(message_ids),
        )
        out: dict[str, tuple[int, int, list[str]]] = {}
        for r in rows:
            up, down, reasons = out.get(r["target_id"], (0, 0, []))
            if r["value"] == "up":
                up += 1
            else:
                down += 1
                if r["reason"]:
                    reasons.append(masker.mask(r["reason"])[0])
            out[r["target_id"]] = (up, down, reasons)
        return out

    def masker_for_member(self, member_id: str | None) -> Masker:
        member = self._accounts.member(member_id) if member_id else None
        return Masker(member.email, member.display_name) if member else Masker()

    def dislikes(self, window: str, limit: int, offset: int, ds: Dataset | None) -> DislikePage:
        since = since_iso(window, self._clock)
        where = "value='down'" + (" AND updated_at >= ?" if since else "")
        params: list[Any] = [since] if since else []
        total = int(self._db.one(f"SELECT COUNT(*) AS n FROM feedback WHERE {where}", params)["n"])  # type: ignore[index]
        rows = self._db.query(
            f"SELECT rowid, * FROM feedback WHERE {where} ORDER BY updated_at DESC, rowid DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        items = []
        for r in rows:
            masker = self.masker_for_member(r["subject"] if r["subject_kind"] == "member" else None)
            label, session_id = self._target_label(r["feature"], r["target_id"], ds, masker)
            reason = masker.mask(r["reason"])[0] if r["reason"] else None
            items.append(
                DislikeRow(
                    at=r["updated_at"],
                    feature=r["feature"],
                    feature_label=FEATURE_LABEL[r["feature"]],
                    target_id=r["target_id"],
                    target_label=label,
                    reason=reason,
                    voter=self._keys.pseudonym(r["subject_kind"], r["subject"]),
                    session_id=session_id,
                )
            )
        return DislikePage(items=items, next_cursor=str(offset + limit) if offset + limit < total else None, total=total)

    def _target_label(self, feature: str, target_id: str, ds: Dataset | None, masker: Masker) -> tuple[str, str | None]:
        if feature == "chatbot_answer":
            row = self._db.one("SELECT session_id, question FROM chat_messages WHERE id=?", (target_id,))
            if row is None:
                return target_id, None
            question = masker.mask(row["question"])[0]
            return question if len(question) <= 60 else question[:59] + "…", row["session_id"]
        round_id, _, event_id = target_id.partition("/")
        parsed = parse_round_id(round_id)
        round_label = f"{parsed[0].isoformat()} {EDITION_LABEL[parsed[1]]}" if parsed else round_id
        if feature == "briefing_round":
            return round_label, None
        issue = ds.issues.get(event_id) if ds else None
        return f"{round_label} · {issue.title if issue else event_id}", None
