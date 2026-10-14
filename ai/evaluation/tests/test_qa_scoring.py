import unittest

from support import Case, oracle, record, score, val


def qa(run):
    return score(run)["qa"]["all"]


def out(run, case):
    return record(run, "qa", case)["output"]


class QaOracle(Case):
    def test_oracle_is_perfect_where_defined_in_both_splits(self):
        for split in ("dev", "test"):
            a = qa(oracle(split))
            self.assertEqual(a["coverage"], {"total": 9, "ok": 9, "refused": 0, "error": 0, "missing": 0})
            for path in (("outcome", "correct"), ("outcome", "endToEndCorrect"), ("answer", "entitySetExact"), ("answer", "factSetExact"),
                         ("abstention", "recall"), ("abstention", "precision"), ("abstention", "conflictRecall"),
                         ("retrieval", "supportPrecision"), ("retrieval", "supportRecall"), ("retrieval", "fullSupportCases"),
                         ("path", "validity"), ("path", "exactMatch"), ("path", "hopCoverage"),
                         ("citations", "precision"), ("citations", "recall")):
                self.assertEqual(val(a, *path), 1.0, (split, path))
            self.assertEqual(val(a, "abstention", "unsupportedAnswer"), 0.0)

    def test_three_hop_traversal_is_scored_in_full_without_a_depth_cap(self):
        s = score(oracle())["qa"]["byHop"]
        self.assertEqual(val(s["3"], "path", "hopCoverage"), 1.0)
        self.assertEqual(s["3"]["path"]["hopCoverage"]["den"], 3)
        self.assertEqual(val(s["3"], "outcome", "endToEndCorrect"), 1.0)

    def test_free_text_is_never_scored_automatically(self):
        run = oracle()
        out(run, "QA-1")["answerText"] = "Eskel Materials supplies Arcturus."
        a = qa(run)
        self.assertEqual(a["freeText"], {"answerTextRecords": 1, "automaticMetric": None, "status": "human_or_model_evaluation_required"})
        self.assertEqual(val(a, "outcome", "endToEndCorrect"), 1.0)


class DirectionTemporalUnknownConflict(Case):
    def test_wrong_direction_path_is_invalid_and_wrong_direction_fact_is_counted(self):
        run = oracle()
        back = {"subject": "E-BRL", "predicate": "SUPPLIES", "object": "E-ARC"}  # real edge is ARC -> BRL
        out(run, "QA-2")["path"] = [back]
        out(run, "QA-2")["facts"] = [{**back}]
        a = qa(run)
        self.assertEqual(a["path"]["invalidReasons"], {"reversed_edge": 1})
        self.assertEqual(a["path"]["validity"]["num"], 5)  # 6 produced paths, one invalid
        self.assertEqual(a["answer"]["factsReversedDirection"], 1)
        self.assertEqual(a["path"]["exactMatch"]["num"], 5)
        self.assertEqual(a["outcome"]["endToEndCorrect"]["num"], 8)

    def test_upstream_question_may_walk_an_edge_against_its_direction_but_not_reverse_the_edge(self):
        # QA-1 asks who supplies Arcturus: the gold path walks ESK->ARC from the anchor ARC, i.e. upstream.
        self.assertEqual(val(qa(oracle()), "path", "validity"), 1.0)

    def test_temporal_answer_from_the_wrong_period_is_a_valid_path_but_not_the_right_one(self):
        run = oracle()
        o = out(run, "QA-5")  # asked as of 2026-01-15; BRL's stake only starts 2026-07-01
        a5 = {"subject": "E-BRL", "predicate": "INVESTS_IN", "object": "E-ESK"}
        o.update(answerEntities=["E-BRL"], facts=[{**a5, "validFrom": "2026-07-01", "validTo": None, "status": "asserted"}], path=[a5])
        a = qa(run)
        self.assertEqual(a["path"]["validity"]["num"], 6)  # the edge exists in the graph and is connected...
        self.assertEqual(a["path"]["exactMatch"]["num"], 5)  # ...but it is not the path for that date
        self.assertEqual(a["path"]["reachesAnswer"]["num"], 5)
        self.assertEqual(a["outcome"]["endToEndCorrect"]["num"], 8)

    def test_temporal_fact_with_wrong_validity_is_not_an_exact_fact(self):
        run = oracle()
        out(run, "QA-5")["facts"][0]["validTo"] = "2026-12-31"
        a = qa(run)
        self.assertEqual(a["answer"]["factSetExact"]["num"], a["answer"]["factSetExact"]["den"] - 1)
        self.assertEqual(a["answer"]["entitySetExact"]["value"], 1.0)

    def test_answering_an_unknown_end_date_is_an_unsupported_answer(self):
        run = oracle()
        o = out(run, "QA-7")
        del o["abstainReason"]
        o.update(outcome="answered", answerEntities=["E-ESK"])
        a = qa(run)["abstention"]
        self.assertEqual(a["unsupportedAnswer"], {"num": 1, "den": 2, "value": 0.5})
        self.assertEqual(a["recall"]["num"], 1)

    def test_abstaining_with_the_wrong_reason_is_correct_abstention_with_reason_mismatch(self):
        run = oracle()
        out(run, "QA-7")["abstainReason"] = "no_evidence"
        a = qa(run)["abstention"]
        self.assertEqual(a["recall"]["value"], 1.0)
        self.assertEqual(a["reasonMatchOfCorrect"], {"num": 1, "den": 2, "value": 0.5})

    def test_over_abstention_on_an_answerable_multi_hop_question(self):
        run = oracle()
        o = out(run, "QA-4")
        o.clear()
        o.update(outcome="abstained", abstainReason="no_evidence")
        s = score(run)["qa"]
        self.assertEqual(s["all"]["abstention"]["overAbstention"], {"num": 1, "den": 7, "value": 0.142857})
        self.assertEqual(val(s["byHop"]["3"], "outcome", "correct"), 0.0)
        self.assertEqual(val(s["byHop"]["1"], "outcome", "correct"), 1.0)

    def test_conflict_must_be_surfaced_not_resolved(self):
        run = oracle()
        o = out(run, "QA-8")
        o.update(outcome="answered", answerEntities=["E-BRL"])
        a = qa(run)["abstention"]
        self.assertEqual(a["conflictRecall"], {"num": 0, "den": 1, "value": 0.0})
        self.assertEqual(a["conflictPrecision"]["value"], None)  # nothing predicted as conflict -> null


class PathRetrievalCitation(Case):
    def test_disconnected_path_gets_partial_hop_coverage_but_is_invalid(self):
        run = oracle()
        path = out(run, "QA-4")["path"]
        del path[1]  # skip the middle hop
        a = qa(run)["path"]
        self.assertEqual(a["invalidReasons"], {"disconnected": 1})
        self.assertEqual(a["hopCoverage"]["num"], 9 - 1)
        self.assertEqual(a["exactMatch"]["num"], 5)

    def test_retrieval_precision_recall_and_unknown_references(self):
        run = oracle()
        out(run, "QA-4")["retrieved"] = ["D01-P1", "D03-P1", "D13-P1", "D99-P1"]  # 2 relevant, 1 distractor, 1 not in corpus
        a = qa(run)["retrieval"]
        self.assertEqual(a["unknownPassageRefs"], 1)
        self.assertEqual(a["supportRecall"]["num"], 13 - 1)  # D02-P1 not retrieved
        self.assertEqual(a["supportPrecision"]["den"], 13 - 3 + 4)
        self.assertEqual(a["fullSupportCases"]["num"], 8 - 1)

    def test_recall_at_k_only_counts_the_ranked_prefix(self):
        run = oracle()
        out(run, "QA-3")["retrieved"] = ["D13-P1", "D12-P1", "D11-P1", "D10-P1", "D09-P1", "D01-P1", "D02-P1"]
        a = qa(run)["retrieval"]
        self.assertEqual(a["supportRecall"]["num"], 13)
        self.assertEqual(a["supportRecallAt5"]["num"], 13 - 2)

    def test_citation_precision_recall_and_uncited_answers(self):
        run = oracle()
        out(run, "QA-3")["citations"] = ["D01-P1", "D13-P1"]
        out(run, "QA-1")["citations"] = []
        a = qa(run)["citations"]
        self.assertEqual(a["uncitedAnswers"]["num"], 1)
        self.assertEqual(a["recall"]["num"], 13 - 1 - 1)
        self.assertEqual(a["precision"]["den"], 13 - 1 - 2 + 2)

    def test_undeclared_capability_is_null_not_zero_and_emitting_it_is_a_contradiction(self):
        run = oracle()
        run["system"]["capabilities"]["path"] = False
        self.rejected(run, "capability_contradiction")
        for r in run["records"]:
            if r["task"] == "qa":
                r["output"].pop("path", None)
        s = score(run)
        self.assertEqual(s["qa"]["all"]["path"], {"status": "capability_not_declared"})
        self.assertEqual(s["headline"]["qa.path.validity"], {"value": None, "status": "capability_not_declared"})
        self.assertEqual(val(s["qa"]["all"], "retrieval", "supportRecall"), 1.0)

    def test_declared_but_not_produced_path_is_a_miss_not_a_skip(self):
        run = oracle()
        for r in run["records"]:
            if r["task"] == "qa":
                r["output"].pop("path", None)
        a = qa(run)["path"]
        self.assertEqual(a["produced"]["num"], 0)
        self.assertIsNone(a["validity"]["value"])  # nothing produced -> empty denominator
        self.assertEqual(a["hopCoverage"], {"num": 0, "den": 9, "value": 0.0})


class QaDenominators(Case):
    def test_all_abstain_run_has_null_precisions_and_full_miss_recalls(self):
        run = oracle()
        for r in run["records"]:
            if r["task"] == "qa":
                r["output"] = {"outcome": "abstained", "abstainReason": "no_evidence", "retrieved": [], "citations": []}
        a = qa(run)
        self.assertIsNone(val(a, "answer", "entityPrecision"))
        self.assertIsNone(val(a, "retrieval", "supportPrecision"))
        self.assertEqual(val(a, "answer", "entityRecall"), 0.0)
        self.assertEqual(val(a, "retrieval", "supportRecall"), 0.0)
        self.assertEqual(a["abstention"]["precision"], {"num": 2, "den": 9, "value": 0.222222})
        self.assertEqual(a["abstention"]["overAbstention"]["value"], 1.0)

    def test_refused_error_and_missing_are_separate_and_never_become_empty_answers(self):
        run = oracle()
        run["records"].remove(record(run, "qa", "QA-1"))
        r = record(run, "qa", "QA-2")
        r.update(status="refused", detail="policy")
        del r["output"]
        r = record(run, "qa", "QA-3")
        r.update(status="error", detail="timeout")
        del r["output"]
        a = qa(run)
        self.assertEqual(a["coverage"], {"total": 9, "ok": 6, "refused": 1, "error": 1, "missing": 1})
        self.assertEqual(a["outcome"]["correct"], {"num": 6, "den": 9, "value": 0.666667})
        self.assertEqual(a["outcome"]["confusion"]["answered"]["noOutput"], 3)
        self.assertEqual(a["abstention"]["unsupportedAnswer"]["value"], 0.0)  # failures are not 'answered'

    def test_unmatched_case_and_duplicates_are_rejected(self):
        run = oracle()
        run["records"].append({**record(run, "qa", "QA-1")})
        self.rejected(run, "duplicate_record")
        run = oracle()
        record(run, "qa", "QA-1")["caseId"] = "QB-1"
        self.rejected(run, "unmatched_case")

    def test_inconsistent_answer_record_is_rejected(self):
        run = oracle()
        out(run, "QA-8")["answerEntities"] = ["E-BRL"]  # conflict outcome cannot also assert an answer
        self.rejected(run, "record_inconsistent")


if __name__ == "__main__":
    unittest.main()
