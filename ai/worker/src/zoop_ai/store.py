"""Private execution ledger. Every network attempt is reserved and committed before send."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import SourceGrant, canonical, digest, now

DDL = """
CREATE TABLE IF NOT EXISTS jobs (
 job_id TEXT PRIMARY KEY, input_digest TEXT NOT NULL, request TEXT NOT NULL, configs TEXT NOT NULL,
 state TEXT NOT NULL, phase TEXT NOT NULL, failure TEXT, resume_mode TEXT NOT NULL,
 attempt_id TEXT, fence INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS calls (
 attempt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id), stage TEXT NOT NULL,
 request_digest TEXT NOT NULL, mode TEXT NOT NULL, state TEXT NOT NULL, fence INTEGER NOT NULL,
 config TEXT NOT NULL, fixture_digest TEXT, ordinal INTEGER, started_at TEXT NOT NULL,
 received_at TEXT, receipt TEXT, content TEXT, usage TEXT, error TEXT, duration_ms REAL,
 UNIQUE(job_id,stage));
CREATE TABLE IF NOT EXISTS budget_reservations (
 attempt_id TEXT PRIMARY KEY REFERENCES calls(attempt_id), scope TEXT NOT NULL, reserved_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS budgets (scope TEXT PRIMARY KEY, call_limit INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS artifacts (
 artifact_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id), kind TEXT NOT NULL,
 input_digest TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(job_id,kind));
CREATE TABLE IF NOT EXISTS grants (grant_id TEXT PRIMARY KEY, revision TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS grant_history (grant_id TEXT NOT NULL, revision TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(grant_id,revision));
CREATE TABLE IF NOT EXISTS cache (input_digest TEXT PRIMARY KEY, artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id));
CREATE TRIGGER IF NOT EXISTS immutable_artifact_update BEFORE UPDATE ON artifacts
 BEGIN SELECT RAISE(ABORT,'immutable artifact'); END;
CREATE TRIGGER IF NOT EXISTS immutable_artifact_delete BEFORE DELETE ON artifacts
 BEGIN SELECT RAISE(ABORT,'immutable artifact'); END;
CREATE TRIGGER IF NOT EXISTS immutable_received_receipt BEFORE UPDATE OF receipt,content,usage ON calls
 WHEN OLD.receipt IS NOT NULL BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
"""


class WorkerFailure(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        self.directory = directory
        self.path = directory / "worker.sqlite3"
        self.db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        os.chmod(self.path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(DDL)

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        else:
            self.db.execute("COMMIT")

    def close(self):
        self.db.close()

    def job(self, job_id: str):
        row = self.db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise WorkerFailure("job_not_found")
        return row

    def register_grants(self, grants: list[SourceGrant]):
        with self.transaction() as c:
            for grant in grants:
                payload = canonical(grant.wire())
                old = c.execute("SELECT payload FROM grant_history WHERE grant_id=? AND revision=?",
                                (grant.grant_id, grant.revision)).fetchone()
                if old and old["payload"] != payload:
                    raise WorkerFailure("grant_revision_conflict")
                c.execute("INSERT OR IGNORE INTO grant_history VALUES (?,?,?)", (grant.grant_id, grant.revision, payload))
                c.execute("INSERT INTO grants VALUES (?,?,?) ON CONFLICT(grant_id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload",
                          (grant.grant_id, grant.revision, payload))

    def grant(self, grant_id: str) -> SourceGrant | None:
        row = self.db.execute("SELECT payload FROM grants WHERE grant_id=?", (grant_id,)).fetchone()
        return SourceGrant.model_validate_json(row["payload"]) if row else None

    def authorize(self, request, kind: str, config) -> SourceGrant:
        grant = self.grant(request.input.grant_id)
        if grant is None or grant.rights != "known" or not grant.enabled or not grant.evidence:
            raise WorkerFailure("source_rights_unknown_or_denied")
        source_id = request.input.source_id if request.kind == "briefing-outlook" else request.input.document.source_id
        if grant.revision != request.input.grant_revision or grant.source_id != source_id:
            raise WorkerFailure("grant_revision_or_source_changed")
        if grant.source_id.lower().replace("_", "-") in {"naver-search", "naver-developers-search"}:
            raise WorkerFailure("naver_search_ai_prohibited")
        if grant.expires_at and datetime.fromisoformat(grant.expires_at) <= datetime.now(UTC):
            raise WorkerFailure("source_grant_expired")
        if not {"read", "store", "model-send", "quote-display"} <= set(grant.allowed_operations):
            raise WorkerFailure("source_operation_denied")
        recipient = config.provider if request.mode == "replay" else config.provider + ":" + config.provider_revision
        if kind not in grant.purposes or recipient not in grant.recipients:
            raise WorkerFailure("source_purpose_or_recipient_denied")
        return grant

    def configure_budget(self, limit: int):
        if limit <= 0:
            raise WorkerFailure("live_budget_required")
        with self.transaction() as c:
            previous = c.execute("SELECT call_limit FROM budgets WHERE scope='global'").fetchone()
            # Lowering is allowed; reopening a CLI cannot reset or silently increase an approved ledger ceiling.
            if previous and limit > previous["call_limit"]:
                raise WorkerFailure("budget_increase_requires_new_authorized_ledger")
            c.execute("INSERT INTO budgets VALUES ('global',?) ON CONFLICT(scope) DO UPDATE SET call_limit=excluded.call_limit", (limit,))

    def calls(self, job_id: str):
        return self.db.execute("SELECT * FROM calls WHERE job_id=? ORDER BY started_at,attempt_id", (job_id,)).fetchall()

    def artifacts(self, job_id: str):
        return [json.loads(r["payload"]) for r in self.db.execute("SELECT payload FROM artifacts WHERE job_id=? ORDER BY kind", (job_id,))]

    def status(self, job_id: str, state: str, phase: str, code: str | None = None,
               stage: str | None = None, resume: str = "none", *, fence: int | None = None):
        with self.transaction() as c:
            row = self.job(job_id)
            if fence is not None and row["fence"] != fence:
                return
            c.execute("UPDATE jobs SET state=?,phase=?,failure=?,resume_mode=? WHERE job_id=?",
                      (state, phase, canonical({"code": code, "stage": stage}) if code else None, resume, job_id))

    def reserve(self, *, job_id: str, stage: str, request_digest: str, config: dict[str, Any], mode: str,
                fence: int, attempt_id: str, fixture_digest: str | None):
        with self.transaction() as c:
            row = self.job(job_id)
            if row["fence"] != fence or row["state"] == "cancelled":
                raise WorkerFailure("execution_fence_changed")
            if mode == "live":
                budget = c.execute("SELECT call_limit FROM budgets WHERE scope='global'").fetchone()
                used = c.execute("SELECT COUNT(*) FROM budget_reservations WHERE scope='global'").fetchone()[0]
                if not budget or used >= budget[0]:
                    raise WorkerFailure("global_budget_exhausted")
            ordinal = c.execute("SELECT COUNT(*) FROM calls WHERE fixture_digest=?", (fixture_digest,)).fetchone()[0] if mode == "replay" else None
            c.execute("INSERT INTO calls(attempt_id,job_id,stage,request_digest,mode,state,fence,config,fixture_digest,ordinal,started_at) VALUES (?,?,?,?,?,'started',?,?,?,?,?)",
                      (attempt_id, job_id, stage, request_digest, mode, fence, canonical(config), fixture_digest, ordinal, now()))
            if mode == "live":
                c.execute("INSERT INTO budget_reservations VALUES (?,'global',?)", (attempt_id, now()))
            c.execute("UPDATE jobs SET state='running',phase='outgoingcall.started',attempt_id=? WHERE job_id=?", (attempt_id, job_id))
            return ordinal

    def receive(self, attempt_id: str, reply, duration_ms: float):
        # Deliberately independent from validation and the application import transaction. A response the adapter refused
        # (`reply.invalid`) is failed under its exact code in the SAME transaction as its receipt, so no crash can separate them.
        with self.transaction() as c:
            c.execute("UPDATE calls SET state=?,error=?,received_at=?,receipt=?,content=?,usage=?,duration_ms=? WHERE attempt_id=?",
                      ("failed" if reply.invalid else "received", reply.invalid, now(), canonical(reply.raw), reply.content,
                       canonical(reply.usage), duration_ms, attempt_id))
            c.execute("UPDATE jobs SET phase='receivedreceipt.saved' WHERE job_id=(SELECT job_id FROM calls WHERE attempt_id=?) AND state!='cancelled'", (attempt_id,))

    def save_artifact(self, artifact, cache_key: str | None, fence: int):
        with self.transaction() as c:
            row = self.job(artifact.job_id)
            if row["fence"] != fence or row["state"] == "cancelled":
                raise WorkerFailure("execution_fence_changed")
            c.execute("INSERT INTO artifacts VALUES (?,?,?,?,?)", (artifact.artifact_id, artifact.job_id, artifact.kind,
                      artifact.input_digest, canonical(artifact.wire())))
            if cache_key and artifact.validation.eligible:
                c.execute("INSERT OR IGNORE INTO cache VALUES (?,?)", (cache_key, artifact.artifact_id))
            c.execute("UPDATE calls SET state='validated' WHERE attempt_id=?", (artifact.attempt_id,))
