#!/usr/bin/env python3
"""Build the content-free live spike evidence from the chat ledger.

The inputs are the output of scripts/chat_live_spike_ledger.sql and an operator manifest naming the approved run and which
job measured which scenario. Everything measured comes from the ledger, never from the manifest, and the result is checked
by the same loader as the report gate before it is written. A completed run whose shape is not its scenario stops the
extraction with the runs named: it is neither dropped nor relabelled, and the operator decides what to do with it.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


MANIFEST_SCHEMA = "zoop-chat-live-spike-manifest-1"
AGENT_STAGE = "chat-agent"
MANIFEST_KEYS = {
    "schemaVersion", "candidateCommit", "approvedBy", "approvalRef", "environment", "policyVersion", "pricing", "runs",
}
PRICE_KEYS = {"inputUsdPerMTok", "outputUsdPerMTok"}
MILLION = Decimal(1_000_000)


class ExtractError(ValueError):
    pass


class ShapeMismatch(ExtractError):
    def __init__(self, mismatches: list[str]) -> None:
        super().__init__("completed runs do not match their scenario")
        self.mismatches = mismatches


def _report_module() -> Any:
    name = "chat_live_spike_report"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise ExtractError("cannot load the report gate")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _read(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ExtractError(f"cannot read {what}: {error}") from None


def _price(value: Any, where: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ExtractError(f"{where} must be a decimal string or integer")
    try:
        price = Decimal(str(value))
    except InvalidOperation:
        raise ExtractError(f"{where} must be a decimal amount") from None
    if not price.is_finite() or price < 0:
        raise ExtractError(f"{where} must be a finite non-negative amount")
    return price


def _prices(manifest: dict[str, Any]) -> dict[str, tuple[Decimal, Decimal]]:
    pricing = manifest["pricing"]
    if not isinstance(pricing, dict) or not pricing:
        raise ExtractError("pricing must name each model of the runs")
    prices = {}
    for model, price in pricing.items():
        if not isinstance(price, dict) or set(price) != PRICE_KEYS:
            raise ExtractError(f"pricing.{model} must have exactly {sorted(PRICE_KEYS)}")
        prices[model] = (_price(price["inputUsdPerMTok"], f"pricing.{model}.inputUsdPerMTok"),
                         _price(price["outputUsdPerMTok"], f"pricing.{model}.outputUsdPerMTok"))
    return prices


def _cost(stages: list[dict[str, Any]], prices: dict[str, tuple[Decimal, Decimal]], where: str) -> Decimal:
    """Every provider stage of the attempt, all input at the uncached price: an upper estimate of the bill."""
    total = Decimal(0)
    for stage in stages:
        if stage["sendState"] == "not_sent" or stage["sendState"] is None:
            continue
        model = stage["model"]
        if model not in prices:
            raise ExtractError(f"{where}: no price for model {model}")
        total += Decimal(stage["inputTokens"] or 0) * prices[model][0] / MILLION
        total += Decimal(stage["outputTokens"] or 0) * prices[model][1] / MILLION
    return total


def _single(values: set[Any], what: str) -> Any:
    known = {v for v in values if v is not None}
    if len(known) != 1:
        raise ExtractError(f"the runs must share one {what}, found {sorted(known)}")
    return known.pop()


def _run(job: dict[str, Any], scenario: str, prices: dict[str, tuple[Decimal, Decimal]]) -> dict[str, Any]:
    where = f"job {job['job_id']}"
    if job["status"] not in {"completed", "failed"}:
        raise ExtractError(f"{where} is not finished: {job['status']}")
    if job["attempts"] != 1 or job["attempt_mode"] != "run":
        raise ExtractError(f"{where} was rerun; the spike never sends a run twice")
    if job["started_at"] is None or job["finished_at"] is None:
        raise ExtractError(f"{where} has no start or terminal time")

    stages = job["stages"]
    if any(s["mode"] not in {"live", None} for s in stages):
        raise ExtractError(f"{where} is not a live run")
    agent = [s for s in stages if s["stage"] == AGENT_STAGE and s["sendState"] in {"sent", "unknown"}]
    completed = job["status"] == "completed"
    if completed and (job["path"] != "agent" or not agent):
        raise ExtractError(f"{where} took the direct path; it measures nothing of the agent path")
    if completed:
        for step in agent:
            if None in (step["inputTokens"], step["outputTokens"], step["reasoningTokens"]):
                raise ExtractError(f"{where}: a completed step did not report its tokens; null is not evidence")

    output = sum(s["outputTokens"] or 0 for s in agent)
    reasoning = sum(s["reasoningTokens"] or 0 for s in agent)
    answer = agent[-1]["outputTokens"] - agent[-1]["reasoningTokens"] if completed else 0
    return {
        "runId": job["job_id"],
        "scenario": scenario,
        "mode": "live",
        "status": job["status"],
        "startedAt": job["started_at"],
        "committedAt": job["finished_at"],
        "toolCalls": job["tool_calls"],
        "approvalRounds": max(len(agent) - 1, 0),
        "providerCalls": len(agent),
        "inputTokens": sum(s["inputTokens"] or 0 for s in agent),
        "outputTokens": output,
        "reasoningTokens": reasoning,
        "answerTokens": answer,
        "costUsd": format(_cost(stages, prices, where), "f"),
        "failureCode": None if completed else job["failure_code"] or "failed",
    }


def extract(manifest: Any, ledger: Any) -> dict[str, Any]:
    report = _report_module()
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS:
        raise ExtractError(f"manifest must have exactly {sorted(MANIFEST_KEYS)}")
    if manifest["schemaVersion"] != MANIFEST_SCHEMA:
        raise ExtractError(f"schemaVersion must be {MANIFEST_SCHEMA}")
    if not isinstance(manifest["runs"], list) or not manifest["runs"]:
        raise ExtractError("runs must be a non-empty array")
    if not isinstance(ledger, list):
        raise ExtractError("the ledger must be the array chat_live_spike_ledger.sql prints")
    prices = _prices(manifest)
    jobs = {job["job_id"]: job for job in ledger}

    runs = []
    seen = set()
    mismatches = []
    for entry in manifest["runs"]:
        if not isinstance(entry, dict) or set(entry) != {"jobId", "scenario"}:
            raise ExtractError("each manifest run must have exactly jobId and scenario")
        job_id, scenario = entry["jobId"], entry["scenario"]
        if job_id in seen:
            raise ExtractError(f"job {job_id} is named twice")
        seen.add(job_id)
        if job_id not in jobs:
            raise ExtractError(f"job {job_id} is not in the ledger")
        if scenario not in report.SCENARIOS:
            raise ExtractError(f"job {job_id}: unknown scenario {scenario}")
        run = _run(jobs[job_id], scenario, prices)
        calls, rounds = report.SCENARIOS[scenario]
        if run["status"] == "completed" and (run["toolCalls"], run["approvalRounds"]) != (calls, rounds):
            mismatches.append(f"{job_id}: {scenario} expects {calls} calls in {rounds} rounds, "
                              f"ran {run['toolCalls']} in {run['approvalRounds']}")
        runs.append(run)
    if mismatches:
        raise ShapeMismatch(mismatches)

    named = [jobs[entry["jobId"]] for entry in manifest["runs"]]
    agent = [s for job in named for s in job["stages"] if s["stage"] == AGENT_STAGE]
    return {
        "schemaVersion": report.SCHEMA,
        "candidateCommit": manifest["candidateCommit"],
        "approvedBy": manifest["approvedBy"],
        "approvalRef": manifest["approvalRef"],
        "environment": manifest["environment"],
        "policyVersion": manifest["policyVersion"],
        "model": _single({s["model"] for s in agent}, "agent model"),
        "promptVersion": _single({s["promptVersion"] for s in agent}, "agent prompt version"),
        "toolRegistryVersion": _single({v for job in named for v in job["registry_versions"]}, "tool registry version"),
        "runs": runs,
    }


def write(evidence: dict[str, Any], output: Path) -> None:
    """Writes the evidence only once the report gate's loader accepts it."""
    encoded = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    report = _report_module()
    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory) / "evidence.json"
        probe.write_text(encoded, encoding="utf-8")
        try:
            report.load(probe)
        except report.EvidenceError as error:
            raise ExtractError(f"the report gate refuses the evidence: {error}") from None
    output.write_text(encoded, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="operator manifest (zoop-chat-live-spike-manifest-1)")
    parser.add_argument("ledger", type=Path, help="output of scripts/chat_live_spike_ledger.sql")
    parser.add_argument("--output", type=Path, required=True, help="the zoop-chat-live-spike-1 evidence to write")
    args = parser.parse_args(argv)
    try:
        write(extract(_read(args.manifest, "manifest"), _read(args.ledger, "ledger")), args.output)
    except ShapeMismatch as error:
        print(json.dumps({"status": "shape_mismatch", "mismatches": error.mismatches}, ensure_ascii=False))
        return 2
    except ExtractError as error:
        print(json.dumps({"status": "invalid", "error": str(error)}, ensure_ascii=False))
        return 64
    print(json.dumps({"status": "written", "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
