"""Container collector: consistent checkpoints, manifest verification, restore, cooperative stop and SIGTERM shutdown."""
import hashlib
import json
import multiprocessing
import shutil
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager, nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from scripts.collection_smoke import LocalSite
from scripts.private_intake_smoke import article, config_data
from zoop_ai_pipeline import collector_checkpoint as cp
from zoop_ai_pipeline import collector_cli as cli
from zoop_ai_pipeline import collector_runtime as rt
from zoop_ai_pipeline import private_intake as intake
from zoop_ai_pipeline.collector_control import NO_CONTROL, Control, PipeControl
from zoop_ai_pipeline.news_sources import descriptor, surface
from zoop_ai_pipeline.collector_s3 import S3Store


@pytest.fixture(scope="module", autouse=True)
def shared_store():
    global _store_manager
    with multiprocessing.get_context("spawn").Manager() as manager:
        _store_manager = manager
        yield


class FakeStore:
    """Process-shared object store; `calls` records completed write order."""

    def __init__(self):
        self.objects, self.calls, self.lock = _store_manager.dict(), _store_manager.list(), _store_manager.Lock()

    def put_file(self, key, path, *, sha256):
        with self.lock:
            self.objects[key] = (Path(path).read_bytes(), sha256)
            self.calls.append(("put", key))

    def copy(self, source_key, key, *, sha256):
        with self.lock:
            self.objects[key] = (self.objects[source_key][0], sha256)
            self.calls.append(("copy", key))

    def put_bytes(self, key, data):
        with self.lock:
            self.objects[key] = (data, None)
            self.calls.append(("put", key))

    put_pointer = put_bytes

    def get_bytes(self, key):
        item = self.objects.get(key)
        return None if item is None else item[0]

    def get_file(self, key, path):
        if key not in self.objects:
            raise cp.CheckpointError("file_missing", key)
        Path(path).write_bytes(self.objects[key][0])

    def head(self, key):
        item = self.objects.get(key)
        return None if item is None else (len(item[0]), item[1])


class UnsignedStore(S3Store):
    """Reconstruct the SDK's non-pickleable UNSIGNED sentinel inside each process."""

    def __init__(self, endpoint, read_timeout):
        from botocore import UNSIGNED
        from botocore.config import Config
        self.endpoint, self.read_timeout = endpoint, read_timeout
        super().__init__("bucket", client_options={
            "endpoint_url": endpoint, "region_name": "us-east-1",
            "config": Config(signature_version=UNSIGNED, proxies={}, read_timeout=read_timeout,
                             request_checksum_calculation="when_required", retries={"total_max_attempts": 5})})

    def __getstate__(self):
        return self.endpoint, self.read_timeout

    def __setstate__(self, state):
        self.__init__(*state)


class ObjectServer:
    """Loopback S3 protocol fixture; a blocked response outlives the publishing client."""

    def __init__(self):
        self.store = FakeStore()
        self.block = None
        self.before = None
        self.retry_key = None
        self.trickle = False
        self.entered, self.release = threading.Event(), threading.Event()
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def handle_object(self):
                key = self.path.removeprefix("/bucket/")
                owner.requests.append((self.command, key, time.monotonic()))
                if owner.before:
                    owner.before(self.command, key)
                data = b""
                if self.command == "PUT":
                    data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                    source = self.headers.get("x-amz-copy-source")
                    metadata = self.headers.get("x-amz-meta-sha256")
                    if source:
                        data = owner.store.objects[source.removeprefix("bucket/").removeprefix("/bucket/")][0]
                    owner.store.objects[key] = (data, metadata)
                    if source:
                        data = b'<CopyObjectResult><ETag>"copied"</ETag><LastModified>2026-10-30T00:00:00Z</LastModified></CopyObjectResult>'
                    else:
                        data = b""
                elif key in owner.store.objects:
                    data = owner.store.objects[key][0]
                if owner.block and owner.block(self.command, key):
                    owner.entered.set()
                    owner.release.wait(8)
                status = 200 if key in owner.store.objects else 404
                if key == owner.retry_key:
                    status, data = 503, b"<Error><Code>SlowDown</Code></Error>"
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                if key in owner.store.objects:
                    metadata = owner.store.objects[key][1]
                    if metadata:
                        self.send_header("x-amz-meta-sha256", metadata)
                self.send_header("ETag", '"fixture"')
                self.end_headers()
                if self.command != "HEAD":
                    try:
                        if owner.trickle and key.endswith("MANIFEST.json"):
                            for byte in data:
                                self.wfile.write(bytes([byte]))
                                self.wfile.flush()
                                time.sleep(0.02)
                        else:
                            self.wfile.write(data)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

            do_GET = do_HEAD = do_PUT = handle_object

            def log_message(self, *args):
                pass

        class Server(ThreadingHTTPServer):
            request_queue_size = 64

        self.server = Server(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def client(self, read_timeout=30):
        return UnsignedStore(f"http://127.0.0.1:{self.server.server_port}", read_timeout)

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(1)


def sha(data):
    return hashlib.sha256(data).hexdigest()


# -- capture / manifest / restore -----------------------------------------------------------------------------------

def write_state(root: Path):
    private = root / "private"
    private.mkdir(parents=True)
    (private / "STATE.json").write_text('{"state":{"unknownRequests":2,"tasks":{},"candidates":{}}}')
    (private / ".lock").write_bytes(b"")
    (private / (".stage-" + "0" * 32)).write_bytes(b"in-flight")
    database = sqlite3.connect(private / "QUEUE.sqlite3")
    database.execute("CREATE TABLE a(n INTEGER)")
    database.execute("CREATE TABLE b(n INTEGER)")
    database.commit()
    database.close()
    (private / "empty").mkdir()
    return private


def test_capture_backs_up_sqlite_while_a_writer_commits_and_skips_transients(tmp_path):
    private = write_state(tmp_path / "state")
    database = sqlite3.connect(private / "QUEUE.sqlite3", isolation_level=None, check_same_thread=False)
    database.execute("PRAGMA journal_mode=WAL")
    stop = threading.Event()

    def writer():
        counter = 0
        while not stop.is_set():
            counter += 1
            database.execute("BEGIN IMMEDIATE")
            database.execute("INSERT INTO a VALUES(?)", (counter,))
            database.execute("INSERT INTO b VALUES(?)", (counter,))
            database.execute("COMMIT")

    thread = threading.Thread(target=writer)
    thread.start()
    time.sleep(0.2)
    try:
        tables = cp.capture({"private": private}, tmp_path / "stage")
    finally:
        stop.set()
        thread.join()
        database.close()
    paths = {entry["path"]: entry for entry in tables["files"]}
    assert set(paths) == {"private/STATE.json", "private/.lock", "private/QUEUE.sqlite3"}
    assert tables["sqlite"] == [{"path": "private/QUEUE.sqlite3", "method": "backup"}]
    assert "private/empty" in tables["dirs"]
    copy = tmp_path / "stage" / "private" / "QUEUE.sqlite3"
    assert paths["private/QUEUE.sqlite3"]["sha256"] == sha(copy.read_bytes())
    assert sorted(p.name for p in copy.parent.iterdir() if "sqlite" in p.name) == ["QUEUE.sqlite3"]
    checked = sqlite3.connect(copy)
    rows = [checked.execute(f"SELECT count(*), coalesce(sum(n),0) FROM {t}").fetchone() for t in ("a", "b")]
    assert rows[0] == rows[1] and rows[0][0] > 0
    assert checked.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    checked.close()
    assert cp.count_unknown("private", tmp_path / "stage") == 2


def test_capture_refuses_symlinks_and_orphan_journals(tmp_path):
    private = write_state(tmp_path / "state")
    (private / "link").symlink_to(private / "STATE.json")
    with pytest.raises(cp.CheckpointError, match="unsafe_entry"):
        cp.capture({"private": private}, tmp_path / "one")
    (private / "link").unlink()
    (private / "orphan.sqlite3-journal").write_bytes(b"x")
    with pytest.raises(cp.CheckpointError, match="orphan_sqlite_sidecar"):
        cp.capture({"private": private}, tmp_path / "two")


def checkpoint_once(tmp_path, store, *, seq=1, previous=None, state=None):
    private = state or write_state(tmp_path / f"state{seq}")
    staging = tmp_path / f"stage{seq}"
    tables = cp.capture({"private": private}, staging)
    manifest = cp.build_manifest(run_id="run-1", checkpoint_id=cp.new_checkpoint_id(), seq=seq, kind="periodic", tables=tables,
                                 paths=[{"name": "private"}], unknown=cp.count_unknown("private", staging), previous=None,
                                 image={"gitCommit": None})
    pointer = cp.publish(store, "pfx/runs/run-1", staging, manifest, previous)
    return manifest, pointer


def test_manifest_is_written_after_every_file_and_the_pointer_last(tmp_path):
    store = FakeStore()
    manifest, pointer = checkpoint_once(tmp_path, store)
    keys = [key for _, key in store.calls]
    base = cp.checkpoint_base("pfx/runs/run-1", 1, manifest["checkpointId"])
    assert keys[-2:] == [f"{base}/{cp.MANIFEST_NAME}", "pfx/runs/run-1/latest.json"]
    assert {f"{base}/{entry['path']}" for entry in manifest["files"]} == set(keys[:-2])
    assert json.loads(store.get_bytes("pfx/runs/run-1/latest.json"))["manifestSha256"] == sha(cp.encode_manifest(manifest))
    assert manifest["unknownOutcomes"] == 2 and manifest["schemaVersion"] == cp.SCHEMA_VERSION


def test_unchanged_files_are_copied_server_side_from_the_previous_checkpoint(tmp_path):
    store = FakeStore()
    first, _ = checkpoint_once(tmp_path, store, seq=1)
    store.calls[:] = []
    # Same bytes in a second checkpoint: every file is reused; the SQLite backup may legitimately differ.
    staging = tmp_path / "again"
    second_tables = cp.capture({"private": tmp_path / "state1" / "private"}, staging)
    manifest = cp.build_manifest(run_id="run-1", checkpoint_id="aaaaaaaaaaaa", seq=2, kind="periodic", tables=second_tables,
                                 paths=[], unknown=0, previous=None, image={})
    cp.publish(store, "pfx/runs/run-1", staging, manifest, first)
    assert {kind for kind, key in store.calls if "/private/STATE.json" in key} == {"copy"}


def test_restore_installs_only_after_every_hash_verifies(tmp_path):
    store = FakeStore()
    manifest, _ = checkpoint_once(tmp_path, store)
    root = tmp_path / "restored"
    root.mkdir()
    restored = cp.restore(store, "pfx/runs/run-1", "run-1", root)
    assert restored["checkpointId"] == manifest["checkpointId"]
    private = root / "private"
    assert (private / "STATE.json").read_bytes() == (tmp_path / "state1" / "private" / "STATE.json").read_bytes()
    assert oct(os.stat(private / "STATE.json").st_mode & 0o777) == "0o600" and oct(os.stat(private).st_mode & 0o777) == "0o700"
    assert (private / "empty").is_dir() and not list(root.glob(".restore-*"))
    for entry in manifest["files"]:
        assert sha(Path(root / entry["path"]).read_bytes()) == entry["sha256"]


@pytest.mark.parametrize("damage, code", [("flip", "sha256_mismatch"), ("truncate", "size_mismatch"), ("drop", "file_missing")])
def test_restore_rejects_a_damaged_object_and_leaves_no_state(tmp_path, damage, code):
    store = FakeStore()
    manifest, _ = checkpoint_once(tmp_path, store)
    key = f"{cp.checkpoint_base('pfx/runs/run-1', 1, manifest['checkpointId'])}/private/STATE.json"
    data, meta = store.objects[key]
    if damage == "flip":
        store.objects[key] = (b"X" + data[1:], meta)
    elif damage == "truncate":
        store.objects[key] = (data[:-1], meta)
    else:
        del store.objects[key]
    root = tmp_path / "restored"
    root.mkdir()
    with pytest.raises(cp.CheckpointError) as raised:
        cp.restore(store, "pfx/runs/run-1", "run-1", root)
    assert raised.value.code == code or (damage == "drop" and raised.value.code == "file_missing")
    assert list(root.iterdir()) == []


def test_restore_refuses_a_manifest_changed_after_the_pointer_was_written(tmp_path):
    store = FakeStore()
    manifest, _ = checkpoint_once(tmp_path, store)
    key = f"{cp.checkpoint_base('pfx/runs/run-1', 1, manifest['checkpointId'])}/{cp.MANIFEST_NAME}"
    store.objects[key] = (store.objects[key][0].replace(b'"periodic"', b'"final"  '), None)
    (tmp_path / "r").mkdir()
    with pytest.raises(cp.CheckpointError, match="manifest_sha256_mismatch"):
        cp.restore(store, "pfx/runs/run-1", "run-1", tmp_path / "r")


def test_restore_refuses_a_non_empty_state_directory_and_other_runs(tmp_path):
    store = FakeStore()
    checkpoint_once(tmp_path, store)
    root = tmp_path / "restored"
    (root / "private").mkdir(parents=True)
    (root / "private" / "STATE.json").write_text("live")
    with pytest.raises(cp.CheckpointError, match="state_not_empty"):
        cp.restore(store, "pfx/runs/run-1", "run-1", root)
    assert (root / "private" / "STATE.json").read_text() == "live"
    with pytest.raises(cp.CheckpointError, match="manifest_invalid|latest_pointer_invalid"):
        cp.restore(store, "pfx/runs/run-1", "run-2", tmp_path / "x")


def test_manifest_paths_cannot_escape_the_state_tree(tmp_path):
    store = FakeStore()
    manifest, _ = checkpoint_once(tmp_path, store)
    manifest["files"][0]["path"] = "private/../../etc/passwd"
    with pytest.raises(cp.CheckpointError, match="path_unsafe"):
        cp.validate_manifest(manifest)


# -- cooperative control -------------------------------------------------------------------------------------------

def test_pipe_control_acknowledges_pause_blocks_and_resumes(tmp_path):
    command_r, command_w = os.pipe()
    event_r, event_w = os.pipe()
    control = PipeControl(command_r, event_w)
    assert control.boundary() is False
    os.write(command_w, b"PAUSE n1\n")
    outcome = []
    thread = threading.Thread(target=lambda: outcome.append(control.boundary()))
    thread.start()
    assert json.loads(os.read(event_r, 100)) == {"event": "paused", "nonce": "n1"}
    time.sleep(0.2)
    assert thread.is_alive()
    os.write(command_w, b"RESUME\n")
    thread.join(5)
    assert outcome == [False]
    os.write(command_w, b"STOP\n")
    assert control.boundary() is True
    assert PipeControl(command_r, event_w, stopping=True).boundary() is True


def test_pipe_control_treats_controller_death_as_stop():
    command_r, command_w = os.pipe()
    _, event_w = os.pipe()
    control = PipeControl(command_r, event_w)
    os.close(command_w)
    assert control.boundary() is True


def test_default_control_never_stops_and_cannot_be_changed():
    assert NO_CONTROL.boundary() is False
    with pytest.raises(RuntimeError):
        NO_CONTROL.request_stop()


# -- a private path stops at request boundaries and resumes without resending ---------------------------------------

def paged_values(root: Path, site, count=6, delay=0.0):
    source = descriptor("paged-fixture", "editorial", [
        surface("listing", "https://publisher.example/list", routes=[r"/list"], coverage="finite-index")],
        ["publisher.example"], [r"/article/[0-9]+"], bodies=["//article"])
    values = {key: value for key, value in config_data(root, site.url("")).items()
              if key not in {"maxListingPages", "maxCandidates", "maxDocuments", "maxArticleAttempts", "perDayCap"}}
    values.update(schemaVersion="zoop-private-news-config-2", selectionMode="fresh-first", stateDir=str(root / "state" / "private"),
                  sources=[{"name": "paged-fixture", "sourceType": "editorial", "reliability": "authored synthetic fixture",
                            "queries": [], "descriptor": source.wire()}])
    (root / "state").mkdir(exist_ok=True)
    values["policy"] = {**values["policy"], "maxRequests": 200, "maxTotalBytes": 8_000_000, "timeoutSeconds": 30}
    site.route("/robots.txt", b"User-agent: *\nAllow: /\n", content_type="text/plain")
    links = "".join(f'<a href="{site.url(f"/article/{i}")}">SyntheticCo {i}</a>' for i in range(count))
    site.route("/list", f"<html><main>{links}</main></html>".encode())
    for index in range(count):
        site.route(f"/article/{index}", article("2026-07-27"), **({"delay": delay} if delay else {}))
    return values


class StopAfter(Control):
    def __init__(self, boundaries):
        super().__init__()
        self.left = boundaries

    def boundary(self):
        self.left -= 1
        return self.left < 0


def test_private_run_stops_at_boundaries_and_resume_never_refetches(tmp_path):
    site = LocalSite()
    try:
        values = paged_values(tmp_path, site)
        config = intake.Config.model_validate(values)
        partial = intake.run(config, "run", StopAfter(3))
        assert partial["stopCode"] == "admission_stopped" and 0 < partial["retainedInWindow"] < 6
        first_pass = {entry["path"] for entry in site.log}
        retained = partial["retainedInWindow"]
        final = intake.run(config, "resume")
        assert final["retainedInWindow"] == 6 and final["coverage"] == "all" and final["unknownRequests"] == 0
        counts = {}
        for entry in site.log:
            counts[entry["path"]] = counts.get(entry["path"], 0) + 1
        assert all(counts[f"/article/{i}"] == 1 for i in range(6)) and retained < 6 and first_pass
    finally:
        site.close()


# -- controller ------------------------------------------------------------------------------------------------------

def controller_env(tmp_path, values, **overrides):
    state_root, config_dir = tmp_path / "state", tmp_path / "etc"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "private-config.json").write_text(json.dumps(values))
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "ZOOP_COLLECTOR_RUN_ID": "run-1",
           "ZOOP_COLLECTOR_S3_URI": "s3://bucket/pfx", "ZOOP_COLLECTOR_STATE_ROOT": str(state_root),
           "ZOOP_COLLECTOR_CONFIG_DIR": str(config_dir), "PRIVATE_CONFIG": str(config_dir / "private-config.json"),
           "ZOOP_COLLECTOR_CHECKPOINT_INTERVAL_SECONDS": "0"}
    env.update(overrides)
    return env


@contextmanager
def sigterm_when(condition, timeout=60):
    cancelled = threading.Event()

    def watcher():
        deadline = time.monotonic() + timeout
        while not cancelled.wait(0.05) and time.monotonic() < deadline:
            if condition():
                if not cancelled.is_set():
                    os.kill(os.getpid(), signal.SIGTERM)
                return

    thread = threading.Thread(target=watcher, daemon=True)
    thread.start()
    try:
        yield thread
    finally:
        cancelled.set()
        thread.join(1)
        assert not thread.is_alive(), "signal watcher outlived its test scope"


@pytest.mark.parametrize("end", ["timeout", "scope-error"])
def test_signal_watcher_leaves_its_process_alive_without_a_trigger(end):
    program = """
import signal
import sys
import threading
from tests.test_collector_container import sigterm_when

signal.signal(signal.SIGTERM, signal.SIG_DFL)
ready = threading.Event()
try:
    with sigterm_when(ready.is_set, timeout=0.1 if sys.argv[1] == "timeout" else 60) as thread:
        if sys.argv[1] == "scope-error":
            raise RuntimeError("synthetic test failure")
        thread.join(1)
except RuntimeError:
    pass
ready.set()
thread.join(1)
assert not thread.is_alive()
print("scope-closed")
"""
    child = subprocess.run([sys.executable, "-c", program, end], capture_output=True, text=True,
                           timeout=5, start_new_session=True)
    assert child.returncode == 0, (child.returncode, child.stdout, child.stderr)
    assert child.stdout.strip() == "scope-closed"


def latest_manifest(store):
    found = cp.find_checkpoint(store, "pfx/runs/run-1", "run-1")
    return found[0]


def test_sigterm_stops_admission_drains_and_uploads_a_final_checkpoint(tmp_path):
    site = LocalSite()
    try:
        values = paged_values(tmp_path, site, count=12, delay=0.4)
        env, store = controller_env(tmp_path, values), FakeStore()
        started = time.monotonic()
        with sigterm_when(lambda: site.hits("/article/2") >= 1):
            code = rt.run(env, store_factory=lambda bucket: store)
        elapsed = time.monotonic() - started
        assert code == rt.EXIT_OK and elapsed < 40
        manifest = latest_manifest(store)
        assert manifest["kind"] == "final" and manifest["paths"][0]["shutdown"] == "exited"
        names = {entry["path"] for entry in manifest["files"]}
        assert {"private/STATE.json", "private/PLAN.json", "private/QUEUE.sqlite3", "private/.lock"} <= names
        admitted = sum(site.hits(f"/article/{i}") for i in range(12))
        assert admitted < 12
        status = json.loads((tmp_path / "state" / "control" / "status.json").read_bytes())
        assert status["phase"] == "stopped" and status["workers"]["private"]["result"]["summary"]["stopCode"] == "admission_stopped"
    finally:
        site.close()


def test_restore_on_start_continues_without_refetching_settled_articles(tmp_path):
    site = LocalSite()
    try:
        values = paged_values(tmp_path, site, count=10, delay=0.3)
        env, store = controller_env(tmp_path, values), FakeStore()
        with sigterm_when(lambda: site.hits("/article/1") >= 1):
            assert rt.run(env, store_factory=lambda bucket: store) == rt.EXIT_OK
        first = latest_manifest(store)
        shutil.rmtree(tmp_path / "state")
        assert rt.run(env, store_factory=lambda bucket: store) == rt.EXIT_OK
        second = latest_manifest(store)
        assert second["seq"] == first["seq"] + 1 and second["previous"]["checkpointId"] == first["checkpointId"]
        assert all(site.hits(f"/article/{i}") == 1 for i in range(10))
        state = json.loads((tmp_path / "state" / "private" / "STATE.json").read_bytes())["state"]
        assert state["unknownRequests"] == 0 and state["stopCode"] is None
    finally:
        site.close()


def test_drain_deadline_kills_the_worker_marks_it_unknown_and_still_checkpoints(tmp_path):
    site = LocalSite()
    try:
        values = paged_values(tmp_path, site, count=4, delay=25)
        env = controller_env(tmp_path, values, ZOOP_COLLECTOR_DRAIN_SECONDS="1")
        store = FakeStore()
        started = time.monotonic()
        with sigterm_when(lambda: sum(site.hits(f"/article/{i}") for i in range(4)) >= 1):
            code = rt.run(env, store_factory=lambda bucket: store)
        assert code == rt.EXIT_OK and time.monotonic() - started < 40
        manifest = latest_manifest(store)
        assert manifest["paths"][0]["shutdown"] == "killed-marked-unknown"
        assert manifest["unknownOutcomes"] >= 1
        restored = tmp_path / "restored"
        restored.mkdir()
        cp.restore(store, "pfx/runs/run-1", "run-1", restored)
        state = json.loads((restored / "private" / "STATE.json").read_bytes())["state"]
        assert state["pendingRequest"] is None and state["unknownRequests"] >= 1
        before = {i: site.hits(f"/article/{i}") for i in range(4)}
        unknown_before = state["unknownRequests"]
        shutil.rmtree(tmp_path / "state")
        for i in range(4):
            site.route(f"/article/{i}", article("2026-07-27"))
        assert rt.run(env, store_factory=lambda bucket: store) == rt.EXIT_OK
        resumed = json.loads((tmp_path / "state" / "private" / "STATE.json").read_bytes())["state"]
        assert resumed["unknownRequests"] == unknown_before and resumed["pendingRequest"] is None
        assert resumed["blocked"] == ["127.0.0.1"]
        assert {i: site.hits(f"/article/{i}") for i in range(4)} == before
        assert sum(before.values()) == 1
    finally:
        site.close()


def test_sigterm_while_a_checkpoint_waits_for_a_busy_worker_still_drains_on_time(tmp_path):
    site = LocalSite()
    try:
        values = paged_values(tmp_path, site, count=4, delay=25)
        env = controller_env(tmp_path, values, ZOOP_COLLECTOR_DRAIN_SECONDS="1", ZOOP_COLLECTOR_CHECKPOINT_INTERVAL_SECONDS="1")
        store = FakeStore()
        started = time.monotonic()
        with sigterm_when(lambda: sum(site.hits(f"/article/{i}") for i in range(4)) >= 1 and time.monotonic() > started + 3):
            assert rt.run(env, store_factory=lambda bucket: store) == rt.EXIT_OK
        assert time.monotonic() - started < 30
        assert latest_manifest(store)["kind"] == "final"
    finally:
        site.close()


def test_sigterm_during_upload_stops_admission_and_bounds_exit(tmp_path):
    site, objects = LocalSite(), ObjectServer()
    try:
        values = paged_values(tmp_path, site, count=30, delay=0.2)
        env = controller_env(tmp_path, values, ZOOP_COLLECTOR_CHECKPOINT_INTERVAL_SECONDS="1",
                             ZOOP_COLLECTOR_DRAIN_SECONDS="1", ZOOP_COLLECTOR_RECOVER_SECONDS="1",
                             ZOOP_COLLECTOR_FINAL_SECONDS="2", ZOOP_COLLECTOR_RESERVE_SECONDS="1",
                             ZOOP_COLLECTOR_STOP_TIMEOUT_SECONDS="5")
        objects.block = lambda method, key: method == "PUT" and "/private/" in key
        observed = {}

        def upload_ready():
            if not objects.entered.is_set():
                return False
            observed["sent"] = time.monotonic()
            observed["admitted"] = sum(site.hits(f"/article/{i}") for i in range(30))
            return True

        with sigterm_when(upload_ready, timeout=15):
            code = rt.run(env, store_factory=lambda bucket: objects.client())
        assert "sent" in observed
        elapsed = time.monotonic() - observed["sent"]
        admitted = sum(site.hits(f"/article/{i}") for i in range(30))
        assert admitted <= observed["admitted"] + 1, (observed, admitted, elapsed)
        assert code == rt.EXIT_CHECKPOINT and elapsed < 5, (code, elapsed)
        print(json.dumps({"proof": "sigterm-during-upload", "seconds": elapsed,
                          "admittedAtSignal": observed["admitted"], "admittedAtExit": admitted, "exit": code}))
        objects.release.set()
        time.sleep(0.3)
        assert not [key for method, key, _ in objects.requests if method == "PUT" and key.endswith("latest.json")]
        assert len(multiprocessing.active_children()) == 1  # Only the fixture's shared-store manager remains.
    finally:
        objects.close()
        site.close()


@pytest.mark.parametrize("fault", ["stalled-put", "retry", "trickle-body"])
def test_whole_publish_deadline_preserves_previous_latest(tmp_path, fault):
    objects = ObjectServer()
    try:
        store = objects.client(read_timeout=1.2 if fault == "trickle-body" else 30)
        first, pointer = checkpoint_once(tmp_path, store)
        prior = store.get_bytes("pfx/runs/run-1/latest.json")
        staging = tmp_path / "late"
        (staging / "private").mkdir(parents=True)
        (staging / "private" / "first").write_bytes(b"first")
        (staging / "private" / "last").write_bytes(b"last")
        tables = {"dirs": ["private"], "sqlite": [], "files": [
            {"path": f"private/{name}", "bytes": len(data), "sha256": sha(data), "kind": "file"}
            for name, data in (("first", b"first"), ("last", b"last"))]}
        second = cp.build_manifest(run_id="run-1", checkpoint_id="bbbbbbbbbbbb", seq=2, kind="final",
                                   tables=tables, paths=[], unknown=0, previous=pointer, image={})
        base = cp.checkpoint_base("pfx/runs/run-1", 2, second["checkpointId"])
        started = time.monotonic()
        deadline = started + 2

        def delay_first_head(method, key):
            if method == "HEAD" and key == f"{base}/private/first":
                time.sleep(max(0, started + 1 - time.monotonic()))

        objects.before = delay_first_head
        if fault == "stalled-put":
            objects.block = lambda method, key: method == "PUT" and key == f"{base}/private/last"
        elif fault == "retry":
            objects.retry_key = f"{base}/private/last"
        else:
            objects.trickle = True
        with pytest.raises(cp.CheckpointError, match="deadline_exceeded"):
            cp.publish(store, "pfx/runs/run-1", staging, second, first, deadline=deadline, workers=1)
        elapsed = time.monotonic() - started
        last_start = next(at for method, key, at in objects.requests if method == "PUT" and key == f"{base}/private/last")
        assert 0.9 <= last_start - started < 1.5
        assert elapsed < 2
        objects.release.set()
        objects.trickle = False
        requests_at_return = len(objects.requests)
        time.sleep(0.4)
        assert len(objects.requests) == requests_at_return
        assert store.get_bytes("pfx/runs/run-1/latest.json") == prior
        restored = tmp_path / "restored"
        restored.mkdir()
        manifest = cp.restore(store, "pfx/runs/run-1", "run-1", restored)
        assert manifest["checkpointId"] == first["checkpointId"] and manifest["unknownOutcomes"] == 2
        assert cp.count_unknown("private", restored) == 2
        assert len(multiprocessing.active_children()) == 1
        print(json.dumps({"proof": fault, "seconds": elapsed, "lastTransferStartSeconds": last_start - started,
                          "deadlineSeconds": 2, "restoredUnknown": 2}))
    finally:
        objects.close()


@pytest.mark.parametrize("interrupt", ["deadline", "sigterm", "read-timeout"])
def test_accepted_latest_with_lost_response_is_unknown_and_never_retried(tmp_path, interrupt):
    site, objects = LocalSite(), ObjectServer()
    try:
        values = paged_values(tmp_path, site, count=12 if interrupt == "sigterm" else 1, delay=0.2)
        env = controller_env(tmp_path, values, ZOOP_COLLECTOR_CHECKPOINT_INTERVAL_SECONDS="1" if interrupt == "sigterm" else "0",
                             ZOOP_COLLECTOR_DRAIN_SECONDS="1", ZOOP_COLLECTOR_RECOVER_SECONDS="1",
                             ZOOP_COLLECTOR_FINAL_SECONDS="3", ZOOP_COLLECTOR_RESERVE_SECONDS="1",
                             ZOOP_COLLECTOR_STOP_TIMEOUT_SECONDS="6")
        objects.block = lambda method, key: method == "PUT" and key.endswith("latest.json")
        started = time.monotonic()
        with sigterm_when(objects.entered.is_set) if interrupt == "sigterm" else nullcontext():
            code = rt.run(env, store_factory=lambda bucket: objects.client(read_timeout=0.1 if interrupt == "read-timeout" else 30))
        elapsed = time.monotonic() - started
        assert objects.entered.is_set() and code == rt.EXIT_CHECKPOINT
        status = json.loads((tmp_path / "state" / "control" / "status.json").read_bytes())
        assert status["publicationUnknown"]["manifestKey"].endswith("/MANIFEST.json")
        assert status["phase"] == "stopped"
        accepted = json.loads(objects.store.get_bytes("pfx/runs/run-1/latest.json"))
        assert accepted["manifestKey"] == status["publicationUnknown"]["manifestKey"]
        objects.release.set()
        time.sleep(0.4)
        puts = [key for method, key, _ in objects.requests if method == "PUT" and key.endswith("latest.json")]
        assert len(puts) == 1 and elapsed < 6
        assert len(multiprocessing.active_children()) == 1
        print(json.dumps({"proof": f"accepted-latest-{interrupt}", "seconds": elapsed, "exit": code,
                          "latestPuts": len(puts), "unknown": status["publicationUnknown"]}))
    finally:
        objects.close()
        site.close()


@pytest.mark.parametrize("kind", ["requested", "periodic"])
def test_periodic_and_external_checkpoint_is_served_by_the_live_controller(tmp_path, kind):
    site = LocalSite()
    try:
        values = paged_values(tmp_path, site, count=10, delay=0.3)
        env = controller_env(tmp_path, values, ZOOP_COLLECTOR_CHECKPOINT_INTERVAL_SECONDS="1" if kind == "periodic" else "0")
        store = FakeStore()
        os.environ.update({key: env[key] for key in ("ZOOP_COLLECTOR_STATE_ROOT", "ZOOP_COLLECTOR_CONFIG_DIR")})
        outcome = []
        checkpoint_ready = threading.Event()

        def client():
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and not (tmp_path / "state" / "control" / "status.json").exists():
                time.sleep(0.05)
            if kind == "requested":
                outcome.append(cli._checkpoint(60))
            else:
                while time.monotonic() < deadline:
                    status = json.loads((tmp_path / "state" / "control" / "status.json").read_bytes())
                    if status["lastCheckpoint"] is not None:
                        break
                    time.sleep(0.05)
            checkpoint_ready.set()

        threading.Thread(target=client, daemon=True).start()
        try:
            with sigterm_when(checkpoint_ready.is_set):
                assert rt.run(env, store_factory=lambda bucket: store) == rt.EXIT_OK
        finally:
            os.environ.pop("ZOOP_COLLECTOR_STATE_ROOT")
            os.environ.pop("ZOOP_COLLECTOR_CONFIG_DIR")
        assert outcome == ([rt.EXIT_OK] if kind == "requested" else [])
        first = [key for key in store.objects if key.endswith("MANIFEST.json") and "/000001-" in key]
        kinds = [json.loads(store.objects[key][0])["kind"] for key in first]
        assert kinds == [kind] and latest_manifest(store)["kind"] == "final"
    finally:
        site.close()


def test_checkpoint_command_refuses_without_a_live_controller(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ZOOP_COLLECTOR_STATE_ROOT", str(tmp_path / "state"))
    assert cli._checkpoint(1) == rt.EXIT_NO_CONTROLLER
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "controller.lock").write_bytes(b"")
    assert cli._checkpoint(1) == rt.EXIT_NO_CONTROLLER
    assert not (tmp_path / "state" / "control").exists()


def test_a_second_controller_on_the_same_state_root_is_refused(tmp_path):
    site = LocalSite()
    try:
        env = controller_env(tmp_path, paged_values(tmp_path, site))
        import fcntl
        holder = os.open(tmp_path / "state" / "controller.lock", os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(holder, fcntl.LOCK_EX)
        try:
            assert rt.run(env, store_factory=lambda bucket: FakeStore()) == rt.EXIT_BUSY
        finally:
            os.close(holder)
    finally:
        site.close()


# -- settings and configuration supply -------------------------------------------------------------------------------

def test_settings_refuse_a_stop_budget_longer_than_the_container_stop_timeout():
    env = {"ZOOP_COLLECTOR_RUN_ID": "r", "ZOOP_COLLECTOR_DRAIN_SECONDS": "80"}
    with pytest.raises(rt.ConfigError, match="stop_budget_exceeds_timeout"):
        rt.settings_from_env(env)
    assert rt.settings_from_env({"ZOOP_COLLECTOR_RUN_ID": "r"}).stop_budget() == 115
    with pytest.raises(rt.ConfigError, match="run_id_invalid"):
        rt.settings_from_env({"ZOOP_COLLECTOR_RUN_ID": "../x"})
    with pytest.raises(rt.ConfigError, match="config_pin_required"):
        rt.settings_from_env({"ZOOP_COLLECTOR_RUN_ID": "r", "PRIVATE_CONFIG": "/etc/x.json", "PRIVATE_CONFIG_S3_URI": "s3://b/k"})


def supply(tmp_path, values, **overrides):
    env = controller_env(tmp_path, values, **overrides)
    return rt.settings_from_env(env), env


def test_config_supply_verifies_the_pinned_digest_before_writing(tmp_path):
    site = LocalSite()
    try:
        values = paged_values(tmp_path, site)
        raw = json.dumps(values).encode()
        store = FakeStore()
        store.objects["cfg/private.json"] = (raw, None)
        target = tmp_path / "etc" / "fetched.json"
        settings, env = supply(tmp_path, values, PRIVATE_CONFIG=str(target), PRIVATE_CONFIG_S3_URI="s3://bucket/cfg/private.json",
                               PRIVATE_CONFIG_SHA256="0" * 64)
        with pytest.raises(rt.ConfigError, match="config_sha256_mismatch"):
            rt.supply_configs(settings, env, lambda bucket: store)
        assert not target.exists()
        settings, env = supply(tmp_path, values, PRIVATE_CONFIG=str(target), PRIVATE_CONFIG_S3_URI="s3://bucket/cfg/private.json",
                               PRIVATE_CONFIG_SHA256=sha(raw))
        assert rt.supply_configs(settings, env, lambda bucket: store)["private"].plan_id == values["planId"]
        assert oct(target.stat().st_mode & 0o777) == "0o444"
    finally:
        site.close()


def test_config_supply_refuses_unsupported_and_unfixed_configuration(tmp_path):
    site = LocalSite()
    try:
        values = paged_values(tmp_path, site)
        settings, env = supply(tmp_path, {**values, "stateDir": str(tmp_path / "elsewhere")})
        with pytest.raises(rt.ConfigError, match="state_dir_not_fixed"):
            rt.supply_configs(settings, env, None)
        values["predecessor"] = {"stateDir": str(tmp_path / "old"), "planSha256": "0" * 64, "stateSha256": "0" * 64, "queueSha256": "0" * 64}
        settings, env = supply(tmp_path, values)
        with pytest.raises(rt.ConfigError, match="config_unsupported"):
            rt.supply_configs(settings, env, None)
    finally:
        site.close()


def test_restore_is_bound_to_the_plan_and_state_directory_it_was_taken_for(tmp_path):
    site = LocalSite()
    try:
        values = paged_values(tmp_path, site)
        settings, _ = supply(tmp_path, values)
        manifest = {"paths": [{"name": "private", "stateDir": str(settings.state_dir("private")),
                               "configSha256": sha(settings.paths["private"].config_path.read_bytes())}]}
        rt.check_restorable(manifest, settings, {"private": settings.paths["private"].config_path})
        for field, value, code in (("configSha256", "0" * 64, "restore_config_changed"),
                                   ("stateDir", "/elsewhere/private", "restore_state_dir_mismatch"),
                                   ("name", "korea", "restore_path_not_configured")):
            broken = {"paths": [{**manifest["paths"][0], field: value}]}
            with pytest.raises(rt.ConfigError, match=code):
                rt.check_restorable(broken, settings, {"private": settings.paths["private"].config_path})
    finally:
        site.close()


def test_korea_and_official_paths_stop_before_admission_and_resume(tmp_path):
    from scripts.korea_corpus_smoke import article as korea_article, config as korea_config, listing
    from tests.test_official_source_adapters import config as official_config, fsc_routes
    from zoop_ai_pipeline import korea_corpus as corpus
    from zoop_ai_pipeline import official_source_intake as official
    from zoop_ai_pipeline.korea_portal import ROUTES

    site = LocalSite()
    try:
        site.route("/robots.txt", b"User-agent: *\nAllow: /\n", content_type="text/plain")
        value, _ = korea_config(tmp_path / "korea", site)
        site.route(ROUTES["policy-news"][0], listing(["100000001"]))
        site.route(ROUTES["policy-news"][1], korea_article(site, "100000001"))
        config = corpus.Config.model_validate(value)
        stopped = corpus.run(config, StopAfter(0))
        assert stopped["state"] == "partial" and site.log == []
        assert corpus.run(config)["counts"]["exported"] == 1
        fsc_routes(site)
        site.log.clear()
        selected = official_config(site, tmp_path / "official")
        assert official.run(selected, "run", control=StopAfter(0))["state"] == "partial" and site.log == []
        assert official.run(selected, "resume")["retainedInWindow"] == 1
    finally:
        site.close()
