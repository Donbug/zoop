#!/usr/bin/env python3
"""Actual-Neo4j adversarial check of `graph_tool_bench.py cleanup` (test only; it changes no production code).

Needs the pipeline interpreter and a FRESH EMPTY throwaway Neo4j database (prepare refuses a non-empty one):

    export ZOOP_GRAPH_SMOKE_URI=bolt://127.0.0.1:<port> ZOOP_GRAPH_AUTH=none      # basic: ZOOP_GRAPH_USER / ZOOP_GRAPH_PASSWORD
    ai/pipeline/.venv/bin/python ai/evaluation/scripts/graph_tool_cleanup_adversarial.py [--other-uri bolt://127.0.0.1:<port2>]

--other-uri is an OPTIONAL second empty throwaway instance (same auth). Without it the "wrong live target" case is only exercised against a closed
loopback port and the report says `otherLiveInstance: false`; the dangerous variant (a live database that holds a colliding identity) is then NOT proven.

What it does, in its own temp directory and with its own run id (it never touches another run's state):
  1. `prepare` a fresh owned world, then plant a SAME-PREFIX version `<run>-main-extra` (marker + company node) that the manifest does not own.
  2. Wrong target: cleanup with the environment pointing at another port, another database name and (if given) a live second instance that holds
     a colliding `<run>-main` identity. Each must exit non-zero, keep the owned root and manifest, and leave BOTH databases byte-for-byte unchanged.
  3. Correct target: cleanup must exit 0, remove exactly the two manifest versions and the exact store marker and the owned root, and leave the
     same-prefix extra version (marker + node) alive. Nothing else may remain.
  4. Remove only what this script planted, by exact identity. Exit 0 iff every check passed, else 1.

Prints one JSON report (no URIs, paths or credentials). It never wipes a database.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

BENCH = Path(__file__).resolve().parent / "graph_tool_bench.py"
ZERO = "0" * 64


class Graph:
    def __init__(self, uri: str, database: str):
        from neo4j import GraphDatabase, basic_auth
        auth = basic_auth(os.environ["ZOOP_GRAPH_USER"], os.environ["ZOOP_GRAPH_PASSWORD"]) if os.environ["ZOOP_GRAPH_AUTH"] == "basic" else None
        self.driver, self.database = GraphDatabase.driver(uri, auth=auth), database

    def q(self, cypher: str, **params) -> list[dict]:
        with self.driver.session(database=self.database) as session:
            return [record.data() for record in session.run(cypher, params)]

    def count(self) -> int:
        return self.q("MATCH (n) RETURN count(n) AS c")[0]["c"]

    def plant(self, version: str, store: str) -> None:
        """An unowned same-prefix version: a marker plus one company node, shaped like the real ones."""
        self.q("CREATE (:ZgVersion {versionId: $v, schema: 'zoop-graph-version-1', storeId: $s, payloadDigest: $z, graphDigest: $z, nodeCount: 1, edgeCount: 0})",
               v=version, s=store, z=ZERO)
        self.q("CREATE (:ZgCompany {vk: $vk, v: $v, id: 'kr-000100'})", vk=f"{version}|kr-000100", v=version)

    def present(self, version: str) -> tuple[int, int]:
        return (self.q("MATCH (m:ZgVersion {versionId: $v}) RETURN count(m) AS c", v=version)[0]["c"],
                self.q("MATCH (n) WHERE n.v = $v RETURN count(n) AS c", v=version)[0]["c"])

    def remove(self, version: str) -> None:
        self.q("MATCH (n) WHERE n.v = $v DETACH DELETE n", v=version)
        self.q("MATCH (m:ZgVersion {versionId: $v}) DELETE m", v=version)

    def fingerprint(self) -> str:
        nodes = self.q("MATCH (n) RETURN labels(n) AS l, properties(n) AS p")
        edges = self.q("MATCH (a)-[e]->(b) RETURN type(e) AS t, properties(e) AS p, elementId(a) AS a, elementId(b) AS b")
        return json.dumps(sorted(json.dumps(x, sort_keys=True, default=str) for x in (*nodes, *edges)))

    def close(self) -> None:
        self.driver.close()


def bench(*argv: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(BENCH), *argv], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env or os.environ.copy(), timeout=1800)


def redacted_failure(child: subprocess.CompletedProcess) -> dict:
    """Expose only the benchmark command's stable stage/code fields, never stderr, paths, URIs or credentials."""
    diagnostic = {"exitCode": child.returncode, "code": "unstructured_failure", "stage": "unknown"}
    try:
        document = json.loads(child.stdout.decode("utf-8"))
        error = document.get("error")
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return diagnostic
    if not isinstance(error, dict):
        return diagnostic
    for key in ("code", "stage", "errorCode"):
        value = error.get(key)
        if isinstance(value, str) and 1 <= len(value) <= 80 and all(character.isalnum() or character in "_-" for character in value):
            diagnostic[key] = value
    return diagnostic


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--other-uri", help="optional second EMPTY throwaway instance (same auth) for the live wrong-target case")
    args = parser.parse_args()
    uri, database = os.environ.get("ZOOP_GRAPH_SMOKE_URI"), os.environ.get("ZOOP_GRAPH_SMOKE_DATABASE", "neo4j")
    if not uri or os.environ.get("ZOOP_GRAPH_AUTH") not in {"none", "basic"}:
        raise SystemExit("ZOOP_GRAPH_SMOKE_URI and ZOOP_GRAPH_AUTH (none|basic, plus ZOOP_GRAPH_USER/ZOOP_GRAPH_PASSWORD) are required")
    run = f"adv{uuid.uuid4().hex[:8]}"
    tmp = Path(tempfile.mkdtemp(prefix="zoop-gtb-adv-"))
    root, manifest_path = tmp / "root", tmp / "manifest.json"
    checks: list[dict] = []

    def check(name: str, passed: bool) -> None:
        checks.append({"check": name, "passed": bool(passed)})

    graph, other = Graph(uri, database), (Graph(args.other_uri, database) if args.other_uri else None)
    extra, store = f"{run}-main-extra", f"{run}-store"
    try:
        prepared = bench("prepare", "--root", str(root), "--manifest", str(manifest_path), "--run-id", run)
        check("prepare succeeds on an empty database", prepared.returncode == 0)
        if prepared.returncode != 0:
            print(json.dumps({"status": "FAILED", "runId": run, "checks": checks, "prepareFailure": redacted_failure(prepared),
                              "ownedStateRootStillPresent": root.is_dir(), "manifestStillPresent": manifest_path.is_file()}, indent=1))
            return 1
        manifest = json.loads(manifest_path.read_text("utf-8"))
        owned_versions = sorted(manifest["versions"].values())
        graph.plant(extra, store)
        if other:
            other.plant(f"{run}-main", f"{run}-store")   # a colliding identity in the wrong live target
        before_graph, before_other = graph.fingerprint(), (other.fingerprint() if other else None)

        port = urlsplit(uri).port
        wrong = {
            "another port (closed)": {"ZOOP_GRAPH_SMOKE_URI": f"bolt://127.0.0.1:{port + 1}"},
            "another database name": {"ZOOP_GRAPH_SMOKE_DATABASE": f"{database}-adversarial-other"},
        }
        if args.other_uri:
            wrong["another live instance holding a colliding identity"] = {"ZOOP_GRAPH_SMOKE_URI": args.other_uri}
        for label, override in wrong.items():
            result = bench("cleanup", "--manifest", str(manifest_path), env={**os.environ, **override})
            check(f"wrong target ({label}): exits non-zero", result.returncode != 0)
            check(f"wrong target ({label}): owned root and manifest kept", root.is_dir() and manifest_path.is_file())
            check(f"wrong target ({label}): prepared database unchanged", graph.fingerprint() == before_graph)
            if other:
                check(f"wrong target ({label}): other instance unchanged", other.fingerprint() == before_other)

        result = bench("cleanup", "--manifest", str(manifest_path))
        check("correct target: exits 0", result.returncode == 0)
        check("correct target: owned root removed, manifest kept", not root.exists() and manifest_path.is_file())
        check("correct target: both manifest versions gone", all(graph.present(v) == (0, 0) for v in owned_versions))
        check("correct target: exact store marker gone", graph.q("MATCH (s:ZgStore {storeId: $s}) RETURN count(s) AS c", s=store)[0]["c"] == 0)
        check("correct target: same-prefix unowned version survives (marker and node)", graph.present(extra) == (1, 1))
        check("correct target: nothing else remains", graph.count() == 2)
    finally:
        graph.remove(extra)
        if other:
            other.remove(f"{run}-main")
            other.close()
        remaining = graph.count()
        graph.close()
    state_kept = root.exists()
    if not state_kept:
        shutil.rmtree(tmp, ignore_errors=True)
    failed = [c["check"] for c in checks if not c["passed"]]
    print(json.dumps({"status": "FAILED" if failed else "passed", "runId": run, "otherLiveInstance": bool(args.other_uri), "failedChecks": failed,
                      "checks": checks, "nodesLeftAfterOwnPlantsRemoved": remaining, "ownedStateRootStillPresent": state_kept}, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
