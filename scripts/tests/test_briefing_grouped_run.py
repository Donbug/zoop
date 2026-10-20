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
        self.archive_path.write_bytes(base.canonical(archive))
        return archive

    def args(self, execute=True):
        values = ["--archive", str(self.archive_path), "--sources", str(self.clock.sources),
                  "--clocks", str(self.clock.clocks), "--output", str(self.output),
                  "--user-inbox-ref", "inbox/authored-grouped-run.md", "--max-repairs", "0"]
        if execute:
            values.append("--execute-authorized")
        return run.parser().parse_args(values)

    def execute(self, transport, execute=True):
        with contextlib.redirect_stdout(io.StringIO()):
            return run.run(self.args(execute), transport)

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
        self.assertEqual(1, len(transport.requests))
        self.assertEqual(1, len(first["receipts"]))
        receipt = first["receipts"][0]
        self.assertEqual(first["groupedSelectionRequestDigest"], receipt["requestDigest"])
        self.assertTrue(receipt["usageKnown"])
        self.assertEqual(100, receipt["inputTokens"])
        self.assertEqual(50, receipt["outputTokens"])
        self.assertEqual([receipt], bundle["receipts"])
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


if __name__ == "__main__":
    unittest.main()
