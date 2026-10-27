"""CLI-level isolation, ranking and diagnostic denominator regressions.

Synthetic expectations below are authored test oracles, never benchmark measurements.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from scripts.materials_smoke import copy_materials, replace_file, run_cli
from zoop_eval.materials import DEFAULT_MATERIALS


class MaterialRetrievalTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="zoop-retrieval-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.materials = self.root / "materials"
        copy_materials(self.materials)
        self.run_path = self.root / "run.json"

    def invoke(self, command, *args, code=0, materials=None):
        result = run_cli(command, *map(str, args), "--materials", str(materials or self.materials))
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        document, audit = json.loads(result.stdout), json.loads(result.stderr)
        self.assertEqual(document["ok"], code == 0)
        self.assertFalse(any(audit["audit"].values()), audit)
        if code == 2:
            self.assertEqual(set(document), {"ok", "error"})
        return document, audit, result.stdout

    def retrieve(self, top_k=5):
        return self.invoke("materials-retrieve", "--top-k", top_k)[0]

    def score(self, run, code=0):
        self.run_path.write_text(json.dumps(run), encoding="utf-8")
        return self.invoke("materials-retrieval-score", self.run_path, code=code)

    def fixture(self):
        inputs = {
            "dataset": "NExTplusplus/TAT-QA", "split": "dev", "selection": "synthetic regression fixture",
            "records": [{"table": {"uid": "ctx", "table": [["tableonlytoken"]]},
                         "paragraphs": [{"uid": "p-b", "order": 1, "text": "apple"},
                                        {"uid": "p-a", "order": 2, "text": "apple"},
                                        {"uid": "p-c", "order": 3, "text": "orange"}],
                         "questions": [{"uid": f"q{i}", "order": i, "question": question}
                                       for i, question in enumerate(("APPLE apple", "orange", "tableonlytoken", "???", "apple"), 1)]}],
        }
        supports = [["1"], ["3"], [], None, ["1", "2"]]
        gold = {"dataset": "NExTplusplus/TAT-QA", "annotationStatus": "upstream annotations; not independently reviewed by Zoop",
                "records": [{"tableUid": "ctx", "questions": [
                    {"uid": f"q{i}", "answer": "not retrieval input", "derivation": "not executed",
                     "answer_type": "span", "answer_from": "table" if i == 3 else "text",
                     "scale": "", "req_comparison": False, "rel_paragraphs": support}
                    for i, support in enumerate(supports, 1)]}]}
        replace_file(self.materials, "tatqa.inputs.json", inputs)
        replace_file(self.materials, "tatqa.gold.json", gold)
        manifest = json.loads((self.materials / "manifest.json").read_text())
        for source in manifest["sources"]:
            if source["id"] == "tatqa":
                source["counts"] = {"contexts": 1, "questions": 5}
        (self.materials / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return inputs, gold

    def test_retained_dev_queries_binding_determinism_and_gold_isolation(self):
        run, audit, _ = self.invoke("materials-retrieve", materials=DEFAULT_MATERIALS)
        self.assertEqual(len(run["records"]), 30)
        self.assertEqual(len(run["queryIds"]), 30)
        self.assertEqual(audit["opened"], [str(DEFAULT_MATERIALS), "manifest.json", "tatqa.inputs.json"])
        _, _, normalized = self.invoke("materials-inputs", "--dataset", "tatqa", materials=DEFAULT_MATERIALS)
        self.assertEqual(run["inputsSha256"], hashlib.sha256(normalized.rstrip("\n").encode()).hexdigest())
        self.assertEqual(run["provenance"]["sources"][0]["license"], "CC-BY-4.0")
        self.assertEqual(run["status"], "development-intake")
        # Corrupt gold without updating the manifest, then remove it altogether.
        (self.materials / "tatqa.gold.json").write_text("invalid gold")
        corrupted = self.retrieve()
        (self.materials / "tatqa.gold.json").unlink()
        (self.materials / "klue-re.gold.json").unlink()
        (self.materials / "klue-re.inputs.json").unlink()
        absent = self.retrieve()
        for candidate in (corrupted, absent):
            self.assertEqual(candidate["inputsSha256"], run["inputsSha256"])
            for a, b in zip(run["records"], candidate["records"]):
                self.assertEqual({k: v for k, v in a.items() if k != "elapsedNs"},
                                 {k: v for k, v in b.items() if k != "elapsedNs"})
                self.assertIs(type(b["elapsedNs"]), int)
                self.assertGreaterEqual(b["elapsedNs"], 0)
        # Restore exactly the original gold after the producer finishes.
        (self.materials / "tatqa.gold.json").write_bytes((DEFAULT_MATERIALS / "tatqa.gold.json").read_bytes())
        score, _, _ = self.score(run)
        self.assertEqual(score["counts"]["questions"], 30)
        self.assertEqual(score["counts"]["ok"], 30)
        self.assertEqual(score["counts"]["error"], 0)
        self.assertEqual(score["counts"]["missing"], 0)
        self.assertEqual(score["counts"]["scorable"] + score["counts"]["notScorable"], 30)
        for row in score["queries"]:
            if not row["scorable"]:
                self.assertIsNone(row["recallAtK"])
                self.assertIsNone(row["reciprocalRankAtK"])
                self.assertIsNone(row["exactSupportCoverageAtK"])

    def test_frozen_tokens_bm25_ties_and_custom_diagnostics(self):
        self.fixture()
        run = self.retrieve(1)
        self.assertEqual([r["ranking"][0]["paragraphId"] for r in run["records"]],
                         ["p-a", "p-c", "p-a", "p-a", "p-a"])
        # N=3, df(apple)=2, all lengths=1: BM25 TF factor is exactly one.
        self.assertAlmostEqual(run["records"][0]["ranking"][0]["score"], math.log(1.6))
        self.assertEqual(run["records"][0]["ranking"], run["records"][4]["ranking"])
        self.assertEqual(run["records"][2]["ranking"][0]["score"], 0)
        self.assertEqual(run["records"][3]["ranking"][0]["score"], 0)
        score, _, _ = self.score(run)
        self.assertEqual(score["counts"], {"questions": 5, "recorded": 5, "ok": 5, "error": 0,
                                          "missing": 0, "scorable": 3, "notScorable": 2,
                                          "tableOnly": 1, "noParagraphGold": 1})
        self.assertEqual(score["metrics"]["paragraphSupportRecallAtK"], {"numerator": 1.5, "denominator": 3, "value": 0.5})
        self.assertAlmostEqual(score["metrics"]["mrrAtK"]["value"], 2 / 3)
        self.assertAlmostEqual(score["metrics"]["exactSupportCoverageAtK"]["value"], 1 / 3)
        self.assertEqual(score["queries"][2]["notScorableReason"], "table-only")
        self.assertIsNone(score["queries"][3]["supportCount"])
        score2, _, _ = self.score(self.retrieve(2))
        self.assertEqual(score2["metrics"]["paragraphSupportRecallAtK"]["value"], 1)
        self.assertAlmostEqual(score2["metrics"]["mrrAtK"]["value"], 5 / 6)
        self.assertEqual(score2["metrics"]["exactSupportCoverageAtK"]["value"], 1)

    def test_bm25_document_frequency_and_length_normalization(self):
        inputs, _ = self.fixture()
        inputs["records"][0]["paragraphs"] = [
            {"uid": "p-a", "order": 1, "text": "apple apple filler filler filler"},
            {"uid": "p-b", "order": 2, "text": "apple"},
            {"uid": "p-c", "order": 3, "text": "orange"}]
        replace_file(self.materials, "tatqa.inputs.json", inputs)
        run = self.retrieve(3)
        self.assertEqual([x["paragraphId"] for x in run["records"][0]["ranking"]], ["p-b", "p-a", "p-c"])
        # Authored numeric oracle for df=2, N=3, avgdl=7/3, dl=1, tf=1.
        self.assertAlmostEqual(run["records"][0]["ranking"][0]["score"], math.log(1.6) * 2.2 / (1 + 1.2 * (0.25 + 0.75 * 3 / 7)))

    def test_missing_and_error_records_remain_in_scorable_denominators(self):
        self.fixture()
        run = self.retrieve(1)
        run["records"][0].update(status="error", ranking=[], error="retrieval-error")
        del run["records"][1]
        score, _, _ = self.score(run)
        self.assertEqual(score["counts"]["missing"], 1)
        self.assertEqual(score["counts"]["error"], 1)
        self.assertEqual(score["counts"]["recorded"], 4)
        self.assertEqual(score["counts"]["scorable"], 3)
        self.assertAlmostEqual(score["metrics"]["paragraphSupportRecallAtK"]["value"], 1 / 6)
        self.assertEqual(score["metrics"]["paragraphSupportRecallAtK"]["denominator"], 3)
        run["records"] = []
        score, _, _ = self.score(run)
        self.assertEqual(score["counts"]["missing"], 5)
        for metric in score["metrics"].values():
            self.assertEqual(metric, {"numerator": 0, "denominator": 3, "value": 0})

    def test_empty_pool_and_unannotated_gold_are_not_invented_successes(self):
        inputs, gold = self.fixture()
        inputs["records"][0]["paragraphs"] = []
        for q in gold["records"][0]["questions"]:
            q["rel_paragraphs"] = []
        replace_file(self.materials, "tatqa.inputs.json", inputs)
        replace_file(self.materials, "tatqa.gold.json", gold)
        run = self.retrieve()
        self.assertTrue(all(r["ranking"] == [] for r in run["records"]))
        self.assertEqual(run["candidatePools"], [{"contextId": "ctx", "paragraphIds": []}])
        score, _, _ = self.score(run)
        self.assertEqual(score["counts"]["notScorable"], 5)
        for metric in score["metrics"].values():
            self.assertEqual(metric, {"numerator": 0, "denominator": 0, "value": None})
        self.assertTrue(all(q["recallAtK"] is None for q in score["queries"]))

    def test_closed_bindings_identity_and_malformed_records_rejected_before_gold(self):
        self.fixture()
        run = self.retrieve(2)
        mutations = {
            "not-final": lambda r: r.update(finalized=False),
            "family": lambda r: r.update(schema="zoop-bench-run-1"),
            "digest": lambda r: r.update(inputsSha256="0" * 64),
            "dataset": lambda r: r.update(dataset="klue-re"),
            "provenance": lambda r: r["provenance"].update(collectedAt="foreign"),
            "algorithm": lambda r: r["algorithm"].update(k1=2),
            "config-extra": lambda r: r["config"].update(secret=True),
            "topk-bool": lambda r: r["config"].update(topK=True),
            "queries": lambda r: r["queryIds"].append("foreign"),
            "candidate-pool": lambda r: r["candidatePools"][0]["paragraphIds"].append("foreign"),
            "foreign-query": lambda r: r["records"][0].update(queryId="foreign"),
            "duplicate-query": lambda r: r["records"].append(r["records"][0]),
            "context": lambda r: r["records"][0].update(contextId="foreign"),
            "foreign-paragraph": lambda r: r["records"][0]["ranking"][0].update(paragraphId="foreign"),
            "duplicate-paragraph": lambda r: r["records"][0]["ranking"].append(r["records"][0]["ranking"][0]),
            "wrong-tie-order": lambda r: r["records"][0]["ranking"].reverse(),
            "score": lambda r: r["records"][0]["ranking"][0].update(score=99),
            "score-bool": lambda r: r["records"][0]["ranking"][0].update(score=True),
            "negative-time": lambda r: r["records"][0].update(elapsedNs=-1),
            "time-bool": lambda r: r["records"][0].update(elapsedNs=True),
            "answer-leak": lambda r: r["records"][0].update(answer="unexpected"),
            "short-ok": lambda r: r["records"][0].update(ranking=[]),
            "error-with-ranking": lambda r: r["records"][0].update(status="error", error="retrieval-error"),
            "error-without-code": lambda r: r["records"][0].update(status="error", ranking=[]),
        }
        (self.materials / "tatqa.gold.json").unlink()
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(run)
                mutate(changed)
                _, audit, _ = self.score(changed, code=2)
                self.assertNotIn("tatqa.gold.json", audit["opened"])

    def test_changed_normalized_input_and_foreign_context_candidate_rejected(self):
        run = self.retrieve()
        # A genuine paragraph from another context is still a foreign candidate.
        changed = copy.deepcopy(run)
        changed["records"][0]["ranking"][0]["paragraphId"] = run["candidatePools"][1]["paragraphIds"][0]
        self.score(changed, code=2)
        inputs = json.loads((self.materials / "tatqa.inputs.json").read_text())
        inputs["records"][0]["questions"][0]["question"] += " changed"
        replace_file(self.materials, "tatqa.inputs.json", inputs)
        _, audit, _ = self.score(run, code=2)
        self.assertNotIn("tatqa.gold.json", audit["opened"])

    def test_wire_duplicates_nonfinite_and_unsafe_files_rejected(self):
        run = self.retrieve()
        raw = json.dumps(run)
        for content in ('{"schema":"x","schema":"y"}', raw.replace('"elapsedNs": ', '"elapsedNs": NaN, "unused": ', 1), "[", "null"):
            with self.subTest(content=content[:40]):
                self.run_path.write_text(content, encoding="utf-8")
                self.invoke("materials-retrieval-score", self.run_path, code=2)
        self.run_path.unlink()
        other = self.root / "other.json"
        other.write_text(raw, encoding="utf-8")
        self.run_path.symlink_to(other)
        self.invoke("materials-retrieval-score", self.run_path, code=2)
        for value in ("0", "-1", "not-an-int"):
            self.invoke("materials-retrieve", "--top-k", value, code=2)

    def test_producer_rejects_run_larger_than_scorer_wire_limit(self):
        inputs, gold = self.fixture()
        context = inputs["records"][0]
        context["paragraphs"] = [
            {"uid": f"p-{i:04d}-" + "x" * 48, "order": i + 1, "text": "apple"}
            for i in range(1000)
        ]
        context["questions"] = [
            {"uid": f"q-{i:04d}", "order": i + 1, "question": "apple"}
            for i in range(200)
        ]
        annotation = gold["records"][0]["questions"][0]
        gold["records"][0]["questions"] = [
            {**annotation, "uid": question["uid"], "rel_paragraphs": ["1"]}
            for question in context["questions"]
        ]
        replace_file(self.materials, "tatqa.inputs.json", inputs)
        replace_file(self.materials, "tatqa.gold.json", gold)
        manifest = json.loads((self.materials / "manifest.json").read_text())
        for source in manifest["sources"]:
            if source["id"] == "tatqa":
                source["counts"] = {"contexts": 1, "questions": 200}
        (self.materials / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        # Establish valid material and a usable producer -> scorer path first;
        # large K alone expands the run, not the source input or gold files.
        small = self.retrieve(1)
        score, _, _ = self.score(small)
        self.assertEqual(score["counts"]["questions"], 200)
        self.assertEqual(score["counts"]["ok"], 200)
        self.assertEqual(score["counts"]["scorable"], 200)
        # The wire budget includes every byte, including terminal whitespace/LF.
        small_wire = json.dumps(small).encode("utf-8")
        at_limit = small_wire + b" " * (8 * 1024 * 1024 - len(small_wire) - 1) + b"\n"
        self.run_path.write_bytes(at_limit)
        self.invoke("materials-retrieval-score", self.run_path)
        self.run_path.write_bytes(at_limit + b"\n")
        rejected, audit, _ = self.invoke("materials-retrieval-score", self.run_path, code=2)
        self.assertEqual(rejected["error"]["code"], "materials_retrieval_run_size")
        self.assertNotIn("tatqa.gold.json", audit["opened"])

        result = run_cli("materials-retrieve", "--top-k", "1000",
                         "--materials", str(self.materials))
        audit = json.loads(result.stderr)
        self.assertFalse(any(audit["audit"].values()), audit)
        self.assertNotIn("tatqa.gold.json", audit["opened"])
        wire_bytes = len(result.stdout.encode("utf-8"))  # Includes the CLI's LF.
        scorer_code = None
        if result.returncode == 0:
            # Preserve the producer's exact bytes rather than reserializing.
            self.run_path.write_bytes(result.stdout.encode("utf-8"))
            rejected, _, _ = self.invoke("materials-retrieval-score", self.run_path, code=2)
            scorer_code = rejected["error"]["code"]
        self.assertEqual(
            result.returncode, 2,
            f"producer emitted a successful {wire_bytes}-byte run (including LF), "
            f"but its scorer rejected it with {scorer_code}; reject oversized runs before success",
        )
        rejected = json.loads(result.stdout)
        self.assertEqual(set(rejected), {"ok", "error"})
        self.assertIs(rejected["ok"], False)
        self.assertEqual(rejected["error"]["code"], "materials_retrieval_run_size")

    def test_annotation_in_input_rejected_and_existing_score_families_stay_closed(self):
        run = self.retrieve()
        self.run_path.write_text(json.dumps(run), encoding="utf-8")
        for command in ("score", "verify-score", "summary-verify-score"):
            result = run_cli(command, str(self.run_path), audited=False)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertFalse(json.loads(result.stdout)["ok"])
        inputs = json.loads((self.materials / "tatqa.inputs.json").read_text())
        inputs["records"][0]["questions"][0]["rel_paragraphs"] = ["1"]
        replace_file(self.materials, "tatqa.inputs.json", inputs)
        self.invoke("materials-retrieve", code=2)


if __name__ == "__main__":
    unittest.main()
