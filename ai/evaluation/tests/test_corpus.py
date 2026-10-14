import unittest

from zoop_eval.bench import load_bench
from zoop_eval.contracts import parse_json

from support import Case, bench, cleanup, temp_corpus


class CorpusIntegrity(Case):
    def test_each_split_has_every_hop_depth_and_the_required_case_kinds(self):
        b = bench()
        for split in ("dev", "test"):
            qs = [b.gold_questions[q] for q in b.cases("qa", split)]
            self.assertEqual({g["hop"] for g in qs if g["hop"]}, {1, 2, 3}, split)
            self.assertEqual({g["kind"] for g in qs}, {"direct", "directed", "temporal", "conflict", "unknown"}, split)
            kinds = {m["kind"] for t in b.cases("graph", split) for m in b.graph_tasks[t]["mergeCandidates"]}
            self.assertEqual(kinds, {"event", "entity"}, split)
        decisions = {d for g in b.gold_graph.values() for d in g["merges"].values()}
        self.assertEqual(decisions, {"SAME", "DIFFERENT", "UNDECIDABLE"})
        self.assertTrue(any(v is None for g in b.gold_graph.values() for v in g["entityLinks"].values()), "needs an unlinkable mention")
        self.assertTrue(any(e["status"] == "disputed" for e in b.edges.values()))

    def test_three_hop_gold_is_not_capped_by_the_relation_producer_limit(self):
        # S3 MAX_PATH=2 limits relation production; retrieval traversal depth is a separate, uncapped contract.
        self.assertEqual(max(len(p) for g in bench().gold_questions.values() for p in g["paths"]), 3)

    def test_splits_share_no_document_entity_or_system_visible_gold(self):
        b = bench()
        dev_docs = {d for t in b.cases("graph", "dev") for d in b.graph_tasks[t]["docIds"]}
        test_docs = {d for t in b.cases("graph", "test") for d in b.graph_tasks[t]["docIds"]}
        self.assertFalse(dev_docs & test_docs)
        visible = (b.directory / "corpus.json").read_text() + (b.directory / "tasks.json").read_text()
        for needle in ("edgeId", "supportPassages", "UNDECIDABLE", "answerEntities", "abstainReason"):
            self.assertNotIn(needle, visible, "gold vocabulary must not appear in system-visible inputs")

    def test_revision_hashes_are_stable_and_separate_gold_from_inputs(self):
        b = bench()
        self.assertEqual(len(b.inputs_sha256), 64)
        self.assertNotEqual(b.inputs_sha256, b.gold_sha256)

    def test_document_in_two_splits_is_rejected(self):
        def mutate(corpus, tasks, gold):
            tasks["graphTasks"][5]["docIds"].append("D01")
        path = temp_corpus(mutate)
        try:
            self.rejected(lambda: load_bench(path), "split_leakage")
        finally:
            cleanup(path)

    def test_entity_used_by_edges_of_both_splits_is_rejected(self):
        def mutate(corpus, tasks, gold):
            edge = gold["graph"][5]["edges"][0]  # a test-split edge
            edge["subject"] = "E-ESK"  # an entity of the dev world
        path = temp_corpus(mutate)
        try:
            self.rejected(lambda: load_bench(path), "split_leakage")
        finally:
            cleanup(path)

    def test_gold_path_that_does_not_reach_its_answer_is_rejected(self):
        def mutate(corpus, tasks, gold):
            next(q for q in gold["questions"] if q["questionId"] == "QA-3")["answerEntities"] = ["E-CRV"]
        path = temp_corpus(mutate)
        try:
            self.rejected(lambda: load_bench(path), "gold_inconsistent")
        finally:
            cleanup(path)

    def test_gold_that_misses_a_task_label_is_rejected(self):
        def mutate(corpus, tasks, gold):
            del gold["graph"][0]["entityLinks"]["m-a01"]
        path = temp_corpus(mutate)
        try:
            self.rejected(lambda: load_bench(path), "gold_incomplete")
        finally:
            cleanup(path)

    def test_duplicate_json_keys_and_non_finite_numbers_are_rejected(self):
        self.rejected(lambda: parse_json('{"a": 1, "a": 2}', "x"), "json_duplicate_key")
        self.rejected(lambda: parse_json('{"a": NaN}', "x"), "json_non_finite")


if __name__ == "__main__":
    unittest.main()
