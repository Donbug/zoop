#!/usr/bin/env python3
"""Run the authored S1 fixture through actual JSON CLI invocations and optional BFF import.

No live environment, secret, real-news file or default BFF state is forwarded.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "ai/worker/fixtures/contracts/synthetic-document"
WORKER_COMMAND = [str(ROOT / "ai/worker/.venv/bin/zoop-ai")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-state", type=Path, required=True)
    parser.add_argument("--bff-state", type=Path)
    args = parser.parse_args()
    if args.bff_state and args.bff_state.resolve() == args.worker_state.resolve():
        parser.error("worker and BFF stores must be separate")
    if args.bff_state and args.bff_state.resolve() == (ROOT / "prototype/bff/var").resolve():
        parser.error("synthetic replay may not use the shared BFF state")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()),
           "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
           "ZOOP_QUOTE_PROVIDER": "off", "ZOOP_METRICS_PROVIDER": "off", "ZOOP_BRIEFING_SCHEDULER": "0",
           "ZOOP_SNAPSHOT_PATH": str(FIXTURE / "snapshot.json"),
           "ZOOP_COMPANY_CATALOG": str(FIXTURE / "snapshot.json")}
    jobs = json.loads((FIXTURE / "jobs.json").read_text())["jobs"]
    observed = []
    for request in jobs:
        for command, data in [("submit", request), ("run", {"schemaVersion": "zoop-ai-s1-1", "jobId": request["jobId"]}),
                              ("get", {"schemaVersion": "zoop-ai-s1-1", "jobId": request["jobId"]})]:
            process = subprocess.run([*WORKER_COMMAND, command, "--state-dir", str(args.worker_state),
                                      "--grants", str(FIXTURE / "grants.json"), "--replay", str(FIXTURE / "replay.json")],
                                     input=json.dumps(data, ensure_ascii=False), env=env, capture_output=True, text=True, timeout=120)
            result = json.loads(process.stdout)
            if process.returncode or command != "submit" and result.get("state") != "ready":
                raise SystemExit(json.dumps({"status": "failed", "command": command, "result": result}, ensure_ascii=False))
        observed.append({"jobId": result["jobId"], "state": result["state"], "artifactIds": result["artifactIds"], "usage": result["usage"]})
    imported = None
    if args.bff_state:
        argv = [sys.executable, str(ROOT / "prototype/bff/scripts/document_analysis.py"), "import",
                "--state-dir", str(args.bff_state), "--worker-state", str(args.worker_state),
                "--grants", str(FIXTURE / "grants.json")]
        for request in jobs:
            argv += ["--job-id", request["jobId"]]
        process = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120)
        if process.returncode:
            raise SystemExit(process.stdout or "BFF import failed")
        imported = json.loads(process.stdout)
    print(json.dumps({"schemaVersion": "zoop-ai-s1-1", "jobs": observed, "bffImport": imported,
                      "bffSnapshot": str(FIXTURE / "snapshot.json"), "modelNetworkCalls": 0}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
