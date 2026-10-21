"""Shared USD and call budget for live S2/S3 provider calls: one SQLite file, durable across processes and process death.

A call is *reserved* before it is sent. The reservation charges the worst case (conservative rates, configured maximum output
including reasoning, an input upper bound from the exact request bytes) and stays charged until the outcome is known:

* `settled`  - a response was received. Reported usage replaces the worst case; missing or unusable usage keeps the worst case.
* `released` - the request was provably never sent (a refusal before the socket). Charged 0 and not counted as a call.
* `reserved` - nothing recorded after the reservation (process death, transport timeout, unknown outcome). Charged worst case
  and counted as a call forever: a reservation is never reused to send again.

Money is an integer number of nano-USD, so rates (USD per 1M tokens) are exact integers per token and no float is involved.
The ceilings are bound to the budget directory on first use and may only decrease afterwards. Nothing here knows a provider.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_NAME = "live-budget.sqlite3"
NANO = 1_000_000_000
BUSY_SECONDS = 30
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value INTEGER NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS reservations(
  attempt_id TEXT PRIMARY KEY,
  stage TEXT NOT NULL,
  recipient TEXT NOT NULL,
  request_digest TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('reserved','settled','released')),
  reserved_nano INTEGER NOT NULL CHECK(reserved_nano >= 0),
  charged_nano INTEGER NOT NULL CHECK(charged_nano >= 0),
  usage_known INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
) STRICT;
"""


class BudgetError(Exception):
    """A budget refusal. The runtime maps `code` to a LiveFailure; none of these ever follows a sent request."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def usd(nano: int) -> str:
    """Exact decimal USD string for an integer nano-USD amount (nine fractional digits, never a float)."""
    return f"{nano // NANO}.{nano % NANO:09d}"


def nano_from_usd(text: str) -> int:
    """Parse a positive plain decimal such as `10` or `0.5` (at most nine fractional digits) into nano-USD; ValueError otherwise."""
    whole, dot, fraction = text.strip().partition(".")
    if not whole.isascii() or not whole.isdigit() or (dot and not (fraction.isascii() and fraction.isdigit() and len(fraction) <= 9)):
        raise ValueError("budget_amount_invalid")
    value = int(whole) * NANO + int((fraction or "0").ljust(9, "0"))
    if value <= 0 or value > 1_000_000 * NANO:
        raise ValueError("budget_amount_invalid")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Budget:
    """Handle to one budget directory. Every operation is its own short `BEGIN IMMEDIATE` transaction, so threads and processes
    that share the directory serialize on the database lock and never overspend the shared ceiling."""

    def __init__(self, directory: str | Path, max_nano: int, max_calls: int):
        self.path = Path(directory) / DB_NAME
        self.max_nano, self.max_calls = max_nano, max_calls

    @contextmanager
    def _tx(self):
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.close(os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600))
            connection = sqlite3.connect(self.path, timeout=BUSY_SECONDS, isolation_level=None)
        except (OSError, sqlite3.Error):
            raise BudgetError("live_budget_unavailable") from None
        try:
            with closing(connection):
                connection.execute("BEGIN IMMEDIATE")
                try:
                    yield connection
                except BudgetError:
                    connection.execute("COMMIT")  # a refusal is a decision, not a failure: a lowered ceiling stays lowered
                    raise
                except BaseException:
                    connection.execute("ROLLBACK")
                    raise
                else:
                    connection.execute("COMMIT")
        except sqlite3.Error:
            raise BudgetError("live_budget_unavailable") from None

    def _bind_ceilings(self, db: sqlite3.Connection) -> None:
        for statement in SCHEMA.split(";"):
            if statement.strip():
                db.execute(statement)
        increase = False
        for key, wanted in (("max_nano", self.max_nano), ("max_calls", self.max_calls)):
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            if row is None:
                db.execute("INSERT INTO meta VALUES(?,?)", (key, wanted))
            elif wanted > row[0]:
                increase = True
            elif wanted < row[0]:
                db.execute("UPDATE meta SET value=? WHERE key=?", (wanted, key))
        if increase:  # a decrease of the other ceiling is kept: the transaction commits on every deliberate refusal
            raise BudgetError("live_budget_ceiling_increase")

    def reserve(self, attempt_id: str, stage: str, recipient: str, request_digest: str, worst_case_nano: int) -> None:
        """Durably charge the worst case of one future call. The unique attempt id spans S2 and S3 and every process."""
        with self._tx() as db:
            self._bind_ceilings(db)
            if db.execute("SELECT 1 FROM reservations WHERE attempt_id=?", (attempt_id,)).fetchone():
                raise BudgetError("live_budget_attempt_duplicate")
            charged, calls = db.execute("SELECT COALESCE(SUM(charged_nano),0), COUNT(*) FROM reservations WHERE state!='released'").fetchone()
            if calls + 1 > self.max_calls:
                raise BudgetError("live_budget_exhausted_calls")
            if charged + worst_case_nano > self.max_nano:
                raise BudgetError("live_budget_exhausted_usd")
            now = _now()
            db.execute("INSERT INTO reservations VALUES(?,?,?,?,'reserved',?,?,0,?,?)",
                       (attempt_id, stage, recipient, request_digest, worst_case_nano, worst_case_nano, now, now))

    def settle(self, attempt_id: str, actual_nano: int | None) -> int:
        """A response arrived. `actual_nano` replaces the worst case only when the provider reported usable usage; None keeps it.
        Returns the nano-USD now charged for this attempt (an actual above the reservation is recorded, never hidden)."""
        with self._tx() as db:
            row = db.execute("SELECT state,charged_nano FROM reservations WHERE attempt_id=?", (attempt_id,)).fetchone()
            if row is None or row[0] != "reserved":
                raise BudgetError("live_budget_unavailable")
            charged = row[1] if actual_nano is None else actual_nano
            db.execute("UPDATE reservations SET state='settled', charged_nano=?, usage_known=?, updated_at=? WHERE attempt_id=?",
                       (charged, int(actual_nano is not None), _now(), attempt_id))
            return charged

    def release(self, attempt_id: str) -> None:
        """Only for a request that provably never reached the provider (a refusal before send). Charged 0, not counted."""
        with self._tx() as db:
            db.execute("UPDATE reservations SET state='released', charged_nano=0, updated_at=? WHERE attempt_id=? AND state='reserved'",
                       (_now(), attempt_id))

    def snapshot(self) -> dict:
        """Totals for diagnostics and the smoke report: no attempt contents."""
        with self._tx() as db:
            self._bind_ceilings(db)
            charged, calls = db.execute("SELECT COALESCE(SUM(charged_nano),0), COUNT(*) FROM reservations WHERE state!='released'").fetchone()
            ceilings = dict(db.execute("SELECT key,value FROM meta").fetchall())
            states = dict(db.execute("SELECT state, COUNT(*) FROM reservations GROUP BY state").fetchall())
        return {"chargedUsd": usd(charged), "calls": calls, "maxUsd": usd(ceilings["max_nano"]), "maxCalls": ceilings["max_calls"], "states": states}
