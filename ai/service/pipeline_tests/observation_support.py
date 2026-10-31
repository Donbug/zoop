"""Synthetic native ingestion -> production HTTP -> actual source-pinned installed-module CLI.

No provider doubles or forged CLI replies. Only test-owned registry/ledger mutations are used
for revocation/corruption cases; every read checks that its source bytes and metadata stay put.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PIPELINE = ROOT / "ai/pipeline"
SERVICE = ROOT / "ai/service"
PYTHON = PIPELINE / ".venv/bin/python"
PATH = "/internal/v1/observations/export"
SCHEMA = "zoop-ingestion-s2-1"
# Every test child denies .env reads; service sockets may reach loopback only, ingestion has no socket use.
GUARD = '''import os, sys
def guard(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        name = os.path.basename(os.fsdecode(args[0]))
        if name == ".env" or name.startswith(".env."):
            raise RuntimeError("dotenv access denied")
    if event in ("socket.connect", "socket.bind"):
        address = args[1]
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1"):
            raise RuntimeError("external network denied")
    if event == "socket.getaddrinfo" and args[0] not in ("127.0.0.1", "::1", "localhost"):
        raise RuntimeError("external resolution denied")
sys.addaudithook(guard)
'''


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def snapshot(paths):
    found = {}
    for path in paths:
        for item in (sorted(path.rglob("*")) if path.is_dir() else [path]):
            info = item.stat()
            found[str(item)] = (info.st_mode, info.st_size, info.st_mtime_ns, hashlib.sha256(item.read_bytes()).hexdigest() if item.is_file() else None)
    return found


def fixture(root):
    # Runs only in the installed pipeline interpreter, never imported by service code.
    exec(GUARD)
    sys.path[:0] = [str(PIPELINE / "src"), str(PIPELINE)]
    from scripts.ingestion_smoke import OfflineFixture
    kit = OfflineFixture(root)
    declared = kit.item(publisher="Synthetic publisher")
    unspecified = kit.item(candidate="c2", supplier="supplier-2", url="https://example.invalid/unspecified")
    manifest = kit.manifest("observation", [[declared, unspecified]])
    return {"manifest": str(manifest), "request": kit.request(manifest)}


def smoke(root: Path) -> dict:
    sys.path.insert(0, str(SERVICE / "tests"))
    from support import ServiceProcess, Workspace
    import httpx
    import zoop_ai_service.main as entry
    assert Path(entry.__file__).resolve() == SERVICE / "src/zoop_ai_service/main.py"
    assert PYTHON.is_file(), "installed pipeline interpreter required; no dependency installation is performed"
    root.mkdir(parents=True, exist_ok=True)
    operator = root / "operator"
    prepared = subprocess.run([str(PYTHON), __file__, "--fixture", str(operator)], capture_output=True, text=True,
                              env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}, timeout=30)
    assert prepared.returncode == 0, prepared.stderr
    fixture_info = json.loads(prepared.stdout)
    sources = operator / "sources.json"
    ingestion = operator / "ingestion"
    pin = root / "pipeline-module.txt"
    command = root / "zoop-ai-ingest"
    command.write_text(f"#!{PYTHON}\n" + GUARD + f'''sys.path.insert(0, {str(PIPELINE / "src")!r})
from pathlib import Path
from zoop_ai_pipeline import ingestion_cli
assert Path(ingestion_cli.__file__).resolve() == Path({str(PIPELINE / "src/zoop_ai_pipeline/ingestion_cli.py")!r})
Path({str(pin)!r}).write_text(ingestion_cli.__file__)
raise SystemExit(ingestion_cli.main())
''')
    command.chmod(0o700)
    child_env = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "ZOOP_STATE_DIR": str(root / "app"),
                 "ZOOP_AI_WORKER_STATE_DIR": str(root / "worker")}

    def cli(operation, payload, *extra):
        return subprocess.run([str(command), operation, "--state-dir", str(ingestion), "--sources", str(sources), *extra],
                              input=canonical(payload).encode(), capture_output=True, env=child_env, timeout=60)

    ingested = cli("run", fixture_info["request"], "--fixture-manifest", fixture_info["manifest"])
    assert ingested.returncode == 0, ingested.stdout
    native = json.loads(ingested.stdout)
    assert native["state"] == "complete" and native["counts"]["textReady"] == 2
    ref = native["documentRefs"][0]
    selector = {"schemaVersion": SCHEMA, "roundId": "round-1", "sourceId": "synthetic-source",
                **{key: ref[key] for key in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")}}
    direct = cli("export", selector, "--require-store")
    assert direct.returncode == 0, direct.stdout
    exported = json.loads(direct.stdout)
    unspecified_ref = native["documentRefs"][1]
    unspecified_selector = {**selector, **{key: unspecified_ref[key] for key in (
        "page", "ordinal", "documentId", "rawVersion", "documentVersion")}}
    unspecified_export = cli("export", unspecified_selector, "--require-store")
    assert unspecified_export.returncode == 0, unspecified_export.stdout
    guard_dir = root / "guard"
    guard_dir.mkdir()
    (guard_dir / "sitecustomize.py").write_text(GUARD)
    workspace = Workspace(root / "service-profile")
    workspace.credentials.scopes["alpha"].append("observation.read")
    workspace.credentials.scopes["handoffer"].append("observation.read")
    env = workspace.env(ZOOP_AI_SERVICE_INGESTION_COMMAND=str(command), ZOOP_AI_INGESTION_STATE_DIR=str(ingestion),
                        ZOOP_AI_SERVICE_SOURCES=str(sources), ZOOP_STATE_DIR=str(root / "app"),
                        PYTHONPATH=os.pathsep.join([str(guard_dir), str(SERVICE / "src")]), PYTHONDONTWRITEBYTECODE="1")
    service = ServiceProcess(workspace, env=env)
    service.client.close()
    service.client = httpx.Client(base_url=f"http://127.0.0.1:{workspace.port}", timeout=60, trust_env=False)
    checks = []
    responses = []

    def request(label, status, code=None, *, body=None, **kwargs):
        before = snapshot([ingestion, operator / "inputs", sources])
        response = service.request("POST", PATH, body=selector if body is None else body, **kwargs)
        assert snapshot([ingestion, operator / "inputs", sources]) == before, label + ": source writes"
        assert response.status_code == status, (label, response.status_code, response.text[:200])
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        if code:
            assert response.json()["error"]["code"] == code, label
            assert exported["document"]["text"] not in response.text
        responses.append(response)
        checks.append(label)
        return response

    try:
        service.start()
        assert request("native-byte-equality", 200).content == direct.stdout
        assert request("second-observation-bytes-equal", 200, body=unspecified_selector).content == unspecified_export.stdout
        assert request("second-explicit-scope-principal", 200, as_="handoffer").content == direct.stdout
        request("different-principal-without-scope", 403, "scope_denied", as_="beta")
        request("wrong-scope", 403, "scope_denied", as_="reader")
        request("unknown-credential", 401, "authentication_required", token="synthetic-unknown-credential")
        request("missing-schema-version", 422, "invalid_request", body={k: v for k, v in selector.items() if k != "schemaVersion"})
        request("invented-observation-id", 422, "invalid_request", body={**selector, "observationId": "not-a-native-field"})
        request("store-cannot-be-disabled", 422, "invalid_request", body={**selector, "requireStore": False})
        request("client-path-refused", 422, "invalid_request", body={**selector, "stateDir": str(root)})
        request("wrong-document-version", 404, "observation_not_found", body={**selector, "documentVersion": "0" * 64})
        request("wrong-raw-version", 404, "observation_not_found", body={**selector, "rawVersion": "0" * 64})
        registry = json.loads(sources.read_text())
        for label, change in (("grant-revoked", lambda g: g.update(enabled=False)),
                              ("store-right-required", lambda g: g.update(allowedOperations=["read", "quote-display"]))):
            modified = copy.deepcopy(registry)
            change(modified["sources"][0]["grant"])
            sources.write_text(canonical(modified))
            refused = cli("export", selector, "--require-store")
            assert refused.returncode == 2 and json.loads(refused.stdout)["error"]["code"] == "source_unauthorized"
            request(label, 403, "source_unauthorized")
        sources.write_text(canonical(registry))
        drift = copy.deepcopy(registry)
        drift["sources"][0]["allowedHosts"].append("other.invalid")
        sources.write_text(canonical(drift))
        request("frozen-source-config-mismatch", 409, "scope_configuration_conflict")
        sources.write_text(canonical(registry))
        with (ingestion / "ingestion.lock").open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            busy = request("ingestion-writer-busy", 503, "runtime_busy")
            assert busy.json()["error"]["runtimeCode"] == "ingestion_busy"
            assert busy.json()["error"]["retryable"] is True and busy.headers["retry-after"] == "2"
        wal = ingestion / "ingestion.sqlite3-wal"
        assert not wal.exists()
        wal.write_bytes(b"synthetic-unsettled-wal")
        recovery = request("hot-wal-not-recovered", 503, "service_configuration_invalid")
        assert recovery.json()["error"]["runtimeCode"] == "ingestion_recovery_required"
        wal.unlink()
        database = ingestion / "ingestion.sqlite3"
        original = database.read_bytes()
        info = database.stat()
        db = sqlite3.connect(database)
        try:
            content = json.loads(db.execute("SELECT content FROM versions WHERE id=?", (selector["documentVersion"],)).fetchone()[0])
            content["textHash"] = "0" * 64
            # Only this fresh synthetic fixture is corrupted. Restore its immutability trigger before the HTTP read.
            db.execute("DROP TRIGGER immutable_versions_update")
            db.execute("UPDATE versions SET content=? WHERE id=?", (canonical(content), selector["documentVersion"]))
            db.execute("CREATE TRIGGER immutable_versions_update BEFORE UPDATE ON versions BEGIN SELECT RAISE(ABORT,'immutable'); END")
            db.commit()
        finally:
            db.close()
        request("native-source-hash-corruption", 500, "runtime_contract_mismatch")
        database.write_bytes(original)
        os.utime(database, ns=(info.st_atime_ns, info.st_mtime_ns))
        assert request("fresh-read-after-restoration", 200).content == direct.stdout
        oversized = service.request("POST", PATH, raw=b" " * 2_000_001, headers={"Content-Type": "application/json"})
        assert oversized.status_code == 413 and oversized.headers["cache-control"] == "no-store"
        checks.append("request-size-bound")
        service.stop()
        private = [str(root), *workspace.private_strings(), exported["document"]["text"]]
        assert all(value not in service.logs() for value in private)
        assert all(str(root) not in response.text for response in responses)
        checks.append("body-path-key-log-redaction")
    finally:
        service.close()
    disabled_env = {key: value for key, value in env.items() if key not in {
        "ZOOP_AI_SERVICE_INGESTION_COMMAND", "ZOOP_AI_INGESTION_STATE_DIR", "ZOOP_AI_SERVICE_SOURCES"}}
    disabled = ServiceProcess(workspace, env=disabled_env)
    disabled.client.close()
    disabled.client = httpx.Client(base_url=f"http://127.0.0.1:{workspace.port}", timeout=60, trust_env=False)
    try:
        disabled.start()
        response = disabled.request("POST", PATH, body=selector)
        assert response.status_code == 503 and response.json()["error"]["code"] == "execution_unavailable"
        assert response.headers["cache-control"] == "no-store"
        checks.append("disabled-group")
    finally:
        disabled.close()
    return {"status": "passed", "checks": checks, "sourceWrites": 0, "providerCalls": 0,
            "network": "loopback only; child audit denies external sockets/resolution and .env opens",
            "serviceModule": entry.__file__, "pipelineModule": pin.read_text(),
            "exportSha256": hashlib.sha256(direct.stdout).hexdigest(), "exportBytes": len(direct.stdout)}


if __name__ == "__main__":
    assert sys.argv[1] == "--fixture"
    print(json.dumps(fixture(Path(sys.argv[2]))))
