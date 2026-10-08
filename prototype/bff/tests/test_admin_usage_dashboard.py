"""Requirements 77 and 81: AI usage/cost reporting, the dashboard and the audit log."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from .conftest import ADMIN, ALPHA_ISSUES, DEMO, base_payload, jobs_settled
from .chat_support import ask_job, job_body, new_member, open_conversation
from .fakes import run_report

KST = timezone(timedelta(hours=9))


def _usage(kit, window="7d"):
    return kit.client.get("/api/admin/ai-usage", params={"window": window}).json()


def _feature(body, name):
    return next(f for f in body["features"] if f["feature"] == name)


def _ledger_run(run_id, *, web, calls, processed, approved, held, errors=0, cost=None):
    return {
        "run_id": run_id,
        "report": {
            "processed": processed,
            "approved": approved,
            "held": held,
            "rejected": 0,
            "pending": 1,
            "errors": [{"error": "ModelResponseError"}] * errors,
            "elapsed_seconds": 100.0,
            "web_policy_fingerprint": "abc" if web else None,
            "usage": {"calls": calls, "input_tokens": calls * 10, "output_tokens": calls, "elapsed_seconds": 90.0, "estimated_cost": cost},
        },
    }


def test_rule_based_features_are_measured_and_report_zero_model_calls(admin):
    asker = new_member(admin.client)
    session = open_conversation(asker)
    answered = ask_job(asker, "어떤 실적을 발표했나요?", [ALPHA_ISSUES["q2"]], session_id=session)
    assert answered["status"] == "completed" and answered["outcome"] == "answered"
    refused = ask_job(asker, "내일 주가가 오를까요?", [ALPHA_ISSUES["q2"]], session_id=session)
    assert refused["outcome"] == "insufficient_evidence"
    other = new_member(admin.client, "other@example.com", "다른사람")
    stolen = other.post(f"/api/chat/sessions/{session}/jobs", json=job_body("훔쳐보기", [ALPHA_ISSUES["q2"]]))
    assert stolen.status_code == 403

    chatbot = _feature(_usage(admin), "chatbot")
    assert chatbot["modelBacked"] is False and chatbot["usage"] == {"modelCalls": 0, "inputTokens": 0, "outputTokens": 0, "replayCalls": 0, "retries": 0}
    assert (chatbot["requests"], chatbot["succeeded"], chatbot["failed"]) == (2, 2, 0)  # a 403 is not an AI request
    assert chatbot["latencyMs"]["max"] >= chatbot["latencyMs"]["avg"] > 0 and chatbot["source"] == "measured"
    assert chatbot["cost"]["status"] == "unavailable" and chatbot["cost"]["estimated"] is None

    # A server-side failure is a failed request with its code.
    (admin.state_dir / "graph" / "v1.json").chmod(0o644)
    (admin.state_dir / "graph" / "v1.json").write_text("{}")
    broken = asker.post(f"/api/chat/sessions/{session}/jobs", json=job_body("다시", [ALPHA_ISSUES["q2"]]))
    assert broken.status_code == 503
    chatbot = _feature(_usage(admin), "chatbot")
    assert (chatbot["requests"], chatbot["failed"]) == (3, 1) and chatbot["recentErrors"][0]["code"] == "source_unavailable"


def test_briefing_attempts_are_counted_with_their_failures(make_admin):
    broken = base_payload()
    for issue in broken["issues"]:
        for ev in [e for m in issue["mentions"] for e in m["evidence"]]:
            ev["quote"] = "원문에 없는 문장"
    kit = make_admin(broken)
    kit.login()
    kit.clock.travel_to(datetime(2026, 9, 17, 7, 45, tzinfo=KST))
    kit.services.briefings.tick()
    kit.client.get("/api/briefings")
    kit.client.get("/api/briefings")

    briefing = _feature(_usage(kit), "briefing")
    assert (briefing["requests"], briefing["failed"], briefing["modelBacked"]) == (1, 1, False)
    assert briefing["recentErrors"][0]["code"] == "verification_failed"
    assert "사용자 조회는 BFF 기동 이후 2회" in briefing["note"]
    assert briefing["usage"]["modelCalls"] == 0


def test_news_analysis_comes_from_ledger_runs_and_never_invents_a_cost(admin):
    admin.ledger.runs = [
        _ledger_run("run-strict-1", web=True, calls=200, processed=20, approved=1, held=19, errors=6),
        _ledger_run("run-relaxed-1", web=False, calls=150, processed=43, approved=15, held=28, errors=0),
    ]
    everything = _usage(admin, "all")
    runs = {r["runId"]: r for r in everything["pastRuns"]}
    assert runs["run-strict-1"]["policyGroup"] == "strict-web" and runs["run-relaxed-1"]["policyGroup"] == "relaxed-no-web"
    assert runs["run-strict-1"]["source"] == "ledger-db" and runs["run-strict-1"]["errorCount"] == 6
    assert runs["run-relaxed-1"]["usage"] == {"calls": 150, "replayCalls": 0, "inputTokens": 1500, "outputTokens": 150, "elapsedSeconds": 90.0, "estimatedCost": None}
    news = _feature(everything, "news-analysis")
    assert news["modelBacked"] is True and news["source"] == "ledger-db"
    assert (news["requests"], news["failed"], news["usage"]["modelCalls"]) == (2, 1, 350)
    assert everything["cost"]["status"] == "unavailable" and everything["cost"]["actual"] is None and everything["cost"]["estimated"] is None
    assert news["cost"]["status"] == "unavailable"

    # Within a time window only runs started through this BFF are known; ledger runs carry no timestamp.
    assert _feature(_usage(admin, "7d"), "news-analysis")["requests"] == 0

    admin.launcher.script(stdout=json.dumps(run_report(calls=21, run_id="run-job-1")))
    created = admin.client.post(
        "/api/admin/jobs", json={"kind": "retry-model-errors", "reason": "재처리", "confirmPaid": True, "maxModelCalls": 25}
    )
    assert created.status_code == 202
    jobs_settled(admin)
    week = _usage(admin, "7d")
    news = _feature(week, "news-analysis")
    assert (news["requests"], news["succeeded"], news["source"], news["usage"]["modelCalls"]) == (1, 1, "job-runner", 21)
    assert any(r["policyGroup"] == "admin-job" and r["runId"] == "run-job-1" for r in week["pastRuns"])

    admin.ledger.runs.append(_ledger_run("run-job-1", web=False, calls=21, processed=4, approved=1, held=3))
    again = _usage(admin, "all")
    assert [r["runId"] for r in again["pastRuns"]].count("run-job-1") == 1  # the CLI saved the same run in the ledger
    assert next(r for r in again["pastRuns"] if r["runId"] == "run-job-1")["policyGroup"] == "admin-job"

    admin.ledger.runs[0]["report"]["usage"]["estimated_cost"] = 1.25
    estimated = _usage(admin, "all")
    assert estimated["cost"]["status"] == "estimated" and estimated["cost"]["estimated"] == 1.25


def test_an_unreadable_ledger_falls_back_to_the_documented_runs(admin):
    admin.ledger.down = True
    body = _usage(admin, "all")
    strict, relaxed = body["pastRuns"][:2]
    assert (strict["source"], strict["policyGroup"], strict["usage"]["calls"]) == ("document", "strict-web", 600)
    assert (relaxed["source"], relaxed["policyGroup"], relaxed["usage"]["calls"]) == ("document", "relaxed-no-web", 400)
    assert strict["usage"]["inputTokens"] == 7_896_703 and relaxed["usage"]["outputTokens"] == 508_128
    assert relaxed["pending"] is None  # unknown stays null instead of a made-up number
    news = _feature(body, "news-analysis")
    assert news["source"] == "document" and news["usage"]["modelCalls"] == 1000
    assert body["cost"]["status"] == "unavailable"


def test_dashboard_summarises_every_area(admin):
    member = TestClient(admin.client.app)
    member.post("/api/auth/login", json=DEMO)
    TestClient(admin.client.app).post("/api/auth/guest")
    admin.clock.travel_to(datetime(2026, 9, 17, 8, 5, tzinfo=KST))
    admin.launcher.script(code=1, stdout=json.dumps(run_report(calls=5, errors=1)))
    admin.client.post("/api/admin/jobs", json={"kind": "retry-model-errors", "reason": "재처리", "confirmPaid": True})
    jobs_settled(admin)
    admin.client.post(
        "/api/admin/pipeline/candidates/candidate-a14f9dee7d35615c950a6830/decision", json={"decision": "reject", "reason": "거부"}
    )

    body = admin.client.get("/api/admin/dashboard").json()
    assert body["ledger"] == {"status": "connected", "error": None}
    assert body["graph"]["activeVersionId"] == "v1" and body["graph"]["versionCount"] == 1
    assert body["graph"]["reviewDecisions"] == 1 and body["graph"]["graphDb"]["status"] == "reflected"
    assert body["candidates"] == {"allow": 4, "hold": 1, "reject": 0, "inactive": 0, "holdPendingReview": 0}
    assert body["jobs"]["failed24h"] == 1 and body["jobs"]["running"] == 0 and body["jobs"]["recent"][0]["status"] == "failed"
    assert body["members"] == {"registered": 1, "activeMemberSessions": 1, "activeGuestSessions": 1, "source": "bff-mock"}
    assert [f["feature"] for f in body["ai"]["features"]] == ["chatbot", "news-analysis", "briefing", "document-sentiment", "briefing-outlook", "document-summary", "semantic-verification"]
    assert body["briefings"]["latest"][0]["id"] == "brf-2026-09-17-morning"
    assert body["briefings"]["latest"][0]["status"] == "missing" and body["briefings"]["delayedOrFailed"] == 1
    assert body["audit"]["last24h"] >= 3


def test_audit_log_filters_pages_and_never_holds_secrets(admin):
    for i in range(3):
        admin.client.post(
            "/api/admin/pipeline/candidates/candidate-a14f9dee7d35615c950a6830/decision",
            json={"decision": "reject" if i % 2 == 0 else "allow", "reason": f"검수 {i}"},
        )
    admin.client.post("/api/admin/auth/login", json={**ADMIN, "password": "wrong-password-xyz"})

    def page(**params):
        return admin.client.get("/api/admin/audit-log", params=params).json()

    decided = page(action="review.decide")
    assert len(decided["items"]) == 3 and decided["items"][0]["reason"] == "검수 2"  # newest first
    assert all(e["actorEmail"] == "admin@zoop.local" and e["targetType"] == "review-candidate" for e in decided["items"])
    assert page(actor="admin@zoop.local", targetType="review-candidate")["items"] == decided["items"]
    assert [e["reason"] for e in page(q="검수 1")["items"]] == ["검수 1"]

    first = page(limit=2)
    assert len(first["items"]) == 2 and first["nextCursor"]
    second = page(limit=2, cursor=first["nextCursor"])
    ids = [e["id"] for e in first["items"] + second["items"]]
    assert ids == sorted(ids, reverse=True) and len(set(ids)) == len(ids)
    assert admin.client.get("/api/admin/audit-log", params={"cursor": "x"}).status_code == 422

    everything = json.dumps(page(limit=200), ensure_ascii=False)
    for secret in ("wrong-password-xyz", ADMIN["password"], admin.client.cookies.get("zoop_admin_session")):
        assert secret not in everything
