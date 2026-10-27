"""Test-only transparent boundaries for analyze_plan_queue_smoke; no product hooks.

HTTP faults run AFTER real upstream processing unless explicitly marked before.
PostgreSQL faults stop the actual JDBC COMMIT frame or its committed response.
Neither proxy implements a job, admission, pipeline result, or replacement queue.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import http.server
import json
import os
import pty
import re
import secrets
import select
import shutil
import signal
import socket
import socketserver
import struct
import subprocess
import termios
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def legacy_history_matches(before, after):
    """Allow only the declared nullable plan_id schema addition, not a history edit."""
    if len(before) != len(after):
        return False
    for old, new in zip(before, after, strict=True):
        if "plan_id" in old or "plan_id" not in new or new["plan_id"] is not None:
            return False
        if {key: value for key, value in new.items() if key != "plan_id"} != old:
            return False
    return True


def wait_for(predicate, timeout=90, what="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise TimeoutError(f"bounded wait expired: {what}")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def private_json(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(canonical(value) + "\n")


def stop(process, kill=False):
    if process and process.poll() is None:
        # All owned subprocesses use their own session; never discover/kill by name.
        os.killpg(process.pid, signal.SIGKILL if kill else signal.SIGTERM)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


class HttpFault:
    def __init__(self, method, suffix, *, before=False, drop=False, transform=None, repeat=False):
        self.method, self.suffix = method, suffix
        self.before, self.drop, self.transform, self.repeat = before, drop, transform, repeat
        self.entered, self.release = threading.Event(), threading.Event()
        self.hits = 0
        self.transformed = 0

    def matches(self, method, path):
        return method == self.method and path.split("?", 1)[0].endswith(self.suffix)

    def transform_payload(self, status, payload):
        # Binding negatives alter successful real envelopes only. A genuine
        # status-first 404 has status:null and must reach the app unchanged so
        # its original, fixed-ID submit path can run.
        if self.transform is None or status not in (200, 202):
            return payload
        rewritten = self.transform(json.loads(payload))
        self.transformed += 1
        return canonical(rewritten).encode()


class HttpProxy:
    def __init__(self, upstream, observation=None):
        self.upstream, self.observation = upstream, observation
        self.rules, self.events, self.errors = [], [], []
        self.all_rules = []
        self.lock = threading.Lock()
        self.client = httpx.Client(timeout=90, trust_env=False)
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_):
                pass

            def forward(self):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    check(0 <= length <= 16 * 1024 * 1024, "test proxy framing exceeds bound")
                    raw = self.rfile.read(length)
                    with outer.lock:
                        rule = next((r for r in outer.rules if r.matches(self.command, self.path)), None)
                        if rule and not rule.repeat:
                            outer.rules.remove(rule)
                    if rule and rule.before:
                        rule.hits += 1
                        rule.entered.set()
                        check(rule.release.wait(90), "before-upstream barrier not released")
                    if outer.observation:
                        outer.observation(self.command, self.path, raw)
                    headers = {key: self.headers[key] for key in ("Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID", "Accept") if key in self.headers}
                    response = outer.client.request(self.command, outer.upstream + self.path, headers=headers, content=raw)
                    payload = response.content
                    event = {"method": self.command, "path": self.path.split("?", 1)[0], "status": response.status_code,
                             "requestSha256": hashlib.sha256(raw).hexdigest(), "at": time.time()}
                    if response.status_code >= 400:
                        with contextlib.suppress(ValueError, AttributeError, TypeError):
                            code = response.json().get("error", {}).get("code")
                            if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code):
                                event["errorCode"] = code
                    with outer.lock:
                        outer.events.append(event)
                    if rule and not rule.before:
                        rule.hits += 1
                        rule.entered.set()
                        check(rule.release.wait(90), "after-upstream barrier not released")
                    if rule and rule.drop:
                        self.close_connection = True
                        with contextlib.suppress(OSError):
                            self.connection.shutdown(socket.SHUT_RDWR)
                        return
                    if rule:
                        payload = rule.transform_payload(response.status_code, payload)
                    self.send_response(response.status_code)
                    for key in ("Content-Type", "X-Request-ID", "ETag", "Retry-After"):
                        if key in response.headers:
                            self.send_header(key, response.headers[key])
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    self.close_connection = True
                except httpx.TransportError:
                    with outer.lock:
                        outer.events.append({"method": self.command, "path": self.path.split("?", 1)[0],
                                             "status": "upstream_transport_lost", "requestSha256": hashlib.sha256(raw).hexdigest(), "at": time.time()})
                    self.close_connection = True
                except Exception as error:
                    with outer.lock:
                        outer.errors.append({"method": self.command, "path": self.path.split("?", 1)[0],
                                             "exceptionType": type(error).__name__})
                    self.close_connection = True

            do_GET = forward
            do_POST = forward
            do_PUT = forward

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def arm(self, *args, **kwargs):
        rule = HttpFault(*args, **kwargs)
        with self.lock:
            self.rules.append(rule)
            self.all_rules.append(rule)
        return rule

    def close(self):
        for rule in self.all_rules:
            rule.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.client.close()
        self.thread.join(5)


def recv_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise EOFError
        data.extend(chunk)
    return bytes(data)


class CommitFault:
    def __init__(self, boundary):
        check(boundary in ("before", "after"), "unknown commit boundary")
        self.boundary = boundary
        self.entered, self.release = threading.Event(), threading.Event()
        self.hit = False


class PgProxy:
    """PostgreSQL v3 frame relay. sslmode=disable is REQUIRED for owned JDBC clients.

    Only one armed transaction containing result_observed is intercepted. Frames and
    credentials are never retained. A pre-COMMIT hold has no DB settlement; a hold
    on backend CommandComplete(COMMIT) is AFTER the real database durable commit.
    """
    def __init__(self, upstream_port):
        outer = self
        self.fault = None
        self.connections = []
        self.lock = threading.Lock()
        self.errors = []

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                upstream = socket.create_connection(("127.0.0.1", upstream_port), timeout=10)
                upstream.settimeout(None)
                client = self.request
                with outer.lock:
                    outer.connections.extend([client, upstream])
                marker = threading.Event()
                transaction_fault = [None]
                try:
                    size = struct.unpack("!I", recv_exact(client, 4))[0]
                    startup = recv_exact(client, size - 4)
                    if startup == struct.pack("!I", 80877103):
                        client.sendall(b"N")
                        size = struct.unpack("!I", recv_exact(client, 4))[0]
                        startup = recv_exact(client, size - 4)
                    check(size <= 100_000, "unexpected postgres startup frame")
                    upstream.sendall(struct.pack("!I", size) + startup)

                    def relay_frontend():
                        try:
                            while True:
                                tag = recv_exact(client, 1)
                                raw_size = recv_exact(client, 4)
                                length = struct.unpack("!I", raw_size)[0]
                                check(4 <= length <= 32 * 1024 * 1024, "postgres frontend frame exceeds bound")
                                body = recv_exact(client, length - 4)
                                if tag in (b"B", b"Q") and (b'"state":"result_observed"' in body or b'"state": "result_observed"' in body):
                                    marker.set()
                                commit = tag in (b"P", b"Q") and b"COMMIT" in body.upper()
                                if commit and marker.is_set():
                                    with outer.lock:
                                        fault = outer.fault
                                        if fault and not fault.hit:
                                            fault.hit = True
                                            transaction_fault[0] = fault
                                    if transaction_fault[0] and transaction_fault[0].boundary == "before":
                                        transaction_fault[0].entered.set()
                                        transaction_fault[0].release.wait(90)
                                upstream.sendall(tag + raw_size + body)
                        except (EOFError, OSError):
                            with contextlib.suppress(OSError):
                                upstream.shutdown(socket.SHUT_RDWR)
                        except Exception as error:
                            outer.errors.append(type(error).__name__)
                            with contextlib.suppress(OSError):
                                upstream.shutdown(socket.SHUT_RDWR)

                    thread = threading.Thread(target=relay_frontend, daemon=True)
                    thread.start()
                    while True:
                        tag = recv_exact(upstream, 1)
                        raw_size = recv_exact(upstream, 4)
                        length = struct.unpack("!I", raw_size)[0]
                        check(4 <= length <= 32 * 1024 * 1024, "postgres backend frame exceeds bound")
                        body = recv_exact(upstream, length - 4)
                        if tag == b"C" and body == b"COMMIT\0":
                            fault = transaction_fault[0]
                            if fault and fault.boundary == "after":
                                fault.entered.set()
                                fault.release.wait(90)
                            marker.clear()
                            transaction_fault[0] = None
                        client.sendall(tag + raw_size + body)
                except (EOFError, OSError):
                    pass
                except Exception as error:
                    outer.errors.append(type(error).__name__)
                finally:
                    upstream.close()

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def arm(self, boundary):
        self.fault = CommitFault(boundary)
        return self.fault

    def close(self):
        if self.fault:
            self.fault.release.set()
        for connection in self.connections:
            with contextlib.suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)
                connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


class Database:
    """Fresh owned cached Postgres only; SQL assertions/faults, never positive queue seeding."""
    def __init__(self, root, *, postgres_bin=None, image="postgres:16.13-alpine"):
        self.root = root
        self.bin = Path(postgres_bin) if postgres_bin else None
        self.name = "zoop-queue-proof-" + secrets.token_hex(6)
        self.user = "queue_smoke"
        self.db = "postgres"
        self.password = secrets.token_urlsafe(24)
        self.process = None
        self.started = False
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(root), "LANG": "C.UTF-8"}
        self.image = image
        self.port = free_port()

    def command_env(self):
        # Read the selected Docker context; never change it or forward its config
        # to application/model descendants, which retain an isolated HOME.
        return {**self.env, "HOME": str(Path.home())} if not self.bin else self.env

    def command(self, args, *, raw=None, timeout=60):
        return subprocess.run(args, input=raw, capture_output=True, timeout=timeout, env=self.command_env())

    def start(self):
        if self.bin:
            for name in ("initdb", "pg_ctl", "psql"):
                check((self.bin / name).is_file(), f"missing cached PostgreSQL executable: {name}")
            initialized = self.command([str(self.bin / "initdb"), "-D", str(self.root / "pgdata"), "-A", "trust", "-U", self.user, "--no-locale", "-E", "UTF8"])
            check(initialized.returncode == 0, "owned initdb failed")
            self.started = True
            launched = self.command([str(self.bin / "pg_ctl"), "-D", str(self.root / "pgdata"), "-l", str(self.root / "postgres.log"),
                                     "-o", f"-h 127.0.0.1 -p {self.port} -k {self.root}", "-w", "start"])
            check(launched.returncode == 0, "owned PostgreSQL failed to start")
        else:
            check(shutil.which("docker"), "cached PostgreSQL required: pass --postgres-bin or make Docker available")
            check(self.command(["docker", "image", "inspect", self.image]).returncode == 0, "cached PostgreSQL image missing; this proof never pulls")
            self.started = True
            started = self.command(["docker", "run", "-d", "--pull=never", "--name", self.name, "--label", "com.zoop.analyze-plan-proof=1",
                                    "--tmpfs", "/var/lib/postgresql/data", "-p", f"127.0.0.1:{self.port}:5432",
                                    "-e", f"POSTGRES_USER={self.user}", "-e", "POSTGRES_DB=postgres", "-e", "POSTGRES_HOST_AUTH_METHOD=trust", self.image])
            check(started.returncode == 0, "owned cached PostgreSQL container failed to start")
        wait_for(lambda: self.sql("SELECT 1", tolerate=True) == "1", 90, "owned PostgreSQL readiness")
        return self

    def argv(self):
        if self.bin:
            return [str(self.bin / "psql"), "-h", "127.0.0.1", "-p", str(self.port), "-U", self.user, "-d", self.db, "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1"]
        return ["docker", "exec", "-i", self.name, "psql", "-h", "127.0.0.1", "-U", self.user, "-d", self.db, "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1"]

    def sql(self, statement, tolerate=False):
        result = self.command(self.argv(), raw=statement.encode(), timeout=30)
        if tolerate and result.returncode:
            return None
        check(result.returncode == 0, "PostgreSQL assertion/fault statement failed (SQL text withheld)")
        return result.stdout.decode().strip()

    def json(self, statement):
        return json.loads(self.sql(statement))

    def hold(self, statement):
        name = "queue-proof-barrier-" + secrets.token_hex(8)
        process = subprocess.Popen(self.argv(), env=self.command_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        process.stdin.write(("SET application_name='" + name + "'; BEGIN; " + statement + "; SELECT 'barrier-held';\n").encode())
        process.stdin.flush()
        try:
            wait_for(lambda: self.sql("SELECT count(*) FROM pg_stat_activity WHERE state='idle in transaction' AND application_name='" + name + "'") == "1",
                     15, "specific held PostgreSQL transaction")
        except BaseException:
            self.release(process)
            raise
        return process

    def release(self, process):
        if process.poll() is None:
            try:
                process.stdin.write(b"ROLLBACK;\n\\q\n")
                process.stdin.flush()
                process.communicate(timeout=10)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                stop(process)

    def close(self):
        if self.started:
            if self.bin:
                self.command([str(self.bin / "pg_ctl"), "-D", str(self.root / "pgdata"), "-m", "immediate", "-w", "stop"])
            else:
                self.command(["docker", "rm", "-f", "-v", self.name])
            self.started = False


def provision(java, jar, env, cwd, email, password, *, diagnostic_path=None):
    """Use the supported interactive Console reader through a private PTY; no SQL admin."""
    master, slave = pty.openpty()
    attrs = termios.tcgetattr(slave)
    attrs[3] &= ~termios.ECHO
    termios.tcsetattr(slave, termios.TCSANOW, attrs)
    process = subprocess.Popen([java, "-XX:TieredStopAtLevel=1", "-jar", str(jar),
                                "--spring.main.web-application-type=none", "--spring.profiles.active=local,admin-provision",
                                f"--zoop.admin.provision.email={email}", "--zoop.admin.provision.display-name=Synthetic queue administrator"],
                               cwd=cwd, env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    buffer, answers = bytearray(), 0
    transcript = bytearray()
    deadline = time.monotonic() + 120
    try:
        while process.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], .1)[0]:
                try:
                    block = os.read(master, 8192)
                except OSError:
                    break
                buffer.extend(block)
                transcript.extend(block)
                if len(transcript) > 65536:
                    del transcript[:-65536]
                prompt = b"Administrator password: " if answers == 0 else b"Confirm administrator password: "
                if answers < 2 and prompt in buffer:
                    os.write(master, password.encode() + b"\n")
                    answers += 1
                    buffer.clear()
            if len(buffer) > 65536:
                del buffer[:-8192]
        process.wait(timeout=max(1, deadline - time.monotonic()))
        check(process.returncode == 0 and answers == 2, "supported interactive administrator provisioning failed; no SQL fallback")
    finally:
        stop(process)
        os.close(master)
        buffer.clear()
        if diagnostic_path is not None:
            # Persist only allowlisted signals and Java class names. Never dump
            # terminal text, command environment, email, passwords, or tokens.
            text = transcript.decode("utf-8", "replace")
            private_json(diagnostic_path, {
                "returnCode": process.returncode,
                "passwordPromptsAnswered": answers,
                "profiles": ["local", "admin-provision"],
                "invalidAuthOrigin": "Invalid auth Origin configuration" in text,
                "interactiveConsoleUnavailable": "Interactive terminal required" in text,
                "applicationFailedToStart": "APPLICATION FAILED TO START" in text,
                "provisioned": "Administrator account provisioned:" in text,
                "exceptionTypes": sorted(set(re.findall(r"(?:Caused by: |^)([A-Za-z_$][A-Za-z0-9_$.]*(?:Exception|Error))(?=:|$)", text, re.MULTILINE))),
            })
        transcript.clear()
