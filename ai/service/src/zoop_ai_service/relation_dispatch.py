"""Dispatch policy (pure) and the single supervised dispatcher thread for S3 relation jobs and the revalidations their reviews request.

The initial intent of an accepted job is one `resume`, claimed once; the intent of an accepted `allow` review is one `revalidate`, claimed once.
Everything after that is an explicit `recover`:

  * a child that timed out, died or produced unreadable output, and a row a dead service left in flight, are AMBIGUOUS: the child may
    already have reserved or sent a call. They end `idle` (`transport_unknown`, `service_restarted`) and are never run again
    automatically. The pipeline itself turns a call that was reserved but never answered into `reconciling` and never resends it, but
    that is the pipeline's rule for an explicit resume, not a licence for this service to start a second attempt on its own;
  * `relation_busy` is the one automatic retry. The pipeline raises it while opening its ledger lock, before any command effect, so
    nothing ran; it is retried with a bounded backoff and then left for an explicit recover.

Revalidations share the dispatcher, the gate, the FIFO sequence, the cap and these rules with jobs, and add two more:

  * authority first: before any child the owner must still be listed for the job's upstream (the allowlist is re-read), otherwise the
    dispatch ends idle as `upstream_not_allowed` with no child started, and a later recover (after the operator restores access) is explicit;
  * a revalidation answered by "the relation moved" (`review_revision_conflict`, `revalidation_not_requested`) is settled by READING the chain
    in the same gate hold: a verdict at the next sequence means it was already verified, a reject there means the allow was superseded and
    nothing may overwrite the rejection. Whatever the chain does not prove stays unsettled for an explicit recover.

This is sound because the pipeline is replay-only (`live_mode_unsupported`): a repeated attempt can cost nothing, and the rules above
do not depend on that. Before any live S3 the pipeline needs an under-lock initial-only flag like the S1 worker's.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from pydantic import ValidationError

from .relation_ledger import Claim, RelationLedger, Update
from .relation_review import settlement
from .relation_runtime import RelationGate, RelationProcess
from .relation_wire import RelationChain, RelationView
from .runtime import Outcome

MAX_BUSY = 8
MAX_BACKOFF = 60.0
IDLE_POLL = 0.25
GATE_POLL = 0.25
BUSY_CODES = frozenset({"relation_busy"})
# The pipeline's answers to a revalidation of a relation that is no longer at the revision the review left.
MOVED_CODES = frozenset({"review_revision_conflict", "revalidation_not_requested"})


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
                 authorize: Callable[[str, str, str], str | None] | None = None):
        """`authorize(owner, upstream job id, upstream input digest)` returns None when the owner may still use that upstream, otherwise a stable
        refusal code. It is asked before every revalidation child (never for a job resume, whose authority was checked at submit)."""
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

    def _record(self, claim: Claim, update: Update) -> None:
        if claim.operation_id is None:
            self._ledger.finish(claim.job_id, update)
        else:
            self._ledger.finish_operation(claim.operation_id, update)

    def step(self) -> bool:
        """Claim and supervise at most one dispatch. The outcome of a finished child is held until its ledger write succeeds, and only
        that write is retried: a ledger fault never reruns the child."""
        if self._unrecorded is not None:
            claim, update = self._unrecorded
            self._record(claim, update)
            self._unrecorded = None
            return True
        claim = self._ledger.claim_next()
        if claim is None:
            return False
        update = self._supervise_operation(claim) if claim.operation_id is not None else self._supervise(claim)
        if update is not None:
            self._unrecorded = (claim, update)
            self._record(claim, update)
            self._unrecorded = None
        return True

    def _hold_gate(self) -> bool:
        """Wait for the gate; False when the service is stopping (the claim then stays in flight and no child was started for it)."""
        while not self._gate.acquire(GATE_POLL):
            if self._stop.is_set():
                return False
        return True

    def _view(self, claim: Claim, outcome: Outcome) -> tuple[Outcome, RelationView | None, Update | None]:
        """Parse a result outcome and bind it to the claim. A payload that does not parse is unreadable; one bound to another job, another
        input digest or (for a revalidation claim, which carries it) another upstream is a binding mismatch and is never used for anything."""
        if outcome.kind != "result":
            return outcome, None, None
        try:
            view = RelationView.model_validate(outcome.result)
        except ValidationError:
            return Outcome("abnormal", exit_code=outcome.exit_code), None, None
        upstream = view.binding.upstream
        bound_upstream = claim.upstream_job_id is None or (upstream.job_id, upstream.input_digest) == (claim.upstream_job_id, claim.upstream_input_digest)
        if view.job_id != claim.job_id or view.input_digest != claim.input_digest or not bound_upstream:
            self._log({"event": "relation_dispatch", "jobId": claim.job_id, "outcome": "binding_mismatch"})
            return outcome, view, Update("idle", "runtime_error", "runtime_binding_mismatch")
        return outcome, view, None

    def _supervise(self, claim: Claim) -> Update | None:
        if not self._hold_gate():
            return None
        try:
            outcome = self._process.resume(claim.job_id, self._stop)
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

    @staticmethod
    def _settled(claim: Claim, raw: dict[str, Any] | None) -> tuple[str, str | None] | None:
        """What the chain proves. `raw` has already been bound to the claim and reported delivery current; the chain's own identity is
        checked once more here, so no caller can settle from a chain of another job or input."""
        if raw is None:
            return None
        try:
            chain = RelationChain.model_validate(raw)
        except ValidationError:
            return None
        if chain.job_id != claim.job_id or chain.input_digest != claim.input_digest:
            return None
        assert claim.relation_candidate_id is not None and claim.review_revision is not None
        return settlement(chain, claim.relation_candidate_id, claim.review_revision)

    def _supervise_operation(self, claim: Claim) -> Update | None:
        """One `revalidate` for an accepted allow, under the gate. Authority first, then the one child, then (only when the pipeline says the
        relation moved) a read of the chain to settle what happened. Nothing here appends a review or sends a second call."""
        if not self._hold_gate():
            return None
        try:
            assert claim.owner is not None and claim.upstream_job_id is not None and claim.upstream_input_digest is not None
            refusal = None if self._authorize is None else self._authorize(claim.owner, claim.upstream_job_id, claim.upstream_input_digest)
            if refusal is not None:
                self._log({"event": "relation_revalidation", "operationId": claim.operation_id, "outcome": refusal})
                return Update("idle", "runtime_error", refusal)
            assert claim.relation_candidate_id is not None
            outcome = self._process.revalidate(claim.job_id, claim.relation_candidate_id, claim.expected_revision, self._stop)
            if outcome.kind == "abandoned":
                return None
            probe: Outcome | None = None
            if outcome.kind == "error" and outcome.code in MOVED_CODES:
                probe = self._process.inspect(claim.job_id)  # same gate hold: nothing else runs between the refusal and this read
        finally:
            self._gate.release()
        outcome, view, mismatch = self._view(claim, outcome)
        if mismatch is not None:
            return mismatch
        raw: dict[str, Any] | None = outcome.result if view is not None and view.delivery.status == "current" else None
        if probe is not None:
            # The probe is a read of the pipeline like any other: bound to the claimed job, input digest and upstream before ANY use. A valid
            # chain of another job (candidate ids repeat across jobs over one upstream) must never settle this operation: settlement is terminal.
            probe, probe_view, probe_mismatch = self._view(claim, probe)
            if probe_mismatch is not None:
                self._log({"event": "relation_revalidation", "operationId": claim.operation_id, "outcome": "probe_binding_mismatch"})
                return probe_mismatch
            if probe_view is not None and probe_view.delivery.status == "current":
                raw = probe.result
        update = policy(outcome, view, busy_count=claim.busy_count)
        settled = self._settled(claim, raw)
        if settled is not None:
            update = replace(update, settled=settled[0], settled_eligibility=settled[1])
        elif view is not None and update.runtime_code is None:
            # The child answered but the chain proves no verdict: keep the reason (the job's failure or the delivery gate) for the operator.
            update = replace(update, runtime_code=view.failure.code if view.failure is not None else view.delivery.code)
        self._log({"event": "relation_revalidation", "operationId": claim.operation_id, "runtime": outcome.kind, "runtimeExit": outcome.exit_code,
                   "runtimeCode": outcome.code, "outcome": update.last_outcome, "settled": update.settled})
        return update
