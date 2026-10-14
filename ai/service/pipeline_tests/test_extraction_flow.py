"""S2 extraction jobs over a real uvicorn process and the real installed `zoop-ai-extract`: submit -> status -> result, the strict caller body, ownership,
idempotent reservation, refusal to adopt an operator's job, cancel semantics, no leakage, no network and operator state left untouched."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from extraction_support import (CONTENT_PRIVATE, JOB, PLAIN, PRIVATE_KEYS, SCHEMA, STATUS_KEYS, digest, extraction_processes, inspect_direct, ledger_rows,
                                operator_submit, walk_keys)


def assert_clean(service, *texts: str, delivered: tuple[str, ...] = ()) -> None:
    """Neither a path nor a token is in the given texts or the service log, and no cited sentence is in the log (a delivered result body carries its
    cited quotes by design, and only that)."""
    private = service.workspace.private_strings()
    log = service.logs()
    for text in (*texts, log):
        for value in private:
            assert value not in text, value
    for quote in delivered:
        assert quote not in log
    assert service.workspace.network_attempts() == ""


def without_request_id(response) -> dict:
    body = response.json()
    body["error"].pop("requestId")
    return body


def no_child_ever_ran(workspace) -> bool:
    return not any(workspace.extraction_state.iterdir())


def test_submit_status_and_result_over_the_real_pipeline(start_extraction, world):
    service = start_extraction()
    workspace = service.workspace
    accepted = service.esubmit()
    assert accepted.status_code == 202 and accepted.headers["location"] == f"/internal/v1/extraction-jobs/{JOB}"
    body = accepted.json()
    assert set(body) == STATUS_KEYS and body["schemaVersion"] == SCHEMA and body["state"] == "queued" and body["next"] == "wait"
    assert body["dispatch"]["state"] in {"pending", "in_flight"} and body["delivery"] == {"state": "withheld", "reason": "job_not_ready"}
    assert body["approval"] == {"approvedRequestDigest": workspace.approved_digest(JOB)} and body["acceptedAt"]
    # The pipeline job the service registered is byte-identical to the operator's: same request, same producer fixture bytes.
    assert body["inputDigest"] == world.upstream["inputDigest"]
    assert body["provenance"] == {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"}

    final = service.ewait(states={"ready"}, dispatch={"idle"})
    assert set(final) == STATUS_KEYS and final["next"] == "fetch_result" and final["failure"] is None
    assert final["dispatch"]["dispatchCount"] == 1 and final["dispatch"]["lastOutcome"] == "exited" and final["dispatch"]["lastRuntimeCode"] is None
    assert final["usage"] == {"replayCalls": world.s2_replay_calls, "startedWithoutReceipt": 0, "providerCalls": 0, "paidModelCalls": 0}
    assert final["stages"] == [{"stage": "extract", "state": "complete"}, {"stage": "compare", "state": "complete"}, {"stage": "topic", "state": "complete"}]
    assert final["delivery"] == {"state": "available", "reason": None} and final["inputDigest"] == world.upstream["inputDigest"]
    assert not set(walk_keys(final)) & PRIVATE_KEYS
    assert_clean(service, accepted.text, json.dumps(final, ensure_ascii=False))

    result = service.eresult()
    assert result.status_code == 200
    envelope = result.json()
    assert envelope["schemaVersion"] == SCHEMA and envelope["delivery"] == {"state": "available", "reason": None}
    assert set(envelope) == {"schemaVersion", "status", "delivery", "job", "receipts"} and set(envelope["status"]) == STATUS_KEYS
    assert not set(walk_keys(envelope)) & CONTENT_PRIVATE
    job = envelope["job"]
    assert job["jobId"] == JOB and job["inputDigest"] == world.upstream["inputDigest"] and job["counts"] == world.s2_counts
    # Meaningful candidate data survives the allowlist: the event, its comparison with the frozen snapshot, its disposition and the topic.
    assert len(job["eventCandidates"]) == 1 and len(job["topicCandidates"]) == 1
    event = job["eventCandidates"][0]
    assert event["approved"] is False and event["state"] == "candidate" and event["mention"]["participants"] and event["mention"]["title"]
    assert event["comparisons"][0]["targetEventId"] == "event-1" and event["comparisons"][0]["effective"]["relation"] == "DIFFERENT"
    assert event["disposition"]["status"] == "new-event-candidate" and event["disposition"]["comparedEvents"] == 1
    quotes = [c["quote"] for c in event["citations"]]
    assert quotes and all(c["end"] - c["start"] == len(c["quote"]) and c["offsetUnit"] == "unicode_code_point" for c in event["citations"])
    topic = job["topicCandidates"][0]
    assert topic["approved"] is False and {m["kind"] for m in topic["members"]} == {"event-candidate", "snapshot-event"} and topic["citations"]
    assert len(envelope["receipts"]) == world.s2_replay_calls and all(set(r) == {"stage", "state", "verdict"} for r in envelope["receipts"])
    assert_clean(service, result.text.replace(json.dumps(quotes[0], ensure_ascii=False)[1:-1], ""), delivered=tuple(quotes))
    service.close()
    code, direct = inspect_direct(workspace)  # exactly one pipeline job, executed once, with no model call
    assert code == 0 and direct["state"] == "ready" and direct["usage"]["replayCalls"] == world.s2_replay_calls and direct["usage"]["providerCalls"] == 0


def test_a_topicless_approved_request_runs_without_the_topic_fixture(start_extraction, world):
    service = start_extraction(topic=False, requests=(PLAIN,))
    assert service.esubmit(PLAIN).status_code == 202
    done = service.ewait(PLAIN, states={"ready"}, dispatch={"idle"})
    assert done["usage"]["replayCalls"] == world.s2_replay_calls - 1 and done["stages"][2] == {"stage": "topic", "state": "complete"}
    envelope = service.eresult(PLAIN).json()
    assert envelope["delivery"]["state"] == "available" and envelope["job"]["topicCandidates"] == []
    assert envelope["job"]["counts"]["topicCandidates"] == 0


def test_the_caller_can_send_nothing_but_a_reference_to_an_approved_request(start_extraction, world):
    service = start_extraction(hold=True)
    workspace = service.workspace
    approved = workspace.requests[JOB]
    reference = {"schemaVersion": "zoop-extraction-s2-2", "jobId": JOB, "approvedRequestDigest": workspace.approved_digest()}
    # The real, approved S2 Submit body is NOT accepted from a caller, nor is any piece of it, a path, a registry or a mode.
    spoofs = [approved, {**reference, "snapshot": approved["snapshot"]}, {**reference, "catalogue": approved["catalogue"]},
              {**reference, "incoming": approved["incoming"]}, {**reference, "replay": str(workspace.s2_replay)},
              {**reference, "topicReplay": str(workspace.s2_topic)}, {**reference, "sources": str(world.registry)}, {**reference, "mode": "live"},
              {**reference, "provenance": approved["provenance"]}]
    for body in spoofs:
        refused = service.request("POST", "/internal/v1/extraction-jobs", as_="alpha", body=body, key=JOB)
        assert refused.status_code == 422 and refused.json()["error"]["code"] == "invalid_request" and refused.json()["error"]["field"] == "body"
    assert service.request("POST", "/internal/v1/extraction-jobs", as_="alpha", body={**reference, "jobId": "other"}, key=JOB).status_code == 422
    assert ledger_rows(workspace, "SELECT COUNT(*) FROM extraction_jobs") == [(0,)] and no_child_ever_ran(workspace)   # no spoof left a row or a child
    # A query string or header naming a path is not an input: the same reference is simply accepted, and it ran against the server-owned inputs.
    accepted = service.request("POST", f"/internal/v1/extraction-jobs?sources={world.registry}&replay=/etc/passwd", as_="alpha", body=reference, key=JOB,
                               headers={"X-Sources": str(world.registry)})
    assert accepted.status_code == 202
    workspace.revoke_source(False)    # the registry the SERVICE was configured with decides, whatever a request says
    workspace.go()
    stopped = service.ewait(states={"stopped"}, dispatch={"idle"})
    assert stopped["failure"] and stopped["usage"]["replayCalls"] == 0


def test_requests_that_are_not_approved_or_malformed_reach_neither_ledger_nor_pipeline(start_extraction, world):
    service = start_extraction()
    workspace = service.workspace
    wrong_digest = service.esubmit(JOB, digest_="0" * 64)                       # a digest the operator never approved
    unknown_job = service.request("POST", "/internal/v1/extraction-jobs", as_="alpha", key="never-approved", body={
        "schemaVersion": "zoop-extraction-s2-2", "jobId": "never-approved", "approvedRequestDigest": workspace.approved_digest()})
    other_principal = service.esubmit(JOB, as_="beta")                          # beta is approved for the plain request only
    for refused in (wrong_digest, unknown_job, other_principal):
        assert refused.status_code == 403 and refused.json()["error"]["code"] == "request_not_approved"
    # The same answer whether or not the job exists: nothing can be probed.
    assert without_request_id(wrong_digest) == without_request_id(unknown_job) == without_request_id(other_principal)
    assert service.estatus().status_code == 404
    assert service.request("POST", "/internal/v1/extraction-jobs", as_="alpha", raw=b"{not json", key=JOB,
                           headers={"Content-Type": "application/json"}).status_code == 422
    body = {"schemaVersion": "zoop-extraction-s2-2", "jobId": JOB, "approvedRequestDigest": workspace.approved_digest()}
    assert service.request("POST", "/internal/v1/extraction-jobs", as_="alpha", body=body).status_code == 422                  # no Idempotency-Key
    assert service.request("POST", "/internal/v1/extraction-jobs", as_="alpha", body=body, key="another-job").status_code == 422  # key != jobId
    assert service.request("POST", "/internal/v1/extraction-jobs", as_="alpha", raw=json.dumps(body).encode(), key=JOB,
                           headers={"Content-Type": "text/plain"}).status_code == 415
    for as_ in ("reader", "submitter", "viewer"):
        assert service.esubmit(as_=as_).status_code == 403
    service.stop()
    assert ledger_rows(workspace, "SELECT COUNT(*) FROM extraction_jobs") == [(0,)] and no_child_ever_ran(workspace)


def test_each_principal_owns_exactly_the_jobs_it_submitted(start_extraction):
    service = start_extraction(hold=True)
    assert service.esubmit(PLAIN, as_="alpha").status_code == 202
    for call in (service.estatus, service.eresult, service.ecancel, service.erecover):
        denied = call(PLAIN, as_="beta")
        assert denied.status_code == 404 and denied.json()["error"]["code"] == "job_not_found", call.__name__
    unknown = service.estatus("never-created", as_="beta")
    assert without_request_id(unknown) == without_request_id(service.estatus(PLAIN, as_="beta")) and unknown.status_code == 404
    taken = service.esubmit(PLAIN, as_="beta")     # beta is approved for the same request, but the id is spent
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "job_id_unavailable"
    assert service.estatus(PLAIN, as_="viewer").status_code == 404   # reading is a scope, ownership is a separate rule
    still = service.estatus(PLAIN, as_="alpha").json()
    assert still["state"] == "queued" and still["dispatch"]["dispatchCount"] == 0 and still["delivery"]["reason"] == "job_not_ready"
    for as_ in ("reader", "submitter"):
        for response in (service.esubmit(PLAIN, as_=as_), service.estatus(PLAIN, as_=as_), service.eresult(PLAIN, as_=as_), service.ecancel(PLAIN, as_=as_),
                         service.erecover(PLAIN, as_=as_)):
            assert response.status_code == 403 and response.json()["error"]["code"] == "scope_denied"


def test_an_exact_repeat_keeps_the_frozen_identity_and_a_modified_request_conflicts(start_extraction, world):
    service = start_extraction(hold=True)
    workspace = service.workspace
    first = service.esubmit()
    assert first.status_code == 202
    again = service.esubmit()
    assert again.status_code == 200 and {k: v for k, v in again.json().items() if k != "observedAt"} == {k: v for k, v in first.json().items() if k != "observedAt"}
    conflict = service.esubmit(JOB, digest_=digest(workspace.requests[PLAIN]))  # the same job id naming another request
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"
    assert service.esubmit(JOB, as_="beta").json()["error"]["code"] == "request_not_approved"  # an unapproved principal learns nothing about the id
    # The operator edits the approved request of the same job id: the exact original body is still the same job, and its frozen identity did not move.
    edited = {**workspace.requests[JOB], "promptVersion": "edited-prompt"}
    workspace.write_entries([workspace.entry("alpha", JOB, edited)])
    replay = service.esubmit()
    assert replay.status_code == 200 and replay.json()["inputDigest"] == first.json()["inputDigest"]
    assert replay.json()["approval"] == first.json()["approval"]
    assert service.esubmit(JOB, digest_=digest(edited)).json()["error"]["code"] == "idempotency_conflict"
    service.stop()
    assert ledger_rows(workspace, "SELECT COUNT(*), MIN(approved_digest) FROM extraction_jobs") == [(1, workspace.approved_digest())]


def test_concurrent_identical_submits_register_one_job(start_extraction, world):
    service = start_extraction(hold=True)
    with ThreadPoolExecutor(4) as pool:
        responses = list(pool.map(lambda _: service.esubmit(), range(4)))
    assert sorted(r.status_code for r in responses) == [200, 200, 200, 202]
    service.workspace.go()
    done = service.ewait(states={"ready"}, dispatch={"idle"})
    assert done["dispatch"]["dispatchCount"] == 1 and done["usage"]["replayCalls"] == world.s2_replay_calls


def test_a_job_an_operator_registered_is_never_adopted_and_stays_untouched(start_extraction, world):
    service = start_extraction(hold=True)
    workspace = service.workspace
    code, registered = operator_submit(workspace, workspace.requests[PLAIN])
    assert code == 0 and registered["state"] == "queued" and registered["calls"] == []
    refused = service.esubmit(PLAIN)                                       # alpha is approved for exactly this request
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "job_id_unavailable"
    assert service.estatus(PLAIN).status_code == 404 and service.eresult(PLAIN).status_code == 404   # never readable through the service
    service.stop()
    assert ledger_rows(workspace, "SELECT COUNT(*) FROM extraction_jobs") == [(0,)]                    # the reservation was released
    code, direct = inspect_direct(workspace, PLAIN)
    assert code == 0 and direct["state"] == "queued" and direct["inputDigest"] == registered["inputDigest"] and direct["calls"] == []
    assert not extraction_processes(workspace)


def test_cancel_is_idempotent_final_and_refused_for_a_ready_job(start_extraction, world):
    service = start_extraction(hold=True)
    assert service.esubmit().status_code == 202
    cancelled = service.ecancel()
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert (body["state"], body["next"], body["dispatch"]["state"], body["dispatch"]["lastOutcome"], body["dispatch"]["dispatchCount"]) == (
        "cancelled", "none", "idle", "cancelled", 0)
    assert body["delivery"] == {"state": "withheld", "reason": "job_cancelled"} and body["usage"]["replayCalls"] == 0
    service.workspace.go()  # a dispatcher that is free to run still has nothing to run
    quiet = service.estay(JOB, 3.0)
    assert (quiet["state"], quiet["dispatch"]["dispatchCount"], quiet["usage"]["replayCalls"]) == ("cancelled", 0, 0)
    assert service.ecancel().json()["state"] == "cancelled"
    envelope = service.eresult().json()
    assert envelope["delivery"] == {"state": "withheld", "reason": "job_cancelled"} and envelope["job"] is None and envelope["receipts"] == []
    refused = service.erecover()
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "job_not_recoverable" and refused.json()["status"]["state"] == "cancelled"
    # A ready job is not cancelled: the pipeline leaves it ready and the service reports that instead of pretending.
    assert service.esubmit(PLAIN).status_code == 202
    service.ewait(PLAIN, states={"ready"}, dispatch={"idle"})
    ready = service.ecancel(PLAIN)
    assert ready.status_code == 409 and ready.json()["error"]["code"] == "job_already_terminal" and ready.json()["status"]["state"] == "ready"
    assert ready.json()["status"]["delivery"] == {"state": "available", "reason": None}
    assert service.erecover(PLAIN).json()["error"]["code"] == "job_not_recoverable"
    assert service.eresult(PLAIN).json()["delivery"]["state"] == "available"
    service.close()
    code, direct = inspect_direct(service.workspace, PLAIN)
    assert code == 0 and direct["state"] == "ready" and direct["delivery"]["status"] == "current"


def test_recover_while_a_dispatch_is_pending_is_coalesced_and_adds_no_run(start_extraction, world):
    service = start_extraction(hold=True)
    service.esubmit()
    coalesced = service.erecover()
    assert coalesced.status_code == 200 and coalesced.json()["dispatch"]["state"] == "pending" and coalesced.json()["dispatch"]["dispatchCount"] == 0
    service.workspace.go()
    done = service.ewait(states={"ready"}, dispatch={"idle"})
    assert done["dispatch"]["dispatchCount"] == 1 and done["usage"]["replayCalls"] == world.s2_replay_calls


def test_an_error_path_never_reaches_a_network_and_never_leaks(start_extraction, world):
    service = start_extraction()
    service.workspace.revoke_source(False)      # the pipeline itself refuses the approved request at registration
    refused = service.esubmit()
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "request_unavailable" and refused.json()["error"]["runtimeCode"]
    assert_clean(service, refused.text)
    service.stop()
    assert ledger_rows(service.workspace, "SELECT COUNT(*) FROM extraction_jobs") == [(0,)]   # nothing was registered, so the claim was released
    assert not extraction_processes(service.workspace)


def test_an_unapproved_principal_gets_the_same_denial_before_and_after_the_job_exists(start_extraction, world):
    """beta is approved for the plain request only. Its submission of JOB must not reveal whether alpha has reserved or accepted that id."""
    service = start_extraction(hold=True)
    before = service.esubmit(JOB, as_="beta")
    assert before.status_code == 403 and before.json()["error"]["code"] == "request_not_approved"
    assert service.esubmit(JOB).status_code == 202                        # alpha creates the job
    after = service.esubmit(JOB, as_="beta")
    assert after.status_code == 403 and without_request_id(after) == without_request_id(before)
    wrong = service.esubmit(JOB, as_="beta", digest_="0" * 64)           # a digest beta was never approved for, same answer
    assert wrong.status_code == 403 and without_request_id(wrong) == without_request_id(before)
    # An approved principal of the same id still gets the ownership conflict, and the owner keeps idempotent replay after its approval is gone.
    assert service.esubmit(PLAIN).status_code == 202
    assert service.esubmit(PLAIN, as_="beta").json()["error"]["code"] == "job_id_unavailable"
    service.workspace.write_entries([])
    assert service.esubmit(JOB).status_code == 200
