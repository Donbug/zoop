"""Authored Yahoo/Naver histories; no provider/network access."""

from datetime import datetime
from decimal import Decimal
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("market_data_tests", Path(__file__).resolve().parents[1] / "briefing_market_data.py")
market = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(market)
base = market.base


def index_bytes(symbol="^KS11", values=None, timezone="Asia/Seoul"):
    values = values or [("2026-10-01", "2500.005"), ("2026-10-02", "2510.015"), ("2026-10-05", "2520.025")]
    stamps = [int(datetime.fromisoformat(day + "T09:00:00+09:00").timestamp()) for day, value in values]
    return base.canonical({"chart": {"error": None, "result": [{"meta": {"symbol": symbol, "exchangeTimezoneName": timezone},
        "timestamp": stamps, "indicators": {"quote": [{"close": [value for day, value in values]}]}}]}})


def fx_bytes(values=None):
    return base.canonical([{"localTradedAt": day, "closePrice": value} for day, value in
                           (values or [("2026-10-01", "1,300.005"), ("2026-10-02", "1,310.015"), ("2026-10-05", "1,320.025")])])


class AuthoredMarketTransport:
    def __init__(self, status=200):
        self.calls = []
        self.status = status

    def __call__(self, url):
        self.calls.append(url)
        if "FX_USDKRW" in url:
            raw = fx_bytes()
        elif "%5EKS11" in url:
            raw = index_bytes()
        else:
            raw = index_bytes("^KQ11")
        return self.status, raw


def round_(date="2026-10-02", edition="morning"):
    return {"date": date, "edition": edition, "window": {"to": date + ("T09:20:00+09:00" if edition == "morning" else "T17:30:00+09:00")}}


class MarketDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "output"
        self.transport = AuthoredMarketTransport()
        self.receipts, self.calls = market.fetch_receipts(self.root, self.transport)

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self, definition=None):
        return market.snapshot(definition or round_(), self.receipts, self.root)

    def test_am_excludes_same_day_daily_close_and_pm_includes_1530_close(self):
        morning, evening = self.snapshot(), self.snapshot(round_(edition="evening"))
        am = {row["id"]: row for row in morning["marketVariables"]["indicators"]}
        pm = {row["id"]: row for row in evening["marketVariables"]["indicators"]}
        for key in ("kospi", "kosdaq"):
            self.assertEqual("2026-10-01", am[key]["observedDate"])
            self.assertEqual(2500.01, am[key]["value"])
            self.assertEqual("delayed", am[key]["status"])
            self.assertEqual("2026-10-02", pm[key]["observedDate"])
            self.assertEqual(2510.02, pm[key]["value"])
            self.assertEqual("ok", pm[key]["status"])
            self.assertIsNone(pm[key]["observedAt"])
        for binding in evening["indicatorBindings"]:
            if binding["id"] != "usdkrw":
                self.assertEqual("2026-10-02T15:30:00+09:00", binding["availabilityUpperBound"])

    def test_bank_daily_reference_has_its_own_kind_instead_of_a_market_close(self):
        indicators = {x["id"]: x for x in self.snapshot()["marketVariables"]["indicators"]}
        self.assertEqual("reference", indicators["usdkrw"]["valueKind"])
        self.assertEqual("close", indicators["kospi"]["valueKind"])
        self.assertIsNone(indicators["usdkrw"]["observedAt"])

    def test_provider_no_bar_day_carries_latest_without_inventing_calendar(self):
        result = self.snapshot(round_("2026-10-04", "evening"))
        for row in result["marketVariables"]["indicators"]:
            self.assertEqual("2026-10-02", row["observedDate"])
            self.assertEqual("delayed", row["status"])
        self.assertFalse(result["sessionRule"]["exactSessionCalendarVerified"])
        self.assertTrue(any("특별 세션" in value for value in result["limitations"]))

    def test_date_only_fx_excludes_same_calendar_day_even_at_evening(self):
        for edition in ("morning", "evening"):
            result = self.snapshot(round_(edition=edition))
            fx = result["marketVariables"]["indicators"][2]
            self.assertEqual("2026-10-01", fx["observedDate"])
            self.assertEqual(1300.01, fx["value"])
            self.assertEqual("delayed", fx["status"])
            self.assertIn("외환시장 종가", fx["source"]["delayNote"])
            binding = next(b for b in result["indicatorBindings"] if b["id"] == "usdkrw")
            self.assertEqual("2026-10-02T00:00:00+09:00", binding["availabilityUpperBound"])
            self.assertEqual("day", binding["precision"])

    def test_half_up_two_decimals_and_change_from_stored_values(self):
        self.assertEqual(Decimal("2500.01"), market.number("2,500.005"))
        self.assertEqual(Decimal("1.01"), market.number("1.005"))
        row = self.snapshot(round_(edition="evening"))["marketVariables"]["indicators"][0]
        self.assertEqual(2500.01, row["baseline"]["value"])
        self.assertEqual(2510.02, row["value"])
        self.assertEqual(10.01, row["change"])
        self.assertAlmostEqual(10.01 / 2500.01, row["changeRate"])

    def test_missing_before_first_observation_has_no_zero_or_baseline(self):
        result = self.snapshot(round_("2026-09-30", "morning"))
        self.assertEqual([], result["indicatorBindings"])
        for row in result["marketVariables"]["indicators"]:
            self.assertEqual("unavailable", row["status"])
            for field in ("value", "baseline", "change", "changeRate", "observedDate", "observedAt"):
                self.assertIsNone(row[field])

    def test_fetch_failure_is_failed_not_zero_and_receipt_kept(self):
        other = Path(self.temp.name) / "failed-output"
        receipts, count = market.fetch_receipts(other, AuthoredMarketTransport(status=503))
        result = market.snapshot(round_(), receipts, other)
        self.assertEqual(3, count)
        self.assertTrue(all(row["status"] == "failed" and row["value"] is None for row in result["marketVariables"]["indicators"]))
        self.assertTrue(all(r["httpStatus"] == 503 for r in result["rawRefs"]))

    def test_wrong_symbol_or_timezone_and_duplicate_dates_rejected(self):
        for raw, error in ((index_bytes("^WRONG"), "symbol_or_timezone"),
                           (index_bytes(timezone="America/New_York"), "symbol_or_timezone"),
                           (index_bytes(values=[("2026-10-01", 2500), ("2026-10-01", 2501)]), "duplicate_market_date"),
                           (fx_bytes(values=[("2026-10-01", 1300), ("2026-10-01", 1301)]), "duplicate_market_date")):
            with self.subTest(error=error):
                with self.assertRaisesRegex(base.ReplayError, error):
                    market.daily_rows("usdkrw" if raw.startswith(b"[") else "kospi", raw)

    def test_naive_or_wrong_round_cutoff_rejected(self):
        for definition in (round_(edition="noon"), {**round_(), "window": {"to": "2026-10-02T09:20:00"}},
                           {**round_(), "window": {"to": "2026-10-02T09:21:00+09:00"}}):
            with self.subTest(definition=definition):
                with self.assertRaises(base.ReplayError):
                    self.snapshot(definition)

    def test_second_fetch_reuses_all_frozen_raws_with_zero_http(self):
        transport = AuthoredMarketTransport()
        receipts, calls = market.fetch_receipts(self.root, transport)
        self.assertEqual(0, calls)
        self.assertEqual([], transport.calls)
        self.assertEqual(self.receipts, receipts)
        self.assertEqual(3, self.calls)

    def test_cached_raw_hash_tamper_fails_before_refetch(self):
        receipt = self.receipts["kospi"]
        (self.root / "market/raw" / (receipt["sha256"] + ".bin")).write_bytes(b"tampered authored bytes")
        transport = AuthoredMarketTransport()
        with self.assertRaisesRegex(base.ReplayError, "cached_raw_binding_mismatch"):
            market.fetch_receipts(self.root, transport)
        self.assertEqual([], transport.calls)

    def test_fx_clock_must_be_date_only_and_numbers_must_be_finite_positive(self):
        with self.assertRaises(ValueError):
            market.daily_rows("usdkrw", base.canonical([{"localTradedAt": "2026-10-01T23:00:00+09:00", "closePrice": "1300"}]))
        for value in (None, True, 0, -1, "NaN", "Infinity"):
            with self.subTest(value=value):
                with self.assertRaises(base.ReplayError):
                    market.number(value)


if __name__ == "__main__":
    unittest.main()
