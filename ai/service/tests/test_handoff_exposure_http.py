"""Real loopback HTTP and scripted subprocess adversaries; real CLI proof lives in pipeline_tests."""
import copy
import json

import pytest

from exposure_support import SCHEMA, URL, exposure_env, query, report, workspace
from handoff_support import HANDOFF, bundle_url, export_entry
from support import canonical
from test_handoff_http import BASE_KEYS, OS_ADDED, error_of, operator_state


def post(service, body=None, **kwargs):
    return service.request("POST", URL, body=query() if body is None else body, **kwargs)


def test_disabled_auth_and_scope_isolation(tmp_path, start):
    ws = workspace(tmp_path / "off")
    svc = start(workspace=ws)
    assert post(svc).status_code == 409
    ws = workspace(tmp_path / "on")
    svc = start(workspace=ws, env=exposure_env(ws))
    for principal, status, code in [(None, 401, "authentication_required"), ("handoffer", 403, "scope_denied"), ("reader", 403, "scope_denied")]:
        response = post(svc, as_=principal)
        assert response.status_code == status and error_of(response)["code"] == code
    assert error_of(svc.request("GET", bundle_url(), as_="viewer"))["code"] == "scope_denied"
    assert ws.calls() == []
    ws.write_exports([export_entry(principal="viewer")])
    assert post(svc, as_="viewer").status_code == 200


def test_complete_selection_authorization_precedes_child(tmp_path, start):
    ws = workspace(tmp_path)
    ws.write_exports([export_entry(principal="alpha"), export_entry(principal="beta", handoff_id="foreign")])
    svc = start(workspace=ws, env=exposure_env(ws))
    for ident in ("foreign", "unknown"):
        response = post(svc, query(ids=[HANDOFF, ident]))
        assert response.status_code == 403 and error_of(response)["code"] == "handoff_not_allowed"
    assert ws.calls() == []


@pytest.mark.parametrize("changed", [{"kind": "source", "sourceId": "synthetic-source"},
                                     {"kind": "document", "documentId": "document", "documentVersion": None, "rawVersion": None},
                                     {"kind": "grant", "grantId": "grant", "revision": None},
                                     {"kind": "s3-relation", "jobId": "relation", "relationCandidateId": "rc-" + "a" * 64}])
def test_exact_command_identity_relay_and_no_writes(tmp_path, start, changed):
    ws = workspace(tmp_path)
    request = query(changed)
    output = report(request)
    ws.script({"output": output})
    svc = start(workspace=ws, env=exposure_env(ws, only=True))
    before = operator_state(ws)
    response = post(svc, request)
    assert response.status_code == 200 and response.json() == {"schemaVersion": "zoop-ai-internal-handoff-1", "report": output}
    assert response.headers["cache-control"] == "no-store"
    call, = ws.calls()
    expected = ["--state-dir", str(ws.handoff_state)]
    if changed["kind"] != "s3-relation":
        expected += ["--ingestion-state-dir", str(ws.ingestion_state), "--extraction-state-dir", str(ws.extraction_state)]
    assert call["argv"] == expected and json.loads(call["stdin"]) == request
    assert set(call["env"]) <= BASE_KEYS | OS_ADDED | {"ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"}
    assert operator_state(ws) == before
    assert not list((ws.state / "transport").iterdir())


@pytest.mark.parametrize("raw", [b'{"schemaVersion":1,"schemaVersion":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":"\xff"}',
                                 b'[]', canonical(query(ids=[HANDOFF, HANDOFF])).encode(), canonical({**query(), "root": "/tmp"}).encode(),
                                 canonical({**query(), "handoffIds": []}).encode(), canonical(query(ids=[str(n) for n in range(21)])).encode(),
                                 canonical(query({"kind": "grant", "grantId": "g"})).encode()])
def test_bad_body_never_starts_child(tmp_path, start, raw):
    ws = workspace(tmp_path)
    svc = start(workspace=ws, env=exposure_env(ws))
    response = svc.request("POST", URL, raw=raw, headers={"Content-Type": "application/json"})
    assert response.status_code == 422 and error_of(response)["code"] == "invalid_request"
    assert ws.calls() == []


def test_declared_chunked_and_exact_body_limit(tmp_path, start):
    ws = workspace(tmp_path)
    svc = start(workspace=ws, env=exposure_env(ws))
    raw = canonical(query()).encode()
    exact = raw + b" " * (65536 - len(raw))
    assert svc.request("POST", URL, raw=exact, headers={"Content-Type": "application/json"}).status_code == 200
    assert svc.request("POST", URL, raw=exact + b" ", headers={"Content-Type": "application/json"}).status_code == 413
    response = svc.client.post(URL, content=iter([exact, b" "]), headers={"Authorization": "Bearer " + ws.credentials.tokens["alpha"], "Content-Type": "application/json"})
    assert response.status_code == 413 and len(ws.calls()) == 1
    assert svc.request("POST", URL, raw=raw, headers={"Content-Type": "text/plain"}).status_code == 415
    assert svc.request("POST", URL + "?all=true", body=query()).status_code == 422


@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("change_pin", [False, True])
def test_allowlist_change_during_child_suppresses_success_and_error(tmp_path, start, failed, change_pin):
    ws = workspace(tmp_path)
    replacement = [export_entry(principal="alpha", bundleDigest="f" * 64)] if change_pin else []
    output = {"schemaVersion": SCHEMA, "error": {"code": "handoff_selection_unmappable", "detail": {"handoffs": ["private"]}}} if failed else report()
    ws.script({"output": output, "exit": 2 if failed else 0,
               "rewrite": {"path": str(ws.exports), "content": canonical({"schemaVersion": "zoop-ai-handoff-exports-1", "handoffs": replacement})}})
    response = post(start(workspace=ws, env=exposure_env(ws)))
    assert response.status_code == 403 and error_of(response)["code"] == "handoff_not_allowed" and len(ws.calls()) == 1
    assert set(response.json()) == {"schemaVersion", "error"}


@pytest.mark.parametrize("path,value,code,status", [
    (("title",), "private", "runtime_contract_mismatch", 500),
    (("handoffs", 0, "url"), "private", "runtime_contract_mismatch", 500),
    (("handoffs", 0, "issues", 0, "body"), "private", "runtime_contract_mismatch", 500),
    (("handoffs", 0, "counts", "issues"), 2, "runtime_contract_mismatch", 500),
    (("handoffs", 0, "issues", 0, "reasons"), ["unknown"], "runtime_contract_mismatch", 500),
    (("handoffs", 0, "exposed"), False, "runtime_contract_mismatch", 500),
    (("handoffs", 0, "manifestDigest"), "f" * 64, "handoff_pin_mismatch", 409),
    (("changed", "sourceId"), "another", "runtime_binding_mismatch", 500),
    (("usage", "modelCalls"), True, "runtime_contract_mismatch", 500),
    (("usage", "providerCalls"), 1, "runtime_contract_mismatch", 500),
    (("scope", "notCovered"), [], "runtime_contract_mismatch", 500),
    (("handoffs",), [], "runtime_contract_mismatch", 500),
    (("identity", "recordedInIngestion"), None, "runtime_contract_mismatch", 500),
])
def test_hostile_report_never_partially_leaves(tmp_path, start, path, value, code, status):
    ws = workspace(tmp_path)
    output = report()
    node = output
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    ws.script({"output": output})
    response = post(start(workspace=ws, env=exposure_env(ws)))
    assert response.status_code == status and error_of(response)["code"] == code
    assert set(response.json()) == {"schemaVersion", "error"} and len(ws.calls()) == 1


@pytest.mark.parametrize("raw", [json.dumps(report()), canonical(report()), canonical(report()) + "\n\n", canonical(report()) + "\nextra", "x" * (6 * 1024 * 1024 + 1)],
                         ids=("noncanonical", "missing-newline", "extra-newline", "trailing-data", "oversized"))
def test_noncanonical_partial_and_oversized_stdout_is_refused(tmp_path, start, raw):
    ws = workspace(tmp_path)
    ws.script({"mode": "raw", "raw": raw, "exit": 0})
    response = post(start(workspace=ws, env=exposure_env(ws)))
    assert response.status_code == 500 and error_of(response)["code"] == "runtime_contract_mismatch" and len(ws.calls()) == 1


@pytest.mark.parametrize("runtime,status,code", [("handoff_selection_unmappable", 409, "handoff_selection_unmappable"),
    ("changed_identity_unknown", 422, "changed_identity_unknown"), ("changed_relation_unused", 422, "changed_relation_unused"),
    ("exposure_report_limit", 422, "exposure_report_limit"), ("handoff_busy", 503, "runtime_busy"),
    ("input_or_configuration_invalid", 503, "service_configuration_invalid"), ("arbitrary_private_code", 500, "internal_error")])
def test_errors_are_bounded_and_never_retried(tmp_path, start, runtime, status, code):
    ws = workspace(tmp_path)
    ws.script({"exit": 2, "output": {"schemaVersion": SCHEMA, "error": {"code": runtime, "detail": {"body": "private"}}}})
    response = post(start(workspace=ws, env=exposure_env(ws)))
    assert response.status_code == status and error_of(response)["code"] == code and len(ws.calls()) == 1
    assert error_of(response)["runtimeCode"] in (None, "handoff_busy")


def test_invalid_dependency_record_is_repairable_without_details_or_retry(tmp_path, start):
    ws = workspace(tmp_path)
    ws.script({"exit": 2, "output": {"schemaVersion": SCHEMA, "error": {
        "code": "dependency_record_invalid", "detail": {"body": "private dependency data"},
    }}})
    response = post(start(workspace=ws, env=exposure_env(ws)))
    error = error_of(response)
    assert (response.status_code, error["code"], error["retryable"]) == (503, "service_configuration_invalid", True)
    assert response.headers["retry-after"] == "30"
    assert error["runtimeCode"] is None and "private dependency data" not in response.text
    assert len(ws.calls()) == 1


def test_timeout_is_unavailable_without_retry(tmp_path, start):
    ws = workspace(tmp_path)
    ws.script({"mode": "sleep", "seconds": 2, "output": report()})
    svc = start(workspace=ws, env=exposure_env(ws), launcher=True, launcher_env={"ZOOP_TEST_HANDOFF_DEADLINE": "0.05"})
    response = post(svc)
    assert response.status_code == 503 and error_of(response)["code"] == "runtime_unavailable"
    assert ws.calls() == []


def test_twenty_ids_are_complete_and_sorted_but_narrowed_or_expanded_reports_fail(tmp_path, start):
    ws = workspace(tmp_path)
    ids = [f"handoff-{n:02d}" for n in range(20)]
    request = query(ids=list(reversed(ids)))
    ws.write_exports([export_entry(principal="alpha", handoff_id=ident) for ident in ids])
    output = report(request)
    ws.script({"output": output})
    svc = start(workspace=ws, env=exposure_env(ws))
    response = post(svc, request)
    assert response.status_code == 200 and response.json()["report"] == output
    narrower = copy.deepcopy(output)
    narrower["scope"]["handoffIds"].pop()
    narrower["handoffs"].pop()
    expanded = copy.deepcopy(output)
    expanded["scope"]["handoffIds"][-1] = "handoff-unselected"
    expanded["handoffs"][-1]["handoffId"] = "handoff-unselected"
    for invalid in (narrower, expanded):
        ws.script({"output": invalid})
        response = post(svc, request)
        assert response.status_code == 500 and error_of(response)["code"] == "runtime_binding_mismatch"
    unordered = copy.deepcopy(output)
    unordered["scope"]["handoffIds"].reverse()
    unordered["handoffs"].reverse()
    ws.script({"output": unordered})
    assert error_of(post(svc, request))["code"] == "runtime_contract_mismatch"
    assert len(ws.calls()) == 4


@pytest.mark.parametrize("mutation", ["article", "evidence", "recorded", "unbound"])
def test_relation_retraction_cannot_claim_source_withdrawal(tmp_path, start, mutation):
    ws = workspace(tmp_path)
    request = query({"kind": "s3-relation", "jobId": "relation", "relationCandidateId": "rc-" + "a" * 64})
    output = report(request)
    row = output["handoffs"][0]
    if mutation == "article":
        row["articles"] = [{"articleId": "doc-" + "a" * 64, "articleVersion": "b" * 64, "documentId": "doc", "documentVersion": "c" * 64}]
        row["counts"]["articles"] = 1
    elif mutation == "evidence":
        row["evidenceIds"] = ["ev-" + "a" * 64]
        row["counts"]["evidence"] = 1
    elif mutation == "recorded":
        output["identity"]["recordedInIngestion"] = False
    else:
        row["bound"] = False
        output["identity"]["boundInSelection"] = False
    ws.script({"output": output})
    response = post(start(workspace=ws, env=exposure_env(ws)), request)
    assert response.status_code == 500 and error_of(response)["code"] == "runtime_contract_mismatch"
