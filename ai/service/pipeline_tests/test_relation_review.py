"""S3 relation review over a real uvicorn process, the real installed `zoop-ai-relation` and a fresh synthetic operator world:
allow -> queued revalidation -> verdict -> new runtime revision, reject, exact stale-source refusal, idempotency, ownership, revoked access.

Two numbers are never confused here. `sourceRevision` / `expectedSourceRevision` is the runtime's event-chain revision of ONE relation candidate
(a decimal string on the wire). The application's own review revision is a different thing the service never sees and never forwards.
"""
from __future__ import annotations

import fcntl
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest

from relation_support import JOB, MARKER, OPERATION_PRIVATE, SCHEMA, direct_relation, ledger_rows, pipeline_cli, walk_keys

KEY = "decision-allow-0001"
OPERATION_KEYS = {"schemaVersion", "operationId", "jobId", "relationCandidateId", "decision", "reviewer", "expectedSourceVersion",
                  "expectedSourceRevision", "review", "revalidation", "publication", "next", "acceptedAt", "observedAt"}


def ready(service) -> dict:
    assert service.rsubmit().status_code == 202
    return service.rwait(states={"ready"}, dispatch={"idle"})


def stages(service) -> Counter:
    return Counter(receipt["stage"] for receipt in service.rresult().json()["receipts"])


def stable(response) -> dict:
    """A response body without the one field that is a timestamp of the read itself."""
    body = response.json()
    body.pop("observedAt", None)
    return body


def clean(service, *texts: str) -> None:
    """No path, token, source sentence or marker in what a caller saw or in the service log."""
    corpus = [*texts, service.logs()]
    for value in [*service.workspace.private_strings(), *service.workspace.world.source_texts, MARKER]:
        for text in corpus:
            assert value not in text, value


def operations(workspace) -> int:
    return ledger_rows(workspace, "SELECT COUNT(*) FROM relation_operations")[0][0]


def test_an_allow_is_recorded_then_revalidated_and_the_relation_gets_a_new_source_revision(start_relation, world):
    service = start_relation()
    status = ready(service)
    before = service.result_relation(world.held)
    assert before["eligibility"]["status"] == "hold" and before["eligibility"]["reviewPending"] is False
    # The result hands the client exactly what a review must quote back: the job's inputDigest and the relation's chain revision.
    assert before["sourceVersion"] == status["inputDigest"] and before["sourceRevision"] == str(world.held_revision) == str(before["eligibility"]["revision"])
    assert service.result_relation(world.eligible)["sourceRevision"] == "1" and service.result_relation(world.eligible)["sourceVersion"] == status["inputDigest"]
    stages_before = stages(service)

    accepted = service.rreview(KEY, world.held)
    assert accepted.status_code == 202 and accepted.headers["location"] == f"/internal/v1/relation-jobs/{JOB}/reviews/{KEY}"
    operation = accepted.json()
    assert set(operation) == OPERATION_KEYS and operation["schemaVersion"] == SCHEMA
    assert (operation["operationId"], operation["jobId"], operation["relationCandidateId"], operation["decision"], operation["reviewer"]) == (
        KEY, JOB, world.held, "allow", "alpha")  # the reviewer is the authenticated principal
    assert (operation["expectedSourceVersion"], operation["expectedSourceRevision"]) == (status["inputDigest"], "1")
    # Acceptance, verification and publication are three separate facts.
    assert operation["review"]["state"] == "applied" and operation["review"]["resultingSourceRevision"] == "2" and operation["review"]["recordedAt"]
    assert operation["revalidation"]["state"] in {"queued", "running"} and operation["revalidation"]["verdict"] is None
    assert operation["publication"] == {"state": "not_published"} and operation["next"] == "wait"
    assert not set(walk_keys(operation)) & OPERATION_PRIVATE

    done = service.rowait(KEY, {"verified"})
    assert done["revalidation"]["verdict"] == "eligible" and done["revalidation"]["resultingSourceRevision"] == "3"
    assert done["revalidation"]["dispatchCount"] == 1 and done["next"] == "none" and done["publication"] == {"state": "not_published"}
    assert done["review"]["state"] == "applied" and done["review"]["resultingSourceRevision"] == "2"
    job = service.rwait(states={"ready"}, dispatch={"idle"})
    assert job["dispatch"]["dispatchCount"] == 1 and job["usage"]["providerCalls"] == job["usage"]["modelCalls"] == 0 and job["next"] == "fetch_result"

    after = service.result_relation(world.held)
    assert after["eligibility"]["status"] == "eligible" and after["eligibility"]["reviewPending"] is False and after["approved"] is False
    assert after["sourceRevision"] == "3" == str(after["eligibility"]["revision"]) and after["sourceVersion"] == status["inputDigest"]
    assert [event["kind"] for event in after["history"]] == ["verdict", "review", "verdict"]
    assert after["history"][1]["decision"] == "allow" and after["history"][1]["effect"] == "revalidation-requested"
    assert after["impact"]["status"] == "complete"
    stages_after = stages(service)
    assert stages_after["verify-relation"] == stages_before["verify-relation"] + 1  # exactly one verification call for the revalidation
    assert stages_after["relation"] == stages_before["relation"] == 1  # nothing was regenerated

    # The same chain read straight from the installed CLI: ONE review event, written by the principal, carrying only the operation marker.
    direct = direct_relation(service.workspace, world.held)
    review = direct["history"][1]
    assert [event["kind"] for event in direct["history"]] == ["verdict", "review", "verdict"] and direct["history"][2]["attempt"]["kind"] == "revalidation"
    assert (review["reviewer"], review["note"], review["decision"], review["expectedRevision"], review["effect"]) == (
        "alpha", MARKER + KEY, "allow", 1, "revalidation-requested")

    # Same key and body: the existing operation, although the relation has moved on since (the body still quotes revision 1).
    replay = service.rreview(KEY, world.held)
    assert replay.status_code == 200 and stable(replay) == stable(service.roperation(KEY)) and replay.json()["revalidation"]["state"] == "verified"
    assert service.rstatus().json()["dispatch"]["dispatchCount"] == 1 and operations(service.workspace) == 1
    clean(service, json.dumps(operation), json.dumps(done), replay.text)


def test_a_reject_is_recorded_without_any_revalidation_and_closes_the_relation(start_relation, world):
    service = start_relation()
    ready(service)
    calls = stages(service)
    rejected = service.rreview("decision-reject-0001", world.held, decision="reject")
    assert rejected.status_code == 200
    operation = rejected.json()
    assert operation["decision"] == "reject" and operation["review"]["state"] == "applied" and operation["review"]["resultingSourceRevision"] == "2"
    assert operation["revalidation"]["state"] == "not_requested" and operation["revalidation"]["dispatchCount"] == 0 and operation["next"] == "none"
    assert operation["publication"] == {"state": "not_published"}
    relation = service.result_relation(world.held)
    assert relation["eligibility"]["status"] == "reject" and relation["sourceRevision"] == "2" and relation["approved"] is False
    assert [reason["code"] for reason in relation["eligibility"]["reasons"]] == ["admin_rejected"]
    assert [event["effect"] for event in relation["history"] if event["kind"] == "review"] == ["excluded"]
    assert stages(service) == calls  # no call of any kind
    assert service.stay(JOB, 2.0)["dispatch"]["dispatchCount"] == 1
    # A rejected relation is not on hold any more: an allow, however current its quoted revision, is refused and records nothing.
    again = service.rreview("decision-allow-late", world.held, revision=2)
    assert again.status_code == 409 and again.json()["error"]["code"] == "review_target_not_hold"
    stale = service.rreview("decision-allow-stale", world.held, revision=1)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "source_revision_conflict"
    assert service.roperation("decision-allow-late").status_code == 404 and service.roperation("decision-allow-stale").status_code == 404
    assert operations(service.workspace) == 1


def test_a_stale_source_version_or_revision_records_nothing_anywhere(start_relation, world):
    service = start_relation()
    status = ready(service)
    before = direct_relation(service.workspace, world.held)
    usage = service.rstatus().json()["usage"]
    wrong_version = service.rreview("op-version", world.held, version="0" * 64)
    assert wrong_version.status_code == 409 and wrong_version.json()["error"]["code"] == "source_version_conflict"
    # The pipeline enforces the revision inside its own append transaction, so the refusal is the pipeline's, relayed with a stable code.
    stale = service.rreview("op-revision", world.held, revision=2)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "source_revision_conflict"
    assert stale.json()["error"]["runtimeCode"] == "review_revision_conflict" and stale.json()["error"]["retryable"] is False
    not_hold = service.rreview("op-eligible", world.eligible, revision=1)
    assert not_hold.status_code == 409 and not_hold.json()["error"]["code"] == "review_target_not_hold"
    unknown = service.rreview("op-unknown", "rc-" + "f" * 64, revision=1)
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "relation_candidate_not_found"
    for key in ("op-version", "op-revision", "op-eligible", "op-unknown"):
        assert service.roperation(key).status_code == 404 and service.roperation(key).json()["error"]["code"] == "operation_not_found"
    assert operations(service.workspace) == 0
    assert direct_relation(service.workspace, world.held) == before and before["eligibility"]["revision"] == world.held_revision  # no event, no verdict
    quiet = service.stay(JOB, 2.5)
    assert quiet["dispatch"]["dispatchCount"] == 1 and quiet["usage"] == usage and quiet["inputDigest"] == status["inputDigest"]
    # A refusal frees the key: the corrected request under the same key is a new operation.
    assert service.rreview("op-revision", world.held, revision=1).status_code == 202


@pytest.mark.parametrize("mutate", [
    lambda body: body.update(reviewer="admin@example.invalid"), lambda body: body.update(note="free text"), lambda body: body.update(jobId="other"),
    lambda body: body.update(expectedRevision=1), lambda body: body.update(expectedSourceRevision=1), lambda body: body.update(expectedSourceRevision="0"),
    lambda body: body.update(expectedSourceRevision="01"), lambda body: body.update(expectedSourceRevision="1.0"), lambda body: body.update(expectedSourceRevision=""),
    lambda body: body.update(expectedSourceVersion="abc"), lambda body: body.update(decision="approve"), lambda body: body.update(relationCandidateId="relation"),
    lambda body: body.pop("expectedSourceRevision"), lambda body: body.pop("decision"),
])
def test_the_review_body_is_exact_and_carries_no_reviewer(start_relation, world, mutate):
    service = start_relation(hold=True)
    service.rsubmit()
    body = {"relationCandidateId": world.held, "expectedSourceVersion": "0" * 64, "expectedSourceRevision": "1", "decision": "allow"}
    mutate(body)
    refused = service.request("POST", f"/internal/v1/relation-jobs/{JOB}/reviews", body=body, key="hostile")
    assert refused.status_code == 422 and refused.json()["error"]["field"] == "body" and refused.json()["schemaVersion"] == SCHEMA
    assert operations(service.workspace) == 0


def test_the_review_request_is_framed_strictly(start_relation, world):
    service = start_relation(hold=True)
    service.rsubmit()
    path = f"/internal/v1/relation-jobs/{JOB}/reviews"
    body = {"relationCandidateId": world.held, "expectedSourceVersion": "0" * 64, "expectedSourceRevision": "1", "decision": "allow"}
    assert service.request("POST", path, body=body).status_code == 422  # no Idempotency-Key
    assert service.request("POST", path, body=body, key="bad key!").json()["error"]["field"] == "Idempotency-Key"
    assert service.request("POST", path, raw=b"{}", key="x", headers={"Content-Type": "text/plain"}).status_code == 415
    assert service.request("POST", path, raw=b"{" + b" " * 2_000_100 + b"}", key="x", headers={"Content-Type": "application/json"}).status_code == 413
    duplicate = b'{"relationCandidateId":"a","relationCandidateId":"a"}'
    assert service.request("POST", path, raw=duplicate, key="x", headers={"Content-Type": "application/json"}).status_code == 422
    assert service.request("POST", "/internal/v1/relation-jobs/bad id!/reviews", body=body, key="x").status_code in (404, 422)
    # A query string is not an input: the (wrong) expected version in the body decides, and nothing is recorded.
    ignored = service.request("POST", path + "?reviewer=root&decision=reject&expectedSourceVersion=" + "1" * 64, body=body, key="query-ignored")
    assert ignored.status_code == 409 and ignored.json()["error"]["code"] == "source_version_conflict"
    assert operations(service.workspace) == 0


def test_the_same_key_and_body_return_one_operation_and_another_body_is_a_conflict(start_relation, world):
    service = start_relation()
    status = ready(service)
    version = status["inputDigest"]
    with ThreadPoolExecutor(6) as pool:
        replies = [future.result() for future in [pool.submit(service.rreview, KEY, world.held, version=version) for _ in range(6)]]
    codes = sorted(reply.status_code for reply in replies)
    assert codes.count(202) == 1 and set(codes) <= {200, 202}, codes
    assert len({reply.json()["operationId"] for reply in replies}) == 1 and operations(service.workspace) == 1
    done = service.rowait(KEY, {"verified"})
    assert done["revalidation"]["dispatchCount"] == 1  # one review, one revalidation, however many times it was sent
    for conflicting in (service.rreview(KEY, world.held, decision="reject", version=version), service.rreview(KEY, world.held, revision=2, version=version),
                        service.rreview(KEY, world.eligible, version=version), service.rreview(KEY, world.held, version="1" * 64)):
        assert conflicting.status_code == 409 and conflicting.json()["error"]["code"] == "idempotency_conflict"
    assert stable(service.roperation(KEY)) == {key: value for key, value in done.items() if key != "observedAt"}
    service.close()
    chain = direct_relation(service.workspace, world.held)["history"]
    assert [event["kind"] for event in chain] == ["verdict", "review", "verdict"]  # exactly one review event


def test_each_principal_sees_only_its_own_operations(start_relation, world):
    service = start_relation()
    ready(service)
    assert service.rreview(KEY, world.held).status_code == 202
    service.rowait(KEY, {"verified"})
    version = service.rstatus().json()["inputDigest"]
    for response in (service.rreview("beta-try", world.held, as_="beta", version=version), service.roperation(KEY, as_="beta"), service.roprecover(KEY, as_="beta")):
        assert response.status_code == 404 and response.json()["error"]["code"] == "job_not_found"
    never = service.roperation(KEY, "never-created", as_="beta")
    assert never.status_code == 404 and never.json()["error"] == service.roperation(KEY, as_="beta").json()["error"] | {"requestId": never.json()["error"]["requestId"]}
    assert operations(service.workspace) == 1
    # beta owns its own job over the same allowlisted upstream; the key of alpha's operation is not available to it.
    assert service.rsubmit("beta-job", as_="beta").status_code == 202
    beta_status = service.rwait("beta-job", {"ready"}, dispatch={"idle"}, as_="beta")
    taken = service.rreview(KEY, world.held, job_id="beta-job", as_="beta", version=beta_status["inputDigest"])
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "operation_id_unavailable"
    assert service.roperation(KEY, "beta-job", as_="beta").status_code == 404 and service.roperation(KEY, "beta-job", as_="alpha").status_code == 404
    own = service.rreview("beta-own", world.held, job_id="beta-job", as_="beta", version=beta_status["inputDigest"])
    assert own.status_code == 202 and own.json()["reviewer"] == "beta" and own.json()["jobId"] == "beta-job"
    assert service.roperation("beta-own", "beta-job", as_="alpha").status_code == 404  # alpha cannot read it, not even under beta's own job id
    # The decision of beta is attributed to beta in the chain of beta's job; alpha's chain holds only alpha's.
    service.rowait("beta-own", {"verified"}, job_id="beta-job", as_="beta")
    # Scopes: reading is not reviewing, and principals without any relation scope reach nothing.
    assert service.roperation(KEY, as_="viewer").status_code == 404  # viewer may read, but owns nothing
    for response in (service.rreview("viewer-try", world.held, as_="viewer", version=version),):
        assert response.status_code == 403 and response.json()["error"]["code"] == "scope_denied"
    for as_ in ("reader", "submitter"):
        for response in (service.rreview("nope", world.held, as_=as_, version=version), service.roperation(KEY, as_=as_), service.roprecover(KEY, as_=as_)):
            assert response.status_code == 403 and response.json()["error"]["code"] == "scope_denied"
    assert operations(service.workspace) == 2


def test_operation_reads_never_touch_the_pipeline(start_relation, world):
    service = start_relation()
    ready(service)
    assert service.rreview(KEY, world.held).status_code == 202
    service.rowait(KEY, {"verified"})
    with open(service.workspace.relation_state / "relation.lock", "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # an operator holds the pipeline ledger
        try:
            looked_up = service.roperation(KEY)
            assert looked_up.status_code == 200 and looked_up.json()["revalidation"]["state"] == "verified"
            assert service.rstatus().status_code == 503  # a job status is read from the pipeline, and says so
            conflicting = service.rreview(KEY, world.held, version="0" * 64)  # another body: answered from the ledger alone, no child
            assert conflicting.status_code == 409 and conflicting.json()["error"]["code"] == "idempotency_conflict"
            assert service.rreview(KEY, world.held, version=looked_up.json()["expectedSourceVersion"]).status_code == 200
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def test_a_review_needs_the_upstream_listed_now_and_a_grant_that_still_holds(start_relation, world):
    service = start_relation()
    workspace = service.workspace
    status = ready(service)
    version = status["inputDigest"]
    before = direct_relation(workspace, world.held)
    both = [(name, world.upstream["jobId"], world.upstream["inputDigest"]) for name in ("alpha", "beta")]

    workspace.write_upstreams([entry for entry in both if entry[0] == "beta"])  # alpha's upstream entry is removed
    refused = service.rreview("op-unlisted", world.held, version=version)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "upstream_not_allowed"
    assert operations(workspace) == 0 and service.roperation("op-unlisted").status_code == 404
    workspace.write_upstreams(both)

    workspace.revoke_source(False)  # the operator revokes the source grant: the pipeline itself refuses to append
    revoked = service.rreview("op-revoked", world.held, version=version)
    assert revoked.status_code == 409 and revoked.json()["error"]["code"] == "upstream_unavailable" and revoked.json()["error"]["runtimeCode"]
    assert all(text not in revoked.text for text in world.source_texts) and operations(workspace) == 0
    workspace.revoke_source(True)
    assert direct_relation(workspace, world.held) == before  # nothing was appended by either refusal

    # An allowlist the service cannot read fails closed, with no detail.
    workspace.upstreams.write_text("{broken")
    broken = service.rreview("op-broken", world.held, version=version)
    assert broken.status_code == 503 and broken.json()["error"]["code"] == "service_configuration_invalid" and str(workspace.upstreams) not in broken.text
    workspace.write_upstreams(both)
    assert operations(workspace) == 0

    # Looking an existing operation up needs no authority beyond ownership, but changing anything again does.
    assert service.rreview("op-fine", world.held, version=version).status_code == 202
    service.rowait("op-fine", {"verified"})
    workspace.write_upstreams([entry for entry in both if entry[0] == "beta"])
    assert service.roperation("op-fine").status_code == 200
    assert service.rreview("op-fine", world.held, version=version).status_code == 200  # a replay returns the recorded operation
    assert service.roprecover("op-fine").json()["revalidation"]["state"] == "verified"  # nothing to recover: no authority needed to say so
    clean(service, refused.text, revoked.text, broken.text)


def test_a_revalidation_waits_for_the_owner_to_be_listed_and_then_recovers_explicitly(start_relation, world):
    first = start_relation()
    workspace = first.workspace
    ready(first)
    first.stop()
    service = start_relation(workspace=workspace, hold=True)  # the accepted allow stays queued until released
    assert service.rreview(KEY, world.held).status_code == 202
    queued = service.roperation(KEY).json()
    assert queued["revalidation"]["state"] == "queued" and queued["revalidation"]["dispatchCount"] == 0
    calls = stages(service)
    workspace.write_upstreams([("beta", world.upstream["jobId"], world.upstream["inputDigest"])])  # access is withdrawn while it waits
    workspace.go()
    refused = service.rowait(KEY, {"failed"})
    assert (refused["revalidation"]["lastOutcome"], refused["revalidation"]["lastRuntimeCode"], refused["revalidation"]["dispatchCount"], refused["next"]) == (
        "runtime_error", "upstream_not_allowed", 1, "recover")
    assert stages(service) == calls and service.rstatus().json()["state"] == "ready"  # no child was started for it
    forbidden = service.roprecover(KEY)
    assert forbidden.status_code == 403 and forbidden.json()["error"]["code"] == "upstream_not_allowed"
    assert service.stay(JOB, 2.0)["dispatch"]["dispatchCount"] == 1 and service.roperation(KEY).json()["revalidation"]["dispatchCount"] == 1
    workspace.write_upstreams([(name, world.upstream["jobId"], world.upstream["inputDigest"]) for name in ("alpha", "beta")])
    assert service.roprecover(KEY).status_code == 202
    done = service.rowait(KEY, {"verified"})
    assert done["revalidation"]["dispatchCount"] == 2 and done["revalidation"]["verdict"] == "eligible"


def test_a_pending_allow_can_never_overwrite_a_rejection_that_came_after_it(start_relation, world):
    first = start_relation()
    workspace = first.workspace
    ready(first)
    before = stages(first)
    first.stop()
    service = start_relation(workspace=workspace, hold=True)
    assert service.rreview("allow-first", world.held).status_code == 202  # revision 1 -> 2, revalidation queued behind the hold
    reject = service.rreview("reject-second", world.held, decision="reject", revision=2)  # a reject is allowed on top of a pending allow
    assert reject.status_code == 200 and reject.json()["review"]["resultingSourceRevision"] == "3"
    stale = service.rreview("allow-stale", world.held, revision=2)  # the relation moved to 3 and is rejected: this allow can never apply
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "source_revision_conflict"
    workspace.go()
    superseded = service.rowait("allow-first", {"superseded"})
    assert superseded["revalidation"]["verdict"] is None and superseded["revalidation"]["resultingSourceRevision"] == "3" and superseded["next"] == "none"
    assert superseded["review"]["state"] == "applied" and superseded["revalidation"]["dispatchCount"] == 1
    relation = service.result_relation(world.held)
    assert relation["eligibility"]["status"] == "reject" and relation["sourceRevision"] == "3"
    assert [(event["kind"], event["decision"]) for event in relation["history"]] == [("verdict", None), ("review", "allow"), ("review", "reject")]
    assert stages(service) == before  # the stale allow's revalidation sent nothing, and appended nothing
    # Recovering a superseded operation changes nothing either.
    again = service.roprecover("allow-first")
    assert again.status_code == 200 and again.json()["revalidation"]["state"] == "superseded"
    assert service.stay(JOB, 2.0)["dispatch"]["dispatchCount"] == 1 and operations(workspace) == 2


def test_a_cancelled_job_refuses_reviews_and_recovery(start_relation, world):
    service = start_relation()
    ready(service)
    version = service.rstatus().json()["inputDigest"]
    allowed = service.rreview(KEY, world.held)
    assert allowed.status_code == 202
    service.rowait(KEY, {"verified"})
    # the operator cancels the job directly in the pipeline ledger
    code, cancelled = pipeline_cli(service.workspace, "cancel", {"schemaVersion": "zoop-relation-s3", "jobId": JOB})
    assert cancelled["state"] == "cancelled"
    refused = service.rreview("after-cancel", world.held, revision=3, version=version)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "job_cancelled"
    assert service.roperation("after-cancel").status_code == 404 and operations(service.workspace) == 1
    assert service.rrecover().status_code == 409  # the job itself is final


def test_a_revalidation_that_ends_on_hold_is_a_verdict_and_a_second_attempt_is_a_separate_explicit_one(start_relation, world):
    service = start_relation(verifier=world.verifier_hold)
    ready(service)
    assert service.rreview(KEY, world.held).status_code == 202
    done = service.rowait(KEY, {"verified"})
    assert done["revalidation"]["verdict"] == "hold" and done["revalidation"]["resultingSourceRevision"] == "3"  # verified is not eligible
    relation = service.result_relation(world.held)
    assert relation["eligibility"]["status"] == "hold" and relation["eligibility"]["reviewPending"] is False and relation["sourceRevision"] == "3"
    # The relation is on hold again at revision 3, so a new decision is possible; its revalidation attempt has no authored answer.
    second = service.rreview("decision-allow-0002", world.held, revision=3)
    assert second.status_code == 202 and second.json()["review"]["resultingSourceRevision"] == "4"
    failed = service.rowait("decision-allow-0002", {"failed"})
    assert failed["revalidation"]["lastRuntimeCode"].endswith("_replay_missing") and failed["revalidation"]["dispatchCount"] == 1 and failed["next"] == "recover"
    assert service.stay(JOB, 2.0)["state"] == "ready"  # the pipeline restored the job; nothing was sent and nothing continues on its own
    assert service.roperation("decision-allow-0002").json()["revalidation"]["dispatchCount"] == 1
    assert service.roprecover("decision-allow-0002").status_code == 202  # explicit, and it fails the same way again
    again = service.rowait("decision-allow-0002", {"failed"})
    assert again["revalidation"]["dispatchCount"] == 2 and service.rstatus().json()["usage"]["startedWithoutReceipt"] == 0
