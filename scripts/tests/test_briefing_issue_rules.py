"""Real-team contract/identity regressions; no source fixture or provider calls."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "briefing_issue_rules.py"
SPEC = importlib.util.spec_from_file_location("briefing_issue_rules_under_test", PATH)
rules_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rules_module)


class TeamIssueRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = os.environ.get("ZOOP_TEST_POC_ROOT")
        if not cls.root:
            raise unittest.SkipTest("ZOOP_TEST_POC_ROOT must name the separately supplied audited team checkout")
        cls.rules = rules_module.IssueRules(cls.root)

    def setUp(self):
        self.article = self.rules.article({"article_id": "article-incoming", "url": "https://example.com/a",
            "title": "Example", "body": "Alpha announced the chip in 2026. This sentence is evidence.", "publisher": "example",
            "published_at": "2026-10-07T09:00:00+09:00", "collected_at": "2026-10-07T09:05:00+09:00"})
        self.mention = self.make_mention(self.article)
        self.prior_article = self.rules.article({**self.article.model_dump(), "article_id": "article-prior"})
        self.prior = self.make_mention(self.prior_article)
        self.issue = self.rules.issue_snapshot({"issue_id": "issue-existing", "mentions": [self.prior],
                                                "articles": [self.prior_article]})

    def evidence(self, article):
        quote = "Alpha announced the chip in 2026."
        return {"article_id": article.article_id, "article_version": article.version,
                "start": 0, "end": len(quote), "quote": quote}

    def make_mention(self, article, **updates):
        return self.rules.domain.Mention.model_validate({"mention_id": "mention-a", "article_id": article.article_id,
            "article_version": article.version, "title": "Chip announcement", "event_type": "announcement",
            "action": "announced", "target": "chip", "event_time": "2026-10-07", "period": "2026",
            "assertion_status": "announced", "participants": [{"company_id": "company-alpha", "name": "Alpha", "role": "announcer"}],
            "evidence": [self.evidence(article)], **updates}, strict=True)

    def decision(self, relation="SAME", evidence=None):
        return self.rules.domain.PairDecision.model_validate({"relation": relation, "reason": "source comparison",
            "evidence": [self.evidence(self.article)] if evidence is None else evidence}, strict=True)

    def test_actual_contract_is_used_and_collection_time_is_not_version(self):
        self.assertTrue(type(self.article).__module__.startswith("_zoop_team_issue_"))
        changed = self.rules.article({**self.article.model_dump(), "collected_at": "2030-01-01T00:00:00Z"})
        self.assertEqual(self.article.version, changed.version)
        self.assertFalse(self.rules.identity()["fullPipelineExecuted"])

    def test_source_drift_fails_before_import(self):
        with patch.dict(rules_module.SOURCE_HASHES, {"search.py": "0" * 64}):
            with self.assertRaisesRegex(rules_module.IssueRulesError, "team_poc_source_changed"):
                rules_module.IssueRules(self.root)

    def test_extraction_requires_exact_quote_and_version(self):
        self.rules.extraction({"mentions": [self.mention]}, self.article)
        for update in [{"article_version": "wrong"}, {"evidence": []},
                       {"evidence": [{**self.evidence(self.article), "quote": "unsupported quote"}]}]:
            with self.subTest(update=update), self.assertRaises(rules_module.IssueRulesError):
                self.rules.extraction({"mentions": [{**self.mention.model_dump(), **update}]}, self.article)

    def test_duplicate_mentions_rejected(self):
        with self.assertRaisesRegex(rules_module.IssueRulesError, "duplicate"):
            self.rules.extraction({"mentions": [self.mention, self.mention]}, self.article)

    def test_same_merges_only_single_whole_issue(self):
        result = self.rules.assign(self.mention, self.article, [(self.issue, self.decision())])
        self.assertEqual("MERGE", result["status"])
        self.assertEqual(self.issue.issue_id, result["issueId"])
        self.assertFalse(result["approved"])

    def test_conflicting_non_nearest_member_forbids_same(self):
        other = self.prior.model_copy(update={"mention_id": "mention-b", "period": "2027"})
        issue = self.issue.model_copy(update={"mentions": [self.prior, other]})
        effective = self.rules.effective_comparison(self.mention, issue, self.article, self.decision())
        self.assertEqual("DIFFERENT", effective.relation)
        self.assertEqual("NEW", self.rules.assign(self.mention, self.article, [(issue, self.decision())])["status"])

    def test_absent_identity_fields_are_not_invented(self):
        prior = self.prior.model_copy(update={"event_time": None, "period": None})
        issue = self.issue.model_copy(update={"mentions": [prior]})
        self.assertEqual("SAME", self.rules.effective_comparison(self.mention, issue, self.article, self.decision()).relation)

    def test_same_without_exact_comparison_evidence_is_held(self):
        effective = self.rules.effective_comparison(self.mention, self.issue, self.article, self.decision(evidence=[]))
        self.assertEqual("HOLD", effective.relation)

    def test_follows_requires_incoming_evidence(self):
        decision = self.decision("FOLLOWS", [self.evidence(self.prior_article)])
        self.assertEqual("HOLD", self.rules.effective_comparison(self.mention, self.issue, self.article, decision).relation)
        result = self.rules.assign(self.mention, self.article, [(self.issue, self.decision("FOLLOWS"))])
        self.assertEqual("NEW", result["status"])
        self.assertEqual([self.issue.issue_id], result["follows"])

    def test_multiple_same_and_unresolved_comparison_hold(self):
        second = self.issue.model_copy(update={"issue_id": "issue-second"})
        for decision in [self.decision(), self.decision("CONFLICT", []), self.decision("HOLD", [])]:
            with self.subTest(decision=decision.relation):
                result = self.rules.assign(self.mention, self.article,
                    [(self.issue, self.decision()), (second, decision)])
                self.assertEqual("HOLD", result["status"])

    def test_duplicate_target_cannot_manufacture_multiple_same(self):
        with self.assertRaisesRegex(rules_module.IssueRulesError, "duplicate_comparison_target"):
            self.rules.assign(self.mention, self.article, [(self.issue, self.decision()), (self.issue, self.decision())])

    def test_new_issue_id_matches_team_expression_and_is_stable(self):
        first = self.rules.assign(self.mention, self.article, [])
        expected = "issue-" + self.rules.domain.digest({"article": self.article.article_id,
            "version": self.article.version, "mention": self.mention.mention_id})[:24]
        self.assertEqual(expected, first["issueId"])
        self.assertEqual(first, self.rules.assign(self.mention, self.article, []))

    def test_snapshot_requires_all_member_sources(self):
        issue = self.issue.model_copy(update={"articles": [self.article]})
        with self.assertRaisesRegex(rules_module.IssueRulesError, "snapshot_mention_source_missing"):
            self.rules.issue_snapshot(issue)

    def test_original_numerical_decision_uses_probability_not_confidence(self):
        observation = {"question_id": "q", "target": "issue", "check": "source support", "choice": "SUPPORTED",
            "probabilities": {"SUPPORTED": .95, "CONTRADICTED": .02, "INSUFFICIENT": .03}, "confidence": .1}
        self.assertEqual("ALLOW", self.rules.classify_observation(observation))
        observation["probabilities"] = {"SUPPORTED": .91, "CONTRADICTED": .02, "INSUFFICIENT": .08}
        self.assertEqual("HOLD", self.rules.classify_observation(observation))


if __name__ == "__main__":
    unittest.main()
