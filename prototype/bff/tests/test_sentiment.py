"""Sentiment acceptance: fixed responses only, no billable network calls."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from zoop_bff.config import BFF_ROOT
from zoop_bff.sentiment import (
    CallLimitReached, ModelReply, OpenAICompatibleProvider, ProviderFailure, ReplayProvider,
    SentimentService, document_input, document_pairs, outlook_input,
)

from .conftest import ALPHA_ISSUES, base_payload, with_companies

KST = timezone(timedelta(hours=9))
MORNING = "brf-2026-09-17-morning"


def attach(kit, responses, *, max_calls=20, model="replay-sentiment"):
    provider = ReplayProvider(responses, model=model)
    service = kit.services.sentiment
    service.provider = provider
    service.max_calls = max_calls
    return service, provider


def answer(ds, pair, **overrides):
    payload = document_input(ds, *pair)
    quote = payload["article"]["body"].split(". ")[0]
    data = {"label": "undetermined", "rationale": "보도된 사실만으로 기업에 유리한지 확인하기 어렵습니다.", "quotes": [quote]}
    data.update(overrides)
    return ModelReply(json.dumps(data, ensure_ascii=False), 20, 10)


@pytest.mark.parametrize("override,code", [
    ({"quotes": ["원문에 없는 문장"]}, "quote_mismatch"),
    ({"quotes": [" "]}, "quote_mismatch"),
    ({"rationale": "지수가 상승할 것입니다."}, "prohibited_expression"),
    ({"rationale": "매수를 추천합니다."}, "prohibited_expression"),
    ({"rationale": "Buy this stock now."}, "prohibited_expression"),
    ({"label": "positive", "probability": 0.9}, "response_schema_invalid"),
    ({"quotes": []}, "response_schema_invalid"),
])
def test_invalid_response_is_discarded_and_public_field_is_null(admin, override, code):
    ds = admin.services.provider.get()
    pair = document_pairs(ds)[0]
    service, provider = attach(admin, [answer(ds, pair, **override)])
    assert service.judge_document(ds, *pair) is None
    docs = admin.client.get(f"/api/companies/{pair[1]}/documents").json()["items"]
    assert next(d for d in docs if d["id"] == pair[0])["sentiment"] is None
    record = admin.services.db.one("SELECT status,result,failure_code FROM sentiment_results")
    assert (record["status"], record["result"], record["failure_code"]) == ("failed", None, code)
    assert service.judge_document(ds, *pair) is None and provider.calls == 1


def test_valid_judgement_is_cached_persisted_and_only_shown_in_approved_company_context(make_admin):
    admin = make_admin(with_companies(base_payload()))
    ds = admin.services.provider.get()
    pair = document_pairs(ds)[0]
    service, provider = attach(admin, [answer(ds, pair)])
    result = service.judge_document(ds, *pair)
    assert result.company_id == pair[1] and result.quotes
    assert result.prompt_version and result.model == "replay-sentiment" and result.judged_at
    assert service.judge_document(ds, *pair) == result and provider.calls == 1
    restarted = admin.restart()
    docs = restarted.client.get(f"/api/companies/{pair[1]}/documents").json()["items"]
    assert next(d for d in docs if d["id"] == pair[0])["sentiment"] == result.model_dump(by_alias=True)
    ev = next(e for e in ds.evidence.values() if e.article_id == pair[0])
    assert admin.client.get(f"/api/evidence/{ev.id}").json()["sentiment"] is None
    assert admin.client.get(f"/api/evidence/{ev.id}", params={"companyId": pair[1]}).json()["sentiment"]["companyId"] == pair[1]
    other = next(c for c in ds.companies if c != pair[1])
    response = admin.client.get(f"/api/evidence/{ev.id}", params={"companyId": other})
    assert response.status_code == 422 and response.json()["error"]["code"] == "sentiment_context_mismatch"


def test_model_change_uses_a_different_input_hash(admin):
    ds = admin.services.provider.get()
    pair = document_pairs(ds)[0]
    first, p1 = attach(admin, [answer(ds, pair)], model="model-one")
    first.judge_document(ds, *pair)
    second, p2 = attach(admin, [answer(ds, pair)], model="model-two")
    second.judge_document(ds, *pair)
    assert p1.calls == p2.calls == 1
    assert admin.services.db.one("SELECT COUNT(*) AS n FROM sentiment_results")["n"] == 2


def test_call_ceiling_includes_retries_and_caches_the_terminal_failure(admin):
    ds = admin.services.provider.get()
    first, second = document_pairs(ds)[:2]
    service, provider = attach(admin, [ProviderFailure("timeout", transient=True), answer(ds, first)], max_calls=1)
    assert service.judge_document(ds, *first) is None
    assert service.judge_document(ds, *first) is None
    with pytest.raises(CallLimitReached):
        service.judge_document(ds, *second)
    assert provider.calls == service.calls == 1
    assert admin.services.db.one("SELECT COUNT(*) AS n FROM ai_events WHERE feature='document-sentiment'")["n"] == 1


def test_usage_separates_replays_retries_failures_and_cache_reads(admin):
    ds = admin.services.provider.get()
    pair = document_pairs(ds)[0]
    service, provider = attach(admin, [ProviderFailure("timeout", transient=True), answer(ds, pair)])
    assert service.judge_document(ds, *pair) is not None
    assert service.judge_document(ds, *pair) is not None
    usage = admin.client.get("/api/admin/ai-usage", params={"window": "all"})
    assert usage.status_code == 200
    row = next(f for f in usage.json()["features"] if f["feature"] == "document-sentiment")
    assert (row["requests"], row["succeeded"], row["failed"]) == (2, 1, 1)
    assert row["usage"] == {"modelCalls": 0, "inputTokens": 20, "outputTokens": 10, "replayCalls": 2, "retries": 1}
    assert provider.calls == 2


def test_outlook_and_document_judgements_are_fixed_at_publication(admin):
    ds = admin.services.provider.get()
    pair = document_pairs(ds)[0]
    reply = ModelReply(json.dumps({"label": "undetermined", "rationale": "이번 회차의 사실만으로 유불리를 확인하기 어렵습니다.", "issueIds": [ALPHA_ISSUES["q1"]]}))
    service, provider = attach(admin, [answer(ds, pair), reply])
    service.judge_document(ds, *pair)
    admin.clock.travel_to(datetime(2026, 9, 17, 7, 45, tzinfo=KST))
    assert admin.services.briefings.tick() == [MORNING]
    before = admin.client.get("/api/briefings").json()
    assert before["outlook"]["label"] == "undetermined"
    assert any(i["documentSentiments"] for i in before["items"])
    assert provider.calls == 2
    admin.services.sentiment.provider = ReplayProvider([ModelReply("{}")], model="different-model")
    frozen = admin.services.briefings.record(MORNING).payload
    altered = outlook_input(MORNING, frozen["scheduledAt"], frozen["items"], {})
    altered["issues"][0]["title"] = "발행 이후 바뀐 내용"
    assert service.judge_outlook(altered).model_dump(by_alias=True) == before["outlook"]
    assert service.provider.calls == 0
    assert admin.client.get("/api/briefings").json() == before
    assert admin.client.post(f"/api/admin/briefings/{MORNING}/reprocess", json={"reason": "재판정"}).status_code == 409
    with pytest.raises(sqlite3.IntegrityError):
        admin.services.db.execute("UPDATE briefing_rounds SET payload='{}' WHERE id=?", (MORNING,))
    ev = next(e for e in ds.evidence.values() if e.article_id == pair[0])
    value = admin.client.get(f"/api/evidence/{ev.id}", params={"companyId": pair[1], "round": MORNING}).json()["sentiment"]
    assert value["model"] == "replay-sentiment"
    outlook_usage = next(f for f in admin.services.usage.response("all", []).features if f.feature == "briefing-outlook")
    assert outlook_usage.requests == 1 and outlook_usage.usage.replay_calls == 1


def test_empty_core_issues_and_http_default_never_call_a_provider(make_admin):
    kit = make_admin()
    service, provider = attach(kit, [ModelReply("{}")])
    kit.clock.travel_to(datetime(2026, 9, 16, 7, 45, tzinfo=KST))
    kit.services.briefings.tick()
    empty = kit.client.get("/api/briefings").json()
    assert empty["items"] == [] and empty["outlook"] is None and provider.calls == 0
    ordinary = make_admin()
    ordinary.clock.travel_to(datetime(2026, 9, 17, 7, 45, tzinfo=KST))
    ordinary.services.briefings.tick()
    assert ordinary.client.get("/api/briefings").json()["outlook"] is None
    assert ordinary.services.db.one("SELECT COUNT(*) AS n FROM sentiment_attempts")["n"] == 0


def test_outlook_invalid_issue_reference_is_discarded(admin):
    ds = admin.services.provider.get()
    service, provider = attach(admin, [ModelReply(json.dumps({"label": "positive", "rationale": "사업 성과가 확인됩니다.", "issueIds": ["not-in-round"]}))])
    payload = {"roundId": MORNING, "issues": [{"eventId": ALPHA_ISSUES["q1"]}]}
    assert service.judge_outlook(payload) is None
    assert provider.calls == 1
    assert admin.services.db.one("SELECT failure_code FROM sentiment_results")["failure_code"] == "issue_reference_invalid"


def test_openai_compatible_wire_uses_fixed_transport_and_records_model_usage(make_admin):
    payload = base_payload()
    for issue in payload["issues"]:
        for article in issue["articles"]:
            article["allow_model_send"] = True
    kit = make_admin(payload)
    ds = kit.services.provider.get()
    pair = document_pairs(ds)[0]
    fixed = answer(ds, pair)
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": fixed.content}}],
                                        "usage": {"prompt_tokens": 51, "completion_tokens": 12}})

    provider = OpenAICompatibleProvider(base_url="https://model.invalid/v1", api_key="test-only", model="fixed-transport", transport=httpx.MockTransport(respond))
    service = SentimentService(kit.services.db, kit.clock, kit.services.usage, provider=provider, max_calls=1)
    try:
        assert service.judge_document(ds, *pair) is not None
        assert service.judge_document(ds, *pair) is not None
    finally:
        provider.close()
    assert len(requests) == 1
    assert requests[0]["response_format"]["json_schema"]["strict"] is True
    assert requests[0]["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    feature = next(f for f in kit.services.usage.response("all", []).features if f.feature == "document-sentiment")
    assert (feature.usage.model_calls, feature.usage.input_tokens, feature.usage.output_tokens, feature.usage.replay_calls) == (1, 51, 12, 0)


def test_live_adapter_respects_document_send_permission(admin):
    ds = admin.services.provider.get()
    pair = document_pairs(ds)[0]
    requests = []
    provider = OpenAICompatibleProvider(base_url="https://model.invalid/v1", api_key="test-only", model="fixed-transport",
        transport=httpx.MockTransport(lambda req: requests.append(req)))
    service = SentimentService(admin.services.db, admin.clock, admin.services.usage, provider=provider, max_calls=1)
    try:
        assert service.judge_document(ds, *pair) is None
    finally:
        provider.close()
    assert requests == [] and service.calls == 0


def test_cli_dry_run_reports_targets_without_changing_source_state(admin):
    before = admin.services.db.query("SELECT * FROM ai_events")
    env = {"ZOOP_STATE_DIR": str(admin.state_dir), "ZOOP_SNAPSHOT_PATH": str(admin.settings.snapshot_path),
           "ZOOP_COMPANY_CATALOG": "", "ZOOP_QUOTE_PROVIDER": "off"}
    import os
    result = subprocess.run(["uv", "run", "python", "scripts/judge_sentiment.py", "--dry-run"],
                            cwd=BFF_ROOT, env={**os.environ, **env}, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["documentPairs"] == 3 and report["permissionBlockedPairs"] == 3
    assert report["expectedCalls"] == 1 and report["rounds"] == 1
    assert admin.services.db.query("SELECT * FROM ai_events") == before
