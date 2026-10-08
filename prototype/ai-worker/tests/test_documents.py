"""Public worker protocol invariants, synthetic text only; HTTP uses MockTransport."""
from __future__ import annotations

import copy
import json
import multiprocessing
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from zoop_ai.contracts import SCHEMA_VERSION, SourceGrant, Submit, digest
from zoop_ai.provider import OpenAICompatibleProvider, ReplayProvider, request_identity, stage_config
from zoop_ai.runner import Runner
from zoop_ai.store import Store, WorkerFailure

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/contracts/synthetic-document"
ROOT = Path(__file__).resolve().parents[3]


def fixture(name):
    return json.loads((FIXTURE / (name + ".json")).read_text())


def job(index=0):
    return Submit.model_validate(fixture("jobs")["jobs"][index])


def payload(request, candidate=None):
    data = {"schemaVersion": SCHEMA_VERSION, "document": request.input.document.wire(),
            "company": request.input.company.wire(),
            "grantRef": {"grantId": request.input.grant_id, "revision": request.input.grant_revision}}
    if candidate is not None:
        data["candidate"] = candidate
    return data


def recording(tmp_path, request, response=None, *, decision="supported"):
    index = next(i for i, j in enumerate(fixture("jobs")["jobs"]) if j["kind"] == request.kind)
    answer = copy.deepcopy(response or fixture("replay")["responses"][index * 2]["response"])
    verify = {"claims": [{"claimId": c["claimId"], "decision": decision, "reason": "합성 판정 표본"} for c in answer["claims"]],
              "prohibitedAdvice": False, "unsupportedCausality": False}
    stages = [(request.kind, payload(request), answer),
              ("semantic-verification", payload(request, answer), verify)]
    data = {"schemaVersion": SCHEMA_VERSION, "recordingKind": "authored-test", "responses": [
        {"stage": kind, "inputDigest": request_identity(kind, value, stage_config(kind, request.mode)), "response": result}
        for kind, value, result in stages]}
    file = tmp_path / "recording.json"
    file.write_text(json.dumps(data, ensure_ascii=False))
    return ReplayProvider(file)


def setup(tmp_path, request=None, response=None, *, decision="supported"):
    request = request or job()
    store = Store(tmp_path / "worker")
    grant = fixture("grants")["grants"][0]
    if request.mode == "live":
        config = stage_config(request.kind, "live")
        grant["recipients"] = [config.provider + ":" + config.provider_revision]
    store.register_grants([SourceGrant.model_validate(grant)])
    provider = recording(tmp_path, request, response, decision=decision)
    runner = Runner(store, provider)
    runner.submit(request)
    return runner, provider, request

def semantic_setup(tmp_path, *, decision="supported"):
    from zoop_ai.contracts import SummaryAnswer
    candidate = SummaryAnswer.model_validate(fixture("replay")["responses"][0]["response"])
    request = job().model_copy(update={"job_id": "verify-only", "kind": "semantic-verification",
                                      "input": job().input.model_copy(update={"candidate": candidate})})
    response = copy.deepcopy(fixture("replay")["responses"][1]["response"])
    for claim in response["claims"]:
        claim["decision"] = decision
    data = {"schemaVersion": SCHEMA_VERSION, "recordingKind": "authored-test", "responses": [{
        "stage": "semantic-verification",
        "inputDigest": request_identity("semantic-verification", payload(request, candidate.wire()),
                                        stage_config("semantic-verification", "replay")),
        "response": response}]}
    path = tmp_path / "verify-replay.json"
    path.write_text(json.dumps(data))
    store = Store(tmp_path / "worker")
    store.register_grants([SourceGrant.model_validate(fixture("grants")["grants"][0])])
    provider = ReplayProvider(path)
    runner = Runner(store, provider)
    runner.submit(request)
    return runner, provider, request


def test_durable_submit_run_get_cache_and_cancel(tmp_path):
    runner, provider, request = setup(tmp_path)
    assert runner.get(request.job_id).state == "queued" and provider.calls == 0
    result = runner.run(request.job_id)
    assert result.state == "ready" and len(result.artifacts) == 2 and provider.calls == 2
    summary = next(a for a in result.artifacts if a.kind == "document-summary")
    assert summary.validation.eligible and summary.result.citations[0].quote.startswith("🚀")
    assert runner.run(request.job_id).artifact_ids == result.artifact_ids and provider.calls == 2
    runner.store.close()
    restarted = Runner(Store(tmp_path / "worker"))
    assert restarted.submit(request).state == "ready"
    assert restarted.resume(request.job_id).artifact_ids == result.artifact_ids
    cached = request.model_copy(update={"job_id": "same-input-second-job"})
    restarted.submit(cached)
    hit = restarted.run(cached.job_id)
    assert hit.phase == "artifact.cache_hit" and hit.artifact_ids == result.artifact_ids
    assert hit.usage.provider_attempts == hit.usage.replay_calls == 0
    queued = request.model_copy(update={"job_id": "cancel-before-send", "kind": "document-sentiment"})
    restarted.submit(queued)
    assert restarted.cancel(queued.job_id).state == "cancelled"
    assert restarted.run(queued.job_id).usage.replay_calls == 0
    restarted.store.close()


def test_job_input_conflict_and_changed_version_model_effort_miss(tmp_path, monkeypatch):
    runner, provider, request = setup(tmp_path)
    runner.run(request.job_id)
    with pytest.raises(WorkerFailure, match="job_input_conflict"):
        runner.submit(request.model_copy(update={"kind": "document-sentiment"}))
    monkeypatch.setenv("ZOOP_AI_DOCUMENT_SUMMARY_MODEL", "other-synthetic-model")
    model_job = request.model_copy(update={"job_id": "model-change"})
    assert runner.submit(model_job).input_digest != runner.get(request.job_id).input_digest
    monkeypatch.setenv("ZOOP_AI_DOCUMENT_SUMMARY_REASONING_EFFORT", "high")
    effort_job = request.model_copy(update={"job_id": "effort-change"})
    assert runner.submit(effort_job).input_digest != runner.get(model_job.job_id).input_digest
    revised = request.input.document.model_copy(update={"document_version": "new-content-version"})
    version_job = request.model_copy(update={"job_id": "version-change", "input": request.input.model_copy(update={"document": revised})})
    assert runner.submit(version_job).input_digest != runner.get(effort_job.job_id).input_digest
    assert runner.run(version_job.job_id).state == "failed"  # fixture exhausted; never a generated fallback
    assert provider.calls == 3
    runner.store.close()


@pytest.mark.parametrize("change,reason", [("utf16", "quote_mismatch"), ("missing", "claim_citation_missing")])
def test_invalid_quote_and_claim_never_reach_semantic_call(tmp_path, change, reason):
    response = fixture("replay")["responses"][0]["response"]
    if change == "utf16":
        response["citations"][1]["start"] += 1  # emoji before this span makes UTF-16 index wrong
        response["citations"][1]["end"] += 1
    else:
        response["claims"][0]["evidenceIds"] = []
    runner, provider, request = setup(tmp_path, response=response)
    result = runner.run(request.job_id)
    assert result.state == "failed" and result.failure.code == reason
    assert result.artifacts == [] and provider.calls == 1
    assert runner.resume(request.job_id).state == "failed" and provider.calls == 1
    runner.store.close()


def test_false_factual_claim_is_semantic_hold_not_public_eligible(tmp_path):
    response = fixture("replay")["responses"][0]["response"]
    response["claims"][0]["text"] = "합성 알파는 세계 최대 기업이다."
    response["text"] = "\n".join(c["text"] for c in response["claims"] if c["assertionKind"] != "limitation")
    runner, provider, request = setup(tmp_path, response=response, decision="insufficient")
    result = runner.run(request.job_id)
    summary = next(a for a in result.artifacts if a.kind == "document-summary")
    assert result.state == "ready" and summary.validation.semantic == "hold" and not summary.validation.eligible
    assert provider.calls == 2
    runner.store.close()


def test_unclaimed_public_limitation_never_reaches_semantic_verification(tmp_path):
    response = fixture("replay")["responses"][0]["response"]
    response["limitations"].append("원문에 없는 해외 공장을 폐쇄했습니다.")
    runner, provider, request = setup(tmp_path, response=response)
    result = runner.run(request.job_id)
    assert result.state == "failed" and result.failure.code == "limitation_claim_coverage_invalid"
    assert result.artifacts == [] and provider.calls == 1
    runner.store.close()


@pytest.mark.parametrize("change", [{"rights": "unknown"}, {"enabled": False}, {"evidence": []},
    {"allowedOperations": ["read", "store"]}, {"recipients": ["unapproved-recipient"]},
    {"purposes": ["document-summary"]}, {"expiresAt": "2000-01-01T00:00:00+00:00"}])
def test_current_source_permissions_fail_closed_before_send(tmp_path, change):
    runner, provider, request = setup(tmp_path)
    grant = {**fixture("grants")["grants"][0], **change, "revision": "grant-changed"}
    runner.store.register_grants([SourceGrant.model_validate(grant)])
    result = runner.run(request.job_id)
    assert result.state == "failed" and result.artifacts == [] and provider.calls == 0
    runner.store.close()


def test_response_loss_and_process_loss_never_auto_call(tmp_path, monkeypatch):
    request = job().model_copy(update={"mode": "live", "provenance": job().provenance.model_copy(update={"execution_mode": "live", "recording_kind": "provider"})})
    monkeypatch.setenv("ZOOP_AI_DOCUMENT_SUMMARY_MODEL", "synthetic-wire-model")
    monkeypatch.setenv("ZOOP_AI_VERIFY_MODEL", "synthetic-verify-model")
    monkeypatch.setenv("ZOOP_AI_BASE_URL", "https://model.invalid/v1")
    runner, _, _ = setup(tmp_path, request)
    def lose(_):
        raise httpx.ReadTimeout("synthetic timeout")
    wire = OpenAICompatibleProvider(base_url="https://model.invalid/v1", api_key="synthetic-only", transport=httpx.MockTransport(lose))
    runner.provider, runner.live_enabled, runner.max_calls = wire, True, 3
    result = runner.run(request.job_id)
    assert result.state == "reconciling" and result.usage.input_tokens is None and result.usage.cost is None
    assert runner.resume(request.job_id).state == "reconciling" and runner.run(request.job_id).state == "reconciling" and wire.calls == 1
    wire.close()
    runner.store.close()
    restarted = Runner(Store(tmp_path / "worker"))
    assert restarted.resume(request.job_id).state == "reconciling"
    restarted.store.close()
    # A process that died after reservation but before storing any reply also cannot be declared uncharged.
    second = Store(tmp_path / "died")
    second.register_grants([SourceGrant.model_validate(fixture("grants")["grants"][0])])
    crashed = Runner(second)
    crashed.submit(job())
    cfg = stage_config("document-summary", "replay")
    second.reserve(job_id=job().job_id, stage="document-summary", request_digest="synthetic-digest", config=cfg.wire(), mode="replay", fence=0, attempt_id="attempt-crashed", fixture_digest="synthetic-fixture")
    assert crashed.run(job().job_id).state == "reconciling"
    second.close()


def test_received_receipt_storage_recovery_is_no_new_call(tmp_path, monkeypatch):
    runner, provider, request = setup(tmp_path)
    save = runner.store.save_artifact
    def fail_once(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic disk failure")
    monkeypatch.setattr(runner.store, "save_artifact", fail_once)
    before = runner.run(request.job_id)
    assert before.state == "persisting" and before.resume_mode == "save_only" and provider.calls == 2
    monkeypatch.setattr(runner.store, "save_artifact", save)
    after = Runner(runner.store).resume(request.job_id)
    assert after.state == "ready" and provider.calls == 2 and after.usage.provider_attempts == 0
    assert Runner(runner.store).resume(request.job_id).artifact_ids == after.artifact_ids
    runner.store.close()


def test_real_http_request_stage_model_effort_and_unsupported_option(tmp_path, monkeypatch):
    request = job().model_copy(update={"mode": "live", "provenance": job().provenance.model_copy(update={"execution_mode": "live", "recording_kind": "provider"})})
    monkeypatch.setenv("ZOOP_AI_DOCUMENT_SUMMARY_MODEL", "synthetic-generator")
    monkeypatch.setenv("ZOOP_AI_DOCUMENT_SUMMARY_REASONING_EFFORT", "high")
    monkeypatch.setenv("ZOOP_AI_VERIFY_MODEL", "synthetic-verifier")
    monkeypatch.setenv("ZOOP_AI_BASE_URL", "https://model.invalid/v1")
    runner, _, _ = setup(tmp_path, request)
    seen = []
    def respond(req):
        seen.append(json.loads(req.content))
        assert not runner.store.db.in_transaction
        # A second writer can commit while the request is in flight.
        other = Store(runner.store.directory)
        with other.transaction():
            pass
        other.close()
        index = 0 if len(seen) == 1 else 1
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(fixture("replay")["responses"][index]["response"], ensure_ascii=False)}}],
                                       "usage": {"prompt_tokens": 21, "completion_tokens": 13,
                                                 "prompt_tokens_details": {"cached_tokens": 3}, "completion_tokens_details": {"reasoning_tokens": 5}}})
    provider = OpenAICompatibleProvider(base_url="https://model.invalid/v1", api_key="synthetic-only", transport=httpx.MockTransport(respond))
    runner.provider, runner.live_enabled, runner.max_calls = provider, True, 2
    result = runner.run(request.job_id)
    assert result.state == "ready" and result.usage.provider_attempts == 2
    assert result.usage.input_tokens == 42 and result.usage.cached_tokens == 6 and result.usage.reasoning_tokens == 10
    assert seen[0]["model"] == "synthetic-generator" and seen[0]["reasoning_effort"] == "high"
    assert seen[1]["model"] == "synthetic-verifier" and "reasoning_effort" not in seen[1]
    assert all(s["response_format"]["json_schema"]["strict"] and s["response_format"]["json_schema"]["schema"]["additionalProperties"] is False for s in seen)
    provider.close()
    runner.store.close()
    runner, _, _ = setup(tmp_path / "unsupported", request)
    provider = OpenAICompatibleProvider(base_url="https://model.invalid/v1", api_key="synthetic-only", transport=httpx.MockTransport(lambda req: httpx.Response(400, json={"error": "unsupported option"})))
    runner.provider, runner.live_enabled, runner.max_calls = provider, True, 2
    rejected = runner.run(request.job_id)
    assert rejected.failure.code == "provider_option_unsupported" and provider.calls == 1 and rejected.artifacts == []
    runner.resume(request.job_id)
    assert provider.calls == 1
    provider.close()
    runner.store.close()


def _budget_process(directory, request_data, barrier, results):
    request = Submit.model_validate(request_data)
    store = Store(Path(directory))
    grant = fixture("grants")["grants"][0]
    config = stage_config(request.kind, "live")
    grant["recipients"] = [config.provider + ":" + config.provider_revision]
    store.register_grants([SourceGrant.model_validate(grant)])
    runner = Runner(store, live_enabled=True, max_calls=1)
    runner.submit(request)
    barrier.wait()
    response = fixture("replay")["responses"][0]["response"]
    provider = OpenAICompatibleProvider(base_url="https://model.invalid/v1", api_key="synthetic-only", transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(response, ensure_ascii=False)}}]})))
    runner.provider = provider
    result = runner.run(request.job_id)
    results.put((result.state, result.failure.code if result.failure else None, provider.calls))
    provider.close()
    store.close()


def test_global_budget_reservations_across_two_processes(tmp_path, monkeypatch):
    monkeypatch.setenv("ZOOP_AI_DOCUMENT_SUMMARY_MODEL", "synthetic-budget-model")
    monkeypatch.setenv("ZOOP_AI_VERIFY_MODEL", "synthetic-budget-verifier")
    monkeypatch.setenv("ZOOP_AI_BASE_URL", "https://model.invalid/v1")
    request = job().wire()
    request.update(mode="live", provenance={"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"})
    context = multiprocessing.get_context("spawn")
    barrier, results = context.Barrier(2), context.Queue()
    # Initialize WAL before simultaneous independent processes open the same durable ledger.
    Store(tmp_path / "global").close()
    processes = [context.Process(target=_budget_process, args=(str(tmp_path / "global"), {**request, "jobId": "budget-" + str(i)}, barrier, results)) for i in range(2)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(30)
        assert process.exitcode == 0
    observed = [results.get(timeout=5) for _ in processes]
    assert sum(row[2] for row in observed) == 1
    assert all(row[1] == "global_budget_exhausted" for row in observed)
    store = Store(tmp_path / "global")
    assert store.db.execute("SELECT COUNT(*) FROM budget_reservations").fetchone()[0] == 1
    store.close()


def test_actual_cli_submit_run_get_replay_is_durable(tmp_path):
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT / "prototype/ai-worker/src"), "PYTHONDONTWRITEBYTECODE": "1"}
    def command(name, data):
        args = [sys.executable, "-m", "zoop_ai.cli", name, "--state-dir", str(tmp_path / "cli"), "--grants", str(FIXTURE / "grants.json"), "--replay", str(FIXTURE / "replay.json")]
        result = subprocess.run(args, input=json.dumps(data, ensure_ascii=False), env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)
    for request in fixture("jobs")["jobs"]:
        ref = {"schemaVersion": SCHEMA_VERSION, "jobId": request["jobId"]}
        assert command("submit", request)["state"] == "queued"
        result = command("run", ref)
        assert result["state"] == "ready" and result["usage"]["providerAttempts"] == 0
        assert command("get", ref)["artifactIds"] == result["artifactIds"]
        assert command("resume", ref)["artifactIds"] == result["artifactIds"]


@pytest.mark.parametrize("failure", ["mismatch", "exhausted"])
def test_replay_digest_mismatch_and_exhaustion_fail_without_fallback(tmp_path, failure):
    runner, _, request = setup(tmp_path)
    data = json.loads((tmp_path / "recording.json").read_text())
    if failure == "mismatch":
        data["responses"][0]["inputDigest"] = "different-exact-input"
    else:
        data["responses"] = []
    path = tmp_path / "invalid-replay.json"
    path.write_text(json.dumps(data))
    provider = ReplayProvider(path)
    runner.provider = provider
    result = runner.run(request.job_id)
    assert result.state == "failed" and result.artifacts == []
    assert result.failure.code == ("replay_input_mismatch" if failure == "mismatch" else "replay_exhausted")
    assert runner.resume(request.job_id).state == "failed" and provider.calls == 1
    runner.store.close()


def test_separate_semantic_verification_job_is_executable(tmp_path):
    runner, provider, request = semantic_setup(tmp_path)
    result = runner.run(request.job_id)
    assert result.state == "ready" and len(result.artifacts) == 1
    assert result.artifacts[0].kind == "semantic-verification" and result.artifacts[0].validation.eligible
    assert result.usage.replay_calls == provider.calls == 1
    runner.store.close()


def test_standalone_verification_rechecks_current_grant_after_response(tmp_path, monkeypatch):
    runner, provider, request = semantic_setup(tmp_path)
    complete = provider.complete
    def revoke_after_reply(*args, **kwargs):
        reply = complete(*args, **kwargs)
        revoked = {**fixture("grants")["grants"][0], "revision": "opaque-revoked-revision", "enabled": False}
        runner.store.register_grants([SourceGrant.model_validate(revoked)])
        return reply
    monkeypatch.setattr(provider, "complete", revoke_after_reply)
    result = runner.run(request.job_id)
    assert result.state == "failed" and result.failure.code == "source_rights_unknown_or_denied"
    assert result.artifacts == [] and result.calls[0]["state"] == "received" and provider.calls == 1
    runner.store.close()


@pytest.mark.parametrize("decision,semantic", [("insufficient", "hold"), ("contradicted", "reject")])
def test_standalone_noneligible_artifact_ready_crash_resumes_without_provider_call(
    tmp_path, monkeypatch, decision, semantic
):
    runner, provider, request = semantic_setup(tmp_path, decision=decision)
    status = runner.store.status
    failed = False
    def fail_ready_once(job_id, state, phase, *args, **kwargs):
        nonlocal failed
        if state == "ready" and not failed:
            failed = True
            raise sqlite3.OperationalError("synthetic ready persistence failure")
        return status(job_id, state, phase, *args, **kwargs)
    monkeypatch.setattr(runner.store, "status", fail_ready_once)
    before = runner.run(request.job_id)
    assert before.state == "persisting" and before.resume_mode == "save_only"
    assert len(before.artifacts) == 1 and before.artifacts[0].validation.semantic == semantic
    assert not before.artifacts[0].validation.eligible and provider.calls == 1
    monkeypatch.setattr(runner.store, "status", status)
    after = runner.resume(request.job_id)
    assert after.state == "ready" and after.artifact_ids == before.artifact_ids and provider.calls == 1
    runner.store.close()


@pytest.mark.parametrize("lost_receipt", [False, True])
def test_http_received_response_storage_failure_never_charges_a_second_call(tmp_path, monkeypatch, lost_receipt):
    monkeypatch.setenv("ZOOP_AI_DOCUMENT_SUMMARY_MODEL", "synthetic-save-model")
    monkeypatch.setenv("ZOOP_AI_VERIFY_MODEL", "synthetic-save-verifier")
    monkeypatch.setenv("ZOOP_AI_BASE_URL", "https://model.invalid/v1")
    request = job().model_copy(update={"mode": "live", "provenance": job().provenance.model_copy(update={"execution_mode": "live", "recording_kind": "provider"})})
    runner, _, _ = setup(tmp_path, request)
    replies = iter(fixture("replay")["responses"][:2])
    provider = OpenAICompatibleProvider(base_url="https://model.invalid/v1", api_key="synthetic-only",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(next(replies)["response"], ensure_ascii=False)}}]})))
    runner.provider, runner.live_enabled, runner.max_calls = provider, True, 2
    method = "receive" if lost_receipt else "save_artifact"
    original = getattr(runner.store, method)
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic persistence failure")
    monkeypatch.setattr(runner.store, method, unavailable)
    failed = runner.run(request.job_id)
    monkeypatch.setattr(runner.store, method, original)
    recovered = Runner(runner.store).resume(request.job_id)
    assert provider.calls == (1 if lost_receipt else 2)
    assert recovered.usage.provider_attempts == provider.calls
    if lost_receipt:
        assert failed.state == recovered.state == "reconciling"
        assert recovered.usage.input_tokens is None and recovered.artifacts == []
    else:
        assert failed.resume_mode == "save_only" and recovered.state == "ready"
        assert len(recovered.artifacts) == 2
    provider.close()
    runner.store.close()


def test_live_recipient_is_endpoint_pinned_and_provider_cannot_silently_change(tmp_path, monkeypatch):
    monkeypatch.setenv("ZOOP_AI_DOCUMENT_SUMMARY_MODEL", "synthetic-recipient-model")
    monkeypatch.setenv("ZOOP_AI_VERIFY_MODEL", "synthetic-recipient-verifier")
    monkeypatch.setenv("ZOOP_AI_BASE_URL", "https://model.invalid/v1")
    request = job().model_copy(update={"mode": "live", "provenance": job().provenance.model_copy(update={"execution_mode": "live", "recording_kind": "provider"})})
    runner, _, _ = setup(tmp_path, request)
    provider = OpenAICompatibleProvider(base_url="https://different-model.invalid/v1", api_key="synthetic-only", transport=httpx.MockTransport(lambda req: None))
    runner.provider, runner.live_enabled, runner.max_calls = provider, True, 2
    result = runner.run(request.job_id)
    assert result.failure.code == "provider_configuration_changed" and provider.calls == 0
    assert runner.store.db.execute("SELECT COUNT(*) FROM budget_reservations").fetchone()[0] == 0
    provider.close()
    runner.store.close()
    store = Store(tmp_path / "protocol-only")
    grant = fixture("grants")["grants"][0]
    grant["recipients"] = ["openai-compatible"]  # A protocol name is not permission to send to an arbitrary endpoint.
    store.register_grants([SourceGrant.model_validate(grant)])
    runner = Runner(store, live_enabled=True, max_calls=2)
    runner.submit(request)
    assert runner.run(request.job_id).failure.code == "source_purpose_or_recipient_denied"
    store.close()


def test_replay_authority_cannot_be_used_by_a_live_http_adapter(tmp_path):
    runner, _, request = setup(tmp_path)
    provider = OpenAICompatibleProvider(base_url="https://model.invalid/v1", api_key="synthetic-only",
                                        transport=httpx.MockTransport(lambda req: None))
    runner.provider = provider
    result = runner.run(request.job_id)
    assert result.failure.code == "provider_mode_mismatch" and provider.calls == 0
    assert result.calls == [] and result.artifacts == []
    provider.close()
    runner.store.close()


def test_cancel_during_http_keeps_cost_receipt_but_blocks_late_artifacts_and_verify(tmp_path, monkeypatch):
    monkeypatch.setenv("ZOOP_AI_DOCUMENT_SUMMARY_MODEL", "synthetic-cancel-model")
    monkeypatch.setenv("ZOOP_AI_VERIFY_MODEL", "synthetic-cancel-verifier")
    monkeypatch.setenv("ZOOP_AI_BASE_URL", "https://model.invalid/v1")
    request = job().model_copy(update={"mode": "live", "provenance": job().provenance.model_copy(update={"execution_mode": "live", "recording_kind": "provider"})})
    runner, _, _ = setup(tmp_path, request)
    def late_response(req):
        assert runner.cancel(request.job_id).state == "cancelled"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(fixture("replay")["responses"][0]["response"], ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3}})
    provider = OpenAICompatibleProvider(base_url="https://model.invalid/v1", api_key="synthetic-only", transport=httpx.MockTransport(late_response))
    runner.provider, runner.live_enabled, runner.max_calls = provider, True, 2
    result = runner.run(request.job_id)
    assert result.state == "cancelled" and result.artifacts == [] and provider.calls == 1
    assert result.usage.provider_attempts == 1 and result.usage.input_tokens == 7 and result.usage.output_tokens == 3
    assert result.calls[0]["receivedAt"] is not None
    assert runner.resume(request.job_id).state == "cancelled" and provider.calls == 1
    provider.close()
    runner.store.close()
