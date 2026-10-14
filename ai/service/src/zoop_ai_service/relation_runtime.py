"""The only door to the S3 pipeline: six fixed `zoop-ai-relation` commands, stdin JSON in, one canonical stdout JSON out.

The same rules as the S1 door (`runtime.py`, whose generic child runner this reuses): request data reaches the child only through an
anonymous stdin file, argv/environment/working directory are server-owned, stderr is discarded, the child runs in its own session.
Differences that matter:

  * the pipeline exits 2 BOTH for an error object and for a complete result whose delivery is withheld, so a withheld result is a
    `result` outcome (its status part is still needed) and only an object with an `error` key is an `error` outcome;
  * the pipeline takes its ledger lock without waiting, so the service serializes every relation child behind one `RelationGate`;
  * submit/inspect/cancel/review carry no fixture flag (the pipeline refuses them); only `resume` and `revalidate` name the server-owned fixtures.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .config import ServiceConfig
from .runtime import CODE, Deadlines, Outcome, WorkerProcess

RUNTIME_SCHEMA = "zoop-relation-s3"


class GateBusy(Exception):
    """The gate stayed taken for the whole wait."""


class RelationGate:
    """One relation child at a time. The dispatcher holds it for a whole resume; requests wait for it briefly and then answer busy."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def acquire(self, wait: float) -> bool:
        return self._lock.acquire(timeout=wait)

    def release(self) -> None:
        self._lock.release()

    @contextmanager
    def hold(self, wait: float) -> Iterator[None]:
        if not self._lock.acquire(timeout=wait):
            raise GateBusy
        try:
            yield
        finally:
            self._lock.release()


def interpreter(schema: str):
    """The exit-code and stdout interpretation of one pipeline contract: the S3 door and the S2 door differ only in their schema name."""
    def interpret(code: int, raw: bytes) -> Outcome:
        if code not in (0, 2):
            return Outcome("abnormal", exit_code=code)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return Outcome("abnormal", exit_code=code)
        if not isinstance(value, dict) or value.get("schemaVersion") != schema:
            return Outcome("abnormal", exit_code=code)
        if "error" in value:
            error = value["error"]
            name = error.get("code") if isinstance(error, dict) else None
            if code != 2 or not isinstance(name, str) or not CODE.fullmatch(name):
                return Outcome("abnormal", exit_code=code)
            return Outcome("error", code=name, exit_code=2)
        delivery = value.get("delivery")
        status = delivery.get("status") if isinstance(delivery, dict) else None
        if not isinstance(value.get("jobId"), str) or not isinstance(value.get("inputDigest"), str) \
                or status != ("current" if code == 0 else "withheld"):
            return Outcome("abnormal", exit_code=code)
        return Outcome("result", result=value, exit_code=code)
    return interpret


interpret = interpreter(RUNTIME_SCHEMA)


def reference(job_id: str) -> dict[str, str]:
    return {"schemaVersion": RUNTIME_SCHEMA, "jobId": job_id}


class RelationProcess:
    def __init__(self, config: ServiceConfig, deadlines: Deadlines = Deadlines()):
        assert config.relation is not None
        self._relation, self._deadlines = config.relation, deadlines
        self._runner = WorkerProcess(config, deadlines, env=config.relation.child_env)

    def _argv(self, command: str, *, fixtures: bool) -> list[str]:
        relation = self._relation
        argv = [str(relation.command), command, "--state-dir", str(relation.state_dir),
                "--extraction-state-dir", str(relation.extraction_state_dir),
                "--ingestion-state-dir", str(relation.ingestion_state_dir), "--sources", str(relation.sources_path)]
        if fixtures:
            argv += ["--replay", str(relation.producer_replay), "--verifier-replay", str(relation.verifier_replay)]
        return argv

    def submit(self, body: dict[str, Any]) -> Outcome:
        """Registration only: the pipeline freezes the upstream as a queued job; no fixture, call or candidate."""
        return self._runner.execute(self._argv("submit", fixtures=False), body, self._deadlines.quick, interpret=interpret)

    def inspect(self, job_id: str) -> Outcome:
        return self._runner.execute(self._argv("inspect", fixtures=False), reference(job_id), self._deadlines.quick, interpret=interpret)

    def cancel(self, job_id: str) -> Outcome:
        return self._runner.execute(self._argv("cancel", fixtures=False), reference(job_id), self._deadlines.quick, interpret=interpret)

    def resume(self, job_id: str, stop: threading.Event | None = None) -> Outcome:
        return self._runner.execute(self._argv("resume", fixtures=True), reference(job_id), self._deadlines.long, stop, interpret=interpret)

    def review(self, job_id: str, relation_candidate_id: str, expected_revision: int, decision: str, reviewer: str, note: str) -> Outcome:
        """Append one HOLD review event, compare-and-set on the relation's own revision inside the pipeline's transaction. No fixture, no call.
        `reviewer` is the authenticated principal and `note` the operation marker: both are service-derived, never request text."""
        body = {**reference(job_id), "relationCandidateId": relation_candidate_id, "expectedRevision": expected_revision,
                "decision": decision, "reviewer": reviewer, "note": note}
        return self._runner.execute(self._argv("review", fixtures=False), body, self._deadlines.quick, interpret=interpret)

    def revalidate(self, job_id: str, relation_candidate_id: str, expected_revision: int, stop: threading.Event | None = None) -> Outcome:
        """One automatic verification attempt over the stored candidate, compare-and-set on the revision the review left. The pipeline sends
        at most one call per attempt ordinal and never resends a started one, so repeating this command can only finish a saved receipt."""
        body = {**reference(job_id), "relationCandidateId": relation_candidate_id, "expectedRevision": expected_revision}
        return self._runner.execute(self._argv("revalidate", fixtures=True), body, self._deadlines.long, stop, interpret=interpret)
