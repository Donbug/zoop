"""When may content leave the S2 service, and what may start a pipeline child: the preapproval, the source registry, and the pinned fixtures, re-read on
every content-bearing use. Rotations never rebind a job id; an approval only narrows what the pipeline already allows."""
from __future__ import annotations

import json

import httpx

from extraction_support import CONTENT_PRIVATE, JOB, PLAIN, digest, extraction_processes, file_hash, inspect_direct, ledger_rows, walk_keys


def quotes_of(envelope: dict) -> list[str]:
    return [c["quote"] for e in envelope["job"]["eventCandidates"] for c in e["citations"]]


def withheld(service, reason: str, job_id: str = JOB) -> dict:
    """The result envelope of a ready job whose delivery is withheld for `reason`: no content, only accounting receipts."""
    response = service.eresult(job_id)
    assert response.status_code == 200
    envelope = response.json()
    assert envelope["delivery"] == {"state": "withheld", "reason": reason} and envelope["job"] is None and envelope["status"]["delivery"] == envelope["delivery"]
    assert envelope["status"]["state"] == "ready" and envelope["receipts"]
    for quote in service.workspace.delivered_quotes:
        assert quote not in response.text and quote not in service.logs()
    return envelope


def ready_service(start_extraction, **kwargs):
    service = start_extraction(**kwargs)
    assert service.esubmit().status_code == 202
    service.ewait(states={"ready"}, dispatch={"idle"})
    available = service.eresult()
    assert available.json()["delivery"]["state"] == "available"
    service.workspace.delivered_quotes = quotes_of(available.json())
    assert service.workspace.delivered_quotes
    return service


def test_content_follows_the_current_approval_and_the_current_source_grant(start_extraction, world):
    service = ready_service(start_extraction)
    workspace = service.workspace

    # 1. The approval entry is removed (or listed for another principal only): the job stays ready, the content stops, a recovery is refused.
    workspace.write_entries([workspace.entry("beta", PLAIN)])
    status = service.estatus().json()
    assert status["state"] == "ready" and status["delivery"] == {"state": "withheld", "reason": "approval_revoked"} and status["next"] == "fetch_result"
    withheld(service, "approval_revoked")
    refused = service.erecover()
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "request_not_approved"
    workspace.refresh_approvals()
    assert service.eresult().json()["delivery"]["state"] == "available"

    # 2. The approved request of the job id is edited (another digest): the reserved job is not the approved one any more.
    workspace.write_entries([workspace.entry("alpha", JOB, {**workspace.requests[JOB], "promptVersion": "edited"})])
    withheld(service, "approval_revoked")
    workspace.refresh_approvals()

    # 3. The entry's own pins moved (the operator re-pinned the producer fixture): the job's frozen pins no longer match.
    workspace.write_entries([workspace.entry("alpha", JOB, replay="f" * 64)])
    assert service.estatus().json()["delivery"] == {"state": "withheld", "reason": "approval_changed"}
    withheld(service, "approval_changed")
    changed = service.erecover()
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "approval_changed"
    workspace.refresh_approvals()

    # 4. The operator revokes the source grant: the pipeline withholds on its own current check, whatever the approval says.
    workspace.revoke_source(False)
    assert service.estatus().json()["delivery"] == {"state": "withheld", "reason": "source_unauthorized"}
    envelope = withheld(service, "source_unauthorized")
    assert len(envelope["receipts"]) == world.s2_replay_calls  # accounting metadata stays available
    workspace.revoke_source(True)
    assert service.eresult().json()["delivery"]["state"] == "available"

    # 5. An approvals file the service cannot read fails closed with no content and no detail.
    saved = workspace.approvals.read_bytes()
    workspace.approvals.write_text("{broken")
    for response in (service.eresult(), service.estatus(), service.erecover()):
        assert response.status_code == 503 and response.json()["error"]["code"] == "service_configuration_invalid" and response.json()["error"]["retryable"] is True
        assert str(workspace.approvals) not in response.text and all(quote not in response.text for quote in workspace.delivered_quotes)
    workspace.approvals.write_bytes(saved)
    assert json.loads(service.eresult().text)["delivery"]["state"] == "available"
    assert workspace.network_attempts() == ""


def test_a_request_cannot_choose_the_registry_the_command_or_the_fixtures(start_extraction, world):
    service = ready_service(start_extraction)
    service.workspace.revoke_source(False)
    for response in (service.request("GET", f"/internal/v1/extraction-jobs/{JOB}/result?sources={world.registry}&replay=/etc/passwd", as_="alpha"),
                     service.request("GET", f"/internal/v1/extraction-jobs/{JOB}/result", as_="alpha", headers={"X-Sources": str(world.registry)})):
        assert response.json()["delivery"]["state"] == "withheld"


def test_a_rotated_fixture_withholds_and_a_restored_one_does_not_resurrect_a_foreign_receipt(start_extraction, world):
    service = ready_service(start_extraction)
    workspace = service.workspace
    topic, producer = workspace.s2_topic.read_bytes(), workspace.s2_replay.read_bytes()

    workspace.rotate_topic()
    assert service.estatus().json()["delivery"] == {"state": "withheld", "reason": "fixture_changed"}
    withheld(service, "fixture_changed")
    workspace.s2_topic.write_bytes(topic)
    assert service.eresult().json()["delivery"]["state"] == "available"      # restored to the pinned bytes: the same job is deliverable again

    workspace.rotate_producer()
    withheld(service, "fixture_changed")
    workspace.s2_replay.write_bytes(producer)
    assert service.eresult().json()["delivery"]["state"] == "available"

    workspace.s2_topic.unlink()                                               # a missing fixture file fails safely, it does not open
    assert service.estatus().json()["delivery"] == {"state": "withheld", "reason": "fixture_unavailable"}
    withheld(service, "fixture_unavailable")
    workspace.s2_topic.write_bytes(topic)

    # Rotating the approval's pins together with the fixture does NOT rebind the job: its frozen pins are what it was reserved under.
    workspace.rotate_topic()
    workspace.refresh_approvals()
    assert service.estatus().json()["delivery"] == {"state": "withheld", "reason": "approval_changed"}
    withheld(service, "approval_changed")
    same = service.esubmit()                                                   # the exact original request is still the same job, the same input digest
    assert same.status_code == 200 and same.json()["inputDigest"] == world.upstream["inputDigest"] and same.json()["delivery"]["reason"] == "approval_changed"
    assert service.erecover().status_code == 409
    service.stop()
    row = ledger_rows(workspace, "SELECT topic_digest, producer_digest, input_digest FROM extraction_jobs")
    assert row == [(digest_of(topic), digest_of(producer), world.upstream["inputDigest"])]
    assert workspace.network_attempts() == ""


def digest_of(raw: bytes) -> str:
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def test_a_rotation_between_the_check_and_the_childs_own_read_fails_closed_after_the_fact(start_extraction, world):
    """The fixture files are server configuration the child reads itself, so a check cannot be atomic with that read. The window is closed afterwards:
    the receipts record the hash of the bytes that answered, and the service refuses a job whose receipts are not the pinned bytes."""
    service = start_extraction(hold=True)
    workspace = service.workspace
    original = workspace.s2_topic.read_bytes()
    workspace.write_wrapper(f"open({str(workspace.s2_topic)!r}, 'ab').write(b'\\n')", "resume")
    assert service.esubmit().status_code == 202
    workspace.arm()          # the NEXT resume child rotates the topic fixture just before the real CLI reads it
    workspace.go()
    seen = service.ewait(dispatch={"idle"})
    assert seen["dispatch"]["lastOutcome"] == "runtime_error" and seen["dispatch"]["lastRuntimeCode"] == "fixture_changed" and seen["next"] != "wait"
    assert seen["delivery"]["state"] == "withheld"
    workspace.s2_topic.write_bytes(original)         # even the pinned bytes back on disk do not make the foreign receipt the pinned one
    withheld_envelope = service.eresult().json()
    assert withheld_envelope["delivery"] == {"state": "withheld", "reason": "fixture_changed"} and withheld_envelope["job"] is None


def test_a_swap_of_the_producer_fixture_during_registration_is_a_binding_mismatch_never_an_accepted_job(start_extraction, world):
    service = start_extraction(requests=(PLAIN,), topic=False, wrapper=None)
    workspace = service.workspace
    pinned = file_hash(workspace.s2_replay)
    workspace.write_wrapper(f"open({str(workspace.s2_replay)!r}, 'ab').write(b'\\n')", "submit")
    workspace.arm()
    service.close()
    service = start_extraction(workspace=workspace)
    refused = service.esubmit(PLAIN)
    assert refused.status_code == 500 and refused.json()["error"]["code"] == "runtime_binding_mismatch"
    assert service.estatus(PLAIN).status_code == 404                   # never accepted: the id is reserved for its owner, nothing is dispatched
    service.stop()
    assert ledger_rows(workspace, "SELECT state FROM extraction_jobs") == [("reserved",)] and ledger_rows(workspace, "SELECT COUNT(*) FROM extraction_dispatch") == [(0,)]
    code, direct = inspect_direct(workspace, PLAIN)
    assert code == 0 and direct["inputDigest"] != digest({"request": workspace.requests[PLAIN], "replayFixtureHash": pinned})  # a job over foreign bytes
    assert direct["calls"] == []


def test_a_new_submission_with_rotated_fixtures_is_refused_before_any_ledger_row_or_child(start_extraction, world):
    service = start_extraction()
    workspace = service.workspace
    workspace.rotate_topic()                           # the approval still pins the old topic bytes
    refused = service.esubmit()
    assert refused.status_code == 503 and refused.json()["error"]["code"] == "service_configuration_invalid" and refused.json()["error"]["retryable"] is True
    assert '"problem":"fixture_changed"' in service.logs().replace(" ", "")
    workspace.s2_topic.unlink()
    assert service.esubmit().status_code == 503 and '"problem":"fixture_unavailable"' in service.logs().replace(" ", "")
    workspace.approvals.write_text("{broken")
    assert service.esubmit().status_code == 503
    service.stop()
    assert ledger_rows(workspace, "SELECT COUNT(*) FROM extraction_jobs") == [(0,)] and not any(workspace.extraction_state.iterdir())


def test_no_child_starts_while_the_approval_or_the_fixtures_are_not_the_reserved_ones(start_extraction, world):
    service = start_extraction(hold=True)
    workspace = service.workspace
    topic = workspace.s2_topic.read_bytes()
    assert service.esubmit().status_code == 202
    workspace.rotate_topic()
    workspace.go()
    first = service.ewait(dispatch={"idle"})
    assert (first["state"], first["dispatch"]["lastOutcome"], first["dispatch"]["lastRuntimeCode"], first["dispatch"]["dispatchCount"]) == (
        "queued", "runtime_error", "fixture_changed", 1)
    assert first["usage"]["replayCalls"] == 0 and first["next"] == "recover"
    assert service.estay(JOB, 2.0)["dispatch"]["dispatchCount"] == 1          # nothing continues it by itself
    assert service.erecover().status_code == 409 and service.erecover().json()["error"]["code"] == "fixture_changed"   # the explicit path says so too
    workspace.s2_topic.unlink()
    assert service.erecover().json()["error"]["code"] == "service_configuration_invalid"
    workspace.s2_topic.write_bytes(topic)
    workspace.write_entries([])                                                 # no approval at all
    assert service.erecover().status_code == 403
    workspace.refresh_approvals()
    assert service.erecover().status_code == 202
    done = service.ewait(states={"ready"}, dispatch={"idle"})
    assert done["dispatch"]["dispatchCount"] == 2 and done["usage"]["replayCalls"] == world.s2_replay_calls
    assert service.eresult().json()["delivery"]["state"] == "available"


def test_a_dispatch_refused_for_authority_never_started_a_child(start_extraction, world):
    service = start_extraction(hold=True)
    workspace = service.workspace
    assert service.esubmit().status_code == 202
    workspace.write_entries([])
    workspace.go()
    refused = service.ewait(dispatch={"idle"})
    assert (refused["dispatch"]["lastOutcome"], refused["dispatch"]["lastRuntimeCode"], refused["usage"]["replayCalls"]) == ("runtime_error", "approval_revoked", 0)
    service.stop()
    code, direct = inspect_direct(workspace)       # the pipeline job is exactly as registered: queued, no call
    assert code == 0 and direct["state"] == "queued" and direct["calls"] == [] and not extraction_processes(workspace)


def test_a_reserved_identity_is_never_rebound_to_a_rotated_approval(start_extraction, world):
    crashing = start_extraction(requests=(PLAIN,), topic=False, launcher_env={"ZOOP_TEST_EXTRACTION_CRASH_AT": "after_reserve"})
    try:
        crashing.esubmit(PLAIN)
    except httpx.TransportError:
        pass
    crashing.exited()
    workspace = crashing.workspace
    original = workspace.s2_replay.read_bytes()
    workspace.rotate_producer()
    workspace.refresh_approvals()                   # an operator rotated fixture AND approval together while the reservation was pending
    service = start_extraction(workspace=workspace)
    refused = service.esubmit(PLAIN)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "approval_changed"
    assert ledger_rows(workspace, "SELECT state, producer_digest FROM extraction_jobs") == [("reserved", digest_of(original))]   # still the first pins
    workspace.s2_replay.write_bytes(original)       # restored: the owner's identical retry completes the reservation
    workspace.refresh_approvals()
    assert service.esubmit(PLAIN).status_code == 202
    assert service.ewait(PLAIN, states={"ready"}, dispatch={"idle"})["dispatch"]["dispatchCount"] == 1
    assert not set(walk_keys(service.eresult(PLAIN).json())) & CONTENT_PRIVATE
