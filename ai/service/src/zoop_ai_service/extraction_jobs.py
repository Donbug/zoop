"""The S2 extraction-job operations (submit, status, result, cancel, recover), independent of HTTP framing. Blocking: callers run these in a worker thread.

Every state shown to a caller is read from the pipeline (`zoop-ai-extract inspect`) during the same request. The service ledger only adds ownership,
the frozen approval identity, idempotency and the dispatch state, and it never holds a request body or a candidate.

What a caller can do. It names a job id and the digest of an operator-approved request. The operator's server-owned approval file maps
`principal + jobId + approvedRequestDigest` to the exact S2 `Submit` body and the digests of the replay fixtures that body runs against; the body
and the fixtures are what the service hands to the pipeline, never anything the caller sent. Nothing is adopted: a job id that already exists in the
pipeline ledger (an operator's job) is refused at the first attempt.

Frozen identity. The first reservation pins the approved digest, the producer fixture digest, the optional topic fixture digest and the `inputDigest`
the pipeline must report (computed here as `digest({request, replayFixtureHash})` over the approved bytes). Every pinned value is immutable. An exact
repeat of the request keeps them; the same job with another approved digest is `idempotency_conflict`; an approval entry or fixture file that has moved
since is refused (`approval_changed`, `fixture_changed`) and the job id is never rebound.

Authority at every content-bearing use. The approval file is re-read, and the fixture files re-hashed, at submit, at every dispatch (the first
included), at recover and at delivery. Content leaves this service only when ALL of these hold at the moment of the response: the caller owns the job;
the pipeline reports the job `ready` with `delivery.status == "current"` (it re-reads the operator source registry, the ingestion binding and every
document's rights on each call); the approval is still the reserved one; the fixture files are still the pinned bytes and every receipt was answered
by them; and the payload parses strictly through the allowlisted projection. The checks are separate reads at separate instants, so a revocation that
lands between them and the response is not covered, and nothing recalls content a caller already received. Status never carries content.

The fixture files are server configuration the child reads itself, so a digest check cannot be atomic with that read (a time-of-check/time-of-use
window). It is closed after the fact: the pipeline's `inputDigest` must equal the digest computed from the approved request and the pinned producer
digest, and every receipt's fixture hash must equal the pinned digest of its stage; a file swapped in the window therefore fails closed as
`runtime_binding_mismatch` or a withheld `fixture_changed`, never as delivered content. No network path exists for any command, error paths included.
"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from pydantic import ValidationError

from . import extraction_access
from .config import ServiceConfig
from .extraction_dispatch import BUSY_CODES, ExtractionDispatcher, call_pin_problem
from .extraction_ledger import ExtractionLedger, ExtractionRow, Pins
from .extraction_runtime import ExtractionProcess
from .extraction_wire import (RETRYABLE, ExtractionApproval, ExtractionDelivery, ExtractionDispatch, ExtractionErrorEnvelope, ExtractionFailure,
                              ExtractionJobContent, ExtractionJobStatus, ExtractionProvenance, ExtractionReceipt, ExtractionResultEnvelope,
                              ExtractionStage, ExtractionSubmit, ExtractionUsage, ExtractionView, next_action)
from .jobs import ApiError, KeyedLocks, Observation, Reply, request_digest
from .ledger import stamp
from .relation_jobs import CONFIG_PATTERN
from .relation_runtime import GateBusy, RelationGate
from .runtime import Outcome
from .wire import ErrorBody

MAX_PENDING = 1000
CLI_SLOTS = 4
BUSY_WAIT = 10.0
CONFIG_CODES = frozenset({"input_or_configuration_invalid", "persistence_failed", "extraction_internal_failure", "ledger_version_unknown",
                          "analysis_contract_changed", "state_ownership_unconfigured", "replay_fixture_invalid",
                          "replay_fixture_required", "replay_provenance_conflict", "replay_prompt_version_conflict",
                          "fixture_not_allowed", "command_input_limit"})
# A job whose call was sent and never answered is reconcile-only; the pipeline names that failure per execution mode.
UNANSWERED = frozenset({"replay_response_unknown", "live_response_unknown"})


class ExtractionError(ApiError):
    """Same stable-code discipline as the S1 `ApiError`, with the extraction envelope family."""

    def __init__(self, status: int, code: str, *, runtime_code: str | None = None, field: str | None = None, retry_after: int | None = None,
                 job_status: ExtractionJobStatus | None = None, headers: dict[str, str] | None = None):
        super().__init__(status, code, runtime_code=runtime_code, field=field, retry_after=retry_after, headers=headers)
        self.extraction_status = job_status

    def envelope(self, request_id: str) -> ExtractionErrorEnvelope:  # type: ignore[override]
        return ExtractionErrorEnvelope(error=ErrorBody(code=self.code, retryable=self.code in RETRYABLE, request_id=request_id,
                                                       runtime_code=self.runtime_code, field=self.field), status=self.extraction_status)


def is_config_code(code: str) -> bool:
    return code in CONFIG_CODES or CONFIG_PATTERN.fullmatch(code) is not None


class ExtractionJobs:
    def __init__(self, config: ServiceConfig, ledger: ExtractionLedger, process: ExtractionProcess, dispatcher: ExtractionDispatcher,
                 gate: RelationGate, authority: extraction_access.Authority, *, clock: Callable[[], float] = time.time, busy_wait: float = BUSY_WAIT):
        assert config.extraction is not None
        self.config, self.extraction = config, config.extraction
        self.ledger, self.process, self.dispatcher, self.gate, self.authority = ledger, process, dispatcher, gate, authority
        self._clock, self._busy_wait = clock, busy_wait
        self._locks = KeyedLocks()
        self._slots = threading.BoundedSemaphore(CLI_SLOTS)

    # ---- guards ----

    @contextmanager
    def _cli(self) -> Iterator[None]:
        """One pipeline child at a time, S3's included (the pipeline's ledger lock does not wait), within a small number of waiting requests."""
        if not self._slots.acquire(blocking=False):
            raise ExtractionError(503, "service_busy", retry_after=1)
        try:
            try:
                with self.gate.hold(self._busy_wait):
                    yield
            except GateBusy:
                raise ExtractionError(503, "runtime_busy", retry_after=2) from None
        finally:
            self._slots.release()

    def preflight(self) -> str | None:
        """Server-owned inputs the pipeline would read: command, state root, ingestion root, sources, fixtures and the approvals file."""
        extraction = self.extraction
        if not (extraction.command.is_file() and os.access(extraction.command, os.X_OK)):
            return "extraction_command_unavailable"
        if not (extraction.state_dir.is_dir() and os.access(extraction.state_dir, os.R_OK | os.W_OK | os.X_OK) and extraction.ingestion_state_dir.is_dir()):
            return "extraction_state_unavailable"
        paths = [extraction.sources_path, extraction.producer_replay, extraction.approvals_path]
        if extraction.topic_replay is not None:
            paths.append(extraction.topic_replay)
        for path in paths:
            if not (path.is_file() and os.access(path, os.R_OK)):
                return "extraction_input_unavailable"
        return None

    @staticmethod
    def _fault(seen: Observation, problem: str | None) -> ExtractionError:
        seen.problem = problem
        return ExtractionError(503, "service_configuration_invalid", retry_after=30)

    def _approval(self, seen: Observation, owner: str, job_id: str) -> extraction_access.Approval | None:
        try:
            return self.authority.approvals().find(owner, job_id)
        except extraction_access.AccessError as error:
            raise self._fault(seen, error.code) from None

    def _authority_error(self, refusal: str, seen: Observation) -> ExtractionError:
        """A refusal of `Authority.refusal` as the error a caller sees."""
        if refusal == "approval_revoked":
            return ExtractionError(403, "request_not_approved")
        if refusal in ("approval_changed", "fixture_changed"):
            return ExtractionError(409, refusal)
        return self._fault(seen, refusal)

    @staticmethod
    def _log(seen: Observation, command: str, outcome: Outcome) -> None:
        seen.runtime.append({"command": command, "kind": outcome.kind, "exit": outcome.exit_code, "code": outcome.code})

    def _refusal(self, outcome: Outcome, seen: Observation) -> ExtractionError:
        """Map a pipeline outcome that is not a usable result. Callers decide beforehand whether the reservation survives."""
        if outcome.kind == "error":
            code = outcome.code or ""
            if code == "job_input_conflict":
                return ExtractionError(409, "job_input_conflict", runtime_code=code)
            if code in BUSY_CODES:
                return ExtractionError(503, "runtime_busy", runtime_code=code, retry_after=2)
            if is_config_code(code):
                return self._fault(seen, code)
            return ExtractionError(409, "request_unavailable", runtime_code=code)
        return ExtractionError(503, "runtime_unavailable", retry_after=2)

    # ---- pipeline reads ----

    def _parse(self, outcome: Outcome, row: ExtractionRow, seen: Observation, command: str) -> ExtractionView:
        self._log(seen, command, outcome)
        if outcome.kind == "error":
            code = outcome.code or ""
            if code == "job_not_found":
                raise ExtractionError(500, "runtime_binding_mismatch", runtime_code=code)
            if code in BUSY_CODES:
                raise ExtractionError(503, "runtime_busy", runtime_code=code, retry_after=2)
            if is_config_code(code):
                raise self._fault(seen, code)
            raise ExtractionError(500, "internal_error", runtime_code=code)
        return self._bound(outcome, row)

    @staticmethod
    def _view(outcome: Outcome) -> ExtractionView:
        if outcome.kind != "result" or outcome.result is None:
            raise ExtractionError(503, "runtime_unavailable", retry_after=2)
        try:
            return ExtractionView.model_validate(outcome.result)
        except ValidationError:
            raise ExtractionError(503, "runtime_unavailable", retry_after=2) from None

    def _bound(self, outcome: Outcome, row: ExtractionRow) -> ExtractionView:
        """A result outcome as a view bound to the row's job and the PINNED input digest. Anything else is unreadable (503) or a mismatch (500)."""
        view = self._view(outcome)
        if view.job_id != row.job_id or view.input_digest != row.input_digest:
            raise ExtractionError(500, "runtime_binding_mismatch")
        return view

    def _read(self, row: ExtractionRow, seen: Observation) -> ExtractionView:
        return self._read_with_payload(row, seen)[0]

    def _delivery(self, row: ExtractionRow, view: ExtractionView, seen: Observation) -> ExtractionDelivery:
        if view.delivery.status == "withheld":
            return ExtractionDelivery(state="withheld", reason=view.delivery.code or "withheld")
        if view.state != "ready":
            return ExtractionDelivery(state="withheld", reason="job_not_ready")
        refusal = self.authority.refusal(row.owner, row.job_id, row.pins.approval)
        if refusal == "service_configuration_invalid":
            raise self._fault(seen, "extraction_approvals_unreadable")
        if refusal is None:
            refusal = call_pin_problem(view, row.pins)
        if refusal is not None:
            return ExtractionDelivery(state="withheld", reason=refusal)
        return ExtractionDelivery(state="available")

    def _status(self, row: ExtractionRow, view: ExtractionView, seen: Observation, delivery: ExtractionDelivery | None = None) -> ExtractionJobStatus:
        dispatch = self.ledger.dispatch(row.job_id)
        assert dispatch is not None and row.accepted_at is not None
        provenance = view.provenance
        return ExtractionJobStatus(
            job_id=row.job_id, input_digest=view.input_digest, approval=ExtractionApproval(approved_request_digest=row.pins.approved_digest),
            provenance=ExtractionProvenance(source_kind=provenance.source_kind, execution_mode=provenance.execution_mode,
                                            recording_kind=provenance.recording_kind),
            state=view.state, phase=view.phase, resume_mode=view.resume_mode,
            failure=None if view.failure is None else ExtractionFailure(code=view.failure.code),
            usage=ExtractionUsage.model_validate(view.usage.model_dump()),
            stages=[ExtractionStage(stage=name, state=view.stages[name].state) for name in ("extract", "compare", "topic") if name in view.stages],
            delivery=delivery or self._delivery(row, view, seen),
            dispatch=ExtractionDispatch(state=dispatch.state, dispatch_count=dispatch.dispatch_count, last_outcome=dispatch.last_outcome,
                                        last_runtime_code=dispatch.last_runtime_code, updated_at=dispatch.updated_at),
            next=next_action(view.state, dispatch.state), accepted_at=row.accepted_at, observed_at=stamp(self._clock()))

    def _owned(self, owner: str, job_id: str) -> ExtractionRow:
        """Another owner's job, a reserved-only job and an unknown job all answer the same way."""
        row = self.ledger.job(job_id)
        if row is None or row.owner != owner or row.state != "accepted":
            raise ExtractionError(404, "job_not_found")
        return row

    @staticmethod
    def _headers(status: ExtractionJobStatus, **extra: str) -> dict[str, str]:
        headers = dict(extra)
        if status.next == "wait":
            headers["Retry-After"] = "2"
        return headers

    # ---- operations ----

    def submit(self, owner: str, job_id: str, body: ExtractionSubmit, seen: Observation) -> Reply:
        digest = request_digest(body.wire())
        location = {"Location": f"/internal/v1/extraction-jobs/{job_id}"}
        with self._locks.hold(job_id):
            row = self.ledger.job(job_id)
            if row is not None:
                if row.owner != owner:
                    approval = self._approval(seen, owner, job_id)
                    if approval is None or approval.approved_digest != body.approved_request_digest:
                        raise ExtractionError(403, "request_not_approved")
                    raise ExtractionError(409, "job_id_unavailable")
                if row.request_digest != digest:
                    raise ExtractionError(409, "idempotency_conflict")
                if row.state == "accepted":
                    view = self._read(row, seen)
                    status = self._status(row, view, seen)
                    return Reply(200, status, self._headers(status, **location))
            # Not approved for this principal: refused before any ledger row or child exists, and the same answer whether or not the job exists.
            approval = self._approval(seen, owner, job_id)
            if approval is None or approval.approved_digest != body.approved_request_digest:
                raise ExtractionError(403, "request_not_approved")
            pins = Pins(approval.approved_digest, approval.producer_digest, approval.topic_digest, approval.input_digest, approval.live_identity)
            if approval.live and self.config.pipeline_live is None:
                raise ExtractionError(409, "live_unavailable")
            if row is not None and row.pins != pins:
                raise ExtractionError(409, "approval_changed")  # the reserved identity is never rebound to a rotated approval
            problem = self.authority.fixtures(pins.producer_digest, pins.topic_digest)
            if problem is not None:
                raise self._fault(seen, problem)
            if self.ledger.active_count() >= MAX_PENDING:
                raise ExtractionError(503, "queue_full", retry_after=30)
            problem = self.preflight()
            if problem:
                raise self._fault(seen, problem)
            with self._cli():
                # Owner intent first (durable). Then the pipeline registers, then accepted + dispatch intent, then 202.
                row = row or self.ledger.reserve(job_id, owner, digest, pins)
                if row.submit_attempts == 0:
                    self._refuse_adoption(job_id, owner, digest, seen)
                self.ledger.begin_attempt(job_id)
                outcome = self.process.submit(approval.request, live=approval.live)
                self._log(seen, "submit", outcome)
                if outcome.kind != "result":
                    outcome = self._reconcile(job_id, owner, digest, outcome, seen)
            view = self._registered(outcome, row, approval)
            accepted = self.ledger.accept(job_id, owner, MAX_PENDING)
            if accepted == "full":
                raise ExtractionError(503, "queue_full", retry_after=30)  # another submission took the last slot; the claim is kept
            if accepted != "accepted":
                raise ExtractionError(500, "internal_error")
            self.dispatcher.wake()
            row = self.ledger.job(job_id)
            assert row is not None
            status = self._status(row, view, seen)
            return Reply(202, status, self._headers(status, **location))

    def _refuse_adoption(self, job_id: str, owner: str, digest: str, seen: Observation) -> None:
        """The pipeline `submit` of an id that already exists only reports the stored job. A first attempt must therefore find no such job, or a
        caller could adopt (and then read) a job an operator registered. Called under the gate, before the first `submit`."""
        outcome = self.process.inspect(job_id)
        self._log(seen, "inspect", outcome)
        if outcome.kind == "error" and outcome.code == "job_not_found":
            return
        self.ledger.release(job_id, owner, digest)  # nothing of ours exists yet, whatever the answer was
        if outcome.kind == "result":
            raise ExtractionError(409, "job_id_unavailable")
        raise self._refusal(outcome, seen)

    def _reconcile(self, job_id: str, owner: str, digest: str, failed: Outcome, seen: Observation) -> Outcome:
        """A `submit` that did not produce a result may still have registered the job (a timeout or a lost acknowledgement). Ask the pipeline,
        under the same gate. Registered: carry on as if it had answered (the binding checks follow). Provably absent: the reservation is
        released. Anything else: the reservation is kept, so only the owner's identical retry can complete it. Nothing is ever resent here."""
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
        raise ExtractionError(503, "runtime_unavailable", retry_after=2)

    def _registered(self, outcome: Outcome, row: ExtractionRow, approval: extraction_access.Approval) -> ExtractionView:
        """A fresh registration is a queued job with no call, bound to exactly the approved request and provenance and to the input digest the
        service computed from the approved bytes and the pinned fixture digest (not an echo of the job id)."""
        view = self._view(outcome)
        provenance = approval.request["provenance"]
        if (view.job_id != row.job_id or view.input_digest != row.input_digest or view.state != "queued" or view.calls
                or view.provenance.model_dump() != {"source_kind": provenance.get("sourceKind"), "execution_mode": provenance.get("executionMode"),
                                                    "recording_kind": provenance.get("recordingKind")}):
            raise ExtractionError(500, "runtime_binding_mismatch")  # the reservation is kept: this is not a registration the service made
        if row.pins.live_binding is not None and call_pin_problem(view, row.pins) is not None:
            # The pipeline froze this job under a runtime other than the one the operator approved. It will never be dispatched or delivered.
            raise ExtractionError(409, "live_binding_mismatch")
        return view

    def status(self, owner: str, job_id: str, seen: Observation) -> Reply:
        row = self._owned(owner, job_id)
        view = self._read(row, seen)
        status = self._status(row, view, seen)
        return Reply(200, status, self._headers(status))

    def result(self, owner: str, job_id: str, seen: Observation) -> Reply:
        row = self._owned(owner, job_id)
        view, raw = self._read_with_payload(row, seen)
        delivery = self._delivery(row, view, seen)
        job = None
        if delivery.state == "available":
            try:
                job = ExtractionJobContent.model_validate(raw)
                if job.job_id != row.job_id or job.input_digest != row.input_digest:
                    raise ValueError("content binding")
            except (ValidationError, ValueError, KeyError, TypeError):
                job, delivery = None, ExtractionDelivery(state="withheld", reason="projection_invalid")
        status = self._status(row, view, seen, delivery=delivery)
        receipts = [ExtractionReceipt(stage=call.stage, state=call.state, verdict=call.verdict) for call in view.calls]
        return Reply(200, ExtractionResultEnvelope(status=status, delivery=delivery, job=job, receipts=receipts), self._headers(status))

    def _read_with_payload(self, row: ExtractionRow, seen: Observation) -> tuple[ExtractionView, dict[str, Any]]:
        with self._cli():
            outcome = self.process.inspect(row.job_id)
        view = self._parse(outcome, row, seen, "inspect")
        assert outcome.result is not None
        return view, outcome.result

    def cancel(self, owner: str, job_id: str, seen: Observation) -> Reply:
        """Idempotent for a cancelled job; refused for a ready one. Unlike the S3 pipeline, the S2 pipeline's own `cancel` leaves a ready job
        untouched, so it is handed every state and a ready answer is reported as `job_already_terminal`. A queued, running, stopped or reconciling
        job becomes `cancelled` for good (nothing resumes it, a pending dispatch ends, an already running child is never killed)."""
        row = self._owned(owner, job_id)
        with self._cli():
            view = self._parse(self.process.cancel(job_id), row, seen, "cancel")
        if view.state == "cancelled":
            self.ledger.cancel_pending(job_id)
        status = self._status(row, view, seen)
        if view.state == "ready":
            raise ExtractionError(409, "job_already_terminal", job_status=status)
        return Reply(200, status)

    def recover(self, owner: str, job_id: str, seen: Observation) -> Reply:
        row = self._owned(owner, job_id)
        if row.pins.live_binding is not None and self.config.pipeline_live is None:
            raise ExtractionError(409, "live_unavailable", job_status=self._status(row, self._read(row, seen), seen))
        refusal = self.authority.refusal(owner, job_id, row.pins.approval)  # a recovery is a content-bearing use: the approval is read NOW
        if refusal is not None:
            raise self._authority_error(refusal, seen)
        view = self._read(row, seen)
        dispatch = self.ledger.dispatch(job_id)
        assert dispatch is not None
        status = self._status(row, view, seen)
        if dispatch.state in ("pending", "in_flight"):
            return Reply(200, status, self._headers(status))
        if view.state == "reconciling" or (view.failure is not None and view.failure.code in UNANSWERED):
            raise ExtractionError(409, "reconcile_required", job_status=status)
        if view.state not in ("queued", "running", "stopped"):
            raise ExtractionError(409, "job_not_recoverable", job_status=status)
        queued = self.ledger.enqueue(job_id, MAX_PENDING)
        if queued == "full":
            raise ExtractionError(503, "queue_full", retry_after=30)
        self.dispatcher.wake()
        status = self._status(row, view, seen)
        return Reply(202 if queued == "enqueued" else 200, status, self._headers(status))
