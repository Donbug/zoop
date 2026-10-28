"""Security regressions for current-grant acquisition, network deadlines, foreign cache files and HTML scope.

Every scenario uses synthetic local inputs. Network cases only contact an explicit disposable loopback server."""
from __future__ import annotations

import asyncio
import json
import errno
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from scripts.collection_smoke import NEWS, CollectionKit, LocalSite
from scripts.ingestion_smoke import json_bytes, ownership_env
from zoop_ai_pipeline import ingestion_parsers as parsers
from zoop_ai_pipeline.collection import Output, collect
from zoop_ai_pipeline.collection_contracts import Policy, Request
from zoop_ai_pipeline.ingestion_contracts import IngestionFailure

PIPELINE = Path(__file__).resolve().parents[1]
ALLOW_ALL = b"User-agent: *\nAllow: /\n"


@pytest.fixture
def site():
    server = LocalSite()
    yield server
    server.close()


@pytest.fixture
def kit(tmp_path):
    return CollectionKit(tmp_path / "owned")


def revoker(kit):
    def revoke():
        kit.registry["sources"][0]["grant"]["enabled"] = False
        kit.save_registry()

    return revoke


def grant_enabled(kit) -> bool:
    return json.loads(kit.registry_path.read_bytes())["sources"][0]["grant"]["enabled"]


def collections(kit) -> list[str]:
    folder = kit.inputs / "collections"
    return sorted(os.listdir(folder)) if folder.exists() else []


# ------------------------------------------------------------------------------------ grant freshness

def test_a_grant_revoked_while_robots_is_served_sends_no_document_request(kit, site):
    site.route("/robots.txt", ALLOW_ALL, content_type="text/plain", hook=revoker(kit))
    site.route("/news/a", NEWS)
    result = kit.collect("revoked-in-robots", [kit.target(site.url("/news/a"), "n1")], expected=2)
    assert result["error"]["code"] in {"registry_changed", "source_unauthorized"}, result
    assert site.hits("/news/a") == 0, "a document was requested after the grant was revoked"
    assert collections(kit) in ([], [".lock"])


def test_a_grant_revoked_while_a_redirect_is_served_requests_nothing_further(kit, site):
    site.route("/go", status=302, headers={"Location": "/news/a"}, hook=revoker(kit))
    site.route("/news/a", NEWS)
    result = kit.collect("revoked-in-redirect", [kit.target(site.url("/go"), "n1")], expected=2)
    assert result["error"]["code"] in {"registry_changed", "source_unauthorized"}, result
    assert site.hits("/go") == 1 and site.hits("/news/a") == 0, "a redirect target was requested after the grant was revoked"
    assert collections(kit) in ([], [".lock"])


def test_no_receipt_or_body_is_written_once_the_grant_is_no_longer_current(kit, site, monkeypatch):
    site.route("/news/a", NEWS, hook=revoker(kit))
    written = []
    original = Output.write

    def recording(self, relative, data):
        written.append((relative, grant_enabled(kit)))
        return original(self, relative, data)

    monkeypatch.setattr(Output, "write", recording)
    request = Request.model_validate(kit.collection_request("revoked-in-body", [kit.target(site.url("/news/a"), "n1")]))
    with pytest.raises(IngestionFailure) as stopped:
        collect(kit.registry_path, Policy.model_validate(kit.policy), request)
    assert stopped.value.code in {"registry_changed", "source_unauthorized"}
    assert [name for name, current in written if not current] == [], "fetched bytes were stored after the grant stopped being current"
    assert collections(kit) in ([], [".lock"])


def test_revocation_during_receipt_write_stops_body_write_and_discards_private_files(kit, site, monkeypatch):
    site.route("/news/a", NEWS)
    original = Output.write
    writes = []

    def revoke_after_receipt(self, relative, data):
        writes.append(relative)
        original(self, relative, data)
        if relative.startswith("receipts/"):
            revoker(kit)()

    monkeypatch.setattr(Output, "write", revoke_after_receipt)
    request = Request.model_validate(kit.collection_request("revoked-after-receipt", [kit.target(site.url("/news/a"), "n1")]))
    with pytest.raises(IngestionFailure, match="registry_changed|source_unauthorized"):
        collect(kit.registry_path, Policy.model_validate(kit.policy), request)
    assert any(name.startswith("receipts/") for name in writes)
    assert not any(name.startswith("bodies/") for name in writes)
    assert collections(kit) in ([], [".lock"])


def test_a_stored_collection_is_not_returned_when_the_grant_is_revoked_after_it_was_read(kit, site, monkeypatch):
    site.route("/news/a", NEWS)
    targets = [kit.target(site.url("/news/a"), "n1")]
    assert kit.collect("cached", targets)["state"] == "complete"
    original = Output.stored

    def stored_then_revoked(self, collection_id):
        found = original(self, collection_id)
        revoker(kit)()
        return found

    monkeypatch.setattr(Output, "stored", stored_then_revoked)
    request = Request.model_validate(kit.collection_request("cached", targets))
    with pytest.raises(IngestionFailure) as stopped:
        collect(kit.registry_path, Policy.model_validate(kit.policy), request)
    assert stopped.value.code in {"registry_changed", "source_unauthorized"}


def test_revocation_during_final_commit_preparation_prevents_publication(kit, site, monkeypatch):
    site.route("/news/a", NEWS)
    original = Output.commit

    def revoke_before_commit(self, collection_id, guard):
        revoker(kit)()
        return original(self, collection_id, guard)

    monkeypatch.setattr(Output, "commit", revoke_before_commit)
    request = Request.model_validate(kit.collection_request("revoked-at-commit", [kit.target(site.url("/news/a"), "n1")]))
    with pytest.raises(IngestionFailure) as stopped:
        collect(kit.registry_path, Policy.model_validate(kit.policy), request)
    assert stopped.value.code in {"registry_changed", "source_unauthorized"}
    assert not (kit.inputs / "collections" / "revoked-at-commit").exists()
    assert collections(kit) in ([], [".lock"])


def test_revocation_after_rename_before_delivery_retracts_only_the_owned_collection(kit, site, monkeypatch):
    site.route("/news/a", NEWS)
    original = Output.commit
    seen = []

    def revoke_during_commit(self, collection_id, guard):
        def guard_at_boundary():
            seen.append((collection_id, (kit.inputs / "collections" / collection_id).exists()))
            if len(seen) == 2:
                revoker(kit)()
            guard()

        return original(self, collection_id, guard_at_boundary)

    monkeypatch.setattr(Output, "commit", revoke_during_commit)
    request = Request.model_validate(kit.collection_request("revoked-after-rename", [kit.target(site.url("/news/a"), "n1")]))
    with pytest.raises(IngestionFailure, match="registry_changed|source_unauthorized"):
        collect(kit.registry_path, Policy.model_validate(kit.policy), request)
    assert seen == [("revoked-after-rename", False), ("revoked-after-rename", True)]
    assert collections(kit) in ([], [".lock"])


def test_sync_collector_does_not_silently_disable_deadlines_inside_a_running_event_loop(kit, site):
    site.route("/news/a", NEWS)
    request = Request.model_validate(kit.collection_request("async-context", [kit.target(site.url("/news/a"), "n1")]))

    async def attempt():
        return collect(kit.registry_path, Policy.model_validate(kit.policy), request)

    with pytest.raises(IngestionFailure, match="collector_async_context_unsupported"):
        asyncio.run(attempt())
    assert site.log == [] and collections(kit) == []


# --------------------------------------------------------------------------------- absolute deadline

class DrippingServer:
    """Answers robots with 404, then drips incomplete headers or body below inactivity limits.
    Stopped and closed by `close()`; no server thread outlives the test."""

    def __init__(self, seconds=8.0, interval=0.5, *, complete_headers=False):
        self.seconds, self.interval, self.complete_headers = seconds, interval, complete_headers
        self.stop, self.paths = threading.Event(), []
        self.peer_closed = threading.Event()
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.listener.settimeout(0.2)
        self.port = self.listener.getsockname()[1]
        self.threads = [threading.Thread(target=self.accept, daemon=True)]
        self.threads[0].start()

    def accept(self):
        while not self.stop.is_set():
            try:
                connection, _ = self.listener.accept()
            except (TimeoutError, OSError):
                continue
            thread = threading.Thread(target=self.serve, args=(connection,), daemon=True)
            self.threads.append(thread)
            thread.start()

    def serve(self, connection):
        try:
            path = None
            drip_phase = False
            connection.settimeout(2)
            request = b""
            while b"\r\n\r\n" not in request and len(request) < 65536:
                chunk = connection.recv(4096)
                if not chunk:
                    return
                request += chunk
            path = request.split(b" ", 2)[1].decode("ascii", "replace")
            self.paths.append(path)
            if path == "/robots.txt":
                connection.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\n")
                return
            connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 10\r\nConnection: close\r\nX-Slow: "
                               + (b"ok\r\n\r\n" if self.complete_headers else b""))
            drip_phase = True
            deadline = time.monotonic() + self.seconds
            while time.monotonic() < deadline and not self.stop.wait(self.interval):
                connection.sendall(b"a")
                connection.settimeout(0.05)
                try:
                    if connection.recv(1) == b"":
                        self.peer_closed.set()
                        return
                except TimeoutError:
                    pass
            if not self.complete_headers:
                connection.sendall(b"\r\n\r\n")
            connection.sendall(b"hello")
        except OSError as exc:
            # A reset or broken pipe during the target drip is closure too; robots and failed handshakes prove nothing.
            if drip_phase and path != "/robots.txt" and (
                isinstance(exc, (ConnectionResetError, BrokenPipeError)) or exc.errno in (errno.ECONNRESET, errno.EPIPE)
            ):
                self.peer_closed.set()
        except IndexError:
            pass
        finally:
            connection.close()

    def close(self):
        self.stop.set()
        self.listener.close()
        for thread in self.threads:
            thread.join(timeout=3)


@pytest.fixture
def dripping():
    server = DrippingServer()
    yield server
    server.close()


def test_slowly_dripped_response_headers_cannot_outlive_the_absolute_deadline(kit, dripping):
    kit.policy.update(timeoutSeconds=1, maxTotalSeconds=2)
    kit.save_policy()
    url = f"http://127.0.0.1:{dripping.port}/slow"
    started = time.monotonic()
    result = kit.collect("slow-headers", [kit.target(url, "slow")], expected=2)
    elapsed = time.monotonic() - started
    assert result["state"] == "failed" and {t["candidateId"]: t["code"] for t in result["targets"]} == {"slow": "timeout"}, result["targets"]
    # The server keeps sending for 8 s with gaps far below any inactivity timeout; the absolute budget is 1-2 s.
    assert elapsed < 4.5, f"the collector kept reading dripped headers for {elapsed:.1f}s despite a 1s/2s budget"
    assert dripping.peer_closed.wait(1.5), "the timed-out request left a live socket behind"
    assert collections(kit) == [".lock", "slow-headers"], "a timed-out request left a temporary collection behind"


def test_dripping_target_counts_tcp_reset_after_response_begins_as_peer_closure():
    server = DrippingServer(seconds=1, interval=0.02)
    try:
        with socket.create_connection(("127.0.0.1", server.port), timeout=2) as client:
            client.sendall(b"GET /slow HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
            assert client.recv(4096), "the target response must begin before the client resets it"
            client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        assert server.peer_closed.wait(1.5), "a TCP reset during the target drip was not observed as peer closure"
    finally:
        server.close()


def test_slowly_dripped_body_is_cancelled_and_no_partial_body_is_published(kit):
    server = DrippingServer(complete_headers=True)
    try:
        kit.policy.update(timeoutSeconds=1, maxTotalSeconds=2)
        kit.save_policy()
        result = kit.collect("slow-body", [kit.target(f"http://127.0.0.1:{server.port}/slow", "slow")], expected=2)
        assert result["state"] == "failed" and result["targets"][0]["code"] == "timeout"
        assert server.peer_closed.wait(1.5)
        folder = kit.inputs / "collections" / "slow-body"
        assert not (folder / "bodies").exists() and not (folder / "receipts").exists()
    finally:
        server.close()


# ------------------------------------------------------------------------------ foreign special files

def test_a_foreign_fifo_named_collection_json_is_refused_without_blocking_the_collector(kit, site, tmp_path):
    site.route("/news/a", NEWS)
    squatter = kit.inputs / "collections" / "fifo-id"
    squatter.mkdir(parents=True)
    fifo = squatter / "collection.json"
    os.mkfifo(fifo)
    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8",
                   "PYTHONDONTWRITEBYTECODE": "1", **ownership_env()}
    request = kit.collection_request("fifo-id", [kit.target(site.url("/news/a"), "n1")])
    argv = [sys.executable, "-m", "zoop_ai_pipeline.collection_cli", "run", "--sources", str(kit.registry_path), "--policy", str(kit.policy_path)]
    child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, cwd=PIPELINE)
    try:
        out, _ = child.communicate(json_bytes(request), timeout=15)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()
        pytest.fail("the collector blocked on a foreign FIFO while holding its collection lock")
    assert child.returncode == 2 and json.loads(out)["error"]["code"] == "collection_namespace_conflict"
    assert fifo.exists() and site.log == []


# --------------------------------------------------------------------------------- HTML scope work

def _prepare_in_child(sibling_count: int, limit_seconds: int) -> tuple[float, str]:
    code = (
        "import json, sys, time\n"
        "from zoop_ai_pipeline import ingestion_parsers as parsers\n"
        "from zoop_ai_pipeline.ingestion_contracts import IngestionFailure\n"
        f"html = ('<html><body>' + '<article>x</article>' * {sibling_count} + '</body></html>').encode()\n"
        "started = time.monotonic()\n"
        "try:\n"
        "    parsers.prepare(html, 'text/html', None)\n"
        "    code = 'prepared'\n"
        "except IngestionFailure as exc:\n"
        "    code = exc.code\n"
        "print(json.dumps({'code': code, 'seconds': time.monotonic() - started}))\n")
    try:
        child = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, timeout=limit_seconds, cwd=PIPELINE)
    except subprocess.TimeoutExpired:
        pytest.fail(f"{sibling_count} sibling <article> elements took more than {limit_seconds}s to be rejected (quadratic scope selection)")
    assert child.returncode == 0, child.stderr.decode()
    result = json.loads(child.stdout)
    return result["seconds"], result["code"]


def test_fifty_thousand_sibling_articles_are_rejected_as_ambiguous_promptly():
    seconds, code = _prepare_in_child(50_000, limit_seconds=30)
    assert code == "article_scope_ambiguous_or_missing"
    assert seconds < 10, f"ambiguity rejection took {seconds:.1f}s"


def test_nested_articles_are_still_one_scope_and_siblings_still_ambiguous():
    nested = "<html><body><article>outer <article>inner</article> tail</article></body></html>".encode()
    assert parsers.prepare(nested, "text/html", None)["text"].startswith("outer")
    with pytest.raises(IngestionFailure, match="article_scope_ambiguous_or_missing"):
        parsers.prepare(b"<html><body><article>a</article><article>b</article></body></html>", "text/html", None)
    # An explicit selector is unaffected by sibling count.
    only = b"<html><body><article id='a'>A</article><article id='b'>B</article></body></html>"
    assert parsers.prepare(only, "text/html", "//article[@id='b']")["text"] == "B"
