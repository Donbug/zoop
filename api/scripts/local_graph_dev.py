#!/usr/bin/env python3
"""Throwaway local backend for graph-read development: no AWS, no Neo4j, no AI model, no real data.

Starts one unique, throwaway PostgreSQL container (random loopback port, synthetic credentials, data on tmpfs) and the BUILT
Spring jar against it with the existing local/dev fixture source (ZOOP_GRAPH_SNAPSHOT_SOURCE=fixture). The fixture source
registers and activates the two synthetic snapshots bundled in the jar (titles start with "[합성]"). That is temporary dev data,
NOT a graph handoff import and NOT real news: nothing here is staged, imported or published from the AI pipeline.

It waits until GET /api/v1/graph, the asOf read and one edge read all answer 200, prints the URLs, and runs until Ctrl-C
(SIGINT/SIGTERM/SIGHUP). On exit or any failure it stops the application, removes the container (and its tmpfs data) and the
temporary working directory.

Isolation: the application gets a minimal environment (no inherited AWS/model/provider variables), runs in an empty temporary
working directory, and never reads or writes api/.env or your own database. The CSRF signing key and the database password are
random per run and are never printed. Nothing is pulled, installed or built: a missing JDK 21, Docker, local image or jar is a
clear failure.

Prerequisites (this script runs none of them):
  make api-build                      # builds the jar: api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar
  docker pull postgres:16.13-alpine   # once, or pass --image with a PostgreSQL image you already have

Run (repository root; POSIX shell or PowerShell):
  python3 api/scripts/local_graph_dev.py [--server-port 8080]
or `make api-graph-dev`. A container killed with SIGKILL cannot clean up itself; remove it with
  docker ps -a --filter label=com.zoop.local-graph-dev=1
  docker rm -f -v <name>
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_JAR = REPO / "api" / "build" / "libs" / "zoop-api-0.0.1-SNAPSHOT.jar"
DEFAULT_IMAGE = "postgres:16.13-alpine"   # the image api/compose.local.yaml and CI use
LABEL = "com.zoop.local-graph-dev"
DB_NAME = "zoop_graph_dev"
DB_USER = "zoop_local_graph"
# Between the activation of fixture-2026-10-01 and fixture-2026-10-08 (graph-fixtures/index.json): the asOf read must pick the older version.
AS_OF = "2026-10-05T00:00:00Z"
LABEL_PREFIX = "[local-graph-dev]"


class Fail(Exception):
    """A clear, user-facing failure (exit status 1)."""


class Stopped(BaseException):
    """SIGTERM/SIGHUP: a deliberate stop, handled like Ctrl-C."""


def say(message: str) -> None:
    print(f"{LABEL_PREFIX} {message}", file=sys.stderr, flush=True)


def docker(*args: str, timeout: int = 60, env: dict | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["docker", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout,
                              env=env if env is not None else dict(os.environ))
    except subprocess.TimeoutExpired:
        raise Fail(f"`docker {args[0]}` did not finish within {timeout}s")


def first_line(text: str) -> str:
    lines = [line for line in (text or "").strip().splitlines() if line.strip()]
    return lines[-1] if lines else "(no output)"


# ---------------------------------------------------------------------------------------------------- preflight ----
def find_java(explicit: str | None) -> str:
    candidates = [explicit] if explicit else []
    if not explicit:
        if os.environ.get("JAVA_HOME"):
            candidates.append(str(Path(os.environ["JAVA_HOME"]) / "bin" / "java"))
        candidates.append(shutil.which("java") or "")
    for candidate in candidates:
        if not candidate:
            continue
        try:
            done = subprocess.run([candidate, "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue
        match = re.search(r'version "(\d+)', done.stdout or "")
        if done.returncode == 0 and match:
            if int(match.group(1)) < 21:
                raise Fail(f"{candidate} is Java {match.group(1)}; the API needs JDK 21 or newer (set JAVA_HOME or pass --java)")
            return candidate
    raise Fail("no working JDK 21 found: set JAVA_HOME to a JDK 21 or pass --java")


def preflight_docker(image: str) -> None:
    if not shutil.which("docker"):
        raise Fail("`docker` is not on PATH; install Docker or use the compose-based setup in api/README.md")
    info = docker("info", "--format", "{{.ServerVersion}}", timeout=30)
    if info.returncode != 0:
        raise Fail("the Docker daemon is not reachable: " + first_line(info.stderr))
    if docker("image", "inspect", image).returncode != 0:
        raise Fail(f"image {image} is not present locally and this launcher never pulls. Run `docker pull {image}` "
                   "yourself, or pass --image with a PostgreSQL image you already have")


def pick_port(wanted: int) -> int:
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", wanted))
        except OSError:
            raise Fail(f"127.0.0.1:{wanted} is already in use; pick another --server-port (0 chooses a free one)")
        return probe.getsockname()[1]


# ---------------------------------------------------------------------------------------------------- database -----
def start_database(name: str, image: str, password: str) -> int:
    # `-e POSTGRES_PASSWORD` (no value) copies it from this process' environment, so it never appears on a command line.
    started = docker("run", "-d", "--pull", "never", "--name", name, "--label", f"{LABEL}=1",
                     "-e", f"POSTGRES_DB={DB_NAME}", "-e", f"POSTGRES_USER={DB_USER}", "-e", "POSTGRES_PASSWORD",
                     "--tmpfs", "/var/lib/postgresql/data", "-p", "127.0.0.1::5432", image,
                     env={**os.environ, "POSTGRES_PASSWORD": password})
    if started.returncode != 0:
        raise Fail("could not start the throwaway PostgreSQL container: " + first_line(started.stderr))
    mapped = docker("port", name, "5432/tcp")
    for line in mapped.stdout.splitlines():
        host, _, port = line.strip().rpartition(":")
        if host == "127.0.0.1" and port.isdigit():
            return int(port)
    raise Fail("the database container did not publish a loopback port: " + first_line(mapped.stderr or mapped.stdout))


def wait_database(name: str, port: int, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = docker("inspect", "-f", "{{.State.Running}}", name)
        if state.returncode != 0 or state.stdout.strip() != "true":
            logs = docker("logs", "--tail", "20", name)
            raise Fail("the database container stopped during startup:\n" + (logs.stdout + logs.stderr).strip())
        # -h 127.0.0.1: the entrypoint's temporary init server listens on a unix socket only, so this is the real server.
        ready = docker("exec", name, "pg_isready", "-h", "127.0.0.1", "-p", "5432", "-U", DB_USER, "-d", DB_NAME)
        if ready.returncode == 0:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=2).close()
                return
            except OSError:
                pass
        time.sleep(1)
    raise Fail(f"the database did not accept connections within {timeout:.0f}s")


# ---------------------------------------------------------------------------------------------------- application ---
class App:
    """The built jar as a loopback web server; its output is streamed with the two run secrets redacted."""

    def __init__(self, java: str, jar: Path, port: int, db_port: int, password: str, csrf_key: str, workdir: str):
        origins = f"http://localhost:3000,http://localhost:{port},http://127.0.0.1:{port}"
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "C.UTF-8",
            "DB_URL": f"jdbc:postgresql://127.0.0.1:{db_port}/{DB_NAME}", "DB_USERNAME": DB_USER, "DB_PASSWORD": password,
            "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID": "local-graph-dev-v1", "ZOOP_AUTH_CSRF_KEYS": "local-graph-dev-v1=" + csrf_key,
            "ZOOP_GRAPH_SNAPSHOT_SOURCE": "fixture", "SPRING_PROFILES_ACTIVE": "local",
            "ZOOP_AUTH_ALLOWED_ORIGINS": origins, "ZOOP_API_CORS_ALLOWED_ORIGINS": "http://localhost:3000",
        }
        self.port = port
        self.secrets = [password, csrf_key]
        self.tail: deque[str] = deque(maxlen=40)
        self.process = subprocess.Popen(
            [java, "-XX:TieredStopAtLevel=1", "-jar", str(jar), f"--server.port={port}", "--server.address=127.0.0.1"],
            cwd=workdir, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=(os.name == "posix"))
        self.reader = threading.Thread(target=self._drain, daemon=True)
        self.reader.start()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _drain(self) -> None:
        for raw in self.process.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            for secret in self.secrets:
                line = line.replace(secret, "***")
            self.tail.append(line)
            print(line, flush=True)

    def get(self, path: str) -> tuple[int, str]:
        try:
            with self.opener.open(f"http://127.0.0.1:{self.port}{path}", timeout=30) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8", "replace")

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.reader.join(timeout=5)

    def failure(self, what: str) -> Fail:
        self.reader.join(timeout=2)
        return Fail(what + "\n--- last application output ---\n" + "\n".join(self.tail))


def wait_ready(app: App, timeout: float) -> dict:
    """Returns the default graph once the fixture versions are registered; 409 VERSION_UNAVAILABLE and refused connections are the startup window."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if app.process.poll() is not None:
            raise app.failure(f"the application exited with status {app.process.returncode} before it was ready")
        try:
            status, body = app.get("/api/v1/graph")
        except (urllib.error.URLError, OSError):
            status, body = None, ""
        if status == 200:
            return json.loads(body)
        if status not in (None, 409):
            raise app.failure(f"GET /api/v1/graph answered {status} instead of 200: {body[:300]}")
        time.sleep(1)
    raise app.failure(f"the application was not ready within {timeout:.0f}s")


def read_json(app: App, label: str, path: str) -> dict:
    status, body = app.get(path)
    if status != 200:
        raise app.failure(f"{label} {path} answered {status} instead of 200: {body[:300]}")
    return json.loads(body)


def report_ready(app: App, default_graph: dict, db_port: int, container: str) -> None:
    base = f"http://127.0.0.1:{app.port}"
    as_of_path = f"/api/v1/graph?asOf={AS_OF}"
    as_of = read_json(app, "asOf read", as_of_path)
    edges = default_graph["edges"]
    if not edges:
        raise app.failure("the fixture graph has no edge to read")
    edge = next((e for e in edges if e["relationType"] == "STRUCTURALLY_RELATED_TO"), edges[0])
    edge_path = "/api/v1/graph/edges/" + urllib.parse.quote(edge["id"], safe="")
    read_json(app, "edge read", edge_path)

    def describe(graph: dict) -> str:
        version = graph["metadata"]["graphVersion"]
        if not version.startswith("fixture-"):
            raise app.failure(f"the graph read served version {version!r}, not a bundled fixture version")
        return f"graphVersion={version}, {len(graph['nodes'])} nodes, {len(graph['edges'])} edges"

    print(f"""
READY. Temporary SYNTHETIC fixture data ("[합성]" titles): not a real import, not real news, discarded when you stop (Ctrl-C).
  API      {base}
  graph    {base}/api/v1/graph  -> 200 ({describe(default_graph)})
  asOf     {base}{as_of_path}  -> 200 ({describe(as_of)})
  edge     {base}{edge_path}  -> 200
  database throwaway container {container} on 127.0.0.1:{db_port}; removed on exit
""", flush=True)


# ---------------------------------------------------------------------------------------------------- lifecycle ----
def cleanup(app: App | None, container: str | None, workdir: str | None) -> bool:
    """Stops the application, removes the container and the working directory. Returns False if anything is left behind."""
    clean = True
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), signal.SIG_IGN)   # a second signal must not interrupt the cleanup
    if app is not None:
        say("stopping the application")
        app.stop()
    if container is not None:
        try:
            docker("rm", "-f", "-v", container)
            if docker("container", "inspect", container).returncode == 0:
                clean = False
                say(f"WARNING: container {container} still exists; remove it with `docker rm -f -v {container}`")
            else:
                say(f"database container {container} removed")
        except Fail as failure:
            clean = False
            say(f"WARNING: {failure}; check `docker ps -a --filter label={LABEL}=1`")
    if workdir is not None:
        shutil.rmtree(workdir, ignore_errors=True)
    return clean


def raise_stopped(signum, _frame):
    raise Stopped(signum)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jar", type=Path, default=DEFAULT_JAR, help="built Spring jar (default: %(default)s)")
    parser.add_argument("--java", default=None, help="java binary, JDK 21+ (default: $JAVA_HOME/bin/java, then PATH)")
    parser.add_argument("--image", default=DEFAULT_IMAGE, help="PostgreSQL image that is already present locally (never pulled; default: %(default)s)")
    parser.add_argument("--server-port", type=int, default=0, help="loopback port of the API (default 0: a free random port)")
    parser.add_argument("--ready-timeout", type=int, default=240, help="seconds to wait for the application (default: %(default)s)")
    args = parser.parse_args()

    for name in ("SIGTERM", "SIGHUP", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), raise_stopped)

    app: App | None = None
    container: str | None = None
    workdir: str | None = None
    status = 0
    try:
        jar = args.jar.resolve()
        if not jar.is_file():
            raise Fail(f"jar not found: {jar}. Build it first (`make api-build`); this launcher never builds")
        java = find_java(args.java)
        preflight_docker(args.image)
        port = pick_port(args.server_port)

        password = secrets.token_urlsafe(24)
        csrf_key = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
        container = f"zoop-local-graph-dev-{secrets.token_hex(4)}"
        say(f"starting throwaway PostgreSQL container {container} ({args.image}, no pull)")
        db_port = start_database(container, args.image, password)
        wait_database(container, db_port)

        workdir = tempfile.mkdtemp(prefix="zoop-local-graph-dev-")   # empty cwd: no stray application.yml or config/ is picked up
        say(f"starting the application on 127.0.0.1:{port} with the synthetic fixture graph source")
        app = App(java, jar, port, db_port, password, csrf_key, workdir)
        default_graph = wait_ready(app, args.ready_timeout)
        report_ready(app, default_graph, db_port, container)
        while app.process.poll() is None:
            time.sleep(1)
        raise app.failure(f"the application exited with status {app.process.returncode}")
    except (KeyboardInterrupt, Stopped):
        say("stop requested")
    except Fail as failure:
        print(f"{LABEL_PREFIX} FAILED: {failure}", file=sys.stderr, flush=True)
        status = 1
    finally:
        if not cleanup(app, container, workdir):
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
