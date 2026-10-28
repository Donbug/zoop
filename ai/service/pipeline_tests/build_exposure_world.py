#!/usr/bin/env python3
"""Build the existing authored exposure world with the pipeline interpreter; no production state or model."""
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from scripts.handoff_exposure_smoke import (FULL, LEAN, UNCITED, build_main, doc_change, expect_a2, expect_retraction, source_change, relation_change, want)
from scripts.graph_handoff_smoke import PRIVATE

ctx = build_main(Path(sys.argv[2]))
root, world, model = ctx.root, ctx.world, ctx.m
bundle = ctx.exports[FULL]["bundle"]
requests = {"source": source_change(UNCITED), "document": doc_change(world.refs["a2"]),
            "grant": {"kind": "grant", "grantId": model.grants["uncited"]["grantId"], "revision": None},
            "relation": relation_change("rel-a", model.rc["A1"]), "empty": doc_change(world.extra)}
wants = {name: expect_a2(model) for name in ("source", "document", "grant")}
wants["relation"] = expect_retraction(model, "A1")
wants["empty"] = {hid: want(model, bound=False) for hid in (FULL, LEAN)}
print(json.dumps({"root": str(root), "relation": str(root / "relation"), "extraction": str(root / "extraction"), "ingestion": str(root / "ingestion"),
                  "sources": str(world.kit.registry_path), "canonical": str(root / "canonical.json"), "decisions": str(root / "decisions.json"),
                  "bindings": str(root / "bindings.json"), "handoffState": str(ctx.state),
                  "handoffs": {hid: out["receipt"] for hid, out in ctx.exports.items()}, "counts": bundle["counts"],
                  "evidenceIds": sorted(e["id"] for e in bundle["evidence"]), "issueIds": sorted(i["id"] for i in bundle["issues"]),
                  "relationEdges": [], "exclusions": bundle["exclusions"]["counts"], "private": list(PRIVATE),
                  "articleIds": sorted(a["articleId"] for a in bundle["articles"]),
                  "expect": {"requests": requests, "handoffs": wants, "full": FULL, "source": UNCITED}}))
