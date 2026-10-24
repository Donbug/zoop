"""Bounded Hacker News link discovery, never article acquisition or community analysis.

The native HTTP engine keeps its DNS pinning, robots, TLS, deadline and blocked-host gates.
Only this private policy admits JSON; the document collector's policy/wire is unchanged.
No raw API body, author, comment, user profile or linked article is persisted.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import Field, field_validator, model_validator

from .collection import Fetcher
from .ingestion_contracts import IngestionFailure, Wire, byte_hash, canonical, digest, now

OFFICIAL_ORIGIN = "https://hacker-news.firebaseio.com"
MAX_SNAPSHOT = 1_000_000
MAX_ID = 9_007_199_254_740_991
STOP_CODES = frozenset({"http_401", "http_403", "http_429", "host_blocked", "request_budget", "byte_budget",
                        "timeout", "rate_limit", "robots_denied", "robots_malformed", "robots_unavailable"})


class Config(Wire):
    schema_version: Literal["zoop-hn-discovery-config-1"]
    feed: Literal["new", "top", "best"]
    limit: int = Field(ge=1, le=50)
    user_agent: str = Field(min_length=1, max_length=200)
    timeout_seconds: int = Field(ge=1, le=300)
    max_total_seconds: int = Field(ge=1, le=3600)
    max_requests: int = Field(ge=1, le=52)
    max_response_bytes: int = Field(ge=1, le=1_000_000)
    max_total_bytes: int = Field(ge=1, le=10_000_000)
    min_interval_seconds: float = Field(ge=1, le=60)
    synthetic_loopback: bool = False
    synthetic_base_url: str | None = None

    @field_validator("user_agent")
    @classmethod
    def printable(cls, value):
        if any(not 0x20 <= ord(c) <= 0x7E for c in value):
            raise ValueError("user agent must be printable ASCII")
        return value

    @model_validator(mode="after")
    def bounded(self):
        if self.timeout_seconds > self.max_total_seconds or self.max_response_bytes > self.max_total_bytes:
            raise ValueError("per-response limits exceed run limits")
        if self.synthetic_loopback:
            if not self.synthetic_base_url or not re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}", self.synthetic_base_url):
                raise ValueError("synthetic mode requires an explicit numeric loopback origin")
            if not 1 <= urlsplit(self.synthetic_base_url).port <= 65535:
                raise ValueError("synthetic port invalid")
        elif self.synthetic_base_url is not None:
            raise ValueError("synthetic origin requires synthetic mode")
        return self

    @property
    def origin(self):
        return self.synthetic_base_url if self.synthetic_loopback else OFFICIAL_ORIGIN

    @property
    def max_redirects(self):
        return 0

    @property
    def allowed_media_types(self):
        return ("application/json",)


class Story(Wire):
    hn_story_id: int = Field(ge=1, le=MAX_ID)
    hn_submitted_title_html: str = Field(min_length=1, max_length=2000)
    story_created_at: str
    observed_at: str
    score: int | None = Field(ge=0, le=MAX_ID)
    comment_count: int | None = Field(ge=0, le=MAX_ID)
    raw_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Candidate(Wire):
    candidate_id: str = Field(pattern=r"^hn-url-[0-9a-f]{64}$")
    canonical_url: str = Field(max_length=4000)
    story_refs: list[Story] = Field(min_length=1, max_length=50)
    article_published_at: None = None
    publisher: None = None
    article_access: Literal["not-assessed"] = "not-assessed"
    license: Literal["not-assessed"] = "not-assessed"
    model_send: Literal["not-authorized"] = "not-authorized"


class Disposition(Wire):
    hn_story_id: int = Field(ge=1, le=MAX_ID)
    code: str = Field(pattern=r"^[a-z0-9_]{1,80}$")
    observed_at: str | None
    raw_response_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")


class Snapshot(Wire):
    schema_version: Literal["zoop-hn-discovery-1"]
    config: Config
    config_digest: str
    state: Literal["completed", "stopped"]
    provenance: Literal["external-hn-api-metadata", "synthetic-loopback-metadata"]
    started_at: str
    observed_at: str
    source_requests: int = Field(ge=0, le=52)
    # The last received chunk can cross the transport cap; report measured bytes without clamping.
    source_bytes: int = Field(ge=0)
    feed_fetched_at: str | None
    feed_response_sha256: str | None
    selected_story_ids: list[int] = Field(max_length=50)
    candidates: list[Candidate] = Field(max_length=50)
    dispositions: list[Disposition] = Field(max_length=50)
    stop_code: str | None


class _JsonFetcher(Fetcher):
    """Fixed-origin, fixed-path specialization; even redirects cannot escape the selected paths."""

    def __init__(self, config):
        super().__init__(config, [urlsplit(config.origin).hostname])
        self.origin = config.origin
        self.paths = {"/robots.txt", f"/v0/{config.feed}stories.json"}

    def _guard(self, value):
        url, host = super()._guard(value)
        parts = urlsplit(url)
        if f"{parts.scheme}://{parts.netloc}" != self.origin or parts.path not in self.paths or parts.query or parts.fragment:
            raise IngestionFailure("discovery_endpoint_not_allowed")
        return url, host


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (ValueError, UnicodeError, RecursionError):
        raise IngestionFailure("json_invalid") from None


def _read_at(directory, name, cap):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > cap:
            raise IngestionFailure("discovery_file_invalid")
        with os.fdopen(fd, "rb", closefd=False) as source:
            raw = source.read(cap + 1)
        if len(raw) > cap:
            raise IngestionFailure("discovery_file_invalid")
        return raw
    finally:
        os.close(fd)


def load_config(path):
    path = Path(path)
    directory = os.open(path.absolute().parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        return Config.model_validate(_json(_read_at(directory, path.name, 100_000)))
    finally:
        os.close(directory)


def link_identity(value):
    """Metadata identity only. Preserve scheme and meaningful query; never resolve or open the host."""
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 4000:
            raise ValueError("invalid link")
        parts = urlsplit(value)
        if (parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None or parts.password is not None
                or "\\" in value or any(ord(c) < 33 or ord(c) == 127 for c in value)):
            raise ValueError("invalid link")
        url = httpx.URL(value)
        if not url.is_absolute_url:
            raise ValueError("invalid link")
        normalized = str(url.copy_with(raw_path=url.raw_path, fragment=None))
        if len(normalized) > 4000:
            raise ValueError("normalized link too large")
        return normalized
    except (ValueError, UnicodeError, httpx.InvalidURL):
        raise IngestionFailure("link_invalid") from None


def _integer(value, minimum=0, maximum=MAX_ID):
    return type(value) is int and minimum <= value <= maximum


def parse_item(raw, story_id, observed_at):
    """Return one minimized link/ref or a bounded disposition code; never retain unselected keys."""
    item = _json(raw)
    if item is None:
        raise IngestionFailure("item_null")
    if not isinstance(item, dict) or not _integer(item.get("id"), 1) or item["id"] != story_id:
        raise IngestionFailure("item_identity_invalid")
    for flag in ("deleted", "dead"):
        if flag in item and type(item[flag]) is not bool:
            raise IngestionFailure("item_type_invalid")
    if item.get("deleted"):
        raise IngestionFailure("item_deleted")
    if item.get("dead"):
        raise IngestionFailure("item_dead")
    if not isinstance(item.get("type"), str) or not 1 <= len(item["type"]) <= 32:
        raise IngestionFailure("item_type_invalid")
    if item["type"] != "story":
        raise IngestionFailure("item_nonstory" if item["type"] in {"job", "comment", "poll", "pollopt"} else "item_unsupported")
    title = item.get("title")
    if (not isinstance(title, str) or not 1 <= len(title) <= 2000 or not title.strip()
            or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in title)
            or not _integer(item.get("time"), 0, 253402300799)):
        raise IngestionFailure("item_metadata_invalid")
    for name in ("score", "descendants"):
        if name in item and not _integer(item[name]):
            raise IngestionFailure("item_metadata_invalid")
    if "url" not in item:
        raise IngestionFailure("item_no_link")
    url = link_identity(item["url"])
    # A discussion self-link is not an external article candidate, regardless of its submission type.
    if urlsplit(url).hostname.rstrip(".") in {"news.ycombinator.com", "hacker-news.firebaseio.com"}:
        raise IngestionFailure("item_internal_link")
    story = Story(hnStoryId=story_id, hnSubmittedTitleHtml=title,
                  storyCreatedAt=datetime.fromtimestamp(item["time"], UTC).isoformat(), observedAt=observed_at,
                  score=item.get("score"), commentCount=item.get("descendants"), rawResponseSha256=byte_hash(raw))
    return url, story


class _Output:
    """A new external directory, locked; publish one fsynced no-clobber snapshot, never raw responses."""

    def __init__(self, path, create):
        path = Path(path)
        if not path.is_absolute() or ".." in path.parts:
            raise IngestionFailure("discovery_output_invalid")
        checkout = Path(__file__).resolve().parents[4]
        for reserved in (checkout, Path.home() / "InvestMateLogicTest"):
            if path == reserved or path.is_relative_to(reserved) or reserved.is_relative_to(path):
                raise IngestionFailure("discovery_output_not_external")
        self.fd = self.lock = None
        parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in path.parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                os.close(parent)
                parent = child
            created = False
            if create:
                try:
                    os.mkdir(path.name, 0o700, dir_fd=parent)
                    created = True
                except FileExistsError:
                    pass
            self.fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            names = set(os.listdir(self.fd))
            if (not created and ".lock" not in names) or names - {".lock", "SNAPSHOT.json"}:
                raise IngestionFailure("discovery_namespace_conflict")
            self.lock = os.open(".lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK if not created else
                                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
            if not stat.S_ISREG(os.fstat(self.lock).st_mode):
                raise IngestionFailure("discovery_namespace_conflict")
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise IngestionFailure("discovery_busy") from None
            # A killed/incomplete run is not resumed or resent under the same directory.
            if not created and "SNAPSHOT.json" not in names:
                raise IngestionFailure("discovery_incomplete_output")
        except BaseException:
            self.close()
            raise
        finally:
            os.close(parent)

    def close(self):
        for fd in (self.lock, self.fd):
            if fd is not None:
                os.close(fd)
        self.lock = self.fd = None

    def stored(self, config):
        try:
            raw = _read_at(self.fd, "SNAPSHOT.json", MAX_SNAPSHOT)
        except FileNotFoundError:
            return None
        envelope = _json(raw)
        if not isinstance(envelope, dict) or set(envelope) != {"snapshot", "sha256"} or digest(envelope["snapshot"]) != envelope["sha256"]:
            raise IngestionFailure("discovery_snapshot_invalid")
        snapshot = Snapshot.model_validate(envelope["snapshot"])
        if snapshot.config.wire() != config.wire() or snapshot.config_digest != digest(config.wire()):
            raise IngestionFailure("discovery_config_conflict")
        return snapshot.wire()

    def publish(self, snapshot):
        data = canonical({"snapshot": snapshot, "sha256": digest(snapshot)}).encode()
        if len(data) > MAX_SNAPSHOT:
            raise IngestionFailure("discovery_snapshot_too_large")
        temporary = ".staging-" + uuid.uuid4().hex
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, "SNAPSHOT.json", src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)
            os.fsync(self.fd)
        finally:
            os.unlink(temporary, dir_fd=self.fd)
            os.fsync(self.fd)


def _acquire(config):
    fetcher = _JsonFetcher(config)
    started = now()
    candidates, dispositions, selected = {}, [], []
    feed_at = feed_hash = stop = None
    try:
        response = fetcher.fetch(config.origin + f"/v0/{config.feed}stories.json")
        feed_at, feed_hash = response.fetched_at, byte_hash(response.body)
        ids = _json(response.body)
        if not isinstance(ids, list) or len(ids) > 500 or any(not _integer(value, 1) for value in ids) or len(set(ids)) != len(ids):
            raise IngestionFailure("feed_identity_invalid")
        selected = ids[:config.limit]
        fetcher.paths.update(f"/v0/item/{value}.json" for value in selected)
        for story_id in selected:
            observed = raw_hash = None
            if stop is not None:
                dispositions.append(Disposition(hnStoryId=story_id, code="not_requested_" + stop,
                                                observedAt=None, rawResponseSha256=None))
                continue
            try:
                response = fetcher.fetch(config.origin + f"/v0/item/{story_id}.json")
                observed, raw_hash = response.fetched_at, byte_hash(response.body)
                url, story = parse_item(response.body, story_id, observed)
                if url not in candidates:
                    candidates[url] = Candidate(candidateId="hn-url-" + byte_hash(url.encode()), canonicalUrl=url, storyRefs=[story])
                else:
                    candidates[url].story_refs.append(story)
            except IngestionFailure as exc:
                dispositions.append(Disposition(hnStoryId=story_id, code=exc.code, observedAt=observed, rawResponseSha256=raw_hash))
                if exc.code in STOP_CODES:
                    stop = exc.code
    except IngestionFailure as exc:
        stop = exc.code
    result = Snapshot(schemaVersion="zoop-hn-discovery-1", config=config, configDigest=digest(config.wire()),
                      state="stopped" if stop else "completed",
                      provenance="synthetic-loopback-metadata" if config.synthetic_loopback else "external-hn-api-metadata",
                      startedAt=started, observedAt=now(), sourceRequests=fetcher.requests, sourceBytes=fetcher.downloaded,
                      feedFetchedAt=feed_at, feedResponseSha256=feed_hash, selectedStoryIds=selected,
                      candidates=list(candidates.values()), dispositions=dispositions, stopCode=stop)
    return result.wire()


def run(config: Config, output: Path):
    store = _Output(output, create=True)
    try:
        found = store.stored(config)
        if found is not None:
            return {**found, "replayed": True}
        snapshot = _acquire(config)
        store.publish(snapshot)
        return {**snapshot, "replayed": False}
    finally:
        store.close()


def status(config: Config, output: Path):
    store = _Output(output, create=False)
    try:
        found = store.stored(config)
        if found is None:
            raise IngestionFailure("discovery_snapshot_missing")
        return {**found, "replayed": True}
    finally:
        store.close()
