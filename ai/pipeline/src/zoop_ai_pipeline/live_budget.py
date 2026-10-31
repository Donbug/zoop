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
import fcntl
import json
import time
import uuid
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .live_funding import MODE, operating_policy, stage_allowances, timestamp
from .relation_contracts import canonical, digest

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

OPERATING_SCHEMA = """
CREATE TABLE operating_identity(id TEXT PRIMARY KEY, policy TEXT NOT NULL) STRICT;
CREATE TABLE operating_bindings(name TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
CREATE TABLE operating_control(singleton INTEGER PRIMARY KEY CHECK(singleton=1), state TEXT NOT NULL,
 reason TEXT NOT NULL, drain_until REAL, last_send REAL NOT NULL DEFAULT 0, owner TEXT, owner_pid INTEGER, resume_state TEXT) STRICT;
CREATE TABLE operating_history(seq INTEGER PRIMARY KEY, at REAL NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL) STRICT;
CREATE TABLE operating_sets(id TEXT PRIMARY KEY, pins TEXT NOT NULL, allowances TEXT NOT NULL, complete INTEGER NOT NULL DEFAULT 0) STRICT;
CREATE TABLE operating_attempts(attempt_id TEXT PRIMARY KEY REFERENCES reservations(attempt_id),
 set_id TEXT NOT NULL REFERENCES operating_sets(id), stage TEXT NOT NULL, request_digest TEXT NOT NULL,
 dispatched INTEGER NOT NULL DEFAULT 0, deferred INTEGER NOT NULL DEFAULT 0, receipt TEXT, UNIQUE(set_id,stage,request_digest)) STRICT;
CREATE TABLE operating_deferrals(seq INTEGER PRIMARY KEY, attempt_id TEXT NOT NULL, at REAL NOT NULL, code TEXT NOT NULL) STRICT;
"""


class BudgetError(Exception):
    """A budget refusal. The runtime maps `code` to a LiveFailure; none of these ever follows a sent request."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class BudgetBusy(BudgetError):
    """SQLite BUSY/LOCKED after transaction cleanup; distinct from corruption or an unknown provider outcome."""


def _database_failure(error: BaseException, operating: bool) -> BudgetError:
    if (operating and isinstance(error, sqlite3.OperationalError)
            and (getattr(error, "sqlite_errorcode", 0) & 0xFF) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)):
        return BudgetBusy("operating_ledger_busy")
    return BudgetError("live_budget_unavailable")


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
    """One accounting directory. Writes serialize through short `BEGIN IMMEDIATE` transactions;
    operating observers use read snapshots, and request control polling never waits on a database lock."""

    def __init__(self, directory: str | Path, max_nano: int | None, max_calls: int | None, *, policy: dict | None = None):
        self.path = Path(directory) / DB_NAME
        self.max_nano, self.max_calls = max_nano, max_calls
        self.policy = operating_policy(policy) if policy is not None else None
        self.marker = self.path.parent / "operating-identity.json"
        self.identity = None
        if self.policy is not None:
            if max_nano is not None or max_calls is not None:
                raise BudgetError("operating_caps_forbidden")
            self._check_identity()
        elif type(max_nano) is not int or max_nano <= 0 or type(max_calls) is not int or not 1 <= max_calls <= 100000:
            raise BudgetError("live_budget_config_invalid")

    @classmethod
    def initialize(cls, directory: str | Path, policy: dict) -> Budget:
        """Exclusive first initialization. A partial initialization is a recovery incident, never a new balance."""
        policy = operating_policy(policy)
        directory = Path(directory)
        try:
            directory.mkdir(mode=0o700, parents=True, exist_ok=False)
            path = directory / DB_NAME
            with path.open("xb") as output:
                os.chmod(path, 0o600)
                output.flush()
                os.fsync(output.fileno())
            identity = uuid.uuid4().hex
            with closing(sqlite3.connect(path)) as db:
                db.executescript(SCHEMA + OPERATING_SCHEMA)
                db.execute("INSERT INTO operating_identity VALUES(?,?)", (identity, canonical(policy)))
                db.execute("INSERT INTO operating_control(singleton,state,reason) VALUES(1,'running','initialized')")
                db.execute("INSERT INTO operating_history(at,action,reason) VALUES(?,'initialize','initialized')", (time.time(),))
                db.commit()
            for name in ("owner.lock", "send.lock"):
                with (directory / name).open("xb") as lock:
                    os.chmod(directory / name, 0o600)
                    os.fsync(lock.fileno())
            stat = path.stat()
            marker = {"id": identity, "device": stat.st_dev, "inode": stat.st_ino, "policyDigest": digest(policy),
                      "locks": {name: (directory / name).stat().st_ino for name in ("owner.lock", "send.lock")}}
            with (directory / "operating-identity.json").open("x") as output:
                os.chmod(output.name, 0o600)
                output.write(canonical(marker))
                output.flush()
                os.fsync(output.fileno())
            fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except (OSError, sqlite3.Error):
            raise BudgetError("operating_initialization_refused") from None
        return cls(directory, None, None, policy=policy)

    def _check_identity(self) -> None:
        try:
            marker = json.loads(self.marker.read_text())
            stat = self.path.stat()
            if (self.path.is_symlink() or self.marker.is_symlink() or marker["policyDigest"] != digest(self.policy)
                    or (marker["device"], marker["inode"]) != (stat.st_dev, stat.st_ino)
                    or (self.identity is not None and self.identity != marker)):
                raise BudgetError("operating_ledger_replaced")
            if (stat.st_mode & 0o077 or self.path.parent.stat().st_mode & 0o077 or self.marker.stat().st_mode & 0o077
                    or self.path.parent.resolve() != self.path.parent):
                raise BudgetError("operating_storage_unsafe")
            self.identity = marker
        except (OSError, ValueError, KeyError, TypeError):
            raise BudgetError("operating_ledger_missing") from None

    @contextmanager
    def _tx(self, *, timeout: float | None = None, readonly: bool = False):
        try:
            if self.policy is not None:
                self._check_identity()
                connection = sqlite3.connect(self.path.as_uri() + ("?mode=ro" if readonly else "?mode=rw"), uri=True,
                                             timeout=BUSY_SECONDS if timeout is None else timeout, isolation_level=None)
            else:
                if self.marker.exists():
                    raise BudgetError("live_budget_policy_mismatch")
                self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                os.close(os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600))
                connection = sqlite3.connect(self.path, timeout=BUSY_SECONDS, isolation_level=None)
        except (OSError, sqlite3.Error) as exc:
            raise _database_failure(exc, self.policy is not None) from None
        try:
            with closing(connection):
                connection.execute("BEGIN" if readonly else "BEGIN IMMEDIATE")
                if self.policy is not None:
                    identity = connection.execute("SELECT id,policy FROM operating_identity").fetchall()
                    if identity != [(self.identity["id"], canonical(self.policy))]:
                        raise BudgetError("operating_ledger_replaced")
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
        except sqlite3.Error as exc:
            raise _database_failure(exc, self.policy is not None) from None

    def _bind_ceilings(self, db: sqlite3.Connection) -> None:
        if self.policy is not None:
            return
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='operating_identity'").fetchone():
            raise BudgetError("live_budget_policy_mismatch")
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

    def reserve(self, attempt_id: str, stage: str, recipient: str, request_digest: str, worst_case_nano: int, *,
                set_id: str | None = None, owner: str | None = None, binding_identity: str | None = None,
                allow_defer: bool = False, resume_unsent: bool = False) -> None:
        """Durably charge the worst case of one future call. The unique attempt id spans S2 and S3 and every process."""
        with self._tx() as db:
            self._bind_ceilings(db)
            prior = db.execute("SELECT state,stage,recipient,request_digest,reserved_nano FROM reservations WHERE attempt_id=?", (attempt_id,)).fetchone()
            rearm = False
            if prior is not None:
                if self.policy is not None and prior[1:] == (stage, recipient, request_digest, worst_case_nano):
                    intent = db.execute("SELECT set_id,dispatched,deferred,receipt FROM operating_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
                    if intent is not None and intent[0] == set_id and intent[1] == 0 and intent[3] is None:
                        rearm = ((prior[0] == "released" and intent[2] == 1)
                                 or (resume_unsent and prior[0] == "reserved"))
                if not rearm:
                    raise BudgetError("live_budget_attempt_duplicate")
            if self.policy is not None:
                if not owner:
                    raise BudgetError("operating_owner_required")
                self._operating_gate(db, owner=owner, allow_pause=allow_defer)
                item = db.execute("SELECT allowances,complete,pins FROM operating_sets WHERE id=?", (set_id,)).fetchone()
                if item is None or item[1]:
                    raise BudgetError("operating_set_unavailable")
                if binding_identity != json.loads(item[2])["runtimeIdentity"]:
                    raise BudgetError("operating_set_binding_changed")
                limit = json.loads(item[0]).get(stage, 0)
                count = db.execute("SELECT COUNT(*) FROM operating_attempts WHERE set_id=? AND stage=?", (set_id, stage)).fetchone()[0]
                if not rearm and count >= limit:
                    raise BudgetError("operating_stage_exhausted")
                if not rearm and db.execute("SELECT 1 FROM operating_attempts WHERE set_id=? AND stage=? AND request_digest=?",
                                            (set_id, stage, request_digest)).fetchone():
                    raise BudgetError("live_budget_request_duplicate")
                if db.execute("SELECT 1 FROM reservations WHERE state='reserved' AND (?=0 OR attempt_id!=?)", (int(rearm), attempt_id)).fetchone():
                    raise BudgetError("operating_unresolved_attempt")
            charged, calls = db.execute("SELECT COALESCE(SUM(charged_nano),0), COUNT(*) FROM reservations WHERE state!='released'").fetchone()
            if self.max_calls is not None and calls + 1 > self.max_calls:
                raise BudgetError("live_budget_exhausted_calls")
            if self.max_nano is not None and charged + worst_case_nano > self.max_nano:
                raise BudgetError("live_budget_exhausted_usd")
            now = _now()
            if rearm:
                db.execute("UPDATE reservations SET state='reserved',charged_nano=reserved_nano,updated_at=? WHERE attempt_id=?", (now, attempt_id))
                db.execute("UPDATE operating_attempts SET deferred=0 WHERE attempt_id=?", (attempt_id,))
                return
            db.execute("INSERT INTO reservations VALUES(?,?,?,?,'reserved',?,?,0,?,?)",
                       (attempt_id, stage, recipient, request_digest, worst_case_nano, worst_case_nano, now, now))
            if self.policy is not None:
                db.execute("INSERT INTO operating_attempts(attempt_id,set_id,stage,request_digest) VALUES(?,?,?,?)",
                           (attempt_id, set_id, stage, request_digest))

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
            if self.policy is not None:
                row = db.execute("SELECT dispatched FROM operating_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
                if row is None or row[0]:
                    raise BudgetError("operating_release_not_proven_unsent")
            db.execute("UPDATE reservations SET state='released', charged_nano=0, updated_at=? WHERE attempt_id=? AND state='reserved'",
                       (_now(), attempt_id))

    def snapshot(self) -> dict:
        """Totals for diagnostics and the smoke report: no attempt contents."""
        with self._tx(readonly=self.policy is not None) as db:
            self._bind_ceilings(db)
            charged, calls = db.execute("SELECT COALESCE(SUM(charged_nano),0), COUNT(*) FROM reservations WHERE state!='released'").fetchone()
            ceilings = dict(db.execute("SELECT key,value FROM meta").fetchall())
            states = dict(db.execute("SELECT state, COUNT(*) FROM reservations GROUP BY state").fetchall())
            if self.policy is not None:
                known, unknown, reserved = db.execute("""SELECT
                    COALESCE(SUM(CASE WHEN state='settled' AND usage_known=1 THEN charged_nano ELSE 0 END),0),
                    COALESCE(SUM(CASE WHEN state='settled' AND usage_known=0 THEN charged_nano ELSE 0 END),0),
                    COALESCE(SUM(CASE WHEN state='reserved' THEN charged_nano ELSE 0 END),0) FROM reservations""").fetchone()
                control = db.execute("SELECT state,reason,drain_until FROM operating_control").fetchone()
                sets = db.execute("SELECT COUNT(*),COALESCE(SUM(complete),0) FROM operating_sets").fetchone()
                return {"mode": MODE, "ledgerId": self.identity["id"], "chargedUsd": usd(charged), "calls": calls,
                        "maxUsd": None, "maxCalls": None, "remainingUsd": None, "states": states,
                        "settledKnownUsageUsd": usd(known), "settledUnknownUsageUsd": usd(unknown), "outstandingHoldUsd": usd(reserved),
                        "control": {"state": control[0], "reason": control[1], "drainUntil": control[2]},
                        "sets": {"admitted": sets[0], "complete": sets[1]}}
        return {"chargedUsd": usd(charged), "calls": calls, "maxUsd": usd(ceilings["max_nano"]), "maxCalls": ceilings["max_calls"], "states": states}

    def _operating_gate(self, db, *, admission: bool = False, owner: str | None = None, allow_pause: bool = False) -> None:
        state, drain, current_owner, pid = db.execute("SELECT state,drain_until,owner,owner_pid FROM operating_control").fetchone()
        if owner is not None and (owner != current_owner or pid != os.getpid()):
            raise BudgetError("operating_owner_lost")
        if (self.path.parent / "force-stop.json").exists():
            raise BudgetError("operating_stopped")
        now = time.time()
        lifecycle = self.policy["lifecycle"]
        if lifecycle["kind"] == "deadline":
            end = timestamp(lifecycle["until"])
            if now >= end + (0 if admission else self.policy["drainSeconds"]):
                raise BudgetError("operating_deadline")
        if state == "stopped" or (state == "paused" and (admission or not allow_pause)) or (state == "stopping" and (admission or now >= drain)):
            raise BudgetError("operating_" + state)

    def check_active(self, owner: str) -> None:
        with self._tx(timeout=0, readonly=True) as db:
            self._operating_gate(db, owner=owner)

    @contextmanager
    def lock(self, name: str):
        """A kernel-held process/thread gate; lock files are part of the initialization identity."""
        self._check_identity()
        try:
            fd = os.open(self.path.parent / name, os.O_RDWR | os.O_NOFOLLOW)
        except OSError:
            raise BudgetError("operating_lock_unavailable") from None
        try:
            if os.fstat(fd).st_ino != self.identity["locks"][name]:
                raise BudgetError("operating_lock_replaced")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise BudgetError("operating_busy") from None
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def owner(self):
        with self.lock("owner.lock"):
            token = uuid.uuid4().hex
            with self._tx() as db:
                db.execute("UPDATE operating_control SET owner=?,owner_pid=?", (token, os.getpid()))
                db.execute("INSERT INTO operating_history(at,action,reason) VALUES(?,'owner','acquired')", (time.time(),))
            try:
                yield token
            except KeyboardInterrupt:
                self.control("force-stop", "owner-signal")
                raise
            finally:
                with self._tx() as db:
                    db.execute("UPDATE operating_control SET owner=NULL,owner_pid=NULL WHERE owner=?", (token,))

    def control(self, action: str, reason: str) -> None:
        if action not in {"pause", "resume", "stop", "force-stop"} or not isinstance(reason, str) or not 1 <= len(reason) <= 200:
            raise BudgetError("operating_control_invalid")
        if action == "force-stop":
            intent = self.path.parent / "force-stop.json"
            try:
                with intent.open("x") as output:
                    os.chmod(intent, 0o600)
                    output.write(canonical({"reason": reason, "at": time.time()}))
                    output.flush()
                    os.fsync(output.fileno())
                fd = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except FileExistsError:
                pass
        with self._tx(timeout=BUSY_SECONDS) as db:
            state, drain, resume = db.execute("SELECT state,drain_until,resume_state FROM operating_control").fetchone()
            if state == "stopped" or (action == "resume" and state != "paused") or (state == "stopping" and action == "stop"):
                raise BudgetError("operating_control_terminal")
            if action == "pause":
                target, resume = "paused", resume if state == "paused" else state
            elif action == "resume":
                target, resume = resume, None
            elif action == "stop":
                target = "paused" if state == "paused" else "stopping"
                resume = "stopping" if state == "paused" else None
                drain = time.time() + self.policy["drainSeconds"] if drain is None else drain
            else:
                target, resume = "stopped", None
            db.execute("UPDATE operating_control SET state=?,reason=?,drain_until=?,resume_state=?", (target, reason, drain, resume))
            db.execute("INSERT INTO operating_history(at,action,reason) VALUES(?,?,?)", (time.time(), action, reason))

    def _fault_pause(self, db, reason: str) -> None:
        state = db.execute("SELECT state FROM operating_control").fetchone()[0]
        if state in {"running", "stopping"}:
            db.execute("UPDATE operating_control SET state='paused',reason=?,resume_state=?", (reason, state))
            db.execute("INSERT INTO operating_history(at,action,reason) VALUES(?,'pause',?)", (time.time(), reason))

    def defer(self, attempt_id: str, code: str) -> None:
        with self._tx() as db:
            row = db.execute("""SELECT r.state,a.dispatched FROM reservations r JOIN operating_attempts a USING(attempt_id)
                                WHERE attempt_id=?""", (attempt_id,)).fetchone()
            if code != "operating_paused" or row != ("reserved", 0):
                raise BudgetError("operating_deferral_not_proven")
            db.execute("UPDATE reservations SET state='released',charged_nano=0,updated_at=? WHERE attempt_id=?", (_now(), attempt_id))
            db.execute("UPDATE operating_attempts SET deferred=1 WHERE attempt_id=?", (attempt_id,))
            db.execute("INSERT INTO operating_deferrals(attempt_id,at,code) VALUES(?,?,?)", (attempt_id, time.time(), code))

    def is_deferred(self, attempt_id: str) -> bool:
        with self._tx(readonly=True) as db:
            return db.execute("""SELECT 1 FROM reservations r JOIN operating_attempts a USING(attempt_id)
                                 WHERE attempt_id=? AND r.state='released' AND a.dispatched=0 AND a.deferred=1""",
                              (attempt_id,)).fetchone() is not None

    def admit_set(self, set_id: str, pins: dict, allowances: dict, owner: str, *, jobs: tuple[str, ...] = (),
                  source_context: dict | None = None) -> None:
        allowances = stage_allowances(allowances)
        with self._tx() as db:
            row = db.execute("SELECT pins,allowances FROM operating_sets WHERE id=?", (set_id,)).fetchone()
            expected = (canonical(pins), canonical(allowances))
            if row is not None:
                if row != expected:
                    raise BudgetError("operating_set_binding_changed")
                return
            self._operating_gate(db, admission=True, owner=owner)
            lifecycle = self.policy["lifecycle"]
            if lifecycle["kind"] == "frontier" and set_id not in lifecycle["setIds"]:
                raise BudgetError("operating_frontier_refused")
            for job in jobs:
                claim = db.execute("SELECT value FROM operating_bindings WHERE name=?", ("job:" + job,)).fetchone()
                if claim is not None and claim[0] != canonical(set_id):
                    raise BudgetError("operating_binding_changed")
            if source_context is not None:
                bound = db.execute("SELECT value FROM operating_bindings WHERE name='native-input-context'").fetchone()
                if bound is not None and bound[0] != canonical(source_context):
                    raise BudgetError("operating_source_context_changed")
                db.execute("INSERT OR IGNORE INTO operating_bindings VALUES('native-input-context',?)", (canonical(source_context),))
            for job in jobs:
                db.execute("INSERT OR IGNORE INTO operating_bindings VALUES(?,?)", ("job:" + job, canonical(set_id)))
            db.execute("INSERT INTO operating_sets(id,pins,allowances) VALUES(?,?,?)", (set_id, *expected))

    def complete_set(self, set_id: str) -> None:
        with self._tx() as db:
            if db.execute("""SELECT 1 FROM reservations r JOIN operating_attempts a USING(attempt_id)
                             WHERE a.set_id=? AND r.state='reserved'""", (set_id,)).fetchone():
                raise BudgetError("operating_unresolved_attempt")
            db.execute("UPDATE operating_sets SET complete=1 WHERE id=?", (set_id,))
            lifecycle = self.policy["lifecycle"]
            completed = {row[0] for row in db.execute("SELECT id FROM operating_sets WHERE complete=1")}
            if lifecycle["kind"] == "frontier" and completed == set(lifecycle["setIds"]):
                db.execute("UPDATE operating_control SET state='stopped',reason='frontier-complete'")
                db.execute("INSERT INTO operating_history(at,action,reason) VALUES(?,'stop','frontier-complete')", (time.time(),))

    def begin_send(self, attempt_id: str, owner: str) -> None:
        with self._tx() as db:
            self._operating_gate(db, owner=owner)
            last = db.execute("SELECT last_send FROM operating_control").fetchone()[0]
            if time.time() - last < self.policy["minIntervalMilliseconds"] / 1000:
                raise BudgetError("operating_pacing")
            changed = db.execute("UPDATE operating_attempts SET dispatched=1 WHERE attempt_id=? AND dispatched=0", (attempt_id,)).rowcount
            if changed != 1:
                raise BudgetError("live_budget_attempt_duplicate")
            db.execute("UPDATE operating_control SET last_send=?", (time.time(),))

    def pacing_delay(self) -> float:
        with self._tx(readonly=True) as db:
            last = db.execute("SELECT last_send FROM operating_control").fetchone()[0]
            return max(0, self.policy["minIntervalMilliseconds"] / 1000 - (time.time() - last))

    def record_response(self, attempt_id: str, receipt: dict, actual_nano: int | None, *, fault: str | None = None) -> None:
        """Commit raw evidence and exact settlement together, before the native stage can decode it."""
        with self._tx() as db:
            row = db.execute("SELECT state,charged_nano FROM reservations WHERE attempt_id=?", (attempt_id,)).fetchone()
            if row is None or row[0] != "reserved":
                raise BudgetError("operating_receipt_conflict")
            charged = row[1] if actual_nano is None else actual_nano
            db.execute("UPDATE reservations SET state='settled',charged_nano=?,usage_known=?,updated_at=? WHERE attempt_id=?",
                       (charged, int(actual_nano is not None), _now(), attempt_id))
            db.execute("UPDATE operating_attempts SET receipt=? WHERE attempt_id=?", (canonical(receipt), attempt_id))
            status = receipt["http"]["status"]
            if fault is not None or actual_nano is None or not 200 <= status < 300:
                reason = fault if fault is not None else ("usage-unresolved" if 200 <= status < 300 else "provider-" + str(status))
                self._fault_pause(db, reason)

    def receipt(self, attempt_id: str) -> dict | None:
        with self._tx(readonly=True) as db:
            row = db.execute("SELECT receipt FROM operating_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            return json.loads(row[0]) if row is not None and row[0] is not None else None

    def bind(self, name: str, value) -> None:
        with self._tx() as db:
            row = db.execute("SELECT value FROM operating_bindings WHERE name=?", (name,)).fetchone()
            if row is not None and row[0] != canonical(value):
                raise BudgetError("operating_binding_changed")
            db.execute("INSERT OR IGNORE INTO operating_bindings VALUES(?,?)", (name, canonical(value)))

    def bound(self, name: str):
        with self._tx(readonly=True) as db:
            row = db.execute("SELECT value FROM operating_bindings WHERE name=?", (name,)).fetchone()
            return json.loads(row[0]) if row else None

    def sets(self) -> list[dict]:
        with self._tx(readonly=True) as db:
            return [{"id": row[0], "pins": json.loads(row[1]), "complete": bool(row[2])}
                    for row in db.execute("SELECT id,pins,complete FROM operating_sets ORDER BY rowid")]

    def attempts(self) -> dict[str, dict]:
        with self._tx(readonly=True, timeout=BUSY_SECONDS) as db:
            return {row[0]: {"state": row[1], "setId": row[2], "stage": row[3], "dispatched": bool(row[4]), "receipt": row[5] is not None}
                    for row in db.execute("""SELECT r.attempt_id,r.state,a.set_id,a.stage,a.dispatched,a.receipt
                                             FROM reservations r JOIN operating_attempts a USING(attempt_id)""")}
