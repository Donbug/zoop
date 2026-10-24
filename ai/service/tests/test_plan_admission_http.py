"""Real ASGI routes and real SQLite authority; no fake facade or verifier.

These tests exercise framing/auth/policy errors without spawning any child. The
actual installed verifier/admission/replay/no-dispatch proof is in pipeline_tests.
"""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from support import Workspace
from test_extraction_unit import extraction_env, relation_part
from zoop_ai_service.app import create_app
from zoop_ai_service.config import load
from zoop_ai_service.ledger import ProcessLock
from zoop_ai_service.openapi_doc import plan_examples
from zoop_ai_service.plan_admission import PlanAdmissionService
from zoop_ai_service.plan_authority import PlanAuthority
from zoop_ai_service.plan_wire import (MAX_BODY, MAX_COUNTER, PlanAdmissionEnvelope, PlanErrorEnvelope, PlanPolicyState,
                                       PlanPolicyUpdate, parse_plan_policy)

ADMIT = "/internal/v1/plan-admissions"
POLICY = "/internal/v1/plan-admission-policy"
REFERENCE = {"schemaVersion": "zoop-ai-plan-admission-1", "planId": "s2plan-" + "a" * 64, "planDigest": "b" * 64}
DISABLED = {"schemaVersion": "zoop-ai-plan-policy-1", "enabled": False}


def headers(ws, principal="alpha", **extra):
    return {"Authorization": "Bearer " + ws.credentials.tokens[principal], "X-Request-ID": "request-plan-test", **extra}


def workspace(root):
    ws = Workspace(root)
    ws.credentials.scopes["alpha"] += ["plan.admit", "plan.read"]
    ws.credentials.tokens["operator"] = "t" + "synthetic-policy-operator-" * 3
    ws.credentials.scopes["operator"] = ["plan.policy"]
    return ws


@pytest.fixture
def online(tmp_path):
    ws = workspace(tmp_path)
    env = extraction_env(ws, tmp_path)
    env.update(relation_part(tmp_path))
    plans = tmp_path / "plans"
    plans.mkdir()
    env.update(ZOOP_AI_SERVICE_PLAN_ADMISSION="1", ZOOP_AI_SERVICE_PLAN_ROOT=str(plans))
    env.pop("ZOOP_AI_SERVICE_EXTRACTION_APPROVALS")
    env.pop("ZOOP_AI_SERVICE_RELATION_UPSTREAMS")
    config = load(env)
    with ProcessLock(config.state_dir):
        pass
    authority = PlanAuthority(config)
    app = create_app(SimpleNamespace(config=config), plans=PlanAdmissionService(config, authority))
    with TestClient(app) as client:
        yield ws, client, authority
    authority.close()


def error(response, status, code):
    assert response.status_code == status
    value = response.json()
    PlanErrorEnvelope.model_validate(value)
    assert set(value) == {"schemaVersion", "error"}
    assert value["error"]["code"] == code
    assert value["error"]["requestId"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "server" not in response.headers
    return value["error"]


@pytest.mark.parametrize("method,path,principal", [("POST", ADMIT, "alpha"), ("GET", ADMIT + "/bad", "alpha"),
                                                   ("GET", POLICY, "operator"), ("PUT", POLICY, "operator")])
def test_authentication_and_scope_precede_disabled_facade_and_framing(tmp_path, method, path, principal):
    ws = workspace(tmp_path)
    config = load(ws.env())
    before = sorted(p.name for p in ws.state.iterdir())
    with TestClient(create_app(SimpleNamespace(config=config))) as client:
        error(client.request(method, path, content=b"not-json", headers={"Content-Length": "999999999"}), 401, "authentication_required")
        error(client.request(method, path, content=b"not-json", headers=headers(ws, "reader")), 403, "scope_denied")
        denied = client.request(method, path, content=b"not-json", headers=headers(ws, principal))
        error(denied, 409, "execution_unavailable")
    assert sorted(p.name for p in ws.state.iterdir()) == before
    assert not (ws.state / "plan-authority.sqlite3").exists()


def test_app_token_cannot_read_or_write_policy_and_operator_cannot_admit(online):
    ws, client, authority = online
    for method in ("GET", "PUT"):
        error(client.request(method, POLICY, content=b"bad", headers=headers(ws)), 403, "scope_denied")
    error(client.post(ADMIT, json=REFERENCE, headers=headers(ws, "operator")), 403, "scope_denied")
    assert authority.policy_status()["revision"] == 0


@pytest.mark.parametrize("raw", [b"[]", b"{}", b"\xff", b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}',
                                  b'{"schemaVersion":"zoop-ai-plan-admission-1","planId":"x","planId":"x"}',
                                  json.dumps({**REFERENCE, "planPath": "/private/not-an-input"}).encode(),
                                  json.dumps({**REFERENCE, "planDigest": True}).encode(),
                                  json.dumps({"schema_version": REFERENCE["schemaVersion"], "plan_id": REFERENCE["planId"], "plan_digest": REFERENCE["planDigest"]}).encode()],
                         ids=["array", "missing", "utf8", "nan", "infinity", "overflow", "duplicate", "path", "bool", "python-alias"])
def test_exact_duplicate_free_finite_utf8_reference_body(online, raw):
    ws, client, authority = online
    response = client.post(ADMIT, content=raw, headers=headers(ws, **{"Content-Type": "application/json", "Idempotency-Key": REFERENCE["planId"]}))
    error(response, 422, "invalid_request")
    assert "/private" not in response.text
    assert authority.policy_status()["usage"] == {"plans": 0, "units": 0}


@pytest.mark.parametrize("suffix", ["", "?planDigest=" + "b" * 64 + "&planDigest=" + "b" * 64,
                                    "?planDigest=" + "b" * 64 + "&path=ignored", "?planDigest=BAD"])
def test_exact_query_requires_digest_once_without_unknown_keys(online, suffix):
    ws, client, _ = online
    error(client.get(ADMIT + "/" + REFERENCE["planId"] + suffix, headers=headers(ws)), 422, "invalid_request")


def test_unknown_admission_is_closed_404_not_empty_success(online):
    ws, client, _ = online
    response = client.get(ADMIT + "/" + REFERENCE["planId"], params={"planDigest": REFERENCE["planDigest"]}, headers=headers(ws))
    assert error(response, 404, "admission_not_found")["retryable"] is False


def test_bounded_headers_media_type_and_exact_admission_key(online):
    ws, client, _ = online
    base = headers(ws, **{"Idempotency-Key": REFERENCE["planId"]})
    error(client.post(ADMIT, content=b"{}", headers={**base, "Content-Type": "text/plain"}), 415, "unsupported_media_type")
    error(client.post(ADMIT, json=REFERENCE, headers=headers(ws)), 422, "invalid_request")
    error(client.post(ADMIT, json=REFERENCE, headers={**base, "Idempotency-Key": "s2plan-" + "c" * 64}), 422, "invalid_request")
    error(client.post(ADMIT + "?x=y", json=REFERENCE, headers=base), 422, "invalid_request")
    error(client.post(ADMIT, content=b"x" * (MAX_BODY + 1), headers={**base, "Content-Type": "application/json"}), 413, "request_too_large")
    duplicate = [*base.items(), ("Content-Type", "application/json"), ("Idempotency-Key", REFERENCE["planId"])]
    error(client.post(ADMIT, content=b"{}", headers=duplicate), 422, "invalid_request")
    repeated_length = [*base.items(), ("Content-Type", "application/json"), ("Content-Length", "2"), ("Content-Length", "2")]
    error(client.post(ADMIT, content=b"{}", headers=repeated_length), 422, "invalid_request")


def test_configured_without_policy_refuses_without_verifier_or_quota(online):
    ws, client, authority = online
    response = client.post(ADMIT, json=REFERENCE, headers=headers(ws, **{"Idempotency-Key": REFERENCE["planId"]}))
    assert error(response, 409, "admission_disabled")["retryable"] is False
    assert authority.policy_status()["usage"] == {"plans": 0, "units": 0}
    assert list((ws.root / "plans").iterdir()) == []
    assert not list(ws.state.glob("*jobs.sqlite3"))


def test_real_policy_cas_historical_receipt_and_exact_operation_identity(online):
    ws, client, authority = online
    operator = headers(ws, "operator")
    initial = client.get(POLICY, headers=operator)
    assert initial.status_code == 200
    assert PlanPolicyState.model_validate(initial.json()).revision == 0
    assert initial.headers["etag"] == '"plan-policy-0-none"'
    put = {**operator, "If-Match": initial.headers["etag"], "Idempotency-Key": "disable-1"}
    first = client.put(POLICY, json=DISABLED, headers=put)
    assert first.status_code == 200
    receipt = PlanPolicyUpdate.model_validate(first.json())
    assert receipt.changed and receipt.revision == 1
    current = client.get(POLICY, headers=operator)
    assert current.json()["status"] == "disabled"
    assert current.headers["etag"] == f'"plan-policy-1-{receipt.policy_digest}"'
    same = client.put(POLICY, json=DISABLED, headers={**put, "If-Match": current.headers["etag"], "Idempotency-Key": "disable-2"})
    assert same.status_code == 200 and same.json()["changed"] is False and same.json()["revision"] == 1
    replay = client.put(POLICY, json=DISABLED, headers=put)
    assert replay.status_code == 200 and replay.json() == first.json()
    conflict = client.put(POLICY, json=DISABLED, headers={**put, "If-Match": current.headers["etag"]})
    assert error(conflict, 409, "idempotency_conflict")["retryable"] is False
    stale = client.put(POLICY, json=DISABLED, headers={**put, "Idempotency-Key": "new-stale"})
    assert error(stale, 412, "policy_conflict")["retryable"] is False
    assert authority.policy_status()["usage"] == {"plans": 0, "units": 0}


@pytest.mark.parametrize("body", [{**DISABLED, "principal": "alpha"}, {**DISABLED, "enabled": 0},
                                   {**DISABLED, "enabled": "false"}, {**DISABLED, "extra": None}])
def test_raw_closed_policy_body_rejects_unknown_or_coerced_fields(online, body):
    ws, client, authority = online
    response = client.put(POLICY, json=body, headers=headers(ws, "operator", **{"If-Match": '"plan-policy-0-none"', "Idempotency-Key": "bad-policy"}))
    error(response, 422, "invalid_request")
    assert authority.policy_status()["revision"] == 0


@pytest.mark.parametrize("tag", ["*", 'W/"plan-policy-0-none"', "plan-policy-0-none", '"plan-policy-00-none"',
                                 '"plan-policy-0-none", "plan-policy-1-' + "a" * 64 + '"'])
def test_policy_if_match_is_one_exact_strong_etag(online, tag):
    ws, client, _ = online
    error(client.put(POLICY, json=DISABLED, headers=headers(ws, "operator", **{"If-Match": tag, "Idempotency-Key": "bad-etag"})), 422, "invalid_request")


def test_generated_public_examples_are_closed_and_unit_bound():
    sample = plan_examples()
    receipt = PlanAdmissionEnvelope.model_validate(sample["admitted"])
    assert receipt.manifest.units[0].relation_submit.upstream.job_id == receipt.manifest.units[0].unit_key
    with pytest.raises(ValidationError):
        PlanAdmissionEnvelope.model_validate({**sample["admitted"], "observedAt": "not-a-field"})
    wrong = copy.deepcopy(sample["admitted"])
    wrong["manifest"]["units"][0]["relationSubmit"]["upstream"]["inputDigest"] = "f" * 64
    with pytest.raises(ValidationError):
        PlanAdmissionEnvelope.model_validate(wrong)
    with pytest.raises(ValidationError):
        PlanPolicyState.model_validate({**sample["unconfigured"], "usage": {"plans": MAX_COUNTER + 1, "units": 0}})
    assert parse_plan_policy(json.dumps(DISABLED).encode()) == DISABLED


@pytest.mark.parametrize("change", [
    {"limits": {"maxPlans": True, "maxUnits": 1}},
    {"limits": {"maxPlans": MAX_COUNTER + 1, "maxUnits": 1}},
    {"sourceIds": ["source", "source"]},
    {"expiresAt": "2099-01-01T01:00:00+01:00"},
    {"runtime": {"kind": "live", "liveRuntimeIdentity": "a" * 64, "producerReplayDigest": "b" * 64}},
    {"topic": {"producerVersion": "zoop-topic-replay-producer-1"}},
])
def test_enabled_policy_nested_contract_is_validated_before_cas(online, change):
    ws, client, authority = online
    policy = {
        "schemaVersion": "zoop-ai-plan-policy-1", "enabled": True, "principal": "alpha", "sourceIds": ["source"],
        "sourceKind": "synthetic", "expiresAt": "2099-01-01T00:00:00Z", "promptVersion": "prompt-1",
        "catalogueDigest": "a" * 64, "snapshotDigest": "b" * 64, "topic": None,
        "runtime": {"kind": "replay", "producerReplayDigest": "c" * 64, "topicReplayDigest": None,
                    "relationReplayDigest": "d" * 64, "relationVerifierReplayDigest": "e" * 64},
        "limits": {"maxPlans": 1, "maxUnits": 1}, **change}
    response = client.put(POLICY, json=policy, headers=headers(ws, "operator", **{
        "If-Match": '"plan-policy-0-none"', "Idempotency-Key": "invalid-enabled-policy"}))
    error(response, 422, "invalid_request")
    assert authority.policy_status()["revision"] == 0


def test_policy_duplicate_nested_keys_and_headers_are_not_normalized(online):
    ws, client, authority = online
    base = headers(ws, "operator", **{"Content-Type": "application/json", "If-Match": '"plan-policy-0-none"',
                                     "Idempotency-Key": "duplicate-policy"})
    raw = b'{"schemaVersion":"zoop-ai-plan-policy-1","enabled":false,"enabled":false}'
    error(client.put(POLICY, content=raw, headers=base), 422, "invalid_request")
    repeated = [*base.items(), ("If-Match", '"plan-policy-0-none"')]
    error(client.put(POLICY, content=json.dumps(DISABLED).encode(), headers=repeated), 422, "invalid_request")
    assert authority.policy_status()["revision"] == 0
