"""The service's own ledger for S3 relation jobs: owner binding, idempotency and dispatch state. The pipeline ledger stays the only job state.

A separate SQLite file (`relation-jobs.sqlite3`) under the service state directory, so the S1 ledger and its schema are untouched. It
never stores a request body, candidate, quote, fixture or registry; the upstream identity it keeps is two opaque identifiers.

Reservation lifecycle (the owner claim is durable BEFORE the pipeline is asked to register anything):
    reserved   owner + jobId + request digest are bound; the pipeline may or may not hold the job
    accepted   the pipeline registered the job (its inputDigest is recorded) and a dispatch row exists, in one transaction
A reservation is deleted only by `release`, which the caller invokes after the pipeline provably holds no such job (an `inspect`
under the same exclusive gate answered `job_not_found`). Nothing is ever swept by age, so a registration whose acknowledgement was
lost can never be claimed by another principal; the owner's own retry completes it.

Dispatch: the initial intent is one `pending` row that a dispatcher claims once. Every later dispatch is an explicit `recover`.
A row left `in_flight` by a dead process is never made `pending` again: it ends `idle` as `service_restarted`, because whether its
child already ran is unknown.

Review operations (`relation_operations`, one row per Idempotency-Key) follow the same discipline with two phases:
    reserved   owner + job + candidate + decision + the two expected source values are bound durably BEFORE the pipeline is asked to append
               the review event. The pipeline may or may not hold that event; the event carries a marker derived from the operation id, so
               the service can prove it from the pipeline's append-only chain and never appends a second time.
    applied    the exact event is confirmed (its sequence is the expected revision + 1, its own timestamp is recorded), in one transaction.
               An `allow` is a FINAL human approval (effect `approved`) and an `reject` an exclusion: neither schedules, dispatches or settles
               anything, and no model call follows either.
A reservation is deleted only by `release_operation`, after the chain provably does not hold the event and can no longer take it (the relation
moved past the expected revision, or the pipeline refused the review itself).

Contract column. Every operation row carries the review contract it was written under. `final-approval` is the current one. `legacy-revalidation`
rows are exactly the ones a `-2` ledger held: an `allow` then meant "ask for an automatic revalidation", with its own dispatch/settlement columns.
They stay readable as history, are never dispatched, resent or reinterpreted as approvals (`review_contract_changed`), and no code writes their
revalidation columns any more.

Schema: `zoop-ai-relation-jobs-ledger-4`. Supported `-1` through `-3` ledgers migrate forward, retaining legacy operation history. The `-2` operations
table is rebuilt transactionally with every row copied and marked `legacy-revalidation`. Existing manual rows keep a null authority_ref; online
rows pin an immutable admission origin. Nothing is reset or rebound, and future or foreign schemas are refused.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .config import ConfigError
from .ledger import stamp

LEDGER_SCHEMA = "zoop-ai-relation-jobs-ledger-4"
MIGRATES_FROM = ("zoop-ai-relation-jobs-ledger-1", "zoop-ai-relation-jobs-ledger-2", "zoop-ai-relation-jobs-ledger-3")
LEGACY = "legacy-revalidation"
FINAL = "final-approval"
FILE = "relation-jobs.sqlite3"

DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS relation_jobs (
 job_id TEXT PRIMARY KEY,
 owner TEXT NOT NULL,
 request_digest TEXT NOT NULL,
 upstream_job_id TEXT NOT NULL,
 upstream_input_digest TEXT NOT NULL,
 state TEXT NOT NULL CHECK (state IN ('reserved','accepted')),
 submit_attempts INTEGER NOT NULL DEFAULT 0,
 input_digest TEXT,
 reserved_at TEXT NOT NULL,
 accepted_at TEXT,
 live_binding TEXT,
 authority_ref TEXT,
 execution_mode TEXT NOT NULL DEFAULT 'replay' CHECK (execution_mode IN ('replay','live') AND ((execution_mode='live') = (live_binding IS NOT NULL))),
 CHECK ((state='reserved' AND input_digest IS NULL AND accepted_at IS NULL)
     OR (state='accepted' AND input_digest IS NOT NULL AND accepted_at IS NOT NULL)));
CREATE TRIGGER IF NOT EXISTS relation_jobs_release_only BEFORE DELETE ON relation_jobs
 WHEN OLD.state<>'reserved'
 BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TABLE IF NOT EXISTS relation_dispatch (
 job_id TEXT PRIMARY KEY REFERENCES relation_jobs(job_id),
 seq INTEGER NOT NULL UNIQUE,
 state TEXT NOT NULL CHECK (state IN ('pending','in_flight','idle')),
 dispatch_count INTEGER NOT NULL DEFAULT 0,
 busy_count INTEGER NOT NULL DEFAULT 0,
 not_before REAL,
 last_outcome TEXT,
 last_runtime_code TEXT,
 explicit INTEGER NOT NULL DEFAULT 0 CHECK (explicit IN (0,1)),
 updated_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS relation_dispatch_undeletable BEFORE DELETE ON relation_dispatch
 BEGIN SELECT RAISE(ABORT,'immutable'); END;
"""

OPERATION_COLUMNS = ("operation_id,owner,job_id,relation_candidate_id,decision,expected_source_version,expected_source_revision,request_digest,"
                     "review_state,review_attempts,reserved_at,applied_at,applied_event_at,reval_state,reval_seq,reval_count,busy_count,not_before,"
                     "last_outcome,last_runtime_code,reval_updated_at,settled,settled_eligibility,settled_at")
OPERATIONS = ("""CREATE TABLE IF NOT EXISTS relation_operations (
 operation_id TEXT PRIMARY KEY,
 owner TEXT NOT NULL,
 job_id TEXT NOT NULL REFERENCES relation_jobs(job_id),
 relation_candidate_id TEXT NOT NULL,
 decision TEXT NOT NULL CHECK (decision IN ('allow','reject')),
 expected_source_version TEXT NOT NULL,
 expected_source_revision INTEGER NOT NULL CHECK (expected_source_revision>=1),
 request_digest TEXT NOT NULL,
 review_state TEXT NOT NULL CHECK (review_state IN ('reserved','applied')),
 review_attempts INTEGER NOT NULL DEFAULT 0,
 reserved_at TEXT NOT NULL,
 applied_at TEXT,
 applied_event_at TEXT,
 reval_state TEXT CHECK (reval_state IS NULL OR reval_state IN ('pending','in_flight','idle')),
 reval_seq INTEGER UNIQUE,
 reval_count INTEGER NOT NULL DEFAULT 0,
 busy_count INTEGER NOT NULL DEFAULT 0,
 not_before REAL,
 last_outcome TEXT,
 last_runtime_code TEXT,
 reval_updated_at TEXT,
 settled TEXT CHECK (settled IS NULL OR settled IN ('verified','superseded')),
 settled_eligibility TEXT,
 settled_at TEXT,
 contract TEXT NOT NULL CHECK (contract IN ('legacy-revalidation','final-approval')),
 CHECK ((review_state='reserved' AND applied_at IS NULL AND applied_event_at IS NULL AND reval_state IS NULL AND reval_seq IS NULL)
     OR (review_state='applied' AND applied_at IS NOT NULL AND applied_event_at IS NOT NULL
         AND ((contract='legacy-revalidation'
               AND ((decision='allow' AND reval_state IS NOT NULL AND reval_seq IS NOT NULL)
                 OR (decision='reject' AND reval_state IS NULL AND reval_seq IS NULL)))
           OR (contract='final-approval' AND reval_state IS NULL AND reval_seq IS NULL)))),
 CHECK (settled IS NULL OR (contract='legacy-revalidation' AND decision='allow' AND review_state='applied' AND settled_at IS NOT NULL)))""",
              """CREATE TRIGGER IF NOT EXISTS relation_operations_identity BEFORE UPDATE ON relation_operations
 WHEN NOT (OLD.operation_id=NEW.operation_id AND OLD.owner=NEW.owner AND OLD.job_id=NEW.job_id
       AND OLD.relation_candidate_id=NEW.relation_candidate_id AND OLD.decision=NEW.decision AND OLD.contract=NEW.contract
       AND OLD.expected_source_version=NEW.expected_source_version AND OLD.expected_source_revision=NEW.expected_source_revision
       AND OLD.request_digest=NEW.request_digest AND OLD.reserved_at=NEW.reserved_at
       AND (OLD.review_state='reserved' OR (NEW.review_state='applied' AND OLD.applied_at=NEW.applied_at AND OLD.applied_event_at=NEW.applied_event_at))
       AND (OLD.settled IS NULL OR (OLD.settled=NEW.settled AND OLD.settled_eligibility IS NEW.settled_eligibility AND OLD.settled_at=NEW.settled_at)))
 BEGIN SELECT RAISE(ABORT,'immutable'); END""",
              """CREATE TRIGGER IF NOT EXISTS relation_operations_release_only BEFORE DELETE ON relation_operations
 WHEN OLD.review_state<>'reserved'
 BEGIN SELECT RAISE(ABORT,'immutable'); END""")

# One FIFO sequence over job dispatches and one cap over everything that waits to run: pending and in-flight job dispatches. Review operations
# never wait to run (an approval or an exclusion is recorded the moment the chain proves it).
NEXT_SEQ = "(SELECT COALESCE(MAX(seq),0)+1 FROM relation_dispatch)"
ACTIVE = "(SELECT COUNT(*) FROM relation_dispatch WHERE state IN ('pending','in_flight'))"

# Columns added after the first schema. A fresh ledger creates them in DDL above; an older one gains them in place (ALTER ADD COLUMN: nothing is
# rewritten and every old row reads as a replay job whose dispatch was not an explicit recovery).
ADDED_COLUMNS = (("relation_jobs", "authority_ref", "TEXT"), ("relation_jobs", "live_binding", "TEXT"),
                 ("relation_jobs", "execution_mode",
                  "TEXT NOT NULL DEFAULT 'replay' CHECK (execution_mode IN ('replay','live') AND ((execution_mode='live') = (live_binding IS NOT NULL)))"),
                 ("relation_dispatch", "explicit", "INTEGER NOT NULL DEFAULT 0 CHECK (explicit IN (0,1))"))
JOBS_IMMUTABLE = """CREATE TRIGGER relation_jobs_immutable BEFORE UPDATE ON relation_jobs
 WHEN NOT (OLD.job_id=NEW.job_id AND OLD.owner=NEW.owner AND OLD.request_digest=NEW.request_digest
       AND OLD.upstream_job_id=NEW.upstream_job_id AND OLD.upstream_input_digest=NEW.upstream_input_digest
       AND OLD.execution_mode=NEW.execution_mode AND OLD.live_binding IS NEW.live_binding
       AND OLD.authority_ref IS NEW.authority_ref
       AND OLD.reserved_at=NEW.reserved_at AND OLD.state='reserved'
       AND ((NEW.state='reserved' AND NEW.submit_attempts=OLD.submit_attempts+1)
         OR (NEW.state='accepted' AND NEW.submit_attempts=OLD.submit_attempts)))
 BEGIN SELECT RAISE(ABORT,'immutable'); END"""


@dataclass(frozen=True)
class RelationRow:
    job_id: str
    owner: str
    request_digest: str
    upstream_job_id: str
    upstream_input_digest: str
    state: str
    submit_attempts: int
    input_digest: str | None
    accepted_at: str | None
    execution_mode: str = "replay"
    live_binding: str | None = None   # the runtime identity the operator's allowlist pinned for this live job; None for a replay job
    authority_ref: str | None = None


@dataclass(frozen=True)
class DispatchRow:
    job_id: str
    state: str
    dispatch_count: int
    busy_count: int
    last_outcome: str | None
    last_runtime_code: str | None
    updated_at: str


@dataclass(frozen=True)
class OperationRow:
    operation_id: str
    owner: str
    job_id: str
    relation_candidate_id: str
    decision: str
    expected_source_version: str
    expected_source_revision: int
    request_digest: str
    review_state: str
    review_attempts: int
    reserved_at: str
    applied_at: str | None
    applied_event_at: str | None
    reval_state: str | None
    reval_count: int
    busy_count: int
    last_outcome: str | None
    last_runtime_code: str | None
    reval_updated_at: str | None
    settled: str | None
    settled_eligibility: str | None
    settled_at: str | None
    contract: str

    @property
    def legacy(self) -> bool:
        """A row written under the old "allow requests a revalidation" contract: history only, never dispatched or read as an approval."""
        return self.contract == LEGACY


@dataclass(frozen=True)
class Claim:
    """One claimed job dispatch: a `resume` of the job. `live` is the job's frozen execution mode; `explicit` says the dispatch is an operator's
    recover, not the one automatic initial dispatch (which runs under the pipeline's lock as initial-only). A live claim also names the owner,
    the upstream and the pinned runtime identity the dispatcher re-authorizes before any child that may spend money."""
    job_id: str
    input_digest: str
    busy_count: int
    live: bool = False
    explicit: bool = False
    owner: str | None = None
    upstream_job_id: str | None = None
    upstream_input_digest: str | None = None
    live_binding: str | None = None
    authority_ref: str | None = None


@dataclass(frozen=True)
class Update:
    """The pure result of the dispatch policy for one finished (or refused) dispatch."""
    state: str                 # "pending" (a busy retry only) or "idle"
    last_outcome: str
    runtime_code: str | None = None
    delay: float = 0.0
    busy_count: int = 0


class RelationLedger:
    def __init__(self, directory: Path, relation_state_dir: Path, clock=time.time):
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
            self._bind(relation_state_dir)
        except sqlite3.Error:
            raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "relation_ledger_unavailable") from None

    def _added_columns(self) -> None:
        """Bring an older ledger up to the current columns in place, and install the current job-identity trigger. Inside the caller's transaction."""
        for table, name, definition in ADDED_COLUMNS:
            if name not in [row["name"] for row in self._db.execute(f"PRAGMA table_info({table})")]:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        self._db.execute("DROP TRIGGER IF EXISTS relation_jobs_immutable")
        self._db.execute(JOBS_IMMUTABLE)

    def _operations_table(self) -> None:
        """Create the operations table, or rebuild a `-2` one in place (every row copied, marked `legacy-revalidation`). Inside the caller's transaction."""
        columns = [row["name"] for row in self._db.execute("PRAGMA table_info(relation_operations)")]
        if columns and "contract" not in columns:
            self._db.execute("DROP TRIGGER IF EXISTS relation_operations_identity")
            self._db.execute("DROP TRIGGER IF EXISTS relation_operations_release_only")
            self._db.execute("ALTER TABLE relation_operations RENAME TO relation_operations_v2")
            self._db.execute(OPERATIONS[0])
            self._db.execute(f"INSERT INTO relation_operations({OPERATION_COLUMNS},contract) SELECT {OPERATION_COLUMNS},'{LEGACY}' FROM relation_operations_v2")
            self._db.execute("DROP TABLE relation_operations_v2")
        for statement in OPERATIONS:
            self._db.execute(statement)

    def _bind(self, relation_state_dir: Path) -> None:
        binding = hashlib.sha256(os.path.realpath(relation_state_dir).encode("utf-8")).hexdigest()
        with self._guard:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                for key, value in (("schema", LEDGER_SCHEMA), ("relationLedger", binding)):
                    row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
                    if row is None:
                        self._db.execute("INSERT INTO meta VALUES (?,?)", (key, value))
                    elif row["value"] != value:
                        if key == "schema" and row["value"] in MIGRATES_FROM:
                            # Forward only: the operations table is created or rebuilt below; no job or dispatch row changes.
                            self._db.execute("UPDATE meta SET value=? WHERE key='schema'", (value,))
                            continue
                        raise ConfigError("ZOOP_AI_RELATION_STATE_DIR" if key == "relationLedger" else "ZOOP_AI_SERVICE_STATE_DIR",
                                          "relation_ledger_binding_mismatch" if key == "relationLedger" else "relation_ledger_schema_mismatch")
                self._added_columns()
                self._operations_table()
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

    def job(self, job_id: str) -> RelationRow | None:
        with self._guard:
            row = self._db.execute("SELECT * FROM relation_jobs WHERE job_id=?", (job_id,)).fetchone()
        return None if row is None else RelationRow(row["job_id"], row["owner"], row["request_digest"], row["upstream_job_id"],
                                                    row["upstream_input_digest"], row["state"], row["submit_attempts"],
                                                    row["input_digest"], row["accepted_at"], row["execution_mode"], row["live_binding"], row["authority_ref"])

    def reserve(self, job_id: str, owner: str, request_digest: str, upstream_job_id: str, upstream_input_digest: str,
                live_binding: str | None = None, authority_ref: str | None = None) -> RelationRow:
        """`live_binding` is the runtime identity the operator's allowlist pinned for a live job (None: a replay job). Immutable from here on."""
        with self._tx() as db:
            db.execute("INSERT OR IGNORE INTO relation_jobs(job_id,owner,request_digest,upstream_job_id,upstream_input_digest,state,reserved_at,"
                       "live_binding,execution_mode,authority_ref) VALUES (?,?,?,?,?,'reserved',?,?,?,?)",
                       (job_id, owner, request_digest, upstream_job_id, upstream_input_digest, stamp(self._clock()), live_binding,
                        "live" if live_binding is not None else "replay", authority_ref))
        row = self.job(job_id)
        assert row is not None
        return row

    def begin_attempt(self, job_id: str) -> int:
        """Counted and committed before the pipeline is invoked, so a crash mid-call is still counted."""
        with self._tx() as db:
            db.execute("UPDATE relation_jobs SET submit_attempts=submit_attempts+1 WHERE job_id=? AND state='reserved'", (job_id,))
        row = self.job(job_id)
        assert row is not None
        return row.submit_attempts

    def release(self, job_id: str, owner: str, request_digest: str) -> bool:
        """Drop a reservation. Only called once the pipeline provably holds no such job."""
        with self._tx() as db:
            cursor = db.execute("DELETE FROM relation_jobs WHERE job_id=? AND owner=? AND request_digest=? AND state='reserved'",
                                (job_id, owner, request_digest))
            return cursor.rowcount == 1

    def accept(self, job_id: str, owner: str, input_digest: str, limit: int) -> str:
        """The pipeline holds the job: record its digest and create the one initial dispatch intent in one transaction.

        The cap counts everything waiting to run in the same transaction. Returns "accepted", "full" (the reservation is
        kept for a later retry) or "conflict".
        """
        now = self._clock()
        with self._tx() as db:
            cursor = db.execute("UPDATE relation_jobs SET state='accepted', input_digest=?, accepted_at=? "
                                f"WHERE job_id=? AND owner=? AND state='reserved' AND {ACTIVE}<?",
                                (input_digest, stamp(now), job_id, owner, limit))
            if cursor.rowcount != 1:
                held = db.execute("SELECT 1 FROM relation_jobs WHERE job_id=? AND owner=? AND state='reserved'", (job_id, owner)).fetchone()
                return "full" if held else "conflict"
            db.execute(f"INSERT INTO relation_dispatch(job_id,seq,state,updated_at) VALUES (?,{NEXT_SEQ},'pending',?)", (job_id, stamp(now)))
            return "accepted"

    # ---- dispatch ----

    def dispatch(self, job_id: str) -> DispatchRow | None:
        with self._guard:
            row = self._db.execute("SELECT * FROM relation_dispatch WHERE job_id=?", (job_id,)).fetchone()
        return None if row is None else _dispatch_row(row)

    def active_count(self) -> int:
        with self._guard:
            return self._db.execute(f"SELECT {ACTIVE}").fetchone()[0]

    def claim_next(self) -> Claim | None:
        """The pending job dispatch with the lowest sequence, or None."""
        now = self._clock()
        with self._tx() as db:
            job = db.execute("SELECT d.job_id, d.busy_count, d.explicit, j.input_digest, j.execution_mode, j.owner, j.upstream_job_id, "
                             "j.upstream_input_digest, j.live_binding, j.authority_ref FROM relation_dispatch d "
                             "JOIN relation_jobs j ON j.job_id=d.job_id "
                             "WHERE d.state='pending' AND (d.not_before IS NULL OR d.not_before<=?) ORDER BY d.seq LIMIT 1", (now,)).fetchone()
            if job is None:
                return None
            db.execute("UPDATE relation_dispatch SET state='in_flight', dispatch_count=dispatch_count+1, not_before=NULL, updated_at=? WHERE job_id=?",
                       (stamp(now), job["job_id"]))
            return Claim(job["job_id"], job["input_digest"], job["busy_count"], job["execution_mode"] == "live", bool(job["explicit"]),
                         job["owner"], job["upstream_job_id"], job["upstream_input_digest"], job["live_binding"], job["authority_ref"])

    def finish(self, job_id: str, update: Update) -> bool:
        now = self._clock()
        with self._tx() as db:
            cursor = db.execute(
                "UPDATE relation_dispatch SET state=?, not_before=?, last_outcome=?, last_runtime_code=?, busy_count=?, updated_at=? "
                "WHERE job_id=? AND state='in_flight'",
                (update.state, now + update.delay if update.state == "pending" and update.delay else None, update.last_outcome,
                 update.runtime_code, update.busy_count, stamp(now), job_id))
            return cursor.rowcount == 1

    def enqueue(self, job_id: str, limit: int) -> str:
        """Explicit recovery. A pending or in-flight dispatch absorbs the request and costs no capacity; only an idle row becoming
        pending counts against the cap, checked in the same transaction. Returns "enqueued", "coalesced" or "full"."""
        with self._tx() as db:
            cursor = db.execute(
                f"UPDATE relation_dispatch SET state='pending', seq={NEXT_SEQ}, not_before=NULL, busy_count=0, explicit=1, "
                f"updated_at=? WHERE job_id=? AND state='idle' AND {ACTIVE}<?",
                (stamp(self._clock()), job_id, limit))
            if cursor.rowcount == 1:
                return "enqueued"
            idle = db.execute("SELECT 1 FROM relation_dispatch WHERE job_id=? AND state='idle'", (job_id,)).fetchone()
            return "full" if idle else "coalesced"

    def cancel_pending(self, job_id: str) -> None:
        """A cancelled job's queued dispatch ends. An in-flight child is never killed."""
        now = stamp(self._clock())
        with self._tx() as db:
            db.execute("UPDATE relation_dispatch SET state='idle', not_before=NULL, last_outcome='cancelled', last_runtime_code=NULL, updated_at=? "
                       "WHERE job_id=? AND state='pending'", (now, job_id))

    def interrupt_in_flight(self) -> int:
        """Service start: the previous process died with these in flight. Whether the child ran is unknown, so they are NOT run again. Legacy
        revalidation columns are history and are never touched."""
        now = stamp(self._clock())
        with self._tx() as db:
            return db.execute("UPDATE relation_dispatch SET state='idle', not_before=NULL, last_outcome='service_restarted', last_runtime_code=NULL, "
                              "updated_at=? WHERE state='in_flight'", (now,)).rowcount

    # ---- review operations ----

    def operation(self, operation_id: str) -> OperationRow | None:
        with self._guard:
            row = self._db.execute("SELECT * FROM relation_operations WHERE operation_id=?", (operation_id,)).fetchone()
        return None if row is None else _operation_row(row)

    def reserve_operation(self, operation_id: str, owner: str, job_id: str, relation_candidate_id: str, decision: str,
                          expected_version: str, expected_revision: int, request_digest: str) -> OperationRow:
        """Bind the owner's intent durably BEFORE the pipeline is asked to append. An existing row is returned untouched (whatever its contract)."""
        with self._tx() as db:
            found = db.execute("SELECT * FROM relation_operations WHERE operation_id=?", (operation_id,)).fetchone()
            if found is not None:
                return _operation_row(found)
            db.execute("INSERT INTO relation_operations(operation_id,owner,job_id,relation_candidate_id,decision,expected_source_version,"
                       "expected_source_revision,request_digest,review_state,reserved_at,contract) VALUES (?,?,?,?,?,?,?,?,'reserved',?,?)",
                       (operation_id, owner, job_id, relation_candidate_id, decision, expected_version, expected_revision, request_digest,
                        stamp(self._clock()), FINAL))
            return _operation_row(db.execute("SELECT * FROM relation_operations WHERE operation_id=?", (operation_id,)).fetchone())

    def begin_review_attempt(self, operation_id: str) -> int:
        """Counted and committed before the pipeline is invoked, so a crash mid-call is still counted."""
        with self._tx() as db:
            db.execute("UPDATE relation_operations SET review_attempts=review_attempts+1 WHERE operation_id=? AND review_state='reserved'", (operation_id,))
            row = db.execute("SELECT review_attempts FROM relation_operations WHERE operation_id=?", (operation_id,)).fetchone()
            return row["review_attempts"]

    def release_operation(self, operation_id: str, owner: str, request_digest: str) -> bool:
        """Drop a reservation. Only called once the chain provably holds no such event and can no longer take it."""
        with self._tx() as db:
            cursor = db.execute("DELETE FROM relation_operations WHERE operation_id=? AND owner=? AND request_digest=? AND review_state='reserved'",
                                (operation_id, owner, request_digest))
            return cursor.rowcount == 1

    def apply_operation(self, operation_id: str, event_at: str) -> bool:
        """The exact event is proven in the pipeline chain: record it (its own timestamp is part of the identity). Only a current-contract row can
        be applied; a legacy reservation is history and is never adopted. Returns False when the row is not an adoptable reservation any more."""
        now = stamp(self._clock())
        with self._tx() as db:
            cursor = db.execute("UPDATE relation_operations SET review_state='applied', applied_at=?, applied_event_at=? "
                                "WHERE operation_id=? AND review_state='reserved' AND contract=?", (now, event_at, operation_id, FINAL))
            return cursor.rowcount == 1


class _Transaction:
    def __init__(self, ledger: RelationLedger):
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
    return DispatchRow(row["job_id"], row["state"], row["dispatch_count"], row["busy_count"], row["last_outcome"],
                       row["last_runtime_code"], row["updated_at"])


def _operation_row(row: sqlite3.Row) -> OperationRow:
    return OperationRow(row["operation_id"], row["owner"], row["job_id"], row["relation_candidate_id"], row["decision"],
                        row["expected_source_version"], row["expected_source_revision"], row["request_digest"], row["review_state"],
                        row["review_attempts"], row["reserved_at"], row["applied_at"], row["applied_event_at"], row["reval_state"],
                        row["reval_count"], row["busy_count"], row["last_outcome"], row["last_runtime_code"], row["reval_updated_at"],
                        row["settled"], row["settled_eligibility"], row["settled_at"], row["contract"])
