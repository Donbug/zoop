"""Who may build, read and cancel an S3 relation job, and when content may leave the service."""
from __future__ import annotations

import json
import sqlite3

from relation_support import JOB, PRIVATE_KEYS, RelationWorkspace, inspect_direct, pipeline_cli, walk_keys


def ledger_rows(workspace: RelationWorkspace, table: str = "relation_jobs") -> int:
    database = sqlite3.connect(f"file:{workspace.state / 'relation-jobs.sqlite3'}?mode=ro", uri=True)
    try:
        return database.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        database.close()


def without_request_id(response) -> dict:
    body = response.json()
    body["error"].pop("requestId")
    return body


def test_each_principal_owns_exactly_the_jobs_it_submitted(start_relation):
    service = start_relation(hold=True)
    assert service.rsubmit(as_="alpha").status_code == 202
    for call in (service.rstatus, service.rresult, service.rcancel, service.rrecover):
        denied = call(as_="beta")
        assert denied.status_code == 404 and denied.json()["error"]["code"] == "job_not_found", call.__name__
    # Another principal's job, and a job that never existed, answer in exactly the same way.
    unknown = service.rstatus("never-created", as_="beta")
    assert without_request_id(unknown) == without_request_id(service.rstatus(as_="beta")) and unknown.status_code == 404
    taken = service.rsubmit(as_="beta")
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "job_id_unavailable"
    assert service.rsubmit("beta-job", as_="beta").status_code == 202  # the same allowlisted upstream, an independent job of its own
    assert service.rstatus("beta-job", as_="alpha").status_code == 404
    # None of that touched the owner's job.
    still = service.rstatus(as_="alpha").json()
    assert still["state"] == "queued" and still["dispatch"]["dispatchCount"] == 0 and still["delivery"]["reason"] == "job_not_ready"
    # Principals without a relation scope reach nothing, however they authenticate.
    for as_ in ("reader", "submitter"):
        for response in (service.rsubmit(as_=as_), service.rstatus(as_=as_), service.rresult(as_=as_), service.rcancel(as_=as_), service.rrecover(as_=as_)):
            assert response.status_code == 403 and response.json()["error"]["code"] == "scope_denied"


def test_an_upstream_must_be_listed_for_the_calling_principal(start_relation, world):
    service = start_relation(listed=("alpha",), hold=True)
    wrong_digest = {**world.upstream, "inputDigest": "0" * 64}
    unknown_job = {"jobId": "no-such-s2-job", "inputDigest": world.upstream["inputDigest"]}
    refusals = [service.rsubmit("unlisted", upstream=wrong_digest), service.rsubmit("unlisted", upstream=unknown_job),
                service.rsubmit("unlisted", as_="beta")]  # beta asks for the real upstream, which is listed for alpha only
    for refused in refusals:
        assert refused.status_code == 403 and refused.json()["error"]["code"] == "upstream_not_allowed"
    # The same answer whether or not the upstream exists, so it cannot be probed.
    assert without_request_id(refusals[0]) == without_request_id(refusals[1]) == without_request_id(refusals[2])
    assert service.rstatus("unlisted").status_code == 404 and service.rstatus("unlisted", as_="beta").status_code == 404
    # Nothing was stored and no child ever started: the refusal happens before the ledger and before the pipeline.
    assert ledger_rows(service.workspace) == 0 and not service.workspace.relation_state.exists()
    assert service.rsubmit().status_code == 202  # the listed pair works


def test_a_job_an_operator_registered_in_the_pipeline_ledger_cannot_be_adopted(start_relation, world, tmp_path):
    root = tmp_path / "adopt"
    root.mkdir()
    workspace = RelationWorkspace(root, world)
    submit = {"schemaVersion": "zoop-relation-s3", "jobId": "operator-job", "upstream": dict(world.upstream),
              "provenance": {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"}}
    code, registered = pipeline_cli(workspace, "submit", submit)
    assert code == 0 and registered["state"] == "queued"
    service = start_relation(workspace=workspace, hold=True)
    refused = service.rsubmit("operator-job")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "job_id_unavailable"
    assert ledger_rows(workspace) == 0  # the reservation was released: the id stays the operator's
    for as_ in ("alpha", "beta"):
        assert service.rstatus("operator-job", as_=as_).status_code == 404 and service.rresult("operator-job", as_=as_).status_code == 404
    service.close()
    code, untouched = inspect_direct(workspace, "operator-job")
    assert code == 0 and untouched["state"] == "queued" and untouched["calls"] == [] and untouched["usage"]["replayCalls"] == 0


def withheld_envelope(service, *, reason: str) -> dict:
    response = service.rresult()
    assert response.status_code == 200, response.text
    envelope = response.json()
    assert envelope["delivery"] == {"state": "withheld", "reason": reason} and envelope["job"] is None and envelope["status"]["delivery"] == envelope["delivery"]
    assert not set(walk_keys(envelope)) & PRIVATE_KEYS
    for text in service.workspace.world.source_texts:
        assert text not in response.text
    return envelope


def test_content_follows_the_current_allowlist_and_the_current_source_grant(start_relation, world):
    service = start_relation()
    workspace = service.workspace
    service.rsubmit()
    service.rwait(states={"ready"}, dispatch={"idle"})
    available = service.rresult()
    assert available.json()["delivery"]["state"] == "available" and world.source_texts[0] in available.text
    both = [(name, world.upstream["jobId"], world.upstream["inputDigest"]) for name in ("alpha", "beta")]

    # 1. The upstream is no longer listed for the owner: the job stays ready, the content stops.
    workspace.write_upstreams([entry for entry in both if entry[0] == "beta"])
    status = service.rstatus().json()
    assert status["state"] == "ready" and status["delivery"] == {"state": "withheld", "reason": "upstream_not_allowed"} and status["next"] == "fetch_result"
    envelope = withheld_envelope(service, reason="upstream_not_allowed")
    assert len(envelope["receipts"]) == world.replay_calls  # accounting metadata stays available
    workspace.write_upstreams(both)
    assert service.rresult().json()["delivery"]["state"] == "available"

    # 2. The operator revokes the source grant: the pipeline withholds on its own current check.
    workspace.revoke_source(False)
    assert service.rstatus().json()["delivery"] == {"state": "withheld", "reason": "source_unauthorized"}
    withheld_envelope(service, reason="source_unauthorized")
    workspace.revoke_source(True)
    assert service.rresult().json()["delivery"]["state"] == "available"

    # 3. An allowlist the service cannot read fails closed with no content and no detail.
    workspace.upstreams.write_text("{broken")
    for response in (service.rresult(), service.rstatus()):
        assert response.status_code == 503 and response.json()["error"]["code"] == "service_configuration_invalid" and response.json()["error"]["retryable"] is True
        assert str(workspace.upstreams) not in response.text and all(text not in response.text for text in world.source_texts)
    workspace.write_upstreams(both)
    assert json.loads(service.rresult().text)["delivery"]["state"] == "available"


def test_a_request_cannot_choose_the_registry_the_command_or_the_fixtures(start_relation, world):
    """The pipeline's inputs are server-owned: revoking the registry copy the SERVICE was configured with is what withholds, whatever a request says."""
    service = start_relation()
    service.rsubmit()
    service.rwait(states={"ready"}, dispatch={"idle"})
    service.workspace.revoke_source(False)
    for response in (service.request("GET", f"/internal/v1/relation-jobs/{JOB}/result?sources={world.registry}&replay=/etc/passwd", as_="alpha"),
                     service.request("GET", f"/internal/v1/relation-jobs/{JOB}/result", as_="alpha", headers={"X-Sources": str(world.registry)})):
        assert response.json()["delivery"]["state"] == "withheld"
