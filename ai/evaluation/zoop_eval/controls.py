"""Authored control runs: scorer sanity inputs derived from the gold, plus one hand-degraded variant.

They exist to prove the scorer rewards a perfect echo and catches specific mistakes. They are provenance
`authored_control`, carry authored (not measured) timing, and are never a benchmark result."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .bench import Bench
from .contracts import SCHEMA_RUN

CONTROL_FILES = {"oracle-dev.run.json": ("oracle", "dev"), "oracle-test.run.json": ("oracle", "test"),
                 "degraded-dev.run.json": ("degraded", "dev")}


def _graph_trace(index: int) -> dict[str, Any]:
    # two tool spans overlap on purpose: tool time is their union (100), not their sum (120)
    return {"startMs": 0, "endMs": 130 + 10 * index, "spans": [
        {"spanId": "s1", "kind": "tool", "name": "link", "startMs": 0, "endMs": 60, "costUsd": 0},
        {"spanId": "s2", "kind": "tool", "name": "merge", "startMs": 40, "endMs": 100, "costUsd": 0}]}


def _qa_trace(hop: int | None) -> dict[str, Any]:
    steps = hop or 1
    spans = [{"spanId": f"s{i}", "kind": "tool", "name": "graph_lookup", "startMs": 10 + 30 * i, "endMs": 40 + 30 * i, "costUsd": 0} for i in range(steps)]
    return {"startMs": 0, "endMs": 20 + 30 * steps + 10, "spans": spans}


def _step(edge: dict[str, Any]) -> dict[str, str]:
    return {key: edge[key] for key in ("subject", "predicate", "object")}


def _fact(edge: dict[str, Any]) -> dict[str, Any]:
    return {key: edge[key] for key in ("subject", "predicate", "object", "validFrom", "validTo", "status")}


def build_control(bench: Bench, kind: str, split: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for index, tid in enumerate(bench.cases("graph", split)):
        gold = bench.gold_graph[tid]
        decisions = [{"pairId": p, "decision": "HOLD" if d == "UNDECIDABLE" else d} for p, d in gold["merges"].items()]
        output = {
            "entityLinks": [{"mentionId": m, "entityId": e} for m, e in gold["entityLinks"].items()],
            "events": [{"eventMentionId": m, "eventType": v["eventType"], "eventDate": v["eventDate"]} for m, v in gold["events"].items()],
            "mergeDecisions": decisions,
            "edges": [{**_fact(e), "citations": list(e["evidence"])} for e in gold["edges"]],
        }
        records.append({"task": "graph", "caseId": tid, "status": "ok", "output": output, "trace": _graph_trace(index)})
    for qid in bench.cases("qa", split):
        gold = bench.gold_questions[qid]
        output = {
            "outcome": gold["outcome"], "answerEntities": list(gold["answerEntities"]), "facts": copy.deepcopy(gold["facts"]),
            "retrieved": list(gold["supportPassages"]), "citations": list(gold["supportPassages"]),
        }
        if gold["paths"]:
            output["path"] = [_step(bench.edges[e]) for e in gold["paths"][0]]
        if gold["abstainReason"]:
            output["abstainReason"] = gold["abstainReason"]
        records.append({"task": "qa", "caseId": qid, "status": "ok", "output": output, "trace": _qa_trace(gold["hop"])})
    run = {
        "schema": SCHEMA_RUN, "runId": f"control-{kind}-{split}", "label": f"authored {kind} control, {split} split",
        "provenance": {"kind": "authored_control", "executionMode": "authored", "recorder": "zoop_eval.controls", "recordedAt": None,
                       "controlKind": "oracle_gold_echo" if kind == "oracle" else "hand_degraded_mistakes",
                       "note": "Derived from the gold by code. A scorer sanity input; not a system and not a measurement."},
        "corpus": {"corpusId": bench.corpus_id, "corpusRevision": bench.corpus_revision, "goldRevision": bench.gold_revision,
                   "inputsSha256": bench.inputs_sha256, "split": split, "tasks": ["graph", "qa"]},
        "system": {"systemId": f"control-{kind}", "family": "no_model_deterministic", "model": None, "config": {"control": kind},
                   "promptRevision": None, "toolRevision": "authored-control-1", "schemaRevision": SCHEMA_RUN, "graphRevision": None,
                   "capabilities": {"retrieval": True, "path": True, "citations": True}},
        "records": records,
    }
    if kind == "degraded":
        if split != "dev":
            raise ValueError("the degraded control is authored against dev ids only")
        _degrade(bench, run)
    return run


def _degrade(bench: Bench, run: dict[str, Any]) -> None:
    by = {(r["task"], r["caseId"]): r for r in run["records"]}
    a = bench.edges

    def out(task: str, case: str) -> dict[str, Any]:
        return by[(task, case)]["output"]

    def drop(task: str, case: str) -> None:
        run["records"].remove(by.pop((task, case)))

    edges = out("graph", "GT-A1")["edges"]
    edges[0] = {**_fact(a["a1"]), "subject": a["a1"]["object"], "object": a["a1"]["subject"], "citations": ["D01-P1"]}  # wrong direction
    edges[2] = {"subject": "E-DQL", "predicate": "SUPPLIES", "object": "E-CRV", "validFrom": None, "validTo": None, "status": "asserted", "citations": ["D03-P2"]}
    links = {l["mentionId"]: l for l in out("graph", "GT-A1")["entityLinks"]}
    links["m-a07"]["entityId"] = None
    links["m-a08"]["entityId"] = "E-DQL"
    out("graph", "GT-A2")["edges"][1]["validTo"] = "2026-12-31"  # invented bound for an unknown end
    by[("graph", "GT-A3")].update(status="refused", detail="provider refused the request")
    del by[("graph", "GT-A3")]["output"]
    drop("graph", "GT-A4")
    merges = {m["pairId"]: m for m in out("graph", "GT-A5")["mergeDecisions"]}
    merges["pair-a03"]["decision"] = "SAME"  # same company, same day, different event
    merges["pair-a04"]["decision"] = "DIFFERENT"  # missed merge
    next(e for e in out("graph", "GT-A5")["events"] if e["eventMentionId"] == "em-a05")["eventDate"] = "2026-09-04"

    qa2 = out("qa", "QA-2")
    backwards = {"subject": "E-BRL", "predicate": "SUPPLIES", "object": "E-ARC"}  # the real edge is ARC -> BRL
    qa2.update(facts=[{**backwards, "validFrom": None, "validTo": None, "status": "asserted"}], path=[backwards])
    out("qa", "QA-3").clear()
    out("qa", "QA-3").update(outcome="abstained", abstainReason="no_evidence", retrieved=["D01-P1", "D02-P1"], citations=[])
    qa4 = out("qa", "QA-4")
    qa4.update(retrieved=["D01-P1", "D03-P1"], citations=["D01-P1", "D03-P1"], path=[_step(a["a1"]), _step(a["a3"])])
    qa5 = out("qa", "QA-5")
    qa5.update(answerEntities=["E-BRL"], facts=[_fact(a["a5"])], path=[_step(a["a5"])], retrieved=["D05-P1", "D04-P1"], citations=["D05-P1"])
    drop("qa", "QA-6")
    out("qa", "QA-7").update(outcome="answered", answerEntities=["E-ESK"], facts=[{**_fact(a["a5"]), "validTo": "2027-01-01"}], citations=["D05-P1"], retrieved=["D05-P1"])
    del out("qa", "QA-7")["abstainReason"]
    out("qa", "QA-8").update(outcome="answered", answerEntities=["E-BRL"], citations=["D06-P1"], retrieved=["D06-P1", "D03-P1"])
    by[("qa", "QA-9")].update(status="error", detail="tool timeout")
    del by[("qa", "QA-9")]["output"]


def write_controls(bench: Bench, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, (kind, split) in CONTROL_FILES.items():
        path = directory / name
        path.write_text(json.dumps(build_control(bench, kind, split), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(path)
    return written
