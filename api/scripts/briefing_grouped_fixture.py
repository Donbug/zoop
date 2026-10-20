#!/usr/bin/env python3
"""Persist authored issue/clock/provider recordings for the actual DB/HTTP integration gate.

This helper never loads credentials or sends network requests. The test transport
authors every selection, generation and verification response.
"""

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def create(directory):
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
        fixture.prepare()
        transport = module.fixtures.AuthoredTransport()
        result = fixture.execute(transport)
        if result["selectedRounds"] != 14 or result["selectedIssues"] != 14 or len(transport.requests) != 42:
            raise AssertionError("Authored grouped fixture did not produce all fourteen successful rounds")
        return {"sources": str(fixture.clock.sources), "clocks": str(fixture.clock.clocks),
                "archive": str(fixture.archive_path), "bundle": str(fixture.output / "bundle-v2.json"),
                "selectedRounds": result["selectedRounds"], "selectedIssues": result["selectedIssues"],
                "authoredTransportCalls": len(transport.requests), "realHttpCalls": 0, "realPaidCalls": 0}
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    print(create(Path(sys.argv[1])))
