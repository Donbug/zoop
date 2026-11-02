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
are byte-identical. Further worlds: the reviewed field-verdict world and the ISSUE-SUMMARY worlds (an available authored-replay summary over two articles, a verifier-hold
job code; forged summaries refused although every digest and the pin match). The throwaway worlds are removed at the end; this script never touches a real state directory.
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

from handoff_support import SUMMARY_KEYS, basis_of, bundle_url, json_keys, status_url  # noqa: E402
from real_handoff_support import (BUILD_SUMMARY_HANDOFF_WORLD, BUILD_VERDICT_HANDOFF_WORLD, FORGERIES, HANDOFF_CLI, SUMMARY_HANDOFF, SUMMARY_WITHHELD_HANDOFF, VERDICT_HANDOFF,
                                  HandoffWorld, RealWorkspace, build_handoff_world, digest_of, forge_command, pin_entry, producer_accepts, require_handoff_pipeline,
                                  summary_problems, verdict_problems)
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
bundle["digests"]["content"] = hashlib.sha256(canon({k: bundle[k] for k in ("companies", "pathCompanies", "issues", "relations", "impacts", "evidence", "articles")}).encode()).hexdigest()
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
    fields = ("title", "action", "target", "eventTime", "period", "assertionStatus")
    identity = lambda item: {k: item[k] for k in ("documentId", "documentVersion", "mentionId")}  # noqa: E731
    def truthful(i: dict) -> bool:
        p, ids = i["fieldProvenance"], lambda m: canonical(identity(m))  # noqa: E731
        basis = [m for m in i["mentions"] if ids(m) == ids(i["representative"])] if i["representative"] is not None else list(i["mentions"])
        suppressed = [f for f in ("eventTime", "period") if any(v["field"] == f and v["decision"] != "ALLOW" and ids(v) in {ids(m) for m in basis} for v in i["fieldVerdicts"])]
        return (set(p) == {"selection", "verification", "withheld", "sameValueMentions"} and p["verification"] == "none" and p["withheld"] == suppressed
                and p["selection"] == ("operator-representative" if i["representative"] is not None else "unanimous")
                and all(v["verification"] == "operator-field-verdict" and set(v) >= {"evidenceIds", "reviewer", "decisionRef"} and "evidence" not in v and "note" not in v
                        for v in i["fieldVerdicts"])
                and all(p["sameValueMentions"][f] == [identity(m) for m in i["mentions"] if m[f] == basis[0][f]] != []
                        and i[f] == (None if f in suppressed else basis[0][f]) for f in fields))
    check(bundle["schemaVersion"] == "zoop-graph-handoff-bundle-8" and all(truthful(i) for i in bundle["issues"]),
          "every issue states its actual field selection and any operator field verdict: exact same-value lists, withheld recomputed, never an inferred verdict")
    check(bundle["policy"]["issueSummary"] == "zoop-issue-summary-policy-1" and [i["summary"] for i in bundle["issues"]]
          == [{"status": "unavailable", "code": "not-requested", "source": None}] * len(bundle["issues"]), "no decision pins a summary and no verdict holds a field: every issue is not-requested")
    main_ids = {c["id"] for c in bundle["companies"]}
    middles = {m for r in bundle["relations"] if (r["structuralPath"] or {}).get("status") == "complete" for m in r["structuralPath"]["companyIds"][1:-1]}
    check(all((r["structuralPath"] is None) == (r["type"] != "STRUCTURALLY_RELATED_TO") for r in bundle["relations"])
          and all("businessScope" in b and "productScope" in b for r in bundle["relations"] for b in r["basis"])
          and [c["id"] for c in bundle["pathCompanies"]] == sorted(middles - main_ids) and bundle["counts"]["pathCompanies"] == len(bundle["pathCompanies"])
          and not {c["id"] for c in bundle["pathCompanies"]} & ({i["id"] for i in bundle["issues"]} | main_ids),
          "structural paths are explicit, bases carry scopes, and the private path companies are exactly the unlisted mapped middles, disjoint from public nodes")
    involves = sorted((r["id"], ref["jobId"], ref["id"]) for r in bundle["relations"] if r["type"] == "INVOLVES" for ref in r["sourceRefs"] if ref["kind"] == "s3-relation")
    check(world.impacts and bundle["impacts"] == world.impacts and bundle["counts"]["impacts"] == len(bundle["impacts"])
          and [(i["edgeId"], i["sourceRelation"]["jobId"], i["sourceRelation"]["relationCandidateId"]) for i in bundle["impacts"]] == involves
          and bundle["policy"]["impacts"] == "s3-independent-verifier-quote-effect",
          "impact rows equal the pipeline world's hand-written expectation and cover exactly every INVOLVES source relation, one row each, sorted")
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
    check(not [s for s in ("effects", "proposal", "verifierRequestDigest", "targetVerdict", "impactCandidateId") if s in json.dumps(status)], "status carries no impact content")
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


def run_verdicts(smoke: Smoke, world: HandoffWorld) -> list[str]:
    """The reviewed (verdict) world: the installed CLI exports operator field verdicts, the HTTP service relays them byte for byte (not an empty default world), the suppressed
    headline values stay null while the original mentions keep theirs, and the verdicts follow the current rights and the pinned decisions file. Expectations are the
    pipeline smoke's own hand-written ones (`world.expect`), the child is the REAL command (no stand-in echo)."""
    before = world.ledgers()
    pins = world.handoffs[VERDICT_HANDOFF]
    ws = RealWorkspace(smoke.root / "verdict-svc", world, listed(world, VERDICT_HANDOFF))
    service = smoke.launch(ws)
    smoke.root_secrets = [*ws.private_strings(), *world.private]
    code, oracle, _ = ws.direct(VERDICT_HANDOFF)
    check(code == 0 and oracle["delivery"]["status"] == "current", f"verdict oracle export: {oracle.get('delivery')}")
    response = smoke.get(service, bundle_url(VERDICT_HANDOFF))
    wire = response.json()
    check(response.status_code == 200 and wire["delivery"]["state"] == "current", response.text[:300])
    bundle = wire["bundle"]
    check(bundle == oracle["bundle"] and canonical(bundle) == canonical(oracle["bundle"]) and digest_of(bundle) == pins["bundleDigest"] == wire["verification"]["bundleDigest"],
          "the verdict bundle equals the CLI export and hashes to the operator's pin")
    delivered = [v for issue in bundle["issues"] for v in issue["fieldVerdicts"]]
    check(len(delivered) == 5 and {v["decision"] for v in delivered} == {"ALLOW", "HOLD", "REJECT"}, f"non-empty verdicts of every decision were delivered: {len(delivered)}")
    problems = verdict_problems(bundle, world)
    check(not problems and producer_accepts(response.content), f"delivered verdicts, suppressed headlines, withheld lists and original mentions equal the hand-written expectation: {problems}")
    check(smoke.js_digest(response.content) == pins["bundleDigest"], "another language recomputes the pinned digest of the verdict bundle")
    status = smoke.get(service, status_url(VERDICT_HANDOFF))
    check(status.status_code == 200 and "fieldVerdicts" not in status.text and "operator-field-verdict" not in status.text, "the status carries no verdict")
    lines = [f"field verdicts: status=passed, delivered={len(delivered)} (ALLOW/HOLD/REJECT), withheld headline fields={sum(len(v) for v in world.expect['withheld'].values())} null with "
             "original mentions unchanged, equals the CLI export and the hand-written expectation, producer validator accepts"]
    refs = {v["decisionRef"] for entries in world.expect["verdicts"].values() for v in entries}
    leaking = ("operator-field-verdict", "fieldVerdicts", "contradicted", *refs)
    registry = json.loads(ws.originals["sources"])
    registry["sources"][0]["grant"]["enabled"] = False
    for name, change, reason in (("source", lambda: ws.sources.write_text(canonical(registry), encoding="utf-8"), None),
                                 ("decisions", lambda: ws.decisions.write_bytes(ws.originals["decisions"] + b"\n"), "decisions_changed")):
        change()
        try:
            code, oracle_w, _ = ws.direct(VERDICT_HANDOFF)
            check(code == 2 and oracle_w["delivery"]["status"] == "withheld" and (reason is None or oracle_w["delivery"]["code"] == reason), f"{name}: the CLI withholds")
            for route in (bundle_url(VERDICT_HANDOFF), status_url(VERDICT_HANDOFF)):
                answer = smoke.get(service, route)
                body = answer.json()
                check(answer.status_code == 200 and body["delivery"]["state"] == "withheld" and body["delivery"]["reason"] == oracle_w["delivery"]["code"]
                      and body.get("bundle") is None and body["verification"] is None and not [t for t in leaking if t in answer.text], f"{name}: withheld without any verdict content")
        finally:
            ws.restore("sources" if name == "source" else "decisions")
    restored = smoke.get(service, bundle_url(VERDICT_HANDOFF)).json()
    check(restored["delivery"]["state"] == "current" and canonical(restored["bundle"]) == canonical(bundle), "restoring the exact inputs delivers the same verdicts again")
    lines.append("field verdict rights: status=passed, a revoked source and a changed pinned decisions file withhold every verdict (no content), the exact restore returns the same bundle")
    for service_process in smoke.started:
        service_process.stop()
    logs = "\n".join(service_process.logs() for service_process in smoke.started)
    forbidden = [*smoke.root_secrets, str(world.root), str(smoke.root)]
    leaked = [s for s in forbidden if s in logs or any(s in answer for answer in smoke.answers)]
    check(not leaked and world.ledgers() == before, "no private string reached a response or log and the verdict world's ledgers are byte-identical")
    lines.append(f"verdict privacy: status=passed, strings checked={len(forbidden)}, ledgers unchanged")
    return lines


def run_summaries(smoke: Smoke, world: HandoffWorld, held_world: HandoffWorld) -> list[str]:
    """The ISSUE-SUMMARY worlds (bundle `-7`): the installed `zoop-ai-issue-summary` (authored replay, no model) summarised the supply issue over TWO articles (the second one in its
    own source, read but uncited), the operator's decisions pinned the immutable result, the installed `zoop-ai-handoff` froze and exported it, and the HTTP service relays it byte for byte. Expectations are the pipeline
    smoke's hand-written ones (`world.expect`), the child is the REAL command. Then: tampered content, a hidden (geography-only) evidence id, a wrong basis, a wrong provenance,
    a deterministic code without its condition and a dropped summary are each refused (500) although every digest, the receipt and the operator's pin were re-derived for the
    forged bytes; source revocation and a changed pinned decisions file withhold the whole handoff (no summary text) and the exact restore returns the same bytes; a job-coded
    (`verifier-hold`) summary is relayed with its source and none of the failed claims; no private string, claim text or summary-ledger path reached a log or a status; and no
    ledger, the summary ledger included, changed (the service never opens it and never runs a summary job)."""
    before, held_before = world.ledgers(), held_world.ledgers()
    expect, pins = world.expect, world.handoffs[SUMMARY_HANDOFF]
    ws = RealWorkspace(smoke.root / "summary-svc", world, listed(world, SUMMARY_HANDOFF))
    service = smoke.launch(ws)
    smoke.root_secrets = [*ws.private_strings(), *world.private, str(world.summaries), str(held_world.summaries)]
    claim_texts = [*expect["claimTexts"], expect["job"]]
    url = bundle_url(SUMMARY_HANDOFF)
    code, oracle, _ = ws.direct(SUMMARY_HANDOFF)
    check(code == 0 and oracle["delivery"]["status"] == "current" and oracle["usage"] == {"providerCalls": 0, "modelCalls": 0}, f"summary oracle export: {oracle.get('delivery')}")
    response = smoke.get(service, url)
    wire = response.json()
    check(response.status_code == 200 and wire["delivery"]["state"] == "current", response.text[:300])
    bundle = wire["bundle"]
    check(bundle == oracle["bundle"] and canonical(bundle) == canonical(oracle["bundle"]) and digest_of(bundle) == pins["bundleDigest"] == wire["verification"]["bundleDigest"],
          "the summary bundle equals the CLI export and hashes to the operator's pin")
    check(bundle["schemaVersion"] == "zoop-graph-handoff-bundle-8" and bundle["policy"]["issueSummary"] == "zoop-issue-summary-policy-1" and producer_accepts(response.content),
          "bundle 7 with the summary policy, accepted by the producer's own validator")
    problems = summary_problems(bundle, world)
    check(not problems, f"delivered summaries equal the hand-written expectation: {problems}")
    supply = next(i for i in bundle["issues"] if i["id"] == expect["supply"])
    factory = next(i for i in bundle["issues"] if i["id"] == expect["factory"])
    basis = basis_of(bundle, bundle["issues"].index(supply))
    summary = supply["summary"]
    check(len(basis["quotes"]) == 2 and len({q["articleId"] for q in basis["quotes"]}) == 2 and summary["source"]["basisDigest"] == digest_of(basis)
          and set(summary["evidenceIds"]) and set(summary["evidenceIds"]) < {q["evidenceId"] for q in basis["quotes"]},
          "the summary rests on two quotes of two articles and cites fewer than it read (every input quote, cited or not, is part of its basis)")
    check(factory["summary"] == {"status": "unavailable", "code": "temporal-review-pending", "source": None} and any(v["decision"] == "HOLD" for v in factory["fieldVerdicts"]),
          "an issue with a HOLD verdict states exactly temporal-review-pending")
    check(smoke.js_digest(response.content) == pins["bundleDigest"], "another language recomputes the pinned digest of the summary bundle")
    status = smoke.get(service, status_url(SUMMARY_HANDOFF))
    check(status.status_code == 200 and "bundle" not in status.json() and not json_keys(status.json()) & SUMMARY_KEYS and not [t for t in claim_texts if t in json.dumps(status.json(), ensure_ascii=False)],
          "the status carries no summary")
    lines = [f"issue summary: status=passed, supply=available (claims={len(summary['claims'])}, quotes={len(basis['quotes'])}, articles=2, authored-replay), factory=temporal-review-pending, "
             "equals the CLI export + hand-written expectation + producer validator + JS digest"]

    forged_lines = []
    for name, forgery in FORGERIES.items():
        wrapper = forge_command(smoke.root / f"forge-{name}.py", forgery)
        code, forged, _ = RealWorkspace(smoke.root / f"forge-{name}-probe", world, []).direct(SUMMARY_HANDOFF, command=wrapper)
        check(code == 0, f"{name}: the forge wrapper ran the real command")
        forged_bundle = forged["bundle"]
        check(digest_of(forged_bundle) != pins["bundleDigest"] and not producer_accepts(json.dumps({"bundle": forged_bundle}, ensure_ascii=False).encode("utf-8")),
              f"{name}: the forged bundle differs and the producer's own validator refuses it")
        forged_ws = RealWorkspace(smoke.root / f"forge-{name}-ws", world, [{"principal": PRINCIPAL, "handoffId": SUMMARY_HANDOFF, "manifestDigest": forged_bundle["manifestDigest"],
                                                                       "bundleDigest": digest_of(forged_bundle)}])
        forged_ws.command = wrapper
        forged_service = smoke.launch(forged_ws)
        for route in (url, status_url(SUMMARY_HANDOFF)):
            refused = smoke.get(forged_service, route)
            check(refused.status_code == 500 and error_of(refused)["code"] == "runtime_contract_mismatch" and not error_of(refused)["retryable"] and "bundle" not in refused.json()
                  and not [t for t in claim_texts if t in json.dumps(refused.json(), ensure_ascii=False)], f"{name}: {refused.text[:300]}")
        forged_lines.append(name)
    lines.append(f"forged summaries: status=passed, {len(forged_lines)} forgeries ({', '.join(forged_lines)}) over the real command with receipt, content digest and the operator's pin re-derived -> "
                 "500 runtime_contract_mismatch on both routes, no content")

    def withheld() -> str:
        code_, out, _ = ws.direct(SUMMARY_HANDOFF)
        check(code_ == 2 and out["delivery"]["status"] == "withheld" and "bundle" not in out, "summary oracle is withheld")
        for route in (status_url(SUMMARY_HANDOFF), url):
            answer = smoke.get(service, route)
            body = answer.json()
            check(answer.status_code == 200 and body["delivery"]["state"] == "withheld" and body["delivery"]["reason"] == out["delivery"]["code"] and body["verification"] is None
                  and body.get("bundle") is None and body.get("manifest") is None and not json_keys(body) & SUMMARY_KEYS
                  and not [t for t in claim_texts if t in json.dumps(body, ensure_ascii=False)], f"withheld without any summary content: {answer.text[:300]}")
        return out["delivery"]["code"]

    registry = json.loads(ws.originals["sources"])
    source_ids = [s["sourceId"] for s in registry["sources"]]
    check(len(source_ids) >= 2 and (expect["uncited"] is None or expect["uncited"]["source"] in source_ids), f"the summary world has a source of its own for the uncited article: {source_ids}")
    for revoked in source_ids:                      # ONE input source's right at a time: the cited article's and the UNCITED article's
        broken = json.loads(json.dumps(registry))
        next(s for s in broken["sources"] if s["sourceId"] == revoked)["grant"]["enabled"] = False
        ws.sources.write_text(canonical(broken), encoding="utf-8")
        try:
            withheld()
        finally:
            ws.restore("sources")
        restored_after_source = smoke.get(service, url).json()
        check(restored_after_source["delivery"]["state"] == "current" and canonical(restored_after_source["bundle"]) == canonical(bundle), f"restoring {revoked} returns the same bytes")
    ws.decisions.write_bytes(ws.originals["decisions"] + b"\n")
    try:
        check(withheld() == "decisions_changed", "a changed pinned decisions file (it holds the summary pin) is withheld decisions_changed")
    finally:
        ws.restore("decisions")
    restored = smoke.get(service, url).json()
    check(restored["delivery"]["state"] == "current" and canonical(restored["bundle"]) == canonical(bundle), "the exact restore returns the same summary bytes")
    lines.append(f"summary rights: status=passed, revoking EITHER input source's grant ({', '.join(source_ids)}; the second article is read but uncited) and changing the pinned decisions file "
                 "withhold the whole handoff (no summary text), each exact restore returns the same bundle")

    held_ws = RealWorkspace(smoke.root / "summary-held-svc", held_world, listed(held_world, SUMMARY_WITHHELD_HANDOFF))
    held_service = smoke.launch(held_ws)
    held_pins, held_expect = held_world.handoffs[SUMMARY_WITHHELD_HANDOFF], held_world.expect
    code, held_oracle, _ = held_ws.direct(SUMMARY_WITHHELD_HANDOFF)
    held_response = smoke.get(held_service, bundle_url(SUMMARY_WITHHELD_HANDOFF))
    held_wire = held_response.json()
    check(code == 0 and held_response.status_code == 200 and held_wire["delivery"]["state"] == "current", held_response.text[:300])
    held_bundle = held_wire["bundle"]
    held_summary = next(i for i in held_bundle["issues"] if i["id"] == held_expect["supply"])["summary"]
    check(held_bundle == held_oracle["bundle"] and digest_of(held_bundle) == held_pins["bundleDigest"] and producer_accepts(held_response.content)
          and not summary_problems(held_bundle, held_world), "the verifier-hold bundle equals the CLI export, hashes to the pin and equals the hand-written expectation")
    check(held_summary["code"] == "verifier-hold" and set(held_summary) == {"status", "code", "source"} and held_summary["source"] is not None
          and next(i for i in held_bundle["issues"] if i["id"] == held_expect["factory"])["summary"] == {"status": "unavailable", "code": "not-requested", "source": None}
          and not [t for t in held_expect["claimTexts"] if t in json.dumps(held_wire, ensure_ascii=False)], "a job-coded summary names its pinned source and carries none of the failed claims")
    lines.append("summary job code: status=passed, verifier-hold relayed with its pinned source, factory not-requested, no failed claim text in the handoff")

    for service_process in smoke.started:
        service_process.stop()
    logs = "\n".join(service_process.logs() for service_process in smoke.started)
    forbidden = [*smoke.root_secrets, str(world.root), str(held_world.root), str(smoke.root)]
    leaked = [s for s in forbidden if s in logs or any(s in answer for answer in smoke.answers)]
    check(not leaked and not [t for t in claim_texts if t in logs], f"{len(leaked)} private string(s) or claim text reached a response, header or log")
    check(world.ledgers() == before and held_world.ledgers() == held_before, "no ledger changed: relation, extraction, ingestion, handoff and the issue-summary ledger are byte-identical")
    lines.append(f"summary privacy: status=passed, strings checked={len(forbidden)}, ledgers (summary ledger included) unchanged, providerCalls=0, modelCalls=0")
    return lines


def main() -> int:
    try:
        require_handoff_pipeline()
    except AssertionError as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    root = Path(tempfile.mkdtemp(prefix="zoop-ai-handoff-service-smoke-")).resolve()    # a symlinked parent (macOS /tmp -> /private/tmp) is refused by every pipeline ledger
    smoke = Smoke(root)
    verdict_smoke = Smoke(root)
    summary_smoke = Smoke(root)
    failure: str | None = None
    lines: list[str] = []
    try:
        world = build_handoff_world(root / "world")
        lines = run(smoke, world)
        lines += run_verdicts(verdict_smoke, build_handoff_world(root / "verdict-world", BUILD_VERDICT_HANDOFF_WORLD))
        lines += run_summaries(summary_smoke, build_handoff_world(root / "summary-world", BUILD_SUMMARY_HANDOFF_WORLD, ("available",)),
                               build_handoff_world(root / "summary-held-world", BUILD_SUMMARY_HANDOFF_WORLD, ("verifier-hold",)))
    except SmokeFailure as error:
        failure = str(error)
    except AssertionError as error:
        failure = f"assertion: {str(error)[:600]}"
    except Exception as error:  # noqa: BLE001 - report the class only: a subprocess message must not carry a path or a secret
        failure = f"unexpected {type(error).__name__}"
    finally:
        for service in [*smoke.started, *verdict_smoke.started, *summary_smoke.started]:
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
