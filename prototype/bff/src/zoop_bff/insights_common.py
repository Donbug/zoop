"""Shared pieces of the usage-insight features (requirements 74, 75, 78).

* ``Subject``/``SubjectKeys``: who an event, a chat or a vote belongs to. A member is identified by the
  member id; a guest only by a keyed hash of its session's principal id. No real name, e-mail or IP is
  stored by the insight tables, and the admin side only ever sees ``pseudonym`` ids.
* ``RateLimiter``: sliding-window limiter on an injectable clock.
* ``ratio``/``since_for``/``kst_day``: window and sample-size rules every statistic shares.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Literal

from .audit import Clock
from .dataset import Dataset
from .statedb import StateDb, utc_iso

KST = timezone(timedelta(hours=9))
MIN_SAMPLE = 5  # a ratio whose denominator is smaller than this is not shown, only the counts
Window = Literal["7d", "30d", "all"]
_DAYS: dict[str, int | None] = {"7d": 7, "30d": 30, "all": None}
_PEPPER_KEY = "insights_pepper"
MAX_TREND_DAYS = 90


def today_kst(clock: Clock) -> date:
    return clock.now().astimezone(KST).date()


def window_start(window: str, clock: Clock) -> datetime | None:
    """First instant of the window: a window of N days is today (KST) and the N-1 days before it."""
    days = _DAYS[window]
    if days is None:
        return None
    first = today_kst(clock) - timedelta(days=days - 1)
    return datetime.combine(first, time.min, tzinfo=KST).astimezone(UTC)


def since_iso(window: str, clock: Clock) -> str | None:
    start = window_start(window, clock)
    return utc_iso(start) if start else None


def day_range(window: str, clock: Clock, first_at: str | None) -> list[str]:
    """KST days a trend covers, oldest first. ``all`` starts at the first record (at most 90 days back)."""
    today = today_kst(clock)
    days = _DAYS[window]
    if days is None:
        first = kst_day(first_at) if first_at else today.isoformat()
        start = max(date.fromisoformat(first), today - timedelta(days=MAX_TREND_DAYS - 1))
    else:
        start = today - timedelta(days=days - 1)
    return [(start + timedelta(days=n)).isoformat() for n in range((today - start).days + 1)]


def kst_day(at: str) -> str:
    return datetime.fromisoformat(at).astimezone(KST).date().isoformat()


def ratio(numerator: int, denominator: int) -> float | None:
    """``None`` when the sample is too small to read a percentage from (denominator < MIN_SAMPLE)."""
    if denominator < MIN_SAMPLE:
        return None
    return numerator / denominator


@dataclass(frozen=True)
class Subject:
    kind: Literal["member", "guest"]
    id: str


class SubjectKeys:
    """Pseudonymous identities. The pepper is generated once and kept in the state database."""

    def __init__(self, db: StateDb):
        self._db = db
        self._lock = threading.Lock()
        self._pepper: bytes | None = None

    def _key(self) -> bytes:
        with self._lock:
            if self._pepper is None:
                row = self._db.one("SELECT value FROM meta WHERE key=?", (_PEPPER_KEY,))
                if row is None:
                    self._db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES (?,?)", (_PEPPER_KEY, secrets.token_hex(32)))
                    row = self._db.one("SELECT value FROM meta WHERE key=?", (_PEPPER_KEY,))
                assert row is not None
                self._pepper = bytes.fromhex(row["value"])
            return self._pepper

    def _digest(self, scope: str, value: str) -> str:
        return hmac.new(self._key(), f"{scope}:{value}".encode(), hashlib.sha256).hexdigest()

    def subject(self, kind: Literal["member", "guest"], principal_id: str) -> Subject:
        """Members keep their id; a guest session id is replaced by a keyed hash."""
        if kind == "member":
            return Subject("member", principal_id)
        return Subject("guest", "g-" + self._digest("guest", principal_id)[:24])

    def pseudonym(self, kind: Literal["member", "guest"], subject_id: str) -> str:
        """Short id shown to administrators: ``M-3FA9C2D1`` (member) or ``G-…`` (guest session)."""
        if kind == "member":
            return "M-" + self._digest("member", subject_id)[:8].upper()
        return "G-" + subject_id.removeprefix("g-")[:8].upper()


class RateLimiter:
    """At most ``limit`` units per ``window`` seconds per key (sliding window)."""

    def __init__(self, clock: Clock, limit: int, window: float):
        self._clock = clock
        self._limit = limit
        self._window = window
        self._lock = threading.Lock()
        self._hits: dict[str, deque[tuple[float, int]]] = {}

    def allow(self, key: str, cost: int = 1) -> bool:
        now = self._clock.now().timestamp()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0][0] <= now - self._window:
                hits.popleft()
            if sum(units for _, units in hits) + cost > self._limit:
                return False
            hits.append((now, cost))
            if len(self._hits) > 10_000:  # forget idle keys so the table cannot grow without bound
                for stale in [k for k, v in self._hits.items() if not v or v[-1][0] <= now - self._window]:
                    del self._hits[stale]
            return True


def companies_of(ds: Dataset, target_id: str) -> list[str]:
    """Companies a graph node, issue or edge id relates to (empty for unknown ids)."""
    if target_id in ds.companies:
        return [target_id]
    issue = ds.issues.get(target_id)
    if issue is not None:
        return [c for c in issue.company_ids if c in ds.companies]
    edge = ds.edges.get(target_id)
    if edge is not None:
        return [c for c in dict.fromkeys((edge.source, edge.target)) if c in ds.companies]
    return []


def node_kind(ds: Dataset | None, target_id: str) -> str:
    if ds is None:
        return "other"
    if target_id in ds.companies:
        return "company"
    if target_id in ds.issues:
        return "issue"
    return "other"
