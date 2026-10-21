#!/usr/bin/env python3
"""Generate chronological, broad-evidence outlooks over a preserved presentation replay.

No collection or issue extraction is repeated. All original paid reservations,
including unknown usage, count toward the same ceiling. New model calls require
an explicit flag and a separate immutable output directory.
"""

import argparse
import copy
import importlib.util
import os
from pathlib import Path


def helper(name):
    spec = importlib.util.spec_from_file_location("_outlook_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


context = helper("briefing_market_context")
base = context.base
VERSION = "market-context-v2.3-outlook"
context.PROMPTS = context.PROMPTS.with_name(VERSION)


def _copy_tree(source, destination):
    for path in sorted(source.rglob("*")):
        if path.is_file():
            target = destination / path.relative_to(source)
            base.private_dir(target.parent)
            base.write_once(target, base.regular(path))


def rebind_derived_contexts(layer, inbox):
    """Re-authorize unchanged, unpaid display inputs; never rewrite paid records."""
    for row in layer["rounds"]:
        if row.get("summaryMode") != "verified_issue_claims_and_indicators_v1":
            continue
        market = row["marketEnrichment"]
        context.require(market["summaryResult"] is None and not market["receipts"], "outlook_derived_paid_record")
        market["context"]["userInboxRef"] = inbox
        market["contextSha256"] = base.digest(base.canonical(market["context"]))


def prepare(args):
    global VERSION
    if getattr(args, "prompt_version", None):
        VERSION = args.prompt_version
        context.PROMPTS = context.PROMPTS.with_name(VERSION)
    baseline = Path(args.baseline).resolve()
    raw = base.regular(baseline / "bundle-v2.json")
    bundle = base.strict_load(raw)
    presentation = bundle.get("presentationEnrichment")
    context.require(presentation and presentation.get("schemaVersion") == "zoop-briefing-presentation-enrichment-v1",
                    "outlook_presentation_baseline_required")
    # Refuse before any paid transport: the importer currently supports one history layer.
    context.require(not presentation.get("outlookHistory"), "outlook_nested_history_not_supported")
    context.require(base.digest(base.regular(Path(args.sources))) == bundle["sourceFileSha256"]
                    and base.digest(base.regular(Path(args.clocks))) == bundle["clockFileSha256"],
                    "outlook_source_or_clock_mismatch")
    rows, unknown, _ = context.simulation.load_inputs(Path(args.sources), Path(args.clocks))
    calendar = base.strict_load(base.regular(Path(args.session_calendar)))
    keys = args.round or [r["date"] + "-" + r["edition"] for r in presentation["rounds"]]
    definitions = {r["roundId"]: r for r in bundle["rounds"]}
    recovered = {r["roundId"]: r for r in bundle["briefingRecovery"]["rounds"]}
    records = {r["roundId"]: r for r in presentation["rounds"]}
    chosen = []
    for key in keys:
        matches = [r for r in presentation["rounds"] if r["date"] + "-" + r["edition"] == key]
        context.require(len(matches) == 1, "outlook_round_missing_or_ambiguous")
        row = matches[0]
        effective = recovered[row["roundId"]]
        context.require(effective["status"] == "SELECTED"
                        and effective["result"]["verification"]["status"] == "PASS"
                        and base.digest(base.canonical(effective["result"])) == effective["resultSha256"],
                        "outlook_verified_news_required")
        chosen.append((definitions[row["roundId"]], effective, row))
    cutoffs = [context.legacy._aware(x[0]["window"]["to"]) for x in chosen]
    context.require(cutoffs == sorted(set(cutoffs)), "outlook_chronological_rounds_required")
    # Verify the calendar and all source populations without making a paid call.
    coverage = []
    for definition, effective, row in chosen:
        snapshot = row["marketEnrichment"]["marketSnapshot"]
        broad = context.build_context(rows, definition, snapshot, (), calendar, len(unknown))
        context.require(broad["forecastTargets"], "outlook_verified_target_required")
        coverage.append({"roundId": definition["roundId"], **broad["coverage"],
                         "targetDates": sorted({t["targetDate"] for t in broad["forecastTargets"]})})
    prior = len(list((baseline / "calls").glob("*.pending.json")))
    context.require(prior + 2 * len(chosen) <= args.max_calls <= 512, "outlook_shared_budget_insufficient")
    if args.max_calls > 400:
        context.require(bool(getattr(args, "budget_approval_ref", None)), "outlook_budget_extension_approval_required")
    prompts = {p.name: base.digest(base.regular(p)) for p in sorted(context.PROMPTS.iterdir()) if p.is_file()}
    plan = {"schemaVersion": "zoop-market-outlook-execution-v1", "baselineBundleSha256": base.digest(raw),
            "userInboxRef": args.user_inbox_ref, "runId": args.run_id, "promptVersion": VERSION,
            "promptArtifacts": prompts, "sourceFileSha256": bundle["sourceFileSha256"],
            "clockFileSha256": bundle["clockFileSha256"], "calendarSha256": base.digest(base.canonical(calendar)),
            "priorReservations": prior, "maxCallsIncludingPrior": args.max_calls,
            "budgetApprovalRef": getattr(args, "budget_approval_ref", None),
            "maxRepairsPerRound": getattr(args, "max_repairs", 0),
            "plannedNewCalls": 2 * len(chosen), "roundIds": [r[0]["roundId"] for r in chosen],
            "coverage": coverage, "newProviderFetches": 0, "operationalCollectionGate": False}
    return raw, bundle, rows, unknown, calendar, chosen, records, plan


def run(args, transport=None):
    raw, original, rows, unknown, calendar, chosen, records, plan = prepare(args)
    if not args.execute_authorized_generation:
        return {**plan, "status": "OFFLINE", "newPaidCalls": 0}
    output, baseline = Path(args.output).resolve(), Path(args.baseline).resolve()
    context.require(output != baseline and baseline not in output.parents and output not in baseline.parents,
                    "outlook_separate_output_required")
    context.require(args.user_inbox_ref and (args.key_file or transport), "outlook_explicit_authorization_required")
    base.private_dir(output)
    base.write_once(output / "outlook-plan.json", base.canonical(plan))
    if (output / "outlook-proof.json").exists():
        proof = base.strict_load(base.regular(output / "outlook-proof.json"))
        context.require(base.digest(base.regular(output / "bundle-v2.json")) == proof["bundleSha256"],
                        "outlook_completed_bundle_changed")
        return {**proof, "newPaidCalls": 0, "reusedCompletedRun": True}
    lock = output / ".outlook-execution.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    client = None
    try:
        for name in ("base-presentation-bundle.json", "base-bundle-v2.json", "grouped-issues.json", "editorial-review-holds.json"):
            if (baseline / name).exists():
                base.write_once(output / name, base.regular(baseline / name))
        _copy_tree(baseline / "calls", output / "calls")
        _copy_tree(baseline / "market", output / "market")
        base.write_once(output / "input-presentation-bundle.json", raw)
        prompt_root = output / "outlook-prompts"
        base.private_dir(prompt_root)
        for path in sorted(context.PROMPTS.iterdir()):
            if path.is_file():
                base.write_once(prompt_root / path.name, base.regular(path))
        # Count the original 391 reservations and preserve their two unknown calls.
        client = context.legacy.MarketSummaryClient(output,
            transport or base.authenticated_transport(Path(args.key_file), timeout=600),
            args.max_calls, prompt_root=prompt_root)
        final = copy.deepcopy(original)
        layer = final["presentationEnrichment"]
        layer.update(runId=args.run_id, userInboxRef=args.user_inbox_ref,
                     maximumPaidCallsIncludingPrior=args.max_calls)
        rebind_derived_contexts(layer, args.user_inbox_ref)
        if original["presentationEnrichment"]["receipts"]:
            sha = base.digest(raw)
            base.private_dir(output / "market/outlook-history")
            base.write_once(output / "market/outlook-history" / (sha + ".json"), raw)
            layer["outlookHistory"] = {"bundleSha256": sha,
                "receipts": original["presentationEnrichment"]["receipts"]}
        target_rows = {r["roundId"]: r for r in layer["rounds"]}
        completed = []
        for definition, effective, row in chosen:
            snapshot = row["marketEnrichment"]["marketSnapshot"]
            snapshot_sha = base.digest(base.canonical(snapshot))
            # Replacements from this run win. The next round reads the exact new PASS version.
            histories = [*completed, *(r["marketEnrichment"] for r in records.values()
                if r["roundId"] not in {x["roundId"] for x in completed})]
            broad = context.build_context(rows, definition, snapshot, histories, calendar, len(unknown))
            identity = {"roundId": definition["roundId"], "date": definition["date"], "edition": definition["edition"],
                        "cutoff": definition["window"]["to"], "newsResultSha256": effective["resultSha256"],
                        "marketSnapshotSha256": snapshot_sha, "userInboxRef": args.user_inbox_ref,
                        "promptArtifacts": plan["promptArtifacts"], "summaryPromptVersion": VERSION,
                        "marketContextSha256": base.digest(base.canonical(broad))}
            data = {"context": identity, "contextSha256": base.digest(base.canonical(identity)),
                    "selected": effective["selected"], "newsItems": effective["result"]["items"],
                    "marketSnapshot": snapshot, "marketContext": broad}
            frozen = context._prepare(data)[0]
            for folder, value in (("contexts", broad), ("frozen-inputs", frozen)):
                encoded = base.canonical(value)
                base.private_dir(output / "market" / folder)
                base.write_once(output / "market" / folder / (base.digest(encoded) + ".json"), encoded)
            # No unbounded repair loop; later reruns reuse completed request/response bytes.
            result = context.generate_market_summary(client, data, max_repairs=getattr(args, "max_repairs", 0))
            result_raw = base.canonical(result)
            base.private_dir(output / "market/summaries")
            base.write_once(output / "market/summaries" / (base.digest(result_raw) + ".json"), result_raw)
            record = {**{k: identity[k] for k in ("roundId", "date", "edition", "cutoff", "newsResultSha256")},
                      "marketSnapshot": snapshot, "marketSnapshotSha256": snapshot_sha,
                      "marketContext": broad, "context": identity, "contextSha256": data["contextSha256"],
                      "summaryResult": result, "summaryResultSha256": base.digest(result_raw), "receipts": result["usage"]}
            completed.append(record)
            target_rows[definition["roundId"]]["marketEnrichment"] = record
            target_rows[definition["roundId"]].pop("summaryMode", None)
            base.private_dir(output / "completed-outlook-rounds")
            base.write_once(output / "completed-outlook-rounds" / (definition["roundId"] + ".json"), base.canonical(record))
            print(base.canonical({"round": definition["date"] + "-" + definition["edition"],
                "status": result["verification"]["status"], "claims": len(result["claims"]),
                "forecasts": len(result["forecasts"]), "previous": broad["previousPublication"]["status"],
                "newPaidCalls": len(client.new_calls)}).decode(), flush=True)
        owned = {r["requestDigest"] for row in layer["rounds"] for r in row["marketEnrichment"]["receipts"]}
        layer["receipts"] = [r for r in client.receipts() if r["requestDigest"] in owned]
        base.save_json(output / "bundle-v2.json", final)
        proof = {"status": "COMPLETE", "runId": args.run_id, "rounds": len(completed),
                 "summaryPass": sum(r["summaryResult"]["verification"]["status"] == "PASS" for r in completed),
                 "newPaidCalls": len(client.new_calls), "priorReservations": plan["priorReservations"],
                 "totalReservations": len(list(client.calls.glob("*.pending.json"))), "newProviderFetches": 0,
                 "bundleSha256": base.digest(base.regular(output / "bundle-v2.json")),
                 "inputTokens": sum(r["inputTokens"] for r in layer["receipts"] if r["usageKnown"]),
                 "outputTokens": sum(r["outputTokens"] for r in layer["receipts"] if r["usageKnown"]),
                 "usageKnownForNewCalls": all(r["usageKnown"] for r in layer["receipts"]),
                 "bundlePath": str(output / "bundle-v2.json")}
        base.write_once(output / "outlook-proof.json", base.canonical(proof))
        return proof
    finally:
        if client:
            accounting = base.canonical(client.receipts())
            base.write_once(output / ("outlook-accounting-" + base.digest(accounting) + ".json"), accounting)
        lock.unlink(missing_ok=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ("baseline", "sources", "clocks", "session-calendar", "output", "user-inbox-ref", "run-id"):
        p.add_argument("--" + flag, required=True)
    p.add_argument("--round", action="append", help="Chronological date-edition key; defaults to all available rounds")
    p.add_argument("--key-file")
    p.add_argument("--prompt-version", choices=("market-context-v2.1-outlook", "market-context-v2.2-outlook", "market-context-v2.3-outlook"),
                   help="Fresh CLI runs default to v2.3; select the original version to reuse an immutable old plan")
    p.add_argument("--max-calls", type=base.bounded(1, 512), default=400)
    p.add_argument("--budget-approval-ref", help="Separate explicit human approval for a ceiling above the existing 400 calls")
    p.add_argument("--max-repairs", type=int, choices=(0, 1), default=0)
    p.add_argument("--execute-authorized-generation", action="store_true")
    return p


if __name__ == "__main__":
    print(base.canonical(run(parser().parse_args())).decode(), flush=True)
