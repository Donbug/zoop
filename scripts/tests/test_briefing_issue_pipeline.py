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
import shutil
import tempfile
import unittest
from unittest.mock import patch

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

    def test_fifty_six_cached_calls_and_one_unresolved_reservation_are_never_resent(self):
        output = self.root / "recovery-cache"
        prompts = {"cache_stage": "authored cache accounting test"}
        schema = pipeline.obj({"value": pipeline.strings()})
        def authored(raw):
            request = pipeline.base.strict_load(raw)
            data = pipeline.base.strict_load(request["input"])
            if data["index"] == 56:
                raise OSError("authored unknown receive")
            return clock_fixture.response({"value": str(data["index"])}, raw)
        client = pipeline.IssueClient(output, authored, prompts, 57)
        for index in range(56):
            self.assertEqual({"value": str(index)}, client.ask("cache_stage", {"index": index}, schema))
        with self.assertRaisesRegex(pipeline.Error, "transport_unknown"):
            client.ask("cache_stage", {"index": 56}, schema)
        before = {p.name: p.read_bytes() for p in client.calls.glob("*")}
        calls = []
        def deny(raw):
            calls.append(raw)
            raise AssertionError("recovery must not resend paid reservations")
        default = pipeline.IssueClient(output, deny, prompts, 57)
        with self.assertRaisesRegex(pipeline.Error, "unresolved_paid_reservation"):
            default.ask("cache_stage", {"index": 56}, schema)
        self.assertTrue(default.stopped.is_set())
        recovered = pipeline.IssueClient(output, deny, prompts, 57, hold_unresolved_requests=True)
        for index in range(56):
            self.assertEqual({"value": str(index)}, recovered.ask("cache_stage", {"index": index}, schema))
        with self.assertRaises(pipeline.HeldPaidRequest):
            recovered.ask("cache_stage", {"index": 56}, schema)
        self.assertFalse(recovered.stopped.is_set())
        receipts = recovered.receipts()
        self.assertEqual(56, sum(r["usageKnown"] for r in receipts))
        unknown = next(r for r in receipts if not r["usageKnown"])
        self.assertIsNone(unknown["inputTokens"])
        self.assertIsNone(unknown["outputTokens"])
        self.assertEqual([], calls)
        self.assertEqual(before, {p.name: p.read_bytes() for p in client.calls.glob("*")})
        with self.assertRaisesRegex(pipeline.Error, "paid_call_budget_exhausted"):
            recovered.ask("cache_stage", {"index": 57}, schema)
        self.assertEqual([], calls)

    def test_explicit_recovery_holds_six_documents_and_reuses_all_other_calls(self):
        self.prepared(self.same_event_rows(12))
        args = self.args(True)
        args.batch_size = 6
        args.comparison_batch_size = 6
        normal = AuthoredIssueTransport()
        def fail_second_batch(raw):
            request = pipeline.base.strict_load(raw)
            data = pipeline.base.strict_load(request["input"])
            if request["text"]["format"]["name"] == "issue_extraction" \
                    and any(d["article"]["article_id"] == "same-report-6" for d in data["documents"]):
                raise OSError("authored unknown extraction response")
            return normal(raw)
        captured = []
        original_client = pipeline.IssueClient
        def capture(*values, **kwargs):
            value = original_client(*values, **kwargs)
            captured.append(value)
            return value
        with patch.object(pipeline, "IssueClient", side_effect=capture), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(pipeline.Error, "transport_unknown"):
                pipeline.run(args, fail_second_batch)
        identity = pipeline.base.strict_load((self.root / "output/identity.json").read_bytes())
        rows, _, _ = pipeline.sim.load_inputs(self.clocks.sources, self.clocks.clocks)
        rows.sort(key=lambda r: (r["clockTime"], r["documentId"]))
        # Complete the known six-document comparison as an authored prior receipt.
        # The later recovery must then need zero new transport calls at any stage.
        prefill = original_client(self.root / "output", AuthoredIssueTransport(), captured[0].prompts, args.max_calls)
        accepted, held = pipeline.extraction_batch(prefill, self.rules, self.prompts,
            pipeline.load_catalogue(self.companies), rows[:6], identity["authorization"])
        self.assertEqual([], held)
        pipeline.compare_batch(prefill, self.rules, self.prompts, accepted, {}, identity["authorization"])
        before = {p.name: p.read_bytes() for p in prefill.calls.glob("*")}
        args.hold_unresolved_requests = True
        def deny(_):
            raise AssertionError("all completed calls must reuse; unknown extraction must be held")
        with contextlib.redirect_stdout(io.StringIO()):
            result = pipeline.run(args, deny)
        archive = pipeline.base.strict_load((self.root / "output/grouped-issues.json").read_bytes())
        self.assertEqual("COMPLETE", result["status"])
        self.assertEqual(0, result["newPaidCalls"])
        self.assertEqual({"NEW": 6, "MERGE": 0, "HOLD": 0}, result["assignmentCounts"])
        withheld = [h for h in archive["held"] if h["reason"] == "operator_held_unresolved_paid_request"]
        self.assertEqual({"same-report-" + str(i) for i in range(6, 12)}, {h["articleId"] for h in withheld})
        self.assertEqual(1, len({h["requestDigest"] for h in withheld}))
        self.assertTrue(all(h["usageKnown"] is False and h["inputTokens"] is None and h["outputTokens"] is None for h in withheld))
        self.assertEqual(6, result["counts"]["mentions"])
        self.assertEqual(6, result["counts"]["holds"])
        self.assertEqual(1, sum(not r["usageKnown"] for r in archive["receipts"]))
        self.assertEqual(before, {p.name: p.read_bytes() for p in prefill.calls.glob("*")})

    def test_unresolved_comparison_holds_batch_without_new_or_merge(self):
        self.prepared(self.same_event_rows(3))
        args = self.args(True)
        args.batch_size = 3
        args.comparison_batch_size = 3
        normal = AuthoredIssueTransport()
        def fail_comparison(raw):
            request = pipeline.base.strict_load(raw)
            if request["text"]["format"]["name"] == "issue_comparison":
                raise OSError("authored unknown comparison response")
            return normal(raw)
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(pipeline.Error, "transport_unknown"):
                pipeline.run(args, fail_comparison)
        args.hold_unresolved_requests = True
        def deny(_):
            raise AssertionError("comparison recovery must not send a request")
        with contextlib.redirect_stdout(io.StringIO()):
            result = pipeline.run(args, deny)
        archive = pipeline.base.strict_load((self.root / "output/grouped-issues.json").read_bytes())
        self.assertEqual(0, result["newPaidCalls"])
        self.assertEqual({"NEW": 0, "MERGE": 0, "HOLD": 3}, result["assignmentCounts"])
        self.assertEqual([], archive["issues"])
        self.assertTrue(all(d["issueId"] is None and not d["approved"] for d in archive["decisions"]))
        self.assertEqual({"issue_comparison"}, {h["stage"] for h in archive["held"]})
        self.assertEqual(1, sum(not r["usageKnown"] for r in archive["receipts"]))

    def comparison_data(self, index=0, copies=3):
        article, mention = self.article_and_mention()
        prior_article = self.rules.article({**article.model_dump(), "article_id": "earlier-article"})
        evidence = {**mention.evidence[0].model_dump(), "article_id": prior_article.article_id, "article_version": prior_article.version}
        prior = mention.model_copy(update={"article_id": prior_article.article_id, "article_version": prior_article.version,
                                          "evidence": [self.rules.domain.Evidence.model_validate(evidence)]})
        issue = self.rules.issue_snapshot({"issue_id": "stable-issue", "mentions": [prior], "articles": [prior_article]})
        native = self.prompts.request_input("compare", mention=mention, issue=issue, article=article)
        return {"authorization": {"scope": "authored-test", "index": index},
                "pairs": {"pair-" + str(i): {"mentionKey": "incoming-mention", "targetIssueId": issue.issue_id,
                                               "input": copy.deepcopy(native)} for i in range(copies)},
                "retrievalMeaning": "authored bounded retrieval"}

    def test_article_catalog_is_lossless_and_keeps_whole_members_and_metadata(self):
        original = self.comparison_data(copies=4)
        before = copy.deepcopy(original)
        encoded = pipeline.comparison_catalogue_data(original)
        self.assertEqual(before, original)
        self.assertEqual(pipeline.COMPARISON_WIRE, encoded["comparisonWireVersion"])
        self.assertEqual(2, len(encoded["articleCatalog"]))
        self.assertEqual(original, pipeline.expand_comparison_catalogue(encoded))
        self.assertLess(len(pipeline.canonical(encoded)), len(pipeline.canonical(original)))
        for key, value in encoded["articleCatalog"].items():
            self.assertEqual(key, pipeline.digest(pipeline.canonical(value)))
            self.assertIn("body", value)
            self.assertIn("published_at", value)
            self.assertIn("allow_model_send", value)
        for key, pair in encoded["pairs"].items():
            self.assertEqual(original["pairs"][key]["input"]["mention"], pair["input"]["mention"])
            self.assertEqual(original["pairs"][key]["input"]["issue"]["mentions"], pair["input"]["issue"]["mentions"])
        tampered = copy.deepcopy(encoded)
        first = next(iter(tampered["articleCatalog"]))
        tampered["articleCatalog"][first]["body"] += " changed"
        with self.assertRaisesRegex(pipeline.Error, "reference_unbound"):
            pipeline.expand_comparison_catalogue(tampered)

    def test_nine_original_comparison_recordings_reuse_with_unchanged_prompt_and_receipts(self):
        native_output = self.root / "native"
        prompts = {"issue_comparison": "Original audited native comparison instructions."}
        transport = AuthoredIssueTransport()
        native = pipeline.IssueClient(native_output, transport, prompts, 400)
        schema = pipeline.obj({"comparisons": pipeline.obj({"pair-0": pipeline.obj({
            "relation": pipeline.strings(), "reason": pipeline.strings(), "evidence": {"type": "array", "items": {}}})})})
        results = [native.ask("issue_comparison", self.comparison_data(index, 1), schema, 18000) for index in range(9)]
        target = self.root / "catalog"
        target.mkdir(mode=0o700)
        shutil.copytree(native.calls, target / "calls")
        before = {p.name: p.read_bytes() for p in (target / "calls").glob("*")}
        def deny(_):
            raise AssertionError("old native recording must not be sent again")
        client = pipeline.IssueClient(target, deny, prompts, 400, comparison_wire=pipeline.COMPARISON_WIRE)
        for index, expected in enumerate(results):
            self.assertEqual(expected, client.ask("issue_comparison", self.comparison_data(index, 1), schema, 18000))
        self.assertEqual(0, len(client.new_calls))
        self.assertEqual(9, len(client.reused_calls))
        self.assertEqual(before, {p.name: p.read_bytes() for p in client.calls.glob("*")})
        data = self.comparison_data(9)
        request, _, prompt_sha = client.request("issue_comparison", data, "issue_comparison", "issue_comparison", 18000, schema)
        recorded = pipeline.base.strict_load(request)
        self.assertEqual(prompts["issue_comparison"] + pipeline.COMPARISON_CATALOG_INSTRUCTIONS, recorded["instructions"])
        self.assertEqual(pipeline.digest(recorded["instructions"].encode()), prompt_sha)
        self.assertEqual(data, pipeline.expand_comparison_catalogue(pipeline.base.strict_load(recorded["input"])))

    def test_optional_catalog_wire_preserves_same_event_result_and_native_default_identity(self):
        self.prepared(self.same_event_rows(2))
        native_args = self.args(True)
        native_args.comparison_batch_size = 2
        native_transport = SameEventTransport()
        with contextlib.redirect_stdout(io.StringIO()):
            native_result = pipeline.run(native_args, native_transport)
        native_archive = pipeline.base.strict_load((self.root / "output/grouped-issues.json").read_bytes())
        native_identity = pipeline.base.strict_load((self.root / "output/identity.json").read_bytes())
        self.assertNotIn("comparisonCodec", native_identity)
        catalog_args = self.args(True)
        catalog_args.comparison_batch_size = 2
        catalog_args.output = str(self.root / "catalog-output")
        catalog_args.comparison_wire = pipeline.COMPARISON_WIRE
        catalog_transport = SameEventTransport()
        with contextlib.redirect_stdout(io.StringIO()):
            catalog_result = pipeline.run(catalog_args, catalog_transport)
        catalog_archive = pipeline.base.strict_load((self.root / "catalog-output/grouped-issues.json").read_bytes())
        catalog_identity = pipeline.base.strict_load((self.root / "catalog-output/identity.json").read_bytes())
        self.assertEqual(native_result["assignmentCounts"], catalog_result["assignmentCounts"])
        self.assertEqual({"NEW": 1, "MERGE": 1, "HOLD": 0}, catalog_result["assignmentCounts"])
        self.assertEqual(native_archive["decisions"], catalog_archive["decisions"])
        self.assertEqual(native_archive["issues"], catalog_archive["issues"])
        codec = catalog_identity.pop("comparisonCodec")
        self.assertEqual(native_identity, catalog_identity)
        self.assertEqual(pipeline.COMPARISON_WIRE, codec["wireVersion"])
        self.assertEqual(native_identity["promptSha256"]["issue_comparison"], codec["nativePromptSha256"])
        native_requests = [pipeline.base.strict_load(raw) for raw in native_transport.calls]
        catalog_requests = [pipeline.base.strict_load(raw) for raw in catalog_transport.calls]
        self.assertEqual(native_requests[:2], catalog_requests[:2])
        native_request, catalog_request = native_requests[2], catalog_requests[2]
        self.assertEqual(pipeline.base.strict_load(native_request["input"]),
                         pipeline.expand_comparison_catalogue(pipeline.base.strict_load(catalog_request["input"])))
        self.assertEqual(codec["catalogPromptSha256"], pipeline.digest(catalog_request["instructions"].encode()))

    def test_catalog_wire_offline_is_explicit_and_never_calls_provider(self):
        self.prepared()
        native_args = self.args()
        catalog_args = self.args()
        catalog_args.comparison_wire = pipeline.COMPARISON_WIRE
        transport = AuthoredIssueTransport()
        native = pipeline.run(native_args, transport)
        catalog = pipeline.run(catalog_args, transport)
        self.assertNotEqual(native["identitySha256"], catalog["identitySha256"])
        self.assertEqual("OFFLINE", catalog["status"])
        self.assertEqual(0, catalog["newPaidCalls"])
        self.assertEqual([], transport.calls)
        self.assertFalse((self.root / "output").exists())

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
