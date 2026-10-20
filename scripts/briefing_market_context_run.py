#!/usr/bin/env python3
"""Execute an already frozen market preview without refetching or replacing prior versions."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location("frozen_market_preview", Path(__file__).with_name("briefing_market_context_preview.py"))
preview = importlib.util.module_from_spec(spec); spec.loader.exec_module(preview)
context, base = preview.context, preview.base
spec = importlib.util.spec_from_file_location("frozen_market_enrichment", Path(__file__).with_name("briefing_market_enrichment.py"))
enrichment = importlib.util.module_from_spec(spec); spec.loader.exec_module(enrichment)


def copy_tree(source, destination):
    for p in sorted(source.rglob("*")):
        if p.is_file():
            target = destination / p.relative_to(source)
            base.private_dir(target.parent); base.write_once(target, base.regular(p))


def prepare(args):
    inputs, prior_path = Path(args.inputs).resolve(), Path(args.market_bundle).resolve()
    manifest_raw = base.regular(inputs / "preview.json"); manifest = base.strict_load(manifest_raw)
    check = preview.run(argparse.Namespace(market_bundle=str(prior_path), sources=args.sources, clocks=args.clocks,
        user_inbox_ref=manifest["userInboxRef"], session_calendar=None, output=None, write_inputs=False))
    context.require(check == manifest, "frozen_preview_changed_or_not_reproducible")
    rows = []
    for r in manifest["rounds"]:
        raw = base.regular(inputs / (r["requestSha256"] + ".request.json"))
        context.require(base.digest(raw) == r["requestSha256"] and len(raw) == r["requestBytes"], "frozen_request_digest")
        request = base.strict_load(raw); data = base.strict_load(request["input"])
        fields = ("context", "contextSha256", "selected", "newsItems", "marketSnapshot", "marketContext")
        data = {k: data[k] for k in fields}
        frozen, evidence, indicators, prior, evaluations, _ = context._prepare(data)
        first = {**frozen, "frozenInputSha256": base.digest(base.canonical(frozen)), "repairAttempt": 0,
                 "priorDraft": None, "priorValidation": None}
        actual = context.legacy.prepare_market_request(context.PROMPTS, "market_summary_generation", first,
            "generation.md", "generation.schema.json", max_output=8000,
            schema_override=context._schema(frozen, evidence, indicators, prior, evaluations))[0]
        context.require(actual == raw and data["context"]["roundId"] == r["roundId"], "frozen_request_not_exact")
        rows.append((r, data, frozen))
    context.require(0 < len(rows) <= 14, "frozen_round_count")
    return manifest_raw, manifest, base.regular(prior_path), rows


def run(args, transport=None):
    manifest_raw, manifest, prior_raw, rows = prepare(args)
    prior = base.strict_load(prior_raw)
    output, inputs, prior_dir = Path(args.output).resolve(), Path(args.inputs).resolve(), Path(args.market_bundle).resolve().parent
    context.require(output != inputs and inputs not in output.parents and output != prior_dir and prior_dir not in output.parents,
                    "frozen_run_separate_output_required")
    plan = {"schemaVersion": "zoop-frozen-market-execution-v1", "previewSha256": base.digest(manifest_raw),
            "comparisonBaselineSha256": base.digest(prior_raw), "inputUserInboxRef": manifest["userInboxRef"],
            "executionAuthorizationRef": args.user_inbox_ref, "rounds": len(rows), "maxCalls": args.max_calls,
            "preparedRequestSha256s": [r[0]["requestSha256"] for r in rows]}
    if not args.execute_authorized_generation:
        return {**plan, "status": "OFFLINE", "newPaidCalls": 0, "newHttpCalls": 0}
    context.require(args.user_inbox_ref and (args.key_file or transport) and 2 * len(rows) <= args.max_calls,
                    "frozen_run_authorization_or_budget")
    base.private_dir(output); base.write_once(output / "execution-plan.json", base.canonical(plan))
    lock = output / ".frozen-execution.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
    client = None
    try:
        copy_tree(prior_dir / "market", output / "market")
        enrichment.copy_calls(prior_dir / "calls", output / "calls")
        for folder, sha, raw in (("baselines", plan["comparisonBaselineSha256"], prior_raw),
                                 ("previews", plan["previewSha256"], manifest_raw)):
            base.private_dir(output / "market" / folder)
            base.write_once(output / "market" / folder / (sha + ".json"), raw)
        prompt_root = output / "summary-run/prompts"
        base.private_dir(prompt_root)
        for p in sorted(context.PROMPTS.iterdir()):
            base.write_once(prompt_root / p.name, base.regular(p))
        client = context.legacy.MarketSummaryClient(output / "summary-run",
            transport or base.authenticated_transport(Path(args.key_file)), args.max_calls, prompt_root=prompt_root)
        def generate(value):
            r, data, frozen = value
            for folder, raw in (("contexts", base.canonical(data["marketContext"])),
                                ("frozen-inputs", base.canonical(frozen))):
                base.private_dir(output / "market" / folder)
                base.write_once(output / "market" / folder / (base.digest(raw) + ".json"), raw)
            result = context.generate_market_summary(client, data, 1)
            context.require(result["attempts"][0]["generationRequestDigest"] == r["requestSha256"], "frozen_first_call_changed")
            result_raw = base.canonical(result)
            base.write_once(output / "market/summaries" / (base.digest(result_raw) + ".json"), result_raw)
            record = {"roundId": r["roundId"], "date": r["date"], "edition": r["edition"],
                "cutoff": data["context"]["cutoff"], "newsResultSha256": data["context"]["newsResultSha256"],
                "marketSnapshot": data["marketSnapshot"], "marketSnapshotSha256": data["context"]["marketSnapshotSha256"],
                "marketContext": data["marketContext"], "context": data["context"], "contextSha256": data["contextSha256"],
                "summaryResult": result, "summaryResultSha256": base.digest(result_raw), "receipts": result["usage"],
                "frozenExecution": {**{k: plan[k] for k in ("previewSha256", "comparisonBaselineSha256", "executionAuthorizationRef")},
                                    "preparedRequestSha256": r["requestSha256"]}}
            base.private_dir(output / "completed-rounds")
            base.write_once(output / "completed-rounds" / (r["requestSha256"] + ".json"), base.canonical(record))
            print(base.canonical({"date": r["date"], "edition": r["edition"], "verification": result["verification"]["status"],
                "claims": len(result["claims"]), "paidReceipts": len(result["usage"])}).decode(), flush=True)
            return record
        # Fixed comparisons are independent; do not replace them with newly generated preceding rounds.
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            records = list(executor.map(generate, rows))
        original = {k: v for k, v in prior.items() if k != "marketEnrichment"}
        layer = {"schemaVersion": "zoop-briefing-market-enrichment-v1", "digestScheme": "raw-json-sha256-v1",
            "userInboxRef": manifest["userInboxRef"], "baselineBundleSha256": base.digest(base.canonical(original)),
            "comparisonBaselineSha256": plan["comparisonBaselineSha256"], "frozenPreviewSha256": plan["previewSha256"],
            "executionAuthorizationRef": args.user_inbox_ref, "rounds": records, "receipts": client.receipts()}
        enrichment.copy_calls(client.calls, output / "calls")
        bundle = {**original, "marketEnrichment": layer}
        base.write_once(output / "bundle-v2.json", base.canonical(bundle))
        receipts = client.receipts()
        return {"status": "COMPLETE", "rounds": len(records), "summaryPass": sum(r["summaryResult"]["verification"]["status"] == "PASS" for r in records),
            "newPaidCalls": len(client.new_calls), "newHttpCalls": 0, "knownUsage": all(r["usageKnown"] for r in receipts),
            "inputTokens": sum(r["inputTokens"] for r in receipts) if all(r["usageKnown"] for r in receipts) else None,
            "outputTokens": sum(r["outputTokens"] for r in receipts) if all(r["usageKnown"] for r in receipts) else None,
            "bundlePath": str(output / "bundle-v2.json"), "previewSha256": plan["previewSha256"]}
    finally:
        if client:
            raw = base.canonical(client.receipts()); base.write_once(output / ("accounting-" + base.digest(raw) + ".json"), raw)
        lock.unlink(missing_ok=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs", "market-bundle", "sources", "clocks", "output", "user-inbox-ref"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--key-file")
    p.add_argument("--max-calls", type=base.bounded(1, 56), default=44)
    p.add_argument("--workers", type=base.bounded(1, 3), default=3)
    p.add_argument("--execute-authorized-generation", action="store_true")
    return p


if __name__ == "__main__":
    print(base.canonical(run(parser().parse_args())).decode(), flush=True)
