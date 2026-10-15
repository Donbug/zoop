"""Neo4j adapter of the nonpublic version projection. The only module that imports the driver.

Every statement is a module constant and every datum (version, IDs, properties, counts) is a query PARAMETER; `run()` refuses any statement that is
not in the closed set, so no caller, registry or model text can ever become Cypher. Transactions are explicit and unmanaged (`begin_transaction`),
never auto-retried (`disable_auto_commit_retries`, no `execute_*`/`session.run`), and carry fixed timeouts. This module has no delete, MERGE,
LOAD, APOC or admin statement; the only writes are CREATE of schema, the store marker, version nodes, version edges and the version marker.
"""
from __future__ import annotations

import ipaddress
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit

from neo4j import READ_ACCESS, WRITE_ACCESS, GraphDatabase, basic_auth
from neo4j.exceptions import AuthError, ConstraintError, DriverError, Neo4jError

from .graph_projection_contracts import (ALLOWED_LABELS, ALLOWED_RELATIONSHIPS, EDGE_SPECS, LABELS, MARKER_KEYS, MAX_EDGES, MAX_NODES, NODE_KEYS,
    STORE_LABEL, STORE_SCHEMA, STORE_SLOT, TYPE_OF_RELATIONSHIP, VERSION_LABEL, ExtractionFailure, node_key, observed_props, split_key)

USER_AGENT = "zoop-graph-projection/1"
TX_TIMEOUT = 30.0          # seconds, every read and write transaction
CONNECT_TIMEOUT = 5.0
ACQUIRE_TIMEOUT = 10.0
POOL = 2
AWAIT_SECONDS = 20         # stays below TX_TIMEOUT

LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
_DNS = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")


# ---------------------------------------------------------------------------------------------- connection configuration -------------

def validate_uri(uri: object) -> str:
    """The normalized URI of an allowed target, else `graph_uri_invalid`.

    Allowed: plain `bolt://` to a loopback host, or `bolt+s://` (certificate-verified TLS) to any host; both with an explicit port. Refused: routing
    (`neo4j*`), unverified TLS (`bolt+ssc`), userinfo, path, query, fragment, whitespace, a missing/invalid port and plain bolt to a non-loopback host."""
    bad = ExtractionFailure("graph_uri_invalid")
    if not isinstance(uri, str) or not uri.isascii() or not 8 <= len(uri) <= 300 or any(c in uri for c in " \t\r\n\\#?@%"):
        raise bad
    try:
        parts = urlsplit(uri)
        port = parts.port
    except ValueError:
        raise bad from None
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"bolt", "bolt+s"} or parts.path or parts.query or parts.fragment or parts.username is not None or parts.password is not None:
        raise bad
    if not host or port is None or not 1 <= port <= 65535:
        raise bad
    if parts.scheme == "bolt":
        if host not in LOOPBACK:
            raise bad
    else:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not _DNS.fullmatch(host):
                raise bad from None
    shown = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{shown}:{port}"


def is_secure(uri: str) -> bool:
    return uri.startswith("bolt+s://")


def read_auth(uri: str, env: dict | None = None) -> tuple[str, str] | None:
    """Credentials only from the environment (`ZOOP_GRAPH_AUTH=none|basic`, `ZOOP_GRAPH_USER`, `ZOOP_GRAPH_PASSWORD`), never from stdin, argv or
    the ledger. A remote (TLS) target always needs basic credentials. Nothing here is ever echoed."""
    source = os.environ if env is None else env
    mode = source.get("ZOOP_GRAPH_AUTH")
    if mode == "none" and not is_secure(uri):
        return None
    if mode == "basic":
        user, password = source.get("ZOOP_GRAPH_USER"), source.get("ZOOP_GRAPH_PASSWORD")
        if user and password and len(user) <= 200 and len(password) <= 2000:
            return user, password
    raise ExtractionFailure("graph_auth_unconfigured")


# ---------------------------------------------------------------------------------------------- the closed statement set -------------

CONSTRAINTS: dict[str, tuple[str, str, str, str]] = {   # name -> (SHOW type, entityType, label/relationship type, property)
    "zg_store_slot": ("UNIQUENESS", "NODE", STORE_LABEL, "slot"),
    "zg_version_id": ("UNIQUENESS", "NODE", VERSION_LABEL, "versionId"),
    **{f"zg_{kind}_vk": ("UNIQUENESS", "NODE", label, "vk") for kind, label in LABELS.items()},
    **{f"zg_{name.lower()}_vk": ("RELATIONSHIP_UNIQUENESS", "RELATIONSHIP", spec.relationship, "vk") for name, spec in EDGE_SPECS.items()},
}
VERSION_INDEXES: dict[str, tuple[str, str]] = {f"zg_{kind}_v": (label, "v") for kind, label in LABELS.items()}
# Expected RANGE indexes: the ten indexes owned by the constraints plus the three per-label version indexes.
INDEXES: dict[str, tuple[str, str, str]] = {**{name: (entity, label, prop) for name, (_, entity, label, prop) in CONSTRAINTS.items()},
                                           **{name: ("NODE", label, prop) for name, (label, prop) in VERSION_INDEXES.items()}}


def _constraint_ddl(name: str, entity: str, label: str, prop: str) -> str:
    if entity == "NODE":
        return f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
    return f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR ()-[r:{label}]-() REQUIRE r.{prop} IS UNIQUE"


DDL: tuple[str, ...] = (
    *(_constraint_ddl(name, entity, label, prop) for name, (_, entity, label, prop) in CONSTRAINTS.items()),
    *(f"CREATE INDEX {name} IF NOT EXISTS FOR (n:{label}) ON (n.{prop})" for name, (label, prop) in VERSION_INDEXES.items()),
)
AWAIT_INDEXES = f"CALL db.awaitIndexes({AWAIT_SECONDS})"

COMPONENTS = "CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition"
DB_INFO = "CALL db.info() YIELD id, name RETURN id, name"
COUNT_NODES = "MATCH (n) RETURN count(n) AS c"
COUNT_RELATIONSHIPS = "MATCH ()-[r]->() RETURN count(r) AS c"
FOREIGN_NODES = "MATCH (n) WHERE size(labels(n)) <> 1 OR NOT labels(n)[0] IN $allowed RETURN count(n) AS c"
FOREIGN_RELATIONSHIPS = "MATCH ()-[r]->() WHERE NOT type(r) IN $allowed RETURN count(r) AS c"
SHOW_CONSTRAINTS = "SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties"
SHOW_INDEXES = "SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, properties, state"
# The store marker is found WITHOUT naming the label as a pattern: a query that names a label/type/property key the database has never seen makes
# the server emit an UnknownLabel/UnknownPropertyKey warning notification (printed by the driver's logger). `init` probes a database BEFORE any
# schema object (and therefore any token) exists, so nothing queried before the DDL may name a Zg label. The string literal is not a label reference.
STORE_READ = f"MATCH (s) WHERE '{STORE_LABEL}' IN labels(s) RETURN labels(s) AS l, properties(s) AS p LIMIT 3"
# Guarded so a store marker can only be created in a database that has no node at all; the slot constraint makes a concurrent second creator fail.
STORE_CREATE = (f"MATCH (n) WITH count(n) AS c WHERE c = 0 "
                f"CREATE (s:{STORE_LABEL} {{slot: $slot, storeId: $storeId, schema: $schema, owner: $owner}}) RETURN count(s) AS created")

READ_MARKER = f"MATCH (m:{VERSION_LABEL} {{versionId: $v}}) RETURN labels(m) AS l, properties(m) AS p LIMIT 2"
# Nodes that CLAIM the version (`v`, or key prefix `version|...`) under ANY label or none: a ZgVersion/ZgStore-labelled node carrying them is neither the
# marker nor allowed data. One bounded scan over nodes, the same class of scan as FOREIGN_NODES and READ_OWNED_EDGES.
DATA_LABELS = frozenset(LABELS.values())
READ_OWNED_NODES = "MATCH (n) WHERE n.v = $v OR n.vk STARTS WITH $prefix RETURN labels(n) AS l, properties(n) AS p LIMIT $cap"
# Relationships attached to this version's nodes (they may belong to another version: that is foreign data and fails the check).
READ_EDGES = {label: (f"MATCH (n:{label} {{v: $v}})-[e]-() RETURN DISTINCT elementId(e) AS eid, type(e) AS t, properties(e) AS p, "
                      f"labels(startNode(e)) AS sl, startNode(e).vk AS svk, labels(endNode(e)) AS el, endNode(e).vk AS evk LIMIT $cap")
              for label in LABELS.values()}
# Relationships that CLAIM the version (`v` or key prefix) wherever they are attached: a version-owned relationship between another version's nodes is
# invisible to the incident enumeration above. One bounded scan over relationships, the same class of scan as FOREIGN_RELATIONSHIPS.
READ_OWNED_EDGES = ("MATCH (a)-[e]->(b) WHERE e.v = $v OR e.vk STARTS WITH $prefix RETURN elementId(e) AS eid, type(e) AS t, properties(e) AS p, "
                    "labels(a) AS sl, a.vk AS svk, labels(b) AS el, b.vk AS evk LIMIT $cap")
NODE_WRITE = {label: f"UNWIND $ids AS ident CREATE (n:{label} {{vk: $v + '|' + ident, v: $v, id: ident}}) RETURN count(n) AS c" for label in LABELS.values()}
# `WITH r, a` keeps the second endpoint lookup in its own query part (an Apply per row); two MATCH patterns in one part would be planned as a
# cartesian product and the server would warn about it.
EDGE_WRITE = {name: (f"UNWIND $rows AS r MATCH (a:{LABELS[spec.subject]} {{vk: $v + '|' + r.subject}}) WITH r, a "
                     f"MATCH (b:{LABELS[spec.object]} {{vk: $v + '|' + r.object}}) CREATE (a)-[e:{spec.relationship}]->(b) SET e = r.props RETURN count(e) AS c")
              for name, spec in EDGE_SPECS.items()}
MARKER_WRITE = (f"CREATE (m:{VERSION_LABEL} {{versionId: $v, schema: $schema, storeId: $storeId, payloadDigest: $payload, graphDigest: $graph, "
                f"nodeCount: $nodes, edgeCount: $edges}}) RETURN count(m) AS c")

STATEMENTS = frozenset({*DDL, AWAIT_INDEXES, COMPONENTS, DB_INFO, COUNT_NODES, COUNT_RELATIONSHIPS, FOREIGN_NODES, FOREIGN_RELATIONSHIPS, SHOW_CONSTRAINTS,
                        SHOW_INDEXES, STORE_READ, STORE_CREATE, READ_MARKER, READ_OWNED_NODES, *READ_EDGES.values(), READ_OWNED_EDGES, *NODE_WRITE.values(),
                        *EDGE_WRITE.values(), MARKER_WRITE})


def run(tx, statement: str, **params) -> list[dict]:
    """Execute one registered statement with parameters and consume every row. Anything else is refused before it can reach the server."""
    if statement not in STATEMENTS:
        raise ExtractionFailure("graph_internal_failure")
    return [record.data() for record in tx.run(statement, params)]


# ---------------------------------------------------------------------------------------------- driver / transactions ---------------

def translate(exc: BaseException, write: bool = False) -> ExtractionFailure:
    """A stable code and, at most, a non-secret classification (Neo4j status code / exception class). Messages, URIs and paths are never kept."""
    if isinstance(exc, AuthError):
        return ExtractionFailure("graph_auth_failed")
    if isinstance(exc, Neo4jError):
        return ExtractionFailure("graph_write_failed" if write else "graph_query_failed", {"neo4j": str(exc.code)[:120]})
    if isinstance(exc, (DriverError, OSError)):
        return ExtractionFailure("graph_unavailable", {"driver": type(exc).__name__})
    return ExtractionFailure("graph_internal_failure")


def _quietly(call) -> None:
    try:
        call()
    except Exception:  # noqa: BLE001 - release only; the work's own failure is already in flight or reported
        pass


class Graph:
    def __init__(self, uri: str, database: str, auth: tuple[str, str] | None):
        self.database = database
        try:
            self.driver = GraphDatabase.driver(uri, auth=basic_auth(*auth) if auth else None, connection_timeout=CONNECT_TIMEOUT,
                                               connection_acquisition_timeout=ACQUIRE_TIMEOUT, max_connection_pool_size=POOL,
                                               disable_auto_commit_retries=True, user_agent=USER_AGENT, telemetry_disabled=True)
        except (DriverError, ValueError, OSError) as exc:
            raise translate(exc) from None

    def close(self) -> None:
        _quietly(self.driver.close)

    @contextmanager
    def transaction(self, *, write: bool, metadata: dict | None = None, timeout: float = TX_TIMEOUT, raw: bool = False):
        """One explicit transaction in its own session; leaving the block without a commit rolls it back. With `raw` the driver's own exceptions
        pass through so the caller can classify a commit outcome itself; otherwise they become stable error codes."""
        try:
            session = self.driver.session(database=self.database, default_access_mode=WRITE_ACCESS if write else READ_ACCESS)
            try:
                tx = session.begin_transaction(metadata=metadata, timeout=timeout)
                try:
                    yield tx
                finally:
                    _quietly(tx.close)
            finally:
                _quietly(session.close)
        except (DriverError, Neo4jError, OSError) as exc:
            if raw:
                raise
            raise translate(exc, write) from None


# ---------------------------------------------------------------------------------------------- server identity and schema ----------

def _server(rows: list[dict]) -> dict:
    """Edition and version of a supported (Neo4j 5.x) server."""
    try:
        (row,) = rows
        version = str(row["versions"][0])
        if row["name"] != "Neo4j Kernel" or version.split(".")[0] != "5":
            raise ValueError
        return {"agent": f"Neo4j/{version}", "edition": str(row["edition"])}
    except (ValueError, KeyError, IndexError, TypeError):
        raise ExtractionFailure("graph_server_unsupported") from None


def schema_objects(constraints: list[dict], indexes: list[dict]) -> tuple[dict, dict]:
    """Observed constraints {name: (type, entityType, labelsOrTypes, properties)} and indexes {name: (type, entityType, labelsOrTypes, properties,
    state)}. A LOOKUP index is kept only when it carries a NAME of this schema (it is then a wrong definition of that object); the database's own
    default token-lookup indexes carry other names and are not part of this schema. Any other unexpected index is."""
    return ({r["name"]: (r["type"], r["entityType"], tuple(r["labelsOrTypes"] or ()), tuple(r["properties"] or ())) for r in constraints},
            {r["name"]: (r["type"], r["entityType"], tuple(r["labelsOrTypes"] or ()), tuple(r["properties"] or ()), r["state"]) for r in indexes
             if r["type"] != "LOOKUP" or r["name"] in INDEXES})


def schema_rows(graph: Graph) -> tuple[dict, dict]:
    with graph.transaction(write=False) as tx:
        constraints = run(tx, SHOW_CONSTRAINTS)
    with graph.transaction(write=False) as tx:
        indexes = run(tx, SHOW_INDEXES)
    return schema_objects(constraints, indexes)


def expected_schema() -> tuple[dict, dict]:
    return ({name: (kind, entity, (label,), (prop,)) for name, (kind, entity, label, prop) in CONSTRAINTS.items()},
            {name: ("RANGE", entity, (label,), (prop,), "ONLINE") for name, (entity, label, prop) in INDEXES.items()})


def schema_conflicts(constraints: dict, indexes: dict) -> bool:
    """True when an existing object that carries an EXPECTED NAME has another definition (type, entity, label/type, property; an index may be
    POPULATING or ONLINE, never FAILED). Objects with unexpected names are a different question (not an empty database)."""
    wanted_constraints, wanted_indexes = expected_schema()
    if any(name in wanted_constraints and found != wanted_constraints[name] for name, found in constraints.items()):
        return True
    return any(name in wanted_indexes and (found[:4] != wanted_indexes[name][:4] or found[4] not in {"ONLINE", "POPULATING"}) for name, found in indexes.items())


def probe(graph: Graph) -> dict:
    """What an UNBOUND database contains, for `init`: server, database identity, node/relationship counts, existing schema DEFINITIONS by name and any
    store marker."""
    with graph.transaction(write=False) as tx:
        components, info = run(tx, COMPONENTS), run(tx, DB_INFO)
        nodes, relationships = run(tx, COUNT_NODES)[0]["c"], run(tx, COUNT_RELATIONSHIPS)[0]["c"]
        stores = run(tx, STORE_READ) if nodes <= 1 else []   # only a database holding at most this ledger's own marker can still be adopted
    constraints, indexes = schema_rows(graph)
    if len(info) != 1:
        raise ExtractionFailure("graph_server_unsupported")
    return {"server": _server(components), "dbId": str(info[0]["id"]), "database": str(info[0]["name"]), "nodes": nodes, "relationships": relationships,
            "stores": stores, "constraints": constraints, "indexes": indexes}


def ensure_schema(graph: Graph) -> None:
    """Idempotent DDL (`IF NOT EXISTS`), each statement in its own explicit transaction, then wait for the indexes."""
    for statement in DDL:
        with graph.transaction(write=True) as tx:
            run(tx, statement)
            tx.commit()
    with graph.transaction(write=False) as tx:
        run(tx, AWAIT_INDEXES)


def verify_binding(graph: Graph, binding: dict) -> dict:
    """The database is exactly the one this ledger was initialized against: Neo4j 5, same database id and name, exactly one store marker with this
    ledger's identity, nothing but Zg labels/relationship types, and exactly the expected constraints and ONLINE indexes."""
    with graph.transaction(write=False) as tx:
        components, info, stores = run(tx, COMPONENTS), run(tx, DB_INFO), run(tx, STORE_READ)
        foreign_nodes = run(tx, FOREIGN_NODES, allowed=list(ALLOWED_LABELS))[0]["c"]
        foreign_relationships = run(tx, FOREIGN_RELATIONSHIPS, allowed=list(ALLOWED_RELATIONSHIPS))[0]["c"]
    server = _server(components)
    store = {"slot": STORE_SLOT, "storeId": binding["storeId"], "schema": STORE_SCHEMA, "owner": binding["owner"]}
    if (len(info) != 1 or str(info[0]["id"]) != binding["dbId"] or str(info[0]["name"]).lower() != binding["database"].lower()
            or len(stores) != 1 or stores[0]["l"] != [STORE_LABEL] or stores[0]["p"] != store):
        raise ExtractionFailure("graph_store_identity_mismatch")
    if foreign_nodes or foreign_relationships:
        raise ExtractionFailure("graph_store_foreign_data")
    constraints, indexes = schema_rows(graph)
    if (constraints, indexes) != expected_schema():
        raise ExtractionFailure("graph_store_schema_mismatch")
    return server


def create_store(graph: Graph, binding: dict) -> None:
    """The store marker, in one explicit write transaction, only into a database with no node. A commit whose outcome is unknown is reported as such
    (re-running `init` resumes: the ledger's own intent plus the exact marker are what it adopts)."""
    committing = False
    try:
        with graph.transaction(write=True, raw=True) as tx:
            rows = run(tx, STORE_CREATE, slot=STORE_SLOT, storeId=binding["storeId"], schema=STORE_SCHEMA, owner=binding["owner"])
            if rows != [{"created": 1}]:
                raise ExtractionFailure("graph_store_not_empty")
            committing = True
            tx.commit()
    except ExtractionFailure:
        raise
    except Exception as exc:  # noqa: BLE001 - classified below
        if committing:
            raise ExtractionFailure("graph_commit_unknown") from None
        if isinstance(exc, ConstraintError):
            raise ExtractionFailure("graph_store_not_empty") from None
        raise translate(exc, True) from None


# ---------------------------------------------------------------------------------------------- one version -----------------------------

class Mismatch(Exception):
    """The stored version is not exactly a well formed version: a short reason, never data."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass
class Observed:
    marker: dict
    nodes: list[tuple[str, str]]
    edges: list[tuple[str, str, tuple[str, str], tuple[str, str], dict]]


def owned_data(tx, version_id: str) -> bool:
    """Whether ANYTHING claims this version, under any label or type: a node by `v` or by `version|` key prefix, or a relationship by `v` or key prefix
    wherever it is attached. One row per query, so bounded."""
    prefix = node_key(version_id, "")
    return bool(run(tx, READ_OWNED_NODES, v=version_id, prefix=prefix, cap=1) or run(tx, READ_OWNED_EDGES, v=version_id, prefix=prefix, cap=1))


def presence(tx, version_id: str) -> tuple[list[dict], bool]:
    """(marker rows, whether any version data exists), correct under read-committed isolation (a read transaction is not a snapshot).

    A version is written by ONE atomic, append-only transaction (nodes, edges and marker), so committed data always comes with its marker. Order: marker,
    then the data, then the marker AGAIN when the first read found none. A commit that became visible in between is therefore seen as a marker, never as
    'data without marker'; data whose final marker read is still absent is damage (a valid commit writes both atomically)."""
    markers = run(tx, READ_MARKER, v=version_id)
    data = owned_data(tx, version_id)
    if not markers:
        markers = run(tx, READ_MARKER, v=version_id)
    return markers, data


def _edge(version_id: str, row: dict, nodes: dict) -> tuple:
    name = TYPE_OF_RELATIONSHIP.get(row["t"])
    if name is None:
        raise Mismatch("edge_type")
    spec = EDGE_SPECS[name]
    try:
        props = observed_props(version_id, row["p"])
        start, end = split_key(version_id, row["svk"]), split_key(version_id, row["evk"])
    except ValueError:
        raise Mismatch("edge_shape") from None   # a relationship of another version, or one with a foreign key/owner, attached here or claiming this version
    if row["sl"] != [LABELS[spec.subject]] or row["el"] != [LABELS[spec.object]]:
        raise Mismatch("edge_labels")
    edge = (name, props["id"], (LABELS[spec.subject], start), (LABELS[spec.object], end), props)
    if edge[2] not in nodes or edge[3] not in nodes:
        raise Mismatch("edge_endpoint")
    return edge


def observe(tx, version_id: str) -> Observed:
    """The ACTUAL stored version: one marker with exactly the marker keys; every node that claims the version by `v` OR by key prefix under ANY label
    (exactly one data label, keys, `version|id` round-trip, owner); every relationship attached to those nodes OR claiming the version anywhere (type,
    keys, owner, endpoint labels, endpoints that are this version's nodes). Every query is bounded, and the marker is read again at the end (it must be
    unchanged). Extra, missing or altered elements are not detected here but by comparing the returned content digest with the planned one."""
    prefix = node_key(version_id, "")
    markers = run(tx, READ_MARKER, v=version_id)
    if len(markers) != 1:
        raise Mismatch("marker")
    marker = markers[0]
    if marker["l"] != [VERSION_LABEL] or not isinstance(marker["p"], dict) or set(marker["p"]) != MARKER_KEYS:
        raise Mismatch("marker_shape")
    rows = run(tx, READ_OWNED_NODES, v=version_id, prefix=prefix, cap=MAX_NODES + 1)
    if len(rows) > MAX_NODES:
        raise Mismatch("node_cap")
    nodes: set[tuple[str, str]] = set()
    for row in rows:
        labels, props = row["l"], row["p"]
        if (len(labels) != 1 or labels[0] not in DATA_LABELS or not isinstance(props, dict) or set(props) != NODE_KEYS
                or props["v"] != version_id):
            raise Mismatch("node_shape")
        try:
            ident = split_key(version_id, props["vk"])
        except ValueError:
            raise Mismatch("node_key") from None
        if props["id"] != ident or (labels[0], ident) in nodes:
            raise Mismatch("node_key")
        nodes.add((labels[0], ident))
    seen: dict[str, tuple] = {}
    ids: set[tuple[str, str]] = set()
    for rows in (run(tx, READ_OWNED_EDGES, v=version_id, prefix=prefix, cap=MAX_EDGES + 1),
                 *(run(tx, READ_EDGES[label], v=version_id, cap=MAX_EDGES + 1) for label in LABELS.values())):
        if len(rows) > MAX_EDGES:
            raise Mismatch("edge_cap")
        for row in rows:
            edge = _edge(version_id, row, nodes)
            if seen.setdefault(row["eid"], edge) != edge:
                raise Mismatch("edge_inconsistent")
    for edge in seen.values():
        if (edge[0], edge[1]) in ids:
            raise Mismatch("edge_duplicate")
        ids.add((edge[0], edge[1]))
    if len(seen) > MAX_EDGES:
        raise Mismatch("edge_cap")
    if run(tx, READ_MARKER, v=version_id) != markers:
        raise Mismatch("marker_changed")
    return Observed(marker["p"], list(nodes), list(seen.values()))


def write_nodes(tx, version_id: str, label: str, ids: list[str]) -> None:
    if run(tx, NODE_WRITE[label], v=version_id, ids=ids) != [{"c": len(ids)}]:
        raise ExtractionFailure("graph_write_mismatch")


def write_edges(tx, version_id: str, name: str, rows: list[dict]) -> None:
    """rows: [{"subject": id, "object": id, "props": stored property map}]. A row whose endpoint does not match is silently dropped by Cypher, so the
    returned count is compared with the number of rows."""
    if run(tx, EDGE_WRITE[name], v=version_id, rows=rows) != [{"c": len(rows)}]:
        raise ExtractionFailure("graph_write_mismatch")


def write_marker(tx, marker: dict) -> None:
    rows = run(tx, MARKER_WRITE, v=marker["versionId"], schema=marker["schema"], storeId=marker["storeId"], payload=marker["payloadDigest"],
               graph=marker["graphDigest"], nodes=marker["nodeCount"], edges=marker["edgeCount"])
    if rows != [{"c": 1}]:
        raise ExtractionFailure("graph_write_mismatch")
