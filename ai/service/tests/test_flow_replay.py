"""All four S1 kinds end to end over real loopback HTTP, the real installed worker CLI and authored synthetic replay (0 provider calls)."""
from __future__ import annotations

import copy

from conftest import outlook_verify_replay
from support import (cli, combined_replay, document_jobs, document_replay, outlook_job, outlook_replay, reference,
                     semantic_job_and_entry)


def test_four_document_jobs_flow_in_fixture_order(start):
    service = start(replay=document_replay())
    jobs = document_jobs()
    first = service.submit(jobs[0])
    assert first.status_code == 202
    assert first.headers["Location"] == f"/internal/v1/analysis-jobs/{jobs[0]['jobId']}"
    queued = first.json()
    assert queued["state"] == "queued" and queued["dispatch"]["state"] in {"pending", "in_flight"} and queued["next"] == "wait"
    for job in jobs[1:]:
        assert service.submit(job).status_code == 202
    statuses = [service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"}) for job in jobs]
    assert [s["kind"] for s in statuses] == ["document-summary", "document-sentiment"] * 2
    assert all(s["next"] == "fetch_result" and s["phase"] == "artifact.persisted" for s in statuses)
    assert sum(s["usage"]["replayCalls"] for s in statuses) == 8
    assert sum(s["usage"]["providerAttempts"] for s in statuses) == 0
    assert all(s["unreceiptedAttempts"] == 0 and s["dispatch"]["lastOutcome"] == "exited" for s in statuses)
    for status in statuses:
        # A status never carries content or receipts.
        assert not {"input", "artifacts", "grant", "calls"} & set(status)


def test_result_equals_direct_runtime_get_and_is_available(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    service.submit(job)
    service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})
    result = service.result(job["jobId"])
    assert result.status_code == 200
    body = result.json()
    code, direct = cli(service.workspace, "get", reference(job["jobId"]))
    assert code == 0
    assert body["delivery"] == {"state": "available", "reason": None}
    # The allowlisted DTO must lose nothing the existing BFF importer needs: it equals the runtime's own `get`.
    assert body["job"] == direct
    assert body["receipts"] == direct["calls"]
    assert body["status"]["jobId"] == job["jobId"] and body["status"]["state"] == "ready"
    assert {a["kind"] for a in body["job"]["artifacts"]} == {"document-summary", "semantic-verification"}


def test_outlook_and_empty_round_and_standalone_verification(start):
    service = start(replay=outlook_verify_replay())
    outlook = outlook_job()
    assert service.submit(outlook).status_code == 202
    ready = service.wait_state(outlook["jobId"], {"ready"}, dispatch={"idle"})
    assert ready["kind"] == "briefing-outlook" and ready["usage"]["replayCalls"] == 1 and ready["phase"] == "artifact.persisted"
    empty = copy.deepcopy(outlook)
    empty["jobId"] = "outlook-empty-round"
    empty["input"]["issues"] = []
    assert service.submit(empty).status_code == 202
    done = service.wait_state(empty["jobId"], {"ready"}, dispatch={"idle"})
    assert done["phase"] == "empty_round.no_call" and done["usage"]["replayCalls"] == 0 and done["artifactIds"] == []
    verify, _ = semantic_job_and_entry()
    assert service.submit(verify).status_code == 202
    checked = service.wait_state(verify["jobId"], {"ready"}, dispatch={"idle"})
    assert checked["kind"] == "semantic-verification" and checked["usage"]["replayCalls"] == 1
    # `get` and the result route agree with the runtime for the importer's outlook path as well.
    code, direct = cli(service.workspace, "get", reference(outlook["jobId"]))
    assert service.result(outlook["jobId"]).json()["job"] == direct


def test_cache_hit_is_reported_as_it_is_and_costs_nothing(start):
    service = start(replay=document_replay())
    first = document_jobs()[0]
    service.submit(first)
    service.wait_state(first["jobId"], {"ready"}, dispatch={"idle"})
    twin = copy.deepcopy(first)
    twin["jobId"] = "same-input-second-job"
    assert service.submit(twin).status_code == 202
    hit = service.wait_state(twin["jobId"], {"ready"}, dispatch={"idle"})
    assert hit["phase"] == "artifact.cache_hit"
    assert hit["usage"]["replayCalls"] == 0 and hit["usage"]["providerAttempts"] == 0 and hit["unreceiptedAttempts"] == 0
    assert hit["artifactIds"] == service.status(first["jobId"]).json()["artifactIds"]


def test_status_is_read_from_the_runtime_not_remembered_from_post(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    accepted = service.submit(job).json()
    assert accepted["state"] == "queued"
    final = service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})
    assert final["state"] == "ready" and final["acceptedAt"] == accepted["acceptedAt"]
    # Same jobId, same body: the idempotent replay shows the actual current state, never the stale queued answer.
    again = service.submit(job)
    assert again.status_code == 200 and again.json()["state"] == "ready" and again.json()["inputDigest"] == accepted["inputDigest"]


def test_runtime_job_failure_is_job_data_not_an_http_error(start):
    replay = document_replay()
    replay["responses"][0]["response"]["claims"][0]["evidenceIds"] = ["missing"]  # an authored defect: never reaches verification
    service = start(replay=replay)
    job = document_jobs()[0]
    service.submit(job)
    failed = service.wait_state(job["jobId"], {"failed"}, dispatch={"idle"})
    assert failed["failure"]["code"] and failed["next"] == "none" and failed["resumeMode"] == "none"
    assert service.result(job["jobId"]).status_code == 200


def test_outlook_fixture_alone_with_its_own_service(start):
    service = start(replay=outlook_replay(), grants=None)
    job = outlook_job()
    assert service.submit(job).status_code == 202
    assert service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})["usage"]["replayCalls"] == 1


def test_all_four_kinds_in_one_service_in_submission_order(start):
    service = start(replay=combined_replay())
    verify, _ = semantic_job_and_entry()
    jobs = [*document_jobs(), outlook_job(), verify]
    assert [service.submit(job).status_code for job in jobs] == [202] * 6
    statuses = [service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"}) for job in jobs]
    assert {s["kind"] for s in statuses} == {"document-summary", "document-sentiment", "semantic-verification", "briefing-outlook"}
    assert sum(s["usage"]["replayCalls"] for s in statuses) == 10 and sum(s["usage"]["providerAttempts"] for s in statuses) == 0
