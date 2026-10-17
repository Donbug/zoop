#!/usr/bin/env python3
"""Actual ingestion + S2 + S3 world -> `zoop-ai-graph` subprocesses against a REAL, dedicated, EMPTY Neo4j 5 database.

Needs a running Neo4j that nothing else uses (this smoke fails, never skips, without it):
    ZOOP_GRAPH_SMOKE_URI=bolt://127.0.0.1:<port>   ZOOP_GRAPH_AUTH=none|basic [ZOOP_GRAPH_USER / ZOOP_GRAPH_PASSWORD]
    [ZOOP_GRAPH_SMOKE_DATABASE=neo4j]
    ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_projection_smoke.py [--run-id ID]
    ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_projection_smoke.py --cleanup ID    # targeted recovery by name, never a global wipe

Replay is authored-response replay: no model, no provider, no original PoC state, no network except the one Neo4j socket (every CLI subprocess runs
under an audit hook that aborts any other socket use). Every expectation below is written by hand from the authored world, never derived from the
planner or the reader under test. The smoke removes only what it planted itself, by exact identity; the throwaway database is disposed by its owner.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE)]

from scripts.ingestion_smoke import json_bytes, ownership_env  # noqa: E402
from scripts.relation_smoke import (BAD, CO, COMP, EVT, GOOD, INV, QB, SUP, SUP2, VALID, build_world, co, converge, ev, find, impact_item, proposal, step,  # noqa: E402
                                    tp, tree, world_cite)
from zoop_ai_pipeline.ingestion_contracts import digest  # noqa: E402

SCHEMA = "zoop-graph-projection-1"
CANONICAL_SCHEMA = "zoop-graph-canonical-1"
CUSTOM = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
SOURCED = {"freeze", "project", "read", "focus"}
EDGE_KEYS = ("id", "direction", "connection", "businessScope", "productScope", "validFrom", "validUntil", "countries", "pathCompanyIds", "evidenceIds",
             "validityEvidenceIds", "step1EvidenceIds", "step2EvidenceIds", "sourceRelationCandidateIds")
LISTS = {"countries", "pathCompanyIds", "evidenceIds", "validityEvidenceIds", "step1EvidenceIds", "step2EvidenceIds", "sourceRelationCandidateIds"}
# Source text, titles, URLs and review/model text that must NEVER appear in any graph command output.
PRIVATE = (SUP, SUP2, COMP, INV, VALID, CO, EVT, GOOD, BAD, QB, "합성 공급 계약", "합성 공장 착공", "example.invalid", "authored producer reason", "operator-a",
           "authored review")
WITHHELD_KEYS = {"schemaVersion", "versionId", "state", "publication", "delivery", "usage"}


def trust_env() -> dict[str, str]:
    """The ONE trust variable a graph CLI child receives: `SSL_CERT_FILE`, the public CA file of a private-CA `bolt+s` target, exactly as an operator
    passes it per command. Nothing else (no SSL_CERT_DIR, no generic secret or proxy environment) is forwarded."""
    return {"SSL_CERT_FILE": os.environ["SSL_CERT_FILE"]} if os.environ.get("SSL_CERT_FILE") else {}


CREDENTIAL_KEYS = frozenset({"user", "username", "password", "passwd", "auth", "authorization", "credential", "credentials", "secret", "token", "uri", "graphuri", "owner"})


def assert_no_credential_leak(text: str, database: str) -> None:
    """No password anywhere in one command output, no credential-shaped field, and the user name only where it IS a legitimate constant of the answer.
    On Community the only user is `neo4j`, the same word as the database name (`"database":"neo4j"`) and, case-insensitively, the server agent prefix
    (`Neo4j/5.x`): a plain substring test would fail on those constants, so the user name is checked outside exactly those two positions."""
    password, user = os.environ.get("ZOOP_GRAPH_PASSWORD"), os.environ.get("ZOOP_GRAPH_USER")
    assert not password or password not in text, "password echoed"
    if not text:
        return

    def walk(value, key: str | None = None) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                assert k.lower() not in CREDENTIAL_KEYS, f"credential-shaped field {k!r}"
                walk(v, k)
        elif isinstance(value, list):
            for v in value:
                walk(v, key)
        elif isinstance(value, str) and user:
            legitimate = (key == "database" and value.lower() == database.lower()) or (key == "agent" and value.startswith("Neo4j/"))
            assert legitimate or user.lower() not in value.lower(), "user name echoed outside its legitimate constants"

    walk(json.loads(text))


# ---------------------------------------------------------------- the authored world (also used by the unit tests) -----------------

def mapping(world) -> dict:
    """The operator's canonical decisions. Two S3 event endpoints (a produced event candidate and a snapshot event) deliberately decide ONE canonical
    event; SYNTH-2 sorts before SYNTH-1 by canonical ID, so the symmetric competition pair is reversed against S3's own order."""
    return {("company", "SYNTH-1"): "kr-000100", ("company", "SYNTH-2"): "kr-000050", ("company", "SYNTH-3"): "kr-000300", ("company", "SYNTH-4"): "kr-000400",
            ("event", world.evc): "event:main-event", ("event", world.event): "event:main-event", ("topic", world.tp): "topic:ev-supply-chain"}


def registry(world, decisions: dict | None = None, decision: str = "decision-2026-10-15") -> dict:
    upstream = {"jobId": world.s2["jobId"], "inputDigest": world.s2["inputDigest"]}
    return {"schemaVersion": CANONICAL_SCHEMA,
            "entries": [{"upstream": upstream, "kind": kind, "ref": ref, "canonicalId": cid, "decisionRef": f"{decision}:{kind}"}
                        for (kind, ref), cid in sorted((mapping(world) if decisions is None else decisions).items())]}


def cites(world):
    return lambda text, nth=0: world_cite(world, "main", text, nth)


def p_supplies(world):
    return proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [cites(world)(SUP)], product="배터리 부품")


def p_indirect(world):
    c = cites(world)
    return proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-2"), [], connection="indirect", product="부품",
                    path=[step("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(SUP)]), step("SUPPLIES", co("SYNTH-1"), co("SYNTH-2"), [c(SUP2)])])


def p_hold(world):
    return proposal("SHARES_ISSUE", co("SYNTH-1"), co("SYNTH-2"), [cites(world)(CO)])


def proposals_main(world) -> list:
    """Seven eligible relations over all five types (one a two-step path, one a reversed symmetric pair, one dated, two event endpoints that merge),
    one HOLD (not a relationship proof) and one REJECT (an event ID spelled as a topic)."""
    c = cites(world)
    return [p_supplies(world), p_indirect(world),
            proposal("COMPETES_WITH", co("SYNTH-2"), co("SYNTH-1"), [c(COMP)], business="전기차 시장"),
            proposal("INVESTS_IN", co("SYNTH-4"), co("SYNTH-3"), [c(INV)], validity={"from": "2026-01-01", "until": "2026-12-31", "citations": [c(VALID)]}),
            proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(world.evc), [c(EVT)]),
            proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(world.event), [world_cite(world, "b", QB)]),
            proposal("RELATES_TO_TOPIC", co("SYNTH-1"), tp(world.tp), [c(EVT)]),
            p_hold(world),
            proposal("RELATES_TO_TOPIC", co("SYNTH-1"), tp(world.event), [c(EVT)])]


def proposals_two(world) -> list:
    return [p_supplies(world), proposal("INVESTS_IN", co("SYNTH-4"), co("SYNTH-3"), [cites(world)(INV)])]


def impacts(world):
    c = cites(world)

    def make(r: dict):
        if r["type"] == "SUPPLIES" and r["subject"]["ref"] == "SYNTH-3" and r["object"]["ref"] == "SYNTH-1" and r["connection"] == "direct":
            return [impact_item("SYNTH-1", "positive", [c(GOOD)], [c(BAD)])]
        if r["type"] == "COMPETES_WITH":
            return [impact_item("SYNTH-1", "positive", [c(GOOD)], [])]
        return []
    return make


def effects(_impact: dict) -> dict:
    return {GOOD: "positive", BAD: "negative"}


def build_relations(world, *, process: bool, only: tuple[str, ...] | None = None) -> dict:
    """S3 jobs over the one S2 upstream, through the existing relation CLI (process=True) or the same engine in-process."""
    spec = {"rel-main": proposals_main(world), "rel-two": proposals_two(world), "rel-path": [p_indirect(world)], "rel-empty": [p_hold(world)],
            "rel-review": [p_supplies(world), p_hold(world)]}
    jobs = {}
    for job, proposals in spec.items():
        if only is not None and job not in only:
            continue
        jobs[job] = converge(world, job, proposals, impacts=impacts(world) if job == "rel-main" else None, effects=effects if job == "rel-main" else None, process=process)
        assert jobs[job]["state"] == "ready", (job, jobs[job].get("failure"))
    return jobs


def evidence_id(world, name: str, text: str) -> str:
    """The S2-published evidence identity formula, applied to the authored coordinates (not read back from any graph output)."""
    c = world_cite(world, name, text)
    return "ev-" + digest([c["documentVersion"], c["start"], c["end"]])[:32]


def expected_main(world, jobs: dict) -> dict:
    """Hand-written expectation of version `rel-main` under `mapping(world)`: 6 nodes, 6 edges (7 eligible relations, one merge), 7 evidence."""
    out = jobs["rel-main"]
    e = {"SUP": evidence_id(world, "main", SUP), "SUP2": evidence_id(world, "main", SUP2), "COMP": evidence_id(world, "main", COMP),
         "INV": evidence_id(world, "main", INV), "VALID": evidence_id(world, "main", VALID), "EVT": evidence_id(world, "main", EVT),
         "QB": evidence_id(world, "b", QB)}
    rc = lambda *args, **match: find(out, *args, **match)["relationCandidateId"]  # noqa: E731
    edges = [
        {"type": "SUPPLIES", "start": "kr-000300", "end": "kr-000100", "direction": "directed", "connection": "direct", "productScope": "배터리 부품",
         "evidenceIds": [e["SUP"]], "sourceRelationCandidateIds": [rc("SUPPLIES", "SYNTH-3", "SYNTH-1")]},
        {"type": "SUPPLIES", "start": "kr-000300", "end": "kr-000050", "direction": "directed", "connection": "indirect", "productScope": "부품",
         "pathCompanyIds": ["kr-000300", "kr-000100", "kr-000050"], "step1EvidenceIds": [e["SUP"]], "step2EvidenceIds": [e["SUP2"]],
         "sourceRelationCandidateIds": [rc("SUPPLIES", "SYNTH-3", "SYNTH-2", connection="indirect")]},
        {"type": "COMPETES_WITH", "start": "kr-000050", "end": "kr-000100", "direction": "symmetric", "connection": "direct", "businessScope": "전기차 시장",
         "evidenceIds": [e["COMP"]], "sourceRelationCandidateIds": [rc("COMPETES_WITH")]},
        {"type": "INVESTS_IN", "start": "kr-000400", "end": "kr-000300", "direction": "directed", "connection": "direct", "validFrom": "2026-01-01",
         "validUntil": "2026-12-31", "evidenceIds": [e["INV"]], "validityEvidenceIds": [e["VALID"]], "sourceRelationCandidateIds": [rc("INVESTS_IN")]},
        {"type": "PARTICIPATES_IN", "start": "kr-000100", "end": "event:main-event", "direction": "directed", "connection": "direct",
         "evidenceIds": sorted([e["EVT"], e["QB"]]),
         "sourceRelationCandidateIds": sorted([rc("PARTICIPATES_IN", "SYNTH-1", world.evc), rc("PARTICIPATES_IN", "SYNTH-1", world.event)])},
        {"type": "RELATES_TO_TOPIC", "start": "kr-000100", "end": "topic:ev-supply-chain", "direction": "directed", "connection": "direct",
         "evidenceIds": [e["EVT"]], "sourceRelationCandidateIds": [rc("RELATES_TO_TOPIC", "SYNTH-1", world.tp)]},
    ]
    return {"nodes": {"ZgCompany": {"kr-000050", "kr-000100", "kr-000300", "kr-000400"}, "ZgEvent": {"event:main-event"}, "ZgTopic": {"topic:ev-supply-chain"}},
            "edges": edges, "evidence": sorted(e.values()),
            "audit": {"s3Relations": 9, "eligibility": {"eligible": 7, "hold": 1, "reject": 1, "pending": 0}, "reviewPending": 0, "projectedCandidates": 7,
                      "canonicalMerges": 1, "impactCandidatesNotProjected": 2}}


def expected_two(world, jobs: dict) -> dict:
    out = jobs["rel-two"]
    sup, inv = evidence_id(world, "main", SUP), evidence_id(world, "main", INV)
    return {"nodes": {"ZgCompany": {"kr-000100", "kr-000300", "kr-000400"}, "ZgEvent": set(), "ZgTopic": set()},
            "edges": [{"type": "SUPPLIES", "start": "kr-000300", "end": "kr-000100", "direction": "directed", "connection": "direct", "productScope": "배터리 부품",
                       "evidenceIds": [sup], "sourceRelationCandidateIds": [find(out, "SUPPLIES", "SYNTH-3", "SYNTH-1")["relationCandidateId"]]},
                      {"type": "INVESTS_IN", "start": "kr-000400", "end": "kr-000300", "direction": "directed", "connection": "direct", "evidenceIds": [inv],
                       "sourceRelationCandidateIds": [find(out, "INVESTS_IN")["relationCandidateId"]]}],
            "evidence": sorted([sup, inv])}


def full(spec: dict) -> dict:
    """An expected edge with every EDGE_KEYS entry present: absent scalars None, absent lists []."""
    return {key: spec.get(key, [] if key in LISTS else None) for key in EDGE_KEYS if key != "id"}


# ---------------------------------------------------------------- operator harness -------------------------------------------------

def guard_source(port: int) -> str:
    return ("import os, sys, runpy\n"
            f"LOCAL, PORT = {{'127.0.0.1', 'localhost', '::1'}}, {port}\n"
            "def _guard(event, args):\n"
            " if event == 'socket.connect':\n"
            "  address = args[1]\n"
            "  if not (isinstance(address, tuple) and address[0] in LOCAL and address[1] == PORT):\n"
            "   raise RuntimeError('network attempted')\n"
            " elif event in {'socket.getaddrinfo', 'socket.gethostbyname'}:\n"
            "  host = args[0].decode() if isinstance(args[0], bytes) else args[0]\n"
            "  if host not in LOCAL:\n"
            "   raise RuntimeError('network attempted')\n"
            " elif event == 'socket.bind':\n"
            "  raise RuntimeError('network attempted')\n"
            "sys.addaudithook(_guard)\n"
            "from zoop_ai_pipeline.graph_projection import Projector\n")


HOOKS = {
    # The transaction is committed on the server, then the client sees a lost response.
    "unknown-committed": ("from neo4j.exceptions import IncompleteCommit\ndef _c(self, tx):\n tx.commit()\n raise IncompleteCommit('test: response lost after commit')\n"
                          "Projector._commit = _c\n"),
    # Nothing was committed, the client sees the same lost connection.
    "unknown-uncommitted": ("from neo4j.exceptions import IncompleteCommit\ndef _c(self, tx):\n raise IncompleteCommit('test: connection lost before commit')\n"
                            "Projector._commit = _c\n"),
    # The process dies after the server committed and before the ledger acknowledged it.
    "kill-after-commit": "def _c(self, tx):\n tx.commit()\n os._exit(9)\nProjector._commit = _c\n",
    # The process dies after the attempt is durably reserved and before the first graph write.
    "kill-after-reserve": "Projector._after_reserve = lambda self: os._exit(9)\n",
    # A real server-side failure in the middle of the transaction, after nodes and some edges were written.
    "write-fault": "def _w(self, tx, stage):\n if stage == 'edges:SUPPLIES':\n  list(tx.run('RETURN 1/0'))\nProjector._written = _w\n",
}


class Raw:
    """Test-only direct driver. It is the oracle for what Neo4j actually holds and the planter of corruption; never the code under test."""

    def __init__(self, uri: str, database: str):
        from neo4j import GraphDatabase, basic_auth
        auth = basic_auth(os.environ["ZOOP_GRAPH_USER"], os.environ["ZOOP_GRAPH_PASSWORD"]) if os.environ["ZOOP_GRAPH_AUTH"] == "basic" else None
        self.driver, self.database = GraphDatabase.driver(uri, auth=auth), database

    def q(self, cypher: str, **params) -> list[dict]:
        with self.driver.session(database=self.database) as session:
            return [record.data() for record in session.run(cypher, params)]

    def count(self, cypher: str, **params) -> int:
        return self.q(cypher, **params)[0]["c"]

    def nodes_of(self, version: str) -> dict:
        found: dict = {}
        for row in self.q("MATCH (n) WHERE n.v = $v RETURN labels(n) AS l, properties(n) AS p", v=version):
            found.setdefault(row["l"][0], set()).add(row["p"]["id"])
        return found

    def edges_of(self, version: str) -> list[dict]:
        return self.q("MATCH (a)-[e]->(b) WHERE e.v = $v RETURN type(e) AS t, properties(e) AS p, a.id AS start, b.id AS end", v=version)

    def dump(self, version: str) -> str:
        """Everything stored for one version (nodes, edges, marker), canonical and comparable."""
        nodes = self.q("MATCH (n) WHERE n.v = $v RETURN labels(n) AS l, properties(n) AS p", v=version)
        edges = self.q("MATCH (a)-[e]->(b) WHERE e.v = $v RETURN type(e) AS t, properties(e) AS p, a.vk AS s, b.vk AS e2", v=version)
        marker = self.q("MATCH (m:ZgVersion {versionId: $v}) RETURN properties(m) AS p", v=version)
        return json.dumps(sorted(json.dumps(x, sort_keys=True, ensure_ascii=False) for x in (*nodes, *edges, *marker)), ensure_ascii=False)

    def remove_version(self, version: str) -> None:
        """Targeted removal by exact version identity only."""
        self.q("MATCH (n) WHERE n.v = $v DETACH DELETE n", v=version)
        self.q("MATCH (m:ZgVersion {versionId: $v}) DELETE m", v=version)

    def close(self) -> None:
        self.driver.close()


class Operator:
    def __init__(self, world, uri: str, database: str, run: str):
        self.world, self.uri, self.database, self.run = world, uri, database, run
        self.root, self.kit = world.kit.root, world.kit
        self.port = urlsplit(uri).port
        self.canonical = self.root / "canonical.json"
        self.outputs: list[str] = []
        self.write_registry(registry(world))

    def vid(self, name: str) -> str:
        return f"{self.run}-{name}"

    def write_registry(self, document) -> None:
        raw = document if isinstance(document, bytes) else json_bytes(document)
        temporary = self.root / "next-canonical.json"
        temporary.write_bytes(raw)
        temporary.replace(self.canonical)

    def graph(self, command: str, request: dict, *, state: str = "graph", expected: int = 0, hook: str | None = None, uri: str | None = None,
              extra: tuple = (), canonical: Path | None = None, raw_input: bytes | None = None):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", **ownership_env(), **CUSTOM,
               **{k: v for k, v in os.environ.items() if k.startswith("ZOOP_GRAPH_") and k != "ZOOP_GRAPH_SMOKE_URI"}, **trust_env()}
        program = guard_source(self.port) + (HOOKS[hook] if hook else "") + "runpy.run_module('zoop_ai_pipeline.graph_projection_cli', run_name='__main__')\n"
        argv = [sys.executable, "-c", program, command, "--state-dir", str(self.root / state)]
        if command in SOURCED:
            argv += ["--relation-state-dir", str(self.root / "relation"), "--extraction-state-dir", str(self.root / "extraction"),
                     "--ingestion-state-dir", str(self.root / "ingestion"), "--sources", str(self.kit.registry_path), "--canonical", str(canonical or self.canonical)]
        if command == "init":
            argv += ["--graph-uri", uri or self.uri]
        argv += list(extra)
        child = subprocess.run(argv, input=raw_input if raw_input is not None else json_bytes(request), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                               cwd=PIPELINE, timeout=300)
        text = child.stdout.decode()
        self.outputs.append(text)
        assert child.returncode == expected, (command, request, child.returncode, text, child.stderr.decode()[-2000:])
        assert expected == 9 or not child.stderr, (command, child.stderr.decode()[-2000:])
        assert_no_credential_leak(text, self.database)
        return json.loads(text) if text else None

    def sel(self, name: str) -> dict:
        return {"schemaVersion": SCHEMA, "versionId": self.vid(name)}

    def freeze(self, name: str, job: str, *, expected: int = 0, input_digest: str | None = None, canonical: Path | None = None):
        relation = {"jobId": job, "inputDigest": input_digest or self.jobs[job]["inputDigest"]}
        return self.graph("freeze", {**self.sel(name), "relation": relation}, expected=expected, canonical=canonical)

    def error(self, out: dict, code: str, detail: dict | None = None) -> None:
        assert out == {"schemaVersion": SCHEMA, "error": {"code": code, **({"detail": detail} if detail else {})}}, out

    def withheld(self, out: dict, name: str, code: str) -> None:
        assert set(out) == WITHHELD_KEYS and out["delivery"] == {"status": "withheld", "code": code} and out["publication"] == "not-published", out
        assert out["versionId"] == self.vid(name) and out["usage"] == {"providerCalls": 0, "modelCalls": 0}, out

    def state(self, name: str) -> dict:
        return self.graph("inspect", self.sel(name))

    def ledger(self, state: str = "graph") -> str:
        """The whole ledger content (rows, not file bytes), from a read-only immutable connection."""
        db = sqlite3.connect((self.root / state / "graph.sqlite3").as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            return json.dumps([db.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall() for table in ("meta", "versions", "attempts")], ensure_ascii=False)
        finally:
            db.close()


# ---------------------------------------------------------------- checks -------------------------------------------------------------

def edges_equal(actual: list[dict], expected: list[dict]) -> None:
    """Stored edges (by type, endpoint canonical IDs and every property) equal the hand-written expectation exactly."""
    seen = []
    for row in actual:
        assert row["t"].startswith("ZG_") and row["p"]["id"].startswith("rel-") and len(row["p"]["id"]) == 68, row
        props = {k: v for k, v in row["p"].items() if k not in {"vk", "v", "id"}}
        assert set(props) <= set(EDGE_KEYS) and all(v not in (None, []) for v in props.values()), props
        seen.append({"type": row["t"][3:], "start": row["start"], "end": row["end"], **full(props)})
    wanted = [{"type": e["type"], "start": e["start"], "end": e["end"], **full(e)} for e in expected]
    key = lambda d: (d["type"], d["start"], d["end"], json.dumps(d, sort_keys=True, ensure_ascii=False))  # noqa: E731
    assert sorted(seen, key=key) == sorted(wanted, key=key), (sorted(seen, key=key), sorted(wanted, key=key))


def view_edges_equal(actual: list[dict], expected: list[dict]) -> None:
    """The `read`/`focus` edge objects equal the same expectation (subject/object by canonical ID, scopes, validity, path, evidence)."""
    shaped = []
    for e in actual:
        assert e["relationId"].startswith("rel-")
        shaped.append({"type": e["type"], "start": e["subject"]["id"], "end": e["object"]["id"], "direction": e["direction"], "connection": e["connection"],
                       "businessScope": e["businessScope"], "productScope": e["productScope"], "validFrom": e["validity"]["from"], "validUntil": e["validity"]["until"],
                       "countries": e["countries"], "pathCompanyIds": e["path"]["companyIds"], "evidenceIds": e["evidence"]["relation"],
                       "validityEvidenceIds": e["evidence"]["validity"], "step1EvidenceIds": e["evidence"]["steps"][0], "step2EvidenceIds": e["evidence"]["steps"][1],
                       "sourceRelationCandidateIds": e["sourceRelationCandidateIds"]})
    wanted = [{"type": e["type"], "start": e["start"], "end": e["end"], **full(e)} for e in expected]
    key = lambda d: (d["type"], d["start"], d["end"])  # noqa: E731
    assert sorted(shaped, key=key) == sorted(wanted, key=key), (sorted(shaped, key=key), sorted(wanted, key=key))


def check_stored(raw: Raw, version: str, expected: dict) -> None:
    assert raw.nodes_of(version) == {k: v for k, v in expected["nodes"].items() if v}, raw.nodes_of(version)
    edges_equal(raw.edges_of(version), expected["edges"])
    marker = raw.q("MATCH (m:ZgVersion {versionId: $v}) RETURN properties(m) AS p", v=version)
    assert len(marker) == 1 and marker[0]["p"]["nodeCount"] == sum(len(v) for v in expected["nodes"].values()) and marker[0]["p"]["edgeCount"] == len(expected["edges"]), marker
    keys = {k for row in raw.q("MATCH (n) WHERE n.v = $v RETURN keys(n) AS k", v=version) for k in row["k"]}
    keys |= {k for row in raw.q("MATCH ()-[e]->() WHERE e.v = $v RETURN keys(e) AS k", v=version) for k in row["k"]}
    assert keys <= {"vk", "v", "id", *EDGE_KEYS}, keys   # no `active`, `public`, `approved` or `published` flag exists anywhere


def read_matches(out: dict, expected: dict, op: Operator, name: str) -> None:
    assert out["delivery"]["status"] == "current" and out["publication"] == "not-published" and out["state"] == "ready" and out["versionId"] == op.vid(name), out
    assert out["usage"] == {"providerCalls": 0, "modelCalls": 0}
    want = sorted((kind, ident) for kind, label in (("company", "ZgCompany"), ("event", "ZgEvent"), ("topic", "ZgTopic")) for ident in expected["nodes"][label])
    assert sorted((n["kind"], n["id"]) for n in out["graph"]["nodes"]) == want and out["verification"]["marker"] == "matched", out["graph"]["nodes"]
    assert out["verification"]["nodes"] == len(want) and out["verification"]["edges"] == len(expected["edges"])
    view_edges_equal(out["graph"]["edges"], expected["edges"])
    assert [e["evidenceId"] for e in out["evidence"]] == expected["evidence"]
    assert all(set(e) == {"evidenceId", "documentId", "documentVersion", "rawVersion", "start", "end"} for e in out["evidence"])


def focus_checks(op: Operator, name: str, expected: dict) -> None:
    """Depth-limited views over the verified version, computed by hand from the six expected edges (A=kr-000050 B=kr-000100 C=kr-000300 D=kr-000400,
    event E, topic T): A-B competes, C-B and C-A supply, D-C invests, B-E participates, B-T relates."""
    by = {(e["type"], e["start"], e["end"]): e for e in expected["edges"]}
    ab, cb, ca, dc = (by[("COMPETES_WITH", "kr-000050", "kr-000100")], by[("SUPPLIES", "kr-000300", "kr-000100")], by[("SUPPLIES", "kr-000300", "kr-000050")],
                      by[("INVESTS_IN", "kr-000400", "kr-000300")])
    be, bt = by[("PARTICIPATES_IN", "kr-000100", "event:main-event")], by[("RELATES_TO_TOPIC", "kr-000100", "topic:ev-supply-chain")]
    cases = {("kr-000100", 1): ({"kr-000100": 0, "kr-000300": 1, "kr-000050": 1, "event:main-event": 1, "topic:ev-supply-chain": 1}, [ab, cb, be, bt]),
             ("kr-000100", 2): ({"kr-000100": 0, "kr-000300": 1, "kr-000050": 1, "event:main-event": 1, "topic:ev-supply-chain": 1, "kr-000400": 2}, [ab, cb, ca, dc, be, bt]),
             ("kr-000100", 3): ({"kr-000100": 0, "kr-000300": 1, "kr-000050": 1, "event:main-event": 1, "topic:ev-supply-chain": 1, "kr-000400": 2}, [ab, cb, ca, dc, be, bt]),
             ("kr-000400", 1): ({"kr-000400": 0, "kr-000300": 1}, [dc]),
             ("kr-000400", 2): ({"kr-000400": 0, "kr-000300": 1, "kr-000100": 2, "kr-000050": 2}, [dc, cb, ca]),
             ("kr-000400", 3): ({"kr-000400": 0, "kr-000300": 1, "kr-000100": 2, "kr-000050": 2, "event:main-event": 3, "topic:ev-supply-chain": 3}, [dc, cb, ca, ab, be, bt])}
    for (company, depth), (distances, edges) in cases.items():
        out = op.graph("focus", {**op.sel(name), "companyId": company, "depth": depth})
        assert out["focus"] == {"companyId": company, "depth": depth, "found": True} and out["delivery"]["status"] == "current", out["focus"]
        assert {n["id"]: n["distance"] for n in out["graph"]["nodes"]} == distances, (company, depth, out["graph"]["nodes"])
        view_edges_equal(out["graph"]["edges"], edges)
        # The hand-written expectation names only the evidence fields an edge type uses (a direct edge has no step lists, an undated one no validity list);
        # the contract's absent lists are [] and `full()` supplies exactly that, so every evidence ID an included edge references must be returned.
        referenced = {i for e in edges for i in (*full(e)["evidenceIds"], *full(e)["validityEvidenceIds"], *full(e)["step1EvidenceIds"], *full(e)["step2EvidenceIds"])}
        assert {e["evidenceId"] for e in out["evidence"]} == referenced, (company, depth)
    absent = op.graph("focus", {**op.sel(name), "companyId": "kr-999999", "depth": 2})
    assert absent["focus"] == {"companyId": "kr-999999", "depth": 2, "found": False} and absent["graph"] == {"nodes": [], "edges": []} and absent["evidence"] == []


# ---------------------------------------------------------------- the smoke ---------------------------------------------------------

def smoke(root: Path, uri: str, database: str, run: str) -> dict:
    checks: list[str] = []
    raw = Raw(uri, database)
    try:
        if raw.count("MATCH (n) RETURN count(n) AS c") != 0:
            raise SystemExit("the Neo4j database is not empty: this smoke needs a fresh dedicated database "
                             f"(or `--cleanup {run}` for a previous run of this id). It never wipes a database.")
        world = build_world(root)
        jobs = build_relations(world, process=True)
        op = Operator(world, uri, database, run)
        op.jobs = jobs
        main, two = expected_main(world, jobs), expected_two(world, jobs)
        assert jobs["rel-main"]["counts"]["eligibility"] == {"pending": 0, "eligible": 7, "hold": 1, "reject": 1} and jobs["rel-main"]["counts"]["impactCandidates"] == 2
        sources_before = {name: tree(root / name) for name in ("ingestion", "extraction")}
        relation_before = tree(root / "relation")
        checks.append("world: actual ingestion + S2 + five S3 jobs (7 eligible over all five types, 1 HOLD, 1 REJECT, 2 impact candidates) built through the existing CLIs")

        # 1. init: bound once to an empty database; idempotent; a second ledger and other identities are refused; unsafe URIs never create state.
        out = op.graph("init", {"schemaVersion": SCHEMA, "storeId": f"{run}-store", "database": database})
        assert out["store"]["state"] == "bound" and out["store"]["schemaObjects"] == {"constraints": 10, "indexes": 13} and out["usage"] == {"providerCalls": 0, "modelCalls": 0}, out
        init_store = out["store"]
        constraints = {r["name"]: (r["type"], r["entityType"]) for r in raw.q("SHOW CONSTRAINTS YIELD name, type, entityType")}
        assert len(constraints) == 10 and sorted(v[0] for v in constraints.values()).count("RELATIONSHIP_UNIQUENESS") == 5 and sorted(constraints) == sorted(
            ["zg_store_slot", "zg_version_id", "zg_company_vk", "zg_event_vk", "zg_topic_vk", "zg_supplies_vk", "zg_invests_in_vk", "zg_competes_with_vk",
             "zg_participates_in_vk", "zg_relates_to_topic_vk"]), constraints
        index_rows = raw.q("SHOW INDEXES YIELD name, type, state")
        indexes = [r["name"] for r in index_rows if r["type"] == "RANGE"]
        assert len(indexes) == 13 and all(r["state"] == "ONLINE" for r in index_rows if r["type"] != "LOOKUP"), index_rows
        assert raw.count("MATCH (n) RETURN count(n) AS c") == 1 and raw.q("MATCH (s:ZgStore) RETURN s.storeId AS id") == [{"id": f"{run}-store"}]
        ledger_dir = root / "graph"
        assert sorted(p.name for p in ledger_dir.iterdir()) == ["graph.lock", "graph.sqlite3"] and oct(ledger_dir.stat().st_mode & 0o777) == "0o700"
        assert all(oct(p.stat().st_mode & 0o777) == "0o600" for p in ledger_dir.iterdir())
        assert op.graph("init", {"schemaVersion": SCHEMA, "storeId": f"{run}-store", "database": database})["store"] == out["store"]
        op.error(op.graph("init", {"schemaVersion": SCHEMA, "storeId": f"{run}-other", "database": database}, expected=2), "graph_store_already_bound")
        op.error(op.graph("init", {"schemaVersion": SCHEMA, "storeId": f"{run}-store", "database": database}, state="graph-second", expected=2), "graph_store_not_empty")
        assert raw.count("MATCH (n) RETURN count(n) AS c") == 1
        port = urlsplit(uri).port
        for index, unsafe in enumerate((f"bolt://user:secret@127.0.0.1:{port}", f"neo4j://127.0.0.1:{port}", f"bolt://127.0.0.1:{port}/db", f"bolt://127.0.0.1:{port}?x=1",
                                        "bolt://example.com:7687", "bolt://127.0.0.1", f"bolt+ssc://127.0.0.1:{port}", f"http://127.0.0.1:{port}")):
            state = f"graph-unsafe-{index}"
            op.error(op.graph("init", {"schemaVersion": SCHEMA, "storeId": f"{run}-u{index}", "database": database}, state=state, expected=2, uri=unsafe), "graph_uri_invalid")
            assert not (root / state).exists()
        op.error(op.graph("project", op.sel("v1"), extra=("--graph-uri", uri), expected=2), "input_or_configuration_invalid")
        checks.append("init: one ZgStore, exactly 10 uniqueness constraints (5 relationship) and 13 ONLINE RANGE indexes, private ledger, idempotent re-run; "
                      "other storeId/second ledger/unsafe URIs refused with no state")

        # 2. Whole-freeze failures write no version row and touch nothing.
        before = op.ledger()
        missing = registry(world, {k: v for k, v in mapping(world).items() if k != ("topic", world.tp)})
        op.write_registry(missing)
        out = op.freeze("bad-unresolved", "rel-main", expected=2)
        op.error(out, "canonical_mapping_unresolved", {"total": 1, "unresolved": [{"kind": "topic", "ref": world.tp}]})
        collapsed = {**mapping(world), ("company", "SYNTH-4"): "kr-000300"}
        op.write_registry(registry(world, collapsed))
        reason = op.freeze("bad-self", "rel-two", expected=2)
        assert reason["error"]["code"] == "canonical_mapping_conflict" and reason["error"]["detail"]["reason"] == "self_relation", reason
        op.write_registry(registry(world, {**mapping(world), ("company", "SYNTH-1"): "kr-000300"}))
        reason = op.freeze("bad-path", "rel-path", expected=2)
        assert reason["error"]["code"] == "canonical_mapping_conflict" and reason["error"]["detail"]["reason"] == "path_collapsed", reason
        op.write_registry(registry(world))
        for name in ("bad-unresolved", "bad-self", "bad-path"):
            op.error(op.graph("inspect", op.sel(name), expected=2), "version_not_found")
        assert op.ledger() == before and raw.count("MATCH (n) RETURN count(n) AS c") == 1
        checks.append("freeze: an unresolved endpoint, a self-collapsed relation and a collapsed path each fail the WHOLE freeze with no row; the unmapped topic-spelled event "
                      "of the REJECT candidate never needed a decision")

        # 3. freeze v1: SQLite only; exact audit counts; idempotent; a different request conflicts.
        frozen = op.freeze("v1", "rel-main")
        assert frozen["state"] == "frozen" and frozen["next"] == "project" and frozen["publication"] == "not-published" and frozen["failure"] is None, frozen
        assert frozen["counts"] == {"nodes": {"company": 4, "event": 1, "topic": 1}, "edges": {"SUPPLIES": 2, "INVESTS_IN": 1, "COMPETES_WITH": 1, "PARTICIPATES_IN": 1,
                                                                                    "RELATES_TO_TOPIC": 1}, "evidence": 7}, frozen["counts"]
        assert frozen["audit"] == main["audit"] and frozen["canonical"]["entries"] == 7 and frozen["attempts"] == []
        assert frozen["source"]["upstream"]["jobId"] == "s2-job" and frozen["source"]["relation"] == {"jobId": "rel-main", "inputDigest": jobs["rel-main"]["inputDigest"]}
        assert frozen["source"]["upstream"]["digest"] == jobs["rel-main"]["binding"]["upstream"]["digest"] and frozen["usage"] == {"providerCalls": 0, "modelCalls": 0}
        assert raw.count("MATCH (n) RETURN count(n) AS c") == 1   # freeze never touches Neo4j
        assert op.freeze("v1", "rel-main") == frozen == op.state("v1")
        before = op.ledger()
        op.error(op.freeze("v1", "rel-two", expected=2), "version_input_conflict")
        assert op.ledger() == before
        checks.append("freeze v1: exact audit counts (9 S3 relations: 7 eligible, 1 hold, 1 reject, 0 pending; 7 projected -> 6 edges after 1 alias merge; 2 impact candidates not "
                      "projected), digests pinned, idempotent, a different request is version_input_conflict, Neo4j untouched")

        # 4. project v1: one explicit transaction; stored content equals the hand-written expectation; no activation flag; idempotent.
        ready = op.graph("project", op.sel("v1"))
        assert ready["state"] == "ready" and ready["next"] == "read" and ready["attempts"] == [{"n": 1, "outcome": "committed", "code": None}] and ready["publication"] == "not-published"
        check_stored(raw, op.vid("v1"), main)
        marker = raw.q("MATCH (m:ZgVersion {versionId: $v}) RETURN properties(m) AS p", v=op.vid("v1"))[0]["p"]
        assert marker["payloadDigest"] == ready["digests"]["payload"] and marker["graphDigest"] == ready["digests"]["graph"] and marker["storeId"] == f"{run}-store"
        total = raw.count("MATCH (n) RETURN count(n) AS c")
        assert total == 1 + 1 + 6
        dump_v1 = raw.dump(op.vid("v1"))
        again = op.graph("project", op.sel("v1"))
        assert again == ready and raw.count("MATCH (n) RETURN count(n) AS c") == total and raw.dump(op.vid("v1")) == dump_v1
        checks.append("project v1: 6 nodes/6 edges/marker stored exactly as authored (all 5 types, the two-step path [kr-000300,kr-000100,kr-000050], the reversed symmetric pair, "
                      "the merged event edge with unioned evidence), only vk/v/id + EDGE_KEYS properties (no active/public flag), repeat project is a no-op")

        # 5. read v1: authority + full verification; no quote/title/URL/rationale anywhere.
        out = op.graph("read", op.sel("v1"))
        read_matches(out, main, op, "v1")
        assert out["current"] == {"s3ReviewDigestMatches": True} and out["source"]["upstream"] == frozen["source"]["upstream"] and out["digests"] == ready["digests"]
        focus_checks(op, "v1", main)
        checks.append("read/focus v1: full graph verified; depth 1/2/3 from kr-000100 and kr-000400 equal the hand-computed node distances and edge sets; absent company is found:false")

        # 6. A second immutable version never touches the first.
        op.freeze("v2", "rel-two")
        op.graph("project", op.sel("v2"))
        check_stored(raw, op.vid("v2"), two)
        assert raw.dump(op.vid("v1")) == dump_v1
        assert not {r["vk"] for r in raw.q("MATCH (n) WHERE n.v = $v RETURN n.vk AS vk", v=op.vid("v1"))} & {r["vk"] for r in raw.q("MATCH (n) WHERE n.v = $v RETURN n.vk AS vk", v=op.vid("v2"))}
        read_matches(op.graph("read", op.sel("v1")), main, op, "v1")
        read_matches(op.graph("read", op.sel("v2")), two, op, "v2")
        checks.append("two immutable versions: v2 (3 nodes, 2 edges) shares canonical IDs with v1 yet has disjoint version-scoped nodes; v1 stored content is byte-identical afterwards")

        # 6b. Repeating `init` of the SAME ledger/store while two staged (nonpublic) versions exist is idempotent: no DDL, no store write, no version change;
        #     a fresh ledger is still never allowed to adopt that database.
        def store_state() -> dict:
            return {"store": raw.q("MATCH (s:ZgStore) RETURN properties(s) AS p"), "nodes": raw.count("MATCH (n) RETURN count(n) AS c"),
                    "relationships": raw.count("MATCH ()-[r]->() RETURN count(r) AS c"),
                    "constraints": sorted((r["name"], r["type"]) for r in raw.q("SHOW CONSTRAINTS YIELD name, type")),
                    "indexes": sorted((r["name"], r["type"], r["state"]) for r in raw.q("SHOW INDEXES YIELD name, type, state"))}
        dump_v2 = raw.dump(op.vid("v2"))
        store_before, ledger_before_init = store_state(), op.ledger()
        assert store_before["nodes"] == 1 + (1 + 6) + (1 + 3) and store_before["relationships"] == 6 + 2 and len(store_before["store"]) == 1, store_before   # store + v1 + v2, written by hand
        repeated = op.graph("init", {"schemaVersion": SCHEMA, "storeId": f"{run}-store", "database": database})
        assert repeated["store"] == init_store and repeated["usage"] == {"providerCalls": 0, "modelCalls": 0}, repeated
        assert store_state() == store_before and raw.dump(op.vid("v1")) == dump_v1 and raw.dump(op.vid("v2")) == dump_v2 and op.ledger() == ledger_before_init
        op.error(op.graph("init", {"schemaVersion": SCHEMA, "storeId": f"{run}-store", "database": database}, state="graph-second", expected=2), "graph_store_not_empty")
        assert store_state() == store_before
        read_matches(op.graph("read", op.sel("v1")), main, op, "v1")
        read_matches(op.graph("read", op.sel("v2")), two, op, "v2")
        checks.append("repeated init after two staged nonpublic versions: same store result, store marker/constraints/indexes/node and relationship counts and both versions' stored content "
                      "and the ledger unchanged (no DDL, no store write); a fresh ledger is still refused with graph_store_not_empty; both versions still read as current")

        # 7. Current authority gates: grants, upstream digest, canonical decisions, review state.
        grant = op.kit.registry["sources"][0]["grant"]
        ledger_before = op.ledger()
        grant["enabled"] = False
        op.kit.save_registry()
        text_out = op.graph("read", op.sel("v1"), expected=2)
        op.withheld(text_out, "v1", "source_unauthorized")
        grant["enabled"] = True
        op.kit.save_registry()
        grant["revision"] = "rights-2"
        op.kit.save_registry()
        op.withheld(op.graph("read", op.sel("v1"), expected=2), "v1", "grant_revision_changed")
        op.withheld(op.graph("focus", {**op.sel("v1"), "companyId": "kr-000100", "depth": 1}, expected=2), "v1", "grant_revision_changed")
        op.error(op.freeze("v1", "rel-main", expected=2), "grant_revision_changed")   # the unchanged request is bound to the frozen upstream every time
        op.error(op.freeze("v3", "rel-main", expected=2), "grant_revision_changed")   # a NEW freeze under the changed grant is refused too
        grant["revision"] = "rights-1"
        op.kit.save_registry()
        assert op.ledger() == ledger_before, "withheld reads and refused freezes wrote the ledger"
        frozen_v3 = op.freeze("v3", "rel-main")
        grant["revision"] = "rights-3"
        op.kit.save_registry()
        refused = op.graph("project", op.sel("v3"), expected=2)
        op.error(refused, "grant_revision_changed")
        failed = op.state("v3")
        assert failed["state"] == "frozen" and failed["failure"]["code"] == "grant_revision_changed" and failed["attempts"] == [], failed
        assert raw.nodes_of(op.vid("v3")) == {}
        grant["revision"] = "rights-1"
        op.kit.save_registry()
        read_matches(op.graph("read", op.sel("v1")), main, op, "v1")
        for label, change in (("topic decision revoked", lambda m: {k: v for k, v in m.items() if k != ("topic", world.tp)}),
                              ("company re-mapped", lambda m: {**m, ("company", "SYNTH-3"): "kr-000301"})):
            op.write_registry(registry(world, change(mapping(world))))
            op.withheld(op.graph("read", op.sel("v1"), expected=2), "v1", "canonical_mapping_changed")
        op.write_registry(registry(world, decision="decision-other"))
        op.withheld(op.graph("read", op.sel("v1"), expected=2), "v1", "canonical_mapping_changed")   # the decision identity is part of the pinned mapping
        op.write_registry(b"{not json")
        op.error(op.graph("read", op.sel("v1"), expected=2), "canonical_registry_invalid")
        op.write_registry(registry(world))
        read_matches(op.graph("read", op.sel("v1")), main, op, "v1")
        assert {n: tree(root / n) for n in ("ingestion", "extraction")} == sources_before and tree(root / "relation") == relation_before
        checks.append("authority: revoked grant, changed grant revision (also on an unchanged freeze request and on project), revoked/re-mapped/re-decided canonical mapping and a "
                      "malformed registry each withhold or refuse with no content and no ledger write; restoring the exact state serves v1 again; source ledgers unchanged")
        op.graph("project", op.sel("v3"))
        check_stored(raw, op.vid("v3"), main)
        assert frozen_v3["digests"]["payload"] != frozen["digests"]["payload"], "payload digest must bind the version"

        # 8. Atomic rollback of a real server-side failure in the middle of the transaction, then a clean retry.
        op.freeze("v-rb", "rel-two")
        out = op.graph("project", op.sel("v-rb"), hook="write-fault", expected=2)
        assert out["error"]["code"] == "graph_write_failed" and out["error"]["detail"]["neo4j"].startswith("Neo.ClientError"), out
        state = op.state("v-rb")
        assert state["state"] == "frozen" and state["failure"]["code"] == "graph_write_failed" and state["attempts"] == [{"n": 1, "outcome": "not-committed", "code": "graph_write_failed"}], state
        assert raw.nodes_of(op.vid("v-rb")) == {} and raw.edges_of(op.vid("v-rb")) == [] and raw.dump(op.vid("v-rb")) == "[]"
        done = op.graph("project", op.sel("v-rb"))
        assert done["state"] == "ready" and [a["outcome"] for a in done["attempts"]] == ["not-committed", "committed"]
        check_stored(raw, op.vid("v-rb"), two)
        checks.append("rollback: a server error after nodes and edges were written leaves NO node, edge or marker; the ledger records not-committed; a retry commits as attempt 2")

        # 9. Unknown commit reconciliation by reading the full graph back.
        op.freeze("v-u1", "rel-two")
        out = op.graph("project", op.sel("v-u1"), hook="unknown-committed", expected=2)
        op.error(out, "graph_commit_unknown")
        assert op.state("v-u1")["state"] == "unknown" and op.state("v-u1")["next"] == "recover" and raw.nodes_of(op.vid("v-u1")), "committed data must exist"
        op.error(op.graph("project", op.sel("v-u1"), expected=2), "graph_commit_unknown", {"state": "unknown"})
        recovered = op.graph("recover", op.sel("v-u1"))
        assert recovered["state"] == "ready" and recovered["attempts"] == [{"n": 1, "outcome": "confirmed", "code": None}], recovered
        read_matches(op.graph("read", op.sel("v-u1")), two, op, "v-u1")
        op.error(op.graph("recover", op.sel("v-u1"), expected=2), "recovery_not_required", {"state": "ready"})
        op.freeze("v-u2", "rel-two")
        op.error(op.graph("project", op.sel("v-u2"), hook="unknown-uncommitted", expected=2), "graph_commit_unknown")
        assert op.state("v-u2")["state"] == "unknown" and raw.nodes_of(op.vid("v-u2")) == {} and raw.dump(op.vid("v-u2")) == "[]"
        back = op.graph("recover", op.sel("v-u2"))
        assert back["state"] == "frozen" and back["next"] == "project" and back["attempts"] == [{"n": 1, "outcome": "not-committed", "code": None}], back
        assert op.graph("project", op.sel("v-u2"))["state"] == "ready"
        op.freeze("v-u3", "rel-two")
        op.graph("project", op.sel("v-u3"), hook="kill-after-commit", expected=9)
        op.error(op.graph("inspect", op.sel("v-u3"), expected=2), "graph_recovery_required")   # the killed writer left a hot WAL: a writer must settle it first
        op.error(op.graph("project", op.sel("v-u3"), expected=2), "graph_commit_unknown", {"state": "reserved"})
        assert op.state("v-u3")["state"] == "reserved" and raw.nodes_of(op.vid("v-u3")), "the killed process had committed"
        assert op.graph("recover", op.sel("v-u3"))["state"] == "ready"
        read_matches(op.graph("read", op.sel("v-u3")), two, op, "v-u3")
        op.freeze("v-u4", "rel-two")
        op.graph("project", op.sel("v-u4"), hook="kill-after-reserve", expected=9)
        op.error(op.graph("project", op.sel("v-u4"), expected=2), "graph_commit_unknown", {"state": "reserved"})
        assert raw.nodes_of(op.vid("v-u4")) == {} and op.graph("recover", op.sel("v-u4"))["state"] == "frozen" and op.graph("project", op.sel("v-u4"))["state"] == "ready"
        checks.append("commit unknown: committed-then-lost-response, lost-before-commit, process killed after commit before the ledger ack, and killed after reserve are each settled by "
                      "recover from the actual graph (confirmed / back to frozen), project refuses to guess in between, and a hot WAL blocks read-only openers")

        # 10. A foreign or conflicting version identity is never adopted.
        op.freeze("v-cf", "rel-two")
        raw.q("CREATE (:ZgVersion {versionId: $v, schema: 'zoop-graph-version-1', storeId: $s, payloadDigest: $z, graphDigest: $z, nodeCount: 0, edgeCount: 0})",
              v=op.vid("v-cf"), s=f"{run}-store", z="0" * 64)
        op.error(op.graph("project", op.sel("v-cf"), expected=2), "graph_commit_unknown")
        assert raw.nodes_of(op.vid("v-cf")) == {}
        conflict = op.graph("recover", op.sel("v-cf"))
        assert conflict["state"] == "failed" and conflict["failure"]["code"] == "graph_version_conflict" and conflict["next"] is None, conflict
        op.error(op.graph("project", op.sel("v-cf"), expected=2), "version_not_frozen", {"state": "failed"})
        raw.remove_version(op.vid("v-cf"))
        op.freeze("v-stray", "rel-two")
        raw.q("CREATE (:ZgCompany {vk: $vk, v: $v, id: 'kr-000100'})", vk=f"{op.vid('v-stray')}|kr-000100", v=op.vid("v-stray"))
        op.error(op.graph("project", op.sel("v-stray"), expected=2), "graph_version_corrupt")
        assert op.state("v-stray")["state"] == "failed"
        raw.remove_version(op.vid("v-stray"))
        checks.append("conflict: a marker with other digests is never adopted (unknown -> failed graph_version_conflict, terminal); stray version nodes without a marker fail corrupt")

        # 11. Corruption fails closed: the marker alone is never trusted.
        for name in ("v-c1", "v-c2", "v-c3", "v-c4", "v-c5", "v-c6"):
            op.freeze(name, "rel-two")
            op.graph("project", op.sel(name))
        v = op.vid
        raw.q("MATCH (:ZgCompany {v: $v})-[e:ZG_INVESTS_IN]->() DELETE e", v=v("v-c1"))
        raw.q("MATCH ()-[e:ZG_SUPPLIES {v: $v}]->() SET e.productScope = 'tampered'", v=v("v-c2"))
        raw.q("CREATE (:ZgCompany {vk: $vk, v: $v, id: 'extra'})", vk=f"{v('v-c3')}|extra", v=v("v-c3"))
        raw.q("MATCH (m:ZgVersion {versionId: $v}) SET m.payloadDigest = $f", v=v("v-c4"), f="f" * 64)
        raw.q("MATCH (a:ZgCompany {vk: $a}) WITH a MATCH (b:ZgCompany {vk: $b}) CREATE (a)-[:ZG_SUPPLIES {vk: $k, v: $v, id: 'rel-forged', direction: 'directed', connection: 'direct'}]->(b)",
              a=f"{v('v-c5')}|kr-000400", b=f"{v('v-c5')}|kr-000300", k=f"{v('v-c5')}|rel-forged", v=v("v-c5"))
        raw.q("MATCH (m:ZgVersion {versionId: $v}) DELETE m", v=v("v-c6"))
        for name in ("v-c1", "v-c2", "v-c3", "v-c4", "v-c5", "v-c6"):
            op.withheld(op.graph("read", op.sel(name), expected=2), name, "graph_version_corrupt")
            assert op.state(name)["state"] == "ready"   # the ledger is not rewritten by a read; the read just refuses to serve
        read_matches(op.graph("read", op.sel("v-rb")), two, op, "v-rb")
        tag = f"{run}-tag"
        raw.q("CREATE (:InvestMateIssue {smoke: $t})", t=tag)
        op.withheld(op.graph("read", op.sel("v1"), expected=2), "v1", "graph_store_foreign_data")
        op.freeze("v-fd", "rel-two")
        op.error(op.graph("project", op.sel("v-fd"), expected=2), "graph_store_foreign_data")
        assert op.state("v-fd")["state"] == "frozen" and raw.nodes_of(op.vid("v-fd")) == {}
        raw.q("MATCH (n:InvestMateIssue) WHERE n.smoke = $t DELETE n", t=tag)
        raw.q("MATCH (a:ZgCompany {vk: $a}) CREATE (a)-[:KNOWS {smoke: $t}]->(a)", a=f"{v('v2')}|kr-000300", t=tag)
        op.withheld(op.graph("read", op.sel("v2"), expected=2), "v2", "graph_store_foreign_data")
        raw.q("MATCH ()-[r:KNOWS]->() WHERE r.smoke = $t DELETE r", t=tag)
        read_matches(op.graph("read", op.sel("v2")), two, op, "v2")
        raw.q("DROP CONSTRAINT zg_topic_vk")
        op.withheld(op.graph("read", op.sel("v1"), expected=2), "v1", "graph_store_schema_mismatch")
        raw.q("CREATE CONSTRAINT zg_topic_vk IF NOT EXISTS FOR (n:ZgTopic) REQUIRE n.vk IS UNIQUE")
        raw.q("CALL db.awaitIndexes(20)")
        read_matches(op.graph("read", op.sel("v1")), main, op, "v1")
        assert op.graph("project", op.sel("v-fd"))["state"] == "ready"
        checks.append("corruption: a deleted edge, an edited property, an extra node, a forged marker digest, an extra same-type edge and a missing marker each withhold the read; "
                      "a foreign label or foreign relationship type in the database, or a dropped constraint, withholds every read and blocks project until removed")

        # 12. Empty eligible set: a valid empty version, distinct from a failed read.
        empty = op.freeze("v-empty", "rel-empty")
        assert empty["counts"] == {"nodes": {"company": 0, "event": 0, "topic": 0}, "edges": {k: 0 for k in ("SUPPLIES", "INVESTS_IN", "COMPETES_WITH", "PARTICIPATES_IN", "RELATES_TO_TOPIC")}, "evidence": 0}
        assert empty["audit"] == {"s3Relations": 1, "eligibility": {"eligible": 0, "hold": 1, "reject": 0, "pending": 0}, "reviewPending": 0, "projectedCandidates": 0,
                                  "canonicalMerges": 0, "impactCandidatesNotProjected": 0}, empty["audit"]
        assert op.graph("project", op.sel("v-empty"))["state"] == "ready"
        out = op.graph("read", op.sel("v-empty"))
        assert out["delivery"]["status"] == "current" and out["graph"] == {"nodes": [], "edges": []} and out["evidence"] == [] and out["verification"]["nodes"] == 0
        marker = raw.q("MATCH (m:ZgVersion {versionId: $v}) RETURN properties(m) AS p", v=op.vid("v-empty"))
        assert len(marker) == 1 and marker[0]["p"]["nodeCount"] == 0 and marker[0]["p"]["edgeCount"] == 0 and raw.nodes_of(op.vid("v-empty")) == {}
        raw.q("MATCH (m:ZgVersion {versionId: $v}) DELETE m", v=op.vid("v-empty"))
        op.withheld(op.graph("read", op.sel("v-empty"), expected=2), "v-empty", "graph_version_corrupt")
        checks.append("empty: zero eligible relations is a valid empty version (marker with 0/0, read returns empty lists with verification); a missing marker is a withheld failure, not an empty result")

        # 13. Review state: a newer review never mutates a ready version and never lets a frozen one be written.
        op.freeze("v-rv-ready", "rel-review")
        op.graph("project", op.sel("v-rv-ready"))
        op.freeze("v-rv-frozen", "rel-review")
        held = find(jobs["rel-review"], "SHARES_ISSUE")
        reviewed = op.kit.rel("review", {**op.kit.rsel("rel-review"), "relationCandidateId": held["relationCandidateId"], "expectedRevision": held["eligibility"]["revision"],
                                         "decision": "allow", "reviewer": "operator-a", "note": "authored review"})
        assert find(reviewed, "SHARES_ISSUE")["eligibility"]["reviewPending"] is True
        out = op.graph("read", op.sel("v-rv-ready"))
        assert out["delivery"]["status"] == "current" and out["current"] == {"s3ReviewDigestMatches": False}, out["current"]
        op.error(op.graph("project", op.sel("v-rv-frozen"), expected=2), "review_revision_changed")
        failed = op.state("v-rv-frozen")
        assert failed["state"] == "frozen" and failed["failure"]["code"] == "review_revision_changed" and raw.nodes_of(op.vid("v-rv-frozen")) == {}
        checks.append("review: after an admin allow on the HOLD candidate the ready version stays served (s3ReviewDigestMatches=false) while the frozen one refuses to project "
                      "(review_revision_changed) and writes nothing")

        # 14. Hostile identifiers are data: refused before any state, or stored literally and never executed.
        ledger_before, graph_before = op.ledger(), raw.count("MATCH (n) RETURN count(n) AS c")
        hostile = ("x'}) DETACH DELETE n //", "v1' OR 1=1 //", '"; MATCH (n) DETACH DELETE n; //', "v1|kr-000100", "a b", "é", "v" * 201, "")
        for text in hostile:
            for command, body in (("project", {"schemaVersion": SCHEMA, "versionId": text}), ("inspect", {"schemaVersion": SCHEMA, "versionId": text}),
                                  ("focus", {"schemaVersion": SCHEMA, "versionId": op.vid("v1"), "companyId": text, "depth": 1}),
                                  ("freeze", {"schemaVersion": SCHEMA, "versionId": text, "relation": {"jobId": "rel-main", "inputDigest": "0" * 64}})):
                op.error(op.graph(command, body, expected=2), "input_or_configuration_invalid")
        for body in ({"schemaVersion": SCHEMA, "versionId": op.vid("v1"), "companyId": "kr-000100", "depth": 4}, {"schemaVersion": SCHEMA, "versionId": op.vid("v1"), "companyId": "kr-000100", "depth": True},
                     {"schemaVersion": SCHEMA, "versionId": op.vid("v1"), "companyId": "kr-000100", "depth": "2"}, {"schemaVersion": SCHEMA, "versionId": op.vid("v1"), "extra": 1}):
            op.error(op.graph("focus", body, expected=2), "input_or_configuration_invalid")
        op.error(op.graph("inspect", op.sel("v1"), raw_input=b"x" * 70_000, expected=2), "command_input_limit")
        assert op.ledger() == ledger_before and raw.count("MATCH (n) RETURN count(n) AS c") == graph_before
        from zoop_ai_pipeline import graph_neo4j as neo
        from zoop_ai_pipeline.graph_projection_contracts import ExtractionFailure
        adapter = neo.Graph(uri, database, None if os.environ["ZOOP_GRAPH_AUTH"] == "none" else (os.environ["ZOOP_GRAPH_USER"], os.environ["ZOOP_GRAPH_PASSWORD"]))
        try:
            for text in hostile[:4]:
                with adapter.transaction(write=False) as tx:
                    assert neo.presence(tx, text) == ([], False)
                    try:
                        neo.observe(tx, text)
                        raise AssertionError("a missing version must not observe")
                    except neo.Mismatch:
                        pass
                with adapter.transaction(write=True) as tx:   # never committed: closing rolls it back
                    neo.write_nodes(tx, text, "ZgCompany", [text])
                    rows = neo.run(tx, neo.READ_OWNED_NODES, v=text, prefix=neo.node_key(text, ""), cap=5)
                    assert len(rows) == 1 and rows[0]["p"]["id"] == text and rows[0]["p"]["v"] == text, rows   # stored LITERALLY as data, never executed
            with adapter.transaction(write=True) as tx:
                try:
                    neo.run(tx, "MATCH (n) DETACH DELETE n")
                    raise AssertionError("an unregistered statement reached the server")
                except ExtractionFailure as exc:
                    assert exc.code == "graph_internal_failure"
        finally:
            adapter.close()
        assert raw.count("MATCH (n) RETURN count(n) AS c") == graph_before and raw.dump(op.vid("v1")) == dump_v1
        checks.append("hostile IDs: injection-shaped version/company/store IDs are refused by the wire contract before any state; through the real adapter they are parameters "
                      "(stored literally inside a rolled-back transaction, never executed), and an unregistered statement is refused before the server; v1 unchanged")

        # 15. Nothing downstream wrote upstream state, nothing called a model, nothing left the loopback Neo4j socket.
        assert {n: tree(root / n) for n in ("ingestion", "extraction")} == sources_before
        everything = "\n".join(op.outputs)
        assert not [text for text in PRIVATE if text in everything], [text for text in PRIVATE if text in everything]
        assert '"quote"' not in everything and "https://" not in everything and "evidenceId" in everything
        assert os.environ.get("ZOOP_GRAPH_PASSWORD", "\0") not in everything
        checks.append("isolation: ingestion/extraction ledgers byte/mode/mtime unchanged; no source quote, title, URL, review note or model text in any output of the run; every CLI "
                      "subprocess ran under a socket audit hook that allowed only the Neo4j endpoint; providerCalls=0, modelCalls=0")
        return {"status": "passed", "schemaVersion": SCHEMA, "runId": run, "checks": checks, "providerCalls": 0, "modelCalls": 0,
                "neo4j": "versions created by this run remain in the throwaway database; dispose it (or run --cleanup) - this smoke never wipes global data"}
    finally:
        raw.close()


def cleanup(uri: str, database: str, run: str) -> dict:
    """Targeted recovery by NAME: removes only nodes/edges/markers whose version identity starts with this run's prefix and the store marker with this run's
    exact store ID. Schema objects are left (re-initialisation tolerates them). Never a global wipe."""
    raw = Raw(uri, database)
    try:
        prefix = f"{run}-"
        removed = raw.count("MATCH (n) WHERE n.v STARTS WITH $p RETURN count(n) AS c", p=prefix)
        raw.q("MATCH (n) WHERE n.v STARTS WITH $p DETACH DELETE n", p=prefix)
        raw.q("MATCH (m:ZgVersion) WHERE m.versionId STARTS WITH $p DELETE m", p=prefix)
        raw.q("MATCH (s:ZgStore {storeId: $s}) DELETE s", s=f"{run}-store")
        return {"status": "cleaned", "runId": run, "versionNodesRemoved": removed, "remainingNodes": raw.count("MATCH (n) RETURN count(n) AS c")}
    finally:
        raw.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=f"smoke{uuid.uuid4().hex[:8]}")
    parser.add_argument("--cleanup", metavar="RUN_ID")
    args = parser.parse_args()
    uri, database = os.environ.get("ZOOP_GRAPH_SMOKE_URI"), os.environ.get("ZOOP_GRAPH_SMOKE_DATABASE", "neo4j")
    if not uri or os.environ.get("ZOOP_GRAPH_AUTH") not in {"none", "basic"}:
        raise SystemExit("ZOOP_GRAPH_SMOKE_URI and ZOOP_GRAPH_AUTH (none|basic, plus ZOOP_GRAPH_USER/ZOOP_GRAPH_PASSWORD) are required: this smoke does not skip")
    if args.cleanup:
        print(json.dumps(cleanup(uri, database, args.cleanup), ensure_ascii=False, indent=2))
        return
    print(f"run id: {args.run_id} (targeted recovery: --cleanup {args.run_id})", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix="zoop-graph-smoke-") as temporary:
        root = Path(temporary).resolve()
        result = smoke(root, uri, database, args.run_id)
    assert not root.exists()
    result["temporaryStateCleanup"] = {"removed": True, "root": str(root)}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
