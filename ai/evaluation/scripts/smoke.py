"""Throwaway end-to-end smoke of the scorer CLI on authored controls. Not a benchmark.

Runs the real entry point once in a subprocess, then drives every command in-process with network access
blocked by an audit hook. It proves the scorer wiring and its rejection paths; it says nothing about any
model, retriever or graph database, and it records `measuredResults: 0`.

    python3 -B ai/evaluation/scripts/smoke.py
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from zoop_eval import cli  # noqa: E402
from zoop_eval.controls import CONTROL_FILES, build_control  # noqa: E402
from zoop_eval.bench import load_bench  # noqa: E402


def run_cli(*argv: str) -> tuple[int, dict | str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(list(argv))
    text = out.getvalue()
    return code, (text if "--format" in argv and "text" in argv else json.loads(text))


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"smoke failed: {message}")


def main() -> int:
    real = subprocess.run([sys.executable, "-B", "-m", "zoop_eval", "validate"], cwd=ROOT, capture_output=True, text=True, check=False)
    expect(real.returncode == 0 and json.loads(real.stdout)["ok"], f"subprocess validate failed: {real.stdout}{real.stderr}")

    def no_network(event: str, args: tuple) -> None:
        if event.startswith("socket.") and event not in ("socket.__new__", "socket.gethostname"):
            raise RuntimeError(f"smoke must not use the network: {event}")

    sys.addaudithook(no_network)
    steps: list[str] = ["subprocess: python -m zoop_eval validate"]
    with tempfile.TemporaryDirectory(prefix="zoop-eval-smoke-") as tmp:
        tmpdir = Path(tmp)
        code, out = run_cli("controls", "--out-dir", str(tmpdir))
        expect(code == 0 and len(out["written"]) == len(CONTROL_FILES), "controls")
        bench = load_bench()
        for name, (kind, split) in CONTROL_FILES.items():
            expect(json.loads((ROOT / "fixtures" / "controls" / name).read_text("utf-8")) == build_control(bench, kind, split),
                   f"checked-in fixture {name} drifted from the generator; rerun `controls --out-dir fixtures/controls`")
        steps.append("controls + fixture drift check")

        scores = {}
        for name in CONTROL_FILES:
            code, doc = run_cli("score", str(tmpdir / name))
            expect(code == 0 and "NOT a measurement" in doc["provenanceLabel"], f"score {name}")
            scores[name] = doc["headline"]["qa.outcome.endToEndCorrect"]["value"]
        expect(scores["oracle-dev.run.json"] == 1.0 and scores["oracle-test.run.json"] == 1.0, "oracle must score 1.0")
        expect(scores["degraded-dev.run.json"] < 1.0, "degraded control must lose points")
        steps.append(f"score x3 (qa end-to-end: {scores})")

        code, text = run_cli("score", str(tmpdir / "degraded-dev.run.json"), "--format", "text")
        expect(code == 0 and "FALSE-MERGE" in text and "NOT EVALUATED" in text, "text report")
        code, doc = run_cli("compare", str(tmpdir / "oracle-dev.run.json"), str(tmpdir / "degraded-dev.run.json"))
        expect(code == 0 and doc["comparable"] and doc["provenanceKind"] == "authored_control", "compare controls")
        steps.append("text report + compare controls")

        forged = json.loads((tmpdir / "oracle-dev.run.json").read_text("utf-8"))
        forged["runId"] = "smoke-forged-measured-label"
        forged["provenance"] = {"kind": "real_measured", "executionMode": "replay", "recorder": "smoke", "recordedAt": "2026-10-14T00:00:00+00:00"}
        forged_path = tmpdir / "forged.run.json"
        forged_path.write_text(json.dumps(forged), encoding="utf-8")
        code, doc = run_cli("compare", str(tmpdir / "oracle-dev.run.json"), str(forged_path))
        expect(code == 2 and doc["error"]["code"] == "mixed_provenance", "measured and control must not compare")
        dup = json.loads((tmpdir / "oracle-dev.run.json").read_text("utf-8"))
        dup["records"].append(dup["records"][0])
        dup_path = tmpdir / "dup.run.json"
        dup_path.write_text(json.dumps(dup), encoding="utf-8")
        code, doc = run_cli("score", str(dup_path))
        expect(code == 2 and doc["error"]["code"] == "duplicate_record", "duplicate record must be rejected")
        steps.append("rejections: mixed provenance, duplicate record")

    print(json.dumps({"status": "passed", "steps": steps, "modelCalls": 0, "networkCalls": 0, "measuredResults": 0,
                      "note": "scorer wiring only; authored controls are not benchmark results"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
