"""The existing briefing-outlook producer is preserved, not a future-stage placeholder."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from zoop_ai.contracts import SourceGrant, Submit
from zoop_ai.provider import OpenAICompatibleProvider, ReplayProvider, stage_config
from zoop_ai.runner import Runner
from zoop_ai.store import Store

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/contracts/synthetic-outlook"


def fixture(name):
    return json.loads((FIXTURE / (name + ".json")).read_text())


def setup(tmp_path, *, grant_change=None, response_change=None):
    request = Submit.model_validate(fixture("jobs")["jobs"][0])
    store = Store(tmp_path / "worker")
    grant = {**fixture("grants")["grants"][0], **(grant_change or {})}
    store.register_grants([SourceGrant.model_validate(grant)])
    recording = fixture("replay")
    recording["responses"][0]["response"].update(response_change or {})
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(recording))
    provider = ReplayProvider(path)
    runner = Runner(store, provider)
    runner.submit(request)
    return runner, provider, request


def test_existing_outlook_exact_policy_has_a_real_durable_artifact(tmp_path):
    runner, provider, request = setup(tmp_path)
    result = runner.run(request.job_id)
    assert result.state == "ready" and len(result.artifacts) == 1 and provider.calls == 1
    artifact = result.artifacts[0]
    assert artifact.kind == "briefing-outlook" and artifact.result.issue_ids == ["event-synthetic-s1"]
    assert artifact.validation.exact and artifact.validation.semantic is None and artifact.validation.eligible
    assert artifact.policy_version == "legacy-outlook-exact-1"
    assert runner.run(request.job_id).artifact_ids == result.artifact_ids and provider.calls == 1
    assert runner.get(request.job_id).usage.provider_attempts == 0
    runner.store.close()


@pytest.mark.parametrize("answer,code", [({"issueIds": ["unselected-event"]}, "issue_reference_invalid"),
    ({"rationale": "매수를 추천합니다."}, "prohibited_expression"),
    ({"rationale": "내일 지수가 오를 전망입니다."}, "prohibited_expression"),
    ({"probability": 0.9}, "response_schema_invalid")])
def test_outlook_keeps_existing_reference_and_no_advice_rules(tmp_path, answer, code):
    runner, provider, request = setup(tmp_path, response_change=answer)
    result = runner.run(request.job_id)
    assert result.state == "failed" and result.failure.code == code and result.artifacts == []
    assert runner.resume(request.job_id).state == "failed" and provider.calls == 1
    runner.store.close()


@pytest.mark.parametrize("change", [{"enabled": False}, {"rights": "unknown"}, {"allowedOperations": ["read", "store"]},
    {"recipients": ["unapproved-recipient"]}, {"purposes": ["document-summary"]}, {"evidence": []}])
def test_outlook_input_send_requires_current_source_authority(tmp_path, change):
    runner, provider, request = setup(tmp_path, grant_change=change)
    assert runner.run(request.job_id).state == "failed" and provider.calls == 0
    runner.store.close()


def test_empty_outlook_round_has_no_call_and_no_fabricated_label(tmp_path):
    runner, provider, request = setup(tmp_path)
    empty = request.model_copy(update={"job_id": "empty-outlook", "input": request.input.model_copy(update={"issues": []})})
    runner.submit(empty)
    result = runner.run(empty.job_id)
    assert result.state == "ready" and result.phase == "empty_round.no_call"
    assert result.artifacts == [] and result.usage.replay_calls == provider.calls == 0
    runner.store.close()


def test_outlook_real_http_uses_its_stage_model_effort_and_same_global_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("ZOOP_AI_BRIEFING_OUTLOOK_MODEL", "synthetic-outlook-wire-model")
    monkeypatch.setenv("ZOOP_AI_BRIEFING_OUTLOOK_REASONING_EFFORT", "low")
    monkeypatch.setenv("ZOOP_AI_BASE_URL", "https://model.invalid/v1")
    request = Submit.model_validate(fixture("jobs")["jobs"][0]).model_copy(update={"mode": "live"})
    request = request.model_copy(update={"provenance": request.provenance.model_copy(update={"execution_mode": "live", "recording_kind": "provider"})})
    cfg = stage_config("briefing-outlook", "live")
    grant = fixture("grants")["grants"][0]
    grant["recipients"] = [cfg.provider + ":" + cfg.provider_revision]
    store = Store(tmp_path / "live-mock")
    store.register_grants([SourceGrant.model_validate(grant)])
    seen = []
    def response(req):
        seen.append(json.loads(req.content))
        assert not store.db.in_transaction
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(fixture("replay")["responses"][0]["response"], ensure_ascii=False)}}]})
    provider = OpenAICompatibleProvider(base_url="https://model.invalid/v1", api_key="synthetic-only", transport=httpx.MockTransport(response))
    runner = Runner(store, provider, live_enabled=True, max_calls=1)
    runner.submit(request)
    result = runner.run(request.job_id)
    assert result.state == "ready" and result.usage.provider_attempts == 1 and provider.calls == 1
    assert seen[0]["model"] == "synthetic-outlook-wire-model" and seen[0]["reasoning_effort"] == "low"
    assert seen[0]["response_format"]["json_schema"]["name"] == "briefing_outlook"
    assert store.db.execute("SELECT COUNT(*) FROM budget_reservations").fetchone()[0] == 1
    provider.close()
    store.close()
