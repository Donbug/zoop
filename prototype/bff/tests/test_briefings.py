"""Requirements 26-33, 79, 80: commute briefing rounds (windows, publication, immutability, corrections)."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from zoop_bff.config import BFF_ROOT

from .conftest import ALPHA_ISSUES, DEMO, base_payload

KST = timezone(timedelta(hours=9))
MORNING = "brf-2026-09-17-morning"
EVENING = "brf-2026-09-17-evening"
STRESS = BFF_ROOT / "fixtures" / "synthetic-stress-300.json"


def at(day: str, hour: int, minute: int = 0) -> datetime:
    return datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=KST)


def _admin_round(kit, rid):
    return kit.client.get(f"/api/admin/briefings/{rid}").json()


def _public(kit, **params):
    return kit.client.get("/api/briefings", params=params).json()


def _publish_morning(kit):
    kit.clock.travel_to(at("2026-09-17", 7, 45))
    assert kit.services.briefings.tick() == [MORNING]
    return _public(kit)


def test_scheduler_pass_publishes_the_due_round_once_with_an_open_first_window(admin):
    admin.clock.travel_to(at("2026-09-17", 7, 45))
    assert admin.services.briefings.tick() == [MORNING]
    assert admin.services.briefings.tick() == []  # nothing new, nothing duplicated

    briefing = _public(admin)
    assert (briefing["id"], briefing["status"], briefing["edition"], briefing["date"]) == (MORNING, "published", "morning", "2026-09-17")
    assert briefing["scheduledAt"] == "2026-09-17T07:40:00+09:00" and briefing["publishedAt"]
    assert briefing["dataWindow"] == {"start": None, "end": "2026-09-17T07:40:00+09:00", "openStart": True}
    assert briefing["dataAsOf"] == briefing["dataWindow"]["end"] and briefing["graphVersion"] == "v1"
    assert [i["rank"] for i in briefing["items"]] == [1, 2, 3]
    assert {i["eventId"] for i in briefing["items"]} == set(ALPHA_ISSUES.values())
    assert all(i["matchedCompanyIds"] == [] and i["reason"] and i["evidenceIds"] for i in briefing["items"])
    assert briefing["references"]["eventIds"] == [i["eventId"] for i in briefing["items"]]
    assert briefing["marketSummary"]["status"] == "unavailable"
    market = briefing["marketVariables"]  # no market source in this app: the round says so for each indicator
    assert market["status"] == "available" and [i["id"] for i in market["indicators"]] == ["kospi", "kosdaq", "usdkrw"]
    assert all(i["status"] == "unavailable" and i["reasonCode"] == "not_connected" and i["value"] is None for i in market["indicators"])
    assert briefing["metadata"]["schedule"] == {"morning": "07:40", "evening": "18:10", "confirmed": True}
    assert briefing["notice"] is None and briefing["corrections"] == []

    row = _admin_round(admin, MORNING)
    assert (row["status"], row["trigger"], row["attempts"], row["delayed"], row["itemCount"]) == ("published", "scheduler", 1, False, 3)
    assert [row["stages"][s]["status"] for s in ("generate", "verify", "publish")] == ["done", "done", "done"]
    assert row["graphVersion"] == "v1" and row["reviewRevision"] == 0
    assert row["published"]["items"] == briefing["items"]


def test_everyone_gets_the_same_published_round(admin):
    _publish_morning(admin)
    anonymous = TestClient(admin.client.app)
    member = TestClient(admin.client.app)
    assert member.post("/api/auth/login", json=DEMO).status_code == 200
    guest = TestClient(admin.client.app)
    guest.post("/api/auth/guest")
    bodies = [c.get("/api/briefings").json() for c in (anonymous, member, guest)]
    assert bodies[0] == bodies[1] == bodies[2]


def test_each_issue_belongs_to_exactly_one_round_and_an_empty_window_is_published_empty(make_admin):
    # The synthetic articles are published 2026-09-16 09:00 KST: inside the evening window of that day only.
    kit = make_admin()
    kit.login()
    kit.clock.travel_to(at("2026-09-16", 7, 45))
    assert kit.services.briefings.tick() == ["brf-2026-09-16-morning"]
    first = _public(kit)
    assert first["items"] == [] and first["emptyReason"] == "no_issues_in_window" and first["status"] == "published"
    assert first["dataWindow"]["openStart"] is True  # the service's first round has no lower bound

    kit.clock.travel_to(at("2026-09-16", 18, 15))
    assert kit.services.briefings.tick() == ["brf-2026-09-16-evening"]
    evening = _public(kit)
    assert {i["eventId"] for i in evening["items"]} == set(ALPHA_ISSUES.values())
    assert evening["dataWindow"] == {"start": first["dataWindow"]["end"], "end": "2026-09-16T18:10:00+09:00", "openStart": False}

    kit.clock.travel_to(at("2026-09-17", 7, 45))
    assert kit.services.briefings.tick() == ["brf-2026-09-17-morning"]
    next_morning = _public(kit)
    assert next_morning["items"] == [] and next_morning["emptyReason"] == "no_issues_in_window"  # not filled up with old news
    assert next_morning["dataWindow"]["start"] == evening["dataWindow"]["end"]  # windows tile the calendar


def test_a_window_with_few_issues_is_not_padded_to_three(make_admin):
    payload = json.loads(STRESS.read_text())

    def latest(issue):
        return max(datetime.fromisoformat(a["published_at"].replace("Z", "+00:00")) for a in issue["articles"])

    start, end = at("2026-07-16", 7, 40), at("2026-07-16", 18, 10)
    expected = {i["issue_id"] for i in payload["issues"] if start < latest(i) <= end}
    assert len(expected) == 2  # the fixture really has a two-issue window (guards the oracle)

    kit = make_admin(payload)
    kit.login()
    kit.clock.travel_to(at("2026-07-16", 7, 45))
    kit.services.briefings.tick()
    kit.clock.travel_to(at("2026-07-16", 18, 15))
    assert kit.services.briefings.tick() == ["brf-2026-07-16-evening"]
    evening = _public(kit)
    assert {i["eventId"] for i in evening["items"]} == expected and len(evening["items"]) == 2
    assert [i["rank"] for i in evening["items"]] == [1, 2]


def test_a_round_holds_at_most_three_core_issues(make_admin):
    kit = make_admin(json.loads(STRESS.read_text()))
    kit.login()
    kit.clock.travel_to(at("2026-09-10", 8))
    kit.services.briefings.tick()
    published = _admin_round(kit, "brf-2026-09-10-morning")["published"]
    assert published["selectedFrom"] > 3 and len(published["items"]) == 3
    times = [i["eventTime"] or "" for i in published["items"]]
    assert times == sorted(times, reverse=True)  # newest event first, the rule behind "선정 이유"


def test_a_published_round_cannot_be_replaced_by_any_path(admin):
    _publish_morning(admin)
    before = _admin_round(admin, MORNING)

    again = admin.client.post(f"/api/admin/briefings/{MORNING}/reprocess", json={"reason": "다시"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_published"
    admin.services.briefings.tick()
    after = _admin_round(admin, MORNING)
    assert after["published"] == before["published"] and after["publishedAt"] == before["publishedAt"] and after["attempts"] == 1

    db = admin.services.db
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE briefing_rounds SET payload='{}' WHERE id=?", (MORNING,))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM briefing_rounds WHERE id=?", (MORNING,))
    assert _admin_round(admin, MORNING)["published"] == before["published"]


def test_admin_reprocesses_only_rounds_that_are_due_and_not_before_the_first_one(admin):
    admin.clock.travel_to(at("2026-09-17", 8))
    rounds = admin.client.get("/api/admin/briefings").json()
    assert rounds["schedule"] == {"morning": "07:40", "evening": "18:10", "timezone": "Asia/Seoul"}
    newest, latest_due = rounds["items"][0], rounds["items"][1]
    assert (newest["id"], newest["status"], newest["reprocessable"]) == (EVENING, "scheduled", False)
    assert newest["blockedReason"]
    assert (latest_due["id"], latest_due["status"], latest_due["reprocessable"], latest_due["delayed"]) == (MORNING, "missing", True, True)
    assert all(r["id"] in (EVENING, MORNING) for r in rounds["items"])  # nothing before the first possible round

    early = admin.client.post(f"/api/admin/briefings/{EVENING}/reprocess", json={"reason": "일찍"})
    assert early.status_code == 409 and early.json()["error"]["code"] == "round_not_due"
    older = admin.client.post("/api/admin/briefings/brf-2026-09-16-evening/reprocess", json={"reason": "이전"})
    assert older.status_code == 409 and older.json()["error"]["code"] == "round_not_allowed"
    assert admin.client.post("/api/admin/briefings/not-a-round/reprocess", json={"reason": "x"}).status_code == 404
    assert admin.client.post(f"/api/admin/briefings/{MORNING}/reprocess", json={"reason": ""}).status_code == 422

    done = admin.client.post(f"/api/admin/briefings/{MORNING}/reprocess", json={"reason": "스케줄러가 놓친 회차"})
    assert done.status_code == 202 and done.json()["status"] == "published" and done.json()["trigger"] == "admin"
    actions = [e["action"] for e in admin.client.get("/api/admin/audit-log").json()["items"]]
    assert "briefing.reprocess" in actions and "briefing.generate" in actions

    # Once the service has a first round, older calendar slots stay closed and later ones follow the calendar.
    admin.clock.travel_to(at("2026-09-17", 19))
    evening = admin.client.post(f"/api/admin/briefings/{EVENING}/reprocess", json={"reason": "퇴근 회차"}).json()
    assert evening["dataWindow"] == {"start": "2026-09-17T07:40:00+09:00", "end": "2026-09-17T18:10:00+09:00", "openStart": False}


def test_the_scheduler_only_catches_up_a_recently_missed_round(admin):
    admin.clock.travel_to(at("2026-09-17", 15))  # the 07:40 round is 7h20m old
    assert admin.services.briefings.tick() == []
    assert _public(admin)["status"] == "not_ready"
    assert _admin_round(admin, MORNING)["status"] == "missing"


def test_a_failed_verification_is_visible_to_admins_only_and_a_later_attempt_can_publish(make_admin):
    broken = base_payload()
    q2 = next(i for i in broken["issues"] if i["issue_id"] == ALPHA_ISSUES["q2"])
    for ev in [e for m in q2["mentions"] for e in m["evidence"]] + [e for r in q2["relations"] for e in r["evidence"]]:
        ev["quote"] = "원문에 없는 문장"
    kit = make_admin(broken, ledger_payload=base_payload())
    kit.login()
    kit.clock.travel_to(at("2026-09-17", 8))
    assert kit.services.briefings.tick() == [MORNING]

    failed = _admin_round(kit, MORNING)
    assert failed["status"] == "failed" and "인용이 원문과 맞지 않음" in failed["failureReason"]
    assert [failed["stages"][s]["status"] for s in ("generate", "verify", "publish")] == ["done", "failed", "skipped"]
    assert failed["published"] is None and failed["reprocessable"] is True
    user = _public(kit)
    assert user["status"] == "failed" and user["items"] == [] and user["notice"]["kind"] == "failed"
    assert "인용" not in json.dumps(user, ensure_ascii=False) and user["notice"]["reason"] is None
    assert kit.services.briefings.tick() == []  # a failed round is not retried automatically

    again = kit.client.post(f"/api/admin/briefings/{MORNING}/reprocess", json={"reason": "같은 데이터로 재시도"})
    assert again.status_code == 202 and again.json()["status"] == "failed" and again.json()["attempts"] == 2

    # Publishing the corrected ledger as a new version lets the next attempt succeed.
    assert kit.client.post("/api/admin/graph/versions", json={"reason": "정정된 원장 반영"}).status_code == 201
    fixed = kit.client.post(f"/api/admin/briefings/{MORNING}/reprocess", json={"reason": "새 버전으로 재시도"}).json()
    assert (fixed["status"], fixed["attempts"], fixed["graphVersion"], fixed["failureReason"]) == ("published", 3, "v2", None)
    log = _admin_round(kit, MORNING)["attemptsLog"]
    assert [(a["n"], a["status"]) for a in log] == [(1, "failed"), (2, "failed"), (3, "published")]
    assert [a["trigger"] for a in log] == ["scheduler", "admin", "admin"]
    assert _public(kit)["status"] == "published"


def test_corrections_sit_beside_the_original_and_never_change_it(admin):
    published = _publish_morning(admin)
    first = published["items"][0]
    before = _admin_round(admin, MORNING)["published"]

    item = admin.client.post(
        f"/api/admin/briefings/{MORNING}/corrections",
        json={"eventId": first["eventId"], "correctedText": "정정된 제목입니다", "reason": "수치 오기"},
    )
    assert item.status_code == 201, item.text
    body = item.json()
    assert (body["seq"], body["eventId"], body["original"], body["corrected"]) == (1, first["eventId"], first["title"], "정정된 제목입니다")
    assert body["reason"] == "수치 오기" and body["createdAt"] and body["adminEmail"] == "admin@zoop.local"
    whole = admin.client.post(
        f"/api/admin/briefings/{MORNING}/corrections", json={"eventId": None, "correctedText": "전체 정정", "reason": "범위 오류"}
    ).json()
    assert (whole["seq"], whole["eventId"], whole["original"]) == (2, None, None)

    user = _public(admin)
    assert user["items"] == published["items"]  # the published items are exactly as before
    assert [(c["eventId"], c["original"], c["corrected"]) for c in user["corrections"]] == [
        (first["eventId"], first["title"], "정정된 제목입니다"),
        (None, None, "전체 정정"),
    ]
    assert _admin_round(admin, MORNING)["published"] == before
    assert _admin_round(admin, MORNING)["correctionCount"] == 2

    unknown = admin.client.post(
        f"/api/admin/briefings/{MORNING}/corrections", json={"eventId": "issue-nope", "correctedText": "x", "reason": "y"}
    )
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "unknown_item"
    too_long = admin.client.post(
        f"/api/admin/briefings/{MORNING}/corrections", json={"eventId": None, "correctedText": "가" * 1001, "reason": "y"}
    )
    assert too_long.status_code == 422
    unpublished = admin.client.post(
        f"/api/admin/briefings/{EVENING}/corrections", json={"eventId": None, "correctedText": "x", "reason": "y"}
    )
    assert unpublished.status_code == 409 and unpublished.json()["error"]["code"] == "not_published"


def test_suspending_hides_the_items_with_the_admin_reason_and_resuming_restores_them(admin):
    published = _publish_morning(admin)

    suspended = admin.client.post(f"/api/admin/briefings/{MORNING}/suspension", json={"action": "suspend", "reason": "원문 정정 확인 중"})
    assert suspended.status_code == 200 and suspended.json()["status"] == "suspended"
    assert suspended.json()["suspension"]["reason"] == "원문 정정 확인 중"
    user = _public(admin)
    assert (user["status"], user["items"]) == ("suspended", [])
    assert user["notice"]["kind"] == "suspended" and user["notice"]["reason"] == "원문 정정 확인 중" and user["notice"]["at"]
    rounds = admin.client.get("/api/briefings/rounds").json()["items"]
    assert [(r["id"], r["status"]) for r in rounds] == [(MORNING, "suspended")]
    assert _admin_round(admin, MORNING)["published"]["items"] == published["items"]  # the original is kept

    repeat = admin.client.post(f"/api/admin/briefings/{MORNING}/suspension", json={"action": "suspend", "reason": "또"})
    assert repeat.status_code == 200
    entries = admin.client.get("/api/admin/audit-log", params={"action": "briefing.suspend"}).json()["items"]
    assert len(entries) == 1  # same state again is a no-op
    assert admin.client.post(f"/api/admin/briefings/{MORNING}/reprocess", json={"reason": "교체"}).status_code == 409

    resumed = admin.client.post(f"/api/admin/briefings/{MORNING}/suspension", json={"action": "resume", "reason": "확인 끝"})
    assert resumed.json()["status"] == "published" and resumed.json()["suspension"] is None
    assert _public(admin)["items"] == published["items"]
    nothing = admin.client.post(f"/api/admin/briefings/{EVENING}/suspension", json={"action": "suspend", "reason": "x"})
    assert nothing.status_code == 409 and nothing.json()["error"]["code"] == "not_published"


def test_users_pick_a_round_by_date_and_edition_and_unready_rounds_say_so(admin):
    _publish_morning(admin)
    admin.clock.travel_to(at("2026-09-17", 19))
    admin.services.briefings.tick()

    latest = _public(admin)
    assert latest["id"] == EVENING and latest["status"] == "published"
    assert _public(admin, edition="morning")["id"] == MORNING
    assert _public(admin, date="2026-09-17", edition="morning")["id"] == MORNING
    assert [r["id"] for r in admin.client.get("/api/briefings/rounds").json()["items"]] == [EVENING, MORNING]

    future = _public(admin, date="2026-09-18", edition="morning")
    assert future["status"] == "not_ready" and future["items"] == [] and "07:40" in future["notice"]["message"]
    assert future["notice"]["kind"] == "not_ready" and future["publishedAt"] is None
    never = _public(admin, date="2026-09-01", edition="evening")
    assert never["status"] == "not_ready" and never["items"] == []
    assert admin.client.get("/api/briefings", params={"date": "bad"}).status_code == 422
    assert admin.client.get("/api/briefings", params={"edition": "noon"}).status_code == 422


def test_rounds_interrupted_by_a_restart_become_failed(admin):
    admin.clock.travel_to(at("2026-09-17", 8))
    db = admin.services.db
    db.execute(
        "INSERT INTO briefing_rounds(id,date,edition,status,data,payload,updated_at) VALUES (?,?,?,?,?,NULL,?)",
        (MORNING, "2026-09-17", "morning", "generating", json.dumps({"attempts": 1, "trigger": "scheduler", "stages": {"generate": {"status": "running", "at": "2026-09-17T00:00:00+00:00"}}}), "2026-09-17T00:00:00+00:00"),
    )
    db.execute("INSERT INTO meta(key,value) VALUES ('briefing_epoch', ?)", (MORNING,))
    db.execute(
        "INSERT INTO briefing_attempts(round_id,n,trigger,started_at,status) VALUES (?,1,'scheduler','2026-09-17T00:00:00+00:00','running')",
        (MORNING,),
    )
    assert _public(admin)["status"] == "generating"

    restarted = admin.restart()
    restarted.login()
    row = _admin_round(restarted, MORNING)
    assert row["status"] == "failed" and "다시 시작" in row["failureReason"]
    assert row["attemptsLog"][0]["status"] == "failed"
    assert row["reprocessable"] is True


def test_the_in_process_scheduler_publishes_the_due_round_when_the_app_starts(make_admin):
    kit = make_admin(briefing_scheduler=True)
    kit.clock.travel_to(at("2026-09-17", 8))
    with kit.client:  # the lifespan starts and stops the scheduler thread
        deadline = time.monotonic() + 5
        status = None
        while time.monotonic() < deadline and status != "published":
            status = kit.client.get("/api/briefings").json()["status"]
            time.sleep(0.05)
    assert status == "published"
    assert kit.client.get("/api/briefings").json()["id"] == MORNING
