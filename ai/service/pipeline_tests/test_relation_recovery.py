"""Crashes, ambiguity and explicit recovery of S3 relation jobs, over the real installed pipeline.

The invariants under test: the initial queued dispatch runs once; nothing ambiguous (a dead, timed-out or unreadable child, a restarted
service) is ever run again automatically; a pipeline call that was reserved but never answered is never resent; recovery is an explicit
request; a busy pipeline ledger is retried only because the pipeline refuses before any effect.
"""
from __future__ import annotations

import fcntl
import sqlite3
import time

import httpx
import pytest

from relation_support import CRASH_AFTER_RELATION_STAGE, CRASH_UNKNOWN, JOB, inspect_direct


def crash_at(point: str) -> dict[str, str]:
    return {"ZOOP_TEST_RELATION_CRASH_AT": point}


def submit_into_a_crash(service) -> None:
    try:
        service.rsubmit()
    except httpx.TransportError:
        pass  # the service may die before the response is written


def dispatch_row(workspace) -> tuple:
    database = sqlite3.connect(f"file:{workspace.state / 'relation-jobs.sqlite3'}?mode=ro", uri=True)
    try:
        return database.execute("SELECT state, dispatch_count, busy_count, last_outcome, last_runtime_code FROM relation_dispatch").fetchone()
    finally:
        database.close()


def test_the_initial_dispatch_runs_once_even_across_restarts(start_relation, world):
    service = start_relation(hold=True)
    assert service.rsubmit().status_code == 202
    pending = service.stay(JOB, 1.0)
    assert (pending["state"], pending["dispatch"]["state"], pending["dispatch"]["dispatchCount"]) == ("queued", "pending", 0)
    service.kill()  # the intent was durable before the 202; the dispatcher never claimed it
    second = start_relation(workspace=service.workspace)
    done = second.rwait(states={"ready"}, dispatch={"idle"})
    assert done["dispatch"]["dispatchCount"] == 1 and done["usage"]["replayCalls"] == world.replay_calls
    second.kill()
    third = start_relation(workspace=service.workspace)
    quiet = third.stay(JOB, 3.0)
    assert (quiet["state"], quiet["dispatch"]["dispatchCount"], quiet["dispatch"]["lastOutcome"], quiet["usage"]) == (
        "ready", 1, "exited", done["usage"])


def test_a_claim_that_never_started_a_child_is_not_run_again_automatically(start_relation, world):
    crashing = start_relation(launcher_env=crash_at("after_claim"))
    submit_into_a_crash(crashing)
    crashing.exited()
    service = start_relation(workspace=crashing.workspace)
    interrupted = service.rwait(dispatch={"idle"})
    assert (interrupted["state"], interrupted["dispatch"]["lastOutcome"], interrupted["dispatch"]["dispatchCount"], interrupted["next"]) == (
        "queued", "service_restarted", 1, "recover")
    quiet = service.stay(JOB, 3.0)
    assert quiet["state"] == "queued" and quiet["dispatch"]["dispatchCount"] == 1 and quiet["usage"]["replayCalls"] == 0
    recovered = service.rrecover()
    assert recovered.status_code == 202 and recovered.json()["next"] == "wait"
    done = service.rwait(states={"ready"}, dispatch={"idle"})
    assert done["dispatch"]["dispatchCount"] == 2 and done["usage"]["replayCalls"] == world.replay_calls
    assert service.rresult().json()["delivery"]["state"] == "available"


def test_a_child_that_finished_before_the_service_recorded_it_is_not_run_again(start_relation, world):
    crashing = start_relation(launcher_env=crash_at("after_child"))
    submit_into_a_crash(crashing)
    crashing.exited(timeout=180)
    service = start_relation(workspace=crashing.workspace)
    seen = service.rwait(dispatch={"idle"})
    # The pipeline job is ready; the service cannot know that its child finished, so it says so and does nothing.
    assert (seen["state"], seen["dispatch"]["lastOutcome"], seen["dispatch"]["dispatchCount"], seen["next"]) == ("ready", "service_restarted", 1, "fetch_result")
    assert seen["usage"]["replayCalls"] == world.replay_calls
    quiet = service.stay(JOB, 3.0)
    assert quiet["dispatch"]["dispatchCount"] == 1 and quiet["usage"] == seen["usage"]
    assert service.rresult().json()["delivery"]["state"] == "available"


@pytest.mark.parametrize("point", ["after_reserve", "after_registration", "before_response"])
def test_a_crash_inside_submit_never_loses_or_duplicates_the_job(start_relation, world, point):
    crashing = start_relation(launcher_env=crash_at(point))
    submit_into_a_crash(crashing)
    crashing.exited()
    workspace = crashing.workspace
    if point == "after_registration":
        code, registered = inspect_direct(workspace, JOB)  # the pipeline holds the queued job; the service never accepted it
        assert code == 0 and registered["state"] == "queued" and registered["calls"] == []
    service = start_relation(workspace=workspace)
    taken = service.rsubmit(as_="beta")  # the durable owner claim survives the crash
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "job_id_unavailable"
    accepted_already = point == "before_response"
    assert service.rstatus().status_code == (200 if accepted_already else 404)
    retried = service.rsubmit()
    assert retried.status_code == (200 if accepted_already else 202)
    done = service.rwait(states={"ready"}, dispatch={"idle"})
    assert done["dispatch"]["dispatchCount"] == 1 and done["usage"]["replayCalls"] == world.replay_calls
    service.close()
    code, direct = inspect_direct(workspace, JOB)  # exactly one pipeline job, executed once
    assert code == 0 and direct["state"] == "ready" and direct["usage"]["replayCalls"] == world.replay_calls


def test_a_child_that_dies_after_reserving_a_call_is_never_resent(start_relation, world):
    service = start_relation(wrapper=CRASH_UNKNOWN)
    service.workspace.arm()
    assert service.rsubmit().status_code == 202
    ambiguous = service.rwait(dispatch={"idle"})
    assert (ambiguous["dispatch"]["lastOutcome"], ambiguous["dispatch"]["dispatchCount"], ambiguous["state"], ambiguous["next"]) == (
        "transport_unknown", 1, "running", "recover")
    assert ambiguous["usage"] == {"replayCalls": 0, "startedWithoutReceipt": 1, "providerCalls": 0, "modelCalls": 0}
    quiet = service.stay(JOB, 3.0)
    assert quiet["dispatch"]["dispatchCount"] == 1 and quiet["usage"]["startedWithoutReceipt"] == 1  # nothing continued it
    assert service.rrecover().status_code == 202  # explicit, and the pipeline itself refuses to resend an unreceipted call
    reconciling = service.rwait(states={"reconciling"}, dispatch={"idle"})
    assert (reconciling["next"], reconciling["failure"], reconciling["usage"]["replayCalls"], reconciling["usage"]["startedWithoutReceipt"]) == (
        "operator_reconcile", {"code": "replay_response_unknown"}, 0, 1)
    assert reconciling["dispatch"]["dispatchCount"] == 2
    again = service.rrecover()
    assert again.status_code == 409 and again.json()["error"]["code"] == "reconcile_required" and again.json()["status"]["state"] == "reconciling"
    withheld = service.rresult().json()
    assert withheld["delivery"] == {"state": "withheld", "reason": "job_not_ready"} and withheld["job"] is None
    abandoned = service.rcancel()  # the owner may abandon a reconciling job; nothing is pretended to be resolved
    assert abandoned.status_code == 200 and abandoned.json()["state"] == "cancelled" and abandoned.json()["next"] == "none"


def test_a_saved_receipt_is_reused_on_explicit_recovery_and_never_called_again(start_relation, world):
    service = start_relation(wrapper=CRASH_AFTER_RELATION_STAGE)
    service.workspace.arm()
    service.rsubmit()
    interrupted = service.rwait(dispatch={"idle"})
    assert (interrupted["dispatch"]["lastOutcome"], interrupted["state"], interrupted["usage"]["replayCalls"], interrupted["next"]) == (
        "transport_unknown", "running", 1, "recover")
    quiet = service.stay(JOB, 3.0)
    assert quiet["usage"]["replayCalls"] == 1 and quiet["dispatch"]["dispatchCount"] == 1  # a stored stage is not continued automatically
    assert service.rrecover().status_code == 202
    done = service.rwait(states={"ready"}, dispatch={"idle"})
    assert done["dispatch"]["dispatchCount"] == 2 and done["usage"]["replayCalls"] == world.replay_calls
    receipts = service.rresult().json()["receipts"]
    assert len(receipts) == world.replay_calls and sum(r["stage"] == "relation" for r in receipts) == 1  # generated once, reused after the crash


def test_a_child_past_its_deadline_is_ambiguous_and_waits_for_an_explicit_recover(start_relation, world):
    slow = start_relation(launcher_env={"ZOOP_TEST_RUN_DEADLINE": "0.05"})
    assert slow.rsubmit().status_code == 202
    timed_out = slow.rwait(dispatch={"idle"})
    assert (timed_out["dispatch"]["lastOutcome"], timed_out["dispatch"]["dispatchCount"], timed_out["next"]) == ("transport_unknown", 1, "recover")
    assert timed_out["usage"]["replayCalls"] == 0
    assert slow.stay(JOB, 2.0)["dispatch"]["dispatchCount"] == 1
    slow.kill()
    service = start_relation(workspace=slow.workspace)
    assert service.rrecover().status_code == 202
    done = service.rwait(states={"ready"}, dispatch={"idle"})
    assert done["usage"]["replayCalls"] == world.replay_calls and done["dispatch"]["dispatchCount"] == 2


def test_a_stopped_job_waits_for_an_explicit_recover_and_recovery_is_repeatable(start_relation, world):
    service = start_relation(producer=world.empty_producer, verifier=world.empty_verifier)
    service.rsubmit()
    stopped = service.rwait(states={"stopped"}, dispatch={"idle"})
    assert stopped["failure"] == {"code": "producer_replay_missing"} and stopped["next"] == "recover" and stopped["dispatch"]["dispatchCount"] == 1
    assert stopped["delivery"] == {"state": "withheld", "reason": "job_not_ready"}
    envelope = service.rresult().json()
    assert envelope["job"] is None and "requestDigest" not in str(envelope)  # the pipeline's detail carries a request digest: never relayed
    assert service.stay(JOB, 2.0)["dispatch"]["dispatchCount"] == 1
    assert service.rrecover().status_code == 202
    again = service.rwait(states={"stopped"}, dispatch={"idle"})
    assert again["dispatch"]["dispatchCount"] == 2 and again["usage"]["replayCalls"] == 0
    service.workspace.use_fixtures(world.producer, world.verifier)  # the operator fixes the server-owned input
    assert service.rrecover().status_code == 202
    done = service.rwait(states={"ready"}, dispatch={"idle"})
    assert done["dispatch"]["dispatchCount"] == 3 and done["failure"] is None and done["usage"]["replayCalls"] == world.replay_calls
    assert service.rresult().json()["delivery"]["state"] == "available"


def test_a_busy_pipeline_ledger_is_retried_before_any_effect_and_reads_never_serve_stale_state(start_relation, world):
    service = start_relation(hold=True)
    workspace = service.workspace
    assert service.rsubmit().status_code == 202  # creates the pipeline ledger and its lock file
    with open(workspace.relation_state / "relation.lock", "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # another process (an operator) holds the ledger
        try:
            busy = service.rstatus()
            assert busy.status_code == 503 and busy.json()["error"]["code"] == "runtime_busy" and busy.json()["error"]["retryable"] is True
            assert busy.headers["retry-after"] == "2"
            refused = service.rsubmit("second")  # the adoption probe cannot read the ledger: refused, and the reservation is released
            assert refused.status_code == 503 and refused.json()["error"]["code"] == "runtime_busy"
            workspace.go()
            time.sleep(3.0)
            state, count, busy_count, outcome, code = dispatch_row(workspace)
            assert state in {"pending", "in_flight"} and count >= 2 and busy_count >= 1 and outcome == "busy" and code == "relation_busy"
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    done = service.rwait(states={"ready"}, dispatch={"idle"}, timeout=180)
    assert done["dispatch"]["dispatchCount"] >= 2 and done["usage"]["replayCalls"] == world.replay_calls  # one execution after the retries
    assert service.rsubmit("second").status_code == 202  # the earlier refusal left nothing behind
