"""Post-child-exit metadata export without opening the source ledger in SQLite.

The caller must have waited for the child and prevented another job from starting
in the same state directory. Existing native writer locks are also respected.
DB/WAL/SHM bytes, identity and metadata are pinned before and after copying and
again after recovery. Only a unique owned copy is opened in SQLite; captured
bytes and manifest.json remain separate from that disposable recovery copy.

Rows retain native response/verdict/state values. A started call without response
is still unknown, not proof of a send or permission to release/resend a budget
reservation. A refusal raises ValueError, never a misleading empty result. The
manifest is provenance for this read, not a repair of any historical journal.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import struct
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path


_SUFFIXES = ("", "-wal", "-shm")


def _metadata(info: os.stat_result) -> dict:
    # Reading can update atime; preserving it would itself require a source write.
    return {"device": info.st_dev, "inode": info.st_ino, "mode": info.st_mode,
            "links": info.st_nlink, "uid": info.st_uid, "gid": info.st_gid,
            "size": info.st_size, "mtimeNs": info.st_mtime_ns, "ctimeNs": info.st_ctime_ns}


def _members(database: Path, *, initial: bool = False) -> dict:
    members = {}
    for suffix in _SUFFIXES:
        path = database.with_name(database.name + suffix)
        try:
            info = path.lstat()
        except FileNotFoundError:
            if suffix:
                continue
            raise ValueError("receipt_source_missing" if initial else "receipt_source_changed") from None
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("receipt_source_not_regular")
        members[path.name] = _metadata(info)
    if database.name + "-shm" in members and database.name + "-wal" not in members:
        raise ValueError("receipt_source_missing" if initial else "receipt_source_changed")
    return members


@contextmanager
def _source_file(path: Path, expected: dict):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError as exc:
        raise ValueError("receipt_source_changed") from exc
    with os.fdopen(descriptor, "rb", buffering=0) as source:
        if _metadata(os.fstat(source.fileno())) != expected:
            raise ValueError("receipt_source_changed")
        yield source
        if _metadata(os.fstat(source.fileno())) != expected:
            raise ValueError("receipt_source_changed")
        try:
            current = _metadata(path.lstat())
        except FileNotFoundError as exc:
            raise ValueError("receipt_source_changed") from exc
        if current != expected:
            raise ValueError("receipt_source_changed")


def _fingerprints(database: Path, *, initial: bool = False) -> dict:
    members = _members(database, initial=initial)
    result = {}
    for name, metadata in members.items():
        with _source_file(database.parent / name, metadata) as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        result[name] = {**metadata, "sha256": digest}
    if _members(database) != members:
        raise ValueError("receipt_source_changed")
    return result


@contextmanager
def _quiescent_writer(database: Path):
    # Never create/adopt a native lock or open a Store just to inspect receipts.
    lock = database.with_suffix(".lock")
    try:
        descriptor = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        yield
        return
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("receipt_source_not_regular")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("receipt_writer_not_quiescent") from exc
        yield
    finally:
        os.close(descriptor)


def _bounded_chunks(reader, size):
    """Read exactly the pinned size plus one EOF sentinel, even if the source keeps growing."""
    remaining = size
    while remaining:
        chunk = reader.read(min(1024 * 1024, remaining))
        if not chunk:
            raise ValueError("receipt_source_changed")
        remaining -= len(chunk)
        yield chunk
    if reader.read(1):
        raise ValueError("receipt_source_changed")


def _bounded_hash(reader, size):
    digest = hashlib.sha256()
    for chunk in _bounded_chunks(reader, size):
        digest.update(chunk)
    return digest.hexdigest()


def _capture(source: Path, target: Path, expected: dict) -> None:
    metadata = {key: value for key, value in expected.items() if key != "sha256"}
    with _source_file(source, metadata) as reader, target.open("xb") as writer:
        os.fchmod(writer.fileno(), 0o600)
        for chunk in _bounded_chunks(reader, expected["size"]):
            writer.write(chunk)
        writer.flush()
        os.fsync(writer.fileno())
    with target.open("rb") as copied:
        actual = _bounded_hash(copied, expected["size"])
    if target.stat().st_size != expected["size"] or actual != expected["sha256"]:
        raise ValueError("receipt_copy_mismatch")
    target.chmod(0o400)


def capture_quiescent_sqlite(database: Path, target: Path) -> dict:
    """Capture bounded immutable bytes without SQLite access or opening the producer lock."""
    from zoop_ai_pipeline.ingestion_contracts import MAX_LEDGER_COPY
    database, target = Path(database), Path(target)
    sidecars = {database.name + suffix for suffix in ("-wal", "-shm", "-journal")}
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)

    def inspect():
        for parent in [*reversed(database.parent.parents), database.parent]:
            if not stat.S_ISDIR(parent.lstat().st_mode):
                raise ValueError("ingestion_state_not_regular")
        for member in database.parent.iterdir():
            info = member.lstat()
            if member.name in sidecars:
                raise ValueError("ingestion_state_not_quiescent")
            if member.name not in {database.name, "ingestion.lock"}:
                raise ValueError("state_namespace_conflict")
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("ingestion_state_not_regular")
        metadata = _metadata(database.lstat())
        if metadata["size"] > MAX_LEDGER_COPY:
            raise ValueError("ingestion_state_too_large")
        return metadata

    before = inspect()
    try:
        with _source_file(database, before) as source:
            fingerprint = {**before, "sha256": _bounded_hash(source, before["size"])}
        _capture(database, target, fingerprint)
        if inspect() != before:
            raise ValueError("ingestion_state_changed")
        with _source_file(database, before) as source:
            if _bounded_hash(source, before["size"]) != fingerprint["sha256"]:
                raise ValueError("ingestion_state_changed")
        if inspect() != before:
            raise ValueError("ingestion_state_changed")
    except (ValueError, OSError) as exc:
        target.unlink(missing_ok=True)
        raise ValueError("ingestion_state_changed") from exc
    return {"name": database.name, **fingerprint}


def _wal_checksum(data: bytes, endian: str, seed: tuple[int, int]) -> tuple[int, int]:
    first, second = seed
    for left, right in struct.iter_unpack(endian + "II", data):
        first = (first + left + second) & 0xFFFFFFFF
        second = (second + right + first) & 0xFFFFFFFF
    return first, second


def _wal_commit(database: Path) -> tuple[int, int | None]:
    """Pin the last committed frame so SQLite cannot silently ignore a bad WAL.

    Validate checksums before recovery, then require SQLite to report every
    committed frame. Old salt tails after WAL reuse are not part of the current
    log; uncommitted frames are not receipts. Partial/invalid current frames are
    refused rather than silently dropped or repaired.
    """
    wal = database.with_name(database.name + "-wal")
    if not wal.exists() or wal.stat().st_size == 0:
        return 0, None
    size = wal.stat().st_size
    with wal.open("rb") as source:
        header = source.read(32)
        if len(header) != 32:
            raise ValueError("receipt_recovery_mismatch")
        magic, version, page_size = struct.unpack(">III", header[:12])
        if (magic not in (0x377F0682, 0x377F0683) or version != 3_007_000
                or page_size < 512 or page_size > 65_536 or page_size & (page_size - 1)):
            raise ValueError("receipt_recovery_mismatch")
        endian = "<" if magic == 0x377F0682 else ">"
        checksum = _wal_checksum(header[:24], endian, (0, 0))
        if checksum != struct.unpack(">II", header[24:32]):
            raise ValueError("receipt_recovery_mismatch")
        frame_size = 24 + page_size
        if (size - 32) % frame_size:
            raise ValueError("receipt_recovery_mismatch")
        committed, pages = 0, None
        for index in range(1, (size - 32) // frame_size + 1):
            frame = source.read(24)
            if frame[8:16] != header[16:24]:
                if index == 1:
                    raise ValueError("receipt_recovery_mismatch")
                break
            page, database_size = struct.unpack(">II", frame[:8])
            if page == 0:
                raise ValueError("receipt_recovery_mismatch")
            if database_size:
                committed, pages = index, database_size
            checksum = _wal_checksum(source.read(page_size), endian, _wal_checksum(frame[:8], endian, checksum))
            if checksum != struct.unpack(">II", frame[16:24]):
                raise ValueError("receipt_recovery_mismatch")
    return committed, pages


def _rows(connection: sqlite3.Connection, job_id: str, state_name: str) -> list[dict]:
    rows = [dict(row) for row in connection.execute(
        "SELECT * FROM calls WHERE job_id=? ORDER BY started_at,attempt_id", (job_id,))]
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    refused = {row[0] for row in connection.execute("SELECT attempt_id FROM refusals")} if "refusals" in tables else set()
    if state_name == "relation":
        refused.update(row[0] for row in connection.execute(
            "SELECT ref FROM stages WHERE job_id=? AND stage='refusal'", (job_id,)))
    for row in rows:
        row["provenUnsent"] = row["state"] == "unsent" or row["attempt_id"] in refused
    return rows


def _recover(database: Path, job_id: str, state_name: str, expected: tuple[int, int | None]) -> tuple[list[dict], dict]:
    committed, pages = expected
    # The copied wal-index is only a cache. Rebuild it from the captured WAL so
    # its pre-crash contents cannot bypass recovery; never unlink the source SHM.
    database.with_name(database.name + "-shm").unlink(missing_ok=True)
    with closing(sqlite3.connect(database.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=0)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA trusted_schema=OFF")
        if [row[0] for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
            raise ValueError("receipt_recovery_mismatch")
        rows = _rows(connection, job_id, state_name)
        busy, logged, checkpointed = connection.execute("PRAGMA wal_checkpoint(FULL)").fetchone()
        if busy or (committed and (logged != committed or checkpointed != committed)):
            raise ValueError("receipt_recovery_mismatch")
        if not committed and (logged not in (-1, 0) or checkpointed not in (-1, 0)):
            raise ValueError("receipt_recovery_mismatch")
        page_count = connection.execute("PRAGMA page_count").fetchone()[0]
        if pages is not None and page_count != pages:
            raise ValueError("receipt_recovery_mismatch")
        if _rows(connection, job_id, state_name) != rows:
            raise ValueError("receipt_recovery_mismatch")
    return rows, {"committedWalFrames": committed, "checkpointedFrames": checkpointed,
                  "pageCount": page_count, "integrityCheck": "ok"}


def read_call_rows(database: Path, snapshot_root: Path, *, job_id: str, state_name: str, child_exited: bool) -> list[dict]:
    """Return native call rows plus provenUnsent; retain partial/unknown attempts.

    Each successful read owns a new snapshot_root/receipt-*/manifest.json, even
    on repeated reads. Only completed, source-stable reads write that manifest.
    Source/capture failures retain their artifacts and raise receipt_* ValueError;
    callers must report unknown/incomplete coverage, not treat refusal as [].
    """
    if child_exited is not True:
        raise ValueError("receipt_child_not_exited")
    database = Path(os.path.abspath(database))
    snapshot_root = Path(os.path.abspath(snapshot_root))
    if snapshot_root.resolve().is_relative_to(database.parent.resolve()):
        raise ValueError("receipt_snapshot_namespace_conflict")
    try:
        with _quiescent_writer(database):
            before = _fingerprints(database, initial=True)
            parent_identity = database.parent.stat()
            snapshot_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            snapshot = Path(tempfile.mkdtemp(prefix="receipt-", dir=snapshot_root))
            captured, recovered = snapshot / "captured", snapshot / "recovered"
            captured.mkdir(mode=0o700)
            recovered.mkdir(mode=0o700)
            for name, fingerprint in before.items():
                _capture(database.parent / name, captured / name, fingerprint)
            if _fingerprints(database) != before:
                raise ValueError("receipt_source_changed")
            for name, fingerprint in before.items():
                target = recovered / name
                shutil.copyfile(captured / name, target)
                target.chmod(0o600)
                with target.open("rb") as copied:
                    if hashlib.file_digest(copied, "sha256").hexdigest() != fingerprint["sha256"]:
                        raise ValueError("receipt_copy_mismatch")
            expected = _wal_commit(captured / database.name)
            rows, recovery = _recover(recovered / database.name, job_id, state_name, expected)
            after_parent = database.parent.stat()
            if (_fingerprints(database) != before or
                    (after_parent.st_dev, after_parent.st_ino) != (parent_identity.st_dev, parent_identity.st_ino)):
                raise ValueError("receipt_source_changed")
            manifest = {"schemaVersion": "zoop-receipt-snapshot-1", "sourceDatabase": str(database),
                        "jobId": job_id, "stateName": state_name, "childExited": True,
                        "files": [{"name": name, "capturedPath": "captured/" + name, **fingerprint}
                                  for name, fingerprint in before.items()],
                        "recovery": recovery, "callCount": len(rows),
                        "rowsSha256": hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False,
                                                               separators=(",", ":")).encode()).hexdigest()}
            with (snapshot / "manifest.json").open("x", encoding="utf-8") as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")
                output.flush()
                os.fsync(output.fileno())
                os.fchmod(output.fileno(), 0o400)
            return rows
    except (sqlite3.Error, struct.error, KeyError) as exc:
        raise ValueError("receipt_snapshot_recovery_failed") from exc
    except OSError as exc:
        raise ValueError("receipt_snapshot_io_failed") from exc
