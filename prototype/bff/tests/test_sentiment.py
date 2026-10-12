"""S1 worker→application import→stored GET. All inputs are authored synthetic data."""
from __future__ import annotations

import copy
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from zoop_bff.ai_worker import WORKER_COMMAND, AiWorkerClient, AnalysisImportError, _digest
from zoop_bff.config import BFF_ROOT
from zoop_bff.schemas import DocumentSentiment
from zoop_bff.sentiment import document_input, input_hash
from zoop_bff.statedb import dumps

FIXTURE = BFF_ROOT.parents[1] / "ai/worker/fixtures/contracts/synthetic-document"


def fixture(name):
    return json.loads((FIXTURE / (name + ".json")).read_text())

def cloned_ready_result(result, suffix):
    cloned = copy.deepcopy(result)
    cloned["jobId"] = result["jobId"] + "-" + suffix
    cloned["inputDigest"] = result["inputDigest"] + "-" + suffix
    cloned["input"]["jobId"] = cloned["jobId"]
    artifact_ids = {a["artifactId"]: a["artifactId"] + "-" + suffix for a in cloned["artifacts"]}
    attempt_ids = {c["attemptId"]: c["attemptId"] + "-" + suffix for c in cloned["calls"]}
    for call in cloned["calls"]:
        call["attemptId"] = attempt_ids[call["attemptId"]]
        call["inputDigest"] += "-" + suffix
        call["config"]["model"] += "-" + suffix
    for artifact in cloned["artifacts"]:
        artifact["artifactId"] = artifact_ids[artifact["artifactId"]]
        artifact["jobId"] = cloned["jobId"]
        artifact["inputDigest"] = cloned["inputDigest"]
        artifact["attemptId"] = attempt_ids[artifact["attemptId"]]
        artifact["dependencyRefs"] = [artifact_ids.get(value, value) for value in artifact["dependencyRefs"]]
        artifact["resultVersion"] += "-" + suffix
        call = next(c for c in cloned["calls"] if c["attemptId"] == artifact["attemptId"])
        artifact["modelConfigRevision"] = _digest(call["config"])
    cloned["artifactIds"] = [artifact_ids[value] for value in cloned["artifactIds"]]
    return cloned

def register_current_grants(kit, grants=None):
    current = grants or fixture("grants")["grants"]
    kit.services.sentiment.analysis_store.replace_current_grants(current)




def populated(make_admin, tmp_path):
    kit = make_admin(fixture("snapshot"))
    register_current_grants(kit)
    client = AiWorkerClient(state_dir=kit.state_dir, worker_state=tmp_path / "worker",
                            grants=FIXTURE / "grants.json", replay=FIXTURE / "replay.json")
    results = []
    for request in fixture("jobs")["jobs"]:
        queued = client.command("submit", request)
        imported = kit.services.sentiment.analysis_store.import_job(kit.services.provider.get(), queued)
        assert imported["status"] == "pending"
        result = client.command("run", {"schemaVersion": "zoop-ai-s1-1", "jobId": request["jobId"]})
        assert result["state"] == "ready", result
        kit.services.sentiment.analysis_store.import_job(kit.services.provider.get(), result)
        results.append(result)
    return kit, client, results


def test_two_companies_opposite_judgements_and_exact_summary_citations_reach_both_gets(make_admin, tmp_path):
    kit, client, results = populated(make_admin, tmp_path)
    before = kit.services.db.one("SELECT COUNT(*) AS n FROM document_analysis_calls")["n"]
    for company_id, label in (("SYNTH-A", "positive"), ("SYNTH-B", "negative")):
        docs = kit.client.get(f"/api/companies/{company_id}/documents")
        assert docs.status_code == 200
        doc = docs.json()["items"][0]
        assert doc["sentiment"]["label"] == label and doc["sentiment"]["companyId"] == company_id
        summary = doc["documentSummary"]
        assert summary["text"] == "\n".join(c["text"] for c in summary["claims"] if c["assertionKind"] != "limitation")
        assert doc["resultVersion"] == summary["resultVersion"] and doc["documentVersion"] == summary["documentVersion"]
        assert doc["analysisStatus"]["summary"] == doc["analysisStatus"]["sentiment"] == {"status": "available", "reason": None}
        assert summary["provenance"] == {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"}
        for citation in summary["citations"]:
            evidence = kit.client.get("/api/evidence/" + citation["evidenceId"], params={"companyId": company_id})
            assert evidence.status_code == 200
            data = evidence.json()
            assert data["quote"] == citation["quote"] and data["start"] == citation["start"] and data["end"] == citation["end"]
            assert data["documentSummary"]["resultVersion"] == summary["resultVersion"] and data["sentiment"]["label"] == label
        assert kit.client.get("/api/evidence/" + summary["citations"][0]["evidenceId"]).json()["sentiment"] is None
    restarted = kit.restart()
    assert restarted.client.get("/api/companies/SYNTH-A/documents").json()["items"][0]["documentSummary"] is not None
    assert kit.services.db.one("SELECT COUNT(*) AS n FROM document_analysis_calls")["n"] == before == 8
    kit.login()
    features = kit.client.get("/api/admin/ai-usage?window=all").json()["features"]
    for name, count in (("document-summary", 2), ("document-sentiment", 2), ("semantic-verification", 4)):
        usage = next(f for f in features if f["feature"] == name)["usage"]
        assert usage["modelCalls"] == 0 and usage["replayCalls"] == count
        assert usage["inputTokens"] is None and usage["outputTokens"] is None


def test_application_save_failure_repeat_import_does_not_call_or_charge(make_admin, tmp_path, monkeypatch):
    kit, client, results = populated(make_admin, tmp_path)
    result = results[0]
    store = kit.services.sentiment.analysis_store
    first = store.import_job(kit.services.provider.get(), client.get(result["jobId"]))
    assert store.import_job(kit.services.provider.get(), client.get(result["jobId"])) == first
    assert kit.services.db.one("SELECT COUNT(*) AS n FROM document_analysis")["n"] == 4
    assert kit.services.db.one("SELECT COUNT(*) AS n FROM document_analysis_calls")["n"] == 8
    # Force a real BFF transaction rollback before the first import into an independent app state.
    unimported = make_admin(fixture("snapshot"))
    register_current_grants(unimported)
    unimported.services.db.execute("CREATE TRIGGER synthetic_fail_import BEFORE INSERT ON document_analysis BEGIN SELECT RAISE(ABORT,'synthetic import failure'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        unimported.services.sentiment.analysis_store.import_job(unimported.services.provider.get(), result)
    assert unimported.services.db.one("SELECT COUNT(*) AS n FROM document_analysis_calls")["n"] == 0
    unimported.services.db.execute("DROP TRIGGER synthetic_fail_import")
    assert unimported.services.sentiment.analysis_store.import_job(unimported.services.provider.get(), client.get(result["jobId"]))["status"] == "available"
    assert client.get(result["jobId"])["usage"] == result["usage"]

def test_actual_cli_cache_hit_import_reuses_creator_receipts_without_duplicate_usage(make_admin, tmp_path):
    kit, client, results = populated(make_admin, tmp_path)
    original = results[0]
    request = copy.deepcopy(fixture("jobs")["jobs"][0])
    request["jobId"] = "synthetic-SYNTH-A-document-summary-cache-hit"
    assert client.command("submit", request)["state"] == "queued"
    cached = client.command("run", {"schemaVersion": "zoop-ai-s1-1", "jobId": request["jobId"]})
    assert cached["state"] == "ready" and cached["phase"] == "artifact.cache_hit"
    assert cached["artifactIds"] == original["artifactIds"] and cached["usage"]["replayCalls"] == 0
    before_calls = kit.services.db.one("SELECT COUNT(*) AS n FROM document_analysis_calls")["n"]
    before_artifacts = kit.services.db.one("SELECT COUNT(*) AS n FROM document_analysis")["n"]
    imported = kit.services.sentiment.analysis_store.import_job(kit.services.provider.get(), cached)
    assert imported["status"] == "available" and imported["artifactId"] in original["artifactIds"]
    assert kit.services.db.one("SELECT COUNT(*) AS n FROM document_analysis_calls")["n"] == before_calls
    assert kit.services.db.one("SELECT COUNT(*) AS n FROM document_analysis")["n"] == before_artifacts
    assert kit.services.db.one("SELECT status FROM document_analysis_jobs WHERE job_id=?",
                               (request["jobId"],))["status"] == "available"
    expected = next(a["resultVersion"] for a in original["artifacts"] if a["kind"] == "document-summary")
    assert kit.client.get("/api/companies/SYNTH-A/documents").json()["items"][0]["resultVersion"] == expected
    collision = copy.deepcopy(cached)
    collision["calls"][0]["startedAt"] = "2030-01-01T00:00:00+00:00"
    with pytest.raises(AnalysisImportError, match="attempt_identity_conflict"):
        kit.services.sentiment.analysis_store.import_job(kit.services.provider.get(), collision)

def test_worker_result_cannot_restore_a_revoked_server_grant(make_admin, tmp_path):
    kit, _, results = populated(make_admin, tmp_path)
    delayed_r1 = results[0]
    revoked_r2 = {**fixture("grants")["grants"][0], "revision": "opaque-revoked-r2", "enabled": False}
    register_current_grants(kit, [revoked_r2])
    imported = kit.services.sentiment.analysis_store.import_job(kit.services.provider.get(), delayed_r1)
    assert imported["artifactId"] is None
    current = kit.services.db.one("SELECT revision,payload FROM document_analysis_grants WHERE grant_id=?",
                                  (revoked_r2["grantId"],))
    assert current["revision"] == revoked_r2["revision"] and not json.loads(current["payload"])["enabled"]
    document = kit.client.get("/api/companies/SYNTH-A/documents").json()["items"][0]
    assert document["documentSummary"] is None and document["sentiment"] is None
    assert document["analysisStatus"]["summary"]["status"] == "withheld"
    evidence_id = next(a for a in delayed_r1["artifacts"] if a["kind"] == "document-summary")["result"]["citations"][0]["evidenceId"]
    evidence = kit.client.get("/api/evidence/" + evidence_id, params={"companyId": "SYNTH-A"}).json()
    assert evidence["documentSummary"] is None and evidence["sentiment"] is None
    assert kit.services.db.one("SELECT revision FROM document_analysis_grants WHERE grant_id=?",
                               (revoked_r2["grantId"],))["revision"] == revoked_r2["revision"]


def test_same_old_job_reimport_does_not_replace_newer_public_result(make_admin, tmp_path):
    kit, _, results = populated(make_admin, tmp_path)
    old = results[0]
    newer = cloned_ready_result(old, "newer")
    kit.clock.travel_to(datetime(2030, 10, 8, 1, 0, tzinfo=timezone.utc))
    kit.services.sentiment.analysis_store.import_job(kit.services.provider.get(), newer)
    expected = next(a["resultVersion"] for a in newer["artifacts"] if a["kind"] == "document-summary")
    assert kit.client.get("/api/companies/SYNTH-A/documents").json()["items"][0]["resultVersion"] == expected
    kit.clock.travel_to(datetime(2030, 10, 8, 2, 0, tzinfo=timezone.utc))
    kit.services.sentiment.analysis_store.import_job(kit.services.provider.get(), old)
    assert kit.client.get("/api/companies/SYNTH-A/documents").json()["items"][0]["resultVersion"] == expected

def test_historical_artifact_from_weaker_policy_is_preserved_but_withheld(make_admin, tmp_path):
    kit, _, results = populated(make_admin, tmp_path)
    historical = cloned_ready_result(results[0], "old-policy")
    for call in historical["calls"]:
        call["config"]["policyVersion"] = "zoop-document-gate-1"
    for artifact in historical["artifacts"]:
        artifact["policyVersion"] = "zoop-document-gate-1"
        call = next(c for c in historical["calls"] if c["attemptId"] == artifact["attemptId"])
        artifact["modelConfigRevision"] = _digest(call["config"])
    summary = next(a for a in historical["artifacts"] if a["kind"] == "document-summary")
    source = summary["sourceRefs"][0]
    with kit.services.db.transaction() as c:
        c.execute("INSERT INTO document_analysis_jobs VALUES (?,?,?,?,?,?,?,?,?)",
                  (historical["jobId"], historical["inputDigest"], "document-summary", source["documentId"],
                   source["documentVersion"], summary["companyId"], "available", None,
                   "2030-10-08T03:00:00+00:00"))
        for call in historical["calls"]:
            c.execute("INSERT INTO document_analysis_calls VALUES (?,?,?,?,?,?,?)",
                      (call["attemptId"], historical["jobId"], call["stage"], call["mode"],
                       call["state"], call["startedAt"], dumps(call)))
        c.execute("INSERT INTO document_analysis VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (summary["artifactId"], historical["jobId"], historical["inputDigest"], summary["kind"],
                   source["documentId"], source["documentVersion"], source["sourceHash"], summary["companyId"],
                   summary["grantId"], summary["grantRevision"], "2030-10-08T03:00:00+00:00", dumps(summary)))
    before = kit.services.db.one("SELECT COUNT(*) AS n FROM document_analysis")["n"]
    document = kit.client.get("/api/companies/SYNTH-A/documents").json()["items"][0]
    assert document["documentSummary"] is None
    assert document["analysisStatus"]["summary"] == {"status": "withheld", "reason": "document_policy_outdated"}
    assert kit.services.db.one("SELECT COUNT(*) AS n FROM document_analysis")["n"] == before


def test_received_attempt_import_advances_state_and_usage_without_duplicate_charge(make_admin, tmp_path):
    _, _, results = populated(make_admin, tmp_path / "source")
    ready = cloned_ready_result(results[0], "live-usage")
    ready["input"]["mode"] = "live"
    ready["input"]["provenance"] = {"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"}
    live_grant = {**fixture("grants")["grants"][0],
                  "recipients": ["openai-compatible:synthetic-provider-revision"]}
    ready["grant"] = live_grant
    for index, call in enumerate(ready["calls"]):
        call["mode"] = "live"
        call["config"]["provider"] = "openai-compatible"
        call["config"]["providerRevision"] = "synthetic-provider-revision"
        call["usage"] = {"inputTokens": 11 + index * 2, "outputTokens": 7 - index * 2,
                         "cachedTokens": 1, "reasoningTokens": 2}
    for artifact in ready["artifacts"]:
        artifact["provenance"] = ready["input"]["provenance"]
        call = next(c for c in ready["calls"] if c["attemptId"] == artifact["attemptId"])
        artifact["modelConfigRevision"] = _digest(call["config"])
    received = copy.deepcopy(ready)
    received["state"], received["phase"] = "persisting", "receivedreceipt.saved"
    for call in received["calls"]:
        call["state"] = "received"
        call["usage"] = {key: None for key in ("inputTokens", "outputTokens", "cachedTokens", "reasoningTokens")}
    target = make_admin(fixture("snapshot"))
    register_current_grants(target, [live_grant])
    store = target.services.sentiment.analysis_store
    assert store.import_job(target.services.provider.get(), received)["status"] == "pending"
    assert store.import_job(target.services.provider.get(), ready)["status"] == "available"
    assert store.import_job(target.services.provider.get(), ready)["status"] == "available"
    assert target.services.db.one("SELECT COUNT(*) AS n FROM document_analysis_calls")["n"] == 2
    target.login()
    features = target.client.get("/api/admin/ai-usage?window=all").json()["features"]
    summary = next(f for f in features if f["feature"] == "document-summary")
    verify = next(f for f in features if f["feature"] == "semantic-verification")
    assert (summary["succeeded"], summary["failed"], summary["usage"]["modelCalls"],
            summary["usage"]["inputTokens"], summary["usage"]["outputTokens"]) == (1, 0, 1, 11, 7)
    assert (verify["succeeded"], verify["failed"], verify["usage"]["modelCalls"],
            verify["usage"]["inputTokens"], verify["usage"]["outputTokens"]) == (1, 0, 1, 13, 5)


def test_import_rejects_raw_forgery_source_change_and_actual_replay(make_admin, tmp_path):
    kit, _, results = populated(make_admin, tmp_path)
    forged = copy.deepcopy(results[0])
    summary = next(a for a in forged["artifacts"] if a["kind"] == "document-summary")
    summary["result"]["citations"][0]["end"] += 1
    with pytest.raises(AnalysisImportError, match="citation_current_evidence_mismatch"):
        kit.services.sentiment.analysis_store.import_job(kit.services.provider.get(), forged)
    invented = copy.deepcopy(results[0])
    summary = next(a for a in invented["artifacts"] if a["kind"] == "document-summary")
    summary["result"]["limitations"].append("원문에 없는 해외 공장을 폐쇄했습니다.")
    with pytest.raises(AnalysisImportError, match="limitation_claim_coverage_invalid"):
        kit.services.sentiment.analysis_store.import_job(kit.services.provider.get(), invented)
    changed = fixture("snapshot")
    changed["issues"][0]["articles"][0]["body"] += " 수정된 문서입니다."
    changed_kit = make_admin(changed)
    with pytest.raises(AnalysisImportError, match="document_version_or_hash_changed"):
        changed_kit.services.sentiment.analysis_store.import_job(changed_kit.services.provider.get(), results[0])
    actual = fixture("snapshot")
    actual["issues"][0]["articles"][0]["synthetic"] = False
    actual_kit = make_admin(actual)
    with pytest.raises(AnalysisImportError, match="authored_replay_requires_synthetic"):
        actual_kit.services.sentiment.analysis_store.import_job(actual_kit.services.provider.get(), results[0])


def test_current_deny_blocks_direct_evidence_and_document_outputs_but_keeps_immutable_records(make_admin, tmp_path):
    kit, _, _ = populated(make_admin, tmp_path)
    docs = kit.client.get("/api/companies/SYNTH-A/documents").json()["items"]
    document_id = docs[0]["id"]
    citation_id = docs[0]["documentSummary"]["citations"][0]["evidenceId"]
    before = kit.services.db.one("SELECT COUNT(*) AS n FROM document_analysis")["n"]
    kit.services.sentiment.analysis_store.deny(document_id, "합성 문서의 공개가 철회되었습니다.")
    assert kit.client.get("/api/evidence/" + citation_id, params={"companyId": "SYNTH-A"}).status_code == 404
    assert kit.client.get("/api/companies/SYNTH-A/documents").json()["items"] == []
    assert kit.services.db.one("SELECT COUNT(*) AS n FROM document_analysis")["n"] == before
    assert kit.restart().client.get("/api/evidence/" + citation_id).status_code == 404


def test_semantic_hold_and_failed_summary_do_not_hide_independent_valid_sentiment(make_admin, tmp_path):
    from zoop_ai.contracts import SourceGrant, Submit
    from zoop_ai.provider import ReplayProvider, request_identity, stage_config
    from zoop_ai.runner import Runner
    from zoop_ai.store import Store
    kit = make_admin(fixture("snapshot"))
    register_current_grants(kit)
    request = Submit.model_validate(fixture("jobs")["jobs"][0])
    response = fixture("replay")["responses"][0]["response"]
    response["claims"][0]["text"] = "원문에 없는 세계 최대라는 사실입니다."
    response["text"] = "\n".join(c["text"] for c in response["claims"] if c["assertionKind"] != "limitation")
    payload = {"schemaVersion": "zoop-ai-s1-1", "document": request.input.document.wire(), "company": request.input.company.wire(),
               "grantRef": {"grantId": request.input.grant_id, "revision": request.input.grant_revision}}
    verifier = {"claims": [{"claimId": c["claimId"], "decision": "insufficient", "reason": "원문이 이 사실을 지지하지 않습니다."} for c in response["claims"]], "prohibitedAdvice": False, "unsupportedCausality": False}
    path = tmp_path / "hold-replay.json"
    path.write_text(json.dumps({"schemaVersion": "zoop-ai-s1-1", "recordingKind": "authored-test", "responses": [
        {"stage": stage, "inputDigest": request_identity(stage, data, stage_config(stage, "replay")), "response": answer}
        for stage, data, answer in [(request.kind, payload, response), ("semantic-verification", {**payload, "candidate": response}, verifier)]]}, ensure_ascii=False))
    store = Store(tmp_path / "held-worker")
    store.register_grants([SourceGrant.model_validate(fixture("grants")["grants"][0])])
    runner = Runner(store, ReplayProvider(path))
    runner.submit(request)
    kit.services.sentiment.analysis_store.import_job(kit.services.provider.get(), runner.run(request.job_id).wire())
    doc = kit.client.get("/api/companies/SYNTH-A/documents").json()["items"][0]
    assert doc["documentSummary"] is None and doc["analysisStatus"]["summary"]["status"] == "withheld"
    assert "세계 최대" not in json.dumps(doc, ensure_ascii=False)
    # An independent valid sentiment job can still publish; summary HOLD is not a broad document deny.
    sentiment = Submit.model_validate(fixture("jobs")["jobs"][1])
    responses = fixture("replay")["responses"][2:4]
    valid_path = tmp_path / "sentiment-replay.json"
    valid_path.write_text(json.dumps({"schemaVersion": "zoop-ai-s1-1", "recordingKind": "authored-test", "responses": responses}, ensure_ascii=False))
    runner.provider = ReplayProvider(valid_path)
    runner.submit(sentiment)
    kit.services.sentiment.analysis_store.import_job(kit.services.provider.get(), runner.run(sentiment.job_id).wire())
    doc = kit.client.get("/api/companies/SYNTH-A/documents").json()["items"][0]
    assert doc["documentSummary"] is None and doc["sentiment"]["label"] == "positive"
    store.close()


def test_legacy_immutable_judgement_and_round_outlook_are_read_without_provider(admin):
    ds = admin.services.provider.get()
    company_id = next(iter(ds.companies))
    article_id = ds.issues_of_company(company_id)[0].article_ids[0]
    payload = document_input(ds, article_id, company_id)
    legacy = DocumentSentiment(label="undetermined", company_id=company_id, rationale="과거 원문에서 방향이 충분하지 않습니다.",
                               quotes=[payload["article"]["body"][:5]], judged_at="2026-10-01T00:00:00+00:00", model="historical-model", prompt_version="sentiment-2026-10-06-v1")
    admin.services.db.execute("INSERT INTO sentiment_results VALUES (?,?,?,?,?,?,?,?,?,?,?)", (input_hash("document-sentiment", legacy.model, payload), "document-sentiment", article_id, company_id,
                             legacy.model, legacy.prompt_version, legacy.judged_at, "accepted", dumps(legacy.model_dump(by_alias=True)), None, None))
    doc = next(d for d in admin.client.get(f"/api/companies/{company_id}/documents").json()["items"] if d["id"] == article_id)
    assert doc["sentiment"]["label"] == "undetermined" and doc["documentSummary"] is None
    assert doc["analysisStatus"]["sentiment"]["reason"] == "legacy_immutable"
    assert admin.services.db.one("SELECT COUNT(*) AS n FROM document_analysis_calls")["n"] == 0
    assert not hasattr(admin.services.sentiment, "provider") and not hasattr(admin.services.sentiment, "judge_document")


@pytest.mark.parametrize("state,status", [("persisting", "pending"), ("cancelled", "failed")])
def test_import_does_not_publish_an_artifact_before_ready_or_after_cancellation(make_admin, tmp_path, state, status):
    _, _, results = populated(make_admin, tmp_path)
    pending = copy.deepcopy(results[0])
    pending["state"] = state
    pending["phase"] = "artifact.validated" if state == "persisting" else "cancel.requested"
    target = make_admin(fixture("snapshot"))
    register_current_grants(target)
    imported = target.services.sentiment.analysis_store.import_job(target.services.provider.get(), pending)
    assert imported["status"] == status and imported["artifactId"] is None
    doc = target.client.get("/api/companies/SYNTH-A/documents").json()["items"][0]
    assert doc["documentSummary"] is None and doc["analysisStatus"]["summary"]["status"] == status
    assert target.services.db.one("SELECT COUNT(*) AS n FROM document_analysis")["n"] == 0


def test_import_requires_the_frozen_company_name_to_match_its_master_id(make_admin, tmp_path):
    kit, _, results = populated(make_admin, tmp_path)
    wrong_company = copy.deepcopy(results[0])
    wrong_company["input"]["input"]["company"]["name"] = "합성 베타"
    with pytest.raises(AnalysisImportError, match="company_context_mismatch"):
        kit.services.sentiment.analysis_store.import_job(kit.services.provider.get(), wrong_company)


def test_client_resolves_relative_caller_paths_before_the_worker_changes_directory(tmp_path, monkeypatch):
    """The worker runs in a throwaway request folder; relative worker state/grants/replay must still be the caller's."""
    monkeypatch.chdir(tmp_path)
    relative = lambda path: Path(os.path.relpath(path, tmp_path))
    client = AiWorkerClient(state_dir=Path("app-state"), worker_state=Path("worker-ledger"),
                            grants=relative(FIXTURE / "grants.json"), replay=relative(FIXTURE / "replay.json"),
                            worker_command=[os.path.relpath(WORKER_COMMAND[0], tmp_path)])
    request = fixture("jobs")["jobs"][0]
    assert client.command("submit", request)["state"] == "queued"
    assert client.command("run", {"schemaVersion": "zoop-ai-s1-1", "jobId": request["jobId"]})["state"] == "ready"
    assert client.get(request["jobId"])["state"] == "ready"
    assert (tmp_path / "worker-ledger").is_dir() and (tmp_path / "app-state/ai-transport").is_dir()
