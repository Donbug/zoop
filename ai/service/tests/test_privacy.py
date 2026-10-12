"""Private content, current-grant delivery, allowlisted DTOs and the absence of secrets from every response, header and log."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from support import cli, document_jobs, document_replay, live_job, merged_grants, reference
from zoop_ai_service.wire import JobView

JOBS = "/internal/v1/analysis-jobs"


def snippets(job: dict) -> list[str]:
    text = job["input"]["document"]["text"]
    return [text[:18], text[30:50], text[-18:]]


def rewrite_grants(workspace, mutate) -> None:
    registry = json.loads(workspace.grants_path.read_text(encoding="utf-8"))
    mutate(registry)
    replacement = workspace.grants_path.with_suffix(".tmp")
    replacement.write_text(json.dumps(registry), encoding="utf-8")
    os.replace(replacement, workspace.grants_path)


def ready_service(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    service.submit(job)
    service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})
    return service, job


@pytest.mark.parametrize("mutate,reason", [
    (lambda g: g[0].update(enabled=False), "source_rights_unknown_or_denied"),
    (lambda g: g[0].update(rights="denied"), "source_rights_unknown_or_denied"),
    (lambda g: g[0].update(evidence=[]), "source_rights_unknown_or_denied"),
    (lambda g: g.pop(0), "source_rights_unknown_or_denied"),
    (lambda g: g[0].update(revision="grant-synthetic-s1-2"), "grant_revision_or_source_changed"),
    (lambda g: g[0].update(sourceId="another-source"), "grant_revision_or_source_changed"),
    (lambda g: g[0].update(expiresAt="2020-01-01T00:00:00+00:00"), "source_grant_expired"),
    (lambda g: g[0].update(allowedOperations=["read", "store", "model-send"]), "source_operation_denied"),
    (lambda g: g[0].update(purposes=["document-summary"]), "source_purpose_or_recipient_denied"),
    (lambda g: g[0].update(recipients=["openai-compatible"]), "source_purpose_or_recipient_denied"),
])
def test_revoked_or_changed_authority_withholds_content_at_delivery(start, mutate, reason):
    service, job = ready_service(start)
    available = service.result(job["jobId"]).json()
    assert available["delivery"] == {"state": "available", "reason": None}
    assert all(snippet in json.dumps(available, ensure_ascii=False) for snippet in snippets(job))
    rewrite_grants(service.workspace, lambda registry: mutate(registry["grants"]))
    withheld = service.result(job["jobId"])
    body = withheld.json()
    assert withheld.status_code == 200
    assert body["delivery"] == {"state": "withheld", "reason": reason} and body["job"] is None
    assert body["status"]["state"] == "ready" and len(body["receipts"]) == 2  # accounting stays, content does not
    rendered = withheld.text
    assert not any(snippet in rendered for snippet in snippets(job)) and "artifacts" not in rendered and '"grant"' not in rendered
    # The runtime's own echo of the grant is only an execution snapshot: it still says enabled. Delivery used current authority.
    code, direct = cli(service.workspace, "get", reference(job["jobId"]))
    assert direct["grant"]["enabled"] is True and direct["state"] == "ready"
    rewrite_grants(service.workspace, lambda registry: registry.update(grants=merged_grants()["grants"]))
    assert service.result(job["jobId"]).json()["delivery"]["state"] == "available"


def test_unreadable_or_invalid_grant_registry_never_delivers_content(start):
    service, job = ready_service(start)
    original = service.workspace.grants_path.read_text(encoding="utf-8")
    for broken in ("{not json", json.dumps({"schemaVersion": "zoop-ai-s1-1", "grants": [{"grantId": "x"}]}), ""):
        service.workspace.grants_path.write_text(broken, encoding="utf-8")
        response = service.result(job["jobId"])
        assert response.status_code == 503 and response.json()["error"]["code"] == "service_configuration_invalid"
        assert response.json()["error"]["retryable"] is True and "job" not in response.json()
        assert not any(snippet in response.text for snippet in snippets(job))
        assert service.status(job["jobId"]).status_code == 200  # status carries no content and needs no grant
    service.workspace.grants_path.unlink()
    assert service.result(job["jobId"]).status_code == 503
    service.workspace.grants_path.write_text(original, encoding="utf-8")
    assert service.result(job["jobId"]).json()["delivery"]["state"] == "available"


def test_a_broken_server_input_is_a_503_not_a_client_422_at_submit(start):
    service = start(replay=document_replay())
    job = document_jobs()[0]
    service.workspace.grants_path.write_text("{not json", encoding="utf-8")
    refused = service.submit(job)
    assert refused.status_code == 503 and refused.json()["error"]["code"] == "service_configuration_invalid"
    assert refused.json()["error"]["retryable"] is True and refused.headers["Retry-After"] == "30"
    assert cli(service.workspace, "get", reference(job["jobId"]))[0] == 2  # nothing was registered
    service.workspace.grants_path.write_text(json.dumps(merged_grants()), encoding="utf-8")
    assert service.submit(job).status_code == 202


def test_no_response_header_or_log_line_holds_a_private_value(start):
    service, job = ready_service(start)
    seen = []

    def call(*args, **kwargs):
        response = service.request(*args, **kwargs)
        seen.append(response)
        return response

    other = document_jobs()[1]
    broken = copy.deepcopy(other)
    broken["input"]["document"]["sourceHash"] = "0" * 64
    call("GET", f"{JOBS}/{job['jobId']}")
    call("GET", f"{JOBS}/{job['jobId']}/result")
    call("GET", f"{JOBS}/{job['jobId']}", as_=None)
    call("GET", f"{JOBS}/{job['jobId']}", as_="reader")
    call("GET", f"{JOBS}/{job['jobId']}", as_="beta")
    call("POST", f"{JOBS}/{job['jobId']}/cancel")
    call("POST", f"{JOBS}/{job['jobId']}/recover")
    call("POST", JOBS, body=broken, key=broken["jobId"])  # a 422 whose request body holds the document text
    call("POST", JOBS, body={**job, "extra": 1}, key=job["jobId"])
    call("POST", JOBS, body=job, key=job["jobId"], headers={"Content-Type": "text/plain"})
    call("POST", JOBS, raw=b" " * 2_000_001, key="big", headers={"Content-Type": "application/json"})
    call("POST", JOBS, body=job, key=job["jobId"], as_="beta")
    call("GET", "/openapi.json", as_=None)
    for response in seen:
        assert response.headers.get("cache-control") == "no-store"
        error = response.json().get("error") if response.status_code >= 400 else None
        if error:
            assert set(error) == {"code", "retryable", "requestId", "runtimeCode", "field"}  # no message, stack, path or text
    corpus = [json.dumps(dict(r.headers)) for r in seen] + [r.text for r in seen if r.status_code >= 400] + [service.logs()]
    for private in service.workspace.private_strings():
        assert not any(private in text for text in corpus), private
    logs = service.logs()
    for snippet in snippets(job) + snippets(other):
        assert snippet not in logs
    for forbidden in ("Authorization", "Bearer", "Traceback", "sourceHash", "ZOOP_AI_"):
        assert forbidden not in logs
    # Every log line is a JSON object of stable fields only.
    assert service.logs("err").strip() == ""
    for line in service.logs("out").splitlines():
        record = json.loads(line)
        assert set(record) <= {"ts", "event", "requestId", "principal", "method", "route", "jobId", "status", "error", "errorClass",
                               "runtime", "problem", "durationMs", "principals", "live", "replay", "requeuedInFlight", "command",
                               "outcome", "runtimeExit", "runtimeCode"}
    # The service ledger holds owner/idempotency/dispatch state only, never document text.
    ledger = Path(service.workspace.state)
    raw = b"".join(path.read_bytes() for path in ledger.glob("service.sqlite3*"))
    assert raw and not any(snippet.encode() in raw for snippet in snippets(job))


def test_runtime_stderr_and_paths_are_never_relayed(start):
    service, job = ready_service(start)
    worker = service.workspace.worker
    for suffix in ("-wal", "-shm"):
        (worker / f"worker.sqlite3{suffix}").unlink(missing_ok=True)
    (worker / "worker.sqlite3").write_bytes(b"this is not a database " * 200)  # the runtime now dies with a traceback on stderr
    responses = [service.status(job["jobId"]), service.result(job["jobId"]), service.cancel(job["jobId"]), service.recover(job["jobId"]),
                 service.submit(job)]
    for response in responses:
        assert response.status_code == 503 and response.json()["error"]["code"] == "runtime_unavailable"
        assert response.json()["error"]["retryable"] is True and response.headers["Retry-After"] == "2"
    corpus = "\n".join([r.text + json.dumps(dict(r.headers)) for r in responses] + [service.logs()])
    for leaked in (str(worker), "Traceback", "DatabaseError", "sqlite3", "not a database"):
        assert leaked not in corpus


def real_get(service, job):
    code, direct = cli(service.workspace, "get", reference(job["jobId"]))
    assert code == 0
    return direct


def test_the_runtime_view_is_an_allowlist_that_drops_extras_and_redacts_free_text(start):
    service, job = ready_service(start)
    direct = real_get(service, job)
    assert JobView.model_validate(direct).wire() == direct  # a faithful runtime payload passes through unchanged
    tainted = copy.deepcopy(direct)
    tainted.update(receipt={"raw": "provider receipt"}, content="model reply", fence=3, fixtureDigest="f" * 64, path="/private/path")
    tainted["calls"][0].update(receipt="raw", content="reply", fixtureDigest="f", fence=1, ordinal=0)
    tainted["calls"][0]["config"]["apiKey"] = "k-secret"
    tainted["calls"][0]["error"] = "ProviderError: Authorization: Bearer secret at /private/path"
    tainted["grant"]["internalNote"] = "secret"
    tainted["phase"] = "stack trace here\nline two"
    cleaned = JobView.model_validate(tainted).wire()
    rendered = json.dumps(cleaned, ensure_ascii=False)
    for leaked in ("provider receipt", "model reply", "/private/path", "k-secret", "secret", "Bearer", "fixtureDigest", "fence", "ordinal"):
        assert leaked not in rendered
    assert cleaned["calls"][0]["error"] == "redacted" and cleaned["phase"] == "redacted"
    for key in ("jobId", "inputDigest", "calls", "grant", "usage", "input"):
        broken = copy.deepcopy(direct)
        del broken[key]
        with pytest.raises(ValidationError):
            JobView.model_validate(broken)  # a missing key fails closed instead of being invented
    nested = copy.deepcopy(direct)
    del nested["calls"][0]["config"]["providerRevision"]
    with pytest.raises(ValidationError):
        JobView.model_validate(nested)


def test_two_principals_hold_separate_deliveries(start):
    service, job = ready_service(start)
    sentiment = document_jobs()[1]
    service.submit(sentiment, as_="beta")
    service.wait_state(sentiment["jobId"], {"ready"}, dispatch={"idle"}, as_="beta")
    mine, theirs = service.result(job["jobId"]).json(), service.result(sentiment["jobId"], as_="beta").json()
    assert mine["job"]["input"]["kind"] == "document-summary" and theirs["job"]["input"]["kind"] == "document-sentiment"
    assert service.result(sentiment["jobId"]).status_code == 404 and service.result(job["jobId"], as_="beta").status_code == 404


def taint(direct: dict) -> dict:
    """The real runtime payload with private/unknown protocol fields injected at every nested level."""
    tainted = copy.deepcopy(direct)
    artifact = tainted["artifacts"][0]
    artifact["receipt"] = {"raw": "provider receipt"}
    artifact["fixtureDigest"] = "f" * 64
    artifact["sourceRefs"][0]["localPath"] = "/private/path"
    artifact["validation"]["fence"] = 4
    artifact["claims"][0]["internalNote"] = "note"
    artifact["result"]["citations"][0]["debug"] = "dbg"
    artifact["provenance"]["token"] = "tok"
    tainted["input"]["workerPath"] = "/private/worker"
    tainted["input"]["input"]["secretKey"] = "k"
    tainted["input"]["input"]["document"]["cachePath"] = "/private/cache"
    tainted["input"]["input"]["company"]["owner"] = "x"
    tainted["input"]["input"]["document"]["rawLocators"][0]["handle"] = "h"
    tainted["input"]["provenance"]["envName"] = "e"
    return tainted


def test_nested_input_and_artifacts_are_projected_strictly(start):
    service, job = ready_service(start)
    direct = real_get(service, job)
    cleaned = JobView.model_validate(taint(direct)).wire()
    assert cleaned == direct  # every injected nested field is dropped, nothing legitimate is lost
    rendered = json.dumps(cleaned, ensure_ascii=False)
    for leaked in ("provider receipt", "/private", "internalNote", "dbg", "tok", "fixtureDigest", "secretKey", "envName", '"fence"'):
        assert leaked not in rendered
    for path in (("artifacts", 0, "inputDigest"), ("artifacts", 0, "validation", "exact"), ("artifacts", 0, "result", "claims"),
                 ("artifacts", 0, "sourceRefs", 0, "text"), ("input", "input", "document", "text"), ("input", "input", "company"),
                 ("input", "provenance", "sourceKind"), ("input", "mode")):
        broken = copy.deepcopy(direct)
        node = broken
        for step in path[:-1]:
            node = node[step]
        del node[path[-1]]
        with pytest.raises(ValidationError):
            JobView.model_validate(broken)
    typed = copy.deepcopy(direct)
    typed["artifacts"][0]["result"]["citations"][0]["start"] = "1"  # strict: no coercion of a malformed required field
    with pytest.raises(ValidationError):
        JobView.model_validate(typed)


def test_the_served_result_is_exactly_the_published_worker_contract_for_every_kind(start):
    from conftest import outlook_verify_replay
    from support import combined_replay, outlook_job, semantic_job_and_entry
    from zoop_ai.contracts import JobResult
    service = start(replay=combined_replay())
    verify, _ = semantic_job_and_entry()
    jobs = [*document_jobs(), outlook_job(), verify]
    for job in jobs:
        service.submit(job)
    for job in jobs:
        service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"}, timeout=90)
        served = service.result(job["jobId"]).json()["job"]
        assert served == cli(service.workspace, "get", reference(job["jobId"]))[1]
        JobResult.model_validate(served)  # the worker's own strict, extra-forbidding model is the schema the OpenAPI references
    kinds = {service.result(job["jobId"]).json()["job"]["input"]["kind"] for job in jobs}
    assert kinds == {"document-summary", "document-sentiment", "semantic-verification", "briefing-outlook"}


def test_view_models_mirror_the_worker_contract_field_for_field():
    from zoop_ai import contracts
    from zoop_ai_service import wire
    pairs = {"ProvenanceView": "Provenance", "RawLocatorView": "RawLocator", "DocumentView": "Document", "CompanyView": "Company",
             "EvidenceRefView": "EvidenceRef", "ClaimView": "Claim", "SummaryView": "SummaryAnswer", "SentimentView": "SentimentAnswer",
             "ClaimVerdictView": "ClaimVerdict", "VerificationView": "VerificationAnswer", "JobInputView": "JobInput",
             "OutlookAnswerView": "OutlookAnswer", "OutlookIssueView": "OutlookIssue", "OutlookInputView": "OutlookInput",
             "SubmitView": "Submit", "ValidationView": "Validation", "ArtifactView": "AnalysisArtifact"}
    for ours, theirs in pairs.items():
        ours_schema = getattr(wire, ours).model_json_schema(by_alias=True)
        theirs_schema = getattr(contracts, theirs).model_json_schema(by_alias=True)
        assert set(ours_schema["properties"]) == set(theirs_schema["properties"]), ours
        assert set(ours_schema.get("required", [])) == set(theirs_schema.get("required", [])), ours


def test_queued_live_job_content_is_withheld_until_the_recipient_is_provable(start, provider, live):
    workspace, env = live()
    service = start(workspace=workspace, env=env)
    gate = provider.gate("document_summary")
    first, second = live_job(job_id="live-first"), live_job(document_jobs()[1], job_id="live-second")
    service.submit(first)
    assert gate.entered.wait(30)  # the single dispatcher is busy: the second job waits with no call and no recipient evidence
    assert service.submit(second).status_code == 202
    original = workspace.grants_path.read_text(encoding="utf-8")
    for label, mutate in (("valid current grant", lambda g: None), ("no recipients at all", lambda g: g[0].update(recipients=[]))):
        rewrite_grants(workspace, lambda registry: mutate(registry["grants"]))
        response = service.result(second["jobId"])
        body = response.json()
        assert response.status_code == 200 and body["job"] is None and body["delivery"]["state"] == "withheld", label
        assert body["receipts"] == [] and not any(snippet in response.text for snippet in snippets(second)), label
    workspace.grants_path.write_text(original, encoding="utf-8")
    assert service.result(second["jobId"]).json()["delivery"] == {"state": "withheld", "reason": "recipient_unproven"}
    gate.release()
    service.wait_state(first["jobId"], {"ready"}, dispatch={"idle"}, timeout=60)
    assert service.result(first["jobId"]).json()["delivery"]["state"] == "available"  # calls now prove the recipient
    rewrite_grants(workspace, lambda registry: registry["grants"][0].update(recipients=["authored-replay", "openai-compatible"]))
    assert service.result(first["jobId"]).json()["delivery"]["reason"] == "source_purpose_or_recipient_denied"


@pytest.mark.parametrize("bad", [[], {}, ["known"]])
def test_a_registry_that_becomes_malformed_while_serving_is_a_retryable_503_and_leaks_nothing(start, bad):
    service, job = ready_service(start)
    rewrite_grants(service.workspace, lambda registry: registry["grants"][0].update(rights=bad))
    response = service.result(job["jobId"])
    body = response.json()
    assert response.status_code == 503 and body["error"]["code"] == "service_configuration_invalid" and body["error"]["retryable"] is True
    assert set(body["error"]) == {"code", "retryable", "requestId", "runtimeCode", "field"} and "job" not in body
    assert not any(snippet in response.text for snippet in snippets(job))
    assert "Traceback" not in service.logs() and service.status(job["jobId"]).status_code == 200
    service.workspace.grants_path.write_text(json.dumps(merged_grants()), encoding="utf-8")
    assert service.result(job["jobId"]).json()["delivery"]["state"] == "available"
