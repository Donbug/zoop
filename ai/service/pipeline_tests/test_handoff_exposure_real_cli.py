"""Installed CLI -> actual HTTP, with independently authored closure expectations and read-only snapshots."""
from real_exposure_support import build, exercise


def test_real_exposure_transport_and_post_revocation_identity_reads(tmp_path):
    world = build(tmp_path / "world")
    result = exercise(tmp_path / "service", world)
    assert result["status"] == "passed"


def test_routed_real_cli_http_bundle_and_exposure_keep_grants_independent(tmp_path):
    import json
    import os
    import subprocess
    from pathlib import Path

    from exposure_support import URL, exposure_env, query
    from handoff_support import HANDOFF_VARS, HandoffWorkspace, bundle_url
    from real_handoff_support import BUILD_HANDOFF_WORLD, HANDOFF_CLI
    from relation_support import PIPELINE, PIPELINE_BIN, PIPELINE_PYTHON, tree
    from support import ServiceProcess, canonical

    root = tmp_path.resolve() / "native"
    built = subprocess.run([str(PIPELINE_PYTHON), str(BUILD_HANDOFF_WORLD), str(PIPELINE), str(root), "--contexts"],
                           capture_output=True, text=True, timeout=900,
                           env={"PATH": os.defpath, "HOME": str(Path.home()), "PYTHONDONTWRITEBYTECODE": "1"})
    assert built.returncode == 0, built.stdout + built.stderr
    info = json.loads(built.stdout.strip().splitlines()[-1])
    entry = {key: info[key] for key in ("handoffId", "manifestDigest", "bundleDigest")}
    ws = HandoffWorkspace(tmp_path / "service", command=HANDOFF_CLI, exports=[{"principal": "alpha", **entry}])
    ws.handoff_state = Path(info["handoffState"])
    ws.canonical, ws.decisions, ws.bindings = (root / f"{name}.json" for name in ("canonical", "decisions", "bindings"))
    env = ws.env(**exposure_env(ws, PIPELINE_BIN / "zoop-ai-handoff-exposure"))
    for name in (*HANDOFF_VARS[2:6], "ZOOP_AI_HANDOFF_EXPOSURE_EXTRACTION_STATE_DIR", "ZOOP_AI_HANDOFF_EXPOSURE_INGESTION_STATE_DIR"):
        del env[name]
    for prefix in ("ZOOP_AI_SERVICE_HANDOFF", "ZOOP_AI_SERVICE_HANDOFF_EXPOSURE"):
        env[prefix + "_SOURCE_CONTEXTS"] = info["contexts"]
        env[prefix + "_SOURCE_CONTEXTS_SHA256"] = info["sha256"]
    before = {path: tree(Path(path)) for path in info["ledgerPaths"]}
    contexts = json.loads(Path(info["contexts"]).read_bytes())["contexts"]
    service = ServiceProcess(ws, env=env)
    try:
        service.start()
        response = service.request("GET", bundle_url(info["handoffId"]))
        assert response.status_code == 200, response.text
        assert {issue["id"] for issue in response.json()["bundle"]["issues"]} == {"issue:context-0", "issue:context-1"}
        source = query({"kind": "source", "sourceId": "synthetic-source"}, [info["handoffId"]])
        response = service.request("POST", URL, body=source)
        assert response.status_code == 200, response.text
        report = response.json()["report"]
        for index, context in enumerate(contexts):
            leaf = Path(context["sources"])
            original = leaf.read_bytes()
            revoked = json.loads(original)
            grant = revoked["sources"][0]["grant"]
            grant["enabled"] = False
            leaf.write_text(canonical(revoked))
            try:
                response = service.request("GET", bundle_url(info["handoffId"]))
                assert response.status_code == 200 and response.json()["delivery"]["state"] == "withheld"
                response = service.request("POST", URL, body=source)
                assert response.status_code == 200 and response.json()["report"] == report
                changed = {"kind": "grant", "grantId": grant["grantId"], "revision": grant["revision"]}
                response = service.request("POST", URL, body=query(changed, [info["handoffId"]]))
                assert response.status_code == 200, response.text
                assert {issue["id"] for issue in response.json()["report"]["handoffs"][0]["issues"]} == {f"issue:context-{index}"}
            finally:
                leaf.write_bytes(original)
        context_file = Path(info["contexts"])
        original = context_file.read_bytes()
        context_file.write_bytes(original + b" ")
        try:
            for method, url, body in (("GET", bundle_url(info["handoffId"]), None), ("POST", URL, source)):
                response = service.request(method, url, **({"body": body} if body is not None else {}))
                assert response.status_code == 503 and response.json()["error"]["code"] == "service_configuration_invalid"
        finally:
            context_file.write_bytes(original)
        assert {path: tree(Path(path)) for path in info["ledgerPaths"]} == before
    finally:
        service.close()
