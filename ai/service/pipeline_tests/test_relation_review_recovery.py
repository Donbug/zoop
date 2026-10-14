"""Crashes, ambiguity and explicit recovery of relation reviews and their revalidations, over the real installed pipeline.

The invariants under test: a review is appended at most once, however a crash falls around the pipeline's append and the service's record of it
(the operation marker in the append-only chain is the proof, never a guess); an event that is not exactly the operation's is never adopted; a
revalidation is dispatched once and everything ambiguous after that waits for an explicit recover, which reads the chain before it does anything;
a verification call that was received is finished from its saved receipt without any new call, and one that was never answered is never resent.
"""
from __future__ import annotations

import json
from collections import Counter

import httpx
import pytest

from relation_support import (CRASH_AFTER_FIRST_RECEIPT, CRASH_UNKNOWN, JOB, MARKER, direct_relation, ledger_rows, pipeline_cli, review_into_an_orphan)

KEY = "decision-allow-0001"


def crash_at(point: str) -> dict[str, str]:
    return {"ZOOP_TEST_RELATION_CRASH_AT": point}


def ready(service) -> dict:
    assert service.rsubmit().status_code == 202
    return service.rwait(states={"ready"}, dispatch={"idle"})


def stages(service) -> Counter:
    return Counter(receipt["stage"] for receipt in service.rresult().json()["receipts"])


def review_into_a_crash(service, key: str, relation: str) -> None:
    try:
        service.rreview(key, relation)
    except httpx.TransportError:
        pass  # the service may die before the response is written


def kinds(workspace, relation: str) -> list[str]:
    return [event["kind"] for event in direct_relation(workspace, relation)["history"]]


@pytest.mark.parametrize("point,landed,recorded", [
    ("after_review_reserve", False, False),   # the reservation committed; the pipeline was never asked to append
    ("after_review_child", True, False),       # the pipeline appended the event; the service died before it recorded anything
    ("after_review_applied", True, True),      # the service recorded the event and queued its revalidation; the response was lost
])
def test_a_crash_around_a_review_never_loses_or_duplicates_the_event(start_relation, world, point, landed, recorded):
    crashing = start_relation(launcher_env=crash_at(point))
    status = ready(crashing)
    review_into_a_crash(crashing, KEY, world.held)
    crashing.exited()
    workspace = crashing.workspace
    chain = direct_relation(workspace, world.held)["history"]  # the service is gone: the chain as the pipeline holds it
    assert [event["kind"] for event in chain] == (["verdict", "review"] if landed else ["verdict"])
    if landed:
        assert (chain[1]["reviewer"], chain[1]["note"], chain[1]["decision"], chain[1]["expectedRevision"]) == ("alpha", MARKER + KEY, "allow", 1)

    service = start_relation(workspace=workspace)
    found = service.roperation(KEY)
    assert found.status_code == 200  # a lookup finds the operation after the crash, whatever was or was not proven
    body = found.json()
    assert (body["operationId"], body["jobId"], body["relationCandidateId"], body["decision"], body["reviewer"]) == (KEY, JOB, world.held, "allow", "alpha")
    assert (body["expectedSourceVersion"], body["expectedSourceRevision"]) == (status["inputDigest"], "1")
    if recorded:
        assert body["review"]["state"] == "applied" and body["review"]["resultingSourceRevision"] == "2"
    else:
        assert body["review"] == {"state": "unconfirmed", "resultingSourceRevision": None, "recordedAt": None}
        assert body["revalidation"]["state"] == "not_requested" and body["next"] == "retry_review"
        assert service.stay(JOB, 2.0)["dispatch"]["dispatchCount"] == 1 and kinds(workspace, world.held) == (["verdict", "review"] if landed else ["verdict"])
        if landed:
            # Another key at the same revision cannot take the unproven operation's place or adopt its event: the relation has moved on.
            other = service.rreview("other-key", world.held)
            assert other.status_code == 409 and other.json()["error"]["code"] == "source_revision_conflict"
            assert service.roperation("other-key").status_code == 404
        # The same request again reconciles: the chain is read first, and an event that is already there is adopted, never appended twice.
        assert service.rreview(KEY, world.held, revision=2).status_code == 409  # another body under the same key is a conflict, never a second event
        retried = service.rreview(KEY, world.held)
        assert retried.status_code == 202 and retried.json()["review"] == {
            "state": "applied", "resultingSourceRevision": "2", "recordedAt": retried.json()["review"]["recordedAt"]}
    done = service.rowait(KEY, {"verified"})
    assert done["revalidation"]["dispatchCount"] == 1 and done["revalidation"]["verdict"] == "eligible"  # one revalidation, however it fell
    service.close()
    chain = direct_relation(workspace, world.held)["history"]
    assert [event["kind"] for event in chain] == ["verdict", "review", "verdict"]  # exactly one review event and one verdict
    assert [event["note"] for event in chain if event["kind"] == "review"] == [MARKER + KEY]
    assert ledger_rows(workspace, "SELECT COUNT(*), MAX(review_attempts) FROM relation_operations") == [(1, 1 if recorded else 2)]


def test_an_event_that_is_not_the_operations_own_is_never_adopted(start_relation, world):
    crashing = start_relation(launcher_env=crash_at("after_review_reserve"))
    ready(crashing)
    review_into_a_crash(crashing, KEY, world.held)
    crashing.exited()
    workspace = crashing.workspace
    # While the service is down an operator reviews the same relation directly: the chain moves without the service's marker.
    code, reviewed = pipeline_cli(workspace, "review", {
        "schemaVersion": "zoop-relation-s3", "jobId": JOB, "relationCandidateId": world.held, "expectedRevision": 1, "decision": "allow",
        "reviewer": "operator", "note": "operator note"})
    assert code == 0 and reviewed["state"] == "ready"
    service = start_relation(workspace=workspace)
    assert service.roperation(KEY).json()["review"]["state"] == "unconfirmed"
    retried = service.rreview(KEY, world.held)
    assert retried.status_code == 409 and retried.json()["error"]["code"] == "source_revision_conflict"
    assert service.roperation(KEY).status_code == 404  # the reservation was released: the event can never appear at that revision
    assert ledger_rows(workspace, "SELECT COUNT(*) FROM relation_operations") == [(0,)]
    chain = direct_relation(workspace, world.held)["history"]
    assert [(event["kind"], event["reviewer"]) for event in chain if event["kind"] == "review"] == [("review", "operator")]  # only the operator's
    assert service.stay(JOB, 2.0)["dispatch"]["dispatchCount"] == 1  # and the service did not revalidate someone else's allow


def test_a_child_that_dies_after_saving_the_verifier_receipt_is_finished_from_the_receipt_and_calls_nothing_again(start_relation, world):
    service = start_relation(wrapper=CRASH_AFTER_FIRST_RECEIPT)
    ready(service)
    base = stages(service)
    service.workspace.arm()  # the next resume/revalidate child saves its first receipt and dies
    assert service.rreview(KEY, world.held).status_code == 202
    interrupted = service.rowait(KEY, {"interrupted"})
    assert (interrupted["revalidation"]["lastOutcome"], interrupted["revalidation"]["dispatchCount"], interrupted["next"]) == ("transport_unknown", 1, "recover")
    job = service.rstatus().json()
    assert job["usage"]["startedWithoutReceipt"] == 0 and job["usage"]["replayCalls"] == world.replay_calls + 1  # the verifier receipt is stored
    # No fixture can answer the verifier any more: finishing the revalidation must come from the saved receipt alone.
    service.workspace.use_fixtures(world.producer, world.empty_verifier)
    quiet = service.stay(JOB, 3.0)
    assert quiet["usage"] == job["usage"] and service.roperation(KEY).json()["revalidation"]["dispatchCount"] == 1  # nothing continues on its own
    assert service.roprecover(KEY).status_code == 202  # explicit
    done = service.rowait(KEY, {"verified"})
    assert done["revalidation"]["verdict"] == "eligible" and done["revalidation"]["resultingSourceRevision"] == "3" and done["revalidation"]["dispatchCount"] == 2
    after = stages(service)
    assert after["verify-relation"] == base["verify-relation"] + 1 and after["relation"] == base["relation"] == 1  # one verifier call in total
    final = service.rwait(states={"ready"}, dispatch={"idle"})
    assert final["usage"]["startedWithoutReceipt"] == 0 and final["usage"]["providerCalls"] == final["usage"]["modelCalls"] == 0
    assert service.result_relation(world.held)["sourceRevision"] == "3"
    assert service.roprecover(KEY).status_code == 200  # a settled operation has nothing left to recover
    assert service.roperation(KEY).json()["revalidation"]["dispatchCount"] == 2


def test_an_unanswered_verification_call_is_never_resent_and_stays_a_reconcile(start_relation, world):
    service = start_relation(wrapper=CRASH_UNKNOWN)
    ready(service)
    base = stages(service)
    service.workspace.arm()  # the next child dies after the pipeline reserved the verifier call and before it saved any answer
    assert service.rreview(KEY, world.held).status_code == 202
    interrupted = service.rowait(KEY, {"interrupted"})
    assert interrupted["revalidation"]["dispatchCount"] == 1 and interrupted["next"] == "recover"
    job = service.rstatus().json()
    assert job["usage"]["startedWithoutReceipt"] == 1 and job["usage"]["replayCalls"] == world.replay_calls
    assert service.stay(JOB, 3.0)["usage"] == job["usage"]  # nothing continued it
    assert service.roprecover(KEY).status_code == 202  # explicit; the pipeline itself refuses to send a call that may already have gone out
    unanswered = service.rowait(KEY, {"failed"})
    assert (unanswered["revalidation"]["lastRuntimeCode"], unanswered["revalidation"]["dispatchCount"], unanswered["next"]) == (
        "replay_response_unknown", 2, "operator_reconcile")
    reconciling = service.rstatus().json()
    assert (reconciling["state"], reconciling["failure"], reconciling["next"]) == ("reconciling", {"code": "replay_response_unknown"}, "operator_reconcile")
    assert reconciling["usage"] == job["usage"]  # still one call started without a receipt; nothing was resent
    for _ in range(2):
        again = service.roprecover(KEY)
        assert again.status_code == 409 and again.json()["error"]["code"] == "reconcile_required"
        assert again.json()["status"]["state"] == "reconciling" and again.json()["operation"]["operationId"] == KEY
    assert service.roperation(KEY).json()["revalidation"]["dispatchCount"] == 2  # a refused recover dispatches nothing
    assert stages(service)["verify-relation"] == base["verify-relation"] + 1  # the one reserved call, in state `started`
    withheld = service.rresult().json()
    assert withheld["delivery"] == {"state": "withheld", "reason": "job_not_ready"} and withheld["job"] is None


def test_a_revalidation_that_finished_before_the_service_recorded_it_is_settled_by_reading_the_chain(start_relation, world):
    crashing = start_relation(launcher_env=crash_at("after_revalidation_child"))
    ready(crashing)
    base = stages(crashing)
    assert crashing.rreview(KEY, world.held).status_code == 202
    crashing.exited(timeout=180)  # the real revalidate child finished and appended its verdict; the service died before recording it
    workspace = crashing.workspace
    service = start_relation(workspace=workspace)
    interrupted = service.roperation(KEY).json()
    assert (interrupted["revalidation"]["state"], interrupted["revalidation"]["lastOutcome"], interrupted["revalidation"]["dispatchCount"], interrupted["next"]) == (
        "interrupted", "service_restarted", 1, "recover")
    assert service.stay(JOB, 2.0)["dispatch"]["dispatchCount"] == 1  # a row a dead process left in flight is not run again by itself
    recovered = service.roprecover(KEY)  # the chain is read first: the verdict is already there, so nothing is dispatched
    assert recovered.status_code == 200
    assert (recovered.json()["revalidation"]["state"], recovered.json()["revalidation"]["verdict"], recovered.json()["revalidation"]["dispatchCount"]) == (
        "verified", "eligible", 1)
    assert stages(service)["verify-relation"] == base["verify-relation"] + 1
    service.close()
    assert kinds(workspace, world.held) == ["verdict", "review", "verdict"]


# ---- a real orphan: a review child that outlives its service and appends AFTER the retry has read the chain -----------------------------------
#
# No hook in the service or the pipeline. The service is configured with a test-owned stand-in command (`write_review_gate_wrapper`) that runs the
# real installed CLI, except that one `review` child can be paused before the real CLI starts (so before it takes the pipeline's ledger lock), be
# released by the next review child, or be preceded by an operator's own review. The paused child is in its own session, so SIGKILL of the service
# leaves it alive.

def retry_review_runs(service) -> list[dict]:
    """The pipeline commands the service logged for each POST /reviews that it answered (`command`, `kind`, `code`: no content)."""
    records = [json.loads(line) for line in service.logs("out").splitlines() if line.startswith("{")]
    return [entry for record in records if record.get("method") == "POST" and str(record.get("route", "")).endswith("/reviews")
            for entry in record.get("runtime", [])]


def test_an_orphaned_review_child_that_appends_after_the_retry_read_the_chain_is_adopted_not_released(start_relation, world):
    first = start_relation(review_gate=True)
    workspace = first.workspace
    version = ready(first)["inputDigest"]
    pid = review_into_an_orphan(first, KEY, world.held, version)
    # The orphan is alive and holds no lock yet: the pipeline's chain is readable (a direct inspect would fail on a held lock) and has no review.
    assert pid > 0 and kinds(workspace, world.held) == ["verdict"] and not workspace.orphan_done()

    service = start_relation(workspace=workspace)
    assert service.roperation(KEY).json()["review"]["state"] == "unconfirmed"
    workspace.release_orphan_before_next_review()  # the retry's own child lets the orphan append, and only then takes the lock itself
    retried = service.rreview(KEY, world.held, version=version)
    # The retry's child was refused (its expected revision is stale: the orphan appended first), yet the operation is NOT lost.
    assert retried.status_code == 202, retried.text
    assert workspace.orphan_done()
    body = retried.json()
    assert (body["review"]["state"], body["review"]["resultingSourceRevision"], body["revalidation"]["state"]) == ("applied", "2", "queued")
    found = service.roperation(KEY)
    assert found.status_code == 200 and found.json()["operationId"] == KEY  # the key is still bound to its operation
    done = service.rowait(KEY, {"verified"})
    assert done["revalidation"]["dispatchCount"] == 1 and done["revalidation"]["verdict"] == "eligible"  # its revalidation was queued and ran once
    service.close()
    # The service's access log is complete once it has stopped: the retry's own child really was refused, so the race was exercised.
    assert any(entry["command"] == "review" and entry["code"] == "review_revision_conflict" for entry in retry_review_runs(service)), (
        "the retry's own review child must have been refused: otherwise this test did not exercise the race")
    chain = direct_relation(workspace, world.held)["history"]
    assert [event["kind"] for event in chain] == ["verdict", "review", "verdict"]  # exactly one review event: the orphan's, adopted
    assert [(event["reviewer"], event["note"], event["decision"], event["expectedRevision"]) for event in chain if event["kind"] == "review"] == [
        ("alpha", MARKER + KEY, "allow", 1)]
    assert ledger_rows(workspace, "SELECT COUNT(*), MAX(review_attempts), MIN(review_state='applied') FROM relation_operations") == [(1, 2, 1)]


def test_a_foreign_event_appended_after_the_retry_read_the_chain_releases_the_reservation_and_the_key_is_reusable(start_relation, world):
    crashing = start_relation(review_gate=True, launcher_env=crash_at("after_review_reserve"))
    version = ready(crashing)["inputDigest"]
    review_into_a_crash(crashing, KEY, world.held)  # one attempt is counted; no child ever ran
    crashing.exited()
    workspace = crashing.workspace
    workspace.foreign_review_before_next_review(world.held)  # the retry's child first lets an OPERATOR append an allow at revision 1

    service = start_relation(workspace=workspace)
    refused = service.rreview(KEY, world.held, version=version)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "source_revision_conflict"
    # The reservation is actually gone: nothing in the ledger, nothing to look up, and nothing of the operator's was adopted.
    assert service.roperation(KEY).status_code == 404
    assert ledger_rows(workspace, "SELECT COUNT(*) FROM relation_operations") == [(0,)]
    chain = direct_relation(workspace, world.held)["history"]
    assert [(event["kind"], event["reviewer"]) for event in chain if event["kind"] == "review"] == [("review", "operator")]
    # The key is reusable under the safe CURRENT revision: the relation is at revision 2 with the operator's allow pending, and a reject may sit on
    # top of a pending allow. (A retained reservation would answer idempotency_conflict here, because the body differs.)
    reused = service.rreview(KEY, world.held, decision="reject", revision=2, version=version)
    assert reused.status_code == 200, reused.text
    assert (reused.json()["decision"], reused.json()["review"]["state"], reused.json()["review"]["resultingSourceRevision"]) == ("reject", "applied", "3")
    service.close()
    assert any(entry["command"] == "review" and entry["code"] == "review_revision_conflict" for entry in retry_review_runs(service)), (
        "the retry's own review child must have been refused: otherwise this test did not exercise the race")
    chain = direct_relation(workspace, world.held)["history"]
    assert [(event["kind"], event["reviewer"], event["decision"]) for event in chain if event["kind"] == "review"] == [
        ("review", "operator", "allow"), ("review", "alpha", "reject")]
    assert [event["note"] for event in chain if event["kind"] == "review"][1] == MARKER + KEY
