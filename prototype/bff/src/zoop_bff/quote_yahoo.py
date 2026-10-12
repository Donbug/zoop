"""Yahoo Finance public chart endpoint (no key) — the stand-in while 토스증권 keys are absent.

``GET {base}/v8/finance/chart/{symbol}?range=1d|1mo|1y&interval=5m|1d`` returns
``{chart: {result: [{meta, timestamp: [...], indicators: {quote: [{open, high, low, close, volume}]}}], error}}``.
It is unofficial and undocumented, and quotes may be delayed, so the source is labeled that way.
``meta`` carries the last price (``regularMarketPrice``/``regularMarketTime``), ``previousClose`` (for
``range=1d``), the day range, volume and 52-week range. It has no market cap or share count, so those
stay empty. Symbols: ``KRX:005930`` -> ``005930.KS`` (KOSPI) or ``.KQ`` (KOSDAQ, tried when ``.KS``
is not found), US tickers as-is with ``.`` -> ``-`` (``BRK.B`` -> ``BRK-B``), ``TSE:6702`` -> ``6702.T``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx

from .market_data import (
    ACCESS_DENIED,
    KST,
    SERIES_TTL,
    TEMPORARY,
    US_EXCHANGES,
    _KRX_CODE,
    _TSE_CODE,
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

DELAY_NOTE = "비공식 공개 차트 자료예요. 지연된 시세일 수 있어요."
NOT_LISTED = "야후 파이낸스에서 이 종목을 찾지 못했어요."
FORMAT_CHANGED = "야후 파이낸스가 알 수 없는 형식으로 답했어요."
_RANGES: dict[Period, tuple[str, str]] = {"1d": ("1d", "5m"), "1w": ("1mo", "1h"), "1m": ("1mo", "1d"), "1y": ("1y", "1wk")}


class YahooProvider:
    id = "yahoo"

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float,
        cache: TtlCache,
        transport: httpx.BaseTransport | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(KST),
    ):
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        self._cache = cache
        self._now = now
        self._resolved: dict[Listing, str] = {}
        self._lock = threading.Lock()

    def supports(self, listing: Listing) -> bool:
        return bool(self._candidates(listing))

    @staticmethod
    def _candidates(listing: Listing) -> list[str]:
        code = listing.code
        if listing.exchange == "KRX" and _KRX_CODE.match(code):
            return [f"{code}.KS", f"{code}.KQ"]
        if listing.exchange in US_EXCHANGES and _US_TICKER.match(code):
            return [code.replace(".", "-")]
        if listing.exchange == "TSE" and _TSE_CODE.match(code):
            return [f"{code}.T"]
        return []

    def _source(self, symbol: str) -> Source:
        return Source("yahoo", "Yahoo Finance", False, DELAY_NOTE, symbol, f"https://finance.yahoo.com/quote/{symbol}")

    def _chart(self, listing: Listing, period: Period, start: datetime | None = None, end: datetime | None = None) -> tuple[str, dict[str, Any]]:
        range_, interval = _RANGES[period]
        params = {"range": range_, "interval": interval}
        if start and end:
            params = {"period1": int(start.timestamp()), "period2": int(end.timestamp()) + 1, "interval": interval}
        with self._lock:
            known = self._resolved.get(listing)
        for symbol in [known] if known else self._candidates(listing):
            response = request_json(
                self._client, "GET", f"/v8/finance/chart/{symbol}", params=params
            )
            if response.status_code == 404:
                continue
            if response.status_code in (400, 422):
                raise QuoteUnavailable("no_data", "출처에 이 기간의 시세가 없어요. 장중 자료는 제공 기간이 제한돼요.")
            if response.status_code in (401, 403):
                raise QuoteUnavailable("auth_failed", ACCESS_DENIED)
            if not response.is_success:
                raise QuoteUnavailable("temporary_failure", TEMPORARY)
            body = json_body(response)
            chart = body.get("chart") if isinstance(body, dict) else None
            if not isinstance(chart, dict):
                raise QuoteUnavailable("format_changed", FORMAT_CHANGED)
            results = chart.get("result")
            if not results:
                continue  # ``result: null`` with an error object is how Yahoo says it does not know the symbol
            if not isinstance(results, list) or not isinstance(results[0], dict):
                raise QuoteUnavailable("format_changed", FORMAT_CHANGED)
            with self._lock:
                self._resolved[listing] = symbol
            return symbol, results[0]
        raise QuoteUnavailable("unsupported_symbol", NOT_LISTED)

    @staticmethod
    def _zone(meta: dict[str, Any]) -> timezone:
        offset = number(meta.get("gmtoffset"))
        return timezone(timedelta(seconds=int(offset))) if offset is not None else timezone.utc

    def _bars(self, result: dict[str, Any]) -> list[Bar]:
        zone = self._zone(result.get("meta") or {})
        stamps = result.get("timestamp") or []
        quotes = ((result.get("indicators") or {}).get("quote") or [{}])[0] or {}
        columns = [quotes.get(k) or [] for k in ("open", "high", "low", "close", "volume")]
        bars = []
        for i, stamp in enumerate(stamps):
            o, h, low, c, v = (number(col[i]) if i < len(col) else None for col in columns)
            if stamp is None or c is None:
                continue
            bars.append(
                Bar(datetime.fromtimestamp(stamp, zone), o if o is not None else c, h if h is not None else c, low if low is not None else c, c, v)
            )
        return bars

    def _candles(self, result: dict[str, Any], period: Period) -> list[Bar]:
        bars = self._bars(result)
        # A trailing flat, zero-volume quote sample is not a traded candle.
        while bars and bars[-1].volume == 0 and bars[-1].open == bars[-1].high == bars[-1].low == bars[-1].close:
            bars.pop()
        if period == "1d":
            bars = [bar for bar in bars if bar.time.second == 0 and bar.time.minute % 5 == 0]
        elif period == "1w" and bars:
            phase = next((bar.time.minute for bar in bars if bar.time.second == 0), None)
            bars = [bar for bar in bars if bar.time.second == 0 and bar.time.minute == phase]
        return bars

    def quote(self, listing: Listing) -> tuple[Source, Quote]:
        symbol, result = self._chart(listing, "1d")
        meta = result.get("meta") or {}
        price = number(meta.get("regularMarketPrice"))
        currency = meta.get("currency")
        if price is None or not isinstance(currency, str) or not currency:
            raise QuoteUnavailable("no_data", "야후 파이낸스에 이 종목의 현재가가 없어요.")
        stamp = number(meta.get("regularMarketTime"))
        previous_close = number(meta.get("previousClose"))
        quote = Quote(
            currency=currency,
            price=price,
            as_of=datetime.fromtimestamp(stamp, self._zone(meta)) if stamp is not None else None,
            previous_close=previous_close,
            day_high=number(meta.get("regularMarketDayHigh")),
            day_low=number(meta.get("regularMarketDayLow")),
            volume=number(meta.get("regularMarketVolume")),
            fifty_two_week_high=number(meta.get("fiftyTwoWeekHigh")),
            fifty_two_week_low=number(meta.get("fiftyTwoWeekLow")),
            derived=("change", "changeRate") if previous_close is not None else (),
        )
        source = self._source(symbol)
        bars = self._candles(result, "1d")
        if bars:  # the same response is today's intraday chart; spare a second request
            self._cache.put(("yahoo", "series", listing, "1d"), SERIES_TTL["1d"], (source, Series(currency, "5m", tuple(bars))))
        return source, quote

    def series(self, listing: Listing, period: Period, *, start: datetime | None = None, end: datetime | None = None) -> tuple[Source, Series]:
        symbol, result = self._chart(listing, period, start, end)
        currency = (result.get("meta") or {}).get("currency")
        bars = self._candles(result, period)
        if period != "1d" and start is None:
            cutoff = period_start(period, self._now().date())
            bars = [b for b in bars if b.time.date() >= cutoff]
        if not bars or not isinstance(currency, str):
            raise QuoteUnavailable("no_data", "이 기간의 시세가 없어요.")
        return self._source(symbol), Series(currency, _RANGES[period][1], tuple(bars))

    def history(
        self, symbol: str, start: datetime, end: datetime, interval: Literal["1d", "5m"]
    ) -> tuple[Source, Series]:
        """Bars of one provider symbol (an index such as ``^KS11`` or a rate such as ``KRW=X``) between two instants.

        Used for the briefing's market indicators, which are fixed to a point in time. The provider's own window
        edges are not trusted, so callers filter the bars by time. A range the provider refuses (5-minute bars older
        than about 60 days answer 422) is ``no_data``: asking again cannot help.
        """
        response = request_json(
            self._client,
            "GET",
            f"/v8/finance/chart/{symbol}",
            params={"period1": int(start.timestamp()), "period2": int(end.timestamp()), "interval": interval},
        )
        if response.status_code == 404:
            raise QuoteUnavailable("unsupported_symbol", NOT_LISTED)
        if response.status_code in (400, 422):
            raise QuoteUnavailable("no_data", "출처에 이 기간의 자료가 없어요.")
        if not response.is_success:
            raise QuoteUnavailable("temporary_failure", TEMPORARY)
        body = json_body(response)
        chart = body.get("chart") if isinstance(body, dict) else None
        results = chart.get("result") if isinstance(chart, dict) else None
        if not results or not isinstance(results[0], dict):
            raise QuoteUnavailable("no_data", "출처에 이 기간의 자료가 없어요.")
        currency = (results[0].get("meta") or {}).get("currency")
        bars = self._bars(results[0])
        if not bars or not isinstance(currency, str):
            raise QuoteUnavailable("no_data", "출처에 이 기간의 자료가 없어요.")
        bars.sort(key=lambda b: b.time)
        return self._source(symbol), Series(currency, interval, tuple(bars))
