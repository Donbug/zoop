"""The only door to the S3 pipeline: five fixed `zoop-ai-relation` commands, stdin JSON in, one canonical stdout JSON out.

The same rules as the S1 door (`runtime.py`, whose generic child runner this reuses): request data reaches the child only through an
anonymous stdin file, argv/environment/working directory are server-owned, stderr is discarded, the child runs in its own session.
Differences that matter:

  * the pipeline exits 2 BOTH for an error object and for a complete result whose delivery is withheld, so a withheld result is a
    `result` outcome (its status part is still needed) and only an object with an `error` key is an `error` outcome;
  * the pipeline takes its ledger lock without waiting, so the service serializes every relation child behind one `RelationGate`;
  * submit/inspect/cancel/review carry no fixture flag (the pipeline refuses them); only a REPLAY `resume` names the server-owned fixtures;
  * environment: the replay-only child environment carries no provider key, URL, model setting or live switch. A LIVE job's `submit` child
    additionally gets the gate and the non-secret model settings, and only its `resume` child (the one that may send) the budget and both keys
    (`config.PipelineLive`). `inspect`, `cancel` and `review` never get any of it, and neither does any replay command.
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
        self._live = config.pipeline_live

    @property
    def live_available(self) -> bool:
        """Whether this service process was started with the live group. A live job whose service restarted WITHOUT it must never reach `_env`."""
        return self._live is not None

    def _env(self, live: bool, *, send: bool) -> dict[str, str] | None:
        """None: the runner's fixed replay-only environment."""
        if not live:
            return None
        assert self._live is not None
        base = self._relation.child_env
        return self._live.send_env(base) if send else self._live.freeze_env(base)

    def _argv(self, command: str, *, fixtures: bool) -> list[str]:
        relation = self._relation
        argv = [str(relation.command), command, "--state-dir", str(relation.state_dir),
                "--extraction-state-dir", str(relation.extraction_state_dir),
                "--ingestion-state-dir", str(relation.ingestion_state_dir), "--sources", str(relation.sources_path)]
        if fixtures:
            argv += ["--replay", str(relation.producer_replay), "--verifier-replay", str(relation.verifier_replay)]
        return argv

    def submit(self, body: dict[str, Any], *, live: bool = False) -> Outcome:
        """Registration only: the pipeline freezes the upstream as a queued job; no fixture, call or candidate. A live job's child additionally
        gets the gate and the non-secret model settings so the pipeline can freeze its runtime binding (no key, no budget)."""
        return self._runner.execute(self._argv("submit", fixtures=False), body, self._deadlines.quick, interpret=interpret,
                                    env=self._env(live, send=False))

    def inspect(self, job_id: str) -> Outcome:
        return self._runner.execute(self._argv("inspect", fixtures=False), reference(job_id), self._deadlines.quick, interpret=interpret)

    def cancel(self, job_id: str) -> Outcome:
        return self._runner.execute(self._argv("cancel", fixtures=False), reference(job_id), self._deadlines.quick, interpret=interpret)

    def resume(self, job_id: str, stop: threading.Event | None = None, *, live: bool = False, initial_only: bool = False) -> Outcome:
        """One execution attempt. `initial_only` is the pipeline's under-lock restriction for the automatic dispatch: it refuses
        (`initial_dispatch_taken`, no effect) a job that already took its first dispatch, so only an explicit recover can ever run it again.
        A live job names no fixture and gets the send environment; a replay job gets the fixtures and the replay-only environment."""
        argv = self._argv("resume", fixtures=not live)
        if initial_only:
            argv.append("--initial-only")
        return self._runner.execute(argv, reference(job_id), self._deadlines.long, stop, interpret=interpret, env=self._env(live, send=True))

    def review(self, job_id: str, relation_candidate_id: str, expected_revision: int, decision: str, reviewer: str, note: str) -> Outcome:
        """Append one review event (`allow` is the operator's FINAL approval, `reject` an exclusion), compare-and-set on the relation's own revision
        inside the pipeline's transaction. The pipeline re-checks the deterministic gate and the current source rights itself. No fixture, no call,
        no environment. `reviewer` is the authenticated principal and `note` the operation marker: both are service-derived, never request text."""
        body = {**reference(job_id), "relationCandidateId": relation_candidate_id, "expectedRevision": expected_revision,
                "decision": decision, "reviewer": reviewer, "note": note}
        return self._runner.execute(self._argv("review", fixtures=False), body, self._deadlines.quick, interpret=interpret)
