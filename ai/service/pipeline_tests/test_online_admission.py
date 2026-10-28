"""Actual HTTP + installed pipeline regressions for bounded online admission.

The fixtures author replay answers from real stored candidates, not from HTTP echoes.
They prove mechanics and zero provider calls, never model quality.
"""
from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from extraction_support import pipeline_env
from online_admission_support import DISABLED, POLICY_PATH, OnlineScenario, check
from relation_support import canonical, tree


def error(response, status, code=None):
    check(response.status_code == status, f"expected HTTP {status}, got {response.status_code}")
    if code is not None:
        check(response.json()["error"]["code"] == code, f"expected stable refusal {code}")


def controls(scenario):
    service = scenario.start()
    reference = scenario.references[0]
    current = scenario.policy_status()
    check(current.status_code == 200 and current.json()["revision"] == 0 and current.json()["policy"] is None
          and current.json()["usage"] == {"plans": 0, "units": 0}, "online store did not start without policy")
    initial_etag = current.headers["etag"]
    check(initial_etag == '"plan-policy-0-none"', "wrong initial CAS token")
    error(scenario.admit(reference), 409, "admission_disabled")
    error(service.request("PUT", POLICY_PATH, body=DISABLED, key="app-policy", headers={"If-Match": initial_etag}), 403, "scope_denied")
    error(service.request("GET", POLICY_PATH), 403, "scope_denied")
    error(scenario.admit(reference, as_="operator"), 403, "scope_denied")
    disabled = scenario.put_policy(DISABLED, "disable-first", initial_etag)
    check(disabled.status_code == 200, "operator could not install disabled policy")
    error(scenario.admit(reference), 409, "admission_disabled")
    disabled_etag = scenario.policy_status().headers["etag"]
    policy = scenario.policy()
    enabled = scenario.install_policy(policy, "enable-first")
    enabled_state = scenario.policy_status()
    enabled_etag = enabled_state.headers["etag"]
    error(scenario.put_policy(policy, "stale-cas", initial_etag), 412, "policy_conflict")
    admitted = scenario.admit(reference)
    check(admitted.status_code == 201, "fresh admission was not committed")
    record = admitted.json()
    check(record["authority"] == {"state": "active", "reason": None}, "fresh admission inactive")
    check(scenario.dispatch_counts() == {"extraction": [], "relation": []}, "admission dispatched work")
    replay = scenario.admit(reference)
    check(replay.status_code == 200 and replay.json() == record and scenario.status(reference).json() == record, "exact admission replay changed record")
    check(scenario.usage() == {"plans": 1, "units": 1}, "exact admission replay consumed quota")
    error(scenario.status(reference, as_="beta"), 404, "admission_not_found")
    changed_digest = {**reference, "planDigest": "0" * 64}
    error(scenario.admit(changed_digest), 409, "idempotency_conflict")
    unchanged = scenario.put_policy(policy, "same-policy", enabled_etag)
    check(unchanged.status_code == 200 and unchanged.json()["changed"] is False
          and unchanged.json()["revision"] == enabled.json()["revision"], "identical policy renewed revision")
    replacement = scenario.install_policy(DISABLED, "disable-later")
    current_before_retry = scenario.policy_status()
    historical = scenario.put_policy(policy, "enable-first", disabled_etag)
    # The exact original expected token is the disabled revision's ETag, not a later
    # current-state ETag. Historical retry must never select its old policy again.
    check(historical.status_code == 200 and historical.json() == enabled.json(), "historical policy retry did not return original receipt")
    check(scenario.policy_status().json() == current_before_retry.json(), "historical policy retry mutated current state")
    error(scenario.put_policy(policy, "enable-first", enabled_etag), 409, "idempotency_conflict")
    error(scenario.put_policy(DISABLED, "enable-first", enabled_etag), 409, "idempotency_conflict")
    scenario.install_policy(policy, "restore-identical")
    restored = scenario.status(reference)
    check(restored.status_code == 200 and restored.json()["authority"]["state"] == "inactive"
          and restored.json()["manifest"] == record["manifest"], "restoring identical bytes revived retired admission")
    replay_inactive = scenario.admit(reference)
    check(replay_inactive.status_code == 200 and replay_inactive.json() == restored.json()
          and scenario.usage() == {"plans": 1, "units": 1}, "inactive historical replay regranted/debited")
    scenario.record("policy-controls", {"noPolicyRefused": True, "disabledRefused": True, "appPolicy403": True,
                    "historicalCASReplayStable": True, "staleCAS412": True, "immutableAdmission": True, "quotaDebits": 1,
                    "policyRevision": replacement.json()["revision"], "admissionNeverDispatched": True})


def paused_verification(scenario):
    scenario.start()
    scenario.install_policy(scenario.policy())
    scenario.pause_verify()
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(scenario.admit, scenario.references[0])
        try:
            scenario.wait_verify()
            scenario.install_policy(DISABLED, "disable-during-verification")
        finally:
            scenario.release_verify()
        error(pending.result(timeout=60), 409, "policy_changed")
    check(scenario.usage() == {"plans": 0, "units": 0}, "stale verifier consumed quota")
    error(scenario.status(scenario.references[0]), 404, "admission_not_found")
    check(scenario.dispatch_counts() == {"extraction": [], "relation": []}, "stale verifier dispatched")
    scenario.record("paused-verification", {"policyChanged409": True, "quotaDebits": 0, "dispatches": 0})


def quota_contention(scenario):
    scenario.start()
    scenario.install_policy(scenario.policy(max_plans=1, max_units=1))
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(scenario.admit, scenario.references[:2]))
    check(sorted(r.status_code for r in responses) == [201, 409], "last-slot contenders did not produce one admission")
    error(next(r for r in responses if r.status_code == 409), 409, "quota_exhausted")
    check(scenario.usage() == {"plans": 1, "units": 1}, "quota contenders committed more than one debit")
    check(scenario.dispatch_counts() == {"extraction": [], "relation": []}, "quota contention dispatched work")
    scenario.record("last-quota-slot", {"contenders": 2, "commits": 1, "plans": 1, "units": 1, "dispatches": 0})


def source_revocation(scenario):
    service = scenario.start(hold=True)
    scenario.install_policy(scenario.policy())
    reference = scenario.references[0]
    scenario.workspace.revoke_source(False)
    refused = scenario.admit(reference)
    check(refused.status_code in (403, 409), "revoked current source read authorized admission")
    check(scenario.usage() == {"plans": 0, "units": 0}, "source-refused admission consumed quota")
    scenario.workspace.revoke_source(True)
    accepted = scenario.admit(reference)
    check(accepted.status_code == 201, "restored synthetic read right did not admit")
    unit = accepted.json()["manifest"]["units"][0]
    submit = unit["extractionSubmit"]
    check(service.esubmit(submit["jobId"], digest_=submit["approvedRequestDigest"]).status_code == 202, "online S2 reservation failed")
    scenario.workspace.revoke_source(False)
    scenario.workspace.go()
    status = service.ewait(submit["jobId"], dispatch={"idle"})
    check(status["state"] != "ready" and status["delivery"]["state"] == "withheld", "dispatch ignored revoked source")
    withheld = service.eresult(submit["jobId"]).json()
    check(withheld["delivery"]["state"] == "withheld" and withheld.get("job") is None, "revoked dispatch leaked result content")
    scenario.record("source-read-and-dispatch-revocation", {"admissionRefused": True, "dispatchReady": False, "deliveryWithheld": True})


def no_operator_adoption(scenario):
    service = scenario.start()
    scenario.install_policy(scenario.policy())
    reference = scenario.references[0]
    admitted = scenario.admit(reference)
    check(admitted.status_code == 201, "adoption fixture admission refused")
    unit = admitted.json()["manifest"]["units"][0]
    approval_file = scenario.plan_root / reference["planId"] / "approvals.json"
    request = json.loads(approval_file.read_bytes())["approvals"][0]["request"]
    workspace = scenario.workspace
    done = subprocess.run([str(workspace.s2_command), "run", "--state-dir", str(workspace.extraction_state), "--ingestion-state-dir", str(scenario.world.ingestion),
                           "--sources", str(workspace.sources), "--replay", str(workspace.s2_replay)],
                          input=canonical(request).encode(), env=pipeline_env(workspace), capture_output=True, timeout=120)
    check(done.returncode == 0 and not done.stderr and json.loads(done.stdout)["state"] == "ready", "real operator S2 setup failed")
    relation = unit["relationSubmit"]
    response = service.request("POST", "/internal/v1/relation-jobs", body=relation, key=relation["jobId"])
    check(response.status_code in (403, 409), "online S3 adopted operator-only S2 without same-origin service row")
    submit = unit["extractionSubmit"]
    error(service.esubmit(submit["jobId"], digest_=submit["approvedRequestDigest"]), 409)
    check(scenario.dispatch_counts() == {"extraction": [], "relation": []}, "operator adoption created dispatch intent")
    scenario.record("operator-adoption-refused", {"realOperatorS2Ready": True, "onlineS2AdoptionRefused": True, "onlineS3AdoptionRefused": True})


@pytest.fixture
def online_scenario(tmp_path):
    scenario = OnlineScenario(tmp_path / "online", tmp_path / "evidence")
    try:
        scenario.prepare()
        yield scenario
    finally:
        scenario.close()


def test_actual_http_policy_controls_and_terminal_replacement(online_scenario):
    controls(online_scenario)


def test_actual_installed_verifier_cannot_commit_after_policy_change(online_scenario):
    paused_verification(online_scenario)


def test_actual_http_last_quota_slot_has_one_winner(online_scenario):
    quota_contention(online_scenario)


def test_current_source_read_and_dispatch_rights_are_not_policy_grants(online_scenario):
    source_revocation(online_scenario)


def test_online_authority_does_not_adopt_operator_s2(online_scenario):
    no_operator_adoption(online_scenario)


def admission_crash(scenario, boundary):
    crashing = scenario.start(fault=boundary)
    scenario.install_policy(scenario.policy())
    reference = scenario.references[0]
    (scenario.root / "arm-service-fault").touch()
    try:
        scenario.admit(reference)
    except httpx.TransportError:
        pass
    check(crashing.exited() < 0 and (scenario.root / "fault-observed").read_text() == boundary,
          "test-owned admission crash missed its actual transaction boundary")
    (scenario.root / "arm-service-fault").unlink()
    scenario.start()
    committed = boundary == "after-commit"
    check(scenario.usage() == {"plans": int(committed), "units": int(committed)}, "crash broke atomic quota debit")
    status = scenario.status(reference)
    check(status.status_code == (200 if committed else 404), "crash exposed a partial/lost admission")
    historical = status.json() if committed else None
    check(scenario.dispatch_counts() == {"extraction": [], "relation": []}, "admission crash dispatched jobs")
    retry = scenario.admit(reference)
    check(retry.status_code == (200 if committed else 201), "crash retry did not recover durable admission")
    if historical is not None:
        check(retry.json() == historical, "after-commit retry regenerated manifest/identity")
    check(scenario.usage() == {"plans": 1, "units": 1}, "crash retry duplicated quota")
    manifest = retry.json()["manifest"]
    # Both grants must be usable after recovery, not merely visible in the manifest.
    unit = manifest["units"][0]
    submit = unit["extractionSubmit"]
    service = scenario.service
    check(service.esubmit(submit["jobId"], digest_=submit["approvedRequestDigest"]).status_code == 202, "recovered admission lost S2 grant")
    service.ewait(submit["jobId"], states={"ready"}, dispatch={"idle"})
    relation = unit["relationSubmit"]
    check(service.request("POST", "/internal/v1/relation-jobs", body=relation, key=relation["jobId"]).status_code == 202, "recovered admission lost paired S3 grant")
    done = service.rwait(relation["jobId"], states={"ready"}, dispatch={"idle"})
    check(done["usage"]["providerCalls"] == 0 and scenario.usage() == {"plans": 1, "units": 1}, "crash recovery called provider or duplicated debit")
    scenario.record("admission-crash-" + boundary, {"actualBoundaryReached": True, "durableBeforeRetry": committed,
                    "exactHistoricalRecovery": committed, "pairedS2S3Executed": True, "quotaDebits": 1, "providerCalls": 0})


def execution_crashes(scenario, *, unknown=False):
    service = scenario.start()
    scenario.install_policy(scenario.policy())
    admitted = scenario.admit(scenario.references[0])
    check(admitted.status_code == 201, "execution-crash admission refused")
    unit = admitted.json()["manifest"]["units"][0]
    submit = unit["extractionSubmit"]
    (scenario.root / ("crash-s2-unknown" if unknown else "crash-s2-receipt")).touch()
    check(service.esubmit(submit["jobId"], digest_=submit["approvedRequestDigest"]).status_code == 202, "execution-crash S2 submit refused")
    interrupted = service.ewait(submit["jobId"], dispatch={"idle"})
    check(interrupted["dispatch"]["lastOutcome"] == "transport_unknown" and interrupted["dispatch"]["dispatchCount"] == 1,
          "S2 child did not crash at real receive boundary")
    expected_calls = 0 if unknown else 1
    check(interrupted["usage"]["replayCalls"] == expected_calls and interrupted["usage"]["startedWithoutReceipt"] == int(unknown), "S2 crash receipt accounting wrong")
    service.kill()
    service = scenario.start()
    restarted = service.estatus(submit["jobId"]).json()
    check(restarted["usage"] == interrupted["usage"] and restarted["dispatch"]["dispatchCount"] == 1, "restart resent interrupted S2")
    check(service.erecover(submit["jobId"]).status_code == 202, "explicit S2 crash recovery refused")
    settled = service.ewait(submit["jobId"], states={"reconciling"} if unknown else {"ready"}, dispatch={"idle"})
    check(settled["usage"]["replayCalls"] == expected_calls and settled["usage"]["startedWithoutReceipt"] == int(unknown)
          and settled["usage"]["providerCalls"] == 0, "S2 recovery resent existing/ambiguous call")
    if unknown:
        check(settled["failure"] == {"code": "replay_response_unknown"}, "ambiguous S2 did not require operator reconciliation")
        check(service.erecover(submit["jobId"]).status_code == 409, "ambiguous S2 was automatically made resendable")
        scenario.record("ambiguous-execution", {"serviceRestarted": True, "callsResent": 0, "operatorReconciliationRequired": True, "providerCalls": 0})
        return
    receipts = service.eresult(submit["jobId"]).json()["receipts"]
    check(len(receipts) == 1 and receipts[0]["stage"] == "extract", "S2 stored receipt was duplicated")
    relation = unit["relationSubmit"]
    (scenario.root / "crash-s3-receipt").touch()
    check(service.request("POST", "/internal/v1/relation-jobs", body=relation, key=relation["jobId"]).status_code == 202, "execution-crash S3 submit refused")
    interrupted_s3 = service.rwait(relation["jobId"], dispatch={"idle"})
    check(interrupted_s3["dispatch"]["lastOutcome"] == "transport_unknown" and interrupted_s3["usage"]["replayCalls"] == 1
          and interrupted_s3["usage"]["startedWithoutReceipt"] == 0, "S3 receipt crash seam missed actual saved receipt")
    first_receipts = service.rresult(relation["jobId"]).json()["receipts"]
    service.kill()
    service = scenario.start()
    restarted_s3 = service.rstatus(relation["jobId"]).json()
    check(restarted_s3["usage"] == interrupted_s3["usage"] and restarted_s3["dispatch"]["dispatchCount"] == 1, "restart resent interrupted S3")
    check(service.rrecover(relation["jobId"]).status_code == 202, "explicit S3 receipt recovery refused")
    ready = service.rwait(relation["jobId"], states={"ready"}, dispatch={"idle"})
    final_receipts = service.rresult(relation["jobId"]).json()["receipts"]
    check(all(receipt in final_receipts for receipt in first_receipts) and sum(r["stage"] == "relation" for r in final_receipts) == 1
          and ready["usage"]["providerCalls"] == 0 and ready["usage"]["startedWithoutReceipt"] == 0, "S3 did not preserve/reuse exact saved receipt")
    scenario.record("receipt-execution-crashes", {"s2ReceiptCount": 1, "s3FirstReceiptPreserved": True,
                    "serviceRestarts": 2, "callsResent": 0, "providerCalls": 0})


def terminal_expiry(scenario):
    (scenario.root / "clock-offset").write_text("0")
    service = scenario.start(fault="clock")
    scenario.install_policy(scenario.policy())
    admitted = scenario.admit(scenario.references[0])
    check(admitted.status_code == 201, "clock fixture admission refused")
    (scenario.root / "clock-offset").write_text("7200")
    expired = scenario.status(scenario.references[0]).json()
    check(expired["authority"] == {"state": "inactive", "reason": "policy_expired"}, "observed expiry did not retire admission")
    (scenario.root / "clock-offset").write_text("0")
    check(scenario.status(scenario.references[0]).json() == expired, "clock rollback revived expired admission")
    service.kill()
    scenario.start()
    check(scenario.status(scenario.references[0]).json() == expired and scenario.usage() == {"plans": 1, "units": 1}, "restart revived expired admission/reset quota")
    scenario.record("terminal-expiry", {"observedExpiry": True, "clockRollbackDidNotRevive": True, "restartDidNotRevive": True})


@pytest.mark.parametrize("boundary", ["before-commit", "after-commit"])
def test_actual_admission_crash_is_atomic_and_recovers_paired_grants(online_scenario, boundary):
    admission_crash(online_scenario, boundary)


@pytest.mark.parametrize("unknown", [False, True], ids=["saved-receipt", "ambiguous-call"])
def test_actual_execution_crash_keeps_receipts_and_never_resends(online_scenario, unknown):
    execution_crashes(online_scenario, unknown=unknown)


def test_observed_expiry_is_terminal_across_clock_rollback_and_restart(online_scenario):
    terminal_expiry(online_scenario)


def mode_change_refused(scenario, *, from_online):
    reference = scenario.references[0]
    if not from_online:
        # Operator configuration is a private synthetic copy, never a real grant.
        scenario.workspace.approvals.write_bytes((scenario.plan_root / reference["planId"] / "approvals.json").read_bytes())
        scenario.original_manual = (scenario.workspace.approvals.read_bytes(), scenario.workspace.upstreams.read_bytes())
    service = scenario.start(online=from_online)
    if from_online:
        scenario.install_policy(scenario.policy())
        check(scenario.admit(reference).status_code == 201, "mode fixture online admission failed")
    else:
        approval = json.loads(scenario.workspace.approvals.read_bytes())["approvals"][0]
        check(service.esubmit(approval["jobId"], digest_=approval["approvedRequestDigest"]).status_code == 202, "manual mode fixture S2 submit failed")
        service.ewait(approval["jobId"], states={"ready"}, dispatch={"idle"})
    service.stop()
    before = tree(scenario.workspace.state)
    refused = scenario.start(online=not from_online, wait=False)
    check(refused.exited() == 78 and "authority_mode_mismatch" in refused.logs(), "populated service changed authority origin")
    check(tree(scenario.workspace.state) == before, "mode mismatch changed populated authority state")
    scenario.record("populated-mode-change", {"from": "online" if from_online else "manual", "startupExit": 78, "priorStateUnchanged": True})


def queued_policy_revocation(scenario):
    service = scenario.start(hold=True)
    policy = scenario.policy()
    scenario.install_policy(policy)
    admitted = scenario.admit(scenario.references[0])
    check(admitted.status_code == 201, "queued-revocation admission failed")
    unit = admitted.json()["manifest"]["units"][0]
    submit = unit["extractionSubmit"]
    check(service.esubmit(submit["jobId"], digest_=submit["approvedRequestDigest"]).status_code == 202, "queued-revocation S2 submit failed")
    scenario.install_policy(DISABLED, "disable-queued-dispatch")
    scenario.workspace.go()
    settled = service.ewait(submit["jobId"], dispatch={"idle"})
    check(settled["state"] != "ready" and settled["usage"]["replayCalls"] == 0 and settled["usage"]["providerCalls"] == 0,
          "queued replay dispatched after policy revocation")
    scenario.install_policy(policy, "restore-queued-policy")
    check(scenario.status(scenario.references[0]).json()["authority"]["state"] == "inactive", "queued admission revived after policy restore")
    check(service.erecover(submit["jobId"]).status_code in (403, 409), "retired queued work was recoverable")
    scenario.record("queued-policy-revocation", {"replayCalls": 0, "providerCalls": 0, "restorationDidNotRevive": True})


@pytest.mark.parametrize("from_online", [False, True], ids=["manual-to-online", "online-to-manual"])
def test_populated_service_cannot_change_authority_origins(online_scenario, from_online):
    mode_change_refused(online_scenario, from_online=from_online)


def test_policy_revocation_prevents_queued_replay_dispatch(online_scenario):
    queued_policy_revocation(online_scenario)
