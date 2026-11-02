"""Cross-process Fetch dispatch admission: one account window and per-origin spacing.

All producers for the approved account must share this directory. This does not pace
unrelated applications using the same provider account, nor infer provider arrival times.
"""
from __future__ import annotations

import math
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from .ingestion_contracts import IngestionFailure
from .ingestion_url import canonical_url

FETCH_ACCOUNT_QPS = 25
PACING_PROFILE = "deepseek-fetch-shared-pacing-1"
DB_NAME = "fetch-pacing.sqlite3"


class SharedFetchPacer:
    """Durable dispatch slots, never monetary reservations or permission to send."""
    def __init__(self, directory: str | Path):
        self.path = Path(directory) / DB_NAME

    def acquire(self, url: str, *, min_interval_seconds: float, not_before_monotonic: float = 0,
                deadline_monotonic: float) -> float:
        values = (min_interval_seconds, not_before_monotonic, deadline_monotonic)
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in values):
            raise IngestionFailure("fetch_pacing_invalid")
        normalized, _ = canonical_url(url)
        parts = urlsplit(normalized)
        origin = parts.scheme + "://" + parts.netloc
        while True:
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise IngestionFailure("fetch_pacing_deadline")
            try:
                self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                os.close(os.open(self.path, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600))
                with closing(sqlite3.connect(self.path, timeout=min(remaining, 30), isolation_level=None)) as db:
                    db.execute("BEGIN IMMEDIATE")
                    try:
                        db.execute("CREATE TABLE IF NOT EXISTS profile(value TEXT NOT NULL) STRICT")
                        profile = db.execute("SELECT value FROM profile").fetchall()
                        if not profile:
                            db.execute("INSERT INTO profile VALUES(?)", (PACING_PROFILE,))
                        elif profile != [(PACING_PROFILE,)]:
                            raise IngestionFailure("fetch_pacing_profile_mismatch")
                        db.execute("CREATE TABLE IF NOT EXISTS dispatches(at REAL NOT NULL) STRICT")
                        db.execute("CREATE TABLE IF NOT EXISTS origins(origin TEXT PRIMARY KEY,last REAL NOT NULL,spacing REAL NOT NULL) STRICT")
                        current = time.monotonic()
                        latest = db.execute("SELECT max(at) FROM dispatches").fetchone()[0]
                        if latest is not None and current < latest:
                            raise IngestionFailure("fetch_pacing_clock_regressed")
                        # Retain the closed boundary: at most 25 admissions in any inclusive one-second window.
                        db.execute("DELETE FROM dispatches WHERE at < ?", (current - 1.0,))
                        recent = db.execute("SELECT at FROM dispatches ORDER BY at").fetchall()
                        previous = db.execute("SELECT last,spacing FROM origins WHERE origin=?", (origin,)).fetchone()
                        ready = not_before_monotonic
                        if previous:
                            ready = max(ready, previous[0] + max(previous[1], min_interval_seconds))
                        if len(recent) >= FETCH_ACCOUNT_QPS:
                            ready = max(ready, math.nextafter(recent[-FETCH_ACCOUNT_QPS][0] + 1.0, math.inf))
                        if current >= deadline_monotonic or ready >= deadline_monotonic:
                            raise IngestionFailure("fetch_pacing_deadline")
                        delay = max(0.0, ready - current)
                        if delay == 0:
                            db.execute("INSERT INTO dispatches VALUES(?)", (current,))
                            db.execute("INSERT INTO origins VALUES(?,?,?) ON CONFLICT(origin) DO UPDATE SET last=excluded.last,spacing=excluded.spacing",
                                       (origin, current, min_interval_seconds))
                        db.execute("COMMIT")
                    except BaseException:
                        db.execute("ROLLBACK")
                        raise
            except (OSError, sqlite3.Error) as exc:
                raise IngestionFailure("fetch_pacing_unavailable") from exc
            if delay == 0:
                return current
            # Never hold the shared transaction while sleeping; another origin can proceed.
            time.sleep(delay)
