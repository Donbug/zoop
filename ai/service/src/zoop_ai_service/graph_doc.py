"""Authored OpenAPI semantics and examples of the read-only graph-version family. Every example is built through the real wire models, so an example that
stops validating fails at generation; the route and model schemas themselves come from the application (`app.openapi()`)."""
from __future__ import annotations

from typing import Any

from .graph_wire import GraphErrorEnvelope, GraphFocusResult, GraphVersionStatus
from .wire import ErrorBody

STAMP = "2026-10-12T03:00:00Z"
VERSION = "graph-synthetic-main"
GRAPH_DIGEST = "5" * 64
PAYLOAD_DIGEST = "6" * 64
RELATION = "rel-" + "1" * 64
EVIDENCE = "ev-" + "2" * 64
VERIFICATION = {"graphDigest": GRAPH_DIGEST, "payloadDigest": PAYLOAD_DIGEST, "nodes": 6, "edges": 5}
CURRENT = {"state": "current", "reason": None}

DESCRIPTION = """\
**Graph versions (`/internal/v1/graph-versions`, schema `zoop-ai-internal-graph-1`, scope `graph.read`).** A third, separate, strictly read-only family over the
installed `zoop-ai-graph read|focus` pipeline commands: a verified status of one version and the bounded neighbourhood of one company. It writes nothing
(no version, no pointer, no graph ledger, Neo4j or source ledger write, no model call), runs no caller-supplied query and has no list route. It is off unless
its all-or-nothing server configuration group is set (otherwise every route answers 409 `execution_unavailable` after authentication) and it is **not**
public: nothing here activates, publishes or withdraws a version, and `publication` is always `not-published`.

**Which versions a caller may read.** The version id is only a label, so the operator lists per principal the exact `{versionId, graphDigest, payloadDigest}` (and
optionally the frozen S3 relation job as `sourceRelation`) in a server-owned allowlist that is re-read on every request. A version that is not listed answers 403
`version_not_allowed` before any ledger or child process is touched, with one answer for "unknown" and "exists but not yours"; the service never adopts a version
the operator did not list. A listed version that the graph ledger does not have answers 404 `version_not_found` (an operator configuration gap).

**Delivery.** Content leaves only while the version verifies *now*: the pipeline re-checks the S3/S2 authority and source grants, every canonical decision, the S3
review state, the Neo4j store binding and the **full stored graph** against the frozen digest on every call, the digests it reports must equal the listed ones, and
the listed entry must be unchanged when read again just before the response. Otherwise the answer is **200 with `delivery.state=withheld`**, a reason code
(`source_unauthorized`, `upstream_changed`, `canonical_mapping_changed`, `review_revision_changed`, `graph_version_corrupt`, `graph_store_identity_mismatch`,
`version_not_ready`, `version_pin_mismatch`, `source_pin_mismatch` ...) and nothing else: no `verification`, `graph` or `evidence`. A withheld answer is not an
error and not an empty graph. These checks are separate reads at separate instants, so a revocation that lands between them and the response is not covered and
nothing recalls content a caller already received. `current` means "verified now", never "the version the application shows": there is no active pointer.

**Status.** `GET /{versionId}` runs the same gate chain and returns identity, `state` (`frozen|reserved|unknown|ready|failed`), `delivery` and, only when current,
`verification` (graph and payload digests, node and edge counts). It carries no node, edge or evidence and no Issue counts: the graph is built from S3
relations, not from Issues.

**Focus.** `GET /{versionId}/focus?companyId=&depth=` takes exactly these two query parameters, each once; `depth` is exactly 1, 2 or 3 and anything else (an unknown
or repeated key, `01`, `4`, a list) is 422. The neighbourhood is breadth-first over the undirected edges of the verified version; an edge is shown iff one endpoint is
closer than `depth`. `focus.found=false` (with empty `graph.nodes`, `graph.edges` and `evidence`) means the company is not a node of the verified version; it is a
verified answer, not an error. `evidence` lists only the records the shown edges reference, as IDs and document/version/span coordinates: the graph holds no quote,
title, URL, rationale or review note, and none is returned.

**Busy and unavailable.** An operator writer holding a ledger (`graph_busy`, `relation_busy`, `extraction_busy`, `ingestion_busy`) is 503 `runtime_busy`, a graph
database that does not answer is 503 `runtime_unavailable`, unusable server configuration or state (credentials, unbound store, damaged ledger) is 503
`service_configuration_invalid`, and too many concurrent reads is 503 `service_busy`; all carry `Retry-After`. A 503 is never an empty graph.
"""


def error(code: str, *, retryable: bool = False, runtime_code: str | None = None, field: str | None = None) -> dict[str, Any]:
    return GraphErrorEnvelope(error=ErrorBody(code=code, retryable=retryable, request_id="req-0001", runtime_code=runtime_code, field=field)).wire()


def status(**overrides: Any) -> dict[str, Any]:
    base = {"versionId": VERSION, "state": "ready", "delivery": CURRENT, "verification": VERIFICATION, "observedAt": STAMP, **overrides}
    return GraphVersionStatus.model_validate(base).wire()


def focus(**overrides: Any) -> dict[str, Any]:
    edge = {"relationId": RELATION, "type": "SUPPLIES", "direction": "directed", "connection": "direct",
            "subject": {"kind": "company", "id": "SYNTH-3"}, "object": {"kind": "company", "id": "SYNTH-1"},
            "businessScope": None, "productScope": None, "validity": {"from": None, "until": None}, "countries": [],
            "path": {"companyIds": []}, "evidence": {"relation": [EVIDENCE], "validity": [], "steps": [[], []]},
            "sourceRelationCandidateIds": ["rc-" + "3" * 64]}
    base = {"versionId": VERSION, "state": "ready", "delivery": CURRENT, "focus": {"companyId": "SYNTH-1", "depth": 1, "found": True},
            "verification": VERIFICATION,
            "graph": {"nodes": [{"kind": "company", "id": "SYNTH-1", "distance": 0}, {"kind": "company", "id": "SYNTH-3", "distance": 1}], "edges": [edge]},
            "evidence": [{"evidenceId": EVIDENCE, "documentId": "synthetic-doc-1", "documentVersion": "v1", "rawVersion": "raw-1", "start": 12, "end": 48}],
            "observedAt": STAMP, **overrides}
    return GraphFocusResult.model_validate(base).wire()


def examples() -> dict[str, Any]:
    withheld = {"state": "withheld", "reason": "source_unauthorized"}
    withheld_focus = {"focus": {"companyId": "SYNTH-1", "depth": 1, "found": None}, "verification": None, "graph": None, "evidence": None}
    return {
        "status": {"current": {"summary": "The version verifies now", "value": status()},
                   "withheld": {"summary": "A current authority gate refused delivery: identity, state and a reason code only",
                                "value": status(delivery=withheld, verification=None)},
                   "notReady": {"summary": "The version is frozen but not projected yet", "value": status(state="frozen", delivery={"state": "withheld", "reason": "version_not_ready"}, verification=None)}},
        "focus": {"current": {"summary": "Depth 1 around one company of a verified version", "value": focus()},
                  "absent": {"summary": "A company that is not a node of the verified version: found=false, empty content",
                             "value": focus(focus={"companyId": "SYNTH-9", "depth": 2, "found": False}, graph={"nodes": [], "edges": []}, evidence=[])},
                  "withheld": {"summary": "Source rights were revoked: no graph, no evidence", "value": focus(delivery=withheld, **withheld_focus)}},
        "errors": {
            "401": {"summary": "Missing, malformed or unknown bearer token", "value": error("authentication_required")},
            "403.scope": {"summary": "The principal lacks graph.read", "value": error("scope_denied")},
            "403.version": {"summary": "Not listed for this principal (unknown and unlisted answer alike)", "value": error("version_not_allowed")},
            "404": {"summary": "Listed by the operator but absent from the graph ledger", "value": error("version_not_found", runtime_code="version_not_found")},
            "409": {"summary": "The graph configuration group is not enabled", "value": error("execution_unavailable")},
            "422": {"summary": "Path or query validation", "value": error("invalid_request", field="depth")},
            "503.busy": {"summary": "A writer holds a ledger: retry later", "value": error("runtime_busy", retryable=True, runtime_code="graph_busy")},
            "503.unavailable": {"summary": "The graph database does not answer", "value": error("runtime_unavailable", retryable=True, runtime_code="graph_unavailable")},
        },
    }


def _attach(operation: dict[str, Any], code: str, mapping: dict[str, Any]) -> None:
    operation["responses"][code]["content"]["application/json"]["examples"] = mapping


def document(spec: dict[str, Any]) -> None:
    sample = examples()
    errors = sample["errors"]
    status_op = spec["paths"]["/internal/v1/graph-versions/{versionId}"]["get"]
    focus_op = spec["paths"]["/internal/v1/graph-versions/{versionId}/focus"]["get"]
    for operation in (status_op, focus_op):
        _attach(operation, "401", {"example": errors["401"]})
        _attach(operation, "403", {"scopeDenied": errors["403.scope"], "versionNotAllowed": errors["403.version"]})
        _attach(operation, "404", {"example": errors["404"]})
        _attach(operation, "409", {"example": errors["409"]})
        _attach(operation, "422", {"example": errors["422"]})
        _attach(operation, "503", {"runtimeBusy": errors["503.busy"], "runtimeUnavailable": errors["503.unavailable"]})
    status_op["responses"]["200"]["description"] = ("Verified status read from the pipeline during this request: identity, state, delivery and, only when current, "
                                                    "digests and counts. Never a node, edge, evidence record or Issue count.")
    _attach(status_op, "200", sample["status"])
    focus_op["responses"]["200"]["description"] = ("The neighbourhood of one company, only while every delivery gate holds at this moment; otherwise `delivery.state` is "
                                                   "`withheld` and graph, evidence and verification are null.")
    _attach(focus_op, "200", sample["focus"])
    for parameter in focus_op["parameters"]:
        if parameter["name"] == "depth":
            parameter["schema"] = {"type": "integer", "enum": [1, 2, 3]}
