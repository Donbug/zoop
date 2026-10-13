"""The single supervised dispatcher thread for S2 extraction jobs.

The initial intent of an accepted job is one `resume`, claimed once. Everything after that is an explicit `recover`:

  * a child that timed out, died or produced unreadable output, and a row a dead service left in flight, are AMBIGUOUS: the child may already
    have reserved or sent a replay call. They end `idle` (`transport_unknown`, `service_restarted`) and are never run again automatically. The
    pipeline turns a call it reserved but never saw answered into `reconciling` and never resends it, but that is the pipeline's rule for an explicit
    resume, not a licence for this service to start a second attempt on its own;
  * `extraction_busy` / `ingestion_busy` as a pipeline ERROR are the one automatic retry. The pipeline raises them while opening its ledger lock or
    the ingestion reader, before any command effect, so nothing ran; they are retried with a bounded backoff and then left for an explicit recover.
    A busy that happens INSIDE an execution is different: the pipeline records the job `stopped` (failure `ingestion_busy`) and answers a normal
    result, which is `exited` here and only an explicit recover resumes it. The pipeline is not changed to retry that.

Authority first, on every dispatch (the first included): before any child the owner's approval for the job must still be exactly the one the job was
reserved under and the fixture files must still be the pinned bytes, otherwise the dispatch ends idle with that refusal code and no child is started.
A later recover (after the operator restores the approval or the fixture) is explicit.

The gate is the one the relation dispatcher uses, so an S2 child and an S3 child can never run at the same time (the pipeline's ledger lock does
not wait, and S3 reads the very ledger S2 writes).

This is sound because the pipeline is replay-only (`live_mode_unsupported`): a repeated attempt can cost nothing, and the rules above do not depend
on that. Before any live S2 the pipeline needs an under-lock initial-only flag like the S1 worker's.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from .extraction_ledger import Claim, ExtractionLedger, Pins
from .extraction_runtime import ExtractionProcess
from .extraction_wire import ExtractionView
from .relation_dispatch import GATE_POLL, IDLE_POLL, policy
from .relation_ledger import Update
from .relation_runtime import RelationGate
from .runtime import Outcome

BUSY_CODES = frozenset({"extraction_busy", "ingestion_busy"})


def call_pin_problem(view: ExtractionView, pins: Pins) -> str | None:
    """Every receipt must have been answered by exactly the pinned fixture bytes (the topic stage by the topic fixture, the others by the producer
    fixture). This is what closes the window between the service's digest check and the child's own read of the file."""
    for call in view.calls:
        wanted = pins.topic_digest if call.stage == "topic" else pins.producer_digest
        if wanted is None or call.fixture_hash != wanted:
            return "fixture_changed"
    return None


class ExtractionDispatcher:
    def __init__(self, ledger: ExtractionLedger, process: ExtractionProcess, gate: RelationGate, log: Callable[[dict[str, Any]], None],
                 authorize: Callable[[str, Pins, str], str | None]):
        """`authorize(owner, pins, job id)` returns None when the approval and fixtures are still the reserved ones, otherwise a stable refusal code."""
        self._ledger, self._process, self._gate, self._log, self._authorize = ledger, process, gate, log, authorize
        self._wake, self._stop = threading.Event(), threading.Event()
        self._unrecorded: tuple[Claim, Update] | None = None  # a finished dispatch whose ledger write has not yet succeeded
        self._thread = threading.Thread(target=self._loop, name="zoop-ai-extraction-dispatcher", daemon=True)

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
                self._log({"event": "extraction_dispatcher_error", "errorClass": type(error).__name__})
                self._stop.wait(1.0)
                continue
            self._wake.wait(IDLE_POLL)
            self._wake.clear()

    def step(self) -> bool:
        """Claim and supervise at most one dispatch. The outcome of a finished child is held until its ledger write succeeds, and only that write
        is retried: a ledger fault never reruns the child."""
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

    def _view(self, claim: Claim, outcome: Outcome) -> tuple[Outcome, ExtractionView | None, Update | None]:
        """Parse a result outcome and bind it to the claim: another job, another input digest or another fixture is a binding mismatch and is
        never used for anything."""
        if outcome.kind != "result":
            return outcome, None, None
        try:
            view = ExtractionView.model_validate(outcome.result)
        except ValidationError:
            return Outcome("abnormal", exit_code=outcome.exit_code), None, None
        if view.job_id != claim.job_id or view.input_digest != claim.pins.input_digest:
            self._log({"event": "extraction_dispatch", "jobId": claim.job_id, "outcome": "binding_mismatch"})
            return outcome, view, Update("idle", "runtime_error", "runtime_binding_mismatch")
        problem = call_pin_problem(view, claim.pins)
        if problem is not None:
            self._log({"event": "extraction_dispatch", "jobId": claim.job_id, "outcome": problem})
            return outcome, view, Update("idle", "runtime_error", problem)
        return outcome, view, None

    def _supervise(self, claim: Claim) -> Update | None:
        if not self._hold_gate():
            return None
        try:
            refusal = self._authorize(claim.owner, claim.pins, claim.job_id)
            if refusal is not None:
                self._log({"event": "extraction_dispatch", "jobId": claim.job_id, "outcome": refusal})
                return Update("idle", "runtime_error", refusal)
            outcome = self._process.resume(claim.job_id, topic=claim.pins.topic_digest is not None, stop=self._stop)
        finally:
            self._gate.release()
        if outcome.kind == "abandoned":
            return None
        outcome, view, mismatch = self._view(claim, outcome)
        if mismatch is not None:
            return mismatch
        update = policy(outcome, view, busy_count=claim.busy_count, busy_codes=BUSY_CODES)
        self._log({"event": "extraction_dispatch", "jobId": claim.job_id, "runtime": outcome.kind, "runtimeExit": outcome.exit_code,
                   "runtimeCode": outcome.code, "outcome": update.last_outcome})
        return update
