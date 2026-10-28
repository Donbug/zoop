#!/usr/bin/env python3
"""Persist authored issue/clock/provider recordings for the actual DB/HTTP integration gate.

This helper never loads credentials or sends network requests. The test transport
authors every selection, generation and verification response.
"""

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def create(directory, unknown=False, selection_mode="normal"):
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
            archive["receipts"].append(receipt)
            archive["held"] = [{"articleId": document["documentId"], "requestDigest": digest,
                "stage": stage, "usageKnown": False, "reason": "operator_held_unresolved_paid_request"}]
            fixture.archive_path.write_bytes(module.base.canonical(archive))
        if selection_mode not in {"normal", "held", "corrected", "unresolved", "unresolved-correction"} or (unknown and selection_mode != "normal"):
            raise ValueError("Unknown authored selection fixture mode")
        class AuthoredSelectionFailure(module.fixtures.AuthoredTransport):
            def __call__(self, raw):
                status, response = super().__call__(raw)
                request = module.base.strict_load(raw)
                if request["text"]["format"]["name"] != module.fixtures.grouped.SELECTION_STAGE:
                    return status, response
                data = module.base.strict_load(request["input"])
                if not any(issue["issueId"] == "stable-authored-issue-0" for issue in data["issues"]):
                    return status, response
                if selection_mode == "corrected" and "selectionCorrection" in data:
                    return status, response
                provider = module.base.strict_load(response)
                part = provider["output"][0]["content"][0]
                reply = module.base.strict_load(part["text"])
                # The answer obeys JSON schema, but contradicts its own chosen issue's eligibility.
                reply["assessments"]["stable-authored-issue-0"].update(status="HOLD", importance=1)
                part["text"] = module.base.canonical(reply).decode()
                return status, module.base.canonical(provider)
        transport = module.fixtures.AuthoredTransport() if selection_mode == "normal" else AuthoredSelectionFailure()
        if selection_mode in {"unresolved", "unresolved-correction"}:
            first = module.UnknownStageTransport(module.fixtures.grouped.SELECTION_STAGE) if selection_mode == "unresolved" else module.UnknownCorrectionTransport()
            try:
                fixture.execute(first)
            except module.base.ReplayError:
                pass
            else:
                raise AssertionError("Authored unknown request unexpectedly completed")
            transport = module.fixtures.AuthoredTransport()
            result = fixture.execute(transport, hold_unresolved=True)
        else:
            result = fixture.execute(transport)
        expected = 13 if unknown or selection_mode in {"held", "unresolved", "unresolved-correction"} else 14
        expected_calls = expected * 3 + (2 if selection_mode == "held" else 1 if selection_mode == "corrected" else 0)
        if result["selectedRounds"] != expected or result["selectedIssues"] != expected or len(transport.requests) != expected_calls:
            raise AssertionError("Authored grouped fixture did not produce all fourteen successful rounds")
        return {"sources": str(fixture.clock.sources), "clocks": str(fixture.clock.clocks),
                "archive": str(fixture.archive_path), "bundle": str(fixture.output / "bundle-v2.json"),
                "selectedRounds": result["selectedRounds"], "selectedIssues": result["selectedIssues"],
                "authoredTransportCalls": len(transport.requests), "unknownGroupingCalls": int(unknown),
                "realHttpCalls": 0, "realPaidCalls": 0}
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    mode = "unresolved-correction" if "--unresolved-correction" in sys.argv else "unresolved" if "--unresolved" in sys.argv else "held" if "--held-selection" in sys.argv else "corrected" if "--corrected-selection" in sys.argv else "normal"
    print(create(Path(sys.argv[1]), "--unknown" in sys.argv, mode))
