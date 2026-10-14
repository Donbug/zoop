#!/usr/bin/env python3
"""Real Java -> Python -> installed pipeline gate for the Spring app's S2 extraction and S3 relation clients.

Builds a FRESH synthetic operator world with the actual pipeline code (authored HTML -> actual `zoop-ai-ingest` -> a server-approved S2 request
-> authored S3 fixtures), starts six real `ai/service` processes (127.0.0.1, fresh private state, replay only, synthetic in-memory principals, no model
call, no network, no PostgreSQL) over it, writes a private manifest and runs `./api/gradlew aiPipelineContractTest` against them.

The six services are the real installed `zoop-ai-extract` / `zoop-ai-relation` behind the real service, and differ only in the operator-side fault they
are launched with: `main` (the whole chain: S2 -> operator lists the upstream -> S3 -> review/revalidation, plus source/approval/upstream revocation),
`s2Crash` (a child dies after its stage was stored), `s2Unknown` (a child dies with a call reserved and unanswered), `s2Hold` and `s3Hold` (a dispatch is
held so a queued job can be cancelled), `s3Crash` (S3 child dies after its stage was stored).

After the Java run the script verifies that the Java tests really executed (exactly the declared number, none skipped or failed), that no service died,
that no credential, private path or source text reached a service log or the Gradle output, that no S2 child attempted a network connection, and that the
operator's ingestion and extraction state is byte-identical to before. Services, orphaned children and temp state are removed on every exit path.

Needs the installed pipeline (`make pipeline-install`) AND the service environment (`make service-install`); a missing pipeline FAILS, it never skips.
Run with the ai/service interpreter: `make api-ai-pipeline-smoke`. Needs JDK 21 (JAVA_HOME) like any api build.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai" / "service" / "pipeline_tests"))

from extraction_support import (APPROVALS_SCHEMA, CRASH_AFTER_EXTRACT_STAGE, CRASH_UNKNOWN as EXTRACT_CRASH_UNKNOWN, JOB, PLAIN,  # noqa: E402
                                ExtractionService, ExtractionWorkspace, make_service, terminate_extraction)
from relation_support import (CRASH_AFTER_RELATION_STAGE, UPSTREAMS_SCHEMA, RelationService, RelationWorkspace, World, build_world,  # noqa: E402
                              canonical, terminate_relation, tree)
from support import remove_tree  # noqa: E402

API = ROOT / "api"
TEST_SOURCE = API / "src" / "test" / "java" / "com" / "zoop" / "ai" / "AiPipelineContractTest.java"
RESULTS = API / "build" / "test-results" / "aiPipelineContractTest"
GRADLE_TIMEOUT_SECONDS = 1200


class GateFailure(Exception):
    pass


def launch_extraction(root: Path, name: str, world: World, *, wrapper: str | None = None, hold: bool = False, chain: bool = False) -> ExtractionService:
    workspace = ExtractionWorkspace(root / name, world, chain=chain)
    if wrapper is not None:
        workspace.write_wrapper(wrapper)
        workspace.arm()   # one-shot: the first resumed child dies at the named boundary, then the fault disarms itself
    env = {"ZOOP_TEST_EXTRACTION_HOLD_FILE": str(workspace.root / "extract-go")} if hold else {}
    return make_service(workspace, env=workspace.env(), launcher=bool(env), launcher_env=env).start()


def launch_relation(root: Path, name: str, world: World, *, wrapper: str | None = None, hold: bool = False) -> RelationService:
    workspace = RelationWorkspace(root / name, world)   # alpha and beta are listed for the operator-built S2 upstream
    if wrapper is not None:
        workspace.write_wrapper(wrapper)
        workspace.arm()
    env = {"ZOOP_TEST_RELATION_HOLD_FILE": str(workspace.root / "go")} if hold else {}
    return RelationService(workspace, launcher=bool(env), launcher_env=env).start()


def entry(service: Any) -> dict[str, Any]:
    workspace = service.workspace
    return {"baseUrl": f"http://127.0.0.1:{workspace.port}", "tokens": dict(workspace.credentials.tokens)}


def write_variants(main: ExtractionService, world: World, directory: Path) -> dict[str, str]:
    """The operator's server-side files and the variants the Java test copies over them (and restores): never edited by this script afterwards."""
    workspace = main.workspace
    directory.mkdir()
    registry = json.loads(workspace.sources.read_text(encoding="utf-8"))
    registry["sources"][0]["grant"]["enabled"] = False
    revoked = directory / "sources.revoked.json"
    revoked.write_text(canonical(registry), encoding="utf-8")
    approvals_empty = directory / "approvals.empty.json"
    approvals_empty.write_text(json.dumps({"schemaVersion": APPROVALS_SCHEMA, "approvals": []}), encoding="utf-8")
    listed = directory / "upstreams.listed.json"
    listed.write_text(json.dumps({"schemaVersion": UPSTREAMS_SCHEMA, "upstreams": [
        {"principal": "alpha", "jobId": world.upstream["jobId"], "inputDigest": world.upstream["inputDigest"]}]}), encoding="utf-8")
    upstreams_empty = directory / "upstreams.empty.json"
    upstreams_empty.write_text(json.dumps({"schemaVersion": UPSTREAMS_SCHEMA, "upstreams": []}), encoding="utf-8")
    return {"sources": str(workspace.sources), "sourcesRevoked": str(revoked), "approvals": str(workspace.approvals),
            "approvalsEmpty": str(approvals_empty), "upstreams": str(workspace.upstreams), "upstreamsListed": str(listed),
            "upstreamsEmpty": str(upstreams_empty)}


def run_gradle(manifest: Path, captured: list[str]) -> int:
    env = {**os.environ, "ZOOP_AI_PIPELINE_MANIFEST": str(manifest)}
    process = subprocess.Popen([str(API / "gradlew"), "-p", str(API), "aiPipelineContractTest", "--console=plain"], env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")

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
        raise GateFailure(f"gradle aiPipelineContractTest exceeded {GRADLE_TIMEOUT_SECONDS}s") from None
    reader.join(10)
    return code


def verify_junit() -> int:
    expected = TEST_SOURCE.read_text(encoding="utf-8").count("@Test\n")
    reports = sorted(RESULTS.glob("TEST-*.xml"))
    if not reports:
        raise GateFailure("aiPipelineContractTest produced no JUnit report: the contract tests did not run")
    tests = failures = 0
    for report in reports:
        suite = ET.parse(report).getroot()
        tests += int(suite.get("tests", "0"))
        failures += int(suite.get("failures", "0")) + int(suite.get("errors", "0"))
        if int(suite.get("skipped", "0")):
            raise GateFailure("aiPipelineContractTest skipped tests: a skip is not a pass")
    if failures:
        raise GateFailure(f"{failures} contract test failures")
    if tests == 0 or tests != expected:
        raise GateFailure(f"aiPipelineContractTest executed {tests} tests, the source declares {expected}")
    return tests


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="zoop-api-ai-pipeline-")).resolve()
    root.chmod(0o700)
    started: list[Any] = []
    captured: list[str] = []
    try:
        world = build_world(root / "world")
        before = {"ingestion": tree(world.ingestion), "extraction": tree(world.extraction)}

        def start(service: Any) -> Any:
            started.append(service)
            return service

        main_service = start(launch_extraction(root, "main", world, chain=True))
        s2_crash = start(launch_extraction(root, "s2crash", world, wrapper=CRASH_AFTER_EXTRACT_STAGE))
        s2_unknown = start(launch_extraction(root, "s2unknown", world, wrapper=EXTRACT_CRASH_UNKNOWN))
        s2_hold = start(launch_extraction(root, "s2hold", world, hold=True))
        s3_hold = start(launch_relation(root, "s3hold", world, hold=True))
        s3_crash = start(launch_relation(root, "s3crash", world, wrapper=CRASH_AFTER_RELATION_STAGE))

        workspace = main_service.workspace
        main_entry = {**entry(main_service), "files": write_variants(main_service, world, root / "variants")}
        manifest = {
            "world": {
                "s2JobId": JOB, "s2ApprovedRequestDigest": workspace.approved_digest(JOB),
                "s2OtherJobId": PLAIN, "s2OtherApprovedRequestDigest": workspace.approved_digest(PLAIN),
                "s2Counts": world.s2_counts, "s2ReplayCalls": world.s2_replay_calls,
                "upstream": dict(world.upstream), "counts": world.counts, "relationReplayCalls": world.replay_calls,
                "heldRelation": world.held, "heldRevision": world.held_revision, "eligibleRelation": world.eligible,
            },
            "main": main_entry,
            "s2Crash": entry(s2_crash), "s2Unknown": entry(s2_unknown), "s2Hold": entry(s2_hold),
            "s3Hold": entry(s3_hold), "s3Crash": entry(s3_crash),
        }
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        manifest_path.chmod(0o600)

        shutil.rmtree(RESULTS, ignore_errors=True)
        code = run_gradle(manifest_path, captured)
        if code != 0:
            raise GateFailure(f"gradle aiPipelineContractTest exited with {code}")
        tests = verify_junit()
        for service in started:
            if service.process is None or service.process.poll() is not None:
                raise GateFailure("a service process died during the run")
        output = "".join(captured)
        for service in started:
            private = [*service.workspace.private_strings(), *world.source_texts]
            if any(value in output or value in service.logs() for value in private):
                raise GateFailure("a credential, private path or source text reached a service log or the Gradle output")
            if isinstance(service.workspace, ExtractionWorkspace) and service.workspace.network_attempts() != "":
                raise GateFailure("a pipeline child attempted a network connection")
        if {"ingestion": tree(world.ingestion), "extraction": tree(world.extraction)} != before:
            raise GateFailure("the operator's ingestion or extraction state changed: the service must only read it")
        print(f"api-ai-pipeline-smoke: status=passed, javaTests={tests}, services={len(started)}, providerCalls=0, networkAttempts=0, "
              f"operatorStateChanged=false")
        return 0
    except (GateFailure, AssertionError, OSError, KeyError, json.JSONDecodeError) as error:
        print(f"api-ai-pipeline-smoke: status=failed: {error}", file=sys.stderr)
        return 1
    finally:
        for service in started:
            service.close()
        for workspace in {id(s.workspace): s.workspace for s in started}.values():
            if isinstance(workspace, ExtractionWorkspace):
                terminate_extraction(workspace)
                if workspace.chain:
                    terminate_relation(workspace)
            else:
                terminate_relation(workspace)
        remove_tree(root)


if __name__ == "__main__":
    sys.exit(main())
