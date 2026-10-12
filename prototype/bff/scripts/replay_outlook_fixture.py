#!/usr/bin/env python3
"""Preserve existing outlook generation with an actual CLI, frozen synthetic round, and empty-round proof."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "ai/worker/fixtures/contracts/synthetic-outlook"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-state", type=Path, required=True)
    parser.add_argument("--bff-state", type=Path, required=True)
    parser.add_argument("--empty-bff-state", type=Path, required=True)
    args = parser.parse_args()
    paths = [p.resolve() for p in (args.worker_state, args.bff_state, args.empty_bff_state)]
    if len(set(paths)) != 3 or (ROOT / "prototype/bff/var").resolve() in paths:
        parser.error("three separate nonshared synthetic state directories are required")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8",
           "PYTHONDONTWRITEBYTECODE": "1",
           "ZOOP_QUOTE_PROVIDER": "off", "ZOOP_METRICS_PROVIDER": "off", "ZOOP_BRIEFING_SCHEDULER": "0",
           "ZOOP_SNAPSHOT_PATH": str(FIXTURE / "snapshot.json"), "ZOOP_COMPANY_CATALOG": str(FIXTURE / "snapshot.json"),
           "ZOOP_POC_SANDBOX": str(args.bff_state.parent / "no-sandbox"),
           "ZOOP_ADMIN_POC_DSN": "postgresql://synthetic:synthetic@127.0.0.1:1/synthetic",
           "ZOOP_ADMIN_NEO4J_URI": "bolt://127.0.0.1:1"}
    def run(state, rid, moment):
        command = [sys.executable, str(ROOT / "prototype/bff/scripts/judge_outlook.py"), "--replay", str(FIXTURE / "replay.json"),
                   "--state-dir", str(state), "--worker-state", str(args.worker_state), "--grants", str(FIXTURE / "grants.json"),
                   "--source-id", "authored-synthetic-round", "--grant-id", "grant-synthetic-outlook",
                   "--grant-revision", "grant-synthetic-outlook-1", "--round", rid, "--synthetic-now", moment]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise SystemExit(result.stdout or "Outlook CLI failed")
        return json.loads(result.stdout)
    first = run(args.bff_state, "brf-2026-10-08-evening", "2026-10-08T18:15:00+09:00")
    repeated = run(args.bff_state, "brf-2026-10-08-evening", "2026-10-08T18:15:00+09:00")
    empty = run(args.empty_bff_state, "brf-2026-10-08-morning", "2026-10-08T07:45:00+09:00")
    assert first["rounds"][0]["status"] == "published" and first["rounds"][0]["issueCount"] > 0
    assert first["rounds"][0]["outlook"] is not None
    assert repeated["rounds"][0]["outlook"] == first["rounds"][0]["outlook"] and repeated["workerJobs"] == []
    assert empty["rounds"][0]["issueCount"] == 0 and empty["rounds"][0]["outlook"] is None and empty["workerJobs"] == []
    assert all(j["usage"]["providerAttempts"] == 0 for j in first["workerJobs"])
    print(json.dumps({"nonempty": first, "immutableRepeat": repeated, "emptyNoCall": empty, "modelNetworkCalls": 0}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
