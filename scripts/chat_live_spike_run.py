#!/usr/bin/env python3
"""Check a live spike environment, and send the spike's questions.

`preflight` makes no model call: it reads the public graph, checks the scenarios' companies against it, and sees /mcp answer
401 Bearer. `run` sends questions, each a paid model run, so it refuses to start without --i-approved-paid-calls and a hard
--max-runs that counts the runs already in the manifest. A question is sent once: a job that fails stays a failed run, and
one whose submission has an unknown fate stops the whole run. The manifest is written after every job, so nothing is lost.

Credentials come from ZOOP_SPIKE_EMAIL and ZOOP_SPIKE_PASSWORD, never from arguments. Nothing here prints a question, an
answer, a credential or a token.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

SCENARIOS = Path(__file__).resolve().with_name("chat_live_spike_scenarios.json")
MANIFEST_KEYS = {"schemaVersion", "candidateCommit", "approvedBy", "approvalRef", "environment", "policyVersion", "pricing"}
ACTIVE = {"queued", "running"}
WAIT_SECONDS = 120.0
POLL_SECONDS = 1.0


class SpikeError(RuntimeError):
    pass


class Unsure(SpikeError):
    """A question may have been accepted: sending it again could pay for it twice."""


class Client:
    def __init__(self, base_url: str, origin: str) -> None:
        self.base = base_url.rstrip("/")
        self.origin = origin
        self.csrf: str | None = None
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None) -> tuple[int, Any]:
        sent = {"Origin": self.origin, "Accept": "application/json", **(headers or {})}
        if self.csrf and method != "GET":
            sent["X-CSRF-Token"] = self.csrf
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            sent["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, headers=sent, method=method)
        try:
            with self.http.open(request, timeout=30) as response:
                text = response.read()
                return response.status, json.loads(text) if text else None
        except urllib.error.HTTPError as error:
            text = error.read()
            try:
                return error.code, json.loads(text) if text else None
            except json.JSONDecodeError:
                return error.code, None

    def login(self, email: str, password: str) -> dict[str, Any]:
        status, body = self.call("POST", "/api/v1/auth/login", {"email": email, "password": password})
        if status != 200 or not isinstance(body, dict) or not body.get("csrfToken"):
            raise SpikeError(f"login failed with status {status}")
        self.csrf = body["csrfToken"]
        return body


def credentials(env: dict[str, str]) -> tuple[str, str]:
    email, password = env.get("ZOOP_SPIKE_EMAIL"), env.get("ZOOP_SPIKE_PASSWORD")
    if not email or not password:
        raise SpikeError("set ZOOP_SPIKE_EMAIL and ZOOP_SPIKE_PASSWORD")
    return email, password


def scenarios(path: Path = SCENARIOS) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))["scenarios"]


def preflight(client: Client, env: dict[str, str], mcp_url: str, opener: Callable[..., Any] | None = None,
              path: Path = SCENARIOS) -> list[str]:
    """Every problem found; none means the environment can take the spike."""
    problems: list[str] = []
    status, graph = client.call("GET", "/api/v1/graph?mode=all")
    labels: set[str] = set()
    if status != 200 or not isinstance(graph, dict):
        problems.append(f"the public graph answered {status}")
    else:
        labels = {n.get("label") for n in graph.get("nodes", []) if n.get("kind") == "company"}
        issues = sum(1 for n in graph.get("nodes", []) if n.get("kind") == "issue")
        print(f"graph {graph.get('metadata', {}).get('graphVersion')}: {len(labels)} companies, {issues} issues")
        for name, scenario in scenarios(path).items():
            for company in scenario.get("inGraph", []):
                if company not in labels:
                    problems.append(f"{name}: {company} is not in the graph")
            for company in scenario.get("notInGraph", []):
                if company in labels:
                    problems.append(f"{name}: {company} is in the graph, so its empty read cannot open the web")
    if not mcp_answers_bearer(mcp_url, opener):
        problems.append("/mcp did not answer 401 Bearer")
    try:
        session = client.login(*credentials(env))
        if not (session.get("setup") or {}).get("completed", False):
            problems.append("the spike member has not finished onboarding")
    except SpikeError as error:
        problems.append(str(error))
    return problems


def mcp_answers_bearer(url: str, opener: Callable[..., Any] | None = None) -> bool:
    open_url = opener or urllib.request.urlopen
    request = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    try:
        with open_url(request, timeout=15):
            return False
    except urllib.error.HTTPError as error:
        return error.code == 401 and "bearer" in (error.headers.get("WWW-Authenticate") or "").lower()
    except OSError:
        return False


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as out:
        json.dump(manifest, out, ensure_ascii=False, indent=2)
    Path(out.name).replace(path)


def ask(client: Client, question: str, wait: float, poll: float, sleep: Callable[[float], None],
        now: Callable[[], float]) -> tuple[str, str]:
    """Sends one question in a session of its own and waits for its end: the job id and its status."""
    session, job = "spike-" + secrets.token_urlsafe(12), "spike-" + secrets.token_urlsafe(12)
    status, _ = client.call("PUT", f"/api/v1/chat/sessions/{session}")
    if status not in (200, 201):
        raise SpikeError(f"the session was refused with status {status}")
    try:
        status, body = client.call("POST", f"/api/v1/chat/sessions/{session}/jobs", {"jobId": job, "question": question},
                                   {"Idempotency-Key": job})
    except OSError as error:
        raise Unsure(f"job {job}: submission fate unknown ({type(error).__name__})") from None
    if status not in (200, 201, 202):
        if status >= 500:
            raise Unsure(f"job {job}: submission fate unknown (status {status})")
        raise SpikeError(f"the question was refused with status {status}")
    deadline = now() + wait
    state = (body or {}).get("status")
    while state in ACTIVE:
        if now() > deadline:
            raise Unsure(f"job {job}: still {state} after {wait:.0f}s")
        sleep(poll)
        status, body = client.call("GET", f"/api/v1/chat/jobs/{job}")
        state = (body or {}).get("status") if status == 200 else state
    return job, str(state)


def run(client: Client, manifest_path: Path, base: dict[str, Any], names: list[str], repeat: int, max_runs: int,
        wait: float = WAIT_SECONDS, poll: float = POLL_SECONDS, sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic, path: Path = SCENARIOS) -> dict[str, Any]:
    known = scenarios(path)
    unknown = [n for n in names if n not in known]
    if unknown:
        raise SpikeError(f"unknown scenarios: {unknown}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {**base, "runs": []}
    done = {n: sum(1 for r in manifest["runs"] if r["scenario"] == n) for n in names}
    for name in names:
        while done[name] < repeat:
            if len(manifest["runs"]) >= max_runs:
                write_manifest(manifest_path, manifest)
                raise SpikeError(f"stopped at --max-runs {max_runs}")
            job, state = ask(client, known[name]["question"], wait, poll, sleep, now)
            manifest["runs"].append({"jobId": job, "scenario": name})
            done[name] += 1
            write_manifest(manifest_path, manifest)
            print(f"{name} {done[name]}/{repeat}: {job} {state}")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--origin", required=True, help="an allowed web origin of that server")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("preflight")
    check.add_argument("--mcp-url", required=True)
    send = commands.add_parser("run")
    send.add_argument("--base-manifest", type=Path, required=True, help=f"JSON with {sorted(MANIFEST_KEYS)}")
    send.add_argument("--manifest", type=Path, required=True)
    send.add_argument("--scenario", action="append", help="repeatable; every scenario when left out")
    send.add_argument("--repeat", type=int, default=5)
    send.add_argument("--max-runs", type=int, required=True, help="the approved total, retries included")
    send.add_argument("--i-approved-paid-calls", action="store_true")
    args = parser.parse_args(argv)
    client = Client(args.base_url, args.origin)
    try:
        if args.command == "preflight":
            problems = preflight(client, dict(os.environ), args.mcp_url)
            for problem in problems:
                print("problem:", problem)
            print("preflight:", "failed" if problems else "passed")
            return 2 if problems else 0
        if not args.i_approved_paid_calls:
            raise SpikeError("every run is a paid model call: pass --i-approved-paid-calls once it is approved")
        base = json.loads(args.base_manifest.read_text(encoding="utf-8"))
        if set(base) != MANIFEST_KEYS:
            raise SpikeError(f"the base manifest must have exactly {sorted(MANIFEST_KEYS)}")
        client.login(*credentials(dict(os.environ)))
        run(client, args.manifest, base, args.scenario or list(scenarios()), args.repeat, args.max_runs)
        print("run: done")
        return 0
    except Unsure as error:
        print("stopped, not resent:", error)
        return 3
    except (SpikeError, OSError, json.JSONDecodeError) as error:
        print("stopped:", error)
        return 2


if __name__ == "__main__":
    sys.exit(main())
