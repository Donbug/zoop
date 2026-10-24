#!/usr/bin/env python3
"""Fresh synthetic OPERATOR world WITH REAL IMPACT STATES for the handoff service tests and smoke. Run with the interpreter of `ai/pipeline/.venv`, never the service's.

The world is the pipeline's own `rich` impact world (`scripts/graph_handoff_smoke.py` `impact_export`): on the supply edge a verified positive, a verifier-rejected (target
contradicted), a verified negative of the other S3 job and a verified-undetermined (insufficient target) row; on the factory edge a no-evidence row and a precheck-rejected
technical reject. One handoff (`handoff-impacts-1`) is frozen and exported with the INSTALLED `zoop-ai-handoff` (authored replay only; no model, provider or network call).
The expected rows are the pipeline smoke's hand-written ones (`expected(world)["impacts"]`). The pipeline's own one-rule-broken negative bundles (digest refreshed) and its
valid Unicode-length bundle are carried along so the service can be shown to refuse exactly what the producer's validator refuses.

usage: build_impact_world.py <pipeline project dir> <empty output dir>   (prints one JSON document in the shape of `build_handoff_world.py`)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PIPELINE = Path(sys.argv[1]).resolve()
ROOT = Path(sys.argv[2]).resolve()
sys.path[:0] = [str(PIPELINE)]

from scripts.graph_handoff_smoke import IMPACT_HANDOFF, PRIVATE, expected, impact_export, impact_mutations, unicode_impact_bundle  # noqa: E402
from zoop_ai_pipeline.handoff_contracts import content_digest, validate_bundle  # noqa: E402
from zoop_ai_pipeline.ingestion_contracts import byte_hash, canonical  # noqa: E402


def main() -> dict:
    world, out = impact_export(ROOT)
    validate_bundle(out["bundle"])
    raw = canonical(out["bundle"]).encode("utf-8")
    receipt = out["receipt"]
    assert byte_hash(raw) == receipt["bundleDigest"] and len(raw) == receipt["bundleBytes"], receipt
    want = expected(world)
    assert out["bundle"]["impacts"] == want["impacts"] and out["bundle"]["counts"] == want["counts"]
    described = {IMPACT_HANDOFF: {"manifestDigest": receipt["manifestDigest"], "bundleDigest": receipt["bundleDigest"], "contentDigest": receipt["contentDigest"],
                                  "bundleBytes": receipt["bundleBytes"], "sourceJobs": sorted(s["relation"]["jobId"] for s in out["bundle"]["sources"]),
                                  "upstreamJobs": sorted(s["upstream"]["jobId"] for s in out["bundle"]["sources"])}}
    negatives = {}
    for name, (change, at, refresh) in impact_mutations().items():
        broken = json.loads(json.dumps(out["bundle"]))
        change(broken)
        if refresh:
            broken["digests"]["content"] = content_digest(broken)
        negatives[name] = {"bundle": broken, "validatorLocation": at, "digestRefreshed": refresh}
    return {
        "root": str(ROOT), "relation": str(ROOT / "relation"), "extraction": str(ROOT / "extraction"), "ingestion": str(ROOT / "ingestion"),
        "sources": str(world.kit.registry_path), "canonical": str(ROOT / "canonical.json"), "decisions": str(ROOT / "decisions.json"),
        "bindings": str(ROOT / "bindings.json"), "handoffState": str(ROOT / "handoff"), "handoffs": described, "counts": want["counts"],
        "evidenceIds": want["evidence"], "issueIds": sorted(want["issues"]), "relationEdges": sorted([*key, ids] for key, ids in want["relations"].items()),
        "exclusions": want["exclusions"], "private": list(PRIVATE), "impacts": want["impacts"], "impactNegatives": negatives,
        "impactUnicode": unicode_impact_bundle(out["bundle"]),
        "articleIds": sorted(ref["documentId"] for ref in world.refs.values())}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
