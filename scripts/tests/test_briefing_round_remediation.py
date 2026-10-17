"""Authored baseline and bounded remediation; never uses external sources or a key."""

import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

fixtures = module("remediation_fixtures", HERE / "test_briefing_quality_v2.py")
rem = module("remediation_subject", HERE.parent / "briefing_round_remediation.py")
legacy = fixtures.legacy


class RemediationTest(unittest.TestCase):
    setUp = legacy.RoundSimulationTest.setUp
    tearDown = legacy.RoundSimulationTest.tearDown
    prepare = legacy.RoundSimulationTest.prepare

    def baseline(self):
        self.prepare([legacy.source("first", "2026-10-02T09:00:00+09:00")])
        legacy.sim.run(legacy.RoundSimulationTest.args(self, True), legacy.AuthoredTransport())

    def args(self, execute=True):
        values = ["--baseline", str(self.output), "--output", str(self.root / "quality-output"),
                  "--sources", str(self.sources), "--clocks", str(self.clocks),
                  "--user-inbox-ref", "inbox/authored-quality.md", "--round", "2026-10-02-morning"]
        if execute:
            values.append("--execute-authorized-recheck")
        return rem.parser().parse_args(values)

    def test_offline_never_constructs_a_transport_or_sends(self):
        self.baseline()
        transport = fixtures.V2Transport()
        result = rem.run(self.args(False), transport)
        self.assertEqual("OFFLINE", result["status"])
        self.assertEqual([], transport.requests)

    def test_same_source_paid_assessment_reuse_new_selection_generation_and_zero_call_resume(self):
        self.baseline()
        before = (self.output / "bundle-v2.json").read_bytes()
        transport = fixtures.V2Transport()
        first = rem.run(self.args(), transport)
        self.assertEqual(1, first["pass"])
        self.assertEqual(3, first["newPaidCalls"])
        self.assertFalse(first["published"])
        path = self.root / "quality-output/recheck-bundle.json"
        saved = path.read_bytes()
        second = rem.run(self.args(), transport)
        self.assertEqual(0, second["newPaidCalls"])
        self.assertEqual(saved, path.read_bytes())
        self.assertEqual(before, (self.output / "bundle-v2.json").read_bytes())
        self.assertFalse(any(b'round_simulation_importance' in r for r in transport.requests))

    def test_mutated_cached_recheck_fails_before_a_new_paid_request(self):
        self.baseline()
        rem.run(self.args(), fixtures.V2Transport())
        path = self.root / "quality-output/2026-10-02-morning/recheck.json"
        path.write_bytes(path.read_bytes() + b" ")
        transport = fixtures.V2Transport()
        with self.assertRaisesRegex(rem.base.ReplayError, "cached_recheck_digest_mismatch"):
            rem.run(self.args(), transport)
        self.assertEqual([], transport.requests)

    def test_mutated_baseline_request_cannot_reuse_assessment(self):
        self.baseline()
        request = next(p for p in (self.output / "calls").glob("*.request.json")
                       if rem.base.strict_load(p.read_bytes())["text"]["format"]["name"] == "round_simulation_importance")
        request.write_bytes(request.read_bytes() + b" ")
        transport = fixtures.V2Transport()
        with self.assertRaisesRegex(rem.base.ReplayError, "cached_paid_evidence_digest_mismatch"):
            rem.run(self.args(), transport)
        self.assertEqual([], transport.requests)

    def test_overwrite_baseline_and_unknown_or_duplicate_cases_fail_closed(self):
        self.baseline()
        transport = fixtures.V2Transport()
        args = self.args(False)
        args.output = str(self.output)
        with self.assertRaisesRegex(rem.base.ReplayError, "output_must_be_separate"):
            rem.run(args, transport)
        for names in [["missing"], ["2026-10-02-morning"] * 2]:
            args = self.args(False)
            args.round = names
            with self.assertRaises(rem.base.ReplayError):
                rem.run(args, transport)
        self.assertEqual([], transport.requests)


if __name__ == "__main__":
    unittest.main()
