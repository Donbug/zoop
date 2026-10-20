#!/usr/bin/env python3
"""Real-process smoke for the read-only handoff routes: real uvicorn on 127.0.0.1, the real installed `zoop-ai-handoff`, an ACTUAL two-S3-job world.

It FAILS, never skips, without the pipeline install (and without `node` or `bun` for the cross-language digest). Required:
    make pipeline-install && make service-install                    (public dependencies only; no private credential)
Run: `make service-handoff-smoke` or `ai/service/.venv/bin/python ai/service/scripts/handoff_service_smoke.py`. No Neo4j, model, provider or network is involved
(the pipeline's own authoring runs under a socket audit hook; the handoff command never opens a socket) and no environment secret is read.

What it does. The operator side (ai/pipeline's interpreter) builds an OWNED synthetic world: actual ingestion, TWO S2 jobs and TWO S3 jobs, authored replay,
operator documents, and two frozen handoffs through the installed `zoop-ai-handoff freeze`. The operator lists them in a server-owned allowlist per principal with
BOTH SHA-256 pins; the service reads private copies of the source registry and the three operator files so the smoke can revoke and change them. Every HTTP answer
is compared with a direct `zoop-ai-handoff export` subprocess (the oracle) AND with the hand-authored expectation of the authored world (never derived from the tool
under test); the delivered bundle is accepted by the PRODUCER's own validator, and its SHA-256 over canonical bytes is recomputed by a second language (JavaScript)
after a plain JSON round trip. Then: principal isolation, pin mismatch, an absent handoff, source revocation and operator file changes (withheld, then current again),
an operator writer holding the ledger (503 busy), a real deadline (503), concurrency limits, an unknown nested field inside an otherwise self-consistent bundle (refused
even though every digest and the operator's pin were updated to match), and finally that no private string reached a response or a log and that the operator ledgers
are byte-identical. The throwaway world is removed at the end; this script never touches a real state directory.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE / "tests"))
sys.path.insert(0, str(SERVICE / "pipeline_tests"))

from handoff_support import bundle_url, status_url  # noqa: E402
from real_handoff_support import HANDOFF_CLI, HandoffWorld, RealWorkspace, build_handoff_world, digest_of, pin_entry, producer_accepts, require_handoff_pipeline  # noqa: E402
from relation_support import PIPELINE_PYTHON  # noqa: E402
from support import ServiceProcess, canonical, remove_tree  # noqa: E402

PRINCIPAL = "handoffer"
JS_DIGEST = r"""
const fs = require('fs'), crypto = require('crypto');
const canon = (v) => Array.isArray(v) ? '[' + v.map(canon).join(',') + ']'
  : (v !== null && typeof v === 'object') ? '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + canon(v[k])).join(',') + '}' : JSON.stringify(v);
const doc = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(crypto.createHash('sha256').update(canon(doc.bundle), 'utf8').digest('hex'));
"""
# Runs the REAL installed command, then adds one unknown nested key to the bundle and re-derives every digest, so the answer is internally consistent: only a closed
# model can refuse it. Written to the workspace and run by the pipeline's interpreter; the service sees only an installed-looking command.
TAMPER = '''#!__PYTHON__
import hashlib, json, subprocess, sys
raw = sys.stdin.buffer.read()
done = subprocess.run([__CLI__, *sys.argv[1:]], input=raw, capture_output=True)
out = json.loads(done.stdout)
canon = lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
bundle = out["bundle"]
bundle["policy"]["extraField"] = "nested-unknown"
bundle["digests"]["content"] = hashlib.sha256(canon({k: bundle[k] for k in ("companies", "issues", "relations", "evidence", "articles")}).encode()).hexdigest()
data = canon(bundle).encode()
out["receipt"].update(bundleDigest=hashlib.sha256(data).hexdigest(), bundleBytes=len(data), contentDigest=bundle["digests"]["content"])
sys.stdout.write(canon(out) + "\\n")
sys.exit(done.returncode)
'''
# The same wrapper over the real command with ONE manifest mutation and nothing else changed (digests, receipt and pins untouched).
MANIFEST_TAMPER = TAMPER.split("bundle = out")[0] + '''__MUTATION__
sys.stdout.write(canon(out) + "\\n")
sys.exit(done.returncode)
'''


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
        self.answers: list[str] = []
        self.root_secrets: list[str] = []

    def launch(self, ws: RealWorkspace, *, deadline: str | None = None) -> ServiceProcess:
        service = ServiceProcess(ws, env=ws.env(), launcher=deadline is not None, launcher_env={"ZOOP_TEST_HANDOFF_DEADLINE": deadline} if deadline else None)
        self.started.append(service)
        return service.start()

    def get(self, service: ServiceProcess, url: str, as_: str = PRINCIPAL):
        response = service.request("GET", url, as_=as_)
        self.answers.append(response.text + json.dumps(dict(response.headers)))
        return response

    def js_digest(self, body: bytes, key: str = "bundle") -> str:
        runner = shutil.which("node") or shutil.which("bun")
        check(runner is not None, "node or bun is required for the cross-language digest check")
        program = JS_DIGEST.replace("doc.bundle", f"doc.{key}")
        argv = [runner, "-e", program] if runner.endswith("node") else [runner, "--eval", program]
        done = subprocess.run(argv, input=body, capture_output=True, timeout=60)
        check(done.returncode == 0, "the cross-language digest program failed: " + done.stderr.decode()[-300:])
        return done.stdout.decode()


def listed(world: HandoffWorld, *ids: str, principal: str = PRINCIPAL) -> list[dict]:
    return [pin_entry(world, principal, handoff_id) for handoff_id in ids]


def run(smoke: Smoke, world: HandoffWorld) -> list[str]:
    lines: list[str] = []
    before = world.ledgers()
    pins1, pins2 = world.handoffs["handoff-1"], world.handoffs["handoff-2"]
    check(pins1["sourceJobs"] == ["rel-a", "rel-b"] and len(set(pins1["upstreamJobs"])) == 2, f"the authored world has two S3 source jobs over two S2 upstreams: {pins1}")
    ws = RealWorkspace(smoke.root / "svc", world, [*listed(world, "handoff-1"), *listed(world, "handoff-2", principal="beta"), pin_entry(world, PRINCIPAL, "handoff-1") | {"handoffId": "handoff-absent"}])
    service = smoke.launch(ws)
    smoke.root_secrets = [*ws.private_strings(), *world.private]

    # 1 authority and isolation
    url = bundle_url("handoff-1")
    check(error_of(service.request("GET", url, as_=None))["code"] == "authentication_required", "no token is 401")
    check(error_of(smoke.get(service, url, "reader"))["code"] == "scope_denied" and error_of(smoke.get(service, url, "grapher"))["code"] == "scope_denied", "other scopes are 403")
    refusals = [smoke.get(service, status_url("handoff-2")), smoke.get(service, url, "beta"), smoke.get(service, status_url("handoff-never"))]
    check(all(r.status_code == 403 for r in refusals) and len({json.dumps({k: v for k, v in error_of(r).items() if k != "requestId"}, sort_keys=True) for r in refusals}) == 1
          and error_of(refusals[0])["code"] == "handoff_not_allowed", "unlisted, other principal's and unknown handoffs answer identically")
    lines.append("isolation: status=passed, handoffs=2, principals=3, unlisted/other/unknown identical 403 before any child")

    # 2 the full bundle against the oracle, the hand-authored expectation, the producer's validator and a second language
    code, oracle, _ = ws.direct("handoff-1")
    check(code == 0 and oracle["delivery"]["status"] == "current" and oracle["usage"] == {"providerCalls": 0, "modelCalls": 0}, f"oracle export: {oracle.get('delivery')}")
    response = smoke.get(service, url)
    wire = response.json()
    check(response.status_code == 200 and wire["delivery"]["state"] == "current" and wire["publication"] == "not-published" and wire["appImport"] == "pending", response.text[:300])
    bundle = wire["bundle"]
    check(bundle == oracle["bundle"] and canonical(bundle) == canonical(oracle["bundle"]), "HTTP bundle equals the CLI export (content and canonical form)")
    check(digest_of(bundle) == pins1["bundleDigest"] == wire["verification"]["bundleDigest"] == oracle["receipt"]["bundleDigest"], "canonical digest equals the pin, the receipt and the response")
    check([s["relation"]["jobId"] for s in bundle["sources"]] == ["rel-a", "rel-b"] and wire["verification"]["sources"] == 2, "two source jobs")
    check(bundle["counts"] == world.counts and [e["id"] for e in bundle["evidence"]] == world.evidence_ids and sorted(i["id"] for i in bundle["issues"]) == world.issue_ids
          and sorted([r["type"], r["source"], r["target"], r["evidenceIds"]] for r in bundle["relations"]) == world.relation_edges
          and bundle["exclusions"]["counts"] == world.exclusions, "the bundle equals the hand-authored expectation of the world")
    check(producer_accepts(response.content), "the producer's own validator accepts the bundle the service delivered")
    check(smoke.js_digest(response.content) == pins1["bundleDigest"], "another language recomputes the pinned SHA-256 after a plain JSON round trip")
    manifest = wire["manifest"]
    check(manifest == oracle["manifest"] and canonical(manifest) == canonical(oracle["manifest"]), "HTTP manifest equals the CLI export manifest (the ledger's frozen request)")
    check(digest_of(manifest) == pins1["manifestDigest"] == bundle["manifestDigest"] == wire["verification"]["manifestDigest"] == oracle["receipt"]["manifestDigest"],
          "Python recomputes the manifest digest from the response alone and it equals the pin, the bundle's manifestDigest and the receipt")
    check(smoke.js_digest(response.content, "manifest") == pins1["manifestDigest"], "another language recomputes the manifest digest after a plain JSON round trip")
    check(manifest["handoffId"] == "handoff-1" and manifest["files"] == bundle["policy"]["files"] and manifest["policyVersion"] == bundle["policy"]["version"]
          and sorted(canonical(s) for s in manifest["sources"]) == sorted(canonical({"relation": s["relation"], "upstream": s["upstream"], "reviewDigest": s["reviewDigest"]}) for s in bundle["sources"]),
          "manifest source pins and operator-file hashes agree with the bundle")
    status = smoke.get(service, status_url("handoff-1")).json()
    check("bundle" not in status and "manifest" not in status and status["verification"]["bundleDigest"] == pins1["bundleDigest"] and status["verification"]["counts"] == world.counts,
          "status carries digests and counts only, no manifest")
    second = smoke.get(service, bundle_url("handoff-2"), "beta").json()
    check(second["bundle"]["handoffId"] == "handoff-2" and digest_of(second["bundle"]) == pins2["bundleDigest"] != pins1["bundleDigest"], "beta reads its own pinned handoff")
    lines.append(f"bundle: status=passed, sources=2, bytes={pins1['bundleBytes']}, equals CLI export + hand-authored expectation + producer validator + JS digest {pins1['bundleDigest'][:12]}")

    # 3 pins, absent handoff
    wrong = smoke.launch(RealWorkspace(smoke.root / "wrong", world, [pin_entry(world, PRINCIPAL, "handoff-1", bundleDigest=pins2["bundleDigest"])]))
    mismatch = smoke.get(wrong, bundle_url("handoff-1")).json()
    check(mismatch["delivery"] == {"state": "withheld", "reason": "handoff_pin_mismatch", "checkedAt": None} and mismatch["verification"] is None and mismatch["bundle"] is None, "pin mismatch is withheld")
    missing = smoke.get(service, bundle_url("handoff-absent"))
    check(missing.status_code == 404 and error_of(missing)["code"] == "handoff_not_found", "a listed absent handoff is 404")
    lines.append("pins: status=passed, wrong bundle pin withheld handoff_pin_mismatch with no content, listed absent handoff 404")

    # 4 source revocation and operator file changes, then restoration
    def withheld(expected: str | None) -> None:
        code, out, _ = ws.direct("handoff-1")
        check(code == 2 and out["delivery"]["status"] == "withheld" and "bundle" not in out, "oracle is withheld")
        for url_ in (status_url("handoff-1"), bundle_url("handoff-1")):
            answer = smoke.get(service, url_)
            body = answer.json()
            check(answer.status_code == 200 and body["delivery"]["state"] == "withheld" and body["delivery"]["reason"] == out["delivery"]["code"], f"withheld like the CLI: {answer.text[:300]}")
            check(body["verification"] is None and body.get("bundle") is None and body.get("manifest") is None
                  and not any(s in answer.text for s in (*world.private, "KRX:005930", "rel-a", *oracle["manifest"]["files"].values())), "withheld carries no content, no manifest, no pin")
        check(expected is None or out["delivery"]["code"] == expected, f"reason {out['delivery']['code']} != {expected}")

    registry = json.loads(ws.originals["sources"])
    registry["sources"][0]["grant"]["enabled"] = False
    ws.sources.write_text(canonical(registry), encoding="utf-8")
    try:
        withheld(None)
    finally:
        ws.restore("sources")
    check(smoke.get(service, url).json()["delivery"]["state"] == "current", "restored sources are current again")
    for name, reason in (("decisions", "decisions_changed"), ("canonical", "canonical_mapping_changed"), ("bindings", "bindings_changed")):
        getattr(ws, name).write_bytes(ws.originals[name] + b"\n")
        try:
            withheld(reason)
        finally:
            ws.restore(name)
        check(smoke.get(service, url).json()["delivery"]["state"] == "current", f"restored {name} is current again")
    lines.append("authority: status=passed, revoked grant and three operator-file changes withheld exactly as the CLI withholds them, current again after each exact restore")

    # 5 an operator writer holding the ledger
    descriptor = os.open(world.state / "handoff.lock", os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        busy = smoke.get(service, url)
        error = error_of(busy)
        check(busy.status_code == 503 and (error["code"], error["runtimeCode"], error["retryable"]) == ("runtime_busy", "handoff_busy", True) and busy.headers["retry-after"]
              and "bundle" not in busy.json(), f"a held ledger is a retryable 503, never an empty bundle: {busy.text[:300]}")
    finally:
        os.close(descriptor)
    check(smoke.get(service, url).status_code == 200, "released ledger serves again")
    lines.append("busy: status=passed, held handoff.lock is 503 runtime_busy (handoff_busy) with Retry-After, served again after release")

    # 6 concurrency over the real command: at most two children, the rest answer busy, none answers empty
    results: list[tuple[int, str | None]] = [(0, None)] * 6

    def read(index: int) -> None:
        answer = service.client.get(url, headers={"Authorization": f"Bearer {ws.credentials.tokens[PRINCIPAL]}"})
        results[index] = (answer.status_code, answer.json().get("error", {}).get("code"))

    threads = [threading.Thread(target=read, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(120)
    check(all(r in ((200, None), (503, "service_busy")) for r in results) and (200, None) in results, f"concurrent reads are served or busy, never empty: {results}")
    lines.append(f"concurrency: status=passed, 6 simultaneous reads -> {sum(r == (200, None) for r in results)} served, {sum(r[1] == 'service_busy' for r in results)} service_busy")

    # 7 a real deadline on a second service (the child cannot finish in 50 ms)
    quick = smoke.launch(RealWorkspace(smoke.root / "deadline", world, listed(world, "handoff-1")), deadline="0.05")
    timed_out = smoke.get(quick, url)
    check(timed_out.status_code == 503 and error_of(timed_out)["code"] == "runtime_unavailable" and error_of(timed_out)["retryable"], f"a missed deadline is a retryable 503: {timed_out.text[:300]}")
    lines.append("deadline: status=passed, real child stopped at the deadline, 503 runtime_unavailable")

    # 8 an unknown nested field in a self-consistent bundle (digests, receipt and the operator's pin all updated)
    tamper = smoke.root / "tamper.py"
    tamper.write_text(TAMPER.replace("__PYTHON__", str(PIPELINE_PYTHON)).replace("__CLI__", repr(str(HANDOFF_CLI))), encoding="utf-8")
    tamper.chmod(0o755)
    probe = RealWorkspace(smoke.root / "tamper-ws", world, [])
    code, tampered, _ = probe.direct("handoff-1", command=tamper)
    check(code == 0, "the tamper wrapper ran the real command")
    forged_bundle = tampered["bundle"]
    check(forged_bundle["policy"]["extraField"] == "nested-unknown" and forged_bundle != oracle["bundle"], "the forged bundle carries the unknown nested field")
    forged_pins = {"manifestDigest": forged_bundle["manifestDigest"], "bundleDigest": digest_of(forged_bundle)}
    check(forged_pins["bundleDigest"] != pins1["bundleDigest"], "the forged digest differs from the real one")
    tampered_ws = RealWorkspace(smoke.root / "tampered", world, [{"principal": PRINCIPAL, "handoffId": "handoff-1", **forged_pins}])
    tampered_ws.command = tamper
    forged_service = smoke.launch(tampered_ws)
    refused = smoke.get(forged_service, url)
    check(refused.status_code == 500 and error_of(refused)["code"] == "runtime_contract_mismatch" and not error_of(refused)["retryable"] and "bundle" not in refused.json()
          and "nested-unknown" not in refused.text, f"the closed model refuses an unknown nested field even with every digest and the pin updated: {refused.text[:300]}")
    check(smoke.get(forged_service, status_url("handoff-1")).status_code == 500, "the status refuses it too")
    lines.append("closed model: status=passed, unknown nested policy field with updated receipt/content/bundle digest and operator pin -> 500 runtime_contract_mismatch, no content")

    # 8b a manifest the ledger did not freeze (one pin changed, nothing else) and a missing manifest, both over the real command
    for name, mutation, wanted in (("file-pin", 'out["manifest"]["files"]["bindings"] = "f" * 64', "runtime_binding_mismatch"),
                                   ("source-pin", 'out["manifest"]["sources"][0]["reviewDigest"] = "f" * 64', "runtime_binding_mismatch"),
                                   ("missing", 'del out["manifest"]', "runtime_contract_mismatch")):
        wrapper = smoke.root / f"manifest-{name}.py"
        wrapper.write_text(MANIFEST_TAMPER.replace("__PYTHON__", str(PIPELINE_PYTHON)).replace("__CLI__", repr(str(HANDOFF_CLI))).replace("__MUTATION__", mutation), encoding="utf-8")
        wrapper.chmod(0o755)
        bad_ws = RealWorkspace(smoke.root / f"manifest-{name}-ws", world, listed(world, "handoff-1"))
        bad_ws.command = wrapper
        bad_service = smoke.launch(bad_ws)
        for route in (url, status_url("handoff-1")):
            refused_manifest = smoke.get(bad_service, route)
            check(refused_manifest.status_code == 500 and error_of(refused_manifest)["code"] == wanted and not error_of(refused_manifest)["retryable"]
                  and "bundle" not in refused_manifest.json() and "manifest" not in refused_manifest.json(), f"{name}: {refused_manifest.text[:300]}")
    lines.append("manifest binding: status=passed, a changed file pin or source pin -> 500 runtime_binding_mismatch, a missing manifest -> 500 runtime_contract_mismatch, no content")

    # 9 nothing private, nothing written, no model
    for service_process in smoke.started:
        service_process.stop()
    logs = "\n".join(service_process.logs() for service_process in smoke.started)
    forbidden = [*smoke.root_secrets, str(world.root), str(smoke.root)]
    leaked = [s for s in forbidden if s in logs or any(s in answer for answer in smoke.answers)]
    check(not leaked, f"{len(leaked)} private string(s) reached a response, header or log")
    check(world.ledgers() == before, "operator ledgers are byte-identical (relation, extraction, ingestion, handoff)")
    lines.append(f"privacy: status=passed, strings checked={len(forbidden)}, ledgers unchanged, providerCalls=0, modelCalls=0 (oracle usage and no model path)")
    return lines


def main() -> int:
    try:
        require_handoff_pipeline()
    except AssertionError as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    root = Path(tempfile.mkdtemp(prefix="zoop-ai-handoff-service-smoke-")).resolve()    # a symlinked parent (macOS /tmp -> /private/tmp) is refused by every pipeline ledger
    smoke = Smoke(root)
    failure: str | None = None
    lines: list[str] = []
    try:
        world = build_handoff_world(root / "world")
        lines = run(smoke, world)
    except SmokeFailure as error:
        failure = str(error)
    except AssertionError as error:
        failure = f"assertion: {str(error)[:600]}"
    except Exception as error:  # noqa: BLE001 - report the class only: a subprocess message must not carry a path or a secret
        failure = f"unexpected {type(error).__name__}"
    finally:
        for service in smoke.started:
            service.close()
        if failure is None:
            remove_tree(root)
    if failure is not None:
        print("FAILED: " + failure, file=sys.stderr)
        print(f"retained for inspection: {root}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    print("handoff service smoke: status=passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
