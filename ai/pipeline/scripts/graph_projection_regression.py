#!/usr/bin/env python3
"""Tests-first regressions for the independent review findings R1-R4 of the nonpublic S3 -> Neo4j version projection, against a REAL Neo4j 5 database.

Every case below describes the REQUIRED behavior. Against the code as reviewed they are expected to be RED (each prints what it observed instead);
a green case means the required behavior holds. The findings:

  R1  cross-version owned relationships/nodes are invisible to the claimed version (read/focus, recover, and absence checks of project); r1e: so is data
      claimed under a NON-data label (a ZgVersion-labelled node carrying v/vk but no versionId passes every allowed-label check)
  R2  a commit that becomes visible BETWEEN the two presence queries (read-committed isolation) must not burn the version as corrupt
  R3  an existing schema object with an expected NAME but another DEFINITION must be refused before any DDL, store marker or ledger binding; r3c: also a
      token LOOKUP index (the projection defines none) that takes an expected name
  R4  `focus` must report a path-intermediate company that is a node of the verified version as found, without synthetic path-step edges

Needs a running, EMPTY, dedicated Neo4j 5 database that this script may use (it fails, never skips; use a database other than the smoke's):
    ZOOP_GRAPH_REGRESSION_URI=bolt://127.0.0.1:<port>   ZOOP_GRAPH_AUTH=none|basic [ZOOP_GRAPH_USER / ZOOP_GRAPH_PASSWORD]
    [ZOOP_GRAPH_REGRESSION_DATABASE=neo4j]
    ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_projection_regression.py [--cases r1a,r2a,...] [--run-id BASE]
    ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_projection_regression.py --cleanup BASE      # exact, by run id; never a global wipe

One store per database is possible, so every case gets its own run id (`BASE<case>`), initializes its own store, and afterwards removes ONLY what carries
that run id (version nodes by `v` prefix, version markers by `versionId` prefix, its store marker by its exact store ID) plus the projection schema objects
by their exact names. A case refuses to start, and the script stops, unless the database is pristine (no node, no relationship, no constraint, no index
except the default lookup indexes), and the same check runs after each cleanup: a user's data is never touched or wiped.
Exit 0 only when every selected case is green; 1 when any case is red (defect reproduced) or errored (harness problem, reported separately).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE)]

from neo4j import WRITE_ACCESS  # noqa: E402

from scripts.graph_projection_smoke import Operator, Raw, build_relations, expected_two, read_matches  # noqa: E402
from scripts.relation_smoke import build_world  # noqa: E402
from zoop_ai_pipeline import graph_neo4j as neo  # noqa: E402
from zoop_ai_pipeline import graph_projection as gp  # noqa: E402
from zoop_ai_pipeline.graph_projection_contracts import ExtractionFailure, Selector, marker_props  # noqa: E402

SCHEMA = "zoop-graph-projection-1"
# The projection's schema objects, by exact name (hand-written, not imported): the only schema this script ever drops, and only after its own case.
CONSTRAINTS = ("zg_store_slot", "zg_version_id", "zg_company_vk", "zg_event_vk", "zg_topic_vk", "zg_supplies_vk", "zg_invests_in_vk", "zg_competes_with_vk",
               "zg_participates_in_vk", "zg_relates_to_topic_vk")
INDEXES = ("zg_company_v", "zg_event_v", "zg_topic_v")
REFUSED_BEFORE_ANY_WRITE = {"graph_store_schema_mismatch", "graph_store_not_empty"}


class CaseOperator(Operator):
    """The smoke's operator, bound to one ledger directory per case."""

    def __init__(self, world, uri: str, database: str, run: str, ledger: str):
        super().__init__(world, uri, database, run)
        self.ledger_name = ledger

    def graph(self, command: str, request: dict, **kw):
        kw.setdefault("state", self.ledger_name)
        return super().graph(command, request, **kw)

    def ledger(self, state: str | None = None) -> str:
        return super().ledger(state or self.ledger_name)


# ---------------------------------------------------------------- harness ------------------------------------------------------------

def step(report: dict, label: str, call) -> None:
    """One required behavior. An AssertionError is a reproduced defect (red); any other exception is a harness error and aborts the case."""
    try:
        call()
    except AssertionError as exc:
        report["red"].append(f"{label}: {str(exc)[:1200]}")


def auth():
    return None if os.environ["ZOOP_GRAPH_AUTH"] == "none" else (os.environ["ZOOP_GRAPH_USER"], os.environ["ZOOP_GRAPH_PASSWORD"])


def pristine(raw: Raw) -> bool:
    return (raw.count("MATCH (n) RETURN count(n) AS c") == 0 and raw.count("MATCH ()-[r]->() RETURN count(r) AS c") == 0
            and not raw.q("SHOW CONSTRAINTS YIELD name") and not [r for r in raw.q("SHOW INDEXES YIELD name, type") if r["type"] != "LOOKUP"])


def cleanup(raw: Raw, run: str) -> None:
    """Only what carries this run id, and the projection schema by exact name. Nothing else is ever deleted."""
    prefix = f"{run}-"
    raw.q("MATCH (n) WHERE n.v STARTS WITH $p DETACH DELETE n", p=prefix)
    raw.q("MATCH (m:ZgVersion) WHERE m.versionId STARTS WITH $p DELETE m", p=prefix)
    raw.q("MATCH (s:ZgStore {storeId: $s}) DELETE s", s=f"{run}-store")
    for name in CONSTRAINTS:
        raw.q(f"DROP CONSTRAINT {name} IF EXISTS")
    for name in INDEXES:
        raw.q(f"DROP INDEX {name} IF EXISTS")


def init(op: CaseOperator, database: str) -> None:
    out = op.graph("init", {"schemaVersion": SCHEMA, "storeId": f"{op.run}-store", "database": database})
    assert out["store"]["state"] == "bound", out


def stage(op: CaseOperator, name: str, job: str) -> None:
    op.freeze(name, job)
    assert op.graph("project", op.sel(name))["state"] == "ready"


def plant_owned_edge(raw: Raw, owner: str, carrier: str) -> None:
    """A relationship that CLAIMS version `owner` (v and vk) but sits entirely between two nodes of version `carrier`: every uniqueness constraint and
    label/type check allows it."""
    raw.q("MATCH (a:ZgCompany {vk: $a}) WITH a MATCH (b:ZgCompany {vk: $b}) "
          "CREATE (a)-[:ZG_SUPPLIES {vk: $k, v: $v, id: 'rel-extra', direction: 'directed', connection: 'direct'}]->(b)",
          a=f"{carrier}|kr-000300", b=f"{carrier}|kr-000100", k=f"{owner}|rel-extra", v=owner)


def stored_plan(op: CaseOperator, name: str) -> tuple[dict, str, str]:
    db = sqlite3.connect((op.root / op.ledger_name / "graph.sqlite3").as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        plan, payload, graph = db.execute("SELECT plan, payload_digest, graph_digest FROM versions WHERE version_id=?", (op.vid(name),)).fetchone()
        return json.loads(plan), payload, graph
    finally:
        db.close()


class Staged:
    """A complete valid version written by a REAL driver transaction that stays uncommitted until `commit()`: the 'original' server transaction of an
    unknown commit that completes late. Uses the production writer statements; it is the test's stand-in for a late-completing commit, not an oracle."""

    def __init__(self, op: CaseOperator, name: str, uri: str, database: str):
        plan, payload, graph = stored_plan(op, name)
        self.graph = neo.Graph(uri, database, auth())
        self.session = self.graph.driver.session(database=database, default_access_mode=WRITE_ACCESS)
        self.tx = self.session.begin_transaction(timeout=120)
        self.committed = False
        gp.Projector(None)._writes(self.tx, plan, marker_props(plan, f"{op.run}-store", payload, graph))

    def commit(self) -> None:
        self.tx.commit()
        self.committed = True

    def close(self) -> None:
        if not self.committed:
            self.tx.close()
        self.session.close()
        self.graph.close()


@contextmanager
def late_commit_after_marker_read(version_id: str, action):
    """Real read-committed interleaving: the first time the marker query of this version returns NOTHING, `action` (a real commit on another connection)
    runs before the caller's next statement. The hook sits on the statement executor, not inside any presence/observe implementation."""
    original, fired = neo.run, {"count": 0}

    def run(tx, statement, **params):
        rows = original(tx, statement, **params)
        if statement == neo.READ_MARKER and params.get("v") == version_id and not rows and not fired["count"]:
            fired["count"] += 1
            action()
        return rows

    with mock.patch.object(neo, "run", run):
        yield fired


def projector(op: CaseOperator) -> tuple[gp.Store, gp.Projector]:
    relation, extraction, ingestion = op.root / "relation", op.root / "extraction", op.root / "ingestion"
    store = gp.Store(op.root / op.ledger_name, relation, extraction, ingestion, mode="write")
    return store, gp.Projector(store, gp.Paths(relation, extraction, ingestion, op.kit.registry_path, op.canonical))


# ---------------------------------------------------------------- R1: cross-version ownership --------------------------------------

def r1a(op, raw, report, uri, database):
    """A ready version A is read/focused while a relationship claiming A is attached to ANOTHER version's nodes: it must be withheld as corrupt."""
    init(op, database)
    stage(op, "carrier", "rel-two")
    stage(op, "A", "rel-two")
    read_matches(op.graph("read", op.sel("A")), expected_two(op.world, op.jobs), op, "A")   # baseline: green before the corruption
    plant_owned_edge(raw, op.vid("A"), op.vid("carrier"))
    step(report, "read A with a cross-version owned relationship", lambda: op.withheld(op.graph("read", op.sel("A"), expected=2), "A", "graph_version_corrupt"))
    step(report, "focus A with a cross-version owned relationship",
         lambda: op.withheld(op.graph("focus", {**op.sel("A"), "companyId": "kr-000100", "depth": 2}, expected=2), "A", "graph_version_corrupt"))


def r1b(op, raw, report, uri, database):
    """Reconciling an unknown commit must not confirm a version while a relationship claiming it hangs off another version: failed corrupt."""
    init(op, database)
    stage(op, "carrier", "rel-two")
    op.freeze("U", "rel-two")
    op.error(op.graph("project", op.sel("U"), hook="unknown-committed", expected=2), "graph_commit_unknown")
    plant_owned_edge(raw, op.vid("U"), op.vid("carrier"))

    def recovered():
        out = op.graph("recover", op.sel("U"))
        assert out["state"] == "failed" and out["failure"]["code"] == "graph_version_corrupt", (out["state"], out["failure"])

    step(report, "recover U with a cross-version owned relationship", recovered)


def r1c(op, raw, report, uri, database):
    """Version data without a marker or nodes (a surviving owned relationship) is data: project must not write over it."""
    init(op, database)
    stage(op, "carrier", "rel-two")
    op.freeze("W", "rel-two")
    plant_owned_edge(raw, op.vid("W"), op.vid("carrier"))

    def refused():
        op.error(op.graph("project", op.sel("W"), expected=2), "graph_version_corrupt")
        assert op.state("W")["state"] == "failed" and not raw.q("MATCH (m:ZgVersion {versionId: $v}) RETURN m", v=op.vid("W"))

    step(report, "project W with a surviving owned relationship and no marker/nodes", refused)


def r1d(op, raw, report, uri, database):
    """A node whose key claims version A but whose v is another version is not invisible either."""
    init(op, database)
    stage(op, "carrier", "rel-two")
    stage(op, "A", "rel-two")
    raw.q("CREATE (:ZgCompany {vk: $vk, v: $v, id: 'ghost'})", vk=f"{op.vid('A')}|ghost", v=op.vid("carrier"))
    step(report, "read A with a node whose vk claims A but whose v is another version",
         lambda: op.withheld(op.graph("read", op.sel("A"), expected=2), "A", "graph_version_corrupt"))


def r1e(op, raw, report, uri, database):
    """Version data under a label that is not a data label: a ZgVersion-labelled node (the MARKER label) with v/vk/id but no versionId claims the version
    like a data node does. It is neither the marker nor allowed data, so it must make the version corrupt wherever the version is checked."""
    init(op, database)
    stage(op, "A", "rel-two")
    raw.q("CREATE (:ZgVersion {v: $v, vk: $vk, id: 'extra'})", v=op.vid("A"), vk=f"{op.vid('A')}|extra")
    step(report, "read A with a marker-labelled node claiming A", lambda: op.withheld(op.graph("read", op.sel("A"), expected=2), "A", "graph_version_corrupt"))
    step(report, "focus A with a marker-labelled node claiming A",
         lambda: op.withheld(op.graph("focus", {**op.sel("A"), "companyId": "kr-000100", "depth": 1}, expected=2), "A", "graph_version_corrupt"))
    op.freeze("W", "rel-two")
    raw.q("CREATE (:ZgVersion {v: $v, vk: $vk, id: 'extra'})", v=op.vid("W"), vk=f"{op.vid('W')}|extra")

    def refused():
        op.error(op.graph("project", op.sel("W"), expected=2), "graph_version_corrupt")
        assert op.state("W")["state"] == "failed" and not raw.q("MATCH (m:ZgVersion {versionId: $v}) RETURN m", v=op.vid("W"))

    step(report, "project W while a marker-labelled node claims W (no marker, no data-label nodes)", refused)


# ---------------------------------------------------------------- R2: late commit between presence reads ------------------------

def settle_checks(op, report, name: str) -> None:
    step(report, f"{name} is not burned as failed", lambda: _not_failed(op, name))


def _not_failed(op, name: str) -> None:
    state = op.state(name)
    assert state["state"] != "failed", (state["state"], state["failure"])
    if state["state"] == "ready":
        read_matches(op.graph("read", op.sel(name)), expected_two(op.world, op.jobs), op, name)


def r2a(op, raw, report, uri, database):
    """recover: the marker query finds nothing, then the ORIGINAL transaction commits the full valid version, then the node query runs."""
    init(op, database)
    op.freeze("V", "rel-two")
    op.error(op.graph("project", op.sel("V"), hook="unknown-uncommitted", expected=2), "graph_commit_unknown")
    assert op.state("V")["state"] == "unknown" and not raw.nodes_of(op.vid("V"))
    staged = Staged(op, "V", uri, database)
    store, proj = projector(op)
    try:
        with late_commit_after_marker_read(op.vid("V"), staged.commit) as fired:
            try:
                result = proj.recover(Selector.model_validate(op.sel("V")))
            except ExtractionFailure as exc:
                report["red"].append(f"recover V raised {exc.code}")
                result = None
        step(report, "the interleaving was actually forced", lambda: _assert(fired["count"] == 1, "the marker query never ran empty: the barrier was not reached"))
        step(report, "recover V did not burn the version", lambda: _assert(result is not None and result["state"] != "failed", result and (result["state"], result["failure"])))
    finally:
        store.close()
        staged.close()
    settle_checks(op, report, "V")


def r2b(op, raw, report, uri, database):
    """project's guard: the marker query finds nothing, the original transaction commits, the node query then sees data: that is an UNKNOWN commit."""
    init(op, database)
    op.freeze("V", "rel-two")
    staged = Staged(op, "V", uri, database)
    store, proj = projector(op)
    raised = None
    try:
        with late_commit_after_marker_read(op.vid("V"), staged.commit) as fired:
            try:
                proj.project(Selector.model_validate(op.sel("V")))
            except ExtractionFailure as exc:
                raised = exc.code
        step(report, "the interleaving was actually forced", lambda: _assert(fired["count"] == 1, "the marker query never ran empty: the barrier was not reached"))
    finally:
        store.close()
        staged.close()
    step(report, "project guard classifies a newly visible commit as unknown, not corrupt", lambda: _assert(raised == "graph_commit_unknown", raised))
    settle_checks(op, report, "V")


def _assert(condition, message) -> None:
    assert condition, message


# ---------------------------------------------------------------- R3: schema definition preflight --------------------------------

def _schema_names(raw: Raw, lookups: bool) -> tuple[set, set]:
    """Constraint names and index names; token LOOKUP indexes only when the case plants one (the default ones exist on every database)."""
    return ({r["name"] for r in raw.q("SHOW CONSTRAINTS YIELD name")},
            {r["name"] for r in raw.q("SHOW INDEXES YIELD name, type") if lookups or r["type"] != "LOOKUP"})


def _r3(op, raw, report, plant: str | None, expected_names: tuple[set, set] | None, lookups: bool = False) -> None:
    if plant:
        raw.q(plant)
    pre = _schema_names(raw, lookups)
    assert expected_names is None or pre == expected_names, pre
    expected_names = pre

    def refused():
        out = op.graph("init", {"schemaVersion": SCHEMA, "storeId": f"{op.run}-store", "database": os.environ.get("ZOOP_GRAPH_REGRESSION_DATABASE", "neo4j")}, expected=2)
        assert out["error"]["code"] in REFUSED_BEFORE_ANY_WRITE, out

    def unchanged_database():
        now = _schema_names(raw, lookups)
        assert now == expected_names, f"DDL was sent: {now}"
        assert raw.count("MATCH (n) RETURN count(n) AS c") == 0, "a node (the store marker) was created"

    def unbound_ledger():
        path = op.root / op.ledger_name / "graph.sqlite3"
        if not path.exists():
            return   # nothing was created at all: certainly not bound
        db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            keys = [row[0] for row in db.execute("SELECT key FROM meta ORDER BY key")]
        finally:
            db.close()
        assert keys == ["ledger"], f"the ledger was bound before the refusal: {keys}"

    step(report, "init is refused", refused)
    step(report, "no DDL and no store marker reached the database", unchanged_database)
    step(report, "no local binding was committed", unbound_ledger)


def r3a(op, raw, report, uri, database):
    """An existing CONSTRAINT with an expected name but another label/property."""
    _r3(op, raw, report, "CREATE CONSTRAINT zg_company_vk IF NOT EXISTS FOR (n:ZgOther) REQUIRE n.other IS UNIQUE", ({"zg_company_vk"}, {"zg_company_vk"}))


def r3b(op, raw, report, uri, database):
    """An existing INDEX with an expected name but another label/property."""
    _r3(op, raw, report, "CREATE INDEX zg_company_v IF NOT EXISTS FOR (n:ZgOther) ON (n.other)", (set(), {"zg_company_v"}))


def r3c(op, raw, report, uri, database):
    """A token LOOKUP index that takes an expected name (the projection never defines a LOOKUP): a non-RANGE index must not hide behind the
    schema_rows filter. A database allows one node LOOKUP, so the default one is replaced for the case and restored after it (cleanup drops
    only the planted name; the restore recreates the default under its own name)."""
    defaults = [r["name"] for r in raw.q("SHOW INDEXES YIELD name, type, entityType") if r["type"] == "LOOKUP" and r["entityType"] == "NODE"]
    assert len(defaults) == 1 and re.fullmatch(r"\w+", defaults[0]), defaults
    original = defaults[0]
    raw.q(f"DROP INDEX `{original}`")
    try:
        raw.q("CREATE LOOKUP INDEX zg_company_vk FOR (n) ON EACH labels(n)")
        planted = {r["name"]: r["type"] for r in raw.q("SHOW INDEXES YIELD name, type")}
        assert planted.get("zg_company_vk") == "LOOKUP", planted
        _r3(op, raw, report, None, None, lookups=True)
    finally:
        raw.q("DROP INDEX zg_company_vk IF EXISTS")
        raw.q(f"CREATE LOOKUP INDEX `{original}` IF NOT EXISTS FOR (n) ON EACH labels(n)")


# ---------------------------------------------------------------- R4: focus presence ----------------------------------------------

def r4(op, raw, report, uri, database):
    """rel-path: kr-000300 -> kr-000050 through the intermediate kr-000100. The intermediate company is a node of the verified version."""
    init(op, database)
    stage(op, "P", "rel-path")
    nodes = sorted(row["p"]["id"] for row in raw.q("MATCH (n:ZgCompany) WHERE n.v = $v RETURN properties(n) AS p", v=op.vid("P")))
    assert nodes == ["kr-000050", "kr-000100", "kr-000300"], nodes   # the intermediate is stored

    def intermediate_present():
        for depth in (1, 2, 3):
            out = op.graph("focus", {**op.sel("P"), "companyId": "kr-000100", "depth": depth})
            assert out["focus"] == {"companyId": "kr-000100", "depth": depth, "found": True}, out["focus"]
            assert out["graph"] == {"nodes": [{"kind": "company", "id": "kr-000100", "distance": 0}], "edges": []} and out["evidence"] == [], out["graph"]

    def endpoint_has_no_synthetic_step_edges():
        out = op.graph("focus", {**op.sel("P"), "companyId": "kr-000300", "depth": 3})
        assert {n["id"]: n["distance"] for n in out["graph"]["nodes"]} == {"kr-000300": 0, "kr-000050": 1}, out["graph"]["nodes"]
        assert [(e["subject"]["id"], e["object"]["id"], e["connection"]) for e in out["graph"]["edges"]] == [("kr-000300", "kr-000050", "indirect")], out["graph"]["edges"]

    step(report, "a path-intermediate company is found, alone at distance 0, with no edges", intermediate_present)
    step(report, "no synthetic path-step edges appear around the endpoints", endpoint_has_no_synthetic_step_edges)


CASES = {"r1a": r1a, "r1b": r1b, "r1c": r1c, "r1d": r1d, "r1e": r1e, "r2a": r2a, "r2b": r2b, "r3a": r3a, "r3b": r3b, "r3c": r3c, "r4": r4}


def cleanup_only(uri: str, database: str, base: str) -> dict:
    raw = Raw(uri, database)
    try:
        for key in CASES:
            cleanup(raw, f"{base}{key}")
        return {"status": "cleaned", "base": base, "pristine": pristine(raw)}
    finally:
        raw.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", default=",".join(CASES), help="comma separated subset of: " + ",".join(CASES))
    parser.add_argument("--run-id", default=f"reg{uuid.uuid4().hex[:8]}")
    parser.add_argument("--cleanup", metavar="BASE")
    args = parser.parse_args()
    uri, database = os.environ.get("ZOOP_GRAPH_REGRESSION_URI"), os.environ.get("ZOOP_GRAPH_REGRESSION_DATABASE", "neo4j")
    if not uri or os.environ.get("ZOOP_GRAPH_AUTH") not in {"none", "basic"}:
        raise SystemExit("ZOOP_GRAPH_REGRESSION_URI and ZOOP_GRAPH_AUTH (none|basic, plus ZOOP_GRAPH_USER/ZOOP_GRAPH_PASSWORD) are required: this script does not skip")
    if args.cleanup:
        print(json.dumps(cleanup_only(uri, database, args.cleanup), indent=2))
        return 0
    selected = [c.strip() for c in args.cases.split(",") if c.strip()]
    unknown = [c for c in selected if c not in CASES]
    if unknown:
        raise SystemExit(f"unknown cases: {unknown}")
    print(f"run id base: {args.run_id} (targeted recovery: --cleanup {args.run_id})", file=sys.stderr)
    raw, results = Raw(uri, database), []
    try:
        if not pristine(raw):
            raise SystemExit("the Neo4j database is not pristine: this script needs its own empty database and never wipes one (use a fresh container, or --cleanup <base>)")
        with tempfile.TemporaryDirectory(prefix="zoop-graph-regression-") as temporary:
            root = Path(temporary).resolve()
            world = build_world(root)
            jobs = build_relations(world, process=False, only=("rel-two", "rel-path"))
            for key in selected:
                run = f"{args.run_id}{key}"
                report = {"case": key, "runId": run, "red": [], "error": None}
                op = CaseOperator(world, uri, database, run, f"graph-{key}")
                op.jobs = jobs
                try:
                    CASES[key](op, raw, report, uri, database)
                except Exception as exc:  # noqa: BLE001 - a harness/setup problem, reported apart from reproduced defects
                    report["error"] = f"{type(exc).__name__}: {str(exc)[:1500]}"
                finally:
                    cleanup(raw, run)
                results.append(report)
                if not pristine(raw):
                    print(json.dumps({"stopped": f"cleanup of {run} left residue; refusing to continue", "results": results}, ensure_ascii=False, indent=2))
                    return 1
    finally:
        raw.close()
    summary = {"cases": [{"case": r["case"], "status": "error" if r["error"] else "red" if r["red"] else "green", "red": r["red"], "error": r["error"]} for r in results]}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(c["status"] == "green" for c in summary["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
