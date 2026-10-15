"""Wire models of the read-only graph family (`zoop-ai-internal-graph-1`) and the allowlisted projection of a `zoop-ai-graph read|focus` result.

Two kinds of model live here, mirroring `relation_wire.py` without sharing its schema or state machine:
  * `Graph*` models (extra forbidden) are what this service emits and what the generated OpenAPI documents;
  * `Rt*` / `GraphRead` projections (strict, extra ignored) parse the pipeline's canonical stdout. Each field the service relays is named exactly
    once, so a key the pipeline adds later (source job ids, review and canonical digests, attempts, audit counts, usage detail) is dropped
    instead of leaking, and a missing or mistyped required field fails closed.

The pipeline's graph output carries IDs and document/version/span coordinates only: no quote, title, URL, rationale or review note exists in it
(`graph_projection.py` module docstring), so there is nothing of that kind to filter here. What is filtered is everything that is not part of the
contract the application may read.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .relation_wire import Projection, Rel
from .wire import ErrorBody, Safe

SCHEMA = "zoop-ai-internal-graph-1"
RUNTIME_SCHEMA = "zoop-graph-projection-1"
VERSION_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,120}$"
COMPANY_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,200}$"
HASH_PATTERN = r"^[a-f0-9]{64}$"
DEPTHS = (1, 2, 3)
RETRYABLE = frozenset({"runtime_unavailable", "runtime_busy", "service_busy", "service_configuration_invalid"})

STATES = ("frozen", "reserved", "unknown", "ready", "failed")
State = Literal["frozen", "reserved", "unknown", "ready", "failed"]
Kind = Literal["company", "event", "topic"]
Direction = Literal["directed", "symmetric"]
Connection = Literal["direct", "indirect"]


# ---- what this service emits --------------------------------------------------------------------------------------------

class GraphDelivery(Rel):
    state: Literal["current", "withheld"]
    reason: Safe | None = None


class GraphVerification(Rel):
    """What the pipeline verified for this very response: the stored graph is exactly the frozen one. Digests and counts only."""
    graph_digest: str = Field(pattern=HASH_PATTERN)
    payload_digest: str = Field(pattern=HASH_PATTERN)
    nodes: int
    edges: int


class GraphNode(Rel):
    kind: Kind
    id: str
    distance: int = Field(description="Undirected hop distance from the focus company (0 for the company itself).")


class GraphEndpoint(Rel):
    kind: Kind
    id: str


class GraphValidity(Rel):
    valid_from: str | None = Field(alias="from")
    until: str | None


class GraphPath(Rel):
    company_ids: list[str]


class GraphEdgeEvidence(Rel):
    relation: list[str]
    validity: list[str]
    steps: list[list[str]]


class GraphEdge(Rel):
    relation_id: str
    type: str
    direction: Direction
    connection: Connection
    subject: GraphEndpoint
    object_: GraphEndpoint = Field(alias="object")
    business_scope: str | None
    product_scope: str | None
    validity: GraphValidity
    countries: list[str]
    path: GraphPath
    evidence: GraphEdgeEvidence
    source_relation_candidate_ids: list[str]


class GraphEvidence(Rel):
    evidence_id: str
    document_id: str
    document_version: str
    raw_version: str
    start: int
    end: int


class GraphContent(Rel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class GraphFocus(Rel):
    company_id: str = Field(pattern=COMPANY_ID_PATTERN)
    depth: Literal[1, 2, 3]
    found: bool | None = Field(description="Whether the company is a node of the verified version. null while delivery is withheld.")


class GraphVersionStatus(Rel):
    schema_version: Literal["zoop-ai-internal-graph-1"] = SCHEMA
    version_id: str = Field(pattern=VERSION_ID_PATTERN)
    state: State
    publication: Literal["not-published"] = "not-published"
    delivery: GraphDelivery
    verification: GraphVerification | None
    observed_at: str


class GraphFocusResult(Rel):
    schema_version: Literal["zoop-ai-internal-graph-1"] = SCHEMA
    version_id: str = Field(pattern=VERSION_ID_PATTERN)
    state: State
    publication: Literal["not-published"] = "not-published"
    delivery: GraphDelivery
    focus: GraphFocus
    verification: GraphVerification | None
    graph: GraphContent | None
    evidence: list[GraphEvidence] | None
    observed_at: str


class GraphErrorEnvelope(Rel):
    schema_version: Literal["zoop-ai-internal-graph-1"] = SCHEMA
    error: ErrorBody


# ---- what the pipeline reports (`zoop-ai-graph read|focus`) ---------------------------------------------------------------

class RtDelivery(Projection):
    status: Literal["current", "withheld"]
    code: str | None = None


class RtUsage(Projection):
    provider_calls: Literal[0]
    model_calls: Literal[0]


class RtDigests(Projection):
    payload: str = Field(pattern=HASH_PATTERN)
    graph: str = Field(pattern=HASH_PATTERN)


class RtJobRef(Projection):
    job_id: str
    input_digest: str = Field(pattern=HASH_PATTERN)


class RtSource(Projection):
    relation: RtJobRef


class RtVerification(Projection):
    marker: Literal["matched"]
    graph_digest: str = Field(pattern=HASH_PATTERN)
    nodes: int
    edges: int


class RtNode(Projection):
    kind: Kind
    id: str
    distance: int | None = None


class RtEndpoint(Projection):
    kind: Kind
    id: str


class RtValidity(Projection):
    valid_from: str | None = Field(alias="from")
    until: str | None


class RtPath(Projection):
    company_ids: list[str]


class RtEdgeEvidence(Projection):
    relation: list[str]
    validity: list[str]
    steps: list[list[str]]


class RtEdge(Projection):
    relation_id: str
    type: str
    direction: Direction
    connection: Connection
    subject: RtEndpoint
    object_: RtEndpoint = Field(alias="object")
    business_scope: str | None
    product_scope: str | None
    validity: RtValidity
    countries: list[str]
    path: RtPath
    evidence: RtEdgeEvidence
    source_relation_candidate_ids: list[str]


class RtEvidence(Projection):
    evidence_id: str
    document_id: str
    document_version: str
    raw_version: str
    start: int
    end: int


class RtGraph(Projection):
    nodes: list[RtNode]
    edges: list[RtEdge]


class RtFocus(Projection):
    company_id: str
    depth: int
    found: bool


class GraphRead(Projection):
    """A `read`/`focus` result. A withheld result carries only identity, state, delivery and usage; a current one also carries the rest."""
    schema_version: Literal["zoop-graph-projection-1"]
    version_id: str
    state: State
    publication: Literal["not-published"]
    delivery: RtDelivery
    usage: RtUsage
    digests: RtDigests | None = None
    source: RtSource | None = None
    verification: RtVerification | None = None
    focus: RtFocus | None = None
    graph: RtGraph | None = None
    evidence: list[RtEvidence] | None = None
