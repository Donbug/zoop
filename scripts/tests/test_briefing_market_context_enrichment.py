"""Context integration and offline preview boundaries; all external transports authored."""

import unittest

import test_briefing_market_enrichment as legacy

context_fixtures = legacy.module("context_enrichment_fixtures", legacy.HERE / "test_briefing_market_context.py")
preview = legacy.module("context_preview_tests", legacy.HERE.parent / "briefing_market_context_preview.py")


class ContextEnrichmentTest(unittest.TestCase):
    def setUp(self):
        self.fixture = legacy.EnrichmentTests(); self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def run_context(self):
        args = self.fixture.args(); args.include_market_context = True
        return self.fixture.run_enrichment(args=args, ai_transport=context_fixtures.ContextTransport())

    def test_cached_frozen_input_tamper_is_rejected_without_calls(self):
        self.run_context()
        path = next((self.fixture.output / "market/frozen-inputs").glob("*.json"))
        path.write_bytes(b"{}")
        with self.assertRaisesRegex(legacy.base.ReplayError, "cached_frozen_input_changed"):
            self.run_context()

    def test_out_of_order_rounds_fail_before_output_or_calls(self):
        base = preview.base
        bundle = base.strict_load(self.fixture.baseline_bytes)
        bundle["rounds"] = list(reversed(bundle["rounds"]))
        (self.fixture.baseline / "bundle-v2.json").write_bytes(base.canonical(bundle))
        with self.assertRaisesRegex(legacy.base.ReplayError, "chronological_rounds_required"):
            self.run_context()
        self.assertFalse(self.fixture.output.exists())

    def test_real_input_preparation_is_offline_idempotent_and_does_not_mutate_prior_outputs(self):
        self.fixture.run_enrichment()
        baseline = self.fixture.output
        before = {str(p.relative_to(baseline)): preview.base.digest(p.read_bytes()) for p in baseline.rglob("*") if p.is_file()}
        output = self.fixture.root / "preview"
        args = preview.parser().parse_args(["--market-bundle", str(baseline / "bundle-v2.json"),
            "--sources", str(self.fixture.fixture.sources), "--clocks", str(self.fixture.fixture.clocks),
            "--user-inbox-ref", "inbox/authored-preview.md", "--output", str(output)])
        plan = preview.run(args)
        self.assertFalse(output.exists())
        self.assertEqual(0, plan["realPaidCalls"])
        self.assertEqual(0, plan["realHttpCalls"])
        self.assertEqual(0, plan["generatedMarketSummaries"])
        args.write_inputs = True
        self.assertEqual(plan, preview.run(args))
        self.assertEqual(plan, preview.run(args))
        self.assertEqual(1, len(list(output.glob("*.request.json"))))
        after = {str(p.relative_to(baseline)): preview.base.digest(p.read_bytes()) for p in baseline.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
