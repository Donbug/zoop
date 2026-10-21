"""Harness for the S3 relation-job tests: a real uvicorn service, the real installed `zoop-ai-relation` and a fresh synthetic operator world.

The service lock stays public: the pipeline is reached only as an installed command (`ai/pipeline/.venv/bin/zoop-ai-relation`) and,
for the operator side of the harness, as the interpreter that builds the world. Nothing here imports `zoop_ai_pipeline`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

TESTS = Path(__file__).resolve().parents[1] / "tests"
sys.path.insert(0, str(TESTS))

from support import ServiceProcess, Workspace, canonical, merged_grants, wait_for  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
PIPELINE = ROOT / "ai" / "pipeline"
PIPELINE_BIN = PIPELINE / ".venv" / "bin"
PIPELINE_PYTHON = PIPELINE_BIN / "python"
RELATION_CLI = PIPELINE_BIN / "zoop-ai-relation"
BUILD_WORLD = Path(__file__).resolve().parent / "build_world.py"
RUNTIME_SCHEMA = "zoop-relation-s3"
SCHEMA = "zoop-ai-internal-relation-1"
UPSTREAMS_SCHEMA = "zoop-ai-relation-upstreams-1"
JOB = "relation-job-1"
PGREP = "pgrep"

# Keys that exist in the pipeline payload (or its stored binding) and must never reach a caller.
PRIVATE_KEYS = frozenset({
    "binding", "fixtureHash", "requestDigest", "responseDigest", "creatorJobId", "rawVersion", "textArtifactId", "rawLocatorIds", "sourceSegments",
    "evidenceId", "relationKey", "facts", "claims", "quotes", "reviewer", "note", "attempt", "mapped", "target", "relationFacts"})

def require_pipeline() -> None:
    """The pipeline targets fail, they never skip: a green run must mean the real pipeline ran."""
    for path in (PIPELINE_PYTHON, RELATION_CLI):
        assert path.is_file() and os.access(path, os.X_OK), f"{path} is missing: run `make pipeline-install` before service-pipeline-test"


@dataclass
class World:
    root: Path
    extraction: Path
    ingestion: Path
    registry: Path
    upstream: dict[str, str]
    producer: Path
    verifier: Path
    empty_producer: Path
    empty_verifier: Path
    relations: dict[str, str]
    counts: dict[str, Any]
    replay_calls: int
    source_texts: list[str]
    held: str                # the relation candidate on HOLD: the only one a review may target
    held_revision: int       # its runtime event-chain revision at the end of the job's initial run
    eligible: str            # the relation candidate that is already eligible
    s2_request: dict[str, Any]        # the authored S2 Submit the operator job was built from (topic requested)
    s2_plain_request: dict[str, Any]  # the same without a topic stage, under the job id `s2-plain`
    s2_replay: Path
    s2_topic: Path
    s2_counts: dict[str, Any]
    s2_replay_calls: int


def build_world(root: Path) -> World:
    require_pipeline()
    root.mkdir(parents=True, exist_ok=True)
    done = subprocess.run([str(PIPELINE_PYTHON), str(BUILD_WORLD), str(PIPELINE), str(root)], capture_output=True, text=True, timeout=600,
                          env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"})
    assert done.returncode == 0, done.stderr[-4000:] + done.stdout[-2000:]
    info = json.loads(done.stdout.strip().splitlines()[-1])
    return World(Path(info["root"]), Path(info["extraction"]), Path(info["ingestion"]), Path(info["registry"]), info["upstream"],
                 Path(info["producer"]), Path(info["verifier"]), Path(info["emptyProducer"]), Path(info["emptyVerifier"]), info["relations"],
                 info["counts"], info["replayCalls"], info["sourceTexts"], info["held"], info["heldRevision"], info["eligible"],
                 info["s2Request"], info["s2PlainRequest"], Path(info["s2Replay"]), Path(info["s2Topic"]),
                 info["s2Counts"], info["s2ReplayCalls"])


def tree(path: Path) -> dict[str, tuple[int, int, str]]:
    """Mode, size and content hash of every file under a directory (the proof that a read-only upstream was left alone)."""
    found: dict[str, tuple[int, int, str]] = {}
    for item in sorted(path.rglob("*")):
        if item.is_file():
            found[str(item.relative_to(path))] = (item.stat().st_mode & 0o777, item.stat().st_size, hashlib.sha256(item.read_bytes()).hexdigest())
    return found


class RelationWorkspace(Workspace):
    """One service's fresh state. The world's ingestion/extraction directories are shared and read-only; everything that tests mutate
    (source registry, fixtures, upstream allowlist, wrapper) is a private copy."""

    def __init__(self, root: Path, world: World, *, producer: Path | None = None, verifier: Path | None = None, listed: tuple[str, ...] = ("alpha", "beta")):
        super().__init__(root, replay=None, grants=merged_grants())
        self.world = world
        self.relation_state = root / "relation"
        self.app_state = root / "app"
        self.app_state.mkdir()
        self.sources = root / "sources.json"
        self.producer = root / "producer.json"
        self.verifier = root / "verifier.json"
        self.upstreams = root / "upstreams.json"
        self.command = RELATION_CLI
        shutil.copyfile(world.registry, self.sources)
        shutil.copyfile(producer or world.producer, self.producer)
        shutil.copyfile(verifier or world.verifier, self.verifier)
        self.write_upstreams([(name, world.upstream["jobId"], world.upstream["inputDigest"]) for name in listed])

    def write_upstreams(self, entries: list[tuple[str, str, str]]) -> None:
        self.upstreams.write_text(json.dumps({"schemaVersion": UPSTREAMS_SCHEMA, "upstreams": [
            {"principal": principal, "jobId": job_id, "inputDigest": digest} for principal, job_id, digest in entries]}))

    def env(self, **overrides: str | None) -> dict[str, str]:
        env = super().env()
        env.update({
            "ZOOP_AI_SERVICE_RELATION_COMMAND": str(self.command), "ZOOP_AI_RELATION_STATE_DIR": str(self.relation_state),
            "ZOOP_AI_EXTRACTION_STATE_DIR": str(self.world.extraction), "ZOOP_AI_INGESTION_STATE_DIR": str(self.world.ingestion),
            "ZOOP_AI_SERVICE_SOURCES": str(self.sources), "ZOOP_AI_SERVICE_RELATION_REPLAY": str(self.producer),
            "ZOOP_AI_SERVICE_RELATION_VERIFIER_REPLAY": str(self.verifier), "ZOOP_AI_SERVICE_RELATION_UPSTREAMS": str(self.upstreams),
            "ZOOP_STATE_DIR": str(self.app_state)})
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    def private_strings(self) -> list[str]:
        return [*super().private_strings(), str(self.relation_state), str(self.world.extraction), str(self.world.ingestion), str(self.sources),
                str(self.producer), str(self.verifier), str(self.upstreams), str(RELATION_CLI), str(self.app_state)]

    def revoke_source(self, enabled: bool) -> None:
        registry = json.loads(self.sources.read_text(encoding="utf-8"))
        registry["sources"][0]["grant"]["enabled"] = enabled
        self.sources.write_text(canonical(registry), encoding="utf-8")

    def use_fixtures(self, producer: Path, verifier: Path) -> None:
        shutil.copyfile(producer, self.producer)
        shutil.copyfile(verifier, self.verifier)

    def write_wrapper(self, hook: str) -> Path:
        """An executable stand-in command that runs the REAL installed relation CLI module after arming one process-kill fault inside the
        pipeline engine (the pipeline's own smoke uses the same technique). The fault fires only while `arm` exists and only for `resume`,
        and disarms itself, so exactly one child dies. Everything else about the command is the real thing."""
        script = self.root / "relation-wrapper.py"
        arm = self.root / "arm"
        script.write_text(
            f"#!{PIPELINE_PYTHON}\nimport os, runpy, sys\nfrom zoop_ai_pipeline.relation import Engine\n"
            f"if sys.argv[1:2] == ['resume'] and os.path.exists({str(arm)!r}):\n    os.unlink({str(arm)!r})\n"
            + "".join(f"    {line}\n" for line in hook.splitlines())
            + "sys.argv[0] = 'zoop-ai-relation'\nrunpy.run_module('zoop_ai_pipeline.relation_cli', run_name='__main__')\n", encoding="utf-8")
        script.chmod(0o755)
        self.command = script
        return script

    def arm(self) -> None:
        (self.root / "arm").write_text("1")

    def go(self) -> None:
        """Release a service started with ZOOP_TEST_RELATION_HOLD_FILE."""
        (self.root / "go").write_text("1")

    # ---- a real orphan: a review child paused BEFORE it takes the pipeline's ledger lock (see REVIEW_GATE_WRAPPER) ----

    def write_review_gate_wrapper(self) -> Path:
        """Install the test-owned stand-in command that runs the REAL installed relation CLI, except that a `review` child can be made to pause
        before the real CLI starts, to release such a paused child, or to run an operator's own review first. Nothing in the service or the
        pipeline knows about it: it is only the command the service was configured with."""
        script = self.root / "relation-wrapper.py"
        script.write_text(REVIEW_GATE_WRAPPER.replace("__PYTHON__", str(PIPELINE_PYTHON)).replace("__ROOT__", repr(str(self.root))), encoding="utf-8")
        script.chmod(0o755)
        self.command = script
        return script

    def pause_next_review(self) -> None:
        (self.root / "pause-next-review").write_text("1")

    def release_orphan_before_next_review(self) -> None:
        """The next review child first lets the paused orphan run to completion (its event is committed, its lock released), then runs for real."""
        (self.root / "release-orphan-before-next-review").write_text("1")

    def foreign_review_before_next_review(self, relation: str, *, expected_revision: int = 1) -> None:
        """The next review child first appends an OPERATOR's allow (free-text note, no operation marker) with the real CLI, then runs for real."""
        (self.root / "foreign.json").write_text(canonical({
            "schemaVersion": RUNTIME_SCHEMA, "jobId": JOB, "relationCandidateId": relation, "expectedRevision": expected_revision,
            "decision": "allow", "reviewer": "operator", "note": "operator note"}))
        (self.root / "foreign-review-before-next-review").write_text("1")

    def orphan_pid(self) -> int | None:
        path = self.root / "orphan.pid"
        return int(path.read_text()) if path.exists() else None

    def orphan_done(self) -> bool:
        return (self.root / "orphan-done").exists()


CRASH_UNKNOWN = "Engine._receive = lambda *a: os._exit(75)"
CRASH_AFTER_RELATION_STAGE = "Engine._stage_saved = lambda self, stage: os._exit(75) if stage == 'relation' else None"
# The first receipt a child saves is committed, and then the process dies before anything else is written (the pipeline smoke's `receipt:1`).
CRASH_AFTER_FIRST_RECEIPT = ("original = Engine._receive\ncount = [0]\ndef stop(self, *a):\n    original(self, *a)\n    count[0] += 1\n"
                             "    if count[0] == 1:\n        os._exit(75)\nEngine._receive = stop")
# What a status, an error or an operation may never carry. `reviewer` is deliberately absent: an operation names the principal that decided.
OPERATION_PRIVATE = PRIVATE_KEYS - {"reviewer"}
MARKER = "zoop-ai-service-review:"
REVIEW_GATE_WRAPPER = '''#!__PYTHON__
"""Test-only stand-in for zoop-ai-relation. Only a `review` child is ever treated differently, and only while a marker file asks for it:
  pause-next-review                      this child is an ORPHAN-TO-BE: it records its pid and waits BEFORE the real CLI starts, so before the
                                         pipeline's ledger lock is taken (a killed service leaves it alive; it holds no lock)
  release-orphan-before-next-review      this child first releases the paused orphan and waits until it has finished, then runs for real
  foreign-review-before-next-review      this child first runs an operator's own review (foreign.json), then runs for real
Everything else, including every other command, is the real installed CLI."""
import os, runpy, subprocess, sys, time

ROOT = __ROOT__


def marker(name):
    return os.path.join(ROOT, name)


def wait_for(path):
    end = time.time() + 90
    while not os.path.exists(path):
        if time.time() > end:
            os._exit(79)
        time.sleep(0.05)


orphan = False
if sys.argv[1:2] == ['review']:
    if os.path.exists(marker('pause-next-review')):
        os.unlink(marker('pause-next-review'))
        orphan = True
        with open(marker('orphan.pid.tmp'), 'w') as handle:
            handle.write(str(os.getpid()))
        os.replace(marker('orphan.pid.tmp'), marker('orphan.pid'))
        wait_for(marker('orphan-go'))
    elif os.path.exists(marker('release-orphan-before-next-review')):
        os.unlink(marker('release-orphan-before-next-review'))
        open(marker('orphan-go'), 'w').close()
        wait_for(marker('orphan-done'))
    elif os.path.exists(marker('foreign-review-before-next-review')):
        os.unlink(marker('foreign-review-before-next-review'))
        with open(marker('foreign.json'), 'rb') as handle:
            subprocess.run([sys.executable, '-m', 'zoop_ai_pipeline.relation_cli', *sys.argv[1:]], input=handle.read(), env=os.environ,
                           check=True, stdout=subprocess.DEVNULL)
sys.argv[0] = 'zoop-ai-relation'
try:
    runpy.run_module('zoop_ai_pipeline.relation_cli', run_name='__main__')
finally:
    if orphan:
        open(marker('orphan-done'), 'w').close()  # after the CLI closed its store: the lock is released and the event is committed
'''


class RelationService(ServiceProcess):
    def rsubmit(self, job_id: str = JOB, *, as_: str = "alpha", upstream: dict[str, str] | None = None, key: str | None = None,
                provenance: dict[str, str] | None = None, extra: dict[str, Any] | None = None) -> httpx.Response:
        world = self.workspace.world
        body = {"schemaVersion": RUNTIME_SCHEMA, "jobId": job_id,
                "provenance": provenance or {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"},
                "upstream": upstream or dict(world.upstream), **(extra or {})}
        return self.request("POST", "/internal/v1/relation-jobs", as_=as_, body=body, key=key or job_id)

    def rstatus(self, job_id: str = JOB, *, as_: str = "alpha") -> httpx.Response:
        return self.request("GET", f"/internal/v1/relation-jobs/{job_id}", as_=as_)

    def rresult(self, job_id: str = JOB, *, as_: str = "alpha") -> httpx.Response:
        return self.request("GET", f"/internal/v1/relation-jobs/{job_id}/result", as_=as_)

    def rcancel(self, job_id: str = JOB, *, as_: str = "alpha") -> httpx.Response:
        return self.request("POST", f"/internal/v1/relation-jobs/{job_id}/cancel", as_=as_)

    def rrecover(self, job_id: str = JOB, *, as_: str = "alpha") -> httpx.Response:
        return self.request("POST", f"/internal/v1/relation-jobs/{job_id}/recover", as_=as_)

    def rwait(self, job_id: str = JOB, states: set[str] | None = None, *, dispatch: set[str] | None = None, timeout: float = 90,
              as_: str = "alpha") -> dict[str, Any]:
        """Poll status until the job is in one of `states` and its dispatch row is in one of `dispatch`. A 503 `runtime_busy` is a retry."""
        def reached() -> dict[str, Any] | None:
            response = self.rstatus(job_id, as_=as_)
            if response.status_code == 503:
                return None
            assert response.status_code == 200, response.text
            body = response.json()
            if (states is None or body["state"] in states) and (dispatch is None or body["dispatch"]["state"] in dispatch):
                return body
            return None
        return wait_for(reached, timeout, 0.25, f"{job_id} in {sorted(states or [])} / {sorted(dispatch or [])}")

    def rsettled(self, job_id: str = JOB, *, as_: str = "alpha", timeout: float = 90) -> dict[str, Any]:
        return self.rwait(job_id, dispatch={"idle"}, timeout=timeout, as_=as_)

    def stay(self, job_id: str, seconds: float = 2.5, *, as_: str = "alpha") -> dict[str, Any]:
        """Observe that nothing happens: the status after a quiet period, with the dispatch count it must not have moved."""
        time.sleep(seconds)
        return self.rwait(job_id, as_=as_)

    def rreview(self, key: str, relation: str, *, decision: str = "allow", revision: str | int = 1, version: str | None = None, job_id: str = JOB,
                as_: str = "alpha", extra: dict[str, Any] | None = None, raw_key: str | None = None) -> httpx.Response:
        """POST one review. `version` defaults to the job's own `inputDigest` (its `sourceVersion`), read from the status first."""
        if version is None:
            version = self.rstatus(job_id, as_=as_).json()["inputDigest"]
        body = {"relationCandidateId": relation, "expectedSourceVersion": version, "expectedSourceRevision": str(revision), "decision": decision,
                **(extra or {})}
        return self.request("POST", f"/internal/v1/relation-jobs/{job_id}/reviews", as_=as_, body=body, key=raw_key or key)

    def roperation(self, key: str, job_id: str = JOB, *, as_: str = "alpha") -> httpx.Response:
        return self.request("GET", f"/internal/v1/relation-jobs/{job_id}/reviews/{key}", as_=as_)

    def reviewed(self, key: str, *, job_id: str = JOB, timeout: float = 90, as_: str = "alpha") -> dict[str, Any]:
        """Poll an operation until its review is recorded. Operation reads never touch the pipeline, so a 503 is a real failure."""
        def reached() -> dict[str, Any] | None:
            response = self.roperation(key, job_id, as_=as_)
            assert response.status_code == 200, response.text
            body = response.json()
            return body if body["review"]["state"] == "applied" else None
        return wait_for(reached, timeout, 0.25, f"operation {key} review applied")

    def result_relation(self, relation: str, job_id: str = JOB, *, as_: str = "alpha") -> dict[str, Any]:
        """One relation of a delivered result (the job must be ready and every delivery gate must hold)."""
        envelope = self.rresult(job_id, as_=as_).json()
        assert envelope["delivery"]["state"] == "available", envelope["delivery"]
        return next(item for item in envelope["job"]["relations"] if item["relationCandidateId"] == relation)


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def review_into_an_orphan(service: RelationService, key: str, relation: str, version: str) -> int:
    """POST a review whose child is paused before it takes the pipeline's ledger lock, then SIGKILL the service. The child runs in its own session,
    so it outlives the service: a real orphan that will append the operation's event later, with no hook in the service or the pipeline.
    Returns the orphan's pid."""
    service.workspace.pause_next_review()
    failures: list[Exception] = []

    def post() -> None:
        try:
            service.rreview(key, relation, version=version)
        except httpx.HTTPError as error:  # the service is killed under the request
            failures.append(error)

    poster = threading.Thread(target=post, daemon=True)
    poster.start()
    pid = wait_for(service.workspace.orphan_pid, 60, 0.05, "a review child paused before the pipeline lock")
    service.kill()
    poster.join(30)
    assert not poster.is_alive() and failures, "the request must have died with the service"
    assert process_alive(pid), "the paused child must outlive its service"
    return pid


def inspect_direct(workspace: RelationWorkspace, job_id: str) -> tuple[int, dict[str, Any]]:
    """`zoop-ai-relation inspect` straight against the service's pipeline ledger (the service must be idle: the ledger lock does not wait)."""
    return pipeline_cli(workspace, "inspect", {"schemaVersion": RUNTIME_SCHEMA, "jobId": job_id})


def pipeline_cli(workspace: RelationWorkspace, command: str, payload: dict[str, Any], *extra: str) -> tuple[int, dict[str, Any]]:
    env = {"PATH": "/usr/bin:/bin", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "ZOOP_STATE_DIR": str(workspace.app_state),
           "ZOOP_AI_WORKER_STATE_DIR": str(workspace.worker)}
    argv = [str(RELATION_CLI), command, "--state-dir", str(workspace.relation_state), "--extraction-state-dir", str(workspace.world.extraction),
            "--ingestion-state-dir", str(workspace.world.ingestion), "--sources", str(workspace.sources), *extra]
    done = subprocess.run(argv, input=canonical(payload).encode(), capture_output=True, env=env, timeout=120)
    return done.returncode, json.loads(done.stdout.decode())


def direct_relation(workspace: RelationWorkspace, relation: str, job_id: str = JOB) -> dict[str, Any]:
    """One relation of `zoop-ai-relation inspect` against the service's pipeline ledger, with its FULL append-only history (reviewer and note
    included). The service must be idle: the ledger lock does not wait."""
    code, direct = inspect_direct(workspace, job_id)
    assert code == 0 and direct["delivery"]["status"] == "current", direct.get("delivery")
    return next(item for item in direct["relations"] if item["relationCandidateId"] == relation)


def ledger_rows(workspace: RelationWorkspace, sql: str) -> list[tuple]:
    """A read-only query against the service's own relation ledger."""
    database = sqlite3.connect(f"file:{workspace.state / 'relation-jobs.sqlite3'}?mode=ro", uri=True)
    try:
        return database.execute(sql).fetchall()
    finally:
        database.close()


def relation_processes(workspace: RelationWorkspace) -> list[int]:
    """Pids of live relation children bound to this workspace's pipeline ledger (exact owned argv; pgrep exit 1 is a genuine no-match)."""
    pattern = (r"(zoop-ai-relation|relation-wrapper\.py) (submit|inspect|resume|cancel|review) --state-dir "
               + re.escape(str(workspace.relation_state)) + r"( |$)")
    found = subprocess.run([PGREP, "-f", "--", pattern], capture_output=True, text=True)
    if found.returncode == 1:
        return []
    if found.returncode != 0:
        raise RuntimeError(f"pgrep failed with exit {found.returncode}")
    return [int(pid) for pid in found.stdout.split() if int(pid) != os.getpid()]


def terminate_relation(workspace: RelationWorkspace, timeout: float = 10.0) -> None:
    end = time.monotonic() + timeout
    while True:
        pids = relation_processes(workspace)
        if not pids:
            return
        if time.monotonic() >= end:
            raise AssertionError(f"relation children still alive: {pids}")
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(0.1)


def walk_keys(node: Any):
    """Every dict key in a JSON tree."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from walk_keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_keys(value)


APPROVAL_BASIS_KEYS = {"kind", "revision", "reviewer", "decidedAt"}


def delivered_keys(node: Any):
    """`walk_keys` for a DELIVERED relation result: the one designated audit field `approvalBasis` is a closed object `{kind, revision, reviewer, decidedAt}`
    (the automatic verifier has `reviewer: null`, an operator's final approval names the approving principal). It is checked exactly and not descended into;
    EVERY other key, including a `reviewer` or `note` anywhere else (the raw review history), is still reported and so still private."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            if key == "approvalBasis" and value is not None:
                assert isinstance(value, dict) and set(value) == APPROVAL_BASIS_KEYS, value
                assert value["kind"] in ("automatic-verifier", "operator-final-approval")
                assert (value["reviewer"] is None) == (value["kind"] == "automatic-verifier") and isinstance(value["revision"], int), value
                continue
            yield from delivered_keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from delivered_keys(value)
