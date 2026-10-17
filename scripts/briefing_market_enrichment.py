#!/usr/bin/env python3
"""Append frozen market components to a preserved simulation in a separate output/DB."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
import sys


def helper(name):
    spec = importlib.util.spec_from_file_location("_enrichment_" + name, Path(__file__).with_name(name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


market = helper("briefing_market_data")
summary = helper("briefing_market_summary")
base = market.base


def copy_calls(source, destination):
    base.private_dir(destination)
    for path in sorted(source.glob("*.json")):
        if path.name.endswith((".pending.json", ".request.json", ".response.json", ".complete.json")):
            base.write_once(destination / path.name, base.regular(path))


def run(args, market_transport=None, ai_transport=None):
    baseline, output = Path(args.baseline).resolve(), Path(args.output).resolve()
    if output == baseline or baseline in output.parents:
        raise base.ReplayError("market_enrichment_requires_separate_output")
    original_bytes = base.regular(baseline / "bundle-v2.json")
    original = base.strict_load(original_bytes)
    if original.get("schemaVersion") != "zoop-briefing-round-simulation-v2" or original.get("marketEnrichment"):
        raise base.ReplayError("market_enrichment_original_simulation_required")
    if base.digest(base.regular(Path(args.sources))) != original["sourceFileSha256"] \
            or base.digest(base.regular(Path(args.clocks))) != original["clockFileSha256"]:
        raise base.ReplayError("market_enrichment_source_or_clock_mismatch")
    rounds = [r for r in original["rounds"] if r["selectionStatus"] == "SELECTED"]
    if len(original["rounds"]) != 14 or len(rounds) > 14:
        raise base.ReplayError("market_enrichment_round_population_invalid")
    for r in rounds:
        if r.get("result", {}).get("verification", {}).get("status") != "PASS" \
                or base.digest(base.canonical(r["result"])) != r["resultSha256"]:
            raise base.ReplayError("market_enrichment_news_not_verified")
    plan = {"baselineBundleSha256": base.digest(original_bytes), "userInboxRef": args.user_inbox_ref,
            "roundIds": [r["roundId"] for r in rounds], "maximumSummaryCalls": 4 * len(rounds),
            "maxCalls": args.max_calls, "sourceFileSha256": original["sourceFileSha256"],
            "clockFileSha256": original["clockFileSha256"], "operationalCollectionGate": False}
    if not args.execute_authorized_enrichment:
        return {**plan, "status": "OFFLINE", "newHttpCalls": 0, "newPaidCalls": 0}
    if not args.user_inbox_ref or not (args.key_file or ai_transport) or 2 * len(rounds) > args.max_calls:
        raise base.ReplayError("market_enrichment_explicit_authorization_or_budget_required")
    base.private_dir(output)
    base.save_json(output / "plan.json", plan)
    final_path = output / "bundle-v2.json"
    if final_path.exists():
        binding = base.strict_load(base.regular(output / "bundle.binding.json"))
        if binding != {"bundleSha256": base.digest(base.regular(final_path)), "planSha256": base.digest(base.canonical(plan))}:
            raise base.ReplayError("market_enrichment_cached_bundle_changed")
        final = base.strict_load(base.regular(final_path))
        for record in final["marketEnrichment"]["rounds"]:
            for name, directory in (("marketSnapshotSha256", "snapshots"), ("summaryResultSha256", "summaries")):
                sha = record[name]
                if base.digest(base.regular(output / "market" / directory / (sha + ".json"))) != sha:
                    raise base.ReplayError("market_enrichment_cached_artifact_changed")
        market.fetch_receipts(output, lambda _: (_ for _ in ()).throw(base.ReplayError("cached_enrichment_must_not_refetch")))
        return {"status": "COMPLETE", "rounds": len(rounds), "newHttpCalls": 0, "newPaidCalls": 0,
                "summaryPass": sum(r["summaryResult"]["verification"]["status"] == "PASS" for r in final["marketEnrichment"]["rounds"]),
                "bundlePath": str(final_path)}
    lock = output / ".enrichment.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise base.ReplayError("active_or_interrupted_market_enrichment_requires_inspection") from error
    os.close(fd)
    client = None
    original_prompts = summary.PROMPTS
    try:
        receipts, http_calls = market.fetch_receipts(output, market_transport or market.transport)
        ai_output = output / "summary-run"
        base.private_dir(ai_output)
        frozen_prompts = ai_output / "prompts"
        base.private_dir(frozen_prompts)
        for prompt in sorted(original_prompts.iterdir()):
            if prompt.is_file():
                base.write_once(frozen_prompts / prompt.name, base.regular(prompt))
        summary.PROMPTS = frozen_prompts
        prompt_artifacts = {p.name: base.digest(base.regular(p)) for p in sorted(frozen_prompts.iterdir()) if p.is_file()}
        client = summary.MarketSummaryClient(ai_output, ai_transport or base.authenticated_transport(Path(args.key_file)), args.max_calls)
        snapshots, summaries = output / "market/snapshots", output / "market/summaries"
        base.private_dir(snapshots)
        base.private_dir(summaries)

        def enrich(r):
            snapshot = market.snapshot(r, receipts, output)
            snapshot_bytes = base.canonical(snapshot)
            snapshot_sha = base.digest(snapshot_bytes)
            base.write_once(snapshots / (snapshot_sha + ".json"), snapshot_bytes)
            cutoff = r["window"]["to"]
            context = {"roundId": r["roundId"], "date": r["date"], "edition": r["edition"], "cutoff": cutoff,
                       "newsResultSha256": r["resultSha256"], "marketSnapshotSha256": snapshot_sha,
                       "userInboxRef": args.user_inbox_ref, "promptArtifacts": prompt_artifacts}
            context_sha = base.digest(base.canonical(context))
            result = summary.generate_market_summary(client, {"context": context, "contextSha256": context_sha,
                "selected": r["selected"], "newsItems": r["result"]["items"], "marketSnapshot": snapshot}, 1)
            result_bytes = base.canonical(result)
            result_sha = base.digest(result_bytes)
            base.write_once(summaries / (result_sha + ".json"), result_bytes)
            record = {"roundId": r["roundId"], "date": r["date"], "edition": r["edition"], "cutoff": cutoff,
                      "newsResultSha256": r["resultSha256"], "marketSnapshot": snapshot, "marketSnapshotSha256": snapshot_sha,
                      "summaryResult": result, "summaryResultSha256": result_sha, "context": context, "contextSha256": context_sha,
                      "receipts": result["usage"]}
            print(base.canonical({"round": r["date"] + "-" + r["edition"], "summary": result["verification"]["status"],
                "indicators": {i["id"]: i["observedDate"] for i in snapshot["marketVariables"]["indicators"]}}).decode(), flush=True)
            return record
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            components = list(executor.map(enrich, rounds))
        final = {**original, "marketEnrichment": {"schemaVersion": "zoop-briefing-market-enrichment-v1",
                 "digestScheme": "raw-json-sha256-v1", "userInboxRef": args.user_inbox_ref,
                 "baselineBundleSha256": plan["baselineBundleSha256"], "rounds": components, "receipts": client.receipts()}}
        copy_calls(baseline / "calls", output / "calls")
        copy_calls(ai_output / "calls", output / "calls")
        base.save_json(final_path, final)
        base.save_json(output / "bundle.binding.json", {"bundleSha256": base.digest(base.regular(final_path)),
                       "planSha256": base.digest(base.canonical(plan))})
        return {"status": "COMPLETE", "rounds": len(rounds), "newHttpCalls": http_calls, "newPaidCalls": len(client.new_calls),
                "summaryPass": sum(r["summaryResult"]["verification"]["status"] == "PASS" for r in components), "bundlePath": str(final_path)}
    finally:
        if client is not None:
            accounting = base.canonical(client.receipts())
            base.write_once(output / ("accounting-" + base.digest(accounting) + ".json"), accounting)
        summary.PROMPTS = original_prompts
        lock.unlink(missing_ok=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ("baseline", "output", "sources", "clocks", "user-inbox-ref"):
        p.add_argument("--" + flag, required=True)
    p.add_argument("--key-file")
    p.add_argument("--execute-authorized-enrichment", action="store_true")
    p.add_argument("--max-calls", type=base.bounded(1, 56), default=44)
    p.add_argument("--workers", type=base.bounded(1, 3), default=3)
    return p


if __name__ == "__main__":
    try:
        print(base.canonical(run(parser().parse_args())).decode())
    except (base.ReplayError, ValueError) as error:
        print(base.canonical({"status": "STOPPED", "reason": str(error)}).decode(), file=sys.stderr)
        raise SystemExit(2)
