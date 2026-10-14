"""Graph-construction scoring: entity linking, event attributes, merge decisions, graph edges.

Gold-side denominators always cover every in-scope task (a missing, refused or failed record contributes
misses, never silently shrinks the denominator). Prediction-side denominators count only what ok records
actually emitted; an empty denominator is null."""
from __future__ import annotations

from collections import Counter
from typing import Any

from .bench import Bench, triple_key
from .stats import f1, ratio

_MISSING = object()


def _coverage(task_ids: list[str], records: dict[tuple[str, str], dict[str, Any]], task: str) -> dict[str, Any]:
    counts = Counter()
    for tid in task_ids:
        record = records.get((task, tid))
        counts[record["status"] if record else "missing"] += 1
    return {"total": len(task_ids), "ok": counts["ok"], "refused": counts["refused"], "error": counts["error"], "missing": counts["missing"]}


def score_graph(bench: Bench, task_ids: list[str], records: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    link, event, merge, edge = Counter(), Counter(), {"event": Counter(), "entity": Counter()}, Counter()
    for tid in task_ids:
        task, gold = bench.graph_tasks[tid], bench.gold_graph[tid]
        record = records.get(("graph", tid))
        out = record["output"] if record and record["status"] == "ok" else None
        out = out or {"entityLinks": None, "events": None, "mergeDecisions": None, "edges": None}

        links = out["entityLinks"]
        if links is not None:
            known = set(gold["entityLinks"])
            for mention_id, entity_id in links.items():
                if mention_id not in known:  # a prediction about something that was never asked
                    link["unmatchedRefs"] += 1
                    if entity_id is not None:
                        link["predictedLinks"] += 1
        for mention_id, expected in gold["entityLinks"].items():
            link["gold"] += 1
            link["goldLinked"] += expected is not None
            link["goldNil"] += expected is None
            predicted = _MISSING if links is None else links.get(mention_id, _MISSING)
            if predicted is _MISSING:
                link["notAnswered"] += 1
                continue
            link["predictedLinks"] += predicted is not None
            if predicted == expected:
                link["correct"] += 1
                link["correctLinked"] += expected is not None
            elif expected is None:
                link["falseLinkOnUnknown"] += 1
            elif predicted is None:
                link["missedLink"] += 1
            else:
                link["misLink"] += 1  # linked to a different entity: homonym conflation

        events = out["events"]
        for mention_id, expected in gold["events"].items():
            event["gold"] += 1
            event["goldDateUnknown"] += expected["eventDate"] is None
            predicted = None if events is None else events.get(mention_id)
            if predicted is None:
                event["notAnswered"] += 1
                continue
            event["typeCorrect"] += predicted["eventType"] == expected["eventType"]
            event["dateCorrect"] += predicted["eventDate"] == expected["eventDate"]
            event["dateInvented"] += expected["eventDate"] is None and predicted["eventDate"] is not None
            event["dateWrong"] += expected["eventDate"] is not None and predicted["eventDate"] not in (None, expected["eventDate"])
            event["dateDropped"] += expected["eventDate"] is not None and predicted["eventDate"] is None

        decisions = out["mergeDecisions"]
        kind_of = {p["pairId"]: p["kind"] for p in task["mergeCandidates"]}
        for pair_id, expected in gold["merges"].items():
            c = merge[kind_of[pair_id]]
            c["gold"] += 1
            c[f"gold_{expected}"] += 1
            predicted = None if decisions is None else decisions.get(pair_id)
            if predicted is None:
                c["notAnswered"] += 1
                continue
            c[f"predicted_{predicted}"] += 1
            c["correct"] += (expected == predicted) or (expected == "UNDECIDABLE" and predicted == "HOLD")
            if predicted == "SAME":
                c["sameCorrect"] += expected == "SAME"
                c["falseMerge"] += expected == "DIFFERENT"
                c["unsafeMerge"] += expected == "UNDECIDABLE"
            c["missedMerge"] += expected == "SAME" and predicted != "SAME"
            c["holdCorrect"] += expected == "UNDECIDABLE" and predicted == "HOLD"
            c["overHold"] += expected != "UNDECIDABLE" and predicted == "HOLD"

        predicted_edges = out["edges"]
        gold_index = {triple_key(bench.predicates, e["subject"], e["predicate"], e["object"]): e for e in gold["edges"]}
        edge["gold"] += len(gold["edges"])
        for gold_edge in gold["edges"]:
            edge["goldUnknownBounds"] += (gold_edge["validFrom"] is None) + (gold_edge["validTo"] is None)
        for pred in predicted_edges or []:
            edge["predicted"] += 1
            edge["invalidCitationRefs"] += sum(1 for c in pred["citations"] if c not in bench.passages)
            key = triple_key(bench.predicates, pred["subject"], pred["predicate"], pred["object"])
            hit = gold_index.get(key)
            if hit is None:
                reverse = (pred["object"], pred["predicate"], pred["subject"])
                if bench.predicates.get(pred["predicate"], True) and triple_key(bench.predicates, *reverse) in gold_index:
                    edge["reversedDirection"] += 1
                else:
                    edge["notInGold"] += 1
                continue
            edge["tripleCorrect"] += 1
            exact = True
            for bound in ("validFrom", "validTo"):
                expected, got = hit[bound], pred[bound]
                if expected is None:
                    edge["unknownBounds"] += 1
                    if got is not None:
                        edge["temporalInvented"] += 1
                        exact = False
                else:
                    edge["knownBounds"] += 1
                    if got == expected:
                        edge["knownBoundsCorrect"] += 1
                    else:
                        edge["temporalDropped" if got is None else "temporalWrong"] += 1
                        exact = False
            edge["statusCorrect"] += pred["status"] == hit["status"]
            exact = exact and pred["status"] == hit["status"]
            edge["exactCorrect"] += exact
            cited = pred["citations"]
            edge["citedMatched"] += bool(cited) and all(c in bench.passages for c in cited) and bool(set(cited) & set(hit["evidence"]))
            edge["uncitedMatched"] += not cited

    pred_n, gold_n = edge["predicted"], edge["gold"]
    edge_exact_p, edge_exact_r = ratio(edge["exactCorrect"], pred_n), ratio(edge["exactCorrect"], gold_n)
    return {
        "coverage": _coverage(task_ids, records, "graph"),
        "entityLinking": {
            "accuracy": ratio(link["correct"], link["gold"]),
            "linkPrecision": ratio(link["correctLinked"], link["predictedLinks"]),
            "linkRecall": ratio(link["correctLinked"], link["goldLinked"]),
            "falseLinkOnUnknown": ratio(link["falseLinkOnUnknown"], link["goldNil"]),
            "misLinkedToOtherEntity": ratio(link["misLink"], link["goldLinked"]),
            "missedLink": ratio(link["missedLink"], link["goldLinked"]),
            "notAnswered": link["notAnswered"], "unmatchedRefs": link["unmatchedRefs"],
        },
        "events": {
            "typeAccuracy": ratio(event["typeCorrect"], event["gold"]),
            "dateAccuracy": ratio(event["dateCorrect"], event["gold"]),
            "dateInvented": ratio(event["dateInvented"], event["goldDateUnknown"]),
            "dateWrong": event["dateWrong"], "dateDropped": event["dateDropped"], "notAnswered": event["notAnswered"],
        },
        "merges": {kind: _merge_block(c) for kind, c in merge.items()},
        "edges": {
            "triplePrecision": ratio(edge["tripleCorrect"], pred_n),
            "tripleRecall": ratio(edge["tripleCorrect"], gold_n),
            "exactPrecision": edge_exact_p, "exactRecall": edge_exact_r, "exactF1": f1(edge_exact_p, edge_exact_r),
            "reversedDirection": ratio(edge["reversedDirection"], pred_n),
            "notInGold": ratio(edge["notInGold"], pred_n),
            "temporalInvented": ratio(edge["temporalInvented"], edge["unknownBounds"]),
            "temporalBoundAccuracy": ratio(edge["knownBoundsCorrect"], edge["knownBounds"]),
            "temporalWrong": edge["temporalWrong"], "temporalDropped": edge["temporalDropped"],
            "statusAccuracy": ratio(edge["statusCorrect"], edge["tripleCorrect"]),
            "citationSupportedOfMatched": ratio(edge["citedMatched"], edge["tripleCorrect"]),
            "uncitedMatched": edge["uncitedMatched"], "invalidCitationRefs": edge["invalidCitationRefs"],
            "goldEdges": gold_n, "predictedEdges": pred_n,
        },
    }


def _merge_block(c: Counter) -> dict[str, Any]:
    predicted_same = c["predicted_SAME"]
    return {
        "accuracy": ratio(c["correct"], c["gold"]),
        "sameBinding": {"precision": ratio(c["sameCorrect"], predicted_same), "recall": ratio(c["sameCorrect"], c["gold_SAME"])},
        "falseMerge": ratio(c["falseMerge"], c["gold_DIFFERENT"]),
        "unsafeMergeOnUndecidable": ratio(c["unsafeMerge"], c["gold_UNDECIDABLE"]),
        "missedMerge": ratio(c["missedMerge"], c["gold_SAME"]),
        "holdOnUndecidable": ratio(c["holdCorrect"], c["gold_UNDECIDABLE"]),
        "overHold": ratio(c["overHold"], c["gold"] - c["gold_UNDECIDABLE"]),
        "goldPairs": c["gold"], "notAnswered": c["notAnswered"],
    }
