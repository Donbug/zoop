"""Requirements 74, 75, 78: behaviour events, usage statistics, AI votes and transcripts, member blocking."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from zoop_bff.accounts import SESSION_COOKIE
from zoop_bff.masking import TOKENS, Masker

from .conftest import ALPHA_ISSUES, DEMO

KST = timezone(timedelta(hours=9))
EVENING = "brf-2026-09-16-evening"
SIGNUP = {"password": "zoop-pass-1", "displayName": "김민수", "agreements": ["service", "privacy"]}


def at(day: str, hour: int, minute: int = 0) -> datetime:
    return datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=KST)


def guest(kit) -> TestClient:
    client = TestClient(kit.client.app)
    assert client.post("/api/auth/guest").status_code == 200
    return client


def member(kit, email: str = "kim.minsu@example.com", name: str = "김민수") -> TestClient:
    client = TestClient(kit.client.app)
    response = client.post("/api/auth/signup", json={**SIGNUP, "email": email, "displayName": name})
    assert response.status_code == 201, response.text
    return client


def demo(kit) -> TestClient:
    client = TestClient(kit.client.app)
    assert client.post("/api/auth/login", json=DEMO).status_code == 200
    return client


def vid() -> str:
    return uuid.uuid4().hex[:16]


def send(client: TestClient, *events: dict):
    return client.post("/api/telemetry", json={"events": list(events)})


def main_view(view_id: str) -> dict:
    return {"type": "screen_view", "screen": "main", "viewId": view_id}


def node(target: str, view_id: str | None = None) -> dict:
    return {"type": "graph_node_select", "targetId": target, **({"viewId": view_id} if view_id else {})}


def summary(kit, window: str = "all") -> dict[str, dict]:
    response = kit.client.get("/api/admin/insights/summary", params={"window": window})
    assert response.status_code == 200, response.text
    return {m["key"]: m for m in response.json()["metrics"]}


def publish_evening(kit) -> dict:
    kit.clock.travel_to(at("2026-09-16", 18, 15))
    kit.services.briefings.tick()
    briefing = kit.client.get("/api/briefings").json()
    assert briefing["id"] == EVENING and briefing["status"] == "published"
    return briefing


def ask(client: TestClient, question: str, contexts: list[str] | None = None) -> dict:
    contexts = contexts or [ALPHA_ISSUES["q1"]]
    session = client.post("/api/chat/sessions", json={"contextIds": contexts}).json()["id"]
    reply = client.post(f"/api/chat/sessions/{session}/messages", json={"question": question})
    assert reply.status_code == 200, reply.text
    return reply.json()


# ---- 74: collection


def test_only_whitelisted_events_within_size_limits_are_stored(admin):
    user = guest(admin)
    assert send(user, main_view(vid()), node("c1", vid())).json() == {"accepted": 2}

    bad = [
        {"events": [{"type": "page_scroll", "targetId": "x"}]},  # not on the whitelist
        {"events": [{"type": "graph_node_select", "targetId": "c1", "email": "kim@example.com"}]},  # no free-form fields
        {"events": [{"type": "screen_view", "screen": "main"}]},  # missing viewId
        {"events": [{"type": "graph_node_select", "targetId": "has space"}]},
        {"events": [{"type": "briefing_view", "targetId": "not-a-round"}]},
        {"events": []},
        {"events": [node("c1")] * 21},  # more than a batch
    ]
    for body in bad:
        response = user.post("/api/telemetry", json=body)
        assert response.status_code == 422, body

    huge = user.post("/api/telemetry", content=b" " * 17_000, headers={"content-type": "application/json"})
    assert huge.status_code == 413 and huge.json()["error"]["code"] == "payload_too_large"
    assert TestClient(admin.client.app).post("/api/telemetry", json={"events": [node("c1")]}).status_code == 401

    stored = admin.services.db.one("SELECT COUNT(*) AS n FROM telemetry_events")["n"]
    assert stored == 2  # nothing from the refused requests


def test_events_carry_no_identity_and_a_guest_is_only_a_hash(admin):
    user = guest(admin)
    send(user, node("c1"))
    principal = admin.client.app.state.zoop.accounts.principal(user.cookies.get(SESSION_COOKIE))
    row = admin.services.db.one("SELECT * FROM telemetry_events")
    assert row["subject_kind"] == "guest" and row["subject"].startswith("g-")
    assert principal.principal_id not in " ".join(str(v) for v in tuple(row))


def test_a_session_that_floods_is_refused_until_the_minute_passes(admin):
    user = guest(admin)
    for _ in range(60):
        assert send(user, node("c1")).status_code == 202
    flooded = send(user, node("c1"))
    assert flooded.status_code == 429 and flooded.json()["error"]["code"] == "rate_limited"
    assert admin.services.db.one("SELECT COUNT(*) AS n FROM telemetry_events")["n"] == 60  # refused, not half-stored
    admin.clock.advance(61)
    assert send(user, node("c1")).status_code == 202


# ---- 74: statistics


def test_ratios_need_a_minimum_sample_and_count_each_exposure_once(admin):
    a, b = guest(admin), guest(admin)
    views = [vid() for _ in range(4)]
    send(a, *[main_view(v) for v in views[:2]])
    send(b, *[main_view(v) for v in views[2:]])
    send(a, node("c1", views[0]), node("c2", views[0]), node("c3", views[0]))  # three clicks, one exposure
    send(b, {"type": "graph_edge_select", "targetId": "e1", "viewId": views[2]})

    four = summary(admin)
    assert four["node_click"]["denominator"] == 4 and four["node_click"]["numerator"] == 1
    assert four["node_click"]["sampleHidden"] is True and four["node_click"]["rate"] is None
    assert four["node_selections"]["count"] == 3  # the counts stay visible

    send(b, main_view(vid()))
    five = summary(admin)
    assert five["node_click"]["sampleHidden"] is False and five["node_click"]["rate"] == pytest.approx(0.2)
    assert five["edge_click"]["rate"] == pytest.approx(0.2)
    assert five["main_exposures"]["count"] == 5


def test_a_repeated_exposure_id_is_one_exposure(admin):
    user = guest(admin)
    same = vid()
    send(user, main_view(same), main_view(same))
    assert summary(admin)["main_exposures"]["count"] == 1


def test_active_users_come_from_events_chats_and_votes_without_double_counting(admin):
    publish_evening(admin)
    watcher, asker, voter = guest(admin), member(admin), guest(admin)
    send(watcher, main_view(vid()))
    send(asker, main_view(vid()))
    answer = ask(asker, "어떤 실적을 발표했나요?")
    vote = voter.put("/api/feedback", json={"feature": "briefing_round", "targetId": EVENING, "value": "up"})
    assert vote.status_code == 200

    metrics = summary(admin)
    assert metrics["active_users"]["count"] == 3 and metrics["active_members"]["count"] == 1 and metrics["active_guests"]["count"] == 2
    assert metrics["ai_questions"]["count"] == 1
    assert (metrics["ai_usage_rate"]["numerator"], metrics["ai_usage_rate"]["denominator"]) == (1, 3)
    assert answer["messageId"].endswith("-m1")


def test_onboarding_comes_from_member_settings_not_client_events(admin):
    done = member(admin, "done@example.com", "완료")
    member(admin, "todo@example.com", "미완료")
    version = done.get("/api/me/settings").json()["version"]
    assert done.put("/api/me/settings", json={"version": version, "completed": True}).status_code == 200

    onboarding = summary(admin)["onboarding_completion"]
    assert (onboarding["numerator"], onboarding["denominator"]) == (1, 3)  # the demo member has not finished either


def test_a_window_counts_only_its_own_kst_days(admin):
    user = guest(admin)
    admin.clock.travel_to(at("2026-09-01", 12))
    send(user, node("c1"))
    admin.clock.travel_to(at("2026-09-20", 12))
    send(user, node("c1"), node("c2"))

    assert summary(admin, "all")["node_selections"]["count"] == 3
    assert summary(admin, "7d")["node_selections"]["count"] == 2
    trend = admin.client.get("/api/admin/insights/summary", params={"window": "7d"}).json()["trend"]
    assert [d["date"] for d in trend][-1] == "2026-09-20" and len(trend) == 7
    assert sum(d["nodeSelections"] for d in trend) == 2


def test_company_ranking_and_trend_match_what_users_did(admin):
    ds = admin.client.app.state.zoop.provider.get()
    cid = next(c for c in ds.companies if ds.company_edges.get(c))
    edge = ds.company_edges[cid][0].id
    watcher, other = member(admin), guest(admin)
    version = watcher.get("/api/me/settings").json()["version"]
    assert watcher.put("/api/me/settings", json={"version": version, "watchlistIds": [cid]}).status_code == 200

    send(watcher, node(cid), node(cid), {"type": "graph_edge_select", "targetId": edge})
    send(other, node(cid))
    ask(watcher, "어떤 실적을 발표했나요?", [cid])

    ranking = admin.client.get("/api/admin/insights/companies", params={"window": "all"}).json()
    row = next(r for r in ranking["items"] if r["companyId"] == cid)
    assert (row["nodeViews"], row["edgeSelections"], row["aiQuestions"], row["watchlistMembers"]) == (3, 1, 1, 1)
    assert ranking["items"][0]["companyId"] == cid  # the most viewed company comes first

    detail = admin.client.get(f"/api/admin/insights/companies/{cid}", params={"window": "7d"}).json()
    assert (detail["nodeViews"], detail["edgeSelections"], detail["aiQuestions"], detail["viewers"]) == (3, 1, 1, 2)
    assert sum(p["nodeViews"] for p in detail["series"]) == detail["nodeViews"]
    assert admin.client.get("/api/admin/insights/companies/NOPE", params={"window": "7d"}).status_code == 404


# ---- 75: votes


def test_one_vote_per_person_can_be_switched_and_taken_back(admin):
    publish_evening(admin)
    first, second = guest(admin), member(admin)
    target = {"feature": "briefing_round", "targetId": EVENING}

    assert first.put("/api/feedback", json={**target, "value": "up"}).json()["value"] == "up"
    assert first.put("/api/feedback", json={**target, "value": "up"}).status_code == 200  # same vote again: still one
    assert second.put("/api/feedback", json={**target, "value": "down"}).status_code == 200
    stat = next(f for f in admin.client.get("/api/admin/feedback/summary", params={"window": "all"}).json()["features"] if f["feature"] == "briefing_round")
    assert (stat["up"], stat["down"], stat["total"]) == (1, 1, 2)

    assert first.put("/api/feedback", json={**target, "value": "down", "reason": "근거가 부족해요"}).status_code == 200
    stat = next(f for f in admin.client.get("/api/admin/feedback/summary", params={"window": "all"}).json()["features"] if f["feature"] == "briefing_round")
    assert (stat["up"], stat["down"]) == (0, 2)  # switched, not added
    mine = first.get("/api/feedback", params={"feature": "briefing_round", "targetIds": EVENING}).json()["items"]
    assert [(i["value"], i["reason"]) for i in mine] == [("down", "근거가 부족해요")]

    assert first.delete("/api/feedback", params={"feature": "briefing_round", "targetId": EVENING}).status_code == 204
    assert first.delete("/api/feedback", params={"feature": "briefing_round", "targetId": EVENING}).status_code == 204  # idempotent
    assert first.get("/api/feedback", params={"feature": "briefing_round", "targetIds": EVENING}).json()["items"] == []
    stat = next(f for f in admin.client.get("/api/admin/feedback/summary", params={"window": "all"}).json()["features"] if f["feature"] == "briefing_round")
    assert (stat["up"], stat["down"]) == (0, 1)
    assert stat["sampleHidden"] is True and stat["rate"] is None  # one vote is not a percentage


def test_the_like_rate_appears_once_five_votes_exist(admin):
    publish_evening(admin)
    for index in range(5):
        voter = guest(admin)
        value = "down" if index == 0 else "up"
        assert voter.put("/api/feedback", json={"feature": "briefing_round", "targetId": EVENING, "value": value}).status_code == 200
    stat = next(f for f in admin.client.get("/api/admin/feedback/summary", params={"window": "all"}).json()["features"] if f["feature"] == "briefing_round")
    assert stat["sampleHidden"] is False and stat["rate"] == pytest.approx(0.8)
    assert sum(d["up"] for d in stat["days"]) == 4 and sum(d["down"] for d in stat["days"]) == 1


def test_votes_only_go_to_real_targets_and_answers_only_to_their_asker(admin):
    briefing = publish_evening(admin)
    user, other = guest(admin), guest(admin)
    answer = ask(user, "어떤 실적을 발표했나요?")
    issue = f"{EVENING}/{briefing['items'][0]['eventId']}"

    assert user.put("/api/feedback", json={"feature": "chatbot_answer", "targetId": answer["messageId"], "value": "up"}).status_code == 200
    assert user.put("/api/feedback", json={"feature": "briefing_issue", "targetId": issue, "value": "down", "reason": "선정 이유가 약해요"}).status_code == 200
    assert other.put("/api/feedback", json={"feature": "chatbot_answer", "targetId": answer["messageId"], "value": "up"}).status_code == 403
    for feature, target in (
        ("chatbot_answer", "chat-0000-m1"),
        ("briefing_round", "brf-2026-01-01-morning"),
        ("briefing_issue", f"{EVENING}/issue-unknown"),
        ("briefing_issue", EVENING),  # an issue vote needs an issue
    ):
        assert user.put("/api/feedback", json={"feature": feature, "targetId": target, "value": "up"}).status_code == 404, (feature, target)
    assert user.put("/api/feedback", json={"feature": "briefing_round", "targetId": EVENING, "value": "up", "reason": "좋아요에 사유"}).status_code == 422
    assert user.put("/api/feedback", json={"feature": "briefing_round", "targetId": EVENING, "value": "down", "reason": "가" * 201}).status_code == 422
    assert TestClient(admin.client.app).put("/api/feedback", json={"feature": "briefing_round", "targetId": EVENING, "value": "up"}).status_code == 401


# ---- 75: transcripts and masking


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("메일은 minsu.kim+test@example.co.kr 입니다", "email"),
        ("010-1234-5678로 연락", "phone"),
        ("01012345678 입니다", "phone"),
        ("+82 10-1234-5678", "phone"),
        ("02-345-6789", "phone"),
        ("주민번호 900101-1234567", "rrn"),
        ("카드 4111-1111-1111-1111", "card"),
        ("카드 4111 1111 1111 1111", "card"),
        ("계좌 110-123-456789", "account"),
        ("계좌 12345678901234", "account"),
        ("주민번호 9001011234567", "rrn"),
    ],
)
def test_each_personal_data_pattern_is_masked(text, kind):
    masked, counts = Masker().mask(text)
    assert counts[kind] == 1 and sum(counts.values()) == 1
    assert TOKENS[kind] in masked and not any(ch.isdigit() for ch in masked)


@pytest.mark.parametrize("text", ["2026-09-16 18:10 발표", "매출 12,345억 원", "주가 70000원", "2026년 3분기 실적", "issue-b4c3b887f7cb"])
def test_dates_amounts_and_ids_are_not_mistaken_for_personal_data(text):
    assert Masker().mask(text) == (text, {})


QUESTION = (
    "메일은 kim.minsu@example.com 이고 연락처는 010-1234-5678, 주민번호 900101-1234567, "
    "카드 4111 1111 1111 1111, 계좌 110-123-456789 입니다. 김민수 2026-09-16 실적은요?"
)


def test_transcripts_are_masked_when_read_and_the_stored_original_is_kept(admin):
    asker = member(admin)
    answer = ask(asker, QUESTION)
    session_id = answer["sessionId"]

    listing = admin.client.get("/api/admin/transcripts")
    detail = admin.client.get(f"/api/admin/transcripts/{session_id}")
    assert listing.status_code == 200 and detail.status_code == 200
    body = detail.json()
    text = body["messages"][0]["question"]
    for token in ("[이메일]", "[전화번호]", "[주민등록번호]", "[카드번호]", "[계좌번호]", "[이름]"):
        assert token in text
    assert "2026-09-16" in text  # a date is not an account number
    assert body["masking"]["counts"] == {"email": 1, "phone": 1, "rrn": 1, "card": 1, "account": 1, "name": 1}

    everything = listing.text + detail.text
    for secret in ("kim.minsu", "010-1234-5678", "900101", "4111", "110-123", "김민수"):
        assert secret not in everything
    assert body["user"].startswith("M-") and body["userKind"] == "member"

    stored = admin.services.db.one("SELECT question FROM chat_messages WHERE session_id=?", (session_id,))
    assert stored["question"] == QUESTION  # masking never rewrote the original

    audit = admin.client.get("/api/admin/audit-log", params={"action": "transcript.view"}).json()["items"]
    assert [(e["targetId"], e["actorEmail"]) for e in audit] == [(session_id, "admin@zoop.local")]
    assert "kim.minsu" not in json.dumps(audit)


def test_dislike_reasons_are_masked_and_link_to_the_conversation(admin):
    asker = member(admin)
    answer = ask(asker, "어떤 실적을 발표했나요?")
    reason = "답이 틀렸어요. 연락주세요 010-9999-8888 kim.minsu@example.com"
    assert asker.put("/api/feedback", json={"feature": "chatbot_answer", "targetId": answer["messageId"], "value": "down", "reason": reason}).status_code == 200

    page = admin.client.get("/api/admin/feedback/dislikes", params={"window": "all"}).json()
    row = page["items"][0]
    assert page["total"] == 1 and row["sessionId"] == answer["sessionId"]
    assert row["reason"] == "답이 틀렸어요. 연락주세요 [전화번호] [이메일]"
    assert row["voter"].startswith("M-") and "kim.minsu" not in json.dumps(page)

    only = admin.client.get("/api/admin/transcripts", params={"only": "disliked"}).json()
    assert [t["id"] for t in only["items"]] == [answer["sessionId"]] and only["items"][0]["down"] == 1


def test_conversations_survive_a_restart(admin):
    user = guest(admin)
    answer = ask(user, "어떤 실적을 발표했나요?")
    restarted = admin.restart()
    restarted.login()
    detail = restarted.client.get(f"/api/admin/transcripts/{answer['sessionId']}")
    assert detail.status_code == 200 and detail.json()["messages"][0]["id"] == answer["messageId"]
    assert restarted.client.get("/api/admin/transcripts/chat-missing").status_code == 404


def test_insight_admin_apis_refuse_members_and_visitors(admin):
    user = member(admin)
    for path in ("/api/admin/insights/summary", "/api/admin/feedback/summary", "/api/admin/transcripts", "/api/admin/members"):
        assert user.get(path).status_code == 403
        assert TestClient(admin.client.app).get(path).status_code == 401


# ---- 78: members


def test_members_are_listed_pseudonymously_with_masked_email_and_activity(admin):
    one = member(admin)
    send(one, node("c1"), node("c2"), {"type": "briefing_view", "targetId": EVENING, "viewId": vid()})
    ask(one, "어떤 실적을 발표했나요?")

    response = admin.client.get("/api/admin/members")
    assert response.status_code == 200
    listing = response.json()
    assert listing["counts"] == {"all": 2, "active": 2, "blocked": 0}  # the demo member and the new one; no admin
    by_mask = {m["emailMasked"]: m for m in listing["items"]}
    assert set(by_mask) == {"d***@zoop.local", "k***@example.com"}
    mine = by_mask["k***@example.com"]
    assert mine["id"].startswith("M-") and mine["signupMethod"] == "email"
    assert mine["activity"] == {"sessions": 1, "graphSelections": 2, "aiQuestions": 1, "briefingViews": 1}
    assert "kim.minsu" not in response.text and "김민수" not in response.text

    detail = admin.client.get(f"/api/admin/members/{mine['id']}").json()
    assert detail["member"]["id"] == mine["id"] and detail["history"] == [] and detail["onboardingCompleted"] is False
    assert admin.client.get("/api/admin/members/M-00000000").status_code == 404
    assert [m["id"] for m in admin.client.get("/api/admin/members", params={"q": "k***@"}).json()["items"]] == [mine["id"]]


def test_blocking_ends_the_session_refuses_login_and_is_idempotent_and_audited(admin):
    target = member(admin)
    other = demo(admin)
    pid = next(m["id"] for m in admin.client.get("/api/admin/members").json()["items"] if m["emailMasked"] == "k***@example.com")

    assert admin.client.post(f"/api/admin/members/{pid}/block", json={}).status_code == 422
    assert admin.client.post(f"/api/admin/members/{pid}/block", json={"reason": "   "}).status_code == 422
    assert target.get("/api/auth/session").json()["kind"] == "member"

    blocked = admin.client.post(f"/api/admin/members/{pid}/block", json={"reason": "약관 위반 신고 3건"})
    assert blocked.status_code == 200 and blocked.json()["changed"] is True
    assert blocked.json()["detail"]["member"]["status"] == "blocked"

    refused = send(target, node("c1"))  # the open tab's next request
    assert refused.status_code == 401 and refused.json()["error"]["code"] == "member_blocked"
    login = TestClient(admin.client.app).post("/api/auth/login", json={"email": "kim.minsu@example.com", "password": SIGNUP["password"]})
    assert login.status_code == 403 and login.json()["error"]["code"] == "member_blocked"
    assert other.get("/api/auth/session").json()["kind"] == "member"  # nobody else is affected

    again = admin.client.post(f"/api/admin/members/{pid}/block", json={"reason": "다시 눌렀어요"})
    assert again.status_code == 200 and again.json()["changed"] is False
    audit = admin.client.get("/api/admin/audit-log", params={"action": "member."}).json()["items"]
    assert [(e["action"], e["targetId"], e["reason"]) for e in audit] == [("member.block", pid, "약관 위반 신고 3건")]

    restored = admin.client.post(f"/api/admin/members/{pid}/unblock", json={"reason": "오해로 확인됨"})
    assert restored.status_code == 200 and restored.json()["changed"] is True
    assert admin.client.post(f"/api/admin/members/{pid}/unblock", json={"reason": "한 번 더"}).json()["changed"] is False
    relogin = TestClient(admin.client.app).post("/api/auth/login", json={"email": "kim.minsu@example.com", "password": SIGNUP["password"]})
    assert relogin.status_code == 200

    history = admin.client.get(f"/api/admin/members/{pid}").json()["history"]
    assert [(h["action"], h["reason"]) for h in history] == [("member.unblock", "오해로 확인됨"), ("member.block", "약관 위반 신고 3건")]
