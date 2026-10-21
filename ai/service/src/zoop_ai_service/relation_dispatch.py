"""Dispatch policy (pure) and the single supervised dispatcher thread for S3 relation jobs.

The initial intent of an accepted job is one `resume`, claimed once, and run under the pipeline's own under-lock INITIAL-ONLY restriction: a job that
already took its first dispatch is refused (`initial_dispatch_taken`, no effect) however the service came to ask again. Everything after that is an
explicit `recover`, which is the only dispatch that runs without the restriction:

  * a child that timed out, died or produced unreadable output, and a row a dead service left in flight, are AMBIGUOUS: the child may
    already have reserved or sent a call. They end `idle` (`transport_unknown`, `service_restarted`) and are never run again
    automatically. The pipeline itself turns a call that was reserved but never answered into `reconciling` and never resends it, but
    that is the pipeline's rule for an explicit resume, not a licence for this service to start a second attempt on its own;
  * `relation_busy` is the one automatic retry. The pipeline raises it while opening its ledger lock, before any command effect, so
    nothing ran; it is retried with a bounded backoff and then left for an explicit recover.

A LIVE job (a model call that costs money) adds two rules: when the service was started without the live group the dispatch ends idle `live_unavailable` with no child; otherwise,
before any child, the owner must still be listed for the job's upstream with the same
pinned runtime identity (the allowlist is re-read), otherwise the dispatch ends idle with the refusal code and no child is started. A review
(`allow` is the operator's final approval) never dispatches anything: there is no revalidation to run.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from .relation_ledger import Claim, RelationLedger, Update
from .relation_runtime import RelationGate, RelationProcess
from .relation_wire import RelationView
from .runtime import Outcome

MAX_BUSY = 8
MAX_BACKOFF = 60.0
IDLE_POLL = 0.25
GATE_POLL = 0.25
BUSY_CODES = frozenset({"relation_busy"})


def busy_delay(busy_count: int) -> float:
    return float(min(MAX_BACKOFF, 2 ** busy_count))


def policy(outcome: Outcome, view: object | None, *, busy_count: int, busy_codes: frozenset[str] = BUSY_CODES) -> Update:
    """(outcome) -> the dispatch row's next state. `view` is the parsed pipeline result when outcome.kind == 'result'. `busy_codes` are the
    refusals the pipeline raises before any command effect (S3 default; the S2 door passes its own)."""
    if outcome.kind == "result":
        assert view is not None
        return Update("idle", "exited")
    if outcome.kind == "error":
        if outcome.code in busy_codes:
            if busy_count + 1 < MAX_BUSY:
                return Update("pending", "busy", outcome.code, busy_delay(busy_count), busy_count + 1)
            return Update("idle", "busy", outcome.code, 0.0, busy_count + 1)
        return Update("idle", "runtime_error", outcome.code)
    if outcome.kind in ("timeout", "abnormal"):
        return Update("idle", "transport_unknown")
    return Update("idle", "runtime_unavailable")


class RelationDispatcher:
    def __init__(self, ledger: RelationLedger, process: RelationProcess, gate: RelationGate, log: Callable[[dict[str, Any]], None],
                 authorize: Callable[[str, str, str, str], str | None] | None = None):
        """`authorize(owner, upstream job id, upstream input digest, pinned runtime identity)` returns None when the owner may still run this LIVE
        job, otherwise a stable refusal code. It is asked before every live child (never for a replay job, whose authority was checked at submit)."""
        self._ledger, self._process, self._gate, self._log = ledger, process, gate, log
        self._authorize = authorize
        self._wake, self._stop = threading.Event(), threading.Event()
        self._unrecorded: tuple[Claim, Update] | None = None  # a finished dispatch whose ledger write has not yet succeeded
        self._thread = threading.Thread(target=self._loop, name="zoop-ai-relation-dispatcher", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        """Never waits for or kills a child: an in-flight dispatch is abandoned and ends `service_restarted` at the next start."""
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
                self._log({"event": "relation_dispatcher_error", "errorClass": type(error).__name__})
                self._stop.wait(1.0)
                continue
            self._wake.wait(IDLE_POLL)
            self._wake.clear()

    def step(self) -> bool:
        """Claim and supervise at most one dispatch. The outcome of a finished child is held until its ledger write succeeds, and only
        that write is retried: a ledger fault never reruns the child."""
        if self._unrecorded is not None:
            claim, update = self._unrecorded
            self._ledger.finish(claim.job_id, update)
            self._unrecorded = None
            return True
        claim = self._ledger.claim_next()
        if claim is None:
            return False
        update = self._supervise(claim)
        if update is not None:
            self._unrecorded = (claim, update)
            self._ledger.finish(claim.job_id, update)
            self._unrecorded = None
        return True

    def _hold_gate(self) -> bool:
        """Wait for the gate; False when the service is stopping (the claim then stays in flight and no child was started for it)."""
        while not self._gate.acquire(GATE_POLL):
            if self._stop.is_set():
                return False
        return True

    def _view(self, claim: Claim, outcome: Outcome) -> tuple[Outcome, RelationView | None, Update | None]:
        """Parse a result outcome and bind it to the claim. A payload that does not parse is unreadable; one bound to another job or input
        digest is a binding mismatch and is never used for anything."""
        if outcome.kind != "result":
            return outcome, None, None
        try:
            view = RelationView.model_validate(outcome.result)
        except ValidationError:
            return Outcome("abnormal", exit_code=outcome.exit_code), None, None
        if view.job_id != claim.job_id or view.input_digest != claim.input_digest:
            self._log({"event": "relation_dispatch", "jobId": claim.job_id, "outcome": "binding_mismatch"})
            return outcome, view, Update("idle", "runtime_error", "runtime_binding_mismatch")
        return outcome, view, None

    def _supervise(self, claim: Claim) -> Update | None:
        if not self._hold_gate():
            return None
        try:
            if claim.live and not self._process.live_available:
                # The service was restarted without the live group while this job's dispatch was pending: nothing was sent, no child (and so
                # no model environment) is built, and the row ends idle so the operator can recover it once live is configured again.
                self._log({"event": "relation_dispatch", "jobId": claim.job_id, "outcome": "live_unavailable"})
                return Update("idle", "runtime_error", "live_unavailable")
            if claim.live:
                assert claim.owner is not None and claim.upstream_job_id is not None and claim.upstream_input_digest is not None
                refusal = ("live_binding_unpinned" if claim.live_binding is None or self._authorize is None else
                           self._authorize(claim.owner, claim.upstream_job_id, claim.upstream_input_digest, claim.live_binding))
                if refusal is not None:
                    self._log({"event": "relation_dispatch", "jobId": claim.job_id, "outcome": refusal})
                    return Update("idle", "runtime_error", refusal)
            outcome = self._process.resume(claim.job_id, self._stop, live=claim.live, initial_only=not claim.explicit)
        finally:
            self._gate.release()
        if outcome.kind == "abandoned":
            return None
        outcome, view, mismatch = self._view(claim, outcome)
        if mismatch is not None:
            return mismatch
        update = policy(outcome, view, busy_count=claim.busy_count)
        self._log({"event": "relation_dispatch", "jobId": claim.job_id, "runtime": outcome.kind, "runtimeExit": outcome.exit_code,
                   "runtimeCode": outcome.code, "outcome": update.last_outcome})
        return update
