"""Recover only published, sealed, never-used online initialization inodes."""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import stat

from . import extraction_ledger, ledger, plan_authority, plan_install, relation_ledger
from .plan_verify import decode, read_file, sha

ROOT = "authority-initialization"
PREFIX = ".authority-prepare-"
MARKER = "authority-mode.json"
MANIFEST = "initialization.json"
MODE = {"schemaVersion": "zoop-ai-authority-mode-2", "mode": "online"}
FILES = (plan_authority.FILE, "service.sqlite3", extraction_ledger.FILE, relation_ledger.FILE, MARKER)
SCHEMA = "zoop-ai-authority-initialization-1"


def present(directory):
    return any(p.name == ROOT or p.name.startswith(PREFIX) for p in directory.iterdir())


def _identity(info):
    return [info.st_dev, info.st_ino]


def _metadata(config):
    def pin(path):
        return hashlib.sha256(os.path.realpath(path).encode()).hexdigest()
    return {
        plan_authority.FILE: {"schema": plan_authority.SCHEMA,
            "binding": plan_authority.canonical(plan_authority.binding(config)),
            "revision": "0", "plans": "0", "units": "0", "expired_revision": "0"},
        "service.sqlite3": {"schema": ledger.LEDGER_SCHEMA, "workerLedger": pin(config.worker_state_dir)},
        extraction_ledger.FILE: {"schema": extraction_ledger.LEDGER_SCHEMA, "extractionLedger": pin(config.extraction.state_dir)},
        relation_ledger.FILE: {"schema": relation_ledger.LEDGER_SCHEMA, "relationLedger": pin(config.relation.state_dir)},
    }


def _empty_database(path, metadata):
    # immutable avoids creating journals while checking a sealed, hash-pinned image.
    db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok" or dict(db.execute("SELECT key,value FROM meta")) != metadata:
            raise ValueError("invalid prepared database")
        tables = {plan_authority.FILE: ("policies", "policy_operations", "admissions", "grants"),
            "service.sqlite3": ("analysis_jobs", "analysis_dispatch"),
            extraction_ledger.FILE: ("extraction_jobs", "extraction_dispatch"),
            relation_ledger.FILE: ("relation_jobs", "relation_dispatch", "relation_operations")}[path.name]
        for table in tables:
            if db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                raise ValueError("used initialization")
    finally:
        db.close()


def _file(path, directories, *, content):
    parent = directories.fd(path.parent)
    fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077:
            raise ValueError("unsafe initialization file")
        result = {"identity": _identity(info)}
        if content:
            if info.st_size > plan_authority.MAX_RECORD:
                raise ValueError("oversized initialization file")
            raw = handle.read(plan_authority.MAX_RECORD + 1)
            result.update(size=len(raw), sha256=sha(raw))
        after = os.fstat(handle.fileno())
        named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) \
                or _identity(named) != _identity(info):
            raise ValueError("initialization file changed")
        return result


def _directory(path, directories):
    plan_install.private_dir(path)
    return _identity(os.fstat(directories.fd(path)))


def _sync_file(path, directories):
    fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directories.fd(path.parent))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write(path, value, directories):
    fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                 dir_fd=directories.fd(path.parent))
    with os.fdopen(fd, "wb") as handle:
        handle.write(plan_authority.canonical(value).encode())
        handle.flush()
        os.fsync(handle.fileno())


def _seal(instance):
    try:
        result = instance._db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if result[0] != 0 or instance._db.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
            raise ValueError("unsealed initialization")
    finally:
        instance.close()


def _prepare(config, lock, directories):
    root = config.state_dir
    stage = root / (PREFIX + secrets.token_hex(16))
    os.mkdir(stage.name, mode=0o700, dir_fd=directories.fd(root))
    plan_install.sync(root, directories)
    plan_authority.prepare_authority(config, stage)
    for name, constructor, binding in (
        ("service.sqlite3", ledger.ServiceLedger, config.worker_state_dir),
        (extraction_ledger.FILE, extraction_ledger.ExtractionLedger, config.extraction.state_dir),
        (relation_ledger.FILE, relation_ledger.RelationLedger, config.relation.state_dir),
    ):
        _seal(constructor(stage, binding))
    _write(stage / MARKER, MODE, directories)
    if set(os.listdir(directories.fd(stage))) != set(FILES):
        raise ValueError("unexpected initialization sidecar")
    metadata = _metadata(config)
    for name in FILES[:-1]:
        _empty_database(stage / name, metadata[name])
    for name in FILES:
        _sync_file(stage / name, directories)
    manifest = {"schemaVersion": SCHEMA, "binding": plan_authority.binding(config), "metadata": metadata,
        "root": _directory(root, directories), "directory": _directory(stage, directories),
        "lock": list(lock.identity), "files": {name: _file(stage / name, directories, content=True) for name in FILES}}
    fd = os.open(MANIFEST, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                 dir_fd=directories.fd(stage))
    with os.fdopen(fd, "wb") as handle:
        manifest["manifest"] = _identity(os.fstat(handle.fileno()))
        handle.write(plan_authority.canonical(manifest).encode())
        handle.flush()
        os.fsync(handle.fileno())
    plan_install.sync(stage, directories)
    lock.validate()
    plan_install.publish_directory(stage, root / ROOT, directories)
    plan_install.sync(root, directories)


def _manifest(config, lock, directories):
    root, initialization = config.state_dir, config.state_dir / ROOT
    if any(p.name.startswith(PREFIX) for p in root.iterdir()):
        raise ValueError("unpublished initialization")
    value = decode(read_file(initialization / MANIFEST, 65536,
                             directory_fd=directories.fd(initialization), owned=True))
    expected = {"schemaVersion", "binding", "metadata", "root", "directory", "lock", "files", "manifest"}
    if not isinstance(value, dict) or set(value) != expected or value["schemaVersion"] != SCHEMA \
            or value["binding"] != plan_authority.binding(config) or value["metadata"] != _metadata(config) \
            or value["root"] != _directory(root, directories) or value["directory"] != _directory(initialization, directories) \
            or value["manifest"] != _file(initialization / MANIFEST, directories, content=False)["identity"] \
            or value["lock"] != list(lock.identity) or set(value["files"]) != set(FILES):
        raise ValueError("foreign initialization")
    for pin in value["files"].values():
        if not isinstance(pin, dict) or set(pin) != {"identity", "size", "sha256"}:
            raise ValueError("invalid initialization pin")
    lock.validate()
    return value


def _move(source, target, lock, directories):
    lock.validate()
    plan_install.publish_directory(source, target, directories)
    plan_install.sync(source.parent, directories)
    plan_install.sync(target.parent, directories)
    lock.validate()


def _recover(config, lock, directories, manifest):
    root, initialization = config.state_dir, config.state_dir / ROOT
    if any(p.name not in {*FILES[:-1], "service.lock", ROOT, "transport"} for p in root.iterdir()) \
            or (root / "transport").exists() and (not (root / "transport").is_dir() or any((root / "transport").iterdir())):
        raise ValueError("unexpected pending profile data")
    if set(os.listdir(directories.fd(initialization))) - {MANIFEST, *FILES}:
        raise ValueError("unexpected initialization data")
    locations = {}
    for name in FILES:
        candidates = [p for p in (initialization / name, root / name) if os.path.lexists(p)]
        if len(candidates) != 1 or name == MARKER and candidates[0].parent != initialization:
            raise ValueError("missing or duplicate initialization inode")
        path = candidates[0]
        if _file(path, directories, content=True) != manifest["files"][name]:
            raise ValueError("changed initialization inode")
        if name != MARKER:
            if any(os.path.lexists(path.parent / (name + suffix)) for suffix in ("-wal", "-shm", "-journal")):
                raise ValueError("unsealed initialization")
            _empty_database(path, manifest["metadata"][name])
        elif decode(read_file(path, 4096, directory_fd=directories.fd(path.parent), owned=True)) != MODE:
            raise ValueError("invalid prepared marker")
        locations[name] = path
    # All five pins must validate before the first move; constructors cannot touch them yet.
    for name in FILES:
        if name == MARKER:
            for database in FILES[:-1]:
                if _file(root / database, directories, content=True) != manifest["files"][database]:
                    raise ValueError("initialization changed before commitment")
        source = locations[name]
        if source.parent == initialization:
            if _file(source, directories, content=True) != manifest["files"][name]:
                raise ValueError("initialization changed before publication")
            _move(source, root / name, lock, directories)


def initialize(config, lock):
    """Run under the lifetime lock; published files are never regenerated."""
    root = config.state_dir
    info = root.lstat()
    settings = plan_install.Settings(root, (), (), {}, "", {}, ((info.st_dev, info.st_ino),))
    with plan_install.Directories(settings) as directories:
        plan_install.private_dir(root)
        if not os.path.lexists(root / ROOT):
            if present(root) or any(p.name != "service.lock" and not (
                    p.name == "transport" and p.is_dir() and not p.is_symlink() and not any(p.iterdir())) for p in root.iterdir()):
                raise ValueError("not a fresh online profile")
            _prepare(config, lock, directories)
        manifest = _manifest(config, lock, directories)
        if os.path.lexists(root / MARKER):
            if decode(read_file(root / MARKER, 4096, owned=True)) != MODE:
                raise ValueError("invalid committed marker")
            if set(os.listdir(directories.fd(root / ROOT))) != {MANIFEST}:
                raise ValueError("conflicting committed initialization")
            for name in FILES:
                if _file(root / name, directories, content=False)["identity"] != manifest["files"][name]["identity"]:
                    raise ValueError("replaced committed inode")
        else:
            _recover(config, lock, directories, manifest)
