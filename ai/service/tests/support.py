"""Real-process harness. Flow tests drive a real uvicorn process on 127.0.0.1 and the real installed `zoop-ai` CLI.

Credentials are synthetic and exist only in memory and in the child environment; the repository holds no token or digest. The
loopback provider is a stdlib HTTP server that plays the role of an OpenAI-compatible endpoint: a test double for the provider
side only. Nothing here reaches the network.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import httpx

SERVICE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = SERVICE_ROOT.parent / "worker" / "fixtures" / "contracts"
ZOOP_AI = Path(sys.executable).parent / "zoop-ai"
LAUNCHER = Path(__file__).resolve().parent / "launcher.py"
SCHEMA = "zoop-ai-s1-1"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fixture(group: str, name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / group / f"{name}.json").read_text(encoding="utf-8"))


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_for(predicate: Callable[[], Any], timeout: float = 30.0, interval: float = 0.1, what: str = "condition") -> Any:
    end = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() >= end:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(interval)


class Credentials:
    """Synthetic principals with tokens built in memory; only SHA-256 digests reach the service environment."""

    def __init__(self) -> None:
        self.tokens = {name: "t" + secrets.token_urlsafe(36) for name in ("alpha", "beta", "reader", "submitter", "viewer", "grapher", "handoffer",
                                                                            "chatter")}
        relation = ["relation.submit", "relation.read", "relation.cancel", "relation.recover", "relation.review"]
        extraction = ["extraction.submit", "extraction.read", "extraction.cancel", "extraction.recover"]
        self.scopes = {
            "alpha": ["analysis.submit", "analysis.read", "analysis.cancel", "analysis.recover", *relation, *extraction, "graph.read", "handoff.read",
                      "chat.invoke"],
            "beta": ["analysis.submit", "analysis.read", "analysis.cancel", "analysis.recover", *relation, *extraction, "graph.read", "handoff.read",
                     "chat.invoke"],
            "reader": ["analysis.read"],
            "submitter": ["analysis.submit"],
            "viewer": ["relation.read", "extraction.read"],  # may look jobs and operations up, but never write a review or an extraction
            "grapher": ["graph.read"],                       # reads graph versions and nothing else
            "handoffer": ["handoff.read"],                   # reads AI handoff bundles and nothing else
            "chatter": ["chat.invoke"],                      # runs chatbot model stages and nothing else
        }

    def digest(self, name: str) -> str:
        return hashlib.sha256(self.tokens[name].encode("ascii")).hexdigest()

    def principals_json(self) -> str:
        return json.dumps([{"principal": name, "tokenSha256": [self.digest(name)], "scopes": self.scopes[name]}
                           for name in self.tokens])

    def secret_strings(self) -> list[str]:
        return [*self.tokens.values(), *(self.digest(name) for name in self.tokens)]


class Workspace:
    """Fresh state for one service: service dir, worker dir, grants and an optional replay fixture, all under tmp_path."""

    def __init__(self, root: Path, *, replay: dict[str, Any] | None = None, grants: dict[str, Any] | None = None):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.state = root / "service"
        self.worker = root / "worker"
        self.grants_path = root / "grants.json"
        self.replay_path = root / "replay.json"
        self.credentials = Credentials()
        self.port = free_port()
        self.api_key = "k-" + secrets.token_urlsafe(24)
        self.grants_path.write_text(json.dumps(grants if grants is not None else merged_grants()), encoding="utf-8")
        if replay is not None:
            self.replay_path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
        self.has_replay = replay is not None

    def env(self, **overrides: str | None) -> dict[str, str]:
        env = {
            "PATH": "/usr/bin:/bin",
            "ZOOP_AI_SERVICE_PRINCIPALS": self.credentials.principals_json(),
            "ZOOP_AI_SERVICE_STATE_DIR": str(self.state),
            "ZOOP_AI_WORKER_STATE_DIR": str(self.worker),
            "ZOOP_AI_SERVICE_WORKER_COMMAND": str(ZOOP_AI),
            "ZOOP_AI_SERVICE_GRANTS": str(self.grants_path),
            "ZOOP_AI_SERVICE_PORT": str(self.port),
        }
        if self.has_replay:
            env["ZOOP_AI_SERVICE_REPLAY"] = str(self.replay_path)
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    def private_strings(self) -> list[str]:
        """Values that must never appear in any response, header or log line."""
        return [str(self.state), str(self.worker), str(self.grants_path), str(self.replay_path), str(ZOOP_AI),
                self.api_key, *self.credentials.secret_strings()]


def merged_grants() -> dict[str, Any]:
    document, outlook = fixture("synthetic-document", "grants"), fixture("synthetic-outlook", "grants")
    return {"schemaVersion": SCHEMA, "grants": [*document["grants"], *outlook["grants"]]}


def document_jobs() -> list[dict[str, Any]]:
    return copy.deepcopy(fixture("synthetic-document", "jobs")["jobs"])


def outlook_job() -> dict[str, Any]:
    return copy.deepcopy(fixture("synthetic-outlook", "jobs")["jobs"][0])


def document_replay() -> dict[str, Any]:
    return fixture("synthetic-document", "replay")


def outlook_replay() -> dict[str, Any]:
    return fixture("synthetic-outlook", "replay")


def semantic_job_and_entry() -> tuple[dict[str, Any], dict[str, Any]]:
    """A standalone `semantic-verification` job on the first fixture document plus its authored replay entry.

    Built the way the worker's own tests do (candidate = the fixture summary), with the worker's public digest helpers; this is
    fixture authoring in the test process only. The service never imports them.
    """
    from zoop_ai.contracts import SummaryAnswer
    from zoop_ai.provider import request_identity, stage_config

    job = document_jobs()[0]
    candidate = SummaryAnswer.model_validate(document_replay()["responses"][0]["response"]).wire()
    job.update({"jobId": "verify-only-a", "kind": "semantic-verification"})
    job["input"]["candidate"] = candidate
    payload = {"schemaVersion": SCHEMA, "document": job["input"]["document"], "company": job["input"]["company"],
               "grantRef": {"grantId": job["input"]["grantId"], "revision": job["input"]["grantRevision"]}, "candidate": candidate}
    verdict = {"claims": [{"claimId": c["claimId"], "decision": "supported", "reason": "합성 판정 표본"} for c in candidate["claims"]],
               "prohibitedAdvice": False, "unsupportedCausality": False}
    entry = {"stage": "semantic-verification",
             "inputDigest": request_identity("semantic-verification", payload, stage_config("semantic-verification", "replay")),
             "response": verdict}
    return job, entry


def combined_replay() -> dict[str, Any]:
    """Four document jobs (8 calls), one outlook (1 call) and one standalone verification (1 call), in submission order."""
    replay = copy.deepcopy(document_replay())
    replay["responses"] += copy.deepcopy(outlook_replay()["responses"])
    replay["responses"].append(semantic_job_and_entry()[1])
    return replay


class ServiceProcess:
    """A real `python -m zoop_ai_service.main` (or the test launcher) on 127.0.0.1 with its stdout/stderr captured to files."""

    def __init__(self, workspace: Workspace, *, env: dict[str, str] | None = None, launcher: bool = False,
                 launcher_env: dict[str, str] | None = None):
        self.workspace = workspace
        self._env = env if env is not None else workspace.env()
        if launcher_env:
            self._env = {**self._env, **launcher_env}
        self._argv = [sys.executable, str(LAUNCHER)] if launcher else [sys.executable, "-m", "zoop_ai_service.main"]
        self.process: subprocess.Popen | None = None
        self.client = httpx.Client(base_url=f"http://127.0.0.1:{workspace.port}", timeout=60)
        self._runs = 0

    @property
    def log_path(self) -> Path:
        return self.workspace.root / f"service-{self._runs}.out"

    def start(self, *, wait: bool = True) -> ServiceProcess:
        self._runs += 1
        self.process = subprocess.Popen(self._argv, env=self._env, stdin=subprocess.DEVNULL, cwd=self.workspace.root,
                                        stdout=self.log_path.open("wb"), stderr=(self.workspace.root / f"service-{self._runs}.err").open("wb"))
        if wait:
            self.wait_ready()
        return self

    def wait_ready(self) -> None:
        def ready() -> bool:
            if self.process.poll() is not None:
                raise AssertionError(f"service exited with {self.process.returncode}: {self.logs()[-2000:]}")
            try:
                socket.create_connection(("127.0.0.1", self.workspace.port), timeout=0.5).close()
                return True
            except OSError:
                return False
        wait_for(ready, 20, 0.1, "service listener")

    def kill(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.send_signal(signal.SIGKILL)
        if self.process:
            self.process.wait()

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(15)
            except subprocess.TimeoutExpired:
                self.kill()

    def exited(self, timeout: float = 20) -> int:
        assert self.process is not None
        return self.process.wait(timeout)

    def logs(self, stream: str | None = None) -> str:
        parts = []
        for index in range(1, self._runs + 1):
            for suffix in (stream,) if stream else ("out", "err"):
                path = self.workspace.root / f"service-{index}.{suffix}"
                if path.exists():
                    parts.append(path.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(parts)

    def close(self) -> None:
        self.stop()
        self.client.close()

    # ---- HTTP ----

    def request(self, method: str, path: str, *, as_: str | None = "alpha", token: str | None = None, body: Any = None,
                raw: bytes | None = None, key: str | None = None, headers: dict[str, str] | None = None) -> httpx.Response:
        sent = dict(headers or {})
        secret = token if token is not None else (self.workspace.credentials.tokens[as_] if as_ else None)
        if secret is not None:
            sent.setdefault("Authorization", f"Bearer {secret}")
        if key is not None:
            sent["Idempotency-Key"] = key
        if body is not None:
            raw = canonical(body).encode("utf-8")
            sent.setdefault("Content-Type", "application/json")
        return self.client.request(method, path, content=raw, headers=sent)

    def submit(self, job: dict[str, Any], *, as_: str = "alpha", **kwargs: Any) -> httpx.Response:
        return self.request("POST", "/internal/v1/analysis-jobs", as_=as_, body=job, key=kwargs.pop("key", job["jobId"]), **kwargs)

    def status(self, job_id: str, *, as_: str = "alpha") -> httpx.Response:
        return self.request("GET", f"/internal/v1/analysis-jobs/{job_id}", as_=as_)

    def result(self, job_id: str, *, as_: str = "alpha") -> httpx.Response:
        return self.request("GET", f"/internal/v1/analysis-jobs/{job_id}/result", as_=as_)

    def cancel(self, job_id: str, *, as_: str = "alpha") -> httpx.Response:
        return self.request("POST", f"/internal/v1/analysis-jobs/{job_id}/cancel", as_=as_)

    def recover(self, job_id: str, *, as_: str = "alpha") -> httpx.Response:
        return self.request("POST", f"/internal/v1/analysis-jobs/{job_id}/recover", as_=as_)

    def wait_state(self, job_id: str, states: set[str], *, dispatch: set[str] | None = None, timeout: float = 40,
                   as_: str = "alpha") -> dict[str, Any]:
        def reached() -> dict[str, Any] | None:
            body = self.status(job_id, as_=as_).json()
            if body["state"] in states and (dispatch is None or body["dispatch"]["state"] in dispatch):
                return body
            return None
        return wait_for(reached, timeout, 0.2, f"{job_id} in {sorted(states)}")


def cli(workspace: Workspace, command: str, payload: dict[str, Any], *extra: str) -> tuple[int, dict[str, Any]]:
    """Direct installed-CLI call on the same worker ledger, for equivalence and zero-call proof."""
    env = {"PATH": "/usr/bin:/bin", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([str(ZOOP_AI), command, "--state-dir", str(workspace.worker), *extra], input=canonical(payload).encode(),
                          capture_output=True, env=env, timeout=60)
    return done.returncode, json.loads(done.stdout.decode())


def reference(job_id: str) -> dict[str, str]:
    return {"schemaVersion": SCHEMA, "jobId": job_id}


# ---- loopback OpenAI-compatible provider (test double for the provider side only) ----

class Gate:
    def __init__(self) -> None:
        self.entered, self._release = threading.Event(), threading.Event()

    def release(self) -> None:
        self._release.set()

    def wait(self, timeout: float = 60) -> None:
        self.entered.set()
        self._release.wait(timeout)


class ProviderStub:
    """Answers `chat/completions` the way an OpenAI-compatible endpoint would, from the repository's authored fixtures."""

    def __init__(self, *, delay: float = 0.0):
        self.requests: list[str] = []
        self.delay = delay
        self.gates: dict[str, Gate] = {}
        self._guard = threading.Lock()
        generation = {}
        replay = document_replay()["responses"]
        for index, job in enumerate(document_jobs()):
            generation[(job["input"]["document"]["documentId"], job["kind"])] = replay[index * 2]["response"]
        self._generation = generation
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802
                size = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(size))
                try:
                    content = stub.answer(request)
                except Exception:
                    self.send_response(500)
                    self.end_headers()
                    return
                payload = json.dumps({"choices": [{"message": {"content": content}}],
                                      "usage": {"prompt_tokens": 11, "completion_tokens": 7,
                                                "prompt_tokens_details": {"cached_tokens": 0},
                                                "completion_tokens_details": {"reasoning_tokens": 0}}}).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    @property
    def recipient(self) -> str:
        return "openai-compatible:" + sha256(canonical({"endpoint": self.base_url}))

    def gate(self, stage: str) -> Gate:
        gate = self.gates[stage] = Gate()
        return gate

    def answer(self, request: dict[str, Any]) -> str:
        stage = request["response_format"]["json_schema"]["name"]
        payload = json.loads(request["messages"][1]["content"])
        with self._guard:
            self.requests.append(stage)
        gate = self.gates.get(stage)
        if gate:
            gate.wait()
        if self.delay:
            time.sleep(self.delay)
        if stage == "semantic_verification":
            claims = payload["candidate"]["claims"]
            return json.dumps({"claims": [{"claimId": c["claimId"], "decision": "supported", "reason": "합성 판정 표본"} for c in claims],
                               "prohibitedAdvice": False, "unsupportedCausality": False}, ensure_ascii=False)
        kind = stage.replace("_", "-")
        return json.dumps(self._generation[(payload["document"]["documentId"], kind)], ensure_ascii=False)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def live_job(base: dict[str, Any] | None = None, *, job_id: str = "live-summary-a") -> dict[str, Any]:
    job = base or document_jobs()[0]
    job = copy.deepcopy(job)
    job["jobId"] = job_id
    job["mode"] = "live"
    job["provenance"] = {"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"}
    return job


def live_workspace(root: Path, stub: ProviderStub, ceiling: str = "20") -> tuple[Workspace, dict[str, str]]:
    """Grants naming the stub's recipient, plus the live opt-in environment (loopback endpoint, synthetic key and models)."""
    grants = merged_grants()
    grants["grants"][0]["recipients"] = [*grants["grants"][0]["recipients"], stub.recipient]
    workspace = Workspace(root, grants=grants)
    live = {"ZOOP_AI_LIVE_ENABLED": "1", "ZOOP_AI_GLOBAL_MAX_CALLS": ceiling, "ZOOP_AI_BASE_URL": stub.base_url,
            "ZOOP_AI_API_KEY": workspace.api_key, "ZOOP_AI_DOCUMENT_SUMMARY_MODEL": "synthetic-generation-model",
            "ZOOP_AI_DOCUMENT_SENTIMENT_MODEL": "synthetic-generation-model", "ZOOP_AI_VERIFY_MODEL": "synthetic-verify-model"}
    return workspace, live


PGREP = "pgrep"


def runtime_processes(worker_state: Path) -> list[int]:
    """Pids of live `zoop-ai` runtime processes bound to one worker ledger.

    Matches the exact owned argv (`zoop-ai <command> --state-dir <this path>`), escaped and terminated with `--` so the pattern
    is never read as an option. pgrep exit 1 means "no match"; any other failure is an error, never silently "no processes".
    """
    pattern = r"zoop-ai (submit|run|get|resume|cancel) --state-dir " + re.escape(str(worker_state)) + r"( |$)"
    found = subprocess.run([PGREP, "-f", "--", pattern], capture_output=True, text=True)
    if found.returncode == 1:
        return []
    if found.returncode != 0:
        raise RuntimeError(f"pgrep failed with exit {found.returncode}")
    return [int(pid) for pid in found.stdout.split() if int(pid) != os.getpid()]


def terminate_runtime(worker_state: Path, timeout: float = 10.0) -> None:
    """Kill every orphaned runtime process of one worker ledger and prove they are gone, before any state is removed."""
    end = time.monotonic() + timeout
    while True:
        pids = runtime_processes(worker_state)
        if not pids:
            return
        if time.monotonic() >= end:
            raise AssertionError(f"runtime processes still alive: {pids}")
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(0.1)


class Interrupted(BaseException):
    """Stands for a runtime process dying between two stages (not an Exception: no handler of the runner may absorb it)."""


def crash_between_stages(workspace: Workspace, env: dict[str, str], stub: ProviderStub, job_id: str) -> None:
    """Leave a registered live job exactly where a runtime child that died between stages would: the generation call is a
    durable received receipt and the verification stage was never reserved.

    Uses the real worker Runner and Store in this (test) process against the service's own worker ledger; only the second
    stage's entry is cut short. The stub sees exactly one request.
    """
    from zoop_ai.provider import OpenAICompatibleProvider
    from zoop_ai.runner import Runner
    from zoop_ai.store import Store

    class Cut(Runner):
        def _call(self, request, stage, payload, config, fence):
            if stage == "semantic-verification":
                raise Interrupted()
            return super()._call(request, stage, payload, config, fence)

    saved = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    store = Store(workspace.worker)
    provider = OpenAICompatibleProvider(base_url=stub.base_url, api_key=workspace.api_key)
    try:
        runner = Cut(store, provider, live_enabled=True, max_calls=int(env["ZOOP_AI_GLOBAL_MAX_CALLS"]))
        try:
            runner.run(job_id)
        except Interrupted:
            pass
    finally:
        provider.close()
        store.close()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
