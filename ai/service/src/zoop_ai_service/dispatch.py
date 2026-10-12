"""Dispatch policy (pure) and the single supervised dispatcher thread.

One dispatcher, one child at a time: the runtime's replay ordinals are ledger-wide, so serial dispatch keeps fixtures consumed in
submission order, and concurrency would only be raised after latency is measured. The dispatcher never retries a provider call,
never turns an unknown outcome into a failure, and never resolves `reconciling`: it hands the same job back to the runtime, whose
per-job lock and receipt rules decide what may happen.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from .config import ServiceConfig
from .ledger import Claim, ServiceLedger, Update
from .runtime import Outcome, WorkerProcess
from .wire import JobView, continuation_would_send, receipts_complete

MAX_UNKNOWN = 3
MAX_BACKOFF = 60.0
UNKNOWN_DELAY = 1.0
IDLE_POLL = 0.25


def busy_delay(busy_count: int) -> float:
    return float(min(MAX_BACKOFF, 2 ** busy_count))


def execution_unavailable(config: ServiceConfig, mode: str) -> bool:
    """Current server-owned availability of the execution path for a mode (the same rule POST applies)."""
    return not config.live_available if mode == "live" else config.replay_path is None


def policy(command: str, outcome: Outcome, view: JobView | None, *, unknown_count: int, busy_count: int,
           fresh: bool = True) -> Update:
    """(command, outcome) -> the dispatch row's next state. `view` is the parsed runtime result when outcome.kind == 'result'.

    A non-fresh (automatic) redispatch ran with the runtime's under-lock initial-only restriction, so it cannot have sent a new
    stage. If the job it handed back holds some receipts but not all, nothing may continue it automatically: `needs_recover`.
    """
    if outcome.kind == "result":
        assert view is not None
        if not fresh and view.state in ("queued", "running", "persisting") and continuation_would_send(view):
            return Update("idle", None, "needs_recover")
        if view.state in ("queued", "running"):
            # `run` hands back `get` when another process holds the per-job lock: an orphan child or another runtime client.
            return Update("pending", command, "busy", None, busy_delay(busy_count), 0, busy_count + 1)
        if command == "run" and view.state == "persisting" and view.resume_mode == "save_only" and receipts_complete(view):
            # Every receipt this job needs is already stored, so this resume can only persist; it cannot reach a provider.
            return Update("pending", "resume", "exited")
        return Update("idle", None, "exited")
    if outcome.kind == "error":
        return Update("idle", None, "runtime_error", outcome.code)
    if outcome.kind in ("timeout", "abnormal"):
        unknown = unknown_count + 1
        if unknown >= MAX_UNKNOWN:
            return Update("idle", None, "transport_unknown", None, 0.0, unknown, 0)
        return Update("pending", command, "transport_unknown", None, UNKNOWN_DELAY, unknown, 0)
    return Update("idle", None, "runtime_unavailable")


class Dispatcher:
    def __init__(self, config: ServiceConfig, ledger: ServiceLedger, worker: WorkerProcess,
                 log: Callable[[dict[str, Any]], None]):
        self._config, self._ledger, self._worker, self._log = config, ledger, worker, log
        self._wake, self._stop = threading.Event(), threading.Event()
        self._unrecorded: tuple[str, Update] | None = None  # a finished dispatch whose ledger write has not yet succeeded
        self._thread = threading.Thread(target=self._loop, name="zoop-ai-dispatcher", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        """Never waits for or kills a child: an in-flight dispatch is abandoned and recovered by the next start."""
        self._stop.set()
        self._wake.set()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def wake(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self.step():
                    continue
            except Exception as error:  # a ledger fault must not kill supervision; the row stays recoverable
                self._log({"event": "dispatcher_error", "errorClass": type(error).__name__})
                self._stop.wait(1.0)
                continue
            self._wake.wait(IDLE_POLL)
            self._wake.clear()

    def step(self) -> bool:
        """Claim and supervise at most one dispatch. Returns whether any work was done.

        The outcome of a finished child is held until its ledger write succeeds, and only that write is retried: a ledger fault
        never reruns the worker, and no other row is claimed meanwhile.
        """
        if self._unrecorded is not None:
            job_id, update = self._unrecorded
            self._ledger.finish(job_id, update)
            self._unrecorded = None
            return True
        claim = self._ledger.claim_next()
        if claim is None:
            return False
        update = self._supervise(claim)
        if update is not None:
            self._unrecorded = (claim.job_id, update)
            self._ledger.finish(claim.job_id, update)
            self._unrecorded = None
        return True

    def _supervise(self, claim: Claim) -> Update | None:
        if execution_unavailable(self._config, claim.mode):
            self._log({"event": "dispatch", "jobId": claim.job_id, "command": claim.command, "outcome": "execution_unavailable"})
            return Update("idle", None, "runtime_error", "execution_unavailable")
        call = self._worker.run if claim.command == "run" else self._worker.resume
        # Only the original intent and an explicit recover run unrestricted; every automatic redispatch is restricted by the
        # runtime itself, under the job lock, so a snapshot that went stale cannot let it send a new stage.
        outcome = call(claim.job_id, self._stop, initial_only=not claim.fresh)
        if outcome.kind == "abandoned":
            return None
        view = None
        if outcome.kind == "result":
            try:
                view = JobView.model_validate(outcome.result)
            except ValidationError:
                outcome = Outcome("abnormal", exit_code=outcome.exit_code)
            else:
                if view.job_id != claim.job_id or view.input_digest != claim.input_digest:
                    self._log({"event": "dispatch", "jobId": claim.job_id, "command": claim.command, "outcome": "binding_mismatch"})
                    return Update("idle", None, "runtime_error", "runtime_binding_mismatch")
        update = policy(claim.command, outcome, view, unknown_count=claim.unknown_count, busy_count=claim.busy_count,
                        fresh=claim.fresh)
        self._log({"event": "dispatch", "jobId": claim.job_id, "command": claim.command, "runtime": outcome.kind,
                   "runtimeExit": outcome.exit_code, "runtimeCode": outcome.code, "outcome": update.last_outcome})
        return update
