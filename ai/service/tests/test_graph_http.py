"""The read-only graph door over a REAL service process (uvicorn on 127.0.0.1) and a test-owned stand-in for `zoop-ai-graph`.

The stand-in records the argv, stdin, environment, working directory and timing the service gave it and answers what a test scripted, so this file
proves the transport: fixed argv, minimal environment, auth and allowlist order, strict query validation, delivery and withheld shapes, busy and
deadline behavior, concurrency, logs. It does not prove the pipeline: the real installed `zoop-ai-graph` is in `pipeline_tests/test_graph_real_cli.py`
and a real Neo4j in `scripts/graph_service_smoke.py`.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from graph_support import (GRAPH_DIGEST, OTHER_VERSION, PAYLOAD_DIGEST, PRIVATE_KEYS, VERSION, GraphWorkspace, error_output, focus_output, focus_url,
                           read_output, status_url, version_entry, view, withheld_output)
from support import document_replay

BASE_KEYS = {"PATH", "LANG", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED", "PYTHONNOUSERSITE", "PYTHONUTF8"}
OS_ADDED = {"__CF_USER_TEXT_ENCODING", "LC_CTYPE"}   # the operating system or the interpreter may add these to any child


def workspace(tmp_path: Path, name: str = "g", **kwargs: Any) -> GraphWorkspace:
    return GraphWorkspace(tmp_path / name, **kwargs)


def tree(*paths: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for path in paths:
        for item in ([path] if path.is_file() else sorted(path.rglob("*"))):
            if item.is_file():
                found[str(item)] = hashlib.sha256(item.read_bytes()).hexdigest()
    return found


def operator_state(ws: GraphWorkspace) -> dict[str, str]:
    return tree(ws.graph_state, ws.relation_state, ws.extraction_state, ws.ingestion_state, ws.sources, ws.canonical, ws.versions)


def error_of(response) -> dict[str, Any]:
    body = response.json()
    assert body["schemaVersion"] == "zoop-ai-internal-graph-1" and set(body) == {"schemaVersion", "error"}, body
    assert set(body["error"]) == {"code", "retryable", "requestId", "runtimeCode", "field"}
    assert body["error"]["requestId"] == response.headers["x-request-id"]
    return body["error"]


def anonymous(error: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in error.items() if key != "requestId"}


# ---- off by default, auth and framing ----------------------------------------------------------------------------------

def test_without_the_group_every_graph_route_answers_409_after_authentication(start):
    service = start(replay=document_replay())
    for url in (status_url(), focus_url()):
        refused = service.request("GET", url, as_="grapher")
        assert refused.status_code == 409 and error_of(refused)["code"] == "execution_unavailable"
        assert error_of(service.request("GET", url, as_=None))["code"] == "authentication_required"
        assert error_of(service.request("GET", url, as_="reader"))["code"] == "scope_denied"   # authentication and scope come before everything


def test_authentication_scope_and_routing_use_the_graph_envelope_and_never_start_a_child(tmp_path, start):
    ws = workspace(tmp_path)
    service = start(workspace=ws)
    unauthenticated = service.request("GET", status_url(), as_=None)
    assert unauthenticated.status_code == 401 and unauthenticated.headers["www-authenticate"] == "Bearer"
    assert error_of(unauthenticated)["code"] == "authentication_required"
    assert error_of(service.request("GET", status_url(), token="u" * 43))["code"] == "authentication_required"
    for reader in ("reader", "submitter", "viewer"):   # every other scope is refused, however privileged
        denied = service.request("GET", focus_url(), as_=reader)
        assert denied.status_code == 403 and error_of(denied)["code"] == "scope_denied"
    posted = service.request("POST", status_url(), as_="grapher", body={})
    assert posted.status_code == 405 and error_of(posted)["code"] == "method_not_allowed"
    for url in ("/internal/v1/graph-versions", "/internal/v1/graph-versions/", f"{status_url()}/nodes", f"{status_url()}/focus/x"):
        missing = service.request("GET", url, as_="grapher")
        assert missing.status_code in (404, 422) and error_of(missing)["code"] in {"route_not_found", "invalid_request"}, url   # no list route exists
    assert ws.calls() == []


# ---- a current read: the exact child contract ------------------------------------------------------------------------------

def test_a_focus_runs_one_fixed_child_with_server_owned_argv_and_a_minimal_environment(tmp_path, start):
    ws = workspace(tmp_path)
    ws.script({"mode": "result", "output": focus_output(company="kr-000400", depth=3)})
    service = start(workspace=ws)
    before = operator_state(ws)
    response = service.request("GET", focus_url(company="kr-000400", depth=3), as_="grapher")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store" and response.headers["x-content-type-options"] == "nosniff"
    wire = response.json()
    expected = view("kr-000400", 3)
    assert wire["delivery"] == {"state": "current", "reason": None} and wire["publication"] == "not-published"
    assert wire["focus"] == {"companyId": "kr-000400", "depth": 3, "found": True}
    assert wire["graph"]["nodes"] == expected["nodes"] and [e["relationId"] for e in wire["graph"]["edges"]] == [e["relationId"] for e in expected["edges"]]
    assert wire["verification"]["graphDigest"] == GRAPH_DIGEST and not PRIVATE_KEYS & (set(wire) - {"versionId"})
    (call,) = ws.calls()
    assert call["argv"] == ["focus", "--state-dir", str(ws.graph_state), "--relation-state-dir", str(ws.relation_state), "--extraction-state-dir",
                            str(ws.extraction_state), "--ingestion-state-dir", str(ws.ingestion_state), "--sources", str(ws.sources),
                            "--canonical", str(ws.canonical)]
    assert json.loads(call["stdin"]) == {"schemaVersion": "zoop-graph-projection-1", "versionId": VERSION, "companyId": "kr-000400", "depth": 3}
    names = set(call["env"])
    assert BASE_KEYS | {"ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR", "ZOOP_GRAPH_AUTH", "ZOOP_GRAPH_USER", "ZOOP_GRAPH_PASSWORD"} <= names <= \
        BASE_KEYS | {"ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR", "ZOOP_GRAPH_AUTH", "ZOOP_GRAPH_USER", "ZOOP_GRAPH_PASSWORD"} | OS_ADDED
    assert not [name for name in names if name.startswith(("ZOOP_AI_SERVICE", "ZOOP_AI_LIVE", "ZOOP_AI_API", "ZOOP_AI_PROVIDER"))]   # no token digest, key or provider
    assert call["env"]["ZOOP_GRAPH_PASSWORD"] == ws.password and call["env"]["ZOOP_GRAPH_AUTH"] == "basic"
    assert Path(call["cwd"]).resolve() == (ws.state / "transport").resolve()
    assert ws.password not in json.dumps(call["argv"]) and ws.password not in call["stdin"] and ws.user not in call["stdin"]
    assert operator_state(ws) == before and not list((ws.state / "transport").iterdir())   # nothing written, no transport file left behind


def test_a_status_runs_read_and_asks_for_nothing_but_the_version(tmp_path, start):
    ws = workspace(tmp_path)
    service = start(workspace=ws)
    response = service.request("GET", status_url(), as_="grapher")
    wire = response.json()
    assert response.status_code == 200 and wire["verification"] == {"graphDigest": GRAPH_DIGEST, "payloadDigest": PAYLOAD_DIGEST, "nodes": 4, "edges": 3}
    assert not {"graph", "evidence", "focus"} & set(wire) and wire["state"] == "ready" and wire["delivery"]["state"] == "current"
    (call,) = ws.calls()
    assert call["argv"][0] == "read" and json.loads(call["stdin"]) == {"schemaVersion": "zoop-graph-projection-1", "versionId": VERSION}
    for private in ("s2-private-upstream", "reviewDigest", "attempts", "audit", "canonical", "counts", "provenance"):
        assert private not in response.text


def test_an_absent_company_is_a_verified_not_found(tmp_path, start):
    ws = workspace(tmp_path)
    ws.script({"mode": "result", "output": focus_output(company="kr-999999", depth=2)})
    wire = start(workspace=ws).request("GET", focus_url(company="kr-999999", depth=2), as_="grapher").json()
    assert wire["delivery"]["state"] == "current" and wire["focus"]["found"] is False and wire["graph"] == {"nodes": [], "edges": []} and wire["evidence"] == []


# ---- who may read which version ------------------------------------------------------------------------------------------------

def test_a_version_that_is_not_listed_for_the_principal_gets_one_answer_before_any_child(tmp_path, start):
    ws = workspace(tmp_path, versions=[version_entry(), version_entry("alpha", OTHER_VERSION)])
    service = start(workspace=ws)
    answers = []
    for as_, url in (("grapher", status_url(OTHER_VERSION)),               # exists, but listed for another principal
                     ("grapher", status_url("graph-never-existed")),
                     ("beta", status_url()),                               # a principal without any entry
                     ("grapher", focus_url(OTHER_VERSION)), ("alpha", focus_url(VERSION))):
        denied = service.request("GET", url, as_=as_)
        assert denied.status_code == 403
        answers.append(anonymous(error_of(denied)))
    assert all(answer == {"code": "version_not_allowed", "retryable": False, "runtimeCode": None, "field": None} for answer in answers)
    assert ws.calls() == []
    ws.script({"mode": "result", "output": read_output(OTHER_VERSION)})
    assert service.request("GET", status_url(OTHER_VERSION), as_="alpha").status_code == 200   # alpha's own entry works
    assert len(ws.calls()) == 1


def test_the_allowlist_is_read_on_every_request_and_a_removed_entry_takes_effect_at_once(tmp_path, start):
    ws = workspace(tmp_path)
    service = start(workspace=ws)
    assert service.request("GET", status_url(), as_="grapher").status_code == 200
    ws.write_versions([])
    assert error_of(service.request("GET", status_url(), as_="grapher"))["code"] == "version_not_allowed"
    ws.write_versions([version_entry(graph="9" * 64)])   # same version, other pinned digests: the pin is checked against what the child reports
    wire = service.request("GET", status_url(), as_="grapher").json()
    assert wire["delivery"] == {"state": "withheld", "reason": "version_pin_mismatch"} and wire["verification"] is None
    assert len(ws.calls()) == 2   # the removed entry never started a child
    ws.versions.unlink()
    unreadable = service.request("GET", status_url(), as_="grapher")
    assert unreadable.status_code == 503 and unreadable.headers["retry-after"] and error_of(unreadable)["code"] == "service_configuration_invalid"
    assert len(ws.calls()) == 2


def test_an_entry_revoked_while_the_child_runs_returns_nothing_of_its_answer(tmp_path, start):
    ws = workspace(tmp_path)
    ws.script({"mode": "result", "output": focus_output(), "rewrite": {"path": str(ws.versions), "content": json.dumps(
        {"schemaVersion": "zoop-ai-graph-versions-1", "versions": []})}})
    response = start(workspace=ws).request("GET", focus_url(), as_="grapher")
    assert response.status_code == 403 and error_of(response)["code"] == "version_not_allowed"
    assert "kr-000100" not in response.text and "ev-" not in response.text and len(ws.calls()) == 1


def test_the_digests_of_the_current_read_must_equal_the_listed_ones(tmp_path, start):
    ws = workspace(tmp_path)
    ws.script({"mode": "result", "output": focus_output(graph="1" * 64)})
    response = start(workspace=ws).request("GET", focus_url(), as_="grapher")
    wire = response.json()
    assert response.status_code == 200 and wire["delivery"] == {"state": "withheld", "reason": "version_pin_mismatch"}
    assert (wire["verification"], wire["graph"], wire["evidence"]) == (None, None, None) and "kr-000300" not in response.text


# ---- strict query validation -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=kr-000100&depth=0",
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=kr-000100&depth=4",
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=kr-000100&depth=01",
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=kr-000100&depth=1.0",
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=kr-000100&depth=%201",
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=kr-000100&depth=abc",
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=kr-000100&depth=",
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=kr-000100&depth=1&depth=2",
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=kr-000100&companyId=kr-000300&depth=1",
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=kr-000100&depth=1&extra=1",
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=kr-000100",
    f"/internal/v1/graph-versions/{VERSION}/focus?depth=1",
    f"/internal/v1/graph-versions/{VERSION}/focus",
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=&depth=1",
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=a%20b&depth=1",
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=a%2Fb&depth=1",
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=a%00b&depth=1",
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=%EA%B0%80&depth=1",
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=" + "x" * 201 + "&depth=1",
    f"/internal/v1/graph-versions/{VERSION}/focus?companyId=kr-000100&depth=1&query=MATCH%20(n)%20RETURN%20n",
    f"/internal/v1/graph-versions/{VERSION}?x=1",
    f"/internal/v1/graph-versions/{VERSION}?depth=1",
    "/internal/v1/graph-versions/bad%20id",
    f"/internal/v1/graph-versions/{'v' * 121}",
])
def test_anything_but_the_exact_query_is_422_and_never_reaches_a_child(tmp_path, start, url):
    ws = workspace(tmp_path)
    response = start(workspace=ws).request("GET", url, as_="grapher")
    error = error_of(response)
    assert response.status_code == 422 and error["code"] == "invalid_request" and error["retryable"] is False, (url, response.status_code, error)
    assert ws.calls() == []


@pytest.mark.parametrize("depth", [1, 2, 3])
def test_depths_one_to_three_are_accepted_exactly(tmp_path, start, depth):
    ws = workspace(tmp_path)
    ws.script({"mode": "result", "output": focus_output(company="kr-000400", depth=depth)})
    response = start(workspace=ws).request("GET", focus_url(company="kr-000400", depth=depth), as_="grapher")
    assert response.status_code == 200 and json.loads(ws.calls()[0]["stdin"])["depth"] == depth and isinstance(json.loads(ws.calls()[0]["stdin"])["depth"], int)


# ---- withheld, refused and unreadable answers ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("code", ["source_unauthorized", "canonical_mapping_changed", "graph_version_corrupt", "upstream_changed", "review_revision_changed"])
def test_a_withheld_answer_is_a_200_with_identity_and_a_reason_and_no_content(tmp_path, start, code):
    ws = workspace(tmp_path)
    ws.script({"mode": "result", "output": withheld_output(code=code), "exit": 2})
    service = start(workspace=ws)
    for url in (status_url(), focus_url(company="kr-000100", depth=2)):
        response = service.request("GET", url, as_="grapher")
        wire = response.json()
        assert response.status_code == 200 and wire["delivery"] == {"state": "withheld", "reason": code} and wire["publication"] == "not-published"
        assert wire["verification"] is None and wire.get("graph") is None and wire.get("evidence") is None
        for text in ("kr-000300", "ev-", "rel-", GRAPH_DIGEST):
            assert text not in response.text


def test_a_version_that_is_not_projected_yet_is_withheld_with_its_state(tmp_path, start):
    ws = workspace(tmp_path)
    ws.script({"mode": "result", "output": error_output("version_not_ready", {"state": "frozen"}), "exit": 2})
    wire = start(workspace=ws).request("GET", status_url(), as_="grapher").json()
    assert (wire["state"], wire["delivery"]) == ("frozen", {"state": "withheld", "reason": "version_not_ready"}) and wire["verification"] is None


@pytest.mark.parametrize("code,status,public,retryable", [
    ("graph_busy", 503, "runtime_busy", True), ("relation_busy", 503, "runtime_busy", True), ("ingestion_busy", 503, "runtime_busy", True),
    ("graph_unavailable", 503, "runtime_unavailable", True), ("graph_auth_failed", 503, "service_configuration_invalid", True),
    ("graph_state_missing", 503, "service_configuration_invalid", True), ("version_not_found", 404, "version_not_found", False),
    ("brand_new_code", 500, "internal_error", False)])
def test_pipeline_refusals_are_stable_codes_with_a_retry_hint_and_never_an_empty_graph(tmp_path, start, code, status, public, retryable):
    ws = workspace(tmp_path)
    ws.script({"mode": "result", "output": error_output(code, {"neo4j": "Neo.ClientError.Security.Unauthorized"}), "exit": 2})
    response = start(workspace=ws).request("GET", focus_url(), as_="grapher")
    error = error_of(response)
    assert (response.status_code, error["code"], error["retryable"]) == (status, public, retryable)
    assert ("retry-after" in response.headers) == (status == 503)
    assert "graph" not in response.json() and "Neo." not in response.text and "Unauthorized" not in response.text   # the detail is never relayed


@pytest.mark.parametrize("behavior", [
    {"mode": "raw", "raw": "not json", "exit": 0}, {"mode": "raw", "raw": "", "exit": 0}, {"mode": "raw", "raw": "{}", "exit": 0},
    {"mode": "raw", "raw": json.dumps({**read_output(), "schemaVersion": "other"}), "exit": 0},
    {"mode": "raw", "raw": json.dumps(withheld_output()), "exit": 0},          # withheld must exit 2
    {"mode": "raw", "raw": json.dumps(read_output()), "exit": 2},              # current must exit 0
    {"mode": "raw", "raw": json.dumps(read_output()), "exit": 3},
    {"mode": "raw", "raw": json.dumps(read_output()), "exit": 1},
    {"mode": "result", "output": {**read_output(), "usage": {"providerCalls": 1, "modelCalls": 0}}},
    {"mode": "result", "output": {k: v for k, v in read_output().items() if k != "verification"}},
    {"mode": "die"},
])
def test_a_malformed_or_abnormal_child_is_a_retryable_503_and_never_content(tmp_path, start, behavior):
    ws = workspace(tmp_path)
    ws.script(behavior)
    response = start(workspace=ws).request("GET", status_url(), as_="grapher")
    error = error_of(response)
    assert (response.status_code, error["code"], error["retryable"]) == (503, "runtime_unavailable", True) and response.headers["retry-after"]
    assert "verification" not in response.json() and GRAPH_DIGEST not in response.text


def test_a_child_that_misses_the_deadline_is_stopped_and_the_service_stays_usable(tmp_path, start):
    ws = workspace(tmp_path)
    ws.script({"mode": "sleep", "seconds": 60, "output": read_output()})
    service = start(workspace=ws, launcher=True, launcher_env={"ZOOP_TEST_GRAPH_DEADLINE": "1"})
    began = time.monotonic()
    response = service.request("GET", status_url(), as_="grapher")
    assert time.monotonic() - began < 20
    assert response.status_code == 503 and error_of(response)["code"] == "runtime_unavailable"
    ws.script({"mode": "result", "output": read_output()})
    assert service.request("GET", status_url(), as_="grapher").status_code == 200


def test_an_answer_that_does_not_belong_to_the_request_is_a_500_binding_mismatch(tmp_path, start):
    ws = workspace(tmp_path)
    ws.script({"mode": "result", "output": read_output(OTHER_VERSION)})
    service = start(workspace=ws)
    response = service.request("GET", status_url(), as_="grapher")
    assert response.status_code == 500 and error_of(response)["code"] == "runtime_binding_mismatch"
    ws.script({"mode": "result", "output": focus_output(company="kr-000300", depth=1), "echo": False})   # the child answers about another company
    response = service.request("GET", focus_url(company="kr-000100", depth=1), as_="grapher")
    assert response.status_code == 500 and error_of(response)["code"] == "runtime_binding_mismatch" and "kr-000300" not in response.text


# ---- concurrency ----------------------------------------------------------------------------------------------------------------------

def concurrently(service, urls: list[str]) -> list[tuple[int, str | None]]:
    results: list[tuple[int, str | None]] = [(0, None)] * len(urls)

    def get(index: int) -> None:
        response = service.client.get(urls[index], headers={"Authorization": f"Bearer {service.workspace.credentials.tokens['grapher']}"})
        results[index] = (response.status_code, response.json().get("error", {}).get("code"))

    threads = [threading.Thread(target=get, args=(index,)) for index in range(len(urls))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    return results


def overlapping(calls: list[dict[str, Any]]) -> bool:
    spans = sorted((call["t0"], call["t1"]) for call in calls)
    return any(later[0] < earlier[1] for earlier, later in zip(spans, spans[1:]))


def test_without_an_s3_group_reads_run_side_by_side_up_to_four_and_then_answer_busy(tmp_path, start):
    ws = workspace(tmp_path)
    ws.script({"mode": "sleep", "seconds": 3, "output": read_output()})
    service = start(workspace=ws)
    results = concurrently(service, [status_url()] * 6)
    ok = [r for r in results if r == (200, None)]
    busy = [r for r in results if r == (503, "service_busy")]
    assert len(ok) + len(busy) == 6 and len(ok) >= 1 and len(busy) >= 1, results
    assert overlapping(ws.calls())   # no S2/S3 group in this process: nothing to serialize against


def test_with_an_s3_group_in_the_same_process_graph_children_wait_for_its_gate_one_at_a_time(tmp_path, start):
    ws = workspace(tmp_path, with_relation=True)
    ws.script({"mode": "sleep", "seconds": 1.5, "output": read_output()})
    service = start(workspace=ws)
    results = concurrently(service, [status_url()] * 3)
    assert results == [(200, None)] * 3, results   # each waits (up to 10 s) for the gate; none is answered empty
    calls = ws.calls()
    assert len(calls) == 3 and not overlapping(calls)


# ---- logs, secrets and refusing to start -------------------------------------------------------------------------------------------------

def test_nothing_private_reaches_a_response_header_or_log_line_and_the_logged_route_is_the_template(tmp_path, start):
    ws = workspace(tmp_path)
    service = start(workspace=ws)
    responses = [service.request("GET", status_url(), as_="grapher"), service.request("GET", focus_url(), as_="grapher"),
                 service.request("GET", status_url("graph-never-existed"), as_="grapher"), service.request("GET", focus_url(depth=9), as_="grapher")]
    ws.script({"mode": "result", "output": error_output("graph_auth_failed"), "exit": 2})
    responses.append(service.request("GET", status_url(), as_="grapher"))
    secrets = ws.private_strings()
    for response in responses:
        blob = response.text + json.dumps(dict(response.headers))
        assert not [s for s in secrets if s in blob]
    service.stop()
    logs = service.logs()
    assert not [s for s in secrets if s in logs], [s for s in secrets if s in logs]
    lines = [json.loads(line) for line in service.logs("out").splitlines() if line.startswith("{") and '"event":"request"' in line]
    routes = {line["route"] for line in lines}
    assert "/internal/v1/graph-versions/{versionId}" in routes and "/internal/v1/graph-versions/{versionId}/focus" in routes
    assert not [line for line in lines if "kr-000100" in json.dumps(line)] and {line["versionId"] for line in lines if "versionId" in line} >= {VERSION}


def test_a_partial_graph_group_refuses_to_start_with_a_field_name_and_reason_only(tmp_path, start):
    ws = workspace(tmp_path)
    service = start(workspace=ws, env={"ZOOP_AI_SERVICE_GRAPH_CANONICAL": None}, wait=False)
    assert service.exited() == 78
    line = json.loads(service.logs("out").strip().splitlines()[-1])
    assert line == {"error": "service_config_invalid", "field": "ZOOP_AI_SERVICE_GRAPH_CANONICAL", "reason": "graph_group_incomplete"}
    assert not [s for s in ws.private_strings() if s in service.logs()]


def test_the_graph_group_does_not_change_the_other_families(tmp_path, start):
    """An S1 route on a service with the graph group answers exactly as before: the group adds routes, never behavior."""
    ws = workspace(tmp_path)
    service = start(workspace=ws)
    missing = service.request("GET", "/internal/v1/analysis-jobs/never-submitted", as_="alpha")
    assert missing.status_code == 404 and missing.json()["schemaVersion"] == "zoop-ai-internal-1"
    unconfigured = service.request("GET", "/internal/v1/relation-jobs/never-submitted", as_="alpha")
    assert unconfigured.status_code == 409 and unconfigured.json()["schemaVersion"] == "zoop-ai-internal-relation-1"
