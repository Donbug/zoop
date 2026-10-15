#!/usr/bin/env python3
"""Deterministic baseline of the nonpublic `zoop-ai-graph` tool on a synthetic authored-replay world. Four commands:

  prepare  build a fresh OWNED synthetic world (actual ingestion + S2 + S3 through the existing CLIs), `init` an EMPTY Neo4j database, `freeze` + `project`
           two versions, write a manifest. Run with the pipeline interpreter (ai/pipeline/.venv/bin/python): it imports the hand-authored world builder of
           ai/pipeline/scripts. It never calls the projection smoke (which corrupts the graph on purpose) and never wipes a database.
  measure  stdlib only. Invoke the installed `zoop-ai-graph` as a real subprocess per attempt from the manifest and write a measurement record
           (`zoop-graph-tool-run-1`). It never opens the expectation file and never scores.
  score    stdlib only. Score a measurement record against the hand-authored expectation (`fixtures/graph-tool/expected.json`) and write JSON/Markdown.
  cleanup  remove exactly what `prepare` created (this run's Neo4j versions/store marker by name, the owned state directory). Pipeline interpreter.

What is measured is the CLI invocation wall time (including interpreter start, authority gates, SQLite ledger, Bolt verification of the WHOLE stored version
and an in-memory undirected BFS) and the neighborhood it returns. It is not Neo4j traversal speed, RAG/agent answer quality or directed supply-chain reasoning.
Neo4j credentials come only from ZOOP_GRAPH_AUTH (none|basic) / ZOOP_GRAPH_USER / ZOOP_GRAPH_PASSWORD; prepare/cleanup also need ZOOP_GRAPH_SMOKE_URI
(bolt://127.0.0.1:<port>) and optionally ZOOP_GRAPH_SMOKE_DATABASE (default neo4j). No credential, URI or path is written to any record or report.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

EVALUATION = Path(__file__).resolve().parents[1]
PIPELINE = EVALUATION.parent / "pipeline"
FIXTURES = EVALUATION / "fixtures" / "graph-tool"
MARKER = ".zoop-graph-tool-owned"
sys.path.append(str(EVALUATION))   # appended: for `prepare`, ai/pipeline's `scripts` package must win

from zoop_eval import graph_tool as gt  # noqa: E402
from zoop_eval.contracts import Rejected, read_json  # noqa: E402

TOOL_SOURCES = ("graph_projection.py", "graph_projection_cli.py", "graph_projection_contracts.py", "graph_neo4j.py")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class PrepareFailed(Exception):
    """A redacted prepare-stage failure suitable for the subprocess JSON contract."""

    def __init__(self, stage: str, error_code: str):
        self.stage = stage
        self.error_code = error_code
        super().__init__(error_code)


def _prepare_error_code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and 1 <= len(code) <= 80 and all(character.isalnum() or character in "_-" for character in code):
        return code
    return "system_exit" if isinstance(error, SystemExit) else type(error).__name__


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def neo4j_env() -> tuple[str, str]:
    uri, database = os.environ.get("ZOOP_GRAPH_SMOKE_URI"), os.environ.get("ZOOP_GRAPH_SMOKE_DATABASE", "neo4j")
    if not uri or os.environ.get("ZOOP_GRAPH_AUTH") not in {"none", "basic"}:
        raise SystemExit("ZOOP_GRAPH_SMOKE_URI and ZOOP_GRAPH_AUTH (none|basic, plus ZOOP_GRAPH_USER/ZOOP_GRAPH_PASSWORD) are required")
    parts = urlsplit(uri)
    if parts.hostname not in LOOPBACK or not parts.port:
        raise SystemExit("ZOOP_GRAPH_SMOKE_URI must be a loopback bolt://127.0.0.1:<port> endpoint")
    return uri, database


def write_json(path: Path, document: dict, *, exclusive: bool) -> None:
    mode = "x" if exclusive else "w"
    with open(path, mode, encoding="utf-8") as handle:
        handle.write(json.dumps(document, indent=1, ensure_ascii=False) + "\n")


_DB_INFO = "CALL db.info() YIELD id, name RETURN id, name LIMIT 2"
_COMPONENTS = "CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition LIMIT 2"
_STORES = "MATCH (s) WHERE 'ZgStore' IN labels(s) RETURN labels(s) AS labels, properties(s) AS props LIMIT 3"
_VERSION_MARKERS = "MATCH (m) WHERE m.versionId IN $versions RETURN labels(m) AS labels, properties(m) AS props LIMIT 3"
_CLAIMED_NODES = (
    "MATCH (n) WHERE n.v IN $versions OR any(v IN $versions WHERE n.vk STARTS WITH v + '|') "
    "RETURN count(n) AS total, sum(CASE WHEN size(labels(n)) = 1 AND labels(n)[0] IN $labels "
    "AND n.v IN $versions AND n.vk STARTS WITH n.v + '|' THEN 0 ELSE 1 END) AS invalid"
)
_CLAIMED_EDGES = (
    "MATCH (a)-[e]->(b) WHERE e.v IN $versions OR any(v IN $versions WHERE e.vk STARTS WITH v + '|') "
    "RETURN count(e) AS total, sum(CASE WHEN type(e) IN $types AND e.v IN $versions AND e.vk STARTS WITH e.v + '|' "
    "AND a.v = e.v AND b.v = e.v THEN 0 ELSE 1 END) AS invalid"
)
_INCIDENT_EDGES = (
    "MATCH (n)-[e]-() WHERE n.v IN $versions WITH DISTINCT e "
    "RETURN count(e) AS total, sum(CASE WHEN type(e) IN $types AND e.v IN $versions AND e.vk STARTS WITH e.v + '|' "
    "AND startNode(e).v = e.v AND endNode(e).v = e.v THEN 0 ELSE 1 END) AS invalid"
)
_DELETE_EDGES = "MATCH ()-[e]->() WHERE e.v IN $versions DELETE e"
_DELETE_NODES = "MATCH (n) WHERE n.v IN $versions DELETE n"
_DELETE_VERSIONS = "MATCH (m:ZgVersion) WHERE m.versionId IN $versions DELETE m"
_DELETE_STORE = "MATCH (s:ZgStore {slot: $slot, storeId: $storeId, schema: $schema, owner: $owner}) DELETE s"
_REMAINING = (
    "OPTIONAL MATCH (m:ZgVersion) WHERE m.versionId IN $versions "
    "WITH count(m) AS markers OPTIONAL MATCH (n) WHERE n.v IN $versions "
    "WITH markers, count(n) AS nodes OPTIONAL MATCH ()-[e]->() WHERE e.v IN $versions "
    "RETURN markers, nodes, count(e) AS edges"
)
_STORE_REMAINING = "MATCH (s:ZgStore {slot: $slot, storeId: $storeId, schema: $schema, owner: $owner}) RETURN count(s) AS c"


def _one(tx, statement: str, **params) -> dict:
    rows = [record.data() for record in tx.run(statement, params)]
    if len(rows) != 1:
        raise RuntimeError("cleanup_query_shape")
    return rows[0]


def _rows(tx, statement: str, **params) -> list[dict]:
    return [record.data() for record in tx.run(statement, params)]


def _consume(tx, statement: str, **params) -> None:
    tx.run(statement, params).consume()


def _ledger_binding(manifest: dict, *, require_ready: bool) -> tuple[dict, list[tuple[str, str]]]:
    """Read the immutable cleanup authority from the prepared graph ledger, never from environment or manifest claims."""
    _, paths = gt.verify_prepared_ownership(manifest, directories=("stateDir",))
    database = paths["stateDir"] / "graph.sqlite3"
    gt.verify_prepared_ownership({**manifest, "_cleanupLedger": str(database)}, files=("_cleanupLedger",))
    try:
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            meta = {row["key"]: row["value"] for row in connection.execute(
                "SELECT key,value FROM meta WHERE key IN ('ledger','store','store-ready')"
            )}
            versions = [(str(row["version_id"]), str(row["state"])) for row in connection.execute(
                "SELECT version_id,state FROM versions ORDER BY version_id"
            )]
        finally:
            connection.close()
        binding = json.loads(meta["store"])
    except (OSError, sqlite3.Error, KeyError, TypeError, ValueError):
        raise RuntimeError("graph_cleanup_binding_missing") from None
    if require_ready and meta.get("store-ready") != gt.sha256_hex(gt.canonical_json(binding)):
        raise RuntimeError("graph_cleanup_binding_not_ready")
    required = {"uri", "database", "dbId", "storeId", "owner", "schema", "server"}
    if set(binding) != required or not all(isinstance(binding[key], str) and binding[key] for key in required - {"server"}):
        raise RuntimeError("graph_cleanup_binding_invalid")
    if not isinstance(binding["server"], dict):
        raise RuntimeError("graph_cleanup_binding_invalid")
    return binding, versions


def _verify_cleanup_identity(manifest: dict, uri: str, database: str, binding: dict, versions: list[tuple[str, str]], *, require_ready: bool) -> list[str]:
    from zoop_ai_pipeline import graph_neo4j as neo

    normalized_uri = neo.validate_uri(uri)
    if normalized_uri != binding["uri"] or database.lower() != binding["database"].lower():
        raise RuntimeError("graph_cleanup_target_mismatch")
    if manifest.get("database", database).lower() != binding["database"].lower():
        raise RuntimeError("graph_cleanup_manifest_database_mismatch")
    if urlsplit(normalized_uri).port != manifest.get("neo4jLoopbackPort"):
        raise RuntimeError("graph_cleanup_endpoint_mismatch")
    run_id = manifest["runId"]
    if binding["storeId"] != f"{run_id}-store":
        raise RuntimeError("graph_cleanup_store_mismatch")
    ledger_ids = [version_id for version_id, _ in versions]
    if len(ledger_ids) != len(set(ledger_ids)):
        raise RuntimeError("graph_cleanup_ledger_versions_invalid")
    allowed = {f"{run_id}-main", f"{run_id}-split"}
    if not set(ledger_ids) <= allowed:
        raise RuntimeError("graph_cleanup_ledger_versions_invalid")
    if require_ready:
        expected = {"main": f"{run_id}-main", "split": f"{run_id}-split"}
        if manifest.get("versions") != expected or set(ledger_ids) != set(expected.values()) or any(state != "ready" for _, state in versions):
            raise RuntimeError("graph_cleanup_manifest_versions_mismatch")
    return sorted(ledger_ids)


def _exact_graph_cleanup(uri: str, database: str, manifest: dict, *, require_ready: bool) -> dict:
    """Verify ledger, endpoint, database and store identity, then remove only exact ledger-owned versions in one transaction."""
    from zoop_ai_pipeline import graph_neo4j as neo
    from zoop_ai_pipeline.graph_projection_contracts import (
        ALLOWED_RELATIONSHIPS, LABELS, MARKER_KEYS, STORE_LABEL, STORE_SLOT, VERSION_LABEL, VERSION_SCHEMA,
    )

    binding, ledger_versions = _ledger_binding(manifest, require_ready=require_ready)
    versions = _verify_cleanup_identity(manifest, uri, database, binding, ledger_versions, require_ready=require_ready)
    graph = neo.Graph(binding["uri"], binding["database"], neo.read_auth(binding["uri"]))
    try:
        with graph.transaction(write=True) as tx:
            info = _rows(tx, _DB_INFO)
            components = _rows(tx, _COMPONENTS)
            stores = _rows(tx, _STORES)
            expected_store = {"slot": STORE_SLOT, "storeId": binding["storeId"], "schema": binding["schema"], "owner": binding["owner"]}
            expected_server = binding["server"]
            actual_server = None
            if len(components) == 1 and components[0].get("name") == "Neo4j Kernel" and components[0].get("versions"):
                actual_server = {"agent": f"Neo4j/{components[0]['versions'][0]}", "edition": components[0].get("edition")}
            if (len(info) != 1 or str(info[0].get("id")) != binding["dbId"]
                    or str(info[0].get("name", "")).lower() != binding["database"].lower()
                    or actual_server != expected_server
                    or stores != [{"labels": [STORE_LABEL], "props": expected_store}]):
                raise RuntimeError("graph_cleanup_live_binding_mismatch")

            markers = _rows(tx, _VERSION_MARKERS, versions=versions)
            by_version: dict[str, dict] = {}
            for row in markers:
                props = row.get("props")
                if (row.get("labels") != [VERSION_LABEL] or not isinstance(props, dict) or set(props) != MARKER_KEYS
                        or props.get("versionId") not in versions or props.get("schema") != VERSION_SCHEMA
                        or props.get("storeId") != binding["storeId"] or props["versionId"] in by_version
                        or type(props.get("nodeCount")) is not int or props["nodeCount"] < 0
                        or type(props.get("edgeCount")) is not int or props["edgeCount"] < 0):
                    raise RuntimeError("graph_cleanup_version_marker_mismatch")
                by_version[props["versionId"]] = props
            ready_ids = {version_id for version_id, state in ledger_versions if state == "ready"}
            if (require_ready and set(by_version) != set(versions)) or not ready_ids <= set(by_version):
                raise RuntimeError("graph_cleanup_version_marker_missing")

            node_state = _one(tx, _CLAIMED_NODES, versions=versions, labels=list(LABELS.values()))
            edge_state = _one(tx, _CLAIMED_EDGES, versions=versions, types=list(ALLOWED_RELATIONSHIPS))
            incident = _one(tx, _INCIDENT_EDGES, versions=versions, types=list(ALLOWED_RELATIONSHIPS))
            expected_nodes = sum(marker["nodeCount"] for marker in by_version.values())
            expected_edges = sum(marker["edgeCount"] for marker in by_version.values())
            if (node_state != {"total": expected_nodes, "invalid": 0}
                    or edge_state != {"total": expected_edges, "invalid": 0}
                    or incident != {"total": expected_edges, "invalid": 0}):
                raise RuntimeError("graph_cleanup_owned_graph_conflict")

            _consume(tx, _DELETE_EDGES, versions=versions)
            _consume(tx, _DELETE_NODES, versions=versions)
            _consume(tx, _DELETE_VERSIONS, versions=versions)
            _consume(tx, _DELETE_STORE, **expected_store)
            if _one(tx, _REMAINING, versions=versions) != {"markers": 0, "nodes": 0, "edges": 0}:
                raise RuntimeError("graph_cleanup_delete_incomplete")
            if _one(tx, _STORE_REMAINING, **expected_store) != {"c": 0}:
                raise RuntimeError("graph_cleanup_store_delete_incomplete")
            tx.commit()
        return {"status": "cleaned", "versionIds": versions, "versionNodesRemoved": expected_nodes, "versionEdgesRemoved": expected_edges,
                "storeMarkerRemoved": True}
    finally:
        graph.close()


def _remove_owned_root(manifest: dict) -> None:
    root, _ = gt.verify_prepared_ownership(manifest, directories=("stateDir",))
    shutil.rmtree(root)


# ------------------------------------------------------------------ prepare / cleanup (pipeline interpreter) ----------------------------------------

def proposals_split(world):
    """S3 job `rel-split`: two relations over disjoint company pairs, so the projected version has two disconnected components. Both quotes already name
    exactly their own two companies in the authored article."""
    from scripts.relation_smoke import COMP, INV, co, proposal, world_cite
    return [proposal("INVESTS_IN", co("SYNTH-4"), co("SYNTH-3"), [world_cite(world, "main", INV)]),
            proposal("COMPETES_WITH", co("SYNTH-2"), co("SYNTH-1"), [world_cite(world, "main", COMP)], business="전기차 시장")]


def cmd_prepare(args) -> dict:
    uri, database = neo4j_env()
    root, manifest_path = Path(args.root).resolve(), Path(args.manifest).resolve()
    if root.exists() or manifest_path.exists():
        raise PrepareFailed("local-preflight", "state_exists")
    if manifest_path == root or manifest_path.is_relative_to(root):
        raise PrepareFailed("local-preflight", "manifest_inside_root")
    sys.path[:0] = [str(PIPELINE)]
    try:
        from scripts.graph_projection_smoke import SCHEMA, Operator, Raw, build_relations, build_world
        from scripts.relation_smoke import converge
    except BaseException as error:
        raise PrepareFailed("imports", _prepare_error_code(error)) from None
    run = args.run_id or f"gtb{uuid.uuid4().hex[:8]}"
    try:
        raw = Raw(uri, database)
        try:
            if raw.count("MATCH (n) RETURN count(n) AS c") != 0:
                raise PrepareFailed("database-preflight", "database_not_empty")
            components = raw.q("CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition")
        finally:
            raw.close()
    except PrepareFailed:
        raise
    except BaseException as error:
        raise PrepareFailed("database-preflight", _prepare_error_code(error)) from None
    server = {"name": components[0]["name"], "version": components[0]["versions"][0], "edition": components[0]["edition"]} if components else None
    stage = "local-state"
    try:
        root.mkdir(mode=0o700)
        (root / MARKER).write_text(run, encoding="utf-8")
        stage = "world"
        world = build_world(root)
        stage = "relations-main"
        jobs = build_relations(world, process=True, only=("rel-main",))
        stage = "relations-split"
        jobs["rel-split"] = converge(world, "rel-split", proposals_split(world), process=True)
        assert jobs["rel-split"]["state"] == "ready", jobs["rel-split"].get("failure")
        op = Operator(world, uri, database, run)
        op.jobs = jobs
        stage = "graph-init"
        op.graph("init", {"schemaVersion": SCHEMA, "storeId": f"{run}-store", "database": database})
        states = {}
        for name, job in (("main", "rel-main"), ("split", "rel-split")):
            stage = f"freeze-{name}"
            op.freeze(name, job)
            stage = f"project-{name}"
            ready = op.graph("project", op.sel(name))
            assert ready["state"] == "ready", ready
            stage = f"inspect-{name}"
            states[name] = op.state(name)
        stage = "manifest"
        manifest = {
            "schemaVersion": gt.SCHEMA_MANIFEST, "runId": run, "owned": True, "root": str(root), "database": database,
            "stateDir": str(root / "graph"), "relationStateDir": str(root / "relation"), "extractionStateDir": str(root / "extraction"),
            "ingestionStateDir": str(root / "ingestion"), "sources": str(world.kit.registry_path), "canonical": str(op.canonical),
            "neo4jLoopbackPort": urlsplit(uri).port, "versions": {"main": op.vid("main"), "split": op.vid("split")},
            "worldDigest": gt.sha256_hex(gt.canonical_json({"upstream": world.s2["inputDigest"], "relationJobs": {j: jobs[j]["inputDigest"] for j in sorted(jobs)}})),
            "neo4j": server, "environmentNote": args.environment_note, "preparedAt": utc_now()}
        descriptor = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    except BaseException as error:
        sys.stderr.write(f"prepare failed at {stage}; attempting exact owned-state cleanup\n")
        failure_manifest = {
            "owned": True, "root": str(root), "runId": run, "database": database, "stateDir": str(root / "graph"),
            "neo4jLoopbackPort": urlsplit(uri).port,
        }
        try:
            _exact_graph_cleanup(uri, database, failure_manifest, require_ready=False)
            _remove_owned_root(failure_manifest)
        except BaseException as cleanup_error:
            code = _prepare_error_code(cleanup_error)
            sys.stderr.write(f"automatic cleanup refused ({code}); owned root retained for manual recovery\n")
        if isinstance(error, KeyboardInterrupt):
            raise
        raise PrepareFailed(stage, _prepare_error_code(error)) from None
    return {"ok": True, "runId": run, "manifest": str(manifest_path), "versions": manifest["versions"], "worldDigest": manifest["worldDigest"],
            "graph": {name: {"state": s["state"], "counts": s["counts"]} for name, s in states.items()}, "providerCalls": 0, "modelCalls": 0}


def cmd_cleanup(args) -> dict:
    uri, database = neo4j_env()
    manifest = gt.load_manifest(Path(args.manifest))
    sys.path[:0] = [str(PIPELINE)]
    try:
        removed = _exact_graph_cleanup(uri, database, manifest, require_ready=True)
    except Exception as exc:
        code = getattr(exc, "code", str(exc) or type(exc).__name__)
        raise SystemExit(f"cleanup refused before deletion; owned root and manifest retained ({code})") from None
    try:
        _remove_owned_root(manifest)
    except Exception as exc:
        code = getattr(exc, "code", type(exc).__name__)
        raise SystemExit(f"graph cleanup committed, but owned root could not be removed; manifest retained ({code})") from None
    return {"ok": True, "neo4j": removed, "ownedStateRemoved": True, "manifestKept": True}


# ------------------------------------------------------------------ measure (stdlib only) ---------------------------------------------------------

def guard_program(port: int) -> str:
    """Audit wrapper: the CLI process may open a socket only to the configured loopback Neo4j port, never bind, never resolve another host."""
    return ("import sys, runpy\n"
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
            "runpy.run_module('zoop_ai_pipeline.graph_projection_cli', run_name='__main__')\n")


def make_invoker(manifest: dict, *, mode: str, python: Path, cli: Path, timeout: float) -> gt.Invoker:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
    env.update({k: v for k, v in os.environ.items() if (k.startswith("ZOOP_GRAPH_") and k != "ZOOP_GRAPH_SMOKE_URI") or k in ("ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR")})
    program = guard_program(manifest["neo4jLoopbackPort"])

    def argv_for(command: str) -> list[str]:
        args = ["--state-dir", manifest["stateDir"]]
        if command in gt.SOURCED:
            args += ["--relation-state-dir", manifest["relationStateDir"], "--extraction-state-dir", manifest["extractionStateDir"],
                     "--ingestion-state-dir", manifest["ingestionStateDir"], "--sources", manifest["sources"], "--canonical", manifest["canonical"]]
        head = [str(python), "-c", program] if mode == "audit" else [str(cli)]
        return [*head, command, *args]

    def invoke(command: str, stdin: bytes) -> gt.Invocation:
        try:
            child = subprocess.run(argv_for(command), input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=PIPELINE, timeout=timeout)
        except subprocess.TimeoutExpired:
            return gt.Invocation(None, b"", 0, "timeout")
        except OSError:
            return gt.Invocation(None, b"", 0, "spawn_error")
        return gt.Invocation(child.returncode, child.stdout, len(child.stderr))

    return invoke


def cli_runtime(python: Path) -> dict | None:
    try:
        child = subprocess.run([str(python), "-c", "import sys, neo4j; print(sys.version.split()[0]); print(neo4j.__version__)"], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, timeout=60, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1"})
        lines = child.stdout.decode().split()
        return {"python": lines[0], "neo4jDriver": lines[1]} if child.returncode == 0 and len(lines) == 2 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def tool_source_digest() -> str | None:
    base = PIPELINE / "src" / "zoop_ai_pipeline"
    files = [base / name for name in TOOL_SOURCES]
    if not all(f.is_file() for f in files):
        return None
    return gt.sha256_hex(gt.canonical_json([[f.name, gt.sha256_hex(f.read_bytes())] for f in files]))


def cmd_measure(args) -> dict:
    manifest = gt.load_manifest(Path(args.manifest))
    queries, queries_sha = gt.load_queries(Path(args.queries))
    python = Path(args.pipeline_python) if args.pipeline_python else PIPELINE / ".venv" / "bin" / "python"
    cli = Path(args.graph_cli) if args.graph_cli else python.parent / "zoop-ai-graph"
    for needed in (python, cli if args.invoker == "script" else python):
        if not needed.exists():
            raise SystemExit(f"{needed.name} not found; pass --pipeline-python/--graph-cli of the installed pipeline environment")
    out = Path(args.out)
    if out.exists():
        raise SystemExit("--out exists: a measurement record is never overwritten")
    invoker_label = ("audit-guarded `python -c` + runpy of zoop_ai_pipeline.graph_projection_cli (same entry point as the console script; sockets limited to the "
                     "configured loopback Neo4j port)" if args.invoker == "audit" else "installed console script zoop-ai-graph, no wrapper")
    meta = {"measurementId": f"gtm-{uuid.uuid4().hex[:10]}", "recordedAt": utc_now(), "clock": "time.perf_counter_ns (monotonic, integer nanoseconds)",
            "timeoutSeconds": args.timeout, "invoker": invoker_label,
            "system": {"tool": "zoop-ai-graph", "checkoutSourceDigest": tool_source_digest(), "cliRuntime": cli_runtime(python),
                       "host": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(), "cpuCount": os.cpu_count()},
                       "neo4j": manifest.get("neo4j"), "environmentNote": manifest.get("environmentNote"),
                       "concurrency": 1, "warmup": "per-case warm-ups excluded from statistics, recorded in full"}}
    record = gt.run_measurement(
        manifest=manifest, queries=queries, queries_sha256=queries_sha, invoke=make_invoker(manifest, mode=args.invoker, python=python, cli=cli, timeout=args.timeout),
        repeats=args.repeats, warmups=args.warmups, meta=meta, fingerprint=lambda: gt.fingerprint_state(manifest),
        mutate=gt.make_mutator(manifest) if args.authority_checks else None)
    write_json(out, record, exclusive=True)
    outcomes: dict[str, int] = {}
    for a in record["attempts"]:
        outcomes[a["outcome"]] = outcomes.get(a["outcome"], 0) + 1
    return {"ok": True, "measurementId": meta["measurementId"], "attempts": len(record["attempts"]), "attemptsByOutcome": outcomes, "usage": record["usage"]}


# ------------------------------------------------------------------ score (stdlib only) -----------------------------------------------------------

def cmd_score(args) -> dict:
    queries, queries_sha = gt.load_queries(Path(args.queries))
    score = gt.score_run(read_json(Path(args.run)), queries, queries_sha, read_json(Path(args.expected)))
    if args.out:
        write_json(Path(args.out), score, exclusive=False)
    if args.markdown:
        Path(args.markdown).write_text(gt.render_markdown(score), encoding="utf-8")
    return {"ok": True, "measurementId": score["measurementId"], "headline": score["headline"], "readOnly": score["readOnly"]["status"],
            "checks": score["checks"]["status"], "integrity": {v: i["sameVerifiedGraph"] for v, i in score["integrity"].items()}, "warnings": score["warnings"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="build the owned synthetic world and project two versions (pipeline interpreter)")
    p.add_argument("--root", required=True, help="fresh directory to create for the owned state")
    p.add_argument("--manifest", required=True, help="manifest file to create (holds local paths and a loopback port; keep it out of git)")
    p.add_argument("--run-id", help="identity prefix of this run's Neo4j versions (default gtb<random>)")
    p.add_argument("--environment-note", help="free text recorded with the run, e.g. the Neo4j container limits")
    p = sub.add_parser("measure", help="invoke the installed CLI per attempt and write a measurement record")
    p.add_argument("--manifest", required=True)
    p.add_argument("--queries", default=str(FIXTURES / "queries.json"))
    p.add_argument("--out", required=True, help="measurement record to create (never overwritten)")
    p.add_argument("--repeats", type=int, default=20, help="measured repeats per case (default 20; p95 needs n>=20)")
    p.add_argument("--warmups", type=int, default=1, help="excluded warm-ups per case")
    p.add_argument("--timeout", type=float, default=120.0, help="seconds per attempt; a timeout is recorded, never dropped")
    p.add_argument("--invoker", choices=("audit", "script"), default="audit")
    p.add_argument("--pipeline-python", help="interpreter of the installed pipeline environment (default ai/pipeline/.venv/bin/python)")
    p.add_argument("--graph-cli", help="console script for --invoker script (default next to the interpreter)")
    p.add_argument("--authority-checks", action="store_true", help="also run grant/canonical denial and input-refusal checks (owned state only; not timed)")
    p = sub.add_parser("score", help="score a measurement record against the hand-authored expectation")
    p.add_argument("run")
    p.add_argument("--queries", default=str(FIXTURES / "queries.json"))
    p.add_argument("--expected", default=str(FIXTURES / "expected.json"))
    p.add_argument("--out", help="score JSON file (overwritten)")
    p.add_argument("--markdown", help="Markdown report file (overwritten)")
    p = sub.add_parser("cleanup", help="remove what prepare created (pipeline interpreter)")
    p.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)
    try:
        result = {"prepare": cmd_prepare, "measure": cmd_measure, "score": cmd_score, "cleanup": cmd_cleanup}[args.command](args)
    except PrepareFailed as exc:
        print(json.dumps({"ok": False, "error": {"code": "prepare_failed", "stage": exc.stage, "errorCode": exc.error_code}}, indent=1,
                         ensure_ascii=False))
        return 1
    except Rejected as exc:
        print(json.dumps({"ok": False, "error": exc.to_json()}, indent=1, ensure_ascii=False))
        return 2
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
