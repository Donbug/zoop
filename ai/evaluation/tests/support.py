"""Shared helpers. Runs are derived from the authored oracle control and then mutated one mistake at a time."""
from __future__ import annotations

import copy
import functools
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

from zoop_eval.bench import DEFAULT_CORPUS, Bench, load_bench
from zoop_eval.contracts import Rejected
from zoop_eval.controls import build_control
from zoop_eval.run import parse_run
from zoop_eval.scoring import score_run


@functools.lru_cache(maxsize=1)
def bench() -> Bench:
    return load_bench()


def oracle(split: str = "dev") -> dict[str, Any]:
    return build_control(bench(), "oracle", split)


def record(run: dict[str, Any], task: str, case: str) -> dict[str, Any]:
    return next(r for r in run["records"] if r["task"] == task and r["caseId"] == case)


def score(run: dict[str, Any]) -> dict[str, Any]:
    return score_run(bench(), parse_run(copy.deepcopy(run), bench()))


def as_measured(run: dict[str, Any], run_id: str, **system: Any) -> dict[str, Any]:
    """TEST DOUBLE ONLY: relabel an oracle run as a recorded replay so compare/provenance rules can be exercised.
    It is not a measurement and never leaves the test process."""
    out = copy.deepcopy(run)
    out["runId"] = run_id
    out["provenance"] = {"kind": "real_measured", "executionMode": "replay", "recorder": "unit-test", "recordedAt": "2026-10-14T00:00:00+00:00"}
    out["system"].update(system)
    return out


def val(document: dict[str, Any], *path: str) -> Any:
    for key in path:
        document = document[key]
    return document["value"] if isinstance(document, dict) and "value" in document else document


class Case(unittest.TestCase):
    def rejected(self, run_or_callable: Any, code: str) -> Rejected:
        with self.assertRaises(Rejected) as ctx:
            run_or_callable() if callable(run_or_callable) else score(run_or_callable)
        self.assertEqual(ctx.exception.code, code, ctx.exception.message)
        return ctx.exception


def temp_corpus(mutate: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], None]) -> Path:
    """Copy the corpus to a temp dir after applying mutate(corpus, tasks, gold). Caller removes it with shutil.rmtree."""
    target = Path(tempfile.mkdtemp(prefix="zoop-eval-corpus-"))
    docs = {name: json.loads((DEFAULT_CORPUS / name).read_text("utf-8")) for name in ("corpus.json", "tasks.json", "gold.json")}
    mutate(docs["corpus.json"], docs["tasks.json"], docs["gold.json"])
    for name, doc in docs.items():
        (target / name).write_text(json.dumps(doc), "utf-8")
    return target


def cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
