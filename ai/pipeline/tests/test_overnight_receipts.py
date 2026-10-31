"""Offline receipt recovery from actual crashed SQLite WAL fixtures; no providers."""
from __future__ import annotations

import fcntl
import hashlib
import json
import multiprocessing
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))
from scripts import overnight_receipts as receipts


JOB = "partial-job"
RESPONSE = ' {"cost": {"settled": true}, "answer": "preserve original spacing"} '


def _crashed_writer(database, relation, refusal_table):
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE calls(attempt_id TEXT PRIMARY KEY,job_id TEXT,stage TEXT,ref TEXT,"
                       "request_digest TEXT,fixture_hash TEXT,state TEXT,response TEXT,response_digest TEXT,"
                       "verdict TEXT,started_at TEXT,received_at TEXT)")
    if relation:
        connection.execute("CREATE TABLE stages(job_id TEXT,stage TEXT,ref TEXT,summary TEXT,completed_at TEXT)")
    if refusal_table:
        connection.execute("CREATE TABLE refusals(attempt_id TEXT PRIMARY KEY,job_id TEXT,code TEXT,created_at TEXT)")
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    # Earlier received calls and the last reservation exist only in WAL, not the main database.
    rows = [
        ("attempt-b", JOB, "compare", "received", RESPONSE, "HOLD", "2026-10-28T00:00:00Z", "2026-10-28T00:00:01Z"),
        ("attempt-a", JOB, "extract", "received", RESPONSE, "receipt_contract_invalid", "2026-10-28T00:00:00Z", "2026-10-28T00:00:01Z"),
        ("attempt-refused", JOB, "verify-relation", "started", None, None, "2026-10-28T00:00:02Z", None),
        ("attempt-unsent", JOB, "extract", "unsent", None, "live_budget_exhausted_shared", "2026-10-28T00:00:03Z", None),
        ("attempt-other", "other-job", "extract", "received", RESPONSE, None, "2026-10-28T00:00:04Z", "2026-10-28T00:00:05Z"),
        ("attempt-unknown", JOB, "topic", "started", None, None, "2026-10-28T00:00:06Z", None),
    ]
    for attempt, job, stage, state, response, verdict, started, received in rows:
        connection.execute("INSERT INTO calls VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (attempt, job, stage, attempt, "request", "fixture", state, response,
                            hashlib.sha256(response.encode()).hexdigest() if response else None, verdict, started, received))
        connection.commit()
    if relation:
        connection.executemany("INSERT INTO stages VALUES(?,?,?,?,?)", [
            (JOB, "refusal", "attempt-refused", '{"code":"live_budget_exhausted_personal"}', "now"),
            ("other-job", "refusal", "attempt-unknown", "{}", "now"),
            (JOB, "verify-relation", "attempt-unknown", "{}", "now"),
        ])
    if refusal_table:
        connection.execute("INSERT INTO refusals VALUES(?,?,?,?)", ("attempt-refused", JOB, "live_budget_exhausted_personal", "now"))
    connection.commit()
    # Deliberately bypass connection.close(): this is a stopped writer with uncheckpointed commits.
    os._exit(0)


def _mutating_writer(database, channel):
    # A separate process avoids releasing SQLite's process-owned locks when the
    # reader closes its byte-only descriptors for the same DB/WAL/SHM inodes.
    writer = sqlite3.connect(database)
    try:
        channel.send("ready")
        while channel.recv() != "stop":
            writer.execute("UPDATE calls SET verdict='changed-by-live-writer' WHERE attempt_id='attempt-a'")
            writer.commit()
            channel.send("committed")
    finally:
        writer.close()
        channel.close()


def make_wal(tmp_path, *, relation=False, refusal_table=False):
    source = tmp_path / "source"
    source.mkdir()
    database = source / ("relation.sqlite3" if relation else "extraction.sqlite3")
    child = multiprocessing.get_context("spawn").Process(target=_crashed_writer, args=(database, relation, refusal_table))
    child.start()
    child.join(20)
    if child.is_alive():
        child.kill()
        child.join()
        pytest.fail("SQLite fixture writer did not exit")
    assert child.exitcode == 0
    assert database.with_name(database.name + "-wal").stat().st_size > 32
    assert database.with_name(database.name + "-shm").is_file()
    return database


def source_evidence(database):
    evidence = {}
    for path in sorted(database.parent.iterdir()):
        info = path.stat()
        evidence[path.name] = (path.read_bytes(), info.st_dev, info.st_ino, info.st_mode,
                               info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    return evidence


def read(database, root, *, relation=False, child_exited=True):
    return receipts.read_call_rows(database, root, job_id=JOB,
                                   state_name="relation" if relation else "extraction", child_exited=child_exited)


def test_hot_wal_retains_received_and_unknown_calls_without_touching_source(tmp_path, monkeypatch):
    database = make_wal(tmp_path)
    for path in database.parent.iterdir():
        path.chmod(0o440)
        os.utime(path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    before = source_evidence(database)
    root = tmp_path / "snapshots"
    real_connect = sqlite3.connect
    opened = []

    def owned_connect(target, *args, **kwargs):
        assert isinstance(target, str) and kwargs.get("uri") is True
        uri = urlsplit(target)
        assert Path(unquote(uri.path)).is_relative_to(root)
        assert "immutable" not in uri.query and "mode=rw" in uri.query
        opened.append(target)
        return real_connect(target, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", owned_connect)
    rows = read(database, root)
    assert len(opened) == 1
    assert [row["attempt_id"] for row in rows] == ["attempt-a", "attempt-b", "attempt-refused", "attempt-unsent", "attempt-unknown"]
    assert [row["response"] for row in rows[:2]] == [RESPONSE, RESPONSE]
    assert [row["verdict"] for row in rows[:2]] == ["receipt_contract_invalid", "HOLD"]
    assert rows[-1]["state"] == "started" and rows[-1]["response"] is None
    assert rows[-1]["received_at"] is None and rows[-1]["verdict"] is None
    assert rows[-1]["provenUnsent"] is False
    assert rows[-2]["provenUnsent"] is True
    assert source_evidence(database) == before
    manifests = list(root.glob("*/manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text())
    assert manifest["jobId"] == JOB and manifest["childExited"] is True
    assert manifest["callCount"] == 5
    assert manifest["recovery"]["committedWalFrames"] > 0
    for entry in manifest["files"]:
        captured = manifests[0].parent / entry["capturedPath"]
        assert captured.read_bytes() == before[entry["name"]][0]
        assert hashlib.sha256(captured.read_bytes()).hexdigest() == entry["sha256"]
        assert captured.stat().st_mode & 0o777 == 0o400
    assert manifests[0].stat().st_mode & 0o777 == 0o400


def test_repeated_reads_are_identical_but_own_distinct_snapshots(tmp_path):
    database = make_wal(tmp_path)
    before = source_evidence(database)
    root = tmp_path / "snapshots"
    assert read(database, root) == read(database, root)
    manifests = list(root.glob("*/manifest.json"))
    assert len(manifests) == 2 and manifests[0].parent != manifests[1].parent
    copies = [manifest.parent / "captured" / database.name for manifest in manifests]
    assert copies[0].stat().st_ino != copies[1].stat().st_ino
    assert all(path.stat().st_ino != database.stat().st_ino for path in copies)
    assert source_evidence(database) == before


def test_child_must_have_exited_before_any_source_access(tmp_path, monkeypatch):
    def forbidden_open(*args, **kwargs):
        pytest.fail("child-exit refusal must precede source access")

    monkeypatch.setattr(os, "open", forbidden_open)
    root = tmp_path / "snapshots"
    with pytest.raises(ValueError, match="receipt_child_not_exited"):
        read(tmp_path / "absent.sqlite3", root, child_exited=False)
    assert not root.exists()


def test_native_writer_lock_refuses_snapshot_even_with_child_exit_attestation(tmp_path):
    database = make_wal(tmp_path)
    lock = database.with_suffix(".lock")
    with lock.open("wb") as writer:
        fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = source_evidence(database)
        with pytest.raises(ValueError, match="receipt_writer_not_quiescent"):
            read(database, tmp_path / "snapshots")
        assert source_evidence(database) == before
    assert not (tmp_path / "snapshots").exists()


def test_writer_mutation_during_copy_refuses_partial_result(tmp_path, monkeypatch):
    database = make_wal(tmp_path)
    context = multiprocessing.get_context("spawn")
    channel, child_channel = context.Pipe()
    writer = context.Process(target=_mutating_writer, args=(database, child_channel))
    writer.start()
    child_channel.close()
    real_copy = receipts._capture
    mutated = False

    def mutate_after_copy(source, destination, *args, **kwargs):
        nonlocal mutated
        real_copy(source, destination, *args, **kwargs)
        if not mutated:
            mutated = True
            channel.send("mutate")
            assert channel.poll(20) and channel.recv() == "committed"

    monkeypatch.setattr(receipts, "_capture", mutate_after_copy)
    root = tmp_path / "snapshots"
    try:
        assert channel.poll(20) and channel.recv() == "ready"
        with pytest.raises(ValueError, match="receipt_source_changed"):
            read(database, root)
        assert mutated
        assert database.is_file() and database.with_name(database.name + "-wal").is_file()
        assert not list(root.glob("*/manifest.json"))
    finally:
        if writer.is_alive():
            channel.send("stop")
        writer.join(20)
        if writer.is_alive():
            writer.kill()
            writer.join()
        channel.close()
    assert writer.exitcode == 0


@pytest.mark.parametrize("change", ["missing-wal", "replace-db", "metadata", "copied-bytes"])
def test_copy_refuses_missing_changed_or_mismatched_members(tmp_path, monkeypatch, change):
    database = make_wal(tmp_path)
    real_copy = receipts._capture
    changed = False

    def change_after_copy(source, destination, *args, **kwargs):
        nonlocal changed
        real_copy(source, destination, *args, **kwargs)
        if changed:
            return
        changed = True
        if change == "missing-wal":
            database.with_name(database.name + "-wal").unlink()
        elif change == "replace-db":
            replacement = database.with_name("replacement")
            replacement.write_bytes(database.read_bytes())
            os.replace(replacement, database)
        elif change == "metadata":
            info = database.stat()
            os.utime(database, ns=(info.st_atime_ns, info.st_mtime_ns + 1))
        else:
            destination.chmod(0o600)
            with destination.open("r+b") as copied:
                copied.write(b"not sqlite")
            destination.chmod(0o400)

    monkeypatch.setattr(receipts, "_capture", change_after_copy)
    root = tmp_path / "snapshots"
    with pytest.raises(ValueError, match="receipt_(source_changed|copy_mismatch)"):
        read(database, root)
    assert changed and database.exists()
    assert not list(root.glob("*/manifest.json"))


@pytest.mark.parametrize("relation,refusal_table", [(False, False), (False, True), (True, False), (True, True)])
def test_optional_refusals_and_relation_stages_preserve_native_evidence(tmp_path, relation, refusal_table):
    database = make_wal(tmp_path, relation=relation, refusal_table=refusal_table)
    before = source_evidence(database)
    rows = {row["attempt_id"]: row for row in read(database, tmp_path / "snapshots", relation=relation)}
    assert rows["attempt-refused"]["provenUnsent"] is (relation or refusal_table)
    assert rows["attempt-refused"]["state"] == "started"
    assert rows["attempt-refused"]["response"] is None and rows["attempt-refused"]["verdict"] is None
    assert rows["attempt-unknown"]["provenUnsent"] is False
    assert rows["attempt-unsent"]["provenUnsent"] is True
    assert source_evidence(database) == before


@pytest.mark.parametrize("offset", [-1, 24, 40])
def test_corrupt_wal_cannot_silently_drop_a_committed_receipt(tmp_path, offset):
    database = make_wal(tmp_path)
    wal = database.with_name(database.name + "-wal")
    data = bytearray(wal.read_bytes())
    data[offset] ^= 1  # Break a frame, header checksum or first salt; never mutate the main database.
    wal.write_bytes(data)
    before = source_evidence(database)
    root = tmp_path / "snapshots"
    with pytest.raises(ValueError, match="receipt_(recovery_mismatch|snapshot_recovery_failed)"):
        read(database, root)
    assert source_evidence(database) == before
    assert not list(root.glob("*/manifest.json"))


def test_missing_database_fails_closed_instead_of_returning_empty(tmp_path):
    root = tmp_path / "snapshots"
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="receipt_source_missing"):
        read(source / "missing.sqlite3", root)
    assert not root.exists()


def test_wal_without_shm_recovers_without_creating_original_sidecars(tmp_path):
    database = make_wal(tmp_path)
    database.with_name(database.name + "-shm").unlink()
    before = source_evidence(database)
    assert len(read(database, tmp_path / "snapshots")) == 5
    assert source_evidence(database) == before


def test_checkpointed_database_without_optional_sidecars_is_readable(tmp_path):
    database = make_wal(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    assert not database.with_name(database.name + "-wal").exists()
    before = source_evidence(database)
    assert len(read(database, tmp_path / "snapshots")) == 5
    assert source_evidence(database) == before


def test_snapshot_destination_cannot_be_inside_source_state(tmp_path):
    database = make_wal(tmp_path)
    before = source_evidence(database)
    with pytest.raises(ValueError, match="receipt_snapshot_namespace_conflict"):
        read(database, database.parent / "snapshots")
    assert source_evidence(database) == before
