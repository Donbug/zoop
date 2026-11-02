#!/usr/bin/env python3
"""Offline plan-round -> installer -> real S2/S3 HTTP smoke, with test-owned crash injection.

Run with the service interpreter after installing the worker and pipeline. Every world,
registry and ledger is synthetic and fresh. Installer and pipeline commands have a
network-denying audit hook; the only HTTP client talks to the loopback service.
Evidence (command output, service logs and a summary) survives private workspace cleanup.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline_tests"))

from extraction_support import PLAIN, ExtractionService, ExtractionWorkspace, make_service, pipeline_env, terminate_extraction  # noqa: E402
from relation_support import World, build_world, canonical, terminate_relation, tree  # noqa: E402
from support import remove_tree  # noqa: E402
from test_extraction_plan import author_s3_fixtures, descriptor  # noqa: E402


AUDIT = '''import os, runpy, stat, sys
from pathlib import Path
ROOT = Path(__ROOT__)
def audit(event, args):
    if os.environ.get("INSTALL_SMOKE_READ_ONLY") == "1":
        if event == "open" and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            if not isinstance(args[0], int) or not stat.S_ISFIFO(os.fstat(args[0]).st_mode):
                raise RuntimeError("read-only command attempted a writable filesystem open")
        if event in ("os.mkdir", "os.chmod", "os.chown", "os.rename", "os.link", "os.symlink", "os.remove", "os.rmdir", "os.truncate", "os.utime"):
            raise RuntimeError("read-only command attempted filesystem mutation")
    if event.startswith("socket.") and event.split(".", 1)[1] in (
        "connect", "getaddrinfo", "gethostbyname", "gethostbyaddr", "bind", "sendto"):
        with (ROOT / "network-attempt").open("a") as handle:
            handle.write(event + "\\n")
        raise RuntimeError("network attempted")
sys.addaudithook(audit)
'''


def check(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def snapshot(root: Path) -> dict[str, tuple]:
    """Include directory existence/modes and file mtimes, not only registry JSON values."""
    if not root.exists():
        return {}
    result = {".": ("directory", root.stat().st_mode & 0o777)}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        result[str(path.relative_to(root))] = (
            "directory", info.st_mode & 0o777
        ) if path.is_dir() else (info.st_mode & 0o777, info.st_size, info.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
    return result


class Scenario:
    def __init__(self, root: Path, evidence: Path, world: World, name: str, *, seeded: bool = True):
        self.workspace = ExtractionWorkspace(root / name, world, chain=True, requests=(PLAIN,) if seeded else ())
        self.workspace.state.mkdir(mode=0o700)
        self.evidence = evidence / name
        self.evidence.mkdir()
        self.services: list[ExtractionService] = []
        self.commands = 0
        self.plan_dir = self.workspace.root / "plan"
        self.installer = self.workspace.root / "installer.py"
        self.installer.write_text(AUDIT.replace("__ROOT__", repr(str(self.workspace.root))) + '''
if os.environ.get("INSTALL_SMOKE_CRASH_FIRST_REPLACE") == "1":
    original = os.replace
    expected = Path(os.environ["ZOOP_AI_SERVICE_EXTRACTION_APPROVALS"]).absolute()
    expected_parent = expected.parent.stat()
    def replace(source, target, *args, **kwargs):
        original(source, target, *args, **kwargs)
        candidate = Path(os.fsdecode(target))
        directory_fd = kwargs.get("dst_dir_fd")
        if candidate.is_absolute() or directory_fd is None:
            matches = candidate.absolute() == expected
        else:
            parent = os.fstat(directory_fd)
            matches = candidate == Path(expected.name) and (parent.st_dev, parent.st_ino) == (expected_parent.st_dev, expected_parent.st_ino)
        if matches:
            os._exit(75)
    os.replace = replace
runpy.run_module("zoop_ai_service.plan_install_cli", run_name="__main__")
''', encoding="utf-8")
        relation = self.workspace.root / "relation-wrapper.py"
        from relation_support import PIPELINE_PYTHON
        relation.write_text(f"#!{PIPELINE_PYTHON}\n" + AUDIT.replace("__ROOT__", repr(str(self.workspace.root)))
                            + 'runpy.run_module("zoop_ai_pipeline.relation_cli", run_name="__main__")\n', encoding="utf-8")
        relation.chmod(0o755)
        self.workspace.command = relation
        if seeded:
            self.workspace.write_upstreams([("alpha", "old-unrelated-upstream", "1" * 64)])
        for directory in (self.workspace.root, self.workspace.app_state, self.workspace.extraction_state):
            directory.chmod(0o700)
        for path in (self.workspace.approvals, self.workspace.upstreams, self.workspace.sources, self.workspace.grants_path,
                     self.workspace.producer, self.workspace.verifier, self.workspace.s2_replay, self.workspace.s2_topic):
            path.chmod(0o600)
        self.before_registries = self.registries()

    def registries(self) -> tuple[bytes, bytes]:
        return self.workspace.approvals.read_bytes(), self.workspace.upstreams.read_bytes()

    def target_state(self, *extra: Path) -> tuple[tuple, ...]:
        result = []
        for path in (self.workspace.approvals, self.workspace.upstreams, *extra):
            info = path.stat()
            result.append((info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, path.read_bytes()))
        return tuple(result)

    def record(self, label: str, done: subprocess.CompletedProcess) -> None:
        self.commands += 1
        stem = self.evidence / f"{self.commands:02d}-{label}"
        stem.with_suffix(".stdout").write_bytes(done.stdout)
        stem.with_suffix(".stderr").write_bytes(done.stderr)
        stem.with_suffix(".json").write_text(canonical({"returncode": done.returncode}), encoding="utf-8")

    def cli(self, command: str, *args: str, overrides: dict[str, str] | None = None, crash: bool = False,
            raw: bool = False) -> tuple[int, Any]:
        env = {**self.workspace.env(), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", **(overrides or {})}
        if command in ("inspect", "status"):
            env["INSTALL_SMOKE_READ_ONLY"] = "1"
        if crash:
            env["INSTALL_SMOKE_CRASH_FIRST_REPLACE"] = "1"
        extra_targets = tuple(Path(value) for key, value in (overrides or {}).items()
                              if key in ("ZOOP_AI_SERVICE_EXTRACTION_APPROVALS", "ZOOP_AI_SERVICE_RELATION_UPSTREAMS"))
        before_targets = self.target_state(*extra_targets)
        done = subprocess.run([sys.executable, str(self.installer), command, *args], env=env, capture_output=True, timeout=300)
        self.record(command, done)
        if raw:
            return done.returncode, done.stdout
        if done.returncode != 0:
            check(self.target_state(*extra_targets) == before_targets, f"refused {command} changed target bytes or metadata")
        check(done.stderr == b"", f"{command} stderr: {done.stderr.decode(errors='replace')[-2000:]}")
        return done.returncode, json.loads(done.stdout)

    def prepare(self, *, relation: bool = False) -> dict:
        workspace = self.workspace
        selection = self.plan_dir.with_suffix(".selection.json")
        selection.write_text(canonical({"schemaVersion": "zoop-extraction-round-selection-1", "asOf": "2026-10-31T09:00:00+09:00",
                                        "maxAgeSeconds": 3600}), encoding="utf-8")
        argv = [str(workspace.s2_command), "plan-round", "--ingestion-state-dir", str(workspace.world.ingestion),
                "--sources", str(workspace.sources), "--replay", str(workspace.s2_replay), "--topic-replay", str(workspace.s2_topic),
                "--principal", "alpha", "--output", str(self.plan_dir), "--selection", str(selection)]
        done = subprocess.run(argv, input=canonical(descriptor(workspace.world)).encode(), env=pipeline_env(workspace), capture_output=True, timeout=300)
        self.record("plan-round", done)
        check(done.returncode == 0 and done.stderr == b"", f"plan-round failed: {done.stdout!r} {done.stderr!r}")
        manifest = json.loads((self.plan_dir / "manifest.json").read_text(encoding="utf-8"))
        main_version = workspace.world.s2_request["incoming"]["documentVersion"]
        unit = next(item for item in manifest["units"] if item["documentVersion"] == main_version)
        if relation:
            authored = author_s3_fixtures(workspace, workspace.world, self.plan_dir, unit["jobId"])
            check(authored["inputDigest"] == unit["inputDigest"], "fixture authoring changed the planned S2 identity")
            shutil.copyfile(authored["producer"], workspace.producer)
            shutil.copyfile(authored["verifier"], workspace.verifier)
        self.unit = unit
        return manifest

    def inspect(self) -> dict:
        before = snapshot(self.workspace.root)
        code, review = self.cli("inspect", "--plan-dir", str(self.plan_dir))
        check(code == 0, f"inspect refused: {review}")
        check(snapshot(self.workspace.root) == before, "read-only inspection wrote workspace files or changed their metadata")
        check(self.workspace.network_attempts() == "", "inspection attempted network")
        return review

    def install(self, review: dict, **kwargs: Any) -> tuple[int, Any]:
        return self.cli("install", "--plan-dir", str(self.plan_dir), "--expected-current-digest", review["currentDigest"],
                        "--expected-review-digest", review["reviewDigest"], **kwargs)

    def start(self, *, hold: bool = False, wait: bool = True) -> ExtractionService:
        service = make_service(self.workspace, env={**self.workspace.env(), "PYTHONDONTWRITEBYTECODE": "1"},
                               launcher=hold, launcher_env={"ZOOP_TEST_EXTRACTION_HOLD_FILE": str(self.workspace.root / "extract-go")} if hold else None)
        # Unique output names across separate service objects over the same workspace.
        service._runs = len(self.services)
        self.services.append(service)
        return service.start(wait=wait)

    def assert_startup_barrier(self) -> None:
        before = {"service": tree(self.workspace.state), "extraction": tree(self.workspace.extraction_state),
                  "relation": tree(self.workspace.relation_state), "worker": tree(self.workspace.worker)}
        service = self.start(wait=False)
        check(service.exited() == 78, f"pending installation must refuse startup: {service.logs()[-2000:]}")
        check({"service": tree(self.workspace.state), "extraction": tree(self.workspace.extraction_state),
               "relation": tree(self.workspace.relation_state), "worker": tree(self.workspace.worker)} == before,
              "startup touched a service, S2, S3 or worker ledger before the pending-installation barrier")
        check("plan_install_unresolved" in service.logs(), "startup did not report the pending-installation barrier")

    def close(self) -> None:
        try:
            for service in self.services:
                service.close()
            terminate_extraction(self.workspace)
            terminate_relation(self.workspace)
        finally:
            for pattern in ("service-*.out", "service-*.err", "network-attempt"):
                for path in self.workspace.root.glob(pattern):
                    shutil.copyfile(path, self.evidence / path.name)
        check(self.workspace.network_attempts() == "", "a subprocess attempted network")


def flow(root: Path, evidence: Path, world: World, owned: list[Scenario]) -> dict:
    scenario = Scenario(root, evidence, world, "flow")
    owned.append(scenario)
    manifest = scenario.prepare(relation=True)
    workspace, unit = scenario.workspace, scenario.unit
    review = scenario.inspect()
    service = scenario.start(hold=True)
    response = service.esubmit(unit["jobId"], digest_=unit["approvedRequestDigest"])
    check(response.status_code == 403, "planning alone granted an S2 unit")
    before = scenario.registries()
    code, busy = scenario.install(review)
    check(code != 0 and "service_state_busy" in canonical(busy), f"running service did not block install: {busy}")
    check(scenario.registries() == before, "busy install changed registry bytes")
    service.close()
    code, receipt = scenario.install(review)
    check(code == 0 and receipt["outcome"] == "committed" and receipt["appliedNow"] is True and receipt["installationCurrent"] is True,
          f"pinned install refused: {receipt}")
    committed = scenario.target_state()
    code, exact_retry = scenario.install(review)
    check(code == 0 and exact_retry == {**receipt, "appliedNow": False} and scenario.target_state() == committed,
          f"committed retry did not return the exact historical receipt: {exact_retry}")
    approvals = json.loads(workspace.approvals.read_bytes())["approvals"]
    upstreams = json.loads(workspace.upstreams.read_bytes())["upstreams"]
    old_approvals, old_upstreams = [json.loads(raw)[key] for raw, key in zip(scenario.before_registries, ("approvals", "upstreams"))]
    check(all(item in approvals for item in old_approvals) and all(item in upstreams for item in old_upstreams), "add-only install dropped old unrelated grants")
    for item in manifest["units"]:
        check(any(a["principal"] == "alpha" and a["jobId"] == item["jobId"] and a["approvedRequestDigest"] == item["approvedRequestDigest"] for a in approvals),
              "installed approvals omit an exact planned unit")
        check({"principal": "alpha", "jobId": item["jobId"], "inputDigest": item["inputDigest"]} in upstreams, "installed upstreams omit an exact planned unit")
    service = scenario.start(hold=True)
    accepted = service.esubmit(unit["jobId"], digest_=unit["approvedRequestDigest"])
    check(accepted.status_code == 202, accepted.text)
    upstream = {"jobId": unit["jobId"], "inputDigest": unit["inputDigest"]}
    early = service.rsubmit(upstream=upstream)
    check(early.status_code == 409 and early.json()["error"].get("runtimeCode") == "upstream_not_ready", early.text)
    workspace.go()
    s2 = service.ewait(unit["jobId"], states={"ready"}, dispatch={"idle"})
    check(s2["inputDigest"] == unit["inputDigest"] and s2["usage"]["providerCalls"] == 0 and s2["usage"]["paidModelCalls"] == 0,
          "planned S2 did not run in replay")
    accepted = service.rsubmit(upstream=upstream)
    check(accepted.status_code == 202, accepted.text)
    s3 = service.rwait(states={"ready"}, dispatch={"idle"})
    check(s3["usage"]["providerCalls"] == 0 and s3["usage"]["modelCalls"] == 0
          and service.rresult().json()["delivery"] == {"state": "available", "reason": None}, "S3 replay was not ready/deliverable")
    service.close()
    # An explicit later revocation is not undone by retrying the old operation.
    workspace.write_entries(old_approvals)
    workspace.write_upstreams([(item["principal"], item["jobId"], item["inputDigest"]) for item in old_upstreams])
    revoked = scenario.target_state()
    code, replay = scenario.install(review)
    expected = {**receipt, "appliedNow": False, "installationCurrent": False, "error": {"code": "installation_not_current"}}
    check(code == 78 and replay == expected, f"historical retry lost the stored receipt identity or current-state marker: {replay}")
    check(scenario.target_state() == revoked, "historical committed replay regranted separately revoked entries")
    return {"case": "flow", "readOnlyInspect": True, "lockRefused": True, "oldGrantsPreserved": True, "s2": s2["state"], "s3": s3["state"],
            "providerCalls": 0, "historicalReplayDidNotRegrant": True, "installationId": review["installationId"]}


def refusals(root: Path, evidence: Path, world: World, owned: list[Scenario]) -> dict:
    scenario = Scenario(root, evidence, world, "refusals", seeded=False)
    owned.append(scenario)
    scenario.prepare()
    review = scenario.inspect()
    original = scenario.registries()
    principals = json.loads(scenario.workspace.env()["ZOOP_AI_SERVICE_PRINCIPALS"])
    wrong_principals = canonical([item for item in principals if item["principal"] != "alpha"])
    bad_review = {**review, "reviewDigest": "0" * 64}
    for label, pins, overrides in (("principal", review, {"ZOOP_AI_SERVICE_PRINCIPALS": wrong_principals}), ("digest", bad_review, None)):
        code, result = scenario.install(pins, overrides=overrides)
        check(code != 0 and scenario.registries() == original, f"wrong {label} was accepted or changed target files: {result}")
    fixture = scenario.workspace.s2_replay
    original_fixture = fixture.read_bytes()
    fixture.write_bytes(original_fixture + b"\n")
    try:
        code, result = scenario.install(review)
        check(code != 0 and scenario.registries() == original, f"changed fixture config was accepted or changed targets: {result}")
    finally:
        fixture.write_bytes(original_fixture)
    alternate = scenario.workspace.root / "alternate-approvals.json"
    alternate.write_bytes(original[0])
    alternate.chmod(0o600)
    code, result = scenario.install(review, overrides={"ZOOP_AI_SERVICE_EXTRACTION_APPROVALS": str(alternate)})
    check(code != 0 and scenario.registries() == original and alternate.read_bytes() == original[0], f"changed destination config was accepted: {result}")
    scenario.workspace.write_upstreams([("alpha", "new-since-inspection", "2" * 64)])
    changed = scenario.registries()
    code, result = scenario.install(review)
    check(code != 0 and scenario.registries() == changed, f"stale current CAS changed targets: {result}")
    return {"case": "refusals", "principal": True, "reviewDigest": True, "fixtureConfig": True, "destinationConfig": True, "currentCAS": True,
            "targetChanges": 0}


def crash_recovery(root: Path, evidence: Path, world: World, owned: list[Scenario], *, foreign: bool) -> dict:
    scenario = Scenario(root, evidence, world, "crash-foreign" if foreign else "crash-recover")
    owned.append(scenario)
    scenario.prepare()
    review = scenario.inspect()
    code, _ = scenario.install(review, crash=True, raw=True)
    check(code == 75, "test-owned crash did not fire after the first actual registry replace")
    halfway = scenario.registries()
    check(halfway[0] != scenario.before_registries[0] and halfway[1] == scenario.before_registries[1], "crash was not between the registry replacements")
    scenario.assert_startup_barrier()
    before_status = snapshot(scenario.workspace.root)
    code, status = scenario.cli("status", "--installation-id", review["installationId"])
    check(code == 0 and snapshot(scenario.workspace.root) == before_status, f"status failed or wrote files: {status}")
    args = ("--installation-id", review["installationId"], "--expected-transaction-digest", status["transactionDigest"])
    code, result = scenario.cli("recover", "--installation-id", review["installationId"], "--expected-transaction-digest", "0" * 64)
    check(code != 0 and scenario.registries() == halfway, f"wrong recovery pin changed targets: {result}")
    if foreign:
        changed = json.loads(halfway[0])
        changed["approvals"] = [item for item in changed["approvals"] if item["jobId"] != PLAIN]
        scenario.workspace.approvals.write_text(canonical(changed), encoding="utf-8")
        third = scenario.registries()
        code, result = scenario.cli("recover", *args)
        check(code != 0 and scenario.registries() == third, f"recovery overwrote a third-state edit: {result}")
        scenario.assert_startup_barrier()
    else:
        code, result = scenario.cli("recover", *args)
        check(code == 0 and scenario.registries() == scenario.before_registries and "aborted" in canonical(result), f"exact recovery did not safely abort: {result}")
        aborted_receipt = result
        service = scenario.start()
        service.close()
        aborted_targets = scenario.target_state()
        code, result = scenario.install(review)
        check(code == 0 and result == aborted_receipt and scenario.target_state() == aborted_targets,
              f"an aborted operation was silently applied again: {result}")
    return {"case": "crash-foreign" if foreign else "crash-recover", "crashAfterFirstReplace": True, "startupLedgerWrites": 0,
            "wrongRecoveryPinRefused": True, "foreignEditPreserved": foreign, "exactRecoveryAborted": not foreign}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, help="Retained synthetic command output and service logs (default: a new temporary evidence directory)")
    args = parser.parse_args()
    evidence = args.evidence_dir.resolve() if args.evidence_dir else Path(tempfile.mkdtemp(prefix="zoop-plan-install-evidence-")).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="zoop-plan-install-smoke-")).resolve()
    owned: list[Scenario] = []
    results: list[dict] = []
    outcome = "failed"
    failure = None
    try:
        world = build_world(root / "world")
        before = {"ingestion": tree(world.ingestion), "extraction": tree(world.extraction)}
        results.append(flow(root, evidence, world, owned))
        results.append(refusals(root, evidence, world, owned))
        results.append(crash_recovery(root, evidence, world, owned, foreign=False))
        results.append(crash_recovery(root, evidence, world, owned, foreign=True))
        check({"ingestion": tree(world.ingestion), "extraction": tree(world.extraction)} == before, "operator world was modified")
        outcome = "passed"
    except (AssertionError, OSError, ValueError, KeyError, subprocess.SubprocessError, httpx.HTTPError) as error:
        failure = str(error)
    finally:
        for scenario in owned:
            try:
                scenario.close()
            except (AssertionError, OSError, RuntimeError, subprocess.SubprocessError) as error:
                outcome, failure = "failed", f"cleanup: {error}; prior failure: {failure}"
        remove_tree(root)
        summary = {"status": outcome, "cases": results, "failure": failure, "evidenceDir": str(evidence)}
        (evidence / "summary.json").write_text(canonical(summary) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if outcome == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
