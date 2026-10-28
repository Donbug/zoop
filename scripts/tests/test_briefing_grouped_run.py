"""Fourteen-round runner integration with authored issues and provider replies."""
import contextlib
from datetime import timedelta
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


run = module("grouped_run_tests_target", HERE / "briefing_grouped_run.py")
fixtures = module("grouped_run_issue_fixture", Path(__file__).with_name("test_briefing_grouped_rounds.py"))
clocks = module("grouped_run_clock_fixture", Path(__file__).with_name("test_briefing_round_simulation.py"))
base = run.base


class UnsupportedSelectionTransport(fixtures.AuthoredTransport):
    """A well-formed completed paid answer that fails semantic selection guards."""
    def __call__(self, raw):
        status, response = super().__call__(raw)
        request = base.strict_load(raw)
        if request["text"]["format"]["name"] != fixtures.grouped.SELECTION_STAGE:
            return status, response
        provider = base.strict_load(response)
        part = provider["output"][0]["content"][0]
        answer = base.strict_load(part["text"])
        answer["selected"][0]["companyIds"] = ["not-in-frozen-issue"]
        part["text"] = base.canonical(answer).decode()
        return status, base.canonical(provider)


class UnknownStageTransport(fixtures.AuthoredTransport):
    """One authored transport exception leaves its real write-ahead slot unknown."""
    def __init__(self, stage):
        super().__init__()
        self.stage = stage

    def __call__(self, raw):
        response = super().__call__(raw)
        request = base.strict_load(raw)
        if request["text"]["format"]["name"] == self.stage:
            raise OSError("authored transport outcome unknown")
        return response


class UnknownCorrectionTransport(UnsupportedSelectionTransport):
    def __call__(self, raw):
        response = super().__call__(raw)
        if "selectionCorrection" in base.strict_load(base.strict_load(raw)["input"]):
            raise OSError("authored correction outcome unknown")
        return response


class GroupedRunTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.clock = clocks.RoundSimulationTest()
        self.clock.setUp()
        self.archive_path = self.root / "archive.json"
        self.output = self.root / "output"

    def tearDown(self):
        self.clock.tearDown()
        self.temp.cleanup()

    def prepare(self, count=14, unknown=False):
        rows = []
        for i, spec in enumerate(run.sim.windows()[:count]):
            stamp = (run.sim.aware(spec["window"]["to"]) - timedelta(minutes=10)).isoformat()
            doc = fixtures.document("authored-doc-" + str(i), stamp)
            rows.append({**doc, "authoredPublishedAt": stamp, "allowModelSend": False,
                         "rightsStatus": "unconfirmed", "sourceKind": "news"})
        unverified = []
        if unknown:
            rows.append(clocks.source("unresolved-clock", "2026-10-02T08:00:00+09:00"))
            unverified.append("unresolved-clock")
        self.clock.prepare(rows, unverified)
        normalized, _, source = run.sim.load_inputs(self.clock.sources, self.clock.clocks)
        groups = []
        for i, doc in enumerate(normalized):
            groups.append(("stable-authored-issue-" + str(i), [(doc, fixtures.mention(doc, "authored-mention-" + str(i)))]))
        archive = fixtures.archive(*groups)
        archive["documents"] = [{k: v for k, v in doc.items() if k != "clockTime"} for doc in archive["documents"]]
        archive.update(sourceFileSha256=source["sourceFileSha256"], clockFileSha256=source["clockFileSha256"])
        fixtures.record_grounding(archive, self.root)
        self.archive_path.write_bytes(base.canonical(archive))
        return archive

    def args(self, execute=True):
        values = ["--archive", str(self.archive_path), "--sources", str(self.clock.sources),
                  "--clocks", str(self.clock.clocks), "--output", str(self.output),
                  "--user-inbox-ref", "inbox/authored-grouped-run.md", "--max-repairs", "0"]
        if execute:
            values.append("--execute-authorized")
        return run.parser().parse_args(values)

    def execute(self, transport, execute=True, hold_unresolved=False):
        args = self.args(execute)
        args.hold_unresolved_requests = hold_unresolved
        with contextlib.redirect_stdout(io.StringIO()):
            return run.run(args, transport)

    def bundle(self):
        return base.strict_load((self.output / "bundle-v2.json").read_bytes())

    def test_fourteen_round_bundle_has_stable_issues_receipts_and_previous_hashes(self):
        self.prepare()
        transport = fixtures.AuthoredTransport()
        result = self.execute(transport)
        bundle = self.bundle()
        self.assertEqual("COMPLETE", result["status"])
        self.assertEqual(14, result["selectedRounds"])
        self.assertEqual(14, result["selectedIssues"])
        self.assertEqual(42, result["newPaidCalls"])
        self.assertEqual(42, len(transport.requests))
        for index, encoded in enumerate(transport.requests):
            data = base.strict_load(base.strict_load(encoded)["input"])
            expected = index // 3
            self.assertEqual(expected, len(data["priorSelectedIssues"]))
            for prior in data["priorSelectedIssues"]:
                self.assertEqual({"issueId", "title", "sources"}, set(prior))
                self.assertTrue(prior["sources"])
        self.assertEqual(14, len(bundle["rounds"]))
        self.assertEqual("zoop-briefing-grouped-simulation-v1", bundle["schemaVersion"])
        self.assertFalse(bundle["authorization"]["productionAuthorized"])
        self.assertIsNone(bundle["graphVersion"])
        owned = []
        for index, record in enumerate(bundle["rounds"]):
            self.assertEqual("SELECTED", record["selectionStatus"])
            self.assertEqual("stable-authored-issue-" + str(index), record["selected"][0]["issueId"])
            self.assertEqual("PASS", record["result"]["verification"]["status"])
            self.assertEqual(3, len(record["receipts"]))
            self.assertEqual(2, len(record["result"]["usage"]))
            self.assertIn(record["groupedSelectionRequestDigest"], [r["requestDigest"] for r in record["receipts"]])
            self.assertEqual(base.digest(base.canonical(record["result"])), record["resultSha256"])
            owned.extend(r["requestDigest"] for r in record["receipts"])
            if index:
                previous = bundle["rounds"][index - 1]
                self.assertEqual(previous["roundId"], record["previous"]["roundId"])
                self.assertEqual(previous["resultSha256"], record["previous"]["resultSha256"])
            else:
                self.assertEqual("unavailable", record["previous"]["status"])
        self.assertEqual(42, len(set(owned)))
        self.assertEqual(set(owned), {r["requestDigest"] for r in bundle["receipts"]})

    def test_identical_rerun_reuses_every_round_and_makes_zero_provider_calls(self):
        self.prepare()
        self.execute(fixtures.AuthoredTransport())
        before = {str(p.relative_to(self.output)): base.digest(p.read_bytes()) for p in self.output.rglob("*") if p.is_file()}
        def deny(_):
            raise AssertionError("reuse must not call the provider")
        result = self.execute(deny)
        self.assertEqual(0, result["newPaidCalls"])
        self.assertEqual(14, result["selectedRounds"])
        after = {str(p.relative_to(self.output)): base.digest(p.read_bytes()) for p in self.output.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_semantically_rejected_selection_keeps_its_paid_receipt(self):
        self.prepare(count=1, unknown=True)
        transport = UnsupportedSelectionTransport()
        result = self.execute(transport)
        bundle = self.bundle()
        first = bundle["rounds"][0]
        self.assertEqual(0, result["selectedRounds"])
        self.assertEqual("HELD_VALIDATION", first["selectionStatus"])
        self.assertIn("unknown_or_duplicate_company", first["groupedValidationFailure"])
        self.assertEqual([], first["selected"])
        self.assertIsNone(first["result"])
        self.assertIsNone(first["resultSha256"])
        self.assertEqual(2, len(transport.requests))
        self.assertEqual(2, len(first["receipts"]))
        self.assertEqual(1, len(first["groupedSelectionCorrections"]))
        correction = first["groupedSelectionCorrections"][0]
        self.assertEqual("WITHHELD", correction["status"])
        self.assertEqual(first["groupedSelectionRequestDigest"], correction["correctedRequestDigest"])
        receipt = next(r for r in first["receipts"] if r["requestDigest"] == correction["correctedRequestDigest"])
        self.assertEqual(first["groupedSelectionRequestDigest"], receipt["requestDigest"])
        self.assertTrue(receipt["usageKnown"])
        self.assertEqual(100, receipt["inputTokens"])
        self.assertEqual(50, receipt["outputTokens"])
        self.assertEqual(first["receipts"], bundle["receipts"])
        self.assertEqual("unavailable", bundle["rounds"][1]["previous"]["status"])
        self.assertTrue((self.output / "calls" / (receipt["requestDigest"] + ".response.json")).is_file())

    def test_offline_plan_never_creates_output_or_calls_provider(self):
        self.prepare(count=1)
        transport = fixtures.AuthoredTransport()
        result = self.execute(transport, execute=False)
        self.assertEqual("OFFLINE", result["status"])
        self.assertEqual(14, len(result["rounds"]))
        self.assertEqual(0, result["newPaidCalls"])
        self.assertEqual([], transport.requests)
        self.assertFalse(self.output.exists())

    def test_source_binding_mismatch_fails_before_provider(self):
        archive = self.prepare(count=1)
        archive["clockFileSha256"] = "0" * 64
        self.archive_path.write_bytes(base.canonical(archive))
        transport = fixtures.AuthoredTransport()
        with self.assertRaisesRegex(run.sim.ReplayError, "grouped_run_source_binding_mismatch"):
            self.execute(transport)
        self.assertEqual([], transport.requests)

    def test_hold_option_defaults_off(self):
        self.assertFalse(self.args().hold_unresolved_requests)

    def test_startup_unknown_in_any_phase_is_held_without_resend_then_other_rounds_run(self):
        for stage in (run.grouped.SELECTION_STAGE, "round_simulation_morning_generation",
                      "round_simulation_morning_verification"):
            with self.subTest(stage=stage):
                self.output = self.root / stage
                self.prepare(count=3)
                failed = UnknownStageTransport(stage)
                with self.assertRaisesRegex(run.sim.ReplayError, "transport_unknown_usage_no_automatic_retry"):
                    self.execute(failed)
                calls = self.output / "calls"
                unknown_digest = base.digest(failed.requests[-1])
                old_calls = {p.name: base.digest(p.read_bytes()) for p in calls.iterdir() if p.is_file()}
                self.assertTrue((calls / (unknown_digest + ".pending.json")).exists())
                self.assertFalse((calls / (unknown_digest + ".complete.json")).exists())
                def deny(_):
                    raise AssertionError("old unresolved calls must never be resent")
                # The ordinary default retains the old stop behavior.
                with self.assertRaisesRegex(run.sim.ReplayError, "unresolved_paid_reservation_no_automatic_retry"):
                    self.execute(deny)
                resumed = fixtures.AuthoredTransport()
                result = self.execute(resumed, hold_unresolved=True)
                bundle = self.bundle()
                held = bundle["rounds"][0]
                self.assertEqual("HELD_VALIDATION", held["selectionStatus"])
                self.assertEqual("operator_held_unresolved_paid_request", held["groupedValidationFailure"])
                self.assertEqual([], held["selected"])
                self.assertIsNone(held["result"])
                self.assertIsNone(held["resultSha256"])
                disposition = held["groupedUnresolvedPaidRequest"]
                self.assertEqual(unknown_digest, disposition["requestDigest"])
                self.assertEqual(stage, disposition["stage"])
                self.assertEqual("hold_without_retransmission", disposition["operatorDisposition"])
                self.assertTrue(disposition["preexistingAtProcessStart"])
                receipt = next(r for r in held["receipts"] if r["requestDigest"] == unknown_digest)
                self.assertEqual("unknown", receipt["status"])
                self.assertFalse(receipt["usageKnown"])
                self.assertIsNone(receipt["inputTokens"])
                self.assertIsNone(receipt["outputTokens"])
                self.assertEqual(2, result["selectedRounds"])
                self.assertEqual(6, result["newPaidCalls"])
                self.assertEqual(6, len(resumed.requests))
                self.assertNotIn(unknown_digest, {base.digest(raw) for raw in resumed.requests})
                self.assertEqual("unavailable", bundle["rounds"][1]["previous"]["status"])
                for name, sha in old_calls.items():
                    self.assertEqual(sha, base.digest((calls / name).read_bytes()))
                before = {str(p.relative_to(self.output)): base.digest(p.read_bytes())
                          for p in self.output.rglob("*") if p.is_file()}
                reused = self.execute(deny, hold_unresolved=True)
                self.assertEqual(0, reused["newPaidCalls"])
                after = {str(p.relative_to(self.output)): base.digest(p.read_bytes())
                         for p in self.output.rglob("*") if p.is_file()}
                self.assertEqual(before, after)

    def test_new_failure_after_holding_old_unknown_still_stops_the_run(self):
        self.prepare(count=3)
        first = UnknownStageTransport("round_simulation_morning_generation")
        with self.assertRaises(run.sim.ReplayError):
            self.execute(first)
        first_unknown = base.digest(first.requests[-1])
        old_files = {p.name: base.digest(p.read_bytes()) for p in (self.output / "calls").iterdir() if p.is_file()}
        second = UnknownStageTransport("round_simulation_evening_generation")
        with self.assertRaisesRegex(run.sim.ReplayError, "transport_unknown_usage_no_automatic_retry"):
            self.execute(second, hold_unresolved=True)
        self.assertEqual(2, len(second.requests))
        self.assertNotIn(first_unknown, {base.digest(raw) for raw in second.requests})
        self.assertFalse((self.output / "2026-10-02-evening" / "round.json").exists())
        self.assertFalse((self.output / "2026-10-03-morning").exists())
        self.assertFalse((self.output / "bundle-v2.json").exists())
        for name, sha in old_files.items():
            self.assertEqual(sha, base.digest((self.output / "calls" / name).read_bytes()))

    def test_unknown_selection_correction_records_its_actual_final_digest(self):
        self.prepare(count=2)
        failed = UnknownCorrectionTransport()
        with self.assertRaisesRegex(run.sim.ReplayError, "transport_unknown_usage_no_automatic_retry"):
            self.execute(failed)
        self.assertEqual(2, len(failed.requests))
        unknown_digest = base.digest(failed.requests[-1])
        original_digest = base.digest(failed.requests[0])
        old_files = {p.name: base.digest(p.read_bytes()) for p in (self.output / "calls").iterdir() if p.is_file()}
        resumed = fixtures.AuthoredTransport()
        result = self.execute(resumed, hold_unresolved=True)
        held = self.bundle()["rounds"][0]
        self.assertEqual("HELD_VALIDATION", held["selectionStatus"])
        self.assertEqual(unknown_digest, held["groupedSelectionRequestDigest"])
        self.assertEqual(unknown_digest, held["groupedUnresolvedPaidRequest"]["requestDigest"])
        self.assertEqual({original_digest, unknown_digest}, {r["requestDigest"] for r in held["receipts"]})
        self.assertEqual(1, result["selectedRounds"])
        self.assertEqual(3, len(resumed.requests))
        self.assertNotIn(unknown_digest, {base.digest(raw) for raw in resumed.requests})
        for name, sha in old_files.items():
            self.assertEqual(sha, base.digest((self.output / "calls" / name).read_bytes()))


if __name__ == "__main__":
    unittest.main()
