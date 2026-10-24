"""Private offline source protocol. All offsets are Unicode code points, never bytes."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_serializer, model_validator
from pydantic.alias_generators import to_camel

SCHEMA = "zoop-ingestion-s2-1"
MAX_INPUT = 2_000_000
MAX_RAW = 10_000_000
MAX_TEXT = 500_000
CLEANER = "exact-copy-1"


MAX_LEDGER_COPY = 128 * 1024 * 1024         # a ledger holds receipts and plans only (artifacts are files): a main file or WAL beyond this is not ours to copy


def copy_bounded(source: Path, target: Path) -> None:
    """A bounded private copy of one regular, non-symlink ledger file (the source is only read). Any failure is a `ValueError`; the caller names the code."""
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise ValueError("ledger_copy") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_LEDGER_COPY:
            raise ValueError("ledger_copy")
        out = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            copied = 0
            while chunk := os.read(fd, 1 << 20):
                copied += len(chunk)
                if copied > MAX_LEDGER_COPY:
                    raise ValueError("ledger_copy")
                view, written = memoryview(chunk), 0
                while written < len(view):
                    written += os.write(out, view[written:])
        finally:
            os.close(out)
    except OSError:
        raise ValueError("ledger_copy") from None
    finally:
        os.close(fd)


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


def source_checkout() -> bool:
    """True only when this module runs from ai/pipeline/src inside a repository checkout (not an installed package)."""
    here = Path(__file__).resolve()
    project = here.parents[4]
    return here.parents[1].name == "src" and (project / "ai/pipeline/src/zoop_ai_pipeline") == here.parent and (project / "ai/pipeline/pyproject.toml").is_file()


def reserved_state_roots() -> list[Path]:
    """Application, S1 worker and retired prototype state roots that a pipeline ledger must never overlap or adopt.

    In a source checkout the repository roots are known from the file location. An installed package has no repository,
    so ownership must be configured explicitly: ZOOP_STATE_DIR (application) and ZOOP_AI_WORKER_STATE_DIR (S1 worker),
    both absolute. Missing or relative values fail closed; no location is guessed from the interpreter or cwd.
    """
    checkout = source_checkout()
    roots = [Path.home() / "InvestMateLogicTest"]
    if checkout:
        project = Path(__file__).resolve().parents[4]
        roots += [project / name for name in ("prototype/bff/var", "prototype/ai-worker/var", "api/var", "ai/worker/var")]
    for key in ("ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"):
        value = os.environ.get(key)
        if value:
            if not os.path.isabs(value):
                raise IngestionFailure("state_ownership_unconfigured")
            roots.append(Path(value).resolve())
        elif not checkout:
            raise IngestionFailure("state_ownership_unconfigured")
    return roots


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


def _declared_publisher(value: str) -> str:
    """An operator-declared outlet name, stored exactly as written: no trimming and no Unicode normalization.

    Rejected: a lone surrogate, any Unicode control character (category Cc, which includes NUL, tab and newline) and a value made
    only of separator characters (category Z*), because none of them can name an outlet. The application importer applies the same rule."""
    if any(unicodedata.category(c) == "Cc" or 0xD800 <= ord(c) <= 0xDFFF for c in value) or all(unicodedata.category(c).startswith("Z") for c in value):
        raise ValueError("publisher must be a printable outlet name")
    return value


Publisher = Annotated[str, StringConstraints(min_length=1, max_length=200), AfterValidator(_declared_publisher)]


class Declared(Wire):
    """A request/item model with an optional operator-declared publishing outlet.

    Unspecified is the key's absence, never an explicit null: the key is dropped from every dump, including a dump nested in a parent
    model (`Request.wire()` does not call `Target.wire()`, so a `wire()` override would not reach it), and ONLY this key is dropped.
    Every existing nullable key keeps serializing as null, so no earlier request digest, page, metadata or raw version changes.
    A present publisher is identity: it enters the metadata hash, so it yields a new raw/document version of the same document."""
    publisher: Publisher | None = None

    @model_serializer(mode="wrap")
    def _without_unspecified_publisher(self, handler):
        dumped = handler(self)
        if self.publisher is None:
            dumped.pop("publisher", None)
        return dumped


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


class Tick(Wire):
    """Scheduler tick for one source scope. `now` is a deterministic clock override (never later than the real clock); `initialFrom` is the
    explicit first baseline, only valid while the scope has no stored successful `through` time."""
    schema_version: Literal["zoop-ingestion-s2-1"]
    source_id: str = Field(min_length=1, max_length=200)
    scope_id: str = Field(min_length=1, max_length=200)
    initial_from: str | None = None
    now: str | None = None

    @model_validator(mode="after")
    def offsets(self):
        for value in (self.initial_from, self.now):
            if value is not None:
                timestamp(value)
        return self


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
    adapter: Literal["authored-files", "collected-http"]
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


class Published(Wire):
    """The publication time exactly as the operator declared it. Nothing here is read from the page or guessed."""
    raw: str | None
    precision: Literal["instant", "day", "unresolved", "unknown"]
    date: str | None
    basis: str = Field(min_length=1, max_length=200)


class Collected(Wire):
    """Item-level proof that these bytes came from one recorded HTTP acquisition (never set on authored fixtures)."""
    provenance: Literal["collected_http"]
    collection_id: str = Field(min_length=1, max_length=100)
    receipt: FileRef
    fetched_at: str
    final_url: str = Field(min_length=1, max_length=4000)
    http_status: int = Field(ge=200, le=299)
    content_type: str = Field(max_length=200)
    body_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    document_kind: Literal["news", "disclosure"]
    # `synthetic_loopback` marks bytes served by a local synthetic test server (policy `syntheticLoopback`); it is never an external document.
    network: Literal["external", "synthetic_loopback"]
    published: Published

    @model_validator(mode="after")
    def instant(self):
        timestamp(self.fetched_at)
        return self


class Robots(Wire):
    url: str = Field(max_length=4000)
    status: int


class Receipt(Wire):
    """One acquisition, hash-pinned by Collected.receipt. Contains no request header other than the user agent, no cookie, no credential."""
    schema_version: Literal["zoop-collection-receipt-1"]
    collection_id: str
    source_id: str
    scope_id: str
    candidate_id: str
    grant_id: str
    grant_revision: str
    requested_url: str
    final_url: str
    redirects: list[str] = Field(max_length=10)
    http_status: int
    content_type: str
    media_type: Literal["text/html", "application/pdf"]
    content_length: str | None
    etag: str | None
    last_modified: str | None
    server_date: str | None
    body_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    body_bytes: int = Field(ge=0)
    fetched_at: str
    user_agent: str
    network: Literal["external", "synthetic_loopback"]
    robots: list[Robots] = Field(max_length=10)
    request_count: int = Field(ge=1)

    @model_validator(mode="after")
    def instant(self):
        timestamp(self.fetched_at)
        return self


class Item(Declared):
    candidate_id: str = Field(min_length=1, max_length=200)
    supplier_document_id: str | None = Field(default=None, min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=4000)
    body_ref: str = Field(min_length=1, max_length=200)
    media_type: Literal["text/html", "application/pdf"]
    title: str = Field(max_length=2000)
    published_at: str | None
    modified_at: str | None
    source_revision: str | None
    collection: Collected | None = None

    @model_validator(mode="after")
    def dates(self):
        for value in (self.published_at, self.modified_at):
            if value is not None:
                timestamp(value)
        if self.collection is not None:
            declared = self.collection.published
            if self.published_at != (declared.raw if declared.precision == "instant" else None):
                raise ValueError("published time must be the declared instant, never an inferred one")
        return self

    def metadata(self):
        # Collection facts describe one observation; they are not part of the immutable raw-version identity.
        # A present publisher stays in this metadata (it is raw-version identity); an unspecified one has no key at all.
        return {k: v for k, v in self.wire().items() if k not in {"candidateId", "bodyRef", "url", "supplierDocumentId", "collection"}}


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


NAVER_SEARCH = frozenset({"naver-search", "naver-developers-search"})


class Authority:
    def __init__(self, path: Path):
        self.path = path
        self.raw = read_file(path, MAX_INPUT)
        self.registry = Registry.model_validate_json(self.raw)

    def check(self, source_id: str, scope_id: str, operations=("read", "store"), config=None, *, purpose: str | None = None, recipient: str | None = None):
        """Current registry authority for `operations`. `purpose`/`recipient` (together) make this a live model-send check, the only live authority.

        Without them nothing changes: replay and ingestion never need `model-send`. With them the grant must additionally allow `model-send`, the
        source must not be a Naver search source (same normalization as the S1 grant registry), and the exact purpose and recipient must be named
        by the grant (an empty list authorizes nothing). Nothing is inferred from the endpoint, the model or the document's own flags."""
        if (purpose is None) != (recipient is None):
            raise ValueError("purpose and recipient are checked together")
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
        if purpose is not None:
            if source.source_id.lower().replace("_", "-") in NAVER_SEARCH:
                raise IngestionFailure("naver_search_ai_prohibited")
            if "model-send" not in g.allowed_operations:
                raise IngestionFailure("source_operation_denied")
            if purpose not in g.purposes or recipient not in g.recipients:
                raise IngestionFailure("source_purpose_or_recipient_denied")
        return source, scope

    def sending(self, purpose: str, recipient: str) -> "Sending":
        """A view of this authority for one outbound model call: every check it answers is the model-send check for this purpose and recipient."""
        return Sending(self, purpose, recipient)

    def fixture(self, source: Source, ref: FileRef, maximum=MAX_RAW):
        raw = read_file(Path(source.input_root) / ref.file, maximum)
        if byte_hash(raw) != ref.sha256:
            raise IngestionFailure("fixture_hash_mismatch")
        return raw


class Sending:
    """`Authority` as seen by one outbound model call (usable anywhere an Authority is): `check` always adds this purpose and recipient."""

    def __init__(self, authority: Authority, purpose: str, recipient: str):
        self.authority, self.purpose, self.recipient = authority, purpose, recipient

    @property
    def raw(self) -> bytes:
        return self.authority.raw

    def check(self, source_id: str, scope_id: str, operations=("read", "store"), config=None):
        return self.authority.check(source_id, scope_id, operations, config, purpose=self.purpose, recipient=self.recipient)

    def fixture(self, source: Source, ref: FileRef, maximum=MAX_RAW):
        return self.authority.fixture(source, ref, maximum)
