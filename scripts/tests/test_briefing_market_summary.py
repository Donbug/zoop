"""Authored offline news/market summaries; no real news, credentials, API or network."""

import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("summary", Path(__file__).resolve().parents[1] / "briefing_market_summary.py")
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)
base = summary.base


def data(available=True, two_issues=False):
    selected = [{"issueId": "issue-one", "companyNames": ["시험 기업"], "title": "직접 작성 합성 계약",
                 "sources": [{"evidenceId": "news-one", "documentId": "doc-one", "quote": "시험 기업이 공급 계약 계획을 발표했습니다. 계약 체결은 아직 확정되지 않았습니다."}]}]
    if two_issues:
        selected.append({"issueId": "issue-two", "companyNames": ["시험 기업"], "title": "별도 합성 연구",
                         "sources": [{"evidenceId": "news-two", "documentId": "doc-two", "quote": "같은 시험 기업이 별도 연구센터를 개소했습니다. 신규 채용 인원은 200명입니다."}]})
    snapshot = {"scope": "historical_snapshot", "round": {"date": "2026-10-08", "edition": "evening", "cutoff": "2026-10-08T17:30:00+09:00"},
                "fetchedAt": "2026-10-17T12:00:00+09:00", "rawRefs": [],
                "marketVariables": {"status": "available" if available else "unavailable", "referenceAt": "2026-10-08T17:30:00+09:00",
                    "rateCutoffAt": "2026-10-08T17:30:00+09:00", "collectedAt": "2026-10-17T12:00:00+09:00", "indicators": []}}
    if available:
        snapshot["marketVariables"]["indicators"] = [{"id": "kospi", "label": "KOSPI", "unit": "pt", "status": "ok", "value": 2500.5,
            "valueKind": "close", "observedDate": "2026-10-08", "observedAt": None, "baseline": {"date": "2026-10-07", "value": 2500.0, "at": None},
            "change": 0.5, "changeRate": 0.0002, "source": {"provider": "authored", "official": False}, "reason": None, "reasonCode": None},
            {"id": "kosdaq", "label": "KOSDAQ", "unit": "pt", "status": "failed", "value": None},
            {"id": "usdkrw", "label": "USD/KRW", "unit": "KRW", "status": "unavailable", "value": None}]
    context = {"newsResultSha256": "b" * 64, "marketSnapshotSha256": base.digest(base.canonical(snapshot)), "roundId": "authored-round"}
    return {"context": context, "contextSha256": base.digest(base.canonical(context)), "selected": selected,
            "newsItems": [{"issueId": item["issueId"], "title": item["title"], "claims": []} for item in selected], "marketSnapshot": snapshot}


def response(value, request):
    return 200, base.canonical({"id": "authored-" + base.digest(request)[:16], "status": "completed",
        "usage": {"input_tokens": 100, "output_tokens": 40}, "output": [{"type": "message", "content": [{"type": "output_text", "text": base.canonical(value).decode()}]}]})


class Transport:
    def __init__(self, fail=False, repair_pass=False, mutate=None):
        self.requests = []
        self.fail, self.repair_pass, self.mutate = fail, repair_pass, mutate
        self.verifications = 0

    def __call__(self, raw):
        self.requests.append(raw)
        request = base.strict_load(raw)
        value = base.strict_load(request["input"])
        stage = request["text"]["format"]["name"]
        if stage == "market_summary_generation":
            news = value["allowedEvidenceIds"][0]
            claims = [{"text": "시험 기업이 공급 계약 계획을 발표했습니다.", "evidenceIds": [news], "indicatorIds": []}]
            if value["allowedIndicatorIds"]:
                claims.append({"text": "제공된 KOSPI 종가는 2500.5pt입니다.", "evidenceIds": [], "indicatorIds": ["kospi"]})
            else:
                claims.append({"text": "계약 체결은 아직 확정되지 않았습니다.", "evidenceIds": [news], "indicatorIds": []})
            if self.repair_pass and value["repairAttempt"] > 0:
                claims[0]["text"] = "시험 기업의 공급 계약은 확정 체결 전인 계획 단계입니다."
            result = {"claims": claims}
        else:
            self.verifications += 1
            fail = self.fail and not (self.repair_pass and self.verifications > 1)
            result = {"checks": {claim["claimId"]: {"targetId": claim["claimId"], "verdict": "UNSUPPORTED" if fail else "SUPPORTED",
                "noUnsupportedNumbers": not fail, "noUnsupportedCausality": True, "temporalAppropriate": True, "noInvestmentAdvice": True,
                "reason": "직접 작성한 합성 근거에 따른 시험 검증 결과"} for claim in value["draft"]["claims"]}}
        if self.mutate:
            self.mutate(stage, result)
        return response(result, raw)


class MarketSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "calls-output"

    def tearDown(self):
        self.temp.cleanup()

    def client(self, transport):
        return summary.MarketSummaryClient(self.root, transport, max_calls=8)

    def test_structurally_rejected_repair_clears_prior_claims_and_verifier_but_preserves_attempts(self):
        generations = 0
        def mutate(stage, result):
            nonlocal generations
            if stage == "market_summary_generation":
                generations += 1
                if generations == 2:
                    for claim in result["claims"]:
                        claim.update(evidenceIds=[], indicatorIds=["kospi"])
        transport = Transport(fail=True, mutate=mutate)
        result = summary.generate_market_summary(self.client(transport), data())
        self.assertEqual("WITHHELD", result["verification"]["status"])
        self.assertEqual([], result["claims"])
        self.assertIsNone(result["verificationRequestDigest"])
        self.assertIsNone(result["summary"])
        self.assertEqual(2, len(result["attempts"]))
        self.assertIn("verificationRequestDigest", result["attempts"][0])
        self.assertEqual(3, len(result["usage"]))
        self.assertEqual(3, len(transport.requests))

    def test_separate_model_verification_and_public_aggregation(self):
        transport = Transport()
        result = summary.generate_market_summary(self.client(transport), data())
        self.assertEqual("PASS", result["verification"]["status"])
        self.assertEqual(2, len(transport.requests))
        self.assertEqual(["news-one"], result["summary"]["evidenceIds"])
        self.assertEqual("\n".join([*(claim["text"] for claim in result["claims"]), result["scopeNote"]]), result["text"])
        self.assertEqual(result["text"], result["summary"]["text"])
        self.assertIn("시장 전체를 대표", result["text"])
        self.assertIn("미확보 지표는 제외", result["text"])
        self.assertTrue(result["resultVersion"].startswith("market-summary-"))
        self.assertEqual("kospi", result["claims"][1]["indicatorIds"][0])
        for raw in transport.requests:
            request = base.strict_load(raw)
            self.assertEqual("gpt-6-luna", request["model"])
            self.assertFalse(request["store"])
            self.assertTrue(request["text"]["format"]["strict"])
        self.assertEqual(2, len(result["usage"]))

    def test_same_company_distinct_selected_news_is_allowed(self):
        result = summary.generate_market_summary(self.client(Transport()), data(two_issues=True))
        self.assertEqual("PASS", result["verification"]["status"])

    def test_unavailable_market_still_allows_grounded_news_only_summary(self):
        result = summary.generate_market_summary(self.client(Transport()), data(available=False))
        self.assertEqual("PASS", result["verification"]["status"])
        self.assertTrue(all(not claim["indicatorIds"] for claim in result["claims"]))
        self.assertIn("선정된 뉴스만", result["scopeNote"])
        self.assertNotIn("KOSPI", result["text"])

    def test_wrong_news_or_unavailable_indicator_ids_fail_schema_closed(self):
        for field, ref in (("evidenceIds", "other-round-evidence"), ("indicatorIds", "usdkrw")):
            def mutate(stage, result):
                if stage == "market_summary_generation":
                    result["claims"][0][field] = [ref]
            with self.subTest(field=field):
                separate = summary.MarketSummaryClient(Path(self.temp.name) / field, Transport(mutate=mutate), max_calls=4)
                with self.assertRaisesRegex(base.ReplayError, "structured_output_enum_mismatch"):
                    summary.generate_market_summary(separate, data())

    def test_missing_claim_refs_never_produces_public_text(self):
        def mutate(stage, result):
            if stage == "market_summary_generation":
                for claim in result["claims"]:
                    claim["evidenceIds"], claim["indicatorIds"] = [], []
        transport = Transport(mutate=mutate)
        result = summary.generate_market_summary(self.client(transport), data())
        self.assertEqual("WITHHELD", result["verification"]["status"])
        self.assertEqual(2, len(transport.requests))
        self.assertIsNone(result["summary"])
        self.assertIsNone(result["text"])
        self.assertEqual([], result["evidenceIds"])

    def test_only_indicator_claims_cannot_bypass_news_evidence_requirement(self):
        def mutate(stage, result):
            if stage == "market_summary_generation":
                for claim in result["claims"]:
                    claim["text"], claim["evidenceIds"], claim["indicatorIds"] = "제공된 지표만 설명합니다.", [], ["kospi"]
        result = summary.generate_market_summary(self.client(Transport(mutate=mutate)), data())
        self.assertEqual("market_summary_news_evidence_required", result["verification"]["reason"])
        self.assertIsNone(result["summary"])

    def test_one_bounded_repair_uses_identical_frozen_input(self):
        transport = Transport(fail=True, repair_pass=True)
        result = summary.generate_market_summary(self.client(transport), data())
        self.assertEqual("PASS", result["verification"]["status"])
        self.assertEqual(4, len(transport.requests))
        self.assertEqual([0, 1], [attempt["attempt"] for attempt in result["attempts"]])
        requests = [base.strict_load(base.strict_load(raw)["input"]) for raw in transport.requests]
        self.assertEqual(1, len({r["frozenInputSha256"] for r in requests}))
        self.assertEqual(requests[0]["marketSnapshot"], requests[2]["marketSnapshot"])
        self.assertIsNotNone(requests[2]["priorValidation"])

    def test_unresolved_numeric_fabrication_withholds_after_one_repair(self):
        def fabricate(stage, result):
            if stage == "market_summary_generation":
                result["claims"][1]["text"] = "제공된 KOSPI 종가는 9999pt입니다."
        transport = Transport(fail=True, mutate=fabricate)
        result = summary.generate_market_summary(self.client(transport), data())
        self.assertEqual("WITHHELD", result["verification"]["status"])
        # Identical repaired draft reuses the completed failed verification; no blind retry.
        self.assertEqual(3, len(transport.requests))
        self.assertIsNone(result["summary"])
        self.assertIsNone(result["resultVersion"])

    def test_one_causality_false_flag_withholds_whole_summary(self):
        def mutate(stage, result):
            if stage == "market_summary_verification":
                next(iter(result["checks"].values()))["noUnsupportedCausality"] = False
        result = summary.generate_market_summary(self.client(Transport(mutate=mutate)), data(), max_repairs=0)
        self.assertEqual("WITHHELD", result["verification"]["status"])
        self.assertIsNone(result["text"])

    def test_missing_verification_target_fails_closed(self):
        def mutate(stage, result):
            if stage == "market_summary_verification":
                result["checks"].pop(next(iter(result["checks"])))
        with self.assertRaisesRegex(base.ReplayError, "structured_output_membership_mismatch"):
            summary.generate_market_summary(self.client(Transport(mutate=mutate)), data())

    def test_empty_generation_fails_closed_without_retry(self):
        def mutate(stage, result):
            if stage == "market_summary_generation":
                result["claims"] = []
        transport = Transport(mutate=mutate)
        with self.assertRaisesRegex(base.ReplayError, "structured_output_array_bounds"):
            summary.generate_market_summary(self.client(transport), data())
        self.assertEqual(1, len(transport.requests))

    def test_future_or_misaligned_observation_never_reaches_model(self):
        for field, value in (("observedDate", "2026-10-09"), ("observedAt", "2026-10-08T18:00:00+09:00"),
                             ("observedAt", "2026-10-07T12:00:00+09:00")):
            current = data()
            current["marketSnapshot"]["marketVariables"]["indicators"][0][field] = value
            current["context"]["marketSnapshotSha256"] = base.digest(base.canonical(current["marketSnapshot"]))
            transport = Transport()
            with self.subTest(field=field, value=value):
                with self.assertRaises(summary.MarketSummaryError):
                    summary.generate_market_summary(self.client(transport), current)
                self.assertEqual([], transport.requests)

    def test_daily_close_null_time_and_previous_delayed_fx_are_accepted(self):
        current = data()
        fx = current["marketSnapshot"]["marketVariables"]["indicators"][2]
        fx.update({"status": "delayed", "value": 1300.0, "valueKind": "close", "observedDate": "2026-10-07", "observedAt": None,
                   "baseline": None, "change": None, "changeRate": None, "reason": "Bank daily reference, not market close or live quote."})
        current["marketSnapshot"]["marketVariables"]["rateCutoffAt"] = "2026-10-08T17:00:00+09:00"
        current["context"]["marketSnapshotSha256"] = base.digest(base.canonical(current["marketSnapshot"]))
        result = summary.generate_market_summary(self.client(Transport()), current)
        self.assertEqual("PASS", result["verification"]["status"])

    def test_explicit_bank_reference_is_accepted_but_index_reference_is_rejected(self):
        current = data()
        fx = current["marketSnapshot"]["marketVariables"]["indicators"][2]
        fx.update({"status": "delayed", "value": 1300.0, "valueKind": "reference", "observedDate": "2026-10-07", "observedAt": None,
                   "baseline": None, "change": None, "changeRate": None})
        current["context"]["marketSnapshotSha256"] = base.digest(base.canonical(current["marketSnapshot"]))
        result = summary.generate_market_summary(self.client(Transport()), current)
        self.assertEqual("PASS", result["verification"]["status"])
        current["marketSnapshot"]["marketVariables"]["indicators"][0]["valueKind"] = "reference"
        current["context"]["marketSnapshotSha256"] = base.digest(base.canonical(current["marketSnapshot"]))
        with self.assertRaisesRegex(summary.MarketSummaryError, "unit_or_kind_invalid"):
            summary.generate_market_summary(self.client(Transport()), current)

    def test_missing_value_cannot_be_zero_filled_or_cited(self):
        current = data()
        current["marketSnapshot"]["marketVariables"]["indicators"][1]["value"] = 0
        current["context"]["marketSnapshotSha256"] = base.digest(base.canonical(current["marketSnapshot"]))
        with self.assertRaisesRegex(summary.MarketSummaryError, "missing_indicator_has_value"):
            summary.generate_market_summary(self.client(Transport()), current)

    def test_snapshot_hash_and_news_coverage_are_checked(self):
        current = data()
        current["marketSnapshot"]["fetchedAt"] = "2026-10-18T12:00:00+09:00"
        with self.assertRaisesRegex(summary.MarketSummaryError, "snapshot_digest_mismatch"):
            summary.generate_market_summary(self.client(Transport()), current)
        current = data()
        current["newsItems"][0]["issueId"] = "foreign-issue"
        with self.assertRaisesRegex(summary.MarketSummaryError, "news_selected_coverage_mismatch"):
            summary.generate_market_summary(self.client(Transport()), current)

    def test_market_only_or_empty_input_is_withheld_without_paid_calls(self):
        current = data()
        current["selected"], current["newsItems"] = [], []
        transport = Transport()
        result = summary.generate_market_summary(self.client(transport), current)
        self.assertEqual("WITHHELD", result["verification"]["status"])
        self.assertEqual([], transport.requests)
        self.assertIsNone(result["summary"])

    def test_repair_budget_cannot_be_increased_or_boolean(self):
        for repairs in (-1, 2, True):
            with self.assertRaisesRegex(summary.MarketSummaryError, "repair_limit_invalid"):
                summary.generate_market_summary(self.client(Transport()), data(), repairs)

    def test_completed_paid_receipts_are_reused_without_new_transport_call(self):
        current = data()
        first = summary.generate_market_summary(self.client(Transport()), current)
        transport = Transport()
        second = summary.generate_market_summary(self.client(transport), current)
        self.assertEqual([], transport.requests)
        self.assertEqual(base.canonical(first), base.canonical(second))


    def test_unknown_http_outcome_never_retries_automatically(self):
        calls = []
        def unknown(raw):
            calls.append(raw)
            raise OSError("authored transport outcome unknown")
        client = self.client(unknown)
        with self.assertRaisesRegex(base.ReplayError, "transport_unknown_usage_no_automatic_retry"):
            summary.generate_market_summary(client, data())
        self.assertEqual(1, len(calls))
        self.assertFalse(client.receipts()[0]["usageKnown"])

    def test_naive_cutoff_or_nonfinite_indicator_never_reaches_model(self):
        for field in ("cutoff", "value"):
            current = data()
            if field == "cutoff":
                current["marketSnapshot"]["round"]["cutoff"] = "2026-10-08T17:30:00"
                current["context"]["marketSnapshotSha256"] = base.digest(base.canonical(current["marketSnapshot"]))
            else:
                current["marketSnapshot"]["marketVariables"]["indicators"][0]["value"] = float("inf")
            transport = Transport()
            with self.subTest(field=field):
                with self.assertRaises((summary.MarketSummaryError, ValueError)):
                    summary.generate_market_summary(self.client(transport), current)
                self.assertEqual([], transport.requests)


if __name__ == "__main__":
    unittest.main()
