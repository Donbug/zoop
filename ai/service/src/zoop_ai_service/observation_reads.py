"""Synchronous native reads: no cache, ingestion writes, retry, recovery or jobs."""
from __future__ import annotations

import threading

from pydantic import ValidationError

from .handoff_runtime import canonical
from .jobs import ApiError, Observation
from .observation_runtime import ObservationProcess
from .observation_wire import ObservationExport, ObservationExportRequest
from .runtime import MAX_STDOUT
from .wire import ErrorBody, ErrorEnvelope, RETRYABLE


class ObservationError(ApiError):
    def envelope(self, request_id: str) -> ErrorEnvelope:
        return ErrorEnvelope(error=ErrorBody(code=self.code, retryable=self.code in RETRYABLE or self.code in {"runtime_busy", "execution_unavailable"},
                                             request_id=request_id, runtime_code=self.runtime_code, field=self.field))


class ObservationReads:
    def __init__(self, process: ObservationProcess):
        self.process = process
        self._slots = threading.BoundedSemaphore(2)

    def export(self, request: ObservationExportRequest, seen: Observation) -> bytes:
        if not self._slots.acquire(blocking=False):
            raise ObservationError(503, "service_busy", retry_after=1)
        try:
            outcome = self.process.export(request)
            seen.runtime.append({"command": "export", "kind": outcome.kind, "exit": outcome.exit_code})
            if outcome.kind == "error":
                code = outcome.code
                if code == "ingestion_busy":
                    raise ObservationError(503, "runtime_busy", runtime_code=code, retry_after=2)
                if code == "source_unauthorized":
                    raise ObservationError(403, code)
                if code in {"round_not_found", "observation_not_found", "document_version_not_in_round"}:
                    raise ObservationError(404, code)
                if code in {"registry_changed", "scope_configuration_conflict", "preparation_profile_unbound"}:
                    raise ObservationError(409, code)
                # CLI codes have already been reduced to a bounded machine code; never relay its diagnostics.
                raise ObservationError(503, "service_configuration_invalid", runtime_code=code, retry_after=30)
            if outcome.kind == "contract":
                raise ObservationError(500, "runtime_contract_mismatch")
            if outcome.kind != "result" or outcome.result is None:
                raise ObservationError(503, "runtime_unavailable", retry_after=2)
            try:
                exported = ObservationExport.model_validate(outcome.result)
                if exported.wire() != outcome.result:
                    raise ValueError("native normalization")
            except (ValidationError, ValueError, UnicodeError, RecursionError):
                raise ObservationError(500, "runtime_contract_mismatch") from None
            observation = outcome.result["observation"]
            if any(observation[key] != value for key, value in request.wire().items() if key != "schemaVersion"):
                raise ObservationError(500, "runtime_binding_mismatch")
            raw = (canonical(outcome.result) + "\n").encode("utf-8")
            if len(raw) > MAX_STDOUT:
                raise ObservationError(500, "runtime_contract_mismatch")
            return raw
        finally:
            self._slots.release()
