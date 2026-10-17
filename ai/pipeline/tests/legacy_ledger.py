"""Extraction-ledger jobs as they were stored before the native analysis cutover, synthesized for isolated tests.

The original analysis adapter no longer exists in this repository. A legacy job is therefore produced by copying a real native job (its
frozen request, candidates, comparisons, dispositions and receipts) under a new job id and giving the copy the old binding shape
(PoC adapter identity and replay identity). The copy is inserted with plain SQL: the ledger's immutability triggers block UPDATE and
DELETE only, exactly as they did for the original writer. Nothing here is a reader or converter for the old format."""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from zoop_ai_pipeline.extraction_contracts import canonical, digest

LEGACY_ADAPTER = {"version": "zoop-extraction-poc-adapter-1", "candidate": "zoop-event-candidate-1",
                  "pocCommit": "fa446e7c72edfa06ec1a0e8e999199a21d31c695",
                  "analysisFingerprint": "da15369acc6aad52ebf877d341bb08041195ad9f6e0874bda1ed18b7e95eabb4",
                  "contextRevision": "role-context-3", "fingerprint": "f" * 64}
RESUME_MODES = {"queued": "resume", "stopped": "resume", "running": "resume", "reconciling": "reconcile_only", "ready": "none", "cancelled": "none"}


def ledger(root: Path) -> Path:
    return root / "extraction" / "extraction.sqlite3"


def legacy_binding(binding: dict, fixture_hash: str) -> dict:
    """The stored binding of an old job: PoC adapter identity, v2 replay identity and the settings digest, around the same documents."""
    legacy = {k: v for k, v in binding.items() if k not in {"adapter", "replay"}}
    legacy["adapter"] = dict(LEGACY_ADAPTER)
    legacy["replay"] = {"format": "investmate-replay-v2", "synthetic": binding["replay"]["synthetic"], "promptVersion": binding["replay"]["promptVersion"],
                        "modelVersion": "authored-model-1", "analysisVersion": binding["replay"]["analysisVersion"], "embeddingVersion": "authored-embedding-1",
                        "fixtureHash": fixture_hash}
    legacy["settingsDigest"] = "e" * 64
    return legacy


def copy_as_legacy(root: Path, source_job: str, legacy_job: str, *, state: str = "ready", children: bool = True, failure: str | None = None,
                   fixture_hash: str | None = None) -> dict:
    """Insert `legacy_job` as a legacy copy of `source_job` and return its stored row (with its decoded binding).

    `children` copies the source's stages, candidates, comparisons, dispositions, topics and receipts (a `ready` or `stopped` job); without them
    the job is a frozen-but-never-run `queued` one. `reconciling` also carries one started-without-receipt call. `fixture_hash` is the
    replay hash bound into the job; by default the source's, so that a caller can resubmit the very same request and fixture bytes."""
    db = sqlite3.connect(ledger(root))
    db.row_factory = sqlite3.Row
    try:
        job = db.execute("SELECT * FROM jobs WHERE job_id=?", (source_job,)).fetchone()
        replay_hash = fixture_hash or job["replay_hash"]
        request = json.loads(job["request"])
        request["jobId"] = legacy_job
        binding = legacy_binding(json.loads(job["binding"]), replay_hash)
        input_digest = digest({"request": request, "replayFixtureHash": replay_hash})
        db.execute("INSERT INTO jobs(job_id,input_digest,request,binding,replay_hash,state,phase,failure,detail,resume_mode,fence,created_at,updated_at)"
                   " VALUES(?,?,?,?,?,?,?,?,NULL,?,0,?,?)",
                   (legacy_job, input_digest, canonical(request), canonical(binding), replay_hash, state,
                    "complete" if state == "ready" else "cancelled" if state == "cancelled" else "extract", failure, RESUME_MODES[state],
                    job["created_at"], job["updated_at"]))
        if children:
            for table, columns in (("stages", "stage,summary,completed_at"),
                                   ("event_candidates", "event_candidate_id,mention_candidate_id,document_id,document_version,raw_version,local_mention_id,state,reason,payload"),
                                   ("comparisons", "event_candidate_id,target_event_id,payload"), ("dispositions", "event_candidate_id,payload"),
                                   ("topic_candidates", "topic_candidate_id,payload")):
                for row in db.execute(f"SELECT {columns} FROM {table} WHERE job_id=?", (source_job,)).fetchall():
                    db.execute(f"INSERT INTO {table}(job_id,{columns}) VALUES(?,{','.join('?' * len(row))})", (legacy_job, *tuple(row)))
            for call in db.execute("SELECT * FROM calls WHERE job_id=?", (source_job,)).fetchall():
                db.execute("INSERT INTO calls VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           ("attempt-" + uuid.uuid4().hex, legacy_job, call["stage"], call["ref"], call["request_digest"], replay_hash, call["state"],
                            call["response"], call["response_digest"], call["verdict"], call["started_at"], call["received_at"]))
        if state == "reconciling":
            db.execute("INSERT INTO calls(attempt_id,job_id,stage,ref,request_digest,fixture_hash,state,started_at) VALUES(?,?,?,?,?,?,'started',?)",
                       ("attempt-" + uuid.uuid4().hex, legacy_job, "extract", "incoming", "a" * 64, replay_hash, job["created_at"]))
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        stored = dict(db.execute("SELECT * FROM jobs WHERE job_id=?", (legacy_job,)).fetchone())
    finally:
        db.close()
    return {**stored, "binding": binding, "request": request}


def rows(root: Path) -> list[dict]:
    """Every stored job row verbatim (fence, state, failure, updated_at included)."""
    db = sqlite3.connect(ledger(root))
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY job_id")]
    finally:
        db.close()


def counts(root: Path, job_id: str) -> dict[str, int]:
    db = sqlite3.connect(ledger(root))
    try:
        return {table: db.execute(f"SELECT COUNT(*) FROM {table} WHERE job_id=?", (job_id,)).fetchone()[0]
                for table in ("stages", "calls", "event_candidates", "comparisons", "dispositions", "topic_candidates")}
    finally:
        db.close()
