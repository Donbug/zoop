#!/usr/bin/env python3
"""Fresh synthetic OPERATOR world WITH a pinned issue summary, for the handoff service tests and smoke. Run with the interpreter of `ai/pipeline/.venv`.

It is the pipeline's own hand-reviewed summary world (`scripts/graph_handoff_smoke.py::summary_world`): actual ingestion, two READY S2 jobs, two S3 jobs, authored replay,
and ONE handoff exported through the INSTALLED `zoop-ai-handoff` over operator decisions that pin the immutable ready result of an authored-replay `zoop-ai-issue-summary` job:

  * `available`      handoff `handoff-summary-1`: the supply issue (two original mentions in two articles, the second one in its OWN source with its OWN grant) carries an AVAILABLE
                     authored-replay summary of ONE verified claim that cites only the first article; the second article is read (it is part of the basis) but uncited. The factory
                     issue carries an operator HOLD on its period, so its summary is the deterministic `temporal-review-pending` (no job, no source);
  * `verifier-hold`  handoff `handoff-summary-withheld-1`: the independent verifier found the claim insufficient, so the supply issue carries the job-coded
                     `unavailable/verifier-hold` with its pinned `source`, and the factory issue (no verdict, no pin) is `not-requested`.

The review, the replay answers and the claims are SYNTHETIC authored test data, never a real model's output. The pipeline smoke already checks the export against hand-written
expectations; this script also hands those expectations (per public issue: status, code, claims, evidence union, kinds, pinned or not) to the service tests, so they never derive
an expectation from the service. Nothing here calls a model, a provider or the network.

usage: build_summary_handoff_world.py <pipeline project dir> <empty output dir> available|verifier-hold   (prints one JSON document, same shape as build_handoff_world.py)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PIPELINE = Path(sys.argv[1]).resolve()
ROOT = Path(sys.argv[2]).resolve()
OUTCOME = sys.argv[3]
sys.path[:0] = [str(PIPELINE)]

from scripts.graph_handoff_smoke import (FACTORY, PRIVATE, SUMMARY_CLAIMS, SUMMARY_HANDOFF, SUMMARY_WITHHELD_HANDOFF, SUPPLY, expected_summaries_of,  # noqa: E402
                                         summary_world)
from zoop_ai_pipeline.handoff_contracts import validate_bundle  # noqa: E402
from zoop_ai_pipeline.ingestion_contracts import byte_hash, canonical  # noqa: E402


def main() -> dict:
    assert OUTCOME in ("available", "verifier-hold"), OUTCOME
    handoff = SUMMARY_HANDOFF if OUTCOME == "available" else SUMMARY_WITHHELD_HANDOFF
    world, exported = summary_world(ROOT, handoff, OUTCOME)
    bundle, receipt = exported["bundle"], exported["receipt"]
    validate_bundle(bundle)
    raw = canonical(bundle).encode("utf-8")
    assert byte_hash(raw) == receipt["bundleDigest"] and len(raw) == receipt["bundleBytes"], receipt
    summary = world.summary
    described = {handoff: {"manifestDigest": receipt["manifestDigest"], "bundleDigest": receipt["bundleDigest"], "contentDigest": receipt["contentDigest"],
                           "bundleBytes": receipt["bundleBytes"], "sourceJobs": sorted(s["relation"]["jobId"] for s in bundle["sources"]),
                           "upstreamJobs": sorted(s["upstream"]["jobId"] for s in bundle["sources"])}}
    return {
        "root": str(ROOT), "relation": str(ROOT / "relation"), "extraction": str(ROOT / "extraction"), "ingestion": str(ROOT / "ingestion"),
        "sources": str(world.kit.registry_path), "canonical": str(ROOT / "canonical.json"), "decisions": str(ROOT / "decisions.json"),
        "bindings": str(ROOT / "bindings.json"), "handoffState": str(summary.operator.state), "summaries": str(summary.ledger), "handoffs": described,
        "counts": bundle["counts"], "evidenceIds": [e["id"] for e in bundle["evidence"]], "issueIds": sorted(i["id"] for i in bundle["issues"]),
        "relationEdges": sorted([r["type"], r["source"], r["target"], r["evidenceIds"]] for r in bundle["relations"]),
        "exclusions": bundle["exclusions"]["counts"], "private": list(PRIVATE), "articleIds": sorted(a["articleId"] for a in bundle["articles"]),
        "expect": {"outcome": OUTCOME, "handoffId": handoff, "summaries": expected_summaries_of(world, OUTCOME), "pin": summary.pin, "job": summary.job,
                   "supply": SUPPLY, "factory": FACTORY, "claimTexts": [text for text, _, _ in SUMMARY_CLAIMS],
                   # the document the supply summary READ but no claim cites: its own source id, document id and quote evidence id (None if the world has none)
                   "uncited": dict(vars(summary.uncited)) if getattr(summary, "uncited", None) is not None else None}}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
