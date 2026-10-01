"""토스증권 Open API quote provider (requirement 72).

Docs: https://openapi.tossinvest.com/openapi-docs/latest/api-reference/README.md

- ``POST /oauth2/token`` (form, ``grant_type=client_credentials``) -> ``{access_token, token_type, expires_in}``.
  No refresh token: the access token is cached and re-issued 60 s before expiry or after a 401.
- ``GET /api/v1/prices?symbols=a,b`` -> ``{result: [{symbol, timestamp?, lastPrice, currency}]}`` (max 200).
- ``GET /api/v1/candles?symbol&interval=1m|1d&count<=200&before`` ->
  ``{result: {candles: [newest first], nextBefore?}}``; ``1d`` candle timestamps are the trading day at local midnight.
- ``GET /api/v1/stocks?symbols=`` -> ``{result: [StockInfo]}`` (``sharesOutstanding``, ``currency``, ``market``).
- Errors: ``{error: {requestId, code, message}}``; OAuth errors follow the OAuth2 format.

The price endpoint gives only the last price, so the previous close, day range and volume come from
daily candles; the change, 52-week range and market cap (last price x shares outstanding) are
computed here and listed in ``Quote.derived``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx

from .market_data import (
    KST,
    REFERENCE_TTL,
    SERIES_TTL,
    TEMPORARY,
    US_EXCHANGES,
    _KRX_CODE,
    _US_TICKER,
    Bar,
    Listing,
    Period,
    Quote,
    QuoteUnavailable,
    Series,
    Source,
    TtlCache,
    json_body,
    number,
    period_start,
    request_json,
)

AUTH_FAILED = "토스증권 인증에 실패했어요. 시세 키를 확인해 주세요."
NOT_LISTED = "토스증권에서 이 종목을 찾지 못했어요."
PAGE_SIZE = 200


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)


def _bar(item: Any) -> Bar | None:
    if not isinstance(item, dict):
        return None
    moment = _parse_time(item.get("timestamp"))
    values = [number(item.get(k)) for k in ("openPrice", "highPrice", "lowPrice", "closePrice")]
    if moment is None or any(v is None for v in values):
        return None
    o, h, low, c = values  # type: ignore[misc]
    return Bar(moment, o, h, low, c, number(item.get("volume")))  # type: ignore[arg-type]


class TossClient:
    """HTTP client with a cached bearer token. Secrets live only in this object (never logged)."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        base_url: str,
        timeout: float,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self._credentials = {"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret}
        self._client = httpx.Client(
            base_url=base_url, timeout=timeout, transport=transport, headers={"Accept": "application/json"}
        )
        self._clock = clock
        self._token: str | None = None
        self._expires = 0.0
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "TossClient(<credentials hidden>)"

    def token(self, *, stale: str | None = None) -> str:
        """Cached token; ``stale`` forces a re-issue unless another caller already replaced it."""
        with self._lock:
            if self._token and self._clock() < self._expires and self._token != stale:
                return self._token
            response = request_json(self._client, "POST", "/oauth2/token", data=self._credentials)
            if response.status_code in (400, 401, 403):
                raise QuoteUnavailable("auth_failed", AUTH_FAILED)
            if response.status_code != 200:
                raise QuoteUnavailable("temporary_failure", TEMPORARY)
            body = json_body(response)
            token = body.get("access_token") if isinstance(body, dict) else None
            expires_in = number(body.get("expires_in")) if isinstance(body, dict) else None
            if not isinstance(token, str) or not token or not expires_in:
                raise QuoteUnavailable("temporary_failure", "토스증권이 알 수 없는 형식으로 답했어요.")
            self._token = token
            self._expires = self._clock() + max(expires_in - 60, expires_in / 2)
            return token

    def get(self, path: str, params: dict[str, Any]) -> Any:
        token = self.token()
        for attempt in range(2):
            response = request_json(
                self._client, "GET", path, params=params, headers={"Authorization": f"Bearer {token}"}
            )
            if response.status_code == 401 and attempt == 0:
                token = self.token(stale=token)
                continue
            if response.status_code in (401, 403):
                raise QuoteUnavailable("auth_failed", AUTH_FAILED)
            if response.status_code in (400, 404):
                raise QuoteUnavailable("unsupported_symbol", NOT_LISTED)
            if not response.is_success:
                raise QuoteUnavailable("temporary_failure", TEMPORARY)
            body = json_body(response)
            if not isinstance(body, dict) or "result" not in body:
                raise QuoteUnavailable("temporary_failure", "토스증권이 알 수 없는 형식으로 답했어요.")
            return body["result"]
        raise AssertionError("unreachable")


class TossProvider:
    id = "toss"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        base_url: str,
        timeout: float,
        cache: TtlCache,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        now: Callable[[], datetime] = lambda: datetime.now(KST),
    ):
        self.client = TossClient(
            client_id, client_secret, base_url=base_url, timeout=timeout, transport=transport, clock=clock
        )
        self._cache = cache
        self._now = now

    def supports(self, listing: Listing) -> bool:
        if listing.exchange == "KRX":
            return bool(_KRX_CODE.match(listing.code))
        return listing.exchange in US_EXCHANGES and bool(_US_TICKER.match(listing.code))

    def _source(self, symbol: str) -> Source:
        return Source("toss", "토스증권", True, None, symbol, None)

    def _info(self, symbol: str) -> dict[str, Any]:
        def load() -> dict[str, Any]:
            items = self.client.get("/api/v1/stocks", {"symbols": symbol})
            match = next((i for i in items or [] if isinstance(i, dict) and i.get("symbol") == symbol), None)
            if match is None:
                raise QuoteUnavailable("unsupported_symbol", NOT_LISTED)
            return match

        return self._cache.get_or_load(("toss", "info", symbol), REFERENCE_TTL, load)

    def candles(self, symbol: str, interval: str, *, keep: Callable[[Bar], bool], max_pages: int) -> list[Bar]:
        """Newest-first bars, following ``nextBefore`` until a bar fails ``keep`` or pages run out."""
        bars: list[Bar] = []
        before: str | None = None
        for _ in range(max_pages):
            params: dict[str, Any] = {"symbol": symbol, "interval": interval, "count": PAGE_SIZE}
            if before:
                params["before"] = before
            page = self.client.get("/api/v1/candles", params)
            items = page.get("candles") if isinstance(page, dict) else None
            for item in items or []:
                bar = _bar(item)
                if bar is None:
                    continue
                if not keep(bar):
                    return bars
                bars.append(bar)
            before = page.get("nextBefore") if isinstance(page, dict) else None
            if not items or not before:
                break
        return bars

    def _daily_year(self, symbol: str) -> list[Bar]:
        cutoff = self._now().date() - timedelta(days=372)
        return self._cache.get_or_load(
            ("toss", "daily", symbol),
            SERIES_TTL["1m"],
            lambda: self.candles(symbol, "1d", keep=lambda b: b.time.date() >= cutoff, max_pages=3),
        )

    def quote(self, listing: Listing) -> tuple[Source, Quote]:
        symbol = listing.code
        prices = self.client.get("/api/v1/prices", {"symbols": symbol})
        item = next((p for p in prices or [] if isinstance(p, dict) and p.get("symbol") == symbol), None)
        if item is None:
            raise QuoteUnavailable("unsupported_symbol", NOT_LISTED)
        last = number(item.get("lastPrice"))
        if last is None:
            raise QuoteUnavailable("no_data", "토스증권에 이 종목의 현재가가 없어요.")
        as_of = _parse_time(item.get("timestamp"))
        info = self._info(symbol)
        daily = self._daily_year(symbol)
        currency = item.get("currency") or info.get("currency")
        if not isinstance(currency, str) or not currency:
            raise QuoteUnavailable("no_data", "토스증권 응답에 통화가 없어요.")

        derived: list[str] = []
        session = None
        if daily:
            session = as_of.astimezone(daily[0].time.tzinfo).date() if as_of else daily[0].time.date()
        today_bar = next((b for b in daily if b.time.date() == session), None)
        prev_bar = next((b for b in daily if session and b.time.date() < session), None)
        previous_close = prev_bar.close if prev_bar else None
        if previous_close is not None:
            derived += ["previousClose", "change", "changeRate"]
        year = [b for b in daily if session and b.time.date() > session - timedelta(days=365)]
        high_52 = max((b.high for b in year), default=None)
        low_52 = min((b.low for b in year), default=None)
        if year:
            derived += ["fiftyTwoWeekHigh", "fiftyTwoWeekLow"]
        shares = number(info.get("sharesOutstanding"))
        market_cap = last * shares if shares else None
        if market_cap is not None:
            derived.append("marketCap")
        quote = Quote(
            currency=currency,
            price=last,
            as_of=as_of,
            previous_close=previous_close,
            day_high=today_bar.high if today_bar else None,
            day_low=today_bar.low if today_bar else None,
            volume=today_bar.volume if today_bar else None,
            fifty_two_week_high=high_52,
            fifty_two_week_low=low_52,
            market_cap=market_cap,
            shares_outstanding=shares,
            derived=tuple(derived),
        )
        return self._source(symbol), quote

    def series(self, listing: Listing, period: Period) -> tuple[Source, Series]:
        symbol = listing.code
        if period == "1d":
            session: list = []

            def same_session(bar: Bar) -> bool:
                if not session:
                    session.append(bar.time.date())
                return bar.time.date() == session[0]

            bars = self.candles(symbol, "1m", keep=same_session, max_pages=3)
            interval = "1m"
        else:
            start = period_start(period, self._now().date())
            bars = [b for b in self._daily_year(symbol) if b.time.date() >= start]
            interval = "1d"
        if not bars:
            raise QuoteUnavailable("no_data", "이 기간의 시세가 없어요.")
        info = self._info(symbol)
        currency = info.get("currency")
        if not isinstance(currency, str) or not currency:
            raise QuoteUnavailable("no_data", "토스증권 응답에 통화가 없어요.")
        return self._source(symbol), Series(currency, interval, tuple(reversed(bars)))
