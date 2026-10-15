#!/usr/bin/env python3
"""Real-process smoke for the read-only graph routes: real uvicorn on 127.0.0.1, the real installed `zoop-ai-graph`, a REAL isolated Neo4j.

It FAILS, never skips, without the environment below. Required:
    ZOOP_GRAPH_SMOKE_URI=bolt://127.0.0.1:<port>   an EMPTY, isolated Neo4j 5 database nothing else uses (loopback only)
    ZOOP_GRAPH_AUTH=none|basic  [ZOOP_GRAPH_USER / ZOOP_GRAPH_PASSWORD]   [ZOOP_GRAPH_SMOKE_DATABASE=neo4j]
    make pipeline-install && make service-install                         (the private PoC credential is needed for the pipeline)
Run: `make service-graph-smoke` or `ai/service/.venv/bin/python ai/service/scripts/graph_service_smoke.py`.

What it does. The operator side (ai/pipeline's interpreter) builds an OWNED synthetic world with `ai/evaluation/scripts/graph_tool_bench.py prepare`: actual
ingestion, S2 and S3 through the existing CLIs, `init` of the empty database, `freeze` and `project` of two versions (`main`: 6 nodes, 6 edges; `split`:
4 nodes, 2 edges). The operator lists them in a server-owned allowlist per principal; the service reads copies of the source registry and the canonical
registry so the smoke can revoke and change them. Every HTTP answer is compared with a direct `zoop-ai-graph` subprocess (the oracle) AND with the
hand-authored expectation of the authored world (never derived from the tool under test). Then: principal isolation, digest/source pins, depth 1..3 and an
absent company, strict query validation, source revocation and canonical change (withheld, then current again), planted graph corruption (withheld, then
current again), an operator writer holding the ledger (503 busy), a real deadline (503), and finally that no credential, URI, path or source text reached a
response or a log, that the operator ledgers are byte-identical, and that nothing called a model. Only this run's own versions are removed (`cleanup`).
The throwaway database itself is disposed by its owner; this script never wipes a database and never starts or stops Neo4j.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE / "tests"))
sys.path.insert(0, str(SERVICE / "pipeline_tests"))

from graph_support import GraphWorkspace, focus_url, status_url, version_entry  # noqa: E402
from relation_support import PIPELINE_BIN, PIPELINE_PYTHON, tree  # noqa: E402
from support import ServiceProcess, canonical, remove_tree  # noqa: E402

ROOT = SERVICE.parents[1]
BENCH = ROOT / "ai" / "evaluation" / "scripts" / "graph_tool_bench.py"
GRAPH_CLI = PIPELINE_BIN / "zoop-ai-graph"
RUNTIME_SCHEMA = "zoop-graph-projection-1"
# Authored source text that must never appear in any answer or log (the graph holds IDs and coordinates only).
SOURCE_TEXT = ("example.invalid", "합성 공급 계약", "합성 공장 착공", "authored producer reason", "authored review", "operator-a")
MAIN_TRIPLES = {"dc": ("INVESTS_IN", "kr-000400", "kr-000300"), "cb": ("SUPPLIES", "kr-000300", "kr-000100"), "ca": ("SUPPLIES", "kr-000300", "kr-000050"),
                "ab": ("COMPETES_WITH", "kr-000050", "kr-000100"), "be": ("PARTICIPATES_IN", "kr-000100", "event:main-event"),
                "bt": ("RELATES_TO_TOPIC", "kr-000100", "topic:ev-supply-chain")}
# Hand-authored from the world (ai/evaluation/fixtures/graph-tool/expected.json GT01..GT04): anchor, depth -> ({node: distance}, [edge names])
EXPECTED = {("kr-000400", 1): ({"kr-000400": 0, "kr-000300": 1}, ["dc"]),
            ("kr-000400", 2): ({"kr-000400": 0, "kr-000300": 1, "kr-000100": 2, "kr-000050": 2}, ["dc", "cb", "ca"]),
            ("kr-000400", 3): ({"kr-000400": 0, "kr-000300": 1, "kr-000100": 2, "kr-000050": 2, "event:main-event": 3, "topic:ev-supply-chain": 3},
                               ["dc", "cb", "ca", "ab", "be", "bt"]),
            ("kr-000100", 1): ({"kr-000100": 0, "kr-000050": 1, "kr-000300": 1, "event:main-event": 1, "topic:ev-supply-chain": 1}, ["ab", "cb", "be", "bt"])}


class SmokeFailure(Exception):
    pass


def check(condition: object, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def error_of(response) -> dict[str, Any]:
    return response.json()["error"]


class Smoke:
    def __init__(self, root: Path):
        self.root, self.started = root, []
        self.manifest: dict[str, Any] = {}
        self.sources, self.canonical = root / "sources.json", root / "canonical.json"
        self.secrets: list[str] = []
        self.answers: list[str] = []

    # ---- the operator side ----

    def prepare(self, run_id: str) -> None:
        owned, manifest = self.root / "world", self.root / "manifest.json"
        done = subprocess.run([str(PIPELINE_PYTHON), str(BENCH), "prepare", "--root", str(owned), "--manifest", str(manifest), "--run-id", run_id,
                               "--environment-note", "graph service smoke"], capture_output=True, text=True, timeout=1800, env=dict(os.environ))
        check(done.returncode == 0, "prepare failed: " + done.stdout[-1500:] + done.stderr[-1500:])
        self.manifest = json.loads(manifest.read_text(encoding="utf-8"))
        shutil.copyfile(self.manifest["sources"], self.sources)
        shutil.copyfile(self.manifest["canonical"], self.canonical)
        self.sources_original = self.sources.read_bytes()

    def cleanup(self) -> None:
        manifest = self.root / "manifest.json"
        if manifest.exists():
            done = subprocess.run([str(PIPELINE_PYTHON), str(BENCH), "cleanup", "--manifest", str(manifest)], capture_output=True, text=True, timeout=600,
                                  env=dict(os.environ))
            check(done.returncode == 0, "cleanup refused (owned state retained for manual recovery): " + done.stdout[-800:] + done.stderr[-800:])

    def workspace(self, name: str, versions: list[dict] | None = None) -> GraphWorkspace:
        auth = {key: os.environ[key] for key in ("ZOOP_GRAPH_AUTH", "ZOOP_GRAPH_USER", "ZOOP_GRAPH_PASSWORD") if key in os.environ}
        ws = GraphWorkspace(self.root / name, command=GRAPH_CLI, auth=auth, versions=versions)
        ws.graph_state, ws.relation_state = Path(self.manifest["stateDir"]), Path(self.manifest["relationStateDir"])
        ws.extraction_state, ws.ingestion_state = Path(self.manifest["extractionStateDir"]), Path(self.manifest["ingestionStateDir"])
        ws.sources, ws.canonical = self.sources, self.canonical
        return ws

    def direct(self, ws: GraphWorkspace, command: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """The oracle: the installed command run directly, the way the service runs it, on the same ledgers."""
        argv = [str(GRAPH_CLI), command, "--state-dir", str(ws.graph_state), "--relation-state-dir", str(ws.relation_state), "--extraction-state-dir",
                str(ws.extraction_state), "--ingestion-state-dir", str(ws.ingestion_state), "--sources", str(ws.sources), "--canonical", str(ws.canonical)]
        env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "ZOOP_STATE_DIR": str(ws.app_state), "ZOOP_AI_WORKER_STATE_DIR": str(ws.worker),
               **{key: value for key, value in os.environ.items() if key in ("ZOOP_GRAPH_AUTH", "ZOOP_GRAPH_USER", "ZOOP_GRAPH_PASSWORD")}}
        done = subprocess.run(argv, input=json.dumps({"schemaVersion": RUNTIME_SCHEMA, **payload}).encode(), capture_output=True, env=env, timeout=180)
        return done.returncode, json.loads(done.stdout)

    def ledgers(self) -> dict[str, Any]:
        return {name: tree(Path(self.manifest[name])) for name in ("stateDir", "relationStateDir", "extractionStateDir", "ingestionStateDir")}

    def raw_graph(self, action: str, version: str, saved: Path) -> None:
        """Test-only direct driver (pipeline interpreter): plant or undo one property edit on the version's SUPPLIES edges. Never the code under test."""
        program = (
            "import json, os, sys\nfrom neo4j import GraphDatabase, basic_auth\n"
            "uri, database, version, action, saved = sys.argv[1:6]\n"
            "auth = basic_auth(os.environ['ZOOP_GRAPH_USER'], os.environ['ZOOP_GRAPH_PASSWORD']) if os.environ['ZOOP_GRAPH_AUTH'] == 'basic' else None\n"
            "driver = GraphDatabase.driver(uri, auth=auth)\n"
            "with driver.session(database=database) as session:\n"
            "    if action == 'tamper':\n"
            "        rows = [r.data() for r in session.run('MATCH ()-[e:ZG_SUPPLIES {v: $v}]->() RETURN e.vk AS vk, e.productScope AS p', v=version)]\n"
            "        assert rows, 'no SUPPLIES edge'\n"
            "        open(saved, 'w').write(json.dumps(rows))\n"
            "        session.run(\"MATCH ()-[e:ZG_SUPPLIES {v: $v}]->() SET e.productScope = 'tampered'\", v=version).consume()\n"
            "    else:\n"
            "        for row in json.load(open(saved)):\n"
            "            if row['p'] is None:\n"
            "                session.run('MATCH ()-[e:ZG_SUPPLIES {vk: $vk}]->() REMOVE e.productScope', vk=row['vk']).consume()\n"
            "            else:\n"
            "                session.run('MATCH ()-[e:ZG_SUPPLIES {vk: $vk}]->() SET e.productScope = $p', vk=row['vk'], p=row['p']).consume()\n"
            "driver.close()\n")
        done = subprocess.run([str(PIPELINE_PYTHON), "-c", program, os.environ["ZOOP_GRAPH_SMOKE_URI"], self.manifest["database"], version, action, str(saved)],
                              capture_output=True, text=True, timeout=120, env={"PATH": "/usr/bin:/bin", **{k: v for k, v in os.environ.items() if k.startswith("ZOOP_GRAPH_")}})
        check(done.returncode == 0, f"raw graph {action} failed: {done.stderr[-800:]}")

    # ---- the service side ----

    def launch(self, ws: GraphWorkspace, *, deadline: str | None = None) -> ServiceProcess:
        service = ServiceProcess(ws, env=ws.env(), launcher=deadline is not None, launcher_env={"ZOOP_TEST_GRAPH_DEADLINE": deadline} if deadline else None)
        self.started.append(service)
        self.secrets += [s for s in ws.private_strings() if len(s) > 3]
        return service.start()

    def get(self, service: ServiceProcess, url: str, as_: str = "grapher"):
        response = service.request("GET", url, as_=as_)
        self.answers.append(response.text + json.dumps(dict(response.headers)))
        return response

    def revoke_sources(self) -> None:
        registry = json.loads(self.sources_original)
        registry["sources"][0]["grant"]["enabled"] = False
        self.sources.write_text(canonical(registry), encoding="utf-8")

    def mutate_canonical(self, original: bytes, *, drop_topics: bool) -> None:
        document = json.loads(original)
        if drop_topics:
            document["entries"] = [entry for entry in document["entries"] if entry.get("kind") != "topic"]
        self.canonical.write_text(canonical(document), encoding="utf-8")


def withheld(response, code: str, version: str, focus: tuple[str, int] | None = None) -> None:
    """A withheld answer carries identity, state, a reason and, for a focus, ONLY the requested company and depth echoed back (found=null). The echo is
    request data, not graph content: it must appear exactly once and be exactly the request; everything else must be free of any graph identifier."""
    wire = response.json()
    check(response.status_code == 200 and wire["delivery"] == {"state": "withheld", "reason": code}, f"expected withheld {code}: {response.status_code} {response.text[:300]}")
    check(wire["versionId"] == version and wire["publication"] == "not-published" and wire["verification"] is None, "withheld carries identity only")
    check(wire.get("graph") is None and wire.get("evidence") is None, "withheld carries no graph or evidence")
    common = {"schemaVersion", "versionId", "state", "publication", "delivery", "verification", "observedAt"}
    text = response.text
    if focus is None:
        check(set(wire) == common, f"a withheld status has exactly the identity fields: {sorted(wire)}")
    else:
        company, depth = focus
        check(set(wire) == common | {"focus", "graph", "evidence"}, f"a withheld focus has exactly the identity fields plus the request echo: {sorted(wire)}")
        check(wire["focus"] == {"companyId": company, "depth": depth, "found": None} and text.count(company) == 1, "the focus echo is exactly the request")
        text = text.replace(company, "", 1)   # the one permitted occurrence; any other graph identifier below still fails
    check(not any(marker in text for marker in ("kr-", "event:", "topic:", "ev-", "rel-")), "withheld leaked graph text")


def run(smoke: Smoke, run_id: str) -> list[str]:
    lines: list[str] = []
    smoke.prepare(run_id)
    main_id, split_id = smoke.manifest["versions"]["main"], smoke.manifest["versions"]["split"]
    before = smoke.ledgers()
    original_canonical = smoke.canonical.read_bytes()
    probe = smoke.workspace("probe")
    oracle: dict[str, dict[str, Any]] = {}
    for name, version in (("main", main_id), ("split", split_id)):
        code, out = smoke.direct(probe, "read", {"versionId": version})
        check(code == 0 and out["delivery"]["status"] == "current" and out["usage"] == {"providerCalls": 0, "modelCalls": 0}, f"oracle read {name}: {out}")
        oracle[name] = out
    check((oracle["main"]["verification"]["nodes"], oracle["main"]["verification"]["edges"]) == (6, 6)
          and (oracle["split"]["verification"]["nodes"], oracle["split"]["verification"]["edges"]) == (4, 2), "prepared world has the authored size")
    pin = oracle["split"]["source"]["relation"]
    versions = [version_entry("grapher", main_id, oracle["main"]["digests"]["graph"], oracle["main"]["digests"]["payload"]),
                version_entry("alpha", split_id, oracle["split"]["digests"]["graph"], oracle["split"]["digests"]["payload"], sourceRelation=pin),
                version_entry("beta", main_id, "0" * 64, oracle["main"]["digests"]["payload"])]   # beta's pinned graph digest is wrong on purpose
    ws = smoke.workspace("svc", versions)
    service = smoke.launch(ws)
    password = os.environ.get("ZOOP_GRAPH_PASSWORD")
    smoke.secrets += [s for s in (os.environ["ZOOP_GRAPH_SMOKE_URI"], password, os.environ.get("ZOOP_GRAPH_USER"), str(smoke.root), *SOURCE_TEXT) if s]

    # 1 authority and isolation
    check(error_of(service.request("GET", status_url(main_id), as_=None))["code"] == "authentication_required", "no token is 401")
    check(error_of(smoke.get(service, status_url(main_id), "reader"))["code"] == "scope_denied", "another scope is 403")
    refusals = [smoke.get(service, status_url(split_id), "grapher"), smoke.get(service, status_url(main_id), "alpha"), smoke.get(service, status_url("never-existed"), "grapher"),
                smoke.get(service, focus_url(split_id), "grapher")]
    check(all(r.status_code == 403 for r in refusals) and len({json.dumps({k: v for k, v in error_of(r).items() if k != "requestId"}, sort_keys=True) for r in refusals}) == 1
          and error_of(refusals[0])["code"] == "version_not_allowed", "unlisted, other principal's and unknown versions answer identically")
    lines.append("isolation: status=passed, principals=3, unlisted/other/unknown identical 403")

    # 2 status and the digests
    status = smoke.get(service, status_url(main_id)).json()
    check(status["delivery"]["state"] == "current" and status["state"] == "ready" and status["publication"] == "not-published", f"main status current: {status}")
    check(status["verification"] == {"graphDigest": oracle["main"]["digests"]["graph"], "payloadDigest": oracle["main"]["digests"]["payload"], "nodes": 6, "edges": 6},
          "status verification equals the oracle")
    check(not {"graph", "evidence", "focus"} & set(status), "status carries no content")
    split_status = smoke.get(service, status_url(split_id), "alpha").json()   # alpha also pins the frozen S3 relation job, and it matches
    check(split_status["delivery"]["state"] == "current" and split_status["verification"]["edges"] == 2, f"split status with a matching source pin: {split_status}")
    mismatch = smoke.get(service, focus_url(main_id), "beta")
    withheld(mismatch, "version_pin_mismatch", main_id, ("kr-000100", 1))
    lines.append("digests: status=passed, verification equals the oracle, wrong pinned digest withheld version_pin_mismatch, source pin matched")

    # 3 focus 1..3 against the oracle and the hand-authored expectation, plus an absent company
    for (company, depth), (nodes, edge_names) in EXPECTED.items():
        response = smoke.get(service, focus_url(main_id, company, depth))
        wire = response.json()
        check(response.status_code == 200 and wire["delivery"]["state"] == "current" and wire["focus"] == {"companyId": company, "depth": depth, "found": True},
              f"focus {company} depth {depth}: {response.text[:300]}")
        code, direct = smoke.direct(probe, "focus", {"versionId": main_id, "companyId": company, "depth": depth})
        check(code == 0, "oracle focus")
        check(wire["graph"]["nodes"] == direct["graph"]["nodes"] and wire["graph"]["edges"] == direct["graph"]["edges"] and wire["evidence"] == direct["evidence"],
              f"HTTP focus equals the oracle for {company} depth {depth}")
        check({n["id"]: n["distance"] for n in wire["graph"]["nodes"]} == nodes, f"nodes match the hand-authored expectation for {company} depth {depth}")
        check(sorted((e["type"], e["subject"]["id"], e["object"]["id"]) for e in wire["graph"]["edges"]) == sorted(MAIN_TRIPLES[n] for n in edge_names),
              f"edges match the hand-authored expectation for {company} depth {depth}")
        referenced = {i for e in wire["graph"]["edges"] for i in (*e["evidence"]["relation"], *e["evidence"]["validity"], *e["evidence"]["steps"][0], *e["evidence"]["steps"][1])}
        check({e["evidenceId"] for e in wire["evidence"]} == referenced, "evidence is exactly what the shown edges reference")
    absent = smoke.get(service, focus_url(main_id, "kr-999999", 2)).json()
    check(absent["delivery"]["state"] == "current" and absent["focus"]["found"] is False and absent["graph"] == {"nodes": [], "edges": []} and absent["evidence"] == [],
          "an absent company is a verified not-found")
    for bad in ("0", "4", "01", "abc", ""):
        check(smoke.get(service, focus_url(main_id, "kr-000100", bad)).status_code == 422, f"depth {bad!r} is refused")
    check(smoke.get(service, f"{focus_url(main_id)}&extra=1").status_code == 422, "an unknown query parameter is refused")
    lines.append("focus: status=passed, depth 1..3 equal the oracle and the hand-authored expectation, absent company found=false, strict query")

    # 4 source revocation, then restoration
    smoke.revoke_sources()
    try:
        for url in (focus_url(main_id, "kr-000400", 3), status_url(main_id)):
            withheld(smoke.get(service, url), "source_unauthorized", main_id, ("kr-000400", 3) if "focus" in url else None)
    finally:
        smoke.sources.write_bytes(smoke.sources_original)   # the exact original bytes
    check(smoke.get(service, focus_url(main_id, "kr-000400", 1)).json()["delivery"]["state"] == "current", "restored sources are current again")
    lines.append("source revocation: status=passed, withheld source_unauthorized without content, current again after restore")

    # 5 canonical change, then restoration
    smoke.mutate_canonical(original_canonical, drop_topics=True)
    try:
        withheld(smoke.get(service, focus_url(main_id, "kr-000400", 3)), "canonical_mapping_changed", main_id, ("kr-000400", 3))
        check(smoke.get(service, focus_url(split_id, "kr-000050", 1), "alpha").json()["delivery"]["state"] == "current", "a version that uses no removed decision stays current")
    finally:
        smoke.canonical.write_bytes(original_canonical)
    check(smoke.get(service, focus_url(main_id, "kr-000400", 3)).json()["delivery"]["state"] == "current", "restored canonical registry is current again")
    lines.append("canonical change: status=passed, withheld canonical_mapping_changed, unaffected version stays current, current again after restore")

    # 6 planted corruption in the throwaway database, then undo
    saved = smoke.root / "tampered.json"
    smoke.raw_graph("tamper", main_id, saved)
    try:
        withheld(smoke.get(service, focus_url(main_id, "kr-000400", 3)), "graph_version_corrupt", main_id, ("kr-000400", 3))
        withheld(smoke.get(service, status_url(main_id)), "graph_version_corrupt", main_id)
    finally:
        smoke.raw_graph("restore", main_id, saved)
    check(smoke.get(service, focus_url(main_id, "kr-000400", 3)).json()["delivery"]["state"] == "current", "the restored graph verifies again")
    lines.append("corruption: status=passed, planted edit withheld graph_version_corrupt (fail closed), current again after the exact undo")

    # 7 an operator writer holding the ledger
    descriptor = os.open(Path(smoke.manifest["stateDir"]) / "graph.lock", os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        busy = smoke.get(service, focus_url(main_id))
        error = error_of(busy)
        check(busy.status_code == 503 and (error["code"], error["runtimeCode"], error["retryable"]) == ("runtime_busy", "graph_busy", True) and busy.headers["retry-after"]
              and "graph" not in busy.json(), f"a held ledger is a retryable 503, never an empty graph: {busy.text[:300]}")
    finally:
        os.close(descriptor)
    check(smoke.get(service, focus_url(main_id)).json()["delivery"]["state"] == "current", "released ledger serves again")
    lines.append("busy: status=passed, held graph.lock is 503 runtime_busy (graph_busy) with Retry-After, served again after release")

    # 8 a real deadline on a second service (the child cannot finish in 50 ms)
    quick = smoke.launch(smoke.workspace("deadline", versions), deadline="0.05")
    timed_out = smoke.get(quick, status_url(main_id))
    check(timed_out.status_code == 503 and error_of(timed_out)["code"] == "runtime_unavailable" and error_of(timed_out)["retryable"], f"a missed deadline is a retryable 503: {timed_out.text[:300]}")
    lines.append("deadline: status=passed, real child stopped at the deadline, 503 runtime_unavailable")

    # 9 nothing private, nothing written, no model
    for service_process in smoke.started:
        service_process.stop()
    logs = "\n".join(service_process.logs() for service_process in smoke.started)
    leaked = [s for s in smoke.secrets if s in logs or any(s in answer for answer in smoke.answers)]
    check(not leaked, f"{len(leaked)} private string(s) reached a response, header or log")
    check(smoke.ledgers() == before, "operator ledgers are byte-identical (graph, relation, extraction, ingestion)")
    lines.append(f"privacy: status=passed, strings checked={len(smoke.secrets)}, ledgers unchanged, providerCalls=0, modelCalls=0 (oracle usage and no model path)")
    return lines


def main() -> int:
    missing = [name for name in ("ZOOP_GRAPH_SMOKE_URI", "ZOOP_GRAPH_AUTH") if not os.environ.get(name)]
    if missing or os.environ["ZOOP_GRAPH_AUTH"] not in ("none", "basic"):
        print("FAILED: set ZOOP_GRAPH_SMOKE_URI (loopback bolt://127.0.0.1:<port>, empty isolated Neo4j) and ZOOP_GRAPH_AUTH=none|basic "
              "(+ ZOOP_GRAPH_USER/ZOOP_GRAPH_PASSWORD); this smoke never skips", file=sys.stderr)
        return 1
    for path in (PIPELINE_PYTHON, GRAPH_CLI, BENCH):
        if not path.is_file():
            print(f"FAILED: {path.name} is missing: run `make pipeline-install` (private PoC credential)", file=sys.stderr)
            return 1
    root = Path(tempfile.mkdtemp(prefix="zoop-ai-graph-service-smoke-")).resolve()
    smoke, run_id = Smoke(root), "gsm" + os.urandom(4).hex()
    failure: str | None = None
    lines: list[str] = []
    cleanup_failure: str | None = None
    try:
        lines = run(smoke, run_id)
    except SmokeFailure as error:
        failure = str(error)
    except Exception as error:  # noqa: BLE001 - report the class only: a driver or subprocess message must not carry a credential
        failure = f"unexpected {type(error).__name__}"
    finally:
        for service in smoke.started:
            service.close()
        try:
            smoke.cleanup()
        except SmokeFailure as error:
            cleanup_failure = str(error)
        except Exception as error:  # noqa: BLE001 - class only, never a driver or subprocess message
            cleanup_failure = f"cleanup unexpected {type(error).__name__}"
        if cleanup_failure is not None:   # reported alongside any primary failure, never replaced by it
            failure = cleanup_failure if failure is None else f"{failure}\nALSO cleanup failed: {cleanup_failure}"
        for service in smoke.started:
            remove_tree(service.workspace.root)
        if failure is None:
            remove_tree(root)
    if failure is not None:
        print("FAILED: " + failure, file=sys.stderr)
        print(f"retained for inspection: {root}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    print("graph service smoke: status=passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
