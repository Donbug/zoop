#!/usr/bin/env python3
"""Fresh synthetic OPERATOR world WITH reviewed operator field verdicts, for the handoff service tests and smoke. Run with the interpreter of `ai/pipeline/.venv`.

It is the pipeline's own hand-reviewed world (`scripts/graph_handoff_smoke.py::verdict_export`): actual ingestion, two READY S2 jobs, two S3 jobs, authored replay, and
ONE handoff (`handoff-verdicts-1`) frozen and exported through the INSTALLED `zoop-ai-handoff` over operator decisions that carry per-field `eventTime`/`period`
verdicts (supply: REJECT on the representative's event time, factory: HOLD on its only mention's period, plus verdicts that withhold nothing). The review is SYNTHETIC
test data authored in the pipeline smoke, never a real review. `verdict_export` already checks the export against hand-written expectations; this script also hands those
expectations (verdicts, public headline values, original mentions, withheld fields) to the service tests, so they never derive an expectation from the service.
Nothing here calls a model, a provider or the network.

usage: build_verdict_handoff_world.py <pipeline project dir> <empty output dir>   (prints one JSON document describing the world, same shape as build_handoff_world.py)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PIPELINE = Path(sys.argv[1]).resolve()
ROOT = Path(sys.argv[2]).resolve()
sys.path[:0] = [str(PIPELINE)]

from scripts.graph_handoff_smoke import (PRIVATE, VERDICT_HANDOFF, VERDICT_WITHHELD, Operator, expected_headlines, expected_mentions, expected_verdicts,  # noqa: E402
                                         verdict_cases, verdict_export)
from zoop_ai_pipeline.handoff_contracts import validate_bundle  # noqa: E402
from zoop_ai_pipeline.ingestion_contracts import byte_hash, canonical  # noqa: E402


def main() -> dict:
    world, exported = verdict_export(ROOT)
    bundle, receipt = exported["bundle"], exported["receipt"]
    validate_bundle(bundle)
    raw = canonical(bundle).encode("utf-8")
    assert byte_hash(raw) == receipt["bundleDigest"] and len(raw) == receipt["bundleBytes"], receipt
    operator = Operator(world)
    described = {VERDICT_HANDOFF: {"manifestDigest": receipt["manifestDigest"], "bundleDigest": receipt["bundleDigest"], "contentDigest": receipt["contentDigest"],
                                   "bundleBytes": receipt["bundleBytes"], "sourceJobs": sorted(s["relation"]["jobId"] for s in bundle["sources"]),
                                   "upstreamJobs": sorted(s["upstream"]["jobId"] for s in bundle["sources"])}}
    headlines = expected_headlines(world, VERDICT_WITHHELD)
    return {
        "root": str(ROOT), "relation": str(ROOT / "relation"), "extraction": str(ROOT / "extraction"), "ingestion": str(ROOT / "ingestion"),
        "sources": str(world.kit.registry_path), "canonical": str(ROOT / "canonical.json"), "decisions": str(ROOT / "decisions.json"),
        "bindings": str(ROOT / "bindings.json"), "handoffState": str(operator.state), "handoffs": described, "counts": bundle["counts"],
        "evidenceIds": [e["id"] for e in bundle["evidence"]], "issueIds": sorted(i["id"] for i in bundle["issues"]),
        "relationEdges": sorted([r["type"], r["source"], r["target"], r["evidenceIds"]] for r in bundle["relations"]),
        "exclusions": bundle["exclusions"]["counts"], "private": list(PRIVATE), "articleIds": sorted(a["articleId"] for a in bundle["articles"]),
        "expect": {"verdicts": expected_verdicts(world, verdict_cases(world)), "headlines": {issue: list(values) for issue, values in headlines.items()},
                   "mentions": expected_mentions(world), "withheld": VERDICT_WITHHELD}}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
