"""The two read-only graph operations (version status and company focus), independent of HTTP framing. Blocking: callers run these in a worker thread.

Every answer is read from the pipeline (`zoop-ai-graph read|focus`) during the same request, and the service keeps no state of its own: no ledger,
no reservation, no owner binding, no cache. It cannot write a graph version, activate or publish one, list versions, run a caller's Cypher or call a
model; the only things a caller chooses are an allowlisted version id and, for a focus, a validated company id and a depth of 1, 2 or 3.

Authority at delivery. Graph content leaves this service only when ALL of these hold at the moment of the response: the principal is listed for the
version in the server-owned allowlist, read at the start, again after any wait for a slot or the gate and before the child starts, and once more when
the child has answered and before anything of its answer (content, state, reason or an error naming the version) is used, unchanged each time; the pipeline reports the version `ready`
with `delivery.status == "current"` (it re-verifies the S3/S2 authority and the source registry, every canonical decision, the S3 review state, the
Neo4j store binding and the FULL stored graph against the frozen digest on every call); the digests it reports equal the ones the operator listed
(and the frozen S3 relation job equals the optional source pin); and the payload parses strictly through the allowlisted projection. Anything else
is a withheld answer that carries identity, state, `publication = not-published` and a reason code, never a node, an edge or an evidence record.
The checks are separate reads at separate instants, so a revocation that lands between them and the response is not covered, and nothing recalls
content a caller already received. There is no active pointer: `current` means "verified now", never "the version the application shows".
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from pydantic import ValidationError

from . import graph_access
from .config import ServiceConfig
from .graph_runtime import GraphProcess
from .graph_wire import (RETRYABLE, STATES, GraphContent, GraphDelivery, GraphErrorEnvelope, GraphEvidence, GraphFocus, GraphFocusResult,
                         GraphRead, GraphVerification, GraphVersionStatus)
from .jobs import ApiError, Observation, Reply
from .relation_jobs import is_config_code
from .relation_runtime import GateBusy, RelationGate
from .runtime import Outcome
from .wire import ErrorBody

CLI_SLOTS = 4
BUSY_WAIT = 10.0
# Pipeline refusals that mean "a writer holds a ledger right now", never "your request is wrong": retry later, never an empty answer.
BUSY_CODES = frozenset({"graph_busy", "relation_busy", "extraction_busy", "ingestion_busy"})
# The graph database (or the network to it) is not answering: transient, retryable.
UNAVAILABLE_CODES = frozenset({"graph_unavailable", "graph_query_failed"})
# The server's own configuration or stored state is unusable (credentials, unbound store, missing or damaged ledger, canonical registry, ...).
CONFIG_CODES = frozenset({"graph_auth_failed", "graph_auth_unconfigured", "graph_server_unsupported", "graph_store_unbound", "graph_state_missing",
                          "graph_state_invalid", "graph_recovery_required", "ledger_version_unknown", "state_ownership_unconfigured",
                          "canonical_registry_invalid", "input_or_configuration_invalid", "persistence_failed", "graph_internal_failure",
                          "poc_contract_changed"})


class GraphError(ApiError):
    """Same stable-code discipline as the S1 `ApiError`, with the graph envelope family."""

    def envelope(self, request_id: str) -> GraphErrorEnvelope:  # type: ignore[override]
        return GraphErrorEnvelope(error=ErrorBody(code=self.code, retryable=self.code in RETRYABLE, request_id=request_id,
                                                  runtime_code=self.runtime_code, field=self.field))


def stamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unavailable() -> GraphError:
    return GraphError(503, "runtime_unavailable", retry_after=2)


class Fetched:
    """One verified pipeline answer: the version's state and delivery, and the parsed result only when delivery is current and every pin matched."""

    def __init__(self, state: str, delivery: GraphDelivery, read: GraphRead | None = None):
        self.state, self.delivery, self.read = state, delivery, read


def _withheld(state: str, reason: str) -> Fetched:
    return Fetched(state, GraphDelivery(state="withheld", reason=reason))


class GraphReads:
    def __init__(self, config: ServiceConfig, process: GraphProcess, gate: RelationGate | None, *, clock: Callable[[], float] = time.time,
                 busy_wait: float = BUSY_WAIT):
        assert config.graph is not None
        self.config, self.graph = config, config.graph
        self.process, self.gate = process, gate
        self._clock, self._busy_wait = clock, busy_wait
        self._slots = threading.BoundedSemaphore(CLI_SLOTS)
        self._names = [principal.name for principal in config.principals]

    # ---- guards ----

    @contextmanager
    def _cli(self) -> Iterator[None]:
        """A small number of concurrent children. With an S2/S3 group in this process the graph child also waits for THEIR gate (they write ledgers the
        graph reads, and a pipeline writer lock does not wait); without one there is nothing in this process to collide with, so readers run side by
        side and an operator's own writer answers 503 busy."""
        if not self._slots.acquire(blocking=False):
            raise GraphError(503, "service_busy", retry_after=1)
        try:
            if self.gate is None:
                yield
            else:
                try:
                    with self.gate.hold(self._busy_wait):
                        yield
                except GateBusy:
                    raise GraphError(503, "runtime_busy", retry_after=2) from None
        finally:
            self._slots.release()

    @staticmethod
    def _fault(seen: Observation, problem: str | None) -> GraphError:
        seen.problem = problem
        return GraphError(503, "service_configuration_invalid", retry_after=30)

    def _entry(self, owner: str, version_id: str, seen: Observation) -> graph_access.Entry:
        """The principal's listed entry, read fresh. Not listed is one answer whether or not the version exists, given before any child starts."""
        try:
            access = graph_access.load(self.graph.versions_path, self._names)
        except graph_access.AccessError as error:
            raise self._fault(seen, error.code) from None
        entry = access.find(owner, version_id)
        if entry is None:
            raise GraphError(403, "version_not_allowed")
        return entry

    # ---- pipeline reads ----

    @staticmethod
    def _log(seen: Observation, command: str, outcome: Outcome) -> None:
        seen.runtime.append({"command": command, "kind": outcome.kind, "exit": outcome.exit_code, "code": outcome.code})

    def _refused(self, outcome: Outcome, seen: Observation) -> Fetched:
        """An error object of the pipeline: a withheld answer, or a stable error code that never carries a message."""
        code = outcome.code or ""
        if code == "version_not_found":
            raise GraphError(404, "version_not_found", runtime_code=code)   # listed by the operator, absent from the graph ledger
        if code == "version_not_ready":
            error = (outcome.result or {}).get("error")
            detail = error.get("detail") if isinstance(error, dict) else None
            state = detail.get("state") if isinstance(detail, dict) else None
            if state in STATES and state != "ready":
                return _withheld(state, "version_not_ready")
            raise _unavailable()
        if code in BUSY_CODES:
            raise GraphError(503, "runtime_busy", runtime_code=code, retry_after=2)
        if code in UNAVAILABLE_CODES:
            raise GraphError(503, "runtime_unavailable", runtime_code=code, retry_after=2)
        if code in CONFIG_CODES or is_config_code(code):
            raise self._fault(seen, code)
        raise GraphError(500, "internal_error", runtime_code=code)

    def _fetch(self, entry: graph_access.Entry, command: str, call: Callable[[], Outcome], seen: Observation) -> Fetched:
        with self._cli():
            self._still_listed(entry, seen)   # after any wait for the gate or a slot: a revoked entry never starts a child
            outcome = call()
        self._log(seen, command, outcome)
        self._still_listed(entry, seen)       # and nothing of the answer (content, state, reason or an error naming the version) outlives the entry
        if outcome.kind == "error":
            return self._refused(outcome, seen)
        if outcome.kind != "result" or outcome.result is None:
            raise _unavailable()
        try:
            view = GraphRead.model_validate(outcome.result)
        except ValidationError:
            raise _unavailable() from None
        if view.version_id != entry.version_id:
            raise GraphError(500, "runtime_binding_mismatch")
        if view.delivery.status == "withheld":
            return _withheld(view.state, view.delivery.code or "withheld")
        if view.state != "ready" or view.digests is None or view.source is None or view.verification is None \
                or view.verification.graph_digest != view.digests.graph:
            raise _unavailable()
        if (view.digests.graph, view.digests.payload) != (entry.graph_digest, entry.payload_digest):
            return _withheld(view.state, "version_pin_mismatch")
        relation = view.source.relation
        if entry.source_job_id is not None and (relation.job_id, relation.input_digest) != (entry.source_job_id, entry.source_input_digest):
            return _withheld(view.state, "source_pin_mismatch")
        return Fetched(view.state, GraphDelivery(state="current"), view)

    def _still_listed(self, entry: graph_access.Entry, seen: Observation) -> None:
        """The same entry, read again. A removed or changed entry is the same refusal as an unlisted version."""
        if self._entry(entry.principal, entry.version_id, seen) != entry:
            raise GraphError(403, "version_not_allowed")

    @staticmethod
    def _verification(view: GraphRead) -> GraphVerification:
        assert view.digests is not None and view.verification is not None
        return GraphVerification(graph_digest=view.digests.graph, payload_digest=view.digests.payload, nodes=view.verification.nodes,
                                 edges=view.verification.edges)

    # ---- operations ----

    def status(self, owner: str, version_id: str, seen: Observation) -> Reply:
        entry = self._entry(owner, version_id, seen)
        fetched = self._fetch(entry, "read", lambda: self.process.read(version_id), seen)
        if fetched.read is not None:
            self._still_listed(entry, seen)   # the last read before content is built
        verification = None if fetched.read is None else self._verification(fetched.read)
        body = GraphVersionStatus(version_id=version_id, state=fetched.state, delivery=fetched.delivery, verification=verification,
                                  observed_at=stamp(self._clock()))
        return Reply(200, body)

    def focus(self, owner: str, version_id: str, company_id: str, depth: int, seen: Observation) -> Reply:
        entry = self._entry(owner, version_id, seen)
        fetched = self._fetch(entry, "focus", lambda: self.process.focus(version_id, company_id, depth), seen)
        view = fetched.read
        if view is None:
            body = GraphFocusResult(version_id=version_id, state=fetched.state, delivery=fetched.delivery,
                                    focus=GraphFocus(company_id=company_id, depth=depth, found=None), verification=None, graph=None, evidence=None,
                                    observed_at=stamp(self._clock()))
            return Reply(200, body)
        echo = view.focus
        if echo is None or view.graph is None or view.evidence is None:
            raise _unavailable()
        if (echo.company_id, echo.depth) != (company_id, depth):
            raise GraphError(500, "runtime_binding_mismatch")
        try:
            graph = GraphContent.model_validate(view.graph.wire())
            evidence = [GraphEvidence.model_validate(record) for record in (item.wire() for item in view.evidence)]
        except ValidationError:
            raise _unavailable() from None
        self._still_listed(entry, seen)       # the last read before the validated content is built into the response
        verification = self._verification(view)
        body = GraphFocusResult(version_id=version_id, state=fetched.state, delivery=fetched.delivery,
                                focus=GraphFocus(company_id=company_id, depth=depth, found=echo.found), verification=verification,
                                graph=graph, evidence=evidence, observed_at=stamp(self._clock()))
        return Reply(200, body)
