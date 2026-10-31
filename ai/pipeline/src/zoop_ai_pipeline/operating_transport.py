"""One owned operating HTTP process, including DNS, terminated/reaped before normal send-gate release."""
from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

import httpx


def post(base: str, path: str, key: str, body: bytes, *, timeout: float, cleanup: float, max_response: int,
         send_lock: int, check: Callable[[], None]) -> tuple[int, str | None, bytes, bool]:
    deadline = time.monotonic() + timeout
    lifeline, keepalive = os.pipe()
    child = None
    try:
        with tempfile.TemporaryFile() as incoming, tempfile.TemporaryFile() as outgoing:
            payload = {"base": base, "path": path, "key": key, "body": body.decode("utf-8"), "timeout": timeout,
                       "maxResponse": max_response, "lifeline": lifeline, "parent": os.getpid()}
            incoming.write(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
            incoming.seek(0)
            check()
            if time.monotonic() >= deadline:
                raise TimeoutError("request_deadline")
            environment = {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1",
                           "PYTHONPATH": os.pathsep.join(str(Path(p).absolute()) for p in sys.path if p)}
            child = subprocess.Popen([sys.executable, "-m", "zoop_ai_pipeline.operating_transport"], stdin=incoming, stdout=outgoing,
                                     stderr=subprocess.DEVNULL, env=environment, pass_fds=(lifeline, send_lock), start_new_session=True)
            os.close(lifeline)
            lifeline = -1
            while child.poll() is None:
                check()
                remaining = deadline - time.monotonic()
                if remaining <= 0 or os.fstat(outgoing.fileno()).st_size > max_response * 2 + 4096:
                    raise TimeoutError("request_deadline_or_response_limit")
                time.sleep(min(0.02, remaining))
            if child.returncode != 0 or time.monotonic() > deadline:
                raise OSError("request_process_failed")
            outgoing.seek(0)
            raw = outgoing.read(max_response * 2 + 4097)
            if len(raw) > max_response * 2 + 4096:
                raise OSError("response_limit")
            result = json.loads(raw)
            return result["status"], result["contentType"], base64.b64decode(result["body"], validate=True), result["truncated"]
    finally:
        # The child inherits the send lock, so even an OS-level reap failure cannot free a still-live sender's gate.
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=cleanup / 2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=cleanup / 2)
        os.close(keepalive)
        if lifeline >= 0:
            os.close(lifeline)


def main() -> int:
    try:
        request = json.loads(sys.stdin.buffer.read(2_000_001))
        lifeline = request["lifeline"]
        if os.getppid() != request["parent"]:
            return 2

        def parent_exited():
            os.read(lifeline, 1)
            os._exit(70)

        threading.Thread(target=parent_exited, daemon=True).start()
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        headers = {"Authorization": "Bearer " + request["key"], "Content-Type": "application/json", "Accept": "application/json"}
        with httpx.Client(base_url=request["base"] + "/", timeout=request["timeout"], headers=headers,
                          follow_redirects=False, trust_env=False) as client:
            with client.stream("POST", request["path"], content=request["body"].encode("utf-8")) as response:
                chunks, size, truncated = [], 0, False
                for chunk in response.iter_bytes():
                    if size + len(chunk) > request["maxResponse"]:
                        chunks.append(chunk[:request["maxResponse"] - size])
                        truncated = True
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                result = {"status": response.status_code, "contentType": response.headers.get("content-type", "")[:200],
                          "body": base64.b64encode(b"".join(chunks)).decode("ascii"), "truncated": truncated}
        sys.stdout.write(json.dumps(result, separators=(",", ":")))
        sys.stdout.flush()
        return 0
    except Exception:
        # The parent records an unknown outcome; provider bodies and headers never enter stderr or process arguments.
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
