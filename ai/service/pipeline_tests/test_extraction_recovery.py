"""Crashes, ambiguity and explicit recovery of S2 extraction jobs, over the real installed pipeline.

The invariants under test: the initial queued dispatch runs once; nothing ambiguous (a dead, timed-out or unreadable child, a restarted service, a job the
pipeline recorded as stopped) is ever run again automatically; a pipeline call that was reserved but never answered is never resent; recovery is an
explicit request; only a refusal the pipeline raises BEFORE any effect (a busy ledger lock) is retried by itself; a frozen identity is never rebound.
"""
from __future__ import annotations

import fcntl
import json
import time

import httpx
import pytest

from extraction_support import (CRASH_AFTER_EXTRACT_STAGE, CRASH_AFTER_FIRST_RECEIPT, CRASH_UNKNOWN, JOB, PLAIN, dispatch_row, inspect_direct, ledger_rows)

EMPTY_TOPIC = json.dumps({"format": "zoop-topic-replay-1", "synthetic": True, "recordingKind": "authored-test",
                          "producerVersion": "zoop-topic-replay-producer-1", "records": []}).encode()


def crash_at(point: str) -> dict[str, str]:
    return {"ZOOP_TEST_EXTRACTION_CRASH_AT": point}


def submit_into_a_crash(service, job_id: str = JOB, **kwargs) -> None:
    try:
        service.esubmit(job_id, **kwargs)
    except httpx.TransportError:
        pass  # the service may die before the response is written


def test_the_initial_dispatch_runs_once_even_across_restarts(start_extraction, world):
    service = start_extraction(hold=True)
    assert service.esubmit().status_code == 202
    pending = service.estay(JOB, 1.0)
    assert (pending["state"], pending["dispatch"]["state"], pending["dispatch"]["dispatchCount"]) == ("queued", "pending", 0)
    service.kill()  # the intent was durable before the 202; the dispatcher never claimed it
    second = start_extraction(workspace=service.workspace)
    done = second.ewait(states={"ready"}, dispatch={"idle"})
    assert done["dispatch"]["dispatchCount"] == 1 and done["usage"]["replayCalls"] == world.s2_replay_calls
    second.kill()
    third = start_extraction(workspace=service.workspace)
    quiet = third.estay(JOB, 3.0)
    assert (quiet["state"], quiet["dispatch"]["dispatchCount"], quiet["dispatch"]["lastOutcome"], quiet["usage"]) == ("ready", 1, "exited", done["usage"])


def test_a_claim_that_never_started_a_child_is_not_run_again_automatically(start_extraction, world):
    crashing = start_extraction(launcher_env=crash_at("after_claim"))
    submit_into_a_crash(crashing)
    crashing.exited()
    service = start_extraction(workspace=crashing.workspace)
    interrupted = service.ewait(dispatch={"idle"})
    assert (interrupted["state"], interrupted["dispatch"]["lastOutcome"], interrupted["dispatch"]["dispatchCount"], interrupted["next"]) == (
        "queued", "service_restarted", 1, "recover")
    quiet = service.estay(JOB, 3.0)
    assert quiet["state"] == "queued" and quiet["dispatch"]["dispatchCount"] == 1 and quiet["usage"]["replayCalls"] == 0
    recovered = service.erecover()
    assert recovered.status_code == 202 and recovered.json()["next"] == "wait"
    done = service.ewait(states={"ready"}, dispatch={"idle"})
    assert done["dispatch"]["dispatchCount"] == 2 and done["usage"]["replayCalls"] == world.s2_replay_calls
    assert service.eresult().json()["delivery"]["state"] == "available"


def test_a_child_that_finished_before_the_service_recorded_it_is_not_run_again(start_extraction, world):
    crashing = start_extraction(launcher_env=crash_at("after_child"))
    submit_into_a_crash(crashing)
    crashing.exited(timeout=180)
    service = start_extraction(workspace=crashing.workspace)
    seen = service.ewait(dispatch={"idle"})
    # The pipeline job is ready; the service cannot know that its child finished, so it says so and does nothing.
    assert (seen["state"], seen["dispatch"]["lastOutcome"], seen["dispatch"]["dispatchCount"], seen["next"]) == ("ready", "service_restarted", 1, "fetch_result")
    assert seen["usage"]["replayCalls"] == world.s2_replay_calls
    quiet = service.estay(JOB, 3.0)
    assert quiet["dispatch"]["dispatchCount"] == 1 and quiet["usage"] == seen["usage"]
    assert service.eresult().json()["delivery"]["state"] == "available"
    assert service.erecover().json()["error"]["code"] == "job_not_recoverable"


@pytest.mark.parametrize("point", ["after_reserve", "after_registration", "before_response"])
def test_a_crash_inside_submit_never_loses_or_duplicates_the_job(start_extraction, world, point):
    crashing = start_extraction(launcher_env=crash_at(point))
    submit_into_a_crash(crashing, PLAIN)
    crashing.exited()
    workspace = crashing.workspace
    if point == "after_registration":
        code, registered = inspect_direct(workspace, PLAIN)  # the pipeline holds the queued job; the service never accepted it
        assert code == 0 and registered["state"] == "queued" and registered["calls"] == []
    service = start_extraction(workspace=workspace)
    taken = service.esubmit(PLAIN, as_="beta")  # the durable owner claim survives the crash (beta is approved for the very same request)
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "job_id_unavailable"
    accepted_already = point == "before_response"
    assert service.estatus(PLAIN).status_code == (200 if accepted_already else 404)
    retried = service.esubmit(PLAIN)
    assert retried.status_code == (200 if accepted_already else 202)
    done = service.ewait(PLAIN, states={"ready"}, dispatch={"idle"})
    assert done["dispatch"]["dispatchCount"] == 1 and done["usage"]["replayCalls"] == world.s2_replay_calls - 1
    service.close()
    code, direct = inspect_direct(workspace, PLAIN)  # exactly one pipeline job, executed once
    assert code == 0 and direct["state"] == "ready" and direct["usage"]["replayCalls"] == world.s2_replay_calls - 1


def test_a_child_that_dies_after_reserving_a_call_is_never_resent(start_extraction, world):
    service = start_extraction(wrapper=CRASH_UNKNOWN)
    service.workspace.arm()
    assert service.esubmit().status_code == 202
    ambiguous = service.ewait(dispatch={"idle"})
    assert (ambiguous["dispatch"]["lastOutcome"], ambiguous["dispatch"]["dispatchCount"], ambiguous["state"], ambiguous["next"]) == (
        "transport_unknown", 1, "running", "recover")
    assert ambiguous["usage"] == {"replayCalls": 0, "startedWithoutReceipt": 1, "providerCalls": 0, "paidModelCalls": 0, "receivedCalls": 0, "unsentCalls": 0,
                                  "inputTokens": None, "outputTokens": None, "reasoningTokens": None, "estimatedUsd": None, "chargedUsd": None}
    quiet = service.estay(JOB, 3.0)
    assert quiet["dispatch"]["dispatchCount"] == 1 and quiet["usage"]["startedWithoutReceipt"] == 1  # nothing continued it
    assert service.erecover().status_code == 202  # explicit, and the pipeline itself refuses to resend an unreceipted call
    reconciling = service.ewait(states={"reconciling"}, dispatch={"idle"})
    assert (reconciling["next"], reconciling["failure"], reconciling["usage"]["replayCalls"], reconciling["usage"]["startedWithoutReceipt"]) == (
        "operator_reconcile", {"code": "replay_response_unknown"}, 0, 1)
    assert reconciling["dispatch"]["dispatchCount"] == 2
    again = service.erecover()
    assert again.status_code == 409 and again.json()["error"]["code"] == "reconcile_required" and again.json()["status"]["state"] == "reconciling"
    withheld = service.eresult().json()
    assert withheld["delivery"] == {"state": "withheld", "reason": "job_not_ready"} and withheld["job"] is None
    abandoned = service.ecancel()  # the owner may abandon a reconciling job; nothing is pretended to be resolved
    assert abandoned.status_code == 200 and abandoned.json()["state"] == "cancelled" and abandoned.json()["next"] == "none"


def test_a_saved_receipt_is_reused_on_explicit_recovery_and_never_called_again(start_extraction, world):
    service = start_extraction(wrapper=CRASH_AFTER_EXTRACT_STAGE)
    service.workspace.arm()
    service.esubmit()
    interrupted = service.ewait(dispatch={"idle"})
    assert (interrupted["dispatch"]["lastOutcome"], interrupted["state"], interrupted["usage"]["replayCalls"], interrupted["next"]) == (
        "transport_unknown", "running", 1, "recover")
    quiet = service.estay(JOB, 3.0)
    assert quiet["usage"]["replayCalls"] == 1 and quiet["dispatch"]["dispatchCount"] == 1  # a stored stage is not continued automatically
    assert service.erecover().status_code == 202
    done = service.ewait(states={"ready"}, dispatch={"idle"})
    assert done["dispatch"]["dispatchCount"] == 2 and done["usage"]["replayCalls"] == world.s2_replay_calls
    receipts = service.eresult().json()["receipts"]
    assert len(receipts) == world.s2_replay_calls and sum(r["stage"] == "extract" for r in receipts) == 1  # generated once, reused after the crash


def test_a_receipt_saved_before_its_stage_completed_is_reused_and_never_called_again(start_extraction, world):
    """The crash boundary the stage-completed case does not reach: the first receipt is committed, but its candidates and the stage marker are not."""
    service = start_extraction(wrapper=CRASH_AFTER_FIRST_RECEIPT)
    service.workspace.arm()
    service.esubmit()
    interrupted = service.ewait(dispatch={"idle"})
    assert (interrupted["dispatch"]["lastOutcome"], interrupted["state"], interrupted["usage"]["replayCalls"], interrupted["next"]) == (
        "transport_unknown", "running", 1, "recover")
    assert interrupted["usage"]["startedWithoutReceipt"] == 0
    assert interrupted["stages"][0] == {"stage": "extract", "state": "pending"}      # the receipt exists, the stage is NOT complete
    assert service.eresult().json()["job"] is None
    assert service.estay(JOB, 3.0)["usage"]["replayCalls"] == 1                       # nothing continued it
    assert service.erecover().status_code == 202
    done = service.ewait(states={"ready"}, dispatch={"idle"})
    assert done["dispatch"]["dispatchCount"] == 2 and done["usage"]["replayCalls"] == world.s2_replay_calls
    receipts = service.eresult().json()["receipts"]
    assert len(receipts) == world.s2_replay_calls and sum(r["stage"] == "extract" for r in receipts) == 1   # saved response reused: no extra call


def test_a_child_past_its_deadline_is_ambiguous_and_waits_for_an_explicit_recover(start_extraction, world):
    slow = start_extraction(launcher_env={"ZOOP_TEST_RUN_DEADLINE": "0.05"})
    assert slow.esubmit().status_code == 202
    timed_out = slow.ewait(dispatch={"idle"})
    assert (timed_out["dispatch"]["lastOutcome"], timed_out["dispatch"]["dispatchCount"], timed_out["next"]) == ("transport_unknown", 1, "recover")
    assert timed_out["usage"]["replayCalls"] == 0
    assert slow.estay(JOB, 2.0)["dispatch"]["dispatchCount"] == 1
    slow.kill()
    service = start_extraction(workspace=slow.workspace)
    assert service.erecover().status_code == 202
    done = service.ewait(states={"ready"}, dispatch={"idle"})
    assert done["usage"]["replayCalls"] == world.s2_replay_calls and done["dispatch"]["dispatchCount"] == 2


def test_a_stopped_job_waits_for_an_explicit_recover_and_its_pinned_fixture_cannot_be_swapped_to_repair_it(start_extraction, world):
    service = start_extraction()
    workspace = service.workspace
    real_topic = workspace.s2_topic.read_bytes()
    workspace.use_topic(EMPTY_TOPIC, repin=True)   # the operator approved a topic fixture that holds no answer for this request
    service.esubmit()
    stopped = service.ewait(states={"stopped"}, dispatch={"idle"})
    assert stopped["failure"] == {"code": "topic_replay_missing"} and stopped["next"] == "recover" and stopped["dispatch"]["dispatchCount"] == 1
    assert stopped["delivery"] == {"state": "withheld", "reason": "job_not_ready"} and stopped["usage"]["replayCalls"] == 2
    envelope = service.eresult().json()
    assert envelope["job"] is None and "topicRequestDigest" not in str(envelope) and "requestDigest" not in str(envelope)  # the pipeline's detail is never relayed
    assert service.estay(JOB, 2.0)["dispatch"]["dispatchCount"] == 1
    assert service.erecover().status_code == 202    # explicit, repeatable, and the stored stages are reused, not called again
    again = service.ewait(states={"stopped"}, dispatch={"idle"})
    assert again["dispatch"]["dispatchCount"] == 2 and again["usage"]["replayCalls"] == 2
    # Swapping in the real topic fixture (and re-pinning the approval) is NOT a repair: the job was reserved under the empty one and is never rebound.
    workspace.use_topic(real_topic, repin=True)
    refused = service.erecover()
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "approval_changed"
    assert service.estay(JOB, 1.5)["dispatch"]["dispatchCount"] == 2
    cancelled = service.ecancel()
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled" and cancelled.json()["phase"] == "cancelled"
    # Authorization comes first: while the approval is still rotated the refusal is approval_changed, and it starts nothing.
    still = service.erecover()
    assert still.status_code == 409 and still.json()["error"]["code"] == "approval_changed"
    assert service.estay(JOB, 1.5)["dispatch"]["dispatchCount"] == 2 and service.estatus().json()["state"] == "cancelled"
    # Restoring the reserved (empty) fixture and its pin independently proves the terminal code.
    workspace.use_topic(EMPTY_TOPIC, repin=True)
    assert service.erecover().json()["error"]["code"] == "job_not_recoverable"


def test_a_busy_pipeline_ledger_is_retried_before_any_effect_and_reads_never_serve_stale_state(start_extraction, world):
    service = start_extraction(hold=True)
    workspace = service.workspace
    assert service.esubmit().status_code == 202  # creates the pipeline ledger and its lock file
    with open(workspace.extraction_state / "extraction.lock", "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # another process (an operator) holds the ledger
        try:
            busy = service.estatus()
            assert busy.status_code == 503 and busy.json()["error"]["code"] == "runtime_busy" and busy.json()["error"]["retryable"] is True
            assert busy.headers["retry-after"] == "2"
            refused = service.esubmit(PLAIN)  # the adoption probe cannot read the ledger: refused, and the reservation is released
            assert refused.status_code == 503 and refused.json()["error"]["code"] == "runtime_busy"
            workspace.go()
            time.sleep(3.0)
            state, count, busy_count, outcome, code = dispatch_row(workspace)
            assert state in {"pending", "in_flight"} and count >= 2 and busy_count >= 1 and outcome == "busy" and code == "extraction_busy"
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    done = service.ewait(states={"ready"}, dispatch={"idle"}, timeout=180)
    assert done["dispatch"]["dispatchCount"] >= 2 and done["usage"]["replayCalls"] == world.s2_replay_calls  # one execution after the retries
    assert service.esubmit(PLAIN).status_code == 202  # the earlier refusal left nothing behind


def test_a_busy_reader_inside_an_execution_stops_the_job_and_only_an_explicit_recover_resumes_it(start_extraction, world):
    service = start_extraction(hold=True)
    workspace = service.workspace
    assert service.esubmit().status_code == 202
    with open(world.ingestion / "ingestion.lock", "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # an operator's ingestion writer holds the ingestion ledger while the job runs
        try:
            workspace.go()
            stopped = service.ewait(states={"stopped"}, dispatch={"idle"}, timeout=120)
            assert stopped["failure"] == {"code": "ingestion_busy"} and stopped["dispatch"]["lastOutcome"] == "exited"   # the pipeline answered: not a busy REFUSAL
            quiet = service.estay(JOB, 3.0)
            assert quiet["state"] == "stopped" and quiet["dispatch"]["dispatchCount"] == 1 and quiet["next"] == "recover"   # never retried by the service
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    assert service.erecover().status_code == 202
    done = service.ewait(states={"ready"}, dispatch={"idle"})
    assert done["dispatch"]["dispatchCount"] == 2 and done["usage"]["replayCalls"] == world.s2_replay_calls
    assert ledger_rows(workspace, "SELECT COUNT(*) FROM extraction_jobs") == [(1,)]
