"""Member accounts: sign-up validation, persistence across restarts, blocking, social login, tutorial."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from zoop_bff.app import create_app
from zoop_bff.config import Settings

from .conftest import DEMO, base_payload, with_companies

AGREE = ["service", "privacy"]
NEW = {"email": "new@zoop.local", "password": "abcd1234", "displayName": "새 회원", "agreements": AGREE}


def _settings(tmp_path: Path) -> Settings:
    import json

    snapshot = tmp_path / "snapshot.json"
    if not snapshot.exists():
        snapshot.write_text(json.dumps(with_companies(base_payload())), encoding="utf-8")
    return Settings(snapshot_path=snapshot, company_catalog=None, state_dir=tmp_path / "state", briefing_scheduler=False)


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(_settings(tmp_path)))


def test_signup_reports_every_invalid_field_and_duplicate_email(tmp_path):
    client = _client(tmp_path)
    bad = client.post("/api/auth/signup", json={"email": "not-an-email", "password": "short", "displayName": "", "agreements": ["service"]})
    assert bad.status_code == 422
    fields = bad.json()["error"]["details"]["fields"]
    assert set(fields) == {"email", "password", "displayName", "agreements"}
    assert bad.json()["error"]["details"]["missingTerms"] == ["privacy"]
    assert client.get("/api/auth/session").json()["kind"] == "anonymous"  # nothing was created

    created = client.post("/api/auth/signup", json=NEW)
    assert created.status_code == 201 and created.json()["kind"] == "member"
    assert created.json()["setup"] == {"completed": False, "tutorialCompleted": False}

    other = TestClient(client.app)
    taken = other.post("/api/auth/signup", json={**NEW, "email": " NEW@zoop.local "})
    assert taken.status_code == 409 and "email" in taken.json()["error"]["details"]["fields"]


def test_login_reports_missing_fields_and_wrong_password(tmp_path):
    client = _client(tmp_path)
    missing = client.post("/api/auth/login", json={"email": "", "password": ""})
    assert missing.status_code == 422 and set(missing.json()["error"]["details"]["fields"]) == {"email", "password"}
    assert client.post("/api/auth/login", json={**DEMO, "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json=DEMO).status_code == 200


def test_members_settings_and_sessions_survive_a_restart(tmp_path):
    first = _client(tmp_path)
    assert first.post("/api/auth/signup", json=NEW).status_code == 201
    version = first.get("/api/me/settings").json()["version"]
    saved = first.put("/api/me/settings", json={"version": version, "investor": True, "watchlistIds": ["SYNTH-C1"], "completed": True})
    assert saved.status_code == 200
    assert first.post("/api/portfolio/connections", json={"mockPortfolioId": "mock-basic"}).status_code == 201
    assert first.put("/api/auth/tutorial", json={"completed": True}).json()["setup"]["tutorialCompleted"] is True
    holdings = first.get("/api/portfolio").json()["holdings"]
    cookie = first.cookies.get("zoop_session")

    restarted = TestClient(create_app(_settings(tmp_path)))
    restarted.cookies.set("zoop_session", cookie)
    session = restarted.get("/api/auth/session").json()
    assert session["kind"] == "member" and session["setup"] == {"completed": True, "tutorialCompleted": True}
    settings = restarted.get("/api/me/settings").json()
    assert settings["watchlistIds"] == ["SYNTH-C1"] and settings["investor"] is True
    assert restarted.get("/api/portfolio").json()["holdings"] == holdings

    # The password works after the restart too; the stored value is a hash, not the password.
    fresh = TestClient(restarted.app)
    assert fresh.post("/api/auth/login", json={"email": NEW["email"], "password": NEW["password"]}).status_code == 200
    with sqlite3.connect(tmp_path / "state" / "zoop-admin.sqlite3") as db:
        stored = db.execute("SELECT password_hash FROM members WHERE email = ?", (NEW["email"],)).fetchone()[0]
        tokens = [r[0] for r in db.execute("SELECT token_hash FROM member_sessions")]
    assert stored.startswith("scrypt$") and NEW["password"] not in stored
    assert cookie not in tokens


def test_holding_currency_survives_restart_and_older_rows_read_as_unknown(tmp_path):
    first = _client(tmp_path)
    assert first.post("/api/auth/login", json=DEMO).status_code == 200
    assert first.post("/api/portfolio/connections", json={"mockPortfolioId": "mock-basic"}).status_code == 201
    assert {h["avgPriceCurrency"] for h in first.get("/api/portfolio").json()["holdings"]} == {"KRW"}
    cookie = first.cookies.get("zoop_session")
    # A connection stored before the currency was recorded: no migration, the currency is unknown.
    with sqlite3.connect(tmp_path / "state" / "zoop-admin.sqlite3") as db:
        raw = json.loads(db.execute("SELECT holdings FROM member_connections").fetchone()[0])
        db.execute("UPDATE member_connections SET holdings = ?", (json.dumps([{k: v for k, v in h.items() if k != "currency"} for h in raw]),))
    restarted = TestClient(create_app(_settings(tmp_path)))
    restarted.cookies.set("zoop_session", cookie)
    holdings = restarted.get("/api/portfolio").json()["holdings"]
    assert holdings and all(h["avgPriceCurrency"] is None for h in holdings)


def test_session_expires(tmp_path):
    client = _client(tmp_path)
    client.post("/api/auth/login", json=DEMO)
    store = client.app.state.zoop.accounts
    store._clock.advance(store.member_ttl.total_seconds() + 1)
    assert client.get("/api/auth/session").json()["kind"] == "anonymous"
    assert client.get("/api/me/settings").status_code == 401


def test_blocked_member_cannot_log_in_and_open_sessions_are_refused(tmp_path):
    client = _client(tmp_path)
    assert client.post("/api/auth/login", json=DEMO).status_code == 200
    other_tab = TestClient(client.app)
    assert other_tab.post("/api/auth/login", json=DEMO).status_code == 200
    with sqlite3.connect(tmp_path / "state" / "zoop-admin.sqlite3") as db:
        db.execute("UPDATE members SET status = 'blocked' WHERE email = ?", (DEMO["email"],))

    refused = client.get("/api/me/settings")
    assert refused.status_code == 401 and refused.json()["error"]["code"] == "member_blocked"
    # Every later request of that tab is refused the same way until it logs out.
    assert client.get("/api/auth/session").json()["error"]["code"] == "member_blocked"
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/session").json()["kind"] == "anonymous"

    denied = TestClient(client.app).post("/api/auth/login", json=DEMO)
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "member_blocked"

    # Unblocking does not revive sessions opened before the block.
    store = client.app.state.zoop.accounts
    assert store.set_status("user-demo", "active") is True and store.set_status("user-demo", "active") is False
    assert other_tab.get("/api/auth/session").json()["kind"] == "anonymous"
    assert TestClient(client.app).post("/api/auth/login", json=DEMO).status_code == 200


def _social(client: TestClient, email: str, *, cancel: bool = False, tamper: bool = False):
    start = client.get("/api/auth/social/mock/authorize?returnTo=/briefing", follow_redirects=False)
    assert start.status_code == 302
    query = parse_qs(urlparse(start.headers["location"]).query)
    state, redirect_uri = query["state"][0], query["redirect_uri"][0]
    if cancel:
        return client.get(f"{redirect_uri}?error=access_denied&state={state}", follow_redirects=False)
    consent = client.post(
        "/api/auth/social/mock/idp/consent",
        json={"state": state, "redirectUri": redirect_uri, "email": email, "displayName": "소셜 회원"},
    )
    target = consent.json()["redirectTo"]
    if tamper:
        target = target.replace(state, "forged-state")
    return client.get(target, follow_redirects=False)


def test_social_login_creates_then_logs_in_and_checks_state(tmp_path):
    client = _client(tmp_path)
    created = _social(client, "social@zoop.local")
    assert created.status_code == 302 and created.headers["location"] == "/onboarding"
    session = client.get("/api/auth/session").json()
    assert session["kind"] == "member" and session["user"]["email"] == "social@zoop.local"
    member_id = session["user"]["id"]

    client.post("/api/auth/logout")
    again = _social(client, "social@zoop.local")
    assert again.headers["location"] == "/briefing"  # existing member: back to where they were going
    assert client.get("/api/auth/session").json()["user"]["id"] == member_id

    client.post("/api/auth/logout")
    cancelled = _social(client, "social@zoop.local", cancel=True)
    assert cancelled.headers["location"] == "/login?social=cancelled"
    forged = _social(client, "social@zoop.local", tamper=True)
    assert forged.headers["location"] == "/login?social=failed"
    assert client.get("/api/auth/session").json()["kind"] == "anonymous"

    # A state from another browser (no binding cookie) is rejected.
    start = client.get("/api/auth/social/mock/authorize", follow_redirects=False)
    query = parse_qs(urlparse(start.headers["location"]).query)
    consent = client.post(
        "/api/auth/social/mock/idp/consent",
        json={"state": query["state"][0], "redirectUri": query["redirect_uri"][0], "email": "social@zoop.local"},
    )
    stranger = TestClient(client.app)
    assert stranger.get(consent.json()["redirectTo"], follow_redirects=False).headers["location"] == "/login?social=failed"

    # The e-mail of an e-mail member is not taken over by a social identity.
    assert _social(TestClient(client.app), DEMO["email"]).headers["location"] == "/login?social=email_in_use"


def test_guest_tutorial_is_kept_on_the_guest_session_only(tmp_path):
    client = _client(tmp_path)
    assert client.post("/api/auth/guest").json()["setup"]["tutorialCompleted"] is False
    assert client.put("/api/auth/tutorial", json={"completed": True}).json()["setup"]["tutorialCompleted"] is True
    other = TestClient(client.app)
    assert other.post("/api/auth/guest").json()["setup"]["tutorialCompleted"] is False
    assert TestClient(client.app).put("/api/auth/tutorial", json={"completed": True}).status_code == 401


def test_recommendations_rank_by_approved_issues_and_skip_the_watchlist(member):
    body = member.get("/api/me/recommendations").json()
    counts = [item["company"]["issueCount"] for item in body["items"]]
    assert counts == sorted(counts, reverse=True) and all(c > 0 for c in counts)
    top = body["items"][0]["company"]["id"]
    version = member.get("/api/me/settings").json()["version"]
    member.put("/api/me/settings", json={"version": version, "watchlistIds": [top]})
    assert top not in {i["company"]["id"] for i in member.get("/api/me/recommendations").json()["items"]}
