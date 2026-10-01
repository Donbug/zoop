"""Rules the frontend relies on: what the public API may and may not show."""

from __future__ import annotations

import json

from zoop_bff.dataset import evidence_id

from .conftest import ALPHA_ISSUES, HELD_ARTICLE, HELD_ISSUE, base_payload, fresh
from .chat_support import ask_job, new_member


def _all_public_text(client) -> str:
    """Every public GET response the UI can reach, concatenated."""
    chunks = []
    for url in ("/api/graph?mode=all", "/api/events", "/api/companies", "/api/briefings"):
        chunks.append(client.get(url).text)
    for company in client.get("/api/companies").json()["items"]:
        chunks.append(client.get(f"/api/companies/{company['id']}").text)
    for event in client.get("/api/events").json()["items"]:
        detail = client.get(f"/api/events/{event['id']}")
        chunks.append(detail.text)
        for eid in detail.json()["evidenceIds"]:
            chunks.append(client.get(f"/api/evidence/{eid}").text)
    for edge in client.get("/api/graph?mode=all").json()["edges"]:
        chunks.append(client.get(f"/api/graph/edges/{edge['id']}").text)
    return "\n".join(chunks)


def test_hold_and_reject_never_reach_the_public_api(make_client):
    payload = fresh()
    hold = next(c for c in payload["candidates"] if c["status"] == "HOLD")
    # A REJECT candidate the ledger never approved.
    reject = json.loads(json.dumps(hold).replace("issue-bf022d03", "issue-rejected0").replace("synthetic-unknown", "synthetic-rejected"))
    reject["status"] = "REJECT"
    reject["candidate"]["candidate_id"] = "candidate-rejected"
    payload["candidates"].append(reject)
    # A hand-edited snapshot that lists the HOLD candidate under an "approved" issue.
    cand = hold["candidate"]
    payload["issues"].append(
        {
            "issue_id": cand["issue_id"],
            "mentions": [cand["mention"]],
            "articles": cand["articles"],
            "relations": cand["relations"],
            "candidate_ids": [cand["candidate_id"]],
            "field_decisions": [],
            "source_support": {"article_count": 1},
        }
    )
    client = make_client(payload)

    text = _all_public_text(client)
    for marker in (HELD_ISSUE, HELD_ARTICLE, "issue-rejected0", "synthetic-rejected", "candidate-a14f9dee", "논의했다고 밝혔다"):
        assert marker not in text, marker
    assert client.get(f"/api/events/{HELD_ISSUE}").status_code == 404
    held_evidence = evidence_id(HELD_ARTICLE, cand["mention"]["article_version"], 0, 51)
    assert client.get(f"/api/evidence/{held_evidence}").status_code == 404
    assert {e["id"] for e in client.get("/api/events").json()["items"]} == set(ALPHA_ISSUES.values())


def test_unapproved_event_time_is_never_filled_from_publication_date(make_client):
    payload = fresh()
    plant = next(i for i in payload["issues"] if i["issue_id"] == ALPHA_ISSUES["plant"])
    del plant["mentions"][0]["event_time"]  # what inspect() does for an unapproved field
    q2 = next(i for i in payload["issues"] if i["issue_id"] == ALPHA_ISSUES["q2"])
    q2["field_decisions"][0]["outcomes"] = [{"field": "event_time", "decision": "HOLD", "reason": "unverified"}]
    client = make_client(payload)

    for issue_id in (ALPHA_ISSUES["plant"], ALPHA_ISSUES["q2"]):
        detail = client.get(f"/api/events/{issue_id}").json()
        assert detail["eventTime"] is None and detail["timePrecision"] == "unknown"
        assert detail["mentions"][0]["eventTime"] is None
        assert detail["articles"][0]["publishedAt"]  # the publication date is still shown, as such
        summary = next(e for e in client.get("/api/events").json()["items"] if e["id"] == issue_id)
        assert summary["eventTime"] is None
    nodes = {n["id"]: n for n in client.get("/api/graph?mode=all").json()["nodes"]}
    assert nodes[ALPHA_ISSUES["plant"]]["eventTime"] is None
    # An undated event cannot match a date range; the response says how many were left out.
    ranged = client.get("/api/events?from=2000-01-01&to=2100-01-01").json()
    assert {e["id"] for e in ranged["items"]} == {ALPHA_ISSUES["q1"]}
    assert ranged["metadata"]["excludedUnknownTime"] == 2


def test_company_pairs_are_only_derived_never_approved_edges(make_client):
    payload = fresh()
    q1 = next(i for i in payload["issues"] if i["issue_id"] == ALPHA_ISSUES["q1"])
    involves = next(r for r in q1["relations"] if r["relation_type"] == "INVOLVES")
    q1["relations"].append({**involves, "relation_id": "relation-beta", "target": "SYNTH-BETA", "role": "계약 상대"})
    client = make_client(payload)

    graph = client.get("/api/graph?mode=all").json()
    company_edges = [e for e in graph["edges"] if e["relationType"] == "SHARES_ISSUE"]
    assert len(company_edges) == 1
    edge = company_edges[0]
    assert edge["derived"] is True and edge["via"] == [ALPHA_ISSUES["q1"]]
    assert {edge["source"], edge["target"]} == {"SYNTH-ALPHA", "SYNTH-BETA"}
    assert all(not e["derived"] for e in graph["edges"] if e["relationType"] != "SHARES_ISSUE")
    detail = client.get(f"/api/graph/edges/{edge['id']}").json()
    assert detail["derived"] is True and detail["verification"]["status"] == "not_applicable"
    assert detail["evidenceIds"] == [] and detail["explanation"]
    assert [v["id"] for v in detail["via"]] == [ALPHA_ISSUES["q1"]]


def test_summary_sentiment_and_price_are_unavailable_not_invented(make_client):
    client = make_client()
    company = client.get("/api/companies/SYNTH-ALPHA").json()
    assert company["summary"]["status"] == "unavailable" and "price" not in company
    # No provider connected: quotes say why instead of returning empty or made-up values.
    prices = client.get("/api/companies/SYNTH-ALPHA/prices?period=1y").json()
    quote = client.get("/api/companies/SYNTH-ALPHA/quote").json()
    assert prices["status"] == quote["status"] == "unavailable" and quote["reasonCode"] == "not_connected"
    assert client.get(f"/api/events/{ALPHA_ISSUES['q1']}").json()["summary"]["status"] == "unavailable"


def test_evidence_quote_verification_follows_the_article_body(make_client):
    ok = make_client()
    detail = ok.get(f"/api/events/{ALPHA_ISSUES['q2']}").json()
    assert all(ok.get(f"/api/evidence/{e}").json()["quoteVerified"] is True for e in detail["evidenceIds"])

    payload = fresh()
    q2 = next(i for i in payload["issues"] if i["issue_id"] == ALPHA_ISSUES["q2"])
    for ev in [e for m in q2["mentions"] for e in m["evidence"]] + [e for r in q2["relations"] for e in r["evidence"]]:
        ev["quote"] = "원문에 없는 문장"
    bad = make_client(payload)
    evidence = bad.get(f"/api/events/{ALPHA_ISSUES['q2']}").json()["evidenceIds"]
    assert [bad.get(f"/api/evidence/{e}").json()["quoteVerified"] for e in evidence] == [False]
    answer = _ask(bad, [ALPHA_ISSUES["q2"]], "어떤 실적을 발표했나요?")
    assert answer["outcome"] == "insufficient_evidence" and answer["sources"] == []

    no_bodies = fresh()
    for issue in no_bodies["issues"]:
        for article in issue["articles"]:
            del article["body"]
    body_less = make_client(no_bodies)
    ev_id = body_less.get(f"/api/events/{ALPHA_ISSUES['q2']}").json()["evidenceIds"][0]
    assert body_less.get(f"/api/evidence/{ev_id}").json()["quoteVerified"] is None


def _ask(client, context_ids, question):
    member = new_member(client)
    job = ask_job(member, question, context_ids)
    assert job["status"] == "completed", job
    return job["result"]


def test_chat_answers_cite_only_real_evidence_and_ask_back_without_a_target(make_client):
    client = make_client()
    answer = _ask(client, [ALPHA_ISSUES["q1"]], "어떤 실적을 발표했나요?")
    assert answer["outcome"] == "answered" and answer["sources"]
    for source in answer["sources"]:
        assert client.get(f"/api/evidence/{source}").status_code == 200
    assert ALPHA_ISSUES["q1"] in {t["id"] for t in answer["graphTargets"]}

    # No target: the question is asked back (a stored, completed result), never answered from nothing.
    asked_back = _ask(client, [], "무엇이 있나요?")
    assert asked_back["outcome"] == "clarification" and asked_back["sources"] == [] and asked_back["citations"] == []
    company_answer = _ask(client, ["SYNTH-ALPHA"], "이 종목 오를까요?")
    assert company_answer["outcome"] == "insufficient_evidence" and company_answer["sources"] == []
