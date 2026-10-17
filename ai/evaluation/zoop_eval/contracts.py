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


def parse_json(raw: bytes | str, where: str) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_constants)
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
