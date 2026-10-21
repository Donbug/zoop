"""S3 relation jobs over a real uvicorn process, the real installed `zoop-ai-relation` and a fresh synthetic operator world:
submit -> status -> result, idempotent reservation, request strictness, no leakage, and operator state left untouched."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from relation_support import JOB, PRIVATE_KEYS, SCHEMA, delivered_keys, inspect_direct, walk_keys

STATUS_KEYS = {"schemaVersion", "jobId", "inputDigest", "provenance", "upstream", "state", "phase", "resumeMode", "failure", "usage", "delivery",
               "dispatch", "next", "acceptedAt", "observedAt"}


def assert_clean(service, *texts: str, delivered: bool = False) -> None:
    """Neither a path nor a token is in the given texts or the service log, and no source sentence is in the log. Source sentences are also
    absent from the given texts unless `delivered` (a result body that every delivery gate allowed carries its cited quotes by design)."""
    private = service.workspace.private_strings()
    sources = service.workspace.world.source_texts
    log = service.logs()
    for text in (*texts, log):
        for value in private:
            assert value not in text, value
    for text in (log, *(() if delivered else texts)):
        for value in sources:
            assert value not in text, value


def test_submit_status_and_result_over_the_real_pipeline(start_relation, world):
    service = start_relation()
    workspace = service.workspace
    accepted = service.rsubmit()
    assert accepted.status_code == 202 and accepted.headers["location"] == f"/internal/v1/relation-jobs/{JOB}"
    body = accepted.json()
    assert set(body) == STATUS_KEYS and body["schemaVersion"] == SCHEMA and body["state"] == "queued"
    assert body["dispatch"]["state"] in {"pending", "in_flight"} and body["next"] == "wait" and body["upstream"] == world.upstream
    assert body["delivery"] == {"state": "withheld", "reason": "job_not_ready"} and body["acceptedAt"]

    final = service.rwait(states={"ready"}, dispatch={"idle"})
    assert set(final) == STATUS_KEYS and final["next"] == "fetch_result" and final["failure"] is None
    assert final["dispatch"]["dispatchCount"] == 1 and final["dispatch"]["lastOutcome"] == "exited" and final["dispatch"]["lastRuntimeCode"] is None
    assert final["usage"] == {"replayCalls": world.replay_calls, "startedWithoutReceipt": 0, "providerCalls": 0, "modelCalls": 0}
    assert final["delivery"] == {"state": "available", "reason": None} and final["upstream"] == world.upstream
    assert final["provenance"] == {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"}
    assert_clean(service, accepted.text, json.dumps(final, ensure_ascii=False))

    result = service.rresult()
    assert result.status_code == 200
    envelope = result.json()
    assert envelope["schemaVersion"] == SCHEMA and envelope["delivery"] == {"state": "available", "reason": None}
    assert set(envelope) == {"schemaVersion", "status", "delivery", "job", "receipts"} and set(envelope["status"]) == STATUS_KEYS
    assert not set(delivered_keys(envelope)) & PRIVATE_KEYS   # `approvalBasis` (closed, checked exactly) is the only place a reviewer may appear
    job = envelope["job"]
    assert job["jobId"] == JOB and job["counts"] == world.counts
    assert {r["relationCandidateId"]: r["eligibility"]["status"] for r in job["relations"]} == world.relations
    assert all(r["approved"] is False for r in job["relations"])
    assert len(envelope["receipts"]) == world.replay_calls and all(set(r) == {"stage", "state", "verdict"} for r in envelope["receipts"])
    quotes = {c["quote"] for r in job["relations"] for c in r["citations"]}
    assert world.source_texts[0] in quotes  # the exact cited sentence, delivered because every gate holds
    eligible = next(r for r in job["relations"] if r["eligibility"]["status"] == "eligible")
    assert eligible["impact"]["candidates"][0]["verdict"]["label"] == "mixed" and eligible["history"][0]["kind"] == "verdict"

    # The same job read straight from the installed CLI: every field the service relays equals the pipeline's own value.
    code, direct = inspect_direct(workspace, JOB)
    assert code == 0 and direct["delivery"]["status"] == "current" and direct["usage"]["providerCalls"] == 0 and direct["usage"]["modelCalls"] == 0
    by_id = {r["relationCandidateId"]: r for r in direct["relations"]}
    for relation in job["relations"]:
        source = by_id[relation["relationCandidateId"]]
        assert relation["eligibility"]["status"] == source["eligibility"]["status"] and relation["eligibility"]["revision"] == source["eligibility"]["revision"]
        assert [r["code"] for r in relation["eligibility"]["reasons"]] == [r["code"] for r in source["eligibility"]["reasons"]]
        assert relation["citations"] == [{k: c[k] for k in ("documentId", "documentVersion", "start", "end", "quote")} | {"error": None}
                                         for c in source["citations"]]
        assert relation["impact"]["status"] == source["impact"]["status"]
    assert job["counts"] == direct["counts"]

    # Ownership of the files: the service wrote only its own ledger and the pipeline's; nothing else.
    assert {p.name for p in workspace.relation_state.iterdir()} <= {"relation.lock", "relation.sqlite3", "relation.sqlite3-wal", "relation.sqlite3-shm"}
    assert (workspace.state / "relation-jobs.sqlite3").is_file() and list((workspace.state / "transport").iterdir()) == []
    assert_clean(service, result.text, delivered=True)


def test_the_request_is_exact_and_a_caller_names_no_path_fixture_or_live_mode(start_relation):
    service = start_relation(hold=True)  # the accepted job stays queued, so every replay below is deterministic
    first = service.rsubmit()
    assert first.status_code == 202
    again = service.rsubmit()
    assert again.status_code == 200 and again.json()["dispatch"]["dispatchCount"] == 0 and again.json()["state"] == "queued"
    assert service.rsubmit(provenance={"sourceKind": "actual", "executionMode": "replay", "recordingKind": "authored-test"}).json()["error"]["code"] == "idempotency_conflict"
    path = "/internal/v1/relation-jobs"
    body = {"schemaVersion": "zoop-relation-s3", "jobId": "other", "provenance": {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"},
            "upstream": dict(service.workspace.world.upstream)}
    mismatch = service.request("POST", path, body=body, key="not-the-job-id")
    assert mismatch.status_code == 422 and mismatch.json()["error"]["field"] == "Idempotency-Key"
    for hostile in ({"replay": "/etc/passwd"}, {"command": "rm -rf /"}, {"verifierReplay": "/tmp/x"}, {"sources": "/tmp/s"}, {"baseUrl": "http://evil.example"}):
        refused = service.rsubmit("hostile", extra=hostile)
        assert refused.status_code == 422 and refused.json()["error"]["field"] == "body", hostile
    live = service.rsubmit("hostile", provenance={"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "authored-test"})
    assert live.status_code == 422 and live.json()["error"]["field"] == "body"
    assert service.rsubmit("hostile", upstream={"jobId": "../../etc/passwd", "inputDigest": "0" * 64}).status_code == 422
    ignored = service.request("POST", path + "?replay=/etc/passwd&sources=/tmp/s", body=body | {"jobId": "query-ignored"}, key="query-ignored")
    assert ignored.status_code == 202  # a query string is not an input: the job is the allowlisted upstream on the server's own files
    assert service.rstatus("hostile").status_code == 404  # nothing was reserved by any refusal
    assert service.request("POST", path, raw=b"{}", key="x", headers={"Content-Type": "text/plain"}).status_code == 415
    assert service.request("POST", path, raw=b"{" + b" " * 2_000_100 + b"}", key="x", headers={"Content-Type": "application/json"}).status_code == 413
    assert service.request("POST", path, raw=b'{"jobId":"a","jobId":"a"}', key="a", headers={"Content-Type": "application/json"}).status_code == 422
    assert service.request("POST", path, as_="alpha", key="x").status_code == 415
    assert service.rstatus(JOB).json()["dispatch"]["dispatchCount"] == 0


def test_concurrent_identical_submits_register_one_job_and_run_it_once(start_relation, world):
    service = start_relation(hold=True)
    with ThreadPoolExecutor(6) as pool:
        codes = sorted(future.result().status_code for future in [pool.submit(service.rsubmit, "concurrent") for _ in range(6)])
    assert codes[0] in (200, 202) and codes.count(202) == 1 and set(codes) <= {200, 202}
    service.workspace.go()
    done = service.rwait("concurrent", {"ready"}, dispatch={"idle"})
    assert done["dispatch"]["dispatchCount"] == 1 and done["usage"]["replayCalls"] == world.replay_calls
    code, direct = inspect_direct(service.workspace, "concurrent")
    assert code == 0 and direct["usage"]["replayCalls"] == world.replay_calls  # one execution, not six


def test_reads_never_carry_content_and_a_withheld_state_is_visible_in_status(start_relation):
    service = start_relation(hold=True)
    service.rsubmit()
    queued = service.rstatus().json()
    assert queued["state"] == "queued" and queued["delivery"] == {"state": "withheld", "reason": "job_not_ready"}
    envelope = service.rresult().json()
    assert envelope["delivery"] == {"state": "withheld", "reason": "job_not_ready"} and envelope["job"] is None and envelope["receipts"] == []
    assert_clean(service, json.dumps(queued, ensure_ascii=False), json.dumps(envelope, ensure_ascii=False))
