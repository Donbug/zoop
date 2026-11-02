"""Finite, operator-bound private news acquisition. Never a native grant or ingestion input."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
import time
import uuid
from collections import Counter, defaultdict, deque
from collections.abc import MutableMapping
from dataclasses import asdict, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from pydantic import Field, model_serializer, model_validator

from .collection import Fetcher, Rules, parse_robots
from .collection_contracts import Policy
from .collector_control import NO_CONTROL
from .ingestion_contracts import MAX_RAW, IngestionFailure, Wire, byte_hash, canonical, digest, now, reserved_state_roots
from .ingestion_parsers import prepare, profile
from .ingestion_url import canonical_url
from . import news_archives as archives
from .news_sources import SourceDescriptor

MAX_FILE = 64_000_000
USE = {"rights": "unconfirmed", "modelSend": False, "publicUse": False,
       "usage": "private-local-experiment-only; no redistribution or external model transmission"}
RECORD_FIELDS = frozenset(("schemaVersion privateId provenance planDigest source discoveryRefs requestUrl finalUrl "
                          "canonicalUrl redirects robots title publication publicationDay observedAt publisher "
                          "declaredSourceType declaredReliability observedSourceKind articleXPath rawSha256 rawBytes "
                          "textSha256 parserProfile prepared literalAliasMatches rights modelSend publicUse usage").split())
RECORD2_FIELDS = RECORD_FIELDS | {"extractionArtifact", "extractionBackend", "representation"}
RECORD3_FIELDS = RECORD2_FIELDS | {"publicationEvidence"}
RESOURCE_STOPS = frozenset({"request_budget", "byte_budget", "timeout", "fallback_budget_live_set_work_exhausted"})
HARD_STOPS = RESOURCE_STOPS | {"provider_unknown_no_retry", "provider_invalid_response"}
ENGLISH_MONTHS = {name: month for month, name in enumerate(
    ("January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"), 1)}


class PrivatePolicy(Policy):
    max_requests: int = Field(ge=1)
    max_total_seconds: int = Field(ge=1)
    max_total_bytes: int = Field(ge=1)
    max_discovery_response_bytes: int | None = Field(default=None, ge=1, le=MAX_RAW)

    @model_validator(mode="after")
    def discovery_limit_within_total(self):
        if self.max_discovery_response_bytes is not None and self.max_discovery_response_bytes > self.max_total_bytes:
            raise ValueError("discovery response limit exceeds the run limit")
        return self

    @model_serializer(mode="wrap")
    def without_unspecified_discovery_limit(self, handler):
        dumped = super()._without_unspecified_contact(handler)
        if self.max_discovery_response_bytes is None:
            dumped.pop("maxDiscoveryResponseBytes" if "maxDiscoveryResponseBytes" in dumped else "max_discovery_response_bytes", None)
        return dumped


class Source(Wire):
    name: str = Field(min_length=1, max_length=100)
    source_type: Literal["editorial", "corporate-pr", "government", "discovery", "unknown"]
    reliability: str = Field(min_length=1, max_length=200)
    queries: list[str] = Field(max_length=50)
    descriptor: SourceDescriptor | None = None

    @model_serializer(mode="wrap")
    def without_unspecified_descriptor(self, handler):
        dumped = handler(self)
        if self.descriptor is None:
            dumped.pop("descriptor", None)
        return dumped


class FallbackConfig(Wire):
    enabled: Literal[True]
    set_id: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=100)
    approval_ref: str = Field(min_length=1, max_length=1000)
    budget_config_path: str
    budget_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    set_proof_path: str
    set_proof_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    allowed_hosts: list[str] = Field(min_length=1, max_length=100)
    max_calls: int = Field(ge=1)


class Predecessor(Wire):
    state_dir: str
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    queue_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class KnownUnsent(Wire):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_id: str


class Config(Wire):
    schema_version: Literal["zoop-private-news-config-1", "zoop-private-news-config-2"]
    plan_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
    state_dir: str
    from_day: str
    through_day: str
    operator_approval_ref: str = Field(min_length=1, max_length=1000)
    sources: list[Source] = Field(min_length=1, max_length=100)
    exact_article_hosts: list[str] = Field(min_length=1, max_length=100)
    policy: PrivatePolicy
    max_listing_pages: int | None = Field(default=None, ge=1, le=10_000)
    max_candidates: int | None = Field(default=None, ge=1, le=100_000)
    max_documents: int | None = Field(default=None, ge=1, le=10_000)
    max_article_attempts: int | None = Field(default=None, ge=1, le=100_000)
    per_day_cap: int | None = Field(default=None, ge=1, le=1000)
    selection_mode: Literal["fresh-first", "backfill"] = "fresh-first"
    company_aliases: list[str] = Field(default_factory=list, max_length=200)
    synthetic_base_url: str | None = None
    fallback: FallbackConfig | None = None
    predecessor: Predecessor | None = None
    known_unsent: KnownUnsent | None = None

    @model_serializer(mode="wrap")
    def versioned_fields(self, handler):
        dumped = handler(self)
        if self.schema_version == "zoop-private-news-config-1":
            dumped.pop("selectionMode" if "selectionMode" in dumped else "selection_mode", None)
        if self.fallback is None:
            dumped.pop("fallback", None)
        if self.predecessor is None:
            dumped.pop("predecessor", None)
        if self.known_unsent is None:
            dumped.pop("knownUnsent" if "knownUnsent" in dumped else "known_unsent", None)
        return dumped

    @property
    def paged(self):
        return self.schema_version == "zoop-private-news-config-2"
    @model_validator(mode="after")
    def bounded(self):
        if (date.fromisoformat(self.from_day).isoformat() != self.from_day or
                date.fromisoformat(self.through_day).isoformat() != self.through_day or
                self.from_day > self.through_day or
                (date.fromisoformat(self.through_day) - date.fromisoformat(self.from_day)).days >= 366):
            raise ValueError("bounded calendar window required")
        if self.fallback is not None:
            if (not self.paged or self.policy.synthetic_loopback or len(self.sources) != 1
                    or self.fallback.source_id != self.sources[0].name
                    or set(self.fallback.allowed_hosts) != set(self.exact_article_hosts)):
                raise ValueError("fallback requires one exact public source in a v2 plan")
            for path in (self.fallback.budget_config_path, self.fallback.set_proof_path):
                if not Path(path).is_absolute() or os.path.abspath(path) != path:
                    raise ValueError("absolute pinned fallback configuration paths required")
        if not Path(self.state_dir).is_absolute() or os.path.abspath(self.state_dir) != self.state_dir:
            raise ValueError("absolute canonical state path required")
        if self.known_unsent is not None:
            if (not self.paged or self.policy.synthetic_loopback or len(self.sources) != 1
                    or not Path(self.known_unsent.path).is_absolute()):
                raise ValueError("known-unsent continuation requires a pinned public single-source plan")
        if self.predecessor is not None:
            previous, current = Path(self.predecessor.state_dir), Path(self.state_dir)
            if (not self.paged or not previous.is_absolute() or str(previous) != os.path.abspath(previous)
                    or previous == current or previous.is_relative_to(current) or current.is_relative_to(previous)):
                raise ValueError("a distinct canonical predecessor namespace requires schema 2")
        if len({s.name for s in self.sources}) != len(self.sources):
            raise ValueError("duplicate source")
        for source in self.sources:
            if self.paged and source.descriptor is None:
                selected = archives.source_descriptor(source.name)
                if selected is not None:
                    source.descriptor = selected.model_copy(deep=True)
            archives.source_hosts(source.name, descriptor=source.descriptor)
            if any(not 1 <= len(q) <= 1000 for q in source.queries):
                raise ValueError("bounded queries required")
        if len(set(self.exact_article_hosts)) != len(self.exact_article_hosts):
            raise ValueError("duplicate host")
        for host in self.exact_article_hosts:
            if canonical_url("https://" + host + "/")[1] != host or any(c in host for c in "/:@?#"):
                raise ValueError("exact lower-case host required")
        if self.policy.allowed_media_types != ["text/html"]:
            raise ValueError("static HTML articles only")
        if (not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", self.policy.user_agent) or
                self.policy.user_agent.split("/")[0].lower() in {"mozilla", "chrome", "safari", "firefox", "edge", "opera"}):
            raise ValueError("an identifiable non-browser product/version is required")
        limits = (self.max_listing_pages, self.max_candidates, self.max_documents, self.max_article_attempts, self.per_day_cap)
        if self.paged:
            if any(value is not None for value in limits):
                raise ValueError("v2 uses resource budgets, not listing/document/day/attempt quotas")
        elif (any(value is None for value in limits) or
              self.max_documents > self.max_article_attempts or self.max_article_attempts > self.max_candidates):
            raise ValueError("v1 document/attempt/candidate caps must be ordered")
        if any(not 1 <= len(alias) <= 200 for alias in self.company_aliases):
            raise ValueError("bounded literal aliases required")
        if self.policy.synthetic_loopback:
            if not self.synthetic_base_url or not re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}", self.synthetic_base_url):
                raise ValueError("explicit numeric loopback origin required")
            if not 1 <= urlsplit(self.synthetic_base_url).port <= 65535 or self.exact_article_hosts != ["127.0.0.1"]:
                raise ValueError("synthetic articles must stay on numeric loopback")
        elif self.synthetic_base_url is not None or self.policy.min_interval_seconds < 2:
            raise ValueError("public sources require at least two-second pacing; no synthetic origin")
        for source in self.sources:
            archives.initial_tasks(source.name, self.from_day, self.through_day, tuple(source.queries),
                                   synthetic_origin=self.synthetic_base_url, descriptor=source.descriptor)
        return self


def _source_descriptor(config, source):
    return next(item.descriptor for item in config.sources if item.name == source)

def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def _directory(path):
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in Path(path).parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read(fd, name):
    child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        info = os.fstat(child)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
            raise IngestionFailure("private_file_invalid")
        with os.fdopen(child, "rb", closefd=False) as source:
            raw = source.read(MAX_FILE + 1)
        if len(raw) > MAX_FILE:
            raise IngestionFailure("private_file_invalid")
        return raw
    finally:
        os.close(child)


def load_config(path):
    path = Path(os.path.abspath(path))
    fd = _directory(path.parent)
    try:
        raw = _read(fd, path.name)
        if len(raw) > 200_000:
            raise IngestionFailure("private_config_size")
        return Config.model_validate(_json(raw))
    finally:
        os.close(fd)


def _publish(fd, name, raw, *, immutable=False):
    if len(raw) > MAX_FILE:
        raise IngestionFailure("private_file_size")
    temporary = ".stage-" + uuid.uuid4().hex
    child = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(child, "wb") as target:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
        if immutable:
            os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        else:
            os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
            os.fsync(fd)
        except FileNotFoundError:
            pass


def _provenance(config):
    return "synthetic-loopback" if config.policy.synthetic_loopback else "private-public-web"


def _binding(config):
    return {"schemaVersion": "zoop-private-news-plan-1", "config": config.wire(),
            "parserProfile": profile(), "engine": "private-news-2" if config.paged else "private-news-1",
            "provenance": _provenance(config), **USE}


def _task_url(config, task):
    if config.synthetic_base_url:
        parts = urlsplit(task.url)
        task = replace(task, url=config.synthetic_base_url + urlunsplit(("", "", parts.path, parts.query, "")))
    return task


class _QueueRow(dict):
    """Persist explicit top-level mutations; nested values are replaced by callers."""
    def __init__(self, values, changed):
        super().__init__(values)
        self.changed = changed

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.changed(self)

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self.changed(self)


class _QueueMap(MutableMapping):
    def __init__(self, connection, table):
        self.connection, self.table = connection, table

    def __len__(self):
        return self.connection.execute(f"SELECT count(*) FROM {self.table}").fetchone()[0]

    def __iter__(self):
        for row in self.connection.execute(f"SELECT key FROM {self.table} ORDER BY rowid"):
            yield row[0]

    def __getitem__(self, key):
        row = self.connection.execute(f"SELECT value, sha256 FROM {self.table} WHERE key=?", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        value = _json(row[0])
        if digest(value) != row[1]:
            raise IngestionFailure("private_state_corrupt")
        return _QueueRow(value, lambda item: self.__setitem__(key, item))

    def __setitem__(self, key, value):
        refs = value.get("refs", [])
        task = value.get("task", {})
        hint = max((ref.get("archive_day") or "" for ref in refs), default="")
        source = value.get("source") or (refs[0]["source"] if refs else "")
        kind = task.get("kind", "")
        priority = 0 if "feed" in kind or "rss" in kind or "list" in kind or kind == "archive-html" else 1
        self.connection.execute(f"INSERT INTO {self.table}(key,value,sha256,status,source,day,priority) "
                                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
                                "sha256=excluded.sha256,status=excluded.status,source=excluded.source,"
                                "day=excluded.day,priority=excluded.priority",
                                (key, canonical(dict(value)), digest(dict(value)), value.get("status", ""),
                                 source, hint or task.get("from_day", ""), priority))

    def __delitem__(self, key):
        raise IngestionFailure("private_queue_append_only")

    def setdefault(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            self[key] = default
            return self[key]

    def keys_where(self, *, status="pending", fresh=True):
        direction = "DESC" if fresh else "ASC"
        while True:
            rows = self.connection.execute(
                f"SELECT key FROM {self.table} WHERE status=? ORDER BY priority,day {direction},rowid LIMIT 128", (status,)).fetchall()
            if not rows:
                return
            for row in rows:
                yield row[0]


class _QueueAttempts:
    def __init__(self, mapping):
        self.mapping = mapping

    def __len__(self):
        return len(self.mapping)

    def __iter__(self):
        return iter(self.mapping.values())

    def append(self, value):
        key = str(len(self.mapping))
        self.mapping[key] = value
        return self.mapping[key]


class State:
    """Descriptor-relative owned namespace; an immutable plan precedes every mutable snapshot."""
    def __init__(self, config, command, control=NO_CONTROL):
        self.config, self.fd, self.lock, self.control = config, None, None, control
        self.queue = None
        root = Path(config.state_dir)
        for reserved in [Path(__file__).resolve().parents[4], *reserved_state_roots()]:
            if root == reserved or root.is_relative_to(reserved) or reserved.is_relative_to(root):
                raise IngestionFailure("private_namespace_conflict")
        parent = _directory(root.parent)
        try:
            if command == "run":
                try:
                    os.mkdir(root.name, 0o700, dir_fd=parent)
                except FileExistsError:
                    pass
            if command != "status":
                os.fsync(parent)
            self.fd = os.open(root.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        finally:
            os.close(parent)
        try:
            info = os.fstat(self.fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise IngestionFailure("private_namespace_conflict")
            if config.paged:
                with os.scandir(self.fd) as scan:
                    fresh = next(scan, None) is None
                entries = {name for name in ("PLAN.json", "STATE.json", ".lock") if self.exists(name)}
            else:
                entries = set(os.listdir(self.fd))
                fresh = not entries
            if fresh and command != "run":
                raise IngestionFailure("private_state_missing")
            if not fresh and not {"PLAN.json", "STATE.json", ".lock"} <= entries:
                raise IngestionFailure("private_namespace_conflict")
            if not fresh and _json(_read(self.fd, "PLAN.json")) != _binding(config):
                raise IngestionFailure("private_plan_conflict")
            self.lock = os.open(".lock", os.O_RDWR | (os.O_CREAT if fresh else 0) | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
            if not stat.S_ISREG(os.fstat(self.lock).st_mode):
                raise IngestionFailure("private_namespace_conflict")
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise IngestionFailure("private_busy") from None
            if config.paged:
                queue_fd = os.open("QUEUE.sqlite3", os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT | os.O_EXCL if fresh else 0),
                                   0o600, dir_fd=self.fd)
                info = os.fstat(queue_fd)
                os.close(queue_fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
                    raise IngestionFailure("private_namespace_conflict")
                self.queue = sqlite3.connect(str(root / "QUEUE.sqlite3"))
                self.queue.execute("PRAGMA synchronous=FULL")
                self.queue.execute("PRAGMA temp_store=FILE")
                if fresh:
                    for table in ("tasks", "candidates", "attempts"):
                        self.queue.execute(f"CREATE TABLE {table}(key TEXT PRIMARY KEY,value TEXT NOT NULL,"
                                           "sha256 TEXT NOT NULL,status TEXT NOT NULL,source TEXT NOT NULL,"
                                           "day TEXT NOT NULL,priority INTEGER NOT NULL)")
                        self.queue.execute(f"CREATE INDEX {table}_pending ON {table}(status,priority,day)")
                    self.queue.execute("CREATE TABLE binding(digest TEXT NOT NULL)")
                    self.queue.execute("INSERT INTO binding VALUES(?)", (digest(_binding(config)),))
                    self.queue.commit()
                elif self.queue.execute("SELECT digest FROM binding").fetchall() != [(digest(_binding(config)),)]:
                    raise IngestionFailure("private_plan_conflict")
            if fresh:
                tasks = _QueueMap(self.queue, "tasks") if config.paged else {}
                for source in (() if config.predecessor is not None or config.known_unsent is not None else config.sources):
                    for task in archives.initial_tasks(source.name, config.from_day, config.through_day, tuple(source.queries),
                                                       synthetic_origin=config.synthetic_base_url, descriptor=source.descriptor):
                        task = _task_url(config, task)
                        key = digest([source.name, task.key])
                        tasks[key] = {"source": source.name, "task": asdict(task), "status": "pending", "saturated": False}
                self.data = {"schemaVersion": "zoop-private-news-state-1", "planDigest": digest(_binding(config)),
                             "startedAt": now(), "requests": 0, "bytes": 0, "unknownRequests": 0,
                             "unknownByteUpperBound": 0, "pendingRequest": None, "blocked": [], "delays": {},
                             "tasks": tasks, "candidates": {}, "attempts": [], "stopCode": None}
                _publish(self.fd, "PLAN.json", canonical(_binding(config)).encode(), immutable=True)
                if config.paged:
                    self.data.update(providerBytes=0, providerUnknownByteUpperBound=0, providerUnknownRequests=0,
                                     pendingProviderRequest=None)
                    self.data["candidates"] = _QueueMap(self.queue, "candidates")
                    self.data["attempts"] = _QueueAttempts(_QueueMap(self.queue, "attempts"))
                    if config.predecessor is not None:
                        _seed_predecessor(self)
                    elif config.known_unsent is not None:
                        from .private_continuation import seed
                        seed(self)
                self.save()
            else:
                envelope = _json(_read(self.fd, "STATE.json"))
                self.data = envelope["state"]
                if set(envelope) != {"state", "sha256"} or envelope["sha256"] != digest(self.data):
                    raise IngestionFailure("private_state_corrupt")
                if config.paged:
                    if any(self.data.get(name) != "sqlite:" + name for name in ("tasks", "candidates", "attempts")):
                        raise IngestionFailure("private_state_corrupt")
                    self.data["tasks"] = _QueueMap(self.queue, "tasks")
                    self.data["candidates"] = _QueueMap(self.queue, "candidates")
                    self.data["attempts"] = _QueueAttempts(_QueueMap(self.queue, "attempts"))
            self._validate_namespace()
            self._validate_state()
        except BaseException:
            self.close()
            raise

    def exists(self, name):
        try:
            os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False

    def _validate_namespace(self):
        if self.config.paged:
            with os.scandir(self.fd) as entries:
                for entry in entries:
                    name = entry.name
                    if name not in {"PLAN.json", "STATE.json", ".lock", "QUEUE.sqlite3", "QUEUE.sqlite3-journal"}:
                        match = re.fullmatch(r"(private-news-[0-9a-f]{64}|listing-([0-9a-f]{64}))\.(json|raw|extraction\.json)", name)
                        cause = re.fullmatch(r"(?:native-[0-9a-f]{64}\.json|robots-[0-9a-f]{64}\.raw)", name)
                        if not match and not cause and not re.fullmatch(r"\.stage-[0-9a-f]{32}", name):
                            raise IngestionFailure("private_namespace_conflict")
                        if match:
                            mapping = self.data["tasks"] if match[2] else self.data["candidates"]
                            if (match[2] or match[1]) not in mapping:
                                raise IngestionFailure("private_namespace_conflict")
                    info = entry.stat(follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                        raise IngestionFailure("private_namespace_conflict")
                    if info.st_nlink != 1:
                        with os.scandir(self.fd) as others:
                            linked = sum((other.stat(follow_symlinks=False).st_dev, other.inode()) == (info.st_dev, info.st_ino)
                                         for other in others)
                        if linked != info.st_nlink:
                            raise IngestionFailure("private_namespace_conflict")
            return
        entries = os.listdir(self.fd)
        inode_counts = Counter((os.stat(name, dir_fd=self.fd, follow_symlinks=False).st_dev,
                                os.stat(name, dir_fd=self.fd, follow_symlinks=False).st_ino) for name in entries)
        for name in entries:
            if name not in {"PLAN.json", "STATE.json", ".lock", *({"QUEUE.sqlite3", "QUEUE.sqlite3-journal"} if self.config.paged else set())} and not re.fullmatch(
                    r"(?:private-news-[0-9a-f]{64}\.(?:json|raw)|listing-[0-9a-f]{64}\.(?:json|raw)|\.stage-[0-9a-f]{32})", name):
                raise IngestionFailure("private_namespace_conflict")
            info = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                    stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != inode_counts[(info.st_dev, info.st_ino)]):
                raise IngestionFailure("private_namespace_conflict")

    def _validate_state(self):
        data = self.data
        if data["schemaVersion"] != "zoop-private-news-state-1" or data["planDigest"] != digest(_binding(self.config)):
            raise IngestionFailure("private_state_corrupt")
        for field in ("requests", "bytes", "unknownRequests", "unknownByteUpperBound"):
            if type(data[field]) is not int or data[field] < 0:
                raise IngestionFailure("private_state_corrupt")
        for field in ("providerBytes", "providerUnknownByteUpperBound", "providerUnknownRequests"):
            if type(data.get(field, 0)) is not int or data.get(field, 0) < 0:
                raise IngestionFailure("private_state_corrupt")
        datetime.fromisoformat(data["startedAt"])
        if self.config.paged:
            for pin in data.get("client403", {}).values():
                retained = _read(self.fd, pin["file"])
                if pin["file"] != "native-" + pin["sha256"] + ".json" or byte_hash(retained) != pin["sha256"]:
                    raise IngestionFailure("private_state_corrupt")
            for fact in data.get("robotsFacts", {}).values():
                if fact["file"] != "robots-" + fact["sha256"] + ".raw" or byte_hash(_read(self.fd, fact["file"])) != fact["sha256"]:
                    raise IngestionFailure("private_state_corrupt")
            for key, item in data["tasks"].items():
                task = archives.ArchiveTask(**item["task"])
                if key != digest([item["source"], task.key]) or item["status"] not in {"pending", "attempting", "done", "refused", "unknown", "inherited"}:
                    raise IngestionFailure("private_state_corrupt")
                if item["status"] == "inherited" and ((self.config.predecessor is None and self.config.known_unsent is None) or item.get("inheritedStatus") not in {"done", "refused", "unknown"}):
                    raise IngestionFailure("private_state_corrupt")
                if item["status"] == "done":
                    listing = _json(_read(self.fd, "listing-" + key + ".json"))
                    if digest(listing) != item["listingDigest"] or byte_hash(_read(self.fd, "listing-" + key + ".raw")) != listing["rawSha256"]:
                        raise IngestionFailure("private_state_corrupt")
            for identifier, item in data["candidates"].items():
                if identifier != "private-news-" + digest([self.config.plan_id, item["url"]]):
                    raise IngestionFailure("private_state_corrupt")
                if item["status"] not in {"pending", "attempting", "retained", "refused", "unknown", "inherited"}:
                    raise IngestionFailure("private_state_corrupt")
                if item["status"] == "inherited" and (self.config.predecessor is None or item.get("inheritedStatus") not in {"retained", "refused", "unknown"}):
                    raise IngestionFailure("private_state_corrupt")
                if item["status"] == "retained" or self.exists(identifier + ".json"):
                    self.record(identifier)
            return
        names = set(os.listdir(self.fd))
        expected = {"PLAN.json", "STATE.json", ".lock"}
        if self.config.paged:
            expected.update({"QUEUE.sqlite3", "QUEUE.sqlite3-journal"})
        for key, item in data["tasks"].items():
            task = archives.ArchiveTask(**item["task"])
            if key != digest([item["source"], task.key]):
                raise IngestionFailure("private_state_corrupt")
            if item["status"] not in {"pending", "attempting", "done", "refused", "unknown"}:
                raise IngestionFailure("private_state_corrupt")
            for suffix in (".json", ".raw"):
                if "listing-" + key + suffix in names:
                    expected.add("listing-" + key + suffix)
            if item["status"] == "done":
                listing = _json(_read(self.fd, "listing-" + key + ".json"))
                if digest(listing) != item["listingDigest"]:
                    raise IngestionFailure("private_state_corrupt")
                if byte_hash(_read(self.fd, "listing-" + key + ".raw")) != listing["rawSha256"]:
                    raise IngestionFailure("private_state_corrupt")
        for identifier, item in data["candidates"].items():
            if identifier != "private-news-" + digest([self.config.plan_id, item["url"]]):
                raise IngestionFailure("private_state_corrupt")
            if item["status"] not in {"pending", "attempting", "retained", "refused", "unknown"}:
                raise IngestionFailure("private_state_corrupt")
            for suffix in (".json", ".raw"):
                if identifier + suffix in names:
                    expected.add(identifier + suffix)
            if identifier + ".json" in names:
                self.record(identifier)
            elif item["status"] == "retained":
                raise IngestionFailure("private_record_missing")
        if any(name not in expected and not name.startswith(".stage-") for name in names):
            raise IngestionFailure("private_namespace_conflict")

    def record(self, identifier):
        record = _json(_read(self.fd, identifier + ".json"))
        if isinstance(record, dict) and record.get("schemaVersion") in {"zoop-private-news-record-2", "zoop-private-news-record-3"}:
            raw = _read(self.fd, identifier + ".raw")
            envelope = _read(self.fd, identifier + ".extraction.json")
            causal = _causal_bytes(self, _json(envelope))
            verify_record(record, raw, extraction_raw=envelope, causal_raw=causal)
            item = self.data["candidates"][identifier]
            declared = next(source for source in self.config.sources if source.name == record["source"])
            if (record["privateId"] != identifier or record["planDigest"] != self.data["planDigest"]
                    or record["requestUrl"] != canonical_url(item["url"])[0] or record["discoveryRefs"] != item["refs"]
                    or record["provenance"] != "private-public-web-extracted"
                    or record["declaredSourceType"] != declared.source_type
                    or record["declaredReliability"] != declared.reliability):
                raise IngestionFailure("private_record_corrupt")
            if (record["schemaVersion"] == "zoop-private-news-record-3"
                    and record["publicationEvidence"]["sourceDescriptor"] != (declared.descriptor.wire() if declared.descriptor else None)):
                raise IngestionFailure("private_publication_source_unbound")
            return record
        if not isinstance(record, dict) or set(record) != RECORD_FIELDS:
            raise IngestionFailure("private_record_corrupt")
        raw = _read(self.fd, identifier + ".raw")
        item = self.data["candidates"][identifier]
        if (record["schemaVersion"] != "zoop-private-news-record-1" or record["privateId"] != identifier or
                record["planDigest"] != self.data["planDigest"] or record["requestUrl"] != canonical_url(item["url"])[0] or
                any(record[key] != value for key, value in USE.items()) or
                record["rawSha256"] != byte_hash(raw) or
                record["textSha256"] != byte_hash(record["prepared"]["text"].encode()) or
                record["parserProfile"] != profile(record["articleXPath"])):
            raise IngestionFailure("private_record_corrupt")
        meta = archives.article_metadata(record["source"], raw, record["finalUrl"],
                                         synthetic_origin=self.config.synthetic_base_url,
                                         descriptor=_source_descriptor(self.config, record["source"]))
        publication = _publication(meta.published_at)
        if (record["publication"] != publication or record["publicationDay"] != publication["day"] or
                record["title"] != meta.title or record["canonicalUrl"] != meta.canonical_url or
                record["articleXPath"] != meta.article_xpath or record["discoveryRefs"] != item["refs"]):
            raise IngestionFailure("private_record_corrupt")
        declared = next(s for s in self.config.sources if s.name == record["source"])
        if (record["publisher"] != meta.publisher or record["observedSourceKind"] != meta.source_kind or
                record["declaredSourceType"] != declared.source_type or
                record["declaredReliability"] != declared.reliability or
                record["rawBytes"] != len(raw) or record["provenance"] != _provenance(self.config)):
            raise IngestionFailure("private_record_corrupt")
        # Reuse the exact native mapping algorithm, not a parallel coordinate validator.
        if prepare(raw, "text/html", record["articleXPath"]) != record["prepared"]:
            raise IngestionFailure("private_record_corrupt")
        return record

    def save(self):
        snapshot = self.data
        if self.queue is not None:
            self.queue.commit()
            snapshot = {**self.data, **{name: "sqlite:" + name for name in ("tasks", "candidates", "attempts")}}
        _publish(self.fd, "STATE.json", canonical({"state": snapshot, "sha256": digest(snapshot)}).encode())

    def recover(self):
        data = self.data
        if data["pendingRequest"] is not None:
            data["unknownRequests"] += 1
            data["unknownByteUpperBound"] += data["pendingRequest"]["byteUpperBound"]
            data["blocked"] = sorted(set(data["blocked"]) | {data["pendingRequest"]["host"]})
            data["pendingRequest"] = None
        if data.get("pendingProviderRequest") is not None:
            data["providerUnknownRequests"] = data.get("providerUnknownRequests", 0) + 1
            data["providerUnknownByteUpperBound"] = data.get("providerUnknownByteUpperBound", 0) + data["pendingProviderRequest"]["byteUpperBound"]
            data["pendingProviderRequest"] = None
            data["stopCode"] = "provider_unknown_no_retry"
        names = None if self.config.paged else set(os.listdir(self.fd))
        for key, task in data["tasks"].items():
            if task["status"] == "attempting":
                task["status"] = "unknown"
                task["code"] = "unsettled_discovery_no_retry"
        for identifier, item in data["candidates"].items():
            if item["status"] == "attempting":
                if (self.exists(identifier + ".json") if names is None else identifier + ".json" in names):
                    record = self.record(identifier)
                    item.update(status="retained", publicationDay=record["publicationDay"], textSha256=record["textSha256"],
                                literalAliasMatches=record["literalAliasMatches"], source=record["source"])
                else:
                    item.update(status="unknown", code="unsettled_article_no_retry")
        for attempt in data["attempts"]:
            if attempt["status"] == "attempting":
                attempt["status"] = "recovered_committed" if data["candidates"].get(attempt["key"], {}).get("status") == "retained" else "unknown"
        self.save()

    def close(self):
        if self.queue is not None:
            self.queue.close()
            self.queue = None
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class _Policy:
    def __init__(self, policy):
        self.policy = policy
        self.allowed_media_types = ("text/html",)

    def __getattr__(self, key):
        return getattr(self.policy, key)


class PrivateFetcher(Fetcher):
    """Journal each actual GET, including robots and redirects, without altering native transport."""
    def __init__(self, config, state):
        self.config, self.state = config, state
        self.discovery_source = None
        self.article_source = None
        self.discovery_task_url = None
        self.native_response = None
        self.native_redirects = []
        self.robots_observed_at = {}
        self.robots_responses = {}
        policy = _Policy(config.policy)
        hosts = set(config.exact_article_hosts)
        hosts.update(h for source in config.sources for h in archives.source_hosts(source.name, descriptor=source.descriptor))
        if config.synthetic_base_url:
            hosts = {"127.0.0.1"}
        super().__init__(policy, sorted(hosts), authority_guard=self._intent)
        self.requests = state.data["requests"] + state.data["unknownRequests"]
        self.downloaded = state.data["bytes"] + state.data["unknownByteUpperBound"]
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(state.data["startedAt"])).total_seconds()
        self.run_deadline = time.monotonic() + max(0, config.policy.max_total_seconds - max(0, elapsed))
        self._blocked.update(state.data["blocked"])
        self._delay.update(state.data["delays"])
        for origin, fact in state.data.get("robotsFacts", {}).items():
            raw = _read(state.fd, fact["file"])
            if byte_hash(raw) != fact["sha256"]:
                raise IngestionFailure("private_state_corrupt")
            self._robots[origin] = (IngestionFailure(fact["code"]) if fact.get("code") else
                                    parse_robots(raw, config.policy.user_agent) if fact["status"] == 200 else Rules())
            if isinstance(self._robots[origin], Rules):
                host = urlsplit(origin).hostname
                self._delay[host] = max(self._delay.get(host, 0.0), self._robots[origin].delay)
            self._observed[origin] = {"url": fact["url"], "status": fact["status"]}
            self.robots_observed_at[origin] = fact["observedAt"]
        for host in hosts:
            self._last[host] = time.monotonic()

    def _guard(self, value):
        try:
            url, host = super()._guard(value)
        except IngestionFailure as exc:
            if exc.code != "host_blocked" or not self._discovery_after_client403(value):
                raise
            # The base guard reached its final host-block check. All URL/host
            # checks passed; retain the block and admit only this declared route.
            url, host = canonical_url(value)
        parts = urlsplit(url)
        if self.config.synthetic_base_url and f"{parts.scheme}://{parts.netloc}" != self.config.synthetic_base_url:
            raise IngestionFailure("private_synthetic_origin_invalid")
        source = self.discovery_source or self.article_source
        selected = archives._descriptor(source, _source_descriptor(self.config, source)) if source else None
        if selected is not None and selected.access_status == "blocked-policy":
            raise IngestionFailure("archive_source_policy_denied")
        if self.discovery_source:
            if parts.path != "/robots.txt":
                archives.validate_discovery_url(self.discovery_source, url, synthetic_origin=self.config.synthetic_base_url,
                                               descriptor=_source_descriptor(self.config, self.discovery_source))
                expected = urlsplit(self.discovery_task_url)
                if (parts.path != expected.path or
                        sorted(parse_qsl(parts.query)) != sorted(parse_qsl(expected.query))):
                    raise IngestionFailure("archive_endpoint_invalid")
            elif parts.query:
                raise IngestionFailure("archive_endpoint_invalid")
            if not self.config.synthetic_base_url and host not in archives.source_hosts(
                    self.discovery_source, descriptor=_source_descriptor(self.config, self.discovery_source)):
                raise IngestionFailure("archive_endpoint_invalid")
        elif host not in self.config.exact_article_hosts:
            raise IngestionFailure("article_host_not_allowed")
        elif self.article_source and parts.path != "/robots.txt":
            archives.validate_article_url(self.article_source, url, synthetic_origin=self.config.synthetic_base_url,
                                          descriptor=_source_descriptor(self.config, self.article_source))
        return url, host

    def _discovery_after_client403(self, value):
        if not self.config.paged or not self.discovery_source or value != self.discovery_task_url:
            return False
        parts = urlsplit(value)
        origin = f"{parts.scheme}://{parts.netloc}"
        if parts.path == "/robots.txt" or parts.hostname not in public_client403_hosts(self.state):
            return False
        rules = self._robots.get(origin)
        if not isinstance(rules, Rules) or not rules.permits(value):
            return False
        source = self.discovery_source
        archives.validate_discovery_url(source, value, descriptor=_source_descriptor(self.config, source))
        matches = []
        for key, item in self.state.data["tasks"].items():
            if item["source"] == source and item["task"]["url"] == value:
                status = item.get("inheritedStatus", item["status"]) if item["status"] == "inherited" else item["status"]
                if status in {"refused", "unknown"}:
                    return False
                matches.append((key, item))
        initial = {digest([source, task.key]) for task in archives.initial_tasks(
            source, self.config.from_day, self.config.through_day,
            tuple(next(item.queries for item in self.config.sources if item.name == source)),
            descriptor=_source_descriptor(self.config, source))}
        for key, item in matches:
            kind = item["task"]["kind"]
            if not (kind in {"sitemap-xml", "rss-xml", "fnnews-partition"} or kind.startswith("fnnews-index")
                    or kind.startswith("configured:") and kind.rsplit(":", 1)[1] in {"feed", "sitemap"}):
                continue
            visited = set()
            while key not in visited:
                if key in initial:
                    return True
                visited.add(key)
                parent = item.get("discoveredFrom")
                item = self.state.data["tasks"].get(parent)
                if item is None or item.get("inheritedStatus", item["status"]) != "done" or item["source"] != source:
                    break
                key = parent
        return False

    def _intent(self):
        self.state.data["pendingRequest"] = {"host": self._request_host,
            "byteUpperBound": max(0, self.policy.max_total_bytes - self.downloaded - _provider_bytes(self.state)), "startedAt": now()}
        self.state.save()

    def _check(self, response, host, limit):
        if self.article_source and urlsplit(self._request_url).path != "/robots.txt":
            if self.native_response is not None and self.native_response["url"] != self._request_url:
                self.native_redirects.append(self._request_url)
            self.native_response = {"url": self._request_url, "status": response.status_code, "observedAt": now(),
                                    "mediaType": response.headers.get("content-type", "").split(";", 1)[0].strip().lower(),
                                    "wwwAuthenticate": "www-authenticate" in response.headers,
                                    "challenge": (response.headers.get("cf-mitigated", "").lower() == "challenge"
                                                  or response.headers.get("x-amzn-waf-action", "").lower() in {"challenge", "captcha"}),
                                    "body": None}
        super()._check(response, host, limit)

    def _get(self, url, host, deadline, limit):
        if self.discovery_source and urlsplit(url).path != "/robots.txt" and self.config.policy.max_discovery_response_bytes is not None:
            limit = self.config.policy.max_discovery_response_bytes
        self._request_host = host
        self._request_url = url
        before_requests, before_bytes = self.requests, self.downloaded
        self.last_get_known_unsent = True
        try:
            if self.config.paged and self.downloaded + _provider_bytes(self.state) + limit > self.policy.max_total_bytes:
                raise IngestionFailure("byte_budget")
            result = super()._get(url, host, deadline, limit)
            if self.native_response is not None and self.native_response["url"] == url:
                self.native_response["body"] = result[2]
            if urlsplit(url).path == "/robots.txt":
                parts = urlsplit(url)
                origin = f"{parts.scheme}://{parts.netloc}"
                self.robots_observed_at[origin] = now()
                self.robots_responses[origin] = {"raw": result[2], "url": url, "status": result[0],
                                                 "observedAt": self.robots_observed_at[origin]}
            return result
        finally:
            self.last_get_known_unsent = self.requests == before_requests
            data = self.state.data
            data["requests"] += self.requests - before_requests
            data["bytes"] += self.downloaded - before_bytes
            data["pendingRequest"] = None
            data["blocked"] = sorted(self._blocked)
            data["delays"] = dict(self._delay)
            self.state.save()

    def _rules(self, url, deadline):
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        code = None
        try:
            return super()._rules(url, deadline)
        except IngestionFailure as exc:
            code = exc.code
            raise
        finally:
            response = self.robots_responses.get(origin)
            if (self.config.paged and response is not None and origin not in self.state.data.get("robotsFacts", {})
                    and (code is None or code.startswith("robots_"))):
                raw = response["raw"]
                fact = {key: value for key, value in response.items() if key != "raw"}
                fact.update(file="robots-" + byte_hash(raw) + ".raw", sha256=byte_hash(raw), code=code)
                if not self.state.exists(fact["file"]):
                    _publish(self.state.fd, fact["file"], raw, immutable=True)
                self.state.data.setdefault("robotsFacts", {})[origin] = fact
                self.state.save()


def _publication(value):
    try:
        if value is None:
            precision, day = "unknown", None
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            date.fromisoformat(value)
            precision, day = "day", value
        elif re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", value):
            precision, day = "day", date.fromisoformat(value.replace(".", "-")).isoformat()
        elif match := re.fullmatch(r"([A-Za-z]+) ([1-9]|[12][0-9]|3[01]), ([0-9]{4})", value):
            month = ENGLISH_MONTHS.get(match[1])
            if month is None:
                raise ValueError("unsupported English month")
            precision, day = "day", date(int(match[3]), month, int(match[2])).isoformat()
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2}|[+-](?:[01]\d|2[0-3])[0-5]\d)?", value):
            parsed = datetime.fromisoformat(value)
            precision = "instant" if parsed.tzinfo is not None else "unresolved"
            day = value[:10] if parsed.tzinfo is not None else None
        else:
            raise ValueError("unsupported publication")
    except (ValueError, TypeError):
        raise IngestionFailure("article_date_invalid") from None
    return {"raw": value, "precision": precision, "day": day,
            "basis": "article publication metadata; original timezone precision preserved"}


def _attempt(state, kind, key):
    entry = {"kind": kind, "key": key, "startedAt": now(), "status": "attempting"}
    stored = state.data["attempts"].append(entry)
    return stored if stored is not None else entry


def _budget(state, fetcher):
    if state.data["stopCode"] in HARD_STOPS:
        return True
    if state.control.boundary():
        state.data["stopCode"] = state.data["stopCode"] or "admission_stopped"
        return True
    if fetcher.requests >= fetcher.policy.max_requests:
        state.data["stopCode"] = "request_budget"
    elif fetcher.downloaded + _provider_bytes(state) >= fetcher.policy.max_total_bytes:
        state.data["stopCode"] = "byte_budget"
    elif time.monotonic() >= fetcher.run_deadline:
        state.data["stopCode"] = "timeout"
    else:
        return False
    return True


def _balanced_days(days):
    """Farthest-first calendar buckets keep a small cap from selecting only one end."""
    ordered = sorted(set(days))
    if not ordered:
        return []
    selected = [0]
    remaining = set(range(1, len(ordered)))
    distances = list(range(len(ordered)))
    while remaining:
        index = max(remaining, key=lambda i: (distances[i], -i))
        selected.append(index)
        remaining.remove(index)
        for other in remaining:
            distances[other] = min(distances[other], abs(other - index))
    return [ordered[i] for i in selected]


def _discover(config, state, fetcher):
    data = state.data
    day_rank = {} if config.paged else {day: index for index, day in enumerate(_balanced_days(
        item["task"]["from_day"] for item in data["tasks"].values()))}
    while True:
        if config.paged:
            key = next(data["tasks"].keys_where(fresh=config.selection_mode == "fresh-first"), None)
            if key is None:
                break
        else:
            pending = [key for key, item in data["tasks"].items() if item["status"] == "pending"]
            if not pending:
                break
            key = min(pending, key=lambda k: (day_rank.get(data["tasks"][k]["task"]["from_day"], len(day_rank)),
                                             data["tasks"][k]["source"], k))
        item = data["tasks"][key]
        if _budget(state, fetcher):
            break
        if config.max_listing_pages is not None and sum(t["status"] != "pending" for t in data["tasks"].values()) >= config.max_listing_pages:
            data["stopCode"] = "listing_page_cap"
            break
        item.pop("code", None)
        item["status"] = "attempting"
        attempt = _attempt(state, "discovery", key)
        state.save()
        try:
            fetcher.discovery_source = item["source"]
            fetcher.discovery_task_url = item["task"]["url"]
            fetcher.policy.allowed_media_types = ("application/xml", "text/xml", "application/json", "text/json",
                                                   "application/rss+xml", "application/atom+xml", "text/html")
            response = fetcher.fetch(item["task"]["url"])
            task = archives.ArchiveTask(**item["task"])
            listing = archives.parse_listing(item["source"], task, response.body, response.final_url,
                                             synthetic_origin=config.synthetic_base_url,
                                             descriptor=_source_descriptor(config, item["source"]))
            evidence = {"schemaVersion": "zoop-private-news-discovery-1", "source": item["source"],
                        "task": item["task"], "requestUrl": response.requested_url, "finalUrl": response.final_url,
                        "provenance": _provenance(config),
                        "observedAt": response.fetched_at, "rawSha256": byte_hash(response.body),
                        "candidates": [asdict(c) for c in listing.candidates], "saturated": listing.saturated,
                        "nextTasks": [asdict(t) for t in listing.next_tasks]}
            if config.paged:
                evidence.update(redirects=response.redirects, robots=response.robots)
            _publish(state.fd, "listing-" + key + ".raw", response.body, immutable=True)
            _publish(state.fd, "listing-" + key + ".json", canonical(evidence).encode(), immutable=True)
            item.update(status="done", saturated=listing.saturated, listingDigest=digest(evidence))
            for candidate in listing.candidates:
                url = candidate.url
                identifier = "private-news-" + digest([config.plan_id, url])
                current = data["candidates"].setdefault(identifier, {"url": url, "status": "pending", "refs": []})
                if current["status"] == "pending":
                    current["refs"] = [*current["refs"], {"source": item["source"], "listing": key,
                                                        "partitionDay": task.from_day, **asdict(candidate)}]
            for following in listing.next_tasks:
                following = _task_url(config, following)
                following_key = digest([item["source"], following.key])
                data["tasks"].setdefault(following_key, {"source": item["source"], "task": asdict(following),
                                                       "status": "pending", "saturated": False, "discoveredFrom": key})
            attempt["status"] = "done"
        except IngestionFailure as exc:
            if (exc.code in {"request_budget", "byte_budget"} or
                    exc.code == "timeout" and time.monotonic() >= fetcher.run_deadline):
                data["stopCode"] = exc.code
            deferred = config.paged and getattr(fetcher, "last_get_known_unsent", False) and exc.code in {"request_budget", "byte_budget", "timeout", "rate_limit"}
            if deferred:
                data["stopCode"] = "timeout" if exc.code == "rate_limit" else exc.code
            item.update(status="pending" if deferred else "refused", code=exc.code)
            attempt.update(status="deferred" if deferred else "refused", code=exc.code)
        finally:
            fetcher.discovery_source = None
            fetcher.policy.allowed_media_types = ("text/html",)
            state.save()
        if config.paged:
            _acquire(config, state, fetcher)
    # V1 plans retain their historical discovery-then-acquisition ordering.


def _selection(state):
    if state.config.paged:
        yield from state.data["candidates"].keys_where(fresh=state.config.selection_mode == "fresh-first")
        return
    buckets = defaultdict(list)
    for identifier, item in state.data["candidates"].items():
        if item["status"] != "pending":
            continue
        dates = sorted({r["published_at"][:10] for r in item["refs"] if r["published_at"]})
        archive_dates = sorted({r["archive_day"] or r["partitionDay"] for r in item["refs"]})
        bucket = dates[0] if len(dates) == 1 else (archive_dates[0] if len(archive_dates) == 1 else "unknown")
        buckets[bucket].append((identifier, item))
    queues = []
    for day in _balanced_days(buckets):
        # Rotate sources/domains inside every date bucket as well as rotating dates.
        groups = defaultdict(deque)
        for identifier, item in sorted(buckets[day]):
            groups[(item["refs"][0]["source"], urlsplit(item["url"]).hostname)].append(identifier)
        queue = deque()
        while any(groups.values()):
            for group in sorted(groups):
                if groups[group]:
                    queue.append(groups[group].popleft())
        queues.append(queue)
    while any(queues):
        for queue in queues:
            if queue:
                yield queue.popleft()


def _acquire(config, state, fetcher):
    data = state.data
    retained = Counter() if config.paged else Counter(
        item.get("publicationDay") for item in data["candidates"].values() if item["status"] == "retained")
    source_config = {source.name: source for source in config.sources}
    admitted = 0 if config.paged else sum(item["status"] != "pending" for item in data["candidates"].values())
    for identifier in _selection(state):
        if _budget(state, fetcher):
            break
        if config.max_candidates is not None and admitted >= config.max_candidates:
            data["stopCode"] = "candidate_cap"
            break
        if config.max_documents is not None and sum(retained.values()) >= config.max_documents:
            data["stopCode"] = "document_cap"
            break
        if config.max_article_attempts is not None and sum(a["kind"] == "article" for a in data["attempts"]) >= config.max_article_attempts:
            data["stopCode"] = "article_attempt_cap"
            break
        item = data["candidates"][identifier]
        admitted += 1
        if urlsplit(item["url"]).hostname not in config.exact_article_hosts:
            item.update(status="refused", code="article_host_not_allowed")
            state.save()
            continue
        item.pop("code", None)
        item["status"] = "attempting"
        attempt = _attempt(state, "article", identifier)
        state.save()
        try:
            specific_sources = sorted({ref["source"] for ref in item["refs"]
                                       if ref["source"] != "gdelt-doc" and ref["source"] in source_config})
            source = specific_sources[0] if specific_sources else item["refs"][0]["source"]
            fetcher.article_source = source
            fetcher.article_refs = item["refs"]
            response, meta, prepared, extracted = _fetch_article(config, fetcher, item["url"], source, item.get("reusableNative"))
            if response is not None:
                attempt["response"] = {"requestUrl": response.requested_url, "finalUrl": response.final_url,
                                       "observedAt": response.fetched_at, "rawSha256": byte_hash(response.body),
                                       "rawBytes": len(response.body), "mediaType": response.media_type}
            if extracted is not None:
                envelope_raw = canonical(extracted.wire()).encode("utf-8")
                _publish(state.fd, identifier + ".extraction.json", envelope_raw, immutable=True)
                attempt["extractionArtifact"] = {"file": identifier + ".extraction.json", "sha256": byte_hash(envelope_raw)}
                attempt["extractionBackend"] = extracted.backend
                if extracted.provider_receipt is not None:
                    receipt = extracted.provider_receipt
                    attempt["providerOutcome"] = receipt.outcome
                    attempt["providerAttemptId"] = receipt.attempt_id
                    attempt["providerActualNano"] = receipt.actual_nano
                if extracted.format == "markdown":
                    from .publication_evidence import publication_evidence
                    evidence = publication_evidence(source, extracted, descriptor=_source_descriptor(config, source))
                    meta = replace(meta, published_at=evidence["publishedAt"])
            if not isinstance(meta.title, str) or not meta.title.strip():
                raise IngestionFailure("article_title_missing")
            publication = _publication(meta.published_at)
            attempt["articleMetadata"] = {"title": meta.title, "publication": publication,
                                           "canonicalUrl": meta.canonical_url, "publisher": meta.publisher,
                                           "observedSourceKind": meta.source_kind}
            day = publication["day"]
            if day is None:
                raise IngestionFailure("article_date_unknown" if publication["precision"] == "unknown" else "article_date_unresolved")
            if not config.from_day <= day <= config.through_day:
                raise IngestionFailure("article_outside_window")
            discovery_dates = {r["published_at"] for r in item["refs"] if r["published_at"]}
            if discovery_dates and any(_publication(value)["day"] != day for value in discovery_dates):
                raise IngestionFailure("article_discovery_date_conflict")
            if config.per_day_cap is not None and retained[day] >= config.per_day_cap:
                raise IngestionFailure("publication_day_cap")
            if prepared is None:
                prepared = prepare(response.body, "text/html", meta.article_xpath)
            declared = source_config[source]
            if extracted is not None:
                record = _retain_extracted(config, state, identifier, item, source, declared, meta, publication, extracted,
                                           response.robots if response is not None else list(fetcher._observed.values()))
                item.update(status="retained", publicationDay=day, textSha256=record["textSha256"],
                            literalAliasMatches=record["literalAliasMatches"], source=source)
                retained[day] += 1
                attempt["status"] = "retained"
                continue
            record = {"schemaVersion": "zoop-private-news-record-1", "privateId": identifier,
                      "provenance": _provenance(config),
                      "planDigest": data["planDigest"], "source": source, "discoveryRefs": item["refs"],
                      "requestUrl": response.requested_url, "finalUrl": response.final_url,
                      "canonicalUrl": meta.canonical_url, "redirects": response.redirects, "robots": response.robots,
                      "title": meta.title, "publication": publication, "publicationDay": day,
                      "observedAt": response.fetched_at, "publisher": meta.publisher,
                      "declaredSourceType": declared.source_type, "declaredReliability": declared.reliability,
                      "observedSourceKind": meta.source_kind, "articleXPath": meta.article_xpath,
                      "rawSha256": byte_hash(response.body), "rawBytes": len(response.body),
                      "textSha256": byte_hash(prepared["text"].encode()), "parserProfile": profile(meta.article_xpath),
                      "prepared": prepared, "literalAliasMatches": [alias for alias in config.company_aliases
                          if alias in meta.title or alias in prepared["text"]], **USE}
            _publish(state.fd, identifier + ".raw", response.body, immutable=True)
            _publish(state.fd, identifier + ".json", canonical(record).encode(), immutable=True)
            item.update(status="retained", publicationDay=day, textSha256=record["textSha256"],
                        literalAliasMatches=record["literalAliasMatches"], source=source)
            retained[day] += 1
            attempt["status"] = "retained"
        except IngestionFailure as exc:
            if getattr(exc, "native_observation", None) is not None:
                attempt["nativeObservation"] = exc.native_observation.wire()
            if getattr(exc, "provider_receipt", None) is not None:
                attempt["providerReceipt"] = exc.provider_receipt.wire()
            if exc.code in {"provider_unknown_no_retry", "provider_invalid_response"}:
                data["stopCode"] = exc.code
            if (exc.code in {"request_budget", "byte_budget"} or
                    exc.code == "timeout" and time.monotonic() >= fetcher.run_deadline):
                data["stopCode"] = exc.code
            deferred = config.paged and (
                exc.code in {"fallback_budget_live_set_work_exhausted", "fetch_pacing_deadline", "fallback_byte_budget"} or
                getattr(fetcher, "last_get_known_unsent", False) and exc.code in {"request_budget", "byte_budget", "timeout", "rate_limit"})
            if deferred:
                native = getattr(exc, "native_observation", None)
                if native is not None:
                    item["reusableNative"] = {**_retain_observation(state, native), "reason": exc.code}
                data["stopCode"] = ("timeout" if exc.code in {"rate_limit", "fetch_pacing_deadline"}
                                    else "byte_budget" if exc.code == "fallback_byte_budget" else exc.code)
            item.update(status="pending" if deferred else "refused", code=exc.code)
            attempt.update(status="deferred" if deferred else "refused", code=exc.code)
        finally:
            fetcher.article_source = None
            fetcher.article_refs = []
            state.save()


def summary(config, state):
    data = state.data
    partitions, task_states, dispositions, days, sources, domains = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    source_states = {source.name: {"partitions": 0, "traversedPartitions": 0, "inheritedTraversedPartitions": 0,
                                 "pendingPartitions": 0, "saturatedPartitions": 0, "retainedInWindow": 0,
                                 "inheritedRetainedInWindow": 0, "pendingCandidates": 0, "refusals": Counter()}
                     for source in config.sources}
    saturated = matched = retained = pending = inherited_done = inherited_retained = inherited_candidates = current_discovered = 0
    unknown = (data["unknownRequests"] > 0 or data.get("inheritedUnknownRequests", 0) > 0 or data["pendingRequest"] is not None
               or data.get("providerUnknownRequests", 0) > 0 or data.get("pendingProviderRequest") is not None)
    for task in data["tasks"].values():
        effective = task.get("inheritedStatus", task["status"]) if task["status"] == "inherited" else task["status"]
        task_states[task["status"]] += 1
        label = task.get("code", effective)
        partitions[("inherited:" if task["status"] == "inherited" else "") + label] += 1
        inherited_done += task["status"] == "inherited" and effective == "done"
        saturated += bool(task["saturated"])
        row = source_states[task["source"]]
        row["partitions"] += 1
        row["traversedPartitions"] += task["status"] == "done"
        row["inheritedTraversedPartitions"] += task["status"] == "inherited" and effective == "done"
        row["pendingPartitions"] += task["status"] == "pending"
        row["saturatedPartitions"] += bool(task["saturated"])
        if effective in {"refused", "unknown", "attempting"}:
            unknown = True
            row["refusals"][("inherited:" if task["status"] == "inherited" else "") + label] += 1
    duplicates = Counter()
    for item in data["candidates"].values():
        effective = item.get("inheritedStatus", item["status"]) if item["status"] == "inherited" else item["status"]
        label = item.get("code", effective)
        dispositions[("inherited:" if item["status"] == "inherited" else "") + label] += 1
        inherited_candidates += bool(item.get("fromPredecessor"))
        current_discovered += not item.get("fromPredecessor", False)
        row = source_states[item.get("source") or item["refs"][0]["source"]]
        pending += item["status"] == "pending"
        row["pendingCandidates"] += item["status"] == "pending"
        unknown |= effective in {"unknown", "attempting"}
        if item["status"] == "inherited" and effective == "retained":
            inherited_retained += 1
            row["inheritedRetainedInWindow"] += 1
        if item["status"] == "retained":
            retained += 1
            row["retainedInWindow"] += 1
            days[item["publicationDay"]] += 1
            sources[item["source"]] += 1
            domains[urlsplit(item["url"]).hostname] += 1
            matched += bool(item.get("literalAliasMatches"))
            if not config.paged:
                duplicates[item["textSha256"]] += 1
        elif effective not in {"pending", "retained"}:
            row["refusals"][("inherited:" if item["status"] == "inherited" else "") + label] += 1
    weeks = Counter()
    for day, count in days.items():
        year, week, _ = date.fromisoformat(day).isocalendar()
        weeks[f"{year:04d}-W{week:02d}"] += count
    total_tasks, total_items = len(data["tasks"]), len(data["candidates"])
    all_partitions = bool(total_tasks) and task_states["done"] + inherited_done == total_tasks and not saturated
    exhausted = all_partitions and not pending and not unknown
    coverage = "unknown" if unknown else ("all" if all_partitions and not pending and retained + inherited_retained == total_items else "some")
    duplicate_groups = (state.queue.execute("SELECT count(*) FROM (SELECT json_extract(value,'$.textSha256') "
                        "FROM candidates WHERE status='retained' GROUP BY json_extract(value,'$.textSha256') HAVING count(*)>1)").fetchone()[0]
                        if config.paged else sum(count > 1 for count in duplicates.values()))
    for row in source_states.values():
        row["refusals"] = dict(row["refusals"])
        row["queueDrained"] = not row["pendingPartitions"] and not row["pendingCandidates"]
        row["discoveryExhausted"] = row["partitions"] == row["traversedPartitions"] + row["inheritedTraversedPartitions"] and not row["saturatedPartitions"]
        row["discoveredCorpusExhausted"] = row["discoveryExhausted"] and row["queueDrained"] and not row["refusals"]
        row["state"] = ("blocked-or-refused" if row["refusals"] else "pending" if not row["queueDrained"]
                        else "partial-discovery" if row["saturatedPartitions"] else "discovered-corpus-complete")
    provider_outcomes, extraction_backends = Counter(), Counter()
    provider_known_cost = active_attempts = 0
    for attempt in data["attempts"]:
        active_attempts += attempt["status"] == "attempting"
        if attempt.get("extractionBackend"):
            extraction_backends[attempt["extractionBackend"]] += 1
        receipt = attempt.get("providerReceipt", {})
        outcome = attempt.get("providerOutcome") or receipt.get("outcome")
        if outcome:
            provider_outcomes[outcome] += 1
            actual = attempt.get("providerActualNano", receipt.get("actualNano"))
            if type(actual) is int:
                provider_known_cost += actual
    continuable = (config.paged and data["stopCode"] in RESOURCE_STOPS and (task_states["pending"] + pending) > 0
                   and data["pendingRequest"] is None and data.get("pendingProviderRequest") is None and not active_attempts
                   and not provider_outcomes["unknown"] and not provider_outcomes["invalid"])
    with os.scandir(state.fd) as entries:
        artifact_bytes = sum(entry.stat(follow_symlinks=False).st_size for entry in entries if entry.is_file(follow_symlinks=False))
    return {"schemaVersion": "zoop-private-news-summary-1", "planDigest": data["planDigest"],
            "provenance": _provenance(config), "fromDay": config.from_day, "throughDay": config.through_day,
            "state": "completed" if coverage == "all" else "partial", "coverage": coverage,
            "coverageMeaning": "configured discovery partitions and discovered candidates only; never whole-source completeness",
            "discoveredCorpusExhausted": exhausted, "selectionMode": config.selection_mode if config.paged else "v1-balanced",
            "sourceStates": source_states, "sourceRequests": data["requests"], "sourceBytes": data["bytes"],
            "unknownRequests": data["unknownRequests"], "unknownByteUpperBound": data["unknownByteUpperBound"],
            "stopCode": data["stopCode"], "partitions": total_tasks, "traversedPartitions": task_states["done"],
            "saturatedPartitions": saturated, "pendingPartitions": task_states["pending"],
            "partitionDispositions": dict(partitions), "candidates": total_items, "pendingCandidates": pending,
            "retainedInWindow": retained, "candidateDispositions": dict(dispositions),
            "currentRetainedInWindow": retained, "currentDiscoveredCandidates": current_discovered,
            "inheritedCandidates": inherited_candidates, "inheritedRetainedInWindow": inherited_retained,
            "inheritedTraversedPartitions": inherited_done, "continuationEligible": continuable,
            "inheritedSourceRequests": data.get("inheritedSourceRequests", 0),
            "inheritedUnknownRequests": data.get("inheritedUnknownRequests", 0),
            "dayCounts": dict(sorted(days.items())), "weekCounts": dict(sorted(weeks.items())),
            "sourceCounts": dict(sources), "domainCounts": dict(domains), "literalAliasMatchedRecords": matched,
            "exactTextDuplicateGroups": duplicate_groups,
            "providerOutcomeCounts": dict(provider_outcomes), "providerKnownCostNano": provider_known_cost,
            "providerBytes": data.get("providerBytes", 0),
            "providerUnknownByteUpperBound": data.get("providerUnknownByteUpperBound", 0),
            "providerUnknownRequests": data.get("providerUnknownRequests", 0),
            "pendingProviderRequest": data.get("pendingProviderRequest"), "artifactBytes": artifact_bytes,
            "byteAccountingMeaning": "HTTP response-body bytes, not TLS/headers/socket bytes; artifactBytes is measured logical file size, not a disk ceiling",
            "extractionBackendCounts": dict(extraction_backends),
            "providerAccountingMeaning": "observed receipts only; reconcile the monetary ledger, including unresolved reservations",
            "duplicateMeaning": "exact text only; not independent-source or same-event evidence", **USE}


def retained_items(config):
    """Stream exact immutable-record pins; no bodies or native-grant conversion."""
    state = State(config, "status")
    try:
        for identifier, item in state.data["candidates"].items():
            if item["status"] == "retained":
                raw = _read(state.fd, identifier + ".json")
                yield {"sourceId": item["source"], "stateDir": config.state_dir,
                       "recordPath": str(Path(config.state_dir) / (identifier + ".json")),
                       "recordSha256": byte_hash(raw), "privateId": identifier, "planId": config.plan_id}
    finally:
        state.close()


def run(config, command="run", control=NO_CONTROL):
    if command not in {"run", "resume", "status"}:
        raise IngestionFailure("private_command_invalid")
    state = State(config, command, control)
    try:
        if command == "status":
            return summary(config, state)
        if command == "run" and state.data["attempts"]:
            raise IngestionFailure("private_explicit_resume_required")
        state.recover()
        if state.data["stopCode"] not in HARD_STOPS:
            state.data["stopCode"] = None
        fetcher = PrivateFetcher(config, state)
        _discover(config, state, fetcher)
        _acquire(config, state, fetcher)
        state.save()
        return summary(config, state)
    finally:
        state.close()


def status(config):
    return run(config, "status")


def verify_record(record: dict, raw: bytes, *, extraction_raw: bytes | None = None,
                  causal_raw: bytes | None = None) -> dict:
    """Pure retained-record verification; no state, network, recovery or old-selector reinterpretation."""
    try:
        version = record["schemaVersion"]
        expected = (RECORD3_FIELDS if version == "zoop-private-news-record-3" else
                    RECORD2_FIELDS if version == "zoop-private-news-record-2" else RECORD_FIELDS)
        if version not in {"zoop-private-news-record-1", "zoop-private-news-record-2", "zoop-private-news-record-3"} or set(record) != expected:
            raise ValueError
        if (any(record[key] != value for key, value in USE.items()) or
                record["rawSha256"] != byte_hash(raw) or record["rawBytes"] != len(raw) or
                record["textSha256"] != byte_hash(record["prepared"]["text"].encode("utf-8"))):
            raise ValueError
        prepared = record["prepared"]
        text, end = prepared["text"], 0
        if not isinstance(text, str) or not text.strip() or not prepared["segments"]:
            raise ValueError
        for segment in prepared["segments"]:
            start, stop = segment["cleanStart"], segment["cleanEnd"]
            source = prepared["sources"][segment["sourceIndex"]]["text"]
            left, right = segment["sourceStart"], segment["sourceEnd"]
            if (not all(type(value) is int for value in (start, stop, left, right)) or
                    not end <= start < stop <= len(text) or not 0 <= left < right <= len(source) or
                    text[start:stop] != source[left:right] or text[end:start].strip()):
                raise ValueError
            end = stop
        if text[end:].strip() or record["publication"] != _publication(record["publication"]["raw"]):
            raise ValueError
        if record["publicationDay"] != record["publication"]["day"] or record["publicationDay"] is None:
            raise ValueError
        if version in {"zoop-private-news-record-2", "zoop-private-news-record-3"}:
            if extraction_raw is None:
                raise ValueError
            artifact = record["extractionArtifact"]
            if (set(artifact) != {"file", "sha256"} or
                    artifact["file"] != record["privateId"] + ".extraction.json" or
                    artifact["sha256"] != byte_hash(extraction_raw)):
                raise ValueError
            envelope = _json(extraction_raw)
            if (envelope["schemaVersion"] != "zoop-extracted-page-1" or
                    envelope["retainedText"].encode("utf-8") != raw or
                    envelope["rawSha256"] != record["rawSha256"] or
                    envelope["contentSha256"] != record["textSha256"] or
                    envelope["prepared"] != prepared or envelope["normalizationProfile"] != record["parserProfile"] or
                    envelope["backend"] != record["extractionBackend"] or envelope["format"] != record["representation"] or
                    envelope["requestedUrl"] != record["requestUrl"] or envelope["finalUrl"] != record["finalUrl"] or
                    envelope["metadata"]["title"] != record["title"] or envelope["metadata"]["publisher"] != record["publisher"]):
                raise ValueError
            from .extraction_fallback import verify_extracted_page
            native = envelope["nativeObservation"]
            if native.get("publicArticleRef") is not None:
                refs = {"discovery:" + digest(ref) for ref in record["discoveryRefs"]
                        if ref.get("url") == record["requestUrl"] and re.fullmatch(r"[0-9a-f]{64}", ref.get("listing", ""))}
                if native["publicArticleRef"] not in refs:
                    raise ValueError
            cause = native["knownUnsent"]
            if cause is not None:
                if (causal_raw is None or cause["receiptRef"] != "native-" + cause["receiptSha256"] + ".json"
                        or byte_hash(causal_raw) != cause["receiptSha256"]
                        or causal_raw != canonical(cause["observation"]).encode("utf-8")):
                    raise ValueError
            elif causal_raw is not None:
                raise ValueError
            urls = [record["requestUrl"], *native["redirects"], native["finalUrl"], envelope["finalUrl"]]
            hosts = tuple(sorted({urlsplit(url).hostname for url in urls if url is not None}))
            page = verify_extracted_page(envelope, allowed_hosts=hosts)
            if page.backend not in {"defuddle", "deepseek-fetch"}:
                raise ValueError
            if version == "zoop-private-news-record-3":
                from .publication_evidence import verify_publication
                publication = verify_publication(record["publicationEvidence"], record["source"], page)
            else:
                publication = (archives.markdown_publication(record["source"], page.retained_text)
                               if page.format == "markdown" else page.metadata.published_at)
            if (record["publication"] != _publication(publication) or record["observedAt"] != page.observed_at
                    or record["redirects"] != list(page.native_observation.redirects)
                    or record["articleXPath"] is not None or record["provenance"] != "private-public-web-extracted"):
                raise ValueError
            if page.backend == "deepseek-fetch" and record["canonicalUrl"] is not None:
                raise ValueError
        elif extraction_raw is not None or causal_raw is not None:
            raise ValueError
    except (KeyError, ValueError, TypeError, IndexError, AttributeError, UnicodeError) as exc:
        raise IngestionFailure("private_record_corrupt") from exc
    return record


def _pinned_json(path, expected):
    target = Path(path)
    fd = _directory(target.parent)
    try:
        raw = _read(fd, target.name)
    finally:
        os.close(fd)
    if len(raw) > 200_000 or byte_hash(raw) != expected:
        raise IngestionFailure("fallback_config_pin_mismatch")
    return _json(raw)


class _FundedFetch:
    """Lazy official-provider setup; no key read or budget operation for local extraction."""
    def __init__(self, config, fetcher):
        self.config, self.fetcher, self.client = config, fetcher, None

    def fetch(self, url):
        from .extraction_fallback import DeepSeekFetchClient
        from .fetch_pacing import SharedFetchPacer
        from .live_budget import Budget, BudgetError
        from .live_funding import FINISH_RESERVE_SECONDS, SEND_BEFORE_ENV, run_policy, timestamp
        from datetime import timedelta
        from .private_processing import Actor
        try:
            if self.client is None:
                fallback = self.config.fallback
                control = _pinned_json(fallback.budget_config_path, fallback.budget_config_sha256)
                proof = _pinned_json(fallback.set_proof_path, fallback.set_proof_sha256)
                template = self.config.wire()
                template.pop("fallback", None)
                try:
                    policy = run_policy(control)
                except ValueError:
                    raise IngestionFailure("fallback_admission_mismatch") from None
                if (Actor.model_validate(control["processingActor"]).wire() != control["processingActor"]
                        or proof.get("schemaVersion") != "zoop-acquisition-set-1"
                        or proof.get("setId") != fallback.set_id or proof.get("sourceId") != fallback.source_id
                        or proof.get("unitDigest") != digest(template)
                        or proof.get("allowance") != {"fetch": fallback.max_calls, "search": 0}
                        or os.environ.get("ZOOP_AI_PIPELINE_LIVE_SET_ID") != fallback.set_id):
                    raise IngestionFailure("fallback_admission_mismatch")
                if not FINISH_RESERVE_SECONDS + 300 < (timestamp(control["finishBy"]) - timestamp(control["admitUntil"])).total_seconds() <= 3600:
                    raise IngestionFailure("fallback_config_invalid")
                root = Path(control["root"])
                if not root.is_absolute() or str(root) != os.path.abspath(root):
                    raise IngestionFailure("fallback_config_invalid")
                directory = _directory(root / "modelbudget")
                try:
                    ledger = os.open("live-budget.sqlite3", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                    os.close(ledger)
                finally:
                    os.close(directory)
                budget = Budget(root / "modelbudget", policy["totalMaxNanoUsd"], control["maxCalls"],
                                funding=policy, bucket_caps=policy["bucketMaxNanoUsd"], finish_by=control["finishBy"])
                budget.resume_set(fallback.set_id, proof["unitDigest"])
                key = os.environ.get("DEEPSEEK_API_KEY")
                if not key:
                    raise IngestionFailure("fallback_missing_key")
                send_before = timestamp(control["finishBy"]) - timedelta(seconds=FINISH_RESERVE_SECONDS)
                if SEND_BEFORE_ENV in os.environ:
                    send_before = min(send_before, timestamp(os.environ[SEND_BEFORE_ENV]))
                self.client = DeepSeekFetchClient(api_key=key, budget=_FetchByteBudget(budget, self.config, self.fetcher.state),
                                                 set_id=fallback.set_id,
                                                 allowed_hosts=tuple(fallback.allowed_hosts),
                                                 pacer=SharedFetchPacer(root / "collection" / "fetch-pacing"),
                                                 min_interval_seconds=self.config.policy.min_interval_seconds,
                                                 max_response_bytes=self.config.policy.max_response_bytes,
                                                 send_before=send_before.strftime("%Y-%m-%dT%H:%M:%SZ"))
            host = urlsplit(url).hostname
            interval = max(self.config.policy.min_interval_seconds, self.fetcher._delay.get(host, 0.0))
            try:
                result = self.client.fetch(url, min_interval_seconds=interval,
                                           not_before_monotonic=self.fetcher._last.get(host, 0.0) + interval,
                                           deadline_monotonic=self.fetcher.run_deadline)
            except BaseException as exc:
                receipt = getattr(exc, "provider_receipt", None)
                if receipt is not None:
                    _account_provider(self.fetcher.state, receipt)
                elif self.fetcher.state.data.get("pendingProviderRequest") is not None:
                    _account_provider(self.fetcher.state, None)
                    if isinstance(exc, Exception):
                        raise IngestionFailure("provider_unknown_no_retry") from exc
                raise
            _account_provider(self.fetcher.state, result[2])
            return result
        except BudgetError as exc:
            raise IngestionFailure("fallback_budget_" + exc.code) from exc
        except (OSError, KeyError, ValueError, TypeError) as exc:
            raise IngestionFailure("fallback_configuration_invalid") from exc


def _fetch_article(config, fetcher, url, source, reusable=None):
    selected = archives._descriptor(source, _source_descriptor(config, source))
    if selected is not None and selected.body_policy == "native-pdf-intake-required":
        raise IngestionFailure("archive_pdf_native_intake_required")
    from .extraction_fallback import NativePageObservation, ObservedMetadata, _observation_from_wire, extract_page
    fetcher.native_response, fetcher.native_redirects, fetcher.last_get_known_unsent = None, [], False
    response, failure, meta, prepared, native = None, None, None, None, None
    if reusable is not None:
        actor_continuation = reusable.get("reason") == "fallback_admission_mismatch" and config.known_unsent is not None
        if not actor_continuation and reusable.get("reason") not in {
                "fallback_budget_live_set_work_exhausted", "fetch_pacing_deadline", "fallback_byte_budget"}:
            raise IngestionFailure("private_native_reuse_invalid")
        if (not re.fullmatch(r"native-[0-9a-f]{64}\.json", reusable["file"])
                or reusable["file"] != "native-" + reusable["sha256"] + ".json"):
            raise IngestionFailure("private_native_reuse_invalid")
        raw = _read(fetcher.state.fd, reusable["file"])
        if byte_hash(raw) != reusable["sha256"]:
            raise IngestionFailure("private_native_reuse_invalid")
        native = _observation_from_wire(_json(raw))
        if native.requested_url != url or canonical(native.wire()).encode("utf-8") != raw:
            raise IngestionFailure("private_native_reuse_invalid")
        if actor_continuation:
            from .private_continuation import eligible_native
            eligible_native(native.wire(), url)
            fetcher._guard(url)
            if not fetcher._rules(url, min(fetcher.run_deadline, time.monotonic() + config.policy.timeout_seconds)).permits(url):
                raise IngestionFailure("robots_denied")
        if native.http_status == 200 and native.body is not None:
            meta = archives.article_metadata(source, native.body, native.final_url,
                                             descriptor=_source_descriptor(config, source), require_body=False)
    else:
        try:
            response = fetcher.fetch(url)
        except IngestionFailure as exc:
            if not config.paged or exc.code not in {"http_403", "http_404", "host_blocked"} or config.fallback is None and exc.code != "http_403":
                raise
            failure = exc.code
        if response is not None:
            meta = archives.article_metadata(source, response.body, response.final_url,
                                             synthetic_origin=config.synthetic_base_url,
                                             descriptor=_source_descriptor(config, source), require_body=not config.paged)
            if not config.paged:
                return response, meta, None, None
            try:
                prepared = prepare(response.body, "text/html", meta.article_xpath)
                return response, meta, prepared, None
            except IngestionFailure as exc:
                if config.policy.synthetic_loopback:
                    raise
                failure = exc.code
        observed = fetcher.native_response
        if failure == "host_blocked":
            native = _known_unsent_observation(fetcher, url)
        else:
            if observed is None:
                raise IngestionFailure(failure or "native_unknown_no_retry")
            public_evidence = _public_article_fields(fetcher, url)
            native = NativePageObservation(requested_url=url, final_url=observed["url"],
                                           observed_at=observed["observedAt"], http_status=observed["status"],
                                           media_type=observed["mediaType"], body=observed["body"], failure_code=failure,
                                           access=("auth" if observed["wwwAuthenticate"] else
                                                   "unknown" if observed.get("challenge") and not public_evidence else "public"),
                                           www_authenticate=observed["wwwAuthenticate"], redirects=tuple(fetcher.native_redirects),
                                           **public_evidence)
            if native.http_status == 403 and native.access == "public":
                _retain_client403(fetcher, native)
        if failure is not None and config.fallback is None:
            from .extraction_fallback import ExtractionFallbackFailure
            raise ExtractionFallbackFailure(failure, native=native)
    metadata = ObservedMetadata(title=meta.title, published_at=meta.published_at, publisher=meta.publisher) if meta else ObservedMetadata()
    if config.fallback is not None and not hasattr(fetcher, "fallback_provider"):
        fetcher.fallback_provider = _FundedFetch(config, fetcher)
    extracted = extract_page(native, allowed_hosts=tuple(config.exact_article_hosts),
                             article_xpath=meta.article_xpath if meta else None, metadata=metadata,
                             provider=getattr(fetcher, "fallback_provider", None))
    if extracted.backend == "native":
        if reusable is not None:
            raise IngestionFailure("private_native_reuse_invalid")
        return response, meta, extracted.prepared, None
    if extracted.format == "markdown":
        meta = archives.ArticleMeta(extracted.metadata.title, None, None, None,
                                    extracted.metadata.publisher, selected.category if selected else "unknown")
    else:
        meta = replace(meta, article_xpath=None)
    return response, meta, extracted.prepared, extracted


def _retain_extracted(config, state, identifier, item, source, declared, meta, publication, extracted, robots):
    raw = extracted.retained_text.encode("utf-8")
    envelope_raw = canonical(extracted.wire()).encode("utf-8")
    artifact = {"file": identifier + ".extraction.json", "sha256": byte_hash(envelope_raw)}
    prepared = extracted.prepared
    native = extracted.native_observation
    record = {"schemaVersion": "zoop-private-news-record-2", "privateId": identifier,
              "provenance": "private-public-web-extracted", "planDigest": state.data["planDigest"],
              "source": source, "discoveryRefs": item["refs"], "requestUrl": extracted.requested_url,
              "finalUrl": extracted.final_url, "canonicalUrl": meta.canonical_url,
              "redirects": list(native.redirects), "robots": robots,
              "title": meta.title, "publication": publication, "publicationDay": publication["day"],
              "observedAt": extracted.observed_at, "publisher": meta.publisher,
              "declaredSourceType": declared.source_type, "declaredReliability": declared.reliability,
              "observedSourceKind": meta.source_kind, "articleXPath": None,
              "rawSha256": byte_hash(raw), "rawBytes": len(raw),
              "textSha256": byte_hash(prepared["text"].encode("utf-8")), "parserProfile": extracted.normalization_profile,
              "prepared": prepared, "literalAliasMatches": [alias for alias in config.company_aliases
                  if alias in meta.title or alias in prepared["text"]],
              "extractionArtifact": artifact, "extractionBackend": extracted.backend,
              "representation": extracted.format, **USE}
    if extracted.format == "markdown":
        from .publication_evidence import publication_evidence
        record["schemaVersion"] = "zoop-private-news-record-3"
        record["publicationEvidence"] = publication_evidence(source, extracted, descriptor=declared.descriptor)
    verify_record(record, raw, extraction_raw=envelope_raw, causal_raw=_causal_bytes(state, extracted.wire()))
    if state.exists(artifact["file"]):
        if _read(state.fd, artifact["file"]) != envelope_raw:
            raise IngestionFailure("private_record_corrupt")
    else:
        _publish(state.fd, artifact["file"], envelope_raw, immutable=True)
    _publish(state.fd, identifier + ".raw", raw, immutable=True)
    _publish(state.fd, identifier + ".json", canonical(record).encode(), immutable=True)
    return record


def _retain_client403(fetcher, observation):
    pin = _retain_observation(fetcher.state, observation)
    parts = urlsplit(observation.requested_url)
    fetcher.state.data.setdefault("client403", {})[f"{parts.scheme}://{parts.netloc}"] = pin
    fetcher.state.save()


def _known_unsent_observation(fetcher, url):
    from .extraction_fallback import NativePageObservation, PriorPublicClient403, _observation_from_wire
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    pin = fetcher.state.data.get("client403", {}).get(origin)
    rules = fetcher._robots.get(origin)
    observed_at = fetcher.robots_observed_at.get(origin)
    if pin is None or rules is None or isinstance(rules, IngestionFailure) or not rules.permits(url) or not observed_at:
        raise IngestionFailure("host_blocked")
    raw = _read(fetcher.state.fd, pin["file"])
    if byte_hash(raw) != pin["sha256"]:
        raise IngestionFailure("private_state_corrupt")
    value = _json(raw)
    prior = _observation_from_wire(value)
    if prior.wire() != value:
        raise IngestionFailure("private_state_corrupt")
    proof = PriorPublicClient403(prior, pin["file"], pin["sha256"], url, observed_at)
    return NativePageObservation(url, now(), None, failure_code="host_blocked", access="public",
                                 known_unsent=proof, **_public_article_fields(fetcher, url))


def _causal_bytes(state, envelope):
    cause = envelope["nativeObservation"]["knownUnsent"]
    if cause is None:
        return None
    filename = cause["receiptRef"]
    if not re.fullmatch(r"native-[0-9a-f]{64}\.json", filename):
        raise IngestionFailure("private_record_corrupt")
    return _read(state.fd, filename)


def _continuation_scope(config):
    value = config.wire()
    for field in ("planId", "stateDir", "fallback", "predecessor", "selectionMode"):
        value.pop(field, None)
    for field in ("maxRequests", "maxTotalBytes", "maxTotalSeconds"):
        value["policy"].pop(field, None)
    return value


def _hash_file(directory, filename):
    child = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        if not stat.S_ISREG(os.fstat(child).st_mode):
            raise IngestionFailure("private_predecessor_invalid")
        result = hashlib.sha256()
        with os.fdopen(child, "rb", closefd=False) as stream:
            while chunk := stream.read(524_288):
                result.update(chunk)
        return result.hexdigest()
    finally:
        os.close(child)


def _seed_predecessor(state):
    """Copy only queue metadata into a new plan; the predecessor is never writable."""
    pin = state.config.predecessor
    directory, lock, connection = _directory(pin.state_dir), None, None
    try:
        lock = os.open(".lock", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise IngestionFailure("private_predecessor_busy") from None
        for name in ("QUEUE.sqlite3-journal", "QUEUE.sqlite3-wal", "QUEUE.sqlite3-shm"):
            try:
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise IngestionFailure("private_predecessor_unsettled")
        plan_raw, state_raw = _read(directory, "PLAN.json"), _read(directory, "STATE.json")
        if (byte_hash(plan_raw) != pin.plan_sha256 or byte_hash(state_raw) != pin.state_sha256
                or _hash_file(directory, "QUEUE.sqlite3") != pin.queue_sha256):
            raise IngestionFailure("private_predecessor_pin_mismatch")
        plan, snapshot = _json(plan_raw), _json(state_raw)
        previous = Config.model_validate(plan["config"])
        if (not previous.paged or previous.state_dir != pin.state_dir
                or previous.plan_id == state.config.plan_id
                or previous.selection_mode != state.config.selection_mode and
                   (previous.selection_mode, state.config.selection_mode) != ("fresh-first", "backfill")
                or _continuation_scope(previous) != _continuation_scope(state.config)):
            raise IngestionFailure("private_predecessor_scope_mismatch")
        data = snapshot["state"]
        if (set(snapshot) != {"state", "sha256"} or snapshot["sha256"] != digest(data)
                or data["planDigest"] != digest(plan)
                or any(data.get(name) != "sqlite:" + name for name in ("tasks", "candidates", "attempts"))):
            raise IngestionFailure("private_predecessor_invalid")
        if data["pendingRequest"] is not None or data.get("pendingProviderRequest") is not None:
            raise IngestionFailure("private_predecessor_unsettled")
        if data["stopCode"] not in {"request_budget", "byte_budget", "timeout", "fallback_budget_live_set_work_exhausted"}:
            raise IngestionFailure("private_predecessor_not_continuable")
        connection = sqlite3.connect((Path(pin.state_dir) / "QUEUE.sqlite3").as_uri() + "?mode=ro&immutable=1", uri=True)
        if connection.execute("SELECT digest FROM binding").fetchall() != [(data["planDigest"],)]:
            raise IngestionFailure("private_predecessor_invalid")
        if any(connection.execute(f"SELECT 1 FROM {table} WHERE status='attempting' LIMIT 1").fetchone()
               for table in ("tasks", "candidates", "attempts")):
            raise IngestionFailure("private_predecessor_unsettled")
        pending = sum(connection.execute(f"SELECT count(*) FROM {table} WHERE status='pending'").fetchone()[0]
                      for table in ("tasks", "candidates"))
        if not pending:
            raise IngestionFailure("private_predecessor_not_continuable")
        for key, row in _QueueMap(connection, "tasks").items():
            value = dict(row)
            value["fromPredecessor"] = True
            if value.get("inheritedStatus", value["status"]) == "done":
                value.setdefault("evidenceStateDir", pin.state_dir)
            if value["status"] != "pending":
                value["inheritedStatus"] = value.get("inheritedStatus", value["status"])
                value["status"] = "inherited"
            state.data["tasks"][key] = value
        for key, row in _QueueMap(connection, "candidates").items():
            value = dict(row)
            value["fromPredecessor"] = True
            if value["status"] != "pending":
                value["inheritedStatus"] = value.get("inheritedStatus", value["status"])
                value["status"] = "inherited"
            new_key = "private-news-" + digest([state.config.plan_id, value["url"]])
            state.data["candidates"][new_key] = value
            if value.get("reusableNative"):
                _copy_pin(directory, state, value["reusableNative"])
        state.data["blocked"] = list(data["blocked"])
        state.data["delays"] = dict(data["delays"])
        state.data["inheritedSourceRequests"] = data["requests"] + data.get("inheritedSourceRequests", 0)
        state.data["inheritedUnknownRequests"] = data["unknownRequests"] + data.get("inheritedUnknownRequests", 0)
        for field in ("client403", "robotsFacts"):
            state.data[field] = data.get(field, {})
            for fact in state.data[field].values():
                _copy_pin(directory, state, fact)
    except (sqlite3.DatabaseError, OSError, ValueError, KeyError, TypeError) as exc:
        raise IngestionFailure("private_predecessor_invalid") from exc
    finally:
        if connection is not None:
            connection.close()
        if lock is not None:
            os.close(lock)
        os.close(directory)


def _copy_pin(directory, state, pin):
    if not re.fullmatch(r"(?:native-[0-9a-f]{64}\.json|robots-[0-9a-f]{64}\.raw)", pin["file"]):
        raise IngestionFailure("private_predecessor_invalid")
    raw = _read(directory, pin["file"])
    if byte_hash(raw) != pin["sha256"]:
        raise IngestionFailure("private_predecessor_pin_mismatch")
    if not state.exists(pin["file"]):
        _publish(state.fd, pin["file"], raw, immutable=True)


def _retain_observation(state, observation):
    raw = canonical(observation.wire()).encode("utf-8")
    pin = {"file": "native-" + byte_hash(raw) + ".json", "sha256": byte_hash(raw)}
    if not state.exists(pin["file"]):
        _publish(state.fd, pin["file"], raw, immutable=True)
    return pin


def public_client403_hosts(state):
    """Classify pinned public-client failures; this never unblocks native transport."""
    from .extraction_fallback import _observation_from_wire, guard_public_url
    if state.config.policy.synthetic_loopback:
        return ()
    hosts = set()
    for origin, pin in state.data.get("client403", {}).items():
        fact = state.data.get("robotsFacts", {}).get(origin)
        if fact is None or fact.get("code") or fact["status"] not in {200, 404}:
            continue
        raw = _read(state.fd, pin["file"])
        if byte_hash(raw) != pin["sha256"] or pin["file"] != "native-" + pin["sha256"] + ".json":
            raise IngestionFailure("private_state_corrupt")
        prior = _observation_from_wire(_json(raw))
        if (prior.http_status != 403 or prior.failure_code != "http_403" or prior.access != "public"
                or prior.www_authenticate or prior.known_unsent is not None or prior.body is not None):
            continue
        urls = [prior.requested_url, *prior.redirects, *([prior.final_url] if prior.final_url else [])]
        if any(f"{urlsplit(url).scheme}://{urlsplit(url).netloc}" != origin for url in urls):
            continue
        guard_public_url(prior.requested_url, tuple(state.config.exact_article_hosts))
        robot_raw = _read(state.fd, fact["file"])
        if byte_hash(robot_raw) != fact["sha256"]:
            raise IngestionFailure("private_state_corrupt")
        if fact["status"] == 200:
            parse_robots(robot_raw, state.config.policy.user_agent)
        hosts.add(urlsplit(origin).hostname)
    return tuple(sorted(hosts))


def _provider_bytes(state):
    return state.data.get("providerBytes", 0) + state.data.get("providerUnknownByteUpperBound", 0)


class _FetchByteBudget:
    """Add response-body admission/journaling without changing monetary policy."""
    def __init__(self, budget, config, state):
        self.budget, self.config, self.state = budget, config, state

    def reserve(self, *args, **kwargs):
        data = self.state.data
        if data.get("pendingProviderRequest") is not None:
            raise IngestionFailure("provider_unknown_no_retry")
        used = data["bytes"] + data["unknownByteUpperBound"] + _provider_bytes(self.state)
        if used + self.config.policy.max_response_bytes > self.config.policy.max_total_bytes:
            raise IngestionFailure("fallback_byte_budget")
        return self.budget.reserve(*args, **kwargs)

    def check_send(self, attempt_id):
        result = self.budget.check_send(attempt_id)
        self.state.data["pendingProviderRequest"] = {
            "attemptId": attempt_id, "byteUpperBound": self.config.policy.max_response_bytes, "startedAt": now()}
        self.state.save()
        return result

    def settle(self, *args, **kwargs):
        return self.budget.settle(*args, **kwargs)

    def release(self, *args, **kwargs):
        return self.budget.release(*args, **kwargs)


def _account_provider(state, receipt):
    data = state.data
    pending = data.get("pendingProviderRequest")
    if receipt is not None:
        wire = receipt.wire()
        received = wire["receivedBytes"]
        data["providerBytes"] = data.get("providerBytes", 0) + received
        unknown = receipt.outcome in {"unknown", "invalid"}
        limit = wire["responseByteLimit"] if receipt.raw_response is None else received
    else:
        received, unknown = 0, True
        limit = pending["byteUpperBound"]
    if unknown:
        data["providerUnknownRequests"] = data.get("providerUnknownRequests", 0) + 1
        data["providerUnknownByteUpperBound"] = data.get("providerUnknownByteUpperBound", 0) + max(0, limit - received)
        data["stopCode"] = "provider_unknown_no_retry"
    data["pendingProviderRequest"] = None
    state.save()


def _public_article_fields(fetcher, url):
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    rules = fetcher._robots.get(origin)
    observed = fetcher.robots_observed_at.get(origin)
    if not isinstance(rules, Rules) or not rules.permits(url) or not observed:
        return {}
    for reference in getattr(fetcher, "article_refs", ()):
        if (reference.get("url") == url and
                re.fullmatch(r"[0-9a-f]{64}", reference.get("listing", "")) and
                _verified_discovery_reference(fetcher.state, reference)):
            return {"public_article_ref": "discovery:" + digest(reference),
                    "robots_allowed_url": url, "robots_observed_at": observed}
    return {}


def _verified_discovery_reference(state, reference):
    task = state.data["tasks"].get(reference["listing"])
    if (task is None or task.get("inheritedStatus", task["status"]) != "done"
            or task["source"] != reference.get("source") or task["task"]["from_day"] != reference.get("partitionDay")):
        return False
    root = task.get("evidenceStateDir", state.config.state_dir)
    directory = state.fd if root == state.config.state_dir else _directory(root)
    try:
        try:
            evidence = _json(_read(directory, "listing-" + reference["listing"] + ".json"))
        except FileNotFoundError:
            return False
    finally:
        if directory != state.fd:
            os.close(directory)
    if digest(evidence) != task["listingDigest"] or evidence.get("source") != reference["source"]:
        raise IngestionFailure("private_state_corrupt")
    fields = ("url", "title", "published_at", "discovery_seen_at", "archive_day")
    return any(all(candidate.get(field) == reference.get(field) for field in fields)
               for candidate in evidence["candidates"])
