"""The two read-only handoff operations (verified status and the full bundle), independent of HTTP framing. Blocking: callers run these in a worker thread.

Every answer is produced from ONE `zoop-ai-handoff export` child run during the same request, and the service keeps no state of its own: no ledger, no
reservation, no owner binding, no cache, no retry. It cannot freeze, recover, activate, publish or list a handoff, run a caller's path or command, or call a
model or a network; the only thing a caller chooses is an allowlisted handoff id.

Authority at delivery. Handoff content leaves this service only when ALL of these hold at the moment of the response: the principal is listed for the
handoff in the server-owned allowlist, read at the start, again after any wait for a slot or the gate and before the child starts, and once more when the
child has answered and before anything of its answer (content, state, reason or an error naming the handoff) is used, unchanged each time; the producer
reports the handoff `ready` with `delivery.status == "current"` (it re-verifies on every export the S3 authority and S2 upstream pins, the grants, the used
review revisions, the three operator files against the manifest pins and the rebuilt content digest); the digest of the canonical bundle bytes this service
received equals the producer's receipt AND the operator's `bundleDigest` pin, and the manifest digest equals the operator's `manifestDigest` pin; and the
bundle parses through the closed `Bundle` model and dumps back to exactly the canonical bytes that were hashed. Anything else is a withheld answer that
carries identity, state, `publication = not-published` and a reason code, never a count, a source id or a bundle (status and bundle routes alike), or an
error. A pin mismatch is withheld, never delivered "because the producer said current": the pins are the operator's reviewed content.
The checks are separate reads at separate instants, so a revocation that lands between them and the response is not covered, and nothing recalls content a
caller already received. Application import is still pending after any delivery (`appImport = pending`): the producer confirmed source-side facts only.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from . import handoff_access
from .config import ServiceConfig
from .handoff_runtime import HandoffProcess, canonical
from .handoff_wire import (BUNDLE_SCHEMA, RETRYABLE, STATES, Bundle, Export, HandoffManifest, HdBundle, HdDelivery, HdErrorEnvelope, HdStatus, HdVerification)
from .jobs import ApiError, Observation, Reply
from .relation_jobs import is_config_code
from .relation_runtime import GateBusy, RelationGate
from .runtime import Outcome
from .wire import ErrorBody

CLI_SLOTS = 2        # a bundle is parsed, validated and re-serialised in memory (up to the producer's 6 MiB): fewer concurrent children than the graph door
BUSY_WAIT = 10.0
CONTENT_KEYS = ("companies", "issues", "relations", "evidence", "articles")
# Pipeline refusals that mean "a writer holds a ledger right now", never "your request is wrong": retry later, never an empty answer.
BUSY_CODES = frozenset({"handoff_busy", "relation_busy", "extraction_busy", "ingestion_busy"})
# The server's own configuration or the operator's state is unusable (damaged or altered artifact, operator file, ownership, ledger) and needs an operator.
CONFIG_CODES = frozenset({"handoff_artifact_missing", "handoff_artifact_invalid", "handoff_artifact_conflict", "operator_file_changed", "operator_file_pin_mismatch",
                          "decisions_invalid", "bindings_invalid", "canonical_registry_invalid", "handoff_internal_failure", "handoff_limit_exceeded",
                          "input_or_configuration_invalid", "persistence_failed", "ledger_version_unknown", "state_ownership_unconfigured",
                          "state_namespace_conflict", "state_namespace_invalid", "analysis_contract_changed",
                          # the producer could not rebuild the bundle from the sources it is pinned to: an operator must look, the bundle is not deliverable
                          "article_metadata_conflict", "evidence_document_unbound", "evidence_input_kind_unsupported", "evidence_source_mismatch",
                          "evidence_unresolvable", "provenance_conflict", "relation_payload_invalid", "review_revision_changed", "attempt_limit_exceeded"})


class HandoffError(ApiError):
    """Same stable-code discipline as the S1 `ApiError`, with the handoff envelope family."""

    def envelope(self, request_id: str) -> HdErrorEnvelope:  # type: ignore[override]
        return HdErrorEnvelope(error=ErrorBody(code=self.code, retryable=self.code in RETRYABLE, request_id=request_id,
                                               runtime_code=self.runtime_code, field=self.field))


def stamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unavailable() -> HandoffError:
    return HandoffError(503, "runtime_unavailable", retry_after=2)


def _contract() -> HandoffError:
    """The producer's answer is not the contract this service knows: retrying will not change it, so it is not retryable."""
    return HandoffError(500, "runtime_contract_mismatch")


def _binding() -> HandoffError:
    return HandoffError(500, "runtime_binding_mismatch")


class Fetched:
    """One verified producer answer: the handoff's state and delivery, and the verification, parsed manifest and parsed bundle only when delivery is current
    and both pins matched."""

    def __init__(self, state: str, delivery: HdDelivery, verification: HdVerification | None = None, bundle: Bundle | None = None,
                 manifest: HandoffManifest | None = None):
        self.state, self.delivery, self.verification, self.bundle, self.manifest = state, delivery, verification, bundle, manifest


def _withheld(state: str, reason: str) -> Fetched:
    return Fetched(state, HdDelivery(state="withheld", reason=reason))


def content_digest(bundle: dict[str, Any]) -> str:
    """The producer's `content_digest`: SHA-256 of the canonical form of the five content lists."""
    return hashlib.sha256(canonical({key: bundle[key] for key in CONTENT_KEYS}).encode("utf-8")).hexdigest()


class HandoffReads:
    def __init__(self, config: ServiceConfig, process: HandoffProcess, gate: RelationGate | None, *, clock: Callable[[], float] = time.time,
                 busy_wait: float = BUSY_WAIT):
        assert config.handoff is not None
        self.config, self.handoff = config, config.handoff
        self.process, self.gate = process, gate
        self._clock, self._busy_wait = clock, busy_wait
        self._slots = threading.BoundedSemaphore(CLI_SLOTS)
        self._names = [principal.name for principal in config.principals]

    # ---- guards ----

    @contextmanager
    def _cli(self) -> Iterator[None]:
        """A small number of concurrent children. With an S2/S3 group in this process the handoff child also waits for THEIR gate (they write ledgers the
        handoff reads, and a pipeline writer lock does not wait); without one there is nothing in this process to collide with, so readers run side by side
        and an operator's own writer answers 503 busy."""
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

    @staticmethod
    def _fault(seen: Observation, problem: str | None) -> HandoffError:
        seen.problem = problem
        return HandoffError(503, "service_configuration_invalid", retry_after=30)

    def _entry(self, owner: str, handoff_id: str, seen: Observation) -> handoff_access.Entry:
        """The principal's listed entry, read fresh. Not listed is one answer whether or not the handoff exists, given before any child starts."""
        try:
            access = handoff_access.load(self.handoff.exports_path, self._names)
        except handoff_access.AccessError as error:
            raise self._fault(seen, error.code) from None
        entry = access.find(owner, handoff_id)
        if entry is None:
            raise HandoffError(403, "handoff_not_allowed")
        return entry

    def _still_listed(self, entry: handoff_access.Entry, seen: Observation) -> None:
        """The same entry, read again. A removed or changed entry is the same refusal as an unlisted handoff."""
        if self._entry(entry.principal, entry.handoff_id, seen) != entry:
            raise HandoffError(403, "handoff_not_allowed")

    # ---- producer reads ----

    @staticmethod
    def _log(seen: Observation, outcome: Outcome) -> None:
        seen.runtime.append({"command": "export", "kind": outcome.kind, "exit": outcome.exit_code, "code": outcome.code})

    def _refused(self, outcome: Outcome, seen: Observation) -> Fetched:
        """An error object of the producer: a withheld answer, or a stable error code that never carries a message."""
        code = outcome.code or ""
        if code == "handoff_not_found":
            raise HandoffError(404, "handoff_not_found", runtime_code=code)   # listed by the operator, absent from the handoff ledger
        if code == "handoff_not_ready":
            error = (outcome.result or {}).get("error")
            detail = error.get("detail") if isinstance(error, dict) else None
            state = detail.get("state") if isinstance(detail, dict) else None
            if state in STATES and state != "ready":
                return _withheld(state, "handoff_not_ready")
            raise _unavailable()
        if code in BUSY_CODES:
            raise HandoffError(503, "runtime_busy", runtime_code=code, retry_after=2)
        if code in CONFIG_CODES or is_config_code(code):
            raise self._fault(seen, code)
        raise HandoffError(500, "internal_error", runtime_code=code)

    def _fetch(self, entry: handoff_access.Entry, seen: Observation) -> Fetched:
        with self._cli():
            self._still_listed(entry, seen)   # after any wait for the gate or a slot: a revoked entry never starts a child
            outcome = self.process.export(entry.handoff_id)
        self._log(seen, outcome)
        self._still_listed(entry, seen)       # and nothing of the answer (content, state, reason or an error naming the handoff) outlives the entry
        if outcome.kind == "error":
            return self._refused(outcome, seen)
        if outcome.kind != "result" or outcome.result is None:
            raise _unavailable()
        try:
            view = Export.model_validate(outcome.result)
        except ValidationError:
            raise _contract() from None
        if view.handoff_id != entry.handoff_id:
            raise _binding()
        if view.delivery.status == "withheld":
            return _withheld(view.state, view.delivery.code or "withheld")
        receipt, received, frozen = view.receipt, view.bundle, view.manifest
        if view.state != "ready" or receipt is None or received is None or frozen is None or view.delivery.checked_at is None:
            raise _contract()
        # What this service received, hashed as the producer hashes it. The stdout was already proven canonical, so these are the artifact's own bytes.
        try:
            raw = canonical(received).encode("utf-8")
            actual, content = hashlib.sha256(raw).hexdigest(), content_digest(received)
            frozen_digest = hashlib.sha256(canonical(frozen).encode("utf-8")).hexdigest()
            digests = received["digests"]
            internal = (received["handoffId"], received["manifestDigest"], digests["content"], received["schemaVersion"])
            declared = (frozen["handoffId"], frozen["sourceKind"], frozen["policyVersion"], frozen["files"])
            carried = (entry.handoff_id, received["provenance"]["declaredSourceKind"], received["policy"]["version"], received["policy"]["files"])
            pins = sorted(canonical(pin) for pin in frozen["sources"])
            used = sorted(canonical({"relation": s["relation"], "upstream": s["upstream"], "reviewDigest": s["reviewDigest"]}) for s in received["sources"])
        except (KeyError, TypeError, UnicodeEncodeError):
            raise _contract() from None
        if internal != (entry.handoff_id, receipt.manifest_digest, content, BUNDLE_SCHEMA) or receipt.handoff_id != entry.handoff_id \
                or receipt.bundle_digest != actual or receipt.content_digest != content or receipt.bundle_bytes != len(raw) \
                or frozen_digest != receipt.manifest_digest or declared != carried or pins != used:
            raise _binding()
        if (receipt.manifest_digest, actual) != (entry.manifest_digest, entry.bundle_digest):
            return _withheld(view.state, "handoff_pin_mismatch")
        try:
            bundle = Bundle.model_validate(received)
            if canonical(bundle.wire()) != raw.decode("utf-8"):
                raise _contract()   # the model would normalise something: the delivered bundle could not hash to the pin
            manifest = HandoffManifest.model_validate(frozen)
            if canonical(manifest.wire()) != canonical(frozen):
                raise _contract()   # likewise for the manifest: its canonical bytes must hash to manifestDigest
        except ValidationError:
            raise _contract() from None
        verification = HdVerification(manifest_digest=receipt.manifest_digest, bundle_digest=actual, content_digest=content, bundle_bytes=len(raw),
                                      counts=bundle.counts, sources=len(bundle.sources), provenance=bundle.provenance)
        return Fetched(view.state, HdDelivery(state="current", checked_at=view.delivery.checked_at), verification, bundle, manifest)

    # ---- operations ----

    def _answer(self, owner: str, handoff_id: str, seen: Observation) -> tuple[handoff_access.Entry, Fetched]:
        entry = self._entry(owner, handoff_id, seen)
        fetched = self._fetch(entry, seen)
        if fetched.bundle is not None:
            self._still_listed(entry, seen)   # the last read before content is built into the response
        return entry, fetched

    def status(self, owner: str, handoff_id: str, seen: Observation) -> Reply:
        _, fetched = self._answer(owner, handoff_id, seen)
        body = HdStatus(handoff_id=handoff_id, state=fetched.state, delivery=fetched.delivery, verification=fetched.verification,
                        observed_at=stamp(self._clock()))
        return Reply(200, body)

    def bundle(self, owner: str, handoff_id: str, seen: Observation) -> Reply:
        _, fetched = self._answer(owner, handoff_id, seen)
        body = HdBundle(handoff_id=handoff_id, state=fetched.state, delivery=fetched.delivery, verification=fetched.verification, manifest=fetched.manifest,
                        bundle=fetched.bundle, observed_at=stamp(self._clock()))
        return Reply(200, body)
