"""Finite, operator-bound private news acquisition. Never a native grant or ingestion input."""
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import time
import uuid
from collections import Counter, defaultdict, deque
from dataclasses import asdict, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from pydantic import Field, model_validator

from .collection import Fetcher
from .collection_contracts import Policy
from .ingestion_contracts import IngestionFailure, Wire, byte_hash, canonical, digest, now, reserved_state_roots
from .ingestion_parsers import prepare, profile
from .ingestion_url import canonical_url
from . import news_archives as archives

MAX_FILE = 64_000_000
USE = {"rights": "unconfirmed", "modelSend": False, "publicUse": False,
       "usage": "private-local-experiment-only; no redistribution or external model transmission"}
RECORD_FIELDS = frozenset(("schemaVersion privateId provenance planDigest source discoveryRefs requestUrl finalUrl "
                          "canonicalUrl redirects robots title publication publicationDay observedAt publisher "
                          "declaredSourceType declaredReliability observedSourceKind articleXPath rawSha256 rawBytes "
                          "textSha256 parserProfile prepared literalAliasMatches rights modelSend publicUse usage").split())
ENGLISH_MONTHS = {name: month for month, name in enumerate(
    ("January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"), 1)}


class PrivatePolicy(Policy):
    max_requests: int = Field(ge=1, le=20_000)
    max_total_seconds: int = Field(ge=1, le=86_400)


class Source(Wire):
    name: str = Field(min_length=1, max_length=100)
    source_type: Literal["editorial", "corporate-pr", "government", "discovery", "unknown"]
    reliability: str = Field(min_length=1, max_length=200)
    queries: list[str] = Field(max_length=50)


class Config(Wire):
    schema_version: Literal["zoop-private-news-config-1"]
    plan_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
    state_dir: str
    from_day: str
    through_day: str
    operator_approval_ref: str = Field(min_length=1, max_length=1000)
    sources: list[Source] = Field(min_length=1, max_length=20)
    exact_article_hosts: list[str] = Field(min_length=1, max_length=100)
    policy: PrivatePolicy
    max_listing_pages: int = Field(ge=1, le=10_000)
    max_candidates: int = Field(ge=1, le=100_000)
    max_documents: int = Field(ge=1, le=10_000)
    max_article_attempts: int = Field(ge=1, le=100_000)
    per_day_cap: int = Field(ge=1, le=1000)
    company_aliases: list[str] = Field(default_factory=list, max_length=200)
    synthetic_base_url: str | None = None

    @model_validator(mode="after")
    def bounded(self):
        if (date.fromisoformat(self.from_day).isoformat() != self.from_day or
                date.fromisoformat(self.through_day).isoformat() != self.through_day or
                self.from_day > self.through_day or
                (date.fromisoformat(self.through_day) - date.fromisoformat(self.from_day)).days >= 366):
            raise ValueError("bounded calendar window required")
        if not Path(self.state_dir).is_absolute() or os.path.abspath(self.state_dir) != self.state_dir:
            raise ValueError("absolute canonical state path required")
        if len({s.name for s in self.sources}) != len(self.sources):
            raise ValueError("duplicate source")
        for source in self.sources:
            archives.source_hosts(source.name)
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
        if self.max_documents > self.max_article_attempts or self.max_article_attempts > self.max_candidates:
            raise ValueError("document/attempt/candidate caps must be ordered")
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
                                   synthetic_origin=self.synthetic_base_url)
        return self


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
            "parserProfile": profile(), "engine": "private-news-1", "provenance": _provenance(config), **USE}


def _task_url(config, task):
    if config.synthetic_base_url:
        parts = urlsplit(task.url)
        task = replace(task, url=config.synthetic_base_url + urlunsplit(("", "", parts.path, parts.query, "")))
    return task


class State:
    """Descriptor-relative owned namespace; an immutable plan precedes every mutable snapshot."""
    def __init__(self, config, command):
        self.config, self.fd, self.lock = config, None, None
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
            if fresh:
                tasks = {}
                for source in config.sources:
                    for task in archives.initial_tasks(source.name, config.from_day, config.through_day, tuple(source.queries)):
                        task = _task_url(config, task)
                        key = digest([source.name, task.key])
                        tasks[key] = {"source": source.name, "task": asdict(task), "status": "pending", "saturated": False}
                self.data = {"schemaVersion": "zoop-private-news-state-1", "planDigest": digest(_binding(config)),
                             "startedAt": now(), "requests": 0, "bytes": 0, "unknownRequests": 0,
                             "unknownByteUpperBound": 0, "pendingRequest": None, "blocked": [], "delays": {},
                             "tasks": tasks, "candidates": {}, "attempts": [], "stopCode": None}
                _publish(self.fd, "PLAN.json", canonical(_binding(config)).encode(), immutable=True)
                self.save()
            else:
                envelope = _json(_read(self.fd, "STATE.json"))
                self.data = envelope["state"]
                if set(envelope) != {"state", "sha256"} or envelope["sha256"] != digest(self.data):
                    raise IngestionFailure("private_state_corrupt")
            self._validate_namespace()
            self._validate_state()
        except BaseException:
            self.close()
            raise

    def _validate_namespace(self):
        entries = os.listdir(self.fd)
        inode_counts = Counter((os.stat(name, dir_fd=self.fd, follow_symlinks=False).st_dev,
                                os.stat(name, dir_fd=self.fd, follow_symlinks=False).st_ino) for name in entries)
        for name in entries:
            if name not in {"PLAN.json", "STATE.json", ".lock"} and not re.fullmatch(
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
        datetime.fromisoformat(data["startedAt"])
        names = set(os.listdir(self.fd))
        expected = {"PLAN.json", "STATE.json", ".lock"}
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
            if identifier + ".json" in os.listdir(self.fd):
                self.record(identifier)
            elif item["status"] == "retained":
                raise IngestionFailure("private_record_missing")
        if any(name not in expected and not name.startswith(".stage-") for name in names):
            raise IngestionFailure("private_namespace_conflict")

    def record(self, identifier):
        record = _json(_read(self.fd, identifier + ".json"))
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
                                         synthetic_origin=self.config.synthetic_base_url)
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
        _publish(self.fd, "STATE.json", canonical({"state": self.data, "sha256": digest(self.data)}).encode())

    def recover(self):
        data = self.data
        if data["pendingRequest"] is not None:
            data["unknownRequests"] += 1
            data["unknownByteUpperBound"] += data["pendingRequest"]["byteUpperBound"]
            data["blocked"] = sorted(set(data["blocked"]) | {data["pendingRequest"]["host"]})
            data["pendingRequest"] = None
        names = set(os.listdir(self.fd))
        for key, task in data["tasks"].items():
            if task["status"] == "attempting":
                task["status"] = "unknown"
                task["code"] = "unsettled_discovery_no_retry"
        for identifier, item in data["candidates"].items():
            if item["status"] == "attempting":
                if identifier + ".json" in names:
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
        self.discovery_task_url = None
        policy = _Policy(config.policy)
        hosts = set(config.exact_article_hosts)
        hosts.update(h for source in config.sources for h in archives.source_hosts(source.name))
        if config.synthetic_base_url:
            hosts = {"127.0.0.1"}
        super().__init__(policy, sorted(hosts), authority_guard=self._intent)
        self.requests = state.data["requests"] + state.data["unknownRequests"]
        self.downloaded = state.data["bytes"] + state.data["unknownByteUpperBound"]
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(state.data["startedAt"])).total_seconds()
        self.run_deadline = time.monotonic() + max(0, config.policy.max_total_seconds - max(0, elapsed))
        self._blocked.update(state.data["blocked"])
        self._delay.update(state.data["delays"])
        for host in hosts:
            self._last[host] = time.monotonic()

    def _guard(self, value):
        url, host = super()._guard(value)
        parts = urlsplit(url)
        if self.config.synthetic_base_url and f"{parts.scheme}://{parts.netloc}" != self.config.synthetic_base_url:
            raise IngestionFailure("private_synthetic_origin_invalid")
        if self.discovery_source:
            if parts.path != "/robots.txt":
                archives.validate_discovery_url(self.discovery_source, url, synthetic_origin=self.config.synthetic_base_url)
                expected = urlsplit(self.discovery_task_url)
                if (parts.path != expected.path or
                        sorted(parse_qsl(parts.query)) != sorted(parse_qsl(expected.query))):
                    raise IngestionFailure("archive_endpoint_invalid")
            elif parts.query:
                raise IngestionFailure("archive_endpoint_invalid")
            if not self.config.synthetic_base_url and host not in archives.source_hosts(self.discovery_source):
                raise IngestionFailure("archive_endpoint_invalid")
        elif host not in self.config.exact_article_hosts:
            raise IngestionFailure("article_host_not_allowed")
        return url, host

    def _intent(self):
        self.state.data["pendingRequest"] = {"host": self._request_host,
            "byteUpperBound": max(0, self.policy.max_total_bytes - self.downloaded), "startedAt": now()}
        self.state.save()

    def _get(self, url, host, deadline, limit):
        self._request_host = host
        before_requests, before_bytes = self.requests, self.downloaded
        try:
            return super()._get(url, host, deadline, limit)
        finally:
            data = self.state.data
            data["requests"] += self.requests - before_requests
            data["bytes"] += self.downloaded - before_bytes
            data["pendingRequest"] = None
            data["blocked"] = sorted(self._blocked)
            data["delays"] = dict(self._delay)
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
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2})?", value):
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
    state.data["attempts"].append(entry)
    return entry


def _budget(state, fetcher):
    if state.data["stopCode"] in {"request_budget", "byte_budget", "timeout"}:
        return True
    if fetcher.requests >= fetcher.policy.max_requests:
        state.data["stopCode"] = "request_budget"
    elif fetcher.downloaded >= fetcher.policy.max_total_bytes:
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
    day_rank = {day: index for index, day in enumerate(_balanced_days(
        item["task"]["from_day"] for item in data["tasks"].values()))}
    while True:
        pending = [key for key, item in data["tasks"].items() if item["status"] == "pending"]
        if not pending:
            break
        key = min(pending, key=lambda k: (day_rank.get(data["tasks"][k]["task"]["from_day"], len(day_rank)),
                                         data["tasks"][k]["source"], k))
        item = data["tasks"][key]
        if _budget(state, fetcher):
            break
        if sum(t["status"] != "pending" for t in data["tasks"].values()) >= config.max_listing_pages:
            data["stopCode"] = "listing_page_cap"
            break
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
                                             synthetic_origin=config.synthetic_base_url)
            evidence = {"schemaVersion": "zoop-private-news-discovery-1", "source": item["source"],
                        "task": item["task"], "requestUrl": response.requested_url, "finalUrl": response.final_url,
                        "provenance": _provenance(config),
                        "observedAt": response.fetched_at, "rawSha256": byte_hash(response.body),
                        "candidates": [asdict(c) for c in listing.candidates], "saturated": listing.saturated,
                        "nextTasks": [asdict(t) for t in listing.next_tasks]}
            _publish(state.fd, "listing-" + key + ".raw", response.body, immutable=True)
            _publish(state.fd, "listing-" + key + ".json", canonical(evidence).encode(), immutable=True)
            item.update(status="done", saturated=listing.saturated, listingDigest=digest(evidence))
            for candidate in listing.candidates:
                url = candidate.url
                identifier = "private-news-" + digest([config.plan_id, url])
                current = data["candidates"].setdefault(identifier, {"url": url, "status": "pending", "refs": []})
                current["refs"].append({"source": item["source"], "listing": key,
                                        "partitionDay": task.from_day, **asdict(candidate)})
            for following in listing.next_tasks:
                following = _task_url(config, following)
                following_key = digest([item["source"], following.key])
                data["tasks"].setdefault(following_key, {"source": item["source"], "task": asdict(following),
                                                       "status": "pending", "saturated": False})
            attempt["status"] = "done"
        except IngestionFailure as exc:
            if (exc.code in {"request_budget", "byte_budget"} or
                    exc.code == "timeout" and time.monotonic() >= fetcher.run_deadline):
                data["stopCode"] = exc.code
            item.update(status="refused", code=exc.code)
            attempt.update(status="refused", code=exc.code)
        finally:
            fetcher.discovery_source = None
            fetcher.policy.allowed_media_types = ("text/html",)
            state.save()
    # Body admission begins only after discovery; all excess discoveries remain pending.


def _selection(state):
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
    retained = Counter(item.get("publicationDay") for item in data["candidates"].values() if item["status"] == "retained")
    source_config = {source.name: source for source in config.sources}
    admitted = sum(item["status"] != "pending" for item in data["candidates"].values())
    for identifier in _selection(state):
        if _budget(state, fetcher):
            break
        if admitted >= config.max_candidates:
            data["stopCode"] = "candidate_cap"
            break
        if sum(retained.values()) >= config.max_documents:
            data["stopCode"] = "document_cap"
            break
        if sum(a["kind"] == "article" for a in data["attempts"]) >= config.max_article_attempts:
            data["stopCode"] = "article_attempt_cap"
            break
        item = data["candidates"][identifier]
        admitted += 1
        if urlsplit(item["url"]).hostname not in config.exact_article_hosts:
            item.update(status="refused", code="article_host_not_allowed")
            state.save()
            continue
        item["status"] = "attempting"
        attempt = _attempt(state, "article", identifier)
        state.save()
        try:
            response = fetcher.fetch(item["url"])
            attempt["response"] = {"requestUrl": response.requested_url, "finalUrl": response.final_url,
                                   "observedAt": response.fetched_at, "rawSha256": byte_hash(response.body),
                                   "rawBytes": len(response.body), "mediaType": response.media_type}
            specific_sources = sorted({ref["source"] for ref in item["refs"]
                                       if ref["source"] != "gdelt-doc" and ref["source"] in source_config})
            source = specific_sources[0] if specific_sources else item["refs"][0]["source"]
            meta = archives.article_metadata(source, response.body, response.final_url,
                                             synthetic_origin=config.synthetic_base_url)
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
            if retained[day] >= config.per_day_cap:
                raise IngestionFailure("publication_day_cap")
            prepared = prepare(response.body, "text/html", meta.article_xpath)
            declared = source_config[source]
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
            if (exc.code in {"request_budget", "byte_budget"} or
                    exc.code == "timeout" and time.monotonic() >= fetcher.run_deadline):
                data["stopCode"] = exc.code
            item.update(status="refused", code=exc.code)
            attempt.update(status="refused", code=exc.code)
        finally:
            state.save()


def summary(config, state):
    data = state.data
    tasks = list(data["tasks"].values())
    items = list(data["candidates"].values())
    retained = [item for item in items if item["status"] == "retained"]
    days = Counter(item["publicationDay"] for item in retained)
    weeks = Counter()
    for day, count in days.items():
        year, week, _ = date.fromisoformat(day).isocalendar()
        weeks[f"{year:04d}-W{week:02d}"] += count
    dispositions = Counter(item.get("code", item["status"]) for item in items)
    pending = sum(item["status"] == "pending" for item in items)
    all_partitions = bool(tasks) and all(t["status"] == "done" and not t["saturated"] for t in tasks)
    unknown = (any(t["status"] in {"unknown", "refused", "attempting"} for t in tasks) or
               any(i["status"] in {"unknown", "attempting"} for i in items) or
               data["unknownRequests"] > 0 or data["pendingRequest"] is not None)
    coverage = "unknown" if unknown else ("all" if all_partitions and not pending and all(i["status"] == "retained" for i in items) else "some")
    duplicates = defaultdict(list)
    for identifier, item in data["candidates"].items():
        if item["status"] == "retained":
            duplicates[item["textSha256"]].append(identifier)
    return {"schemaVersion": "zoop-private-news-summary-1", "planDigest": data["planDigest"],
            "provenance": _provenance(config),
            "fromDay": config.from_day, "throughDay": config.through_day,
            "state": "completed" if coverage == "all" else "partial", "coverage": coverage,
            "coverageMeaning": "configured discovery partitions and selected candidates only; not whole-news completeness",
            "sourceRequests": data["requests"], "sourceBytes": data["bytes"],
            "unknownRequests": data["unknownRequests"], "unknownByteUpperBound": data["unknownByteUpperBound"],
            "stopCode": data["stopCode"], "partitions": len(tasks),
            "traversedPartitions": sum(t["status"] == "done" for t in tasks),
            "saturatedPartitions": sum(t["saturated"] for t in tasks),
            "pendingPartitions": sum(t["status"] == "pending" for t in tasks),
            "partitionDispositions": dict(Counter(t.get("code", t["status"]) for t in tasks)),
            "candidates": len(items), "pendingCandidates": pending, "retainedInWindow": len(retained),
            "candidateDispositions": dict(dispositions), "dayCounts": dict(sorted(days.items())),
            "weekCounts": dict(sorted(weeks.items())),
            "sourceCounts": dict(Counter(i.get("source", i["refs"][0]["source"]) for i in retained)),
            "domainCounts": dict(Counter(urlsplit(i["url"]).hostname for i in retained)),
            "literalAliasMatchedRecords": sum(bool(i.get("literalAliasMatches")) for i in retained),
            "exactTextDuplicateGroups": sum(len(group) > 1 for group in duplicates.values()),
            "duplicateMeaning": "exact text only; not independent-source or same-event evidence", **USE}


def run(config, command="run"):
    if command not in {"run", "resume", "status"}:
        raise IngestionFailure("private_command_invalid")
    state = State(config, command)
    try:
        if command == "status":
            return summary(config, state)
        if command == "run" and state.data["attempts"]:
            raise IngestionFailure("private_explicit_resume_required")
        state.recover()
        if state.data["stopCode"] not in {"request_budget", "byte_budget", "timeout"}:
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
