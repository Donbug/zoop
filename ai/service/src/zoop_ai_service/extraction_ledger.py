"""The service's own control ledger for S2 extraction jobs: owner binding, the frozen approval identity and the dispatch state. The pipeline's S2
ledger stays the only job state, and this module never opens it: not as a file, not through an import of the pipeline.

A separate SQLite file (`extraction-jobs.sqlite3`) under the service state directory, so the S1 and S3 ledgers and their schemas are untouched. It
never stores a request body, candidate, quote, fixture or registry: the identity it keeps is opaque digests.

Reservation lifecycle (the owner claim is durable BEFORE the pipeline is asked to register anything):
    reserved   owner + jobId + the caller's request digest are bound, together with everything the approval pinned at that moment: the approved
               request digest, the producer fixture digest, the optional topic fixture digest, and the `inputDigest` the pipeline MUST report
               (`digest({request, replayFixtureHash})`, computed here from the approved bytes, never taken from the pipeline). The pipeline may or
               may not hold the job.
    accepted   the pipeline registered a queued job whose reported `inputDigest` equals the pinned one, and a dispatch row exists, in one transaction
A reservation is deleted only by `release`, which the caller invokes after the pipeline provably holds no such job. Nothing is swept by age, so a
registration whose acknowledgement was lost can never be claimed by another principal; the owner's own identical retry completes it. Every pinned
column is immutable from the reservation on: a later approval or fixture rotation can never rebind the same job id to other bytes (the trigger refuses
it); the job id is spent on the pins it was reserved under.

Dispatch: the initial intent is one `pending` row that a dispatcher claims once. Every later dispatch is an explicit `recover`. A row left `in_flight`
by a dead process is never made `pending` again: it ends `idle` as `service_restarted`, because whether its child already ran is unknown.

Schema `zoop-ai-extraction-jobs-ledger-1`; the ledger is bound to the realpath of the extraction state directory, and any other schema or binding is
refused at start.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .config import ConfigError
from .ledger import stamp
from .relation_ledger import DispatchRow, Update

LEDGER_SCHEMA = "zoop-ai-extraction-jobs-ledger-1"
FILE = "extraction-jobs.sqlite3"

DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS extraction_jobs (
 job_id TEXT PRIMARY KEY,
 owner TEXT NOT NULL,
 request_digest TEXT NOT NULL,
 approved_digest TEXT NOT NULL,
 producer_digest TEXT NOT NULL,
 topic_digest TEXT,
 input_digest TEXT NOT NULL,
 state TEXT NOT NULL CHECK (state IN ('reserved','accepted')),
 submit_attempts INTEGER NOT NULL DEFAULT 0,
 reserved_at TEXT NOT NULL,
 accepted_at TEXT,
 CHECK ((state='reserved' AND accepted_at IS NULL) OR (state='accepted' AND accepted_at IS NOT NULL)));
CREATE TRIGGER IF NOT EXISTS extraction_jobs_immutable BEFORE UPDATE ON extraction_jobs
 WHEN NOT (OLD.job_id=NEW.job_id AND OLD.owner=NEW.owner AND OLD.request_digest=NEW.request_digest
       AND OLD.approved_digest=NEW.approved_digest AND OLD.producer_digest=NEW.producer_digest AND OLD.topic_digest IS NEW.topic_digest
       AND OLD.input_digest=NEW.input_digest AND OLD.reserved_at=NEW.reserved_at AND OLD.state='reserved'
       AND ((NEW.state='reserved' AND NEW.submit_attempts=OLD.submit_attempts+1)
         OR (NEW.state='accepted' AND NEW.submit_attempts=OLD.submit_attempts)))
 BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS extraction_jobs_release_only BEFORE DELETE ON extraction_jobs
 WHEN OLD.state<>'reserved'
 BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TABLE IF NOT EXISTS extraction_dispatch (
 job_id TEXT PRIMARY KEY REFERENCES extraction_jobs(job_id),
 seq INTEGER NOT NULL UNIQUE,
 state TEXT NOT NULL CHECK (state IN ('pending','in_flight','idle')),
 dispatch_count INTEGER NOT NULL DEFAULT 0,
 busy_count INTEGER NOT NULL DEFAULT 0,
 not_before REAL,
 last_outcome TEXT,
 last_runtime_code TEXT,
 updated_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS extraction_dispatch_undeletable BEFORE DELETE ON extraction_dispatch
 BEGIN SELECT RAISE(ABORT,'immutable'); END;
"""

NEXT_SEQ = "(SELECT COALESCE(MAX(seq),0)+1 FROM extraction_dispatch)"
ACTIVE = "(SELECT COUNT(*) FROM extraction_dispatch WHERE state IN ('pending','in_flight'))"


@dataclass(frozen=True)
class Pins:
    """What a reservation froze. Compared as a whole against the current approval; never rewritten."""
    approved_digest: str
    producer_digest: str
    topic_digest: str | None
    input_digest: str

    @property
    def approval(self) -> tuple[str, str, str | None]:
        return (self.approved_digest, self.producer_digest, self.topic_digest)


@dataclass(frozen=True)
class ExtractionRow:
    job_id: str
    owner: str
    request_digest: str
    pins: Pins
    state: str
    submit_attempts: int
    accepted_at: str | None

    @property
    def input_digest(self) -> str:
        return self.pins.input_digest


@dataclass(frozen=True)
class Claim:
    job_id: str
    owner: str
    pins: Pins
    busy_count: int


class ExtractionLedger:
    def __init__(self, directory: Path, extraction_state_dir: Path, clock=time.time):
        self._clock = clock
        self._guard = threading.RLock()
        path = directory / FILE
        try:
            self._db = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
            os.chmod(path, 0o600)
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.executescript(DDL)
            self._bind(extraction_state_dir)
        except sqlite3.Error:
            raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "extraction_ledger_unavailable") from None

    def _bind(self, extraction_state_dir: Path) -> None:
        binding = hashlib.sha256(os.path.realpath(extraction_state_dir).encode("utf-8")).hexdigest()
        with self._guard:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                for key, value in (("schema", LEDGER_SCHEMA), ("extractionLedger", binding)):
                    row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
                    if row is None:
                        self._db.execute("INSERT INTO meta VALUES (?,?)", (key, value))
                    elif row["value"] != value:
                        raise ConfigError("ZOOP_AI_EXTRACTION_STATE_DIR" if key == "extractionLedger" else "ZOOP_AI_SERVICE_STATE_DIR",
                                          "extraction_ledger_binding_mismatch" if key == "extractionLedger" else "extraction_ledger_schema_mismatch")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    def close(self) -> None:
        with self._guard:
            self._db.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._guard:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    # ---- owner binding ----

    @staticmethod
    def _row(row: sqlite3.Row) -> ExtractionRow:
        return ExtractionRow(row["job_id"], row["owner"], row["request_digest"],
                             Pins(row["approved_digest"], row["producer_digest"], row["topic_digest"], row["input_digest"]),
                             row["state"], row["submit_attempts"], row["accepted_at"])

    def job(self, job_id: str) -> ExtractionRow | None:
        with self._guard:
            row = self._db.execute("SELECT * FROM extraction_jobs WHERE job_id=?", (job_id,)).fetchone()
        return None if row is None else self._row(row)

    def reserve(self, job_id: str, owner: str, request_digest: str, pins: Pins) -> ExtractionRow:
        with self._tx() as db:
            db.execute("INSERT OR IGNORE INTO extraction_jobs(job_id,owner,request_digest,approved_digest,producer_digest,topic_digest,input_digest,"
                       "state,reserved_at) VALUES (?,?,?,?,?,?,?,'reserved',?)",
                       (job_id, owner, request_digest, pins.approved_digest, pins.producer_digest, pins.topic_digest, pins.input_digest,
                        stamp(self._clock())))
        row = self.job(job_id)
        assert row is not None
        return row

    def begin_attempt(self, job_id: str) -> int:
        """Counted and committed before the pipeline is invoked, so a crash mid-call is still counted."""
        with self._tx() as db:
            db.execute("UPDATE extraction_jobs SET submit_attempts=submit_attempts+1 WHERE job_id=? AND state='reserved'", (job_id,))
        row = self.job(job_id)
        assert row is not None
        return row.submit_attempts

    def release(self, job_id: str, owner: str, request_digest: str) -> bool:
        """Drop a reservation. Only called once the pipeline provably holds no such job."""
        with self._tx() as db:
            cursor = db.execute("DELETE FROM extraction_jobs WHERE job_id=? AND owner=? AND request_digest=? AND state='reserved'",
                                (job_id, owner, request_digest))
            return cursor.rowcount == 1

    def accept(self, job_id: str, owner: str, limit: int) -> str:
        """The pipeline holds the job under the pinned input digest: record that and create the one initial dispatch intent in one transaction.
        The cap counts everything waiting to run in the same transaction. Returns "accepted", "full" (the reservation is kept) or "conflict"."""
        now = self._clock()
        with self._tx() as db:
            cursor = db.execute(f"UPDATE extraction_jobs SET state='accepted', accepted_at=? WHERE job_id=? AND owner=? AND state='reserved' AND {ACTIVE}<?",
                                (stamp(now), job_id, owner, limit))
            if cursor.rowcount != 1:
                held = db.execute("SELECT 1 FROM extraction_jobs WHERE job_id=? AND owner=? AND state='reserved'", (job_id, owner)).fetchone()
                return "full" if held else "conflict"
            db.execute(f"INSERT INTO extraction_dispatch(job_id,seq,state,updated_at) VALUES (?,{NEXT_SEQ},'pending',?)", (job_id, stamp(now)))
            return "accepted"

    # ---- dispatch ----

    def dispatch(self, job_id: str) -> DispatchRow | None:
        with self._guard:
            row = self._db.execute("SELECT * FROM extraction_dispatch WHERE job_id=?", (job_id,)).fetchone()
        return None if row is None else DispatchRow(row["job_id"], row["state"], row["dispatch_count"], row["busy_count"], row["last_outcome"],
                                                    row["last_runtime_code"], row["updated_at"])

    def active_count(self) -> int:
        with self._guard:
            return self._db.execute(f"SELECT {ACTIVE}").fetchone()[0]

    def claim_next(self) -> Claim | None:
        """The pending dispatch with the lowest sequence, or None."""
        now = self._clock()
        with self._tx() as db:
            row = db.execute("SELECT d.job_id, d.busy_count, j.* FROM extraction_dispatch d JOIN extraction_jobs j ON j.job_id=d.job_id "
                             "WHERE d.state='pending' AND (d.not_before IS NULL OR d.not_before<=?) ORDER BY d.seq LIMIT 1", (now,)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE extraction_dispatch SET state='in_flight', dispatch_count=dispatch_count+1, not_before=NULL, updated_at=? WHERE job_id=?",
                       (stamp(now), row["job_id"]))
            return Claim(row["job_id"], row["owner"], Pins(row["approved_digest"], row["producer_digest"], row["topic_digest"], row["input_digest"]),
                         row["busy_count"])

    def finish(self, job_id: str, update: Update) -> bool:
        now = self._clock()
        with self._tx() as db:
            cursor = db.execute(
                "UPDATE extraction_dispatch SET state=?, not_before=?, last_outcome=?, last_runtime_code=?, busy_count=?, updated_at=? "
                "WHERE job_id=? AND state='in_flight'",
                (update.state, now + update.delay if update.state == "pending" and update.delay else None, update.last_outcome,
                 update.runtime_code, update.busy_count, stamp(now), job_id))
            return cursor.rowcount == 1

    def enqueue(self, job_id: str, limit: int) -> str:
        """Explicit recovery. A pending or in-flight dispatch absorbs the request and costs no capacity; only an idle row becoming pending counts
        against the cap, checked in the same transaction. Returns "enqueued", "coalesced" or "full"."""
        with self._tx() as db:
            cursor = db.execute(
                f"UPDATE extraction_dispatch SET state='pending', seq={NEXT_SEQ}, not_before=NULL, busy_count=0, "
                f"updated_at=? WHERE job_id=? AND state='idle' AND {ACTIVE}<?",
                (stamp(self._clock()), job_id, limit))
            if cursor.rowcount == 1:
                return "enqueued"
            idle = db.execute("SELECT 1 FROM extraction_dispatch WHERE job_id=? AND state='idle'", (job_id,)).fetchone()
            return "full" if idle else "coalesced"

    def cancel_pending(self, job_id: str) -> None:
        """A cancelled job's queued dispatch ends. An in-flight child is never killed."""
        with self._tx() as db:
            db.execute("UPDATE extraction_dispatch SET state='idle', not_before=NULL, last_outcome='cancelled', last_runtime_code=NULL, updated_at=? "
                       "WHERE job_id=? AND state='pending'", (stamp(self._clock()), job_id))

    def interrupt_in_flight(self) -> int:
        """Service start: the previous process died with these in flight. Whether the child ran is unknown, so they are NOT run again."""
        with self._tx() as db:
            return db.execute("UPDATE extraction_dispatch SET state='idle', not_before=NULL, last_outcome='service_restarted', last_runtime_code=NULL, "
                              "updated_at=? WHERE state='in_flight'", (stamp(self._clock()),)).rowcount
