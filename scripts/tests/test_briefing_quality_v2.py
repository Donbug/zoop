"""Offline integration coverage for source-bound selection and across-round novelty."""

import copy
import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
LEGACY_SPEC = importlib.util.spec_from_file_location("quality_legacy_fixtures", HERE / "test_briefing_round_simulation.py")
legacy = importlib.util.module_from_spec(LEGACY_SPEC)
LEGACY_SPEC.loader.exec_module(legacy)
sim = legacy.sim
quality = sim.helper("briefing_quality")


class V2Transport(legacy.AuthoredTransport):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cross_document_quote = False
        self.freeform_quote = False

    def __call__(self, raw):
        request = sim.base.strict_load(raw)
        data = sim.base.strict_load(request["input"])
        stage = request["text"]["format"]["name"]
        if stage in {"round_simulation_novelty", "round_simulation_novelty_verification"}:
            self.requests.append(raw)
            prior = data["noveltyHistory"][0]["issueId"]
            result = {"decisions": {row["documentId"]: {
                "documentId": row["documentId"], "decision": "REPEAT" if "repeat" in row["documentId"] else "NEW_EVENT",
                "matchedIssueId": prior if "repeat" in row["documentId"] else None,
                "reason": "같은 사건의 후속 재보도" if "repeat" in row["documentId"] else "별도 계약 사건",
                "delta": "", "quoteIds": [row["quoteCatalog"][0]["quoteId"]]} for row in data["documents"]}}
            return legacy.response(result, raw)
        if stage == "round_simulation_selection" and data.get("qualityPolicy") == sim.QUALITY_V2:
            self.requests.append(raw)
            choices = []
            for row in data["documents"][:3]:
                source = {"documentId": row["documentId"], "quoteIds": [row["quoteCatalog"][0]["quoteId"]]}
                if self.freeform_quote:
                    source = {"documentId": row["documentId"], "quotes": ["This translation is absent from the Korean original source."]}
                if self.cross_document_quote:
                    source["quoteIds"] = [data["documents"][-1]["quoteCatalog"][0]["quoteId"]]
                choices.append({"eventKey": row["assessment"]["eventKey"], "title": "합성 계약 계획", "reason": "직접 작성한 계약 근거",
                    "importance": 2, "priority": 75, "companyNames": row["companyNames"], "limitations": ["오프라인 합성 시험"],
                    "sources": [source], "scope": "COMPANY", "affectedSectors": [], "transmission": ""})
            return legacy.response({"selected": choices, "held": []}, raw)
        return super().__call__(raw)


def published(round_id="first", issue_id="issue-one", end="2026-10-02T09:20:00+09:00", status="SELECTED", verified="PASS"):
    body = "직접 작성한 시험 기업의 연구센터 계획이며 사실로 이용할 수 없는 합성 원문입니다."
    selected = {"issueId": issue_id, "eventKey": "센터계획", "companyNames": ["시험 기업"],
                "sources": [{"documentId": "source-one", "bodySha256": sim.digest(body.encode()), "quote": body,
                             "evidenceId": "evidence-one", "url": "https://example.invalid/source-one"}]}
    result = {"verification": {"status": verified}, "items": [{"issueId": issue_id, "title": "합성 연구센터 계획",
                                                               "claims": [{"text": "연구센터 설립 계획", "type": "plan"}]}]}
    return {"roundId": round_id, "window": {"to": end}, "selectionStatus": status, "selected": [selected],
            "result": result, "resultSha256": sim.digest(sim.canonical(result))}


class QualityV2Test(unittest.TestCase):
    setUp = legacy.RoundSimulationTest.setUp
    tearDown = legacy.RoundSimulationTest.tearDown
    prepare = legacy.RoundSimulationTest.prepare

    def args(self):
        args = legacy.RoundSimulationTest.args(self, True)
        args.quality_policy = sim.QUALITY_V2
        args.max_repairs = 0
        return args

    def run_fixture(self, rows, transport=None):
        self.prepare(rows)
        transport = transport or V2Transport()
        summary = sim.run(self.args(), transport)
        bundle = sim.base.strict_load((self.output / "bundle-v2.json").read_bytes())
        return summary, bundle, transport

    def test_default_policy_is_v2_and_legacy_remains_explicit(self):
        args = sim.parser().parse_args(["--sources", "s", "--clocks", "c", "--output", "o", "--user-inbox-ref", "i"])
        self.assertEqual(sim.QUALITY_V2, args.quality_policy)
        self.assertEqual("legacy-v1", legacy.RoundSimulationTest.args(self, True).quality_policy)

    def test_quote_catalog_preserves_full_unicode_body_and_code_point_offsets(self):
        body = ("😀 한글 공백\n\n" * 301) + "tail-끝부분-공백  "
        row = {"documentId": "unicode-document", "body": body, "bodySha256": sim.digest(body.encode())}
        catalog = quality.quote_catalog(row)
        self.assertEqual(body, "".join(q["text"] for q in catalog))
        self.assertEqual(0, catalog[0]["start"])
        self.assertEqual(len(body), catalog[-1]["end"])
        for index, quote in enumerate(catalog):
            self.assertEqual(body[quote["start"]:quote["end"]], quote["text"])
            self.assertEqual(row["bodySha256"], quote["bodySha256"])
            if index:
                self.assertEqual(catalog[index - 1]["end"], quote["start"])

    def test_exact_body_restoration_never_translates_or_mutates_response(self):
        body = "삼성전자 회사 이름을 포함한 직접 작성 합성 계약 원문입니다.\n  원래 공백과 줄바꿈을 그대로 유지합니다.😀"
        candidates = quality.catalog_candidates([{"documentId": "doc", "body": body}])
        quote = candidates[0]["quoteCatalog"][0]
        reply = {"selected": [{"sources": [{"documentId": "doc", "quoteIds": [quote["quoteId"]]}]}]}
        before = copy.deepcopy(reply)
        restored = quality.restore_selection(reply, candidates)
        self.assertEqual(body, restored["selected"][0]["sources"][0]["quotes"][0])
        self.assertEqual(before, reply)

    def test_quote_catalog_body_digest_mismatch_rejected(self):
        with self.assertRaisesRegex(quality.QualityError, "body_digest_mismatch"):
            quality.quote_catalog({"documentId": "doc", "body": "직접 작성 합성 원문입니다." * 3, "bodySha256": "0" * 64})

    def test_freeform_translated_quote_is_rejected_by_actual_v2_schema(self):
        self.prepare([legacy.source("morning", "2026-10-02T09:00:00+09:00")])
        transport = V2Transport()
        transport.freeform_quote = True
        with self.assertRaisesRegex(sim.ReplayError, "structured_output_membership_mismatch"):
            sim.run(self.args(), transport)
        self.assertFalse((self.output / "bundle-v2.json").exists())

    def test_quote_id_from_another_document_rejected_after_schema_validation(self):
        self.prepare([legacy.source("a-doc", "2026-10-02T09:00:00+09:00"),
                      legacy.source("b-doc", "2026-10-02T09:01:00+09:00")])
        transport = V2Transport()
        transport.cross_document_quote = True
        with self.assertRaisesRegex(sim.ReplayError, "quote_id_does_not_belong_to_document"):
            sim.run(self.args(), transport)
        self.assertFalse((self.output / "bundle-v2.json").exists())

    def test_published_history_includes_only_earlier_selected_pass(self):
        first = published()
        held = published("held", "issue-held", status="HELD_VALIDATION")
        failed = published("failed", "issue-failed", verified="WITHHELD")
        history = quality.published_history([first, held, failed], "2026-10-02T09:20:00+09:00")
        self.assertEqual(["issue-one"], [item["issueId"] for item in history])
        self.assertEqual(first["selected"][0]["sources"], history[0]["sources"])
        self.assertEqual("센터계획", history[0]["eventKey"])

    def test_future_or_naive_history_is_rejected_even_if_held(self):
        for round_, error in ((published(end="2026-10-02T17:30:00+09:00", status="HELD_VALIDATION"), "future_round"),
                              (published(end="2026-10-02T09:20:00"), "timestamp_naive")):
            with self.subTest(error=error):
                with self.assertRaisesRegex(quality.QualityError, error):
                    quality.published_history([round_], "2026-10-02T09:20:00+09:00")

    def test_history_result_sha_and_generated_issue_membership_are_verified(self):
        altered = published()
        altered["result"]["items"][0]["title"] = "변조"
        with self.assertRaisesRegex(quality.QualityError, "result_digest_mismatch"):
            quality.published_history([altered], "2026-10-02T09:20:00+09:00")
        altered = published()
        altered["result"]["items"] = []
        altered["resultSha256"] = sim.digest(sim.canonical(altered["result"]))
        with self.assertRaisesRegex(quality.QualityError, "item_missing"):
            quality.published_history([altered], "2026-10-02T09:20:00+09:00")

    def test_repeat_is_removed_before_max_three_selection_and_other_candidates_backfill(self):
        summary, bundle, transport = self.run_fixture([
            legacy.source("morning-first", "2026-10-02T09:00:00+09:00"),
            *[legacy.source(document, "2026-10-02T10:00:00+09:00")
              for document in ("a-repeat", "b-new-contract", "c-new-product", "d-new-results")]])
        evening = bundle["rounds"][1]
        self.assertEqual("SELECTED", evening["selectionStatus"])
        selected_documents = {s["documentId"] for item in evening["selected"] for s in item["sources"]}
        self.assertEqual({"b-new-contract", "c-new-product", "d-new-results"}, selected_documents)
        self.assertEqual(["a-repeat"], evening["noveltyAudit"]["excludedDocumentIds"])
        self.assertEqual(2, summary["selectedRounds"])
        for item in evening["selected"]:
            self.assertEqual("server_literal_catalog_v2", item["quoteBindingPolicy"])
            self.assertTrue(item["eventKey"])
        selections = [sim.base.strict_load(raw) for raw in transport.requests
                      if sim.base.strict_load(raw)["text"]["format"]["name"] == "round_simulation_selection"]
        evening_request = sim.base.strict_load(selections[1]["input"])
        self.assertEqual(3, len(evening_request["documents"]))
        self.assertTrue(all(d["quoteCatalog"] for d in evening_request["documents"]))

    def test_novelty_memory_survives_empty_round_but_immediate_previous_does_not(self):
        _, bundle, transport = self.run_fixture([
            legacy.source("first", "2026-10-02T09:00:00+09:00"),
            legacy.source("a-repeat", "2026-10-02T10:00:00+09:00"),
            legacy.source("third-new-contract", "2026-10-02T20:00:00+09:00")])
        first, repeated, third = bundle["rounds"][:3]
        self.assertEqual("SELECTED", first["selectionStatus"])
        self.assertEqual("EMPTY_CONFIRMED", repeated["selectionStatus"])
        self.assertEqual("available", repeated["previous"]["status"])
        self.assertEqual("unavailable", third["previous"]["status"])
        self.assertEqual("SELECTED", third["selectionStatus"])
        novelty_data = [sim.base.strict_load(sim.base.strict_load(raw)["input"]) for raw in transport.requests
                        if sim.base.strict_load(raw)["text"]["format"]["name"] == "round_simulation_novelty"]
        self.assertEqual(2, len(novelty_data))
        self.assertEqual(first["roundId"], novelty_data[-1]["noveltyHistory"][0]["roundId"])
        self.assertIsNone(novelty_data[-1]["simulatedPreviousOutput"])

    def test_generation_schema_limits_evidence_ids_per_issue(self):
        _, bundle, transport = self.run_fixture([
            legacy.source("a-doc", "2026-10-02T09:00:00+09:00"),
            legacy.source("b-doc", "2026-10-02T09:01:00+09:00")])
        selected = bundle["rounds"][0]["selected"]
        requests = [sim.base.strict_load(raw) for raw in transport.requests
                    if sim.base.strict_load(raw)["text"]["format"]["name"].endswith("_generation")]
        properties = requests[0]["text"]["format"]["schema"]["properties"]["items"]["properties"]
        for item in selected:
            allowed = sorted(s["evidenceId"] for s in item["sources"])
            issue = properties[item["issueId"]]["properties"]
            self.assertEqual(allowed, issue["titleEvidenceIds"]["items"]["enum"])
            self.assertEqual(allowed, issue["claims"]["items"]["properties"]["evidenceIds"]["items"]["enum"])
        self.assertNotEqual(properties[selected[0]["issueId"]], properties[selected[1]["issueId"]])

    def test_one_failed_generated_item_never_publishes_partial_round(self):
        summary, bundle, _ = self.run_fixture([
            legacy.source("a-doc", "2026-10-02T09:00:00+09:00"),
            legacy.source("b-doc", "2026-10-02T09:01:00+09:00")],
            V2Transport(semantic_failure=("verdict", "UNSUPPORTED")))
        held = bundle["rounds"][0]
        self.assertEqual("HELD_VALIDATION", held["selectionStatus"])
        self.assertEqual([], held["selected"])
        self.assertIsNone(held["result"])
        self.assertIsNone(held["resultSha256"])
        self.assertEqual(0, summary["selectedRounds"])
        draft = sim.base.strict_load((self.output / "2026-10-02-morning/generation-result.json").read_bytes())
        self.assertEqual(2, len(draft["items"]))
        self.assertEqual("WITHHELD", draft["verification"]["status"])


if __name__ == "__main__":
    unittest.main()
