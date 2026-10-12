"""Cancellation and cost truth: the fence blocks late artifacts and the verify stage, receipts stay, nothing hidden is sent."""
from __future__ import annotations

import copy

from support import cli, document_jobs, document_replay, live_job, reference


def test_cancel_while_the_provider_call_is_held_keeps_the_receipt_and_never_sends_verify(start, provider, live):
    workspace, env = live()
    service = start(workspace=workspace, env=env)
    gate = provider.gate("document_summary")
    job = live_job()
    service.submit(job)
    assert gate.entered.wait(30)
    cancelled = service.cancel(job["jobId"])
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled" and cancelled.json()["next"] == "wait"
    assert cancelled.json()["dispatch"]["state"] == "in_flight"  # the child is deliberately not killed
    assert service.cancel(job["jobId"]).status_code == 200  # idempotent
    gate.release()
    final = service.wait_state(job["jobId"], {"cancelled"}, dispatch={"idle"}, timeout=60)
    assert final["artifactIds"] == [] and final["next"] == "none" and final["resumeMode"] == "none"
    assert final["usage"]["providerAttempts"] == 1 and final["unreceiptedAttempts"] == 0
    assert final["usage"]["inputTokens"] == 11 and final["usage"]["outputTokens"] == 7  # the late receipt's usage is recorded
    assert provider.requests == ["document_summary"]  # verify was never sent
    receipts = service.result(job["jobId"]).json()["receipts"]
    assert [(r["stage"], r["state"]) for r in receipts] == [("document-summary", "received")]
    assert service.cancel(job["jobId"]).status_code == 200
    assert service.recover(job["jobId"]).status_code == 409


def test_cancelling_a_queued_job_ends_its_dispatch_and_it_is_never_sent(start, provider, live):
    workspace, env = live()
    service = start(workspace=workspace, env=env)
    gate = provider.gate("document_summary")
    first = live_job(job_id="live-first")
    second = live_job(document_jobs()[1], job_id="live-second")
    service.submit(first)
    assert gate.entered.wait(30)  # the single dispatcher is busy with the first job
    queued = service.submit(second)
    assert queued.status_code == 202 and queued.json()["dispatch"]["state"] == "pending"
    cancelled = service.cancel(second["jobId"])
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
    assert cancelled.json()["dispatch"]["state"] == "idle" and cancelled.json()["dispatch"]["lastOutcome"] == "cancelled"
    gate.release()
    service.wait_state(first["jobId"], {"ready"}, dispatch={"idle"}, timeout=60)
    after = service.status(second["jobId"]).json()
    assert after["state"] == "cancelled" and after["usage"]["providerAttempts"] == 0 and after["dispatch"]["dispatchCount"] == 0
    assert provider.requests == ["document_summary", "semantic_verification"]  # only the first job ever reached the provider


def test_cancel_of_a_terminal_job_is_a_409_with_its_status(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    service.submit(job)
    service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})
    refused = service.cancel(job["jobId"])
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "job_already_terminal"
    assert refused.json()["status"]["state"] == "ready" and refused.json()["status"]["jobId"] == job["jobId"]
    code, direct = cli(service.workspace, "get", reference(job["jobId"]))
    assert direct["state"] == "ready"  # the runtime job was not disturbed
    broken = document_replay()
    broken["responses"][2]["response"]["claims"][0]["evidenceIds"] = ["missing"]
    failing = start(replay=copy.deepcopy(broken))
    first, second = document_jobs()[:2]
    failing.submit(first)
    failing.wait_state(first["jobId"], {"ready"}, dispatch={"idle"})
    failing.submit(second)
    failing.wait_state(second["jobId"], {"failed"}, dispatch={"idle"})
    refused = failing.cancel(second["jobId"])
    assert refused.status_code == 409 and refused.json()["status"]["state"] == "failed"
