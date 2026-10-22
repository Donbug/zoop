#!/usr/bin/env python3
"""Freeze source contexts and cached historical indicators over an unchanged replay.

No network/model transport is exposed. Java reconstructs public details and the
explicitly scoped extractive summary from already verified issue claims; this
script cannot submit arbitrary new summary prose as an AI-verified result.
"""

import argparse
import importlib.util
from pathlib import Path
import sys


def helper(name):
    spec = importlib.util.spec_from_file_location("_presentation_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


market = helper("briefing_market_data")
base = market.base
SCHEMA = "zoop-briefing-presentation-enrichment-v1"
SUMMARY_MODE = "verified_issue_claims_and_indicators_v1"


def source_context(source, body, maximum=1800):
    """Unicode code-point ranges are end-exclusive, including astral characters."""
    if base.digest(body.encode("utf-8")) != source.get("bodySha256") \
            or source.get("documentVersion") != "sha256-" + source["bodySha256"] \
            or source.get("offsetUnit") != "unicode_code_point":
        raise base.ReplayError("presentation_source_version_mismatch")
    start, end = source.get("start"), source.get("end")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(body) \
            or body[start:end] != source.get("quote") or end - start > 6000:
        raise base.ReplayError("presentation_quote_not_exact")
    span = max(maximum, end - start)
    left = max(0, start - (span - (end - start)) // 2)
    right = min(len(body), left + span)
    left = max(0, right - span)
    return {"text": body[left:right], "start": left, "end": right,
            "quoteStart": start, "quoteEnd": end, "offsetUnit": "unicode_code_point"}


def offline_only(_):
    raise base.ReplayError("presentation_network_forbidden_use_cached_market_receipts")


def run(args):
    baseline, output, cached = map(lambda p: Path(p).resolve(), (args.baseline, args.output, args.market_baseline))
    if output == baseline or baseline in output.parents or output == cached or cached in output.parents:
        raise base.ReplayError("presentation_separate_output_required")
    raw = base.regular(baseline / "bundle-v2.json")
    bundle = base.strict_load(raw)
    if bundle.get("presentationEnrichment") or "briefingRecovery" not in bundle:
        raise base.ReplayError("presentation_recovery_baseline_required")
    sources_raw = base.regular(Path(args.sources))
    if base.digest(sources_raw) != bundle["sourceFileSha256"] \
            or base.digest(base.regular(Path(args.clocks))) != bundle["clockFileSha256"]:
        raise base.ReplayError("presentation_source_or_clock_changed")
    rows = [base.strict_load(line) for line in sources_raw.splitlines() if line.strip()]
    bodies = {(r["documentId"], r["bodySha256"]): r["body"] for r in rows}
    base.private_dir(output)
    base.write_once(output / "base-presentation-bundle.json", raw)
    # Recovery validation retains its own base, editorial review and immutable calls.
    for name in ("base-bundle-v2.json", "grouped-issues.json", "editorial-review-holds.json"):
        if (baseline / name).exists():
            base.write_once(output / name, base.regular(baseline / name))
    base.private_dir(output / "calls")
    for path in sorted((baseline / "calls").glob("*.json")):
        base.write_once(output / "calls" / path.name, base.regular(path))
    for folder in ("raw", "providers"):
        base.private_dir(output / "market" / folder)
        for path in sorted((cached / "market" / folder).glob("*")):
            if path.is_file():
                base.write_once(output / "market" / folder / path.name, base.regular(path))
    receipts, calls = market.fetch_receipts(output, offline_only)
    if calls:
        raise base.ReplayError("presentation_must_not_fetch")
    original = {r["roundId"]: r for r in bundle["rounds"]}
    records, details_count, evidence_count = [], 0, 0
    for effective in bundle["briefingRecovery"]["rounds"]:
        if effective["status"] != "SELECTED":
            continue
        definition = original[effective["roundId"]]
        if effective["result"]["verification"]["status"] != "PASS" \
                or base.digest(base.canonical(effective["result"])) != effective["resultSha256"]:
            raise base.ReplayError("presentation_news_verification_required")
        detail = {}
        for selected in effective["selected"]:
            contexts = []
            for source in selected["sources"]:
                body = bodies.get((source["documentId"], source["bodySha256"]))
                if body is None:
                    raise base.ReplayError("presentation_body_missing")
                contexts.append({"id": source["evidenceId"], "bodyContext": source_context(source, body)})
            detail[selected["issueId"]] = {"evidence": contexts}
            details_count += 1
            evidence_count += len(contexts)
        snapshot = market.snapshot(definition, receipts, output)
        sha = base.digest(base.canonical(snapshot))
        base.private_dir(output / "market/snapshots")
        base.write_once(output / "market/snapshots" / (sha + ".json"), base.canonical(snapshot))
        context = {"roundId": effective["roundId"], "date": effective["date"], "edition": effective["edition"],
                   "cutoff": definition["window"]["to"], "newsResultSha256": effective["resultSha256"],
                   "marketSnapshotSha256": sha, "userInboxRef": args.user_inbox_ref}
        market_record = {**{k: context[k] for k in ("roundId", "date", "edition", "cutoff", "newsResultSha256")},
                         "marketSnapshot": snapshot, "marketSnapshotSha256": sha, "context": context,
                         "contextSha256": base.digest(base.canonical(context)), "summaryResult": None,
                         "summaryResultSha256": None, "receipts": []}
        records.append({"roundId": effective["roundId"], "date": effective["date"], "edition": effective["edition"],
                        "baseResultSha256": effective["resultSha256"], "itemDetails": detail,
                        "marketEnrichment": market_record, "summaryMode": SUMMARY_MODE})
    layer = {"schemaVersion": SCHEMA, "runId": args.run_id, "userInboxRef": args.user_inbox_ref,
             "baseBundleSha256": base.digest(raw), "rounds": records, "receipts": [],
             "maximumPaidCallsIncludingPrior": 400}
    final = {**bundle, "presentationEnrichment": layer}
    base.save_json(output / "bundle-v2.json", final)
    proof = {"schemaVersion": SCHEMA, "rounds": len(records), "items": details_count,
             "evidenceContexts": evidence_count, "newPaidCalls": 0, "newHttpCalls": 0,
             "summaryMode": SUMMARY_MODE, "baseBundleSha256": base.digest(raw),
             "bundleSha256": base.digest(base.canonical(final)), "bundlePath": str(output / "bundle-v2.json")}
    base.save_json(output / "presentation-proof.json", proof)
    return proof


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ("baseline", "output", "market-baseline", "sources", "clocks", "user-inbox-ref", "run-id"):
        p.add_argument("--" + flag, required=True)
    return p


if __name__ == "__main__":
    try:
        print(base.canonical(run(parser().parse_args())).decode())
    except (base.ReplayError, ValueError) as error:
        print(base.canonical({"status": "STOPPED", "reason": str(error)}).decode(), file=sys.stderr)
        raise SystemExit(2)
