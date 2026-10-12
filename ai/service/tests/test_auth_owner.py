"""Authentication, scopes and owner isolation over real loopback HTTP."""
from __future__ import annotations

import json

from support import cli, document_jobs, document_replay, reference

JOBS = "/internal/v1/analysis-jobs"


def test_missing_malformed_and_unknown_tokens_get_one_identical_401(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    variants = [
        {"as_": None},
        {"as_": None, "headers": {"Authorization": "Basic Zm9vOmJhcg=="}},
        {"as_": None, "headers": {"Authorization": "Bearer short"}},
        {"as_": None, "headers": {"Authorization": "Bearer " + "x" * 600}},
        {"as_": None, "headers": {"Authorization": "Bearer has space-and-" + "y" * 40}},
        {"as_": None, "token": "u" * 43},
        {"as_": None, "token": service.workspace.credentials.tokens["alpha"][:-1] + "!"},
    ]
    bodies = []
    for variant in variants:
        response = service.submit(job, **variant)
        assert response.status_code == 401 and response.headers["WWW-Authenticate"] == "Bearer"
        body = response.json()
        body["error"]["requestId"] = "normalized"
        bodies.append(body)
    assert all(body == bodies[0] for body in bodies)
    assert bodies[0]["error"]["code"] == "authentication_required" and bodies[0]["status"] is None
    assert service.request("GET", f"{JOBS}/anything", as_=None).status_code == 401  # auth precedes job lookup


def test_scope_denied_is_403_and_precedes_headers_and_body(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    denied = service.request("POST", JOBS, as_="reader", raw=b"not json", key="bad key")
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "scope_denied"
    assert service.status(job["jobId"], as_="submitter").status_code == 403
    assert service.result(job["jobId"], as_="submitter").status_code == 403
    assert service.cancel(job["jobId"], as_="reader").status_code == 403
    assert service.recover(job["jobId"], as_="reader").status_code == 403
    assert service.submit(job, as_="reader").status_code == 403
    assert service.submit(job, as_="submitter").status_code == 202
    assert service.status(job["jobId"], as_="reader").status_code == 404  # authorized scope, but not the owner


def test_documentation_and_unknown_routes_do_not_exist(start):
    service = start(replay=document_replay())
    for path in ("/docs", "/redoc", "/openapi.json", "/", "/internal/v1/analysis-jobs/", "/internal/v1/health"):
        response = service.request("GET", path, as_=None)
        assert response.status_code == 404 and response.json()["error"]["code"] == "route_not_found", path
    allowed = service.request("PUT", JOBS)
    assert allowed.status_code == 405 and allowed.json()["error"]["code"] == "method_not_allowed"
    assert "access-control-allow-origin" not in service.request("OPTIONS", JOBS, headers={"Origin": "http://evil.example"}).headers


def test_responses_are_never_cacheable_and_carry_a_request_id(start):
    service = start(replay=document_replay())
    response = service.request("GET", f"{JOBS}/missing", headers={"X-Request-ID": "caller-req-1"})
    assert response.headers["cache-control"] == "no-store" and response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"] == "caller-req-1" and response.json()["error"]["requestId"] == "caller-req-1"
    assert "server" not in response.headers
    generated = service.request("GET", f"{JOBS}/missing", headers={"X-Request-ID": "not valid!"})
    assert generated.headers["x-request-id"] != "not valid!" and len(generated.headers["x-request-id"]) == 36


def test_other_owner_gets_404_everywhere_and_a_conflict_on_post_without_touching_the_runtime(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    assert service.submit(job, as_="alpha").status_code == 202
    service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})
    code, before = cli(service.workspace, "get", reference(job["jobId"]))
    unknown = service.status("never-existed", as_="beta")
    for response in (service.status(job["jobId"], as_="beta"), service.result(job["jobId"], as_="beta"),
                     service.cancel(job["jobId"], as_="beta"), service.recover(job["jobId"], as_="beta")):
        assert response.status_code == 404 and response.json()["error"]["code"] == "job_not_found"
        normalized = {**response.json(), "error": {**response.json()["error"], "requestId": ""}}
        assert normalized == {**unknown.json(), "error": {**unknown.json()["error"], "requestId": ""}}  # same as a job that does not exist
    taken = service.submit(job, as_="beta")
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "job_id_unavailable"
    different = {**job, "kind": "document-sentiment"}
    assert service.submit(different, as_="beta").json()["error"]["code"] == "job_id_unavailable"
    code, after = cli(service.workspace, "get", reference(job["jobId"]))
    assert after == before and after["state"] == "ready"  # nothing beta sent reached the runtime ledger
    # Beta's requests never reached a runtime call at all.
    beta_lines = [json.loads(line) for line in service.logs().splitlines() if line.startswith("{") and '"principal":"beta"' in line]
    assert beta_lines and all(line["runtime"] == [] for line in beta_lines)
    assert service.status(job["jobId"], as_="alpha").status_code == 200  # the owner is unaffected


def test_owner_is_immutable_per_job_id_across_principals_with_all_scopes(start):
    service = start(replay=document_replay())
    first, second = document_jobs()[:2]
    assert service.submit(first, as_="alpha").status_code == 202
    assert service.submit(second, as_="beta").status_code == 202
    assert service.status(first["jobId"], as_="beta").status_code == 404
    assert service.status(second["jobId"], as_="alpha").status_code == 404
    assert service.wait_state(second["jobId"], {"ready"}, dispatch={"idle"}, as_="beta")["state"] == "ready"
    assert service.result(second["jobId"], as_="beta").json()["delivery"]["state"] == "available"
    assert service.result(second["jobId"], as_="alpha").status_code == 404
