"""Consistent checkpoints of the collector state: SQLite online backup, closed-file copy, hashed manifest written last.

`capture` runs only at a quiescent point (every path paused at a request boundary or exited), copies each state tree
into a staging directory and returns the file table. `publish` uploads a staged checkpoint and moves the `latest`
pointer last. `restore` verifies every byte before a state tree appears under its final name. The object store is
any object with the five methods used here; production uses `collector_s3.S3Store`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

SCHEMA_VERSION = "zoop-collector-checkpoint-1"
LATEST_SCHEMA = "zoop-collector-latest-1"
MANIFEST_NAME = "MANIFEST.json"
LATEST_NAME = "latest.json"
PATH_NAMES = ("private", "korea", "official")
SQLITE_MAGIC = b"SQLite format 3\x00"
_SIDECAR = re.compile(r"(.+)-(?:wal|shm|journal)$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CHUNK = 1 << 20


class CheckpointError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while chunk := source.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def run_prefix(prefix: str, run_id: str) -> str:
    if not _RUN_ID.fullmatch(run_id):
        raise CheckpointError("run_id_invalid")
    return f"{prefix.strip('/')}/runs/{run_id}".lstrip("/")


def checkpoint_base(prefix: str, seq: int, checkpoint_id: str) -> str:
    return f"{prefix}/checkpoints/{seq:06d}-{checkpoint_id}"


def _safe_relative(path: str) -> PurePosixPath:
    parsed = PurePosixPath(path)
    if (not path or parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts)
            or "\\" in path or parsed.parts[0] not in PATH_NAMES):
        raise CheckpointError("path_unsafe", path)
    return parsed


def _stable(before: os.stat_result, after: os.stat_result) -> bool:
    return (before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns)


def _copy_closed_file(source: Path, target: Path) -> tuple[int, str]:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(source, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise CheckpointError("unsafe_entry", str(source))
        digest, size = hashlib.sha256(), 0
        out = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "rb", closefd=False) as reader, os.fdopen(out, "wb") as writer:
            while chunk := reader.read(_CHUNK):
                digest.update(chunk)
                writer.write(chunk)
                size += len(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        if not _stable(before, os.fstat(descriptor)):
            raise CheckpointError("file_changed_during_copy", str(source))
        return size, digest.hexdigest()
    finally:
        os.close(descriptor)


def _backup_sqlite(source: Path, target: Path) -> tuple[int, str]:
    """SQLite online backup into a new file: a consistent page snapshot, never a copy of a live WAL."""
    uri = source.as_uri()
    for mode in ("ro", "rw"):
        reader = None
        try:
            reader = sqlite3.connect(f"{uri}?mode={mode}", uri=True, timeout=30)
            writer = sqlite3.connect(target)
            try:
                reader.backup(writer)
            finally:
                writer.close()
            break
        except sqlite3.OperationalError:
            # A read-only handle cannot recover a WAL left by a killed writer; no writer exists once this runs.
            if mode == "rw":
                raise
            target.unlink(missing_ok=True)
        finally:
            if reader is not None:
                reader.close()
    os.chmod(target, 0o600)
    check = sqlite3.connect(f"{target.as_uri()}?mode=ro", uri=True)
    try:
        result = check.execute("PRAGMA quick_check").fetchall()
    finally:
        check.close()
    for suffix in ("-wal", "-shm", "-journal"):
        target.with_name(target.name + suffix).unlink(missing_ok=True)
    if result != [("ok",)]:
        raise CheckpointError("sqlite_backup_invalid", str(source))
    with open(target, "rb") as handle:
        os.fsync(handle.fileno())
    return target.stat().st_size, sha256_file(target)


def _is_sqlite(path: Path) -> bool:
    with open(path, "rb") as handle:
        return handle.read(len(SQLITE_MAGIC)) == SQLITE_MAGIC


def capture(state_dirs: dict[str, Path], staging: Path) -> dict:
    """Copy every state tree into `staging`; return {"files", "dirs", "sqlite"} manifest tables."""
    files, dirs, databases = [], [], []
    staging.mkdir(mode=0o700, parents=True)
    for name in sorted(state_dirs):
        if name not in PATH_NAMES:
            raise CheckpointError("path_unsafe", name)
        root = state_dirs[name]
        dirs.append(name)
        (staging / name).mkdir(mode=0o700)
        for base, subdirs, names in os.walk(root, followlinks=False):
            subdirs.sort()
            relative = Path(base).relative_to(root)
            for child in subdirs:
                if (Path(base) / child).is_symlink():
                    raise CheckpointError("unsafe_entry", str(Path(base) / child))
                (staging / name / relative / child).mkdir(mode=0o700)
                dirs.append(PurePosixPath(name, *relative.parts, child).as_posix())
            existing = set(names)
            for filename in sorted(names):
                source = Path(base) / filename
                if filename.startswith(".stage-"):
                    continue
                sidecar = _SIDECAR.fullmatch(filename)
                if sidecar is not None:
                    owner = Path(base) / sidecar[1]
                    if sidecar[1] not in existing or not _is_sqlite(owner):
                        raise CheckpointError("orphan_sqlite_sidecar", str(source))
                    continue
                if not stat.S_ISREG(os.lstat(source).st_mode):
                    raise CheckpointError("unsafe_entry", str(source))
                target = staging / name / relative / filename
                relative_path = PurePosixPath(name, *relative.parts, filename).as_posix()
                if _is_sqlite(source):
                    size, digest = _backup_sqlite(source, target)
                    files.append({"path": relative_path, "bytes": size, "sha256": digest, "kind": "sqlite"})
                    databases.append({"path": relative_path, "method": "backup"})
                else:
                    size, digest = _copy_closed_file(source, target)
                    files.append({"path": relative_path, "bytes": size, "sha256": digest, "kind": "file"})
    return {"files": files, "dirs": dirs, "sqlite": databases}


def count_unknown(name: str, staged: Path) -> int:
    """Unknown outcomes recorded in a staged state tree (never the live one)."""
    state = json.loads((staged / name / "STATE.json").read_bytes())
    if name == "korea":
        return state["unknownRequests"] + sum(item["outcome"] == "unknown" for item in state["items"].values())
    state = state["state"]
    unknown = state["unknownRequests"] + state.get("providerUnknownRequests", 0)
    if name == "official":
        return unknown + sum(item["status"] == "unknown" for item in state["tasks"].values())
    if state["tasks"] == "sqlite:tasks":
        database = sqlite3.connect(f"{(staged / name / 'QUEUE.sqlite3').as_uri()}?mode=ro", uri=True)
        try:
            return unknown + sum(database.execute(f"SELECT count(*) FROM {table} WHERE status='unknown'").fetchone()[0]
                                 for table in ("tasks", "candidates"))
        finally:
            database.close()
    return unknown + sum(item["status"] == "unknown" for table in ("tasks", "candidates") for item in state[table].values())


def build_manifest(*, run_id: str, checkpoint_id: str, seq: int, kind: str, tables: dict, paths: list[dict],
                   unknown: int, previous: dict | None, image: dict) -> dict:
    return {"schemaVersion": SCHEMA_VERSION, "runId": run_id, "checkpointId": checkpoint_id, "seq": seq,
            "kind": kind, "createdAt": utc_now(), "image": image, "paths": paths, "dirs": tables["dirs"],
            "files": tables["files"], "sqlite": tables["sqlite"], "unknownOutcomes": unknown, "previous": previous}


def encode_manifest(manifest: dict) -> bytes:
    return (json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def validate_manifest(manifest: dict, *, run_id: str | None = None) -> None:
    try:
        if manifest["schemaVersion"] != SCHEMA_VERSION or (run_id is not None and manifest["runId"] != run_id):
            raise CheckpointError("manifest_invalid", "schema or run id")
        seen = set()
        for entry in manifest["files"]:
            _safe_relative(entry["path"])
            if (entry["path"] in seen or entry["kind"] not in {"file", "sqlite"} or type(entry["bytes"]) is not int
                    or entry["bytes"] < 0 or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
                raise CheckpointError("manifest_invalid", entry["path"])
            seen.add(entry["path"])
        for directory in manifest["dirs"]:
            _safe_relative(directory)
        if {entry["path"] for entry in manifest["sqlite"]} != {e["path"] for e in manifest["files"] if e["kind"] == "sqlite"}:
            raise CheckpointError("manifest_invalid", "sqlite table")
    except (KeyError, TypeError, AttributeError) as exc:
        raise CheckpointError("manifest_invalid", repr(exc)) from None


def verify_tree(root: Path, manifest: dict) -> None:
    """Every manifest file must exist with the recorded size and hash; nothing else may exist."""
    expected = {entry["path"]: entry for entry in manifest["files"]}
    wanted_dirs = set(manifest["dirs"])
    found = set()
    for base, subdirs, names in os.walk(root, followlinks=False):
        for child in subdirs:
            path = Path(base) / child
            if path.is_symlink() or path.relative_to(root).as_posix() not in wanted_dirs:
                raise CheckpointError("unexpected_entry", str(path))
        for filename in names:
            path = Path(base) / filename
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or relative not in expected:
                raise CheckpointError("unexpected_entry", relative)
            found.add(relative)
    for relative, entry in expected.items():
        path = root / relative
        if relative not in found:
            raise CheckpointError("file_missing", relative)
        if path.stat().st_size != entry["bytes"]:
            raise CheckpointError("size_mismatch", relative)
        if sha256_file(path) != entry["sha256"]:
            raise CheckpointError("sha256_mismatch", relative)
    for directory in wanted_dirs:
        if not (root / directory).is_dir():
            raise CheckpointError("file_missing", directory)


def _deadline_check(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise CheckpointError("deadline_exceeded")


def publish(store, prefix: str, staging: Path, manifest: dict, previous: dict | None, *, deadline: float | None = None,
            workers: int = 8) -> dict:
    """Upload and verify every file, write MANIFEST.json, then overwrite the latest pointer. Returns the pointer."""
    base = checkpoint_base(prefix, manifest["seq"], manifest["checkpointId"])
    earlier = ({entry["path"]: entry for entry in previous["files"]} if previous else {})
    earlier_base = (checkpoint_base(prefix, previous["seq"], previous["checkpointId"]) if previous else "")

    def transfer(entry: dict) -> None:
        _deadline_check(deadline)
        key = f"{base}/{entry['path']}"
        before = earlier.get(entry["path"])
        if before is not None and before["sha256"] == entry["sha256"] and before["bytes"] == entry["bytes"]:
            store.copy(f"{earlier_base}/{entry['path']}", key, sha256=entry["sha256"])
        else:
            store.put_file(key, staging / entry["path"], sha256=entry["sha256"])
        if store.head(key) != (entry["bytes"], entry["sha256"]):
            raise CheckpointError("upload_verification_failed", entry["path"])

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in [pool.submit(transfer, entry) for entry in manifest["files"]]:
            future.result()
    _deadline_check(deadline)
    encoded = encode_manifest(manifest)
    manifest_key = f"{base}/{MANIFEST_NAME}"
    store.put_bytes(manifest_key, encoded)
    if store.get_bytes(manifest_key) != encoded:
        raise CheckpointError("upload_verification_failed", MANIFEST_NAME)
    pointer = {"schemaVersion": LATEST_SCHEMA, "runId": manifest["runId"], "seq": manifest["seq"],
               "checkpointId": manifest["checkpointId"], "manifestKey": manifest_key,
               "manifestSha256": hashlib.sha256(encoded).hexdigest(), "updatedAt": utc_now()}
    _deadline_check(deadline)
    store.put_bytes(f"{prefix}/{LATEST_NAME}", (json.dumps(pointer, sort_keys=True, indent=2) + "\n").encode())
    return pointer


def read_pointer(store, prefix: str, run_id: str) -> dict | None:
    raw = store.get_bytes(f"{prefix}/{LATEST_NAME}")
    if raw is None:
        return None
    try:
        pointer = json.loads(raw)
        if pointer["schemaVersion"] != LATEST_SCHEMA or pointer["runId"] != run_id:
            raise ValueError
        return pointer
    except (ValueError, KeyError, TypeError):
        raise CheckpointError("latest_pointer_invalid") from None


def find_checkpoint(store, prefix: str, run_id: str, selector: str = "latest") -> tuple[dict, dict] | None:
    """Return (manifest, pointer) for `latest` or an exact `<seq>-<checkpointId>` selector; None when none exists."""
    if selector == "latest":
        pointer = read_pointer(store, prefix, run_id)
        if pointer is None:
            return None
        key, expected = pointer["manifestKey"], pointer["manifestSha256"]
    else:
        match = re.fullmatch(r"(\d{1,6})-([0-9a-f]{12})", selector)
        if match is None:
            raise CheckpointError("checkpoint_selector_invalid", selector)
        key, expected = f"{checkpoint_base(prefix, int(match[1]), match[2])}/{MANIFEST_NAME}", None
    raw = store.get_bytes(key)
    if raw is None:
        raise CheckpointError("manifest_missing", key)
    if expected is not None and hashlib.sha256(raw).hexdigest() != expected:
        raise CheckpointError("manifest_sha256_mismatch", key)
    try:
        manifest = json.loads(raw)
    except ValueError:
        raise CheckpointError("manifest_invalid", "not JSON") from None
    validate_manifest(manifest, run_id=run_id)
    if key != f"{checkpoint_base(prefix, manifest['seq'], manifest['checkpointId'])}/{MANIFEST_NAME}":
        raise CheckpointError("manifest_invalid", "key does not match seq/checkpointId")
    return manifest, {"manifestKey": key, "manifestSha256": hashlib.sha256(raw).hexdigest()}


def restore(store, prefix: str, run_id: str, state_root: Path, *, selector: str = "latest", deadline: float | None = None,
            workers: int = 8) -> dict:
    """Download, verify and install a checkpoint. Refuses unless every target state directory is absent or empty."""
    found = find_checkpoint(store, prefix, run_id, selector)
    if found is None:
        raise CheckpointError("checkpoint_not_found", run_id)
    manifest, _ = found
    names = sorted({PurePosixPath(directory).parts[0] for directory in manifest["dirs"]})
    for name in names:
        target = state_root / name
        if target.exists() and (target.is_symlink() or not target.is_dir() or any(target.iterdir())):
            raise CheckpointError("state_not_empty", str(target))
    base = checkpoint_base(prefix, manifest["seq"], manifest["checkpointId"])
    scratch = state_root / f".restore-{manifest['checkpointId']}"
    if scratch.exists():
        raise CheckpointError("state_not_empty", str(scratch))
    scratch.mkdir(mode=0o700)
    try:
        for directory in manifest["dirs"]:
            (scratch / directory).mkdir(mode=0o700, exist_ok=True)

        def fetch(entry: dict) -> None:
            _deadline_check(deadline)
            target = scratch / entry["path"]
            store.get_file(f"{base}/{entry['path']}", target)
            os.chmod(target, 0o600)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in [pool.submit(fetch, entry) for entry in manifest["files"]]:
                future.result()
        verify_tree(scratch, manifest)
        for name in names:
            target = state_root / name
            if target.exists():
                target.rmdir()
            os.rename(scratch / name, target)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return manifest


def new_checkpoint_id() -> str:
    return uuid.uuid4().hex[:12]
