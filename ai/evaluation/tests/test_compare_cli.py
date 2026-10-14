import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from zoop_eval import cli
from zoop_eval.compare import compare_scores
from zoop_eval.controls import CONTROL_FILES, build_control

from support import Case, as_measured, bench, oracle, record, score

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "controls"
CONTEXT = {"concurrency": 1, "warmup": "warm", "environment": "unit-test"}


def measured(run_id, **system):
    run = as_measured(oracle(), run_id, **system)
    run["timingContext"] = dict(CONTEXT)
    run["system"].update({"systemId": run_id, "toolRevision": "tool-1"})
    return run


def invoke(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(list(argv))
    return code, out.getvalue()


class Provenance(Case):
    def test_authored_controls_are_labelled_and_carry_warnings(self):
        s = score(oracle())
        self.assertIn("NOT a measurement", s["provenanceLabel"])
        self.assertTrue(any("never rank" in w for w in s["warnings"]))
        self.assertTrue(any("synthetic=True" in w for w in s["warnings"]))

    def test_provenance_must_be_coherent(self):
        run = oracle()
        run["provenance"]["executionMode"] = "live"
        self.rejected(run, "malformed")  # a control cannot claim live execution
        run = oracle()
        del run["provenance"]["controlKind"]
        self.rejected(run, "provenance_invalid")
        run = measured("m")
        run["provenance"]["recordedAt"] = None
        self.rejected(run, "malformed")
        run = measured("m")
        run["system"]["toolRevision"] = None
        self.rejected(run, "provenance_invalid")
        run = measured("m", model={"provider": "p", "name": "n", "version": "v"}, family="agent_graphrag")
        run["system"]["promptRevision"] = None
        self.rejected(run, "provenance_invalid")
        run = measured("m", family="no_model_deterministic", model={"provider": "p", "name": "n", "version": "v"})
        self.rejected(run, "provenance_invalid")

    def test_run_must_name_the_loaded_corpus_revision(self):
        run = oracle()
        run["corpus"]["corpusRevision"] = "2000-01-01.0"
        self.rejected(run, "corpus_mismatch")
        run = oracle()
        run["corpus"]["goldRevision"] = "other"
        self.rejected(run, "corpus_mismatch")
        run = oracle()
        run["corpus"]["inputsSha256"] = "0" * 64
        self.rejected(run, "corpus_mismatch")


class Compare(Case):
    def test_one_factor_comparison_lists_the_factor_and_ranks_nothing(self):
        a = score(measured("m-low", config={"reasoningEffort": "low", "maxToolCalls": 8}))
        b = score(measured("m-high", config={"reasoningEffort": "high", "maxToolCalls": 8}))
        result = compare_scores([a, b])
        self.assertEqual(result["differingFactors"], {"config.reasoningEffort": ["low", "high"]})
        self.assertTrue(result["oneFactorChange"])
        self.assertTrue(result["timingComparable"])
        self.assertFalse([key for key in result if "rank" in key.lower() or "winner" in key.lower()])
        self.assertEqual(result["metrics"]["qa.outcome.correct"][0]["value"], 1.0)
        self.assertEqual(result["deltaVsFirst"]["qa.outcome.correct"], [None, 0.0])

    def test_measured_and_authored_control_runs_are_never_compared(self):
        self.rejected(lambda: compare_scores([score(oracle()), score(measured("m"))]), "mixed_provenance")

    def test_mixed_execution_modes_are_rejected(self):
        live = measured("m-live")
        live["provenance"]["executionMode"] = "live"
        self.rejected(lambda: compare_scores([score(measured("m-replay")), score(live)]), "mixed_mode")

    def test_duplicate_run_ids_and_single_run_are_rejected(self):
        self.rejected(lambda: compare_scores([score(measured("same")), score(measured("same"))]), "duplicate_run_id")
        self.rejected(lambda: compare_scores([score(measured("only"))]), "compare_incompatible")

    def test_different_splits_or_tasks_are_incompatible(self):
        other = oracle("test")
        other["provenance"] = measured("x")["provenance"]
        other["system"] = measured("x")["system"]
        other["runId"] = "x"
        self.rejected(lambda: compare_scores([score(measured("m")), score(other)]), "compare_incompatible")
        graph_only = measured("g")
        graph_only["corpus"]["tasks"] = ["graph"]
        graph_only["records"] = [r for r in graph_only["records"] if r["task"] == "graph"]
        self.rejected(lambda: compare_scores([score(measured("m")), score(graph_only)]), "compare_incompatible")

    def test_timing_is_suppressed_without_an_identical_timing_context(self):
        a, b = measured("a"), measured("b")
        b["timingContext"]["concurrency"] = 5
        result = compare_scores([score(a), score(b)])
        self.assertFalse(result["timingComparable"])
        self.assertFalse([name for name in result["metrics"] if name.startswith("timing.")])
        self.assertTrue(any("timingContext" in n for n in result["notes"]))

    def test_controls_compared_with_controls_are_labelled_as_scorer_checks(self):
        result = compare_scores([score(oracle()), score(build_control(bench(), "degraded", "dev"))])
        self.assertEqual(result["provenanceKind"], "authored_control")
        self.assertTrue(any("AUTHORED CONTROLS" in n for n in result["notes"]))
        self.assertLess(result["metrics"]["qa.outcome.endToEndCorrect"][1]["value"], result["metrics"]["qa.outcome.endToEndCorrect"][0]["value"])

    def test_model_provider_name_version_change_together_is_one_factor(self):
        base = {"family": "agent_graphrag", "promptRevision": "p-1"}
        a = score(measured("m-a", **base, model={"provider": "pa", "name": "na", "version": "va"}))
        b = score(measured("m-b", **base, model={"provider": "pb", "name": "nb", "version": "vb"}))
        result = compare_scores([a, b])
        self.assertEqual(list(result["differingFactors"]), ["model"])
        self.assertTrue(result["oneFactorChange"])


class Controls(Case):
    def test_checked_in_control_fixtures_match_the_generator(self):
        for name, (kind, split) in CONTROL_FILES.items():
            with self.subTest(name):
                self.assertEqual(json.loads((FIXTURES / name).read_text("utf-8")), build_control(bench(), kind, split))

    def test_degraded_control_exposes_each_authored_mistake(self):
        s = score(build_control(bench(), "degraded", "dev"))
        g, q = s["graph"], s["qa"]["all"]
        self.assertEqual(g["coverage"], {"total": 5, "ok": 3, "refused": 1, "error": 0, "missing": 1})
        self.assertEqual((g["edges"]["reversedDirection"]["num"], g["edges"]["notInGold"]["num"], g["edges"]["temporalInvented"]["num"]), (1, 1, 1))
        self.assertEqual(g["merges"]["event"]["falseMerge"]["num"], 1)
        self.assertEqual(g["merges"]["event"]["missedMerge"]["num"], 1)
        self.assertEqual(g["events"]["dateInvented"]["num"], 1)
        self.assertEqual(q["coverage"], {"total": 9, "ok": 7, "refused": 0, "error": 1, "missing": 1})
        self.assertEqual(q["path"]["invalidReasons"], {"reversed_edge": 1, "disconnected": 1})
        self.assertEqual(q["abstention"]["unsupportedAnswer"]["num"], 1)
        self.assertEqual(q["outcome"]["endToEndCorrect"]["num"], 2)


class CommandLine(Case):
    def test_validate_score_and_compare_emit_json(self):
        code, text = invoke("validate")
        self.assertEqual((code, json.loads(text)["ok"]), (0, True))
        code, text = invoke("score", str(FIXTURES / "oracle-dev.run.json"))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text)["headline"]["qa.outcome.endToEndCorrect"]["value"], 1.0)
        code, text = invoke("score", str(FIXTURES / "degraded-dev.run.json"), "--format", "text")
        self.assertEqual(code, 0)
        self.assertIn("AUTHORED CONTROL", text)
        self.assertIn("FALSE-MERGE", text)
        code, text = invoke("compare", str(FIXTURES / "oracle-dev.run.json"), str(FIXTURES / "degraded-dev.run.json"))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(text)["comparable"])

    def test_rejections_exit_two_with_a_json_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text('{"schema": "zoop-bench-run-1", "schema": "again"}')
            code, text = invoke("score", str(bad))
            self.assertEqual((code, json.loads(text)["error"]["code"]), (2, "json_duplicate_key"))
            code, text = invoke("score", str(Path(tmp) / "missing.json"))
            self.assertEqual((code, json.loads(text)["error"]["code"]), (2, "file_unreadable"))
            code, text = invoke("compare", str(FIXTURES / "oracle-dev.run.json"), str(FIXTURES / "oracle-test.run.json"))
            self.assertEqual((code, json.loads(text)["error"]["code"]), (2, "compare_incompatible"))
            code, text = invoke("compare", str(FIXTURES / "oracle-dev.run.json"), str(FIXTURES / "oracle-dev.run.json"))
            self.assertEqual((code, json.loads(text)["error"]["code"]), (2, "duplicate_run_id"))

    def test_controls_command_writes_the_three_fixtures(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = invoke("controls", "--out-dir", tmp)
            self.assertEqual(code, 0)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), sorted(CONTROL_FILES))


if __name__ == "__main__":
    unittest.main()
