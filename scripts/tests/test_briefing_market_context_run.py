"""Fixed request execution, source immutability and comparison-version boundaries."""

import contextlib
import io
import unittest
import test_briefing_market_enrichment as legacy

run = legacy.module("frozen_context_run_tests", legacy.HERE.parent / "briefing_market_context_run.py")
fixtures = legacy.module("frozen_context_run_fixtures", legacy.HERE / "test_briefing_market_context.py")


class FrozenMarketRunTest(unittest.TestCase):
    def setUp(self):
        self.fixture = legacy.EnrichmentTests(); self.fixture.setUp()
        self.fixture.run_enrichment()
        self.inputs, self.output = self.fixture.root / "inputs", self.fixture.root / "actual-run"
        f = self.fixture.fixture
        args = run.preview.parser().parse_args(["--market-bundle", str(self.fixture.output / "bundle-v2.json"),
            "--sources", str(f.sources), "--clocks", str(f.clocks), "--user-inbox-ref", "inbox/authored-preparation.md",
            "--output", str(self.inputs), "--write-inputs"])
        run.preview.run(args)
        self.args = run.parser().parse_args(["--inputs", str(self.inputs),
            "--market-bundle", str(self.fixture.output / "bundle-v2.json"), "--sources", str(f.sources), "--clocks", str(f.clocks),
            "--output", str(self.output), "--user-inbox-ref", "inbox/authored-execution.md"])

    def tearDown(self):
        self.fixture.tearDown()

    def execute(self, transport=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return run.run(self.args, transport or fixtures.ContextTransport())

    def test_offline_execution_does_not_create_output_or_call_provider(self):
        transport = fixtures.ContextTransport(); result = self.execute(transport)
        self.assertEqual("OFFLINE", result["status"])
        self.assertFalse(self.output.exists()); self.assertEqual([], transport.requests)

    def test_execution_uses_exact_frozen_request_and_keeps_authorization_separate(self):
        self.args.execute_authorized_generation = True
        transport = fixtures.ContextTransport(); result = self.execute(transport)
        self.assertEqual(1, result["summaryPass"])
        manifest = run.base.strict_load((self.inputs / "preview.json").read_bytes())
        expected = (self.inputs / (manifest["rounds"][0]["requestSha256"] + ".request.json")).read_bytes()
        self.assertEqual(expected, transport.requests[0])
        bundle = run.base.strict_load((self.output / "bundle-v2.json").read_bytes())
        self.assertEqual("inbox/authored-execution.md", bundle["marketEnrichment"]["executionAuthorizationRef"])
        self.assertEqual("inbox/authored-preparation.md", bundle["marketEnrichment"]["userInboxRef"])
        self.assertEqual(0, result["newHttpCalls"])

    def test_repeat_makes_no_new_provider_calls_and_keeps_output_unchanged(self):
        self.args.execute_authorized_generation = True; self.execute()
        before = (self.output / "bundle-v2.json").read_bytes(); transport = fixtures.ContextTransport()
        self.assertEqual(0, self.execute(transport)["newPaidCalls"])
        self.assertEqual([], transport.requests)
        self.assertEqual(before, (self.output / "bundle-v2.json").read_bytes())

    def test_changed_input_fails_before_calls_or_output(self):
        self.args.execute_authorized_generation = True
        next(self.inputs.glob("*.request.json")).write_bytes(b"{}")
        transport = fixtures.ContextTransport()
        with self.assertRaisesRegex(ValueError, "frozen_request_digest"):
            self.execute(transport)
        self.assertEqual([], transport.requests); self.assertFalse(self.output.exists())

    def test_frozen_prior_version_is_not_replaced_by_new_summary(self):
        self.fixture.fixture.output = self.fixture.root / "baseline-three"
        self.fixture.prepare_baseline(3)
        self.fixture.output = self.fixture.root / "market-three"; self.fixture.run_enrichment()
        self.args.market_bundle = str(self.fixture.output / "bundle-v2.json")
        self.inputs = self.fixture.root / "inputs-three"; self.args.inputs = str(self.inputs)
        p = run.preview.parser().parse_args(["--market-bundle", self.args.market_bundle, "--sources", self.args.sources,
            "--clocks", self.args.clocks, "--user-inbox-ref", "inbox/authored-preparation.md",
            "--output", str(self.inputs), "--write-inputs"])
        run.preview.run(p); self.args.execute_authorized_generation = True; self.execute()
        old = run.base.strict_load((self.fixture.output / "bundle-v2.json").read_bytes())["marketEnrichment"]["rounds"]
        new = run.base.strict_load((self.output / "bundle-v2.json").read_bytes())["marketEnrichment"]["rounds"]
        self.assertEqual(old[0]["summaryResult"], new[1]["marketContext"]["previousPublication"]["summary"])
        self.assertNotEqual(new[0]["summaryResult"], new[1]["marketContext"]["previousPublication"]["summary"])
