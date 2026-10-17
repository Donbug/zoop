"""Offline Korean-finance semantic-verification benchmark: corpus, run and score contracts, authored controls.

Stdlib only. Nothing here calls a model or a network service. A run is what a producer (the worker bridge
`ai/worker/scripts/verification_bench.py`) recorded for the *visible* inputs (`cases.json`); the gold
(`gold.json`) is only ever opened by `load_verify_corpus`, i.e. by validate, controls and score.

What is measured is the verdict a verifier returned for authored candidate claims: per-claim decision
(supported / contradicted / insufficient), the case gate (supported / hold / reject), the prohibited-advice and
unsupported-causality flags, and where the pipeline errored. Errors, holds and rejects are never merged.
Everything produced from authored scripts or a local fake server is an AUTHORED CONTROL that exercises the
harness; it is not evidence about any model."""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import SCORER_VERSION
from .contracts import (
    SCHEMA_VERIFY_CASES, SCHEMA_VERIFY_GOLD, SCHEMA_VERIFY_LOOPBACK, SCHEMA_VERIFY_RUN, SCHEMA_VERIFY_SCORE,
    choice, flag, free_mapping, instant, integer, mapping, number, parse_json, reject, sequence, text, unique,
)
from .stats import f1, ratio
from .timing import parse_trace, summarize

DEFAULT_VERIFY_CORPUS = Path(__file__).resolve().parent.parent / "corpus" / "fin-verify-ko-v1"
DECISIONS = ("supported", "contradicted", "insufficient")
GATES = ("supported", "hold", "reject")
ASSERTION_KINDS = ("fact", "interpretation", "limitation")
TAGS = ("plain", "direction", "negation", "time", "entity", "numeric", "numeric-derived", "causal", "advice", "limitation",
        "unsupported-detail")
POLICY_KEYS = ("choiceProbability", "choiceConfidence", "noulTrue", "noulFalse", "distributionTolerance")
# The provisional native-Jev policy at authoring time. A run declares the policy it was produced under; the scorer uses the
# declared one and warns when it differs from this reference. `ai/worker/tests/test_verification_bench.py` pins it to native_jev.
REFERENCE_POLICY = {"choiceProbability": 0.90, "choiceConfidence": 0.80, "noulTrue": 0.90, "noulFalse": 0.10, "distributionTolerance": 0.02}
PROHIBITED_KEY = "prohibited-advice"
CAUSALITY_KEY = "unsupported-causality"
ENDPOINT_KINDS = ("provider", "loopback_fake", "none")
CONTROL_KINDS = ("oracle", "degraded_all_supported", "injected_errors", "loopback_script_expected", "loopback_fake_native_server")
COST_SOURCES = ("unknown", "loopback_no_charge", "provider_reported")
NATIVE_INVALID = ("native_response_invalid", "native_model_mismatch", "native_answers_invalid")
ERROR_OUTCOMES = ("definite", "unknown")
SCENARIOS = ("answers", "http_error", "non_json", "model_mismatch")
LOOPBACK_MISMATCH_MODEL = "jev-latest"
_MOVING_ALIAS = re.compile(r"(latest|preview)$")
_GOLD_ONLY_KEYS = {"expectedGate", "expectedAdvice", "expectedCausality", "expectedDecision", "decision", "tags", "note"}
CALIBRATION_BINS = ((0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 0.97), (0.97, 1.0000001))
LOG_LOSS_FLOOR = 1e-6
CONTROL_FILES = {
    "oracle-dev.run.json": "oracle", "degraded-dev.run.json": "degraded_all_supported",
    "injected-errors-dev.run.json": "injected_errors", "loopback-expected-dev.run.json": "loopback_script_expected",
}
LOOPBACK_SCRIPT_FILE = "loopback-script.json"
TIMING_SEMANTICS = {
    "loopback_fake_native_server": "loopback_fake_server_time_not_model_latency",
    "loopback_script_expected": "authored_control_values_not_a_measurement",
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def case_sha256(case: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(case).encode("utf-8")).hexdigest()


def gate_of(decisions: list[str], advice: bool, causality: bool) -> str:
    """The documented gate rule (same as the worker): reject on advice, causality or any contradiction; hold on any insufficient."""
    if advice or causality or "contradicted" in decisions:
        return "reject"
    return "hold" if "insufficient" in decisions else "supported"


def _nfc(value: Any, where: str) -> str:
    out = text(value, where)
    if not unicodedata.is_normalized("NFC", out):
        reject("not_nfc", f"{where}: text must be NFC normalized (offsets are Unicode code points)")
    return out


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        reject("file_unreadable", f"{path}: {exc.strerror or exc}")


def _leak_scan(value: Any, where: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _GOLD_ONLY_KEYS:
                reject("gold_leak", f"{where}: system-visible input carries gold-only key {key!r}")
            _leak_scan(item, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _leak_scan(item, f"{where}[{index}]")


# ---------------------------------------------------------------------------------------------------------------- corpus

@dataclass(frozen=True)
class VerifyInputs:
    """Exactly what a producer may see."""
    corpus_id: str
    revision: str
    split: str
    inputs_sha256: str
    cases: dict[str, dict[str, Any]]

    def claim_ids(self, case_id: str) -> list[str]:
        return [c["claimId"] for c in self.cases[case_id]["candidate"]["claims"]]

    def binding(self, case_id: str) -> list[dict[str, str]]:
        return [{"claimId": cid, "key": f"claim-{index}"} for index, cid in enumerate(self.claim_ids(case_id))]


@dataclass(frozen=True)
class VerifyCorpus:
    inputs: VerifyInputs
    gold_revision: str
    gold_sha256: str
    gold_provenance: dict[str, Any]
    gold: dict[str, dict[str, Any]]  # caseId -> {gate, advice, causality, claims: {claimId: {decision, tags}}}


def load_inputs(path: Path) -> VerifyInputs:
    """Validate `cases.json` alone. Never touches the gold, so a producer can call it."""
    raw = _read_bytes(path)
    doc = mapping(parse_json(raw, str(path)), "cases", ("schema", "corpusId", "revision", "split", "provenance", "cases"))
    if doc["schema"] != SCHEMA_VERIFY_CASES:
        reject("schema_mismatch", f"cases: expected schema {SCHEMA_VERIFY_CASES}")
    _leak_scan(doc, "cases")
    mapping(doc["provenance"], "cases.provenance", ("fictional", "language", "documents", "candidates", "split"))
    corpus_id, revision = text(doc["corpusId"], "cases.corpusId"), text(doc["revision"], "cases.revision")
    split = choice(doc["split"], ("dev",), "cases.split")
    cases: dict[str, dict[str, Any]] = {}
    for index, raw_case in enumerate(sequence(doc["cases"], "cases.cases", 1)):
        where = f"cases[{index}]"
        case = mapping(raw_case, where, ("caseId", "document", "company", "candidate"))
        case_id = text(case["caseId"], f"{where}.caseId")
        if case_id in cases:
            reject("duplicate_case", f"duplicate caseId {case_id!r}")
        document = mapping(case["document"], f"{where}.document", ("documentId", "text"))
        text(document["documentId"], f"{where}.document.documentId")
        body = _nfc(document["text"], f"{where}.document.text")
        company = mapping(case["company"], f"{where}.company", ("companyId", "name"))
        text(company["companyId"], f"{where}.company.companyId")
        _nfc(company["name"], f"{where}.company.name")
        candidate = mapping(case["candidate"], f"{where}.candidate", ("claims", "citations"))
        citations: dict[str, dict[str, Any]] = {}
        for ci, raw_ref in enumerate(sequence(candidate["citations"], f"{where}.candidate.citations", 1)):
            ref = mapping(raw_ref, f"{where}.citations[{ci}]", ("evidenceId", "start", "end", "quote"))
            evidence_id = text(ref["evidenceId"], f"{where}.citations[{ci}].evidenceId")
            if evidence_id in citations:
                reject("duplicate_evidence", f"{case_id}: duplicate evidenceId {evidence_id!r}")
            start, end = integer(ref["start"], f"{where}.citations[{ci}].start"), integer(ref["end"], f"{where}.citations[{ci}].end", 1)
            quote = _nfc(ref["quote"], f"{where}.citations[{ci}].quote")
            if not start < end <= len(body) or body[start:end] != quote:
                reject("quote_mismatch", f"{case_id}: citation {evidence_id!r} is not the exact code-point span of the document")
            citations[evidence_id] = ref
        used: set[str] = set()
        ids: list[str] = []
        for ki, raw_claim in enumerate(sequence(candidate["claims"], f"{where}.candidate.claims", 1)):
            claim = mapping(raw_claim, f"{where}.claims[{ki}]", ("claimId", "text", "assertionKind", "evidenceIds"))
            ids.append(text(claim["claimId"], f"{where}.claims[{ki}].claimId"))
            _nfc(claim["text"], f"{where}.claims[{ki}].text")
            kind = choice(claim["assertionKind"], ASSERTION_KINDS, f"{where}.claims[{ki}].assertionKind")
            evidence = [text(e, f"{where}.claims[{ki}].evidenceIds[]") for e in sequence(claim["evidenceIds"], f"{where}.claims[{ki}].evidenceIds")]
            unique(evidence, f"{where}.claims[{ki}].evidenceIds")
            if not set(evidence) <= citations.keys():
                reject("claim_citation_missing", f"{case_id}: claim {ids[-1]!r} cites an unknown evidenceId")
            if kind != "limitation" and not evidence:
                reject("claim_citation_missing", f"{case_id}: non-limitation claim {ids[-1]!r} needs a cited quote")
            used |= set(evidence)
        unique(ids, f"{case_id} claimIds", "duplicate_claim")
        if used != citations.keys():
            reject("citation_unused", f"{case_id}: citations not referenced by any claim")
        if all(c["assertionKind"] == "limitation" for c in candidate["claims"]):
            reject("claim_citation_missing", f"{case_id}: a candidate needs at least one cited (non-limitation) claim")
        cases[case_id] = case
    return VerifyInputs(corpus_id, revision, split, hashlib.sha256(raw).hexdigest(), cases)


def load_verify_corpus(directory: Path = DEFAULT_VERIFY_CORPUS) -> VerifyCorpus:
    inputs = load_inputs(directory / "cases.json")
    raw = _read_bytes(directory / "gold.json")
    doc = mapping(parse_json(raw, "gold.json"), "gold", ("schema", "corpusId", "revision", "inputsSha256", "provenance", "cases"))
    if doc["schema"] != SCHEMA_VERIFY_GOLD:
        reject("schema_mismatch", f"gold: expected schema {SCHEMA_VERIFY_GOLD}")
    if doc["corpusId"] != inputs.corpus_id or doc["inputsSha256"] != inputs.inputs_sha256:
        reject("gold_binding_mismatch", "gold is bound to a different cases.json (corpusId or inputsSha256)")
    prov = mapping(doc["provenance"], "gold.provenance", ("annotators", "adjudicated", "synthetic", "devOnly", "authoredFrom", "note"))
    integer(prov["annotators"], "gold.provenance.annotators", 1)
    for key in ("adjudicated", "synthetic", "devOnly"):
        flag(prov[key], f"gold.provenance.{key}")
    text(prov["authoredFrom"], "gold.provenance.authoredFrom")
    text(prov["note"], "gold.provenance.note")
    if not prov["devOnly"]:
        reject("gold_provenance_invalid", "this corpus is dev-only; the gold must say devOnly=true")
    gold: dict[str, dict[str, Any]] = {}
    for index, raw_case in enumerate(sequence(doc["cases"], "gold.cases", 1)):
        where = f"gold.cases[{index}]"
        item = mapping(raw_case, where, ("caseId", "expectedGate", "expectedAdvice", "expectedCausality", "claims"))
        case_id = text(item["caseId"], f"{where}.caseId")
        if case_id in gold:
            reject("duplicate_gold", f"duplicate gold caseId {case_id!r}")
        gate = choice(item["expectedGate"], GATES, f"{where}.expectedGate")
        advice, causality = flag(item["expectedAdvice"], f"{where}.expectedAdvice"), flag(item["expectedCausality"], f"{where}.expectedCausality")
        claims: dict[str, dict[str, Any]] = {}
        for ci, raw_claim in enumerate(sequence(item["claims"], f"{where}.claims", 1)):
            claim = mapping(raw_claim, f"{where}.claims[{ci}]", ("claimId", "decision", "tags", "note"))
            claim_id = text(claim["claimId"], f"{where}.claims[{ci}].claimId")
            if claim_id in claims:
                reject("duplicate_gold", f"{case_id}: duplicate gold claim {claim_id!r}")
            tags = [choice(t, TAGS, f"{where}.claims[{ci}].tags[]") for t in sequence(claim["tags"], f"{where}.claims[{ci}].tags", 1)]
            text(claim["note"], f"{where}.claims[{ci}].note")
            claims[claim_id] = {"decision": choice(claim["decision"], DECISIONS, f"{where}.claims[{ci}].decision"), "tags": tags}
        gold[case_id] = {"gate": gate, "advice": advice, "causality": causality, "claims": claims}
    if set(gold) != set(inputs.cases):
        reject("gold_coverage", f"gold cases differ from cases.json: missing {sorted(set(inputs.cases) - set(gold))}, extra {sorted(set(gold) - set(inputs.cases))}")
    for case_id, item in gold.items():
        if set(item["claims"]) != set(inputs.claim_ids(case_id)):
            reject("gold_coverage", f"{case_id}: gold claims do not exactly cover the candidate claims")
        decisions = [item["claims"][c]["decision"] for c in inputs.claim_ids(case_id)]
        if gate_of(decisions, item["advice"], item["causality"]) != item["gate"]:
            reject("gold_gate_inconsistent", f"{case_id}: expectedGate disagrees with the documented gate rule over the claim labels")
        all_tags = {t for c in item["claims"].values() for t in c["tags"]}
        if ("advice" in all_tags) != item["advice"] or ("causal" in all_tags) != item["causality"]:
            reject("gold_flag_inconsistent", f"{case_id}: advice/causal tags and expectedAdvice/expectedCausality disagree")
        for claim in inputs.cases[case_id]["candidate"]["claims"]:
            if ("limitation" in item["claims"][claim["claimId"]]["tags"]) != (claim["assertionKind"] == "limitation"):
                reject("gold_flag_inconsistent", f"{case_id}: limitation tag and assertionKind disagree for {claim['claimId']!r}")
    return VerifyCorpus(inputs, text(doc["revision"], "gold.revision"), hashlib.sha256(raw).hexdigest(), prov, gold)


def describe(corpus: VerifyCorpus) -> dict[str, Any]:
    counts: dict[str, dict[str, int]] = {"gates": {}, "decisions": {}, "tags": {}}
    for item in corpus.gold.values():
        counts["gates"][item["gate"]] = counts["gates"].get(item["gate"], 0) + 1
        for claim in item["claims"].values():
            counts["decisions"][claim["decision"]] = counts["decisions"].get(claim["decision"], 0) + 1
            for tag in claim["tags"]:
                counts["tags"][tag] = counts["tags"].get(tag, 0) + 1
    return {"ok": True, "corpusId": corpus.inputs.corpus_id, "corpusRevision": corpus.inputs.revision, "goldRevision": corpus.gold_revision,
            "split": corpus.inputs.split, "inputsSha256": corpus.inputs.inputs_sha256, "goldSha256": corpus.gold_sha256,
            "goldProvenance": corpus.gold_provenance,
            "counts": {"cases": len(corpus.gold), "claims": sum(len(g["claims"]) for g in corpus.gold.values()),
                       "expectedAdvice": sum(g["advice"] for g in corpus.gold.values()),
                       "expectedCausality": sum(g["causality"] for g in corpus.gold.values()),
                       **{k: dict(sorted(v.items())) for k, v in counts.items()}},
            "checks": ["schema and corpus binding (gold.inputsSha256 equals the cases.json digest)", "NFC text and exact code-point quote spans",
                       "unique case, claim and evidence ids; every citation used; every fact claim cited",
                       "no gold-only key in the system-visible cases.json", "gold exactly covers every case and claim",
                       "expectedGate equals the documented gate rule over the claim labels", "advice/causal/limitation tags agree with the flags and claim kinds",
                       "dev split only"],
            "note": "single-author, unadjudicated, synthetic dev gold: supports harness and pipeline checks, not accuracy claims about real Korean finance text"}


# ------------------------------------------------------------------------------------------------- native-Jev reading

def _unit(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ValueError("native_answers_invalid")
    return float(value)


def _choice_answer(answer: Any, tolerance: float) -> tuple[str, dict[str, float], float]:
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise ValueError("native_answers_invalid")
    reported = answer.get("probabilities")
    if not isinstance(reported, dict) or set(reported) != set(DECISIONS):
        raise ValueError("native_answers_invalid")
    probabilities = {option: _unit(reported[option]) for option in DECISIONS}
    if abs(sum(probabilities.values()) - 1.0) > tolerance:
        raise ValueError("native_answers_invalid")
    picked = answer.get("choice")
    if not isinstance(picked, str) or picked not in probabilities or probabilities[picked] < max(probabilities.values()) - 1e-9:
        raise ValueError("native_answers_invalid")
    return picked, probabilities, _unit(answer.get("confidence"))


def derive(raw: Any, claim_count: int, model: str, policy: dict[str, float]) -> dict[str, Any]:
    """Re-derive the normalized outcome from a raw native-Jev body under a declared policy. Mirrors the worker's validation
    order and codes; raises ValueError(code) for a body the worker must have refused."""
    if not isinstance(raw, dict) or not isinstance(raw.get("answers"), dict):
        raise ValueError("native_response_invalid")
    if raw.get("model") != model:
        raise ValueError("native_model_mismatch")
    answers = raw["answers"]
    if set(answers) != {f"claim-{i}" for i in range(claim_count)} | {PROHIBITED_KEY, CAUSALITY_KEY}:
        raise ValueError("native_answers_invalid")
    decided: list[str] = []
    distributions: list[dict[str, float]] = []
    picks: list[str] = []
    for index in range(claim_count):
        picked, probabilities, confidence = _choice_answer(answers[f"claim-{index}"], policy["distributionTolerance"])
        accepted = picked == "insufficient" or (probabilities[picked] >= policy["choiceProbability"] and confidence >= policy["choiceConfidence"])
        decided.append(picked if accepted else "insufficient")
        distributions.append(probabilities)
        picks.append(picked)

    def noul(key: str) -> tuple[float, bool, bool]:
        value = answers[key]
        if not isinstance(value, dict) or value.get("type") != "noul":
            raise ValueError("native_answers_invalid")
        p = _unit(value.get("noul"))
        return p, p >= policy["noulTrue"], policy["noulFalse"] < p < policy["noulTrue"]

    advice_p, advice, advice_uncertain = noul(PROHIBITED_KEY)
    causality_p, causality, causality_uncertain = noul(CAUSALITY_KEY)
    if advice_uncertain or causality_uncertain:
        decided = ["insufficient" if d == "supported" else d for d in decided]
    return {"decisions": decided, "picks": picks, "distributions": distributions, "advice": advice, "causality": causality,
            "advicePossible": advice_p, "causalityPossible": causality_p, "adviceUncertain": advice_uncertain,
            "causalityUncertain": causality_uncertain, "gate": gate_of(decided, advice, causality)}


# ------------------------------------------------------------------------------------------------ authored scenarios

def _choice_body(picked: str, p: float, confidence: float) -> dict[str, Any]:
    rest = round((1 - p) / 2, 6)
    probabilities = dict.fromkeys(DECISIONS, rest)
    probabilities[picked] = p
    return {"type": "choice", "choice": picked, "probabilities": probabilities, "confidence": confidence}


def scenario_response(entry: dict[str, Any], claim_count: int, model: str) -> tuple[int, Any]:
    """(HTTP status, JSON-able payload or raw bytes) a loopback fake native server returns for one authored script entry."""
    kind = entry["scenario"]
    if kind == "http_error":
        return entry["status"], {"error": "synthetic"}
    if kind == "non_json":
        return 200, b"<html>gateway</html>"
    answers: dict[str, Any] = {f"claim-{i}": _choice_body(c["choice"], c["p"], c["confidence"]) for i, c in enumerate(entry["claims"][:claim_count])}
    answers[PROHIBITED_KEY] = {"type": "noul", "noul": entry["prohibited"]}
    answers[CAUSALITY_KEY] = {"type": "noul", "noul": entry["causality"]}
    usage = entry["usage"]
    return 200, {"model": entry.get("model", model), "answers": answers,
                 "usage": {"input_tokens": usage["inputTokens"], "output_tokens": usage["outputTokens"]}}


# Authored deviations from the oracle: each is a plausible verifier mistake the scorer must show up. Keys are claim ids.
CLAIM_DEVIATIONS = {
    "VK-09-c2": ("supported", 0.93, 0.90),      # unsafe accept: an unsupported detail accepted as supported
    "VK-13-c2": ("insufficient", 0.80, 0.70),   # correct label, low probability
    "VK-03-c1": ("contradicted", 0.85, 0.90),   # weak contradiction: policy turns it into insufficient, so hold instead of reject
    "VK-26-c1": ("contradicted", 0.96, 0.92),   # over-reject: gold says insufficient
}
NOUL_DEVIATIONS = {("VK-05", "causality"): 0.55}  # uncertain Noul: the flag stays false and supported claims are held
SCENARIO_DEVIATIONS = {"VK-23": ("http_error", 500), "VK-17": ("model_mismatch", None), "VK-27": ("non_json", None)}


def _entry(case_id: str, claim_ids: list[str], decisions: list[str], advice: bool, causality: bool) -> dict[str, Any]:
    n = len(claim_ids)
    return {"caseId": case_id, "scenario": "answers",
            "claims": [{"choice": d, "p": 0.97, "confidence": 0.93} for d in decisions],
            "prohibited": 0.96 if advice else 0.02, "causality": 0.96 if causality else 0.03,
            "usage": {"inputTokens": 200 + 20 * n, "outputTokens": 12 + 4 * n}}


def _oracle_entries(corpus: VerifyCorpus) -> dict[str, dict[str, Any]]:
    return {case_id: _entry(case_id, ids, [corpus.gold[case_id]["claims"][c]["decision"] for c in ids],
                            corpus.gold[case_id]["advice"], corpus.gold[case_id]["causality"])
            for case_id in corpus.inputs.cases if (ids := corpus.inputs.claim_ids(case_id))}


def build_loopback_script(corpus: VerifyCorpus) -> dict[str, Any]:
    """Authored fake-native-server script: the oracle with explicit deviations and injected failures. A control, not a model."""
    entries = _oracle_entries(corpus)
    for case_id, entry in entries.items():
        for index, claim_id in enumerate(corpus.inputs.claim_ids(case_id)):
            if claim_id in CLAIM_DEVIATIONS:
                entry["claims"][index] = dict(zip(("choice", "p", "confidence"), CLAIM_DEVIATIONS[claim_id]))
        for (target, which), value in NOUL_DEVIATIONS.items():
            if target == case_id:
                entry["causality" if which == "causality" else "prohibited"] = value
        if case_id in SCENARIO_DEVIATIONS:
            scenario, status = SCENARIO_DEVIATIONS[case_id]
            entry["scenario"] = scenario
            if status is not None:
                entry["status"] = status
            if scenario == "model_mismatch":
                entry["model"] = LOOPBACK_MISMATCH_MODEL
    return {"schema": SCHEMA_VERIFY_LOOPBACK, "kind": "authored_control_not_a_model", "corpusId": corpus.inputs.corpus_id,
            "inputsSha256": corpus.inputs.inputs_sha256,
            "note": "Scripted answers for a local fake native server. Authored from the gold plus explicit deviations: a harness control, never a model.",
            "entries": [entries[c] for c in corpus.inputs.cases]}


def parse_loopback_script(raw: Any, inputs: VerifyInputs) -> dict[str, dict[str, Any]]:
    """Strictly validated script entries by case id. Reads only the visible inputs (counts, hash), never gold."""
    doc = mapping(raw, "script", ("schema", "kind", "corpusId", "inputsSha256", "note", "entries"))
    if doc["schema"] != SCHEMA_VERIFY_LOOPBACK or doc["kind"] != "authored_control_not_a_model":
        reject("schema_mismatch", f"script: expected schema {SCHEMA_VERIFY_LOOPBACK} authored_control_not_a_model")
    if doc["corpusId"] != inputs.corpus_id or doc["inputsSha256"] != inputs.inputs_sha256:
        reject("script_binding_mismatch", "the loopback script is bound to a different cases.json")
    entries: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(sequence(doc["entries"], "script.entries", 1)):
        where = f"script.entries[{index}]"
        entry = mapping(item, where, ("caseId", "scenario", "usage"), ("claims", "prohibited", "causality", "status", "model"))
        case_id = text(entry["caseId"], f"{where}.caseId")
        if case_id not in inputs.cases or case_id in entries:
            reject("script_coverage", f"{where}: unknown or duplicate caseId {case_id!r}")
        scenario = choice(entry["scenario"], SCENARIOS, f"{where}.scenario")
        usage = mapping(entry["usage"], f"{where}.usage", ("inputTokens", "outputTokens"))
        integer(usage["inputTokens"], f"{where}.usage.inputTokens")
        integer(usage["outputTokens"], f"{where}.usage.outputTokens")
        if scenario == "http_error":
            integer(entry.get("status"), f"{where}.status", 400)
        if scenario in ("answers", "model_mismatch"):
            claims = sequence(entry.get("claims"), f"{where}.claims", 1)
            if len(claims) != len(inputs.claim_ids(case_id)):
                reject("script_coverage", f"{where}: one answer per claim required")
            for ci, claim in enumerate(claims):
                claim = mapping(claim, f"{where}.claims[{ci}]", ("choice", "p", "confidence"))
                choice(claim["choice"], DECISIONS, f"{where}.claims[{ci}].choice")
                number(claim["p"], f"{where}.claims[{ci}].p")
                number(claim["confidence"], f"{where}.claims[{ci}].confidence")
            number(entry.get("prohibited"), f"{where}.prohibited")
            number(entry.get("causality"), f"{where}.causality")
        entries[case_id] = entry
    if set(entries) != set(inputs.cases):
        reject("script_coverage", f"script does not cover every case: missing {sorted(set(inputs.cases) - set(entries))}")
    return entries


# ------------------------------------------------------------------------------------------------------------ controls

def _system(*, endpoint: str, model: str, provider_revision: str, prompt: str, policy_version: str, identity: str, name: str,
            policy: dict[str, float] | None = None) -> dict[str, Any]:
    return {"name": name, "adapter": "typesafe-native", "endpointKind": endpoint, "model": model, "providerRevision": provider_revision,
            "promptVersion": prompt, "policyVersion": policy_version, "adapterIdentity": identity, "policy": dict(policy or REFERENCE_POLICY)}


CONTROL_MODEL = "jev-1.14.0"


def control_system() -> dict[str, Any]:
    return _system(endpoint="none", model=CONTROL_MODEL, provider_revision="authored-control", prompt="authored-control",
                   policy_version="authored-control", identity="authored-control", name="authored-control")


def _control_record(inputs: VerifyInputs, entry: dict[str, Any], system: dict[str, Any], *, attempt: str) -> dict[str, Any]:
    case_id = entry["caseId"]
    base = {"caseId": case_id, "caseSha256": case_sha256(inputs.cases[case_id]), "claimBinding": inputs.binding(case_id)}
    count = len(inputs.claim_ids(case_id))
    status, payload = scenario_response(entry, count, system["model"])
    if status != 200:
        return {**base, "status": "error", "error": {"code": f"provider_http_{status}", "outcome": "definite"}}
    raw = payload if isinstance(payload, dict) else {"responseText": payload.decode(), "httpStatus": 200}
    usage = entry["usage"]
    call = {"attemptId": attempt, "model": system["model"], "providerRevision": system["providerRevision"],
            "promptVersion": system["promptVersion"], "policyVersion": system["policyVersion"],
            "usage": {"inputTokens": usage["inputTokens"], "outputTokens": usage["outputTokens"]} if "usage" in raw else
                     {"inputTokens": None, "outputTokens": None},
            "cost": {"usd": None, "source": "unknown"}}
    latency = 5 + count
    try:
        derived = derive(raw, count, system["model"], system["policy"])
    except ValueError as exc:
        return {**base, "status": "error", "error": {"code": str(exc), "outcome": "definite"}, "raw": raw, "call": call, "latencyMs": latency}
    ids = inputs.claim_ids(case_id)
    return {**base, "status": "ok",
            "result": {"gate": derived["gate"], "claims": [{"claimId": c, "decision": d} for c, d in zip(ids, derived["decisions"])],
                       "prohibitedAdvice": derived["advice"], "unsupportedCausality": derived["causality"]},
            "raw": raw, "call": call, "latencyMs": latency}


def _unknown_record(inputs: VerifyInputs, case_id: str) -> dict[str, Any]:
    return {"caseId": case_id, "caseSha256": case_sha256(inputs.cases[case_id]), "claimBinding": inputs.binding(case_id), "status": "error",
            "error": {"code": "provider_response_unknown", "outcome": "unknown"}}


def build_control(corpus: VerifyCorpus, kind: str) -> dict[str, Any]:
    inputs = corpus.inputs
    system = control_system()
    entries = _oracle_entries(corpus)
    control_kind = kind
    note = "authored from the gold for scorer sanity; not a measurement of any system"
    if kind == "degraded_all_supported":
        entries = {c: _entry(c, inputs.claim_ids(c), ["supported"] * len(inputs.claim_ids(c)), False, False) for c in inputs.cases}
        note = "hand-degraded: every claim supported at p=0.97 and no finding, so every case is accepted"
    elif kind == "injected_errors":
        for case_id, (scenario, status) in {"VK-02": ("http_error", 500), "VK-08": ("non_json", None), "VK-11": ("model_mismatch", None)}.items():
            entries[case_id] = {**entries[case_id], "scenario": scenario, **({"status": status} if status else {}),
                                **({"model": LOOPBACK_MISMATCH_MODEL} if scenario == "model_mismatch" else {})}
        note = "oracle with injected errors: http 500, non-JSON body, model mismatch, and one unknown-outcome transport failure"
    elif kind == "loopback_script_expected":
        entries = parse_loopback_script(build_loopback_script(corpus), inputs)
        note = "what the loopback script must produce after the worker policy; a pipeline run is compared against this"
    elif kind != "oracle":
        reject("unknown_control", f"unknown control kind {kind!r}")
    records = [_control_record(inputs, entries[c], system, attempt="control-" + c) for c in inputs.cases]
    if kind == "injected_errors":
        records = [_unknown_record(inputs, r["caseId"]) if r["caseId"] == "VK-15" else r for r in records]
    return {"schema": SCHEMA_VERIFY_RUN, "runId": f"control-{kind}-dev", "label": f"authored control: {kind}",
            "provenance": {"kind": "authored_control", "executionMode": "authored", "recorder": "zoop_eval.verification.build_control",
                           "recordedAt": None, "controlKind": control_kind, "note": note},
            "corpus": {"corpusId": inputs.corpus_id, "corpusRevision": inputs.revision, "inputsSha256": inputs.inputs_sha256, "split": inputs.split},
            "system": system, "records": records}


def write_verify_controls(corpus: VerifyCorpus, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    documents = {name: build_control(corpus, kind) for name, kind in CONTROL_FILES.items()}
    documents[LOOPBACK_SCRIPT_FILE] = build_loopback_script(corpus)
    for name, document in documents.items():
        path = directory / name
        path.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(path)
    return written


# ------------------------------------------------------------------------------------------------------------ run parser

def _nullable_int(value: Any, where: str) -> int | None:
    return None if value is None else integer(value, where)


def _policy(raw: Any) -> dict[str, float]:
    block = mapping(raw, "run.system.policy", POLICY_KEYS)
    out = {key: number(block[key], f"run.system.policy.{key}") for key in POLICY_KEYS}
    if not (all(0 <= out[k] <= 1 for k in POLICY_KEYS) and out["noulFalse"] < out["noulTrue"]):
        reject("policy_invalid", "run.system.policy: thresholds must lie in [0,1] with noulFalse < noulTrue")
    return out


def _provenance(raw: Any) -> dict[str, Any]:
    prov = mapping(raw, "run.provenance", ("kind", "executionMode", "recorder", "recordedAt"), ("controlKind", "note"))
    kind = choice(prov["kind"], ("real_measured", "authored_control"), "run.provenance.kind")
    text(prov["recorder"], "run.provenance.recorder")
    if kind == "real_measured":
        # A replay never exercises the raw native receipt, so it is not verification evidence at all.
        if prov["executionMode"] != "live":
            reject("provenance_invalid", "real_measured verification runs must be executionMode=live with raw receipts; replay is not accepted")
        instant(prov["recordedAt"], "run.provenance.recordedAt")
        if "controlKind" in prov:
            reject("provenance_invalid", "controlKind is only valid for authored_control runs")
    else:
        if prov["executionMode"] != "authored":
            reject("provenance_invalid", "authored_control runs must be executionMode=authored")
        if prov["recordedAt"] is not None:
            reject("provenance_invalid", "an authored control has no recording time: recordedAt must be null")
        if "controlKind" not in prov:
            reject("provenance_invalid", "authored_control runs must state their controlKind")
        choice(prov["controlKind"], CONTROL_KINDS, "run.provenance.controlKind")
    return dict(prov)


def _system_block(raw: Any, prov: dict[str, Any]) -> dict[str, Any]:
    system = mapping(raw, "run.system", ("name", "adapter", "endpointKind", "model", "providerRevision", "promptVersion", "policyVersion",
                                         "adapterIdentity", "policy"), ("config",))
    for key in ("name", "model", "providerRevision", "promptVersion", "policyVersion", "adapterIdentity"):
        text(system[key], f"run.system.{key}")
    if system["adapter"] != "typesafe-native":
        reject("system_invalid", "run.system.adapter must be typesafe-native")
    endpoint = choice(system["endpointKind"], ENDPOINT_KINDS, "run.system.endpointKind")
    if _MOVING_ALIAS.search(system["model"]):
        reject("model_not_pinned", f"run.system.model {system['model']!r} is a moving alias; a versioned model is required")
    if prov["kind"] == "real_measured":
        expected = "provider"
    else:
        expected = "loopback_fake" if prov["controlKind"] == "loopback_fake_native_server" else "none"
    if endpoint != expected:
        reject("provenance_invalid", f"endpointKind {endpoint!r} is incompatible with this provenance (expected {expected!r})")
    return {**system, "policy": _policy(system["policy"]), "config": dict(free_mapping(system.get("config", {}), "run.system.config"))}


def _call(raw: Any, system: dict[str, Any], prov: dict[str, Any], body: Any, where: str) -> dict[str, Any]:
    call = mapping(raw, where, ("attemptId", "model", "providerRevision", "promptVersion", "policyVersion", "usage", "cost"))
    text(call["attemptId"], f"{where}.attemptId")
    for key in ("model", "providerRevision", "promptVersion", "policyVersion"):
        if call[key] != system[key]:
            reject("mixed_versions", f"{where}.{key} differs from run.system.{key}: one model/policy/prompt version per run")
    usage = mapping(call["usage"], f"{where}.usage", ("inputTokens", "outputTokens"))
    tokens = {k: _nullable_int(usage[k], f"{where}.usage.{k}") for k in ("inputTokens", "outputTokens")}
    reported = body.get("usage") if isinstance(body, dict) else None
    expected = (None, None)
    if isinstance(reported, dict):
        pair = (reported.get("input_tokens"), reported.get("output_tokens"))
        if all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in pair):
            expected = pair
    if (tokens["inputTokens"], tokens["outputTokens"]) != expected:
        reject("usage_mismatch", f"{where}.usage does not equal the usage in the raw receipt; unreported tokens must stay null")
    cost = mapping(call["cost"], f"{where}.cost", ("usd", "source"))
    source = choice(cost["source"], COST_SOURCES, f"{where}.cost.source")
    usd = number(cost["usd"], f"{where}.cost.usd", nullable=True)
    if (usd is None) != (source == "unknown"):
        reject("cost_unproven", f"{where}.cost: usd must be null exactly when the source is unknown (unknown cost is never 0)")
    if source == "loopback_no_charge" and (usd != 0 or prov.get("controlKind") != "loopback_fake_native_server"):
        reject("cost_unproven", f"{where}.cost: loopback_no_charge is only valid as 0 on a loopback_fake_native_server control")
    if source == "provider_reported" and prov["kind"] != "real_measured":
        reject("cost_unproven", f"{where}.cost: provider_reported cost requires a real_measured run")
    return {"attemptId": call["attemptId"], "tokens": tokens, "usd": usd, "costSource": source}


def parse_verify_run(raw: Any, corpus: VerifyCorpus) -> dict[str, Any]:
    inputs = corpus.inputs
    top = mapping(raw, "run", ("schema", "runId", "provenance", "corpus", "system", "records"), ("label",))
    if top["schema"] != SCHEMA_VERIFY_RUN:
        reject("schema_mismatch", f"run: expected schema {SCHEMA_VERIFY_RUN}")
    prov = _provenance(top["provenance"])
    system = _system_block(top["system"], prov)
    run_corpus = mapping(top["corpus"], "run.corpus", ("corpusId", "corpusRevision", "inputsSha256", "split"))
    if (run_corpus["corpusId"], run_corpus["corpusRevision"], run_corpus["inputsSha256"], run_corpus["split"]) != (
            inputs.corpus_id, inputs.revision, inputs.inputs_sha256, inputs.split):
        reject("corpus_mismatch", "run.corpus does not name this corpus id, revision, split and cases.json digest")
    records: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(sequence(top["records"], "run.records")):
        where = f"run.records[{index}]"
        rec = mapping(item, where, ("caseId", "caseSha256", "status", "claimBinding"), ("result", "raw", "call", "latencyMs", "error"))
        case_id = text(rec["caseId"], f"{where}.caseId")
        if case_id not in inputs.cases:
            reject("unknown_case", f"{where}: caseId {case_id!r} is not in the corpus")
        if case_id in records:
            reject("duplicate_record", f"{where}: duplicate record for {case_id!r}")
        if rec["caseSha256"] != case_sha256(inputs.cases[case_id]):
            reject("case_binding_mismatch", f"{case_id}: caseSha256 does not match the case in cases.json (the case was altered or is another revision)")
        binding = [mapping(b, f"{where}.claimBinding[]", ("claimId", "key")) for b in sequence(rec["claimBinding"], f"{where}.claimBinding", 1)]
        unique([b["claimId"] for b in binding if isinstance(b["claimId"], str)], f"{case_id} claimBinding", "duplicate_claim")
        if binding != inputs.binding(case_id):
            reject("claim_binding_mismatch", f"{case_id}: claimBinding must be the corpus claim ids in order with keys claim-0..claim-n")
        status = choice(rec["status"], ("ok", "error"), f"{where}.status")
        if status == "ok" and ("error" in rec or any(k not in rec for k in ("result", "raw", "call"))):
            reject("malformed", f"{where}: an ok record needs result, raw and call and no error")
        count = len(binding)
        body = rec.get("raw")
        call = _call(rec["call"], system, prov, body, f"{where}.call") if "call" in rec else None
        latency = number(rec.get("latencyMs"), f"{where}.latencyMs", nullable=True) if "latencyMs" in rec else None
        if latency is not None and call is None:
            reject("malformed", f"{where}: latencyMs without a call")
        out: dict[str, Any] = {"caseId": case_id, "status": status, "call": call, "latencyMs": latency, "claimIds": [b["claimId"] for b in binding]}
        if status == "ok":
            result = mapping(rec["result"], f"{where}.result", ("gate", "claims", "prohibitedAdvice", "unsupportedCausality"))
            claims = [mapping(c, f"{where}.result.claims[]", ("claimId", "decision")) for c in sequence(result["claims"], f"{where}.result.claims", 1)]
            unique([c["claimId"] for c in claims if isinstance(c["claimId"], str)], f"{case_id} result claims", "duplicate_claim")
            known = set(out["claimIds"])
            if any(c["claimId"] not in known for c in claims):
                reject("unknown_claim", f"{case_id}: result names a claim that is not in the case")
            if [c["claimId"] for c in claims] != out["claimIds"]:
                reject("claim_coverage_mismatch", f"{case_id}: result must cover exactly the case's claims, in order")
            decisions = [choice(c["decision"], DECISIONS, f"{where}.result.claims[].decision") for c in claims]
            gate = choice(result["gate"], GATES, f"{where}.result.gate")
            advice, causality = flag(result["prohibitedAdvice"], f"{where}.result.prohibitedAdvice"), flag(result["unsupportedCausality"], f"{where}.result.unsupportedCausality")
            try:
                derived = derive(rec["raw"], count, system["model"], system["policy"])
            except ValueError as exc:
                reject("raw_receipt_invalid", f"{case_id}: the raw receipt is not a valid native response ({exc}) yet the record claims ok")
            if (derived["decisions"], derived["advice"], derived["causality"], derived["gate"]) != (decisions, advice, causality, gate):
                reject("normalization_mismatch", f"{case_id}: the normalized result is not what the raw receipt yields under the declared policy")
            out.update(decisions=decisions, advice=advice, causality=causality, gate=gate, derived=derived)
        else:
            if "result" in rec or "error" not in rec:
                reject("malformed", f"{where}: an error record needs error and no result")
            error = mapping(rec["error"], f"{where}.error", ("code", "outcome"))
            code, outcome = text(error["code"], f"{where}.error.code"), choice(error["outcome"], ERROR_OUTCOMES, f"{where}.error.outcome")
            if (code == "provider_response_unknown") != (outcome == "unknown"):
                reject("error_invalid", f"{case_id}: outcome must be unknown exactly for provider_response_unknown")
            if code in NATIVE_INVALID:
                if body is None or call is None:
                    reject("error_invalid", f"{case_id}: {code} requires the raw receipt and its call")
                try:
                    derive(body, count, system["model"], system["policy"])
                except ValueError as exc:
                    if str(exc) != code:
                        reject("error_not_reproducible", f"{case_id}: the raw receipt fails with {exc}, not {code}")
                else:
                    reject("error_not_reproducible", f"{case_id}: the raw receipt is valid under the declared policy, so {code} cannot be true")
            elif body is not None:
                reject("error_invalid", f"{case_id}: a raw receipt belongs only to native validation failures")
            out.update(errorCode=code, errorOutcome=outcome)
        records[case_id] = out
    missing = [c for c in inputs.cases if c not in records]
    if missing:
        reject("missing_record", f"run has no record for case(s) {missing}; every case must be recorded (as ok or error)")
    return {"runId": text(top["runId"], "run.runId"), "label": top.get("label"), "provenance": prov, "system": system, "records": records}


# ------------------------------------------------------------------------------------------------------------- scoring

def _timing_semantics(prov: dict[str, Any]) -> str:
    if prov["kind"] == "real_measured":
        return "recorded_live_trace"
    return TIMING_SEMANTICS.get(prov["controlKind"], "authored_control_values_not_a_measurement")


def _trace(record: dict[str, Any]) -> dict[str, Any] | None:
    latency, call = record["latencyMs"], record["call"]
    if latency is None or call is None:
        return None
    span: dict[str, Any] = {"spanId": "verify", "kind": "llm", "name": "semantic-verification", "startMs": 0, "endMs": latency, "costUsd": call["usd"]}
    if call["tokens"]["inputTokens"] is not None and call["tokens"]["outputTokens"] is not None:
        span["tokens"] = {"input": call["tokens"]["inputTokens"], "output": call["tokens"]["outputTokens"]}
    return parse_trace({"startMs": 0, "endMs": latency, "spans": [span]}, f"trace[{record['caseId']}]")


def _calibration(corpus: VerifyCorpus, run: dict[str, Any]) -> dict[str, Any]:
    prov, system = run["provenance"], run["system"]
    if prov["kind"] != "real_measured" or system["endpointKind"] != "provider":
        return {"status": "not_evaluated", "reason": "calibration needs recorded live provider distributions; this run is an authored control or loopback, whose probabilities are authored"}
    items = [(rec["derived"]["distributions"][i], corpus.gold[cid]["claims"][rec["claimIds"][i]]["decision"])
             for cid, rec in run["records"].items() if rec["status"] == "ok" for i in range(len(rec["claimIds"]))]
    if not items:
        return {"status": "not_evaluated", "reason": "no ok record carries a valid distribution"}
    n = len(items)
    top = [(max(p.values()), max(p, key=p.get), gold) for p, gold in items]
    bins = []
    ece = 0.0
    for low, high in CALIBRATION_BINS:
        members = [(conf, pick == gold) for conf, pick, gold in top if low <= conf < high]
        if members:
            mean_conf = sum(c for c, _ in members) / len(members)
            accuracy = sum(1 for _, ok in members if ok) / len(members)
            ece += len(members) / n * abs(accuracy - mean_conf)
            bins.append({"range": [low, min(high, 1.0)], "n": len(members), "meanConfidence": round(mean_conf, 6), "accuracy": round(accuracy, 6)})
    brier = sum(sum((p[k] - (1.0 if k == gold else 0.0)) ** 2 for k in DECISIONS) for p, gold in items) / n
    log_loss = -sum(math.log(max(p[gold], LOG_LOSS_FLOOR)) for p, gold in items) / n
    return {"status": "evaluated", "n": n, "brier": round(brier, 6), "logLoss": round(log_loss, 6), "logLossFloor": LOG_LOSS_FLOOR,
            "expectedCalibrationError": round(ece, 6), "bins": bins, "labelSource": "gold.json (single author, unadjudicated, synthetic, dev)",
            "caveats": [f"n={n} claims: bins are coarse", "raw model probabilities of the chosen option, before the code-owned acceptance policy",
                        "single-author synthetic dev gold: this is a harness readout, not a calibration of any production threshold",
                        "top-1 choice vs gold label only; Noul probabilities are not calibrated here"]}


def score_verify_run(corpus: VerifyCorpus, run: dict[str, Any]) -> dict[str, Any]:
    inputs, records, prov = corpus.inputs, run["records"], run["provenance"]
    case_ids = list(inputs.cases)
    ok_ids = [c for c in case_ids if records[c]["status"] == "ok"]
    # --- claims (gold side: every claim is in every denominator; error cases are 'unscored', never a verdict)
    matrix = {g: {**dict.fromkeys(DECISIONS, 0), "unscored": 0} for g in DECISIONS}
    rows: list[tuple[str, str, str | None, list[str]]] = []
    for case_id in case_ids:
        rec = records[case_id]
        for index, claim_id in enumerate(rec["claimIds"]):
            gold = corpus.gold[case_id]["claims"][claim_id]
            pred = rec["decisions"][index] if rec["status"] == "ok" else None
            matrix[gold["decision"]][pred or "unscored"] += 1
            rows.append((case_id, claim_id, pred, gold["tags"] + [gold["decision"]]))
    total_claims = len(rows)

    def claim_stats(subset: list[tuple[str, str, str | None, list[str]]]) -> dict[str, Any]:
        golds = [(r[3][-1], r[2]) for r in subset]
        non_supported = [(g, p) for g, p in golds if g != "supported"]
        return {"claims": len(subset), "accuracy": ratio(sum(1 for g, p in golds if g == p), len(golds)),
                "unsafeSupported": ratio(sum(1 for g, p in non_supported if p == "supported"), len(non_supported))}

    per_class: dict[str, Any] = {}
    f1s = []
    for cls in DECISIONS:
        tp, predicted = matrix[cls][cls], sum(matrix[g][cls] for g in DECISIONS)
        precision, recall = ratio(tp, predicted), ratio(tp, sum(matrix[cls].values()))
        per_class[cls] = {"precision": precision, "recall": recall, "f1": f1(precision, recall)}
        if per_class[cls]["f1"] is not None:
            f1s.append(per_class[cls]["f1"])
    claims = {
        "confusion": matrix, "perClass": per_class,
        "macroF1": {"value": round(sum(f1s) / len(f1s), 6) if f1s else None, "classes": len(f1s), "of": len(DECISIONS)},
        **claim_stats(rows),
        "byTag": {tag: claim_stats([r for r in rows if tag in r[3][:-1]]) for tag in TAGS if any(tag in r[3][:-1] for r in rows)},
    }
    # --- case gate
    gate_matrix = {g: {**dict.fromkeys(GATES, 0), "error": 0} for g in GATES}
    for case_id in case_ids:
        gate_matrix[corpus.gold[case_id]["gate"]][records[case_id]["gate"] if records[case_id]["status"] == "ok" else "error"] += 1
    n_cases = len(case_ids)
    gold_not_safe = sum(sum(gate_matrix[g].values()) for g in ("hold", "reject"))
    accepted = sum(gate_matrix[g]["supported"] for g in GATES)
    errors_by_code: dict[str, int] = {}
    for case_id in case_ids:
        if records[case_id]["status"] == "error":
            code = records[case_id]["errorCode"]
            errors_by_code[code] = errors_by_code.get(code, 0) + 1
    error_cases = [c for c in case_ids if records[c]["status"] == "error"]
    gate = {
        "confusion": gate_matrix,
        "outcomes": {"supported": ratio(accepted, n_cases), "hold": ratio(sum(gate_matrix[g]["hold"] for g in GATES), n_cases),
                     "reject": ratio(sum(gate_matrix[g]["reject"] for g in GATES), n_cases),
                     "error": ratio(len(error_cases), n_cases)},
        "accuracy": ratio(sum(gate_matrix[g][g] for g in GATES), n_cases),
        "unsafeAccept": ratio(gate_matrix["hold"]["supported"] + gate_matrix["reject"]["supported"], gold_not_safe),
        "coverage": {"safeCasesAccepted": ratio(gate_matrix["supported"]["supported"], sum(gate_matrix["supported"].values())),
                     "acceptedPrecision": ratio(gate_matrix["supported"]["supported"], accepted)},
        "rejectRecall": ratio(gate_matrix["reject"]["reject"], sum(gate_matrix["reject"].values())),
        "rejectPrecision": ratio(gate_matrix["reject"]["reject"], sum(gate_matrix[g]["reject"] for g in GATES)),
        "holdRecall": ratio(gate_matrix["hold"]["hold"], sum(gate_matrix["hold"].values())),
        "holdPrecision": ratio(gate_matrix["hold"]["hold"], sum(gate_matrix[g]["hold"] for g in GATES)),
        "heldInsteadOfRejected": ratio(gate_matrix["reject"]["hold"], sum(gate_matrix["reject"].values())),
        "rejectedInsteadOfHeld": ratio(gate_matrix["hold"]["reject"], sum(gate_matrix["hold"].values())),
        "falseReject": ratio(gate_matrix["supported"]["reject"], sum(gate_matrix["supported"].values())),
        "falseHold": ratio(gate_matrix["supported"]["hold"], sum(gate_matrix["supported"].values())),
    }
    # --- flags
    flags: dict[str, Any] = {}
    for name, gold_key, pred_key, unc_key in (("prohibitedAdvice", "advice", "advice", "adviceUncertain"), ("unsupportedCausality", "causality", "causality", "causalityUncertain")):
        tp = sum(1 for c in ok_ids if corpus.gold[c][gold_key] and records[c][pred_key])
        fp = sum(1 for c in ok_ids if not corpus.gold[c][gold_key] and records[c][pred_key])
        positives = sum(1 for c in case_ids if corpus.gold[c][gold_key])
        flags[name] = {"precision": ratio(tp, tp + fp), "recall": ratio(tp, positives),
                       "falsePositive": ratio(fp, sum(1 for c in case_ids if not corpus.gold[c][gold_key])),
                       "uncertainMissedPositives": sum(1 for c in ok_ids if corpus.gold[c][gold_key] and records[c]["derived"][unc_key]),
                       "unscoredPositives": sum(1 for c in error_cases if corpus.gold[c][gold_key])}
    errors = {"cases": ratio(len(error_cases), n_cases), "byCode": dict(sorted(errors_by_code.items())),
              "outcomeUnknown": sum(1 for c in error_cases if records[c]["errorOutcome"] == "unknown"),
              "outcomeDefinite": sum(1 for c in error_cases if records[c]["errorOutcome"] == "definite"),
              "note": "an errored case is neither hold nor reject nor accept: it stays in every gold-side denominator with a zero numerator"}
    traces = [_trace(records[c]) for c in ok_ids]
    semantics = _timing_semantics(prov)
    timing = summarize(traces, semantics)
    score: dict[str, Any] = {
        "schema": SCHEMA_VERIFY_SCORE, "scorerVersion": SCORER_VERSION, "runId": run["runId"], "label": run["label"], "provenance": prov,
        "provenanceLabel": ("AUTHORED CONTROL (harness sanity input) - NOT a measurement of any model or verifier"
                            if prov["kind"] == "authored_control" else "recorded live provider measurement"),
        "corpus": {"corpusId": inputs.corpus_id, "corpusRevision": inputs.revision, "goldRevision": corpus.gold_revision,
                   "inputsSha256": inputs.inputs_sha256, "goldSha256": corpus.gold_sha256, "split": inputs.split,
                   "cases": n_cases, "claims": total_claims, "goldProvenance": corpus.gold_provenance},
        "system": run["system"],
        "coverage": {"total": n_cases, "ok": len(ok_ids), "error": len(error_cases), "missing": 0,
                     "note": "missing, duplicate or unbound records are rejected before scoring"},
        "claims": claims, "gate": gate, "flags": flags, "errors": errors,
        "calibration": _calibration(corpus, run), "timing": timing,
        "cost": {"usd": timing["costUsd"], "source": sorted({records[c]["call"]["costSource"] for c in case_ids if records[c]["call"]}) or None,
                 "note": "null/unknown is never 0; a total covers only calls that report cost (see known/unknown)"},
    }
    score["warnings"] = _warnings(corpus, run, score)
    score["notEvaluated"] = [
        "Korean finance verification quality of any real model: no recorded live provider run exists in this corpus",
        "any production threshold or auto-accept policy: the corpus is single-author synthetic dev data",
        "calibration of Noul probabilities and of thresholds (the choice distribution readout needs a recorded live run)",
        "free-text answer quality, retrieval and graph quality (other benchmarks)",
        "provider cost: Jev reports no cost and none is estimated",
    ]
    score["headline"] = headline(score)
    return score


def headline(score: dict[str, Any]) -> dict[str, dict[str, Any]]:
    claims, gate, flags = score["claims"], score["gate"], score["flags"]
    table: dict[str, dict[str, Any]] = {
        "claims.accuracy": claims["accuracy"], "claims.macroF1": claims["macroF1"], "claims.unsafeSupported": claims["unsafeSupported"],
        "gate.accuracy": gate["accuracy"], "gate.unsafeAccept": gate["unsafeAccept"],
        "gate.coverage.safeCasesAccepted": gate["coverage"]["safeCasesAccepted"],
        "gate.coverage.acceptedPrecision": gate["coverage"]["acceptedPrecision"],
        "gate.outcome.hold": gate["outcomes"]["hold"], "gate.outcome.reject": gate["outcomes"]["reject"],
        "gate.outcome.error": gate["outcomes"]["error"], "gate.rejectRecall": gate["rejectRecall"],
        "gate.heldInsteadOfRejected": gate["heldInsteadOfRejected"],
        "flags.prohibitedAdvice.recall": flags["prohibitedAdvice"]["recall"], "flags.unsupportedCausality.recall": flags["unsupportedCausality"]["recall"],
    }
    cal = score["calibration"]
    table["calibration.brier"] = {"value": cal.get("brier"), "n": cal.get("n")} if cal["status"] == "evaluated" else {"value": None, "status": "not_evaluated"}
    for stat in ("wall", "llm"):
        dist = score["timing"]["latencyMs"][stat]
        for q in ("p50", "p95"):
            table[f"timing.{stat}.{q}Ms"] = {"value": dist[q], "n": dist["n"]}
    table["cost.usd"] = {"value": score["cost"]["usd"]["total"], "known": score["cost"]["usd"]["known"], "unknown": score["cost"]["usd"]["unknown"]}
    return table


def _warnings(corpus: VerifyCorpus, run: dict[str, Any], score: dict[str, Any]) -> list[str]:
    out: list[str] = []
    prov = corpus.gold_provenance
    out.append(f"gold is synthetic={prov['synthetic']} adjudicated={prov['adjudicated']} annotators={prov['annotators']} devOnly={prov['devOnly']}: "
               "results support harness and pipeline checks, not accuracy claims about real Korean finance text")
    if run["provenance"]["kind"] == "authored_control":
        out.append("authored control: values come from fixtures or a local fake server written for the harness; never rank or report them as model results")
    if run["provenance"].get("controlKind") == "loopback_fake_native_server":
        out.append("loopback: the answers were authored by a script behind a local fake server; latency is local HTTP time, not model latency, and no paid call was made")
    out.append(f"{score['corpus']['cases']} cases / {score['corpus']['claims']} claims: rates on this few cases are coarse")
    if run["system"]["policy"] != REFERENCE_POLICY:
        out.append("declared policy differs from the harness reference policy; results are not comparable with runs under the reference")
    if score["coverage"]["error"]:
        out.append(f"{score['coverage']['error']} errored case(s) stay in every gold-side denominator; they are not holds, rejects or accepts")
    if score["cost"]["usd"]["unknown"]:
        out.append(f"cost is unknown for {score['cost']['usd']['unknown']} ok record(s); it is reported as unknown, never as 0")
    return out


def render_verify_score(score: dict[str, Any]) -> str:
    from .report import fmt

    c, g, f = score["claims"], score["gate"], score["flags"]
    lines = [f"== verification run {score['runId']}{' - ' + score['label'] if score['label'] else ''} ==", score["provenanceLabel"],
             f"corpus {score['corpus']['corpusId']}@{score['corpus']['corpusRevision']} split={score['corpus']['split']} cases={score['corpus']['cases']} claims={score['corpus']['claims']}",
             f"system {score['system']['name']} model={score['system']['model']} endpoint={score['system']['endpointKind']} policyVersion={score['system']['policyVersion']}",
             f"coverage: ok {score['coverage']['ok']} / error {score['coverage']['error']} of {score['coverage']['total']}", "",
             f"CLAIMS accuracy {fmt(c['accuracy'])}  macro-F1 {fmt(c['macroF1'])}  unsafe-supported {fmt(c['unsafeSupported'])}"]
    for cls, m in c["perClass"].items():
        lines.append(f"  {cls:13} P {fmt(m['precision'])}  R {fmt(m['recall'])}  F1 {m['f1'] if m['f1'] is not None else 'n/a'}")
    lines.append("  by tag: " + "  ".join(f"{t}={fmt(v['accuracy'])}" for t, v in c["byTag"].items()))
    lines += ["", f"GATE accuracy {fmt(g['accuracy'])}  UNSAFE-ACCEPT {fmt(g['unsafeAccept'])}  safe cases accepted {fmt(g['coverage']['safeCasesAccepted'])}  accepted precision {fmt(g['coverage']['acceptedPrecision'])}",
              f"  outcomes: accept {fmt(g['outcomes']['supported'])}  hold {fmt(g['outcomes']['hold'])}  reject {fmt(g['outcomes']['reject'])}  error {fmt(g['outcomes']['error'])}",
              f"  reject R {fmt(g['rejectRecall'])} P {fmt(g['rejectPrecision'])}  hold R {fmt(g['holdRecall'])} P {fmt(g['holdPrecision'])}  held-instead-of-rejected {fmt(g['heldInsteadOfRejected'])}",
              f"FLAGS advice R {fmt(f['prohibitedAdvice']['recall'])} P {fmt(f['prohibitedAdvice']['precision'])}  causality R {fmt(f['unsupportedCausality']['recall'])} P {fmt(f['unsupportedCausality']['precision'])}",
              f"ERRORS {fmt(score['errors']['cases'])} by code {score['errors']['byCode']} unknown-outcome {score['errors']['outcomeUnknown']}"]
    cal = score["calibration"]
    lines.append("CALIBRATION " + (f"brier {cal['brier']} logLoss {cal['logLoss']} ece {cal['expectedCalibrationError']} (n={cal['n']})" if cal["status"] == "evaluated" else f"not evaluated: {cal['reason']}"))
    t = score["timing"]
    lines.append(f"TIMING [{t['semantics']}] wall p50={t['latencyMs']['wall']['p50']} p95={t['latencyMs']['wall']['p95']} tokens in {t['tokens']['input']} out {t['tokens']['output']} costUsd {t['costUsd']}")
    lines += ["", "WARNINGS"] + [f"  - {w}" for w in score["warnings"]] + ["NOT EVALUATED"] + [f"  - {w}" for w in score["notEvaluated"]]
    return "\n".join(lines)
