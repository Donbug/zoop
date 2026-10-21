"""Build an actual producer bundle using authored offline transport; no model or provider network."""
import importlib.util
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("authored_round", root / "scripts/tests/test_briefing_round_simulation.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
folder = Path(sys.argv[1])
fixture = m.RoundSimulationTest()
fixture.root = folder
fixture.sources = folder / "source.jsonl"
fixture.clocks = folder / "clocks.json"
fixture.html = folder / "html"
fixture.html.mkdir(exist_ok=True)
fixture.output = folder / ("producer-" + sys.argv[2] if len(sys.argv) > 2 else "producer-output")
mode = sys.argv[2] if len(sys.argv) > 2 else ""
rows = [m.source("authored-morning", "2026-10-02T09:00:00+09:00"),
        m.source("a-repeat" if mode == "v2-repeat" else "authored-evening", "2026-10-02T10:00:00+09:00")]
fixture.prepare(rows[:1] if mode == "insufficient" else rows)
args = fixture.args(True)
args.user_inbox_ref = "inbox/synthetic-round-authorization.md"
transport = m.AuthoredTransport(select_none=mode == "select-none", insufficient=mode == "insufficient")
if mode == "v2-repeat":
    spec_v2 = importlib.util.spec_from_file_location("authored_quality", root / "scripts/tests/test_briefing_quality_v2.py")
    v2 = importlib.util.module_from_spec(spec_v2)
    spec_v2.loader.exec_module(v2)
    transport = v2.V2Transport()
    args.quality_policy = m.sim.QUALITY_V2
elif mode == "v2-rejected":
    args.quality_policy = m.sim.QUALITY_V2
    class RejectedImportance(m.AuthoredTransport):
        def __call__(self, raw):
            status, body = super().__call__(raw)
            if m.sim.base.strict_load(raw)["text"]["format"]["name"] == "round_simulation_importance":
                answer = m.sim.base.strict_load(body)
                result = m.sim.base.strict_load(answer["output"][0]["content"][0]["text"])
                for value in result["assessments"].values():
                    value.update(status="REJECT", importance=1)
                return m.response(result, raw)
            return status, body
    transport = RejectedImportance()
m.sim.run(args, transport)
output = fixture.output
if len(sys.argv) > 2 and sys.argv[2] == "market-repair":
    spec2 = importlib.util.spec_from_file_location("authored_market", root / "scripts/tests/test_briefing_market_enrichment.py")
    e = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(e)
    class RejectedRepair(e.AuthoredSummaryTransport):
        def __call__(self, raw):
            status, body = super().__call__(raw)
            request = e.base.strict_load(raw)
            data = e.base.strict_load(request["input"])
            response = e.base.strict_load(body)
            result = e.base.strict_load(response["output"][0]["content"][0]["text"])
            if request["text"]["format"]["name"] == "market_summary_verification":
                for check in result["checks"].values():
                    check["verdict"] = "UNSUPPORTED"
            elif data["repairAttempt"] == 1:
                for claim in result["claims"]:
                    claim.update(evidenceIds=[], indicatorIds=["kospi"])
            response["output"][0]["content"][0]["text"] = e.base.canonical(result).decode()
            return status, e.base.canonical(response)
    output = folder / "producer-market-output"
    enrichment_args = e.enrichment.parser().parse_args([
        "--baseline", str(fixture.output), "--output", str(output), "--sources", str(fixture.sources),
        "--clocks", str(fixture.clocks), "--user-inbox-ref", args.user_inbox_ref,
        "--workers", "1", "--execute-authorized-enrichment"])
    class NumericMarket(e.fixtures.AuthoredMarketTransport):
        def __call__(self, url):
            status, body = super().__call__(url)
            if "FX_USDKRW" not in url:
                parsed = e.base.strict_load(body)
                rows = parsed["chart"]["result"][0]["indicators"]["quote"][0]
                rows["close"] = [float(value) if value is not None else None for value in rows["close"]]
                body = e.base.canonical(parsed)
            return status, body
    e.enrichment.run(enrichment_args, NumericMarket(), RejectedRepair())
    for name in ["market", "summary-run"]:
        shutil.copytree(output / name, folder / name, dirs_exist_ok=True)
shutil.copyfile(output / "bundle-v2.json", folder / "bundle.json")
shutil.copytree(output / "calls", folder / "calls", dirs_exist_ok=True)
