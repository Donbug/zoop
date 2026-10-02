"""Mock profiles and holding valuation (FS039, FS054, FS062): market values and weights from prices read at one
calculation time, cash excluded, and 'cannot calculate' kept apart from 0."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from zoop_bff.app import create_app
from zoop_bff.config import Settings
from zoop_bff.market_data import Listing, MarketData, Quote, QuoteUnavailable, Source

from .conftest import DEMO, base_payload

MOCK_AS_OF = "2026-09-30T00:00:00+00:00"
PROFILES = [
    {
        "id": "p-main",
        "label": "모의 계좌 A",
        "accountId": "MOCK-A-01",
        "asOf": MOCK_AS_OF,
        "cash": {"amount": 1_000_000, "currency": "KRW"},
        "holdings": [
            {"companyId": "KRX:000010", "quantity": 10, "avgPrice": 90, "currency": "KRW"},
            {"companyId": "KRX:000020", "quantity": 30, "avgPrice": 120, "currency": "KRW"},
        ],
    },
    {"id": "p-empty", "label": "빈 계좌", "accountId": "MOCK-B-01", "holdings": []},
]


class FakeQuotes:
    """A quote source answering fixed prices; a code without a price is 'no data'."""

    id = "yahoo"

    def __init__(self, prices: dict[str, tuple[float, str]]):
        self.prices = prices

    def supports(self, listing: Listing) -> bool:
        return True

    def quote(self, listing: Listing) -> tuple[Source, Quote]:
        if listing.code not in self.prices:
            raise QuoteUnavailable("no_data", "시세가 없어요.")
        price, currency = self.prices[listing.code]
        source = Source("yahoo", "테스트 시세", False, None, listing.code, None)
        return source, Quote(currency=currency, price=price, as_of=datetime(2026, 10, 2, 6, 0, tzinfo=UTC))

    def series(self, listing, period):  # pragma: no cover - not used here
        raise QuoteUnavailable("no_data", "없음")


def _member(tmp_path: Path, prices: dict[str, tuple[float, str]], profiles: list[dict[str, Any]] = PROFILES) -> TestClient:
    payload = base_payload()
    payload["zoop"] = {**payload.get("zoop", {}), "mockPortfolios": profiles}
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    settings = Settings(snapshot_path=snapshot, company_catalog=None, state_dir=tmp_path / "state", briefing_scheduler=False)
    client = TestClient(create_app(settings, quotes=MarketData("yahoo", yahoo=FakeQuotes(prices))))
    assert client.post("/api/auth/login", json=DEMO).status_code == 200
    return client


def _connected(client: TestClient, profile: str = "p-main") -> dict[str, Any]:
    assert client.post("/api/portfolio/connections", json={"mockPortfolioId": profile}).status_code == 201
    return client.get("/api/portfolio").json()


def test_weights_are_market_value_shares_at_one_calculation_time_without_cash(tmp_path):
    portfolio = _connected(_member(tmp_path, {"000010": (100, "KRW"), "000020": (100, "KRW")}))
    holdings = {h["companyId"]: h for h in portfolio["holdings"]}
    # Quantity and average price are the mock values; the price is the quote, not the purchase price.
    assert (holdings["KRX:000010"]["quantity"], holdings["KRX:000010"]["avgPrice"]) == (10, 90)
    assert holdings["KRX:000010"]["marketValue"] == 1000 and holdings["KRX:000020"]["marketValue"] == 3000
    assert holdings["KRX:000010"]["weight"] == 0.25 and holdings["KRX:000020"]["weight"] == 0.75
    valuation = portfolio["valuation"]
    # Cash (1,000,000) is not in the denominator.
    assert valuation["totalMarketValue"] == 4000 and valuation["currency"] == "KRW" and valuation["weightStatus"] == "available"
    # The mock's as-of time and the calculation time are reported separately.
    assert portfolio["mockAsOf"] == MOCK_AS_OF
    assert valuation["calculatedAt"] != MOCK_AS_OF and valuation["calculatedAt"] > MOCK_AS_OF


@pytest.mark.parametrize(
    ("prices", "code", "total"),
    [
        ({"000010": (100, "KRW")}, "missing_price", None),
        ({"000010": (0, "KRW"), "000020": (0, "KRW")}, "zero_total", 0),
        ({"000010": (100, "KRW"), "000020": (5, "USD")}, "mixed_currency", None),
    ],
)
def test_weights_that_cannot_be_calculated_are_null_never_zero(tmp_path, prices, code, total):
    portfolio = _connected(_member(tmp_path, prices))
    valuation = portfolio["valuation"]
    assert valuation["weightStatus"] == "unavailable" and valuation["weightUnavailableCode"] == code
    assert valuation["weightUnavailableReason"] and valuation["totalMarketValue"] == total
    assert all(h["weight"] is None for h in portfolio["holdings"])
    by_id = {h["companyId"]: h for h in portfolio["holdings"]}
    if code == "missing_price":
        # The priced holding keeps its value; the unpriced one has none (not 0).
        assert by_id["KRX:000010"]["marketValue"] == 1000
        assert by_id["KRX:000020"]["marketValue"] is None and by_id["KRX:000020"]["quote"]["status"] == "unavailable"


def test_mock_profile_returns_its_own_account_cash_and_holdings_and_unknown_is_not_an_account(tmp_path):
    client = _member(tmp_path, {})
    listed = {p["id"]: p for p in client.get("/api/portfolio/mock-portfolios").json()["items"]}
    assert listed["p-main"]["accountId"] == "MOCK-A-01" and listed["p-empty"]["holdingsCount"] == 0

    main = client.get("/api/portfolio/mock-portfolios/p-main").json()
    assert main["accountId"] == "MOCK-A-01" and main["cash"] == {"amount": 1_000_000, "currency": "KRW"}
    assert [(h["companyId"], h["quantity"], h["avgPrice"]) for h in main["holdings"]] == [("KRX:000010", 10, 90), ("KRX:000020", 30, 120)]
    # A profile with no holdings is a normal account; cash it does not provide is null, not 0.
    empty = client.get("/api/portfolio/mock-portfolios/p-empty")
    assert empty.status_code == 200 and empty.json()["holdings"] == [] and empty.json()["cash"] is None

    for response in (
        client.get("/api/portfolio/mock-portfolios/nope"),
        client.post("/api/portfolio/connections", json={"mockPortfolioId": "nope"}),
    ):
        assert response.status_code == 404 and response.json()["error"]["code"] == "mock_portfolio_not_found"
    assert client.get("/api/portfolio").json()["connected"] is False

    # The connected account reports the same account id and cash as the profile.
    portfolio = _connected(client)
    assert portfolio["connection"]["accountId"] == "MOCK-A-01" and portfolio["connection"]["cash"] == main["cash"]
    assert client.delete(f"/api/portfolio/connections/{portfolio['connection']['id']}").status_code == 204
    assert client.get("/api/portfolio").json()["connected"] is False
