"""Deterministic baseline of the nonpublic `zoop-ai-graph` tool: measurement-record runner and scorer.

What this measures: one real CLI subprocess per attempt (`focus`, `read` or `inspect`) against an already projected, READY version over a synthetic
graph whose construction is authored replay. A `focus` answer is an UNDIRECTED breadth-first ego neighborhood computed in memory by the Python CLI over
the frozen plan; Neo4j is only read to verify the whole stored version. So the wall time is a CLI-invocation cost (interpreter start, imports, ledger
SQLite, source authority gates, Bolt connect, whole-database verification, in-memory BFS), never Neo4j traversal speed, and correctness is the
neighborhood the tool returns, never a RAG/agent answer, a directed supply-chain traversal or path reasoning.

Measurement (`run_measurement`) and scoring (`score_run`) are separate: the measurement never receives the expectation, the scorer never calls a tool.
Standard library only; no model, provider or network call here (the subprocess invoker lives with the script that owns the process environment)."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .contracts import choice, flag, integer, mapping, number, parse_json, read_json, reject, sequence, text, unique
from .stats import distribution, ratio

SCHEMA_QUERIES = "zoop-graph-tool-queries-1"
SCHEMA_EXPECTED = "zoop-graph-tool-expected-1"
SCHEMA_RUN = "zoop-graph-tool-run-1"
SCHEMA_SCORE = "zoop-graph-tool-score-1"
SCHEMA_MANIFEST = "zoop-graph-tool-manifest-1"
PROJECTION_SCHEMA = "zoop-graph-projection-1"
PROVENANCE_KIND = "measured_tool"
GRAPH_CONSTRUCTION = "authored_replay_synthetic"
OWNER_MARKER = ".zoop-graph-tool-owned"

COMMANDS = ("focus", "read", "inspect")
SOURCED = frozenset({"read", "focus"})   # commands that consult the source ledgers, grants and the canonical registry
ROLES = ("timing", "control")
MUTATIONS = ("grant-disabled", "grant-revision-changed", "canonical-topic-removed")
ABSENT = "@absent"
OUTCOMES = ("current", "ledger", "withheld", "error", "invalid_output", "timeout", "spawn_error")
SUCCESS = ("current", "ledger")
PHASES = ("warmup", "measure", "integrity", "check", "recheck")
MEASURED_COMPONENT = ("zoop-ai-graph CLI process: interpreter start and imports, ledger SQLite, S1/S2/S3 authority re-verification, Bolt connection, whole-database "
                      "Neo4j verification, and (focus only) an in-memory undirected BFS over the frozen plan")
NOT_MEASURED = ["answer or RAG quality", "agent tool selection", "directed supply-chain traversal or path reasoning", "Neo4j traversal performance",
                "entity linking, extraction or retrieval", "any model, embedding or provider call", "a public API or UI contract", "a fast-model result"]
WALL_SCOPE = ("monotonic time around one whole subprocess invocation: spawn, interpreter start, imports, stdin write, tool work, stdout drained, exit; "
              "no component split is instrumented")
FOCUS_SEMANTICS = ("undirected BFS over all node kinds and edge types of the frozen version held in the ledger; an edge is returned iff an endpoint is at "
                   "distance <= depth-1; edge orientation (subject/object, direction) is carried as an attribute and is not used for reachability")
COMPONENTS = ("pythonStartupAndImports", "ledgerSqlite", "sourceAuthority", "boltVerification", "inMemoryBfs")

_HEX = set("0123456789abcdef")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_hex(raw: bytes | str) -> str:
    return hashlib.sha256(raw.encode("utf-8") if isinstance(raw, str) else raw).hexdigest()


def _hex(value: Any, where: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or not set(value) <= _HEX:
        reject("malformed", f"{where}: expected a lowercase sha256 hex digest")
    return value


def _ms(attempts: list[dict[str, Any]]) -> list[float]:
    return [a["wallNs"] / 1_000_000 for a in attempts]


# ------------------------------------------------------------------ visible input: queries and the manifest -------------------------------------

def load_queries(path: Path) -> tuple[dict[str, Any], str]:
    """The visible dev query set and the sha256 of its exact bytes (bound into every run)."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        reject("file_unreadable", f"{path}: {exc.strerror or exc}")
    return parse_queries(parse_json(raw, str(path))), sha256_hex(raw)


def parse_queries(doc: Any) -> dict[str, Any]:
    doc = mapping(doc, "queries", ("schemaVersion", "queriesId", "split", "about", "versions", "cases", "checks"))
    if doc["schemaVersion"] != SCHEMA_QUERIES:
        reject("schema_mismatch", f"queries.schemaVersion must be {SCHEMA_QUERIES!r}")
    text(doc["queriesId"], "queries.queriesId")
    choice(doc["split"], ("dev",), "queries.split")   # the test split is never touched by the tool baseline
    versions = mapping(doc["versions"], "queries.versions", tuple(doc["versions"]) if isinstance(doc["versions"], dict) else ())
    if not versions:
        reject("malformed", "queries.versions: needs at least one version")
    for name, description in versions.items():
        text(name, "queries.versions key")
        text(description, f"queries.versions.{name}")
    cases = sequence(doc["cases"], "queries.cases", 1)
    for index, case in enumerate(cases):
        where = f"queries.cases[{index}]"
        mapping(case, where, ("caseId", "category", "role", "version", "command"), ("companyId", "depth"))
        text(case["caseId"], f"{where}.caseId")
        text(case["category"], f"{where}.category")
        choice(case["role"], ROLES, f"{where}.role")
        choice(case["command"], COMMANDS, f"{where}.command")
        if case["version"] not in versions:
            reject("malformed", f"{where}.version: unknown version {case['version']!r}")
        if case["command"] == "focus":
            text(case.get("companyId"), f"{where}.companyId")
            if integer(case.get("depth"), f"{where}.depth", 1) > 3:
                reject("malformed", f"{where}.depth: a timing case must use a depth the tool accepts (1..3); refusals belong to `checks`")
        elif "companyId" in case or "depth" in case:
            reject("malformed", f"{where}: only a focus case may carry companyId/depth")
    unique([c["caseId"] for c in cases], "queries.cases", "duplicate_case")
    checks = sequence(doc["checks"], "queries.checks")
    for index, check in enumerate(checks):
        where = f"queries.checks[{index}]"
        mapping(check, where, ("checkId", "kind", "mutation", "version", "companyId", "depth"))
        text(check["checkId"], f"{where}.checkId")
        text(check["kind"], f"{where}.kind")
        if check["mutation"] is not None:
            choice(check["mutation"], MUTATIONS, f"{where}.mutation")
        if check["version"] != ABSENT and check["version"] not in versions:
            reject("malformed", f"{where}.version: unknown version {check['version']!r}")
        text(check["companyId"], f"{where}.companyId")
        integer(check["depth"], f"{where}.depth", 1)
    unique([c["checkId"] for c in checks], "queries.checks", "duplicate_case")
    if {c["caseId"] for c in cases} & {c["checkId"] for c in checks}:
        reject("duplicate_case", "queries: a case id and a check id collide")
    return doc


def load_manifest(path: Path) -> dict[str, Any]:
    """The prepared (or externally supplied, approved) state description. It holds local paths and a loopback port, never a credential."""
    doc = mapping(read_json(Path(path)), "manifest",
                  ("schemaVersion", "runId", "owned", "stateDir", "relationStateDir", "extractionStateDir", "ingestionStateDir", "sources", "canonical",
                   "neo4jLoopbackPort", "versions", "worldDigest"),
                  ("root", "database", "neo4j", "environmentNote", "preparedAt"))
    if doc["schemaVersion"] != SCHEMA_MANIFEST:
        reject("schema_mismatch", f"manifest.schemaVersion must be {SCHEMA_MANIFEST!r}")
    text(doc["runId"], "manifest.runId")
    flag(doc["owned"], "manifest.owned")
    for key in ("stateDir", "relationStateDir", "extractionStateDir", "ingestionStateDir", "sources", "canonical"):
        text(doc[key], f"manifest.{key}")
    integer(doc["neo4jLoopbackPort"], "manifest.neo4jLoopbackPort", 1)
    _hex(doc["worldDigest"], "manifest.worldDigest")
    versions = mapping(doc["versions"], "manifest.versions", tuple(doc["versions"]) if isinstance(doc["versions"], dict) else ())
    for name, version_id in versions.items():
        text(name, "manifest.versions key")
        text(version_id, f"manifest.versions.{name}")
    return doc


def _version_id(manifest: dict[str, Any], version: str) -> str:
    if version == ABSENT:
        return f"{manifest['runId']}-absent"
    if version not in manifest["versions"]:
        reject("manifest_mismatch", f"the manifest has no version {version!r}")
    return manifest["versions"][version]


def request_body(manifest: dict[str, Any], version: str, command: str, company: str | None = None, depth: int | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"schemaVersion": PROJECTION_SCHEMA, "versionId": _version_id(manifest, version)}
    if command == "focus":
        body["companyId"], body["depth"] = company, depth
    return body


# ------------------------------------------------------------------ one invocation and its classification -----------------------------------------

@dataclass(frozen=True)
class Invocation:
    """What one subprocess produced. `failure` is set instead of a return code when the process never completed ('timeout' or 'spawn_error')."""
    returncode: int | None
    stdout: bytes
    stderr_bytes: int
    failure: str | None = None


Invoker = Callable[[str, bytes], Invocation]


def _usage(doc: dict[str, Any]) -> dict[str, int] | None:
    usage = doc.get("usage")
    if isinstance(usage, dict) and all(isinstance(usage.get(k), int) and not isinstance(usage.get(k), bool) for k in ("providerCalls", "modelCalls")):
        return {"providerCalls": usage["providerCalls"], "modelCalls": usage["modelCalls"]}
    return None


def _normalize(doc: dict[str, Any], command: str) -> dict[str, Any]:
    """The tool's neighborhood reduced to what is scored. No relation hash, quote, title, path or credential survives into the record."""
    graph = doc["graph"]
    nodes = sorted(({"kind": n["kind"], "id": n["id"], "distance": n.get("distance")} for n in graph["nodes"]), key=canonical_json)
    edges = []
    for e in graph["edges"]:
        evidence = e["evidence"]
        edges.append({"type": e["type"], "subject": e["subject"]["id"], "object": e["object"]["id"], "direction": e["direction"], "connection": e["connection"],
                      "validFrom": e["validity"]["from"], "validUntil": e["validity"]["until"], "pathCompanyIds": list(e["path"]["companyIds"]),
                      "cited": bool(evidence["relation"] or evidence["validity"] or any(evidence["steps"]))})
    verification = doc["verification"]
    return {"found": doc["focus"]["found"] if command == "focus" else True, "nodes": nodes, "edges": sorted(edges, key=canonical_json),
            "verification": {"nodes": verification["nodes"], "edges": verification["edges"]},
            "digests": {"payload": doc["digests"]["payload"], "graph": doc["digests"]["graph"]}, "evidenceRecords": len(doc["evidence"]),
            "publication": doc["publication"]}


def classify(command: str, inv: Invocation) -> tuple[str, str | None, dict[str, Any] | None, dict[str, int] | None]:
    """(outcome, code, normalized result, observed usage). Withheld and refused results are first-class outcomes, never an empty neighborhood."""
    if inv.failure in ("timeout", "spawn_error"):
        return inv.failure, None, None, None
    try:
        doc = json.loads(inv.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return "invalid_output", None, None, None
    if not isinstance(doc, dict):
        return "invalid_output", None, None, None
    usage = _usage(doc)
    error = doc.get("error")
    if inv.returncode == 2 and isinstance(error, dict) and isinstance(error.get("code"), str):
        return "error", error["code"], {"error": error["code"]}, usage
    try:
        if command == "inspect":
            if inv.returncode == 0 and isinstance(doc["state"], str):
                counts = doc["counts"]
                return "ledger", None, {"state": doc["state"], "nodeCount": sum(counts["nodes"].values()), "edgeCount": sum(counts["edges"].values()),
                                        "digests": {"payload": doc["digests"]["payload"], "graph": doc["digests"]["graph"]}}, usage
        else:
            delivery = doc["delivery"]
            if inv.returncode == 0 and delivery["status"] == "current":
                return "current", None, _normalize(doc, command), usage
            if inv.returncode == 2 and delivery["status"] == "withheld" and isinstance(delivery["code"], str):
                return "withheld", delivery["code"], {"withheld": delivery["code"]}, usage
    except (KeyError, TypeError, AttributeError, ValueError):
        pass
    return "invalid_output", None, None, usage


class _Recorder:
    def __init__(self, invoke: Invoker, clock: Callable[[], int]):
        self.invoke, self.clock = invoke, clock
        self.attempts: list[dict[str, Any]] = []
        self.results: dict[str, dict[str, Any]] = {}
        self.usage = {"providerCalls": 0, "modelCalls": 0, "attemptsWithUsage": 0, "attemptsWithoutUsage": 0}
        self.origin = clock()

    def attempt(self, case_id: str, phase: str, repeat: int, command: str, body: dict[str, Any]) -> dict[str, Any]:
        stdin = canonical_json(body).encode("utf-8")
        start = self.clock()
        inv = self.invoke(command, stdin)
        end = self.clock()
        outcome, code, result, usage = classify(command, inv)
        digest = None
        if result is not None:
            digest = sha256_hex(canonical_json(result))
            self.results.setdefault(digest, result)
        if usage is None:
            self.usage["attemptsWithoutUsage"] += 1
        else:
            self.usage["attemptsWithUsage"] += 1
            self.usage["providerCalls"] += usage["providerCalls"]
            self.usage["modelCalls"] += usage["modelCalls"]
        record = {"seq": len(self.attempts), "caseId": case_id, "phase": phase, "repeat": repeat, "startNs": start - self.origin, "wallNs": end - start,
                  "exitCode": inv.returncode, "outcome": outcome, "code": code, "stdoutBytes": len(inv.stdout), "stderrBytes": inv.stderr_bytes,
                  "resultDigest": digest}
        self.attempts.append(record)
        return record


def run_measurement(*, manifest: dict[str, Any], queries: dict[str, Any], queries_sha256: str, invoke: Invoker, repeats: int, warmups: int,
                    meta: dict[str, Any], clock: Callable[[], int] = time.perf_counter_ns, fingerprint: Callable[[], dict[str, str]] | None = None,
                    mutate: Callable[[str], Callable[[], None]] | None = None) -> dict[str, Any]:
    """The measurement record: every attempt (warm-ups, measured, integrity reads, authority/refusal checks), the distinct normalized results by digest,
    fingerprints of the read-only state before/after, and the observed usage. It never sees an expectation.

    Order: fingerprint -> integrity read per version -> warm-ups per case -> measured repeats round-robin over cases -> integrity read per version ->
    fingerprint -> (optional) authority/refusal checks that temporarily mutate the registries (restored in `finally`) -> fingerprint."""
    if isinstance(repeats, bool) or not isinstance(repeats, int) or not 1 <= repeats <= 1000:
        reject("bad_argument", "repeats must be an integer in 1..1000")
    if isinstance(warmups, bool) or not isinstance(warmups, int) or not 0 <= warmups <= 20:
        reject("bad_argument", "warmups must be an integer in 0..20")
    recorder = _Recorder(invoke, clock)
    cases = queries["cases"]

    def body_of(case: dict[str, Any]) -> dict[str, Any]:
        return request_body(manifest, case["version"], case["command"], case.get("companyId"), case.get("depth"))

    for case in cases:   # fail before any process starts if the manifest lacks a version
        body_of(case)
    fingerprints: dict[str, Any] = {}
    if fingerprint:
        fingerprints["before"] = fingerprint()

    def integrity(moment: str) -> None:
        for name in sorted({c["version"] for c in cases}):
            recorder.attempt(f"INTEGRITY:{name}:{moment}", "integrity", 0, "read", request_body(manifest, name, "read"))

    integrity("before")
    for case in cases:
        for repeat in range(warmups):
            recorder.attempt(case["caseId"], "warmup", repeat, case["command"], body_of(case))
    for repeat in range(repeats):
        for case in cases:
            recorder.attempt(case["caseId"], "measure", repeat, case["command"], body_of(case))
    integrity("after")
    if fingerprint:
        fingerprints["afterTiming"] = fingerprint()
    checks_run = None
    if mutate is not None:
        checks_run = []
        for check in queries["checks"]:
            body = request_body(manifest, check["version"], "focus", check["companyId"], check["depth"])
            restore = mutate(check["mutation"]) if check["mutation"] else None
            try:
                recorder.attempt(check["checkId"], "check", 0, "focus", body)
            finally:
                if restore:
                    restore()
            if check["mutation"]:
                recorder.attempt(check["checkId"], "recheck", 0, "focus", body)
            checks_run.append(check["checkId"])
        if fingerprint:
            fingerprints["afterChecks"] = fingerprint()
    return {
        "schemaVersion": SCHEMA_RUN, "measurementId": meta["measurementId"], "recordedAt": meta["recordedAt"],
        "provenance": {"kind": PROVENANCE_KIND, "graphConstruction": GRAPH_CONSTRUCTION, "measuredComponent": MEASURED_COMPONENT, "split": queries["split"],
                       "notMeasured": NOT_MEASURED},
        "scope": {"queriesId": queries["queriesId"], "queriesSha256": queries_sha256, "worldDigest": manifest["worldDigest"], "worldRunId": manifest["runId"],
                  "stateOwnedByRunner": manifest["owned"]},
        "system": meta["system"],
        "config": {"repeats": repeats, "warmups": warmups, "order": "warm-ups per case, then measured repeats round-robin over cases", "clock": meta["clock"],
                   "wallScope": WALL_SCOPE, "timeoutSeconds": meta["timeoutSeconds"], "invoker": meta["invoker"], "checksRun": checks_run},
        "fingerprints": fingerprints, "attempts": recorder.attempts, "results": recorder.results, "usage": recorder.usage,
    }


# ------------------------------------------------------------------ read-only proof: fingerprints and temporary mutations --------------------------

def _file_digest(path: Path) -> str:
    return sha256_hex(path.read_bytes())


def _tree_digest(path: Path) -> str:
    h = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file():
            h.update(canonical_json([item.relative_to(path).as_posix(), item.stat().st_size, _file_digest(item)]).encode("utf-8"))
    return h.hexdigest()


def _ledger_rows_digest(db: Path) -> str:
    """Every row of every table, from a read-only immutable connection (the same method the projection smoke uses); no file path is part of the digest."""
    conn = sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        h = hashlib.sha256()
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
            h.update(name.encode("utf-8"))
            for row in conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid'):
                h.update(repr(row).encode("utf-8"))
        return h.hexdigest()
    finally:
        conn.close()


def fingerprint_state(manifest: dict[str, Any]) -> dict[str, str]:
    """Digests only, keyed by role: neither a path nor a credential is recorded."""
    state = Path(manifest["stateDir"])
    return {"relationState": _tree_digest(Path(manifest["relationStateDir"])), "extractionState": _tree_digest(Path(manifest["extractionStateDir"])),
            "ingestionState": _tree_digest(Path(manifest["ingestionStateDir"])), "graphLedgerRows": _ledger_rows_digest(state / "graph.sqlite3"),
            "graphStateFiles": sha256_hex(canonical_json(sorted(p.name for p in state.iterdir() if not p.name.endswith(("-wal", "-shm"))))),
            "sourcesRegistry": _file_digest(Path(manifest["sources"])), "canonicalRegistry": _file_digest(Path(manifest["canonical"]))}


def _not_owned(detail: str) -> None:
    reject("not_owned", f"authority mutations require the exact prepared state: {detail}")


def _regular_bytes(path: Path, detail: str) -> tuple[bytes, int]:
    """Read one already-authorized regular file without following a last-component symlink."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            found = os.fstat(descriptor)
            if not stat.S_ISREG(found.st_mode):
                _not_owned(detail)
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                raw = handle.read()
            return raw, stat.S_IMODE(found.st_mode)
        finally:
            os.close(descriptor)
    except OSError:
        _not_owned(detail)
    raise AssertionError("unreachable")


def _owned_path(root: Path, value: Any, name: str, *, directory: bool) -> Path:
    if not isinstance(value, str) or not value:
        _not_owned(f"manifest.{name} is missing")
    try:
        path = Path(os.path.abspath(value))
        relative = path.relative_to(root)
    except (OSError, ValueError, TypeError):
        _not_owned(f"manifest.{name} is outside the prepared root")
    if not relative.parts:
        _not_owned(f"manifest.{name} is the prepared root")
    current = root
    try:
        for part in relative.parts:
            current /= part
            found = current.lstat()
            if stat.S_ISLNK(found.st_mode):
                _not_owned(f"manifest.{name} contains a symlink")
            if current != path and not stat.S_ISDIR(found.st_mode):
                _not_owned(f"manifest.{name} has a non-directory parent")
        wanted = stat.S_ISDIR(found.st_mode) if directory else stat.S_ISREG(found.st_mode)
        if not wanted:
            _not_owned(f"manifest.{name} is not a {'directory' if directory else 'regular file'}")
    except OSError:
        _not_owned(f"manifest.{name} is unavailable")
    return path


def verify_prepared_ownership(manifest: dict[str, Any], *, files: tuple[str, ...] = (), directories: tuple[str, ...] = ()) -> tuple[Path, dict[str, Path]]:
    """Authorize local mutation only for the exact, non-symlink prepared namespace.

    Structural checks use metadata only, so an invalid manifest is rejected before any requested data file is opened.
    """
    if manifest.get("owned") is not True:
        _not_owned("manifest.owned is not true")
    root_value, run_id = manifest.get("root"), manifest.get("runId")
    if not isinstance(root_value, str) or not root_value or not isinstance(run_id, str) or not run_id:
        _not_owned("manifest.root or manifest.runId is missing")
    try:
        root = Path(os.path.abspath(root_value))
        root_stat = root.lstat()
    except (OSError, ValueError, TypeError):
        _not_owned("the prepared root is unavailable")
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        _not_owned("the prepared root is not a real directory")
    marker = root / OWNER_MARKER
    try:
        marker_stat = marker.lstat()
    except OSError:
        _not_owned("the ownership marker is missing")
    if stat.S_ISLNK(marker_stat.st_mode) or not stat.S_ISREG(marker_stat.st_mode):
        _not_owned("the ownership marker is not a regular file")
    marker_raw, _ = _regular_bytes(marker, "the ownership marker cannot be read safely")
    if marker_raw != run_id.encode("utf-8"):
        _not_owned("the ownership marker belongs to another run")
    paths = {name: _owned_path(root, manifest.get(name), name, directory=False) for name in files}
    paths.update({name: _owned_path(root, manifest.get(name), name, directory=True) for name in directories})
    return root, paths


def _swap_owned(path: Path, data: bytes, mode: int) -> None:
    temporary = path.with_name(f".{path.name}.graph-tool-next")
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        created = True
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(descriptor)
        os.fchmod(descriptor, mode)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, path)
        created = False
    except OSError:
        _not_owned("the owned registry could not be replaced safely")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            try:
                temporary.unlink()
            except OSError:
                pass


def make_mutator(manifest: dict[str, Any]) -> Callable[[str], Callable[[], None]]:
    """Temporarily mutate prepared authority registries and restore only the bytes written by this mutation."""
    root, initial = verify_prepared_ownership(manifest, files=("sources", "canonical"))

    def context() -> dict[str, Path]:
        current_root, current = verify_prepared_ownership(manifest, files=("sources", "canonical"))
        if current_root != root or current != initial:
            _not_owned("the prepared namespace changed")
        return current

    def mutate(name: str) -> Callable[[], None]:
        paths = context()
        if name in ("grant-disabled", "grant-revision-changed"):
            path = paths["sources"]
            original, mode = _regular_bytes(path, "the sources registry cannot be read safely")
            doc = json.loads(original)
            grant = doc["sources"][0]["grant"]
            if name == "grant-disabled":
                grant["enabled"] = False
            else:
                grant["revision"] = "rights-graph-tool-changed"
        elif name == "canonical-topic-removed":
            path = paths["canonical"]
            original, mode = _regular_bytes(path, "the canonical registry cannot be read safely")
            doc = json.loads(original)
            doc["entries"] = [e for e in doc["entries"] if e.get("kind") != "topic"]
        else:
            raise ValueError(name)
        changed = canonical_json(doc).encode("utf-8")
        context()
        still_original, current_mode = _regular_bytes(path, "the owned registry cannot be re-read safely")
        if still_original != original or current_mode != mode:
            _not_owned("the owned registry changed before mutation")
        _swap_owned(path, changed, mode)

        def restore() -> None:
            current = context()
            if current["sources" if name.startswith("grant-") else "canonical"] != path:
                _not_owned("the registry path changed before restore")
            observed, observed_mode = _regular_bytes(path, "the mutated registry cannot be read safely")
            if observed != changed or observed_mode != mode:
                _not_owned("the mutated registry no longer contains only this mutation's state")
            _swap_owned(path, original, mode)

        return restore

    return mutate


# ------------------------------------------------------------------ the expectation (scorer only) ------------------------------------------------

def parse_expected(doc: Any, queries: dict[str, Any]) -> dict[str, Any]:
    doc = mapping(doc, "expected", ("schemaVersion", "queriesId", "authoring", "nodeKinds", "edgeDefs", "cases", "checks"))
    if doc["schemaVersion"] != SCHEMA_EXPECTED:
        reject("schema_mismatch", f"expected.schemaVersion must be {SCHEMA_EXPECTED!r}")
    if doc["queriesId"] != queries["queriesId"]:
        reject("scope_mismatch", "expected.queriesId differs from the query set")
    node_kinds = mapping(doc["nodeKinds"], "expected.nodeKinds", tuple(doc["nodeKinds"]) if isinstance(doc["nodeKinds"], dict) else ())
    for ident, kind in node_kinds.items():
        choice(kind, ("company", "event", "topic"), f"expected.nodeKinds.{ident}")
    defs = mapping(doc["edgeDefs"], "expected.edgeDefs", tuple(doc["edgeDefs"]) if isinstance(doc["edgeDefs"], dict) else ())
    for name, edge in defs.items():
        where = f"expected.edgeDefs.{name}"
        mapping(edge, where, ("type", "subject", "object", "direction", "connection", "validFrom", "validUntil", "pathCompanyIds"))
        text(edge["type"], f"{where}.type")
        for key in ("subject", "object"):
            if edge[key] not in node_kinds:
                reject("malformed", f"{where}.{key}: unknown node {edge[key]!r}")
        choice(edge["direction"], ("directed", "symmetric"), f"{where}.direction")
        choice(edge["connection"], ("direct", "indirect"), f"{where}.connection")
        sequence(edge["pathCompanyIds"], f"{where}.pathCompanyIds")
    cases = mapping(doc["cases"], "expected.cases", tuple(doc["cases"]) if isinstance(doc["cases"], dict) else ())
    query_cases = {c["caseId"]: c for c in queries["cases"]}
    if set(cases) != set(query_cases):
        reject("scope_mismatch", "expected.cases must cover exactly the query cases")
    for case_id, expect in cases.items():
        where = f"expected.cases.{case_id}"
        kind = expect.get("kind") if isinstance(expect, dict) else None
        if kind == "neighborhood":
            mapping(expect, where, ("kind", "found", "nodes", "edges"))
            flag(expect["found"], f"{where}.found")
            nodes = mapping(expect["nodes"], f"{where}.nodes", tuple(expect["nodes"]) if isinstance(expect["nodes"], dict) else ())
            for ident, distance in nodes.items():
                if ident not in node_kinds:
                    reject("malformed", f"{where}.nodes: unknown node {ident!r}")
                if distance is not None:
                    integer(distance, f"{where}.nodes.{ident}")
            for ref in sequence(expect["edges"], f"{where}.edges"):
                if ref not in defs:
                    reject("malformed", f"{where}.edges: unknown edge {ref!r}")
            if query_cases[case_id]["command"] == "inspect":
                reject("malformed", f"{where}: an inspect case needs a ledger expectation")
        elif kind == "ledger":
            mapping(expect, where, ("kind", "state", "nodeCount", "edgeCount"))
            text(expect["state"], f"{where}.state")
            integer(expect["nodeCount"], f"{where}.nodeCount")
            integer(expect["edgeCount"], f"{where}.edgeCount")
            if query_cases[case_id]["command"] != "inspect":
                reject("malformed", f"{where}: a ledger expectation belongs to an inspect case")
        else:
            reject("malformed", f"{where}: kind must be 'neighborhood' or 'ledger'")
    checks = mapping(doc["checks"], "expected.checks", tuple(doc["checks"]) if isinstance(doc["checks"], dict) else ())
    if set(checks) != {c["checkId"] for c in queries["checks"]}:
        reject("scope_mismatch", "expected.checks must cover exactly the query checks")
    for check_id, expect in checks.items():
        mapping(expect, f"expected.checks.{check_id}", ("outcome", "code", "recheck"))
        choice(expect["outcome"], ("withheld", "error"), f"expected.checks.{check_id}.outcome")
        text(expect["code"], f"expected.checks.{check_id}.code")
        if expect["recheck"] is not None:
            choice(expect["recheck"], ("current",), f"expected.checks.{check_id}.recheck")
    return doc


# ------------------------------------------------------------------ the recorded measurement, validated ---------------------------------------------

def parse_run(raw: Any) -> dict[str, Any]:
    """Strict validation of a measurement record. Anything that is not a tool measurement is `incompatible_run`, never scored."""
    if not isinstance(raw, dict) or raw.get("schemaVersion") != SCHEMA_RUN:
        reject("incompatible_run", f"only {SCHEMA_RUN} measurement records are scored here (a zoop-bench-run-1 control or authored fixture is not a tool measurement)")
    run = mapping(raw, "run", ("schemaVersion", "measurementId", "recordedAt", "provenance", "scope", "system", "config", "fingerprints", "attempts", "results", "usage"))
    text(run["measurementId"], "run.measurementId")
    text(run["recordedAt"], "run.recordedAt")
    provenance = mapping(run["provenance"], "run.provenance", ("kind", "graphConstruction", "measuredComponent", "split", "notMeasured"))
    if provenance["kind"] != PROVENANCE_KIND or provenance["graphConstruction"] != GRAPH_CONSTRUCTION:
        reject("incompatible_run", f"provenance must be kind={PROVENANCE_KIND!r} over graphConstruction={GRAPH_CONSTRUCTION!r}; authored responses are never scored as measurements")
    choice(provenance["split"], ("dev",), "run.provenance.split")
    scope = mapping(run["scope"], "run.scope", ("queriesId", "queriesSha256", "worldDigest", "worldRunId", "stateOwnedByRunner"))
    text(scope["queriesId"], "run.scope.queriesId")
    _hex(scope["queriesSha256"], "run.scope.queriesSha256")
    _hex(scope["worldDigest"], "run.scope.worldDigest")
    flag(scope["stateOwnedByRunner"], "run.scope.stateOwnedByRunner")
    mapping(run["system"], "run.system", tuple(run["system"]) if isinstance(run["system"], dict) else ())
    config = mapping(run["config"], "run.config", ("repeats", "warmups", "order", "clock", "wallScope", "timeoutSeconds", "invoker", "checksRun"))
    integer(config["repeats"], "run.config.repeats", 1)
    integer(config["warmups"], "run.config.warmups")
    number(config["timeoutSeconds"], "run.config.timeoutSeconds")
    if config["checksRun"] is not None:
        sequence(config["checksRun"], "run.config.checksRun")
    prints = mapping(run["fingerprints"], "run.fingerprints", (), ("before", "afterTiming", "afterChecks"))
    for moment, digests in prints.items():
        digests = mapping(digests, f"run.fingerprints.{moment}", tuple(digests) if isinstance(digests, dict) else ())
        for label, value in digests.items():
            _hex(value, f"run.fingerprints.{moment}.{label}")
    results = mapping(run["results"], "run.results", tuple(run["results"]) if isinstance(run["results"], dict) else ())
    for digest, result in results.items():
        _hex(digest, "run.results key")
        if not isinstance(result, dict) or sha256_hex(canonical_json(result)) != digest:
            reject("result_digest_mismatch", f"run.results[{digest[:12]}]: the stored result does not hash to its key")
    attempts = sequence(run["attempts"], "run.attempts")
    seen_seq: set[int] = set()
    seen_slot: set[tuple[str, str, int]] = set()
    for index, a in enumerate(attempts):
        where = f"run.attempts[{index}]"
        mapping(a, where, ("seq", "caseId", "phase", "repeat", "startNs", "wallNs", "exitCode", "outcome", "code", "stdoutBytes", "stderrBytes", "resultDigest"))
        seq = integer(a["seq"], f"{where}.seq")
        if seq in seen_seq:
            reject("duplicate_attempt", f"{where}: duplicate seq {seq}")
        seen_seq.add(seq)
        text(a["caseId"], f"{where}.caseId")
        choice(a["phase"], PHASES, f"{where}.phase")
        repeat = integer(a["repeat"], f"{where}.repeat")
        slot = (a["caseId"], a["phase"], repeat)
        if slot in seen_slot:
            reject("duplicate_attempt", f"{where}: duplicate attempt {slot}")
        seen_slot.add(slot)
        integer(a["startNs"], f"{where}.startNs")      # a malformed, negative, float, boolean or non-finite time is refused, never repaired
        integer(a["wallNs"], f"{where}.wallNs")
        if a["exitCode"] is not None and (isinstance(a["exitCode"], bool) or not isinstance(a["exitCode"], int)):
            reject("malformed", f"{where}.exitCode: expected an integer or null")
        choice(a["outcome"], OUTCOMES, f"{where}.outcome")
        text(a["code"], f"{where}.code", nullable=True)
        integer(a["stdoutBytes"], f"{where}.stdoutBytes")
        integer(a["stderrBytes"], f"{where}.stderrBytes")
        if a["resultDigest"] is not None:
            _hex(a["resultDigest"], f"{where}.resultDigest")
            if a["resultDigest"] not in results:
                reject("malformed", f"{where}.resultDigest: no stored result")
        if (a["outcome"] in ("timeout", "spawn_error", "invalid_output")) != (a["resultDigest"] is None):
            reject("malformed", f"{where}: only timeout, spawn_error and invalid_output carry no result")
    usage = mapping(run["usage"], "run.usage", ("providerCalls", "modelCalls", "attemptsWithUsage", "attemptsWithoutUsage"))
    for key in usage:
        integer(usage[key], f"run.usage.{key}")
    if usage["modelCalls"] or usage["providerCalls"]:
        reject("unexpected_model_call", "the record observed a provider or model call; this baseline claims zero and is not scored")
    return run


# ------------------------------------------------------------------ judging one result against the expectation ------------------------------------

def _edge_keys(edge: dict[str, Any]) -> tuple[str, str, str]:
    ends = sorted((edge["subject"], edge["object"]))
    oriented = [edge["subject"], edge["object"]] if edge["direction"] == "directed" else ends
    reach = canonical_json([edge["type"], ends])
    orient = canonical_json([edge["type"], oriented, edge["direction"]])
    full = canonical_json([edge["type"], oriented, edge["direction"], edge["connection"], edge["validFrom"], edge["validUntil"], edge["pathCompanyIds"], edge["cited"]])
    return reach, orient, full


JUDGEMENTS = ("found", "nodeSet", "distances", "edgeSet", "orientation", "attributes", "full")


def judge_neighborhood(result: dict[str, Any], expect: dict[str, Any], expected: dict[str, Any]) -> dict[str, bool]:
    """Independent verdicts, each a plain equality: `edgeSet` ignores orientation (reachability), `orientation` adds subject/object order of directed
    edges, `attributes` adds connection, validity, path and the citation flag."""
    kinds, defs = expected["nodeKinds"], expected["edgeDefs"]
    try:
        want_nodes = sorted(canonical_json([kinds[i], i]) for i in expect["nodes"])
        want_distances = sorted(canonical_json([kinds[i], i, d]) for i, d in expect["nodes"].items())
        got_nodes = sorted(canonical_json([n["kind"], n["id"]]) for n in result["nodes"])
        got_distances = sorted(canonical_json([n["kind"], n["id"], n["distance"]]) for n in result["nodes"])
        want_edges = [_edge_keys({**defs[ref], "cited": True}) for ref in expect["edges"]]
        got_edges = [_edge_keys(e) for e in result["edges"]]
        verdict = {"found": result["found"] == expect["found"], "nodeSet": got_nodes == want_nodes, "distances": got_distances == want_distances,
                   "edgeSet": sorted(k[0] for k in got_edges) == sorted(k[0] for k in want_edges),
                   "orientation": sorted(k[1] for k in got_edges) == sorted(k[1] for k in want_edges),
                   "attributes": sorted(k[2] for k in got_edges) == sorted(k[2] for k in want_edges)}
    except (KeyError, TypeError, ValueError):
        return {name: False for name in JUDGEMENTS}
    verdict["full"] = all(verdict.values())
    return verdict


def judge_ledger(result: dict[str, Any], expect: dict[str, Any]) -> dict[str, bool]:
    try:
        verdict = {"state": result["state"] == expect["state"], "counts": result["nodeCount"] == expect["nodeCount"] and result["edgeCount"] == expect["edgeCount"]}
    except (KeyError, TypeError):
        return {"state": False, "counts": False, "full": False}
    verdict["full"] = all(verdict.values())
    return verdict


def _ratio_block(verdicts: list[dict[str, bool]], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: ratio(sum(bool(v.get(name)) for v in verdicts), len(verdicts)) for name in names}


def _timing(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [a for a in attempts if a["outcome"] in SUCCESS]
    return {"attempts": len(attempts), "outcomes": dict(sorted(Counter(a["outcome"] for a in attempts).items())),
            "failureRate": ratio(len(attempts) - len(ok), len(attempts)),
            "successWallMs": distribution(_ms(ok)), "allAttemptsWallMs": distribution(_ms(attempts))}


# ------------------------------------------------------------------ scoring ---------------------------------------------------------------------

def _require_exact_slots(run: dict[str, Any], queries: dict[str, Any]) -> None:
    """The record must hold exactly the planned attempt slots: repeats 0..repeats-1 and warm-ups 0..warmups-1 of every case, one integrity read before and
    after per version, and a check (plus a recheck when the check mutates) for every id in config.checksRun. A missing, shifted or extra attempt is
    refused before any statistic is computed, so it can never shrink or inflate a denominator."""
    config = run["config"]
    cases, versions = [c["caseId"] for c in queries["cases"]], sorted({c["version"] for c in queries["cases"]})
    planned = {(c, "measure", r) for c in cases for r in range(config["repeats"])} | {(c, "warmup", r) for c in cases for r in range(config["warmups"])}
    planned |= {(f"INTEGRITY:{v}:{moment}", "integrity", 0) for v in versions for moment in ("before", "after")}
    check_of = {c["checkId"]: c for c in queries["checks"]}
    for check_id in config["checksRun"] or []:
        if not isinstance(check_id, str) or check_id not in check_of:
            reject("attempt_slots_mismatch", f"config.checksRun names an unknown check {check_id!r}")
        planned.add((check_id, "check", 0))
        if check_of[check_id]["mutation"]:
            planned.add((check_id, "recheck", 0))
    actual = {(a["caseId"], a["phase"], a["repeat"]) for a in run["attempts"]}
    missing, extra = sorted(planned - actual), sorted(actual - planned)
    if missing or extra:
        reject("attempt_slots_mismatch", f"the record does not hold exactly the planned attempts: {len(missing)} missing (first: {missing[:3]}), "
                                         f"{len(extra)} unexpected (first: {extra[:3]})")


def score_run(run_raw: Any, queries: dict[str, Any], queries_sha256: str, expected_raw: Any) -> dict[str, Any]:
    run = parse_run(run_raw)
    expected = parse_expected(expected_raw, queries)
    if run["scope"]["queriesId"] != queries["queriesId"] or run["scope"]["queriesSha256"] != queries_sha256:
        reject("scope_mismatch", "the record was measured with a different query set than the one given to the scorer")
    case_of = {c["caseId"]: c for c in queries["cases"]}
    check_of = {c["checkId"]: c for c in queries["checks"]}
    versions = {c["version"] for c in queries["cases"]}
    integrity_ids = {f"INTEGRITY:{v}:{m}" for v in versions for m in ("before", "after")}
    for a in run["attempts"]:
        legal = {"warmup": case_of, "measure": case_of, "check": check_of, "recheck": check_of}.get(a["phase"])
        known = integrity_ids if a["phase"] == "integrity" else legal
        if a["caseId"] not in known:
            reject("unmatched_case", f"attempt {a['seq']}: {a['phase']} attempt for unknown id {a['caseId']!r}")
    _require_exact_slots(run, queries)
    config, results = run["config"], run["results"]
    by_slot: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for a in sorted(run["attempts"], key=lambda x: x["seq"]):
        by_slot.setdefault((a["caseId"], a["phase"]), []).append(a)

    verdict_cache: dict[tuple[str, str], dict[str, bool]] = {}

    def verdict_of(case_id: str, digest: str | None) -> dict[str, bool]:
        expect = expected["cases"][case_id]
        names = ("state", "counts", "full") if expect["kind"] == "ledger" else JUDGEMENTS
        if digest is None:
            return {n: False for n in names}
        key = (case_id, digest)
        if key not in verdict_cache:
            result = results[digest]
            verdict_cache[key] = judge_ledger(result, expect) if expect["kind"] == "ledger" else judge_neighborhood(result, expect, expected)
        return verdict_cache[key]

    case_rows, measured_all, verdicts_by_case = [], [], {}
    warnings: list[str] = []
    for case in queries["cases"]:
        cid = case["caseId"]
        measured = by_slot.get((cid, "measure"), [])
        warm = by_slot.get((cid, "warmup"), [])
        verdicts = [verdict_of(cid, a["resultDigest"]) if a["outcome"] in SUCCESS else verdict_of(cid, None) for a in measured]
        verdicts_by_case[cid] = verdicts
        names = ("state", "counts", "full") if expected["cases"][cid]["kind"] == "ledger" else JUDGEMENTS
        measured_all.extend(measured)
        case_rows.append({"caseId": cid, "category": case["category"], "role": case["role"], "version": case["version"], "command": case["command"],
                          "companyId": case.get("companyId"), "depth": case.get("depth"), "planned": {"repeats": config["repeats"], "warmups": config["warmups"]},
                          "recorded": {"measured": len(measured), "warmups": len(warm)},
                          "distinctResults": len({a["resultDigest"] for a in measured}),
                          "correctness": _ratio_block(verdicts, names), "timing": _timing(measured),
                          "warmupWallMs": distribution(_ms(warm)) if warm else None})
    pool = [c for c in queries["cases"] if c["role"] == "timing" and c["command"] == "focus" and c["category"] != "unknown-company"]

    def pooled(selected: list[dict[str, Any]]) -> dict[str, Any]:
        attempts = [a for c in selected for a in by_slot.get((c["caseId"], "measure"), [])]
        verdicts = [v for c in selected for v in verdicts_by_case[c["caseId"]]]
        ledger = bool(selected) and all(expected["cases"][c["caseId"]]["kind"] == "ledger" for c in selected)
        return {"cases": [c["caseId"] for c in selected], "correctness": _ratio_block(verdicts, ("state", "counts", "full") if ledger else JUDGEMENTS),
                "timing": _timing(attempts)}

    by_depth = {str(d): pooled([c for c in pool if c["depth"] == d]) for d in sorted({c["depth"] for c in pool})}
    by_category = {cat: pooled([c for c in queries["cases"] if c["category"] == cat]) for cat in sorted({c["category"] for c in queries["cases"]})}
    by_command = {}
    for command in COMMANDS:
        selected = [a for c in queries["cases"] if c["command"] == command for a in by_slot.get((c["caseId"], "measure"), [])]
        if selected:
            by_command[command] = _timing(selected)
    timing_cases = [r for r in case_rows if r["role"] == "timing"]
    all_verdicts = [v for r in case_rows for v in verdicts_by_case[r["caseId"]]]
    fully_successful = sum(1 for r in case_rows if r["recorded"]["measured"] and r["timing"]["failureRate"]["num"] == 0)
    success_attempts = [a for a in measured_all if a["outcome"] in SUCCESS]
    headline = {"measuredAttempts": len(measured_all), "failureRate": ratio(len(measured_all) - len(success_attempts), len(measured_all)),
                "fullyCorrectRate": ratio(sum(v["full"] for v in all_verdicts), len(all_verdicts)),
                "successCoverage": ratio(fully_successful, len(case_rows)),
                "timingCases": len(timing_cases), "controlCases": len(case_rows) - len(timing_cases)}
    failures = [{"seq": a["seq"], "caseId": a["caseId"], "outcome": a["outcome"], "code": a["code"], "exitCode": a["exitCode"]} for a in measured_all if a["outcome"] not in SUCCESS]
    slowest = [{"seq": a["seq"], "caseId": a["caseId"], "wallMs": round(a["wallNs"] / 1_000_000, 3), "outcome": a["outcome"]}
               for a in sorted(measured_all, key=lambda a: (-a["wallNs"], a["seq"]))[:5]]
    if failures:
        warnings.append(f"{len(failures)} measured attempt(s) did not succeed; they are kept in every distribution labelled allAttemptsWallMs and listed under failedAttempts")

    # integrity (Neo4j content, via the full-graph digest the tool itself re-verifies) and read-only proof (fingerprints)
    integrity = {}
    for version in sorted(versions):
        before = by_slot.get((f"INTEGRITY:{version}:before", "integrity"), [])
        after = by_slot.get((f"INTEGRITY:{version}:after", "integrity"), [])
        pair = [(a[0] if a else None) for a in (before, after)]
        ok = all(a and a["outcome"] == "current" for a in pair)
        same = bool(ok and pair[0]["resultDigest"] == pair[1]["resultDigest"])
        integrity[version] = {"beforeOutcome": pair[0]["outcome"] if pair[0] else None, "afterOutcome": pair[1]["outcome"] if pair[1] else None,
                              "bothCurrent": bool(ok), "sameVerifiedGraph": same}
        if not same:
            warnings.append(f"integrity: version {version} was not verified identically before and after the run")
    prints = run["fingerprints"]
    read_only: dict[str, Any] = {"status": "not_recorded", "changedLabels": None}
    if "before" in prints and "afterTiming" in prints:
        changed = sorted(k for k in prints["before"] if prints["before"][k] != prints["afterTiming"].get(k)) + sorted(set(prints["afterTiming"]) - set(prints["before"]))
        read_only = {"status": "unchanged" if not changed else "CHANGED", "changedLabels": changed, "comparedLabels": sorted(prints["before"]),
                     "checksRestored": None if "afterChecks" not in prints else prints["afterChecks"] == prints["before"]}
        if changed:
            warnings.append(f"read-only proof failed: {changed} changed during the timed run")
        if read_only["checksRestored"] is False:
            warnings.append("the temporary authority mutations were not restored byte-exactly")

    # authority and refusal checks (functional smoke, never part of any timing statistic)
    check_rows, executed = [], config["checksRun"]
    for check_id, check in check_of.items():
        expect = expected["checks"][check_id]
        first = by_slot.get((check_id, "check"), [])
        again = by_slot.get((check_id, "recheck"), [])
        if executed is None or check_id not in executed or not first:
            check_rows.append({"checkId": check_id, "kind": check["kind"], "status": "not_run", "expected": expect})
            continue
        got = first[0]
        passed = got["outcome"] == expect["outcome"] and got["code"] == expect["code"]
        recheck = again[0]["outcome"] if again else None
        recheck_ok = (expect["recheck"] is None and not again) or (expect["recheck"] is not None and recheck == expect["recheck"])
        check_rows.append({"checkId": check_id, "kind": check["kind"], "status": "passed" if passed and recheck_ok else "FAILED", "expected": expect,
                           "observed": {"outcome": got["outcome"], "code": got["code"], "recheck": recheck}})
    checks_status = "not_run" if all(r["status"] == "not_run" for r in check_rows) else (
        "passed" if all(r["status"] == "passed" for r in check_rows) else "FAILED")
    warm_all = [a for a in run["attempts"] if a["phase"] == "warmup"]
    return {
        "schemaVersion": SCHEMA_SCORE, "measurementId": run["measurementId"], "recordedAt": run["recordedAt"],
        "provenance": run["provenance"], "scope": run["scope"], "system": run["system"], "config": config,
        "interpretation": {"focusSemantics": FOCUS_SEMANTICS, "latencyScope": WALL_SCOPE, "notMeasured": run["provenance"]["notMeasured"],
                           "stagingVersionNote": "every read/focus includes a whole-version verification (counts, foreign-data scans, observe + digest compare) before its in-memory BFS, "
                                                 "plus CLI start and authority gates; how much each part contributes is unmeasured, and any similarity between depths is a "
                                                 "hypothesis to test with component instrumentation, not a demonstrated cost split",
                           "hopLabel": "depth d = nodes within d undirected hops over all node kinds and edge types; reported as 'depth', never as supply-chain hops",
                           "depthPoolRule": "byDepth pools timing-role focus cases except the unknown-company category"},
        "headline": headline, "cases": case_rows, "byDepth": by_depth, "byCategory": by_category, "byCommand": by_command,
        "decomposition": {"commandWallMs": {c: by_command[c]["successWallMs"] for c in by_command},
                          "components": {name: None for name in COMPONENTS},
                          "note": "component times are NOT instrumented and stay null; differences between command wall times (inspect: CLI start + ledger only; read/focus: plus "
                                  "authority and Neo4j verification) are not a component split"},
        "warmupsExcluded": {"attempts": len(warm_all), "wallMs": distribution(_ms(warm_all)) if warm_all else None},
        "integrity": integrity, "readOnly": read_only, "checks": {"status": checks_status, "rows": check_rows},
        "usage": run["usage"], "slowestAttempts": slowest, "failedAttempts": failures, "warnings": warnings,
    }


# ------------------------------------------------------------------ report --------------------------------------------------------------------

def _fmt(value: Any) -> str:
    return "-" if value is None else (f"{value:.1f}" if isinstance(value, float) else str(value))


def _rate(block: dict[str, Any]) -> str:
    return f"{block['num']}/{block['den']}"


def render_markdown(score: dict[str, Any]) -> str:
    h, cfg = score["headline"], score["config"]
    lines = [f"# graph tool baseline `{score['measurementId']}`", "",
             "**측정 대상:** `zoop-ai-graph focus/read/inspect` CLI 호출 1회의 wall time과 그 이웃 결과의 정확성. 합성 그래프(authored replay)를 임시 Neo4j에 올린 뒤 측정했다.",
             "AI/RAG 답변 품질, agent 도구 선택, 방향 공급망 순회·경로 추론, Neo4j 순회 성능, 빠른 모델의 성능은 **측정하지 않았다**.", "",
             f"- `focus` 의미: {score['interpretation']['focusSemantics']}.",
             f"- 시간 범위: {score['interpretation']['latencyScope']}.",
             f"- 설정: repeats={cfg['repeats']}, warm-up={cfg['warmups']} (통계 제외, 원시 기록은 run 파일에 모두 있음), invoker={cfg['invoker']}.",
             f"- 모델 호출 관측 {score['usage']['modelCalls']}, provider 호출 관측 {score['usage']['providerCalls']} "
             f"(사용량을 보고한 시도 {score['usage']['attemptsWithUsage']}, 보고하지 않은 시도 {score['usage']['attemptsWithoutUsage']}).", "",
             "## 요약", "",
             f"- 측정 시도 {h['measuredAttempts']}, 실패율 {_rate(h['failureRate'])}, 완전 정답률 {_rate(h['fullyCorrectRate'])}, 전 시도 성공 case {_rate(h['successCoverage'])}.",
             f"- 읽기 전용 증거: {score['readOnly']['status']} (변경된 항목 {score['readOnly']['changedLabels']}).",
             f"- authority/거부 점검(타이밍 제외): {score['checks']['status']}.", "",
             "## depth별 (focus, timing role, unknown-company 제외)", "",
             "| depth | cases | 완전 정답 | 이웃 노드 | 거리 | edge 집합 | 방향 | 속성 | 실패율 | 성공 p50 ms | 성공 p95 ms | 전체 p95 ms | 성공 n | 시도 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for depth, block in score["byDepth"].items():
        c, t = block["correctness"], block["timing"]
        lines.append(f"| {depth} | {len(block['cases'])} | {_rate(c['full'])} | {_rate(c['nodeSet'])} | {_rate(c['distances'])} | {_rate(c['edgeSet'])} | {_rate(c['orientation'])} | "
                     f"{_rate(c['attributes'])} | {_rate(t['failureRate'])} | {_fmt(t['successWallMs']['p50'])} | {_fmt(t['successWallMs']['p95'])} | "
                     f"{_fmt(t['allAttemptsWallMs']['p95'])} | {t['successWallMs']['n']} | {t['attempts']} |")
    lines += ["", "## command별 지연 (성공 시도)", "", "| command | 성공 p50 ms | 성공 p95 ms | 전체 p95 ms | 실패율 | 성공 n | 시도 |", "|---|---|---|---|---|---|---|"]
    for command, t in score["byCommand"].items():
        lines.append(f"| {command} | {_fmt(t['successWallMs']['p50'])} | {_fmt(t['successWallMs']['p95'])} | {_fmt(t['allAttemptsWallMs']['p95'])} | {_rate(t['failureRate'])} | "
                     f"{t['successWallMs']['n']} | {t['attempts']} |")
    lines += ["", "구성요소별 시간(파이썬 시작·import, SQLite, authority, Bolt 검증, BFF 메모리 BFS)은 계측하지 않아 모두 null이다. command 간 차이는 구성요소 분해가 아니다.", "",
              "## case별", "", "| case | 종류 | command | anchor | depth | 완전 정답 | 방향 | 실패율 | 성공 p50 ms | 성공 p95 ms | 성공 n | 시도 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in score["cases"]:
        c, t = r["correctness"], r["timing"]
        lines.append(f"| {r['caseId']} | {r['category']} | {r['command']} | {r['companyId'] or '-'} | {r['depth'] or '-'} | {_rate(c['full'])} | "
                     f"{_rate(c['orientation']) if 'orientation' in c else '-'} | {_rate(t['failureRate'])} | {_fmt(t['successWallMs']['p50'])} | {_fmt(t['successWallMs']['p95'])} | "
                     f"{t['successWallMs']['n']} | {t['attempts']} |")
    scopes = [(f"depth {d}", b["timing"]) for d, b in score["byDepth"].items()] + [(f"command {c}", t) for c, t in score["byCommand"].items()] + \
             [(r["caseId"], r["timing"]) for r in score["cases"]]
    caveats = [f"- {label}: {name} 시도 {t[key]['n']}개 기준 — {', '.join(t[key]['caveats'])}"
               for label, t in scopes for name, key in (("성공", "successWallMs"), ("전체", "allAttemptsWallMs")) if t[key]["caveats"]]
    if caveats:
        lines += ["", "## 표본 주의 (백분위수는 표본 수가 적으면 최댓값과 같거나 불안정하다)", ""] + caveats
    lines += ["", "## 가장 느린 시도", ""] + [f"- seq {s['seq']} {s['caseId']}: {s['wallMs']} ms ({s['outcome']})" for s in score["slowestAttempts"]]
    if score["failedAttempts"]:
        lines += ["", "## 실패한 측정 시도 (모두 기록)", ""] + [f"- seq {f['seq']} {f['caseId']}: {f['outcome']} {f['code'] or ''}" for f in score["failedAttempts"]]
    if score["warnings"]:
        lines += ["", "## 경고", ""] + [f"- {w}" for w in score["warnings"]]
    lines += ["", "## authority·거부 점검", ""]
    for row in score["checks"]["rows"]:
        lines.append(f"- {row['checkId']} ({row['kind']}): {row['status']} expected={row['expected']} observed={row.get('observed')}")
    return "\n".join(lines) + "\n"
