"""Exclusive SQLite policy, cumulative quota and immutable paired plan authority.

No file grants participate in this authority. Every execution carries an admission
ID frozen in the service reservation; retirement is terminal and never refunds.
"""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from . import plan_verify

from . import extraction_access
from .config import ConfigError, ServiceConfig
from .jobs import ApiError
from .ledger import stamp
from .plan_verify import decode, digest, read_file, sha

FILE = "plan-authority.sqlite3"
SCHEMA = "zoop-ai-plan-authority-1"
MAX_RECORD = 32_000_000
MAX_RECORDS = 10_000


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fail(code, status=409):
    raise ApiError(status, code)


def expires(document):
    return datetime.fromisoformat(document["expiresAt"].replace("Z", "+00:00")).timestamp()


def etag(revision, pin):
    return f'"plan-policy-{revision}-{pin or "none"}"'


def binding(config):
    extraction, relation = config.extraction, config.relation
    paths = {"service": config.state_dir, "plan": config.plan_root,
             "extraction": extraction.state_dir, "ingestion": extraction.ingestion_state_dir,
             "relationParent": relation.state_dir.parent}
    directories = {}
    for name, path in paths.items():
        if os.path.realpath(path) != str(path):
            raise OSError("unsafe binding")
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise OSError("unsafe binding")
        directories[name] = [str(path), info.st_dev, info.st_ino]
    lock = (config.state_dir / "service.lock").lstat()
    if not stat.S_ISREG(lock.st_mode) or lock.st_nlink != 1 or lock.st_uid != os.getuid():
        raise OSError("unsafe process lock")
    return {"directories": directories, "relation": str(relation.state_dir), "sources": str(extraction.sources_path),
            "serviceLock": [lock.st_dev, lock.st_ino],
            "extractionCommand": str(extraction.command), "relationCommand": str(relation.command),
            "producerReplay": str(extraction.producer_replay), "topicReplay": None if extraction.topic_replay is None else str(extraction.topic_replay),
            "relationReplay": str(relation.producer_replay), "relationVerifierReplay": str(relation.verifier_replay),
            "live": None if config.pipeline_live is None else {
                "public": {k: v for k, v in config.pipeline_live.public.items() if k != "ZOOP_AI_PIPELINE_LIVE_TIMEOUT_SECONDS"},
                "budgetDirectory": os.path.realpath(config.pipeline_live.budget["ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR"])},
            "principals": [{"name": p.name, "scopes": sorted(p.scopes)} for p in config.principals],
            **({"roundProfile": config.rounds.binding()} if config.rounds is not None else {})}


def lock_creation_allowed(config):
    """Pre-lock guard: only a fresh online profile may create its first lock inode."""
    from .online_bootstrap import present
    if present(config.state_dir) or any(os.path.lexists(config.state_dir / name) for name in (FILE, "authority-mode.json")):
        return False
    if config.plan_root is not None and any(
            p.name != "service.lock" and not (p.name == "transport" and p.is_dir() and not any(p.iterdir()))
            for p in config.state_dir.iterdir()):
        raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "authority_mode_mismatch")
    return True


def startup_mode(config, *, lock=None):
    """Classify and finish owned initialization before any runtime-ledger writes."""
    path = config.state_dir / FILE
    marker = config.state_dir / "authority-mode.json"
    online = config.plan_root is not None
    try:
        from . import online_bootstrap
        initializing = online_bootstrap.present(config.state_dir)
        if initializing or online and not os.path.lexists(marker):
            if not online:
                raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "authority_mode_mismatch")
            if lock is None:
                raise ValueError("initialization requires held process lock")
            online_bootstrap.initialize(config, lock)
        if os.path.lexists(marker):
            value = decode(read_file(marker, 4096, owned=True))
            legacy = {"schemaVersion": "zoop-ai-authority-mode-1", "mode": "online" if online else "manual"}
            if value == online_bootstrap.MODE:
                if not online or not os.path.lexists(config.state_dir / online_bootstrap.ROOT):
                    raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "authority_mode_mismatch")
                if lock is None:
                    raise ValueError("online startup requires held process lock")
                if not initializing:
                    online_bootstrap.initialize(config, lock)
            elif value != legacy or initializing:
                raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "authority_mode_mismatch")
            if online and not path.exists():
                raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "authority_unavailable")
            if online:
                for filename, table in (("service.sqlite3", "analysis_jobs"), ("extraction-jobs.sqlite3", "extraction_jobs"),
                                        ("relation-jobs.sqlite3", "relation_jobs")):
                    ledger = config.state_dir / filename
                    info = ledger.lstat()
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
                        raise ValueError("missing control ledger")
                    db = sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True)
                    try:
                        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                            raise ValueError("corrupt control ledger")
                        if table != "analysis_jobs" and db.execute(f"SELECT 1 FROM {table} WHERE authority_ref IS NULL LIMIT 1").fetchone():
                            raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "authority_mode_mismatch")
                    finally:
                        db.close()
        elif online:
            # A pre-existing service profile is never interpreted as a fresh online one.
            if any(p.name != "service.lock" and not (p.name == "transport" and p.is_dir() and not any(p.iterdir()))
                   for p in config.state_dir.iterdir()):
                raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "authority_mode_mismatch")
        elif os.path.lexists(path):
            raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "authority_mode_mismatch")
        if online and os.path.lexists(config.state_dir / "plan-install"):
            raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "authority_mode_mismatch")
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, plan_verify.InstallError):
        raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "authority_unavailable") from None
    return marker


@dataclass(frozen=True)
class AuthorizedS2:
    approval: extraction_access.Approval
    authority_ref: str


@dataclass(frozen=True)
class AuthorizedS3:
    submission: dict
    runtime: dict
    authority_ref: str


DDL = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE policies(revision INTEGER PRIMARY KEY, digest TEXT NOT NULL, document TEXT NOT NULL);
CREATE TABLE policy_operations(operator TEXT NOT NULL, key TEXT NOT NULL, body_digest TEXT NOT NULL,
 expected_etag TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(operator,key));
CREATE TABLE admissions(id TEXT PRIMARY KEY, owner TEXT NOT NULL, plan_id TEXT UNIQUE NOT NULL,
 plan_digest TEXT NOT NULL, revision INTEGER NOT NULL REFERENCES policies(revision), policy_digest TEXT NOT NULL,
 accepted_at TEXT NOT NULL, manifest TEXT NOT NULL, verification TEXT NOT NULL, inactive TEXT);
CREATE TABLE grants(s2_id TEXT PRIMARY KEY, s3_id TEXT UNIQUE NOT NULL, admission TEXT NOT NULL REFERENCES admissions(id),
 owner TEXT NOT NULL, approval TEXT NOT NULL, relation_submit TEXT NOT NULL, runtime TEXT NOT NULL);
CREATE TRIGGER admission_identity BEFORE UPDATE ON admissions
 WHEN NOT (OLD.id=NEW.id AND OLD.owner=NEW.owner AND OLD.plan_id=NEW.plan_id AND OLD.plan_digest=NEW.plan_digest
 AND OLD.revision=NEW.revision AND OLD.policy_digest=NEW.policy_digest AND OLD.accepted_at=NEW.accepted_at
 AND OLD.manifest=NEW.manifest AND OLD.verification=NEW.verification AND OLD.inactive IS NULL AND NEW.inactive IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER admission_delete BEFORE DELETE ON admissions BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER grants_update BEFORE UPDATE ON grants BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER grants_delete BEFORE DELETE ON grants BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER policy_update BEFORE UPDATE ON policies BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER policy_delete BEFORE DELETE ON policies BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER operation_update BEFORE UPDATE ON policy_operations BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER operation_delete BEFORE DELETE ON policy_operations BEGIN SELECT RAISE(ABORT,'immutable'); END;
"""


def prepare_authority(config, directory):
    """Create a private empty image; no runtime caller can initialize authority."""
    path = directory / FILE
    db = sqlite3.connect(path, isolation_level=None)
    try:
        os.chmod(path, 0o600)
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA synchronous=FULL")
        db.executescript("BEGIN IMMEDIATE;" + DDL)
        for key, value in {"schema": SCHEMA, "binding": canonical(binding(config)), "revision": "0",
                           "plans": "0", "units": "0", "expired_revision": "0"}.items():
            db.execute("INSERT INTO meta VALUES (?,?)", (key, value))
        db.execute("COMMIT")
    finally:
        db.close()


class PlanAuthority:
    def __init__(self, config: ServiceConfig, *, clock=time.time):
        self.config, self.clock = config, clock
        self._guard = threading.RLock()
        path = config.state_dir / FILE
        existing = os.path.lexists(path)
        try:
            self._binding = binding(config)
            if not existing:
                raise ValueError("missing authority state")
            if existing:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
                    raise ValueError("unsafe store")
            self._db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=10, isolation_level=None, check_same_thread=False)
            os.chmod(path, 0o600)
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            if self._meta("schema") != SCHEMA or self._meta("binding") != canonical(self._binding):
                raise ValueError("foreign store")
            if self._db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("corrupt store")
            # Validate complete required tables/counters, not just the SQLite header.
            for table in ("policies", "policy_operations", "admissions", "grants"):
                self._db.execute(f"SELECT * FROM {table} LIMIT 1").fetchall()
            for key in ("revision", "plans", "units", "expired_revision"):
                if int(self._meta(key)) < 0:
                    raise ValueError("corrupt counters")
            self.current()
            info = path.lstat()
            self._store_identity = (info.st_dev, info.st_ino)
        except (OSError, ValueError, sqlite3.Error, KeyError, TypeError):
            raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "authority_unavailable") from None

    def close(self):
        self._db.close()

    def _meta(self, key):
        row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if row is None:
            raise ValueError("missing meta")
        return row[0]

    @contextmanager
    def _tx(self):
        with self._guard:
            try:
                info = (self.config.state_dir / FILE).lstat()
            except OSError:
                fail("authority_unavailable", 503)
            if (info.st_dev, info.st_ino) != self._store_identity or not stat.S_ISREG(info.st_mode):
                fail("authority_unavailable", 503)
            try:
                self._db.execute("BEGIN IMMEDIATE")
                yield self._db
                self._db.execute("COMMIT")
            except BaseException as error:
                try:
                    if self._db.in_transaction:
                        self._db.execute("ROLLBACK")
                    # Observed expiry survives refusal, without committing any attempted admission.
                    self._db.execute("BEGIN IMMEDIATE")
                    self._observe()
                    self._db.execute("COMMIT")
                except (sqlite3.Error, ValueError, TypeError, KeyError):
                    if self._db.in_transaction:
                        self._db.execute("ROLLBACK")
                    fail("authority_unavailable", 503)
                if isinstance(error, sqlite3.Error):
                    fail("authority_unavailable", 503)
                raise

    def current(self):
        with self._guard:
            revision = int(self._meta("revision"))
            if not revision:
                return 0, None, None
            row = self._db.execute("SELECT * FROM policies WHERE revision=?", (revision,)).fetchone()
            document = json.loads(row["document"])
            if digest(document) != row["digest"]:
                raise ValueError("policy corrupt")
            return revision, row["digest"], document

    def _observe(self):
        revision, pin, policy = self.current()
        reason = ("policy_disabled" if policy is None or not policy["enabled"] else
                  "policy_expired" if expires(policy) <= self.clock() or int(self._meta("expired_revision")) == revision else None)
        if reason:
            if reason == "policy_expired":
                self._db.execute("UPDATE meta SET value=? WHERE key='expired_revision'", (str(revision),))
            self._db.execute("UPDATE admissions SET inactive=? WHERE inactive IS NULL", (reason,))
        return revision, pin, policy, reason

    def policy_status(self):
        with self._tx():
            revision, pin, policy, reason = self._observe()
            status = "unconfigured" if policy is None else "disabled" if not policy["enabled"] else "expired" if reason else "enabled"
            return {"schemaVersion": "zoop-ai-plan-policy-state-1", "revision": revision, "policyDigest": pin,
                    "policy": policy, "status": status, "usage": {"plans": int(self._meta("plans")), "units": int(self._meta("units"))}}

    def set_policy(self, operator, key, document, expected):
        from .plan_wire import parse_plan_policy_document
        document = parse_plan_policy_document(document)
        pin = digest(document)
        with self._tx() as db:
            old = db.execute("SELECT * FROM policy_operations WHERE operator=? AND key=?", (operator, key)).fetchone()
            if old:
                if (old["body_digest"], old["expected_etag"]) != (pin, expected):
                    fail("idempotency_conflict")
                return json.loads(old["result"])
            revision, current_pin, current = self.current()
            if expected != etag(revision, current_pin):
                fail("policy_conflict", 412)
            changed = document != current
            if changed and document["enabled"]:
                if document["principal"] not in {p.name for p in self.config.principals}:
                    fail("invalid_request", 422)
                if expires(document) <= self.clock():
                    fail("policy_expired")
            if changed:
                if revision >= 9_223_372_036_854_775_807:
                    fail("authority_unavailable", 503)
                revision += 1
                db.execute("INSERT INTO policies VALUES (?,?,?)", (revision, pin, canonical(document)))
                db.execute("UPDATE meta SET value=? WHERE key='revision'", (str(revision),))
                db.execute("UPDATE admissions SET inactive=? WHERE inactive IS NULL", ("policy_replaced" if document["enabled"] else "policy_disabled",))
            result = {"schemaVersion": "zoop-ai-plan-policy-update-1", "operationId": key,
                      "revision": revision, "policyDigest": pin, "changed": changed}
            db.execute("INSERT INTO policy_operations VALUES (?,?,?,?,?)", (operator, key, pin, expected, canonical(result)))
            return result

    def capture(self, owner):
        with self._tx():
            revision, pin, policy, reason = self._observe()
            if reason:
                fail("policy_expired" if reason == "policy_expired" else "admission_disabled")
            if policy["principal"] != owner:
                fail("policy_denied", 403)
            return revision, pin, policy

    def find(self, owner, plan_id, plan_digest, *, query=False):
        with self._tx():
            self._observe()
            row = self._db.execute("SELECT * FROM admissions WHERE plan_id=?", (plan_id,)).fetchone()
            if row is None or row["owner"] != owner:
                if query:
                    fail("admission_not_found", 404)
                if row is not None:
                    fail("idempotency_conflict")
                return None
            if row["plan_digest"] != plan_digest:
                fail("admission_not_found" if query else "idempotency_conflict", 404 if query else 409)
            return self._envelope(row)

    def _envelope(self, row):
        return {"schemaVersion": "zoop-ai-plan-admission-1", "admissionId": row["id"], "acceptedAt": row["accepted_at"],
                "policyRevision": row["revision"], "policyDigest": row["policy_digest"], "manifest": json.loads(row["manifest"]),
                "authority": {"state": "inactive" if row["inactive"] else "active", "reason": row["inactive"]}}

    def commit(self, owner, captured, manifest, verification, grants, recheck):
        encoded = canonical({"manifest": manifest, "verification": verification, "grants": grants})
        if len(encoded.encode()) > MAX_RECORD or not grants:
            fail("plan_verification_failed")
        identity = "pa-" + digest({"format": "zoop-plan-admission-identity-1", "principal": owner,
                                   "planId": manifest["planId"], "planDigest": manifest["planDigest"]})
        with self._tx() as db:
            old = db.execute("SELECT * FROM admissions WHERE plan_id=?", (manifest["planId"],)).fetchone()
            if old:
                if (old["owner"], old["plan_digest"]) != (owner, manifest["planDigest"]):
                    fail("idempotency_conflict")
                self._observe()
                return False, self._envelope(db.execute("SELECT * FROM admissions WHERE id=?", (old["id"],)).fetchone())
            revision, pin, policy, reason = self._observe()
            if (revision, pin) != captured[:2]:
                fail("policy_changed")
            if reason:
                fail("policy_expired" if reason == "policy_expired" else "admission_disabled")
            if binding(self.config) != self._binding:
                fail("service_configuration_invalid", 503)
            recheck()
            plans, units = int(self._meta("plans")), int(self._meta("units"))
            if plans + 1 > policy["limits"]["maxPlans"] or units + len(grants) > policy["limits"]["maxUnits"]:
                fail("quota_exhausted")
            if plans >= MAX_RECORDS or units + len(grants) > MAX_RECORDS:
                fail("authority_unavailable", 503)
            if any(db.execute("SELECT 1 FROM grants WHERE s2_id=? OR s3_id=?", (g["s2"], g["s3"])).fetchone() for g in grants):
                fail("authority_collision")
            db.execute("INSERT INTO admissions VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                       (identity, owner, manifest["planId"], manifest["planDigest"], revision, pin, stamp(self.clock()), canonical(manifest), canonical(verification)))
            for grant in grants:
                db.execute("INSERT INTO grants VALUES (?,?,?,?,?,?,?)", (grant["s2"], grant["s3"], identity, owner,
                           canonical(grant["approval"]), canonical(grant["submission"]), canonical(policy["runtime"])))
            for key, value in (("plans", plans + 1), ("units", units + len(grants))):
                db.execute("UPDATE meta SET value=? WHERE key=?", (str(value), key))
            return True, self._envelope(db.execute("SELECT * FROM admissions WHERE id=?", (identity,)).fetchone())

    def _grant(self, owner, job_id, family):
        with self._tx() as db:
            self._observe()
            row = db.execute(f"SELECT g.*, a.inactive FROM grants g JOIN admissions a ON a.id=g.admission WHERE g.{family}_id=? AND g.owner=?", (job_id, owner)).fetchone()
            if row is None:
                fail("request_not_approved" if family == "s2" else "upstream_not_allowed", 403)
            if row["inactive"]:
                fail(row["inactive"])
            changed = binding(self.config) != self._binding
            if changed:
                db.execute("UPDATE admissions SET inactive='service_configuration_invalid' WHERE id=? AND inactive IS NULL", (row["admission"],))
        if changed:
            fail("service_configuration_invalid", 503)
        return row

    def resolve_s2(self, owner, job_id, approved_request_digest):
        row = self._grant(owner, job_id, "s2")
        document = {"schemaVersion": extraction_access.SCHEMA, "approvals": [json.loads(row["approval"])]}
        approval = extraction_access.parse(canonical(document).encode(), [owner], topic_available=self.config.extraction.topic_replay is not None,
                                           live_available=self.config.pipeline_live is not None).find(owner, job_id)
        if approval.approved_digest != approved_request_digest:
            fail("idempotency_conflict")
        return AuthorizedS2(approval, row["admission"])

    def resolve_s3(self, owner, job_id, submission):
        row = self._grant(owner, job_id, "s3")
        if submission.wire() != json.loads(row["relation_submit"]):
            fail("upstream_not_allowed", 403)
        result = AuthorizedS3(json.loads(row["relation_submit"]), json.loads(row["runtime"]), row["admission"])
        problem = self._fixtures(result.runtime)
        if problem:
            fail(problem)
        return result

    def _fixtures(self, runtime):
        if runtime["kind"] == "live":
            return None if self.config.pipeline_live else "live_unavailable"
        e, r = self.config.extraction, self.config.relation
        pairs = [(e.producer_replay, runtime["producerReplayDigest"]), (r.producer_replay, runtime["relationReplayDigest"]),
                 (r.verifier_replay, runtime["relationVerifierReplayDigest"])]
        if runtime["topicReplayDigest"] is not None:
            pairs.append((e.topic_replay, runtime["topicReplayDigest"]))
        return None if all(path is not None and extraction_access.file_digest(path) == pin for path, pin in pairs) else "fixture_changed"

    def _refuse(self, row, family):
        try:
            grant = self._grant(row.owner, row.job_id, family)
            if row.authority_ref is None or row.authority_ref != grant["admission"]:
                return "authority_origin_mismatch"
            return self._fixtures(json.loads(grant["runtime"]))
        except (ApiError, OSError, ValueError, sqlite3.Error) as error:
            return error.code if isinstance(error, ApiError) else "authority_unavailable"

    def refuse_s2(self, row):
        return self._refuse(row, "s2")

    def refuse_s3(self, row):
        return self._refuse(row, "s3")

    def refuse_s3_result(self, row, raw):
        """Close replay fixture read races using durable pipeline receipt identities, without exposing them."""
        problem = self.refuse_s3(row)
        if problem is not None:
            return problem
        try:
            grant = self._grant(row.owner, row.job_id, "s3")
            runtime, submission = json.loads(grant["runtime"]), json.loads(grant["relation_submit"])
            if (raw["jobId"] != row.job_id or raw["inputDigest"] != digest(submission)
                    or raw["provenance"] != submission["provenance"]):
                return "runtime_binding_mismatch"
            if runtime["kind"] == "live":
                frozen = raw["binding"]["runtime"]
                if frozen["identity"] != runtime["liveRuntimeIdentity"]:
                    return "live_binding_changed"
                return None if all(c["fixtureHash"] == digest(frozen) for c in raw["calls"]) else "live_binding_changed"
            for call in raw["calls"]:
                if call["stage"] in ("relation", "impact"):
                    pin = runtime["relationReplayDigest"]
                elif call["stage"] in ("verify-relation", "verify-impact"):
                    pin = runtime["relationVerifierReplayDigest"]
                else:
                    return "runtime_binding_mismatch"
                if call["fixtureHash"] != pin:
                    return "fixture_changed"
            return None
        except (KeyError, ValueError, TypeError):
            return "runtime_binding_mismatch"
        except (ApiError, OSError, sqlite3.Error) as error:
            return error.code if isinstance(error, ApiError) else "authority_unavailable"
