"""Shared USD and call budget for live S2/S3 provider calls: one SQLite file, durable across processes and process death.

A call is *reserved* before it is sent. The reservation charges the worst case (conservative rates, configured maximum output
including reasoning, an input upper bound from the exact request bytes) and stays charged until the outcome is known:

* `settled`  - a response was received. Reported usage replaces the worst case; missing or unusable usage keeps the worst case.
* `released` - the request was provably never sent (a refusal before the socket). Charged 0 and not counted as a call.
* `reserved` - nothing recorded after the reservation (process death, transport timeout, unknown outcome). Charged worst case
  and counted as a call forever: a reservation is never reused to send again.

Money is an integer number of nano-USD, so rates (USD per 1M tokens) are exact integers per token and no float is involved.
The ceilings bind on first use and may only decrease. Optional versioned funding binds account roles and a non-extendable window;
an unfunded historical ledger is never upgraded or silently interpreted as a funded ledger.
"""
from __future__ import annotations

import json
import re
import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .live_funding import BUCKET_MAX_NANO, CAPPED_POLICY_VERSION, is_set_policy, GENERATION_STAGES, VERIFY_STAGES, deadline, timestamp, validate_policy, finish_policy
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

    def __init__(self, directory: str | Path, max_nano: int, max_calls: int, *, funding: dict | None = None,
                 bucket_caps: dict[str, int] | None = None, finish_by: str | None = None):
        self.path = Path(directory) / DB_NAME
        self.max_nano, self.max_calls = max_nano, max_calls
        try:
            self.funding = validate_policy(funding) if funding is not None else None
        except ValueError:
            raise BudgetError("live_funding_config_invalid") from None
        self.capped_funding = bool(self.funding and self.funding["version"] == CAPPED_POLICY_VERSION)
        if self.capped_funding and (max_nano != self.funding["totalMaxNanoUsd"] or bucket_caps != self.funding["bucketMaxNanoUsd"]):
            raise BudgetError("live_funding_config_invalid")
        self.bucket_caps = dict(bucket_caps) if bucket_caps is not None else {"shared": BUCKET_MAX_NANO, "personal": BUCKET_MAX_NANO}
        if self.funding and (type(max_nano) is not int or not 0 < max_nano <= 2 * BUCKET_MAX_NANO
                             or type(max_calls) is not int or not 1 <= max_calls <= 100_000
                             or set(self.bucket_caps) != {"shared", "personal"}
                             or any(type(cap) is not int or not 0 <= cap <= BUCKET_MAX_NANO for cap in self.bucket_caps.values())):
            raise BudgetError("live_funding_config_invalid")
        self.set_funding = is_set_policy(self.funding)
        try:
            self.finish = finish_policy(finish_by) if finish_by is not None else None
            if self.finish and (not self.set_funding or timestamp(finish_by) <= timestamp(self.funding["admitUntil"])):
                raise ValueError("live_finish_policy_invalid")
        except ValueError:
            raise BudgetError("live_finish_policy_invalid") from None

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

    def _bind_funding(self, db: sqlite3.Connection) -> None:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='funding_policy'").fetchone()
        if self.funding is None:
            if exists:
                raise BudgetError("live_budget_policy_mismatch")
            return
        policy = canonical({k: v for k, v in self.funding.items() if k != "notAfter"})
        if not exists:
            if db.execute("SELECT 1 FROM meta LIMIT 1").fetchone() or db.execute("SELECT 1 FROM reservations LIMIT 1").fetchone():
                raise BudgetError("live_budget_policy_mismatch")
            db.execute("CREATE TABLE funding_policy(policy TEXT NOT NULL) STRICT")
            db.execute("INSERT INTO funding_policy VALUES(?)", (policy,))
            db.execute("""CREATE TABLE reservation_funding(
                attempt_id TEXT PRIMARY KEY, account_role TEXT NOT NULL, bucket TEXT NOT NULL) STRICT""")
            if self.set_funding:
                db.execute("""CREATE TABLE admitted_sets(
                    set_id TEXT PRIMARY KEY, unit_digest TEXT NOT NULL, plan TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('admitted','completed','blocked','unknown')),
                    admitted_at TEXT NOT NULL, finished_at TEXT) STRICT""")
                db.execute("""CREATE TABLE reservation_sets(
                    attempt_id TEXT PRIMARY KEY, set_id TEXT NOT NULL, stage TEXT NOT NULL,
                    request_digest TEXT NOT NULL, UNIQUE(set_id,stage,request_digest)) STRICT""")
                db.execute("""CREATE TABLE admission_stop(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), reason TEXT NOT NULL,
                    stopped_at TEXT NOT NULL, forced INTEGER NOT NULL) STRICT""")
                db.execute("""CREATE TABLE provider_invocations(
                    logical_id TEXT PRIMARY KEY, set_id TEXT NOT NULL, stage TEXT NOT NULL,
                    prepared_digest TEXT NOT NULL, binding_identity TEXT NOT NULL) STRICT""")
                db.execute("""CREATE TABLE provider_attempts(
                    attempt_id TEXT PRIMARY KEY, logical_id TEXT NOT NULL, ordinal INTEGER NOT NULL CHECK(ordinal IN (1,2)),
                    profile TEXT NOT NULL, request_digest TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('started','received','released','unknown')),
                    receipt TEXT, error TEXT, UNIQUE(logical_id,ordinal)) STRICT""")
        elif db.execute("SELECT policy FROM funding_policy").fetchall() != [(policy,)]:
            raise BudgetError("live_budget_policy_mismatch")
        self._bind_finish(db)

    def _finish_authority(self, db):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='finish_authority'").fetchone():
            return None
        rows = db.execute("SELECT policy FROM finish_authority").fetchall()
        try:
            policy = json.loads(rows[0][0])
            if len(rows) != 1 or finish_policy(policy["finishBy"]) != policy:
                raise ValueError
        except (IndexError, KeyError, TypeError, ValueError):
            raise BudgetError("live_finish_policy_invalid") from None
        return policy

    def _bind_finish(self, db):
        observed = self._finish_authority(db)
        if self.finish is None:
            return
        if observed is not None:
            if observed != self.finish:
                raise BudgetError("live_finish_policy_mismatch")
        else:
            # Only a fresh ledger can gain this authority; no historical upgrade.
            if db.execute("SELECT 1 FROM meta LIMIT 1").fetchone():
                raise BudgetError("live_finish_policy_mismatch")
            db.execute("CREATE TABLE finish_authority(singleton INTEGER PRIMARY KEY CHECK(singleton=1), policy TEXT NOT NULL) STRICT")
            db.execute("INSERT INTO finish_authority VALUES(1,?)", (canonical(self.finish),))

    def _check_deadline(self, db: sqlite3.Connection) -> None:
        finish = self._finish_authority(db)
        if finish is not None and (timestamp(finish["sendBefore"]) - datetime.fromisoformat(_now())).total_seconds() <= finish["maxHttpTimeoutSeconds"]:
            raise BudgetError("live_finish_deadline")
        if self.funding and not self.set_funding:
            end = db.execute("SELECT value FROM meta WHERE key='not_after_seconds'").fetchone()[0]
            if datetime.fromisoformat(_now()).timestamp() >= end:
                raise BudgetError("live_budget_deadline")

    def _bind_ceilings(self, db: sqlite3.Connection) -> None:
        for statement in SCHEMA.split(";"):
            if statement.strip():
                db.execute(statement)
        self._bind_funding(db)
        increase = False
        limits = [("max_nano", self.max_nano), ("max_calls", self.max_calls)]
        if self.funding:
            limits.extend((f"bucket_{name}", cap) for name, cap in self.bucket_caps.items())
            if not self.set_funding:
                limits.append(("not_after_seconds", int(deadline(self.funding["notAfter"]).timestamp())))
        deadline_increase = False
        for key, wanted in limits:
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            if row is None:
                db.execute("INSERT INTO meta VALUES(?,?)", (key, wanted))
            elif self.capped_funding and key != "max_calls" and wanted != row[0]:
                raise BudgetError("live_budget_policy_mismatch")
            elif wanted > row[0]:
                increase = True
                deadline_increase |= key == "not_after_seconds"
            elif wanted < row[0]:
                db.execute("UPDATE meta SET value=? WHERE key=?", (wanted, key))
        if increase:  # a decrease of the other ceiling is kept: the transaction commits on every deliberate refusal
            raise BudgetError("live_budget_deadline_increase" if deadline_increase else "live_budget_ceiling_increase")

    def _capacity_refusal(self, db: sqlite3.Connection, code: str, role: str | None) -> None:
        if self.funding and role == "personal-typesafe":
            db.execute("INSERT OR REPLACE INTO meta VALUES('verification_blocked',1)")
        raise BudgetError(code)

    def _funded_gate(self, db: sqlite3.Connection, role: str | None, extra_personal: int = 0) -> None:
        if not self.funding:
            return
        if role == "personal-typesafe":
            return
        if db.execute("SELECT 1 FROM meta WHERE key='verification_blocked' AND value=1").fetchone():
            raise BudgetError("live_budget_verification_blocked")
        charged = db.execute("""SELECT COALESCE(SUM(r.charged_nano),0) FROM reservations r
            JOIN reservation_funding f USING(attempt_id) WHERE f.bucket='personal' AND r.state!='released'""").fetchone()[0]
        if self.bucket_caps["personal"] - charged - extra_personal < self.funding["minimumVerifierReserveNanoUsd"]:
            raise BudgetError("live_budget_verification_blocked")

    def _require_sets(self):
        if not self.set_funding:
            raise BudgetError("live_budget_policy_mismatch")

    def close_admission(self, reason: str, *, forced: bool = False) -> None:
        """Persist stop intent. A soft close never revokes an admitted set."""
        self._require_sets()
        with self._tx() as db:
            self._bind_ceilings(db)
            db.execute("INSERT OR IGNORE INTO admission_stop VALUES(1,?,?,?)", (reason, _now(), int(forced)))
            if forced:
                db.execute("UPDATE admission_stop SET forced=1 WHERE singleton=1")

    def _check_admission(self, db):
        current = datetime.fromisoformat(_now())
        if current >= timestamp(self.funding["admitUntil"]):
            db.execute("INSERT OR IGNORE INTO admission_stop VALUES(1,'admission_cutoff',?,0)", (_now(),))
            raise BudgetError("live_set_admission_closed")
        if current < timestamp(self.funding["admitFrom"]):
            raise BudgetError("live_set_admission_not_open")
        if db.execute("SELECT 1 FROM admission_stop").fetchone():
            raise BudgetError("live_set_admission_closed")

    def check_admission(self) -> None:
        """Observe the common fence; admit_set repeats it atomically with admission."""
        self._require_sets()
        with self._tx() as db:
            self._bind_ceilings(db)
            self._check_admission(db)

    def admit_set(self, set_id: str, unit_digest: str, plan: dict[str, int]) -> None:
        """One admission, atomic with the cutoff/stop check; never an idempotent reset."""
        self._require_sets()
        if (not isinstance(set_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", set_id)
                or not isinstance(unit_digest, str) or not re.fullmatch(r"[a-f0-9]{64}", unit_digest)
                or not isinstance(plan, dict) or not set(plan) <= {stage for route in self.funding["roles"].values() for stage in route["stages"]}
                or any(type(n) is not int or not 0 <= n <= 100_000 for n in plan.values())
                or (not any(plan.values()) and not (plan == {} and self.finish is not None))):
            raise BudgetError("live_set_plan_invalid")
        with self._tx() as db:
            self._bind_ceilings(db)
            if db.execute("SELECT 1 FROM admitted_sets WHERE set_id=?", (set_id,)).fetchone():
                raise BudgetError("live_set_admission_duplicate")
            self._check_admission(db)
            db.execute("INSERT INTO admitted_sets VALUES(?,?,?,'admitted',?,NULL)", (set_id, unit_digest, canonical(plan), _now()))

    def set_status(self, set_id: str) -> str | None:
        self._require_sets()
        with self._tx() as db:
            self._bind_ceilings(db)
            row = db.execute("SELECT state FROM admitted_sets WHERE set_id=?", (set_id,)).fetchone()
            return row[0] if row else None

    def _check_set(self, db, set_id):
        if db.execute("SELECT 1 FROM admission_stop WHERE forced=1").fetchone():
            raise BudgetError("live_set_forced_stop")
        row = db.execute("SELECT unit_digest,plan,state FROM admitted_sets WHERE set_id=?", (set_id,)).fetchone()
        if row is None or row[2] != "admitted":
            raise BudgetError("live_set_not_admitted")
        return row

    def set_request_holder(self, set_id: str, stage: str, request_digest: str) -> dict | None:
        """Read the unique owner without reserving work or another HTTP allowance."""
        self._require_sets()
        with self._tx() as db:
            self._bind_ceilings(db)
            self._check_set(db, set_id)
            finish = self._finish_authority(db)
            if finish is not None and datetime.fromisoformat(_now()) >= timestamp(finish["sendBefore"]):
                raise BudgetError("live_finish_deadline")
            row = db.execute("""SELECT r.attempt_id,r.state,r.recipient,r.charged_nano,f.account_role,f.bucket
                                FROM reservation_sets s JOIN reservations r USING(attempt_id)
                                JOIN reservation_funding f USING(attempt_id)
                                WHERE s.set_id=? AND s.stage=? AND s.request_digest=?""",
                             (set_id, stage, request_digest)).fetchone()
            return dict(zip(("attemptId", "state", "recipient", "chargedNano", "accountRole", "bucket"), row)) if row else None

    def resume_set(self, set_id: str, unit_digest: str) -> dict:
        """Known-receipt continuation keeps the same immutable admission and counters."""
        self._require_sets()
        with self._tx() as db:
            self._bind_ceilings(db)
            row = self._check_set(db, set_id)
            if row[0] != unit_digest:
                raise BudgetError("live_set_identity_mismatch")
            if db.execute("""SELECT 1 FROM reservation_sets s JOIN reservations r USING(attempt_id)
                             WHERE s.set_id=? AND r.state='reserved'""", (set_id,)).fetchone():
                raise BudgetError("live_set_reconcile_only")
            return json.loads(row[1])

    def finish_set(self, set_id: str, state: str) -> None:
        self._require_sets()
        if state not in {"completed", "blocked", "unknown"}:
            raise BudgetError("live_set_state_invalid")
        with self._tx() as db:
            self._bind_ceilings(db)
            row = db.execute("SELECT state FROM admitted_sets WHERE set_id=?", (set_id,)).fetchone()
            if row is None or row[0] not in {"admitted", state}:
                raise BudgetError("live_set_not_admitted")
            db.execute("UPDATE admitted_sets SET state=?,finished_at=COALESCE(finished_at,?) WHERE set_id=?",
                       (state, _now(), set_id))

    def _reserve_set(self, db, set_id, stage, request_digest):
        row = self._check_set(db, set_id)
        limit = json.loads(row[1]).get(stage, 0)
        used = db.execute("SELECT COUNT(*) FROM reservation_sets WHERE set_id=? AND stage=?", (set_id, stage)).fetchone()[0]
        if used >= limit:
            raise BudgetError("live_set_work_exhausted")
        if db.execute("SELECT 1 FROM reservation_sets WHERE set_id=? AND stage=? AND request_digest=?",
                      (set_id, stage, request_digest)).fetchone():
            raise BudgetError("live_set_request_duplicate")

    def begin_invocation(self, logical_id: str, set_id: str, stage: str, prepared_digest: str, binding_identity: str):
        self._require_sets()
        with self._tx() as db:
            self._bind_ceilings(db)
            self._check_set(db, set_id)
            if db.execute("SELECT 1 FROM provider_invocations WHERE logical_id=?", (logical_id,)).fetchone():
                raise BudgetError("live_budget_attempt_duplicate")
            db.execute("INSERT INTO provider_invocations VALUES(?,?,?,?,?)",
                       (logical_id, set_id, stage, prepared_digest, binding_identity))

    def begin_provider_attempt(self, logical_id: str, attempt_id: str, ordinal: int, profile: str, request_digest: str):
        with self._tx() as db:
            self._bind_ceilings(db)
            invocation = db.execute("SELECT set_id FROM provider_invocations WHERE logical_id=?", (logical_id,)).fetchone()
            if invocation is None or ordinal not in (1, 2):
                raise BudgetError("live_chain_invalid")
            self._check_set(db, invocation[0])
            if db.execute("SELECT 1 FROM provider_attempts WHERE logical_id=? AND ordinal=?", (logical_id, ordinal)).fetchone():
                raise BudgetError("live_budget_attempt_duplicate")
            if ordinal == 2:
                previous = db.execute("SELECT state,error FROM provider_attempts WHERE logical_id=? AND ordinal=1", (logical_id,)).fetchone()
                if previous is None or previous[0] not in {"received", "released"} or previous[1] is None:
                    raise BudgetError("live_chain_predecessor_not_settled")
            db.execute("INSERT INTO provider_attempts VALUES(?,?,?,?,?,'started',NULL,NULL)",
                       (attempt_id, logical_id, ordinal, profile, request_digest))

    def record_provider_attempt(self, attempt_id: str, state: str, receipt: dict | None, error: dict | None):
        if state not in {"received", "released", "unknown"}:
            raise BudgetError("live_chain_invalid")
        with self._tx() as db:
            self._bind_funding(db)
            if db.execute("SELECT state FROM provider_attempts WHERE attempt_id=?", (attempt_id,)).fetchone() != ("started",):
                raise BudgetError("live_budget_attempt_duplicate")
            db.execute("UPDATE provider_attempts SET state=?,receipt=?,error=? WHERE attempt_id=?",
                       (state, canonical(receipt) if receipt is not None else None,
                        canonical(error) if error is not None else None, attempt_id))

    def provider_attempts(self, logical_id: str) -> list[dict]:
        if not self.set_funding:
            return []
        with self._tx() as db:
            self._bind_ceilings(db)
            rows = db.execute("""SELECT p.attempt_id,p.profile,p.state,p.receipt,p.error,r.reserved_nano,r.charged_nano,
                                 r.state,f.account_role,f.bucket,i.stage,p.request_digest,r.recipient FROM provider_attempts p
                                 JOIN provider_invocations i USING(logical_id)
                                 LEFT JOIN reservations r USING(attempt_id)
                                 LEFT JOIN reservation_funding f USING(attempt_id)
                                 WHERE p.logical_id=? ORDER BY p.ordinal""", (logical_id,)).fetchall()
            return [{"attemptId": row[0], "profile": row[1], "state": "unknown" if row[2] == "started" else row[2],
                     "receipt": json.loads(row[3]) if row[3] else None,
                     "error": json.loads(row[4]) if row[4] else None,
                     "stage": row[10], "requestDigest": row[11],
                     "recipient": row[12] or self.funding["roles"][row[1]]["recipient"],
                     "cost": {"reservedUsd": usd(row[5] or 0), "chargedUsd": usd(row[6] or 0),
                              "settled": row[7] == "settled", "usageKnown": False, "estimatedUsd": None},
                     "funding": {"accountRole": row[8] or row[1],
                                 "bucket": row[9] or self.funding["roles"][row[1]]["bucket"],
                                 "policyIdentity": digest(self.funding)}} for row in rows]


    def reserve(self, attempt_id: str, stage: str, recipient: str, request_digest: str, worst_case_nano: int, *,
                account_role: str | None = None, set_id: str | None = None) -> None:
        """Durably charge the worst case of one future call. The unique attempt id spans S2 and S3 and every process."""
        with self._tx() as db:
            self._bind_ceilings(db)
            if type(worst_case_nano) is not int or worst_case_nano < 0:
                raise BudgetError("live_budget_config_invalid")
            bucket = None
            if self.funding:
                route = self.funding["roles"].get(account_role)
                if route is None or route.get("stageRecipients", {}).get(stage, route["recipient"]) != recipient or stage not in route["stages"]:
                    raise BudgetError("live_budget_policy_mismatch")
                bucket = route["bucket"]
            elif account_role is not None:
                raise BudgetError("live_budget_policy_mismatch")
            self._check_deadline(db)
            if db.execute("SELECT 1 FROM reservations WHERE attempt_id=?", (attempt_id,)).fetchone():
                raise BudgetError("live_budget_attempt_duplicate")
            if self.set_funding:
                self._reserve_set(db, set_id, stage, request_digest)
            elif set_id is not None:
                raise BudgetError("live_budget_policy_mismatch")
            charged, calls = db.execute("SELECT COALESCE(SUM(charged_nano),0), COUNT(*) FROM reservations WHERE state!='released'").fetchone()
            if calls + 1 > self.max_calls:
                self._capacity_refusal(db, "live_budget_exhausted_calls", account_role)
            if charged + worst_case_nano > self.max_nano:
                self._capacity_refusal(db, "live_budget_exhausted_usd", account_role)
            if bucket:
                bucket_charged = db.execute("""SELECT COALESCE(SUM(r.charged_nano),0) FROM reservations r
                    JOIN reservation_funding f USING(attempt_id) WHERE f.bucket=? AND r.state!='released'""", (bucket,)).fetchone()[0]
                if bucket_charged + worst_case_nano > self.bucket_caps[bucket]:
                    self._capacity_refusal(db, "live_budget_exhausted_" + bucket, account_role)
            self._funded_gate(db, account_role, worst_case_nano if bucket == "personal" else 0)
            now = _now()
            db.execute("INSERT INTO reservations VALUES(?,?,?,?,'reserved',?,?,0,?,?)",
                       (attempt_id, stage, recipient, request_digest, worst_case_nano, worst_case_nano, now, now))
            if bucket:
                db.execute("INSERT INTO reservation_funding VALUES(?,?,?)", (attempt_id, account_role, bucket))
            if self.set_funding:
                db.execute("INSERT INTO reservation_sets VALUES(?,?,?,?)", (attempt_id, set_id, stage, request_digest))

    def check_send(self, attempt_id: str) -> None:
        """Recheck the funded window immediately before transport; settlement remains allowed after it closes."""
        if self.funding is None:
            return
        with self._tx() as db:
            self._bind_ceilings(db)
            if db.execute("SELECT state FROM reservations WHERE attempt_id=?", (attempt_id,)).fetchone() != ("reserved",):
                raise BudgetError("live_budget_attempt_duplicate")
            self._check_deadline(db)
            if self.set_funding:
                set_row = db.execute("SELECT set_id FROM reservation_sets WHERE attempt_id=?", (attempt_id,)).fetchone()
                if set_row is None:
                    raise BudgetError("live_set_not_admitted")
                self._check_set(db, set_row[0])
            role = db.execute("SELECT account_role FROM reservation_funding WHERE attempt_id=?", (attempt_id,)).fetchone()[0]
            charged, calls = db.execute("SELECT COALESCE(SUM(charged_nano),0),COUNT(*) FROM reservations WHERE state!='released'").fetchone()
            if calls > self.max_calls:
                self._capacity_refusal(db, "live_budget_exhausted_calls", role)
            if charged > self.max_nano:
                self._capacity_refusal(db, "live_budget_exhausted_usd", role)
            for name, cap in self.bucket_caps.items():
                total = db.execute("""SELECT COALESCE(SUM(r.charged_nano),0) FROM reservations r
                    JOIN reservation_funding f USING(attempt_id) WHERE f.bucket=? AND r.state!='released'""", (name,)).fetchone()[0]
                if total > cap:
                    self._capacity_refusal(db, "live_budget_exhausted_" + name, role)
            self._funded_gate(db, role)

    def settle(self, attempt_id: str, actual_nano: int | None) -> int:
        """A response arrived. `actual_nano` replaces the worst case only when the provider reported usable usage; None keeps it.
        Returns the nano-USD now charged for this attempt (an actual above the reservation is recorded, never hidden)."""
        with self._tx() as db:
            self._bind_funding(db)
            if actual_nano is not None and (type(actual_nano) is not int or actual_nano < 0):
                raise BudgetError("live_budget_config_invalid")
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
            self._bind_funding(db)
            db.execute("UPDATE reservations SET state='released', charged_nano=0, updated_at=? WHERE attempt_id=? AND state='reserved'",
                       (_now(), attempt_id))

    def snapshot(self) -> dict:
        """Totals for diagnostics and the smoke report: no attempt contents."""
        with self._tx() as db:
            self._bind_ceilings(db)
            charged, calls = db.execute("SELECT COALESCE(SUM(charged_nano),0), COUNT(*) FROM reservations WHERE state!='released'").fetchone()
            ceilings = dict(db.execute("SELECT key,value FROM meta").fetchall())
            states = dict(db.execute("SELECT state, COUNT(*) FROM reservations GROUP BY state").fetchall())
            result = {"chargedUsd": usd(charged), "calls": calls, "maxUsd": usd(ceilings["max_nano"]),
                      "maxCalls": ceilings["max_calls"], "states": states}
            finish = self._finish_authority(db)
            if finish is not None:
                result["finishAuthority"] = finish
            if self.funding:
                buckets = {}
                for name in self.bucket_caps:
                    total, count, actual, reserved, unknown = db.execute("""SELECT COALESCE(SUM(r.charged_nano),0), COUNT(*),
                        COALESCE(SUM(CASE WHEN r.usage_known=1 THEN r.charged_nano ELSE 0 END),0),
                        COALESCE(SUM(CASE WHEN r.state='reserved' THEN r.charged_nano ELSE 0 END),0),
                        COALESCE(SUM(CASE WHEN r.usage_known=0 THEN r.charged_nano ELSE 0 END),0)
                        FROM reservations r JOIN reservation_funding f USING(attempt_id)
                        WHERE f.bucket=? AND r.state!='released'""", (name,)).fetchone()
                    cap = ceilings["bucket_" + name]
                    buckets[name] = {"maxUsd": usd(cap), "chargedUsd": usd(total), "actualUsd": usd(actual),
                                     "reservedUsd": usd(reserved), "unknownUsd": usd(unknown),
                                     "remainingUsd": usd(max(0, cap - total)), "calls": count}
                result.update(buckets=buckets, fundingPolicyIdentity=digest(self.funding),
                              verificationBlocked=bool(ceilings.get("verification_blocked", 0)))
                if self.set_funding:
                    stop = db.execute("SELECT reason,stopped_at,forced FROM admission_stop").fetchone()
                    result.update(admitFrom=self.funding["admitFrom"], admitUntil=self.funding["admitUntil"],
                                  sets=dict(db.execute("SELECT state,COUNT(*) FROM admitted_sets GROUP BY state")),
                                  stopIntent=None if stop is None else {"reason": stop[0], "stoppedAt": stop[1], "forced": bool(stop[2])})
                else:
                    result["notAfter"] = datetime.fromtimestamp(ceilings["not_after_seconds"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return result
