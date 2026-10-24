"""The service's own small ledger: owner binding, idempotency and dispatch state. The runtime ledger stays the only job state.

It never stores a request body, document text, artifact, grant or receipt. Owner/request identity rows are immutable.

Reservation lifecycle (the owner claim is durable BEFORE the runtime is asked to register anything):
    reserved   owner + jobId + request digest are bound; the runtime may or may not hold the job
    accepted   the runtime registered the job (its inputDigest is recorded) and a dispatch row exists in the same transaction
A reservation is deleted only by `release`, which the caller invokes for a refusal the runtime made definitively on the very
first attempt. Nothing is ever swept by age, so a registration whose acknowledgement was lost can never be claimed by another
principal; the owner's own retry completes it.
"""
from __future__ import annotations

import fcntl
import hashlib
import os
import sqlite3
import stat
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import ConfigError

LEDGER_SCHEMA = "zoop-ai-service-ledger-1"

DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS analysis_jobs (
 job_id TEXT PRIMARY KEY,
 owner TEXT NOT NULL,
 request_digest TEXT NOT NULL,
 kind TEXT NOT NULL,
 mode TEXT NOT NULL,
 state TEXT NOT NULL CHECK (state IN ('reserved','accepted')),
 submit_attempts INTEGER NOT NULL DEFAULT 0,
 input_digest TEXT,
 reserved_at TEXT NOT NULL,
 accepted_at TEXT,
 CHECK ((state='reserved' AND input_digest IS NULL AND accepted_at IS NULL)
     OR (state='accepted' AND input_digest IS NOT NULL AND accepted_at IS NOT NULL)));
CREATE TRIGGER IF NOT EXISTS analysis_jobs_immutable BEFORE UPDATE ON analysis_jobs
 WHEN NOT (OLD.job_id=NEW.job_id AND OLD.owner=NEW.owner AND OLD.request_digest=NEW.request_digest
       AND OLD.kind=NEW.kind AND OLD.mode=NEW.mode AND OLD.reserved_at=NEW.reserved_at
       AND OLD.state='reserved'
       AND ((NEW.state='reserved' AND NEW.submit_attempts=OLD.submit_attempts+1)
         OR (NEW.state='accepted' AND NEW.submit_attempts=OLD.submit_attempts)))
 BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS analysis_jobs_release_only BEFORE DELETE ON analysis_jobs
 WHEN NOT (OLD.state='reserved' AND OLD.submit_attempts=1)
 BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TABLE IF NOT EXISTS analysis_dispatch (
 job_id TEXT PRIMARY KEY REFERENCES analysis_jobs(job_id),
 seq INTEGER NOT NULL UNIQUE,
 state TEXT NOT NULL CHECK (state IN ('pending','in_flight','idle')),
 command TEXT CHECK (command IN ('run','resume')),
 dispatch_count INTEGER NOT NULL DEFAULT 0,
 unknown_count INTEGER NOT NULL DEFAULT 0,
 busy_count INTEGER NOT NULL DEFAULT 0,
 fresh INTEGER NOT NULL DEFAULT 1 CHECK (fresh IN (0,1)),
 not_before REAL,
 last_outcome TEXT,
 last_runtime_code TEXT,
 updated_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS analysis_dispatch_undeletable BEFORE DELETE ON analysis_dispatch
 BEGIN SELECT RAISE(ABORT,'immutable'); END;
"""


def stamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class JobRow:
    job_id: str
    owner: str
    request_digest: str
    kind: str
    mode: str
    state: str
    submit_attempts: int
    input_digest: str | None
    accepted_at: str | None


@dataclass(frozen=True)
class DispatchRow:
    job_id: str
    state: str
    command: str | None
    dispatch_count: int
    unknown_count: int
    busy_count: int
    not_before: float | None
    last_outcome: str | None
    last_runtime_code: str | None
    updated_at: str


@dataclass(frozen=True)
class Claim:
    """`fresh` is true for the original submission intent and for an explicit recover; false for every automatic redispatch
    (busy poll, unknown outcome, service restart), which must first look at what the runtime already holds."""
    job_id: str
    command: str
    mode: str
    input_digest: str
    unknown_count: int
    busy_count: int
    fresh: bool


@dataclass(frozen=True)
class Update:
    """The pure result of the dispatch policy for one finished (or refused) dispatch."""
    state: str                 # "pending" or "idle"
    command: str | None        # the command to run next when pending
    last_outcome: str
    runtime_code: str | None = None
    delay: float = 0.0         # seconds before a pending row may be claimed again
    unknown_count: int = 0
    busy_count: int = 0


class ProcessLock:
    """Exclusive non-blocking flock held for the process lifetime. The kernel drops it when the process dies, however it dies."""

    def __init__(self, directory: Path, *, directory_fd: int | None = None, create: bool = True):
        self._directory, self._directory_fd = directory, directory_fd
        try:
            path = directory / "service.lock" if directory_fd is None else "service.lock"
            self._fd = os.open(path, os.O_RDWR | (os.O_CREAT if create else 0) | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=directory_fd)
        except OSError:
            raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "service_lock_unusable") from None
        info = os.fstat(self._fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            os.close(self._fd)
            raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "service_lock_unusable")
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self._fd)
            raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "service_state_busy") from None
        os.set_inheritable(self._fd, False)
        self.identity = (info.st_dev, info.st_ino)
        try:
            self.validate()
        except BaseException:
            self.close()
            raise

    def validate(self) -> None:
        """The named lock must remain the inode whose exclusive flock this object holds."""
        try:
            path = self._directory / "service.lock" if self._directory_fd is None else "service.lock"
            current = os.stat(path, dir_fd=self._directory_fd, follow_symlinks=False)
            held = os.fstat(self._fd)
            if (current.st_dev, current.st_ino) != self.identity or (held.st_dev, held.st_ino) != self.identity \
                    or not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
                raise OSError("lock identity changed")
        except OSError:
            raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "service_lock_unusable") from None

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> ProcessLock:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class ServiceLedger:
    def __init__(self, directory: Path, worker_state_dir: Path, clock=time.time):
        self._clock = clock
        self._guard = threading.RLock()
        path = directory / "service.sqlite3"
        try:
            self._db = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
            os.chmod(path, 0o600)
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.executescript(DDL)
            self._bind(worker_state_dir)
        except sqlite3.Error:
            raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "ledger_unavailable") from None

    def _bind(self, worker_state_dir: Path) -> None:
        binding = hashlib.sha256(os.path.realpath(worker_state_dir).encode("utf-8")).hexdigest()
        with self._guard:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                for key, value in (("schema", LEDGER_SCHEMA), ("workerLedger", binding)):
                    row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
                    if row is None:
                        self._db.execute("INSERT INTO meta VALUES (?,?)", (key, value))
                    elif row["value"] != value:
                        raise ConfigError("ZOOP_AI_WORKER_STATE_DIR" if key == "workerLedger" else "ZOOP_AI_SERVICE_STATE_DIR",
                                          "worker_ledger_binding_mismatch" if key == "workerLedger" else "ledger_schema_mismatch")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    def close(self) -> None:
        with self._guard:
            self._db.close()

    def _tx(self):
        return _Transaction(self)

    # ---- owner binding ----

    def job(self, job_id: str) -> JobRow | None:
        with self._guard:
            row = self._db.execute("SELECT * FROM analysis_jobs WHERE job_id=?", (job_id,)).fetchone()
        return None if row is None else JobRow(row["job_id"], row["owner"], row["request_digest"], row["kind"], row["mode"],
                                               row["state"], row["submit_attempts"], row["input_digest"], row["accepted_at"])

    def reserve(self, job_id: str, owner: str, request_digest: str, kind: str, mode: str) -> JobRow:
        with self._tx() as db:
            db.execute("INSERT OR IGNORE INTO analysis_jobs(job_id,owner,request_digest,kind,mode,state,reserved_at) "
                       "VALUES (?,?,?,?,?,'reserved',?)", (job_id, owner, request_digest, kind, mode, stamp(self._clock())))
        row = self.job(job_id)
        assert row is not None
        return row

    def begin_attempt(self, job_id: str) -> int:
        """Counted and committed before the runtime is invoked, so a crash mid-call is still counted."""
        with self._tx() as db:
            db.execute("UPDATE analysis_jobs SET submit_attempts=submit_attempts+1 WHERE job_id=? AND state='reserved'", (job_id,))
        row = self.job(job_id)
        assert row is not None
        return row.submit_attempts

    def release(self, job_id: str, owner: str, request_digest: str) -> bool:
        """Drop a reservation after a definitive refusal on the first and only attempt. Anything else is retained."""
        with self._tx() as db:
            cursor = db.execute("DELETE FROM analysis_jobs WHERE job_id=? AND owner=? AND request_digest=? "
                                "AND state='reserved' AND submit_attempts=1", (job_id, owner, request_digest))
            return cursor.rowcount == 1

    def accept(self, job_id: str, owner: str, input_digest: str, limit: int) -> str:
        """The runtime holds the job: record its digest and create the dispatch intent in one transaction.

        The cap is part of that same transaction, so concurrent distinct submissions cannot all pass a stale count. It counts
        pending AND in-flight dispatches: a claimed row can return to pending (busy poll, unknown outcome, restart) without any
        check, so its slot stays reserved while it runs and accepted intent is never dropped.
        Returns "accepted", "full" (the owner's reservation is kept for a later retry) or "conflict".
        """
        now = self._clock()
        with self._tx() as db:
            cursor = db.execute("UPDATE analysis_jobs SET state='accepted', input_digest=?, accepted_at=? "
                                "WHERE job_id=? AND owner=? AND state='reserved' "
                                "AND (SELECT COUNT(*) FROM analysis_dispatch WHERE state IN ('pending','in_flight'))<?",
                                (input_digest, stamp(now), job_id, owner, limit))
            if cursor.rowcount != 1:
                held = db.execute("SELECT 1 FROM analysis_jobs WHERE job_id=? AND owner=? AND state='reserved'",
                                  (job_id, owner)).fetchone()
                return "full" if held else "conflict"
            db.execute("INSERT INTO analysis_dispatch(job_id,seq,state,command,updated_at) VALUES "
                       "(?,(SELECT COALESCE(MAX(seq),0)+1 FROM analysis_dispatch),'pending','run',?)", (job_id, stamp(now)))
            return "accepted"

    # ---- dispatch ----

    def dispatch(self, job_id: str) -> DispatchRow | None:
        with self._guard:
            row = self._db.execute("SELECT * FROM analysis_dispatch WHERE job_id=?", (job_id,)).fetchone()
        return None if row is None else _dispatch_row(row)

    def active_count(self) -> int:
        """Pending plus in-flight dispatches: the capacity that admission control reserves."""
        with self._guard:
            return self._db.execute("SELECT COUNT(*) FROM analysis_dispatch WHERE state IN ('pending','in_flight')").fetchone()[0]

    def pending_count(self) -> int:
        with self._guard:
            return self._db.execute("SELECT COUNT(*) FROM analysis_dispatch WHERE state='pending'").fetchone()[0]

    def claim_next(self) -> Claim | None:
        now = self._clock()
        with self._tx() as db:
            row = db.execute("SELECT d.job_id, d.command, d.unknown_count, d.busy_count, d.fresh, j.mode, j.input_digest "
                             "FROM analysis_dispatch d JOIN analysis_jobs j ON j.job_id=d.job_id "
                             "WHERE d.state='pending' AND (d.not_before IS NULL OR d.not_before<=?) ORDER BY d.seq LIMIT 1",
                             (now,)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE analysis_dispatch SET state='in_flight', dispatch_count=dispatch_count+1, not_before=NULL, updated_at=? "
                       "WHERE job_id=?", (stamp(now), row["job_id"]))
            return Claim(row["job_id"], row["command"], row["mode"], row["input_digest"], row["unknown_count"], row["busy_count"],
                         bool(row["fresh"]))

    def finish(self, job_id: str, update: Update) -> bool:
        now = self._clock()
        with self._tx() as db:
            cursor = db.execute(
                "UPDATE analysis_dispatch SET state=?, command=COALESCE(?,command), fresh=0, not_before=?, last_outcome=?, "
                "last_runtime_code=?, unknown_count=?, busy_count=?, updated_at=? WHERE job_id=? AND state='in_flight'",
                (update.state, update.command, now + update.delay if update.state == "pending" and update.delay else None,
                 update.last_outcome, update.runtime_code, update.unknown_count, update.busy_count, stamp(now), job_id))
            return cursor.rowcount == 1

    def enqueue(self, job_id: str, command: str, limit: int) -> str:
        """Explicit recovery. At most one dispatch row per job: a pending or in-flight dispatch absorbs the request and costs
        no capacity. Only an idle row becoming pending counts against the cap, checked in the same transaction.
        Returns "enqueued", "coalesced" or "full"."""
        with self._tx() as db:
            cursor = db.execute(
                "UPDATE analysis_dispatch SET state='pending', command=?, seq=(SELECT MAX(seq)+1 FROM analysis_dispatch), "
                "fresh=1, not_before=NULL, unknown_count=0, busy_count=0, updated_at=? WHERE job_id=? AND state='idle' "
                "AND (SELECT COUNT(*) FROM analysis_dispatch WHERE state IN ('pending','in_flight'))<?",
                (command, stamp(self._clock()), job_id, limit))
            if cursor.rowcount == 1:
                return "enqueued"
            idle = db.execute("SELECT 1 FROM analysis_dispatch WHERE job_id=? AND state='idle'", (job_id,)).fetchone()
            return "full" if idle else "coalesced"

    def cancel_pending(self, job_id: str) -> None:
        """A cancelled job's queued dispatch ends. An in-flight child is never killed: that would turn a known receipt into an unknown."""
        with self._tx() as db:
            db.execute("UPDATE analysis_dispatch SET state='idle', not_before=NULL, last_outcome='cancelled', "
                       "last_runtime_code=NULL, updated_at=? WHERE job_id=? AND state='pending'", (stamp(self._clock()), job_id))

    def requeue_in_flight(self) -> int:
        """Service start: the previous process died with these in flight. The runtime decides what `run` does next."""
        with self._tx() as db:
            return db.execute("UPDATE analysis_dispatch SET state='pending', fresh=0, not_before=NULL, last_outcome='service_restarted', "
                              "updated_at=? WHERE state='in_flight'", (stamp(self._clock()),)).rowcount


class _Transaction:
    def __init__(self, ledger: ServiceLedger):
        self._ledger = ledger

    def __enter__(self) -> sqlite3.Connection:
        self._ledger._guard.acquire()
        try:
            self._ledger._db.execute("BEGIN IMMEDIATE")
        except BaseException:
            self._ledger._guard.release()
            raise
        return self._ledger._db

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            self._ledger._db.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self._ledger._guard.release()


def _dispatch_row(row: sqlite3.Row) -> DispatchRow:
    return DispatchRow(row["job_id"], row["state"], row["command"], row["dispatch_count"], row["unknown_count"],
                       row["busy_count"], row["not_before"], row["last_outcome"], row["last_runtime_code"], row["updated_at"])
