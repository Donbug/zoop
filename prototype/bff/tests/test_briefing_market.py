"""FS031/FS033/FS035: the market indicators fixed into a round, and what an evening round changed since the morning.

The source is a Yahoo-style chart served through ``httpx.MockTransport`` (no network). It ignores the request's end
time on purpose, as the real endpoint has been seen to, so the tests prove the BFF keeps to the round's cut-off itself.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import pytest

from zoop_bff.briefing_market import MarketIndicators
from zoop_bff.briefing_rounds import _reported_at
from zoop_bff.briefing_since import compare
from zoop_bff.market_data import TtlCache
from zoop_bff.quote_yahoo import YahooProvider

KST = timezone(timedelta(hours=9))
MORNING = "brf-2026-09-17-morning"
EVENING = "brf-2026-09-17-evening"


def kst(day: str, hour: int = 0, minute: int = 0) -> datetime:
    return datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=KST)


class FakeYahoo:
    """Daily index closes (09:00 KST bars) and 5-minute rate bars, 2026-09-14 (Mon) to 2026-09-17 (Thu)."""

    def __init__(self) -> None:
        self.daily: dict[str, dict[str, float]] = {
            "^KS11": {"2026-09-14": 7000.0, "2026-09-15": 7010.0, "2026-09-16": 7040.0, "2026-09-17": 7100.0},
            "^KQ11": {"2026-09-14": 850.0, "2026-09-15": 851.0, "2026-09-16": 853.0, "2026-09-17": 860.0},
        }
        self.rate: list[tuple[datetime, float]] = [
            (kst("2026-09-15", 15, 30), 1350.0),
            (kst("2026-09-16", 10, 0), 1352.0),
            (kst("2026-09-16", 15, 30), 1355.0),  # the Seoul close: the base of the change
            (kst("2026-09-16", 15, 35), 1356.0),  # after the close: never the base
            (kst("2026-09-17", 7, 35), 1360.0),
            (kst("2026-09-17", 7, 50), 1399.0),  # after the morning cut-off
            (kst("2026-09-17", 17, 55), 1362.0),
            (kst("2026-09-17", 18, 0), 1363.5),
            (kst("2026-09-17", 18, 10), 1400.0),  # after the 18:05 cut-off
        ]
        self.fail: dict[str, int] = {}
        self.calls: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        symbol = request.url.path.rsplit("/", 1)[-1]
        interval = request.url.params["interval"]
        self.calls.append((symbol, interval))
        if symbol in self.fail:
            return httpx.Response(self.fail[symbol], json={"chart": {"result": None, "error": {"code": "x"}}})
        if interval == "1d":
            bars = [(kst(day, 9), close) for day, close in sorted(self.daily[symbol].items())] if symbol in self.daily else []
            offset = 32400
        else:
            bars, offset = list(self.rate), 3600  # a zone that is not KST: the BFF must convert
        result = {
            "meta": {"currency": "KRW", "symbol": symbol, "gmtoffset": offset},
            "timestamp": [int(t.timestamp()) for t, _ in bars],
            "indicators": {"quote": [{"close": [c for _, c in bars]}]},
        }
        return httpx.Response(200, json={"chart": {"result": [result], "error": None}})

    def provider(self) -> YahooProvider:
        return YahooProvider(base_url="https://y.test", timeout=1, cache=TtlCache(), transport=httpx.MockTransport(self.handler))


@pytest.fixture
def market_kit(make_admin):
    fake = FakeYahoo()
    kit = make_admin(market=fake.provider(), admin_idle_seconds=7 * 86400, admin_absolute_seconds=30 * 86400)
    kit.login()
    return kit, fake


def _indicators(body: dict[str, Any]) -> dict[str, Any]:
    assert body["marketVariables"]["status"] == "available"
    return {i["id"]: i for i in body["marketVariables"]["indicators"]}


def _public(kit, **params):
    return kit.client.get("/api/briefings", params=params).json()


def test_a_round_stores_the_indicators_as_known_at_its_reference_point(market_kit):
    kit, fake = market_kit
    kit.clock.travel_to(kst("2026-09-17", 7, 45))
    assert kit.services.briefings.tick() == [MORNING]

    market = _public(kit)["marketVariables"]
    assert market["referenceAt"] == "2026-09-17T07:40:00+09:00" and market["rateCutoffAt"] == "2026-09-17T07:40:00+09:00"
    by_id = _indicators(_public(kit))
    # Morning: the previous session's close (09-16, not the 09-17 bar) against the session before it.
    kospi = by_id["kospi"]
    assert (kospi["status"], kospi["value"], kospi["valueKind"], kospi["observedDate"], kospi["observedAt"]) == ("ok", 7040.0, "close", "2026-09-16", None)
    assert kospi["baseline"] == {"value": 7010.0, "date": "2026-09-15", "at": None}
    assert kospi["change"] == 30.0 and kospi["changeRate"] == round(30 / 7010, 8)
    assert kospi["source"]["name"] == "Yahoo Finance" and kospi["source"]["symbol"] == "^KS11" and kospi["source"]["official"] is False
    assert (by_id["kosdaq"]["value"], by_id["kosdaq"]["change"]) == (853.0, 2.0)
    # The rate: the last observation at or before 07:40 with its real KST time, against the Seoul close of the day before.
    rate = by_id["usdkrw"]
    assert (rate["status"], rate["value"], rate["valueKind"]) == ("ok", 1360.0, "latest")
    assert rate["observedAt"] == "2026-09-17T07:35:00+09:00" and rate["observedDate"] == "2026-09-17"
    assert rate["baseline"] == {"value": 1355.0, "date": "2026-09-16", "at": "2026-09-16T15:30:00+09:00"}
    assert rate["change"] == 5.0
    assert sorted(fake.calls) == [("KRW=X", "5m"), ("^KQ11", "1d"), ("^KS11", "1d")]  # one request per indicator

    # Evening: the same day's close and the last rate before 18:05.
    kit.clock.travel_to(kst("2026-09-17", 18, 15))
    assert kit.services.briefings.tick() == [EVENING]
    body = _public(kit)
    assert body["marketVariables"]["rateCutoffAt"] == "2026-09-17T18:05:00+09:00"
    by_id = _indicators(body)
    assert (by_id["kospi"]["value"], by_id["kospi"]["observedDate"], by_id["kospi"]["change"]) == (7100.0, "2026-09-17", 60.0)
    assert (by_id["usdkrw"]["value"], by_id["usdkrw"]["observedAt"], by_id["usdkrw"]["status"]) == (1363.5, "2026-09-17T18:00:00+09:00", "ok")


def test_stored_indicators_never_change_after_publication(market_kit):
    kit, fake = market_kit
    kit.clock.travel_to(kst("2026-09-17", 7, 45))
    kit.services.briefings.tick()
    first = _public(kit)
    stored = kit.client.get(f"/api/admin/briefings/{MORNING}").json()["published"]["marketVariables"]
    assert stored == first["marketVariables"]
    calls = len(fake.calls)

    # The source moves and the clock runs on: reading, re-running and replacing the round change nothing.
    fake.daily["^KS11"]["2026-09-16"] = 1.0
    fake.rate.append((kst("2026-09-17", 7, 38), 1.0))
    kit.clock.travel_to(kst("2026-09-17", 9, 0))
    assert _public(kit, date="2026-09-17", edition="morning")["marketVariables"] == first["marketVariables"]
    again = kit.client.post(f"/api/admin/briefings/{MORNING}/reprocess", json={"reason": "다시"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_published"
    kit.services.briefings.tick()
    assert _public(kit, date="2026-09-17", edition="morning") == first
    assert len(fake.calls) == calls  # reading a published round never asks the source
    with pytest.raises(sqlite3.IntegrityError):
        kit.services.db.execute("UPDATE briefing_rounds SET payload='{}' WHERE id=?", (MORNING,))


def test_one_failing_indicator_leaves_the_others_and_the_round_published(market_kit):
    kit, fake = market_kit
    fake.fail = {"^KQ11": 503, "KRW=X": 422}  # KOSDAQ: the source is down (asked twice); rate: no 5-minute data to give
    kit.clock.travel_to(kst("2026-09-17", 7, 45))
    kit.services.briefings.tick()

    body = _public(kit)
    assert body["status"] == "published" and len(body["items"]) == 3
    by_id = _indicators(body)
    assert by_id["kospi"]["status"] == "ok" and by_id["kospi"]["value"] == 7040.0
    # 불러오지 못했어요: the request itself failed.
    kosdaq = by_id["kosdaq"]
    assert (kosdaq["status"], kosdaq["reasonCode"], kosdaq["value"], kosdaq["change"]) == ("failed", "temporary_failure", None, None)
    assert fake.calls.count(("^KQ11", "1d")) == 2
    # 아직 없어요: the source answered, but has nothing for this point in time.
    rate = by_id["usdkrw"]
    assert (rate["status"], rate["reasonCode"], rate["value"]) == ("unavailable", "no_data", None)


def test_a_source_without_data_for_the_point_in_time_is_unavailable_not_failed(market_kit):
    kit, fake = market_kit
    fake.rate = [(kst("2026-09-17", 7, 50), 1399.0)]  # nothing at or before the cut-off
    fake.daily["^KS11"] = {}  # the source lists no sessions at all
    kit.clock.travel_to(kst("2026-09-17", 7, 45))
    kit.services.briefings.tick()

    by_id = _indicators(_public(kit))
    assert (by_id["kospi"]["status"], by_id["kospi"]["reasonCode"]) == ("unavailable", "no_data")
    assert (by_id["usdkrw"]["status"], by_id["usdkrw"]["reasonCode"]) == ("unavailable", "no_data")
    assert by_id["usdkrw"]["reason"] == "07:40 이전 환율이 출처에 없어요."
    assert by_id["kosdaq"]["status"] == "ok"


def test_late_values_keep_their_real_time_and_are_flagged(market_kit):
    kit, fake = market_kit
    fake.rate = [r for r in fake.rate if r[0] <= kst("2026-09-17", 17, 20)] + [(kst("2026-09-17", 17, 20), 1361.0)]
    del fake.daily["^KQ11"]["2026-09-17"]  # KOSDAQ has not posted today's close; KOSPI has
    kit.clock.travel_to(kst("2026-09-17", 18, 15))
    assert kit.services.briefings.tick() == [EVENING]

    by_id = _indicators(_public(kit))
    rate = by_id["usdkrw"]
    assert (rate["status"], rate["value"], rate["observedAt"]) == ("delayed", 1361.0, "2026-09-17T17:20:00+09:00")
    assert rate["reason"] == "기준 시각보다 45분 앞선 값이에요."
    kosdaq = by_id["kosdaq"]
    assert (kosdaq["status"], kosdaq["value"], kosdaq["observedDate"]) == ("delayed", 853.0, "2026-09-16")
    assert by_id["kospi"]["status"] == "ok" and by_id["kospi"]["observedDate"] == "2026-09-17"


def test_the_rate_is_not_late_while_its_market_is_closed_over_the_weekend():
    fake = FakeYahoo()
    fake.rate = [(kst("2026-09-18", 15, 30), 1350.0), (kst("2026-09-19", 6, 55), 1352.0)]  # Friday close, Saturday 06:55

    def rate(day: date, edition: str, hour: int):
        reference = kst(day.isoformat(), hour, 40)
        collected = MarketIndicators(fake.provider()).collect(day, edition, reference, now=reference)  # type: ignore[arg-type]
        return next(i for i in collected.indicators if i.id == "usdkrw")

    saturday = rate(date(2026, 9, 19), "morning", 7)
    assert (saturday.status, saturday.value, saturday.observed_at) == ("ok", 1352.0, "2026-09-19T06:55:00+09:00")
    assert saturday.baseline is not None and saturday.baseline.date == "2026-09-18" and saturday.change == 2.0
    monday = rate(date(2026, 9, 21), "morning", 7)  # the market has only just reopened: Saturday's value is not "late"
    assert (monday.status, monday.observed_at) == ("ok", "2026-09-19T06:55:00+09:00")
    fake.rate.append((kst("2026-09-21", 7, 5), 1360.0))  # but once it is open, 35 minutes without an update is
    assert rate(date(2026, 9, 21), "morning", 7).status == "delayed"


def test_rounds_published_before_indicators_were_stored_say_so_and_have_no_morning_to_compare(admin):
    # An older round as the database holds it: published, and its payload has neither marketVariables nor reportedAt.
    admin.clock.travel_to(kst("2026-09-17", 7, 45))
    admin.services.briefings.tick()
    old = admin.client.get(f"/api/admin/briefings/{MORNING}").json()["published"]
    old.pop("marketVariables")
    for item in old["items"]:
        item.pop("reportedAt")
    data = {"published_at": "2026-09-16T09:10:00+00:00", "graph_version": "v1"}
    admin.services.db.execute(
        "INSERT INTO briefing_rounds(id,date,edition,status,data,payload,updated_at) VALUES (?,?,?,?,?,?,?)",
        ("brf-2026-09-16-evening", "2026-09-16", "evening", "published", json.dumps(data), json.dumps(old), "2026-09-16T09:10:00+00:00"),
    )
    body = _public(admin, date="2026-09-16", edition="evening")
    assert body["status"] == "published"
    assert body["marketVariables"] == {"status": "unavailable", "reason": "이 회차에는 시장 지표가 저장되지 않았어요."}
    assert body["sinceMorning"] == {"status": "unavailable", "reason": "같은 날 출근 브리핑이 없어요."}
    assert all(i["reportedAt"] is None for i in body["items"])


def test_an_unpublished_or_suspended_round_does_not_show_indicators(market_kit):
    kit, _ = market_kit
    kit.clock.travel_to(kst("2026-09-17", 7, 45))
    kit.services.briefings.tick()
    assert _public(kit, date="2026-09-17", edition="evening")["marketVariables"]["status"] == "unavailable"  # not ready
    suspended = kit.client.post(f"/api/admin/briefings/{MORNING}/suspension", json={"action": "suspend", "reason": "정정 확인"})
    assert suspended.status_code == 200
    body = _public(kit, date="2026-09-17", edition="morning")
    assert body["status"] == "suspended" and body["marketVariables"]["status"] == "unavailable"


# ------------------------------------------------------------------ since the morning


def _issue(event_id: str, rank: int, reported: str | None, evidence: int = 1, companies: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "eventId": event_id,
        "title": f"제목 {event_id}",
        "eventTime": None,
        "timePrecision": "unknown",
        "rank": rank,
        "evidenceCount": evidence,
        "reportedAt": reported,
        "companies": [{"id": f"KRX:{name}", "name": name} for name in companies],
    }


def test_issues_are_classified_against_the_morning_and_listed_oldest_first():
    morning = {
        "dataWindow": {"end": "2026-09-17T07:40:00+09:00"},
        "items": [_issue("a", 1, "2026-09-17T06:00:00+09:00", 2), _issue("b", 2, "2026-09-16T23:00:00+09:00")],
    }
    evening = [_issue("c", 1, "2026-09-17T16:00:00+09:00"), _issue("a", 2, "2026-09-17T10:00:00+09:00", 3)]
    result = compare(morning_id=MORNING, morning_published_at="2026-09-16T22:41:00+00:00", morning=morning, evening_items=evening)

    assert [(i.event_id, i.change) for i in result.items] == [("b", "dropped"), ("a", "continuing"), ("c", "new")]
    b, a, c = result.items
    assert (b.rank, b.morning_rank, b.evidence_count, b.morning_evidence_count) == (None, 2, None, 1)
    assert (a.rank, a.morning_rank, a.evidence_count, a.morning_evidence_count) == (2, 1, 3, 2)  # evidence 2 -> 3
    assert (c.rank, c.morning_rank, c.morning_evidence_count) == (1, None, None)
    assert result.morning_data_as_of == "2026-09-17T07:40:00+09:00"

    # Nothing in common: everything this round has is new and everything of the morning is dropped.
    apart = compare(morning_id=MORNING, morning_published_at=None, morning=morning, evening_items=[_issue("z", 1, None)])
    assert sorted(i.change for i in apart.items) == ["dropped", "dropped", "new"]
    # An empty morning round: everything is new. An empty evening round: everything of the morning is dropped.
    empty = {"dataWindow": {"end": "2026-09-17T07:40:00+09:00"}, "items": []}
    assert {i.change for i in compare(morning_id=MORNING, morning_published_at=None, morning=empty, evening_items=evening).items} == {"new"}
    assert {i.change for i in compare(morning_id=MORNING, morning_published_at=None, morning=morning, evening_items=[]).items} == {"dropped"}


def test_a_report_without_a_time_is_never_ordered_or_stored_as_midnight():
    morning = {"dataWindow": {"end": "2026-09-17T07:40:00+09:00"}, "items": [_issue("unknown", 1, None)]}
    evening = [
        _issue("date-only", 1, "2026-09-17"),
        _issue("timed", 2, "2026-09-17T10:00:00+09:00", companies=("삼성전자", "SK하이닉스")),
        _issue("day-before", 3, "2026-09-16T23:59:00+09:00"),
    ]
    result = compare(morning_id=MORNING, morning_published_at=None, morning=morning, evening_items=evening)
    # Oldest first; on 09-17 the item with a time precedes the one that only knows the date; no stored report time is last.
    assert [i.event_id for i in result.items] == ["day-before", "timed", "date-only", "unknown"]
    assert [i.reported_at for i in result.items] == ["2026-09-16T23:59:00+09:00", "2026-09-17T10:00:00+09:00", "2026-09-17", None]
    assert result.items[1].company_names == ["삼성전자", "SK하이닉스"] and result.items[0].company_names == []


def test_a_report_time_keeps_what_the_article_gave():
    # An article with only a date is read as 00:00 KST by the window rule, but a key issue never shows it as a time.
    assert _reported_at("2026-09-16") == "2026-09-16"
    assert _reported_at("2026-09-16T15:00:48+00:00") == "2026-09-17T00:00:48+09:00"  # 15:00:48 UTC is 00:00:48 KST: a real time
    assert _reported_at("2026-09-16T17:00:00") == "2026-09-16T17:00:00+09:00"  # no offset: read as KST
    assert _reported_at(None) is None and _reported_at("sometime") is None


def test_an_evening_round_reads_the_same_days_published_morning_only(make_admin):
    """End to end over stored rounds: a morning round on file, then the evening round the scheduler makes."""
    donor = make_admin()
    donor.login()
    donor.clock.travel_to(kst("2026-09-17", 7, 45))
    donor.services.briefings.tick()
    published = donor.client.get(f"/api/admin/briefings/{MORNING}").json()["published"]
    kept, other = published["items"][0], dict(published["items"][1])
    other["eventId"] = "issue-only-in-the-morning"
    published["items"] = [kept, other]
    db_data = {"published_at": "2026-09-16T22:41:00+00:00", "graph_version": "v1"}

    admin = make_admin(admin_idle_seconds=7 * 86400, admin_absolute_seconds=30 * 86400)
    admin.login()
    admin.services.db.execute(
        "INSERT INTO briefing_rounds(id,date,edition,status,data,payload,updated_at) VALUES (?,?,?,?,?,?,?)",
        (MORNING, "2026-09-17", "morning", "published", json.dumps(db_data), json.dumps(published), "2026-09-16T22:41:00+00:00"),
    )
    admin.clock.travel_to(kst("2026-09-17", 18, 15))
    assert admin.services.briefings.tick() == [EVENING]

    body = _public(admin, date="2026-09-17", edition="evening")
    assert body["status"] == "published" and _public(admin, date="2026-09-17", edition="morning")["sinceMorning"] is None
    since = body["sinceMorning"]
    assert since["status"] == "available" and since["morningRoundId"] == MORNING
    assert since["morningPublishedAt"] == "2026-09-16T22:41:00+00:00" and since["morningDataAsOf"] == "2026-09-17T07:40:00+09:00"
    changes = {i["eventId"]: i["change"] for i in since["items"]}
    assert changes[kept["eventId"]] == "continuing" and changes["issue-only-in-the-morning"] == "dropped"
    assert {i["eventId"] for i in body["items"]} == {e for e, c in changes.items() if c != "dropped"}
    assert sum(1 for c in changes.values() if c == "new") == 2  # the evening's other two key issues
    times = [i["reportedAt"] for i in since["items"] if i["change"] != "dropped"]
    assert times == sorted(times)

    # A morning round that is not usable says why instead of comparing.
    for status, reason in (("suspended", "출근 브리핑이 제공 중단 상태라서 비교할 수 없어요."), ("failed", "출근 브리핑이 발행되지 않아서 비교할 수 없어요.")):
        admin.services.db.execute("UPDATE briefing_rounds SET status=? WHERE id=?", (status, MORNING))
        assert _public(admin, date="2026-09-17", edition="evening")["sinceMorning"] == {"status": "unavailable", "reason": reason}
