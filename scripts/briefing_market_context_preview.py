#!/usr/bin/env python3
"""Freeze real broad/prior-summary inputs from existing historical snapshots without HTTP or AI calls."""

import argparse
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("_market_context_preview", Path(__file__).with_name("briefing_market_context.py"))
context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(context)
base = context.base


def run(args):
    bundle_path = Path(args.market_bundle).resolve()
    raw = base.regular(bundle_path)
    bundle = base.strict_load(raw)
    rows, unknown, coverage = context.simulation.load_inputs(Path(args.sources), Path(args.clocks))
    context.require(bundle["sourceFileSha256"] == coverage["sourceFileSha256"]
                    and bundle["clockFileSha256"] == coverage["clockFileSha256"], "preview_source_binding")
    records = bundle["marketEnrichment"]["rounds"]
    by_id = {r["roundId"]: r for r in records}
    context.require(len(by_id) == len(records), "preview_duplicate_round")
    calendar_raw = base.regular(Path(args.session_calendar)) if args.session_calendar else None
    calendar = base.strict_load(calendar_raw) if calendar_raw else None
    output = Path(args.output).resolve() if args.output else None
    if args.write_inputs:
        context.require(output is not None and output != bundle_path.parent and bundle_path.parent not in output.parents,
                        "preview_separate_output_required")
        base.private_dir(output)
    prompts = {p.name: base.digest(base.regular(p)) for p in sorted(context.PROMPTS.iterdir()) if p.is_file()}
    values = []
    for round_ in bundle["rounds"]:
        if round_["selectionStatus"] != "SELECTED":
            continue
        record = by_id[round_["roundId"]]
        context.require(record["summaryResultSha256"] == base.digest(base.canonical(record["summaryResult"]))
                        and record["marketSnapshotSha256"] == base.digest(base.canonical(record["marketSnapshot"])), "preview_result_binding")
        broad = context.build_context(rows, round_, record["marketSnapshot"], records, calendar, len(unknown))
        identity = {"roundId": round_["roundId"], "date": round_["date"], "edition": round_["edition"],
                    "cutoff": round_["window"]["to"], "newsResultSha256": round_["resultSha256"],
                    "marketSnapshotSha256": record["marketSnapshotSha256"], "marketContextSha256": base.digest(base.canonical(broad)),
                    "userInboxRef": args.user_inbox_ref, "promptArtifacts": prompts, "summaryPromptVersion": "market-context-v2"}
        data = {"context": identity, "contextSha256": base.digest(base.canonical(identity)), "marketContext": broad,
                "marketSnapshot": record["marketSnapshot"], "selected": round_["selected"], "newsItems": round_["result"]["items"]}
        frozen, evidence, indicators, prior, evaluations, _ = context._prepare(data)
        request = {**frozen, "frozenInputSha256": base.digest(base.canonical(frozen)), "repairAttempt": 0,
                   "priorDraft": None, "priorValidation": None}
        encoded, _, _ = context.legacy.prepare_market_request(context.PROMPTS, "market_summary_generation", request,
            "generation.md", "generation.schema.json", max_output=8000,
            schema_override=context._schema(frozen, evidence, indicators, prior, evaluations))
        digest = base.digest(encoded)
        if args.write_inputs:
            base.write_once(output / (digest + ".request.json"), encoded)
        values.append({"roundId": round_["roundId"], "date": round_["date"], "edition": round_["edition"],
                       "requestSha256": digest, "requestBytes": len(encoded), "contextSha256": identity["marketContextSha256"],
                       "sourceCoverage": broad["coverage"], "previousSummary": broad["previousPublication"]["status"],
                       "structuredPriorForecasts": len(prior), "priceForecastTargets": len(broad["forecastTargets"]),
                       "forecastUnavailableReason": broad["forecastUnavailableReason"]})
    result = {"schemaVersion": "zoop-market-context-preview-v1", "baselineBundleSha256": base.digest(raw),
              "userInboxRef": args.user_inbox_ref, "rounds": values, "realHttpCalls": 0, "realPaidCalls": 0,
              "historicalSimulationOnly": True, "generatedMarketSummaries": 0}
    if calendar_raw is not None:
        result["sessionCalendarSha256"] = base.digest(calendar_raw)
        if args.write_inputs:
            base.write_once(output / ("session-calendar-" + result["sessionCalendarSha256"] + ".json"), calendar_raw)
    if args.write_inputs:
        base.write_once(output / "preview.json", base.canonical(result))
    return result


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("market-bundle", "sources", "clocks", "user-inbox-ref"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--session-calendar")
    p.add_argument("--output")
    p.add_argument("--write-inputs", action="store_true")
    return p


if __name__ == "__main__":
    print(base.canonical(run(parser().parse_args())).decode())
