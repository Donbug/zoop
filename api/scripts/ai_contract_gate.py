#!/usr/bin/env python3
"""Real Java -> Python -> installed `zoop-ai` gate for the Spring app's AI transport client.

Starts two real `ai/service` processes (127.0.0.1, fresh temp state, replay only, synthetic in-memory principals, no model call,
no PostgreSQL), writes a private manifest, runs `./api/gradlew aiContractTest` against them, then verifies that the Java run
really executed (non-zero tests, none skipped or failed) and that no credential reached the service logs or the Gradle output.
Temp state, servers and runtime children are removed on every exit path.

Run with the ai/service environment (`make service-install` first): `make api-ai-smoke`. Needs JDK 21 (JAVA_HOME) like any api build.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai" / "service" / "tests"))

from support import (Workspace, ServiceProcess, combined_replay, document_jobs, document_replay, merged_grants,  # noqa: E402
                     outlook_job, remove_tree, semantic_job_and_entry, terminate_runtime)

API = ROOT / "api"
RESULTS = API / "build" / "test-results" / "aiContractTest"
GRADLE_TIMEOUT_SECONDS = 900


class GateFailure(Exception):
    pass


def principals(workspace: Workspace) -> dict[str, str]:
    return dict(workspace.credentials.tokens)


def run_gradle(manifest: Path, captured: list[str]) -> int:
    env = {**os.environ, "ZOOP_AI_CONTRACT_MANIFEST": str(manifest)}
    process = subprocess.Popen([str(API / "gradlew"), "-p", str(API), "aiContractTest", "--console=plain"], env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               errors="replace")

    def pump() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            captured.append(line)
            sys.stdout.write(line)
            sys.stdout.flush()

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        code = process.wait(GRADLE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise GateFailure(f"gradle aiContractTest exceeded {GRADLE_TIMEOUT_SECONDS}s") from None
    reader.join(10)
    return code


def verify_junit() -> tuple[int, int]:
    reports = sorted(RESULTS.glob("TEST-*.xml"))
    if not reports:
        raise GateFailure("aiContractTest produced no JUnit report: the contract tests did not run")
    tests = failures = 0
    for report in reports:
        suite = ET.parse(report).getroot()
        tests += int(suite.get("tests", "0"))
        failures += int(suite.get("failures", "0")) + int(suite.get("errors", "0"))
        if int(suite.get("skipped", "0")):
            raise GateFailure("aiContractTest skipped tests: a skip is not a pass")
    if tests == 0:
        raise GateFailure("aiContractTest executed zero tests")
    return tests, failures


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="zoop-api-ai-contract-")).resolve()
    root.chmod(0o700)
    services: list[ServiceProcess] = []
    captured: list[str] = []
    try:
        # Service 1: all four kinds, replay only, with a revocable grant registry.
        main_ws = Workspace(root / "main", replay=combined_replay())
        grants = merged_grants()
        revoked = copy.deepcopy(grants)
        for grant in revoked["grants"]:
            grant["enabled"] = False
        revoked_path = root / "main" / "grants.revoked.json"
        revoked_path.write_text(json.dumps(revoked), encoding="utf-8")
        services.append(ServiceProcess(main_ws).start())
        verify_job, _ = semantic_job_and_entry()
        jobs = [*document_jobs(), outlook_job(), verify_job]

        # Service 2: a fixture the runtime rejects, so jobs stay queued and blocked: the safe state for cancel and recover.
        broken = document_replay()
        broken["recordingKind"] = "provider"
        recovery_ws = Workspace(root / "recovery", replay=broken)
        good_path = root / "recovery" / "replay.good.json"
        good_path.write_text(json.dumps(document_replay(), ensure_ascii=False), encoding="utf-8")
        services.append(ServiceProcess(recovery_ws).start())
        recover_job, cancel_job = document_jobs()[0], document_jobs()[1]

        manifest = {
            "main": {"baseUrl": f"http://127.0.0.1:{main_ws.port}", "tokens": principals(main_ws), "jobs": jobs,
                     "grantsPath": str(main_ws.grants_path), "revokedGrantsPath": str(revoked_path)},
            "recovery": {"baseUrl": f"http://127.0.0.1:{recovery_ws.port}", "tokens": principals(recovery_ws),
                         "replayPath": str(recovery_ws.replay_path), "goodReplayPath": str(good_path),
                         "recoverJob": recover_job, "cancelJob": cancel_job},
        }
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        manifest_path.chmod(0o600)

        shutil.rmtree(RESULTS, ignore_errors=True)
        code = run_gradle(manifest_path, captured)
        if code != 0:
            raise GateFailure(f"gradle aiContractTest exited with {code}")
        tests, failures = verify_junit()
        if failures:
            raise GateFailure(f"{failures} contract test failures")
        for service in services:
            if service.process is None or service.process.poll() is not None:
                raise GateFailure("a service process died during the run")
        output = "".join(captured)
        for workspace, service in ((main_ws, services[0]), (recovery_ws, services[1])):
            leaked = [s for s in workspace.private_strings() if s in output or s in service.logs()]
            if leaked:
                raise GateFailure("a credential, digest or private path reached the service log or the Gradle output")
        print(f"api-ai-smoke: status=passed, javaTests={tests}, services=2, providerCalls=0")
        return 0
    except (GateFailure, AssertionError, OSError) as error:
        print(f"api-ai-smoke: status=failed: {error}", file=sys.stderr)
        return 1
    finally:
        for service in services:
            service.close()
        for service in services:
            terminate_runtime(service.workspace.worker)
        remove_tree(root)


if __name__ == "__main__":
    sys.exit(main())
