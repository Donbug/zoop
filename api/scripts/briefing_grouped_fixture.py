#!/usr/bin/env python3
"""Persist authored issue/clock/provider recordings for the actual DB/HTTP integration gate.

This helper never loads credentials or sends network requests. The test transport
authors every selection, generation and verification response.
"""

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def create(directory, unknown=False):
    spec = importlib.util.spec_from_file_location("grouped_db_fixture_tests", ROOT / "scripts/tests/test_briefing_grouped_run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = module.GroupedRunTest()
    fixture.setUp()
    try:
        directory = directory.resolve()
        module.base.private_dir(directory)
        fixture.root = directory
        fixture.archive_path = directory / "archive.json"
        fixture.output = directory / "output"
        fixture.clock.root = directory
        fixture.clock.sources = directory / "sources.jsonl"
        fixture.clock.clocks = directory / "clocks.json"
        fixture.clock.html = directory / "html"
        fixture.clock.html.mkdir()
        archive = fixture.prepare()
        if unknown:
            withheld = archive["issues"].pop(0)
            document = next(d for d in archive["documents"] if d["documentId"] == withheld["mentions"][0]["articleId"])
            stage = "issue_extraction"
            request = {"model": module.base.MODEL, "store": False, "max_output_tokens": 1000,
                "instructions": "Authored unanswered extraction; no actual provider is contacted.",
                "input": module.base.canonical({"documents": [{"article": {"article_id": document["documentId"],
                    "body": document["body"]}, "article_version": document["documentVersion"]}]}).decode(),
                "text": {"format": {"name": stage, "schema": {"type": "object"}}}}
            raw = module.base.canonical(request); digest = module.base.digest(raw)
            calls = directory / "calls"; module.base.private_dir(calls)
            module.base.write_once(calls / (digest + ".request.json"), raw)
            reservation = {"stage": stage, "requestDigest": digest, "model": module.base.MODEL,
                "createdAt": "2026-10-20T01:00:00Z", "reservedInputTokenBound": 2 * len(raw) + 4096,
                "maxOutputTokens": 1000, "promptSha256": module.base.digest(request["instructions"].encode()),
                "schemaSha256": module.base.digest(module.base.canonical(request["text"]["format"]["schema"]))}
            module.base.save_json(calls / (digest + ".pending.json"), reservation)
            receipt = {"stage": stage, "model": module.base.MODEL, "requestDigest": digest,
                "responseId": None, "status": "unknown", "usageKnown": False, "inputTokens": None,
                "outputTokens": None, "actualCost": None, "actualCostKnown": False}
            archive["receipts"] = [receipt]
            archive["held"] = [{"articleId": document["documentId"], "requestDigest": digest,
                "stage": stage, "usageKnown": False, "reason": "operator_held_unresolved_paid_request"}]
            fixture.archive_path.write_bytes(module.base.canonical(archive))
        transport = module.fixtures.AuthoredTransport()
        result = fixture.execute(transport)
        expected = 13 if unknown else 14
        if result["selectedRounds"] != expected or result["selectedIssues"] != expected or len(transport.requests) != expected * 3:
            raise AssertionError("Authored grouped fixture did not produce all fourteen successful rounds")
        return {"sources": str(fixture.clock.sources), "clocks": str(fixture.clock.clocks),
                "archive": str(fixture.archive_path), "bundle": str(fixture.output / "bundle-v2.json"),
                "selectedRounds": result["selectedRounds"], "selectedIssues": result["selectedIssues"],
                "authoredTransportCalls": len(transport.requests), "unknownGroupingCalls": int(unknown),
                "realHttpCalls": 0, "realPaidCalls": 0}
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    print(create(Path(sys.argv[1]), "--unknown" in sys.argv))
