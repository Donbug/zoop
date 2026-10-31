#!/usr/bin/env python3
"""Synthetic two-context AI HTTP -> Java/Postgres registration/bindings/import -> public reads.

Run with the installed pipeline interpreter and a freshly built API jar against an EMPTY loopback database.
The fixture uses only the existing loopback simulated provider. All production read requests invoke real native
exports. Revocation and misroute faults touch only this script's newly created synthetic directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import graph_handoff_import_smoke as graph

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "ai/service"
sys.path.insert(0, str(SERVICE / "tests"))
from support import ServiceProcess, Workspace

base, hs, check = graph.base, graph.hs, graph.check
OBSERVATIONS = "/internal/v1/observations/export"


def save(path, value):
    path.write_bytes(base.json_bytes(value) + b"\n")
    path.chmod(0o600)


def native_command(root):
    """Real installed module with a test-owned final-freshness revocation boundary."""
    command, arm = root / "ingestion-export", root / "freshness-fault.json"
    command.write_text(f"#!{sys.executable}\n" + f'''import json, os, sys
from pathlib import Path
sys.path.insert(0, {str(ROOT / 'ai/pipeline/src')!r})
from zoop_ai_pipeline import ingestion_cli
assert Path(ingestion_cli.__file__).resolve() == Path({str(ROOT / 'ai/pipeline/src/zoop_ai_pipeline/ingestion_cli.py')!r})
assert not {{"DB_PASSWORD", "ZOOP_AI_API_KEY", "TYPESAFE_API_KEY", "ZOOP_AI_SERVICE_PRINCIPALS"}} & set(os.environ)
def guard(event, args):
    if event.startswith("socket."):
        raise RuntimeError("native export network denied")
    if event == "open" and isinstance(args[0], (str, bytes)) and os.path.basename(os.fsdecode(args[0])).startswith(".env"):
        raise RuntimeError("dotenv denied")
sys.addaudithook(guard)
arm = Path({str(arm)!r})
if arm.exists():
    fault = json.loads(arm.read_bytes())
    fault["calls"] += 1
    arm.write_text(json.dumps(fault))
    if fault["calls"] == fault["revokeAt"]:
        path = Path(fault["sources"])
        registry = json.loads(path.read_bytes())
        registry["sources"][0]["grant"]["allowedOperations"].remove("store")
        path.write_text(json.dumps(registry))
raise SystemExit(ingestion_cli.main())
''')
    command.chmod(0o700)
    return command, arm


def read_service(args, root, world, command, allowlist=None):
    ws = Workspace(root)
    ws.credentials.scopes = {"handoffer": ["observation.read", "handoff.read", "handoff.exposure"], "reader": ["analysis.read"]}
    ws.credentials.tokens = {key: ws.credentials.tokens[key] for key in ws.credentials.scopes}
    env = ws.env(ZOOP_AI_SERVICE_WORKER_COMMAND=str(args.worker_cli), ZOOP_STATE_DIR=str(root / "app"),
                 PYTHONPATH=str(SERVICE / "src"), PYTHONDONTWRITEBYTECODE="1",
                 ZOOP_AI_SERVICE_INGESTION_COMMAND=str(command),
                 ZOOP_AI_SERVICE_OBSERVATION_SOURCE_CONTEXTS=str(world.context_file),
                 ZOOP_AI_SERVICE_OBSERVATION_SOURCE_CONTEXTS_SHA256=world.context_sha)
    if allowlist:
        env.update(ZOOP_AI_SERVICE_HANDOFF_COMMAND=str(args.handoff_cli), ZOOP_AI_HANDOFF_STATE_DIR=str(world.root / "handoff"),
                   ZOOP_AI_SERVICE_HANDOFF_CANONICAL=str(world.root / "canonical.json"),
                   ZOOP_AI_SERVICE_HANDOFF_DECISIONS=str(world.root / "decisions.json"),
                   ZOOP_AI_SERVICE_HANDOFF_BINDINGS=str(world.root / "bindings.json"),
                   ZOOP_AI_SERVICE_HANDOFF_EXPORTS=str(allowlist),
                   ZOOP_AI_SERVICE_HANDOFF_SOURCE_CONTEXTS=str(world.context_file),
                   ZOOP_AI_SERVICE_HANDOFF_SOURCE_CONTEXTS_SHA256=world.context_sha)
        env.update(ZOOP_AI_SERVICE_HANDOFF_EXPOSURE_COMMAND=str(args.exposure_cli),
                   ZOOP_AI_HANDOFF_EXPOSURE_STATE_DIR=str(world.root / "handoff"),
                   ZOOP_AI_SERVICE_HANDOFF_EXPOSURE_EXPORTS=str(allowlist),
                   ZOOP_AI_SERVICE_HANDOFF_EXPOSURE_SOURCE_CONTEXTS=str(world.context_file),
                   ZOOP_AI_SERVICE_HANDOFF_EXPOSURE_SOURCE_CONTEXTS_SHA256=world.context_sha)
    service = ServiceProcess(ws, env=env)
    service._argv[0] = str(args.service_python)
    service.client.close()
    import httpx
    service.client = httpx.Client(base_url=f"http://127.0.0.1:{ws.port}", timeout=60, trust_env=False)
    service.start()
    return service


def clients(service, *, handoff=False):
    env = {"ZOOP_AI_OBSERVATION_EXPORT_CLIENT_ENABLED": "true",
           "ZOOP_AI_OBSERVATION_EXPORT_CLIENT_BASE_URL": str(service.client.base_url).rstrip("/"),
           "ZOOP_AI_OBSERVATION_EXPORT_CLIENT_TOKEN": service.workspace.credentials.tokens["handoffer"]}
    if handoff:
        env.update(ZOOP_AI_HANDOFF_READ_CLIENT_ENABLED="true",
                   ZOOP_AI_HANDOFF_READ_CLIENT_BASE_URL=str(service.client.base_url).rstrip("/"),
                   ZOOP_AI_HANDOFF_READ_CLIENT_TOKEN=service.workspace.credentials.tokens["handoffer"])
    return env


def operator(jar, root, label, env):
    result = root / f"{label}-result.json"
    done = subprocess.run(jar.argv("--spring.main.web-application-type=none"), env={**jar.base_env(), **env},
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=420)
    (root / f"{label}.log").write_bytes(done.stdout)
    return done.returncode, json.loads(result.read_bytes()) if result.exists() and result.stat().st_size else None


def run(args):
    root = args.output.resolve()
    root.mkdir(mode=0o700)
    db = base.Database(os.environ["DB_URL"], args.db_user or os.environ["DB_USERNAME"], os.environ["DB_PASSWORD"],
                       args.db_name, args.psql_container, args.psql)
    check(not db.tables_exist() or db.scalar("SELECT (SELECT count(*) FROM articles) + (SELECT count(*) FROM graph_versions) = 0"),
          "requires an empty dedicated loopback database")
    world = hs.build_context_world(root / "native")
    decisions = json.loads((world.root / "decisions.json").read_bytes())
    decisions["companies"][0]["publicId"] = "SYNTH:HTTP001"
    save(world.root / "decisions.json", decisions)
    layout = SimpleNamespace(root=root, artifacts=root / "artifacts", requests=root / "requests")
    layout.artifacts.mkdir(mode=0o700)
    layout.requests.mkdir(mode=0o700)
    jar = base.Jar(args.java, args.jar, db, layout)
    command, arm = native_command(root)
    selectors = list(world.refs.values())
    check(len(selectors) == 2 and len(world.contexts) == 2, "two-context fixture")
    ledgers = {str(path): graph.fingerprint(path) for context in world.native_contexts
               for path in (context.paths.ingestion, context.paths.extraction, context.paths.relation, context.metering)}
    checks = []

    def record(name, condition):
        check(condition, name)
        checks.append(name)

    def export(service, selector, status=200, code=None, **kwargs):
        response = service.request("POST", OBSERVATIONS, as_=kwargs.pop("as_", "handoffer"),
                                   body={"schemaVersion": "zoop-ingestion-s2-1", **selector}, **kwargs)
        check(response.status_code == status, f"observation status {response.status_code}, expected {status}")
        check(response.headers.get("cache-control") == "no-store", "observation cache policy")
        if code:
            check(response.json()["error"]["code"] == code, "observation refusal category")
        return response

    service = read_service(args, root / "observation-profile", world, command)
    try:
        native = [export(service, selector).json() for selector in selectors]
        record("two-context-exact-exports", all(out["observation"][key] == ref[key]
               for out, ref in zip(native, selectors) for key in ref))
        export(service, selectors[0], 401, "authentication_required", as_=None)
        export(service, selectors[0], 403, "scope_denied", as_="reader")
        record("authentication-and-scope", True)
        for key in selectors[0]:
            missing = dict(selectors[0])
            del missing[key]
            export(service, missing, 422, "invalid_request")
        export(service, {**selectors[0], "observationId": "invented"}, 422, "invalid_request")
        export(service, {**selectors[0], "ordinal": 99}, 404, "observation_not_found")
        record("closed-full-selector", True)
        registry = world.native_contexts[0].paths.sources
        original = registry.read_bytes()
        try:
            for operation in ("read", "store", "quote-display"):
                revoked = json.loads(original)
                revoked["sources"][0]["grant"]["allowedOperations"].remove(operation)
                save(registry, revoked)
                export(service, selectors[0], 403, "source_unauthorized")
                registry.write_bytes(original)
            record("each-current-source-right-required", True)
        finally:
            registry.write_bytes(original)
        request = root / "documents-request.json"
        save(request, {"schemaVersion": base.IMPORT_SCHEMA, "items": [base.item(ref) for ref in selectors]})
        code, result = operator(jar, root, "documents", {**clients(service), "ZOOP_DOCUMENT_IMPORT_ENABLED": "true",
            "ZOOP_DOCUMENT_IMPORT_OBSERVATION_SOURCE": "http", "ZOOP_DOCUMENT_IMPORT_REQUEST": str(request),
            "ZOOP_DOCUMENT_IMPORT_RESULT": str(root / "documents-result.json"), "ZOOP_ARTIFACT_ROOT": str(layout.artifacts)})
        record("http-document-registration", code == 0 and result and result["status"] == "succeeded")
        record("exact-target-registration", db.scalar("SELECT count(*) FROM article_versions") == 2
               and db.scalar("SELECT count(*) FROM articles WHERE current_version IS NOT NULL") == 0)
        for item in native:
            text = item["document"]["text"].encode()
            stored = layout.artifacts / "extracted_text" / (item["document"]["textArtifactId"] + ".txt")
            record("registered-text-" + item["observation"]["roundId"], stored.read_bytes() == text)
        original_contexts = world.context_file.read_bytes()
        world.context_file.write_bytes(original_contexts + b"\n")
        export(service, selectors[0], 503, "service_configuration_invalid")
        world.context_file.write_bytes(original_contexts)
        record("routing-drift-refused", True)
    finally:
        service.close()

    # An explicit wrong route must not search another ledger that actually contains this observation.
    contexts = json.loads(world.context_file.read_bytes())
    contexts["contexts"][0]["observations"], contexts["contexts"][1]["observations"] = (
        contexts["contexts"][1]["observations"], contexts["contexts"][0]["observations"])
    wrong = root / "misrouted-contexts.json"
    save(wrong, contexts)
    misrouted = SimpleNamespace(context_file=wrong, context_sha=hashlib.sha256(wrong.read_bytes()).hexdigest())
    service = read_service(args, root / "misroute-profile", misrouted, command)
    try:
        response = service.request("POST", OBSERVATIONS, as_="handoffer", body={"schemaVersion": "zoop-ingestion-s2-1", **selectors[0]})
        record("misroute-without-fallback", response.status_code == 404 and response.json()["error"]["code"] in {"round_not_found", "observation_not_found"})
    finally:
        service.close()

    bindings = root / "target-bindings.json"
    code, result = operator(jar, root, "bindings", {"ZOOP_DOCUMENT_BINDINGS_ENABLED": "true",
        "ZOOP_DOCUMENT_BINDINGS_OUTPUT": str(bindings), "ZOOP_DOCUMENT_BINDINGS_RESULT": str(root / "bindings-result.json")})
    record("fresh-target-bindings", code == 0 and result and result["status"] == "succeeded"
           and json.loads(bindings.read_bytes()) == json.loads((world.root / "bindings.json").read_bytes()))
    # This is a fresh synthetic handoff; use the target-derived bytes before its first freeze.
    (world.root / "bindings.json").write_bytes(bindings.read_bytes())
    hid = "http-two-contexts"
    native_operator = hs.Operator(world)
    frozen = native_operator.cli("freeze", hs.manifest_doc(world, hid, hs.file_hashes(world.root)))
    exported = native_operator.cli("export", native_operator.sel(hid))
    allowlist = root / "handoff-exports.json"
    save(allowlist, {"schemaVersion": "zoop-ai-handoff-exports-1", "handoffs": [{"principal": "handoffer", "handoffId": hid,
        "manifestDigest": frozen["receipt"]["manifestDigest"], "bundleDigest": frozen["receipt"]["bundleDigest"]}]})
    db.run("INSERT INTO companies (id,name,name_key,search_text) VALUES ('SYNTH:HTTP001','합성기업','','')")
    service = read_service(args, root / "delivery-profile", world, command, allowlist)
    registry = world.native_contexts[0].paths.sources
    original_registry = registry.read_bytes()
    try:
        url = f"/internal/v1/graph-handoffs/{hid}"
        record("handoff-auth-scope", service.request("GET", url, as_="reader").status_code == 403)
        record("handoff-allowlist", service.request("GET", "/internal/v1/graph-handoffs/unknown", as_="handoffer").status_code == 403)
        answer = service.request("GET", url + "/bundle", as_="handoffer")
        record("native8-current-bundle", answer.status_code == 200 and answer.json()["bundle"] == exported["bundle"]
               and answer.json()["bundle"]["schemaVersion"] == "zoop-graph-handoff-bundle-8")
        exposure = service.request("POST", "/internal/v1/graph-handoffs/exposure", as_="handoffer",
            body={"schemaVersion": "zoop-handoff-exposure-1", "handoffIds": [hid],
                  "changed": {"kind": "source", "sourceId": selectors[0]["sourceId"]}})
        record("multicontext-exposure-preserved", exposure.status_code == 200)
        request = root / "graph-request.json"
        save(request, graph.Smoke.request(hid, frozen["receipt"]["manifestDigest"], frozen["receipt"]["bundleDigest"]))
        graph_env = {**clients(service, handoff=True), "ZOOP_GRAPH_HANDOFF_IMPORT_ENABLED": "true",
                     "ZOOP_GRAPH_HANDOFF_IMPORT_HANDOFF_SOURCE": "http", "ZOOP_GRAPH_HANDOFF_IMPORT_OBSERVATION_SOURCE": "http",
                     "ZOOP_GRAPH_HANDOFF_IMPORT_REQUEST": str(request), "ZOOP_ARTIFACT_ROOT": str(layout.artifacts)}
        save(arm, {"calls": 0, "revokeAt": 3, "sources": str(registry)})
        before = db.snapshot()
        code, result = operator(jar, root, "freshness", {**graph_env, "ZOOP_GRAPH_HANDOFF_IMPORT_RESULT": str(root / "freshness-result.json")})
        record("final-freshness-revocation", code != 0 and result and result["status"] == "failed"
               and json.loads(arm.read_bytes())["calls"] == 3 and db.scalar("SELECT count(*) FROM graph_versions") == 0
               and db.snapshot() == before)
        arm.unlink()
        registry.write_bytes(original_registry)
        code, result = operator(jar, root, "graph", {**graph_env, "ZOOP_GRAPH_HANDOFF_IMPORT_RESULT": str(root / "graph-result.json")})
        record("http-native-handoff-import", code == 0 and result and result["status"] == "succeeded" and result["active"] is False)
        vid = result["graphVersionId"]
        record("inactive-before-explicit-harness-activation", db.scalar("SELECT count(*) FROM graph_versions WHERE active") == 0)
        authorities = []
        for context in world.native_contexts:
            source = json.loads(context.paths.sources.read_bytes())["sources"][0]
            authorities.append({"sourceId": source["sourceId"], "grantId": source["grant"]["grantId"],
                                "revision": source["grant"]["revision"], "sources": str(context.paths.sources)})
        authority = root / "source-authority-set.json"
        save(authority, {"schemaVersion": "zoop-source-authority-set-1", "authorities": authorities})
        db.run(f"""SELECT pg_advisory_xact_lock(x'7a6f6f7067726170'::bigint);
            UPDATE graph_versions SET active=true WHERE id='{vid}';
            INSERT INTO graph_activations(version_id,previous_version_id,action,actor_kind,pointer_changed,admin_id,admin_email_snapshot,reason,activated_at)
            VALUES ('{vid}',NULL,'activate','system',true,NULL,'system','smoke harness: synthetic HTTP activation',now())""")
        with graph.WebRun(jar, {"ZOOP_GRAPH_SNAPSHOT_SOURCE": "artifact", "ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT": str(layout.artifacts),
                "ZOOP_DOCUMENT_READ_ARTIFACT_ROOT": str(layout.artifacts), "ZOOP_DOCUMENT_READ_INGESTION_SOURCES": str(authority)}) as web:
            code, body = web.get("/api/v1/graph")
            public = json.loads(body)
            record("public-two-context-graph", code == 200 and {n["id"] for n in public["nodes"] if n["kind"] == "issue"}
                   == {"issue:context-0", "issue:context-1"})
            texts = {ref["documentId"]: out["document"]["text"] for ref, out in zip(selectors, native)}
            for evidence in exported["bundle"]["evidence"]:
                code, body = web.get("/api/v1/evidence/" + evidence["id"])
                quote = json.loads(body)
                record("public-exact-span-" + evidence["id"], code == 200 and quote["quoteVerified"] is True
                       and quote["quote"] == texts[evidence["articleId"]][evidence["start"]:evidence["end"]])
            revoked = json.loads(original_registry)
            revoked["sources"][0]["grant"]["allowedOperations"].remove("store")
            save(registry, revoked)
            export(service, selectors[0], 403, "source_unauthorized")
            revoked_id = selectors[0]["documentId"]
            evidence = next(e for e in exported["bundle"]["evidence"] if e["articleId"] == revoked_id)
            code, _ = web.get("/api/v1/evidence/" + evidence["id"])
            record("current-authority-set-revocation", code == 404)
            registry.write_bytes(original_registry)
    finally:
        registry.write_bytes(original_registry)
        service.close()
    record("native-ledgers-unchanged", all(graph.fingerprint(Path(path)) == before for path, before in ledgers.items()))
    result = {"status": "passed", "checks": checks, "fixture": "synthetic two native contexts; loopback provider only",
              "paidProviderCalls": 0, "graphVersionId": vid, "documentCount": 2,
              "artifactRoot": str(layout.artifacts), "sourceRoot": str(world.root)}
    save(root / "report.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="new directory; refuses existing output")
    parser.add_argument("--java", default=shutil.which("java"))
    parser.add_argument("--handoff-cli", type=Path, default=ROOT / "ai/pipeline/.venv/bin/zoop-ai-handoff")
    parser.add_argument("--exposure-cli", type=Path, default=ROOT / "ai/pipeline/.venv/bin/zoop-ai-handoff-exposure")
    parser.add_argument("--worker-cli", type=Path, default=ROOT / "ai/worker/.venv/bin/zoop-ai")
    parser.add_argument("--service-python", type=Path, default=SERVICE / ".venv/bin/python")
    parser.add_argument("--psql-container")
    parser.add_argument("--psql", default=shutil.which("psql"))
    parser.add_argument("--db-user")
    parser.add_argument("--db-name")
    args = parser.parse_args()
    args.jar = args.jar.resolve()
    for path in (args.jar, args.handoff_cli, args.exposure_cli, args.worker_cli, args.service_python):
        check(path.is_file(), "required installed executable or built jar missing")
    check(args.java is not None, "java executable required")
    print(json.dumps(run(args), ensure_ascii=False))


if __name__ == "__main__":
    main()
