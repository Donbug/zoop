"""Offline integration with the real external team contracts and authored replies.

Set ZOOP_TEST_POC_ROOT to the audited, separately supplied PoC checkout. No key,
network transport, production data or absolute developer path is required.
"""
import contextlib
import copy
import importlib
import importlib.util
import io
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("issue_pipeline_tests_target", HERE / "briefing_issue_pipeline.py")
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)
fixture_spec = importlib.util.spec_from_file_location("issue_pipeline_clock_fixture", Path(__file__).with_name("test_briefing_round_simulation.py"))
clock_fixture = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(clock_fixture)


class AuthoredIssueTransport:
    def __init__(self, grounding="SUPPORTED", background=False):
        self.calls = []
        self.grounding = grounding
        self.background = background

    def __call__(self, raw):
        self.calls.append(raw)
        request = pipeline.base.strict_load(raw)
        self.assert_private_request(request)
        data = pipeline.base.strict_load(request["input"])
        stage = request["text"]["format"]["name"]
        if stage == "issue_extraction":
            result = {"documents": {}}
            for value in data["documents"]:
                a = value["article"]
                quote = a["body"][:80]
                result["documents"][a["article_id"]] = {"mentions": [{
                    "mention_id": "authored-event", "article_id": a["article_id"],
                    "article_version": value["article_version"], "title": "Synthetic chip announcement",
                    "event_type": "announcement", "action": "announced", "target": "chip",
                    "event_time": None, "period": None, "assertion_status": "announced",
                    "participants": [{"company_id": "company-alpha", "name": "Alpha", "role": "announcer"}],
                    "evidence": [{"article_id": a["article_id"], "article_version": value["article_version"],
                                  "start": 0, "end": len(quote), "quote": quote}],
                    "keywords": ["chip"], "background": self.background, "countries": []}]}
        elif stage == "issue_grounding":
            result = {"verdicts": {key: {"verdict": self.grounding,
                "reason": "Authored independent review: role unsupported" if self.grounding != "SUPPORTED" else "Authored source support"}
                for key in data["mentions"]}}
        elif stage == "issue_comparison":
            result = {"comparisons": {key: {"relation": "DIFFERENT", "reason": "Authored distinct event", "evidence": []}
                                      for key in data["pairs"]}}
        else:
            raise AssertionError("unexpected provider stage: " + stage)
        return clock_fixture.response(result, raw)

    @staticmethod
    def assert_private_request(request):
        if request["store"] is not False:
            raise AssertionError("provider storage enabled")


class SameEventTransport(AuthoredIssueTransport):
    """Two authored reports of one event, with exact evidence from both sources."""
    def __init__(self):
        super().__init__()
        self.comparison_pairs = []

    def __call__(self, raw):
        request = pipeline.base.strict_load(raw)
        if request["text"]["format"]["name"] != "issue_comparison":
            return super().__call__(raw)
        self.calls.append(raw)
        self.assert_private_request(request)
        data = pipeline.base.strict_load(request["input"])
        self.comparison_pairs.extend(data["pairs"].values())
        comparisons = {}
        for key, pair in data["pairs"].items():
            original = pair["input"]
            # The source/version anchors are supplied by the real team contracts.
            # This is a deterministic fixture, not a model-accuracy assertion.
            incoming = original["mention"]["evidence"][0]
            prior = original["issue"]["mentions"][0]["evidence"][0]
            comparisons[key] = {"relation": "SAME", "reason": "Authored same chip announcement in two reports",
                                "evidence": [incoming, prior]}
        return clock_fixture.response({"comparisons": comparisons}, raw)


class IssuePipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.poc_root = os.environ.get("ZOOP_TEST_POC_ROOT")
        if not cls.poc_root:
            raise unittest.SkipTest("ZOOP_TEST_POC_ROOT must name the separately supplied audited team checkout")
        cls.rules = pipeline.team.IssueRules(cls.poc_root)
        cls.prompts = importlib.import_module(cls.rules.domain.__package__ + ".prompts")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.clocks = clock_fixture.RoundSimulationTest()
        self.clocks.setUp()
        self.companies = self.root / "companies.json"
        self.companies.write_bytes(pipeline.canonical({"companies": [
            {"company_id": "company-alpha", "name": "Alpha", "aliases": [], "ticker": None}]}))
        self.seed = self.root / "seed.json"
        self.seed.write_bytes(pipeline.canonical({"issues": [], "review_exclusions": []}))

    def tearDown(self):
        self.clocks.tearDown()
        self.temp.cleanup()

    def row(self, name="source-one", published="2026-10-02T09:00:00+09:00"):
        return clock_fixture.source(name, published,
            "Alpha announced a new chip. This is an authored synthetic event for an offline integration test, not a real news event.")

    def prepared(self, rows=None, unverified=()):
        self.clocks.prepare(rows or [self.row()], unverified)
        return pipeline.sim.load_inputs(self.clocks.sources, self.clocks.clocks)

    def args(self, execute=False):
        values = ["--poc-root", self.poc_root, "--sources", str(self.clocks.sources), "--clocks", str(self.clocks.clocks),
            "--seed", str(self.seed), "--companies", str(self.companies), "--output", str(self.root / "output"),
            "--user-inbox-ref", "inbox/authored-issue-pipeline-test.md", "--workers", "1", "--batch-size", "2"]
        if execute:
            values.append("--execute-authorized")
        return pipeline.parser().parse_args(values)

    def article_and_mention(self, published="2026-10-01T10:00:00+09:00"):
        article = self.rules.article({"article_id": "seed-article", "url": "https://example.invalid/seed", "title": "Synthetic seed",
            "body": "Alpha announced a synthetic chip. This sentence supplies authored test evidence.", "publisher": "authored",
            "published_at": published, "collected_at": "2026-10-20T00:00:00Z"})
        quote = article.body
        mention = self.rules.domain.Mention.model_validate({"mention_id": "seed-mention", "article_id": article.article_id,
            "article_version": article.version, "title": "Synthetic seed", "event_type": "announcement", "action": "announced",
            "assertion_status": "announced", "participants": [], "evidence": [{"article_id": article.article_id,
                "article_version": article.version, "start": 0, "end": len(quote), "quote": quote}]})
        return article, mention

    def seed_payload(self, article, mention, relations=None):
        return {"issues": [{"issue_id": "seed-issue", "articles": [article.model_dump(mode="json")],
                            "mentions": [mention.model_dump(mode="json")], "relations": relations or []}]}

    def test_seed_rejects_future_and_missing_publication_clock(self):
        for stamp in [None, "2026-10-02T00:00:00+09:00"]:
            article, mention = self.article_and_mention(stamp)
            self.seed.write_bytes(pipeline.canonical(self.seed_payload(article, mention)))
            with self.subTest(stamp=stamp), self.assertRaisesRegex(pipeline.Error, "seed_contains_future_or_unresolved_article"):
                pipeline.seed_issues(self.rules, self.seed, pipeline.sim.BASELINE)

    def test_seed_does_not_restore_manually_excluded_relation(self):
        article, mention = self.article_and_mention()
        value = self.seed_payload(article, mention, [{"relation_id": "excluded-edge"}])
        value["review_exclusions"] = [{"relation_id": "excluded-edge"}]
        self.seed.write_bytes(pipeline.canonical(value))
        with self.assertRaisesRegex(pipeline.Error, "seed_resurrected_review_exclusion"):
            pipeline.seed_issues(self.rules, self.seed, pipeline.sim.BASELINE)

    def test_seed_keeps_late_collection_limitation_and_never_approves(self):
        article, mention = self.article_and_mention()
        self.seed.write_bytes(pipeline.canonical(self.seed_payload(article, mention)))
        issues, audit = pipeline.seed_issues(self.rules, self.seed, pipeline.sim.BASELINE)
        self.assertEqual("2026-10-20T00:00:00Z", issues["seed-issue"]["snapshot"].articles[0].collected_at)
        self.assertFalse(audit["rightsOrPublicationApproval"])
        self.assertFalse(audit["snapshotAvailabilityAtHistoricalCutoffProven"])

    def test_projection_preserves_model_flag_and_source_row(self):
        rows, _, _ = self.prepared()
        row = rows[0]
        before = copy.deepcopy(row)
        article = pipeline.project_article(self.rules, row)
        self.assertFalse(article.allow_model_send)
        self.assertFalse(article.synthetic)
        self.assertEqual(row["clockRecord"]["publishedAt"], article.published_at)
        self.assertEqual(before, row)

    def test_quote_span_can_resolve_but_identity_cannot_be_repaired(self):
        article, _ = self.article_and_mention()
        quote = article.body[6:30]
        evidence = {"article_id": article.article_id, "article_version": article.version,
                    "start": 0, "end": 1, "quote": quote}
        resolved = pipeline.resolve_quotes(evidence, [article])
        self.assertEqual((6, 30), (resolved["start"], resolved["end"]))
        self.assertEqual((0, 1), (evidence["start"], evidence["end"]))
        for bad in [{**evidence, "article_version": "wrong"}, {**evidence, "article_id": "wrong"}]:
            with self.assertRaisesRegex(pipeline.Error, "issue_quote_identity_invalid"):
                pipeline.resolve_quotes(bad, [article])

    def test_ambiguous_or_missing_quote_cannot_be_repaired(self):
        article, _ = self.article_and_mention()
        repeated = article.model_copy(update={"body": "Alpha Alpha"})
        for quote in ["Alpha", "missing"]:
            evidence = {"article_id": repeated.article_id, "article_version": repeated.version,
                        "start": 1, "end": 2, "quote": quote}
            with self.assertRaisesRegex(pipeline.Error, "issue_quote_missing_or_ambiguous"):
                pipeline.resolve_quotes(evidence, [repeated])

    def test_semantic_verifier_can_hold_exactly_cited_but_unsupported_role(self):
        rows, _, _ = self.prepared()
        client = pipeline.IssueClient(self.root / "calls", AuthoredIssueTransport(grounding="HOLD"),
                                     {stage: "authored test" for stage in ["issue_extraction", "issue_grounding"]}, 4)
        accepted, held = pipeline.extraction_batch(client, self.rules, self.prompts, [], rows, {"scope": "authored-test"})
        self.assertEqual([], accepted)
        self.assertEqual("semantic_HOLD", held[0]["reason"])
        self.assertEqual(2, len(client.receipts()))

    def test_background_never_becomes_new_event_even_when_supported(self):
        rows, _, _ = self.prepared()
        client = pipeline.IssueClient(self.root / "calls", AuthoredIssueTransport(background=True),
                                     {stage: "authored test" for stage in ["issue_extraction", "issue_grounding"]}, 4)
        accepted, held = pipeline.extraction_batch(client, self.rules, self.prompts, [], rows, {"scope": "authored-test"})
        self.assertEqual([], accepted)
        self.assertEqual("background_event", held[0]["reason"])

    def test_full_run_excludes_unresolved_clocks_and_reuses_without_provider(self):
        self.prepared([self.row("source-good"), self.row("source-unknown")], ["source-unknown"])
        transport = AuthoredIssueTransport()
        with contextlib.redirect_stdout(io.StringIO()):
            result = pipeline.run(self.args(True), transport)
        self.assertEqual("COMPLETE", result["status"])
        self.assertEqual(1, result["eligibleDocuments"])
        self.assertEqual(1, result["timeUnresolvedDocuments"])
        archive = pipeline.base.strict_load((self.root / "output/grouped-issues.json").read_bytes())
        self.assertEqual(["source-good"], [r["documentId"] for r in archive["documents"]])
        self.assertFalse(archive["documents"][0]["allowModelSend"])
        self.assertTrue(any(r["reason"] == "unresolved_round_clock" for r in archive["held"]))
        self.assertFalse(archive["productionAuthorized"])
        self.assertEqual(2, len(transport.calls))
        def deny(_):
            raise AssertionError("cached execution must not call provider")
        with contextlib.redirect_stdout(io.StringIO()):
            reused = pipeline.run(self.args(True), deny)
        self.assertEqual("REUSED", reused["status"])
        self.assertEqual(0, reused["newPaidCalls"])

    def same_event_rows(self, count):
        rows = []
        for index in range(count):
            row = self.row("same-report-" + str(index), "2026-10-02T09:" + str(index).zfill(2) + ":00+09:00")
            row["body"] += " Authored publication detail " + str(index) + "."
            row["bodySha256"] = pipeline.digest(row["body"].encode())
            rows.append(row)
        return rows

    def test_two_different_source_reports_really_merge_into_one_stable_issue(self):
        rows = self.same_event_rows(2)
        self.prepared(rows)
        transport = SameEventTransport()
        args = self.args(True)
        args.comparison_batch_size = 2
        with contextlib.redirect_stdout(io.StringIO()):
            result = pipeline.run(args, transport)
        archive_path = self.root / "output/grouped-issues.json"
        archive = pipeline.base.strict_load(archive_path.read_bytes())
        self.assertEqual({"NEW": 1, "MERGE": 1, "HOLD": 0}, result["assignmentCounts"])
        self.assertEqual(1, result["counts"]["issues"])
        self.assertEqual(2, result["counts"]["mentions"])
        self.assertEqual(2, result["counts"]["evidence"])
        self.assertEqual(1, len(archive["issues"]))
        issue = archive["issues"][0]
        self.assertEqual(2, len(issue["mentions"]))
        self.assertEqual({r["documentId"] for r in rows}, {m["articleId"] for m in issue["mentions"]})
        self.assertEqual(2, len({m["bodySha256"] for m in issue["mentions"]}))
        self.assertEqual([issue["issueId"], issue["issueId"]], [d["issueId"] for d in archive["decisions"]])
        self.assertEqual(1, len(transport.comparison_pairs))
        compared = transport.comparison_pairs[0]["input"]
        self.assertNotEqual(compared["article"]["article_id"], compared["issue"]["articles"][0]["article_id"])
        self.assertEqual(3, len(archive["receipts"]))
        before = archive_path.read_bytes()
        def deny(_):
            raise AssertionError("stable merged archive must reuse without a provider")
        with contextlib.redirect_stdout(io.StringIO()):
            reused = pipeline.run(args, deny)
        self.assertEqual("REUSED", reused["status"])
        self.assertEqual(0, reused["newPaidCalls"])
        self.assertEqual(before, archive_path.read_bytes())

    def test_third_same_batch_alias_is_held_when_whole_issue_expands(self):
        self.prepared(self.same_event_rows(3))
        transport = SameEventTransport()
        args = self.args(True)
        args.batch_size = 3
        args.comparison_batch_size = 3
        with contextlib.redirect_stdout(io.StringIO()):
            result = pipeline.run(args, transport)
        archive = pipeline.base.strict_load((self.root / "output/grouped-issues.json").read_bytes())
        self.assertEqual({"NEW": 1, "MERGE": 1, "HOLD": 1}, result["assignmentCounts"])
        self.assertEqual(1, len(archive["issues"]))
        self.assertEqual(2, len(archive["issues"][0]["mentions"]))
        self.assertEqual({"same-report-0", "same-report-1"},
                         {m["articleId"] for m in archive["issues"][0]["mentions"]})
        third = archive["decisions"][2]
        self.assertEqual("same-report-2", third["articleId"])
        self.assertEqual("HOLD", third["status"])
        self.assertEqual(1, len(third["comparisons"]))
        self.assertEqual("whole_issue_changed_since_comparison", third["comparisons"][0]["effective"]["reason"])
        self.assertEqual("HOLD", third["comparisons"][0]["effective"]["relation"])
        self.assertEqual(3, len(transport.comparison_pairs))
        self.assertEqual(1, result["counts"]["holds"])

    def test_offline_plan_never_calls_provider_or_creates_output(self):
        self.prepared()
        transport = AuthoredIssueTransport()
        result = pipeline.run(self.args(), transport)
        self.assertEqual("OFFLINE", result["status"])
        self.assertEqual([], transport.calls)
        self.assertFalse((self.root / "output").exists())

    def test_sqlite_reimport_is_identical_and_conflicts_are_rejected(self):
        path = self.root / "issues.sqlite3"
        row = self.row()
        args = ({"fixed": "identity"}, [row], {}, [], [], [])
        first = pipeline.database(path, *args)
        self.assertEqual(first, pipeline.database(path, *args))
        with self.assertRaisesRegex(pipeline.Error, "immutable_issue_registry_conflict"):
            pipeline.database(path, args[0], [{**row, "title": "changed"}], {}, [], [], [])
        with self.assertRaisesRegex(pipeline.Error, "issue_registry_identity_conflict"):
            pipeline.database(path, {"fixed": "other"}, [row], {}, [], [], [])
        with sqlite3.connect(path) as db:
            payload = pipeline.base.strict_load(db.execute("SELECT payload FROM documents").fetchone()[0])
            self.assertEqual(row, payload)
            self.assertEqual([], db.execute("PRAGMA foreign_key_check").fetchall())


if __name__ == "__main__":
    unittest.main()
