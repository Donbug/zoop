"""Offline tests use genuine loopback-captured native receipts, never receipt factories."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from zoop_eval import cli
from zoop_eval.contracts import Rejected
from zoop_eval.summary_verification import (
    DEFAULT_SUMMARY_CORPUS, adapter_preimage, canonical, describe_summary, digest,
    expected_request, load_summary_corpus, load_summary_inputs, load_summary_script,
    parse_summary_run, score_summary_run, script_expectation, write_summary_controls,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "summary-verification"


def captured(variant="oracle"):
    # A missing capture is an unmet fixture prerequisite, not a skipped passing test.
    return json.loads((FIXTURES / f"{variant}.run.json").read_text("utf-8"))


def record(run, cid):
    return next(r for r in run["records"] if r["caseId"] == cid)


def rehash_prepared(prepared):
    prepared["requestDigest"] = digest(prepared["body"])
    prepared["requestBytes"] = len(canonical(prepared["body"]).encode("utf-8"))
    prepared["digest"] = digest({k: v for k, v in prepared.items() if k != "digest"})


class SummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load_summary_corpus()
        cls.inputs = cls.corpus["inputs"]

    def rejected(self, code, call):
        with self.assertRaises(Rejected) as caught:
            call()
        self.assertEqual(caught.exception.code, code, caught.exception.message)

    def test_corpus_counts_and_visible_only_loader(self):
        description = describe_summary(self.corpus)
        self.assertEqual(description["counts"], {"cases": 24, "claims": 30,
            "claimsByLabel": {"supported": 12, "insufficient": 11, "contradicted": 7},
            "gates": {"available": 6, "verifier-hold": 5, "verifier-reject": 13}})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.json"
            path.write_bytes((DEFAULT_SUMMARY_CORPUS / "cases.json").read_bytes())
            self.assertEqual(load_summary_inputs(path)["inputsSha256"], self.inputs["inputsSha256"])

    def test_dynamic_case_quotes_remain_scoped_and_ordered(self):
        payload = {"quotes": [{"quoteId": "z", "context": "background", "text": "과거 사실"},
                              {"quoteId": "unused", "context": "report", "text": "미인용 사실"},
                              {"quoteId": "a", "context": "report", "text": "현재 사실"}],
                   "claims": [{"claimId": "c1", "text": "현재와 과거 사실이다.", "quoteIds": ["a", "z"]}]}
        request, expect = expected_request(payload, adapter_preimage())
        self.assertEqual(request["state"], {"quotes": [
            {"label": "Q1", "context": "background", "text": "과거 사실"},
            {"label": "Q2", "context": "report", "text": "현재 사실"}],
            "claims": [{"label": "C1", "text": "현재와 과거 사실이다.", "quotes": ["Q1", "Q2"]}]})
        self.assertEqual(expect["claims"], [{"claimId": "c1", "quoteIds": ["a", "z"]}])
        self.assertIn("Read the quotes Q1, Q2", request["questions"]["claim-0"]["instructions"]["question"])
        payload["claims"][0]["quoteIds"].reverse()
        self.assertEqual(expected_request(payload, adapter_preimage())[0], request)

    def test_case_mutations_rejected_without_gold(self):
        original = json.loads((DEFAULT_SUMMARY_CORPUS / "cases.json").read_text("utf-8"))
        mutations = [
            ("gold_leak", lambda r: r["cases"][0]["payload"].update(expectedWhatever="hidden")),
            ("claim_citation_invalid", lambda r: r["cases"][0]["payload"]["claims"][0].update(quoteIds=[])),
            ("claim_citation_invalid", lambda r: r["cases"][0]["payload"]["claims"][0].update(quoteIds=["missing"])),
            ("claim_invalid", lambda r: r["cases"][0]["payload"]["claims"][0].update(text="줄바꿈\n주장")),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.json"
            for code, mutate in mutations:
                with self.subTest(code=code):
                    raw = copy.deepcopy(original)
                    mutate(raw)
                    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
                    self.rejected(code, lambda: load_summary_inputs(path))

    def test_controls_dynamic_ids_and_script_expectations(self):
        corpus = copy.deepcopy(self.corpus)
        corpus["gold"]["cases"][0]["caseId"] = "renamed"
        corpus["inputs"]["cases"][0]["caseId"] = "renamed"
        corpus["inputs"]["casesById"]["renamed"] = corpus["inputs"]["casesById"].pop("NS01")
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_summary_controls(corpus, tmp)
            script = load_summary_script(paths["deviations"], corpus["inputs"])
            expected = script_expectation(corpus["inputs"], script)
            self.assertEqual(expected["renamed"]["result"]["outcome"], "verifier-hold")
            self.assertEqual(expected["NS07"]["result"]["outcome"], "available")
            self.assertEqual(expected["NS22"]["result"]["backgroundAsCurrent"], "uncertain")
            self.assertEqual(expected["NS17"]["error"], {"code": "live_response_unknown", "phase": "send", "outcome": "unknown"})
            self.assertEqual(expected["NS13"]["error"]["code"], "live_receipt_invalid")

    def test_oracle_metrics_from_captured_native_run(self):
        score = score_summary_run(self.corpus, captured())
        self.assertEqual(score["claims"]["accuracy"], {"num": 30, "den": 30, "value": 1.0})
        self.assertEqual(score["outcomes"]["accuracy"], {"num": 24, "den": 24, "value": 1.0})
        self.assertEqual(score["errors"]["total"], 0)
        self.assertEqual(score["cost"]["actual"], {"source": "loopback_no_charge", "usd": "0"})
        for cid in ("NS10", "NS23"):
            self.assertEqual(len(record(captured(), cid)["prepared"]["body"]["state"]["quotes"]), 1)

    def test_deviations_handwritten_metrics(self):
        score = score_summary_run(self.corpus, captured("deviations"))
        self.assertEqual(score["claims"]["accuracy"], {"num": 22, "den": 30, "value": 0.733333})
        self.assertEqual(score["outcomes"]["accuracy"], {"num": 14, "den": 24, "value": 0.583333})
        self.assertEqual(score["claims"]["unsafeSupported"], 1)
        self.assertEqual(score["outcomes"]["unsafeAvailable"], 1)
        self.assertEqual(score["outcomes"]["availablePrecision"], {"num": 3, "den": 4, "value": 0.75})
        self.assertEqual(score["outcomes"]["heldInsteadOfRejected"], 2)
        self.assertEqual(score["outcomes"]["falseReject"], 1)
        self.assertEqual(score["outcomes"]["falseHold"], 3)
        self.assertEqual(score["errors"]["total"], 5)
        self.assertEqual(score["errors"]["unknown"], 1)
        self.assertEqual(score["checks"]["framing"]["presentMissedAsUncertain"], 1)
        self.assertEqual(score["checks"]["advice"]["unscoredPresent"], 1)
        self.assertEqual(score["checks"]["causality"]["falsePresent"], 1)
        self.assertEqual(score["cost"]["estimate"]["known"], 19)
        self.assertEqual(score["timing"]["errors"]["authorizedMayHaveSentMs"]["n"], 5)
        expected = script_expectation(self.inputs, load_summary_script(FIXTURES / "deviations.script.json", self.inputs))
        for rec in captured("deviations")["records"]:
            with self.subTest(case=rec["caseId"]):
                wanted = expected[rec["caseId"]]
                self.assertEqual({k: rec[k] for k in wanted}, wanted)

    def test_tamper_matrix_closed_errors(self):
        def mutate_question(run, coherent):
            p = run["records"][0]["prepared"]
            p["body"]["questions"]["claim-0"]["criteria"]["supported"] = "changed"
            if coherent:
                rehash_prepared(p)
        mutations = [
            ("missing_record", lambda r: r["records"].pop()),
            ("duplicate_record", lambda r: r["records"].append(copy.deepcopy(r["records"][0]))),
            ("case_binding_mismatch", lambda r: r["records"][0].update(caseSha256="0" * 64)),
            ("claim_binding_mismatch", lambda r: r["records"][0]["claimBinding"].reverse()),
            ("normalization_mismatch", lambda r: r["records"][0]["result"].update(outcome="verifier-hold")),
            ("normalization_mismatch", lambda r: r["records"][0]["result"]["claims"][0].update(decision="insufficient")),
            ("receipt_body_mismatch", lambda r: r["records"][0]["receipt"]["http"].update(bodyText="{}")),
            ("usage_mismatch", lambda r: r["records"][0]["receipt"]["usage"].update(inputTokens=True)),
            ("usage_mismatch", lambda r: r["records"][0]["receipt"]["usage"].update(inputTokens=120.0)),
            ("cost_mismatch", lambda r: r["records"][0]["receipt"]["cost"].update(chargedUsd="0")),
            ("receipt_binding_mismatch", lambda r: r["records"][0]["receipt"].update(bindingIdentity="0" * 64)),
            ("binding_invalid", lambda r: r["system"]["binding"]["verifier"]["policy"].update(choiceProbability=0.1)),
            ("adapter_preimage_mismatch", lambda r: r["system"]["adapterPreimage"].update(task="changed")),
            ("prepared_invalid", lambda r: mutate_question(r, False)),
            ("questions_mismatch", lambda r: mutate_question(r, True)),
            ("provenance_invalid", lambda r: r["provenance"].update(kind="real_measured", executionMode="live")),
            ("timing_invalid", lambda r: r["records"][0]["timing"].update(authorizedOffsetNs=10**30)),
            ("timing_invalid", lambda r: r["records"][0]["timing"].update(sendCallNs=True)),
            ("timing_invalid", lambda r: r["timing"].update(concurrency=1.0)),
            ("corpus_mismatch", lambda r: r["corpus"].update(inputsSha256="0" * 64)),
        ]
        for code, mutate in mutations:
            with self.subTest(code=code):
                run = captured()
                mutate(run)
                self.rejected(code, lambda: parse_summary_run(run, self.inputs))

    def test_replacement_character_body_is_always_hashed(self):
        run = captured()
        receipt = run["records"][0]["receipt"]
        raw = json.loads(receipt["http"]["bodyText"])
        raw["extra"] = "legitimate replacement character: \ufffd"
        receipt["http"]["bodyText"] = json.dumps(raw, ensure_ascii=False)
        self.rejected("receipt_body_mismatch", lambda: parse_summary_run(run, self.inputs))
        receipt["http"]["bodySha256"] = hashlib.sha256(receipt["http"]["bodyText"].encode("utf-8")).hexdigest()
        self.assertEqual(score_summary_run(self.corpus, run)["errors"]["total"], 0)

    def test_uncited_quote_cannot_be_smuggled_into_request(self):
        run = captured()
        prepared = record(run, "NS10")["prepared"]
        prepared["body"]["state"]["quotes"].append({"label": "Q2", "context": "report", "text": "미인용 사실"})
        rehash_prepared(prepared)
        self.rejected("request_mapping_mismatch", lambda: parse_summary_run(run, self.inputs))

    def test_raw_answer_change_with_rehashed_body_cannot_keep_result(self):
        run = captured()
        receipt = run["records"][0]["receipt"]
        body = json.loads(receipt["http"]["bodyText"])
        body["answers"]["claim-0"]["confidence"] = 0.1
        receipt["http"]["bodyText"] = canonical(body)
        receipt["http"]["bodySha256"] = hashlib.sha256(receipt["http"]["bodyText"].encode("utf-8")).hexdigest()
        self.rejected("normalization_mismatch", lambda: parse_summary_run(run, self.inputs))

    def test_errors_and_unrecorded_cases_keep_all_denominators(self):
        run = captured("deviations")
        record(run, "NS17")["error"]["outcome"] = "definite"
        self.rejected("error_invalid", lambda: parse_summary_run(run, self.inputs))
        run = captured("deviations")
        record(run, "NS08")["error"]["code"] = "live_http_500"
        self.rejected("error_not_reproducible", lambda: parse_summary_run(run, self.inputs))
        run = captured()
        for i, rec in enumerate(run["records"]):
            for key in ("receipt", "timing", "result"):
                rec.pop(key)
            if i:
                rec.pop("prepared")
            rec["status"] = "error"
            rec["error"] = {"code": "bench_not_attempted" if i else "bench_outcome_unrecorded",
                            "phase": "unrecorded", "outcome": "definite" if i else "unknown"}
        score = score_summary_run(self.corpus, run)
        self.assertEqual(score["claims"]["accuracy"], {"num": 0, "den": 30, "value": 0.0})
        self.assertEqual(score["outcomes"]["accuracy"], {"num": 0, "den": 24, "value": 0.0})
        self.assertEqual(score["timing"]["errors"]["withoutTiming"], 24)
        self.assertEqual(score["cost"]["estimate"]["knownTotalUsd"], None)
        self.assertGreater(float(score["cost"]["budget"]["unknownOutcomeReservedAtRiskUsd"]), 0)

    def test_cli_rejects_without_partial_output(self):
        run = captured()
        run["records"].pop()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.json"
            output = Path(tmp) / "score.json"
            path.write_text(json.dumps(run), encoding="utf-8")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                status = cli.main(["summary-verify-score", str(path), "--out", str(output)])
            self.assertEqual(status, 2)
            self.assertFalse(output.exists())
            self.assertEqual(json.loads(stream.getvalue())["error"]["code"], "missing_record")

    def test_script_expectation_applies_request_usage_bound_before_model_error(self):
        script = load_summary_script(FIXTURES / "oracle.script.json", self.inputs)
        bound = record(captured(), "NS01")["prepared"]["reservation"]["inputTokensUpperBound"]
        for scenario, usage, expected_error in (
            ("answers", bound, None),
            ("answers", bound + 1, "live_receipt_invalid"),
            ("model_mismatch", bound, "live_model_mismatch"),
            ("model_mismatch", bound + 1, "live_receipt_invalid"),
        ):
            with self.subTest(scenario=scenario, usage=usage):
                changed = copy.deepcopy(script)
                entry = next(e for e in changed["entries"] if e["caseId"] == "NS01")
                entry.update(scenario=scenario, usage={"inputTokens": usage, "outputTokens": 1})
                result = script_expectation(self.inputs, changed)["NS01"]
                if expected_error is None:
                    self.assertEqual(result["status"], "ok")
                    self.assertEqual(result["result"]["outcome"], "available")
                else:
                    self.assertEqual(result, {"status": "error", "error": {
                        "code": expected_error, "phase": "decode", "outcome": "definite"}})

    def test_script_expectation_rejects_oversized_request_before_transport(self):
        inputs = copy.deepcopy(self.inputs)
        inputs["casesById"]["NS01"]["payload"]["quotes"][0]["text"] = "가" * 150000
        script = load_summary_script(FIXTURES / "oracle.script.json", inputs)
        for scenario in ("answers", "silent", "http_error"):
            with self.subTest(scenario=scenario):
                changed = copy.deepcopy(script)
                entry = next(e for e in changed["entries"] if e["caseId"] == "NS01")
                entry["scenario"] = scenario
                if scenario != "answers":
                    del entry["claims"], entry["checks"]
                result = script_expectation(inputs, changed)["NS01"]
                self.assertEqual(result, {"status": "error", "error": {
                    "code": "live_request_too_large", "phase": "prepare", "outcome": "definite"}})

    def test_cli_rejects_unrepresentable_timing_without_partial_output(self):
        for variant, cid in (("oracle", "NS01"), ("deviations", "NS17")):
            with self.subTest(variant=variant):
                run = captured(variant)
                record(run, cid)["timing"]["sendCallNs"] = 10 ** 400
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "invalid.json"
                    output = Path(tmp) / "score.json"
                    path.write_text(json.dumps(run), encoding="utf-8")
                    stream = io.StringIO()
                    with contextlib.redirect_stdout(stream):
                        status = cli.main(["summary-verify-score", str(path), "--out", str(output)])
                    self.assertEqual(status, 2)
                    self.assertFalse(output.exists())
                    self.assertEqual(json.loads(stream.getvalue())["error"]["code"], "timing_invalid")


if __name__ == "__main__":
    unittest.main()
