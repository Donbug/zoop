"""Like/dislike on AI output (requirement 75; spec v1.2 FS066-01/FS066-02, D08).

Only signed-in members rate. The screen sends the rating it wants to end up with (``up``/``down``/``none``),
so a resent request never toggles anything; ``none`` takes the rating back and removes it from every count.
One voter has at most one current rating per target (``feedback`` primary key), linked to the result kind
(``feature``), the result id and its version (``target_version``: the graph version a briefing round was
published on; a chatbot answer never changes, so it has none). A dislike may carry a short reason.
News summaries have no producer in this prototype, so no vote target exists for them.
Administrators see counts, trends and reasons only with pseudonymous voter ids and masked text, filtered by
the KST day of each rating's last valid change.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from .accounts import AccountStore
from .audit import Clock
from .briefing_rounds import parse_round_id
from .dataset import Dataset
from .insights_common import KST, MAX_TREND_DAYS, MIN_SAMPLE, SubjectKeys, Subject, day_range, kst_day, ratio, since_iso, today_kst
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
    "현재 유효한 평가만 셉니다. 취소한 평가는 빠지고, 한 사람이 같은 대상에 남길 수 있는 평가는 1개입니다. "
    "기간은 평가를 마지막으로 바꾼 시각(한국 시간)으로 나눕니다. 표본이 적은 비율은 숨기고 건수만 보여 줍니다."
)


class Period:
    """Which ratings an admin view covers: a preset window or explicit KST start/end days (both inclusive)."""

    def __init__(self, clock: Clock, window: str, start: date | None = None, end: date | None = None):
        self.window = window
        self.start = start
        self.end = end
        self._clock = clock

    @property
    def custom(self) -> bool:
        return self.start is not None or self.end is not None

    def where(self) -> tuple[str, list[Any]]:
        """SQL condition on ``updated_at`` (always prefixed with `` AND ``, or empty) and its parameters."""
        if not self.custom:
            since = since_iso(self.window, self._clock)
            return (" AND updated_at >= ?", [since]) if since else ("", [])
        sql, params = "", []
        if self.start:
            sql += " AND updated_at >= ?"
            params.append(_kst_midnight_utc(self.start))
        if self.end:
            sql += " AND updated_at < ?"
            params.append(_kst_midnight_utc(self.end + timedelta(days=1)))
        return sql, params

    def days(self, first_at: str | None) -> list[str]:
        if not self.custom:
            return day_range(self.window, self._clock, first_at)
        end = self.end or today_kst(self._clock)
        start = self.start or (date.fromisoformat(kst_day(first_at)) if first_at else end)
        start = max(start, end - timedelta(days=MAX_TREND_DAYS - 1))
        return [(start + timedelta(days=n)).isoformat() for n in range((end - start).days + 1)]


def _kst_midnight_utc(day: date) -> str:
    return utc_iso(datetime.combine(day, time.min, tzinfo=KST).astimezone(UTC))


def issue_target(round_id: str, event_id: str) -> str:
    return f"{round_id}/{event_id}"


class FeedbackService:
    def __init__(self, db: StateDb, clock: Clock, keys: SubjectKeys, accounts: AccountStore):
        self._db = db
        self._clock = clock
        self._keys = keys
        self._accounts = accounts
        # State directories created before the rating carried its result version lack the column.
        columns = {r["name"] for r in db.query("PRAGMA table_info(feedback)")}
        if "target_version" not in columns:
            db.execute("ALTER TABLE feedback ADD COLUMN target_version TEXT")

    def period(self, window: str, start: date | None = None, end: date | None = None) -> Period:
        return Period(self._clock, window, start, end)

    # ---- rating (member side)
    def set_rating(
        self,
        subject: Subject,
        feature: str,
        target_id: str,
        version: str | None,
        value: Literal["up", "down", "none"],
        reason: str | None,
    ) -> FeedbackItem:
        """Store the rating the voter wants to end up with. Repeating a request changes nothing (idempotent):
        the same value keeps the rating and its change time, ``none`` on no rating stays no rating."""
        now = utc_iso(self._clock.now())
        key = (feature, target_id, subject.id)
        with self._db.transaction() as conn:
            if value == "none":
                conn.execute("DELETE FROM feedback WHERE feature=? AND target_id=? AND subject=?", key)
                return FeedbackItem(feature=feature, target_id=target_id, target_version=version, value="none", reason=None)  # type: ignore[arg-type]
            row = conn.execute(
                "SELECT value, reason, target_version FROM feedback WHERE feature=? AND target_id=? AND subject=?", key
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO feedback(feature,target_id,subject,subject_kind,value,reason,created_at,updated_at,target_version)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (feature, target_id, subject.id, subject.kind, value, reason, now, now, version),
                )
            elif (row["value"], row["reason"], row["target_version"]) != (value, reason, version):
                conn.execute(
                    "UPDATE feedback SET value=?, reason=?, target_version=?, updated_at=?"
                    " WHERE feature=? AND target_id=? AND subject=?",
                    (value, reason, version, now, *key),
                )
        return FeedbackItem(feature=feature, target_id=target_id, target_version=version, value=value, reason=reason)  # type: ignore[arg-type]

    def mine(self, subject: Subject, feature: str, target_ids: Sequence[str]) -> list[FeedbackItem]:
        if not target_ids:
            return []
        marks = ",".join("?" for _ in target_ids)
        rows = self._db.query(
            "SELECT feature,target_id,target_version,value,reason FROM feedback"
            f" WHERE subject=? AND feature=? AND target_id IN ({marks})",
            [subject.id, feature, *target_ids],
        )
        return [
            FeedbackItem(
                feature=r["feature"], target_id=r["target_id"], target_version=r["target_version"], value=r["value"], reason=r["reason"]
            )
            for r in rows
        ]

    # ---- reading (admin side)
    def summary(self, period: Period) -> FeedbackSummary:
        where, params = period.where()
        rows = self._db.query("SELECT feature, value, updated_at FROM feedback WHERE 1=1" + where, params)
        days = period.days(min((r["updated_at"] for r in rows), default=None))
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
            window=period.window,  # type: ignore[arg-type]
            start=period.start.isoformat() if period.start else None,
            end=period.end.isoformat() if period.end else None,
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

    def dislikes(self, period: Period, limit: int, offset: int, ds: Dataset | None) -> DislikePage:
        cond, params = period.where()
        where = "value='down'" + cond
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
