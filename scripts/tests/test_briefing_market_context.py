"""Authored context/forecast contracts; no provider, real market or credentials."""

import copy
from datetime import timedelta
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("market_context_tests", ROOT / "briefing_market_context.py")
context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(context)
spec = importlib.util.spec_from_file_location("market_context_legacy", ROOT / "tests/test_briefing_market_summary.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
base = context.base


def row(name, stamp, company="다른 시험 기업", body=None):
    body = body or (company + "의 반도체 공급 계약 계획은 아직 확정되지 않았습니다. ") * 12
    sha = base.digest(body.encode())
    return {"documentId": name, "documentVersion": "sha256-" + sha, "bodySha256": sha, "body": body,
            "clockTime": context.legacy._aware(stamp), "clockRecord": {"publishedAt": stamp}, "companyNames": [company]}


def target():
    return {"targetId": "authored-target", "indicatorId": "kospi", "valueKind": "close", "baselineDate": "2026-10-07",
            "baselineValue": 2500.0, "targetDate": "2026-10-08", "targetEnd": "2026-10-08T15:30:00+09:00",
            "calendarRef": "https://example.invalid/authored-calendar", "rule": "close_vs_baseline_v1"}


def prior(conditions=None):
    forecast = {"forecastId": "authored-forecast", "target": target(), "direction": "up", "text": "합성 조건부 상승 전망",
                "conditions": conditions or [], "counterFactors": ["합성 반대 요인"], "evidenceIds": ["news-one"], "indicatorIds": ["kospi"]}
    result = {"text": "직접 작성한 과거 판단", "verification": {"status": "PASS"}, "forecasts": [forecast]}
    return {"roundId": "authored-prior", "date": "2026-10-08", "edition": "morning", "cutoff": "2026-10-08T09:20:00+09:00",
            "summaryResult": result, "summaryResultSha256": base.digest(base.canonical(result))}


def input_data(morning=False, records=(), calendar=None):
    value = fixtures.data()
    edition, lower, upper = ("morning", "2026-10-07T17:30:00+09:00", "2026-10-08T09:20:00+09:00") if morning \
        else ("evening", "2026-10-08T09:20:00+09:00", "2026-10-08T17:30:00+09:00")
    round_ = {"roundId": "authored-round", "date": "2026-10-08", "edition": edition,
              "window": {"from": lower, "to": upper, "openStart": False}}
    snapshot = value["marketSnapshot"]
    snapshot["round"].update(edition=edition, cutoff=upper)
    snapshot["marketVariables"].update(referenceAt=upper, rateCutoffAt=upper)
    if morning:
        snapshot["marketVariables"]["indicators"][0]["observedDate"] = "2026-10-07"
    documents = [row("not-selected", lower, "다른 시험 기업"), row("new-not-selected", upper, "별도 시험 기업")]
    broad = context.build_context(documents, round_, snapshot, records, calendar, 2)
    value["marketContext"] = broad
    value["context"]["marketSnapshotSha256"] = base.digest(base.canonical(snapshot))
    value["context"]["marketContextSha256"] = base.digest(base.canonical(broad))
    value["contextSha256"] = base.digest(base.canonical(value["context"]))
    return value, documents, round_


def claim(text, evidence=(), indicators=(), kind="fact", **extra):
    return {"text": text, "kind": kind, "evidenceIds": list(evidence), "indicatorIds": list(indicators),
            "previousForecastIds": [], "previousPublicationIds": [], "evaluationIds": [], "targetId": None, "direction": None,
            "conditions": [], "counterFactors": [], "updateAction": None, **extra}


class ContextTransport:
    def __init__(self, mutate=None):
        self.requests, self.mutate = [], mutate

    def __call__(self, raw):
        self.requests.append(raw)
        request = base.strict_load(raw)
        data = base.strict_load(request["input"])
        stage = request["text"]["format"]["name"]
        if stage == "market_summary_generation":
            refs = sorted(context.context_evidence(data["marketContext"]))
            result = {"claims": [claim("다른 시험 기업도 미확정 공급 계약 계획을 발표했습니다.", refs[:1]),
                                  claim("제공된 지수는 해당 기준일의 일별 종가입니다.", indicators=["kospi"])]}
            if data["marketContext"]["forecastTargets"]:
                t = data["marketContext"]["forecastTargets"][0]
                result["claims"].append(claim("합성 근거가 지속되면 목표 세션의 상승 가능성이 있으나 반대 요인을 확인해야 합니다.",
                    refs[:1], ["kospi"], "forecast", targetId=t["targetId"], direction="up",
                    conditions=["합성 공급 계획이 유지되는 경우"], counterFactors=["확인되지 않은 수요 하락"] ))
            if data["allowedPreviousForecastIds"]:
                previous = data["allowedPreviousForecastIds"][0]
                if data["marketContext"]["edition"] == "morning":
                    result["claims"].append(claim("새 근거를 반영해 이전 조건부 판단을 유지합니다.", refs[:1], kind="forecast_update",
                        previousForecastIds=[previous], updateAction="maintain"))
                else:
                    result["claims"].append(claim("이전 전망의 평가 가능 여부는 제공된 조건과 관측 범위에 한정됩니다.",
                        kind="result_comparison", previousForecastIds=[previous], evaluationIds=data["allowedEvaluationIds"]))
            elif data["allowedPreviousPublicationIds"]:
                result["claims"].append(claim("직전 요약과 비교해 새 계약 검토 정보가 추가됐으며 가격 전망 평가는 제공하지 않습니다.",
                    refs[:1], kind="interpretation" if data["marketContext"]["edition"] == "morning" else "result_comparison",
                    previousPublicationIds=data["allowedPreviousPublicationIds"]))
        else:
            result = {"checks": {c["claimId"]: {"targetId": c["claimId"], "verdict": "SUPPORTED", "reason": "직접 작성한 합성 검증",
                **{k: True for k in ["noUnsupportedNumbers", "noUnsupportedCausality", "temporalAppropriate", "noInvestmentAdvice",
                                     "comparisonAppropriate", "forecastAppropriate"]}} for c in data["draft"]["claims"]}}
        if self.mutate:
            self.mutate(stage, result)
        return fixtures.response(result, raw)


class MarketContextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def client(self, transport):
        return context.legacy.MarketSummaryClient(Path(self.temp.name), transport, 12, prompt_root=context.PROMPTS)

    def test_all_eligible_unselected_companies_and_background_have_exact_quotes(self):
        data, rows, _ = input_data()
        broad = data["marketContext"]
        self.assertEqual(2, broad["coverage"]["documents"])
        self.assertEqual(1, broad["coverage"]["newDocuments"])
        self.assertEqual(1, broad["coverage"]["backgroundDocuments"])
        by_id = {r["documentId"]: r for r in rows}
        for document in broad["documents"]:
            for citation in document["sources"]:
                self.assertEqual(by_id[citation["documentId"]]["body"][citation["start"]:citation["end"]], citation["quote"])
        self.assertFalse(broad["coverage"]["marketRepresentative"])
        self.assertFalse(broad["coverage"]["sectorPriceFeedAvailable"])

    def test_future_is_excluded_and_lower_bound_is_background(self):
        data, rows, r = input_data()
        rows.append(row("future", "2026-10-09T00:00:00+09:00"))
        broad = context.build_context(rows, r, data["marketSnapshot"])
        self.assertEqual(2, len(broad["documents"]))
        self.assertEqual("background", next(d for d in broad["documents"] if d["documentId"] == "not-selected")["role"])

    def test_reposted_body_does_not_remove_new_window_source(self):
        data, rows, r = input_data()
        rows[1] = row("new-copy", r["window"]["to"], body=rows[0]["body"])
        broad = context.build_context(rows, r, data["marketSnapshot"])
        self.assertEqual({"new", "background"}, {d["role"] for d in broad["documents"]})

    def test_body_tamper_and_duplicate_identity_rejected(self):
        data, rows, r = input_data()
        rows[0]["body"] += "tampered"
        with self.assertRaisesRegex(context.ContextError, "body_digest"):
            context.build_context(rows, r, data["marketSnapshot"])
        _, rows, _ = input_data()
        with self.assertRaisesRegex(context.ContextError, "duplicate_document"):
            context.build_context([*rows, rows[0]], r, data["marketSnapshot"])

    def test_missing_or_withheld_immediate_prior_does_not_fall_back(self):
        data, _, r = input_data(records=[])
        old = prior()
        old["cutoff"] = "2026-10-07T09:20:00+09:00"
        self.assertEqual("unavailable", context.previous_publication(r, [old])["status"])
        current = prior(); current["summaryResult"]["verification"]["status"] = "WITHHELD"
        self.assertEqual("unavailable", context.previous_publication(r, [current])["status"])

    def test_previous_hash_tamper_and_duplicate_prior_rejected(self):
        _, _, r = input_data()
        p = prior(); p["summaryResult"]["text"] += "changed"
        with self.assertRaisesRegex(context.ContextError, "previous_result_digest"):
            context.previous_publication(r, [p])
        with self.assertRaisesRegex(context.ContextError, "ambiguous"):
            context.previous_publication(r, [prior(), prior()])

    def test_exact_finished_unconditional_forecast_can_be_compared(self):
        data, _, _ = input_data(records=[prior()])
        result = data["marketContext"]["forecastEvaluations"][0]
        self.assertEqual("evaluated", result["status"])
        self.assertEqual("up", result["actualDirection"])
        self.assertTrue(result["directionMatched"])

    def test_unobserved_conditions_never_become_wrong_forecast(self):
        data, _, _ = input_data(records=[prior(["未確認条件"])])
        result = data["marketContext"]["forecastEvaluations"][0]
        self.assertEqual("unavailable", result["status"])
        self.assertEqual("condition_outcomes_not_observed", result["reason"])
        self.assertIsNone(result["directionMatched"])

    def test_wrong_date_kind_or_incomplete_period_cannot_be_graded(self):
        for field, value in [("observedDate", "2026-10-07"), ("valueKind", "latest"), ("status", "unavailable")]:
            data, _, _ = input_data(records=[prior()])
            data["marketSnapshot"]["marketVariables"]["indicators"][0][field] = value
            p = context.previous_publication({"edition": "evening", "window": {"from": "2026-10-08T09:20:00+09:00", "to": "2026-10-08T17:30:00+09:00"}}, [prior()])
            with self.subTest(field=field):
                self.assertEqual("unavailable", context.evaluate_forecasts(p, data["marketSnapshot"])[0]["status"])

    def test_summary_really_receives_and_can_cite_unselected_company_evidence(self):
        data, _, _ = input_data()
        transport = ContextTransport()
        result = context.generate_market_summary(self.client(transport), data)
        self.assertEqual("PASS", result["verification"]["status"])
        self.assertTrue(result["evidenceIds"][0].startswith("market-evidence-"))
        self.assertNotIn(result["evidenceIds"][0], [s["evidenceId"] for item in data["selected"] for s in item["sources"]])
        self.assertEqual([], result["forecasts"])
        self.assertIn("가격 전망은 제공하지", result["scopeNote"])
        self.assertEqual(2, len(transport.requests))

    def test_evening_previous_forecast_and_evaluation_reach_independent_verifier(self):
        data, _, _ = input_data(records=[prior()])
        transport = ContextTransport()
        result = context.generate_market_summary(self.client(transport), data)
        self.assertEqual("PASS", result["verification"]["status"])
        self.assertTrue(any(c["kind"] == "result_comparison" for c in result["claims"]))
        request = base.strict_load(base.strict_load(transport.requests[-1])["input"])
        self.assertTrue(request["marketContext"]["forecastEvaluations"][0]["directionMatched"])

    def test_comparison_failure_withholds_instead_of_publishing(self):
        def mutate(stage, result):
            if stage == "market_summary_verification":
                next(iter(result["checks"].values()))["comparisonAppropriate"] = False
        data, _, _ = input_data(records=[prior()])
        result = context.generate_market_summary(self.client(ContextTransport(mutate)), data, max_repairs=0)
        self.assertEqual("WITHHELD", result["verification"]["status"])
        self.assertIsNone(result["summary"])

    def test_context_tamper_is_rejected_before_any_call(self):
        data, _, _ = input_data(); data["marketContext"]["documents"].pop()
        transport = ContextTransport()
        with self.assertRaisesRegex(context.ContextError, "context_digest"):
            context.generate_market_summary(self.client(transport), data)
        self.assertEqual([], transport.requests)

    def test_morning_updates_actual_previous_evening_forecast_without_grading_early(self):
        old = prior()
        old.update(date="2026-10-07", edition="evening", cutoff="2026-10-07T17:30:00+09:00")
        data, _, _ = input_data(morning=True, records=[old])
        result = context.generate_market_summary(self.client(ContextTransport()), data)
        self.assertEqual("PASS", result["verification"]["status"])
        update = next(c for c in result["claims"] if c["kind"] == "forecast_update")
        self.assertEqual(["authored-forecast"], update["previousForecastIds"])
        self.assertEqual("maintain", update["updateAction"])
        self.assertEqual("target_period_not_finished", result["forecastEvaluations"][0]["reason"])
        self.assertIsNone(result["forecastEvaluations"][0]["directionMatched"])

    def test_previous_text_can_be_compared_without_inventing_a_price_forecast(self):
        old = prior(); old["summaryResult"].pop("forecasts")
        old["summaryResultSha256"] = base.digest(base.canonical(old["summaryResult"]))
        data, _, _ = input_data(records=[old])
        result = context.generate_market_summary(self.client(ContextTransport()), data)
        comparison = next(c for c in result["claims"] if c["kind"] == "result_comparison")
        self.assertEqual([old["roundId"]], comparison["previousPublicationIds"])
        self.assertEqual([], comparison["previousForecastIds"])
        self.assertEqual([], result["forecasts"])

    def test_calendar_targets_exact_session_and_rejects_future_calendar_or_duplicates(self):
        data, _, r = input_data(morning=True)
        session = {"date": "2026-10-08", "tradingDay": True, "nextTradingDate": "2026-10-12",
                   "closeAt": "2026-10-08T15:30:00+09:00", "availableAt": "2026-10-01T00:00:00+09:00",
                   "sourceRef": "https://example.invalid/authored-calendar"}
        calendar = {"schemaVersion": "zoop-market-session-calendar-v1", "sessions": [session]}
        targets, reason = context.calendar_targets(calendar, r, data["marketSnapshot"])
        self.assertIsNone(reason)
        self.assertEqual(["kospi"], [t["indicatorId"] for t in targets])
        self.assertEqual("2026-10-08", targets[0]["targetDate"])
        self.assertTrue(targets[0]["targetId"].startswith("market-target-"))
        session["availableAt"] = "2026-10-08T10:00:00+09:00"
        with self.assertRaisesRegex(context.ContextError, "future_information"):
            context.calendar_targets(calendar, r, data["marketSnapshot"])
        session["availableAt"] = "2026-10-01T00:00:00+09:00"
        calendar["sessions"].append(copy.deepcopy(session))
        with self.assertRaisesRegex(context.ContextError, "duplicate"):
            context.calendar_targets(calendar, r, data["marketSnapshot"])

    def test_next_session_is_explicit_and_fx_reference_never_becomes_a_close_target(self):
        data, _, r = input_data()
        sessions = [{"date": date, "tradingDay": True, "nextTradingDate": "2026-10-12",
                     "closeAt": date + "T15:30:00+09:00", "availableAt": "2026-10-01T00:00:00+09:00",
                     "sourceRef": "https://example.invalid/authored-calendar"} for date in ["2026-10-08", "2026-10-12"]]
        calendar = {"schemaVersion": "zoop-market-session-calendar-v1", "sessions": sessions}
        targets, _ = context.calendar_targets(calendar, r, data["marketSnapshot"])
        self.assertEqual({"2026-10-12"}, {t["targetDate"] for t in targets})
        self.assertNotIn("usdkrw", [t["indicatorId"] for t in targets])
        sessions[1]["tradingDay"] = False
        self.assertEqual(([], "target_trading_session_missing"), context.calendar_targets(calendar, r, data["marketSnapshot"]))


if __name__ == "__main__":
    unittest.main()
