"""Authored offline semantic decisions; no provider calls, credentials or real news."""

import copy
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("novelty", Path(__file__).resolve().parents[1] / "briefing_novelty.py")
novelty = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(novelty)
CONTEXT = {"contextSha256": "a" * 64, "context": {"mode": "publication_clock_simulation"}}
OLD = "시험 기업은 국내 AI 연구센터 설립 계획을 발표했습니다. 채용 규모와 실제 설립일은 아직 미정입니다."


def candidate(document="current", body=None, event="AI센터계획"):
    return {"documentId": document, "body": body or "시험 기업이 한국 AI 연구거점을 만들겠다고 밝혔습니다. 구체적인 채용·설립 일정은 공개되지 않았습니다.",
            "title": "시험 기업 연구센터 계획", "companyNames": ["시험 기업"], "assessment": {"eventKey": event, "importance": 2}}


def history():
    return [{"roundId": "old-round", "issueId": "old-issue", "eventKey": "AI센터계획", "title": "시험 기업 센터 설립 계획",
             "companyNames": ["시험 기업"], "sources": [{"documentId": "old-doc", "quote": OLD,
                                                         "bodySha256": novelty.digest(OLD.encode())}]}]


class FakeClient:
    def __init__(self, status="REPEAT", match="old-issue", delta="", mutate=None, verification=None, verify_mutate=None):
        self.status, self.match, self.delta, self.mutate = status, match, delta, mutate
        self.verification, self.verify_mutate = verification, verify_mutate
        self.calls = []

    def call(self, stage, data, prompt_name, schema_name, **kwargs):
        self.calls.append((stage, data, prompt_name, schema_name, kwargs))
        is_verification = stage == "round_simulation_novelty_verification"
        status, match, delta = self.verification if is_verification and self.verification else (self.status, self.match, self.delta)
        reply = {"decisions": {row["documentId"]: {"documentId": row["documentId"], "decision": status,
                 "matchedIssueId": match, "reason": "직접 작성한 자료 간 사건 및 새 사실 비교 결과입니다.", "delta": delta,
                 "quoteIds": [row["quoteCatalog"][0]["quoteId"]]} for row in data["documents"]}}
        mutate = self.verify_mutate if is_verification else self.mutate
        if mutate:
            mutate(reply, data)
        return reply


class NoveltyTests(unittest.TestCase):
    def test_paraphrased_republication_excluded_without_company_blacklist(self):
        client = FakeClient()
        filtered, audit = novelty.filter_candidates(client, [candidate()], history(), CONTEXT)
        self.assertEqual([], filtered)
        self.assertEqual("REPEAT", audit["decisions"][0]["decision"])
        self.assertEqual(["current"], audit["excludedDocumentIds"])
        self.assertEqual(audit["rawModelResponse"]["decisions"]["current"]["matchedIssueId"], "old-issue")

    def test_same_company_distinct_contract_is_new(self):
        client = FakeClient("NEW_EVENT", None)
        row = candidate(body="시험 기업이 별도 고객사와 신규 반도체 납품 계약을 체결했습니다. 계약금액은 100억원입니다.", event="신규납품계약")
        filtered, _ = novelty.filter_candidates(client, [row], history(), CONTEXT)
        self.assertEqual(["current"], [d["documentId"] for d in filtered])

    def test_material_update_with_new_state_and_current_evidence_is_kept(self):
        client = FakeClient("MATERIAL_UPDATE", "old-issue", "설립 계획이 실제 개소로 전환됐고 채용 인원 200명이 확정됨.")
        row = candidate(body="시험 기업의 국내 AI 연구센터가 오늘 개소했습니다. 실제 채용된 인원은 200명이며 연구 업무를 시작했습니다.")
        filtered, audit = novelty.filter_candidates(client, [row], history(), CONTEXT)
        self.assertEqual(1, len(filtered))
        self.assertEqual("MATERIAL_UPDATE", audit["decisions"][0]["decision"])

    def test_identical_body_excluded_without_model_even_if_new_event_key(self):
        client = FakeClient("NEW_EVENT", None)
        filtered, audit = novelty.filter_candidates(client, [candidate(body=OLD, event="다른키")], history(), CONTEXT)
        self.assertEqual([], filtered)
        self.assertEqual([], client.calls)
        self.assertEqual("deterministic_body_digest", audit["decisions"][0]["method"])

    def test_no_history_does_not_cost_or_suppress_same_company(self):
        client = FakeClient()
        rows = [candidate("one", event="센터"), candidate("two", event="납품")]
        filtered, audit = novelty.filter_candidates(client, rows, [], CONTEXT)
        self.assertEqual(2, len(filtered))
        self.assertFalse(audit["modelCalled"])
        self.assertEqual([], client.calls)
        self.assertNotIn("quoteCatalog", rows[0])  # no mutation of frozen input

    def test_uncertainty_is_excluded(self):
        filtered, audit = novelty.filter_candidates(FakeClient("UNCERTAIN", None), [candidate()], history(), CONTEXT)
        self.assertEqual([], filtered)
        self.assertEqual("UNCERTAIN", audit["decisions"][0]["decision"])

    def test_unknown_issue_is_rejected(self):
        with self.assertRaisesRegex(novelty.NoveltyError, "matched_issue_not_in_history"):
            novelty.filter_candidates(FakeClient(match="invented"), [candidate()], history(), CONTEXT)

    def test_foreign_quote_id_is_rejected(self):
        def corrupt(reply, data):
            reply["decisions"]["current"]["quoteIds"] = ["other-document-quote"]
        with self.assertRaisesRegex(novelty.NoveltyError, "quote_not_in_candidate_catalog"):
            novelty.filter_candidates(FakeClient(mutate=corrupt), [candidate()], history(), CONTEXT)

    def test_same_old_event_key_cannot_claim_new_even_with_different_body(self):
        with self.assertRaisesRegex(novelty.NoveltyError, "old_event_requires_material_delta"):
            novelty.filter_candidates(FakeClient("NEW_EVENT", None), [candidate(event="  AI센터계획  ")], history(), CONTEXT)

    def test_material_update_requires_delta_and_known_match(self):
        for client in (FakeClient("MATERIAL_UPDATE", None, "신규 개소"), FakeClient("MATERIAL_UPDATE", "old-issue", "")):
            with self.subTest(match=client.match, delta=client.delta):
                with self.assertRaisesRegex(novelty.NoveltyError, "update_delta_or_match_missing"):
                    novelty.filter_candidates(client, [candidate()], history(), CONTEXT)

    def test_old_quote_reuse_cannot_become_material_update(self):
        row = candidate(body=OLD + " 단순 재보도입니다.")
        row["quoteCatalog"] = [{"quoteId": "same-old-quote", "documentId": "current", "start": 0, "end": len(OLD), "text": OLD}]
        with self.assertRaisesRegex(novelty.NoveltyError, "update_reuses_prior_quote"):
            novelty.filter_candidates(FakeClient("MATERIAL_UPDATE", "old-issue", "새롭다고 주장"), [row], history(), CONTEXT)

    def test_injected_catalog_is_bound_to_exact_offsets_and_document(self):
        for changes in ({"text": "invented"}, {"documentId": "wrong"}, {"start": -1}, {"end": True}):
            row = candidate()
            row["quoteCatalog"] = novelty.build_quote_catalog(row)
            row["quoteCatalog"][0].update(changes)
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(novelty.NoveltyError, "catalog_binding_mismatch"):
                    novelty.filter_candidates(FakeClient(), [row], history(), CONTEXT)

    def test_history_digest_binds_all_previous_events_and_is_in_paid_input(self):
        client = FakeClient()
        _, audit = novelty.filter_candidates(client, [candidate()], history(), CONTEXT)
        self.assertEqual(novelty.digest(novelty.canonical(history())), audit["historySha256"])
        data, kwargs = client.calls[0][1], client.calls[0][4]
        self.assertEqual(audit["historySha256"], data["noveltyHistorySha256"])
        self.assertEqual(CONTEXT["contextSha256"], data["contextSha256"])
        self.assertEqual(8000, kwargs["max_output"])
        item = kwargs["schema_override"]["properties"]["decisions"]["properties"]["current"]
        self.assertEqual([None, "old-issue"], item["properties"]["matchedIssueId"]["enum"])
        changed = history()
        changed[0]["title"] += " 수정"
        _, other = novelty.filter_candidates(FakeClient(), [candidate()], changed, CONTEXT)
        self.assertNotEqual(audit["historySha256"], other["historySha256"])

    def test_missing_or_extra_model_document_fails_closed(self):
        def missing(reply, data):
            reply["decisions"] = {}
        def invented(reply, data):
            reply["decisions"]["invented"] = copy.deepcopy(reply["decisions"]["current"])
        for mutate in (missing, invented):
            with self.subTest(mutate=mutate.__name__):
                with self.assertRaisesRegex(novelty.NoveltyError, "document_coverage_mismatch"):
                    novelty.filter_candidates(FakeClient(mutate=mutate), [candidate()], history(), CONTEXT)

    def test_body_digest_mismatch_rejected_before_model_call(self):
        row = candidate()
        row["bodySha256"] = "0" * 64
        client = FakeClient()
        with self.assertRaisesRegex(novelty.NoveltyError, "body_digest_mismatch"):
            novelty.filter_candidates(client, [row], history(), CONTEXT)
        self.assertEqual([], client.calls)

    def test_quote_catalog_covers_unicode_source_without_normalization(self):
        row = candidate(body="😀 한글\n\n" * 400)
        catalog = novelty.build_quote_catalog(row)
        self.assertEqual(row["body"], "".join(q["text"] for q in catalog))
        self.assertTrue(all(row["body"][q["start"]:q["end"]] == q["text"] for q in catalog))


    def test_all_model_decisions_receive_one_separate_verification_call(self):
        for status, match in (("NEW_EVENT", None), ("REPEAT", "old-issue"), ("UNCERTAIN", None),
                              ("MATERIAL_UPDATE", "old-issue")):
            row = candidate(event="센터개소" if status == "NEW_EVENT" else "AI센터계획")
            client = FakeClient(status, match, "설립 계획이 실제 개소로 변경" if status == "MATERIAL_UPDATE" else "")
            _, audit = novelty.filter_candidates(client, [row], history(), CONTEXT)
            self.assertEqual(["round_simulation_novelty", "round_simulation_novelty_verification"], [c[0] for c in client.calls])
            self.assertTrue(audit["verificationCalled"])
            self.assertEqual(8000, client.calls[1][4]["max_output"])
            proposal = client.calls[1][1]["priorNoveltyDecisions"]
            self.assertEqual(audit["rawModelResponse"], proposal)
            self.assertEqual(novelty.digest(novelty.canonical(proposal)), client.calls[1][1]["priorNoveltyDecisionsSha256"])
            self.assertEqual(client.calls[0][1]["documents"], client.calls[1][1]["documents"])
            self.assertEqual(client.calls[0][1]["noveltyHistorySha256"], client.calls[1][1]["noveltyHistorySha256"])

    def test_tsmc_revenue_falsely_linked_to_samsung_is_corrected_to_new_event(self):
        previous = history()
        previous[0].update({"title": "삼성전자 3분기 잠정실적", "eventKey": "삼성전자-Q3실적", "companyNames": ["삼성전자"]})
        previous[0]["sources"][0]["quote"] = "삼성전자 자체 3분기 잠정실적을 발표했다는 직접 작성 합성 원문입니다."
        previous[0]["sources"][0]["bodySha256"] = novelty.digest(previous[0]["sources"][0]["quote"].encode())
        row = candidate(body="TSMC는 3분기 매출을 발표했습니다. 이 수치는 TSMC 자체 실적이며 삼성전자 실적과는 별도 법인의 발표입니다.",
                        event="TSMC-Q3실적")
        row["companyNames"] = ["TSMC"]
        client = FakeClient("MATERIAL_UPDATE", "old-issue", "다른 기업의 매출 수치를 삼성전자 실적 변화로 잘못 연결",
                            verification=("NEW_EVENT", None, ""))
        filtered, audit = novelty.filter_candidates(client, [row], previous, CONTEXT)
        self.assertEqual(["current"], [d["documentId"] for d in filtered])
        self.assertEqual("MATERIAL_UPDATE", audit["rawModelResponse"]["decisions"]["current"]["decision"])
        self.assertEqual("NEW_EVENT", audit["rawVerificationResponse"]["decisions"]["current"]["decision"])
        self.assertIsNone(audit["decisions"][0]["matchedIssueId"])

    def test_kakao_research_falsely_linked_to_amd_center_is_corrected(self):
        previous = history()
        previous[0].update({"title": "AMD 한국 AI 연구센터 계획", "eventKey": "AMD-한국AI센터", "companyNames": ["AMD"]})
        previous[0]["sources"][0]["quote"] = "AMD가 한국 AI 연구센터 설립 계획을 발표했다는 직접 작성 합성 원문입니다."
        previous[0]["sources"][0]["bodySha256"] = novelty.digest(previous[0]["sources"][0]["quote"].encode())
        row = candidate(body="카카오가 별도 AI 연구 조직의 연구 성과를 공개했습니다. 이 발표는 카카오 자체 연구이며 AMD 센터 설립과 별개입니다.",
                        event="카카오-AI연구성과")
        row["companyNames"] = ["카카오"]
        filtered, audit = novelty.filter_candidates(FakeClient("REPEAT", "old-issue", verification=("NEW_EVENT", None, "")),
                                                     [row], previous, CONTEXT)
        self.assertEqual(1, len(filtered))
        self.assertEqual("REPEAT", audit["rawModelResponse"]["decisions"]["current"]["decision"])
        self.assertEqual("NEW_EVENT", audit["decisions"][0]["decision"])

    def test_verifier_can_withhold_initial_new_event_and_final_gate_uses_verifier(self):
        row = candidate(event="다른표현의센터계획")
        client = FakeClient("NEW_EVENT", None, verification=("REPEAT", "old-issue", ""))
        filtered, audit = novelty.filter_candidates(client, [row], history(), CONTEXT)
        self.assertEqual([], filtered)
        self.assertEqual("NEW_EVENT", audit["rawModelResponse"]["decisions"]["current"]["decision"])
        self.assertEqual("REPEAT", audit["decisions"][0]["decision"])

    def test_malformed_or_foreign_verification_response_never_bypasses_gate(self):
        def missing(reply, data):
            reply["decisions"] = {}
        def foreign(reply, data):
            reply["decisions"]["current"]["quoteIds"] = ["foreign-quote"]
        for mutate, message in ((missing, "verification_document_coverage_mismatch"), (foreign, "quote_not_in_candidate_catalog")):
            client = FakeClient(verify_mutate=mutate)
            with self.subTest(message=message):
                with self.assertRaisesRegex(novelty.NoveltyError, message):
                    novelty.filter_candidates(client, [candidate()], history(), CONTEXT)
                self.assertEqual(2, len(client.calls))

    def test_no_history_and_identical_sha_never_use_verification(self):
        for rows, previous in (([candidate()], []), ([candidate(body=OLD)], history())):
            client = FakeClient()
            _, audit = novelty.filter_candidates(client, rows, previous, CONTEXT)
            self.assertFalse(audit["verificationCalled"])
            self.assertIsNone(audit["rawVerificationResponse"])
            self.assertEqual([], client.calls)


if __name__ == "__main__":
    unittest.main()
