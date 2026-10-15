"""POST validation, idempotency and request limits against the real service and real runtime."""
from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from support import canonical, cli, document_jobs, document_replay, live_job, reference

JOBS = "/internal/v1/analysis-jobs"


def runtime_has(service, job_id: str) -> bool:
    code, body = cli(service.workspace, "get", reference(job_id))
    return code == 0


def error_code(response) -> str:
    return response.json()["error"]["code"]


def test_same_key_and_body_twice_is_202_then_200_with_one_runtime_job_and_one_dispatch(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    first, second = service.submit(job), service.submit(job)
    assert (first.status_code, second.status_code) == (202, 200)
    assert first.json()["inputDigest"] == second.json()["inputDigest"] and first.json()["acceptedAt"] == second.json()["acceptedAt"]
    final = service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})
    assert final["dispatch"]["dispatchCount"] == 1 and final["usage"]["replayCalls"] == 2
    again = service.submit(job)
    assert again.status_code == 200 and again.json()["state"] == "ready"
    assert service.status(job["jobId"]).json()["dispatch"]["dispatchCount"] == 1


def test_key_header_is_required_and_must_equal_the_body_job_id(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    missing = service.request("POST", JOBS, body=job)
    assert missing.status_code == 422 and missing.json()["error"]["field"] == "Idempotency-Key"
    mismatch = service.submit(job, key="some-other-id")
    assert mismatch.status_code == 422 and mismatch.json()["error"]["field"] == "Idempotency-Key"
    for bad in ("has space", "x" * 121, "semi;colon", "ü"):
        try:
            response = service.submit(job, key=bad)
        except Exception:
            continue  # the HTTP client itself may refuse a non-ASCII header value
        assert response.status_code == 422
    assert not runtime_has(service, job["jobId"]) and not runtime_has(service, "some-other-id")


def test_same_key_with_another_body_conflicts_without_calling_the_runtime(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    accepted = service.submit(job).json()
    other = {**job, "kind": "document-sentiment"}
    conflict = service.submit(other)
    assert conflict.status_code == 409 and error_code(conflict) == "idempotency_conflict" and conflict.json()["error"]["retryable"] is False
    code, direct = cli(service.workspace, "get", reference(job["jobId"]))
    assert direct["inputDigest"] == accepted["inputDigest"] and direct["input"]["kind"] == "document-summary"
    submits = [json.loads(line) for line in service.logs().splitlines() if line.startswith("{") and '"method":"POST"' in line]
    assert [entry["status"] for entry in submits] == [202, 409]
    assert submits[1]["runtime"] == []  # the conflict was decided from the service ledger alone


def test_strict_envelope_extra_fields_duplicates_and_encoding(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    body = canonical(job)
    cases = {
        "extra top-level field": canonical({**job, "extra": 1}).encode(),
        "missing field": canonical({k: v for k, v in job.items() if k != "provenance"}).encode(),
        "wrong schemaVersion": canonical({**job, "schemaVersion": "zoop-ai-s1-2"}).encode(),
        "unknown kind": canonical({**job, "kind": "chat"}).encode(),
        "unknown mode": canonical({**job, "mode": "dry-run"}).encode(),
        "duplicate keys": body.replace('"mode":"replay"', '"mode":"replay","mode":"replay"').encode(),
        "invalid JSON": b"{",
        "top-level array": b"[]",
        "non-finite number": body.replace('"start":', '"start":NaN,"x":', 1).encode(),
        "invalid utf-8": body.encode()[:20] + b"\xff\xfe" + body.encode()[20:],
        "byte order mark": b"\xef\xbb\xbf" + body.encode(),
        "empty": b"",
    }
    for label, raw in cases.items():
        response = service.request("POST", JOBS, raw=raw, key=job["jobId"], headers={"Content-Type": "application/json"})
        assert response.status_code == 422 and error_code(response) == "invalid_request", label
    assert not runtime_has(service, job["jobId"])


def test_content_type_and_size_limits(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    raw = canonical(job).encode()
    for content_type in ("text/plain", "application/json; charset=latin-1", "application/jsonx", "application/json; boundary=x", ""):
        response = service.request("POST", JOBS, raw=raw, key=job["jobId"], headers={"Content-Type": content_type})
        assert response.status_code == 415 and error_code(response) == "unsupported_media_type", content_type
    ok = service.request("POST", JOBS, raw=raw, key=job["jobId"], headers={"Content-Type": "Application/JSON; charset=UTF-8"})
    assert ok.status_code == 202
    big = service.request("POST", JOBS, raw=b" " * 2_000_001, key="big-one", headers={"Content-Type": "application/json"})
    assert big.status_code == 413 and error_code(big) == "request_too_large"
    exact = service.request("POST", JOBS, raw=b" " * 2_000_000, key="exact-limit", headers={"Content-Type": "application/json"})
    assert exact.status_code == 422  # within the limit, so it reaches (and fails) JSON parsing
    chunked = service.client.post(JOBS, content=(b" " * 100_000 for _ in range(21)),
                                  headers={"Authorization": f"Bearer {service.workspace.credentials.tokens['alpha']}",
                                           "Idempotency-Key": "chunked", "Content-Type": "application/json"})
    assert chunked.status_code == 413  # no Content-Length: refused while streaming
    assert not runtime_has(service, "big-one")


def test_live_without_opt_in_and_replay_without_fixture_are_unavailable_before_any_runtime_call(start):
    service = start(replay=document_replay())
    live = copy.deepcopy(document_jobs()[0])
    live.update({"jobId": "live-without-opt-in", "mode": "live",
                 "provenance": {"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"}})
    refused = service.submit(live)
    assert refused.status_code == 409 and error_code(refused) == "execution_unavailable"
    assert not runtime_has(service, live["jobId"])
    bare = start(replay=None)
    replay_job = document_jobs()[0]
    refused = bare.submit(replay_job)
    assert refused.status_code == 409 and error_code(refused) == "execution_unavailable"
    assert not runtime_has(bare, replay_job["jobId"])


def test_runtime_rejected_input_is_422_and_releases_the_key_for_a_valid_retry(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    broken = copy.deepcopy(job)
    broken["input"]["document"]["sourceHash"] = "0" * 64  # the runtime's own integrity rule
    refused = service.submit(broken)
    body = refused.json()
    assert refused.status_code == 422 and body["error"]["code"] == "invalid_request" and body["error"]["runtimeCode"] == "input_or_configuration_invalid"
    assert not runtime_has(service, job["jobId"])
    assert service.status(job["jobId"]).status_code == 404
    # The first and only attempt was refused definitively, so nothing is held for this key: the owner (or anyone) may reuse it.
    assert service.submit(job, as_="beta").status_code == 202
    assert service.submit(job, as_="alpha").json()["error"]["code"] == "job_id_unavailable"


def test_concurrent_duplicate_requests_register_and_dispatch_exactly_once(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    with ThreadPoolExecutor(8) as pool:
        codes = sorted(pool.map(lambda _: service.submit(job).status_code, range(8)))
    assert codes == [200] * 7 + [202]
    final = service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})
    assert final["dispatch"]["dispatchCount"] == 1 and final["usage"]["replayCalls"] == 2


def test_concurrent_claims_by_two_principals_have_one_winner(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    with ThreadPoolExecutor(6) as pool:
        responses = list(pool.map(lambda index: service.submit(job, as_=("alpha", "beta")[index % 2]), range(6)))
    winners = {("alpha", "beta")[i % 2] for i, r in enumerate(responses) if r.status_code in (200, 202)}
    assert len(winners) == 1 and sum(r.status_code == 202 for r in responses) == 1
    losers = [r for i, r in enumerate(responses) if ("alpha", "beta")[i % 2] not in winners]
    assert losers and all(r.status_code == 409 and error_code(r) == "job_id_unavailable" for r in losers)
    owner = winners.pop()
    assert service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"}, as_=owner)["dispatch"]["dispatchCount"] == 1


def test_an_oversized_content_length_is_refused_immediately_without_waiting_for_the_body(start):
    import socket
    import time
    service = start(replay=document_replay())
    job = document_jobs()[0]
    token = service.workspace.credentials.tokens["alpha"]
    head = (f"POST {JOBS} HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {token}\r\nIdempotency-Key: {job['jobId']}\r\n"
            "Content-Type: application/json\r\nContent-Length: 2000001\r\n\r\n{").encode()
    began = time.monotonic()
    with socket.create_connection(("127.0.0.1", service.workspace.port), timeout=5) as stalled:
        stalled.sendall(head)  # headers and one byte only; the client then goes quiet and keeps the connection open
        reply = b""
        while b"\r\n\r\n" not in reply or b"request_too_large" not in reply:
            reply += stalled.recv(65536)
    assert reply.startswith(b"HTTP/1.1 413") and b"request_too_large" in reply
    assert time.monotonic() - began < 3
    assert not runtime_has(service, job["jobId"])
    # Authentication still comes first: an unauthenticated oversized upload is a 401, not a 413.
    with socket.create_connection(("127.0.0.1", service.workspace.port), timeout=5) as quiet:
        quiet.sendall(head.replace(token.encode(), b"u" * 43))
        assert quiet.recv(65536).startswith(b"HTTP/1.1 401")


NATIVE = {"ZOOP_AI_VERIFY_PROVIDER": "typesafe-native", "TYPESAFE_API_KEY": "synthetic-jev-key", "TYPESAFE_BASE_URL": "http://127.0.0.1:9/v1",
          "TYPESAFE_VALIDATION_MODEL": "jev-1.14.0", "ZOOP_AI_VERIFY_MODEL": None}


@pytest.mark.parametrize("broken,code", [
    ({"TYPESAFE_VALIDATION_MODEL": "jev-latest"}, "native_model_unsupported"),
    ({"ZOOP_AI_VERIFY_MODEL": "synthetic-verify-model"}, "native_verify_stale_model_setting"),
    ({"ZOOP_AI_VERIFY_REASONING_EFFORT": "high"}, "native_verify_stale_effort_setting"),
])
def test_a_definitely_invalid_native_configuration_is_409_unavailable_releases_the_key_and_a_corrected_retry_is_accepted(
        start, live, broken, code):
    workspace, base = live()
    service = start(workspace=workspace, env={**base, **NATIVE, **broken})
    job = live_job()
    refused = service.submit(job)
    assert refused.status_code == 409 and error_code(refused) == "execution_unavailable"
    assert refused.json()["error"]["runtimeCode"] == code and refused.json()["error"]["retryable"] is False
    assert not runtime_has(service, job["jobId"]) and service.status(job["jobId"]).status_code == 404
    # The only attempt was refused definitively, so nothing is held for this key: another principal may claim it once the
    # configuration is corrected (an unreleased reservation would answer 409 job_id_unavailable here).
    service.stop()
    fixed = start(workspace=workspace, env={**base, **NATIVE})
    assert fixed.submit(job, as_="beta").status_code == 202
