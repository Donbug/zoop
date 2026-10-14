import copy
import unittest

from support import Case, oracle, record, score, val


def graph(run):
    return score(run)["graph"]


def edges(run, task):
    return record(run, "graph", task)["output"]["edges"]


class GraphOracle(Case):
    def test_oracle_is_perfect_where_defined_in_both_splits(self):
        for split in ("dev", "test"):
            g = graph(oracle(split))
            self.assertEqual(g["coverage"], {"total": 5, "ok": 5, "refused": 0, "error": 0, "missing": 0})
            for path in (("entityLinking", "accuracy"), ("events", "dateAccuracy"), ("merges", "event", "accuracy"),
                         ("merges", "entity", "accuracy"), ("edges", "exactPrecision"), ("edges", "exactRecall")):
                self.assertEqual(val(g, *path), 1.0, (split, path))
            self.assertEqual(val(g, "merges", "event", "falseMerge"), 0.0)
            self.assertEqual(g["edges"]["exactF1"], 1.0)


class EdgeDecisions(Case):
    def test_wrong_direction_is_its_own_error_not_a_generic_false_positive(self):
        run = oracle()
        e = edges(run, "GT-A1")[0]
        e["subject"], e["object"] = e["object"], e["subject"]
        g = graph(run)["edges"]
        self.assertEqual(g["reversedDirection"]["num"], 1)
        self.assertEqual(g["notInGold"]["num"], 0)
        self.assertEqual(g["tripleRecall"]["num"], 6)  # 7 gold edges, the reversed one is not matched
        self.assertEqual(g["exactPrecision"]["num"], 6)

    def test_undirected_edge_matches_in_either_order_but_directed_does_not(self):
        run = oracle()
        e = edges(run, "GT-A3")[1]  # COMPETES_WITH is undirected
        e["subject"], e["object"] = e["object"], e["subject"]
        g = graph(run)["edges"]
        self.assertEqual(g["reversedDirection"]["num"], 0)
        self.assertEqual(g["exactRecall"]["value"], 1.0)

    def test_invented_predicate_or_co_mention_edge_is_a_false_positive(self):
        run = oracle()
        edges(run, "GT-A1").append({"subject": "E-DQL", "predicate": "SUPPLIES", "object": "E-CRV", "citations": ["D03-P2"]})
        g = graph(run)["edges"]
        self.assertEqual((g["notInGold"]["num"], g["predictedEdges"]), (1, 8))
        self.assertAlmostEqual(g["exactPrecision"]["value"], 7 / 8, places=6)
        self.assertEqual(g["exactRecall"]["value"], 1.0)

    def test_temporal_invented_wrong_and_dropped_bounds_are_separated(self):
        run = oracle()
        a2 = edges(run, "GT-A2")
        a2[1]["validTo"] = "2026-12-31"  # gold: end unknown -> invented
        a2[0]["validTo"] = "2026-07-31"  # gold 2026-06-30 -> wrong
        a2[0]["validFrom"] = None  # gold 2025-03-01 -> dropped
        g = graph(run)["edges"]
        self.assertEqual((g["temporalInvented"]["num"], g["temporalWrong"], g["temporalDropped"]), (1, 1, 1))
        self.assertEqual(g["tripleRecall"]["value"], 1.0)  # triples are right; the attributes are what failed
        self.assertEqual(g["exactRecall"]["num"], 5)

    def test_unknown_stays_null_and_is_not_penalised(self):
        g = graph(oracle())["edges"]
        self.assertEqual(g["temporalInvented"], {"num": 0, "den": 11, "value": 0.0})

    def test_disputed_edge_reported_as_asserted_is_a_status_error(self):
        run = oracle()
        edges(run, "GT-A3")[0]["status"] = "asserted"
        g = graph(run)["edges"]
        self.assertEqual(g["statusAccuracy"]["num"], 6)
        self.assertEqual(g["exactRecall"]["num"], 6)
        self.assertEqual(g["tripleRecall"]["value"], 1.0)

    def test_citation_must_exist_and_hit_gold_evidence(self):
        run = oracle()
        edges(run, "GT-A1")[0]["citations"] = []
        edges(run, "GT-A1")[1]["citations"] = ["D99-P1"]
        edges(run, "GT-A1")[2]["citations"] = ["D01-P1"]  # exists but is not evidence for that edge
        g = graph(run)["edges"]
        self.assertEqual(g["uncitedMatched"], 1)
        self.assertEqual(g["invalidCitationRefs"], 1)
        self.assertEqual(g["citationSupportedOfMatched"]["num"], 4)  # 7 matched, 3 failing


class EntityLinkingAndMerges(Case):
    def test_homonym_conflation_and_false_link_on_unknown_mention(self):
        run = oracle()
        links = {l["mentionId"]: l for l in record(run, "graph", "GT-A4")["output"]["entityLinks"]}
        links["m-a21"]["entityId"] = "E-MBIO"  # bare "Meridian" has no gold identity
        links["m-a22"]["entityId"] = "E-MBIO"  # Meridian Steel conflated with Meridian Bio
        g = graph(run)["entityLinking"]
        self.assertEqual(g["falseLinkOnUnknown"], {"num": 1, "den": 1, "value": 1.0})
        self.assertEqual(g["misLinkedToOtherEntity"]["num"], 1)

    def test_same_entity_same_day_different_event_must_not_merge(self):
        run = oracle()
        pairs = {m["pairId"]: m for m in record(run, "graph", "GT-A5")["output"]["mergeDecisions"]}
        pairs["pair-a03"]["decision"] = "SAME"  # both Arcturus, both 2026-03-10, different events
        m = graph(run)["merges"]["event"]
        self.assertEqual(m["falseMerge"], {"num": 1, "den": 3, "value": 0.333333})
        self.assertEqual(m["accuracy"]["num"], 4)
        self.assertEqual(m["sameBinding"]["precision"]["num"], 1)  # the one true SAME is still right
        self.assertEqual(m["sameBinding"]["precision"]["den"], 2)

    def test_undecidable_pair_needs_hold_and_a_merge_is_unsafe_not_a_false_merge(self):
        run = oracle()
        pairs = {m["pairId"]: m for m in record(run, "graph", "GT-A5")["output"]["mergeDecisions"]}
        self.assertEqual(pairs["pair-a06"]["decision"], "HOLD")
        pairs["pair-a06"]["decision"] = "SAME"
        m = graph(run)["merges"]["event"]
        self.assertEqual(m["unsafeMergeOnUndecidable"]["num"], 1)
        self.assertEqual(m["falseMerge"]["num"], 0)
        self.assertEqual(m["holdOnUndecidable"]["num"], 0)
        pairs["pair-a06"]["decision"] = "DIFFERENT"  # splitting an undecidable pair is wrong too
        self.assertEqual(graph(run)["merges"]["event"]["accuracy"]["num"], 4)

    def test_missed_merge_and_over_hold(self):
        run = oracle()
        pairs = {m["pairId"]: m for m in record(run, "graph", "GT-A5")["output"]["mergeDecisions"]}
        pairs["pair-a04"]["decision"] = "HOLD"
        m = graph(run)["merges"]["event"]
        self.assertEqual((m["missedMerge"]["num"], m["overHold"]["num"]), (1, 1))

    def test_event_date_invented_for_an_undated_event(self):
        run = oracle()
        next(e for e in record(run, "graph", "GT-A5")["output"]["events"] if e["eventMentionId"] == "em-a03")["eventDate"] = "2026-03-11"
        ev = graph(run)["events"]
        self.assertEqual(ev["dateInvented"], {"num": 1, "den": 2, "value": 0.5})
        self.assertEqual(ev["dateAccuracy"]["num"], 4)


class DenominatorsAndStatuses(Case):
    def test_missing_refused_and_error_records_are_counted_separately_and_stay_in_gold_denominators(self):
        run = oracle()
        run["records"].remove(record(run, "graph", "GT-A1"))
        r = record(run, "graph", "GT-A2")
        r.update(status="refused", detail="policy refusal")
        del r["output"]
        r = record(run, "graph", "GT-A3")
        r.update(status="error", detail="tool crash")
        del r["output"]
        g = graph(run)
        self.assertEqual(g["coverage"], {"total": 5, "ok": 2, "refused": 1, "error": 1, "missing": 1})
        self.assertEqual(g["edges"]["goldEdges"], 7)  # gold side never shrinks
        self.assertEqual(g["entityLinking"]["accuracy"]["den"], 22)
        self.assertEqual(g["edges"]["exactRecall"]["num"], 0)
        self.assertEqual(g["edges"]["exactPrecision"], {"num": 0, "den": 0, "value": None})  # nothing predicted -> null

    def test_unanswered_sections_are_not_empty_answers_and_empty_denominators_are_null(self):
        run = oracle()
        output = record(run, "graph", "GT-A1")["output"]
        del output["edges"]
        for task in ("GT-A2", "GT-A3"):
            del record(run, "graph", task)["output"]["edges"]
        g = graph(run)["edges"]
        self.assertIsNone(g["exactPrecision"]["value"])
        self.assertIsNone(g["exactF1"])
        self.assertEqual(g["exactRecall"], {"num": 0, "den": 7, "value": 0.0})

    def test_empty_gold_denominator_is_null_not_zero_or_one(self):
        run = oracle()
        g = graph(run)
        self.assertEqual(g["merges"]["entity"]["missedMerge"], {"num": 0, "den": 0, "value": None})
        self.assertIsNone(g["merges"]["entity"]["sameBinding"]["precision"]["value"])

    def test_output_about_unasked_items_counts_against_precision(self):
        run = oracle()
        out = record(run, "graph", "GT-A4")["output"]
        out["entityLinks"].append({"mentionId": "m-zzz", "entityId": "E-ARC"})
        g = graph(run)["entityLinking"]
        self.assertEqual(g["unmatchedRefs"], 1)
        self.assertEqual(g["linkPrecision"]["den"], g["linkPrecision"]["num"] + 1)


class RunRejection(Case):
    def test_duplicate_record_is_rejected(self):
        run = oracle()
        run["records"].append(copy.deepcopy(record(run, "graph", "GT-A1")))
        self.rejected(run, "duplicate_record")

    def test_record_for_unknown_case_or_other_split_is_rejected(self):
        run = oracle()
        run["records"][0]["caseId"] = "GT-NOPE"
        self.rejected(run, "unmatched_case")
        run = oracle()
        run["records"][0]["caseId"] = "GT-B1"  # exists, but in the test split: a dev run must not touch it
        self.rejected(run, "unmatched_case")

    def test_duplicate_ids_inside_an_output_are_rejected(self):
        run = oracle()
        out = record(run, "graph", "GT-A1")["output"]
        out["entityLinks"].append(dict(out["entityLinks"][0]))
        self.rejected(run, "duplicate_item")

    def test_unknown_keys_and_bad_values_are_rejected(self):
        run = oracle()
        edges(run, "GT-A1")[0]["valid_from"] = "2025-01-01"
        self.rejected(run, "malformed")
        run = oracle()
        edges(run, "GT-A2")[0]["validTo"] = "2026-13-45"
        self.rejected(run, "malformed")
        run = oracle()
        record(run, "graph", "GT-A5")["output"]["mergeDecisions"][0]["decision"] = "UNDECIDABLE"  # gold vocabulary, not a prediction
        self.rejected(run, "malformed")

    def test_status_ok_needs_output_and_non_ok_needs_detail(self):
        run = oracle()
        del record(run, "graph", "GT-A1")["output"]
        self.rejected(run, "record_inconsistent")
        run = oracle()
        record(run, "graph", "GT-A1").update(status="error")
        self.rejected(run, "record_inconsistent")

    def test_duplicate_canonical_edge_triple_is_rejected_so_one_gold_edge_cannot_score_twice(self):
        run = oracle()
        edges(run, "GT-A1").append(copy.deepcopy(edges(run, "GT-A1")[0]))
        self.rejected(run, "duplicate_item")
        run = oracle()  # undirected predicate: the swapped endpoints are the same canonical triple
        competes = edges(run, "GT-A3")[1]
        edges(run, "GT-A3").append({**copy.deepcopy(competes), "subject": competes["object"], "object": competes["subject"]})
        self.rejected(run, "duplicate_item")

    def test_same_endpoints_with_a_different_predicate_or_direction_are_distinct_edges(self):
        run = oracle()
        a1 = edges(run, "GT-A1")[0]  # directed SUPPLIES ESK -> ARC
        edges(run, "GT-A1").append({**copy.deepcopy(a1), "predicate": "INVESTS_IN"})
        edges(run, "GT-A1").append({**copy.deepcopy(a1), "subject": a1["object"], "object": a1["subject"]})
        g = graph(run)["edges"]
        self.assertEqual((g["predictedEdges"], g["notInGold"]["num"], g["reversedDirection"]["num"]), (9, 1, 1))
        self.assertEqual(g["exactRecall"]["value"], 1.0)
        self.assertLess(g["exactPrecision"]["value"], 1.0)

    def test_merge_decision_for_an_unasked_pair_is_rejected_not_left_to_inflate_precision(self):
        run = oracle()
        record(run, "graph", "GT-A5")["output"]["mergeDecisions"].append({"pairId": "pair-unasked", "decision": "SAME"})
        self.rejected(run, "unmatched_item")
        run = oracle()  # a real pair id that belongs to another task is just as unasked here
        record(run, "graph", "GT-A4")["output"]["mergeDecisions"].append({"pairId": "pair-a04", "decision": "SAME"})
        self.rejected(run, "unmatched_item")


if __name__ == "__main__":
    unittest.main()
