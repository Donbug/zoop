"""Wire constants and strict input validation shared by the corpus, run and trace loaders."""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

SCHEMA_CORPUS = "zoop-bench-corpus-1"
SCHEMA_TASKS = "zoop-bench-tasks-1"
SCHEMA_GOLD = "zoop-bench-gold-1"
SCHEMA_RUN = "zoop-bench-run-1"
SCHEMA_SCORE = "zoop-bench-score-1"
SCHEMA_COMPARE = "zoop-bench-compare-1"
SCHEMA_VERIFY_CASES = "zoop-verify-cases-1"
SCHEMA_VERIFY_GOLD = "zoop-verify-gold-1"
SCHEMA_VERIFY_RUN = "zoop-verify-run-1"
SCHEMA_VERIFY_SCORE = "zoop-verify-score-1"
SCHEMA_VERIFY_LOOPBACK = "zoop-verify-loopback-script-1"
SCHEMA_SUMMARY_VERIFY_CASES = "zoop-summary-verify-cases-1"
SCHEMA_SUMMARY_VERIFY_GOLD = "zoop-summary-verify-gold-1"
SCHEMA_SUMMARY_VERIFY_RUN = "zoop-summary-verify-run-1"
SCHEMA_SUMMARY_VERIFY_SCORE = "zoop-summary-verify-score-1"
SCHEMA_SUMMARY_VERIFY_LOOPBACK = "zoop-summary-verify-loopback-script-1"

# External development materials are conversion artifacts, never scorer run families.
SCHEMA_MATERIAL_INPUTS = "zoop-eval-material-inputs-1"
SCHEMA_MATERIAL_GOLD = "zoop-eval-material-gold-1"
SCHEMA_MATERIAL_VALIDATION = "zoop-eval-material-validation-1"
MATERIAL_ARTIFACT_FIELDS = {
    SCHEMA_MATERIAL_INPUTS: ("schema", "ok", "materialsId", "dataset", "status", "validationScope",
                            "provenance", "limits", "normalization", "contexts", "cases", "choices"),
    SCHEMA_MATERIAL_GOLD: ("schema", "ok", "materialsId", "dataset", "status", "validationScope",
                          "provenance", "limits", "inputsSha256", "annotationStatus", "cases"),
    SCHEMA_MATERIAL_VALIDATION: ("schema", "ok", "materialsId", "status", "validationScope",
                                "provenance", "limits", "counts", "inputsSha256"),
}
MATERIAL_OBJECT_FIELDS = {
    "provenance": ("manifestSha256", "collectedAt", "purpose", "collectionExecution",
                   "collectionLimitations", "sources", "verifiedFiles"),
    "normalization": ("split", "selection", "method", "modifications"),
    "context": ("tableUid", "table", "paragraphs"),
    "paragraph": ("uid", "order", "text"),
    "entity": ("text", "type", "span"),
    "span": ("start", "end", "unit", "endExclusive"),
}
MATERIAL_CASE_FIELDS = {
    (SCHEMA_MATERIAL_INPUTS, "klue-re"): ("guid", "sentence", "source", "subjectEntity", "objectEntity"),
    (SCHEMA_MATERIAL_INPUTS, "tatqa"): ("uid", "order", "question", "contextId"),
    (SCHEMA_MATERIAL_GOLD, "klue-re"): ("guid", "labelId", "label"),
    (SCHEMA_MATERIAL_GOLD, "tatqa"): ("uid", "contextId", "answer", "answer_type", "answer_from",
                                    "scale", "derivation", "req_comparison", "rel_paragraphs", "paragraphIds"),
}

# Retrieval diagnostics have their own closed family; never graph/QA answer runs.
SCHEMA_MATERIAL_RETRIEVAL_RUN = "zoop-eval-material-retrieval-run-1"
SCHEMA_MATERIAL_RETRIEVAL_SCORE = "zoop-eval-material-retrieval-score-1"
MATERIAL_RETRIEVAL_RUN_FIELDS = (
    "schema", "ok", "materialsId", "dataset", "status", "finalized", "inputsSha256",
    "provenance", "normalization", "limits", "algorithm", "config", "measurement",
    "queryIds", "candidatePools", "records",
)
MATERIAL_RETRIEVAL_RECORD_FIELDS = ("queryId", "contextId", "status", "ranking", "elapsedNs", "error")

# Public KLUE RE ClassLabel order, not learned from the selected gold rows.
# https://github.com/KLUE-benchmark/KLUE/wiki/KLUE-RE-dataset-description
# https://huggingface.co/datasets/klue/klue (configuration re, label feature)
KLUE_RE_LABELS = (
    "no_relation", "org:dissolved", "org:founded", "org:place_of_headquarters",
    "org:alternate_names", "org:member_of", "org:members", "org:political/religious_affiliation",
    "org:product", "org:founded_by", "org:top_members/employees", "org:number_of_employees/members",
    "per:date_of_birth", "per:date_of_death", "per:place_of_birth", "per:place_of_death",
    "per:place_of_residence", "per:origin", "per:employee_of", "per:schools_attended",
    "per:alternate_names", "per:parents", "per:children", "per:siblings", "per:spouse",
    "per:other_family", "per:colleagues", "per:product", "per:religion", "per:title",
)

SPLITS = ("dev", "test")
TASK_KINDS = ("graph", "qa")
STATUSES = ("ok", "refused", "error")
OUTCOMES = ("answered", "abstained", "conflict")
EDGE_STATUSES = ("asserted", "disputed")
MERGE_GOLD = ("SAME", "DIFFERENT", "UNDECIDABLE")
MERGE_PRED = ("SAME", "DIFFERENT", "HOLD")
MERGE_KINDS = ("event", "entity")
QUESTION_KINDS = ("direct", "directed", "temporal", "conflict", "unknown")
FAMILIES = ("no_model_deterministic", "vector_rag", "fixed_graph_traversal", "agent_graphrag", "other")
PROVENANCE_KINDS = {"real_measured": ("live", "replay"), "authored_control": ("authored",)}
SPAN_KINDS = ("llm", "tool")

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Rejected(Exception):
    """Input that must not be scored (malformed, inconsistent or incompatible)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_json(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def reject(code: str, message: str):
    raise Rejected(code, message)


def _no_duplicate_keys(pairs):
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            reject("json_duplicate_key", f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def _no_constants(name: str):
    reject("json_non_finite", f"non-finite JSON constant {name}")


def parse_json(raw: bytes | str, where: str, *, parse_float=float) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_constants,
                          parse_float=parse_float)
    except json.JSONDecodeError as exc:
        reject("json_invalid", f"{where}: {exc}")


def read_json(path: Path) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        reject("file_unreadable", f"{path}: {exc.strerror or exc}")
    return parse_json(raw, str(path))


def mapping(value: Any, where: str, required: tuple[str, ...] = (), optional: tuple[str, ...] = ()) -> dict[str, Any]:
    if not isinstance(value, dict):
        reject("malformed", f"{where}: expected an object")
    missing = [key for key in required if key not in value]
    if missing:
        reject("malformed", f"{where}: missing key(s) {missing}")
    extra = sorted(set(value) - set(required) - set(optional))
    if extra:
        reject("malformed", f"{where}: unknown key(s) {extra}")
    return value


def free_mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        reject("malformed", f"{where}: expected an object")
    return value


def sequence(value: Any, where: str, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list):
        reject("malformed", f"{where}: expected an array")
    if len(value) < minimum:
        reject("malformed", f"{where}: needs at least {minimum} item(s)")
    return value


def text(value: Any, where: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        reject("malformed", f"{where}: expected a non-empty string{' or null' if nullable else ''}")
    return value


def flag(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        reject("malformed", f"{where}: expected a boolean")
    return value


def integer(value: Any, where: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        reject("malformed", f"{where}: expected an integer >= {minimum}")
    return value


def number(value: Any, where: str, nullable: bool = False) -> float | int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        reject("malformed", f"{where}: expected a finite number >= 0{' or null' if nullable else ''}")
    return value


def day(value: Any, where: str, nullable: bool = True) -> str | None:
    """ISO calendar date; JSON null means 'not stated / unknown' and is never replaced by a default."""
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not _DAY.match(value):
        reject("malformed", f"{where}: expected YYYY-MM-DD{' or null' if nullable else ''}")
    try:
        date.fromisoformat(value)
    except ValueError:
        reject("malformed", f"{where}: not a calendar date")
    return value


def instant(value: Any, where: str) -> str:
    if not isinstance(value, str):
        reject("malformed", f"{where}: expected an ISO-8601 timestamp")
    try:
        datetime.fromisoformat(value)
    except ValueError:
        reject("malformed", f"{where}: expected an ISO-8601 timestamp")
    return value


def choice(value: Any, values: tuple[str, ...], where: str) -> str:
    if not isinstance(value, str) or value not in values:
        reject("malformed", f"{where}: expected one of {list(values)}")
    return value


def unique(values: list[str], where: str, code: str = "malformed") -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            reject(code, f"{where}: duplicate id {value!r}")
        seen.add(value)


def id_list(value: Any, where: str, minimum: int = 0) -> list[str]:
    items = [text(item, f"{where}[]") for item in sequence(value, where, minimum)]
    unique(items, where)
    return items
