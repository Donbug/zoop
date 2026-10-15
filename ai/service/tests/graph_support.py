"""Harness for the read-only graph door: a workspace with every server-owned input of the graph group, a test-owned stand-in for `zoop-ai-graph`
and pipeline-shaped outputs. The stand-in only records what the service passed it (argv, stdin, environment, working directory, timing) and answers
what a test scripted, so the service's argv, environment, interpretation, projection, allowlist and gating are proven without a Neo4j. The real
installed `zoop-ai-graph` and a real Neo4j are exercised by `pipeline_tests/test_graph_real_cli.py` and `scripts/graph_service_smoke.py`.
"""
from __future__ import annotations

import copy
import json
import secrets
import sys
from pathlib import Path
from typing import Any

from support import Workspace, canonical, merged_grants

SCHEMA = "zoop-graph-projection-1"
VERSIONS_SCHEMA = "zoop-ai-graph-versions-1"
CANONICAL_SCHEMA = "zoop-graph-canonical-1"
VERSION = "graph-main-1"
OTHER_VERSION = "graph-split-1"
GRAPH_DIGEST = "a" * 64
PAYLOAD_DIGEST = "b" * 64
RELATION_JOB = "relation-job-1"
RELATION_DIGEST = "c" * 64
USAGE = {"providerCalls": 0, "modelCalls": 0}
GRAPH_VARS = ("ZOOP_AI_SERVICE_GRAPH_COMMAND", "ZOOP_AI_GRAPH_STATE_DIR", "ZOOP_AI_GRAPH_RELATION_STATE_DIR", "ZOOP_AI_GRAPH_EXTRACTION_STATE_DIR",
              "ZOOP_AI_GRAPH_INGESTION_STATE_DIR", "ZOOP_AI_SERVICE_GRAPH_SOURCES", "ZOOP_AI_SERVICE_GRAPH_CANONICAL", "ZOOP_AI_SERVICE_GRAPH_VERSIONS",
              "ZOOP_GRAPH_AUTH")

STUB = '''#!__PYTHON__
import json, os, signal, sys, time
ROOT = __ROOT__
raw = sys.stdin.read()
behavior = json.load(open(ROOT + "/behavior.json"))
call = {"argv": sys.argv[1:], "stdin": raw, "env": dict(os.environ), "cwd": os.getcwd(), "pid": os.getpid(), "t0": time.time()}
if behavior.get("rewrite"):
    open(behavior["rewrite"]["path"], "w").write(behavior["rewrite"]["content"])
mode = behavior.get("mode", "result")
if mode == "sleep":
    time.sleep(behavior["seconds"])
call["t1"] = time.time()
with open(ROOT + "/calls.jsonl", "a") as handle:
    handle.write(json.dumps(call) + "\\n")
if mode == "die":
    os.kill(os.getpid(), signal.SIGKILL)
if mode == "raw":
    sys.stdout.write(behavior["raw"])
    sys.exit(behavior["exit"])
out = behavior["output"]
request = json.loads(raw)
if behavior.get("echo", True) and "focus" in out:
    out["focus"]["companyId"], out["focus"]["depth"] = request["companyId"], request["depth"]
print(json.dumps(out, sort_keys=True, separators=(",", ":")))
sys.exit(behavior.get("exit", 0))
'''

# The authored graph: B supplies A, C invests in B, A competes with D (an island of its own is not needed). Three companies and one event.
NODES = (("company", "kr-000100"), ("company", "kr-000300"), ("company", "kr-000400"), ("event", "event:main-event"))
EDGES = (
    {"relationId": "rel-" + "1" * 64, "type": "SUPPLIES", "direction": "directed", "connection": "direct",
     "subject": {"kind": "company", "id": "kr-000300"}, "object": {"kind": "company", "id": "kr-000100"}, "businessScope": "합성 부품", "productScope": None,
     "validity": {"from": None, "until": None}, "countries": ["KR"], "path": {"companyIds": []},
     "evidence": {"relation": ["ev-" + "1" * 64], "validity": [], "steps": [[], []]}, "sourceRelationCandidateIds": ["rc-" + "1" * 64]},
    {"relationId": "rel-" + "2" * 64, "type": "INVESTS_IN", "direction": "directed", "connection": "direct",
     "subject": {"kind": "company", "id": "kr-000400"}, "object": {"kind": "company", "id": "kr-000300"}, "businessScope": None, "productScope": None,
     "validity": {"from": "2026-01-01", "until": None}, "countries": [], "path": {"companyIds": []},
     "evidence": {"relation": ["ev-" + "2" * 64], "validity": ["ev-" + "3" * 64], "steps": [[], []]}, "sourceRelationCandidateIds": ["rc-" + "2" * 64]},
    {"relationId": "rel-" + "3" * 64, "type": "PARTICIPATES_IN", "direction": "directed", "connection": "direct",
     "subject": {"kind": "company", "id": "kr-000100"}, "object": {"kind": "event", "id": "event:main-event"}, "businessScope": None, "productScope": None,
     "validity": {"from": None, "until": None}, "countries": [], "path": {"companyIds": []},
     "evidence": {"relation": ["ev-" + "1" * 64], "validity": [], "steps": [[], []]}, "sourceRelationCandidateIds": ["rc-" + "3" * 64]},
)
EVIDENCE = tuple({"evidenceId": "ev-" + digit * 64, "documentId": "synthetic-doc-1", "documentVersion": "v1", "rawVersion": "raw-1", "start": 10 * index,
                  "end": 10 * index + 8} for index, digit in enumerate("123"))
PRIVATE_KEYS = frozenset({"upstream", "attempts", "audit", "canonical", "counts", "reviewDigest", "failure", "next", "provenance", "current", "digests",
                          "source", "usage", "inputDigest", "jobId"})


def view(company: str, depth: int) -> dict[str, Any]:
    """The pipeline's focus semantics over the authored graph: undirected breadth-first, an edge is shown iff one endpoint is closer than `depth`."""
    adjacency: dict[tuple[str, str], set[tuple[str, str]]] = {node: set() for node in NODES}
    for edge in EDGES:
        a, b = (edge["subject"]["kind"], edge["subject"]["id"]), (edge["object"]["kind"], edge["object"]["id"])
        adjacency[a].add(b)
        adjacency[b].add(a)
    start = ("company", company)
    if start not in adjacency:
        return {"found": False, "nodes": [], "edges": []}
    distance = {start: 0}
    frontier = [start]
    for step in range(1, depth + 1):
        following = []
        for node in frontier:
            for other in sorted(adjacency[node]):
                if other not in distance:
                    distance[other] = step
                    following.append(other)
        frontier = following
    shown = [e for e in EDGES if min(distance.get((e["subject"]["kind"], e["subject"]["id"]), depth + 1),
                                    distance.get((e["object"]["kind"], e["object"]["id"]), depth + 1)) <= depth - 1]
    return {"found": True, "nodes": [{"kind": kind, "id": ident, "distance": d} for (kind, ident), d in sorted(distance.items())], "edges": shown}


def _ledger(version: str, graph: str, payload: str, relation: tuple[str, str]) -> dict[str, Any]:
    return {"schemaVersion": SCHEMA, "versionId": version, "state": "ready", "publication": "not-published", "next": "read", "failure": None,
            "source": {"provenance": {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"},
                       "relation": {"jobId": relation[0], "inputDigest": relation[1]},
                       "upstream": {"jobId": "s2-private-upstream", "inputDigest": "d" * 64, "digest": "e" * 64}, "reviewDigest": "f" * 64},
            "canonical": {"entries": 3, "digest": "9" * 64},
            "counts": {"nodes": {"company": 3, "event": 1, "topic": 0}, "edges": {"SUPPLIES": 1}, "evidence": 3},
            "audit": {"s3Relations": 9, "projectedCandidates": 3}, "digests": {"payload": payload, "graph": graph},
            "attempts": [{"n": 1, "outcome": "committed", "code": None}], "usage": dict(USAGE)}


def _verification(graph: str) -> dict[str, Any]:
    return {"marker": "matched", "graphDigest": graph, "nodes": len(NODES), "edges": len(EDGES)}


def read_output(version: str = VERSION, *, graph: str = GRAPH_DIGEST, payload: str = PAYLOAD_DIGEST, relation: tuple[str, str] = (RELATION_JOB, RELATION_DIGEST)) -> dict:
    """A current `read` result: everything the pipeline reports, including what the service must not relay."""
    return {**_ledger(version, graph, payload, relation),
            "delivery": {"status": "current", "authority": "S3/S2 authority, canonical decisions, review state and the full stored graph verified now"},
            "current": {"s3ReviewDigestMatches": True},
            "graph": {"nodes": [{"kind": kind, "id": ident} for kind, ident in NODES], "edges": copy.deepcopy(list(EDGES))}, "evidence": copy.deepcopy(list(EVIDENCE)),
            "verification": _verification(graph)}


def focus_output(version: str = VERSION, company: str = "kr-000100", depth: int = 1, *, graph: str = GRAPH_DIGEST, payload: str = PAYLOAD_DIGEST,
                 relation: tuple[str, str] = (RELATION_JOB, RELATION_DIGEST)) -> dict:
    shown = view(company, depth)
    referenced = {i for e in shown["edges"] for i in (*e["evidence"]["relation"], *e["evidence"]["validity"], *e["evidence"]["steps"][0], *e["evidence"]["steps"][1])}
    return {**read_output(version, graph=graph, payload=payload, relation=relation), "focus": {"companyId": company, "depth": depth, "found": shown["found"]},
            "graph": {"nodes": shown["nodes"], "edges": copy.deepcopy(shown["edges"])},
            "evidence": copy.deepcopy([e for e in EVIDENCE if e["evidenceId"] in referenced])}


def withheld_output(version: str = VERSION, code: str = "source_unauthorized", state: str = "ready") -> dict:
    return {"schemaVersion": SCHEMA, "versionId": version, "state": state, "publication": "not-published", "delivery": {"status": "withheld", "code": code},
            "usage": dict(USAGE)}


def error_output(code: str, detail: dict | None = None) -> dict:
    return {"schemaVersion": SCHEMA, "error": {"code": code, **({"detail": detail} if detail else {})}}


def version_entry(principal: str = "grapher", version: str = VERSION, graph: str = GRAPH_DIGEST, payload: str = PAYLOAD_DIGEST, **extra: Any) -> dict:
    return {"principal": principal, "versionId": version, "graphDigest": graph, "payloadDigest": payload, **extra}


class GraphWorkspace(Workspace):
    """One service's fresh state with every server-owned input of the graph group over throwaway files and a scripted stand-in command."""

    def __init__(self, root: Path, *, with_relation: bool = False, command: Path | None = None, auth: dict[str, str] | None = None,
                 versions: list[dict] | None = None):
        super().__init__(root, replay=None, grants=merged_grants())
        self.with_relation = with_relation
        self.graph_state, self.relation_state = root / "graph", root / "relation"
        self.extraction_state, self.ingestion_state, self.app_state = root / "extraction", root / "ingestion", root / "app"
        for directory in (self.graph_state, self.relation_state, self.extraction_state, self.ingestion_state, self.app_state):
            directory.mkdir()
        self.sources, self.canonical = root / "sources.json", root / "canonical.json"
        self.versions = root / "versions.json"
        self.producer, self.verifier, self.upstreams = root / "producer.json", root / "verifier.json", root / "upstreams.json"
        self.sources.write_text("{}", encoding="utf-8")
        self.canonical.write_text(canonical({"schemaVersion": CANONICAL_SCHEMA, "entries": []}), encoding="utf-8")
        for path in (self.producer, self.verifier):
            path.write_text("{}", encoding="utf-8")
        self.upstreams.write_text(canonical({"schemaVersion": "zoop-ai-relation-upstreams-1", "upstreams": []}), encoding="utf-8")
        self.write_versions(versions if versions is not None else [version_entry()])
        self.password = "pw-" + secrets.token_urlsafe(20)
        self.user = "neo-" + secrets.token_urlsafe(10)
        self.auth = auth if auth is not None else {"ZOOP_GRAPH_AUTH": "basic", "ZOOP_GRAPH_USER": self.user, "ZOOP_GRAPH_PASSWORD": self.password}
        self.calls_path, self.behavior_path = root / "calls.jsonl", root / "behavior.json"
        self.command = command or self.write_stub()

    # ---- the scripted stand-in ----

    def write_stub(self) -> Path:
        script = self.root / "zoop-ai-graph-stub.py"
        script.write_text(STUB.replace("__PYTHON__", sys.executable).replace("__ROOT__", repr(str(self.root))), encoding="utf-8")
        script.chmod(0o755)
        self.script({"mode": "result", "output": read_output()})
        return script

    def script(self, behavior: dict[str, Any]) -> None:
        self.behavior_path.write_text(json.dumps(behavior), encoding="utf-8")

    def calls(self) -> list[dict[str, Any]]:
        if not self.calls_path.exists():
            return []
        return [json.loads(line) for line in self.calls_path.read_text(encoding="utf-8").splitlines()]

    # ---- operator inputs ----

    def write_versions(self, entries: list[dict]) -> None:
        self.versions.write_text(canonical({"schemaVersion": VERSIONS_SCHEMA, "versions": entries}), encoding="utf-8")

    def env(self, **overrides: str | None) -> dict[str, str]:
        env = super().env()
        env.update({
            "ZOOP_STATE_DIR": str(self.app_state), "ZOOP_AI_SERVICE_GRAPH_COMMAND": str(self.command), "ZOOP_AI_GRAPH_STATE_DIR": str(self.graph_state),
            "ZOOP_AI_GRAPH_RELATION_STATE_DIR": str(self.relation_state), "ZOOP_AI_GRAPH_EXTRACTION_STATE_DIR": str(self.extraction_state),
            "ZOOP_AI_GRAPH_INGESTION_STATE_DIR": str(self.ingestion_state), "ZOOP_AI_SERVICE_GRAPH_SOURCES": str(self.sources),
            "ZOOP_AI_SERVICE_GRAPH_CANONICAL": str(self.canonical), "ZOOP_AI_SERVICE_GRAPH_VERSIONS": str(self.versions), **self.auth})
        if self.with_relation:   # an S3 group over the SAME roots: the graph then shares its gate
            env.update({"ZOOP_AI_SERVICE_RELATION_COMMAND": sys.executable, "ZOOP_AI_RELATION_STATE_DIR": str(self.relation_state),
                        "ZOOP_AI_EXTRACTION_STATE_DIR": str(self.extraction_state), "ZOOP_AI_INGESTION_STATE_DIR": str(self.ingestion_state),
                        "ZOOP_AI_SERVICE_SOURCES": str(self.sources), "ZOOP_AI_SERVICE_RELATION_REPLAY": str(self.producer),
                        "ZOOP_AI_SERVICE_RELATION_VERIFIER_REPLAY": str(self.verifier), "ZOOP_AI_SERVICE_RELATION_UPSTREAMS": str(self.upstreams)})
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    def private_strings(self) -> list[str]:
        return [*super().private_strings(), str(self.graph_state), str(self.relation_state), str(self.extraction_state), str(self.ingestion_state),
                str(self.app_state), str(self.sources), str(self.canonical), str(self.versions), str(self.command), self.password, self.user]


GRAPH = "/internal/v1/graph-versions"


def status_url(version: str = VERSION) -> str:
    return f"{GRAPH}/{version}"


def focus_url(version: str = VERSION, company: str = "kr-000100", depth: int | str = 1) -> str:
    return f"{GRAPH}/{version}/focus?companyId={company}&depth={depth}"
