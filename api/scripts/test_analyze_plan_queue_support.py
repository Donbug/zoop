"""Narrow test-owned harness tests. Not substitutes for the real queue acceptance CLI.

Main may run with the existing service interpreter:
  ai/service/.venv/bin/python -m pytest api/scripts/test_analyze_plan_queue_support.py
No production source/migration/configuration is imported or changed.
"""
from __future__ import annotations

import http.server
import socket
import stat
import struct
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from analyze_plan_queue_support import HttpFault, HttpProxy, PgProxy, legacy_history_matches, private_json, recv_exact


def frame(tag, body):
    return tag + struct.pack("!I", len(body) + 4) + body


def test_drop_is_after_real_upstream_processing_and_exact_body():
    received = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, raw, self.headers.get("Idempotency-Key")))
            payload = b'{"accepted":true}'
            self.send_response(202)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    proxy = HttpProxy(f"http://127.0.0.1:{server.server_address[1]}")
    fault = proxy.arm("POST", "/submit", drop=True)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(httpx.post, proxy.url + "/submit", content=b'{"fixed":"body"}', headers={"Idempotency-Key": "same-id"}, timeout=10, trust_env=False)
        try:
            assert fault.entered.wait(5)
            assert received == [("/submit", b'{"fixed":"body"}', "same-id")]
            assert proxy.events[0]["status"] == 202
            fault.release.set()
            with pytest.raises(httpx.TransportError):
                future.result(timeout=5)
        finally:
            fault.release.set()
            proxy.close()
            server.shutdown()
            server.server_close()


@pytest.mark.parametrize("boundary", ["before", "after"])
def test_postgres_commit_barrier_distinguishes_actual_durability(boundary):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    actual_commit = threading.Event()
    finished = threading.Event()

    def actual_database_protocol():
        connection, _ = listener.accept()
        try:
            size = struct.unpack("!I", recv_exact(connection, 4))[0]
            recv_exact(connection, size - 4)
            connection.sendall(frame(b"R", struct.pack("!I", 0)) + frame(b"Z", b"I"))
            while True:
                tag = recv_exact(connection, 1)
                size = struct.unpack("!I", recv_exact(connection, 4))[0]
                body = recv_exact(connection, size - 4)
                if tag == b"Q" and body == b"COMMIT\0":
                    actual_commit.set()
                    connection.sendall(frame(b"C", b"COMMIT\0") + frame(b"Z", b"I"))
                    return
        finally:
            connection.close()
            finished.set()

    threading.Thread(target=actual_database_protocol, daemon=True).start()
    proxy = PgProxy(listener.getsockname()[1])
    fault = proxy.arm(boundary)
    client = socket.create_connection(("127.0.0.1", proxy.port), timeout=5)
    try:
        startup = struct.pack("!I", 196608) + b"user\0test\0database\0test\0\0"
        client.sendall(struct.pack("!I", len(startup) + 4) + startup)
        assert recv_exact(client, 1) == b"R"
        recv_exact(client, 8)
        assert recv_exact(client, 1) == b"Z"
        recv_exact(client, 5)
        client.sendall(frame(b"B", b'{"state":"result_observed"}') + frame(b"Q", b"COMMIT\0"))
        assert fault.entered.wait(5)
        assert actual_commit.is_set() is (boundary == "after")
        fault.release.set()
        assert actual_commit.wait(5)
        assert recv_exact(client, 1) == b"C"
        size = struct.unpack("!I", recv_exact(client, 4))[0]
        assert recv_exact(client, size - 4) == b"COMMIT\0"
        assert finished.wait(5)
        assert not proxy.errors
    finally:
        fault.release.set()
        client.close()
        proxy.close()
        listener.close()


def test_private_bootstrap_is_exclusive_and_0600(tmp_path):
    path = tmp_path / "bootstrap.json"
    private_json(path, {"fixture": "authored-synthetic"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        private_json(path, {"fixture": "must-not-replace"})


def test_legacy_comparison_accepts_only_new_null_binding_and_keeps_raw_baseline():
    before = [{"id": "job-legacy-test", "status": "queued", "input": {"legacy": True},
               "checkpoint": {"legacy": True}, "attempts": [], "lease_until": None}]
    after = [{**before[0], "plan_id": None}]
    assert legacy_history_matches(before, after)
    assert "plan_id" not in before[0]
    assert not legacy_history_matches(before, before)
    assert not legacy_history_matches(before, [])


@pytest.mark.parametrize("column,value", [
    ("plan_id", "s2plan-" + "a" * 64),
    ("status", "running"),
    ("input", {"legacy": False}),
    ("checkpoint", {"legacy": False}),
    ("attempts", [{"ownerToken": "synthetic-new-owner"}]),
    ("lease_until", "2026-10-24T00:00:00Z"),
    ("unexpected_new_column", None),
])
def test_legacy_comparison_still_refuses_any_binding_or_original_field_change(column, value):
    before = [{"id": "job-legacy-test", "status": "queued", "input": {"legacy": True},
               "checkpoint": {"legacy": True}, "attempts": [], "lease_until": None}]
    after = [{**before[0], "plan_id": None, column: value}]
    assert not legacy_history_matches(before, after)


@pytest.mark.parametrize("status", [404, 409, 503])
def test_binding_transform_preserves_real_refusal_envelopes_exactly(status):
    payload = b'{"error":{"code":"job_not_found"},"status":null}'

    def success_only(body):
        body["status"]["inputDigest"] = "0" * 64
        return body

    fault = HttpFault("GET", "/synthetic-job", transform=success_only)
    assert fault.transform_payload(status, payload) is payload
    assert fault.transformed == 0


@pytest.mark.parametrize("status", [200, 202])
def test_malformed_success_transform_still_removes_required_digest(status):
    def malformed(body):
        body.pop("inputDigest")
        return body

    fault = HttpFault("POST", "/extraction-jobs", transform=malformed)
    assert fault.transform_payload(status, b'{"inputDigest":"real-success-pin"}') == b"{}"
    assert fault.transformed == 1


def test_unexpected_transform_failure_on_success_is_not_suppressed():
    def wrong_shape(body):
        body["status"]["inputDigest"] = "0" * 64
        return body

    fault = HttpFault("GET", "/synthetic-job", transform=wrong_shape)
    with pytest.raises(TypeError):
        fault.transform_payload(200, b'{"status":null}')
    assert fault.transformed == 0
