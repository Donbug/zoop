#!/usr/bin/env python3
"""Authored two-version outlook ledger; every provider/model response is local fake transport."""
import contextlib
import importlib.util
import io
from datetime import date, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def create(directory, tampered_history=False, quality=False, continuation=False, role=False, structure=False, grounded=False):
    role = role or structure or grounded
    recovery = load("history_authored_recovery", ROOT / "api/scripts/briefing_recovery_fixture.py")
    presentation = load("history_authored_presentation", ROOT / "scripts/briefing_presentation_enrichment.py")
    market = load("history_authored_market", ROOT / "scripts/tests/test_briefing_market_data.py")
    authored = load("history_authored_summary", ROOT / "scripts/tests/test_briefing_market_context.py")
    runner = load("history_authored_runner", ROOT / "scripts/briefing_market_outlook_run.py")
    base = presentation.base
    directory = directory.resolve()
    with contextlib.redirect_stdout(io.StringIO()):
        recovery.create(directory)
        cache = directory / "market-cache"
        def feed(url):
            if "FX_USDKRW" in url:
                return 200, market.fx_bytes()
            symbol = "^KS11" if "%5EKS11" in url else "^KQ11"
            days = [(str(date(2026, 10, 1) + timedelta(days=i)), 2500 + i * 10) for i in range(9)]
            return 200, market.index_bytes(symbol, days)
        presentation.market.fetch_receipts(cache, feed)
        initial = directory / "presentation"
        presentation.run(presentation.parser().parse_args([
            "--baseline", str(directory / "output"), "--output", str(initial), "--market-baseline", str(cache),
            "--sources", str(directory / "sources.jsonl"), "--clocks", str(directory / "clocks.json"),
            "--user-inbox-ref", "inbox/authored-recovery.md", "--run-id", "authored-presentation"]))
        calendar = {"schemaVersion": "zoop-market-session-calendar-v1", "sessions": []}
        for i in range(10):
            day = date(2026, 10, 1) + timedelta(days=i)
            calendar["sessions"].append({"date": str(day), "tradingDay": True,
                "nextTradingDate": str(day + timedelta(days=1)), "closeAt": str(day) + "T15:30:00+09:00",
                "availableAt": "2026-09-30T00:00:00+09:00", "sourceRef": "https://example.invalid/authored-calendar"})
        calendar_path = directory / "calendar.json"
        base.save_json(calendar_path, calendar)
        def run(version, baseline, output, transport):
            runner.VERSION = version
            runner.context.PROMPTS = ROOT / "api/src/main/resources/briefing/prompts" / version
            arguments = [
                "--baseline", str(baseline), "--sources", str(directory / "sources.jsonl"),
                "--clocks", str(directory / "clocks.json"), "--session-calendar", str(calendar_path),
                "--output", str(output), "--user-inbox-ref", "inbox/authored-recovery.md",
                "--run-id", "authored-" + version.replace(".", "_"), "--max-calls", "400", "--max-repairs", "0",
                "--execute-authorized-generation",
                "--round", "2026-10-07-morning", "--round", "2026-10-07-evening"]
            if version not in runner.context.ROLE_VERSIONS:
                arguments += ["--round", "2026-10-08-morning"]
            arguments += ["--round", "2026-10-08-evening"]
            args = runner.parser().parse_args(arguments)
            return runner.run(args, transport)
        def withheld(stage, answer):
            if stage == "market_summary_verification":
                for value in answer["checks"].values():
                    value.update(verdict="UNCERTAIN", reason="Authored withheld first execution")
        original_context = runner.context.build_context
        if tampered_history:
            def altered_context(*args, **kwargs):
                value = original_context(*args, **kwargs)
                value["documents"][0]["sources"][0]["quote"] += " [authored tamper]"
                return value
            runner.context.build_context = altered_context
        first = run("market-context-v2.1-outlook", initial, directory / "first", authored.ContextTransport(mutate=withheld))
        runner.context.build_context = original_context
        def quality_answer(stage, answer):
            if stage == "market_summary_generation":
                for claim in answer["claims"]:
                    if claim["kind"] == "forecast":
                        claim.update(conditions=[], direction="uncertain", text="합성 근거가 엇갈려 잠정 방향은 불확실합니다.")
            else:
                for check in answer["checks"].values():
                    check.update({flag: True for flag in (runner.context.ROLE_FLAGS if role else runner.context.QUALITY_FLAGS)})
            if role and stage == "market_summary_generation":
                slots, optional = {}, []
                for claim in answer["claims"]:
                    kind = claim["kind"]
                    if kind in {"forecast", "forecast_update", "result_comparison"} and kind not in slots:
                        slots[kind] = claim
                    else:
                        optional.append(claim)
                answer.update(claims=optional, requiredClaims=slots)
        version = runner.context.grounding.VERSION if grounded else runner.context.STRUCTURE_VERSION if structure else runner.context.ROLE_VERSION if role else "market-context-v2.3-outlook" if quality else "market-context-v2.2-outlook"
        ground_transport = load("history_authored_ground", ROOT / "scripts/tests/test_briefing_market_grounding.py")
        second = run(version, directory / "first", directory / "second", ground_transport.GroundTransport() if grounded else authored.ContextTransport(quality_answer if quality or role else None))
        if role:
            plan = base.strict_load(base.regular(directory / "second/outlook-plan.json"))
            assert len(plan["requestedRoundIds"]) == 3 and len(plan["dependencyRoundIds"]) == 1, plan
            assert plan["plannedNewCalls"] == plan["maximumNewCalls"] == (12 if grounded else 8), plan
        if continuation:
            third = run(version if role else "market-context-v2.3-outlook", directory / "second", directory / "third", ground_transport.GroundTransport() if grounded else authored.ContextTransport(quality_answer))
            assert third["summaryPass"] == 4 and third["newPaidCalls"] == (0 if quality or role else 8), third
    assert first["summaryPass"] == 0 and first["newPaidCalls"] == 8, first
    assert second["summaryPass"] == 4 and second["newPaidCalls"] == (12 if grounded else 8), second
    return {"realPaidCalls": 0, "realProviderFetches": 0, "authoredOldCalls": 8, "authoredNewCalls": 12 if grounded else 8,
            "bundle": str(directory / ("third" if continuation else "second") / "bundle-v2.json")}


if __name__ == "__main__":
    print(create(Path(sys.argv[1]), "--tampered-history" in sys.argv, "--quality" in sys.argv, "--continuation" in sys.argv, "--role" in sys.argv, "--structure" in sys.argv, "--grounded" in sys.argv))
