"""Quote providers: 토스증권 adapter against a fake HTTP server, Yahoo mapping, auto selection, API shape."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from zoop_bff.app import create_app
from zoop_bff.config import Settings
from zoop_bff.market_data import KST, Listing, MarketData, TtlCache, build_market_data
from zoop_bff.quote_naver import NaverMetricsProvider
from zoop_bff.quote_toss import TossProvider
from zoop_bff.quote_yahoo import YahooProvider

from .conftest import base_payload

CLIENT_ID = "fake-client-id"
SECRET = "fake-secret-value-123"
NOW = datetime(2026, 10, 1, 14, 0, tzinfo=KST)


def _day(offset: int) -> str:
    return (NOW.date() - timedelta(days=offset)).isoformat() + "T00:00:00+09:00"


class FakeToss:
    """Implements the documented request/response shapes of the endpoints the adapter uses."""

    def __init__(self) -> None:
        self.tokens_issued = 0
        self.calls: list[tuple[str, dict[str, list[str]]]] = []
        self.fail: list[int] = []  # statuses to return (in order) before normal answers
        self.reject_token: str | None = None
        self.token_status = 200
        # 400 calendar days of daily candles, newest first, close = 1000 + offset so values are predictable.
        self.daily = [
            {"timestamp": _day(i), "openPrice": 1000 + i, "highPrice": 1100 + i, "lowPrice": 900 + i,
             "closePrice": str(1000 + i), "volume": 50 + i, "currency": "KRW"}
            for i in range(400)
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        query = parse_qs(request.url.query.decode())
        if path == "/oauth2/token":
            form = parse_qs(request.content.decode())
            self.calls.append((path, form))
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_client"})
            assert form == {"grant_type": ["client_credentials"], "client_id": [CLIENT_ID], "client_secret": [SECRET]}
            self.tokens_issued += 1
            return httpx.Response(200, json={"access_token": f"tok-{self.tokens_issued}", "token_type": "Bearer", "expires_in": 3600})
        self.calls.append((path, query))
        if self.fail:
            return httpx.Response(self.fail.pop(0), json={"error": {"requestId": "r", "code": "x", "message": ""}})
        auth = request.headers.get("Authorization")
        if auth is None or auth == f"Bearer {self.reject_token}":
            return httpx.Response(401, json={"error": {"requestId": "r", "code": "unauthorized", "message": ""}})
        if path == "/api/v1/prices":
            symbols = query["symbols"][0].split(",")
            if symbols != ["005930"]:
                return httpx.Response(200, json={"result": []})
            return httpx.Response(200, json={"result": [{"symbol": "005930", "timestamp": NOW.isoformat(), "lastPrice": "1005", "currency": "KRW"}]})
        if path == "/api/v1/stocks":
            return httpx.Response(200, json={"result": [{"symbol": "005930", "name": "삼성전자", "market": "KOSPI", "currency": "KRW", "sharesOutstanding": "1000000"}]})
        if path == "/api/v1/candles":
            assert int(query["count"][0]) <= 200
            if query["interval"] == ["1d"]:
                start = 0
                if "before" in query:
                    start = next(i for i, c in enumerate(self.daily) if c["timestamp"] <= query["before"][0])
                page = self.daily[start : start + 200]
                rest = self.daily[start + 200 :]
                return httpx.Response(200, json={"result": {"candles": page, "nextBefore": rest[0]["timestamp"] if rest else None}})
            return httpx.Response(200, json={"result": {"candles": [], "nextBefore": None}})
        return httpx.Response(404)

    def count(self, path: str) -> int:
        return sum(1 for p, _ in self.calls if p == path)


def toss(fake: FakeToss, clock=lambda: 0.0) -> TossProvider:
    return TossProvider(
        CLIENT_ID, SECRET, base_url="https://toss.test", timeout=1, cache=TtlCache(),
        transport=httpx.MockTransport(fake.handler), clock=clock, now=lambda: NOW,
    )


def test_token_is_cached_reissued_before_expiry_and_after_401():
    fake, now = FakeToss(), [0.0]
    client = toss(fake, clock=lambda: now[0]).client
    client.get("/api/v1/prices", {"symbols": "005930"})
    client.get("/api/v1/prices", {"symbols": "005930"})
    assert fake.tokens_issued == 1
    now[0] = 3600 - 30  # inside the 60 s safety margin -> re-issue before the server would reject
    client.get("/api/v1/prices", {"symbols": "005930"})
    assert fake.tokens_issued == 2
    fake.reject_token = "tok-2"  # server revoked the token early: one re-issue, then the call succeeds
    assert client.get("/api/v1/prices", {"symbols": "005930"})[0]["lastPrice"] == "1005"
    assert fake.tokens_issued == 3


def test_daily_candles_follow_next_before_and_compute_derived_values():
    fake = FakeToss()
    source, quote = toss(fake).quote(Listing("KRX", "005930"))
    candle_calls = [q for p, q in fake.calls if p == "/api/v1/candles"]
    assert len(candle_calls) == 2 and "before" not in candle_calls[0]
    assert candle_calls[1]["before"] == [_day(200)]  # '+09:00' survives query encoding
    assert source.provider == "toss" and source.official and source.symbol == "005930"
    assert quote.price == 1005 and quote.previous_close == 1001  # yesterday's daily close
    assert quote.day_high == 1100 and quote.volume == 50  # today's daily candle
    assert quote.market_cap == 1005 * 1_000_000
    assert {"marketCap", "previousClose", "change", "fiftyTwoWeekHigh"} <= set(quote.derived)
    assert quote.fifty_two_week_low == 900 and quote.fifty_two_week_high == 1100 + 364


def test_series_for_month_starts_at_the_timeline_period_start():
    _, series = toss(FakeToss()).series(Listing("KRX", "005930"), "1m")
    assert series.interval == "1d" and series.bars[0].time.date().isoformat() == "2026-09-01"
    assert series.bars[-1].time.date() == NOW.date()  # oldest first


@pytest.mark.parametrize(
    ("statuses", "code", "requests"),
    [
        ([429], "temporary_failure", 1),  # rate limit is never retried
        ([503, 503], "temporary_failure", 2),  # 5xx retried once
        ([400], "unsupported_symbol", 1),
    ],
)
def test_errors_are_classified(statuses, code, requests):
    fake = FakeToss()
    fake.fail = list(statuses)
    market = MarketData("toss", toss=toss(fake))
    result = market.quote("KRX:005930")
    assert result.quote is None and result.code == code
    assert fake.count("/api/v1/prices") == requests


def test_transient_5xx_recovers_and_temporary_failures_are_not_cached():
    fake = FakeToss()
    fake.fail = [502]
    assert MarketData("toss", toss=toss(fake)).quote("KRX:005930").quote is not None
    fake = FakeToss()
    market = MarketData("toss", toss=toss(fake))
    fake.fail = [429]
    assert market.quote("KRX:005930").code == "temporary_failure"
    assert market.quote("KRX:005930").quote is not None  # [다시 시도] really asks again


def test_bad_credentials_are_auth_failed_not_a_temporary_outage():
    fake = FakeToss()
    fake.token_status = 401
    result = MarketData("toss", toss=toss(fake)).quote("KRX:005930")
    assert result.code == "auth_failed"


def test_unknown_symbol_is_unsupported_not_empty():
    result = MarketData("toss", toss=toss(FakeToss())).quote("KRX:999999")
    assert result.code == "unsupported_symbol"


def test_symbol_mapping():
    t, y = toss(FakeToss()), YahooProvider(base_url="https://y.test", timeout=1, cache=TtlCache())
    assert t.supports(Listing.of("KRX:005930")) and t.supports(Listing.of("NYSE:BRK.B"))
    assert not t.supports(Listing.of("TSE:6702"))  # Toss lists KRX and US only
    assert y._candidates(Listing.of("KRX:005930")) == ["005930.KS", "005930.KQ"]
    assert y._candidates(Listing.of("NYSE:BRK.B")) == ["BRK-B"]
    assert y._candidates(Listing.of("TSE:6702")) == ["6702.T"]
    assert Listing.of("SYNTH-ALPHA") is None and not y.supports(Listing.of("LSE:VOD"))


def _yahoo_chart(symbol: str) -> dict[str, Any]:
    return {"chart": {"result": [{
        "meta": {"currency": "KRW", "symbol": symbol, "regularMarketPrice": 300.0, "previousClose": 250.0,
                 "regularMarketTime": 1790828459, "gmtoffset": 32400, "regularMarketDayHigh": 310.0,
                 "regularMarketDayLow": 290.0, "regularMarketVolume": 12, "fiftyTwoWeekHigh": 400.0, "fiftyTwoWeekLow": 100.0},
        "timestamp": [1790812800, 1790813100],
        "indicators": {"quote": [{"open": [1, 2], "high": [1, 2], "low": [1, 2], "close": [295.0, None], "volume": [1, 2]}]},
    }], "error": None}}


def test_yahoo_tries_kosdaq_after_kospi_and_never_invents_market_cap():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        symbol = request.url.path.rsplit("/", 1)[-1]
        seen.append(symbol)
        if symbol.endswith(".KS"):
            return httpx.Response(404, json={"chart": {"result": None, "error": {"code": "Not Found"}}})
        return httpx.Response(200, json=_yahoo_chart(symbol))

    cache = TtlCache()
    yahoo = YahooProvider(base_url="https://y.test", timeout=1, cache=cache, transport=httpx.MockTransport(handler))
    market = MarketData("yahoo", yahoo=yahoo, cache=cache)
    result = market.quote("KRX:091990")
    assert seen == ["091990.KS", "091990.KQ"]
    assert result.source.symbol == "091990.KQ" and not result.source.official and result.source.delay_note
    q = result.quote
    assert (q.price, q.change, round(q.change_rate, 2)) == (300.0, 50.0, 0.2)
    assert q.market_cap is None and "marketCap" not in q.derived
    series = market.series("KRX:091990", "1d")  # reused from the quote response
    assert len(seen) == 2 and [b.close for b in series.series.bars] == [295.0]


def test_auto_prefers_toss_when_keys_exist_and_falls_back_per_symbol():
    yahoo = YahooProvider(base_url="https://y.test", timeout=1, cache=TtlCache())
    market = MarketData("auto", toss=toss(FakeToss()), yahoo=yahoo)
    assert market.provider_for("KRX:005930")[0].id == "toss"
    assert market.provider_for("TSE:6702")[0].id == "yahoo"
    keyless = build_market_data("auto", toss_client_id=None, toss_client_secret=None, toss_base_url="https://t",
                                yahoo_base_url="https://y", timeout=1)
    assert keyless.provider_for("KRX:005930")[0].id == "yahoo"
    forced = build_market_data("toss", toss_client_id=None, toss_client_secret=None, toss_base_url="https://t",
                               yahoo_base_url="https://y", timeout=1)
    assert forced.quote("KRX:005930").code == "not_connected"
    assert MarketData("off").series("KRX:005930", "1m").code == "not_connected"


def test_quote_api_reports_source_and_hides_secrets(tmp_path: Path, caplog):
    payload = base_payload()
    payload["zoop"] = {**payload.get("zoop", {}), "companies": [
        {"company_id": "KRX:005930", "name": "삼성전자", "ticker": "005930", "aliases": []},
        {"company_id": "TSE:6702", "name": "Fujitsu", "ticker": "6702", "aliases": []},
    ]}
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    settings = Settings(snapshot_path=snapshot, company_catalog=None, state_dir=tmp_path / "state",
                        toss_client_id=CLIENT_ID, toss_client_secret=SECRET)
    fake = FakeToss()
    client = TestClient(create_app(settings, quotes=MarketData("toss", toss=toss(fake))))
    with caplog.at_level(logging.DEBUG):
        quote = client.get("/api/companies/KRX:005930/quote")
        prices = client.get("/api/companies/KRX:005930/prices", params={"period": "1y"})
        unsupported = client.get("/api/companies/TSE:6702/quote").json()
    body = quote.json()
    assert body["status"] == "available" and body["source"]["name"] == "토스증권"
    assert body["quote"]["marketCap"] == 1005 * 1_000_000 and "marketCap" in body["quote"]["derived"]
    assert body["quote"]["asOf"].endswith("+09:00")
    assert prices.json()["status"] == "available" and prices.json()["points"][0]["time"] < prices.json()["points"][-1]["time"]
    assert unsupported["status"] == "unavailable" and unsupported["reasonCode"] == "unsupported_symbol"
    assert client.get("/api/companies/NOPE/quote").status_code == 404
    leaked = quote.text + prices.text + caplog.text + repr(settings)
    assert SECRET not in leaked and "tok-1" not in leaked


# --------------------------------------------------------------------------- indicators (네이버 증권)


def _naver(handler) -> NaverMetricsProvider:
    return NaverMetricsProvider(
        domestic_url="https://m.test", world_url="https://w.test", ac_url="https://ac.test", timeout=1,
        cache=TtlCache(), transport=httpx.MockTransport(handler),
    )


def _naver_ok(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    if host == "m.test" and path.endswith("/integration"):
        return httpx.Response(200, json={"totalInfos": [
            {"code": "lastClosePrice", "key": "전일", "value": "268,500"},
            {"code": "marketValue", "key": "시총", "value": "1,609조 1,882억"},
            {"code": "per", "key": "PER", "value": "12.35배", "valueDesc": "2026.06."},
            {"code": "cnsPer", "key": "추정PER", "value": "5.78배"},
            {"code": "pbr", "key": "PBR", "value": "N/A", "valueDesc": "2026.06."},
        ]})
    if host == "m.test" and path.endswith("/basic"):
        return httpx.Response(200, json={"localTradedAt": "2026-10-01T14:36:21+09:00"})
    if host == "ac.test":
        return httpx.Response(200, json={"items": [
            {"code": "HPE", "typeCode": "AMEX", "reutersCode": "HPE.A"},
            {"code": "HPE", "typeCode": "NYSE", "reutersCode": "HPE"},
        ]})
    if host == "w.test" and path == "/stock/HPE/basic":
        return httpx.Response(200, json={"localTradedAt": "2026-09-30T16:00:00-04:00", "stockItemTotalInfos": [
            {"code": "marketValue", "key": "시총", "value": "848억 USD", "valueDesc": "116조원"},
            {"code": "per", "key": "PER", "value": "28.97배", "keyDesc": "2026.07."},
        ]})
    return httpx.Response(409)


def test_indicators_pass_through_source_values_and_periods():
    _, krx = _naver(_naver_ok).metrics(Listing("KRX", "005930"))
    assert [(m.code, m.value, m.basis) for m in krx.items] == [("marketValue", "1,609조 1,882억", None), ("per", "12.35배", "2026.06.")]
    assert krx.as_of.isoformat() == "2026-10-01T14:36:21+09:00"  # price rows, estimates and N/A are dropped
    source, us = _naver(_naver_ok).metrics(Listing("NYSE", "HPE"))
    assert source.symbol == "HPE" and not source.official  # resolved on the listing exchange, not AMEX
    assert [(m.code, m.value, m.basis) for m in us.items] == [("marketValue", "848억 USD", None), ("per", "28.97배", "2026.07.")]


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(409), "unsupported_symbol"),
        (httpx.Response(503), "temporary_failure"),
        (httpx.Response(200, json={"renamed": []}), "format_changed"),
        (httpx.Response(200, text="<html>blocked</html>"), "format_changed"),
    ],
)
def test_indicator_failures_are_classified(response, code):
    market = MarketData("off", metrics=_naver(lambda _: response))
    result = market.metrics("KRX:005930")
    assert result.metrics is None and result.code == code


def test_indicator_failure_does_not_touch_quotes():
    fake = FakeToss()
    market = MarketData("toss", toss=toss(fake), metrics=_naver(lambda _: httpx.Response(503)))
    assert market.metrics("KRX:005930").code == "temporary_failure"
    quote = market.quote("KRX:005930")
    assert quote.quote is not None and quote.source.provider == "toss" and quote.quote.market_cap == 1005 * 1_000_000
