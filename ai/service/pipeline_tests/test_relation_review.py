"""S3 relation review over a real uvicorn process, the real installed `zoop-ai-relation` and a fresh synthetic operator world:
allow = the operator's FINAL approval of a HOLD relation (terminal, no revalidation, no call), reject, exact stale-source refusal, idempotency,
ownership, revoked access.

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
                  "expectedSourceRevision", "review", "revalidation", "publication", "next", "limitation", "acceptedAt", "observedAt"}


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


def test_an_allow_is_the_final_approval_of_a_hold_relation_and_calls_nothing(start_relation, world):
    service = start_relation()
    status = ready(service)
    before = service.result_relation(world.held)
    assert before["eligibility"]["status"] == "hold" and before["eligibility"]["reviewPending"] is False and before["eligibility"]["approvalBasis"] is None
    # The result hands the client exactly what a review must quote back: the job's inputDigest and the relation's chain revision.
    assert before["sourceVersion"] == status["inputDigest"] and before["sourceRevision"] == str(world.held_revision) == str(before["eligibility"]["revision"])
    automatic = service.result_relation(world.eligible)
    assert automatic["sourceRevision"] == "1" and automatic["sourceVersion"] == status["inputDigest"]
    assert automatic["eligibility"]["approvalBasis"]["kind"] == "automatic-verifier" and automatic["eligibility"]["approvalBasis"]["reviewer"] is None
    calls_before, usage_before = stages(service), service.rstatus().json()["usage"]

    accepted = service.rreview(KEY, world.held)
    assert accepted.status_code == 200 and accepted.headers["location"] == f"/internal/v1/relation-jobs/{JOB}/reviews/{KEY}"
    operation = accepted.json()
    assert set(operation) == OPERATION_KEYS and operation["schemaVersion"] == SCHEMA
    assert (operation["operationId"], operation["jobId"], operation["relationCandidateId"], operation["decision"], operation["reviewer"]) == (
        KEY, JOB, world.held, "allow", "alpha")  # the reviewer is the authenticated principal
    assert (operation["expectedSourceVersion"], operation["expectedSourceRevision"]) == (status["inputDigest"], "1")
    # Terminal: recorded, nothing requested, nothing to wait for, nothing published, no limitation.
    assert operation["review"]["state"] == "applied" and operation["review"]["resultingSourceRevision"] == "2" and operation["review"]["recordedAt"]
    assert operation["revalidation"]["state"] == "not_requested" and operation["revalidation"]["verdict"] is None and operation["revalidation"]["dispatchCount"] == 0
    assert operation["next"] == "none" and operation["limitation"] is None and operation["publication"] == {"state": "not_published"}
    assert not set(walk_keys(operation)) & OPERATION_PRIVATE

    quiet = service.stay(JOB, 2.5)
    assert quiet["state"] == "ready" and quiet["dispatch"]["dispatchCount"] == 1 and quiet["usage"] == usage_before and quiet["next"] == "fetch_result"
    assert stages(service) == calls_before  # no verifier, producer or impact call of any kind
    after = service.result_relation(world.held)
    assert after["eligibility"]["status"] == "eligible" and after["eligibility"]["reviewPending"] is False and after["approved"] is False
    assert after["eligibility"]["reasons"] == [] and after["sourceRevision"] == "2" == str(after["eligibility"]["revision"])
    assert after["eligibility"]["approvalBasis"] == {"kind": "operator-final-approval", "revision": 2, "reviewer": "alpha",
                                                     "decidedAt": after["eligibility"]["approvalBasis"]["decidedAt"]}
    assert after["eligibility"]["approvalBasis"]["decidedAt"]
    # The earlier automatic HOLD verdict stays in the history, immutable; the approval is the second event.
    assert [event["kind"] for event in after["history"]] == ["verdict", "review"]
    assert after["history"][0]["eligibility"] == "hold" and (after["history"][1]["decision"], after["history"][1]["effect"]) == ("allow", "approved")
    assert after["impact"]["status"] == "not-applicable"

    # The same chain read straight from the installed CLI: ONE review event, written by the principal, carrying only the operation marker.
    direct = direct_relation(service.workspace, world.held)
    review = direct["history"][1]
    assert [event["kind"] for event in direct["history"]] == ["verdict", "review"]
    assert (review["reviewer"], review["note"], review["decision"], review["expectedRevision"], review["effect"]) == ("alpha", MARKER + KEY, "allow", 1, "approved")

    # Same key and body: the existing operation, although the relation has moved on since (the body still quotes revision 1).
    replay = service.rreview(KEY, world.held)
    assert replay.status_code == 200 and stable(replay) == stable(service.roperation(KEY)) and replay.json()["review"]["state"] == "applied"
    assert service.rstatus().json()["dispatch"]["dispatchCount"] == 1 and operations(service.workspace) == 1
    clean(service, json.dumps(operation), replay.text)


def test_a_reject_is_recorded_and_closes_the_relation_and_an_approved_one_cannot_be_reversed_here(start_relation, world):
    service = start_relation()
    ready(service)
    calls = stages(service)
    rejected = service.rreview("decision-reject-0001", world.held, decision="reject")
    assert rejected.status_code == 200
    operation = rejected.json()
    assert operation["decision"] == "reject" and operation["review"]["state"] == "applied" and operation["review"]["resultingSourceRevision"] == "2"
    assert operation["revalidation"]["state"] == "not_requested" and operation["next"] == "none" and operation["publication"] == {"state": "not_published"}
    relation = service.result_relation(world.held)
    assert relation["eligibility"]["status"] == "reject" and relation["sourceRevision"] == "2" and relation["approved"] is False
    assert relation["eligibility"]["approvalBasis"] is None  # an exclusion is not an approval basis
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


def test_an_approved_relation_takes_no_further_decision(start_relation, world):
    service = start_relation()
    ready(service)
    assert service.rreview(KEY, world.held).status_code == 200
    for key, decision in (("approve-again", "allow"), ("reject-approved", "reject")):
        refused = service.rreview(key, world.held, decision=decision, revision=2)
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "review_target_not_hold"  # approving or reversing a final decision is out of scope
        assert service.roperation(key).status_code == 404
    assert service.result_relation(world.held)["eligibility"]["status"] == "eligible" and operations(service.workspace) == 1


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
    assert service.rreview("op-revision", world.held, revision=1).status_code == 200


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
    # The old operation-recover route is gone: there is nothing left to recover.
    assert service.request("POST", f"/internal/v1/relation-jobs/{JOB}/reviews/{KEY}/recover").status_code in (404, 405)


def test_the_same_key_and_body_return_one_operation_and_another_body_is_a_conflict(start_relation, world):
    service = start_relation()
    status = ready(service)
    version = status["inputDigest"]
    with ThreadPoolExecutor(6) as pool:
        replies = [future.result() for future in [pool.submit(service.rreview, KEY, world.held, version=version) for _ in range(6)]]
    assert {reply.status_code for reply in replies} == {200}, [reply.text for reply in replies]
    assert len({reply.json()["operationId"] for reply in replies}) == 1 and operations(service.workspace) == 1
    for conflicting in (service.rreview(KEY, world.held, decision="reject", version=version), service.rreview(KEY, world.held, revision=2, version=version),
                        service.rreview(KEY, world.eligible, version=version), service.rreview(KEY, world.held, version="1" * 64)):
        assert conflicting.status_code == 409 and conflicting.json()["error"]["code"] == "idempotency_conflict"
    assert service.roperation(KEY).json()["review"]["state"] == "applied"
    service.close()
    chain = direct_relation(service.workspace, world.held)["history"]
    assert [event["kind"] for event in chain] == ["verdict", "review"]  # exactly one review event


def test_each_principal_sees_only_its_own_operations(start_relation, world):
    service = start_relation()
    ready(service)
    assert service.rreview(KEY, world.held).status_code == 200
    version = service.rstatus().json()["inputDigest"]
    for response in (service.rreview("beta-try", world.held, as_="beta", version=version), service.roperation(KEY, as_="beta")):
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
    assert own.status_code == 200 and own.json()["reviewer"] == "beta" and own.json()["jobId"] == "beta-job"
    assert service.roperation("beta-own", "beta-job", as_="alpha").status_code == 404  # alpha cannot read it, not even under beta's own job id
    # Scopes: reading is not reviewing, and principals without any relation scope reach nothing.
    assert service.roperation(KEY, as_="viewer").status_code == 404  # viewer may read, but owns nothing
    for response in (service.rreview("viewer-try", world.held, as_="viewer", version=version),):
        assert response.status_code == 403 and response.json()["error"]["code"] == "scope_denied"
    for as_ in ("reader", "submitter"):
        for response in (service.rreview("nope", world.held, as_=as_, version=version), service.roperation(KEY, as_=as_)):
            assert response.status_code == 403 and response.json()["error"]["code"] == "scope_denied"
    assert operations(service.workspace) == 2


def test_operation_reads_never_touch_the_pipeline(start_relation, world):
    service = start_relation()
    ready(service)
    assert service.rreview(KEY, world.held).status_code == 200
    with open(service.workspace.relation_state / "relation.lock", "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # an operator holds the pipeline ledger
        try:
            looked_up = service.roperation(KEY)
            assert looked_up.status_code == 200 and looked_up.json()["review"]["state"] == "applied"
            assert service.rstatus().status_code == 503  # a job status is read from the pipeline, and says so
            conflicting = service.rreview(KEY, world.held, version="0" * 64)  # another body: answered from the ledger alone, no child
            assert conflicting.status_code == 409 and conflicting.json()["error"]["code"] == "idempotency_conflict"
            assert service.rreview(KEY, world.held, version=looked_up.json()["expectedSourceVersion"]).status_code == 200
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def test_a_review_needs_the_upstream_listed_now_and_a_grant_that_still_holds_and_a_human_cannot_override_either(start_relation, world):
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

    workspace.revoke_source(False)  # the operator revokes the source grant: the pipeline itself refuses to append the approval
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
    assert service.rreview("op-fine", world.held, version=version).status_code == 200
    workspace.write_upstreams([entry for entry in both if entry[0] == "beta"])
    assert service.roperation("op-fine").status_code == 200
    assert service.rreview("op-fine", world.held, version=version).status_code == 200  # a replay returns the recorded operation
    clean(service, refused.text, revoked.text, broken.text)


def test_a_cancelled_job_refuses_reviews(start_relation, world):
    service = start_relation()
    ready(service)
    version = service.rstatus().json()["inputDigest"]
    assert service.rreview(KEY, world.held).status_code == 200
    # the operator cancels the job directly in the pipeline ledger
    code, cancelled = pipeline_cli(service.workspace, "cancel", {"schemaVersion": "zoop-relation-s3", "jobId": JOB})
    assert cancelled["state"] == "cancelled"
    refused = service.rreview("after-cancel", world.eligible, revision=1, version=version)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "job_cancelled"
    assert service.roperation("after-cancel").status_code == 404 and operations(service.workspace) == 1
    assert service.rrecover().status_code == 409  # the job itself is final


def test_an_operation_recorded_under_the_earlier_revalidation_contract_is_history_and_is_never_dispatched(start_relation, world):
    """A `-2` ledger's queued revalidation must neither run nor read as an approval after the service moved to the final-approval contract."""
    service = start_relation()
    ready(service)
    service.stop()
    workspace = service.workspace
    import sqlite3
    path = workspace.state / "relation-jobs.sqlite3"
    raw = sqlite3.connect(path)
    raw.execute("INSERT INTO relation_operations(operation_id,owner,job_id,relation_candidate_id,decision,expected_source_version,expected_source_revision,"
                "request_digest,review_state,reserved_at,applied_at,applied_event_at,reval_state,reval_seq,contract) VALUES "
                "('legacy-1','alpha',?,?,'allow',?,1,?,'applied','2026-10-13T00:00:00Z','2026-10-13T00:00:01Z','2026-10-13T00:00:02+00:00','pending',99,"
                "'legacy-revalidation')", (JOB, world.held, "0" * 64, "a" * 64))
    raw.commit()
    raw.close()
    restarted = start_relation(workspace=workspace)
    legacy = restarted.roperation("legacy-1")
    assert legacy.status_code == 200 and legacy.json()["limitation"] == "review_contract_changed"
    assert legacy.json()["revalidation"]["state"] == "contract_changed" and legacy.json()["next"] == "none"
    quiet = restarted.stay(JOB, 2.5)
    assert quiet["dispatch"]["dispatchCount"] == 1  # nothing was dispatched for the old queue
    relation = restarted.result_relation(world.held)
    assert relation["eligibility"]["status"] == "hold" and relation["eligibility"]["approvalBasis"] is None  # the old allow never became an approval
    assert direct_relation(workspace, world.held)["eligibility"]["revision"] == world.held_revision
