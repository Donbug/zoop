"""Outlook-specific omissions must not pass as a complete market briefing."""

import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("outlook_fixtures", Path(__file__).with_name("test_briefing_market_context.py"))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
context = fixture.context
run_spec = importlib.util.spec_from_file_location("outlook_run", Path(__file__).parents[1] / "briefing_market_outlook_run.py")
runner = importlib.util.module_from_spec(run_spec)
run_spec.loader.exec_module(runner)


class MarketOutlookContractTest(unittest.TestCase):
    def frozen(self, morning=False):
        data, _, _ = fixture.input_data(morning=morning)
        data["context"]["summaryPromptVersion"] = "market-context-v2.1-outlook"
        data["contextSha256"] = context.base.digest(context.base.canonical(data["context"]))
        return context._prepare(data)

    def draft(self, frozen):
        evidence = frozen[1]
        return {"claims": [fixture.claim("合成根拠の計画です。", list(evidence)[:1]),
                           fixture.claim("合成観測値です。", indicators=["kospi"])]}

    def test_outlook_does_not_accept_only_fact_summary_when_targets_exist(self):
        values = self.frozen(); frozen, evidence, indicators, prior, evaluations, _ = values
        frozen["marketContext"]["forecastTargets"] = [fixture.target()]
        with self.assertRaisesRegex(context.ContextError, "outlook_forecast_required"):
            context._claims(self.draft(values), frozen, evidence, indicators, prior, evaluations)

    def test_existing_context_v2_is_not_retroactively_relabelled(self):
        values = self.frozen(); frozen, evidence, indicators, prior, evaluations, _ = values
        frozen["context"]["summaryPromptVersion"] = "market-context-v2"
        frozen["marketContext"]["forecastTargets"] = [fixture.target()]
        self.assertEqual(2, len(context._claims(self.draft(values), frozen, evidence, indicators, prior, evaluations)))

    def test_morning_must_explicitly_update_actual_previous_forecast(self):
        values = self.frozen(morning=True); frozen, evidence, indicators, _, evaluations, _ = values
        frozen["marketContext"]["previousPublication"]["status"] = "available"
        with self.assertRaisesRegex(context.ContextError, "outlook_update_required"):
            context._claims(self.draft(values), frozen, evidence, indicators, {"old": {}}, evaluations)

    def test_evening_must_compare_when_previous_publication_is_available(self):
        values = self.frozen(); frozen, evidence, indicators, prior, evaluations, _ = values
        frozen["marketContext"]["previousPublication"]["status"] = "available"
        with self.assertRaisesRegex(context.ContextError, "outlook_comparison_required"):
            context._claims(self.draft(values), frozen, evidence, indicators, prior, evaluations)

    def test_initial_missing_prior_is_not_invented(self):
        values = self.frozen(morning=True); frozen, evidence, indicators, prior, evaluations, _ = values
        self.assertEqual("unavailable", frozen["marketContext"]["previousPublication"]["status"])
        self.assertEqual(2, len(context._claims(self.draft(values), frozen, evidence, indicators, prior, evaluations)))

    def test_unpaid_derived_input_can_be_reauthorized_without_rewriting_paid_record(self):
        derived = {"summaryMode": "verified_issue_claims_and_indicators_v1", "marketEnrichment": {
            "summaryResult": None, "receipts": [], "context": {"userInboxRef": "old"}, "contextSha256": "old"}}
        paid = {"marketEnrichment": {"context": {"userInboxRef": "original-paid"}, "summaryResult": {"text": "unaltered"}}}
        old_paid = copy.deepcopy(paid)
        runner.rebind_derived_contexts({"rounds": [derived, paid]}, "new")
        self.assertEqual("new", derived["marketEnrichment"]["context"]["userInboxRef"])
        self.assertEqual(old_paid, paid)

    def test_paid_record_cannot_be_mislabelled_as_unpaid_for_rebinding(self):
        layer = {"rounds": [{"summaryMode": "verified_issue_claims_and_indicators_v1", "marketEnrichment": {
            "summaryResult": {"text": "paid"}, "receipts": [], "context": {"userInboxRef": "original"}}}]}
        with self.assertRaisesRegex(runner.context.ContextError, "derived_paid_record"):
            runner.rebind_derived_contexts(layer, "new")


if __name__ == "__main__":
    unittest.main()
