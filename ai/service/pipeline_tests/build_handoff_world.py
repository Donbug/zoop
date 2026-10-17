#!/usr/bin/env python3
"""Fresh synthetic OPERATOR world for the handoff service tests and smoke. Run with the interpreter of `ai/pipeline/.venv`, never the service's.

The world is the pipeline's own authored world (`scripts/graph_handoff_smoke.py`): actual ingestion of three authored articles, two READY S2 extraction jobs (two
events, one frozen snapshot event with two documents) and TWO S3 relation jobs, authored replay only. The operator documents (canonical registry, public decisions,
app document bindings) are written the way the pipeline's smoke writes them, and two handoffs (`handoff-1`, `handoff-2`) are frozen with the INSTALLED
`zoop-ai-handoff freeze` subprocess, then exported once with the installed `export` as the oracle. Nothing here calls a model, a provider or the network (every
CLI subprocess runs under the pipeline's socket audit hook). The service tests then talk to the service only; they read this world's directories only to prove
the service left them alone.

usage: build_handoff_world.py <pipeline project dir> <empty output dir>   (prints one JSON document describing the world)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PIPELINE = Path(sys.argv[1]).resolve()
ROOT = Path(sys.argv[2]).resolve()
sys.path[:0] = [str(PIPELINE)]

from scripts.graph_handoff_smoke import (PRIVATE, Operator, build_world, check_export, expected, file_hashes, manifest_doc, write_operator)  # noqa: E402
from zoop_ai_pipeline.handoff_contracts import validate_bundle  # noqa: E402
from zoop_ai_pipeline.ingestion_contracts import byte_hash, canonical  # noqa: E402

HANDOFFS = ("handoff-1", "handoff-2")


def main() -> dict:
    world = build_world(ROOT)
    write_operator(world)
    operator = Operator(world)
    files = file_hashes(ROOT)
    described: dict[str, dict] = {}
    for handoff_id in HANDOFFS:
        frozen = operator.cli("freeze", manifest_doc(world, handoff_id, files))
        assert frozen["state"] == "ready" and frozen["usage"] == {"providerCalls": 0, "modelCalls": 0}, frozen
        exported = operator.cli("export", operator.sel(handoff_id))
        check_export(world, exported)
        validate_bundle(exported["bundle"])
        raw = canonical(exported["bundle"]).encode("utf-8")
        receipt = frozen["receipt"]
        assert byte_hash(raw) == receipt["bundleDigest"] and len(raw) == receipt["bundleBytes"], receipt
        described[handoff_id] = {"manifestDigest": receipt["manifestDigest"], "bundleDigest": receipt["bundleDigest"], "contentDigest": receipt["contentDigest"],
                                 "bundleBytes": receipt["bundleBytes"], "sourceJobs": sorted(s["relation"]["jobId"] for s in exported["bundle"]["sources"]),
                                 "upstreamJobs": sorted(s["upstream"]["jobId"] for s in exported["bundle"]["sources"])}
    want = expected(world)
    return {
        "root": str(ROOT), "relation": str(ROOT / "relation"), "extraction": str(ROOT / "extraction"), "ingestion": str(ROOT / "ingestion"),
        "sources": str(world.kit.registry_path), "canonical": str(ROOT / "canonical.json"), "decisions": str(ROOT / "decisions.json"),
        "bindings": str(ROOT / "bindings.json"), "handoffState": str(operator.state), "handoffs": described, "counts": want["counts"],
        "evidenceIds": want["evidence"], "issueIds": sorted(want["issues"]), "relationEdges": sorted([*key, ids] for key, ids in want["relations"].items()),
        "exclusions": want["exclusions"], "private": list(PRIVATE),
        "articleIds": sorted(ref["documentId"] for ref in world.refs.values())}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
