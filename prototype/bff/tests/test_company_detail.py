"""Company detail reads: period timeline with undated events, and the company document list."""

from __future__ import annotations

from .conftest import ALPHA_ISSUES, fresh


def _issue(payload, key):
    return next(i for i in payload["issues"] if i["issue_id"] == ALPHA_ISSUES[key])


def test_undated_events_are_grouped_by_report_date_without_becoming_dated(make_client):
    payload = fresh()
    q2 = _issue(payload, "q2")
    del q2["mentions"][0]["event_time"]
    q2["articles"][0]["published_at"] = "2026-09-16T20:00:00+00:00"  # 2026-09-17 05:00 KST
    client = make_client(payload)

    inside = client.get("/api/events?companyId=SYNTH-ALPHA&from=2026-09-17").json()
    assert inside["items"] == []
    [undated] = inside["unknownTimeItems"]
    assert undated["id"] == ALPHA_ISSUES["q2"]
    assert undated["eventTime"] is None and undated["timePrecision"] == "unknown"
    assert undated["reportedAt"] == "2026-09-16T20:00:00+00:00"
    assert inside["metadata"]["latestEventTime"] == "2026-04-10"

    after = client.get("/api/events?companyId=SYNTH-ALPHA&from=2026-09-18").json()
    assert after["unknownTimeItems"] == [] and after["metadata"]["excludedUnknownTime"] == 1

    unranged = client.get("/api/events?companyId=SYNTH-ALPHA").json()
    assert unranged["unknownTimeItems"] == []
    assert ALPHA_ISSUES["q2"] in {e["id"] for e in unranged["items"]}


def _set_event_time(payload, key, value):
    for mention in _issue(payload, key)["mentions"]:
        mention["event_time"] = value


def test_the_common_end_time_cuts_later_events_and_an_unknown_day_goes_to_the_unknown_list(make_client):
    payload = fresh()
    _set_event_time(payload, "q1", "2026-09-17T15:00:00+09:00")  # time known
    _set_event_time(payload, "plant", "2026-09-17")  # only the day known
    _set_event_time(payload, "q2", "2026-09")  # only the month: the day is unknown (D05)
    client = make_client(payload)
    query = "/api/events?from=2026-09-01T00:00:00%2B09:00&to="
    ours = set(ALPHA_ISSUES.values())

    def listed(to):
        body = client.get(query + to).json()
        return {e["id"] for e in body["items"]} & ours, {e["id"] for e in body["unknownTimeItems"]} & ours

    items, unknown = listed("2026-09-17T14:59:59%2B09:00")
    assert items == {ALPHA_ISSUES["plant"]}  # 15:00 is after the end; the day-only event stays on its day
    assert unknown == {ALPHA_ISSUES["q2"]}  # judged by its report (2026-09-16), never placed on a day
    assert listed("2026-09-17T15:00:00%2B09:00")[0] == {ALPHA_ISSUES["q1"], ALPHA_ISSUES["plant"]}  # the end is inclusive
    assert listed("2026-09-17T06:00:00%2B00:00")[0] == {ALPHA_ISSUES["q1"], ALPHA_ISSUES["plant"]}  # same instant, UTC
    assert listed("2026-09-16T23:59:59%2B09:00") == (set(), {ALPHA_ISSUES["q2"]})
    assert client.get(query + "2026-08-01").status_code == 422  # end before start
    assert client.get(query + "yesterday").status_code == 422


def test_search_ranks_code_then_name_then_partial_and_returns_every_match(make_client):
    payload = fresh()
    payload["zoop"] = {
        "companies": [
            {"company_id": "KRX:000003", "name": "삼성전자", "ticker": "000003", "aliases": []},
            {"company_id": "KRX:000002", "name": "갑삼성", "ticker": "000002", "aliases": []},
            {"company_id": "KRX:000001", "name": "삼성", "ticker": "000001", "aliases": []},
            {"company_id": "KRX:SAMSUNG", "name": "을회사", "ticker": "삼성", "aliases": []},
            *({"company_id": f"KRX:9{i:05d}", "name": f"검색용{i:02d}", "ticker": f"9{i:05d}", "aliases": []} for i in range(30)),
        ]
    }
    client = make_client(payload)

    names = [c["name"] for c in client.get("/api/companies", params={"q": " 삼성 "}).json()["items"]]
    assert names == ["을회사", "삼성", "갑삼성", "삼성전자"]  # code exact, name exact, then partial by name
    assert [c["id"] for c in client.get("/api/companies", params={"q": "000001"}).json()["items"]] == ["KRX:000001"]
    assert len(client.get("/api/companies", params={"q": "검색용"}).json()["items"]) == 30  # no cap of 20
    assert client.get("/api/companies", params={"q": "없는회사"}).json()["items"] == []



def test_company_documents_are_distinct_newest_first_and_keep_quotes_without_a_link(make_client):
    payload = fresh()
    for issue in payload["issues"]:
        for article in issue["articles"]:
            if article["article_id"] == "synthetic-q2":
                article["url"] = None
                article["published_at"] = "2026-09-20T00:00:00+00:00"
    client = make_client(payload)

    docs = client.get("/api/companies/SYNTH-ALPHA/documents").json()["items"]
    ids = [d["id"] for d in docs]
    assert len(ids) == len(set(ids))
    assert ids[0] == "synthetic-q2"
    linkless = docs[0]
    assert linkless["url"] is None and linkless["publishedAt"] == "2026-09-20T00:00:00+00:00"
    assert [e["eventId"] for e in linkless["events"]] == [ALPHA_ISSUES["q2"]]
    assert linkless["quotes"] and all(q["quote"] for q in linkless["quotes"])
    multi = next(d for d in docs if d["id"] == "synthetic-multi")
    assert ALPHA_ISSUES["q1"] in {e["eventId"] for e in multi["events"]}

    missing = client.get("/api/companies/NO-SUCH/documents")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "company_not_found"
