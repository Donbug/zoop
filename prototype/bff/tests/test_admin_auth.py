"""Requirement 82: admin sessions are separate from member sessions, expire, and leave an audit trail."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import ADMIN, DEMO


def _audit(kit, **query):
    kit.login()  # a fresh admin session reads the log
    return kit.client.get("/api/admin/audit-log", params=query).json()["items"]


def test_login_sets_an_httponly_lax_cookie_and_the_session_reports_the_admin(make_admin):
    kit = make_admin()
    assert kit.client.get("/api/admin/dashboard").status_code == 401

    response = kit.client.post("/api/admin/auth/login", json=ADMIN)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "zoop_admin_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    body = response.json()
    assert body["authenticated"] and body["admin"]["email"] == "admin@zoop.local" and body["admin"]["role"] == "admin"
    assert body["idleTimeoutSeconds"] == 1800 and body["absoluteTimeoutSeconds"] == 8 * 3600
    assert kit.client.get("/api/admin/dashboard").status_code == 200

    # The member session store never saw this login.
    assert kit.client.get("/api/auth/session").json()["kind"] == "anonymous"


def test_wrong_credentials_are_401_and_recorded_without_the_password(make_admin):
    kit = make_admin()
    bad = kit.client.post("/api/admin/auth/login", json={**ADMIN, "password": "hunter2-not-it"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_credentials"
    assert "set-cookie" not in bad.headers
    unknown = kit.client.post("/api/admin/auth/login", json={"email": "nobody@zoop.local", "password": "x"})
    assert unknown.status_code == 401

    entries = _audit(kit, action="auth.login_failed")
    assert len(entries) == 2 and all(e["outcome"] == "denied" for e in entries)
    assert "hunter2-not-it" not in str(entries)


def test_member_and_guest_cookies_cannot_call_admin_apis(make_admin):
    kit = make_admin()
    member = TestClient(kit.client.app)
    assert member.post("/api/auth/login", json=DEMO).status_code == 200
    guest = TestClient(kit.client.app)
    assert guest.post("/api/auth/guest").status_code == 200
    for client in (member, guest):
        for method, url in (("get", "/api/admin/dashboard"), ("get", "/api/admin/jobs"), ("get", "/api/admin/audit-log")):
            response = getattr(client, method)(url)
            assert response.status_code == 403, url
            assert response.json()["error"]["code"] == "admin_forbidden"
        assert client.post("/api/admin/graph/versions", json={"reason": "x"}).status_code == 403

    # Copying a member token into the admin cookie does not make an admin: the stores are separate.
    token = member.cookies.get("zoop_session")
    forged = TestClient(kit.client.app)
    forged.cookies.set("zoop_admin_session", token)
    assert forged.get("/api/admin/dashboard").status_code == 401

    # The admin cookie does not open member APIs either.
    kit.login()
    assert kit.client.get("/api/me/settings").status_code == 401


def test_idle_timeout_expires_the_session_and_activity_extends_it(make_admin):
    kit = make_admin(admin_idle_seconds=60, admin_absolute_seconds=3600)
    kit.login()
    kit.clock.advance(50)
    assert kit.client.get("/api/admin/dashboard").status_code == 200  # activity at t=50 extends the idle window
    kit.clock.advance(50)
    assert kit.client.get("/api/admin/dashboard").status_code == 200  # 50s since the last activity
    seen = kit.client.get("/api/admin/auth/session").json()
    assert seen["authenticated"]

    kit.clock.advance(61)
    # Reading the session reports the expiry and does not revive it.
    expired = kit.client.get("/api/admin/auth/session").json()
    assert (expired["authenticated"], expired["expired"], expired["expiredReason"]) == (False, True, "idle")
    response = kit.client.get("/api/admin/dashboard")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "admin_session_expired"
    assert response.json()["error"]["details"]["reason"] == "idle"

    kit.login()
    assert kit.client.get("/api/admin/dashboard").status_code == 200


def test_absolute_timeout_ends_even_a_busy_session(make_admin):
    kit = make_admin(admin_idle_seconds=100, admin_absolute_seconds=250)
    kit.login()
    for _ in range(2):
        kit.clock.advance(90)
        assert kit.client.get("/api/admin/dashboard").status_code == 200  # never idle for 100s
    kit.clock.advance(90)  # 270s since login
    response = kit.client.get("/api/admin/dashboard")
    assert response.status_code == 401
    assert response.json()["error"]["details"]["reason"] == "absolute"


def test_logout_and_audit_trail(make_admin):
    kit = make_admin()
    kit.login()
    assert kit.client.post("/api/admin/graph/versions/v1/activate", json={"reason": ""}).status_code == 422  # reason is required
    assert kit.client.post("/api/admin/auth/logout").status_code == 204
    assert kit.client.get("/api/admin/dashboard").status_code == 401
    assert kit.client.post("/api/admin/auth/logout").status_code == 204  # no session: still 204

    actions = [e["action"] for e in _audit(kit)]
    assert "auth.login" in actions and "auth.logout" in actions
    entry = next(e for e in _audit(kit) if e["action"] == "auth.login")
    assert entry["actorEmail"] == "admin@zoop.local" and entry["actorKind"] == "admin" and entry["at"]
