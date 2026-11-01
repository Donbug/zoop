"""Credential-free real HTTP/native round scenario shared by pytest and the smoke driver."""
from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from extraction_support import ExtractionWorkspace, make_service, terminate_extraction
from online_admission_support import GUARD, WRAPPER, check
from relation_support import PIPELINE, PIPELINE_PYTHON, canonical, terminate_relation

BUILDER = Path(__file__).with_name("build_round_service_world.py")
RUN = "round-20261017T0905"
CARRY = "round-20261017T0935"
POLICY = "/internal/v1/plan-admission-policy"


def run_scenario(root: Path, *, lost_first_tick=False):
    root = root.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    guard = root / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(GUARD.replace("__ROOT__", repr(str(root))).replace("__GUARD_DIR__", repr(str(guard))))
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(guard), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
           "ZOOP_STATE_DIR": str(root / "builder-app"), "ZOOP_AI_WORKER_STATE_DIR": str(root / "builder-worker")}

    def build(*args):
        done = subprocess.run([str(PIPELINE_PYTHON), str(BUILDER), str(PIPELINE), str(root / "world"), *map(str, args)],
                              env=env, capture_output=True, timeout=600)
        (root / ("author.stderr" if args else "build.stderr")).write_bytes(done.stderr)
        check(done.returncode == 0 and not done.stderr, "round fixture subprocess failed; inspect retained stderr")
        return json.loads(done.stdout)

    info = build()
    world = SimpleNamespace(root=Path(info["root"]), ingestion=Path(info["ingestion"]), extraction=Path(info["extraction"]),
        registry=Path(info["registry"]), producer=Path(info["producer"]), verifier=Path(info["verifier"]),
        s2_replay=Path(info["s2Replay"]), s2_topic=Path(info["s2Topic"]), s2_request=info["s2Request"],
        s2_plain_request=info["s2Request"], upstream={"jobId": "unused", "inputDigest": "0" * 64}, source_texts=[])
    if lost_first_tick:
        world.ingestion = root / "fresh-runtime-ingestion"
        world.ingestion.mkdir(mode=0o700)
    workspace = ExtractionWorkspace(root / "workspace", world, chain=True, topic=False, requests=())
    services = []
    try:
        workspace.relation_state.mkdir()
        plans, handoffs = root / "plans", root / "handoffs"
        plans.mkdir(mode=0o700)
        handoffs.mkdir(mode=0o700)
        credentials = workspace.credentials
        credentials.scopes["alpha"] += ["plan.admit", "plan.read", "round.run", "round.read", "observation.read"]
        credentials.tokens["operator"] = "t" + secrets.token_urlsafe(36)
        credentials.scopes["operator"] = ["plan.policy"]
        commands = {}
        for module, log in (("extraction_cli", "s2"), ("relation_cli", "s3"), ("ingestion_cli", "ingestion"), ("handoff_cli", "handoff")):
            path = root / (module + ".py")
            script = WRAPPER.replace("__PYTHON__", str(PIPELINE_PYTHON)).replace("__GUARD_DIR__", repr(str(guard)))
            script = script.replace("__ROOT__", repr(str(root))).replace("__COMMAND_LOG__", repr(log + "-commands"))
            script = script.replace("__MODULE__", repr("zoop_ai_pipeline." + module))
            if module == "ingestion_cli":
                script = script.replace("runpy.run_module", (
                    "if command == 'tick' and os.path.exists(os.path.join(ROOT, 'crash-round-tick')):\n"
                    "    os.unlink(os.path.join(ROOT, 'crash-round-tick'))\n"
                    "    os._exit(75)\n"
                    "runpy.run_module"))
                script = script.replace("runpy.run_module", (
                    "if command == 'tick' and os.path.exists(os.path.join(ROOT, 'lose-committed-tick')):\n"
                    "    import contextlib, io, json\n"
                    "    from zoop_ai_pipeline.ingestion_cli import main\n"
                    "    with contextlib.redirect_stdout(io.StringIO()) as captured:\n"
                    "        code = main()\n"
                    "    result = json.loads(captured.getvalue())\n"
                    "    assert code == 0 and result['round']['state'] == 'complete' and result['tick']['action'] == 'started'\n"
                    "    with open(os.path.join(ROOT, 'committed-lost-tick.json'), 'w') as proof:\n"
                    "        proof.write(captured.getvalue())\n"
                    "    os.unlink(os.path.join(ROOT, 'lose-committed-tick'))\n"
                    "    os._exit(75)\n"
                    "runpy.run_module"))
            path.write_text(script)
            path.chmod(0o755)
            commands[module] = path
        workspace.s2_command, workspace.command = commands["extraction_cli"], commands["relation_cli"]
        canonical_path, decisions_path, bindings_path, exports_path = (root / name for name in ("canonical.json", "decisions.json", "bindings.json", "exports.json"))
        canonical_path.write_text(canonical({"schemaVersion": "zoop-graph-canonical-1", "entries": []}))
        decisions_path.write_text(canonical({"schemaVersion": "zoop-public-decisions-4", "policyVersion": "zoop-public-projection-policy-2",
                                            "companies": [], "issues": [], "structural": [], "follows": [], "origins": []}))
        bindings_path.write_text(canonical(info["bindings"]))
        exports_path.write_text(canonical({"schemaVersion": "zoop-ai-handoff-exports-1", "handoffs": []}))
        profile = root / "profile.json"
        profile.write_text(canonical({"schemaVersion": "zoop-ai-round-profile-1", "sourceId": "synthetic-source", "scopeId": "body",
            "initialFrom": "2026-10-17T00:00:00+09:00", "fixtureManifest": info["fixtureManifest"], "descriptor": info["descriptor"],
            "selection": {"maxAgeSeconds": 315360000, "limit": 8, "cadenceMinutes": 30}}))
        service_env = workspace.env(ZOOP_AI_SERVICE_PLAN_ADMISSION="1", ZOOP_AI_SERVICE_PLAN_ROOT=str(plans),
            ZOOP_AI_SERVICE_EXTRACTION_APPROVALS=None, ZOOP_AI_SERVICE_RELATION_UPSTREAMS=None,
            ZOOP_AI_SERVICE_INGESTION_COMMAND=str(commands["ingestion_cli"]), ZOOP_AI_SERVICE_ROUND_PROFILE=str(profile),
            ZOOP_AI_SERVICE_HANDOFF_COMMAND=str(commands["handoff_cli"]), ZOOP_AI_HANDOFF_STATE_DIR=str(handoffs),
            ZOOP_AI_HANDOFF_RELATION_STATE_DIR=str(workspace.relation_state), ZOOP_AI_HANDOFF_EXTRACTION_STATE_DIR=str(workspace.extraction_state),
            ZOOP_AI_HANDOFF_INGESTION_STATE_DIR=str(world.ingestion), ZOOP_AI_SERVICE_HANDOFF_SOURCES=str(workspace.sources),
            ZOOP_AI_SERVICE_HANDOFF_CANONICAL=str(canonical_path), ZOOP_AI_SERVICE_HANDOFF_DECISIONS=str(decisions_path),
            ZOOP_AI_SERVICE_HANDOFF_BINDINGS=str(bindings_path), ZOOP_AI_SERVICE_HANDOFF_EXPORTS=str(exports_path))

        def start():
            service = make_service(workspace, env=service_env)
            service._runs = len(services)
            services.append(service)
            return service.start()

        service = start()

        def wait_status(family, round_id, states, timeout=60):
            deadline = time.monotonic() + timeout
            path = f"/internal/v1/round-{family}/{round_id}"
            while time.monotonic() < deadline:
                current = service.request("GET", path)
                check(current.status_code == 200, "round status unavailable: " + current.text)
                if current.json()["state"] in states:
                    return current
                time.sleep(0.05)
            raise AssertionError("round operation did not settle: " + path)

        if lost_first_tick:
            import sqlite3

            def original_row():
                with sqlite3.connect((workspace.state / "rounds" / "rounds.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
                    return db.execute("SELECT body,context,result,version FROM requests WHERE owner='alpha' AND family='run' AND round_id=?",
                                      (RUN,)).fetchone()

            first_body = {"schemaVersion": "zoop-ai-round-run-1", "roundId": RUN}
            (root / "lose-committed-tick").touch()
            first = service.request("POST", "/internal/v1/round-runs", body=first_body, key=RUN)
            check(first.status_code == 202, "first tick was not accepted")
            unknown = wait_status("runs", RUN, {"failed"}).json()
            check(unknown["code"] == "round_outcome_unknown", "lost committed output was not retained as unknown")
            committed = json.loads((root / "committed-lost-tick.json").read_bytes())
            check(committed["round"]["checkpoint"]["through"] == "2026-10-17T09:05:00+09:00", "first checkpoint did not commit")
            original = original_row()
            check("tickComplete" not in json.loads(original[1]), "HTTP observed the intentionally lost output")
            service.close()
            service = start()
            replayed = service.request("POST", "/internal/v1/round-runs", body=first_body, key=RUN)
            check(replayed.status_code == 200 and replayed.json()["code"] == "round_outcome_unknown", "unknown first request reopened")
            shutil.copyfile(info["emptyManifest"], info["fixtureManifest"])
            next_id = "round-20261017T1005"
            next_body = {"schemaVersion": "zoop-ai-round-run-1", "roundId": next_id}
            accepted = service.request("POST", "/internal/v1/round-runs", body=next_body, key=next_id)
            check(accepted.status_code == 202, "future distinct slot was not accepted")
            ready = wait_status("runs", next_id, {"ready", "failed", "no_new_material"}).json()
            check(ready["state"] == "ready", "future slot was poisoned by unknown bootstrap: " + canonical(ready))
            approvals = json.loads((plans / ready["planId"] / "approvals.json").read_bytes())["approvals"]
            check([entry["request"]["incoming"] for entry in approvals] == [info["s2Request"]["incoming"]],
                  "unclaimed observation from committed unknown tick was lost")
            check(ready["ingestionRoundId"] != committed["tick"]["roundId"], "future slot replayed the unknown native tick")
            check(original_row() == original, "future progress rewrote the original unknown request")
            check((root / "ingestion-commands").read_text().splitlines().count("tick") == 2, "unknown first tick was resent")
            check(not (root / "network-attempt").exists(), "native subprocess attempted network")
            report = {"state": "passed", "committedUnknownRecoveredByFutureSlot": True,
                      "originalUnknownPreserved": True, "unclaimedObservationCarried": True,
                      "planId": ready["planId"], "providerCalls": 0, "networkAttempts": 0}
            (root / "report.json").write_text(canonical(report) + "\n")
            return report

        requested = {"schemaVersion": "zoop-ai-round-run-1", "roundId": RUN}
        response = service.request("POST", "/internal/v1/round-runs", body=requested, key=RUN)
        check(response.status_code == 202, "native run was not durably accepted: " + response.text)
        run = wait_status("runs", RUN, {"ready"}).json()
        check(run["ingestionRoundId"].startswith("slot-") and run["ingestionRoundId"] != RUN, "application and ingestion IDs collapsed")
        before = (root / "ingestion-commands").read_text()
        checked = (root / "s2-commands").read_text()
        check(service.request("GET", "/internal/v1/round-runs/" + RUN).status_code == 200, "ready run status unavailable")
        check((root / "ingestion-commands").read_text() == before
              and (root / "s2-commands").read_text().count("plan-round\n") == checked.count("plan-round\n"), "round GET launched a native write")
        again = service.request("POST", "/internal/v1/round-runs", body=requested, key=RUN)
        check(again.status_code == 200 and again.json()["planId"] == run["planId"], "exact replay changed plan")
        check((root / "ingestion-commands").read_text() == before, "exact replay resubmitted tick")
        headers = {"Authorization": "Bearer " + credentials.tokens["alpha"], "Idempotency-Key": RUN, "Content-Type": "application/json"}
        conflict = service.client.post("/internal/v1/round-runs", content=json.dumps(requested, indent=2).encode(), headers=headers)
        check(conflict.status_code == 409 and conflict.json()["error"]["code"] == "request_conflict", "changed exact bytes did not conflict")
        check(service.request("GET", "/internal/v1/round-runs/round-20261017T1005").status_code == 404, "unknown status was not404")
        check((root / "ingestion-commands").read_text() == before, "unknown status submitted tick")
        authored = build(plans / run["planId"] / "approvals.json", workspace.s2_replay)
        workspace.use_fixtures(Path(authored["producer"]), Path(authored["verifier"]))
        descriptor = info["descriptor"]
        sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        digest = lambda value: hashlib.sha256(canonical(value).encode()).hexdigest()
        policy = {"schemaVersion": "zoop-ai-plan-policy-1", "enabled": True, "principal": "alpha", "sourceIds": ["synthetic-source"],
            "sourceKind": "synthetic", "promptVersion": descriptor["promptVersion"], "catalogueDigest": digest(descriptor["catalogue"]),
            "snapshotDigest": digest(descriptor["snapshot"]), "topic": None, "expiresAt": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "limits": {"maxPlans": 2, "maxUnits": 8}, "runtime": {"kind": "replay", "producerReplayDigest": sha(workspace.s2_replay),
            "topicReplayDigest": None, "relationReplayDigest": sha(workspace.producer), "relationVerifierReplayDigest": sha(workspace.verifier)}}
        etag = service.request("GET", POLICY, as_="operator").headers["etag"]
        check(service.request("PUT", POLICY, as_="operator", body=policy, key="synthetic-round-policy", headers={"If-Match": etag}).status_code == 200,
              "bounded replay policy failed")
        reference = {"schemaVersion": "zoop-ai-plan-admission-1", "planId": run["planId"], "planDigest": run["planDigest"]}
        admitted = service.request("POST", "/internal/v1/plan-admissions", body=reference, key=run["planId"])
        check(admitted.status_code == 201, "native plan admission failed: " + admitted.text)
        freeze_body = {"schemaVersion": "zoop-ai-round-handoff-1", "roundId": RUN, "ingestionRoundId": run["ingestionRoundId"],
                       "planId": run["planId"], "bindings": info["bindings"]}
        incomplete = service.request("POST", "/internal/v1/round-handoffs", body=freeze_body, key=RUN)
        check(incomplete.status_code == 409 and incomplete.json()["error"]["code"] == "analysis_incomplete"
              and incomplete.json()["error"]["retryable"], "unsettled plan was admitted: " + incomplete.text)
        check(service.request("GET", "/internal/v1/round-handoffs/" + RUN).status_code == 404, "refused freeze left admission")
        check(not list((workspace.state / "rounds").glob("*/bindings.json")), "refused freeze wrote private bindings")
        check(not (root / "handoff-commands").exists(), "unregistered analysis started native freeze")
        unit = admitted.json()["manifest"]["units"][0]
        extraction = unit["extractionSubmit"]
        check(service.esubmit(extraction["jobId"], digest_=extraction["approvedRequestDigest"]).status_code == 202, "S2 admission submit failed")
        extracted = service.ewait(extraction["jobId"], states={"ready"}, dispatch={"idle"})
        check(extracted["usage"]["providerCalls"] == 0, "S2 used provider")
        relation = unit["relationSubmit"]
        check(service.request("POST", "/internal/v1/relation-jobs", body=relation, key=relation["jobId"]).status_code == 202, "S3 submit failed")
        related = service.rwait(relation["jobId"], states={"ready"}, dispatch={"idle"})
        check(related["usage"]["providerCalls"] == 0, "S3 used provider")
        accepted = service.request("POST", "/internal/v1/round-handoffs", body=freeze_body, key=RUN)
        check(accepted.status_code == 202, "complete native plan was not accepted: " + accepted.text)
        empty = wait_status("handoffs", RUN, {"no_public_material"})
        check(empty.json()["code"] == "window_empty" and empty.json()["selection"]["jobs"], "unmapped selection lost reasons")
        canonical_path.write_text(canonical(authored["canonical"]))
        decisions_path.write_text(canonical(authored["decisions"]))
        carry_body = {"schemaVersion": "zoop-ai-round-handoff-1", "roundId": CARRY, "bindings": info["bindings"]}
        ready = service.request("POST", "/internal/v1/round-handoffs", body=carry_body, key=CARRY)
        check(ready.status_code == 202, "mapped carry-only freeze not durably accepted: " + ready.text)
        handoff = wait_status("handoffs", CARRY, {"ready"}).json()
        check(handoff["handoffId"].startswith("hr-") and len(handoff["manifestDigest"]) == 64 and len(handoff["bundleDigest"]) == 64,
              "content-derived native pins missing")
        exported = service.request("GET", "/internal/v1/graph-handoffs/" + handoff["handoffId"] + "/bundle")
        check(exported.status_code == 200 and exported.json()["delivery"]["state"] == "current", "ready native read failed: " + exported.text)
        bundle = exported.json()["bundle"]
        check(bundle["schemaVersion"] == "zoop-graph-handoff-bundle-8" and len(bundle["issues"]) == 1, "wrong public bundle")
        check(any(edge["type"] == "INVOLVES" and edge["source"] == "issue:round-service" and edge["target"] == "KRX:005930"
                  for edge in bundle["relations"]), "authored participation did not produce public involvement")
        check(hashlib.sha256(canonical(bundle).encode()).hexdigest() == handoff["bundleDigest"], "bundle bytes differ from pin")
        service.close()
        service = start()
        restarted = service.request("GET", "/internal/v1/round-handoffs/" + CARRY)
        check(restarted.status_code == 200 and restarted.json()["handoffId"] == handoff["handoffId"], "restart lost content pins")
        handoff_before = (root / "handoff-commands").read_text().count("freeze-round\n")
        check(service.request("GET", "/internal/v1/round-handoffs/" + CARRY).status_code == 200, "ready status unavailable")
        check((root / "handoff-commands").read_text().count("freeze-round\n") == handoff_before, "GET launched native write")
        workspace.revoke_source(False)
        withheld = service.request("GET", "/internal/v1/round-handoffs/" + CARRY)
        check(withheld.status_code == 200 and withheld.json()["state"] == "failed" and "handoffId" not in withheld.json(), "ready status ignored revocation")
        withheld_bundle = service.request("GET", "/internal/v1/graph-handoffs/" + handoff["handoffId"] + "/bundle")
        check(withheld_bundle.status_code == 200 and withheld_bundle.json()["delivery"]["state"] == "withheld", "read ignored source revocation")
        withheld_id = "round-20261017T1805"
        withheld_new = service.request("POST", "/internal/v1/round-handoffs", key=withheld_id,
            body={"schemaVersion": "zoop-ai-round-handoff-1", "roundId": withheld_id, "bindings": info["bindings"]})
        check(withheld_new.status_code == 202, "all-withheld selection was not admitted")
        empty_withheld = wait_status("handoffs", withheld_id, {"no_public_material"}).json()
        check(empty_withheld["code"] == "window_empty" and any(item["status"] == "withheld" for item in empty_withheld["selection"]["jobs"]),
              "all-withheld selection lost its exclusion reasons")
        workspace.revoke_source(True)
        for invalid in ("round-20991231T1805", "round-20260230T1805"):
            refused = service.request("POST", "/internal/v1/round-handoffs", key=invalid,
                body={"schemaVersion": "zoop-ai-round-handoff-1", "roundId": invalid, "bindings": info["bindings"]})
            check(refused.status_code == 422, "invalid calendar handoff admitted")
        service.close()
        revoked = subprocess.run([sys.executable, "-m", "zoop_ai_service.round_revoke", "--state-dir", str(workspace.state), "--principal", "alpha",
            "--handoff-id", handoff["handoffId"], "--manifest-digest", handoff["manifestDigest"], "--bundle-digest", handoff["bundleDigest"]],
            env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, timeout=30)
        check(revoked.returncode == 0, "exact stopped-service grant revocation failed")
        service = start()
        denied = service.request("GET", "/internal/v1/graph-handoffs/" + handoff["handoffId"] + "/bundle")
        check(denied.status_code == 403 and denied.json()["error"]["code"] == "handoff_not_allowed", "revoked grant fell through to static authority")
        shutil.copyfile(info["emptyManifest"], info["fixtureManifest"])
        empty_id = "round-20261017T1005"
        no_new = service.request("POST", "/internal/v1/round-runs", body={"schemaVersion": "zoop-ai-round-run-1", "roundId": empty_id}, key=empty_id)
        check(no_new.status_code == 202 and wait_status("runs", empty_id, {"no_new_material"}).json()["state"] == "no_new_material", "empty ingestion not settled")
        for round_id, reason in (("round-20261017T1805", "outside_operating_window"), ("round-20261017T0906", "not_due")):
            before = (root / "ingestion-commands").read_text()
            response = service.request("POST", "/internal/v1/round-runs", key=round_id, body={"schemaVersion": "zoop-ai-round-run-1", "roundId": round_id})
            check(response.status_code == 202 and wait_status("runs", round_id, {"no_new_material"}).json()["code"] == reason, "calendar outcome mismatch")
            check((root / "ingestion-commands").read_text() == before, "no-work calendar mutated ingestion")
        unknown_id = "round-20261017T1035"
        unknown_body = {"schemaVersion": "zoop-ai-round-run-1", "roundId": unknown_id}
        (root / "crash-round-tick").touch()
        unknown = service.request("POST", "/internal/v1/round-runs", body=unknown_body, key=unknown_id)
        check(unknown.status_code == 202 and wait_status("runs", unknown_id, {"failed"}).json()["code"] == "round_outcome_unknown", "unknown child reopened")
        commands_after_unknown = (root / "ingestion-commands").read_text()
        service.close()
        service = start()
        reconciled = service.request("GET", "/internal/v1/round-runs/" + unknown_id)
        replay_unknown = service.request("POST", "/internal/v1/round-runs", body=unknown_body, key=unknown_id)
        check(reconciled.status_code == replay_unknown.status_code == 200 and reconciled.json()["code"] == replay_unknown.json()["code"] == "round_outcome_unknown",
              "restart lost unknown status")
        check((root / "ingestion-commands").read_text() == commands_after_unknown, "unknown outcome resubmitted")
        check(not (root / "network-attempt").exists(), "native subprocess attempted network")
        service.close()
        journal = workspace.state / "rounds" / "rounds.sqlite3"
        journal_before = sha(journal)
        disabled_env = {key: value for key, value in service_env.items() if key != "ZOOP_AI_SERVICE_ROUND_PROFILE"}
        disabled = subprocess.run([sys.executable, "-m", "zoop_ai_service.main"], env=disabled_env,
                                  capture_output=True, timeout=30)
        check(disabled.returncode == 78 and sha(journal) == journal_before, "disabled profile adopted an enabled round ledger")
        (root / "disabled-profile-refusal.json").write_bytes(disabled.stdout)
        result = {"state": "passed", "applicationRoundId": RUN, "ingestionRoundId": run["ingestionRoundId"], "planId": run["planId"],
                  "handoffId": handoff["handoffId"], "manifestDigest": handoff["manifestDigest"], "bundleDigest": handoff["bundleDigest"],
                  "providerCalls": 0, "networkAttempts": 0, "exactReplay": True, "exactConflict": True, "initialIncompleteRefusal": True,
                  "noPublicMaterial": True, "allWithheldSelection": True, "noNewMaterial": True, "unknownNoResubmit": True,
                  "restartRead": True, "sourceRevocation": True, "grantRevocation": True, "disabledProfileRefused": True}
        (root / "report.json").write_text(canonical(result) + "\n")
        return result
    finally:
        for service in services:
            service.close()
        terminate_extraction(workspace)
        terminate_relation(workspace)
