"""FS014 HTTP smoke against a disposable loopback API with synthetic graph fixtures.

Creates a synthetic member. Run only against an isolated local database; no credentials
or session tokens are printed or written to disk.
"""

import json
import os
import uuid
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener
from urllib.parse import urlsplit

BASE = os.environ["ZOOP_GRAPH_SMOKE_BASE_URL"].rstrip("/")
ORIGIN = os.environ.get("ZOOP_GRAPH_SMOKE_ORIGIN", BASE)
if urlsplit(BASE).scheme != "http" or urlsplit(BASE).hostname not in {"127.0.0.1", "localhost"}:
    raise SystemExit("ZOOP_GRAPH_SMOKE_BASE_URL must be a loopback HTTP API")
client = build_opener(HTTPCookieProcessor(CookieJar()))


def call(method, path, body=None, csrf=None, headers=None, expected=200):
    payload = None if body is None else json.dumps(body).encode()
    request_headers = {"Origin": ORIGIN, **(headers or {})}
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
    if csrf:
        request_headers["X-CSRF-Token"] = csrf
    request = Request(BASE + path, payload, request_headers, method=method)
    try:
        with client.open(request) as response:
            status = response.status
            data = response.read()
    except HTTPError as error:
        status = error.code
        data = error.read()
    result = json.loads(data) if data else None
    assert status == expected, (method, path, status, result)
    return result


def personal():
    return call("GET", "/api/v1/graph?mode=personal&personalFilter=all")


market = call("GET", "/api/v1/graph?mode=all")
assert market["nodes"] and all(not node["holding"] and not node["watch"] for node in market["nodes"])
call("GET", "/api/v1/graph?mode=personal", expected=401)
assert call("POST", "/api/v1/auth/guest")["kind"] == "guest"
call("GET", "/api/v1/graph?mode=personal", expected=403)

terms = call("GET", "/api/v1/auth/terms")
agreements = [
    {"id": item["id"], "version": item["version"], "accepted": True}
    for item in terms["items"]
    if item["required"]
]
assert agreements and all(item["version"] for item in agreements)
session = call("POST", "/api/v1/auth/signup", {
    "email": "issue42-" + uuid.uuid4().hex + "@example.test",
    "password": "Issue42!TestOnly2026",
    "displayName": "합성 그래프 테스트",
    "agreements": agreements,
}, expected=201)
csrf = session["csrfToken"]
assert call("GET", "/api/v1/auth/session")["kind"] == "member"

empty = personal()
assert empty["nodes"] == [] and empty["metadata"]["emptyReason"] == "no_personal_stocks"
assert call("GET", "/api/v1/me/settings")["watchlistIds"] == []

saved = call("PUT", "/api/v1/me/settings", {
    "version": 1,
    "investor": False,
    "mode": "watchlist",
    "watchlistIds": ["NASDAQ:NVDA", "KRX:005930"],
    "completed": True,
}, csrf=csrf)
watched = personal()
assert watched["metadata"]["focusCompanyIds"] == ["NASDAQ:NVDA", "KRX:005930"]
assert any(node["id"] == "NASDAQ:NVDA" and node["watch"] for node in watched["nodes"])

connection = call("POST", "/api/v1/portfolio/connections", {
    "mockPortfolioId": "demo-balanced",
}, csrf=csrf, headers={"Idempotency-Key": "issue42-connect"}, expected=201)
combined = personal()
assert combined["metadata"]["focusCompanyIds"] == ["KRX:005930", "KRX:000660", "NYSE:TSM", "NASDAQ:NVDA"]
assert any(node["id"] == "KRX:005930" and node["holding"] and node["watch"] for node in combined["nodes"])

call("PUT", "/api/v1/me/settings", {
    "version": saved["version"],
    "watchlistIds": [],
}, csrf=csrf)
held = personal()
assert held["metadata"]["focusCompanyIds"] == ["KRX:005930", "KRX:000660", "NYSE:TSM"]
assert all(not node["watch"] for node in held["nodes"])
call("DELETE", "/api/v1/portfolio/connections/" + connection["id"], csrf=csrf, expected=204)
assert personal()["metadata"]["emptyReason"] == "no_personal_stocks"
call("GET", "/api/v1/graph?mode=personal&round=brf-2026-09-17-evening", expected=422)
print("HTTP FS014: market, anonymous=401, guest=403, empty, watch-only, holdings+watch, holdings-only, clear, round=422 passed")
