"""Crashes at every durable boundary and honest recovery, with the real runtime. No crash may duplicate or invent a model call.

Replay tests inject a SIGKILL of the service itself through tests/launcher.py (the real submit/ledger still run). Live-path tests
use a loopback provider that counts requests, so "no resend" is measured at the provider, not inferred.
"""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import time

import httpx
import pytest

from support import cli, document_jobs, document_replay, live_job, reference, runtime_processes, wait_for

JOBS = "/internal/v1/analysis-jobs"


def runtime_state(service, job_id):
    code, body = cli(service.workspace, "get", reference(job_id))
    return body if code == 0 else None


def dispatch_rows(service):
    db = sqlite3.connect(f"file:{service.workspace.state / 'service.sqlite3'}?mode=ro", uri=True)
    try:
        return db.execute("SELECT job_id, state, dispatch_count, last_outcome FROM analysis_dispatch").fetchall()
    finally:
        db.close()


def run_child(worker):
    return runtime_processes(worker)


def crash_service(start, mode, **kwargs):
    return start(replay=document_replay(), launcher=True, launcher_env={"ZOOP_TEST_CRASH_AT": mode}, **kwargs)


def test_crash_after_owner_intent_keeps_the_claim_and_the_owner_retry_completes_it(start):
    crashing = crash_service(start, "after_intent")
    job = document_jobs()[0]
    with pytest.raises(httpx.TransportError):
        crashing.submit(job)
    assert crashing.exited() == -signal.SIGKILL
    assert runtime_state(crashing, job["jobId"]) is None  # the runtime never registered anything
    service = start(workspace=crashing.workspace)
    assert service.status(job["jobId"]).status_code == 404  # reserved is not accepted
    taken = service.submit(job, as_="beta")
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "job_id_unavailable"
    assert service.submit({**job, "kind": "document-sentiment"}).json()["error"]["code"] == "idempotency_conflict"
    assert service.submit(job).status_code == 202
    final = service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})
    assert final["usage"]["replayCalls"] == 2 and final["dispatch"]["dispatchCount"] == 1


def test_crash_after_worker_registration_cannot_be_claimed_by_another_principal(start):
    crashing = crash_service(start, "after_registration")
    job = document_jobs()[0]
    with pytest.raises(httpx.TransportError):
        crashing.submit(job)
    assert crashing.exited() == -signal.SIGKILL
    orphan = runtime_state(crashing, job["jobId"])
    assert orphan is not None and orphan["state"] == "queued" and orphan["calls"] == []  # registered, zero calls, zero cost
    service = start(workspace=crashing.workspace)
    # The orphan is unowned in the runtime but owned in the service ledger: nobody else can adopt it.
    assert service.submit(job, as_="beta").status_code == 409
    assert service.status(job["jobId"], as_="beta").status_code == 404
    assert service.status(job["jobId"]).status_code == 404
    assert service.submit(job).status_code == 202  # the owner's retry completes the acknowledgement
    final = service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})
    assert final["usage"]["replayCalls"] == 2 and final["dispatch"]["dispatchCount"] == 1


def test_crash_after_accept_before_the_response_runs_the_job_and_a_retry_gets_200(start):
    crashing = crash_service(start, "before_response")
    job = document_jobs()[0]
    with pytest.raises(httpx.TransportError):
        crashing.submit(job)
    assert crashing.exited() == -signal.SIGKILL
    service = start(workspace=crashing.workspace)
    final = service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})  # no client retry was needed
    assert final["usage"]["replayCalls"] == 2 and final["usage"]["providerAttempts"] == 0
    retry = service.submit(job)
    assert retry.status_code == 200 and retry.json()["state"] == "ready"


def test_crash_after_dispatch_claim_is_requeued_once_and_runs_exactly_once(start):
    crashing = crash_service(start, "after_claim")
    job = document_jobs()[0]
    try:
        crashing.submit(job)  # the claim races the response: the client may or may not see the 202 before the crash
    except httpx.TransportError:
        pass
    assert crashing.exited() == -signal.SIGKILL
    assert dispatch_rows(crashing)[0][1:3] == ("in_flight", 1)
    assert runtime_state(crashing, job["jobId"])["calls"] == []  # claimed, but no child ever started
    service = start(workspace=crashing.workspace)
    final = service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})
    assert final["usage"]["replayCalls"] == 2 and final["dispatch"]["dispatchCount"] == 2
    assert '"requeuedInFlight":1' in service.logs()


def test_restart_after_completion_changes_nothing(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    service.submit(job)
    done = service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})
    service.kill()
    restarted = start(workspace=service.workspace)
    after = restarted.status(job["jobId"]).json()
    assert after["state"] == "ready" and after["dispatch"] == done["dispatch"] and after["usage"] == done["usage"]
    assert restarted.submit(job).status_code == 200
    time.sleep(1.0)  # a requeued dispatch would have shown by now
    assert restarted.status(job["jobId"]).json()["dispatch"]["dispatchCount"] == 1


def test_blocked_replay_fixture_is_reported_as_queued_not_as_background_success(start):
    broken = document_replay()
    broken["recordingKind"] = "provider"
    service = start(replay=broken)
    job = document_jobs()[0]
    assert service.submit(job).status_code == 202
    blocked = service.wait_state(job["jobId"], {"queued"}, dispatch={"idle"})
    assert blocked["dispatch"]["lastOutcome"] == "runtime_error" and blocked["dispatch"]["lastRuntimeCode"] == "replay_fixture_invalid"
    assert blocked["next"] == "recover" and blocked["usage"]["replayCalls"] == 0 and blocked["failure"] is None
    service.workspace.replay_path.write_text(json.dumps(document_replay(), ensure_ascii=False))
    recovered = service.recover(job["jobId"])
    assert recovered.status_code == 202 and recovered.json()["next"] == "wait"
    final = service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})
    assert final["usage"]["replayCalls"] == 2 and final["dispatch"]["dispatchCount"] == 2
    assert service.recover(job["jobId"]).status_code == 409  # ready is not recoverable


def test_unreadable_replay_fixture_is_a_runtime_error_until_fixed(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    service.workspace.replay_path.chmod(0)
    try:
        service.submit(job)
        blocked = service.wait_state(job["jobId"], {"queued"}, dispatch={"idle"})
        assert blocked["dispatch"]["lastRuntimeCode"] == "input_or_configuration_invalid" and blocked["next"] == "recover"
    finally:
        service.workspace.replay_path.chmod(0o600)
    assert service.recover(job["jobId"]).status_code == 202
    assert service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})["usage"]["replayCalls"] == 2


def test_recover_coalesces_into_a_pending_or_in_flight_dispatch(start, provider, live):
    workspace, env = live()
    service = start(workspace=workspace, env=env)
    gate = provider.gate("document_summary")
    job = live_job()
    assert service.submit(job).status_code == 202
    assert gate.entered.wait(30)
    first = service.recover(job["jobId"])
    assert first.status_code == 200 and first.json()["dispatch"]["state"] == "in_flight" and first.json()["next"] == "wait"
    assert service.recover(job["jobId"]).status_code == 200
    gate.release()
    final = service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})
    assert final["dispatch"]["dispatchCount"] == 1 and provider.requests == ["document_summary", "semantic_verification"]


def test_kill_right_after_202_runs_the_job_exactly_once(start, provider, live):
    provider.delay = 1.0
    workspace, env = live()
    service = start(workspace=workspace, env=env)
    job = live_job()
    assert service.submit(job).status_code == 202
    service.kill()
    restarted = start(workspace=workspace, env=env)
    final = restarted.wait_state(job["jobId"], {"ready"}, dispatch={"idle"}, timeout=60)
    assert final["usage"]["providerAttempts"] == 2 and final["unreceiptedAttempts"] == 0
    assert provider.requests == ["document_summary", "semantic_verification"]


def test_kill_the_service_during_the_provider_call_then_restart_never_resends(start, provider, live):
    workspace, env = live()
    service = start(workspace=workspace, env=env)
    gate = provider.gate("document_summary")
    job = live_job()
    service.submit(job)
    assert gate.entered.wait(30)
    service.kill()
    restarted = start(workspace=workspace, env=env)
    # The orphan child still holds the job's lock: the runtime answers busy and the service backs off, it does not resend.
    busy = restarted.wait_state(job["jobId"], {"running"}, dispatch={"pending", "in_flight"})
    assert busy["unreceiptedAttempts"] == 1 and busy["usage"]["providerAttempts"] == 1
    wait_for(lambda: restarted.status(job["jobId"]).json()["dispatch"]["lastOutcome"] == "busy", 30, 0.2, "a busy outcome")
    assert provider.requests == ["document_summary"]
    gate.release()
    final = restarted.wait_state(job["jobId"], {"ready"}, dispatch={"idle"}, timeout=60)
    assert final["usage"]["providerAttempts"] == 2 and final["unreceiptedAttempts"] == 0
    assert provider.requests == ["document_summary", "semantic_verification"]


def test_killed_child_becomes_reconciling_with_no_resend_and_stays_so_across_restart(start, provider, live):
    workspace, env = live()
    service = start(workspace=workspace, env=env)
    gate = provider.gate("document_summary")
    job = live_job()
    service.submit(job)
    assert gate.entered.wait(30)
    pids = wait_for(lambda: run_child(workspace.worker), 10, 0.1, "the run child")
    for pid in pids:
        os.kill(pid, signal.SIGKILL)
    gate.release()
    status = service.wait_state(job["jobId"], {"reconciling"}, dispatch={"idle"}, timeout=60)
    assert status["resumeMode"] == "reconcile_only" and status["next"] == "operator_reconcile"
    assert status["unreceiptedAttempts"] == 1 and status["usage"]["providerAttempts"] == 1
    assert '"outcome":"transport_unknown"' in service.logs()
    assert provider.requests == ["document_summary"]
    blocked = service.recover(job["jobId"])
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "reconcile_required"
    assert blocked.json()["status"]["state"] == "reconciling"
    service.kill()
    restarted = start(workspace=workspace, env=env)
    again = restarted.status(job["jobId"]).json()
    assert again["state"] == "reconciling" and again["unreceiptedAttempts"] == 1 and again["next"] == "operator_reconcile"
    assert restarted.recover(job["jobId"]).status_code == 409
    time.sleep(1.5)
    assert provider.requests == ["document_summary"]  # unknown is never resent


def test_deadline_kill_is_an_unknown_outcome_and_reconciles_without_resend(start, provider, live):
    workspace, env = live()
    service = start(workspace=workspace, env=env, launcher=True, launcher_env={"ZOOP_TEST_RUN_DEADLINE": "2"})
    gate = provider.gate("document_summary")
    job = live_job()
    service.submit(job)
    assert gate.entered.wait(30)
    status = service.wait_state(job["jobId"], {"reconciling"}, dispatch={"idle"}, timeout=60)
    assert status["next"] == "operator_reconcile" and status["unreceiptedAttempts"] == 1
    assert '"runtime":"timeout"' in service.logs() and '"outcome":"transport_unknown"' in service.logs()
    gate.release()
    time.sleep(1.0)
    assert provider.requests == ["document_summary"]
    wait_for(lambda: not run_child(workspace.worker), 10, 0.1, "the terminated child to be gone")


def test_exhausted_budget_fails_unsent_and_only_an_explicit_recover_resumes_it(start, provider, live):
    workspace, env = live("1")
    service = start(workspace=workspace, env=env)
    job = live_job()
    service.submit(job)
    failed = service.wait_state(job["jobId"], {"failed"}, dispatch={"idle"}, timeout=60)
    assert failed["failure"] == {"code": "global_budget_exhausted", "stage": "semantic-verification"}
    assert failed["resumeMode"] == "unsent_only" and failed["next"] == "recover" and failed["usage"]["providerAttempts"] == 1
    time.sleep(1.5)
    assert provider.requests == ["document_summary"] and service.status(job["jobId"]).json()["dispatch"]["dispatchCount"] == 1
    again = service.recover(job["jobId"])
    assert again.status_code == 202
    final = service.wait_state(job["jobId"], {"failed"}, dispatch={"idle"}, timeout=60)
    assert final["dispatch"]["dispatchCount"] == 2 and final["failure"]["code"] == "global_budget_exhausted"
    assert provider.requests == ["document_summary"]  # the durable ceiling held: nothing new was sent
