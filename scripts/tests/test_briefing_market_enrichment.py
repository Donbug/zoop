"""Offline baseline-preserving enrichment integration, with authored paid receipts."""

from datetime import timedelta
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

legacy = module("enrichment_legacy_fixtures", HERE / "test_briefing_round_simulation.py")
fixtures = module("enrichment_market_fixtures", HERE / "test_briefing_market_data.py")
enrichment = module("market_enrichment_tests", HERE.parent / "briefing_market_enrichment.py")
base = enrichment.base


class AuthoredSummaryTransport:
    def __init__(self, unknown=False):
        self.calls = []
        self.unknown = unknown

    def __call__(self, raw):
        self.calls.append(raw)
        if self.unknown:
            raise OSError("authored unknown transport outcome")
        request = base.strict_load(raw)
        data = base.strict_load(request["input"])
        stage = request["text"]["format"]["name"]
        if stage == "market_summary_generation":
            indicator = next(item for item in data["marketSnapshot"]["marketVariables"]["indicators"] if item["id"] == "kospi")
            result = {"claims": [
                {"text": "시험 기업이 새 계약 계획을 발표했습니다.", "evidenceIds": [data["allowedEvidenceIds"][0]], "indicatorIds": []},
                {"text": "제공된 KOSPI 일별 종가는 " + str(indicator["value"]) + "pt입니다.", "evidenceIds": [], "indicatorIds": ["kospi"]}]}
        else:
            result = {"checks": {claim["claimId"]: {"targetId": claim["claimId"], "verdict": "SUPPORTED",
                "noUnsupportedNumbers": True, "noUnsupportedCausality": True, "temporalAppropriate": True, "noInvestmentAdvice": True,
                "reason": "직접 작성한 시험 뉴스·지표 정합성 결과"} for claim in data["draft"]["claims"]}}
        return 200, base.canonical({"id": "authored-" + base.digest(raw)[:16], "status": "completed",
            "usage": {"input_tokens": 100, "output_tokens": 40},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": base.canonical(result).decode()}]}]})


class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixture = legacy.RoundSimulationTest()
        self.fixture.setUp()
        self.fixture.output = self.root / "baseline"
        self.prepare_baseline(1)
        self.output = self.root / "enriched"

    def tearDown(self):
        self.fixture.tearDown()
        self.temp.cleanup()

    def prepare_baseline(self, count):
        rows = []
        for index, spec in enumerate(legacy.sim.windows()[:count]):
            stamp = legacy.sim.aware(spec["window"]["to"]) - timedelta(minutes=10)
            rows.append(legacy.source("source-" + str(index), stamp.isoformat()))
        self.fixture.prepare(rows)
        legacy.sim.run(self.fixture.args(True), legacy.AuthoredTransport())
        self.baseline = self.fixture.output
        self.baseline_bytes = (self.baseline / "bundle-v2.json").read_bytes()

    def args(self, execute=True):
        values = ["--baseline", str(self.baseline), "--output", str(self.output),
                  "--sources", str(self.fixture.sources), "--clocks", str(self.fixture.clocks),
                  "--user-inbox-ref", "inbox/authored-market-enrichment.md", "--workers", "1"]
        if execute:
            values.append("--execute-authorized-enrichment")
        return enrichment.parser().parse_args(values)

    def run_enrichment(self, market_transport=None, ai_transport=None, args=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return enrichment.run(args or self.args(), market_transport or fixtures.AuthoredMarketTransport(),
                                  ai_transport or AuthoredSummaryTransport())

    def test_offline_plan_no_output_no_http_no_ai(self):
        market, ai = fixtures.AuthoredMarketTransport(), AuthoredSummaryTransport()
        result = self.run_enrichment(market, ai, self.args(False))
        self.assertEqual("OFFLINE", result["status"])
        self.assertEqual(0, result["newHttpCalls"])
        self.assertEqual([], market.calls)
        self.assertEqual([], ai.calls)
        self.assertFalse(self.output.exists())

    def test_one_selected_round_enriched_and_baseline_is_byte_unchanged(self):
        before = {str(p.relative_to(self.baseline)): base.digest(p.read_bytes()) for p in self.baseline.rglob("*") if p.is_file()}
        result = self.run_enrichment()
        final = base.strict_load((self.output / "bundle-v2.json").read_bytes())
        self.assertEqual(1, result["rounds"])
        self.assertEqual(1, result["summaryPass"])
        self.assertEqual(3, result["newHttpCalls"])
        self.assertEqual(2, result["newPaidCalls"])
        self.assertEqual(14, len(final["rounds"]))
        self.assertEqual(base.strict_load(self.baseline_bytes), {k: v for k, v in final.items() if k != "marketEnrichment"})
        after = {str(p.relative_to(self.baseline)): base.digest(p.read_bytes()) for p in self.baseline.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        component = final["marketEnrichment"]["rounds"][0]
        self.assertEqual("PASS", component["summaryResult"]["verification"]["status"])
        self.assertEqual(base.digest(base.canonical(component["context"])), component["contextSha256"])
        self.assertEqual(final["rounds"][0]["resultSha256"], component["newsResultSha256"])

    def test_all_selected_scope_can_enrich_eleven_rounds_without_touching_three_empty(self):
        self.fixture.output = self.root / "baseline-eleven"
        self.prepare_baseline(11)
        result = self.run_enrichment()
        final = base.strict_load((self.output / "bundle-v2.json").read_bytes())
        self.assertEqual(11, result["rounds"])
        self.assertEqual(11, result["summaryPass"])
        self.assertEqual(22, result["newPaidCalls"])
        self.assertEqual(11, len(final["marketEnrichment"]["rounds"]))
        selected_ids = {r["roundId"] for r in final["rounds"] if r["selectionStatus"] == "SELECTED"}
        self.assertEqual(selected_ids, {r["roundId"] for r in final["marketEnrichment"]["rounds"]})
        self.assertEqual(self.baseline_bytes, (self.baseline / "bundle-v2.json").read_bytes())

    def test_every_snapshot_summary_and_paid_receipt_is_content_bound(self):
        self.run_enrichment()
        final = base.strict_load((self.output / "bundle-v2.json").read_bytes())
        for component in final["marketEnrichment"]["rounds"]:
            for key, directory, field in (("marketSnapshotSha256", "snapshots", "marketSnapshot"),
                                          ("summaryResultSha256", "summaries", "summaryResult")):
                raw = (self.output / "market" / directory / (component[key] + ".json")).read_bytes()
                self.assertEqual(component[key], base.digest(raw))
                self.assertEqual(component[field], base.strict_load(raw))
            self.assertEqual(2, len(component["receipts"]))
            for receipt in component["receipts"]:
                digest = receipt["requestDigest"]
                raw_request = (self.output / "calls" / (digest + ".request.json")).read_bytes()
                raw_response = (self.output / "calls" / (digest + ".response.json")).read_bytes()
                self.assertEqual(digest, base.digest(raw_request))
                self.assertEqual(receipt["responseSha256"], base.digest(raw_response))
                paid_input = base.strict_load(base.strict_load(raw_request)["input"])
                self.assertEqual(component["contextSha256"], paid_input["contextSha256"])
                self.assertEqual(component["marketSnapshot"], paid_input["marketSnapshot"])
                self.assertEqual(component["newsResultSha256"], paid_input["context"]["newsResultSha256"])
        self.assertEqual(2, len(final["marketEnrichment"]["receipts"]))
        self.assertEqual(4, len(final["receipts"]))  # original news receipts preserved

    def test_identical_repeat_run_makes_zero_http_or_ai_calls(self):
        self.run_enrichment()
        final_before = (self.output / "bundle-v2.json").read_bytes()
        market, ai = fixtures.AuthoredMarketTransport(), AuthoredSummaryTransport()
        result = self.run_enrichment(market, ai)
        self.assertEqual(0, result["newHttpCalls"])
        self.assertEqual(0, result["newPaidCalls"])
        self.assertEqual([], market.calls)
        self.assertEqual([], ai.calls)
        self.assertEqual(final_before, (self.output / "bundle-v2.json").read_bytes())

    def test_cannot_overwrite_baseline_or_place_output_inside_baseline(self):
        for path in (self.baseline, self.baseline / "nested-output"):
            args = self.args()
            args.output = str(path)
            with self.subTest(path=path):
                with self.assertRaisesRegex(base.ReplayError, "requires_separate_output"):
                    self.run_enrichment(args=args)
        self.assertEqual(self.baseline_bytes, (self.baseline / "bundle-v2.json").read_bytes())

    def test_insufficient_budget_fails_before_http_or_ai(self):
        args = self.args()
        args.max_calls = 1
        market, ai = fixtures.AuthoredMarketTransport(), AuthoredSummaryTransport()
        with self.assertRaisesRegex(base.ReplayError, "authorization_or_budget_required"):
            self.run_enrichment(market, ai, args)
        self.assertEqual([], market.calls)
        self.assertEqual([], ai.calls)
        self.assertFalse(self.output.exists())

    def test_unknown_ai_response_does_not_retry_or_publish_bundle(self):
        ai = AuthoredSummaryTransport(unknown=True)
        with self.assertRaisesRegex(enrichment.summary.base.ReplayError, "transport_unknown_usage_no_automatic_retry"):
            self.run_enrichment(ai_transport=ai)
        self.assertEqual(1, len(ai.calls))
        self.assertFalse((self.output / "bundle-v2.json").exists())
        self.assertFalse((self.output / ".enrichment.lock").exists())
        self.assertTrue(list(self.output.glob("accounting-*.json")))
        self.assertEqual(self.baseline_bytes, (self.baseline / "bundle-v2.json").read_bytes())

    def test_cached_summary_or_raw_artifact_tamper_fails_without_new_requests(self):
        self.run_enrichment()
        final = base.strict_load((self.output / "bundle-v2.json").read_bytes())
        sha = final["marketEnrichment"]["rounds"][0]["summaryResultSha256"]
        (self.output / "market/summaries" / (sha + ".json")).write_bytes(b"{}")
        market, ai = fixtures.AuthoredMarketTransport(), AuthoredSummaryTransport()
        with self.assertRaisesRegex(base.ReplayError, "cached_artifact_changed"):
            self.run_enrichment(market, ai)
        self.assertEqual([], market.calls)
        self.assertEqual([], ai.calls)

    def test_source_clock_or_news_hash_mismatch_fails_before_enrichment(self):
        self.fixture.clocks.write_bytes(b"{}")
        with self.assertRaisesRegex(base.ReplayError, "source_or_clock_mismatch"):
            self.run_enrichment()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
