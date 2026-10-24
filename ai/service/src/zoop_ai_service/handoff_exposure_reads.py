"""Identity reads remain available after source-rights revocation, but never after allowlist revocation.

Each authorization observation loads the whole allowlist once. These observations are not atomic with the response.
Reported pins are compared to the allowlist; this service does not receive or hash bundle artifact bytes.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from collections.abc import Iterator

from pydantic import ValidationError

from . import handoff_access
from .config import ServiceConfig
from .handoff_exposure_runtime import HandoffExposureProcess
from .handoff_exposure_wire import ExposureQuery, ExposureReport, HdExposure
from .handoff_reads import BUSY_CODES, BUSY_WAIT, CLI_SLOTS, CONFIG_CODES, HandoffError
from .handoff_runtime import canonical
from .jobs import Observation, Reply
from .relation_jobs import is_config_code
from .relation_runtime import GateBusy, RelationGate


class HandoffExposureReads:
    def __init__(self, config: ServiceConfig, process: HandoffExposureProcess, gate: RelationGate | None, *, busy_wait: float = BUSY_WAIT):
        assert config.handoff_exposure is not None
        self.config, self.exposure, self.process, self.gate = config, config.handoff_exposure, process, gate
        self._names = [p.name for p in config.principals]
        self._slots = threading.BoundedSemaphore(CLI_SLOTS)
        self._busy_wait = busy_wait

    def _snapshot(self, owner: str, ids: list[str], seen: Observation) -> tuple[handoff_access.Entry, ...]:
        try:
            access = handoff_access.load(self.exposure.exports_path, self._names)
        except handoff_access.AccessError as error:
            seen.problem = error.code
            raise HandoffError(503, "service_configuration_invalid", retry_after=30) from None
        entries = tuple(access.find(owner, handoff_id) for handoff_id in ids)
        if any(entry is None for entry in entries):
            raise HandoffError(403, "handoff_not_allowed")
        return entries

    def _unchanged(self, owner: str, ids: list[str], entries: tuple[handoff_access.Entry, ...], seen: Observation) -> None:
        if self._snapshot(owner, ids, seen) != entries:
            raise HandoffError(403, "handoff_not_allowed")

    @contextmanager
    def _cli(self) -> Iterator[None]:
        if not self._slots.acquire(blocking=False):
            raise HandoffError(503, "service_busy", retry_after=1)
        try:
            if self.gate is None:
                yield
            else:
                try:
                    with self.gate.hold(self._busy_wait):
                        yield
                except GateBusy:
                    raise HandoffError(503, "runtime_busy", retry_after=2) from None
        finally:
            self._slots.release()

    def query(self, owner: str, query: ExposureQuery, seen: Observation) -> Reply:
        ids = sorted(query.handoff_ids)
        entries = self._snapshot(owner, ids, seen)
        with self._cli():
            self._unchanged(owner, ids, entries, seen)
            outcome = self.process.query(query)
        # Revocation suppresses success AND errors before interpreting/logging any child code.
        self._unchanged(owner, ids, entries, seen)
        seen.runtime.append({"command": "exposure", "kind": outcome.kind, "exit": outcome.exit_code})
        if outcome.kind == "error":
            code = outcome.code or ""
            if code == "handoff_selection_unmappable":
                raise HandoffError(409, code)
            if code in {"changed_identity_unknown", "changed_relation_unused", "exposure_report_limit"}:
                raise HandoffError(422, code)
            if code in BUSY_CODES:
                raise HandoffError(503, "runtime_busy", runtime_code=code, retry_after=2)
            if code in CONFIG_CODES or code in {"exposure_internal_failure", "dependency_record_invalid"} or is_config_code(code):
                seen.problem = code
                raise HandoffError(503, "service_configuration_invalid", retry_after=30)
            raise HandoffError(500, "internal_error")
        if outcome.kind == "contract":
            raise HandoffError(500, "runtime_contract_mismatch")
        if outcome.kind != "result" or outcome.result is None:
            raise HandoffError(503, "runtime_unavailable", retry_after=2)
        try:
            report = ExposureReport.model_validate(outcome.result)
            if canonical(report.wire()) != canonical(outcome.result):
                raise ValueError("normalization")
        except (ValidationError, ValueError, UnicodeError):
            raise HandoffError(500, "runtime_contract_mismatch") from None
        if report.scope.handoff_ids != ids or report.changed.wire() != query.changed.wire():
            raise HandoffError(500, "runtime_binding_mismatch")
        if any((row.manifest_digest, row.bundle_digest) != (entry.manifest_digest, entry.bundle_digest)
               for row, entry in zip(report.handoffs, entries, strict=True)):
            raise HandoffError(409, "handoff_pin_mismatch")
        self._unchanged(owner, ids, entries, seen)
        return Reply(200, HdExposure(report=report))
