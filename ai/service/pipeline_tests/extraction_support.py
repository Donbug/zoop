"""Harness for the S2 extraction-job tests: a real uvicorn service, the real installed `zoop-ai-extract` (and, for the chain, `zoop-ai-relation`) and the
synthetic operator world of `relation_support`. The service-side S2 ledger starts EMPTY in every workspace: the job under test is produced by the
service itself, from the authored request and fixtures the operator world was built from.

Nothing here imports `zoop_ai_pipeline`. The pipeline is reached only as installed commands. Every S2 child runs through a test-owned stand-in command
that executes the REAL `zoop_ai_pipeline.extraction_cli` after (a) installing an audit hook that records, and refuses, any network syscall, and (b)
optionally arming ONE process-kill fault inside the pipeline engine (the pipeline's own smoke uses the same technique). Nothing in the service or the
pipeline knows about it: it is only the command the service was configured with.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from relation_support import PIPELINE_BIN, PIPELINE_PYTHON, RelationService, RelationWorkspace, World, canonical, wait_for
from support import Workspace

EXTRACT_CLI = PIPELINE_BIN / "zoop-ai-extract"
RUNTIME_SCHEMA = "zoop-extraction-s2-2"
SCHEMA = "zoop-ai-internal-extraction-1"
APPROVALS_SCHEMA = "zoop-ai-extraction-approvals-1"
JOB = "s2-job"
PLAIN = "s2-plain"
PGREP = "pgrep"
S3_ONLY = ("ZOOP_AI_SERVICE_RELATION_COMMAND", "ZOOP_AI_RELATION_STATE_DIR", "ZOOP_AI_SERVICE_RELATION_REPLAY",
           "ZOOP_AI_SERVICE_RELATION_VERIFIER_REPLAY", "ZOOP_AI_SERVICE_RELATION_UPSTREAMS")

STATUS_KEYS = {"schemaVersion", "jobId", "inputDigest", "approval", "provenance", "state", "phase", "resumeMode", "failure", "usage", "stages", "delivery",
               "dispatch", "next", "acceptedAt", "observedAt"}
# What a status, an error or a withheld result may never carry (pipeline keys and stored identity).
PRIVATE_KEYS = frozenset({"binding", "fixtureHash", "requestDigest", "responseDigest", "creatorJobId", "rawVersion", "textArtifactId", "rawLocatorIds",
                          "sourceSegments", "groupDigest", "snapshotDigest", "requestKey", "original", "calls", "replay", "adapter"})
# Keys a DELIVERED result may carry that the strict projection must never add: stored identity of the pipeline's artifacts.
CONTENT_PRIVATE = frozenset({"binding", "fixtureHash", "requestDigest", "responseDigest", "creatorJobId", "textArtifactId", "rawLocatorIds", "sourceSegments",
                             "groupDigest", "snapshotDigest", "requestKey", "inputKind", "rawVersion"})

# Process-kill faults (the pipeline smoke's own technique): a child dies at a named boundary of the real engine.
CRASH_UNKNOWN = "Extractor._receive = lambda *a: os._exit(75)"
CRASH_AFTER_EXTRACT_STAGE = "Extractor._stage_saved = lambda self, stage: os._exit(75) if stage == 'extract' else None"
CRASH_AFTER_FIRST_RECEIPT = ("original = Extractor._receive\ncount = [0]\ndef stop(self, *a):\n    original(self, *a)\n    count[0] += 1\n"
                             "    if count[0] == 1:\n        os._exit(75)\nExtractor._receive = stop")

WRAPPER = '''#!__PYTHON__
"""Test-only stand-in for zoop-ai-extract: the real CLI behind a network audit and (while `arm` exists, for one command only) one fault."""
import os, runpy, sys
ROOT = __ROOT__


def audit(event, args):
    if event.startswith("socket.") and event.split(".", 1)[1] in ("connect", "getaddrinfo", "gethostbyname", "gethostbyaddr", "bind", "sendto"):
        with open(os.path.join(ROOT, "network-attempt"), "a") as handle:
            handle.write(event + "\\n")
        raise RuntimeError("network attempted")


sys.addaudithook(audit)
from zoop_ai_pipeline.extraction import Extractor
__HOOKS__
sys.argv[0] = 'zoop-ai-extract'
runpy.run_module('zoop_ai_pipeline.extraction_cli', run_name='__main__')
'''


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ExtractionWorkspace(RelationWorkspace):
    """One service's fresh state with the S2 group configured over its OWN empty extraction ledger. `chain=True` also configures the S3 group on that
    same ledger (and the same ingestion root and source registry), with an empty S3 upstream allowlist: authorizing an S2 job as an S3 upstream is an
    explicit operator act of the test."""

    def __init__(self, root: Path, world: World, *, chain: bool = False, topic: bool = True, requests: tuple[str, ...] = (JOB, PLAIN)):
        assert EXTRACT_CLI.is_file() and os.access(EXTRACT_CLI, os.X_OK), f"{EXTRACT_CLI} is missing: run `make pipeline-install` before service-pipeline-test"
        super().__init__(root, world, listed=())
        self.chain = chain
        self.extraction_state = root / "extraction"
        self.extraction_state.mkdir()
        self.s2_command = EXTRACT_CLI
        self.s2_replay = root / "s2-replay.json"
        self.s2_topic = root / "s2-topic.json"
        self.s2_replay.write_bytes(world.s2_replay.read_bytes())
        self.s2_topic.write_bytes(world.s2_topic.read_bytes())
        self.approvals = root / "approvals.json"
        self.topic_configured = topic
        self.requests = {JOB: world.s2_request, PLAIN: world.s2_plain_request}
        self.write_approvals({"alpha": [r for r in requests], "beta": [PLAIN] if PLAIN in requests else []})
        self.write_wrapper(hooks="")

    # ---- the operator's side: approvals, fixtures, wrapper ----

    def entry(self, principal: str, job_id: str, request: dict[str, Any] | None = None, *, replay: str | None = None, topic: str | None = "auto") -> dict[str, Any]:
        request = self.requests[job_id] if request is None else request
        wants_topic = request["topic"] is not None
        return {"principal": principal, "jobId": job_id, "approvedRequestDigest": digest(request), "request": request,
                "producerReplayDigest": replay or file_hash(self.s2_replay),
                "topicReplayDigest": (file_hash(self.s2_topic) if topic == "auto" else topic) if wants_topic else None}

    def write_approvals(self, listed: dict[str, list[str]], **overrides: Any) -> None:
        self.listed = listed
        entries = [self.entry(principal, job_id, **overrides) for principal, jobs in listed.items() for job_id in jobs]
        self.write_entries(entries)

    def refresh_approvals(self) -> None:
        """The operator re-pins the approvals to the fixture files as they are now."""
        self.write_approvals(self.listed)

    def write_entries(self, entries: list[dict[str, Any]]) -> None:
        self.approvals.write_text(json.dumps({"schemaVersion": APPROVALS_SCHEMA, "approvals": entries}, ensure_ascii=False), encoding="utf-8")

    def approved_digest(self, job_id: str = JOB) -> str:
        return digest(self.requests[job_id])

    def use_topic(self, raw: bytes, *, repin: bool) -> None:
        self.s2_topic.write_bytes(raw)
        if repin:
            self.refresh_approvals()

    def rotate_topic(self) -> None:
        """The operator's topic fixture file now holds other bytes (a semantically identical document, so only its digest moved)."""
        self.s2_topic.write_bytes(self.s2_topic.read_bytes() + b"\n")

    def rotate_producer(self) -> None:
        self.s2_replay.write_bytes(self.s2_replay.read_bytes() + b"\n")

    def write_wrapper(self, hooks: str = "", command: str = "resume") -> Path:  # type: ignore[override]
        """The stand-in command. `hooks` run inside the child, once, only for `command` (`resume` or `submit`) and only while `arm()` was called."""
        script = self.root / "extract-wrapper.py"
        arm = self.root / "extract-arm"
        body = (f"if sys.argv[1:2] == [{command!r}] and os.path.exists({str(arm)!r}):\n    os.unlink({str(arm)!r})\n"
                + "".join(f"    {line}\n" for line in hooks.splitlines())) if hooks else ""
        script.write_text(WRAPPER.replace("__PYTHON__", str(PIPELINE_PYTHON)).replace("__ROOT__", repr(str(self.root))).replace("__HOOKS__", body),
                          encoding="utf-8")
        script.chmod(0o755)
        self.s2_command = script
        return script

    def arm(self) -> None:  # type: ignore[override]
        (self.root / "extract-arm").write_text("1")

    def go(self) -> None:  # type: ignore[override]
        (self.root / "extract-go").write_text("1")

    def network_attempts(self) -> str:
        path = self.root / "network-attempt"
        return path.read_text() if path.exists() else ""

    def env(self, **overrides: str | None) -> dict[str, str]:
        env = super().env()
        if not self.chain:
            for name in S3_ONLY:
                env.pop(name, None)
        env.update({
            "ZOOP_AI_SERVICE_EXTRACTION_COMMAND": str(self.s2_command), "ZOOP_AI_EXTRACTION_STATE_DIR": str(self.extraction_state),
            "ZOOP_AI_SERVICE_EXTRACTION_REPLAY": str(self.s2_replay), "ZOOP_AI_SERVICE_EXTRACTION_APPROVALS": str(self.approvals)})
        if self.topic_configured:
            env["ZOOP_AI_SERVICE_EXTRACTION_TOPIC_REPLAY"] = str(self.s2_topic)
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    def private_strings(self) -> list[str]:
        return [*super().private_strings(), str(self.extraction_state), str(self.s2_replay), str(self.s2_topic), str(self.approvals),
                str(self.s2_command), str(EXTRACT_CLI)]


class ExtractionService(RelationService):
    """The S2 routes (and, with `chain`, the S3 helpers it inherits) of one real service process."""

    def esubmit(self, job_id: str = JOB, *, as_: str = "alpha", digest_: str | None = None, key: str | None = None,
                extra: dict[str, Any] | None = None) -> httpx.Response:
        body = {"schemaVersion": RUNTIME_SCHEMA, "jobId": job_id, "approvedRequestDigest": digest_ or self.workspace.approved_digest(job_id), **(extra or {})}
        return self.request("POST", "/internal/v1/extraction-jobs", as_=as_, body=body, key=key or job_id)

    def estatus(self, job_id: str = JOB, *, as_: str = "alpha") -> httpx.Response:
        return self.request("GET", f"/internal/v1/extraction-jobs/{job_id}", as_=as_)

    def eresult(self, job_id: str = JOB, *, as_: str = "alpha") -> httpx.Response:
        return self.request("GET", f"/internal/v1/extraction-jobs/{job_id}/result", as_=as_)

    def ecancel(self, job_id: str = JOB, *, as_: str = "alpha") -> httpx.Response:
        return self.request("POST", f"/internal/v1/extraction-jobs/{job_id}/cancel", as_=as_)

    def erecover(self, job_id: str = JOB, *, as_: str = "alpha") -> httpx.Response:
        return self.request("POST", f"/internal/v1/extraction-jobs/{job_id}/recover", as_=as_)

    def ewait(self, job_id: str = JOB, states: set[str] | None = None, *, dispatch: set[str] | None = None, timeout: float = 90,
              as_: str = "alpha") -> dict[str, Any]:
        """Poll status until the job is in one of `states` and its dispatch row is in one of `dispatch`. A 503 `runtime_busy` is a retry."""
        def reached() -> dict[str, Any] | None:
            response = self.estatus(job_id, as_=as_)
            if response.status_code == 503:
                return None
            assert response.status_code == 200, response.text
            body = response.json()
            if (states is None or body["state"] in states) and (dispatch is None or body["dispatch"]["state"] in dispatch):
                return body
            return None
        return wait_for(reached, timeout, 0.25, f"{job_id} in {sorted(states or [])} / {sorted(dispatch or [])}")

    def esettled(self, job_id: str = JOB, *, as_: str = "alpha", timeout: float = 90) -> dict[str, Any]:
        return self.ewait(job_id, dispatch={"idle"}, timeout=timeout, as_=as_)

    def estay(self, job_id: str = JOB, seconds: float = 2.5, *, as_: str = "alpha") -> dict[str, Any]:
        """Observe that nothing happens: the status after a quiet period."""
        time.sleep(seconds)
        return self.ewait(job_id, as_=as_)



def make_service(workspace: ExtractionWorkspace, **kwargs: Any) -> ExtractionService:
    return ExtractionService(workspace, **kwargs)


# ---- direct, operator-side access (the service must be idle: the pipeline's ledger lock does not wait) ----

def pipeline_env(workspace: ExtractionWorkspace) -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "ZOOP_STATE_DIR": str(workspace.app_state),
            "ZOOP_AI_WORKER_STATE_DIR": str(workspace.worker)}


def extract_cli(workspace: ExtractionWorkspace, command: str, payload: dict[str, Any], *extra: str) -> tuple[int, dict[str, Any]]:
    argv = [str(EXTRACT_CLI), command, "--state-dir", str(workspace.extraction_state), "--ingestion-state-dir", str(workspace.world.ingestion),
            "--sources", str(workspace.sources), *extra]
    done = subprocess.run(argv, input=canonical(payload).encode(), capture_output=True, env=pipeline_env(workspace), timeout=120)
    return done.returncode, json.loads(done.stdout.decode())


def inspect_direct(workspace: ExtractionWorkspace, job_id: str = JOB) -> tuple[int, dict[str, Any]]:
    return extract_cli(workspace, "inspect", {"schemaVersion": RUNTIME_SCHEMA, "jobId": job_id})


def operator_submit(workspace: ExtractionWorkspace, request: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """An OPERATOR registers a job the service never saw (the adoption attack surface)."""
    return extract_cli(workspace, "submit", request, "--replay", str(workspace.s2_replay))


def ledger_rows(workspace: ExtractionWorkspace, sql: str) -> list[tuple]:
    """A read-only query against the service's own extraction control ledger."""
    database = sqlite3.connect(f"file:{workspace.state / 'extraction-jobs.sqlite3'}?mode=ro", uri=True)
    try:
        return database.execute(sql).fetchall()
    finally:
        database.close()


def dispatch_row(workspace: ExtractionWorkspace) -> tuple:
    rows = ledger_rows(workspace, "SELECT state, dispatch_count, busy_count, last_outcome, last_runtime_code FROM extraction_dispatch")
    return rows[0]


def extraction_processes(workspace: ExtractionWorkspace) -> list[int]:
    """Pids of live S2 children bound to this workspace's ledger (exact owned argv; pgrep exit 1 is a genuine no-match)."""
    pattern = (r"(zoop-ai-extract|extract-wrapper\.py) (submit|inspect|resume|cancel) --state-dir " + re.escape(str(workspace.extraction_state)) + r"( |$)")
    found = subprocess.run([PGREP, "-f", "--", pattern], capture_output=True, text=True)
    if found.returncode == 1:
        return []
    if found.returncode != 0:
        raise RuntimeError(f"pgrep failed with exit {found.returncode}")
    return [int(pid) for pid in found.stdout.split() if int(pid) != os.getpid()]


def terminate_extraction(workspace: ExtractionWorkspace, timeout: float = 10.0) -> None:
    import signal
    end = time.monotonic() + timeout
    while True:
        pids = extraction_processes(workspace)
        if not pids:
            return
        if time.monotonic() >= end:
            raise AssertionError(f"extraction children still alive: {pids}")
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(0.1)


def walk_keys(node: Any):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from walk_keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_keys(value)
