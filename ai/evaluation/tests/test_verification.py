"""Semantic-verification benchmark: corpus validation, strict run binding, scoring on authored controls, CLI.

Every run here derives from an authored control and is mutated one mistake at a time. Nothing is a measurement."""
from __future__ import annotations

import contextlib
import copy
import functools
import hashlib
import io
import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

from zoop_eval import cli
from zoop_eval.contracts import Rejected
from zoop_eval.verification import (
    CONTROL_FILES, DEFAULT_VERIFY_CORPUS, LOOPBACK_SCRIPT_FILE, build_control, build_loopback_script, derive, load_inputs,
    load_verify_corpus, parse_loopback_script, parse_verify_run, score_verify_run, REFERENCE_POLICY,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "verification" / "controls"


@functools.lru_cache(maxsize=1)
def corpus():
    return load_verify_corpus()


def control(kind: str) -> dict[str, Any]:
    return build_control(corpus(), kind)


def score(run: dict[str, Any]) -> dict[str, Any]:
    return score_verify_run(corpus(), parse_verify_run(copy.deepcopy(run), corpus()))


def as_measured(run: dict[str, Any]) -> dict[str, Any]:
    """TEST DOUBLE ONLY: relabel an authored control as a recorded live provider run so the calibration path can be exercised."""
    out = copy.deepcopy(run)
    out["provenance"] = {"kind": "real_measured", "executionMode": "live", "recorder": "unit-test", "recordedAt": "2026-10-15T00:00:00+00:00"}
    out["system"]["endpointKind"] = "provider"
    return out


def record(run: dict[str, Any], case_id: str) -> dict[str, Any]:
    return next(r for r in run["records"] if r["caseId"] == case_id)


def num(metric: dict[str, Any]) -> tuple[Any, Any]:
    return metric["num"], metric["den"]


def temp_corpus(mutate: Callable[[dict[str, Any], dict[str, Any]], None], *, rebind: bool = True) -> Path:
    target = Path(tempfile.mkdtemp(prefix="zoop-verify-corpus-"))
    cases = json.loads((DEFAULT_VERIFY_CORPUS / "cases.json").read_text("utf-8"))
    gold = json.loads((DEFAULT_VERIFY_CORPUS / "gold.json").read_text("utf-8"))
    mutate(cases, gold)
    raw = json.dumps(cases, ensure_ascii=False).encode("utf-8")
    (target / "cases.json").write_bytes(raw)
    if rebind:
        gold["inputsSha256"] = hashlib.sha256(raw).hexdigest()
    (target / "gold.json").write_text(json.dumps(gold, ensure_ascii=False), "utf-8")
    return target


class Case(unittest.TestCase):
    def rejected(self, call: Callable[[], Any], code: str) -> Rejected:
        with self.assertRaises(Rejected) as ctx:
            call()
        self.assertEqual(ctx.exception.code, code, ctx.exception.message)
        return ctx.exception

    def parse_rejected(self, run: dict[str, Any], code: str) -> None:
        self.rejected(lambda: parse_verify_run(copy.deepcopy(run), corpus()), code)


class CorpusTests(Case):
    def test_authored_corpus_shape(self):
        c = corpus()
        self.assertEqual(len(c.inputs.cases), 28)
        self.assertEqual(sum(len(g["claims"]) for g in c.gold.values()), 55)
        self.assertEqual({g["gate"] for g in c.gold.values()}, {"supported", "hold", "reject"})
        self.assertEqual(c.inputs.split, "dev")
        self.assertFalse(c.gold_provenance["adjudicated"])
        self.assertEqual(c.gold_provenance["annotators"], 1)
        self.assertTrue(c.gold_provenance["devOnly"])

    def test_inputs_load_without_the_gold(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(DEFAULT_VERIFY_CORPUS / "cases.json", tmp)
            self.assertEqual(load_inputs(Path(tmp) / "cases.json").inputs_sha256, corpus().inputs.inputs_sha256)
            self.rejected(lambda: load_verify_corpus(Path(tmp)), "file_unreadable")

    def mutated(self, mutate, code, *, rebind=True):
        path = temp_corpus(mutate, rebind=rebind)
        try:
            self.rejected(lambda: load_verify_corpus(path), code)
        finally:
            shutil.rmtree(path, ignore_errors=True)

    def test_gold_key_leak_into_inputs(self):
        self.mutated(lambda cases, gold: cases["cases"][0]["candidate"]["claims"][0].update(decision="supported"), "gold_leak")

    def test_non_nfc_quote_is_rejected(self):
        def nfd(cases, gold):
            case = cases["cases"][0]
            case["document"]["text"] = case["document"]["text"].replace("한", "\u1112\u1161\u11ab", 1)
        self.mutated(nfd, "not_nfc")

    def test_quote_span_must_be_exact(self):
        self.mutated(lambda cases, gold: cases["cases"][0]["candidate"]["citations"][0].update(start=1), "quote_mismatch")

    def test_duplicate_case_and_claim(self):
        self.mutated(lambda cases, gold: cases["cases"].append(copy.deepcopy(cases["cases"][0])), "duplicate_case")
        def twin(cases, gold):
            claims = cases["cases"][0]["candidate"]["claims"]
            claims[1]["claimId"] = claims[0]["claimId"]
        self.mutated(twin, "duplicate_claim")

    def test_unused_citation_and_uncited_fact(self):
        def spare(cases, gold):
            cases["cases"][0]["candidate"]["citations"].append(
                {"evidenceId": "spare", "start": 0, "end": 2, "quote": cases["cases"][0]["document"]["text"][:2]})
        self.mutated(spare, "citation_unused")
        self.mutated(lambda cases, gold: cases["cases"][0]["candidate"]["claims"][0].update(evidenceIds=[]), "claim_citation_missing")

    def test_gold_must_bind_and_cover(self):
        self.mutated(lambda cases, gold: gold.update(inputsSha256="0" * 64), "gold_binding_mismatch", rebind=False)
        self.mutated(lambda cases, gold: gold["cases"].pop(), "gold_coverage")
        self.mutated(lambda cases, gold: gold["cases"][0]["claims"].pop(), "gold_coverage")

    def test_gold_gate_and_flags_must_follow_the_rule(self):
        self.mutated(lambda cases, gold: gold["cases"][0].update(expectedGate="reject"), "gold_gate_inconsistent")
        self.mutated(lambda cases, gold: gold["cases"][0].update(expectedAdvice=True, expectedGate="reject"), "gold_flag_inconsistent")

    def test_gold_must_declare_dev_only(self):
        self.mutated(lambda cases, gold: gold["provenance"].update(devOnly=False), "gold_provenance_invalid")

    def test_split_must_be_dev(self):
        self.mutated(lambda cases, gold: cases.update(split="test"), "malformed")

    def test_loopback_script_binds_to_inputs(self):
        script = build_loopback_script(corpus())
        self.assertEqual(len(parse_loopback_script(script, corpus().inputs)), 28)
        bad = copy.deepcopy(script)
        bad["inputsSha256"] = "0" * 64
        self.rejected(lambda: parse_loopback_script(bad, corpus().inputs), "script_binding_mismatch")
        short = copy.deepcopy(script)
        short["entries"].pop()
        self.rejected(lambda: parse_loopback_script(short, corpus().inputs), "script_coverage")


class ControlScoringTests(Case):
    def test_oracle_scores_perfectly_and_is_labelled_a_control(self):
        s = score(control("oracle"))
        self.assertIn("NOT a measurement", s["provenanceLabel"])
        self.assertEqual((num(s["claims"]["accuracy"]), s["claims"]["accuracy"]["value"]), ((55, 55), 1.0))
        self.assertEqual(num(s["gate"]["accuracy"]), (28, 28))
        self.assertEqual(num(s["gate"]["unsafeAccept"]), (0, 20))
        self.assertEqual(num(s["gate"]["coverage"]["safeCasesAccepted"]), (8, 8))
        self.assertEqual({k: v["num"] for k, v in s["gate"]["outcomes"].items()}, {"supported": 8, "hold": 5, "reject": 15, "error": 0})
        self.assertEqual(s["claims"]["macroF1"], {"value": 1.0, "classes": 3, "of": 3})
        self.assertEqual(num(s["flags"]["prohibitedAdvice"]["recall"]), (3, 3))
        self.assertEqual(num(s["flags"]["unsupportedCausality"]["recall"]), (2, 2))
        self.assertEqual(s["claims"]["byTag"]["limitation"]["claims"], 4)
        self.assertEqual(s["claims"]["byTag"]["numeric-derived"]["claims"], 6)

    def test_degraded_accepts_everything_so_coverage_hides_unsafe_accepts(self):
        s = score(control("degraded_all_supported"))
        self.assertEqual(num(s["gate"]["coverage"]["safeCasesAccepted"]), (8, 8))  # perfect coverage ...
        self.assertEqual(num(s["gate"]["unsafeAccept"]), (20, 20))                 # ... paid for by accepting every unsafe case
        self.assertEqual(num(s["gate"]["coverage"]["acceptedPrecision"]), (8, 28))
        self.assertEqual(num(s["claims"]["accuracy"]), (35, 55))
        self.assertEqual(num(s["claims"]["unsafeSupported"]), (20, 20))
        self.assertEqual(num(s["flags"]["prohibitedAdvice"]["recall"]), (0, 3))
        self.assertIsNone(s["flags"]["prohibitedAdvice"]["precision"]["value"])  # nothing predicted: null, not 0 or 1

    def test_errors_are_neither_hold_nor_reject_nor_accept(self):
        s = score(control("injected_errors"))
        self.assertEqual(num(s["errors"]["cases"]), (4, 28))
        self.assertEqual(s["errors"]["byCode"], {"native_model_mismatch": 1, "native_response_invalid": 1, "provider_http_500": 1,
                                                 "provider_response_unknown": 1})
        self.assertEqual((s["errors"]["outcomeDefinite"], s["errors"]["outcomeUnknown"]), (3, 1))
        outcomes = {k: v["num"] for k, v in s["gate"]["outcomes"].items()}
        self.assertEqual(outcomes, {"supported": 8, "hold": 5, "reject": 11, "error": 4})  # all four injected errors are gold-reject cases
        self.assertEqual(num(s["gate"]["accuracy"]), (24, 28))
        self.assertEqual(num(s["claims"]["accuracy"])[1], 55)  # unscored claims stay in the denominator

    def test_loopback_expected_shows_each_authored_mistake(self):
        s = score(control("loopback_script_expected"))
        self.assertEqual(num(s["claims"]["accuracy"]), (45, 55))
        self.assertEqual(num(s["gate"]["accuracy"]), (21, 28))
        self.assertEqual(num(s["gate"]["unsafeAccept"]), (1, 20))
        self.assertEqual(num(s["gate"]["heldInsteadOfRejected"]), (2, 15))  # weak contradiction and uncertain Noul hold, they do not accept
        self.assertEqual(num(s["gate"]["rejectedInsteadOfHeld"]), (1, 5))
        self.assertEqual(num(s["errors"]["cases"]), (3, 28))
        self.assertEqual(num(s["flags"]["unsupportedCausality"]["recall"]), (1, 2))
        self.assertEqual(s["flags"]["unsupportedCausality"]["uncertainMissedPositives"], 1)
        self.assertEqual(num(s["flags"]["prohibitedAdvice"]["recall"]), (2, 3))
        self.assertEqual(s["flags"]["prohibitedAdvice"]["unscoredPositives"], 1)

    def test_all_errors_gives_null_rates_not_zero_or_one(self):
        run = control("injected_errors")
        run["records"] = [{k: v for k, v in r.items() if k in ("caseId", "caseSha256", "claimBinding")}
                          | {"status": "error", "error": {"code": "provider_response_unknown", "outcome": "unknown"}} for r in run["records"]]
        s = score(run)
        self.assertEqual(num(s["gate"]["outcomes"]["error"]), (28, 28))
        self.assertIsNone(s["claims"]["macroF1"]["value"])
        self.assertIsNone(s["gate"]["coverage"]["acceptedPrecision"]["value"])
        self.assertEqual(s["gate"]["accuracy"]["value"], 0.0)
        self.assertEqual(s["timing"]["latencyMs"]["wall"]["n"], 0)
        self.assertEqual(s["cost"]["usd"], {"known": 0, "unknown": 0, "total": None})

    def test_checked_in_fixtures_equal_the_generator(self):
        for name, kind in CONTROL_FILES.items():
            self.assertEqual(json.loads((FIXTURES / name).read_text("utf-8")), build_control(corpus(), kind), name)
        self.assertEqual(json.loads((FIXTURES / LOOPBACK_SCRIPT_FILE).read_text("utf-8")), build_loopback_script(corpus()))

    def test_derive_applies_the_declared_policy(self):
        run = control("oracle")
        raw = copy.deepcopy(record(run, "VK-01")["raw"])
        raw["answers"]["claim-0"]["confidence"] = 0.5
        self.assertEqual(derive(raw, 3, "jev-1.14.0", REFERENCE_POLICY)["decisions"][0], "insufficient")
        lenient = {**REFERENCE_POLICY, "choiceConfidence": 0.4}
        self.assertEqual(derive(raw, 3, "jev-1.14.0", lenient)["decisions"][0], "supported")


class CalibrationAndCostTests(Case):
    def test_calibration_is_not_evaluated_for_authored_probabilities(self):
        for kind in ("oracle", "loopback_script_expected"):
            self.assertEqual(score(control(kind))["calibration"]["status"], "not_evaluated")

    def test_calibration_reads_recorded_live_distributions_only(self):
        s = score(as_measured(control("oracle")))
        cal = s["calibration"]
        self.assertEqual((cal["status"], cal["n"]), ("evaluated", 55))
        self.assertAlmostEqual(cal["brier"], 0.00135, places=6)       # (1-.97)^2 + 2*.015^2 for every correct claim
        self.assertAlmostEqual(cal["logLoss"], -math.log(0.97), places=5)
        self.assertEqual([(b["range"], b["n"]) for b in cal["bins"]], [([0.97, 1.0], 55)])
        self.assertTrue(any("not a calibration of any production threshold" in c for c in cal["caveats"]))
        self.assertIn("recorded live provider", s["provenanceLabel"])

    def test_calibration_counts_a_wrong_confident_claim(self):
        run = as_measured(control("degraded_all_supported"))
        cal = score(run)["calibration"]
        self.assertGreater(cal["brier"], 0.3)
        self.assertGreater(cal["expectedCalibrationError"], 0.3)

    def test_unknown_cost_is_never_reported_as_zero(self):
        s = score(control("oracle"))
        self.assertEqual(s["cost"]["usd"], {"known": 0, "unknown": 28, "total": None})
        self.assertEqual(s["headline"]["cost.usd"]["value"], None)

    def test_zero_cost_needs_a_proven_source(self):
        run = control("oracle")
        record(run, "VK-01")["call"]["cost"] = {"usd": 0, "source": "unknown"}
        self.parse_rejected(run, "cost_unproven")
        run = control("oracle")
        record(run, "VK-01")["call"]["cost"] = {"usd": 0, "source": "loopback_no_charge"}  # not a loopback control
        self.parse_rejected(run, "cost_unproven")
        run = control("oracle")
        record(run, "VK-01")["call"]["cost"] = {"usd": 0.01, "source": "provider_reported"}  # authored run cannot report a provider cost
        self.parse_rejected(run, "cost_unproven")
        run = as_measured(control("oracle"))
        record(run, "VK-01")["call"]["cost"] = {"usd": 0.01, "source": "provider_reported"}
        self.assertEqual(score(run)["cost"]["usd"], {"known": 1, "unknown": 27, "total": 0.01})

    def test_loopback_zero_cost_is_valid_only_on_a_loopback_control(self):
        run = control("oracle")
        run["provenance"]["controlKind"] = "loopback_fake_native_server"
        run["system"]["endpointKind"] = "loopback_fake"
        for r in run["records"]:
            if "call" in r:
                r["call"]["cost"] = {"usd": 0, "source": "loopback_no_charge"}
        s = score(run)
        self.assertEqual(s["cost"]["usd"]["total"], 0)
        self.assertEqual(s["timing"]["semantics"], "loopback_fake_server_time_not_model_latency")


class BoundaryTests(Case):
    def test_missing_duplicate_and_unknown_cases(self):
        run = control("oracle")
        run["records"].pop()
        self.parse_rejected(run, "missing_record")
        run = control("oracle")
        run["records"].append(copy.deepcopy(run["records"][3]))
        self.parse_rejected(run, "duplicate_record")
        run = control("oracle")
        run["records"][0]["caseId"] = "VK-99"
        self.parse_rejected(run, "unknown_case")

    def test_case_and_claim_binding(self):
        run = control("oracle")
        record(run, "VK-01")["caseSha256"] = "0" * 64
        self.parse_rejected(run, "case_binding_mismatch")
        run = control("oracle")
        record(run, "VK-01")["claimBinding"].reverse()
        self.parse_rejected(run, "claim_binding_mismatch")
        run = control("oracle")
        record(run, "VK-01")["result"]["claims"].reverse()
        self.parse_rejected(run, "claim_coverage_mismatch")
        run = control("oracle")
        record(run, "VK-01")["result"]["claims"][0]["claimId"] = "VK-02-c1"
        self.parse_rejected(run, "unknown_claim")
        run = control("oracle")
        record(run, "VK-01")["result"]["claims"][1]["claimId"] = record(run, "VK-01")["result"]["claims"][0]["claimId"]
        self.parse_rejected(run, "duplicate_claim")

    def test_corpus_binding(self):
        for key in ("corpusId", "corpusRevision", "inputsSha256", "split"):
            run = control("oracle")
            run["corpus"][key] = "x" if key != "split" else "test"
            self.parse_rejected(run, "corpus_mismatch")

    def test_normalized_result_must_follow_from_the_raw_receipt(self):
        run = control("oracle")
        record(run, "VK-02")["result"]["gate"] = "supported"
        self.parse_rejected(run, "normalization_mismatch")
        run = control("oracle")
        record(run, "VK-02")["result"]["claims"][1]["decision"] = "supported"
        self.parse_rejected(run, "normalization_mismatch")
        run = control("oracle")
        record(run, "VK-06")["result"]["prohibitedAdvice"] = False
        self.parse_rejected(run, "normalization_mismatch")
        run = control("oracle")
        record(run, "VK-02")["raw"]["answers"]["claim-1"]["probabilities"]["supported"] = 0.5
        self.parse_rejected(run, "raw_receipt_invalid")
        run = control("oracle")
        record(run, "VK-02")["raw"]["model"] = "jev-1.13.0"
        self.parse_rejected(run, "raw_receipt_invalid")

    def test_declared_policy_is_what_the_normalization_uses(self):
        run = control("oracle")
        run["system"]["policy"]["choiceProbability"] = 0.99  # now a p=0.97 supported is not accepted: the declared result is stale
        self.parse_rejected(run, "normalization_mismatch")

    def test_error_records_must_be_reproducible(self):
        run = control("injected_errors")
        record(run, "VK-11")["raw"] = copy.deepcopy(control("oracle")["records"][10]["raw"])  # a valid receipt labelled model mismatch
        self.parse_rejected(run, "error_not_reproducible")
        run = control("injected_errors")
        for key in ("raw", "call", "latencyMs"):
            del record(run, "VK-11")[key]
        self.parse_rejected(run, "error_invalid")
        run = control("injected_errors")
        record(run, "VK-02")["raw"] = {"model": "jev-1.14.0"}
        self.parse_rejected(run, "error_invalid")
        run = control("injected_errors")
        record(run, "VK-15")["error"]["outcome"] = "definite"
        self.parse_rejected(run, "error_invalid")

    def test_ok_record_needs_its_evidence(self):
        for missing in ("raw", "call", "result"):
            run = control("oracle")
            del record(run, "VK-01")[missing]
            self.parse_rejected(run, "malformed")

    def test_one_version_per_run(self):
        for key in ("model", "providerRevision", "promptVersion", "policyVersion"):
            run = control("oracle")
            record(run, "VK-01")["call"][key] = "other"
            self.parse_rejected(run, "mixed_versions")

    def test_model_must_be_pinned(self):
        for alias in ("jev-latest", "jev-preview"):
            run = control("oracle")
            run["system"]["model"] = alias
            self.parse_rejected(run, "model_not_pinned")

    def test_usage_must_match_the_receipt(self):
        run = control("oracle")
        record(run, "VK-01")["call"]["usage"]["inputTokens"] += 1
        self.parse_rejected(run, "usage_mismatch")
        run = control("injected_errors")
        record(run, "VK-08")["call"]["usage"]["inputTokens"] = 5  # a non-JSON receipt reported no usage: unknown must stay null
        self.parse_rejected(run, "usage_mismatch")

    def test_provenance_rules(self):
        run = control("oracle")
        run["provenance"].update(kind="real_measured", executionMode="replay", recordedAt="2026-10-15T00:00:00+00:00")
        self.parse_rejected(run, "provenance_invalid")
        run = control("oracle")
        run["provenance"].update(kind="real_measured", executionMode="live", recordedAt="2026-10-15T00:00:00+00:00")  # still carries controlKind
        self.parse_rejected(run, "provenance_invalid")
        run = as_measured(control("oracle"))
        run["system"]["endpointKind"] = "loopback_fake"
        self.parse_rejected(run, "provenance_invalid")
        run = control("oracle")
        run["provenance"]["recordedAt"] = "2026-10-15T00:00:00+00:00"
        self.parse_rejected(run, "provenance_invalid")
        run = control("oracle")
        del run["provenance"]["controlKind"]
        self.parse_rejected(run, "provenance_invalid")
        run = control("oracle")
        run["provenance"]["controlKind"] = "made_up"
        self.rejected(lambda: parse_verify_run(run, corpus()), "malformed")
        run = control("oracle")
        run["system"]["endpointKind"] = "loopback_fake"  # a plain oracle control cannot claim a loopback endpoint
        self.parse_rejected(run, "provenance_invalid")

    def test_schema_and_strictness(self):
        run = control("oracle")
        run["schema"] = "zoop-bench-run-1"
        self.parse_rejected(run, "schema_mismatch")
        run = control("oracle")
        run["records"][0]["expectedGate"] = "supported"  # gold-shaped key in a run
        self.parse_rejected(run, "malformed")
        run = control("oracle")
        run["system"]["policy"]["noulFalse"] = 0.95
        self.parse_rejected(run, "policy_invalid")


class CliTests(Case):
    def call(self, *argv: str) -> tuple[int, Any]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(list(argv))
        text = out.getvalue()
        return code, (text if "text" in argv or not text.strip() else json.loads(text))

    def test_validate_controls_score_round_trip(self):
        code, described = self.call("verify-validate")
        self.assertEqual((code, described["counts"]["cases"], described["goldProvenance"]["adjudicated"]), (0, 28, False))
        with tempfile.TemporaryDirectory() as tmp:
            code, written = self.call("verify-controls", "--out-dir", tmp)
            self.assertEqual(code, 0)
            self.assertEqual(len(written["written"]), len(CONTROL_FILES) + 1)
            code, doc = self.call("verify-score", str(Path(tmp) / "oracle-dev.run.json"))
            self.assertEqual((code, doc["claims"]["accuracy"]["value"]), (0, 1.0))
            code, text = self.call("verify-score", str(Path(tmp) / "degraded-dev.run.json"), "--format", "text")
            self.assertIn("UNSAFE-ACCEPT", text)
            self.assertIn("NOT a measurement", text)
            self.assertIn("NOT EVALUATED", text)
            out = Path(tmp) / "score.json"
            code, _ = self.call("verify-score", str(Path(tmp) / "oracle-dev.run.json"), "--out", str(out))
            self.assertEqual(json.loads(out.read_text("utf-8"))["schema"], "zoop-verify-score-1")

    def test_rejections_exit_two_with_a_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = control("oracle")
            run["records"].pop()
            path = Path(tmp) / "short.run.json"
            path.write_text(json.dumps(run), "utf-8")
            code, doc = self.call("verify-score", str(path))
            self.assertEqual((code, doc["ok"], doc["error"]["code"]), (2, False, "missing_record"))
            path.write_text('{"schema": "zoop-verify-run-1", "schema": "x"}', "utf-8")
            code, doc = self.call("verify-score", str(path))
            self.assertEqual((code, doc["error"]["code"]), (2, "json_duplicate_key"))

    def test_the_bench_scorer_does_not_accept_a_verification_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "oracle.run.json"
            path.write_text(json.dumps(control("oracle")), "utf-8")
            code, doc = self.call("score", str(path))
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
