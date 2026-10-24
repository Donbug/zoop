"""Shared actual installed-CLI/real HTTP scenario for pytest and the standalone smoke."""
import fcntl
import json
import os
import subprocess
from pathlib import Path

from exposure_support import SCHEMA, URL, exposure_env, query
from handoff_support import bundle_url, json_keys
from real_handoff_support import RealWorkspace, build_handoff_world, pin_entry
from relation_support import PIPELINE_BIN, tree
from support import ServiceProcess, canonical

CLI = PIPELINE_BIN / "zoop-ai-handoff-exposure"
BUILDER = Path(__file__).with_name("build_exposure_world.py")


def build(root):
    assert CLI.is_file() and os.access(CLI, os.X_OK), "install the pipeline before running exposure integration"
    return build_handoff_world(root, BUILDER)


def direct(ws, request):
    argv = [str(CLI), "--state-dir", str(ws.handoff_state)]
    if request["changed"]["kind"] != "s3-relation":
        argv += ["--ingestion-state-dir", str(ws.ingestion_state), "--extraction-state-dir", str(ws.extraction_state)]
    done = subprocess.run(argv, input=canonical(request).encode(), capture_output=True, timeout=60,
                          env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "ZOOP_STATE_DIR": str(ws.app_state), "ZOOP_AI_WORKER_STATE_DIR": str(ws.worker)})
    assert not done.stderr
    return done.returncode, json.loads(done.stdout), done.stdout


def exercise(root, world):
    ids = sorted(world.handoffs)
    entries = [pin_entry(world, "alpha", hid) for hid in ids]
    ws = RealWorkspace(root, world, entries)
    service = ServiceProcess(ws, env=ws.env(**exposure_env(ws, CLI)))
    before = world.ledgers()
    app_before = tree(ws.app_state)
    answers = {}
    try:
        service.start()
        for name, changed in world.expect["requests"].items():
            request = query(changed, list(reversed(ids)))
            code, oracle, raw = direct(ws, request)
            assert code == 0 and raw == (canonical(oracle) + "\n").encode()
            response = service.request("POST", URL, body=request)
            assert response.status_code == 200, response.text
            output = response.json()["report"]
            assert output == oracle and canonical(output) == canonical(oracle)
            assert output["scope"]["handoffIds"] == ids and output["usage"] == {"providerCalls": 0, "modelCalls": 0}
            for row in output["handoffs"]:
                expected = world.expect["handoffs"][name][row["handoffId"]]
                assert {k: row[k] for k in expected} == expected
                assert all(row[k] == world.handoffs[row["handoffId"]][k] for k in ("manifestDigest", "bundleDigest", "contentDigest"))
            assert not json_keys(output) & {"title", "label", "url", "body", "quote", "detail", "diagnostics"}
            answers[name] = output
        assert answers["empty"]["identity"] == {"boundInSelection": False, "recordedInIngestion": True}
        assert all(not h["exposed"] and not h["bound"] for h in answers["empty"]["handoffs"])
        for changed, code in [({"kind": "source", "sourceId": "unknown-source"}, "changed_identity_unknown"),
                              ({"kind": "s3-relation", "jobId": "unknown", "relationCandidateId": "rc-" + "0" * 64}, "changed_relation_unused")]:
            response = service.request("POST", URL, body=query(changed, ids))
            assert response.status_code == 422 and response.json()["error"]["code"] == code
            assert set(response.json()) == {"schemaVersion", "error"}
        # Genuine listed-but-absent producer selection: no partial result, even with a healthy selected artifact.
        ws.write_exports([*entries, {**entries[0], "handoffId": "missing-handoff"}])
        response = service.request("POST", URL, body=query(world.expect["requests"]["source"], [ids[0], "missing-handoff"]))
        assert response.status_code == 409 and response.json()["error"]["code"] == "handoff_selection_unmappable"
        ws.write_exports(entries)
        # Source ledger writer contention affects source queries but not relation retraction (no source-ledger arguments).
        with (world.ingestion / "ingestion.lock").open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                source = service.request("POST", URL, body=query(world.expect["requests"]["source"], ids))
                relation = service.request("POST", URL, body=query(world.expect["requests"]["relation"], ids))
                assert source.status_code == 503 and source.json()["error"]["code"] == "runtime_busy"
                assert relation.status_code == 200 and relation.json()["report"] == answers["relation"]
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
        # Source grant revoked in the service's private registry. Normal export withholds; exposure remains byte-identical.
        registry = json.loads(ws.sources.read_text())
        next(s for s in registry["sources"] if s["sourceId"] == world.expect["source"])["grant"]["enabled"] = False
        ws.sources.write_text(canonical(registry))
        normal = service.request("GET", bundle_url(world.expect["full"]))
        assert normal.status_code == 200 and normal.json()["delivery"]["state"] == "withheld" and normal.json()["bundle"] is None
        for name in ("source", "grant"):
            response = service.request("POST", URL, body=query(world.expect["requests"][name], ids))
            assert response.status_code == 200 and response.json()["report"] == answers[name]
        ws.write_exports([])
        denied = service.request("POST", URL, body=query(world.expect["requests"]["source"], ids))
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "handoff_not_allowed"
        assert world.ledgers() == before and tree(ws.app_state) == app_before
        return {"status": "passed", "successfulKinds": sorted(answers), "handoffs": len(ids), "providerCalls": 0, "modelCalls": 0,
                "sourceRevocation": "identity-report-only", "allowlistRevocation": "denied", "ledgerAndAppWrites": 0,
                "provenance": "synthetic authored replay; actual installed CLI and loopback HTTP"}
    finally:
        service.close()
