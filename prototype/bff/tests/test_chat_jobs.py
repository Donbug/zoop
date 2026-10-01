"""AI chat question jobs (FS045-FS053, NFS001/003/009): idempotency, one job per conversation, frozen context,
asking back, failure kinds and what a retry may do. Engines and failures are injected; nothing calls a model."""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from zoop_bff.chat import AnswerPlan, Draft, EngineUnavailable, RuleEngine
from zoop_bff.chat_interpret import read_period
from zoop_bff.schemas import Citation, GraphTarget

from .chat_support import ask_job, job_body, new_id, new_member, open_conversation, wait_for
from .conftest import ALPHA_ISSUES, base_payload, with_companies

KST = timezone(timedelta(hours=9))
Q1 = ALPHA_ISSUES["q1"]


class FakeEngine:
    """Counts calls; can hold a call until released and misbehave on demand."""

    generated_by = "fake-engine"

    def __init__(self, *, hold: bool = False, fail_with: Exception | None = None, make_draft=None):
        self.plans: list[AnswerPlan] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        if not hold:
            self.release.set()
        self.fail_with = fail_with
        self.make_draft = make_draft
        self._real = RuleEngine()

    def generate(self, ds, plan: AnswerPlan) -> Draft:
        self.plans.append(plan)
        self.entered.set()
        assert self.release.wait(10), "test never released the engine"
        if self.fail_with is not None:
            raise self.fail_with
        if self.make_draft is not None:
            return self.make_draft(ds, plan)
        return self._real.generate(ds, plan)

    @property
    def calls(self) -> int:
        return len(self.plans)


def chats(client: TestClient):
    return client.app.state.zoop.chats


def clock(client: TestClient):
    return client.app.state.zoop.admin.clock


def db(client: TestClient):
    return client.app.state.zoop.admin.db


def messages_of(client: TestClient, session_id: str) -> int:
    return db(client).one("SELECT COUNT(*) AS n FROM chat_messages WHERE session_id=?", (session_id,))["n"]


def post_job(member: TestClient, session_id: str, body: dict):
    return member.post(f"/api/chat/sessions/{session_id}/jobs", json=body)


@pytest.fixture
def app(make_client):
    return make_client()


@pytest.fixture
def asker(app):
    return new_member(app)


# ---- FS045 / NFS001: who may ask


def test_a_guest_cannot_ask_and_a_visitor_has_no_session(app):
    visitor = TestClient(app.app)
    assert visitor.put("/api/chat/sessions/chat-visitor0001").status_code == 401
    guest = TestClient(app.app)
    assert guest.post("/api/auth/guest").status_code == 200
    for response in (
        guest.put("/api/chat/sessions/chat-guest00001"),
        guest.post("/api/chat/sessions/chat-guest00001/jobs", json=job_body("무엇인가요?", [Q1])),
        guest.get("/api/chat/sessions/current"),
        guest.get("/api/chat/jobs/job-guest00001"),
    ):
        assert response.status_code == 403 and response.json()["error"]["code"] == "guest_forbidden"


def test_an_empty_question_is_refused_before_it_becomes_a_job(asker):
    session = open_conversation(asker)
    assert post_job(asker, session, job_body("   ", [Q1])).status_code == 422
    assert asker.get(f"/api/chat/sessions/{session}").json()["jobs"] == []


# ---- FS046 / NFS003: idempotency, conflicts, one running job per conversation


def test_resending_a_job_returns_the_stored_job_and_never_asks_twice(app, asker):
    engine = chats(app).engine = FakeEngine()
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    first = post_job(asker, session, body)
    assert first.status_code == 202
    settled = wait_for(asker, body["jobId"])
    again = post_job(asker, session, body)
    assert again.status_code == 200 and again.json()["status"] == "completed"
    assert again.json()["result"] == settled["result"]
    assert engine.calls == 1 and messages_of(app, session) == 1
    assert asker.get(f"/api/chat/sessions/{session}").json()["session"]["jobs"] == 1


def test_concurrent_resends_of_one_job_run_it_once(app, asker):
    engine = chats(app).engine = FakeEngine(hold=True)
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])

    def send(_):
        client = TestClient(app.app)
        client.cookies.update(asker.cookies)
        return post_job(client, session, body).status_code

    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(send, range(8)))
    assert sorted(codes) == [200] * 7 + [202]
    engine.release.set()
    wait_for(asker, body["jobId"])
    assert engine.calls == 1 and messages_of(app, session) == 1


def test_the_same_job_id_with_another_body_is_a_conflict_that_changes_nothing(app, asker):
    chats(app).engine = FakeEngine()
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    assert post_job(asker, session, body).status_code == 202
    original = wait_for(asker, body["jobId"])

    for changed in (
        {**body, "question": "다른 질문이에요"},
        {**body, "context": {"contextIds": [ALPHA_ISSUES["q2"]]}},
        {**body, "context": {"contextIds": [Q1], "period": {"start": "2026-01-01", "end": "2026-01-31"}}},
    ):
        response = post_job(asker, session, changed)
        assert response.status_code == 409 and response.json()["error"]["code"] == "chat_job_conflict"
        assert "question" not in response.json()["error"]["details"]
    assert wait_for(asker, body["jobId"]) == original
    other = open_conversation(asker)  # the same id cannot be moved to another conversation either
    assert post_job(asker, other, body).status_code == 409


def test_a_job_id_taken_by_someone_else_is_never_revealed(app, asker):
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    assert post_job(asker, session, body).status_code == 202
    other = new_member(app)
    mine = open_conversation(other)
    response = post_job(other, mine, body)
    assert response.status_code == 409 and "result" not in response.json()
    assert other.get(f"/api/chat/jobs/{body['jobId']}").status_code == 403


def test_two_different_jobs_sent_at_once_to_one_conversation_accept_exactly_one(app, asker):
    engine = chats(app).engine = FakeEngine(hold=True)
    session = open_conversation(asker)
    bodies = [job_body(f"질문 {n}", [Q1]) for n in range(8)]

    def send(body):
        client = TestClient(app.app)
        client.cookies.update(asker.cookies)
        return body["jobId"], post_job(client, session, body)

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(send, bodies))
    accepted = [job_id for job_id, r in results if r.status_code == 202]
    refused = [r for _, r in results if r.status_code == 409]
    assert len(accepted) == 1 and len(refused) == 7
    assert {r.json()["error"]["code"] for r in refused} == {"chat_session_busy"}
    assert {r.json()["error"]["details"]["activeJobId"] for r in refused} == set(accepted)
    engine.release.set()
    wait_for(asker, accepted[0])
    assert engine.calls == 1
    # the refused ids were never registered: sending one again after the first finished is a new job
    refused_id = next(b["jobId"] for b in bodies if b["jobId"] not in accepted)
    assert asker.get(f"/api/chat/jobs/{refused_id}").status_code == 404
    assert post_job(asker, session, next(b for b in bodies if b["jobId"] == refused_id)).status_code == 202


def test_reading_a_busy_conversations_job_is_not_a_new_question(app, asker):
    engine = chats(app).engine = FakeEngine(hold=True)
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    post_job(asker, session, body)
    assert engine.entered.wait(5)
    for _ in range(3):
        status = asker.get(f"/api/chat/jobs/{body['jobId']}")
        assert status.status_code == 200 and status.json()["status"] == "running"
    assert post_job(asker, session, body).status_code == 200  # resending the running job's own id is a status read
    engine.release.set()
    wait_for(asker, body["jobId"])
    assert engine.calls == 1


def test_another_conversation_is_not_blocked_by_a_running_job(app, asker):
    engine = chats(app).engine = FakeEngine(hold=True)
    first, second = open_conversation(asker), open_conversation(asker)
    post_job(asker, first, job_body("질문 하나", [Q1]))
    assert engine.entered.wait(5)
    assert post_job(asker, second, job_body("질문 둘", [Q1])).status_code == 202
    engine.release.set()


# ---- FS047: the first receipt freezes the question


def test_a_relative_period_is_read_against_the_kst_day_the_question_was_first_received(app):
    chats(app).engine = FakeEngine(fail_with=EngineUnavailable("down"))
    clock(app).travel_to(datetime(2026, 12, 31, 14, 30, tzinfo=timezone.utc))  # 23:30 on the last day of 2026 in Korea
    asker = new_member(app)
    session = open_conversation(asker)
    body = job_body("작년 실적은?", [Q1])
    post_job(asker, session, body)
    failed = wait_for(asker, body["jobId"])
    assert failed["status"] == "failed" and failed["failure"]["kind"] == "transient" and failed["failure"]["retry"] == "rerun"
    assert failed["askedAt"].startswith("2026-12-31T14:30")

    clock(app).travel_to(datetime(2027, 1, 2, tzinfo=timezone.utc))  # "last year" would be 2026 now; the job keeps 2025
    engine = chats(app).engine = FakeEngine()
    assert asker.post(f"/api/chat/jobs/{body['jobId']}/retry").status_code == 202
    done = wait_for(asker, body["jobId"])
    assert done["status"] == "completed"
    assert done["result"]["applied"]["period"] == {"start": "2025-01-01", "end": "2025-12-31", "basis": "question", "expression": "작년"}
    assert engine.plans[0].period.start == "2025-01-01"
    assert done["result"]["outcome"] == "insufficient_evidence" and done["result"]["reason"] == "no_evidence_in_period"


@pytest.mark.parametrize(
    ("question", "today", "expected"),
    [
        ("작년 실적", date(2027, 1, 1), ("2026-01-01", "2026-12-31")),  # the whole previous calendar year
        ("최근 이슈", date(2026, 3, 31), ("2026-02-28", "2026-03-31")),  # one month back, clamped to a real day
        ("지난달 뉴스", date(2026, 1, 15), ("2025-12-01", "2025-12-31")),
        ("작년 3월에 무슨 일이", date(2026, 10, 1), ("2025-03-01", "2025-03-31")),
        ("최근 3개월", date(2026, 10, 1), ("2026-07-01", "2026-10-01")),
    ],
)
def test_relative_dates_resolve_to_real_periods(question, today, expected):
    reading = read_period(question, today)
    assert reading.ambiguous is None and (reading.period.start, reading.period.end) == expected


@pytest.mark.parametrize("question", ["그때 무슨 일이 있었나요", "3월에 발표했나요", "3개월 전 이야기", "작년과 올해 비교"])
def test_a_period_that_cannot_be_fixed_is_reported_as_ambiguous(question):
    reading = read_period(question, date(2026, 10, 1))
    assert reading.period is None and reading.ambiguous


def test_recent_means_the_last_month_and_the_applied_period_is_shown(app, asker):
    clock(app).travel_to(datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc))
    done = ask_job(asker, "최근 실적은?", [Q1])
    assert done["result"]["outcome"] == "answered"
    assert done["result"]["applied"]["period"] == {"start": "2026-09-01", "end": "2026-10-01", "basis": "question", "expression": "최근"}
    assert [c["id"] for c in done["result"]["applied"]["companies"]] == ["SYNTH-ALPHA"]
    assert [i["id"] for i in done["result"]["applied"]["issues"]] == [Q1]


def test_the_period_of_the_selection_applies_unless_the_question_names_one(app, asker):
    clock(app).travel_to(datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc))
    selected = {"period": {"start": "2026-09-10", "end": "2026-09-20"}}
    kept = ask_job(asker, "어떤 실적을 발표했나요?", [Q1], **selected)
    assert kept["result"]["applied"]["period"]["basis"] == "context" and kept["result"]["outcome"] == "answered"
    assert kept["context"]["period"] == {"start": "2026-09-10", "end": "2026-09-20"}
    outside = ask_job(asker, "어떤 실적을 발표했나요?", [Q1], period={"start": "2026-01-01", "end": "2026-01-31"})
    assert outside["result"]["outcome"] == "insufficient_evidence" and outside["result"]["reason"] == "no_evidence_in_period"
    overridden = ask_job(asker, "최근 실적은?", [Q1], period={"start": "2026-01-01", "end": "2026-01-31"})
    assert overridden["result"]["applied"]["period"]["basis"] == "question" and overridden["result"]["outcome"] == "answered"


def test_a_retry_keeps_the_original_context_even_if_the_selection_changed_since(app, asker):
    flaky = chats(app).engine = FakeEngine(fail_with=EngineUnavailable("down"))
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    post_job(asker, session, body)
    wait_for(asker, body["jobId"])
    failed_plans = list(flaky.plans)
    chats(app).engine = good = FakeEngine()
    asker.post(f"/api/chat/jobs/{body['jobId']}/retry")
    done = wait_for(asker, body["jobId"])
    assert done["status"] == "completed" and done["runs"] == 2
    assert [c.id for c in good.plans[0].contexts] == [c.id for c in failed_plans[0].contexts] == [Q1]
    assert good.plans[0].evidence_ids == failed_plans[0].evidence_ids


# ---- FS047: asking back is a completed, stored result


def test_an_unclear_target_is_asked_back_and_the_answer_is_a_new_job(app, asker):
    engine = chats(app).engine = FakeEngine()
    session = open_conversation(asker)
    asked = ask_job(asker, "이 회사 요즘 어때요?", [], session_id=session)
    assert asked["status"] == "completed" and asked["outcome"] == "clarification"
    assert asked["result"]["reason"] == "ambiguous_target" and "이 회사" in asked["result"]["answer"]
    assert asked["result"]["citations"] == [] and engine.calls == 0
    assert messages_of(app, session) == 1  # stored like any answer
    again = asker.get(f"/api/chat/jobs/{asked['id']}").json()
    assert again["result"] == asked["result"] and again["outcome"] == "clarification"

    follow_up = ask_job(asker, "합성 알파전자의 실적을 알려 주세요", [], session_id=session)
    assert follow_up["id"] != asked["id"] and follow_up["seq"] == 2 and follow_up["outcome"] == "answered"
    assert follow_up["result"]["applied"]["companies"] == [{"id": "SYNTH-ALPHA", "label": "합성 알파전자"}]
    assert [j["seq"] for j in asker.get(f"/api/chat/sessions/{session}").json()["jobs"]] == [1, 2]


def test_a_vague_period_is_asked_back_instead_of_guessed(app, asker):
    engine = chats(app).engine = FakeEngine()
    asked = ask_job(asker, "그때 무슨 일이 있었나요?", [Q1])
    assert asked["outcome"] == "clarification" and asked["result"]["reason"] == "ambiguous_period" and engine.calls == 0


def test_a_name_that_fits_several_companies_offers_them_as_choices(make_client):
    client = make_client(with_companies(base_payload(), 3))
    asker = new_member(client)
    asked = ask_job(asker, "합성 기업 실적은 어때요?", [])
    assert asked["outcome"] == "clarification" and asked["result"]["reason"] == "ambiguous_company"
    choices = {c["id"] for c in asked["result"]["choices"]}
    assert choices >= {"SYNTH-C0", "SYNTH-C1", "SYNTH-C2"}
    # picking one is the supplementary input: a new job with the same words and the chosen company selected
    picked = ask_job(asker, "합성 기업 실적은 어때요?", ["SYNTH-C1"], session_id=asked["sessionId"])
    assert picked["id"] != asked["id"] and picked["outcome"] != "clarification"
    assert [c["id"] for c in picked["result"]["applied"]["companies"]] == ["SYNTH-C1"]


def test_a_company_named_in_the_question_wins_over_the_selection(make_client):
    client = make_client(with_companies(base_payload(), 3))
    asker = new_member(client)
    done = ask_job(asker, "합성 기업0 관련 사건이 있나요?", [Q1])
    applied = done["result"]["applied"]
    assert applied["questionOverrodeContext"] is True and [c["id"] for c in applied["companies"]] == ["SYNTH-C0"]
    assert done["outcome"] == "insufficient_evidence"  # the replaced selection's evidence is not borrowed


# ---- FS048: conditions and evidence


def test_a_personal_question_without_a_watch_list_is_a_stored_guidance_and_later_settings_do_not_reopen_it(app, asker):
    session = open_conversation(asker)
    guidance = ask_job(asker, "내 관심 종목 이슈를 알려 주세요", [], session_id=session)
    assert guidance["outcome"] == "guidance" and guidance["result"]["reason"] == "watchlist_empty"
    assert guidance["result"]["action"] == {"kind": "set_watchlist", "label": "내 종목 설정하기"}

    version = asker.get("/api/me/settings").json()["version"]
    assert asker.put("/api/me/settings", json={"version": version, "watchlistIds": ["SYNTH-ALPHA"]}).status_code == 200
    assert asker.get(f"/api/chat/jobs/{guidance['id']}").json()["outcome"] == "guidance"  # never re-evaluated
    renewed = ask_job(asker, "내 관심 종목 이슈를 알려 주세요", [], session_id=session)  # only a new question sees the new setting
    assert renewed["outcome"] == "answered" and [c["id"] for c in renewed["result"]["applied"]["companies"]] == ["SYNTH-ALPHA"]


def test_a_prediction_request_is_declined_without_citations(app, asker):
    declined = ask_job(asker, "이 종목 주가 전망은?", ["SYNTH-ALPHA"])
    assert declined["outcome"] == "insufficient_evidence" and declined["result"]["reason"] == "prediction_or_advice_not_supported"
    assert declined["result"]["sources"] == []


def test_a_graph_version_that_changed_is_not_swapped_for_the_new_one(make_admin):
    ledger = base_payload()
    ledger["issues"] = [i for i in ledger["issues"] if i["issue_id"] != ALPHA_ISSUES["q2"]]
    kit = make_admin(ledger_payload=ledger)
    kit.login()
    asker = new_member(kit.client)
    service = chats(kit.client)
    held: list[str] = []
    service._enqueue = held.append  # the job is accepted and waits; nothing runs yet
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [ALPHA_ISSUES["q2"]])
    assert post_job(asker, session, body).status_code == 202
    assert kit.client.post("/api/admin/graph/versions", json={"reason": "다음 버전"}).status_code == 201
    del service._enqueue
    service._run(held[0])
    job = asker.get(f"/api/chat/jobs/{body['jobId']}").json()
    assert job["status"] == "completed" and job["outcome"] == "insufficient_evidence"
    assert job["result"]["reason"] == "pinned_version_unavailable" and job["result"]["citations"] == []


# ---- FS049 / NFS009: what may be shown, and what a retry may do


def _bad_citation(ds, plan):
    ev = next(iter(ds.evidence.values()))
    fake = Citation(
        evidence_id="ev-does-not-exist", quote=ev.quote, article_id=ev.article_id, article_version=ev.article_version,
        start=ev.start, end=ev.end, article_title=None, publisher=None, published_at=None, url=None,
    )
    return Draft("answered", "근거가 없는 인용", None, ("ev-does-not-exist",), (), (fake,))


def _bad_target(ds, plan):
    draft = RuleEngine().generate(ds, plan)
    return Draft(draft.status, draft.text, draft.reason, draft.evidence_ids, (GraphTarget(id="issue-not-in-graph", kind="issue"),), draft.citations)


def test_answers_only_link_graph_targets_that_can_be_opened_there(app, asker):
    ds = app.app.state.zoop.provider.get()
    issue_company_edge = next(e.id for e in ds.edges.values() if not e.derived)  # D03: never a selectable target
    done = ask_job(asker, "어떤 실적을 발표했나요?", [issue_company_edge])
    assert done["status"] == "completed" and done["outcome"] == "answered"
    assert all(t["kind"] != "edge" for t in done["result"]["graphTargets"])
    assert {(t["kind"], t["id"]) for t in done["result"]["graphTargets"]}  # the issue it belongs to is still offered


@pytest.mark.parametrize("make_draft", [_bad_citation, _bad_target])
def test_an_answer_that_fails_validation_is_never_shown_regenerated_or_retried(app, asker, make_draft):
    engine = chats(app).engine = FakeEngine(make_draft=make_draft)
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    post_job(asker, session, body)
    failed = wait_for(asker, body["jobId"])
    assert failed["status"] == "failed" and failed["result"] is None
    assert failed["failure"]["kind"] == "validation_failed" and failed["failure"]["retry"] is None
    assert messages_of(app, session) == 0

    retry = asker.post(f"/api/chat/jobs/{body['jobId']}/retry")
    assert retry.status_code == 409 and retry.json()["error"]["code"] == "chat_job_not_retryable"
    assert post_job(asker, session, body).json()["status"] == "failed"  # resending the same id does not regenerate either
    assert engine.calls == 1
    # the member fixes the question and sends it as a new job
    chats(app).engine = RuleEngine()
    assert ask_job(asker, "다시 물어볼게요", [Q1], session_id=session)["status"] == "completed"


def test_a_confirmed_temporary_failure_is_retried_only_when_the_member_asks(app, asker):
    engine = chats(app).engine = FakeEngine(fail_with=EngineUnavailable("busy"))
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    post_job(asker, session, body)
    failed = wait_for(asker, body["jobId"])
    assert failed["failure"]["kind"] == "transient" and failed["failure"]["retry"] == "rerun"
    assert post_job(asker, session, body).json()["status"] == "failed" and engine.calls == 1  # no hidden rerun

    chats(app).engine = good = FakeEngine()
    assert asker.post(f"/api/chat/jobs/{body['jobId']}/retry").status_code == 202
    done = wait_for(asker, body["jobId"])
    assert done["status"] == "completed" and done["runs"] == 2 and good.calls == 1
    assert asker.post(f"/api/chat/jobs/{body['jobId']}/retry").status_code == 200  # nothing left to retry
    assert good.calls == 1 and messages_of(app, session) == 1


def test_a_retry_cannot_start_while_the_conversation_has_another_running_job(app, asker):
    chats(app).engine = FakeEngine(fail_with=EngineUnavailable("down"))
    session = open_conversation(asker)
    failed = job_body("어떤 실적을 발표했나요?", [Q1])
    post_job(asker, session, failed)
    wait_for(asker, failed["jobId"])
    chats(app).engine = busy = FakeEngine(hold=True)
    assert post_job(asker, session, job_body("다른 질문", [Q1])).status_code == 202
    assert busy.entered.wait(5)

    refused = asker.post(f"/api/chat/jobs/{failed['jobId']}/retry")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "chat_session_busy"
    assert asker.get(f"/api/chat/jobs/{failed['jobId']}").json()["status"] == "failed"  # still retryable later
    busy.release.set()


def test_an_unclassified_error_is_not_retried(app, asker):
    engine = chats(app).engine = FakeEngine(fail_with=RuntimeError("???"))
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    post_job(asker, session, body)
    failed = wait_for(asker, body["jobId"])
    assert failed["failure"]["kind"] == "internal" and failed["failure"]["retry"] is None
    assert asker.post(f"/api/chat/jobs/{body['jobId']}/retry").status_code == 409 and engine.calls == 1


def test_the_number_of_reruns_is_limited(app, asker):
    engine = chats(app).engine = FakeEngine(fail_with=EngineUnavailable("down"))
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    post_job(asker, session, body)
    job = wait_for(asker, body["jobId"])
    while job["failure"]["retry"] == "rerun":
        assert asker.post(f"/api/chat/jobs/{body['jobId']}/retry").status_code == 202
        job = wait_for(asker, body["jobId"], until=lambda j: j["status"] == "failed" and j["runs"] > job["runs"])
    assert job["failure"]["retry"] is None and engine.calls == 4
    assert asker.post(f"/api/chat/jobs/{body['jobId']}/retry").status_code == 409


def test_a_failed_save_keeps_the_verified_result_and_only_saving_is_repeated(app, asker):
    engine = chats(app).engine = FakeEngine()
    store = chats(app).store
    real_commit = store.commit
    broken = {"on": True}

    def commit(*args, **kwargs):
        if broken["on"]:
            raise sqlite3.OperationalError("disk I/O error")
        return real_commit(*args, **kwargs)

    store.commit = commit
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    post_job(asker, session, body)
    failed = wait_for(asker, body["jobId"])
    assert failed["status"] == "failed" and failed["failure"]["kind"] == "save_failed" and failed["failure"]["retry"] == "save_only"
    assert failed["result"] is None and messages_of(app, session) == 0  # an unsaved answer is not shown

    broken["on"] = False
    assert asker.post(f"/api/chat/jobs/{body['jobId']}/retry").status_code == 202
    done = wait_for(asker, body["jobId"])
    assert done["status"] == "completed" and done["result"]["outcome"] == "answered"
    assert engine.calls == 1 and messages_of(app, session) == 1  # no second model call, no duplicate answer


def test_a_verified_result_that_could_not_be_kept_is_lost_and_never_regenerated(app, asker):
    engine = chats(app).engine = FakeEngine()
    store = chats(app).store

    def preserve(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    store.preserve = preserve
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    post_job(asker, session, body)
    lost = wait_for(asker, body["jobId"])
    assert lost["failure"]["kind"] == "result_lost" and lost["failure"]["retry"] is None
    assert asker.post(f"/api/chat/jobs/{body['jobId']}/retry").status_code == 409
    assert engine.calls == 1 and messages_of(app, session) == 0


def test_a_failing_status_read_is_not_reported_as_an_unregistered_job(app, asker):
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    post_job(asker, session, body)
    wait_for(asker, body["jobId"])
    assert asker.get("/api/chat/jobs/job-never-sent-1").status_code == 404  # looked and found nothing

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    chats(app).store.owned_job = broken
    server = TestClient(app.app, raise_server_exceptions=False)
    server.cookies.update(asker.cookies)
    response = server.get(f"/api/chat/jobs/{body['jobId']}")
    assert response.status_code == 500 and response.json()["error"]["code"] == "internal_error"


# ---- late runs, cancellation and restarts (NFS009)


def test_a_run_that_outlives_its_lease_cannot_overwrite_the_job(app, asker):
    slow = chats(app).engine = FakeEngine(hold=True)
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    post_job(asker, session, body)
    assert slow.entered.wait(5)

    clock(app).advance(chats(app).lease_seconds + 1)
    timed_out = asker.get(f"/api/chat/jobs/{body['jobId']}").json()
    assert timed_out["status"] == "failed" and timed_out["failure"]["reason"] == "execution_timeout"
    assert timed_out["failure"]["retry"] == "rerun"

    chats(app).engine = fast = FakeEngine()
    asker.post(f"/api/chat/jobs/{body['jobId']}/retry")
    done = wait_for(asker, body["jobId"])
    assert done["status"] == "completed" and done["runs"] == 2

    slow.release.set()  # the first run finally ends
    threading.Event().wait(0.3)
    after = asker.get(f"/api/chat/jobs/{body['jobId']}").json()
    assert after["result"] == done["result"] and after["runs"] == 2
    assert messages_of(app, session) == 1 and fast.calls == 1


def test_a_cancelled_job_stays_cancelled_and_frees_the_conversation(app, asker):
    engine = chats(app).engine = FakeEngine(hold=True)
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    post_job(asker, session, body)
    assert engine.entered.wait(5)
    assert post_job(asker, session, job_body("또 질문", [Q1])).status_code == 409

    cancelled = asker.post(f"/api/chat/jobs/{body['jobId']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    engine.release.set()
    threading.Event().wait(0.3)
    still = asker.get(f"/api/chat/jobs/{body['jobId']}").json()
    assert still["status"] == "cancelled" and still["result"] is None and messages_of(app, session) == 0
    assert asker.post(f"/api/chat/jobs/{body['jobId']}/retry").status_code == 409
    assert post_job(asker, session, job_body("이어서 질문", [Q1])).status_code == 202


def test_after_a_restart_an_interrupted_run_is_a_retryable_failure_and_the_old_run_cannot_overwrite(make_admin):
    kit = make_admin()
    kit.login()
    asker = new_member(kit.client)
    old = chats(kit.client).engine = FakeEngine(hold=True)
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    post_job(asker, session, body)
    assert old.entered.wait(5)

    restarted = kit.restart()
    again = TestClient(restarted.client.app)
    again.cookies.update(asker.cookies)
    interrupted = again.get(f"/api/chat/jobs/{body['jobId']}").json()
    assert interrupted["status"] == "failed" and interrupted["failure"]["reason"] == "server_restarted"
    assert interrupted["failure"]["retry"] == "rerun"
    # while it waits the conversation is free again, and nothing was started behind the member's back
    assert old.calls == 1

    fresh_engine = chats(again).engine = FakeEngine()
    assert again.post(f"/api/chat/jobs/{body['jobId']}/retry").status_code == 202
    done = wait_for(again, body["jobId"])
    assert done["status"] == "completed" and fresh_engine.calls == 1

    old.release.set()  # the process that no longer exists finishes late
    threading.Event().wait(0.3)
    assert again.get(f"/api/chat/jobs/{body['jobId']}").json()["result"] == done["result"]
    assert messages_of(again, session) == 1


def test_after_a_restart_a_kept_verified_result_is_saved_without_asking_the_engine_again(make_admin):
    kit = make_admin()
    kit.login()
    asker = new_member(kit.client)
    engine = chats(kit.client).engine = FakeEngine()
    reached_save = threading.Event()
    proceed = threading.Event()
    store = chats(kit.client).store
    real_commit = store.commit

    def stalled_commit(*args, **kwargs):
        reached_save.set()
        proceed.wait(10)
        return real_commit(*args, **kwargs)

    store.commit = stalled_commit
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    post_job(asker, session, body)
    assert reached_save.wait(5)

    restarted = kit.restart()
    again = TestClient(restarted.client.app)
    again.cookies.update(asker.cookies)
    recovered_engine = chats(again).engine = FakeEngine()
    done = wait_for(again, body["jobId"])
    assert done["status"] == "completed" and done["result"]["outcome"] == "answered"
    assert engine.calls == 1 and recovered_engine.calls == 0

    proceed.set()
    threading.Event().wait(0.3)
    assert messages_of(again, session) == 1
    assert again.get(f"/api/chat/jobs/{body['jobId']}").json()["result"] == done["result"]


# ---- FS051 / FS052: conversations


def test_creating_a_conversation_twice_with_the_same_id_makes_one(asker):
    session_id = new_id("chat")
    first = asker.put(f"/api/chat/sessions/{session_id}")
    again = asker.put(f"/api/chat/sessions/{session_id}")
    assert (first.status_code, again.status_code) == (201, 200) and first.json() == again.json()


def test_a_new_conversation_starts_empty_and_a_late_answer_of_the_old_one_stays_with_the_old_one(app, asker):
    engine = chats(app).engine = FakeEngine(hold=True)
    old = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    post_job(asker, old, body)
    assert engine.entered.wait(5)

    fresh = open_conversation(asker)  # starting over never cancels or deletes the running question
    assert asker.get(f"/api/chat/sessions/{fresh}").json()["jobs"] == []
    assert asker.get("/api/chat/sessions/current").json()["conversation"]["session"]["id"] == fresh
    engine.release.set()
    done = wait_for(asker, body["jobId"])
    assert done["status"] == "completed" and done["sessionId"] == old
    assert asker.get(f"/api/chat/sessions/{fresh}").json()["jobs"] == []
    assert [j["id"] for j in asker.get(f"/api/chat/sessions/{old}").json()["jobs"]] == [body["jobId"]]


def test_reopening_returns_the_saved_conversation_without_asking_again(app, asker):
    engine = chats(app).engine = FakeEngine()
    assert asker.get("/api/chat/sessions/current").json() == {"conversation": None}
    session = open_conversation(asker)
    first = ask_job(asker, "어떤 실적을 발표했나요?", [Q1], session_id=session)
    second = ask_job(asker, "언제 알려졌나요?", [Q1], session_id=session)
    for _ in range(3):  # the panel closes and opens, the page changes: only reads
        conversation = asker.get("/api/chat/sessions/current").json()["conversation"]
        assert [j["id"] for j in conversation["jobs"]] == [first["id"], second["id"]]
        assert conversation["jobs"][1]["result"] == second["result"]
    assert engine.calls == 2 and messages_of(app, session) == 2


def test_a_pending_job_is_found_again_and_finishes_while_nobody_is_looking(app, asker):
    engine = chats(app).engine = FakeEngine(hold=True)
    session = open_conversation(asker)
    body = job_body("어떤 실적을 발표했나요?", [Q1])
    post_job(asker, session, body)
    assert engine.entered.wait(5)
    pending = asker.get("/api/chat/sessions/current").json()["conversation"]["jobs"][0]
    assert pending["status"] == "running" and pending["result"] is None
    engine.release.set()
    wait_for(asker, body["jobId"])
    finished = asker.get("/api/chat/sessions/current").json()["conversation"]["jobs"][0]
    assert finished["status"] == "completed" and finished["result"]["answer"] and engine.calls == 1
