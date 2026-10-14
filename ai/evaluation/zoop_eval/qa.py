"""Retrieval / answer-support scoring for questions with authored gold.

Everything here is decided by exact comparison against structured gold (entities, facts, passage ids, edge
paths, outcome). Free-text answer quality is NOT decided here: it is reported as requiring human or model
evaluation. A capability the system did not declare (retrieval, path, citations) yields a `not_declared` block,
not a zero."""
from __future__ import annotations

from collections import Counter
from typing import Any

from .bench import Bench, triple_key, walk_steps
from .contracts import OUTCOMES
from .stats import ratio

SUPPORT_K = 5
NOT_DECLARED = {"status": "capability_not_declared"}


def _fact_key(bench: Bench, fact: dict[str, Any]) -> tuple:
    return (triple_key(bench.predicates, fact["subject"], fact["predicate"], fact["object"]),
            fact["validFrom"], fact["validTo"], fact["status"])


def score_qa(bench: Bench, qids: list[str], records: dict[tuple[str, str], dict[str, Any]],
             capabilities: dict[str, bool]) -> dict[str, Any]:
    c: Counter = Counter()
    matrix: dict[str, Counter] = {g: Counter() for g in OUTCOMES}
    for qid in qids:
        gold, question = bench.gold_questions[qid], bench.questions[qid]
        record = records.get(("qa", qid))
        out = record["output"] if record and record["status"] == "ok" else None
        c[f"status_{record['status'] if record else 'missing'}"] += 1
        g_out = gold["outcome"]
        gold_entities, gold_support = set(gold["answerEntities"]), set(gold["supportPassages"])
        gold_facts = {_fact_key(bench, f) for f in gold["facts"]}
        c["total"] += 1
        c[f"gold_{g_out}"] += 1
        c["goldEntities"] += len(gold_entities)
        c["goldFacts"] += len(gold_facts)
        c["goldFactCases"] += bool(gold_facts)
        c["goldSupport"] += len(gold_support)
        c["goldSupportCases"] += bool(gold_support)
        c["goldPathCases"] += bool(gold["paths"])
        c["goldHops"] += len(gold["paths"][0]) if gold["paths"] else 0
        if out is None:
            matrix[g_out]["noOutput"] += 1
            continue
        p_out = out["outcome"]
        matrix[g_out][p_out] += 1
        c[f"pred_{p_out}"] += 1
        c["answerTextRecords"] += out["answerText"] is not None
        pred_entities = set(out["answerEntities"])
        pred_facts = {_fact_key(bench, f) for f in out["facts"]}
        entity_exact = g_out == "answered" and p_out == "answered" and pred_entities == gold_entities
        fact_exact = bool(gold_facts) and p_out == "answered" and pred_facts == gold_facts
        c["outcomeCorrect"] += p_out == g_out
        c["entityExact"] += entity_exact
        c["factExact"] += fact_exact
        c["endToEndCorrect"] += p_out == g_out and (g_out != "answered" or (entity_exact and pred_facts == gold_facts))
        c["predEntities"] += len(pred_entities)
        c["entityTp"] += len(pred_entities & gold_entities)
        c["predFacts"] += len(pred_facts)
        c["factTp"] += len(pred_facts & gold_facts)
        gold_triples = {k[0] for k in gold_facts}
        for fact in out["facts"]:
            triple = triple_key(bench.predicates, fact["subject"], fact["predicate"], fact["object"])
            backwards = triple_key(bench.predicates, fact["object"], fact["predicate"], fact["subject"])
            if bench.predicates.get(fact["predicate"], True) and triple not in gold_triples and backwards in gold_triples:
                c["factsReversed"] += 1
        # abstention / conflict
        c["predAbstained"] += p_out == "abstained"
        c["abstainTp"] += p_out == "abstained" and g_out == "abstained"
        c["abstainReasonMatch"] += p_out == g_out == "abstained" and out["abstainReason"] == gold["abstainReason"]
        c["overAbstained"] += g_out != "abstained" and p_out == "abstained"
        c["unsupportedAnswer"] += g_out == "abstained" and p_out != "abstained"
        c["predConflict"] += p_out == "conflict"
        c["conflictTp"] += p_out == g_out == "conflict"
        # retrieval
        retrieved = out["retrieved"]
        if retrieved is not None:
            c["retrievalRecords"] += 1
            c["retrieved"] += len(retrieved)
            c["retrievedTp"] += len(set(retrieved) & gold_support)
            c["retrievedTpAtK"] += len(set(retrieved[:SUPPORT_K]) & gold_support)
            c["retrievedUnknown"] += sum(1 for p in retrieved if p not in bench.passages)
            c["fullSupport"] += bool(gold_support) and gold_support <= set(retrieved)
        cited = out["citations"]
        if cited is not None:
            c["citationRecords"] += 1
            c["cited"] += len(cited)
            c["citedTp"] += len(set(cited) & gold_support)
            c["citedUnknown"] += sum(1 for p in cited if p not in bench.passages)
            if p_out != "abstained":
                c["answeredLike"] += 1
                c["uncitedAnswered"] += not cited
        # path
        path = out["path"]
        if path is not None:
            c["pathProduced"] += 1
            valid, resolved, end, reason = walk_steps(bench, question["anchorEntity"], path)
            c["pathValid"] += valid
            if reason:
                c[f"pathInvalid_{reason}"] += 1
            if gold["paths"]:
                c["pathCovered"] += max(len(set(resolved) & set(p)) for p in gold["paths"])
                c["pathExact"] += valid and resolved in gold["paths"]
                c["pathReachesAnswer"] += valid and end in gold_entities

    def declared(capability: str, block: dict[str, Any]) -> dict[str, Any]:
        return block if capabilities[capability] else dict(NOT_DECLARED)

    path_reasons = {k[len("pathInvalid_"):]: v for k, v in c.items() if k.startswith("pathInvalid_")}
    n = c["total"]
    answerable = c["gold_answered"] + c["gold_conflict"]
    return {
        "coverage": {"total": n, "ok": c["status_ok"], "refused": c["status_refused"], "error": c["status_error"], "missing": c["status_missing"]},
        "outcome": {
            "correct": ratio(c["outcomeCorrect"], n),
            "endToEndCorrect": ratio(c["endToEndCorrect"], n),
            "confusion": {g: {p: matrix[g][p] for p in (*OUTCOMES, "noOutput")} for g in OUTCOMES},
        },
        "answer": {
            "entitySetExact": ratio(c["entityExact"], c["gold_answered"]),
            "entityPrecision": ratio(c["entityTp"], c["predEntities"]),
            "entityRecall": ratio(c["entityTp"], c["goldEntities"]),
            "factSetExact": ratio(c["factExact"], c["goldFactCases"]),
            "factPrecision": ratio(c["factTp"], c["predFacts"]),
            "factRecall": ratio(c["factTp"], c["goldFacts"]),
            "factsReversedDirection": c["factsReversed"],
        },
        "abstention": {
            "precision": ratio(c["abstainTp"], c["predAbstained"]),
            "recall": ratio(c["abstainTp"], c["gold_abstained"]),
            "reasonMatchOfCorrect": ratio(c["abstainReasonMatch"], c["abstainTp"]),
            "overAbstention": ratio(c["overAbstained"], answerable),
            "unsupportedAnswer": ratio(c["unsupportedAnswer"], c["gold_abstained"]),
            "conflictPrecision": ratio(c["conflictTp"], c["predConflict"]),
            "conflictRecall": ratio(c["conflictTp"], c["gold_conflict"]),
        },
        "retrieval": declared("retrieval", {
            "k": SUPPORT_K, "records": c["retrievalRecords"],
            "supportPrecision": ratio(c["retrievedTp"], c["retrieved"]),
            "supportRecall": ratio(c["retrievedTp"], c["goldSupport"]),
            f"supportRecallAt{SUPPORT_K}": ratio(c["retrievedTpAtK"], c["goldSupport"]),
            "fullSupportCases": ratio(c["fullSupport"], c["goldSupportCases"]),
            "unknownPassageRefs": c["retrievedUnknown"],
        }),
        "path": declared("path", {
            "produced": ratio(c["pathProduced"], n),
            "validity": ratio(c["pathValid"], c["pathProduced"]),
            "exactMatch": ratio(c["pathExact"], c["goldPathCases"]),
            "hopCoverage": ratio(c["pathCovered"], c["goldHops"]),
            "reachesAnswer": ratio(c["pathReachesAnswer"], c["goldPathCases"]),
            "invalidReasons": path_reasons,
        }),
        "citations": declared("citations", {
            "records": c["citationRecords"],
            "precision": ratio(c["citedTp"], c["cited"]),
            "recall": ratio(c["citedTp"], c["goldSupport"]),
            "uncitedAnswers": ratio(c["uncitedAnswered"], c["answeredLike"]),
            "unknownPassageRefs": c["citedUnknown"],
            "scope": "membership in the gold support set of the question; whether a cited passage semantically supports a claim needs human/model evaluation",
        }),
        "freeText": {"answerTextRecords": c["answerTextRecords"], "automaticMetric": None,
                     "status": "human_or_model_evaluation_required"},
    }
