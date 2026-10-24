"""Actual retained-dev retrieval -> scoring CLI, with command-seam isolation audit.

Temporary fixture/run writes belong to this harness, never the commands under audit.
Run: python3 -B ai/evaluation/scripts/materials_retrieval_smoke.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.materials_smoke import copy_materials, expect, run_cli


def observed(*args: str, code: int = 0) -> tuple[dict, dict, str]:
    result = run_cli(*args)
    expect(result.returncode == code, f"CLI exit {result.returncode}: {result.stdout} {result.stderr}")
    audit = json.loads(result.stderr)
    expect(not any(audit["audit"].values()), "unexpected command side effects")
    document = json.loads(result.stdout)
    expect(document["ok"] is (code == 0), "structured outcome")
    return document, audit, result.stdout


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="zoop-retrieval-smoke-") as temporary:
        root = Path(temporary)
        materials = root / "materials"
        copy_materials(materials)
        # Preserve the exact manifest; absence of gold must not change input binding.
        gold_bytes = (materials / "tatqa.gold.json").read_bytes()
        (materials / "tatqa.gold.json").unlink()
        (materials / "klue-re.gold.json").unlink()
        run, audit, raw = observed("materials-retrieve", "--materials", str(materials))
        expect(audit["opened"] == [str(materials), "manifest.json", "tatqa.inputs.json"], "gold-isolated reads")
        expect(len(run["records"]) == len(run["queryIds"]) == 30, "all retained questions")
        expect(all(r["status"] == "ok" and type(r["elapsedNs"]) is int and r["elapsedNs"] >= 0
                   for r in run["records"]), "measured query durations")
        repeated, _, _ = observed("materials-retrieve", "--materials", str(materials))
        expect([{k: v for k, v in r.items() if k != "elapsedNs"} for r in run["records"]] ==
               [{k: v for k, v in r.items() if k != "elapsedNs"} for r in repeated["records"]], "deterministic ranks")
        _, _, inputs_raw = observed("materials-inputs", "--dataset", "tatqa", "--materials", str(materials))
        expect(run["inputsSha256"] == hashlib.sha256(inputs_raw.rstrip("\n").encode()).hexdigest(), "normalized input digest")
        run_path = root / "run.json"
        run_path.write_text(raw, encoding="utf-8")
        # Run has exited and is saved before gold becomes available to scoring.
        (materials / "tatqa.gold.json").write_bytes(gold_bytes)
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in materials.iterdir()}
        score, score_audit, _ = observed("materials-retrieval-score", str(run_path), "--materials", str(materials))
        expect(score["counts"]["questions"] == score["counts"]["recorded"] == score["counts"]["ok"] == 30, "complete scored coverage")
        expect(score["counts"]["missing"] == score["counts"]["error"] == 0, "no missing or failed queries")
        expect(score["counts"]["scorable"] + score["counts"]["notScorable"] == 30, "explicit annotation coverage")
        expect(score_audit["opened"].index(str(run_path)) < score_audit["opened"].index("tatqa.gold.json"), "run before gold")
        expect(before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in materials.iterdir()}, "no material mutation")
        expect(run_path.read_text("utf-8") == raw, "no run mutation")
        direct = run_cli("materials-retrieval-score", str(run_path), "--materials", str(materials), audited=False)
        expect(direct.returncode == 0 and not direct.stderr and json.loads(direct.stdout) == score, "direct module scoring CLI")
        print(json.dumps({"status": "passed", "counts": score["counts"], "metrics": score["metrics"],
                          "inputsSha256": run["inputsSha256"],
                          "elapsedNs": [r["elapsedNs"] for r in run["records"]],
                          "proofScope": "Actual 30 retained development queries; paired-context paragraph retrieval only. Not held-out, answer EM/F1, full RAG or Korean finance quality. Audit begins before application imports, after Python/stdlib bootstrap; argparse display/locale observations are separate. Harness-only temporary writes are not command mutations.",
                          "commandEffects": audit["audit"], "scorerEffects": score_audit["audit"],
                          "limits": score["limits"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
