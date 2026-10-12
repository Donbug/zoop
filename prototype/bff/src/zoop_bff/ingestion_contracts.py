"""Private offline source protocol. All offsets are Unicode code points, never bytes."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

SCHEMA = "zoop-ingestion-s2-1"
MAX_INPUT = 2_000_000
MAX_RAW = 10_000_000
MAX_TEXT = 500_000
CLEANER = "exact-copy-1"


class IngestionFailure(Exception):
    def __init__(self, code: str, preparation: dict | None = None):
        self.code = code
        self.preparation = preparation
        super().__init__(code)


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def byte_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat()


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed


class Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, extra="forbid", strict=True)

    def wire(self):
        return self.model_dump(by_alias=True, mode="json")


class Window(Wire):
    from_: str = Field(alias="from")
    through: str

    @model_validator(mode="after")
    def ordered(self):
        if timestamp(self.from_) > timestamp(self.through):
            raise ValueError("window order")
        return self


class Run(Wire):
    schema_version: Literal["zoop-ingestion-s2-1"]
    round_id: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=200)
    scope_id: str = Field(min_length=1, max_length=200)
    window: Window | None
    checkpoint_revision: int = Field(ge=0)
    fixture_manifest_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    cleaner_version: Literal["exact-copy-1"]


class Inspect(Wire):
    schema_version: Literal["zoop-ingestion-s2-1"]
    round_id: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=200)
    document_id: str | None = None
    document_version: str | None = None
    locator_id: str | None = None
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, gt=0)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def selectors(self):
        if bool(self.document_id) != bool(self.document_version):
            raise ValueError("exact version required")
        if self.locator_id is not None:
            if self.document_id is None or self.start is None or self.end is None or self.start >= self.end:
                raise ValueError("locator interval required")
        elif self.start is not None or self.end is not None:
            raise ValueError("locator required")
        return self


class Resume(Wire):
    schema_version: Literal["zoop-ingestion-s2-1"]
    round_id: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=200)


class Export(Wire):
    """Exact candidate observation selector for authorized downstream consumers (never a client metadata claim)."""
    schema_version: Literal["zoop-ingestion-s2-1"]
    round_id: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=200)
    page: int = Field(ge=0)
    ordinal: int = Field(ge=0)
    document_id: str = Field(min_length=1)
    raw_version: str = Field(min_length=1)
    document_version: str = Field(min_length=1)


class Grant(Wire):
    grant_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    enabled: bool
    rights: Literal["known", "unknown", "denied"]
    allowed_operations: list[Literal["read", "store", "model-send", "quote-display"]]
    recipients: list[str]
    purposes: list[str]
    evidence: list[str]
    expires_at: str | None

    @model_validator(mode="after")
    def expiry(self):
        if self.expires_at is not None:
            timestamp(self.expires_at)
        return self


class Scope(Wire):
    scope_id: str = Field(min_length=1)
    selection: str = Field(min_length=1, max_length=2000)
    initial_cursor: str | None
    article_xpath: str | None = Field(alias="articleXPath")
    timestamp_limitations: list[str] = Field(min_length=1, max_length=20)


class Source(Wire):
    source_id: str = Field(min_length=1)
    adapter: Literal["authored-files"]
    input_root: str = Field(min_length=1)
    allowed_hosts: list[str] = Field(min_length=1, max_length=100)
    scopes: list[Scope] = Field(min_length=1, max_length=100)
    grant: Grant

    @model_validator(mode="after")
    def bindings(self):
        if self.grant.source_id != self.source_id or len({s.scope_id for s in self.scopes}) != len(self.scopes):
            raise ValueError("source binding")
        if not Path(self.input_root).is_absolute():
            raise ValueError("absolute operator namespace required")
        if any(h != h.lower().rstrip(".") or any(c in h for c in "/:@* ") for h in self.allowed_hosts):
            raise ValueError("exact hosts required")
        return self

    def configuration(self, scope: Scope):
        return {"sourceId": self.source_id, "adapter": self.adapter, "inputRoot": self.input_root,
                "allowedHosts": self.allowed_hosts, "scope": scope.wire()}


class Registry(Wire):
    schema_version: Literal["zoop-ingestion-s2-1"]
    revision: str = Field(min_length=1)
    sources: list[Source] = Field(max_length=100)

    @model_validator(mode="after")
    def unique(self):
        if len({s.source_id for s in self.sources}) != len(self.sources):
            raise ValueError("duplicate source")
        return self


class FileRef(Wire):
    file: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def relative(self):
        if self.file.startswith("/") or any(p in {"", ".", ".."} for p in self.file.split("/")) or "\\" in self.file or ":" in self.file:
            raise ValueError("unsafe fixture path")
        return self


class Page(Wire):
    page_id: str = Field(min_length=1, max_length=200)
    cursor: str | None
    response: FileRef
    status: Literal["ok", "failed", "partial"]
    next_cursor: str | None
    terminal: bool
    coverage_through: str | None

    @model_validator(mode="after")
    def coverage(self):
        if self.terminal == (self.next_cursor is not None):
            raise ValueError("terminal continuation conflict")
        if self.coverage_through is not None:
            timestamp(self.coverage_through)
            if not self.terminal or self.status != "ok":
                raise ValueError("coverage requires successful terminal page")
        return self


class Manifest(Wire):
    schema_version: Literal["zoop-ingestion-s2-1"]
    source_id: str
    scope_id: str
    pages: list[Page] = Field(min_length=1, max_length=100)
    documents: dict[str, FileRef] = Field(max_length=1000)

    @model_validator(mode="after")
    def chain(self):
        if len({p.page_id for p in self.pages}) != len(self.pages):
            raise ValueError("duplicate page")
        for previous, current in zip(self.pages, self.pages[1:]):
            if previous.terminal or previous.next_cursor != current.cursor:
                raise ValueError("noncontiguous pages")
        return self


class Item(Wire):
    candidate_id: str = Field(min_length=1, max_length=200)
    supplier_document_id: str | None = Field(default=None, min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=4000)
    body_ref: str = Field(min_length=1, max_length=200)
    media_type: Literal["text/html", "application/pdf"]
    title: str = Field(max_length=2000)
    published_at: str | None
    modified_at: str | None
    source_revision: str | None

    @model_validator(mode="after")
    def dates(self):
        for value in (self.published_at, self.modified_at):
            if value is not None:
                timestamp(value)
        return self

    def metadata(self):
        return {k: v for k, v in self.wire().items() if k not in {"candidateId", "bodyRef", "url", "supplierDocumentId"}}


def read_file(path: Path, maximum: int) -> bytes:
    """No symlink component, no devices/FIFOs, bounded descriptor read."""
    absolute = Path(os.path.abspath(path))
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        leaf = os.open(absolute.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            info = os.fstat(leaf)
            if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
                raise IngestionFailure("input_size_or_type_invalid")
            with os.fdopen(leaf, "rb", closefd=False) as stream:
                raw = stream.read(maximum + 1)
            if len(raw) > maximum:
                raise IngestionFailure("input_size_or_type_invalid")
            return raw
        finally:
            os.close(leaf)
    finally:
        os.close(fd)


class Authority:
    def __init__(self, path: Path):
        self.path = path
        self.raw = read_file(path, MAX_INPUT)
        self.registry = Registry.model_validate_json(self.raw)

    def check(self, source_id: str, scope_id: str, operations=("read", "store"), config=None):
        if read_file(self.path, MAX_INPUT) != self.raw:
            raise IngestionFailure("registry_changed")
        source = next((s for s in self.registry.sources if s.source_id == source_id), None)
        scope = next((s for s in source.scopes if s.scope_id == scope_id), None) if source else None
        if source is None or scope is None:
            raise IngestionFailure("source_unauthorized")
        g = source.grant
        if not g.enabled or g.rights != "known" or not any(e.strip() for e in g.evidence) or not set(operations) <= set(g.allowed_operations) or (g.expires_at is not None and timestamp(g.expires_at) <= datetime.now(UTC)):
            raise IngestionFailure("source_unauthorized")
        if config is not None and source.configuration(scope) != config:
            raise IngestionFailure("scope_configuration_conflict")
        return source, scope

    def fixture(self, source: Source, ref: FileRef, maximum=MAX_RAW):
        raw = read_file(Path(source.input_root) / ref.file, maximum)
        if byte_hash(raw) != ref.sha256:
            raise IngestionFailure("fixture_hash_mismatch")
        return raw
