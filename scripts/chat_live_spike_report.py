#!/usr/bin/env python3
"""Validate and summarize the approved small live chatbot latency spike.

The input is deliberately content-free: it accepts run identity, policy/model revisions,
latency, usage and cost only. Questions, answers, grants, URLs and credentials are not
part of this evidence format. A passing report is a release gate, not permission to run
the spike or enable the feature flags.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


SCHEMA = "zoop-chat-live-spike-1"
MAX_JOB_SECONDS = Decimal("45")
MAX_INPUT_TOKENS = 24_000
MAX_OUTPUT_TOKENS = 2_000
DEFAULT_MIN_SAMPLES = 5

# This is intentionally fixed in code so an operator cannot weaken the gate by editing
# the evidence file. The 8-call case remains required even while the web tool is absent;
# that dependency must be implemented or explicitly resolved by a policy revision.
SCENARIOS: dict[str, tuple[int, int]] = {
    "tools-1-rounds-1": (1, 1),
    "tools-4-rounds-1": (4, 1),
    "tools-4-rounds-3": (4, 3),
    "tools-8-rounds-3": (8, 3),
}

TOP_KEYS = {
    "schemaVersion", "candidateCommit", "approvedBy", "approvalRef", "environment",
    "policyVersion", "model", "promptVersion", "toolRegistryVersion", "runs",
}
RUN_KEYS = {
    "runId", "scenario", "mode", "status", "startedAt", "committedAt", "toolCalls",
    "approvalRounds", "providerCalls", "inputTokens", "outputTokens", "reasoningTokens",
    "costUsd", "failureCode",
}


class EvidenceError(ValueError):
    pass


COMMIT = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class Run:
    run_id: str
    scenario: str
    status: str
    latency_seconds: Decimal
    tool_calls: int
    approval_rounds: int
    provider_calls: int
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cost_usd: Decimal
    failure_code: str | None


def _exact_keys(value: dict[str, Any], expected: set[str], where: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise EvidenceError(f"{where} keys differ: missing={missing}, extra={extra}")


def _text(value: Any, where: str, *, limit: int = 200) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 0x20 for c in value):
        raise EvidenceError(f"{where} must be a non-empty printable string up to {limit} characters")
    return value


def _count(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvidenceError(f"{where} must be a non-negative integer")
    return value


def _time(value: Any, where: str) -> datetime:
    text = _text(value, where)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise EvidenceError(f"{where} must be an ISO-8601 timestamp with an offset") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceError(f"{where} must include an offset")
    return parsed


def _money(value: Any, where: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise EvidenceError(f"{where} must report the provider cost; null is not evidence")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise EvidenceError(f"{where} must be a decimal amount") from None
    if not amount.is_finite() or amount < 0:
        raise EvidenceError(f"{where} must be a finite non-negative amount")
    return amount


def _run(value: Any, index: int) -> Run:
    where = f"runs[{index}]"
    if not isinstance(value, dict):
        raise EvidenceError(f"{where} must be an object")
    _exact_keys(value, RUN_KEYS, where)
    run_id = _text(value["runId"], f"{where}.runId", limit=128)
    scenario = _text(value["scenario"], f"{where}.scenario", limit=64)
    if scenario not in SCENARIOS:
        raise EvidenceError(f"{where}.scenario is not one of {sorted(SCENARIOS)}")
    if value["mode"] != "live":
        raise EvidenceError(f"{where}.mode must be live")
    status = value["status"]
    if status not in {"completed", "failed"}:
        raise EvidenceError(f"{where}.status must be completed or failed")
    failure = value["failureCode"]
    if failure is not None:
        failure = _text(failure, f"{where}.failureCode", limit=64)
    if (status == "completed") == (failure is not None):
        raise EvidenceError(f"{where}.failureCode must be null exactly for completed runs")

    started = _time(value["startedAt"], f"{where}.startedAt")
    committed = _time(value["committedAt"], f"{where}.committedAt")
    seconds = Decimal(str((committed - started).total_seconds()))
    if seconds < 0:
        raise EvidenceError(f"{where}.committedAt is before startedAt")

    tool_calls = _count(value["toolCalls"], f"{where}.toolCalls")
    rounds = _count(value["approvalRounds"], f"{where}.approvalRounds")
    expected_calls, expected_rounds = SCENARIOS[scenario]
    if tool_calls != expected_calls or rounds != expected_rounds:
        raise EvidenceError(
            f"{where} does not match {scenario}: toolCalls={tool_calls}, approvalRounds={rounds}"
        )

    provider_calls = _count(value["providerCalls"], f"{where}.providerCalls")
    if status == "completed" and provider_calls != rounds + 1:
        raise EvidenceError(
            f"{where}.providerCalls must equal approvalRounds + 1 for a completed run"
        )

    return Run(
        run_id=run_id,
        scenario=scenario,
        status=status,
        latency_seconds=seconds,
        tool_calls=tool_calls,
        approval_rounds=rounds,
        provider_calls=provider_calls,
        input_tokens=_count(value["inputTokens"], f"{where}.inputTokens"),
        output_tokens=_count(value["outputTokens"], f"{where}.outputTokens"),
        reasoning_tokens=_count(value["reasoningTokens"], f"{where}.reasoningTokens"),
        cost_usd=_money(value["costUsd"], f"{where}.costUsd"),
        failure_code=failure,
    )


def load(path: Path) -> tuple[dict[str, str], list[Run]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"cannot read evidence: {error}") from None
    if not isinstance(raw, dict):
        raise EvidenceError("evidence root must be an object")
    _exact_keys(raw, TOP_KEYS, "root")
    if raw["schemaVersion"] != SCHEMA:
        raise EvidenceError(f"schemaVersion must be {SCHEMA}")
    candidate_commit = _text(raw["candidateCommit"], "candidateCommit", limit=40)
    if not COMMIT.fullmatch(candidate_commit):
        raise EvidenceError("candidateCommit must be a lowercase 40-character Git commit")
    metadata = {
        key: _text(raw[key], key)
        for key in ("approvedBy", "approvalRef", "environment", "policyVersion", "model", "promptVersion", "toolRegistryVersion")
    }
    metadata["candidateCommit"] = candidate_commit
    if not isinstance(raw["runs"], list) or not raw["runs"]:
        raise EvidenceError("runs must be a non-empty array")
    runs = [_run(value, index) for index, value in enumerate(raw["runs"])]
    ids = [run.run_id for run in runs]
    if len(ids) != len(set(ids)):
        raise EvidenceError("runId values must be unique")
    return metadata, runs


def _percentile(values: list[Decimal], percentage: Decimal) -> Decimal:
    ordered = sorted(values)
    index = max(0, math.ceil(float(percentage * len(ordered))) - 1)
    return ordered[index]


def report(metadata: dict[str, str], runs: list[Run], min_samples: int) -> dict[str, Any]:
    if min_samples < 1:
        raise EvidenceError("min-samples must be at least 1")
    failures: list[str] = []
    scenarios: dict[str, Any] = {}
    for name in SCENARIOS:
        selected = [run for run in runs if run.scenario == name]
        if len(selected) < min_samples:
            failures.append(f"{name}: needs {min_samples} samples, found {len(selected)}")
        if not selected:
            scenarios[name] = {"samples": 0, "status": "missing"}
            continue
        latencies = [run.latency_seconds for run in selected]
        completed = sum(run.status == "completed" for run in selected)
        scenarios[name] = {
            "samples": len(selected),
            "completed": completed,
            "p50Seconds": float(_percentile(latencies, Decimal("0.50"))),
            "p95Seconds": float(_percentile(latencies, Decimal("0.95"))),
            "maxSeconds": float(max(latencies)),
            "providerCalls": sum(run.provider_calls for run in selected),
            "inputTokens": sum(run.input_tokens for run in selected),
            "outputTokens": sum(run.output_tokens for run in selected),
            "reasoningTokens": sum(run.reasoning_tokens for run in selected),
            "costUsd": str(sum((run.cost_usd for run in selected), Decimal(0))),
        }
        if completed != len(selected):
            failures.append(f"{name}: {len(selected) - completed} run(s) failed")

    for run in runs:
        if run.latency_seconds > MAX_JOB_SECONDS:
            failures.append(f"{run.run_id}: terminal commit exceeded {MAX_JOB_SECONDS}s")
        if run.input_tokens > MAX_INPUT_TOKENS:
            failures.append(f"{run.run_id}: input tokens exceeded {MAX_INPUT_TOKENS}")
        if run.output_tokens > MAX_OUTPUT_TOKENS:
            failures.append(f"{run.run_id}: output tokens exceeded {MAX_OUTPUT_TOKENS}")
        if run.failure_code in {"response_unknown", "stage_outcome_unknown", "reconcile_required"}:
            failures.append(f"{run.run_id}: provider outcome is unknown")

    return {
        "schemaVersion": SCHEMA,
        **metadata,
        "gate": "passed" if not failures else "failed",
        "minimumSamplesPerScenario": min_samples,
        "scenarios": scenarios,
        "failures": failures,
        "totals": {
            "runs": len(runs),
            "providerCalls": sum(run.provider_calls for run in runs),
            "inputTokens": sum(run.input_tokens for run in runs),
            "outputTokens": sum(run.output_tokens for run in runs),
            "reasoningTokens": sum(run.reasoning_tokens for run in runs),
            "costUsd": str(sum((run.cost_usd for run in runs), Decimal(0))),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="content-free zoop-chat-live-spike-1 JSON evidence")
    parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    parser.add_argument("--output", type=Path, help="optional JSON report path; stdout is always written")
    args = parser.parse_args(argv)
    try:
        metadata, runs = load(args.evidence)
        result = report(metadata, runs, args.min_samples)
    except EvidenceError as error:
        print(json.dumps({"schemaVersion": SCHEMA, "gate": "invalid", "error": str(error)}, ensure_ascii=False))
        return 64
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    return 0 if result["gate"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
