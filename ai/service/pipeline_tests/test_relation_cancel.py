"""Cancel and recover on every kind of job: explicit terminal behavior, nothing pretended."""
from __future__ import annotations

from relation_support import JOB, inspect_direct


def test_cancelling_a_queued_job_ends_its_dispatch_and_nothing_ever_runs(start_relation, world):
    service = start_relation(hold=True)
    assert service.rsubmit().status_code == 202
    cancelled = service.rcancel()
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert (body["state"], body["next"], body["dispatch"]["state"], body["dispatch"]["lastOutcome"], body["dispatch"]["dispatchCount"]) == (
        "cancelled", "none", "idle", "cancelled", 0)
    assert body["delivery"] == {"state": "withheld", "reason": "job_cancelled"} and body["usage"]["replayCalls"] == 0
    service.workspace.go()  # a dispatcher that is free to run still has nothing to run
    quiet = service.stay(JOB, 3.0)
    assert (quiet["state"], quiet["dispatch"]["dispatchCount"], quiet["usage"]["replayCalls"]) == ("cancelled", 0, 0)
    again = service.rcancel()
    assert again.status_code == 200 and again.json()["state"] == "cancelled"  # idempotent
    envelope = service.rresult().json()
    assert envelope["delivery"] == {"state": "withheld", "reason": "job_cancelled"} and envelope["job"] is None and envelope["receipts"] == []
    refused = service.rrecover()
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "job_not_recoverable" and refused.json()["status"]["state"] == "cancelled"


def test_a_ready_job_is_never_cancelled_and_stays_deliverable(start_relation, world):
    service = start_relation()
    service.rsubmit()
    service.rwait(states={"ready"}, dispatch={"idle"})
    refused = service.rcancel()
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "job_already_terminal"
    assert refused.json()["status"]["state"] == "ready" and refused.json()["status"]["delivery"]["state"] == "available"
    assert service.rrecover().json()["error"]["code"] == "job_not_recoverable"
    still = service.rstatus().json()
    assert still["state"] == "ready" and still["next"] == "fetch_result" and still["dispatch"]["dispatchCount"] == 1
    assert service.rresult().json()["delivery"]["state"] == "available"
    service.close()
    code, direct = inspect_direct(service.workspace, JOB)  # the pipeline's own ready job was never handed its cancel
    assert code == 0 and direct["state"] == "ready" and direct["delivery"]["status"] == "current"


def test_recover_while_a_dispatch_is_pending_is_coalesced_and_adds_no_run(start_relation, world):
    service = start_relation(hold=True)
    service.rsubmit()
    coalesced = service.rrecover()
    assert coalesced.status_code == 200 and coalesced.json()["dispatch"]["state"] == "pending" and coalesced.json()["dispatch"]["dispatchCount"] == 0
    service.workspace.go()
    done = service.rwait(states={"ready"}, dispatch={"idle"})
    assert done["dispatch"]["dispatchCount"] == 1 and done["usage"]["replayCalls"] == world.replay_calls


def test_a_stopped_job_can_be_cancelled_and_is_then_final(start_relation, world):
    service = start_relation(producer=world.empty_producer, verifier=world.empty_verifier)
    service.rsubmit()
    service.rwait(states={"stopped"}, dispatch={"idle"})
    cancelled = service.rcancel()
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled" and cancelled.json()["phase"] == "cancelled"
    refused = service.rrecover()
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "job_not_recoverable"
    assert service.stay(JOB, 2.0)["dispatch"]["dispatchCount"] == 1
