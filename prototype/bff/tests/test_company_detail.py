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
