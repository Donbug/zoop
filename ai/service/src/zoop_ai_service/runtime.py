"""The only door to the S1 runtime: five fixed `zoop-ai` commands, stdin JSON in, one canonical stdout JSON out.

Request data reaches the child only through an anonymous stdin file. The argv, environment and working directory are
server-owned. stderr is discarded, so runtime diagnostics, paths and secrets can never be relayed. The child runs in its own
session: a deadline or a stopping service never has to guess whether an in-flight provider call was charged, and a restarted
service never kills a process whose pid it does not know.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .config import ServiceConfig

RUNTIME_SCHEMA = "zoop-ai-s1-1"
# Covers the largest handoff export envelope: the producer's bundle limit is 6 MiB (MAX_BUNDLE, canonical bytes) plus a receipt and attempts well under 1 MiB.
MAX_STDOUT = 16 * 1024 * 1024
CODE = re.compile(r"[a-z][a-z0-9_]{0,79}")


@dataclass(frozen=True)
class Deadlines:
    quick: float = 30.0   # submit/get/cancel; matches the worker's SQLite busy timeout
    long: float = 300.0   # run/resume
    read: float = 45.0    # graph read/focus: the pipeline's Neo4j connect (5 s) and read transaction (30 s) limits, plus the ledgers
    handoff: float = 45.0  # handoff export: rebuilds the whole bundle from the S2/S3 ledgers (no Neo4j); the same fixed bound as a graph read
    grace: float = 5.0    # SIGTERM to SIGKILL


@dataclass(frozen=True)
class Outcome:
    """What one child process left behind.

    result      exit 0 with a runtime JobResult
    error       exit 2 with a runtime error code
    abnormal    killed by a signal, other exit code, or empty/invalid/unknown-schema output: the runtime may have progressed
    timeout     the deadline passed and the child group was terminated: the runtime may have progressed
    unavailable the child could not start or its output exceeded the cap
    abandoned   the service is stopping; the child was left running on purpose
    """
    kind: str
    result: dict[str, Any] | None = None
    code: str | None = None
    exit_code: int | None = None


class WorkerProcess:
    def __init__(self, config: ServiceConfig, deadlines: Deadlines = Deadlines(), env: Mapping[str, str] | None = None):
        self._config, self._deadlines = config, deadlines
        self._env = dict(config.child_env if env is None else env)

    def _argv(self, command: str, *, grants: bool, replay: bool, initial_only: bool = False) -> list[str]:
        argv = [str(self._config.worker_command), command, "--state-dir", str(self._config.worker_state_dir)]
        if initial_only:
            argv.append("--initial-only")
        if grants:
            argv += ["--grants", str(self._config.grants_path)]
        if replay and self._config.replay_path is not None:
            argv += ["--replay", str(self._config.replay_path)]
        return argv

    def submit(self, body: dict[str, Any]) -> Outcome:
        return self.execute(self._argv("submit", grants=True, replay=False), body, self._deadlines.quick)

    def get(self, job_id: str) -> Outcome:
        return self.execute(self._argv("get", grants=False, replay=False), _reference(job_id), self._deadlines.quick)

    def cancel(self, job_id: str) -> Outcome:
        return self.execute(self._argv("cancel", grants=False, replay=False), _reference(job_id), self._deadlines.quick)

    def run(self, job_id: str, stop: threading.Event | None = None, *, initial_only: bool = False) -> Outcome:
        """`initial_only` is the runtime's own under-lock restriction for automatic redispatch: it may start a job that never made
        a call, and otherwise only persist receipts already stored; it can never send a stage that was not already sent."""
        return self.execute(self._argv("run", grants=True, replay=True, initial_only=initial_only), _reference(job_id),
                             self._deadlines.long, stop)

    def resume(self, job_id: str, stop: threading.Event | None = None, *, initial_only: bool = False) -> Outcome:
        return self.execute(self._argv("resume", grants=True, replay=True, initial_only=initial_only), _reference(job_id),
                             self._deadlines.long, stop)

    def execute(self, argv: list[str], payload: dict[str, Any], deadline: float, stop: threading.Event | None = None,
                interpret: Callable[[int, bytes], Outcome] | None = None) -> Outcome:
        """Run one fixed command: payload through an anonymous stdin file, one canonical JSON out. `interpret` maps the exit code and
        stdout of another contract's runtime (the S3 door) to an Outcome; the default is the S1 contract."""
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        transport = self._config.transport_dir
        try:
            with tempfile.TemporaryFile(dir=transport) as stdin, tempfile.TemporaryFile(dir=transport) as stdout:
                stdin.write(data)
                stdin.flush()
                stdin.seek(0)
                try:
                    child = subprocess.Popen(argv, stdin=stdin, stdout=stdout, stderr=subprocess.DEVNULL, env=self._env,
                                             cwd=transport, start_new_session=True, close_fds=True)
                except OSError:
                    return Outcome("unavailable")
                code = self._wait(child, deadline, stop)
                if code is None:
                    return Outcome("abandoned" if stop is not None and stop.is_set() else "timeout")
                size = stdout.seek(0, os.SEEK_END)
                if size > MAX_STDOUT:
                    return Outcome("unavailable", exit_code=code)
                stdout.seek(0)
                return (interpret or _interpret)(code, stdout.read(MAX_STDOUT + 1))
        except OSError:
            return Outcome("unavailable")

    def _wait(self, child: subprocess.Popen, deadline: float, stop: threading.Event | None) -> int | None:
        """Exit code, or None after a deadline kill / an abandonment. An abandoned child is deliberately left running."""
        end = time.monotonic() + deadline
        while True:
            try:
                return child.wait(timeout=max(0.0, min(0.25, end - time.monotonic())))
            except subprocess.TimeoutExpired:
                if stop is not None and stop.is_set():
                    return None
                if time.monotonic() >= end:
                    self._terminate(child)
                    return None

    def _terminate(self, child: subprocess.Popen) -> None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=self._deadlines.grace)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        except ProcessLookupError:
            child.wait()


def _reference(job_id: str) -> dict[str, str]:
    return {"schemaVersion": RUNTIME_SCHEMA, "jobId": job_id}


def _interpret(code: int, raw: bytes) -> Outcome:
    if code not in (0, 2):
        return Outcome("abnormal", exit_code=code)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return Outcome("abnormal", exit_code=code)
    if not isinstance(value, dict) or value.get("schemaVersion") != RUNTIME_SCHEMA:
        return Outcome("abnormal", exit_code=code)
    if code == 2:
        error = value.get("error")
        name = error.get("code") if isinstance(error, dict) else None
        if not isinstance(name, str) or not CODE.fullmatch(name):
            return Outcome("abnormal", exit_code=code)
        return Outcome("error", code=name, exit_code=code)
    if "error" in value or not isinstance(value.get("jobId"), str) or not isinstance(value.get("inputDigest"), str):
        return Outcome("abnormal", exit_code=code)
    return Outcome("result", result=value, exit_code=code)
