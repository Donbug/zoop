"""Operator-only exact-plan installation, protected by the service's quiescence lock.

Two registry replacements are NOT physically atomic. A durable journal and startup
barrier prevent this service-state owner from using an interrupted pair. No command
here submits jobs, grants source rights, opens a budget, or starts the service.
"""
from __future__ import annotations

import ctypes
import os
import re
import secrets
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config, extraction_access, relation_access
from .ledger import ProcessLock
from .plan_verify import FILES, InstallError, encode, sha, digest, decode, read_file, plan_files, verify_plan

SCHEMA = "zoop-ai-plan-install-1"
ROOT = "plan-install"
ID = re.compile(r"plan-install-[0-9a-f]{64}")
IMAGES = ("before-approvals.json", "before-upstreams.json", "after-approvals.json", "after-upstreams.json")
MAX_RECORD = 32_000_000
MAX_OPERATIONS = 10_000




def private_dir(path: Path) -> None:
    try:
        info = path.lstat()
        if os.path.realpath(path) != str(path) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise InstallError("state_not_private")
    except OSError:
        raise InstallError("state_unavailable") from None


@dataclass(frozen=True)
class Settings:
    state: Path
    targets: tuple[Path, Path]
    principals: tuple[str, ...]
    env: Mapping[str, str]
    fingerprint: str
    environ: Mapping[str, str]
    directory_ids: tuple[tuple[int, int], ...]

    def binding(self) -> dict:
        return {"schemaVersion": SCHEMA, "state": str(self.state), "targets": [str(p) for p in self.targets],
                "directoryIdentities": [{"device": device, "inode": inode} for device, inode in self.directory_ids]}



def directory_identities(state: Path, targets: tuple[Path, Path]) -> tuple[tuple[int, int], ...]:
    result = []
    for path in (state, *(target.parent for target in targets)):
        if os.path.realpath(path) != str(path):
            raise InstallError("unsafe_path")
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise InstallError("directory_identity_changed")
        result.append((info.st_dev, info.st_ino))
    return tuple(result)


class Directories:
    """Hold directory capabilities; compare identities, never mutable directory metadata."""

    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.anchors = (cfg.state, *(target.parent for target in cfg.targets))
        self.handles: dict[Path, int] = {}

    def __enter__(self) -> Directories:
        try:
            for path in self.anchors:
                if path not in self.handles:
                    self.handles[path] = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self.validate()
            return self
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *_: object) -> None:
        for fd in self.handles.values():
            os.close(fd)
        self.handles.clear()

    def validate(self) -> None:
        if directory_identities(self.cfg.state, self.cfg.targets) != self.cfg.directory_ids:
            raise InstallError("directory_identity_changed")
        for path, expected in zip(self.anchors, self.cfg.directory_ids):
            info = os.fstat(self.handles[path])
            if (info.st_dev, info.st_ino) != expected:
                raise InstallError("directory_identity_changed")

    def fd(self, path: Path) -> int:
        self.validate()
        if path in self.anchors:
            return self.handles[path]
        if not path.is_relative_to(self.cfg.state):
            raise InstallError("unsafe_path")
        parent = self.fd(path.parent)
        if path not in self.handles:
            self.handles[path] = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        found = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        held = os.fstat(self.handles[path])
        if not stat.S_ISDIR(found.st_mode) or (found.st_dev, found.st_ino) != (held.st_dev, held.st_ino):
            raise InstallError("directory_identity_changed")
        return self.handles[path]

    def staging(self, parent: Path) -> Path:
        fd = self.fd(parent)
        while True:
            name = ".install-" + secrets.token_hex(16)
            try:
                os.mkdir(name, mode=0o700, dir_fd=fd)
                return parent / name
            except FileExistsError:
                continue

def settings(environ: Mapping[str, str], *, recovery: bool = False) -> Settings:
    """No writes, config.load, provider keys, or budget reads; recovery needs only path identity."""
    state = config._absolute(environ.get("ZOOP_AI_SERVICE_STATE_DIR"), "ZOOP_AI_SERVICE_STATE_DIR")
    private_dir(state)
    if environ.get("ZOOP_AI_SERVICE_PLAN_ADMISSION") is not None or os.path.lexists(state / "plan-authority.sqlite3") \
            or os.path.lexists(state / "authority-mode.json"):
        raise InstallError("authority_mode_mismatch")
    targets = tuple(config._absolute(environ.get(name), name) for name in
                    ("ZOOP_AI_SERVICE_EXTRACTION_APPROVALS", "ZOOP_AI_SERVICE_RELATION_UPSTREAMS"))
    if targets[0] == targets[1]:
        raise InstallError("targets_overlap")
    roots = {"service": state}
    root_names = ("ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR", "ZOOP_AI_INGESTION_STATE_DIR", "ZOOP_AI_EXTRACTION_STATE_DIR", "ZOOP_AI_RELATION_STATE_DIR")
    for name in (() if recovery else root_names):
        if environ.get(name):
            roots[name] = config._absolute(environ[name], name)
        elif not recovery:
            raise InstallError("configuration_incomplete")
    if any(config._overlaps(a, b) for index, a in enumerate(roots.values()) for b in list(roots.values())[index + 1:]):
        raise InstallError("roots_overlap")
    for target in targets:
        if any(config._overlaps(target, root) for root in roots.values()) or not target.parent.is_dir():
            raise InstallError("targets_overlap")
    names: tuple[str, ...] = ()
    public: dict[str, Any] = {"state": str(state), "targets": [str(p) for p in targets]}
    child: dict[str, str] = {}
    if not recovery:
        decode(environ.get("ZOOP_AI_SERVICE_PRINCIPALS", "").encode())
        principals = config._principals(environ.get("ZOOP_AI_SERVICE_PRINCIPALS"))
        names = tuple(p.name for p in principals)
        public["principals"] = [{"principal": p.name, "scopes": sorted(p.scopes)} for p in principals]
        for name in (*config.EXTRACTION_VARS, *config.RELATION_VARS):
            if not environ.get(name):
                raise InstallError("configuration_incomplete")
        paths = ("ZOOP_AI_SERVICE_EXTRACTION_COMMAND", "ZOOP_AI_SERVICE_RELATION_COMMAND", "ZOOP_AI_SERVICE_SOURCES",
                 "ZOOP_AI_SERVICE_EXTRACTION_REPLAY", "ZOOP_AI_SERVICE_RELATION_REPLAY", "ZOOP_AI_SERVICE_RELATION_VERIFIER_REPLAY")
        if environ.get(config.EXTRACTION_TOPIC):
            paths = (*paths, config.EXTRACTION_TOPIC)
        for name in paths:
            path = config._absolute(environ[name], name)
            raw = read_file(path, 100_000_000 if name.endswith("COMMAND") else 20_000_000)
            if name.endswith("COMMAND") and not os.access(path, os.X_OK):
                raise InstallError("command_unusable")
            if path in targets or any(config._overlaps(path, root) for root in roots.values()):
                raise InstallError("input_overlap")
            public[name] = {"path": str(path), "sha256": sha(raw)}
        public["roots"] = {name: str(path) for name, path in roots.items()}
        child = {**config.CHILD_BASE_ENV, "ZOOP_STATE_DIR": environ["ZOOP_STATE_DIR"],
                 "ZOOP_AI_WORKER_STATE_DIR": environ["ZOOP_AI_WORKER_STATE_DIR"]}
        live = environ.get(config.PIPELINE_LIVE_SWITCH) == "1" and environ.get(config.PIPELINE_LIVE_GATE) == "1"
        public["liveAvailable"] = live
        if live:
            for name in (*config.PIPELINE_LIVE_PUBLIC_REQUIRED, *config.PIPELINE_LIVE_PUBLIC_OPTIONAL, "ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR"):
                if name in environ:
                    child[name] = environ[name]
                    public[name] = environ[name]
            if not all(child.get(name) for name in (*config.PIPELINE_LIVE_PUBLIC_REQUIRED, "ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR")):
                raise InstallError("live_configuration_incomplete")
    identities = directory_identities(state, targets)
    public["directoryIdentities"] = identities
    return Settings(state, targets, names, child, digest(public), dict(environ), identities)


def sync(directory: Path, directories: Directories) -> None:
    os.fsync(directories.fd(directory))


def publish(path: Path, raw: bytes, directories: Directories, *, replace: bool = False) -> None:
    """Flush and publish entirely relative to the held, identity-checked parent."""
    parent = directories.fd(path.parent)
    temporary = ".install-" + secrets.token_hex(16)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        directories.validate()
        if replace:
            os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
        else:
            os.link(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        os.fsync(parent)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass


def publish_directory(source: Path, target: Path, directories: Directories) -> None:
    """Publish without replacing a foreign directory, using held parent descriptors."""
    libc = ctypes.CDLL(None, use_errno=True)
    first, second = os.fsencode(source.name), os.fsencode(target.name)
    source_fd, target_fd = directories.fd(source.parent), directories.fd(target.parent)
    if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        failed = libc.renameatx_np(source_fd, first, target_fd, second, 0x4) != 0  # RENAME_EXCL
    elif hasattr(libc, "renameat2"):
        failed = libc.renameat2(source_fd, first, target_fd, second, 1) != 0  # RENAME_NOREPLACE
    else:
        raise InstallError("journal_publication_unsupported")
    if failed:
        raise InstallError("journal_publication_conflict")


def root_for(cfg: Settings, *, create: bool = False, directories: Directories | None = None) -> Path:
    root = cfg.state / ROOT
    if not os.path.lexists(root):
        if not create:
            return root
        if directories is None:
            raise InstallError("directory_identity_changed")
        staging = directories.staging(cfg.state)
        publish(staging / "binding.json", encode(cfg.binding()), directories)
        os.mkdir("transactions", mode=0o700, dir_fd=directories.fd(staging))
        sync(staging, directories)
        publish_directory(staging, root, directories)
        sync(cfg.state, directories)
    private_dir(root)
    binding = root / "binding.json"
    if not os.path.lexists(binding):
        raise InstallError("journal_corrupt")
    if decode(read_file(binding, 4_000)) != cfg.binding():
        raise InstallError("journal_binding_changed")
    transactions = root / "transactions"
    if not os.path.lexists(transactions):
        raise InstallError("journal_corrupt")
    private_dir(transactions)
    for path in root.iterdir():
        if path.name not in {"binding.json", "transactions", "pending.json"} and not path.name.startswith(".install-"):
            raise InstallError("journal_corrupt")
    return root


def operation_dirs(root: Path) -> list[Path]:
    transactions = root / "transactions"
    if not transactions.exists():
        return []
    private_dir(transactions)
    entries = list(transactions.iterdir())
    if len(entries) > MAX_OPERATIONS:
        raise InstallError("journal_bounds")
    result = []
    for path in entries:
        if path.name.startswith(".install-"):
            continue
        if not ID.fullmatch(path.name):
            raise InstallError("journal_corrupt")
        private_dir(path)
        result.append(path)
    return sorted(result)


def record(directory: Path, cfg: Settings) -> tuple[dict, dict | None]:
    private_dir(directory)
    intent = decode(read_file(directory / "intent.json", MAX_RECORD))
    required = {"schemaVersion", "installationId", "binding", "reviewDigest", "currentDigest", "planId", "planDigest", "receiptSha256", "required", "images"}
    if not isinstance(intent, dict) or set(intent) != required or intent["schemaVersion"] != SCHEMA \
            or intent["installationId"] != directory.name or directory.name != "plan-install-" + str(intent["reviewDigest"]) \
            or intent["binding"] != cfg.binding() or not isinstance(intent["images"], dict) or set(intent["images"]) != set(IMAGES):
        raise InstallError("journal_corrupt")
    for name in IMAGES:
        maximum = extraction_access.MAX_BYTES if "approvals" in name else relation_access.MAX_BYTES
        if sha(read_file(directory / name, maximum)) != intent["images"][name]:
            raise InstallError("journal_corrupt")
    for path in directory.iterdir():
        if path.name not in {*IMAGES, "intent.json", "receipt.json"} and not path.name.startswith(".install-"):
            raise InstallError("journal_corrupt")
    result = None
    if os.path.lexists(directory / "receipt.json"):
        result = decode(read_file(directory / "receipt.json", 4_000))
        base = {"schemaVersion": SCHEMA, "installationId": directory.name, "transactionDigest": digest(intent)}
        if result not in ({**base, "outcome": "committed"}, {**base, "outcome": "aborted"}):
            raise InstallError("journal_corrupt")
    return intent, result


def active(root: Path, cfg: Settings) -> str | None:
    marker = root / "pending.json"
    if not os.path.lexists(marker):
        return None
    value = decode(read_file(marker, 4_000))
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "installationId", "transactionDigest"} or value["schemaVersion"] != SCHEMA \
            or not isinstance(value["installationId"], str) or not ID.fullmatch(value["installationId"]):
        raise InstallError("journal_corrupt")
    intent, _ = record(root / "transactions" / value["installationId"], cfg)
    if value["transactionDigest"] != digest(intent):
        raise InstallError("journal_corrupt")
    return value["installationId"]


def ensure_clear(root: Path, cfg: Settings) -> None:
    if active(root, cfg) is not None:
        raise InstallError("installation_pending")
    for directory in operation_dirs(root):
        _, result = record(directory, cfg)
        if result is None:
            raise InstallError("installation_pending")


def startup_barrier(service: config.ServiceConfig) -> None:
    """Run under ProcessLock, before ledgers, in-flight recovery, or dispatchers."""
    root = service.state_dir / ROOT
    try:
        names = tuple(p.name for p in service.principals)
        if service.extraction is not None and service.relation is not None:
            targets = (service.extraction.approvals_path, service.relation.upstreams_path)
            cfg = Settings(service.state_dir, targets, names, {}, "", {}, directory_identities(service.state_dir, targets))
            with Directories(cfg) as directories:
                if os.path.lexists(root):
                    ensure_clear(root_for(cfg), cfg)
                pair = current_pair(cfg, directories)
                extraction_access.parse(pair[0], names, topic_available=service.extraction.topic_replay is not None,
                                        live_available=service.pipeline_live is not None)
                relation_access.parse(pair[1], names)
                directories.validate()
        else:
            if os.path.lexists(root):
                raise InstallError("journal_binding_changed")
            if service.extraction is not None:
                extraction_access.parse(read_file(service.extraction.approvals_path, extraction_access.MAX_BYTES), names,
                                        topic_available=service.extraction.topic_replay is not None, live_available=service.pipeline_live is not None)
            if service.relation is not None:
                relation_access.parse(read_file(service.relation.upstreams_path, relation_access.MAX_BYTES), names)
    except (InstallError, relation_access.AccessError, OSError, ValueError, TypeError, KeyError):
        raise config.ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "plan_install_unresolved") from None




def parse_pair(raw: tuple[bytes, bytes], cfg: Settings) -> tuple[dict, dict]:
    live = cfg.env.get(config.PIPELINE_LIVE_GATE) == "1"
    approvals = extraction_access.parse(raw[0], cfg.principals, topic_available=config.EXTRACTION_TOPIC in cfg.environ, live_available=live)
    upstreams = relation_access.parse(raw[1], cfg.principals)
    # Every retained replay pin must remain usable; merging must never rotate old fixtures away.
    producer = sha(read_file(Path(cfg.environ["ZOOP_AI_SERVICE_EXTRACTION_REPLAY"]), extraction_access.MAX_REPLAY))
    topic = sha(read_file(Path(cfg.environ[config.EXTRACTION_TOPIC]), extraction_access.MAX_REPLAY)) if config.EXTRACTION_TOPIC in cfg.environ else None
    for approval in approvals.entries.values():
        if not approval.live and (approval.producer_digest != producer or (approval.topic_digest is not None and approval.topic_digest != topic)):
            raise InstallError("fixture_changed")
    return approvals.entries, upstreams.entries


def required_present(required: list[dict], raw: tuple[bytes, bytes], cfg: Settings) -> bool:
    names = tuple(p.name for p in config._principals(cfg.environ.get("ZOOP_AI_SERVICE_PRINCIPALS")))
    def entries(pair: tuple[bytes, bytes]) -> tuple[dict, dict]:
        return (extraction_access.parse(pair[0], names, topic_available=True, live_available=True).entries,
                relation_access.parse(pair[1], names).entries)
    current = entries(raw)
    wanted = entries((encode(required[0]), encode(required[1])))
    return all(all(key in installed and installed[key] == value for key, value in needed.items()) for installed, needed in zip(current, wanted))


def current_pair(cfg: Settings, directories: Directories | None = None) -> tuple[bytes, bytes]:
    if directories is None:
        with Directories(cfg) as held:
            return current_pair(cfg, held)
    pair = tuple(read_file(target, maximum, directory_fd=directories.fd(target.parent), owned=True)
                 for target, maximum in zip(cfg.targets, (extraction_access.MAX_BYTES, relation_access.MAX_BYTES)))
    directories.validate()
    return pair


def current_digest(cfg: Settings, raw: tuple[bytes, bytes]) -> str:
    return digest({"binding": cfg.binding(), "files": [{"sha256": sha(data), "bytes": len(data)} for data in raw]})


def proposal(cfg: Settings, path: Path) -> tuple[dict, tuple[bytes, bytes], tuple[bytes, bytes], list[dict]]:
    root = root_for(cfg)
    ensure_clear(root, cfg)
    files, manifest, receipt = plan_files(path, cfg)
    validated = verify_plan(path, cfg, files, manifest, receipt)
    before = current_pair(cfg)
    new = (files["approvals.json"], files["relation-upstreams.json"])
    existing_entries, new_entries = parse_pair(before, cfg), parse_pair(new, cfg)
    if manifest.get("principal") not in cfg.principals:
        raise InstallError("unknown_principal")
    # Full schema/reconstruction belongs to the installed verifier; this ties its held bytes to service loader identities.
    if len(new_entries[0]) != len(new_entries[1]) or any((a.principal, a.job_id, a.input_digest) not in new_entries[1]
            or new_entries[1][(a.principal, a.job_id, a.input_digest)] != a.live_identity for a in new_entries[0].values()):
        raise InstallError("plan_binding_invalid")
    identities = {a.live_identity for a in (*existing_entries[0].values(), *new_entries[0].values()) if a.live}
    identities.update(value for entries in (existing_entries[1], new_entries[1]) for value in entries.values() if value is not None)
    if len(identities) > 1:
        raise InstallError("runtime_pin_conflict")
    merged, counts = [], []
    required = [decode(raw) for raw in new]
    for index, (old, addition) in enumerate(zip(existing_entries, new_entries)):
        if any(key in old and old[key] != value for key, value in addition.items()):
            raise InstallError("plan_conflict")
        old_doc, new_doc = decode(before[index]), required[index]
        field = "approvals" if index == 0 else "upstreams"
        appended = [entry for entry in new_doc[field] if ((entry["principal"], entry["jobId"]) if index == 0 else
                    (entry["principal"], entry["jobId"], entry["inputDigest"])) not in old]
        counts.append({"added": len(appended), "existing": len(addition) - len(appended)})
        merged.append(encode({**old_doc, field: [*old_doc[field], *appended]}) if appended else before[index])
    after = (merged[0], merged[1])
    parse_pair(after, cfg)
    facts = {"schemaVersion": SCHEMA, "planId": receipt["planId"], "planDigest": receipt["planDigest"],
             "receiptSha256": sha(files["receipt.json"]), "principal": manifest["principal"], "round": manifest["round"],
             "mode": manifest["mode"], "pins": manifest["pins"], "counts": manifest["counts"], "binding": cfg.binding(),
             "currentDigest": current_digest(cfg, before), "configurationDigest": cfg.fingerprint, "validation": validated,
             "merged": [{"sha256": sha(raw), "bytes": len(raw), **count} for raw, count in zip(after, counts)]}
    review = digest(facts)
    return {**facts, "reviewDigest": review, "installationId": "plan-install-" + review}, before, after, required


def inspect(cfg: Settings, path: Path) -> dict:
    return proposal(cfg, path)[0]


def status(cfg: Settings, installation_id: str) -> dict:
    if not ID.fullmatch(installation_id):
        raise InstallError("installation_id_invalid")
    root = root_for(cfg)
    intent, receipt = record(root / "transactions" / installation_id, cfg)
    return {"schemaVersion": SCHEMA, "installationId": installation_id, "transactionDigest": digest(intent),
            "outcome": receipt["outcome"] if receipt else "pending", "pendingMarker": active(root, cfg) == installation_id,
            "currentDigest": current_digest(cfg, current_pair(cfg)), "planId": intent["planId"], "planDigest": intent["planDigest"]}


def finish(root: Path, directory: Path, intent: dict, outcome: str, directories: Directories) -> dict:
    receipt = {"schemaVersion": SCHEMA, "installationId": directory.name, "transactionDigest": digest(intent), "outcome": outcome}
    publish(directory / "receipt.json", encode(receipt), directories)
    clear_marker(root, directories)
    return receipt


def replay(receipt: dict, intent: dict, cfg: Settings) -> dict:
    current = False
    if receipt["outcome"] == "committed":
        try:
            current = required_present(intent["required"], current_pair(cfg), cfg)
        except (InstallError, config.ConfigError, relation_access.AccessError, OSError, ValueError, TypeError, KeyError):
            current = False
    result = {**receipt, "appliedNow": False, "installationCurrent": current}
    if receipt["outcome"] == "committed" and not current:
        result["error"] = {"code": "installation_not_current"}
    return result


def clear_marker(root: Path, directories: Directories) -> None:
    fd = directories.fd(root)
    try:
        os.unlink("pending.json", dir_fd=fd)
    except FileNotFoundError:
        pass
    os.fsync(fd)


def install(cfg: Settings, path: Path, expected_current: str, expected_review: str) -> dict:
    if not config.DIGEST.fullmatch(expected_current) or not config.DIGEST.fullmatch(expected_review):
        raise InstallError("digest_invalid")
    installation_id = "plan-install-" + expected_review
    with Directories(cfg) as directories, ProcessLock(cfg.state, directory_fd=directories.fd(cfg.state)):
        root = root_for(cfg)
        active_id = active(root, cfg)
        if active_id is not None:
            raise InstallError("installation_pending")
        directory = root / "transactions" / installation_id
        if os.path.lexists(directory):
            intent, receipt = record(directory, cfg)
            files, _, plan_receipt = plan_files(path, cfg)
            if intent["receiptSha256"] != sha(files["receipt.json"]) or intent["planId"] != plan_receipt["planId"]:
                raise InstallError("operation_conflict")
            if intent["currentDigest"] != expected_current:
                raise InstallError("stale_current")
            if receipt is None:
                raise InstallError("installation_pending")
            return replay(receipt, intent, cfg)
        cfg = settings(cfg.environ)
        directories.validate()
        if cfg.directory_ids != directories.cfg.directory_ids:
            raise InstallError("directory_identity_changed")
        facts, before, after, required = proposal(cfg, path)
        if facts["currentDigest"] != expected_current:
            raise InstallError("stale_current")
        if facts["reviewDigest"] != expected_review:
            raise InstallError("stale_review")
        # The same plan under a different review must not resurrect a revoked historical grant.
        for prior in operation_dirs(root):
            old, old_receipt = record(prior, cfg)
            if old_receipt and old_receipt["outcome"] == "committed" and old["planId"] == facts["planId"]:
                if old["receiptSha256"] != facts["receiptSha256"]:
                    raise InstallError("operation_conflict")
                return replay(old_receipt, old, cfg)
        transactions = root / "transactions"
        if transactions.exists() and len(os.listdir(directories.fd(transactions))) >= MAX_OPERATIONS:
            raise InstallError("journal_bounds")
        # Repeat the complete read-only authority check immediately before journal publication.
        final, final_before, _, _ = proposal(settings(cfg.environ), path)
        if final["reviewDigest"] != expected_review or final_before != before:
            raise InstallError("stale_review")
        root = root_for(cfg, create=True, directories=directories)
        transactions = root / "transactions"
        staging = directories.staging(transactions)
        images = dict(zip(IMAGES, (*before, *after)))
        intent = {"schemaVersion": SCHEMA, "installationId": installation_id, "binding": cfg.binding(), "reviewDigest": expected_review,
                  "currentDigest": expected_current, "planId": facts["planId"], "planDigest": facts["planDigest"],
                  "receiptSha256": facts["receiptSha256"], "required": required, "images": {name: sha(raw) for name, raw in images.items()}}
        for name, raw in images.items():
            publish(staging / name, raw, directories)
        publish(staging / "intent.json", encode(intent), directories)
        sync(staging, directories)
        publish_directory(staging, directory, directories)
        sync(transactions, directories)
        publish(root / "pending.json", encode({"schemaVersion": SCHEMA, "installationId": installation_id, "transactionDigest": digest(intent)}), directories)
        # CAS again after staging. A manual third-state write is never overwritten.
        if current_pair(cfg, directories) != before or settings(cfg.environ).fingerprint != cfg.fingerprint:
            raise InstallError("journal_target_drift")
        for index, target in enumerate(cfg.targets):
            if current_pair(cfg, directories) != tuple(after[i] if i < index else before[i] for i in range(2)):
                raise InstallError("journal_target_drift")
            if before[index] != after[index]:
                publish(target, after[index], directories, replace=True)
        if current_pair(cfg, directories) != after:
            raise InstallError("journal_target_drift")
        return {**finish(root, directory, intent, "committed", directories), "appliedNow": True, "installationCurrent": True}


def recover(cfg: Settings, installation_id: str, expected_transaction: str) -> dict:
    if not ID.fullmatch(installation_id) or not config.DIGEST.fullmatch(expected_transaction):
        raise InstallError("digest_invalid")
    with Directories(cfg) as directories, ProcessLock(cfg.state, directory_fd=directories.fd(cfg.state)):
        directories.validate()
        root = root_for(cfg)
        marker_id = active(root, cfg)
        if marker_id is not None and marker_id != installation_id:
            raise InstallError("installation_pending")
        directory = root / "transactions" / installation_id
        intent, receipt = record(directory, cfg)
        if digest(intent) != expected_transaction:
            raise InstallError("stale_transaction")
        before = tuple(read_file(directory / name, FILES["approvals.json"] if "approvals" in name else FILES["relation-upstreams.json"]) for name in IMAGES[:2])
        after = tuple(read_file(directory / name, FILES["approvals.json"] if "approvals" in name else FILES["relation-upstreams.json"]) for name in IMAGES[2:])
        current = current_pair(cfg, directories)
        if receipt:
            if marker_id is not None:
                expected = after if receipt["outcome"] == "committed" else before
                if current != expected:
                    raise InstallError("journal_target_drift")
                clear_marker(root, directories)
            return replay(receipt, intent, cfg)
        if any(raw not in (before[index], after[index]) for index, raw in enumerate(current)):
            raise InstallError("journal_target_drift")
        # Also protects an unpublished-intent crash: make recovery visible before its first write.
        if marker_id is None:
            publish(root / "pending.json", encode({"schemaVersion": SCHEMA, "installationId": installation_id, "transactionDigest": digest(intent)}), directories)
        for index, target in enumerate(cfg.targets):
            pair = current_pair(cfg, directories)
            if any(raw not in (before[i], after[i]) for i, raw in enumerate(pair)):
                raise InstallError("journal_target_drift")
            if pair[index] != before[index]:
                publish(target, before[index], directories, replace=True)
        if current_pair(cfg, directories) != before:
            raise InstallError("journal_target_drift")
        return {**finish(root, directory, intent, "aborted", directories), "appliedNow": False, "installationCurrent": False}
