"""The S3 relation-job operations (submit, status, result, cancel, recover) and the review operations (review, operation status, operation
recover), independent of HTTP framing. Blocking: callers run these in a worker thread.

Every state shown to a caller is read from the pipeline (`zoop-ai-relation inspect`) during the same request. The service ledger only
adds ownership, idempotency and the dispatch state, and it never holds a request body or a candidate. The one exception is an operation's
status, which is content-free and read from the service ledger alone, so a caller can always look an operation up (a crash included).

Authority at delivery. Content leaves this service only when ALL of these hold at the moment of the response: the caller owns the job;
the pipeline reports the job `ready` with `delivery.status == "current"` (it re-reads the operator source registry, the ingestion
binding and the exact S2 export on every call); the server-owned upstream allowlist still lists the job's upstream for its owner; and the
payload parses strictly through the allowlisted projection. The checks are separate reads at separate instants, so a revocation that
lands between them and the response is not covered, and nothing recalls content a caller already received. Status never carries content.
"""
from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from pydantic import ValidationError

from . import relation_access
from .config import ServiceConfig
from .jobs import ApiError, KeyedLocks, Observation, Reply, request_digest
from .relation_dispatch import BUSY_CODES as DISPATCH_BUSY
from .relation_dispatch import RelationDispatcher
from .relation_ledger import DispatchRow, OperationRow, RelationLedger, RelationRow, stamp
from .relation_review import Evidence, evidence, marker, operation_status
from .relation_runtime import GateBusy, RelationGate, RelationProcess
from .relation_wire import (RETRYABLE, RelationChain, RelationDelivery, RelationDispatch, RelationErrorEnvelope, RelationFailure,
                            RelationJobContent, RelationJobStatus, RelationOperationStatus, RelationProvenance, RelationReceipt,
                            RelationResultEnvelope, RelationReview, RelationSubmit, RelationUpstream, RelationUsage, RelationView, next_action,
                            with_source_identity)
from .runtime import Outcome
from .wire import ErrorBody

MAX_PENDING = 1000
CLI_SLOTS = 4
BUSY_WAIT = 10.0
# Pipeline refusals that mean "the pipeline is busy or the server-side state is unusable", never "your request is wrong".
BUSY_CODES = DISPATCH_BUSY | {"extraction_busy", "ingestion_busy"}
CONFIG_CODES = frozenset({"input_or_configuration_invalid", "persistence_failed", "relation_internal_failure", "ledger_version_unknown",
                          "analysis_contract_changed", "state_ownership_unconfigured"})
# `live_*` pipeline refusals are the live runtime's own configuration/gate errors (gate off, incomplete or invalid settings, budget unavailable).
CONFIG_PATTERN = re.compile(r"state_[a-z_]+|[a-z]+_state_(missing|invalid)|[a-z]+_recovery_required|live_[a-z_]+")
# A job whose call was sent and never answered is reconcile-only; the pipeline names that failure per execution mode.
UNANSWERED = frozenset({"replay_response_unknown", "live_response_unknown"})


class RelationError(ApiError):
    """Same stable-code discipline as the S1 `ApiError`, with the relation envelope family."""

    def __init__(self, status: int, code: str, *, runtime_code: str | None = None, field: str | None = None,
                 retry_after: int | None = None, job_status: RelationJobStatus | None = None, headers: dict[str, str] | None = None,
                 operation: RelationOperationStatus | None = None):
        super().__init__(status, code, runtime_code=runtime_code, field=field, retry_after=retry_after, headers=headers)
        self.relation_status, self.operation = job_status, operation

    def envelope(self, request_id: str) -> RelationErrorEnvelope:  # type: ignore[override]
        return RelationErrorEnvelope(error=ErrorBody(code=self.code, retryable=self.code in RETRYABLE, request_id=request_id,
                                                     runtime_code=self.runtime_code, field=self.field), status=self.relation_status,
                                     operation=self.operation)


def is_config_code(code: str) -> bool:
    return code in CONFIG_CODES or CONFIG_PATTERN.fullmatch(code) is not None


class RelationJobs:
    def __init__(self, config: ServiceConfig, ledger: RelationLedger, process: RelationProcess, dispatcher: RelationDispatcher,
                 gate: RelationGate, *, clock: Callable[[], float] = time.time, busy_wait: float = BUSY_WAIT):
        assert config.relation is not None
        self.config, self.relation = config, config.relation
        self.ledger, self.process, self.dispatcher, self.gate = ledger, process, dispatcher, gate
        self._clock, self._busy_wait = clock, busy_wait
        self._locks = KeyedLocks()
        self._slots = threading.BoundedSemaphore(CLI_SLOTS)
        self._names = [principal.name for principal in config.principals]

    # ---- guards ----

    @contextmanager
    def _cli(self) -> Iterator[None]:
        """One relation child at a time (the pipeline's ledger lock does not wait), within a small number of waiting requests."""
        if not self._slots.acquire(blocking=False):
            raise RelationError(503, "service_busy", retry_after=1)
        try:
            try:
                with self.gate.hold(self._busy_wait):
                    yield
            except GateBusy:
                raise RelationError(503, "runtime_busy", retry_after=2) from None
        finally:
            self._slots.release()

    def preflight(self) -> str | None:
        """Server-owned inputs the pipeline would read: command, state parent, upstream state, sources and fixtures."""
        relation = self.relation
        if not (relation.command.is_file() and os.access(relation.command, os.X_OK)):
            return "relation_command_unavailable"
        probe = relation.state_dir if relation.state_dir.exists() else relation.state_dir.parent
        if not (probe.is_dir() and os.access(probe, os.R_OK | os.W_OK | os.X_OK)):
            return "relation_state_unavailable"
        if not (relation.extraction_state_dir.is_dir() and relation.ingestion_state_dir.is_dir()):
            return "relation_upstream_state_unavailable"
        for path in (relation.sources_path, relation.producer_replay, relation.verifier_replay):
            if not (path.is_file() and os.access(path, os.R_OK)):
                return "relation_input_unavailable"
        return None

    def _fault(self, seen: Observation, problem: str | None) -> RelationError:
        seen.problem = problem
        return RelationError(503, "service_configuration_invalid", retry_after=30)

    def _access(self, seen: Observation) -> relation_access.Access:
        try:
            return relation_access.load(self.relation.upstreams_path, self._names)
        except relation_access.AccessError as error:
            raise self._fault(seen, error.code) from None

    @staticmethod
    def _log(seen: Observation, command: str, outcome: Outcome) -> None:
        seen.runtime.append({"command": command, "kind": outcome.kind, "exit": outcome.exit_code, "code": outcome.code})

    def _refusal(self, outcome: Outcome, seen: Observation) -> RelationError:
        """Map a pipeline outcome that is not a usable result. Callers decide beforehand whether the reservation survives."""
        if outcome.kind == "error":
            code = outcome.code or ""
            if code == "job_input_conflict":
                return RelationError(409, "job_input_conflict", runtime_code=code)
            if code in BUSY_CODES:
                return RelationError(503, "runtime_busy", runtime_code=code, retry_after=2)
            if is_config_code(code):
                return self._fault(seen, code)
            return RelationError(409, "upstream_unavailable", runtime_code=code)
        return RelationError(503, "runtime_unavailable", retry_after=2)

    # ---- pipeline reads ----

    def _parse(self, outcome: Outcome, row: RelationRow, seen: Observation, command: str) -> tuple[RelationView, dict[str, Any]]:
        self._log(seen, command, outcome)
        if outcome.kind == "error":
            code = outcome.code or ""
            if code == "job_not_found":
                raise RelationError(500, "runtime_binding_mismatch", runtime_code=code)
            if code in BUSY_CODES:
                raise RelationError(503, "runtime_busy", runtime_code=code, retry_after=2)
            if is_config_code(code):
                raise self._fault(seen, code)
            raise RelationError(500, "internal_error", runtime_code=code)
        return self._bound(outcome, row)

    @staticmethod
    def _bound(outcome: Outcome, row: RelationRow) -> tuple[RelationView, dict[str, Any]]:
        """A result outcome as a view bound to the row's job, digest and upstream. Anything else is unreadable (503) or a binding mismatch (500)."""
        if outcome.kind != "result" or outcome.result is None:
            raise RelationError(503, "runtime_unavailable", retry_after=2)
        try:
            view = RelationView.model_validate(outcome.result)
        except ValidationError:
            raise RelationError(503, "runtime_unavailable", retry_after=2) from None
        upstream = view.binding.upstream
        if (view.job_id != row.job_id or view.input_digest != row.input_digest
                or (upstream.job_id, upstream.input_digest) != (row.upstream_job_id, row.upstream_input_digest)):
            raise RelationError(500, "runtime_binding_mismatch")
        return view, outcome.result

    def _read(self, row: RelationRow, seen: Observation) -> tuple[RelationView, dict[str, Any]]:
        with self._cli():
            outcome = self.process.inspect(row.job_id)
        return self._parse(outcome, row, seen, "inspect")

    def _live_refusal(self, row: RelationRow, access: relation_access.Access) -> str | None:
        """None when a LIVE job's pinned runtime identity is still exactly what the operator's allowlist approves for this owner and upstream."""
        if row.live_binding is not None and access.live_identity(row.owner, row.upstream_job_id, row.upstream_input_digest) != row.live_binding:
            return "live_not_approved"
        return None

    def _delivery(self, row: RelationRow, view: RelationView, seen: Observation) -> RelationDelivery:
        if view.delivery.status == "withheld":
            return RelationDelivery(state="withheld", reason=view.delivery.code or "withheld")
        if view.state != "ready":
            return RelationDelivery(state="withheld", reason="job_not_ready")
        access = self._access(seen)
        if not access.allows(row.owner, row.upstream_job_id, row.upstream_input_digest):
            return RelationDelivery(state="withheld", reason="upstream_not_allowed")
        if row.live_binding is not None:
            runtime = view.binding.runtime
            if runtime is None or runtime.identity != row.live_binding:
                return RelationDelivery(state="withheld", reason="live_binding_changed")
            refusal = self._live_refusal(row, access)
            if refusal is not None:
                return RelationDelivery(state="withheld", reason=refusal)
        return RelationDelivery(state="available")

    def _status(self, row: RelationRow, view: RelationView, seen: Observation, dispatch: DispatchRow | None = None,
                delivery: RelationDelivery | None = None) -> RelationJobStatus:
        dispatch = dispatch or self.ledger.dispatch(row.job_id)
        assert dispatch is not None and row.accepted_at is not None
        provenance = view.provenance
        return RelationJobStatus(
            job_id=row.job_id, input_digest=view.input_digest,
            provenance=RelationProvenance(source_kind=provenance.source_kind, execution_mode=provenance.execution_mode,
                                          recording_kind=provenance.recording_kind),
            upstream=RelationUpstream(job_id=row.upstream_job_id, input_digest=row.upstream_input_digest),
            state=view.state, phase=view.phase, resume_mode=view.resume_mode,
            failure=None if view.failure is None else RelationFailure(code=view.failure.code),
            usage=RelationUsage.model_validate(view.usage.model_dump()),
            delivery=delivery or self._delivery(row, view, seen),
            dispatch=RelationDispatch(state=dispatch.state, dispatch_count=dispatch.dispatch_count, last_outcome=dispatch.last_outcome,
                                      last_runtime_code=dispatch.last_runtime_code, updated_at=dispatch.updated_at),
            next=next_action(view.state, dispatch.state),
            accepted_at=row.accepted_at, observed_at=stamp(self._clock()))

    def _owned(self, owner: str, job_id: str) -> RelationRow:
        """Another owner's job, a reserved-only job and an unknown job all answer the same way."""
        row = self.ledger.job(job_id)
        if row is None or row.owner != owner or row.state != "accepted":
            raise RelationError(404, "job_not_found")
        return row

    @staticmethod
    def _headers(status: RelationJobStatus, **extra: str) -> dict[str, str]:
        headers = dict(extra)
        if status.next == "wait":
            headers["Retry-After"] = "2"
        return headers

    # ---- operations ----

    def submit(self, owner: str, job_id: str, body: RelationSubmit, seen: Observation) -> Reply:
        wire = body.wire()
        digest = request_digest(wire)
        live = body.provenance.execution_mode == "live"
        location = {"Location": f"/internal/v1/relation-jobs/{job_id}"}
        with self._locks.hold(job_id):
            row = self.ledger.job(job_id)
            if row is not None:
                if row.owner != owner:
                    raise RelationError(409, "job_id_unavailable")
                if row.request_digest != digest:
                    raise RelationError(409, "idempotency_conflict")
                if row.state == "accepted":
                    view, _ = self._read(row, seen)
                    status = self._status(row, view, seen)
                    return Reply(200, status, self._headers(status, **location))
            # Unknown upstream: refused before any ledger row or child exists, and the same answer whether or not it exists.
            access = self._access(seen)
            if not access.allows(owner, body.upstream.job_id, body.upstream.input_digest):
                raise RelationError(403, "upstream_not_allowed")
            pin = None
            if live:
                # A live job spends money: the service must have the live group, and the operator's allowlist must pin the runtime identity it
                # approved for exactly this owner and upstream (a reservation made earlier keeps the pin it was made under).
                if self.config.pipeline_live is None:
                    raise RelationError(409, "live_unavailable")
                pin = access.live_identity(owner, body.upstream.job_id, body.upstream.input_digest)
                if pin is None or (row is not None and row.live_binding != pin):
                    raise RelationError(403, "live_not_approved")
            if self.ledger.active_count() >= MAX_PENDING:
                raise RelationError(503, "queue_full", retry_after=30)
            problem = self.preflight()
            if problem:
                raise self._fault(seen, problem)
            with self._cli():
                # Owner intent first (durable). Then the pipeline registers, then accepted + dispatch intent, then 202.
                row = row or self.ledger.reserve(job_id, owner, digest, body.upstream.job_id, body.upstream.input_digest, pin)
                if row.submit_attempts == 0:
                    self._refuse_adoption(job_id, owner, digest, seen)
                self.ledger.begin_attempt(job_id)
                outcome = self.process.submit(wire, live=live)
                self._log(seen, "submit", outcome)
                if outcome.kind != "result":
                    outcome = self._reconcile(job_id, owner, digest, outcome, seen)
            view = self._registered(outcome, row, body, seen)
            accepted = self.ledger.accept(job_id, owner, view.input_digest, MAX_PENDING)
            if accepted == "full":
                raise RelationError(503, "queue_full", retry_after=30)  # another submission took the last slot; the claim is kept
            if accepted != "accepted":
                raise RelationError(500, "internal_error")
            self.dispatcher.wake()
            row = self.ledger.job(job_id)
            assert row is not None
            status = self._status(row, view, seen)
            return Reply(202, status, self._headers(status, **location))

    def _refuse_adoption(self, job_id: str, owner: str, digest: str, seen: Observation) -> None:
        """The pipeline `submit` of an id that already exists only reports the stored job. A first attempt must therefore find no such job,
        or a caller could adopt (and then read) a job an operator registered. Called under the gate, before the first `submit`."""
        outcome = self.process.inspect(job_id)
        self._log(seen, "inspect", outcome)
        if outcome.kind == "error" and outcome.code == "job_not_found":
            return
        self.ledger.release(job_id, owner, digest)  # nothing of ours exists yet, whatever the answer was
        if outcome.kind == "result":
            raise RelationError(409, "job_id_unavailable")
        raise self._refusal(outcome, seen)

    def _reconcile(self, job_id: str, owner: str, digest: str, failed: Outcome, seen: Observation) -> Outcome:
        """A `submit` that did not produce a result may still have registered the job (a timeout or a lost acknowledgement). Ask the
        pipeline, under the same gate. Registered: carry on as if it had answered. Provably absent: the reservation is released. Anything
        else: the reservation is kept, so only the owner's identical retry can complete it."""
        if failed.kind == "error" and failed.code == "job_input_conflict":
            self.ledger.release(job_id, owner, digest)
            raise self._refusal(failed, seen)
        probe = self.process.inspect(job_id)
        self._log(seen, "inspect", probe)
        if probe.kind == "result":
            return probe
        if probe.kind == "error" and probe.code == "job_not_found":
            self.ledger.release(job_id, owner, digest)
            raise self._refusal(failed, seen)
        raise RelationError(503, "runtime_unavailable", retry_after=2)

    def _registered(self, outcome: Outcome, row: RelationRow, body: RelationSubmit, seen: Observation) -> RelationView:
        """A fresh registration is a queued job with no call, bound to exactly the requested upstream and provenance."""
        try:
            view = RelationView.model_validate(outcome.result)
        except ValidationError:
            raise RelationError(503, "runtime_unavailable", retry_after=2) from None
        upstream, provenance = view.binding.upstream, view.provenance
        if (view.job_id != row.job_id or (upstream.job_id, upstream.input_digest) != (body.upstream.job_id, body.upstream.input_digest)
                or provenance.model_dump() != {"source_kind": body.provenance.source_kind, "execution_mode": body.provenance.execution_mode,
                                               "recording_kind": body.provenance.recording_kind}
                or view.state != "queued" or view.calls):
            raise RelationError(500, "runtime_binding_mismatch")  # the reservation is kept: this is not a registration the service made
        if row.live_binding is not None and (view.binding.runtime is None or view.binding.runtime.identity != row.live_binding):
            # The pipeline froze this job under a runtime other than the one the operator approved. It will never be dispatched or delivered; the
            # reservation is kept, so only a NEW job id (under the approved configuration) can ever be used.
            raise RelationError(409, "live_binding_mismatch")
        return view

    def status(self, owner: str, job_id: str, seen: Observation) -> Reply:
        row = self._owned(owner, job_id)
        view, _ = self._read(row, seen)
        status = self._status(row, view, seen)
        return Reply(200, status, self._headers(status))

    def result(self, owner: str, job_id: str, seen: Observation) -> Reply:
        row = self._owned(owner, job_id)
        view, raw = self._read(row, seen)
        delivery = self._delivery(row, view, seen)
        job = None
        if delivery.state == "available":
            try:
                job = RelationJobContent.model_validate(with_source_identity(raw))
                if job.job_id != row.job_id or job.input_digest != row.input_digest:
                    raise ValueError("content binding")
            except (ValidationError, ValueError, KeyError, TypeError):
                job, delivery = None, RelationDelivery(state="withheld", reason="projection_invalid")
        status = self._status(row, view, seen, delivery=delivery)
        receipts = [RelationReceipt(stage=call.stage, state=call.state, verdict=call.verdict) for call in view.calls]
        envelope = RelationResultEnvelope(status=status, delivery=delivery, job=job, receipts=receipts)
        return Reply(200, envelope, self._headers(status))

    def cancel(self, owner: str, job_id: str, seen: Observation) -> Reply:
        """Idempotent for a cancelled job; refused for a ready one. The pipeline's own `cancel` would turn a ready job into a permanently
        withheld one, so the state is read first and a ready job is never handed to it."""
        row = self._owned(owner, job_id)
        with self._cli():
            view, _ = self._parse(self.process.inspect(job_id), row, seen, "inspect")
            if view.state == "ready":
                raise RelationError(409, "job_already_terminal", job_status=self._status(row, view, seen))
            if view.state != "cancelled":
                view, _ = self._parse(self.process.cancel(job_id), row, seen, "cancel")
        if view.state == "cancelled":
            self.ledger.cancel_pending(job_id)
        status = self._status(row, view, seen)
        if view.state in ("ready",):
            raise RelationError(409, "job_already_terminal", job_status=status)
        return Reply(200, status)

    def recover(self, owner: str, job_id: str, seen: Observation) -> Reply:
        row = self._owned(owner, job_id)
        view, _ = self._read(row, seen)
        dispatch = self.ledger.dispatch(job_id)
        assert dispatch is not None
        status = self._status(row, view, seen, dispatch=dispatch)
        if row.live_binding is not None and self.config.pipeline_live is None:
            # A live job on a service started without the live group can neither be coalesced into a pending dispatch nor queued: nothing may run.
            raise RelationError(409, "live_unavailable", job_status=status)
        if dispatch.state in ("pending", "in_flight"):
            return Reply(200, status, self._headers(status))
        if view.state == "reconciling" or (view.failure is not None and view.failure.code in UNANSWERED):
            raise RelationError(409, "reconcile_required", job_status=status)
        if view.state not in ("queued", "running", "stopped"):
            raise RelationError(409, "job_not_recoverable", job_status=status)
        if row.live_binding is not None:
            # A live recover spends money again: the owner and the pinned runtime must still be approved NOW.
            refusal = self._live_refusal(row, self._access(seen))
            if refusal is not None:
                raise RelationError(403, refusal, job_status=status)
        queued = self.ledger.enqueue(job_id, MAX_PENDING)
        if queued == "full":
            raise RelationError(503, "queue_full", retry_after=30)
        self.dispatcher.wake()
        status = self._status(row, view, seen)
        return Reply(202 if queued == "enqueued" else 200, status, self._headers(status))

    # ---- review operations ----
    #
    # One operation per Idempotency-Key. The review is a synchronous, quick pipeline command (a compare-and-set append of one event). `allow` is the
    # operator's FINAL approval of a HOLD relation (no verifier or model call follows it, nothing is dispatched) and `reject` an exclusion: the POST
    # answers 200 once the exact event is proven in the chain, and nothing here ever publishes. An operation recorded under the earlier contract (an
    # `allow` that meant "revalidate") is history: it stays readable and is never dispatched, resent or read as an approval (`review_contract_changed`).
    _REVIEW_REFUSALS = {"review_revision_conflict": (409, "source_revision_conflict"), "review_target_not_hold": (409, "review_target_not_hold"),
                        "review_call_in_flight": (409, "review_call_in_flight"), "review_candidate_ineligible": (409, "review_candidate_ineligible"),
                        "job_cancelled": (409, "job_cancelled"), "relation_candidate_not_found": (404, "relation_candidate_not_found")}
    # Refusals that are a pure function of the chain and the job at the revision the operation expected: no child, orphaned or not, can append
    # there later, so once the chain is read and shows no event of ours the reservation can go. A revision conflict is not one of them: it says
    # the chain moved, and only the chain can say whether it moved because of this operation.
    _PERMANENT_REFUSALS = frozenset({"review_target_not_hold", "job_cancelled", "relation_candidate_not_found"})

    def _permit(self, owner: str, row: RelationRow, seen: Observation) -> None:
        """A write to the AI ledger (a review or a recovery) needs the upstream to be listed for the owner NOW. A plain lookup does not."""
        if not self._access(seen).allows(owner, row.upstream_job_id, row.upstream_input_digest):
            raise RelationError(403, "upstream_not_allowed")

    def _operation_of(self, owner: str, row: RelationRow, key: str) -> OperationRow:
        """Another owner's operation, another job's and an unknown one all answer the same way."""
        found = self.ledger.operation(key)
        if found is None or found.owner != owner or found.job_id != row.job_id:
            raise RelationError(404, "operation_not_found")
        return found

    def _operation_reply(self, status: int, op: OperationRow, headers: dict[str, str] | None = None) -> Reply:
        view = operation_status(op, stamp(self._clock()))
        extra = dict(headers or {})
        if view.next == "wait":
            extra["Retry-After"] = "2"
        return Reply(status, view, extra)

    @staticmethod
    def _evidence(view: RelationView, raw: dict[str, Any], op: OperationRow) -> Evidence:
        if view.delivery.status != "current":
            return Evidence("unreadable")  # the pipeline withholds the candidate set while rights or the exact upstream do not hold
        try:
            chain = RelationChain.model_validate(raw)
        except ValidationError:
            return Evidence("unreadable")
        return evidence(chain, op)

    def _prove(self, row: RelationRow, op: OperationRow, seen: Observation) -> Evidence:
        """What the chain holds for this operation, read with `inspect` under the gate the caller holds. Never writes."""
        outcome = self.process.inspect(row.job_id)
        self._log(seen, "inspect", outcome)
        if outcome.kind == "error" and outcome.code == "job_not_found":
            raise RelationError(500, "runtime_binding_mismatch", runtime_code=outcome.code)
        if outcome.kind != "result":
            return Evidence("unreadable")
        view, raw = self._bound(outcome, row)
        return self._evidence(view, raw, op)

    def _adopt(self, op: OperationRow, found: Evidence, location: dict[str, str]) -> Reply:
        """The exact event is proven: record it. A final approval or an exclusion is terminal: nothing is queued and no call follows."""
        assert found.event_at is not None
        if not self.ledger.apply_operation(op.operation_id, found.event_at):
            raise RelationError(500, "internal_error")  # only a current-contract reservation reaches here
        done = self.ledger.operation(op.operation_id)
        assert done is not None and done.review_state == "applied"
        return self._operation_reply(200, done, location)

    def _unproven(self, op: OperationRow, found: Evidence) -> RelationError:
        """The chain does not show this operation's event. The reservation is released only when the event can never appear (the relation
        moved past the expected revision, or the candidate is not there); an event that is there but wrong is a contradiction, never adopted."""
        if found.kind == "moved":
            self.ledger.release_operation(op.operation_id, op.owner, op.request_digest)
            return RelationError(409, "source_revision_conflict")
        if found.kind == "missing":
            self.ledger.release_operation(op.operation_id, op.owner, op.request_digest)
            return RelationError(404, "relation_candidate_not_found")
        if found.kind == "mismatch":
            return RelationError(500, "runtime_binding_mismatch")
        return RelationError(503, "review_unconfirmed", retry_after=2)  # absent or unreadable: no proof either way yet; retry the same request

    def _review_refusal(self, code: str) -> RelationError:
        if code in self._REVIEW_REFUSALS:
            status, mapped = self._REVIEW_REFUSALS[code]
            return RelationError(status, mapped, runtime_code=code)
        return RelationError(409, "upstream_unavailable", runtime_code=code)

    def _drive(self, row: RelationRow, op: OperationRow, seen: Observation, location: dict[str, str]) -> Reply:
        """One attempt to get this operation's event into the chain, under the gate. It reads before it writes whenever an earlier attempt may
        already have written, and it adopts only an event that matches the operation in every field."""
        earlier = op.review_attempts
        self.ledger.begin_review_attempt(op.operation_id)
        if earlier > 0:
            found = self._prove(row, op, seen)
            if found.kind == "applied":
                return self._adopt(op, found, location)
            if found.kind != "absent":
                raise self._unproven(op, found)
        outcome = self.process.review(row.job_id, op.relation_candidate_id, op.expected_source_revision, op.decision, op.owner, marker(op.operation_id))
        self._log(seen, "review", outcome)
        if outcome.kind == "result":
            view, raw = self._bound(outcome, row)
            found = self._evidence(view, raw, op)
            if found.kind == "applied":
                return self._adopt(op, found, location)
            if found.kind != "unreadable":
                raise RelationError(500, "runtime_binding_mismatch")  # a success that does not show the event contradicts the pipeline's contract
        elif outcome.kind == "error":
            code = outcome.code or ""
            if code in BUSY_CODES:
                raise RelationError(503, "runtime_busy", runtime_code=code, retry_after=2)  # refused before any effect; the reservation stays
            if code == "job_not_found":
                raise RelationError(500, "runtime_binding_mismatch", runtime_code=code)
            if not is_config_code(code):
                if earlier == 0:
                    # The first attempt has no earlier child that could have written, so the pipeline's refusal (its transaction rolled back)
                    # is definitive.
                    self.ledger.release_operation(op.operation_id, op.owner, op.request_digest)
                    raise self._review_refusal(code)
                # An earlier attempt may have left a child alive that has not yet taken the pipeline's ledger lock (the service that started
                # it is gone). It can append this operation's exact event between the read above and this refusal, which is how a retry gets
                # a revision conflict for its own event. So the refusal is not proof of absence: read the chain again.
                found = self._prove(row, op, seen)
                if found.kind == "applied":
                    return self._adopt(op, found, location)
                if found.kind == "absent" and code in self._PERMANENT_REFUSALS:
                    self.ledger.release_operation(op.operation_id, op.owner, op.request_digest)
                    raise self._review_refusal(code)
                raise self._unproven(op, found)
        # Ambiguous: a timeout, an abnormal exit, unreadable output, a persistence error that may follow a commit, or a withheld result.
        found = self._prove(row, op, seen)
        if found.kind == "applied":
            return self._adopt(op, found, location)
        raise self._unproven(op, found)

    def review(self, owner: str, job_id: str, key: str, body: RelationReview, seen: Observation) -> Reply:
        """Record one allow (final approval) / reject (exclusion) decision on one relation candidate, exactly once per Idempotency-Key.

        The same key and body return the existing operation, even after the relation has since moved on; the same key with another body
        or job is `idempotency_conflict`; another principal's key is `operation_id_unavailable`; a key reserved under the earlier revalidation
        contract is `review_contract_changed` (use a new key). A NEW decision needs the upstream still listed
        for the owner, the job's `sourceVersion` and the relation's `sourceRevision` to match exactly (the revision is enforced by the pipeline
        inside its append transaction), and records nothing at all when any of that fails. The pipeline itself re-runs the deterministic checks
        and re-reads the current source rights, so a human `allow` can never override them."""
        digest = request_digest({"jobId": job_id, **body.wire()})
        location = {"Location": f"/internal/v1/relation-jobs/{job_id}/reviews/{key}"}
        with self._locks.hold("review:" + key):
            row = self._owned(owner, job_id)
            op = self.ledger.operation(key)
            if op is not None:
                if op.owner != owner:
                    raise RelationError(409, "operation_id_unavailable")
                if op.request_digest != digest:
                    raise RelationError(409, "idempotency_conflict")
                if op.review_state == "applied":
                    return self._operation_reply(200, op, location)
                if op.legacy:
                    raise RelationError(409, "review_contract_changed", operation=operation_status(op, stamp(self._clock())))
            self._permit(owner, row, seen)
            if op is None and body.expected_source_version != row.input_digest:
                raise RelationError(409, "source_version_conflict")
            problem = self.preflight()
            if problem:
                raise self._fault(seen, problem)
            with self._cli():
                # Owner intent first (durable, a reserved row), then the pipeline appends, then the exact event is proven and recorded.
                op = self.ledger.reserve_operation(key, owner, job_id, body.relation_candidate_id, body.decision, body.expected_source_version,
                                                   int(body.expected_source_revision), digest)
                return self._drive(row, op, seen, location)

    def operation(self, owner: str, job_id: str, key: str, seen: Observation) -> Reply:
        """Look an operation up by its key. Read from the service ledger alone (no child), so it works while the pipeline is busy and after a
        crash: an operation reserved but not yet proven is reported `unconfirmed` with `next=retry_review`."""
        row = self._owned(owner, job_id)
        return self._operation_reply(200, self._operation_of(owner, row, key))
