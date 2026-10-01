"""Session, settings, portfolio and source-failure rules."""

from __future__ import annotations

from fastapi.testclient import TestClient

from zoop_bff.app import create_app
from zoop_bff.config import Settings

from .conftest import ALPHA_ISSUES, DEMO
from .chat_support import ask_job, job_body, new_member, open_conversation


def _put(client, version, **body):
    return client.put("/api/me/settings", json={"version": version, **body})


def test_watchlist_has_no_limit_but_rejects_unknown_ids(member):
    version = member.get("/api/me/settings").json()["version"]
    unknown = _put(member, version, watchlistIds=["SYNTH-C0", "NOT-A-COMPANY"])
    assert unknown.status_code == 422 and unknown.json()["error"]["details"]["companyIds"] == ["NOT-A-COMPANY"]

    # Rejected writes change nothing (TC-06: the saved list survives).
    saved = member.get("/api/me/settings").json()
    assert saved["watchlistIds"] == [] and saved["version"] == version

    five = ["SYNTH-C0", "SYNTH-C1", "SYNTH-C2", "SYNTH-C3", "SYNTH-C4"]
    stored = _put(member, version, watchlistIds=five)
    assert stored.status_code == 200 and stored.json()["watchlistIds"] == five

    # Resending the same request (stale version, same content) changes nothing and is not an error.
    again = _put(member, version, watchlistIds=five)
    assert again.status_code == 200 and again.json()["version"] == stored.json()["version"]


def test_stale_settings_version_is_a_conflict(member):
    version = member.get("/api/me/settings").json()["version"]
    assert _put(member, version, watchlistIds=["SYNTH-C0"]).status_code == 200
    stale = _put(member, version, watchlistIds=["SYNTH-C1"])
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "version_conflict"
    assert stale.json()["error"]["details"]["currentVersion"] == version + 1
    assert member.get("/api/me/settings").json()["watchlistIds"] == ["SYNTH-C0"]


def test_tutorial_completion_preserves_saved_watchlist(member):
    version = member.get("/api/me/settings").json()["version"]
    saved = _put(member, version, watchlistIds=["SYNTH-ALPHA"])
    assert saved.status_code == 200
    done = _put(member, saved.json()["version"], completed=True, tutorialCompleted=True)
    assert done.status_code == 200
    assert done.json()["watchlistIds"] == ["SYNTH-ALPHA"]
    assert member.get("/api/auth/session").json()["setup"] == {
        "completed": True, "tutorialCompleted": True
    }
    assert member.get("/api/graph?mode=personal").json()["metadata"]["emptyReason"] is None


def test_setup_can_finish_with_no_watchlist_and_no_account(member):
    version = member.get("/api/me/settings").json()["version"]
    done = _put(member, version, investor=False, completed=True)
    assert done.status_code == 200 and done.json()["completed"] is True and done.json()["investor"] is False
    assert member.get("/api/auth/session").json()["setup"] == {"completed": True, "tutorialCompleted": False}
    # Nothing personal: the personal graph says so and the market graph is still available.
    assert member.get("/api/graph?mode=personal").json()["metadata"]["emptyReason"] == "no_personal_stocks"
    assert member.get("/api/graph?mode=all").json()["nodes"]


def test_portfolio_weights_are_cost_based_and_valuation_is_unavailable(member):
    connect = member.post("/api/portfolio/connections", json={"mockPortfolioId": "mock-basic"})
    assert connect.status_code == 201
    portfolio = member.get("/api/portfolio").json()
    assert portfolio["weightBasis"] == "cost" and portfolio["valuation"]["status"] == "unavailable"
    assert abs(sum(h["weight"] for h in portfolio["holdings"]) - 1) < 1e-4
    for h in portfolio["holdings"]:
        assert h["marketValue"]["status"] == "unavailable"
        assert h["costBasis"] == h["quantity"] * h["avgPrice"]
    assert member.post("/api/portfolio/connections", json={"mockPortfolioId": "nope"}).status_code == 404

    assert member.delete(f"/api/portfolio/connections/{connect.json()['id']}").status_code == 204
    assert member.get("/api/portfolio").json()["connected"] is False


def test_personal_graph_needs_holdings_or_watchlist_and_marks_each(member):
    empty = member.get("/api/graph?mode=personal").json()
    assert empty["nodes"] == [] and empty["metadata"]["emptyReason"] == "no_personal_stocks"

    # No holdings: the personal graph is built from the watchlist alone.
    version = member.get("/api/me/settings").json()["version"]
    assert _put(member, version, watchlistIds=["SYNTH-ALPHA"]).status_code == 200
    graph = member.get("/api/graph?mode=personal").json()
    assert graph["metadata"]["mode"] == "personal" and graph["metadata"]["focusCompanyIds"] == ["SYNTH-ALPHA"]
    focus = next(n for n in graph["nodes"] if n["id"] == "SYNTH-ALPHA")
    assert focus["isFocus"] and focus["watch"] and not focus["holding"]
    assert {ALPHA_ISSUES["q1"], ALPHA_ISSUES["q2"]} <= {n["id"] for n in graph["nodes"]}
    assert ALPHA_ISSUES["plant"] not in {n["id"] for n in graph["nodes"]}  # not linked to the company

    # Holdings join the watchlist as focus companies; each node keeps its own holding/watch mark.
    assert member.post("/api/portfolio/connections", json={"mockPortfolioId": "mock-basic"}).status_code == 201
    held = {h["companyId"] for h in member.get("/api/portfolio").json()["holdings"]}
    graph = member.get("/api/graph?mode=personal").json()
    assert set(graph["metadata"]["focusCompanyIds"]) == held | {"SYNTH-ALPHA"}
    for node in graph["nodes"]:
        if node["kind"] == "company":
            assert node["holding"] == (node["id"] in held) and node["watch"] == (node["id"] == "SYNTH-ALPHA")
    # The market-wide graph is the same for everyone but still marks the member's companies.
    market = {n["id"]: n for n in member.get("/api/graph?mode=all").json()["nodes"]}
    assert market["SYNTH-ALPHA"]["watch"] and not market["SYNTH-ALPHA"]["isFocus"]


def test_a_single_watch_toggle_is_idempotent_and_keeps_a_held_company_as_a_holding(member, make_client):
    assert member.post("/api/portfolio/connections", json={"mockPortfolioId": "mock-basic"}).status_code == 201
    held = member.get("/api/portfolio").json()["holdings"][0]["companyId"]
    start = member.get("/api/me/settings").json()["version"]

    for _ in range(2):  # a resent toggle adds the company once and moves the version once
        added = member.put(f"/api/me/watchlist/{held}", json={"watched": True})
        assert added.status_code == 200 and added.json()["watchlistIds"] == [held]
    assert added.json()["version"] == start + 1
    node = next(n for n in member.get("/api/graph?mode=personal").json()["nodes"] if n["id"] == held)
    assert node["holding"] and node["watch"]

    for _ in range(2):
        assert member.put(f"/api/me/watchlist/{held}", json={"watched": False}).json()["watchlistIds"] == []
    node = next(n for n in member.get("/api/graph?mode=personal").json()["nodes"] if n["id"] == held)
    assert node["holding"] and not node["watch"]  # out of the watchlist, still a holding node

    # A toggle never needs the settings version and never undoes another company's saved change.
    version = member.get("/api/me/settings").json()["version"]
    assert _put(member, version, watchlistIds=["SYNTH-C0"]).status_code == 200
    assert member.put("/api/me/watchlist/SYNTH-C1", json={"watched": True}).json()["watchlistIds"] == ["SYNTH-C0", "SYNTH-C1"]
    assert member.put("/api/me/watchlist/NOT-A-COMPANY", json={"watched": True}).status_code == 404

    visitor = make_client()
    assert visitor.post("/api/auth/guest").status_code == 200
    assert visitor.put("/api/me/watchlist/SYNTH-ALPHA", json={"watched": True}).status_code == 403


def test_guest_can_read_the_market_but_every_personal_api_is_403(make_client):
    client = make_client()
    assert client.get("/api/me/settings").status_code == 401  # no session at all
    assert client.post("/api/auth/guest").json()["kind"] == "guest"

    assert client.get("/api/graph?mode=all").status_code == 200
    assert client.get("/api/events").status_code == 200
    for method, url in (
        ("get", "/api/me/settings"),
        ("get", "/api/portfolio"),
        ("get", "/api/portfolio/mock-portfolios"),
        ("post", "/api/portfolio/connections"),
        ("get", "/api/graph?mode=personal"),
    ):
        response = getattr(client, method)(url, **({"json": {"mockPortfolioId": "mock-basic"}} if method == "post" else {}))
        assert response.status_code == 403, url
        assert response.json()["error"]["code"] == "guest_forbidden"
    assert client.put("/api/me/settings", json={"version": 1, "watchlistIds": []}).status_code == 403

    assert client.get("/api/companies/SYNTH-ALPHA").json()["holding"] is None


def test_settings_belong_to_the_session_that_wrote_them(make_client):
    from .conftest import with_companies, base_payload

    client = make_client(with_companies(base_payload()))
    assert client.post("/api/auth/login", json={**DEMO, "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json=DEMO).status_code == 200
    version = client.get("/api/me/settings").json()["version"]
    assert _put(client, version, watchlistIds=["SYNTH-C0"]).status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/me/settings").status_code == 401
    assert client.get("/api/auth/session").json()["kind"] == "anonymous"
    client.post("/api/auth/login", json=DEMO)
    assert client.get("/api/me/settings").json()["watchlistIds"] == ["SYNTH-C0"]  # restored (TC-03)


def test_chat_sessions_are_private_to_their_creator(make_client):
    owner = new_member(make_client())
    session = open_conversation(owner)
    job = ask_job(owner, "어떤 실적을 발표했나요?", [ALPHA_ISSUES["q1"]], session_id=session)
    other = new_member(owner, "other@example.com", "다른사람")
    denied = other.post(f"/api/chat/sessions/{session}/jobs", json=job_body("무엇인가요?", [ALPHA_ISSUES["q1"]]))
    assert denied.status_code == 403 and "result" not in denied.json()
    # nobody else can read the conversation, the job or its saved answer either
    assert other.get(f"/api/chat/sessions/{session}").status_code == 403
    assert other.get(f"/api/chat/jobs/{job['id']}").status_code == 403
    assert other.post(f"/api/chat/jobs/{job['id']}/retry").status_code == 403
    assert other.post(f"/api/chat/jobs/{job['id']}/cancel").status_code == 403
    assert other.put(f"/api/chat/sessions/{session}").status_code == 403


def test_source_failure_is_a_503_not_an_empty_result(tmp_path):
    # The snapshot the first graph version would be registered from does not exist.
    settings = Settings(
        snapshot_path=tmp_path / "missing-snapshot.json", company_catalog=None, state_dir=tmp_path / "state"
    )
    client = TestClient(create_app(settings))
    for url in ("/api/graph?mode=all", "/api/events", "/api/companies"):
        response = client.get(url)
        assert response.status_code == 503, url
        body = response.json()
        assert body["error"]["code"] == "source_unavailable"
        assert str(tmp_path) not in response.text and "items" not in body and "nodes" not in body
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "unavailable" and health.json()["source"]["connected"] is False


def test_snapshot_provenance_distinguishes_real_synthetic_and_unknown(make_client):
    from .conftest import base_payload

    payload = base_payload()
    articles = [article for issue in payload["issues"] for article in issue["articles"]]
    assert articles
    for article in articles:
        article["synthetic"] = False
    real = make_client(payload).get("/api/graph").json()
    assert real["metadata"]["datasetKind"] == "approved-snapshot"
    assert real["metadata"]["sourceMode"] == "snapshot"

    articles[0]["synthetic"] = True
    synthetic = make_client(payload).get("/api/graph").json()
    assert synthetic["metadata"]["datasetKind"] == "synthetic-preview"

    del articles[0]["synthetic"]
    unknown = make_client(payload).get("/api/graph").json()
    assert unknown["metadata"]["datasetKind"] == "synthetic-preview"
