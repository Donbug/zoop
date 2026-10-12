"""Company indicators from 네이버 증권's public JSON (no key, unofficial) — requirement 39 within what the source gives.

Endpoints (observed 2026-10-01; undocumented, may change or block without notice):

- KRX: ``GET {domestic}/api/stock/{code}/integration`` -> ``totalInfos[{code, key, value, valueDesc?}]``
  and ``GET {domestic}/api/stock/{code}/basic`` -> ``localTradedAt`` (source time).
- Others: ``GET {ac}/ac?q={ticker}&target=stock`` resolves the Naver ``reutersCode`` (``NVDA.O``, ``PINS.K``,
  ``HPE``, ``6702.T``; the suffix is not derivable from the exchange alone), then
  ``GET {world}/stock/{reutersCode}/basic`` -> ``stockItemTotalInfos[{code, key, value, keyDesc?}]``, ``localTradedAt``.

Values are passed through as the source formats them (``1,609조 1,882억``, ``12.35배``, ``0.61%``); nothing is
computed, converted or estimated. ``basis`` is the source's own reference period (``2026.06.``). Price-like rows
(전일·시가·고가·저가·거래량·52주) are left to the quote provider, and consensus estimates (추정 PER/EPS) are dropped.
Swap point: replace this module and ``MarketData.metrics`` keeps its contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from .market_data import (
    ACCESS_DENIED,
    KST,
    REFERENCE_TTL,
    TEMPORARY,
    US_EXCHANGES,
    _KRX_CODE,
    _TSE_CODE,
    _US_TICKER,
    Listing,
    QuoteUnavailable,
    Source,
    TtlCache,
    json_body,
    request_json,
)

DELAY_NOTE = "비공식 공개 자료예요. 지연되거나 바뀔 수 있어요."
NOT_LISTED = "네이버 증권에서 이 종목의 지표를 찾지 못했어요."
FORMAT_CHANGED = "지표 출처의 응답 형식을 읽지 못했어요."
NO_VALUES = "네이버 증권에 이 종목의 지표 값이 없어요."

# Rows kept, in display order, with our label. Anything else the source sends is ignored.
LABELS: dict[str, str] = {
    "marketValue": "시가총액",
    "per": "PER",
    "eps": "EPS",
    "pbr": "PBR",
    "bps": "BPS",
    "dividendYieldRatio": "배당수익률",
    "dividend": "주당배당금",
    "foreignRate": "외국인 소진율",
}
_AC_TYPE = {"NASDAQ": "NASDAQ", "NYSE": "NYSE", "AMEX": "AMEX", "TSE": "TOKYO"}


@dataclass(frozen=True)
class Metric:
    code: str
    label: str
    value: str
    basis: str | None


@dataclass(frozen=True)
class Metrics:
    as_of: datetime | None
    items: tuple[Metric, ...]


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)


def parse_rows(rows: Any, basis_key: str) -> tuple[Metric, ...]:
    """The usable rows in display order. A row that is N/A, empty or of the wrong type is simply absent from the
    result -- never 0 and never a reason to drop the others.

    ``no_data`` only when the adapter recognised the expected indicators and the source explicitly left them without a
    value, or sent a valid empty list. Rows of which none is an indicator this adapter knows (renamed or unknown codes
    only) mean it cannot interpret the structure the source advertises: ``format_changed``. Unknown extras next to
    known rows are ignored."""
    if not isinstance(rows, list):
        raise QuoteUnavailable("format_changed", FORMAT_CHANGED)
    by_code = {r["code"]: r for r in rows if isinstance(r, dict) and isinstance(r.get("code"), str)}
    if rows and not any(code in by_code for code in LABELS):
        raise QuoteUnavailable("format_changed", FORMAT_CHANGED)
    items: list[Metric] = []
    for code, label in LABELS.items():
        row = by_code.get(code)
        value = row.get("value") if row else None
        if not isinstance(value, str) or not value.strip() or value.strip().upper() in {"N/A", "-"}:
            continue
        basis = row.get(basis_key)
        items.append(Metric(code, label, value.strip(), basis.strip() if isinstance(basis, str) and basis.strip() else None))
    if not items:
        raise QuoteUnavailable("no_data", NO_VALUES)
    return tuple(items)


class NaverMetricsProvider:
    id = "naver"

    def __init__(
        self,
        *,
        domestic_url: str,
        world_url: str,
        ac_url: str,
        timeout: float,
        cache: TtlCache,
        transport: httpx.BaseTransport | None = None,
    ):
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        self._domestic = httpx.Client(base_url=domestic_url, timeout=timeout, transport=transport, headers=headers)
        self._world = httpx.Client(base_url=world_url, timeout=timeout, transport=transport, headers=headers)
        self._ac = httpx.Client(base_url=ac_url, timeout=timeout, transport=transport, headers=headers)
        self._cache = cache

    def supports(self, listing: Listing) -> bool:
        if listing.exchange == "KRX":
            return bool(_KRX_CODE.match(listing.code))
        if listing.exchange in US_EXCHANGES:
            return bool(_US_TICKER.match(listing.code))
        return listing.exchange == "TSE" and bool(_TSE_CODE.match(listing.code))

    def _get(self, client: httpx.Client, path: str, params: dict[str, str] | None = None) -> Any:
        response = request_json(client, "GET", path, params=params)
        if response.status_code in (400, 404, 409):
            raise QuoteUnavailable("unsupported_symbol", NOT_LISTED)
        if response.status_code in (401, 403):
            raise QuoteUnavailable("auth_failed", ACCESS_DENIED)
        if not response.is_success:
            raise QuoteUnavailable("temporary_failure", TEMPORARY)
        body = json_body(response)
        if not isinstance(body, dict):
            raise QuoteUnavailable("format_changed", FORMAT_CHANGED)
        return body

    def _reuters_code(self, listing: Listing) -> str:
        def load() -> str:
            body = self._get(self._ac, "/ac", {"q": listing.code, "target": "stock"})
            items = body.get("items")
            if not isinstance(items, list):
                raise QuoteUnavailable("format_changed", FORMAT_CHANGED)
            want = _AC_TYPE[listing.exchange] if listing.exchange in _AC_TYPE else None
            for item in items:
                if (
                    isinstance(item, dict)
                    and str(item.get("code", "")).upper() == listing.code
                    and item.get("typeCode") == want
                    and isinstance(item.get("reutersCode"), str)
                ):
                    return item["reutersCode"]
            raise QuoteUnavailable("unsupported_symbol", NOT_LISTED)

        return self._cache.get_or_load(("naver", "reuters", listing), REFERENCE_TTL, load)

    def _source(self, symbol: str, url: str) -> Source:
        return Source("naver", "네이버 증권", False, DELAY_NOTE, symbol, url)

    def metrics(self, listing: Listing) -> tuple[Source, Metrics]:
        if listing.exchange == "KRX":
            code = listing.code
            integration = self._get(self._domestic, f"/api/stock/{code}/integration")
            items = parse_rows(integration.get("totalInfos"), "valueDesc")
            basic = self._get(self._domestic, f"/api/stock/{code}/basic")
            source = self._source(code, f"https://m.stock.naver.com/domestic/stock/{code}/total")
            return source, Metrics(_time(basic.get("localTradedAt")), items)
        reuters = self._reuters_code(listing)
        basic = self._get(self._world, f"/stock/{reuters}/basic")
        # keyDesc is the reference period; valueDesc on overseas rows is a KRW conversion, which we do not show.
        items = parse_rows(basic.get("stockItemTotalInfos"), "keyDesc")
        source = self._source(reuters, f"https://m.stock.naver.com/worldstock/stock/{reuters}/total")
        return source, Metrics(_time(basic.get("localTradedAt")), items)
