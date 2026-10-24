"""Gold-isolated, stdlib BM25 paired-context retrieval and separate diagnostics."""
from __future__ import annotations

import math
import os
import re
import stat
from collections import Counter
from pathlib import Path
from time import perf_counter_ns

from .contracts import (
    MATERIAL_RETRIEVAL_RECORD_FIELDS, MATERIAL_RETRIEVAL_RUN_FIELDS,
    SCHEMA_MATERIAL_RETRIEVAL_RUN, SCHEMA_MATERIAL_RETRIEVAL_SCORE,
    Rejected, choice, id_list, integer, mapping, number, parse_json, reject, sequence,
)
from .materials import DEFAULT_MATERIALS, canonical, convert_materials, digest

# Shared producer/reader wire budget, including the CLI's trailing LF.
MAX_RUN_BYTES = 8 * 1024 * 1024

ALGORITHM = {
    "id": "stdlib-bm25-paired-paragraph-1", "k1": 1.2, "b": 0.75,
    "tokenization": "str.lower then ASCII [a-z0-9]+; no stemming or stopwords",
    "queryTerms": "unique tokens in lexicographic order; no query-frequency weighting",
    "idf": "ln(1 + (N - df + 0.5) / (df + 0.5))",
    "candidateScope": "question-supplied-context-paragraphs-only",
    "tieBreak": "score descending, paragraph UID ascending (Unicode code points)",
    "zeroScores": "retained up to topK; empty candidate pool stays empty",
}
MEASUREMENT = {
    "kind": "measured-local", "clock": "perf_counter_ns", "repeats": 1,
    "scope": "per-query tokenization, local index construction, scoring and sorting",
    "excludes": "material loading, input validation, digesting and serialization",
    "cache": "no ranking or index reuse; no warmup",
}
LIMITS = [
    "Retrieval-only B1 preparation, not full B1 generation or a complete RAG benchmark.",
    "Paired-context paragraph selection, not global-document or table-cell retrieval.",
    "Custom paragraph-support diagnostics, not official TAT-QA answer EM/F1.",
    "Source-order development sample already inspected; not representative or held-out.",
    "Upstream annotations are not Zoop human-adjudicated gold or Korean finance quality evidence.",
    "No answer, QA, graph, path, model-quality or legal/model-send approval claim.",
]


def _require(condition: bool, code: str = "materials_retrieval_invalid") -> None:
    if not condition:
        reject(code, "material retrieval contract rejected")


def rank_paragraphs(question: str, paragraphs: list[dict], top_k: int) -> list[dict]:
    """Rank only supplied paragraph text; statistics are local to this context."""
    if not paragraphs:
        return []
    tokens = [Counter(re.findall(r"[a-z0-9]+", p["text"].lower())) for p in paragraphs]
    lengths = [sum(counts.values()) for counts in tokens]
    average = sum(lengths) / len(tokens)
    df = Counter(term for counts in tokens for term in counts)
    terms = sorted(set(re.findall(r"[a-z0-9]+", question.lower())))
    ranking = []
    for paragraph, counts, length in zip(paragraphs, tokens, lengths):
        score = 0.0
        for term in terms:
            frequency = counts[term]
            if frequency:
                idf = math.log1p((len(tokens) - df[term] + 0.5) / (df[term] + 0.5))
                score += idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * length / average))
        ranking.append({"paragraphId": paragraph["uid"], "score": score})
    return sorted(ranking, key=lambda item: (-item["score"], item["paragraphId"]))[:top_k]


def _header(inputs: dict, top_k: int) -> dict:
    integer(top_k, "topK", 1)
    return {
        "schema": SCHEMA_MATERIAL_RETRIEVAL_RUN, "ok": True,
        "materialsId": inputs["materialsId"], "dataset": "tatqa", "status": inputs["status"],
        "finalized": True, "inputsSha256": digest(inputs), "provenance": inputs["provenance"],
        "normalization": inputs["normalization"], "limits": LIMITS,
        "algorithm": ALGORITHM, "config": {"topK": top_k}, "measurement": MEASUREMENT,
        "queryIds": [case["uid"] for case in inputs["cases"]],
        "candidatePools": [{"contextId": c["tableUid"], "paragraphIds": sorted(p["uid"] for p in c["paragraphs"])}
                           for c in inputs["contexts"]],
    }


def retrieve_materials(materials: Path = DEFAULT_MATERIALS, top_k: int = 5) -> dict:
    integer(top_k, "topK", 1)
    inputs = convert_materials("materials-inputs", materials, "tatqa")
    contexts = {c["tableUid"]: c["paragraphs"] for c in inputs["contexts"]}
    records = []
    for case in inputs["cases"]:
        started = perf_counter_ns()
        ranking = rank_paragraphs(case["question"], contexts[case["contextId"]], top_k)
        elapsed = perf_counter_ns() - started
        records.append({"queryId": case["uid"], "contextId": case["contextId"], "status": "ok",
                        "ranking": ranking, "elapsedNs": elapsed, "error": None})
    # Only return a finalized artifact after all queries finish; never open gold.
    run = {**_header(inputs, top_k), "records": records}
    _require(len((canonical(run) + "\n").encode("utf-8")) <= MAX_RUN_BYTES,
             "materials_retrieval_run_size")
    return run


def _read_run(path: Path) -> dict:
    _require(not any(part.startswith(".env") for part in path.parts), "materials_path")
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        found = os.fstat(fd)
        _require(stat.S_ISREG(found.st_mode), "materials_file_type")
        _require(found.st_size <= MAX_RUN_BYTES, "materials_retrieval_run_size")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            raw = handle.read(MAX_RUN_BYTES + 1)
        _require(len(raw) <= MAX_RUN_BYTES, "materials_retrieval_run_size")
        return parse_json(raw.decode("utf-8"), "retrieval run")
    except OSError:
        reject("materials_unreadable", "retrieval run is not safely readable")
    except (ValueError, TypeError, OverflowError, RecursionError):
        reject("materials_retrieval_invalid", "retrieval run encoding or structure rejected")
    finally:
        if fd is not None:
            os.close(fd)


def _validate_run(run: dict, inputs: dict) -> dict[str, dict]:
    mapping(run, "retrieval run", MATERIAL_RETRIEVAL_RUN_FIELDS)
    config = mapping(run["config"], "config", ("topK",))
    top_k = integer(config["topK"], "topK", 1)
    expected = _header(inputs, top_k)
    # Canonical equality also distinguishes bool from integer and rejects extra
    # nested fields, reordered identities, changed provenance and other families.
    for key, value in expected.items():
        _require(canonical(run[key]) == canonical(value), "materials_retrieval_binding")
    cases = {case["uid"]: case for case in inputs["cases"]}
    contexts = {c["tableUid"]: c["paragraphs"] for c in inputs["contexts"]}
    records = {}
    for record in sequence(run["records"], "records"):
        mapping(record, "record", MATERIAL_RETRIEVAL_RECORD_FIELDS)
        uid = record["queryId"]
        _require(isinstance(uid, str) and uid in cases, "materials_retrieval_identity")
        _require(uid not in records, "materials_retrieval_duplicate")
        case = cases[uid]
        _require(record["contextId"] == case["contextId"], "materials_retrieval_identity")
        status = choice(record["status"], ("ok", "error"), "record.status")
        integer(record["elapsedNs"], "elapsedNs")
        ranking = sequence(record["ranking"], "ranking")
        for item in ranking:
            mapping(item, "ranking item", ("paragraphId", "score"))
            number(item["score"], "score")
        ids = id_list([item["paragraphId"] for item in ranking], "ranked paragraph ids")
        pool = contexts[case["contextId"]]
        _require(set(ids) <= {p["uid"] for p in pool}, "materials_retrieval_identity")
        if status == "error":
            _require(record["error"] == "retrieval-error" and not ranking)
        else:
            _require(record["error"] is None)
            expected_ranking = rank_paragraphs(case["question"], pool, top_k)
            _require(ids == [item["paragraphId"] for item in expected_ranking], "materials_retrieval_ranking")
            # Allow only last-bit libm/JSON roundoff, never a different ranking.
            _require(all(math.isclose(a["score"], b["score"], rel_tol=1e-12, abs_tol=0.0)
                         for a, b in zip(ranking, expected_ranking)), "materials_retrieval_ranking")
        records[uid] = record
    return records


def score_material_retrieval(run_path: Path, materials: Path = DEFAULT_MATERIALS) -> dict:
    """All-or-nothing scoring; malformed records never produce partial scores."""
    try:
        return _score_material_retrieval(run_path, materials)
    except Rejected as exc:
        raise Rejected(exc.code, "material retrieval scoring rejected; no artifact emitted") from None
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise Rejected("materials_retrieval_invalid", "retrieval run structure or encoding rejected") from None


def _score_material_retrieval(run_path: Path, materials: Path) -> dict:
    run = _read_run(run_path)
    inputs = convert_materials("materials-inputs", materials, "tatqa")
    records = _validate_run(run, inputs)
    # Gold is inaccessible until the finalized run and all its bindings validate.
    gold = convert_materials("materials-gold", materials, "tatqa")
    _require(gold["inputsSha256"] == run["inputsSha256"], "materials_retrieval_binding")
    rows = []
    for case in gold["cases"]:
        record = records.get(case["uid"])
        outcome = record["status"] if record else "missing"
        support = case["paragraphIds"]
        reason = ("table-only" if case["answer_from"] == "table" else
                  "no-paragraph-support-annotation" if not support else None)
        ids = [item["paragraphId"] for item in record["ranking"]] if record else []
        hits = len(set(ids) & set(support or []))
        first = next((i for i, uid in enumerate(ids, 1) if uid in (support or [])), None)
        rows.append({"queryId": case["uid"], "contextId": case["contextId"], "outcome": outcome,
                     "scorable": reason is None, "notScorableReason": reason,
                     "supportCount": len(support) if support is not None else None,
                     "supportHits": hits if reason is None else None,
                     "recallAtK": hits / len(support) if reason is None else None,
                     "reciprocalRankAtK": (1 / first if first else 0.0) if reason is None else None,
                     "exactSupportCoverageAtK": int(hits == len(support)) if reason is None else None})
    scorable = [row for row in rows if row["scorable"]]
    metrics = {}
    for name, field in (("paragraphSupportRecallAtK", "recallAtK"),
                        ("mrrAtK", "reciprocalRankAtK"),
                        ("exactSupportCoverageAtK", "exactSupportCoverageAtK")):
        numerator = sum(row[field] for row in scorable)
        metrics[name] = {"numerator": numerator, "denominator": len(scorable),
                         "value": numerator / len(scorable) if scorable else None}
    return {
        "schema": SCHEMA_MATERIAL_RETRIEVAL_SCORE, "ok": True, "materialsId": inputs["materialsId"],
        "dataset": "tatqa", "status": inputs["status"], "inputsSha256": run["inputsSha256"],
        "runSha256": digest(run), "goldSha256": digest(gold), "provenance": gold["provenance"],
        "annotationStatus": gold["annotationStatus"], "limits": LIMITS,
        "algorithm": run["algorithm"], "config": run["config"],
        "counts": {"questions": len(rows), "recorded": len(records),
                   "ok": sum(row["outcome"] == "ok" for row in rows),
                   "error": sum(row["outcome"] == "error" for row in rows),
                   "missing": sum(row["outcome"] == "missing" for row in rows),
                   "scorable": len(scorable), "notScorable": len(rows) - len(scorable),
                   "tableOnly": sum(row["notScorableReason"] == "table-only" for row in rows),
                   "noParagraphGold": sum(row["notScorableReason"] == "no-paragraph-support-annotation" for row in rows)},
        "metrics": metrics, "queries": rows,
    }
