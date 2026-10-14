"""Score one validated run against the gold: graph + QA slices, timing, warnings, headline table."""
from __future__ import annotations

from typing import Any

from . import SCORER_VERSION
from .bench import Bench
from .contracts import SCHEMA_SCORE
from .graph import score_graph
from .qa import score_qa
from .timing import summarize

TIMING_SEMANTICS = {
    ("authored_control", "authored"): "authored_control_values_not_a_measurement",
    ("real_measured", "replay"): "replay_harness_time_not_model_latency",
    ("real_measured", "live"): "recorded_live_trace",
}

# name -> path into the score document. Used by the text report and by `compare`.
HEADLINE: dict[str, tuple[str, ...]] = {
    "graph.entityLinking.accuracy": ("graph", "entityLinking", "accuracy"),
    "graph.entityLinking.falseLinkOnUnknown": ("graph", "entityLinking", "falseLinkOnUnknown"),
    "graph.entityLinking.misLinkedToOtherEntity": ("graph", "entityLinking", "misLinkedToOtherEntity"),
    "graph.events.dateInvented": ("graph", "events", "dateInvented"),
    "graph.merges.event.accuracy": ("graph", "merges", "event", "accuracy"),
    "graph.merges.event.falseMerge": ("graph", "merges", "event", "falseMerge"),
    "graph.merges.event.unsafeMergeOnUndecidable": ("graph", "merges", "event", "unsafeMergeOnUndecidable"),
    "graph.edges.exactPrecision": ("graph", "edges", "exactPrecision"),
    "graph.edges.exactRecall": ("graph", "edges", "exactRecall"),
    "graph.edges.reversedDirection": ("graph", "edges", "reversedDirection"),
    "graph.edges.temporalInvented": ("graph", "edges", "temporalInvented"),
    "qa.outcome.correct": ("qa", "all", "outcome", "correct"),
    "qa.outcome.endToEndCorrect": ("qa", "all", "outcome", "endToEndCorrect"),
    "qa.abstention.recall": ("qa", "all", "abstention", "recall"),
    "qa.abstention.overAbstention": ("qa", "all", "abstention", "overAbstention"),
    "qa.abstention.unsupportedAnswer": ("qa", "all", "abstention", "unsupportedAnswer"),
    "qa.retrieval.supportPrecision": ("qa", "all", "retrieval", "supportPrecision"),
    "qa.retrieval.supportRecall": ("qa", "all", "retrieval", "supportRecall"),
    "qa.path.validity": ("qa", "all", "path", "validity"),
    "qa.path.exactMatch": ("qa", "all", "path", "exactMatch"),
    "qa.path.hopCoverage": ("qa", "all", "path", "hopCoverage"),
    "qa.citations.precision": ("qa", "all", "citations", "precision"),
    "qa.citations.recall": ("qa", "all", "citations", "recall"),
    "qa.hop1.endToEndCorrect": ("qa", "byHop", "1", "outcome", "endToEndCorrect"),
    "qa.hop2.endToEndCorrect": ("qa", "byHop", "2", "outcome", "endToEndCorrect"),
    "qa.hop3.endToEndCorrect": ("qa", "byHop", "3", "outcome", "endToEndCorrect"),
    "qa.hop1.path.hopCoverage": ("qa", "byHop", "1", "path", "hopCoverage"),
    "qa.hop2.path.hopCoverage": ("qa", "byHop", "2", "path", "hopCoverage"),
    "qa.hop3.path.hopCoverage": ("qa", "byHop", "3", "path", "hopCoverage"),
}


def _dig(document: Any, path: tuple[str, ...]) -> Any:
    """Value at `path`. A capability block ({"status": ...}) standing in the way is returned instead of null."""
    for key in path:
        if not isinstance(document, dict):
            return None
        if key not in document:
            return document if "status" in document else None
        document = document[key]
    return document


def headline(score: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flat metric table: every entry has `value` (null when undefined or not evaluated) plus its counts or reason."""
    table: dict[str, dict[str, Any]] = {}
    for name, path in HEADLINE.items():
        found = _dig(score, path)
        if isinstance(found, dict) and "value" in found:
            table[name] = found
        elif isinstance(found, dict) and "status" in found:
            table[name] = {"value": None, "status": found["status"]}
        else:
            table[name] = {"value": None, "status": "not_evaluated"}
    for task, key in (("graph", "timing.graph"), ("qa", "timing.qa")):
        block = _dig(score, ("timing", task)) if task == "graph" else _dig(score, ("timing", "qa", "all"))
        for stat in ("wall", "llm", "tool"):
            dist = _dig(block, ("latencyMs", stat))
            for q in ("p50", "p95"):
                table[f"{key}.{stat}.{q}Ms"] = ({"value": dist[q], "n": dist["n"]} if dist else {"value": None, "status": "not_evaluated"})
    return table


def score_run(bench: Bench, run: dict[str, Any]) -> dict[str, Any]:
    split, tasks, records = run["corpus"]["split"], run["corpus"]["tasks"], run["records"]
    prov, system = run["provenance"], run["system"]
    semantics = TIMING_SEMANTICS[(prov["kind"], prov["executionMode"])]
    score: dict[str, Any] = {
        "schema": SCHEMA_SCORE, "scorerVersion": SCORER_VERSION, "runId": run["runId"], "label": run["label"],
        "provenance": prov,
        "provenanceLabel": ("AUTHORED CONTROL (scorer sanity input) - NOT a measurement of any system"
                            if prov["kind"] == "authored_control" else f"recorded measurement ({prov['executionMode']})"),
        "corpus": {"corpusId": bench.corpus_id, "corpusRevision": bench.corpus_revision, "goldRevision": bench.gold_revision,
                   "inputsSha256": bench.inputs_sha256, "goldSha256": bench.gold_sha256, "split": split, "tasks": tasks,
                   "goldProvenance": bench.gold_provenance},
        "system": system, "timingContext": run["timingContext"],
        "cases": {task: len(bench.cases(task, split)) for task in tasks},
    }
    traces: dict[str, list[dict[str, Any] | None]] = {}
    qa_ids = bench.cases("qa", split)
    if "graph" in tasks:
        ids = bench.cases("graph", split)
        score["graph"] = score_graph(bench, ids, records)
        traces["graph"] = [records[("graph", i)]["trace"] for i in ids if ("graph", i) in records and records[("graph", i)]["status"] == "ok"]
    timing: dict[str, Any] = {}
    if "qa" in tasks:
        hops = sorted({g["hop"] for q, g in bench.gold_questions.items() if q in qa_ids and g["hop"] is not None})
        kinds = sorted({g["kind"] for q, g in bench.gold_questions.items() if q in qa_ids})
        caps = system["capabilities"]
        score["qa"] = {
            "all": score_qa(bench, qa_ids, records, caps),
            "byHop": {str(h): score_qa(bench, [q for q in qa_ids if bench.gold_questions[q]["hop"] == h], records, caps) for h in hops},
            "byKind": {k: score_qa(bench, [q for q in qa_ids if bench.gold_questions[q]["kind"] == k], records, caps) for k in kinds},
        }

        def ok_traces(ids: list[str]) -> list[dict[str, Any] | None]:
            return [records[("qa", i)]["trace"] for i in ids if ("qa", i) in records and records[("qa", i)]["status"] == "ok"]

        timing["qa"] = {"all": summarize(ok_traces(qa_ids), semantics),
                        "byHop": {str(h): summarize(ok_traces([q for q in qa_ids if bench.gold_questions[q]["hop"] == h]), semantics) for h in hops}}
    if "graph" in tasks:
        timing["graph"] = summarize(traces["graph"], semantics)
    score["timing"] = timing
    score["warnings"] = _warnings(bench, run, score, semantics)
    score["notEvaluated"] = [
        "free-text answer quality (answerText): human or model evaluation required; no automatic metric is defined",
        "semantic support of a citation beyond membership in the gold support set: human or model evaluation required",
        "per-fact citation attribution (citations are scored at question level)",
        "any retrieval/graph backend quality in this repository: no retriever, chat or graph-database executable exists to measure",
    ]
    score["headline"] = headline(score)
    return score


def _warnings(bench: Bench, run: dict[str, Any], score: dict[str, Any], semantics: str) -> list[str]:
    out: list[str] = []
    prov = bench.gold_provenance
    if prov["synthetic"] or not prov["adjudicated"]:
        out.append(f"gold is synthetic={prov['synthetic']} adjudicated={prov['adjudicated']} annotators={prov['annotators']}: "
                   "results support scorer/pipeline controls, not accuracy claims about real data")
    if run["provenance"]["kind"] == "authored_control":
        out.append("authored control: values come from fixtures written for the scorer; never rank or report them beside measured results")
    if run["provenance"]["executionMode"] == "replay":
        out.append("replay execution: timing is harness time over recorded fixtures, not model or service latency")
    for task, count in score["cases"].items():
        out.append(f"{task}: {count} cases in the {run['corpus']['split']} split; rates on this few cases are coarse")
        cov = score["graph"]["coverage"] if task == "graph" else score["qa"]["all"]["coverage"]
        bad = {k: cov[k] for k in ("refused", "error", "missing") if cov[k]}
        if bad:
            out.append(f"{task}: non-ok cases {bad}; they stay in every gold-side denominator and are not scored as empty answers")
    for task, block in score["timing"].items():
        pop = (block["all"] if task == "qa" else block)["population"]
        if pop["withoutTrace"]:
            out.append(f"{task}: {pop['withoutTrace']} ok record(s) carry no trace; excluded from timing samples (not counted as 0 ms)")
    if run["provenance"]["kind"] == "real_measured" and run["timingContext"] is None and score["timing"]:
        out.append("no timingContext (concurrency/warmup): latency is not comparable across runs")
    return out
