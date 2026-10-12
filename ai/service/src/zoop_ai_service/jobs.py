"""The five job operations, independent of HTTP framing. Blocking: callers run these in a worker thread.

Every state shown to a caller is read from the runtime during the same request. The service ledger only adds ownership,
idempotency and the dispatch state, and it never holds a request body.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from . import grants
from .config import ServiceConfig
from .dispatch import Dispatcher, execution_unavailable
from .ledger import DispatchRow, JobRow, ServiceLedger, stamp
from .runtime import Outcome, WorkerProcess
from .wire import (DOCUMENT_KINDS, RETRYABLE, CallReceipt, Delivery, Dispatch, ErrorBody, ErrorEnvelope, Failure, JobStatus,
                   JobView, OutlookInputView, ResultEnvelope, Usage, next_action, unreceipted_attempts)

MAX_PENDING = 1000
CLI_SLOTS = 4
# Runtime refusals at submit that prove no registration happened for this request.
CONFIG_REFUSALS = frozenset({"stage_model_required", "provider_unsupported", "reasoning_effort_invalid"})
REGISTRY_REFUSALS = frozenset({"grant_registry_schema_invalid", "grant_revision_conflict"})


class ApiError(Exception):
    """Carries only stable codes. The envelope never has a message, stack, stderr, argv, path or environment text."""

    def __init__(self, status: int, code: str, *, runtime_code: str | None = None, field: str | None = None,
                 retry_after: int | None = None, job_status: JobStatus | None = None, headers: dict[str, str] | None = None):
        super().__init__(code)
        self.status, self.code, self.runtime_code, self.field = status, code, runtime_code, field
        self.job_status, self.headers = job_status, dict(headers or {})
        if retry_after is not None:
            self.headers["Retry-After"] = str(retry_after)

    def envelope(self, request_id: str) -> ErrorEnvelope:
        return ErrorEnvelope(error=ErrorBody(code=self.code, retryable=self.code in RETRYABLE, request_id=request_id,
                                             runtime_code=self.runtime_code, field=self.field), status=self.job_status)


@dataclass
class Reply:
    status: int
    body: JobStatus | ResultEnvelope
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Observation:
    """What one request learned from the runtime and the service ledger, for the access log line."""
    runtime: list[dict[str, Any]] = field(default_factory=list)
    problem: str | None = None


class KeyedLocks:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, list[Any]] = {}

    @contextmanager
    def hold(self, key: str) -> Iterator[None]:
        with self._guard:
            entry = self._locks.setdefault(key, [threading.Lock(), 0])
            entry[1] += 1
        try:
            with entry[0]:
                yield
        finally:
            with self._guard:
                entry[1] -= 1
                if entry[1] == 0:
                    del self._locks[key]


def request_digest(body: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Preflight:
    problem: str | None
    grants_digest: str | None


class JobService:
    def __init__(self, config: ServiceConfig, ledger: ServiceLedger, worker: WorkerProcess, dispatcher: Dispatcher,
                 *, clock: Callable[[], float] = time.time):
        self.config, self.ledger, self.worker, self.dispatcher, self._clock = config, ledger, worker, dispatcher, clock
        self._locks = KeyedLocks()
        self._slots = threading.BoundedSemaphore(CLI_SLOTS)

    # ---- guards ----

    @contextmanager
    def _slot(self) -> Iterator[None]:
        if not self._slots.acquire(blocking=False):
            raise ApiError(503, "service_busy", retry_after=1)
        try:
            yield
        finally:
            self._slots.release()

    def preflight(self) -> Preflight:
        """Server-owned inputs the runtime would read: grant registry, worker command and worker state directory."""
        digest = None
        try:
            digest = grants.load(self.config.grants_path).digest
        except grants.GrantRegistryError as error:
            return Preflight(error.code, None)
        command, state = self.config.worker_command, self.config.worker_state_dir
        if not (command.is_file() and os.access(command, os.X_OK)):
            return Preflight("worker_command_unavailable", digest)
        probe = state if state.exists() else state.parent
        if not (probe.is_dir() and os.access(probe, os.R_OK | os.W_OK | os.X_OK)):
            return Preflight("worker_state_unavailable", digest)
        return Preflight(None, digest)

    def _configuration_fault(self, seen: Observation, problem: str | None) -> ApiError:
        seen.problem = problem
        return ApiError(503, "service_configuration_invalid", retry_after=30)

    # ---- runtime reads ----

    def _view(self, outcome: Outcome, row: JobRow, seen: Observation, command: str) -> JobView:
        seen.runtime.append({"command": command, "kind": outcome.kind, "exit": outcome.exit_code, "code": outcome.code})
        if outcome.kind == "error":
            if outcome.code == "job_not_found":
                raise ApiError(500, "runtime_binding_mismatch", runtime_code=outcome.code)
            if outcome.code == "input_or_configuration_invalid":
                raise self._configuration_fault(seen, "runtime_configuration_unconfirmed")
            raise ApiError(500, "internal_error", runtime_code=outcome.code)
        if outcome.kind != "result":
            raise ApiError(503, "runtime_unavailable", retry_after=2)
        try:
            view = JobView.model_validate(outcome.result)
        except ValidationError:
            raise ApiError(503, "runtime_unavailable", retry_after=2) from None
        if (view.job_id != row.job_id or view.input_digest != row.input_digest or view.input.kind != row.kind
                or view.input.mode != row.mode):
            raise ApiError(500, "runtime_binding_mismatch")
        return view

    def _read(self, row: JobRow, seen: Observation) -> JobView:
        with self._slot():
            outcome = self.worker.get(row.job_id)
        return self._view(outcome, row, seen, "get")

    def _status(self, row: JobRow, view: JobView, dispatch: DispatchRow | None = None) -> JobStatus:
        dispatch = dispatch or self.ledger.dispatch(row.job_id)
        assert dispatch is not None and row.accepted_at is not None
        return JobStatus(
            job_id=row.job_id, kind=row.kind, mode=row.mode, input_digest=view.input_digest, state=view.state,
            phase=view.phase, resume_mode=view.resume_mode,
            failure=None if view.failure is None else Failure(code=view.failure.code, stage=view.failure.stage),
            artifact_ids=view.artifact_ids, usage=Usage.model_validate(view.usage.model_dump()),
            unreceipted_attempts=unreceipted_attempts(view),
            dispatch=Dispatch(state=dispatch.state, command=dispatch.command, dispatch_count=dispatch.dispatch_count,
                              last_outcome=dispatch.last_outcome, last_runtime_code=dispatch.last_runtime_code,
                              updated_at=dispatch.updated_at),
            next=next_action(view.state, view.resume_mode, dispatch.state),
            accepted_at=row.accepted_at, observed_at=stamp(self._clock()))

    def _owned(self, owner: str, job_id: str) -> JobRow:
        """Another owner's job, a reserved-only job and an unknown job all answer the same way."""
        row = self.ledger.job(job_id)
        if row is None or row.owner != owner or row.state != "accepted":
            raise ApiError(404, "job_not_found")
        return row

    @staticmethod
    def _headers(status: JobStatus, **extra: str) -> dict[str, str]:
        headers = dict(extra)
        if status.next == "wait":
            headers["Retry-After"] = "2"
        return headers

    # ---- operations ----

    def submit(self, owner: str, job_id: str, body: dict[str, Any], seen: Observation) -> Reply:
        digest, kind, mode = request_digest(body), body["kind"], body["mode"]
        location = {"Location": f"/internal/v1/analysis-jobs/{job_id}"}
        with self._locks.hold(job_id):
            row = self.ledger.job(job_id)
            if row is not None:
                if row.owner != owner:
                    raise ApiError(409, "job_id_unavailable")
                if row.request_digest != digest:
                    raise ApiError(409, "idempotency_conflict")
                if row.state == "accepted":
                    status = self._status(row, self._read(row, seen))
                    return Reply(200, status, self._headers(status, **location))
            if execution_unavailable(self.config, mode):
                raise ApiError(409, "execution_unavailable")
            if self.ledger.active_count() >= MAX_PENDING:
                raise ApiError(503, "queue_full", retry_after=30)
            before = self.preflight()
            if before.problem:
                raise self._configuration_fault(seen, before.problem)
            with self._slot():
                # Owner intent first (durable), then the runtime registers, then accepted + dispatch, then 202.
                row = row or self.ledger.reserve(job_id, owner, digest, kind, mode)
                attempts = self.ledger.begin_attempt(job_id)
                outcome = self.worker.submit(body)
            seen.runtime.append({"command": "submit", "kind": outcome.kind, "exit": outcome.exit_code, "code": outcome.code})
            if outcome.kind == "error":
                raise self._refuse(owner, job_id, digest, attempts, outcome.code or "", before, seen)
            if outcome.kind != "result":
                raise ApiError(503, "runtime_unavailable", retry_after=2)  # the runtime may hold the job: keep the reservation
            try:
                view = JobView.model_validate(outcome.result)
            except ValidationError:
                raise ApiError(503, "runtime_unavailable", retry_after=2) from None
            if view.job_id != job_id or view.input.kind != kind or view.input.mode != mode:
                raise ApiError(500, "runtime_binding_mismatch")
            accepted = self.ledger.accept(job_id, owner, view.input_digest, MAX_PENDING)
            if accepted == "full":
                raise ApiError(503, "queue_full", retry_after=30)  # another submission took the last slot; the claim is kept
            if accepted != "accepted":
                raise ApiError(500, "internal_error")
            self.dispatcher.wake()
            row = self.ledger.job(job_id)
            assert row is not None
            status = self._status(row, view)
            return Reply(202, status, self._headers(status, **location))

    def _refuse(self, owner: str, job_id: str, digest: str, attempts: int, code: str, before: Preflight,
                seen: Observation) -> ApiError:
        """Map a runtime refusal at submit. Only a refusal that proves nothing was registered releases the reservation."""
        released = lambda: attempts == 1 and self.ledger.release(job_id, owner, digest)  # noqa: E731
        if code == "job_input_conflict":
            released()
            return ApiError(409, "job_input_conflict", runtime_code=code)
        if code in CONFIG_REFUSALS:
            released()
            return ApiError(409, "execution_unavailable", runtime_code=code)
        if code in REGISTRY_REFUSALS:
            released()
            return self._configuration_fault(seen, code)
        if code == "input_or_configuration_invalid":
            # The runtime merges bad request input with server-side I/O faults. Only a clean server preflight that
            # observed the same grant registry before and after proves the request itself was invalid.
            after = self.preflight()
            if after.problem is None and after.grants_digest == before.grants_digest:
                released()
                return ApiError(422, "invalid_request", runtime_code=code)
            return self._configuration_fault(seen, after.problem or "grant_registry_changed")
        return ApiError(500, "internal_error", runtime_code=code)

    def status(self, owner: str, job_id: str, seen: Observation) -> Reply:
        row = self._owned(owner, job_id)
        status = self._status(row, self._read(row, seen))
        return Reply(200, status, self._headers(status))

    def result(self, owner: str, job_id: str, seen: Observation) -> Reply:
        row = self._owned(owner, job_id)
        view = self._read(row, seen)
        status = self._status(row, view)
        try:
            registry = grants.load(self.config.grants_path)
        except grants.GrantRegistryError as error:
            raise self._configuration_fault(seen, error.code) from None
        reason = self._withheld_reason(view, registry)
        job = None if reason else view.wire()
        receipts: list[CallReceipt] = view.calls
        envelope = ResultEnvelope(status=status, delivery=Delivery(state="withheld" if reason else "available", reason=reason),
                                  job=job, receipts=receipts)
        return Reply(200, envelope, self._headers(status))

    def _withheld_reason(self, view: JobView, registry: grants.Registry) -> str | None:
        """Current server authority at delivery, independent of the grant snapshot the runtime echoed.

        A live job's recipient identity (provider + endpoint revision) is only provable from the attempts the runtime recorded:
        until a call exists for every stage this job needs, no recipient can be shown to be authorized, so content stays withheld
        (a queued or not-yet-sent job must not leak through the async queue). Replay recipients are the fixed authored one.
        """
        submit = view.input
        body = submit.input
        source_id = body.source_id if isinstance(body, OutlookInputView) else body.document.source_id
        purposes = [submit.kind, "semantic-verification"] if submit.kind in DOCUMENT_KINDS else [submit.kind]
        recipients = []
        for purpose in purposes:
            if submit.mode == "replay":
                recipients.append("authored-replay")
                continue
            call = next((c for c in view.calls if c.stage == purpose), None)
            if call is None:
                return "recipient_unproven"
            recipients.append(call.config.provider + ":" + call.config.provider_revision)
        return grants.evaluate(registry.current(body.grant_id), source_id=source_id, revision=body.grant_revision,
                               purposes=purposes, recipients=recipients, now=datetime.fromtimestamp(self._clock(), UTC))

    def cancel(self, owner: str, job_id: str, seen: Observation) -> Reply:
        row = self._owned(owner, job_id)
        with self._slot():
            outcome = self.worker.cancel(job_id)
        view = self._view(outcome, row, seen, "cancel")
        if view.state == "cancelled":
            self.ledger.cancel_pending(job_id)
        status = self._status(row, view)
        if view.state in ("ready", "failed"):
            raise ApiError(409, "job_already_terminal", job_status=status)
        return Reply(200, status)

    def recover(self, owner: str, job_id: str, seen: Observation) -> Reply:
        row = self._owned(owner, job_id)
        view = self._read(row, seen)
        dispatch = self.ledger.dispatch(job_id)
        assert dispatch is not None
        if dispatch.state in ("pending", "in_flight"):
            return Reply(200, self._status(row, view, dispatch))
        status = self._status(row, view, dispatch)
        if view.state == "reconciling":
            raise ApiError(409, "reconcile_required", job_status=status)
        command = None
        if view.state in ("queued", "running"):
            command = "run"
        elif view.state == "persisting" and view.resume_mode in ("save_only", "validate_only"):
            command = "resume"
        elif view.state == "failed" and view.resume_mode == "unsent_only":
            command = "resume"  # the only path that can send unsent stages, and only on this explicit request
        if command is None:
            raise ApiError(409, "job_not_recoverable", job_status=status)
        queued = self.ledger.enqueue(job_id, command, MAX_PENDING)
        if queued == "full":
            raise ApiError(503, "queue_full", retry_after=30)
        self.dispatcher.wake()
        status = self._status(row, view)
        return Reply(202 if queued == "enqueued" else 200, status, self._headers(status))
