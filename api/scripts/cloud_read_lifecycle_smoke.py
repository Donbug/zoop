#!/usr/bin/env python3
"""Published-image, keyless read lifecycle proof with an authored ingestion archive.

Run with --image <cached immutable image> --result <new JSON path>. The image must
be linux/amd64. A private Docker volume holds one real synthetic ingestion store;
readers mount it read-only and use per-process tmpfs state. SIGSTOP controls an
actual installed ingestion child, not a replacement CLI. The default expectation
is a drained 12-second read; --expected-long-read-outcome interrupted reproduces
the earlier image's 10-second graceful-shutdown defect.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[2]
PIPELINE_PYTHON = "/opt/zoop/pipeline/.venv/bin/python"
SERVICE = "/opt/zoop/service/.venv/bin/zoop-ai-service"
ARCHIVE = Path("/archive")
SCRATCH = Path("/scratch")


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def save(path, value):
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.write("\n")
    path.chmod(0o600)


def inventory(root):
    return {str(path.relative_to(root)): {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size, "mode": path.stat().st_mode & 0o777, "mtimeNs": path.stat().st_mtime_ns}
            for path in sorted(root.rglob("*")) if path.is_file()}


def prepare():
    ARCHIVE.chmod(0o700)
    os.chown(ARCHIVE, 999, 999)
    os.setgid(999)
    os.setuid(999)
    os.environ.clear()
    os.environ.update(PATH="/usr/bin:/bin", HOME="/tmp", PYTHONDONTWRITEBYTECODE="1",
                      ZOOP_STATE_DIR="/tmp/app", ZOOP_AI_WORKER_STATE_DIR="/tmp/worker")
    sys.path.insert(0, "/fixture")
    from ingestion_smoke import OfflineFixture, SCHEMA
    fixture = OfflineFixture(ARCHIVE)
    manifest = fixture.manifest("lifecycle", [[fixture.item()]])
    result = fixture.cli("run", fixture.request(manifest), manifest=manifest)
    check(result["state"] == "complete", "synthetic ingestion did not complete")
    ref = result["documentRefs"][0]
    selector = {"schemaVersion": SCHEMA, "roundId": "round-1", "sourceId": "synthetic-source",
                **{key: ref[key] for key in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")}}
    expected = fixture.cli("export", selector, extra=("--require-store",))
    save(ARCHIVE / "selector.json", selector)
    save(ARCHIVE / "expected.json", expected)
    save(ARCHIVE / "grants.json", {"schemaVersion": "zoop-ai-s1-1", "grants": []})
    print(json.dumps({"status": "prepared", "documents": 1, "modelCalls": 0}))


def wait_for(probe, description, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        answer = probe()
        if answer:
            return answer
        time.sleep(0.01)
    raise AssertionError(description)


def exercise(expected_long_read_outcome):
    token = secrets.token_urlsafe(32)
    principals = json.dumps([{"principal": "handoffer", "tokenSha256": [hashlib.sha256(token.encode()).hexdigest()],
                              "scopes": ["observation.read", "handoff.read"]}])
    selector = (ARCHIVE / "selector.json").read_bytes()
    expected = json.loads((ARCHIVE / "expected.json").read_bytes())
    before = inventory(ARCHIVE)
    processes, held = [], set()
    report = {"status": "failed", "cases": [], "providerCalls": 0, "modelCalls": 0,
              "expectedLongReadOutcome": expected_long_read_outcome}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(port):
        query = urllib.request.Request(f"http://127.0.0.1:{port}/internal/v1/observations/export", data=selector,
                                       headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        try:
            with opener.open(query, timeout=55) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def start(name, port, state=None):
        root = SCRATCH / (state or name)
        root.mkdir(mode=0o700, exist_ok=True)
        env = {"PATH": "/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
               "ZOOP_AI_SERVICE_PRINCIPALS": principals, "ZOOP_AI_SERVICE_STATE_DIR": str(root / "service"),
               "ZOOP_AI_WORKER_STATE_DIR": str(root / "worker"), "ZOOP_STATE_DIR": str(root / "app"),
               "ZOOP_AI_SERVICE_WORKER_COMMAND": "/opt/zoop/worker/.venv/bin/zoop-ai",
               "ZOOP_AI_SERVICE_GRANTS": str(ARCHIVE / "grants.json"),
               "ZOOP_AI_SERVICE_INGESTION_COMMAND": "/opt/zoop/pipeline/.venv/bin/zoop-ai-ingest",
               "ZOOP_AI_INGESTION_STATE_DIR": str(ARCHIVE / "state"), "ZOOP_AI_SERVICE_SOURCES": str(ARCHIVE / "sources.json"),
               "ZOOP_AI_SERVICE_HOST": "127.0.0.1", "ZOOP_AI_SERVICE_PORT": str(port)}
        log = SCRATCH / (name + ".log")
        with log.open("xb") as output:
            process = subprocess.Popen([SERVICE], env=env, stdout=output, stderr=subprocess.STDOUT)
        processes.append(process)
        return process, log

    def ready(process, port):
        def listening():
            check(process.poll() is None, "service exited before listening")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    return True
            except OSError:
                return False
        wait_for(listening, "service did not listen")
        code, body = request(port)
        check(code == 200 and json.loads(body) == expected, "fresh read differs from native export")

    def stop(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(55)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(5)
                raise AssertionError("service required forced cleanup")

    def child_of(process):
        # Popen runs in an ASGI thread; Linux records children against that TID.
        for task in Path(f"/proc/{process.pid}/task").iterdir():
            try:
                pids = (task / "children").read_text().split()
            except FileNotFoundError:
                continue
            for value in pids:
                pid = int(value)
                try:
                    command = Path(f"/proc/{pid}/cmdline").read_bytes()
                    if b"zoop-ai-ingest" in command:
                        os.kill(pid, signal.SIGSTOP)
                        held.add(pid)
                        return pid
                except ProcessLookupError:
                    continue
        return None

    try:
        first, _ = start("primary", 8000)
        ready(first, 8000)
        contender, log = start("same-state", 8001, state="primary")
        code = contender.wait(30)
        check(code == 78 and '"reason":"service_state_busy"' in log.read_text(), "shared state accepted overlapping owner")
        report["cases"].append({"case": "same-writable-state", "exitCode": code, "reason": "service_state_busy"})
        second, _ = start("separate-state", 8001)
        ready(second, 8001)
        with ThreadPoolExecutor(max_workers=2) as pool:
            answers = list(pool.map(request, (8000, 8001)))
        check(all(status == 200 and json.loads(body) == expected for status, body in answers), "independent readers did not overlap")
        report["cases"].append({"case": "separate-state-shared-ro-archive", "http": [answer[0] for answer in answers]})
        stop(second)
        stop(first)

        for name, pause, terminate in (("within-deadline-control", 12, False), ("short-drain", 2, True), ("beyond-grace", 12, True)):
            service, log = start(name, 8000, state="primary")
            ready(service, 8000)
            with ThreadPoolExecutor(max_workers=1) as pool:
                def timed_request():
                    try:
                        status, body = request(8000)
                        return status, body, time.monotonic(), None
                    except http.client.RemoteDisconnected:
                        return None, b"", time.monotonic(), "RemoteDisconnected"
                response = pool.submit(timed_request)
                child = wait_for(lambda: child_of(service), "actual ingestion child was not observed", seconds=5)
                started = time.monotonic()
                if terminate:
                    service.terminate()
                time.sleep(pause)
                completed_while_paused = response.done()
                if pause == 2 or not terminate:
                    check(not completed_while_paused, "request did not remain in flight at the controlled boundary")
                os.kill(child, signal.SIGCONT)
                held.remove(child)
                status, body, received_at, transport_error = response.result(55)
                http_elapsed = received_at - started
            if not terminate:
                stop(service)
            exit_code = service.wait(55)
            elapsed = time.monotonic() - started
            cancelled = "timeout graceful shutdown exceeded" in log.read_text().lower()
            if pause == 2 or not terminate or expected_long_read_outcome == "drained":
                check(status == 200 and json.loads(body) == expected and not cancelled, "read did not complete within its deadline")
            else:
                check((status == 500 or transport_error == "RemoteDisconnected") and cancelled,
                      "published shutdown cancellation was not observed")
            report["cases"].append({"case": name, "actualChildPausedSeconds": pause, "http": status,
                                    "transportError": transport_error,
                                    "httpObservedSeconds": round(http_elapsed, 3), "serviceExitCode": exit_code,
                                    "serviceExitSeconds": round(elapsed, 3), "graceExceededLogged": cancelled,
                                    "responseCompletedWhileChildPaused": completed_while_paused,
                                    "readDeadlineSeconds": 45})
            restarted, _ = start(name + "-restart", 8000, state="primary")
            ready(restarted, 8000)
            stop(restarted)
            report["cases"].append({"case": name + "-same-state-restart", "http": 200, "nativeExportEqual": True})
        check(inventory(ARCHIVE) == before, "read archive mutated")
        report.update(status="passed", archiveUnchanged=True, longReadOutcome=expected_long_read_outcome,
                      interpretation="Controlled 12-second read, owner-lock, independent-reader and restart expectations passed.")
    except Exception as error:
        report["failure"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        for pid in held:
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
        for process in processes:
            stop(process)
        report["cleanup"] = {"serviceProcessesExited": all(process.poll() is not None for process in processes)}
        report["serviceLogs"] = {path.name: path.read_text() for path in sorted(SCRATCH.glob("*.log"))}
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


def host(args):
    result = args.result.absolute()
    check(not result.exists(), "result must be a new path")
    environment = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
    name = "zoop-read-lifecycle-" + secrets.token_hex(8)
    volume = name + "-archive"
    owned, volume_created = [], False
    report = {"status": "failed", "image": args.image, "isolation": {"network": "none", "readOnlyRoot": True,
              "archiveMount": "read-only during requests", "scratch": "tmpfs UID999 mode0700"}, "cleanup": {}}

    def docker(*argv, timeout=180):
        return subprocess.run(["docker", *argv], env=environment, capture_output=True, text=True, timeout=timeout)

    try:
        context = docker("context", "show")
        check(context.returncode == 0 and context.stdout.strip() == "orbstack", "local OrbStack context required")
        endpoint = docker("context", "inspect", "orbstack", "--format", "{{.Endpoints.docker.Host}}")
        check(endpoint.returncode == 0 and endpoint.stdout.strip().startswith("unix://"), "local Docker socket required")
        image = docker("image", "inspect", args.image, "--format", "{{.Id}} {{.Architecture}}")
        check(image.returncode == 0 and image.stdout.strip().endswith(" amd64"), "cached amd64 image required")
        report["imageIdentity"] = image.stdout.strip()
        created = docker("volume", "create", "--label", "com.zoop.read-lifecycle=1", volume)
        check(created.returncode == 0, "owned synthetic volume creation failed")
        volume_created = True
        for phase in ("prepare", "exercise"):
            container = name + "-" + phase
            owned.append(container)
            command = ["run", "--pull", "never", "--name", container, "--label", "com.zoop.read-lifecycle=1",
                       "--platform", "linux/amd64", "--network", "none", "--read-only", "--cap-drop", "ALL",
                       "--tmpfs", "/tmp:rw,uid=999,gid=999,mode=0700", "--tmpfs", "/scratch:rw,uid=999,gid=999,mode=0700",
                       "--mount", f"type=volume,source={volume},target=/archive" + (",readonly" if phase == "exercise" else ""),
                       "--mount", f"type=bind,source={Path(__file__).resolve()},target=/smoke/api/scripts/cloud_read_lifecycle_smoke.py,readonly",
                       "--mount", f"type=bind,source={REPO / 'ai/pipeline/scripts'},target=/fixture,readonly",
                       "--entrypoint", PIPELINE_PYTHON]
            if phase == "prepare":
                command += ["--user", "0:0", "--cap-add", "CHOWN", "--cap-add", "SETUID", "--cap-add", "SETGID"]
            else:
                command += ["--user", "999:999"]
            completed = docker(*command, args.image, "/smoke/api/scripts/cloud_read_lifecycle_smoke.py", "--" + phase,
                               "--expected-long-read-outcome", args.expected_long_read_outcome)
            report[phase + "ExitCode"] = completed.returncode
            report[phase + "Stderr"] = completed.stderr[-4000:]
            if completed.stdout:
                report[phase] = json.loads(completed.stdout)
            check(completed.returncode == 0, phase + " failed: " + completed.stderr[-1500:])
        report["status"] = "passed"
    except (Exception, KeyboardInterrupt) as error:
        report["failure"] = {"type": type(error).__name__, "message": str(error)[:1800]}
    finally:
        for container in owned:
            docker("stop", "--time", "60", container)
            removed = docker("rm", container)
            report["cleanup"][container] = removed.returncode == 0
        if volume_created:
            report["cleanup"][volume] = docker("volume", "rm", volume).returncode == 0
        if not all(report["cleanup"].values()):
            report["status"] = "failed"
        save(result, report)
    print(json.dumps({"status": report["status"], "result": str(result), "cleanup": report["cleanup"]}))
    return 0 if report["status"] == "passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--expected-long-read-outcome", choices=("drained", "interrupted"), default="drained",
                        help="required observation for the controlled 12-second request during SIGTERM")
    internal = parser.add_mutually_exclusive_group()
    internal.add_argument("--prepare", action="store_true", help=argparse.SUPPRESS)
    internal.add_argument("--exercise", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.prepare:
        prepare()
        return 0
    if args.exercise:
        return exercise(args.expected_long_read_outcome)
    if not args.image or not args.result:
        parser.error("--image and --result are required")
    def interrupted(signum, frame):
        raise InterruptedError("owned lifecycle smoke interrupted")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    return host(args)


if __name__ == "__main__":
    raise SystemExit(main())
