#!/usr/bin/env python3
"""Create explicitly authored offline recordings for the real market-context DB/HTTP gate."""

import contextlib
from datetime import datetime, timedelta
import importlib.util
import io
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def create(directory):
    legacy = load("context_fixture_news", "scripts/tests/test_briefing_round_simulation.py")
    market = load("context_fixture_market", "scripts/tests/test_briefing_market_data.py")
    authored = load("context_fixture_summary", "scripts/tests/test_briefing_market_context.py")
    enrichment = load("context_fixture_enrichment", "scripts/briefing_market_enrichment.py")
    fixture = legacy.RoundSimulationTest()
    fixture.setUp()
    try:
        directory = directory.resolve()
        enrichment.base.private_dir(directory)
        fixture.sources, fixture.clocks = directory / "sources.jsonl", directory / "clocks.json"
        fixture.html = directory / "html"; fixture.html.mkdir()
        fixture.output = directory / "baseline"
        rows = []
        for index, spec in enumerate(legacy.sim.windows()):
            stamp = legacy.sim.aware(spec["window"]["to"]) - timedelta(minutes=10)
            rows.append(legacy.source("authored-selected-" + str(index), stamp.isoformat()))
        extra = legacy.source("z-unselected-industry", "2026-10-02T08:30:00+09:00",
            "별도 시험기업은 반도체 공급 계획을 검토 중이며 계약은 아직 확정하지 않았습니다. " * 12)
        extra["companyAssociations"] = [{"companyName": "별도 시험기업"}]
        rows.append(extra)
        fixture.prepare(rows)
        with contextlib.redirect_stdout(io.StringIO()):
            legacy.sim.run(fixture.args(True), legacy.AuthoredTransport())
        calendar = {"schemaVersion": "zoop-market-session-calendar-v1", "sessions": []}
        # These are synthetic sessions, including weekends; this is never an actual KRX calendar.
        for index in range(10):
            date = (datetime(2026, 10, 1) + timedelta(days=index)).date()
            calendar["sessions"].append({"date": str(date), "tradingDay": True,
                "nextTradingDate": str(date + timedelta(days=1)), "closeAt": str(date) + "T15:30:00+09:00",
                "availableAt": "2026-09-30T00:00:00+09:00", "sourceRef": "https://example.invalid/authored-session-calendar"})
        calendar_path = directory / "calendar.json"
        enrichment.base.save_json(calendar_path, calendar)
        values = ["--baseline", str(fixture.output), "--output", str(directory / "enriched"),
                  "--sources", str(fixture.sources), "--clocks", str(fixture.clocks),
                  "--user-inbox-ref", "inbox/authored-market-context.md", "--include-market-context",
                  "--session-calendar", str(calendar_path), "--execute-authorized-enrichment"]
        transport = market.AuthoredMarketTransport()
        def provider_shape(url):
            status, raw = transport(url)
            value = enrichment.base.strict_load(raw)
            if isinstance(value, dict) and "chart" in value:
                for item in value["chart"]["result"]:
                    quotes = item["indicators"]["quote"][0]
                    quotes["close"] = [float(number) if number is not None else None for number in quotes["close"]]
                raw = enrichment.base.canonical(value)
            return status, raw
        with contextlib.redirect_stdout(io.StringIO()):
            result = enrichment.run(enrichment.parser().parse_args(values), provider_shape, authored.ContextTransport())
        calls = result.pop("newPaidCalls"); result.pop("newHttpCalls")
        return {"sources": str(fixture.sources), "clocks": str(fixture.clocks), **result,
                "authoredTransportCalls": calls, "realHttpCalls": 0, "realPaidCalls": 0}
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    print(create(Path(sys.argv[1])))
