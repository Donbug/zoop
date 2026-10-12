"""Stock quotes and price series for the company detail (requirements 35-37, 72).

Providers (``ZOOP_QUOTE_PROVIDER``):

- ``toss``: 토스증권 Open API (official, OAuth2 client credentials). KRX and US listings only.
- ``yahoo``: Yahoo Finance's public chart endpoint (unofficial, no key, quotes may be delayed).
- ``auto`` (default from the environment): Toss when its keys are set and it lists the symbol,
  otherwise Yahoo. ``off``: no quotes.

A provider value is passed through as received. Values the BFF computes from provider data
(change, market cap, 52-week range from daily candles, ...) are listed in ``Quote.derived``.
A missing value stays ``None``; nothing is estimated from another source.

Failures are classified, never shown as empty data. Normal absence -- ``not_connected`` (provider off or keys
missing), ``unsupported_symbol``, ``no_data`` (provider answered but has nothing for the period) -- is an answer
(``ABSENCE_CODES``). Everything else is a failure of the source: ``auth_failed``, ``temporary_failure`` (timeout,
network, 429, 5xx) and ``format_changed`` (not JSON, or not the shape the adapter reads). Only
``temporary_failure`` is worth retrying unchanged (``RETRYABLE_CODES``).
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar

import httpx

from .config import QuoteProviderMode

if TYPE_CHECKING:
    from .quote_naver import Metrics, NaverMetricsProvider

Period = Literal["1d", "1w", "1m", "1y"]
ProviderId = Literal["toss", "yahoo", "naver"]
ProviderMode = QuoteProviderMode
ReasonCode = Literal[
    "not_connected", "unsupported_symbol", "no_data", "auth_failed", "temporary_failure", "format_changed"
]

ABSENCE_CODES = frozenset({"not_connected", "unsupported_symbol", "no_data"})
RETRYABLE_CODES = frozenset({"temporary_failure"})

KST = timezone(timedelta(hours=9))
US_EXCHANGES = frozenset({"NASDAQ", "NYSE", "AMEX"})
_KRX_CODE = re.compile(r"^[0-9A-Z]{6}$")
_US_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_TSE_CODE = re.compile(r"^[0-9A-Z]{4}$")


class QuoteUnavailable(Exception):
    """A classified reason the quote or series cannot be shown. ``reason`` is user-facing Korean."""

    def __init__(self, code: ReasonCode, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


# Shared by the quote and indicator sources; the screen's title says which area failed.
TEMPORARY = "출처에 잠시 연결하지 못했어요. 잠시 후 다시 시도해 주세요."
RATE_LIMITED = "출처의 요청 한도에 걸렸어요. 잠시 후 다시 시도해 주세요."
ACCESS_DENIED = "출처가 접근을 거부했어요. 키 문제가 아닐 수도 있어요."


@dataclass(frozen=True)
class Listing:
    """Exchange and code taken from the catalog company id (``KRX:005930``, ``NASDAQ:NVDA``)."""

    exchange: str
    code: str

    @classmethod
    def of(cls, company_id: str) -> Listing | None:
        exchange, sep, code = company_id.partition(":")
        if not sep or not exchange or not code:
            return None
        return cls(exchange.strip().upper(), code.strip().upper())


@dataclass(frozen=True)
class Source:
    provider: ProviderId
    name: str
    official: bool
    delay_note: str | None
    symbol: str
    url: str | None


@dataclass(frozen=True)
class Quote:
    currency: str
    price: float
    as_of: datetime | None
    previous_close: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    volume: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    market_cap: float | None = None
    shares_outstanding: float | None = None
    derived: tuple[str, ...] = ()

    @property
    def change(self) -> float | None:
        # Rounded to drop binary float noise (18.89 - 18.54 -> 0.35); prices carry at most 4 decimals.
        return None if self.previous_close is None else round(self.price - self.previous_close, 6)

    @property
    def change_rate(self) -> float | None:
        if not self.previous_close:
            return None
        return round((self.price - self.previous_close) / self.previous_close, 8)


@dataclass(frozen=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None


@dataclass(frozen=True)
class Series:
    currency: str
    interval: str
    bars: tuple[Bar, ...]


class QuoteProvider(Protocol):
    id: ProviderId

    def supports(self, listing: Listing) -> bool: ...

    def quote(self, listing: Listing) -> tuple[Source, Quote]: ...

    def series(self, listing: Listing, period: Period, *, start: datetime | None = None, end: datetime | None = None) -> tuple[Source, Series]: ...


# --------------------------------------------------------------------------- helpers


def period_start(period: Period, today: date) -> date:
    """Same rule as the timeline (web ``periodFrom``): 1 month / 1 year back, clamped to month end."""
    if period == "1d":
        return today
    if period == "1w":
        return today - timedelta(days=7)
    months = 1 if period == "1m" else 12
    index = today.year * 12 + (today.month - 1) - months
    year, month = divmod(index, 12)
    month += 1
    next_month = date(year + (month == 12), month % 12 + 1, 1)
    last_day = (next_month - timedelta(days=1)).day
    return date(year, month, min(today.day, last_day))


def number(value: Any) -> float | None:
    """Provider decimals arrive as JSON numbers or strings; anything else is treated as missing."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None  # NaN -> None


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    retries: int = 1,
    not_found: QuoteUnavailable | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Send with one retry for timeouts, network errors and 5xx; 429 is never retried.

    Returns the response for 2xx and for 4xx other than 404/429 (callers classify those).
    """
    for attempt in range(retries + 1):
        try:
            response = client.request(method, url, **kwargs)
        except httpx.TimeoutException:
            if attempt < retries:
                continue
            raise QuoteUnavailable("temporary_failure", "출처의 응답이 늦어요. 잠시 후 다시 시도해 주세요.") from None
        except httpx.HTTPError:
            if attempt < retries:
                continue
            raise QuoteUnavailable("temporary_failure", TEMPORARY) from None
        if response.status_code == 429:
            raise QuoteUnavailable("temporary_failure", RATE_LIMITED)
        if response.status_code >= 500:
            if attempt < retries:
                continue
            raise QuoteUnavailable("temporary_failure", TEMPORARY)
        if response.status_code == 404 and not_found is not None:
            raise not_found
        return response
    raise AssertionError("unreachable")


def json_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        # Not JSON (block page, HTML error, changed endpoint): retrying will not help, so it is not "temporary".
        raise QuoteUnavailable("format_changed", "출처가 알 수 없는 형식으로 답했어요.") from None


T = TypeVar("T")


@dataclass
class _Entry:
    expires: float
    value: Any


@dataclass
class TtlCache:
    """Small in-process cache. Temporary failures are not cached so [다시 시도] really retries;
    unsupported symbols and empty periods are cached like values. Loads of one key are serialized."""

    clock: Callable[[], float] = time.monotonic
    _entries: dict[tuple, _Entry] = field(default_factory=dict)
    _locks: dict[tuple, threading.Lock] = field(default_factory=dict)
    _guard: threading.Lock = field(default_factory=threading.Lock)

    def get_or_load(self, key: tuple, ttl: float, loader: Callable[[], T]) -> T:
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            entry = self._entries.get(key)
            if entry and entry.expires > self.clock():
                if isinstance(entry.value, QuoteUnavailable):
                    raise entry.value
                return entry.value
            try:
                value = loader()
            except QuoteUnavailable as exc:
                if exc.code in ("unsupported_symbol", "no_data", "format_changed"):
                    self._entries[key] = _Entry(self.clock() + ttl, exc)
                raise
            self._entries[key] = _Entry(self.clock() + ttl, value)
            return value

    def put(self, key: tuple, ttl: float, value: Any) -> None:
        with self._guard:
            self._entries[key] = _Entry(self.clock() + ttl, value)


QUOTE_TTL = 30.0
SERIES_TTL: dict[Period, float] = {"1d": 60.0, "1w": 300.0, "1m": 30 * 60.0, "1y": 60 * 60.0}
REFERENCE_TTL = 12 * 60 * 60.0
METRICS_TTL = 30 * 60.0


# --------------------------------------------------------------------------- service

NOT_CONNECTED_OFF = "시세 출처를 연결하지 않았어요."
NOT_CONNECTED_TOSS = "토스증권 시세 키가 설정되지 않았어요."


@dataclass
class QuoteResult:
    source: Source | None
    quote: Quote | None = None
    series: Series | None = None
    metrics: Metrics | None = None
    code: ReasonCode | None = None
    reason: str | None = None


class MarketData:
    """Chooses a provider per company and caches results (quote ~30 s, daily candles 30-60 min)."""

    def __init__(
        self,
        mode: ProviderMode,
        *,
        toss: QuoteProvider | None = None,
        yahoo: QuoteProvider | None = None,
        metrics: NaverMetricsProvider | None = None,
        cache: TtlCache | None = None,
    ):
        self.mode = mode
        self.toss = toss
        self.yahoo = yahoo
        self.metrics_provider = metrics
        self.cache = cache or TtlCache()

    def provider_for(self, company_id: str) -> tuple[QuoteProvider, Listing]:
        if self.mode == "off":
            raise QuoteUnavailable("not_connected", NOT_CONNECTED_OFF)
        if self.mode == "toss" and self.toss is None:
            raise QuoteUnavailable("not_connected", NOT_CONNECTED_TOSS)
        listing = Listing.of(company_id)
        if self.mode == "toss":
            candidates = [self.toss]
        elif self.mode == "yahoo":
            candidates = [self.yahoo]
        else:
            candidates = [self.toss, self.yahoo]
        for provider in candidates:
            if provider is not None and listing is not None and provider.supports(listing):
                return provider, listing
        raise QuoteUnavailable("unsupported_symbol", "이 종목은 연결한 시세 출처에서 제공하지 않아요.")

    def quote(self, company_id: str) -> QuoteResult:
        try:
            provider, listing = self.provider_for(company_id)
            source, quote = self.cache.get_or_load(
                (provider.id, "quote", listing), QUOTE_TTL, lambda: provider.quote(listing)
            )
        except QuoteUnavailable as exc:
            return QuoteResult(None, code=exc.code, reason=exc.reason)
        return QuoteResult(source, quote=quote)

    def series(self, company_id: str, period: Period, *, start: datetime | None = None, end: datetime | None = None) -> QuoteResult:
        try:
            provider, listing = self.provider_for(company_id)
            source, series = self.cache.get_or_load(
                (provider.id, "series", listing, period, start, end) if start or end else (provider.id, "series", listing, period), SERIES_TTL[period],
                lambda: provider.series(listing, period, start=start, end=end) if start or end else provider.series(listing, period)
            )
        except QuoteUnavailable as exc:
            return QuoteResult(None, code=exc.code, reason=exc.reason)
        return QuoteResult(source, series=series)

    def metrics(self, company_id: str) -> QuoteResult:
        """Indicators from a separate source (네이버 증권), independent of the price provider."""
        if self.metrics_provider is None:
            return QuoteResult(None, code="not_connected", reason="지표 출처를 연결하지 않았어요.")
        provider = self.metrics_provider
        listing = Listing.of(company_id)
        if listing is None or not provider.supports(listing):
            return QuoteResult(None, code="unsupported_symbol", reason="이 종목은 지표 출처에서 제공하지 않아요.")
        try:
            source, metrics = self.cache.get_or_load(("naver", "metrics", listing), METRICS_TTL, lambda: provider.metrics(listing))
        except QuoteUnavailable as exc:
            return QuoteResult(None, code=exc.code, reason=exc.reason)
        return QuoteResult(source, metrics=metrics)


def build_market_data(
    mode: ProviderMode,
    *,
    toss_client_id: str | None,
    toss_client_secret: str | None,
    toss_base_url: str,
    yahoo_base_url: str,
    timeout: float,
    metrics_enabled: bool = False,
    naver_urls: tuple[str, str, str] = ("https://m.stock.naver.com", "https://api.stock.naver.com", "https://ac.stock.naver.com"),
    transport: httpx.BaseTransport | None = None,
) -> MarketData:
    from .quote_naver import NaverMetricsProvider
    from .quote_toss import TossProvider
    from .quote_yahoo import YahooProvider

    cache = TtlCache()
    toss = None
    if mode in ("auto", "toss") and toss_client_id and toss_client_secret:
        toss = TossProvider(
            toss_client_id, toss_client_secret, base_url=toss_base_url, timeout=timeout, transport=transport, cache=cache
        )
    yahoo = (
        YahooProvider(base_url=yahoo_base_url, timeout=timeout, transport=transport, cache=cache)
        if mode in ("auto", "yahoo")
        else None
    )
    domestic, world, ac = naver_urls
    naver = (
        NaverMetricsProvider(domestic_url=domestic, world_url=world, ac_url=ac, timeout=timeout, transport=transport, cache=cache)
        if metrics_enabled
        else None
    )
    return MarketData(mode, toss=toss, yahoo=yahoo, metrics=naver, cache=cache)
