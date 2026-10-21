"""Wire models, limits and pure helpers of the nonpublic S3 -> Neo4j version projection. No I/O, no neo4j import, no SQLite.

The graph is a PROJECTION of one frozen S3 relation job (FS080 slice). It is never the authority for public display: `ready` means staged and
verified, `publication` is always `not-published`, and nothing here is approved, activated or an FS081 withdrawal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .ingestion_contracts import Wire
from .relation_contracts import MAX_RELATIONS, ExtractionFailure, canonical, digest

__all__ = ["ExtractionFailure", "canonical", "digest"]


class Withheld(ExtractionFailure):
    """A current-authority or integrity gate refused delivery. `read`/`focus` answer it as a withheld result (exit 2, no content); the other
    commands report the same code as an error."""


SCHEMA = "zoop-graph-projection-1"
LEDGER_VERSION = "zoop-graph-ledger-1"
STORE_SCHEMA = "zoop-graph-store-1"
VERSION_SCHEMA = "zoop-graph-version-1"
PLAN_VERSION = "zoop-graph-plan-2"
HISTORIC_PLAN_VERSIONS = ("zoop-graph-plan-1",)      # frozen before an approval basis was pinned: history only, never reinterpreted, projected, recovered or read
APPROVAL_KINDS = ("automatic-verifier", "operator-final-approval")       # who made an S3 relation eligible: the independent verifier, or a final human approval
APPROVAL_KEYS = ("kind", "revision", "reviewer", "decidedAt")
RELATION_ID_VERSION = "zoop-graph-relation-1"

MAX_COMMAND = 65_536
MAX_REGISTRY = 2_000_000
MAX_ENTRIES = 20_000
MAX_EDGES = MAX_RELATIONS            # the S3 production cap; read depth is a separate, unrelated limit
MAX_NODES = 300                      # every edge adds at most subject, object and one path intermediate
MAX_EVIDENCE = 8_000
MAX_PLAN = 2_000_000
MAX_ATTEMPTS = 5
UNRESOLVED_SHOWN = 50
DEPTHS = (1, 2, 3)

ID = r"^[A-Za-z0-9._:-]{1,200}$"
VERSION_ID = r"^[A-Za-z0-9._:-]{1,120}$"
HASH = r"^[a-f0-9]{64}$"
DATABASE = r"^[A-Za-z][A-Za-z0-9.-]{2,62}$"
KEY_SEPARATOR = "|"                  # not in ID or VERSION_ID, so `version|id` is unambiguous and round-trips

KINDS = ("company", "event", "topic")
LABELS = {"company": "ZgCompany", "event": "ZgEvent", "topic": "ZgTopic"}
KIND_OF_LABEL = {label: kind for kind, label in LABELS.items()}
STORE_LABEL = "ZgStore"
VERSION_LABEL = "ZgVersion"
ALLOWED_LABELS = (STORE_LABEL, VERSION_LABEL, *LABELS.values())


@dataclass(frozen=True)
class EdgeSpec:
    relationship: str
    subject: str
    object: str
    direction: str


# The closed graph vocabulary. A new S3 type must be added here AND in the Cypher/DDL constants before it can be projected; until then the
# planner fails the whole freeze (`relation_type_unsupported`) instead of dropping or guessing it.
EDGE_SPECS: dict[str, EdgeSpec] = {
    "SUPPLIES": EdgeSpec("ZG_SUPPLIES", "company", "company", "directed"),
    "INVESTS_IN": EdgeSpec("ZG_INVESTS_IN", "company", "company", "directed"),
    "COMPETES_WITH": EdgeSpec("ZG_COMPETES_WITH", "company", "company", "symmetric"),
    "PARTICIPATES_IN": EdgeSpec("ZG_PARTICIPATES_IN", "company", "event", "directed"),
    "RELATES_TO_TOPIC": EdgeSpec("ZG_RELATES_TO_TOPIC", "company", "topic", "directed"),
}
TYPE_OF_RELATIONSHIP = {spec.relationship: name for name, spec in EDGE_SPECS.items()}
ALLOWED_RELATIONSHIPS = tuple(TYPE_OF_RELATIONSHIP)

EDGE_KEYS = ("id", "direction", "connection", "businessScope", "productScope", "validFrom", "validUntil", "countries", "pathCompanyIds",
             "evidenceIds", "validityEvidenceIds", "step1EvidenceIds", "step2EvidenceIds", "sourceRelationCandidateIds")
EDGE_LISTS = frozenset({"countries", "pathCompanyIds", "evidenceIds", "validityEvidenceIds", "step1EvidenceIds", "step2EvidenceIds",
                        "sourceRelationCandidateIds"})
STORED_KEYS = frozenset({"vk", "v", *EDGE_KEYS})
NODE_KEYS = frozenset({"vk", "v", "id"})
MARKER_KEYS = frozenset({"versionId", "schema", "storeId", "payloadDigest", "graphDigest", "nodeCount", "edgeCount"})
STORE_SLOT = "store"


# ---------------------------------------------------------------------------------------------- wire models --------------------------

class RelationRef(Wire):
    job_id: str = Field(pattern=ID)
    input_digest: str = Field(pattern=HASH)


class Init(Wire):
    schema_version: Literal["zoop-graph-projection-1"]
    store_id: str = Field(pattern=ID)
    database: str = Field(pattern=DATABASE)

    @field_validator("database")
    @classmethod
    def user_database(cls, value: str) -> str:
        if value.lower() == "system":
            raise ValueError("the system database is never a projection target")
        return value


class Freeze(Wire):
    schema_version: Literal["zoop-graph-projection-1"]
    version_id: str = Field(pattern=VERSION_ID)
    relation: RelationRef


class Selector(Wire):
    schema_version: Literal["zoop-graph-projection-1"]
    version_id: str = Field(pattern=VERSION_ID)


class Focus(Wire):
    schema_version: Literal["zoop-graph-projection-1"]
    version_id: str = Field(pattern=VERSION_ID)
    company_id: str = Field(pattern=ID)
    depth: int

    @field_validator("depth", mode="before")
    @classmethod
    def exact_depth(cls, value):
        if type(value) is not int or value not in DEPTHS:
            raise ValueError("depth 1, 2 or 3")
        return value


class CanonicalUpstream(Wire):
    job_id: str = Field(pattern=ID)
    input_digest: str = Field(pattern=HASH)


class CanonicalEntry(Wire):
    """One operator decision: this S3 endpoint of this exact S2 upstream (job AND inputDigest) is this canonical identity.

    It is neither S2 SAME, topic approval nor public approval, and the S2 grant revision is deliberately not part of the key (grant currency is
    checked by every command instead, so a renewal does not silently invalidate decisions)."""
    upstream: CanonicalUpstream
    kind: Literal["company", "event", "topic"]
    ref: str = Field(min_length=1, max_length=200)
    canonical_id: str = Field(pattern=ID)
    decision_ref: str = Field(pattern=ID)


class CanonicalRegistry(Wire):
    schema_version: Literal["zoop-graph-canonical-1"]
    entries: list[CanonicalEntry] = Field(max_length=MAX_ENTRIES)

    @model_validator(mode="after")
    def unique(self):
        if len({entry_key(e.upstream.job_id, e.upstream.input_digest, e.kind, e.ref) for e in self.entries}) != len(self.entries):
            raise ValueError("duplicate canonical key")
        return self


def entry_key(job_id: str, input_digest: str, kind: str, ref: str) -> tuple[str, str, str, str]:
    return (job_id, input_digest, kind, ref)


# ---------------------------------------------------------------------------------------------- keys ----------------------------------

def node_key(version_id: str, ident: str) -> str:
    return f"{version_id}{KEY_SEPARATOR}{ident}"


def split_key(version_id: str, key: object) -> str:
    """The identity inside `version|id`, or ValueError. The version prefix must be exactly this version and the rest a well formed ID, so a key can
    never be read as another version's or as an ambiguous split."""
    prefix = node_key(version_id, "")
    if not isinstance(key, str) or not key.startswith(prefix):
        raise ValueError("key version")
    ident = key[len(prefix):]
    if not 1 <= len(ident) <= 200 or KEY_SEPARATOR in ident or not all(c.isascii() and (c.isalnum() or c in "._:-") for c in ident):
        raise ValueError("key identity")
    return ident


def relation_id(relation_type: str, subject: dict, obj: dict, business_scope, product_scope, valid_from, valid_until, connection: str,
                countries: list[str], path: list[dict]) -> str:
    """Stable identity of a canonical relation. Mirrors `relation_rules.relation_key` over canonical endpoints: evidence, wording and upstream
    are not part of it, so equal canonical claims from different S3 candidates merge and different scope/validity/path never do."""
    return "rel-" + digest({"version": RELATION_ID_VERSION, "type": relation_type, "subject": subject, "object": obj,
                            "businessScope": business_scope, "productScope": product_scope, "validity": {"from": valid_from, "until": valid_until},
                            "connection": connection, "countries": countries,
                            "path": [{"type": s["type"], "subject": s["subject"], "object": s["object"]} for s in path]})


# ---------------------------------------------------------------------------------------------- edge properties ----------------------

def normalized_props(props: dict) -> dict:
    """Every EDGE_KEYS entry, absent/null scalars as None and absent lists as []. Anything that is not exactly str / list[str] is rejected."""
    out: dict = {}
    for key in EDGE_KEYS:
        value = props.get(key)
        if key in EDGE_LISTS:
            if value is None:
                value = []
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(key)
        elif value is not None and not isinstance(value, str):
            raise ValueError(key)
        out[key] = value
    return out


def stored_props(version_id: str, props: dict) -> dict:
    """The Neo4j property map of an edge: `vk`, `v` and the non-null, non-empty EDGE_KEYS. Nulls and empty lists are omitted by design."""
    normalized = normalized_props(props)
    kept = {k: v for k, v in normalized.items() if v not in (None, [])}
    return {"vk": node_key(version_id, normalized["id"]), "v": version_id, **kept}


def observed_props(version_id: str, stored: dict) -> dict:
    """Normalized EDGE_KEYS of a stored edge, or ValueError for unknown keys, a foreign version or a key that does not match its id."""
    if not isinstance(stored, dict) or not set(stored) <= STORED_KEYS or stored.get("v") != version_id:
        raise ValueError("edge keys")
    normalized = normalized_props({k: v for k, v in stored.items() if k in EDGE_KEYS})
    if not isinstance(normalized["id"], str) or split_key(version_id, stored.get("vk")) != normalized["id"]:
        raise ValueError("edge key")
    for key in EDGE_LISTS:
        if key in stored and stored[key] == []:
            raise ValueError("empty list stored")
    return normalized


def graph_digest(version_id: str, nodes, edges) -> str:
    """Digest of the actual graph content. Shared by the planner (expected) and the reader (observed), so they can only agree on identical data.

    nodes: iterable of (label, id). edges: iterable of (type, id, (startLabel, startId), (endLabel, endId), props) with S3 type names."""
    return digest({"schema": SCHEMA, "versionId": version_id, "nodes": sorted([label, ident] for label, ident in nodes),
                   "edges": sorted(([t, i, [sl, sid], [el, eid], {k: normalized_props(props)[k] for k in EDGE_KEYS}]
                                    for t, i, (sl, sid), (el, eid), props in edges), key=lambda e: (e[0], e[1]))})


def plan_graph_digest(plan: dict) -> str:
    return graph_digest(plan["versionId"], [tuple(n) for n in plan["nodes"]],
                        [(e["type"], e["props"]["id"], (LABELS[e["subject"]["kind"]], e["subject"]["id"]),
                          (LABELS[e["object"]["kind"]], e["object"]["id"]), e["props"]) for e in plan["edges"]])


def marker_props(plan: dict, store_id: str, payload_digest: str, graph: str) -> dict:
    """Exactly the properties of the ZgVersion marker this plan must have."""
    return {"versionId": plan["versionId"], "schema": VERSION_SCHEMA, "storeId": store_id, "payloadDigest": payload_digest, "graphDigest": graph,
            "nodeCount": len(plan["nodes"]), "edgeCount": len(plan["edges"])}

