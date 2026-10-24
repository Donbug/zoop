"""Local human-review preparation; native ingestion owns current source authorization.

Portable verification proves internal integrity, not publisher authenticity or current rights.
Annotation files are never opened by prepare/verify; annotation checking is a separate read.
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, StringConstraints, model_validator

from .ingestion import Ingestor, Store
from .ingestion_contracts import (MAX_RAW, Authority, Collected, Export, IngestionFailure, Publisher,
    Receipt, Run, Wire, byte_hash, canonical, digest, now, read_file, reserved_state_roots, timestamp)
from .korea_portal import ROUTES, article_id, validate_article

MAX_BINDINGS = 8_000_000
MAX_EXPORT = 8_000_000
MAX_JSON = 16_000_000
MAX_TOTAL = 512_000_000
MAX_DOCUMENTS = 2000
MAX_REVIEW = 200
SHA = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Label = Annotated[str, StringConstraints(min_length=1, max_length=200)]
PathName = Annotated[str, StringConstraints(min_length=1, max_length=4096)]
LIMITS = {
    "authorization": "Current native read/store/quote-display checked at creation only; not perpetual authorization or publisher authenticity.",
    "permission": "Local human handoff only; no model-send, upload, external publication or redistribution permission is conferred.",
    "selection": "Deterministic channel/publication-week review batch; not representative, held-out, a test split or importance ranking.",
    "annotations": "Unreviewed null fields are missing judgments; completed annotations are operator claims, not verified human adjudication or score inputs.",
    "text": "Exact native text/locators retained, including possible boilerplate; no raw HTML, time filling or lineage inference.",
    "bounds": "2000 documents; 8 MB bindings/export; 16 MB inputs/annotations; 512 MB total exports; quota 1..50; review maximum 1..200; one native store at a time.",
}


def fail(code):
    raise IngestionFailure("review_" + code)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail("duplicate_json_key")
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=_object,
                      parse_constant=lambda _: fail("nonfinite_json"))


def absolute(value):
    if not Path(value).is_absolute() or os.path.abspath(value) != value or "\x00" in value:
        raise ValueError("normalized absolute path required")
    return Path(value)


class Pin(Wire):
    path: PathName
    sha256: SHA

    @model_validator(mode="after")
    def path_valid(self):
        absolute(self.path)
        return self


class AuthorityEvidence(Wire):
    kind: Literal["legacy-operator-evidence", "native-corpus-plan"]
    rights_evidence: Pin
    plan_file: Pin | None
    exclusion_manifest: Pin | None

    @model_validator(mode="after")
    def boundary(self):
        if (self.kind == "native-corpus-plan") != (self.plan_file is not None and self.exclusion_manifest is not None):
            raise ValueError("native corpus requires plan and exclusion pins")
        if self.kind == "legacy-operator-evidence" and (self.plan_file is not None or self.exclusion_manifest is not None):
            raise ValueError("legacy evidence has no corpus plan")
        return self


class SelectionMetadata(Wire):
    channel: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,79}$")]
    channel_basis: Literal["portal-path", "operator-classification"]
    channel_provenance: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    publication_day: str | None
    day_provenance: Annotated[str, StringConstraints(min_length=1, max_length=1000)]

    @model_validator(mode="after")
    def calendar(self):
        if self.publication_day is not None and date.fromisoformat(self.publication_day).isoformat() != self.publication_day:
            raise ValueError("exact ISO calendar day required")
        return self


class Binding(Wire):
    original_export: Pin
    native_export: Export
    source_registry_file: Pin
    ingestion_state_dir: PathName
    authority_evidence: AuthorityEvidence
    selection: SelectionMetadata

    @model_validator(mode="after")
    def state(self):
        absolute(self.ingestion_state_dir)
        return self


class Policy(Wire):
    per_stratum_quota: int = Field(ge=1, le=50)
    max_review_documents: int = Field(ge=1, le=MAX_REVIEW)
    allow_unknown_date: bool


class Bindings(Wire):
    schema_version: Literal["zoop-corpus-review-bindings-1"]
    selection_policy: Policy
    documents: list[Binding] = Field(min_length=1, max_length=MAX_DOCUMENTS)


class Observation(Wire):
    round_id: Label
    source_id: Label
    page: int = Field(ge=0)
    ordinal: int = Field(ge=0)
    page_id: Label
    observed_at: str
    document_id: Label
    raw_version: Label
    document_version: Label
    url: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    title: Annotated[str, StringConstraints(max_length=2000)]
    published_at: str | None
    modified_at: str | None
    source_revision: str | None
    media_type: Literal["text/html", "application/pdf"]
    publisher: Publisher | None = None
    provenance: Literal["collected_http"] | None = None
    collection: Collected | None = None

    @model_validator(mode="after")
    def dates(self):
        timestamp(self.observed_at)
        for value in (self.published_at, self.modified_at):
            if value is not None:
                timestamp(value)
        if (self.provenance is None) != (self.collection is None):
            raise ValueError("collection provenance required together")
        return self


class GrantReference(Wire):
    grant_id: Label
    revision: Label


class Locator(Wire):
    locator_id: Label
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class Projection(Wire):
    document_id: Label
    document_version: Label
    source_id: Label
    text_artifact_id: Label
    input_kind: Literal["body"]
    cleaner_version: Label
    text: Annotated[str, StringConstraints(min_length=1, max_length=500_000)]
    source_hash: SHA
    raw_locators: list[Locator] = Field(min_length=1, max_length=30_000)

    @model_validator(mode="after")
    def locators(self):
        if digest(self.text) != self.source_hash:
            raise ValueError("native source hash mismatch")
        if len({r.locator_id for r in self.raw_locators}) != len(self.raw_locators):
            raise ValueError("duplicate locator")
        previous = 0
        for r in self.raw_locators:
            if not previous <= r.start < r.end <= len(self.text):
                raise ValueError("invalid text locator bounds")
            previous = r.end
        return self


class ParserProfile(Wire):
    parser: Label
    lxml: Label
    pypdf: Label
    mapping_version: Label
    html_decoding: Label
    html_scope: Label
    pdf_extraction: Label
    article_xpath: str | None = Field(alias="articleXPath")


class LocatorMetadata(Wire):
    raw_artifact_id: Label
    raw_hash: SHA
    raw_version: Label
    representation_hash: SHA
    mapping_hash: SHA
    parser_profile: ParserProfile
    limitations: list[str] = Field(max_length=100)
    page_count: int | None = Field(default=None, ge=1)
    empty_page_count: int | None = Field(default=None, ge=0)


class NativeDocument(Wire):
    schema_version: Literal["zoop-ingestion-s2-1"]
    observation: Observation
    grant: GrantReference
    document: Projection
    locator_metadata: LocatorMetadata

    @model_validator(mode="after")
    def identities(self):
        for name in ("document_id", "document_version", "source_id"):
            if getattr(self.observation, name) != getattr(self.document, name):
                raise ValueError("native identity mismatch")
        if self.observation.raw_version != self.locator_metadata.raw_version:
            raise ValueError("raw version mismatch")
        return self


class FileReference(Wire):
    file: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    sha256: SHA
    bytes: int = Field(ge=1, le=MAX_JSON)


class PortablePins(Wire):
    registry_sha256: SHA
    rights_evidence_sha256: SHA
    plan_sha256: SHA | None
    exclusion_sha256: SHA | None
    kind: Literal["legacy-operator-evidence", "native-corpus-plan"]


class Record(Wire):
    case_id: Annotated[str, StringConstraints(pattern=r"^case-[a-f0-9]{64}$")]
    export: FileReference
    native_export: Export
    # Exact source dictionaries retain absent optional keys, not newly injected nulls.
    observation: dict
    grant: GrantReference
    authority_pins: PortablePins
    selection: SelectionMetadata


class Stratum(Wire):
    channel: str
    publication_week: str
    available_case_ids: list[str] = Field(max_length=MAX_DOCUMENTS)
    selected_case_ids: list[str] = Field(max_length=MAX_REVIEW)
    available_count: int = Field(ge=0, le=MAX_DOCUMENTS)
    selected_count: int = Field(ge=0, le=MAX_REVIEW)


class Selection(Wire):
    policy: Policy
    algorithm: Literal["channel-iso-week-round-robin-observation-order-1"]
    strata: list[Stratum] = Field(max_length=MAX_DOCUMENTS)
    selected_case_ids: list[str] = Field(max_length=MAX_REVIEW)


class Inputs(Wire):
    schema_version: Literal["zoop-corpus-review-inputs-1"]
    source_input_sha256: SHA
    documents: list[Record] = Field(min_length=1, max_length=MAX_DOCUMENTS)
    selection: Selection


class Manifest(Wire):
    schema_version: Literal["zoop-corpus-review-pack-1"]
    created_at: str
    source_input_sha256: SHA
    immutable_inputs_sha256: SHA
    inputs: FileReference
    document_count: int = Field(ge=1, le=MAX_DOCUMENTS)
    review_count: int = Field(ge=1, le=MAX_REVIEW)
    limits: dict[str, str]


class Span(Wire):
    document_id: Label
    document_version: Label
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: Annotated[str, StringConstraints(min_length=1, max_length=500_000)]


class Annotation(Wire):
    case_id: str
    status: Literal["unreviewed", "reviewed", "excluded"]
    reviewer_id: Label | None
    reviewed_at: str | None
    graph_notes: Annotated[str, StringConstraints(min_length=1, max_length=20_000)] | None
    rag_questions: list[Annotated[str, StringConstraints(min_length=1, max_length=2000)]] | None = Field(max_length=100)
    exclusion_reason: Annotated[str, StringConstraints(min_length=1, max_length=2000)] | None
    evidence_spans: list[Span] | None = Field(max_length=100)

    @model_validator(mode="after")
    def human_fields(self):
        fields = (self.reviewer_id, self.reviewed_at, self.graph_notes, self.rag_questions,
                  self.exclusion_reason, self.evidence_spans)
        if self.status == "unreviewed":
            if any(v is not None for v in fields):
                raise ValueError("unreviewed judgments must remain null")
        else:
            if not self.reviewer_id or not self.reviewer_id.strip() or self.reviewed_at is None:
                raise ValueError("terminal state requires reviewer and time")
            timestamp(self.reviewed_at)
            if self.status == "reviewed":
                if self.graph_notes is None or not self.graph_notes.strip() or self.rag_questions is None or self.exclusion_reason is not None:
                    raise ValueError("reviewed requires graph notes and explicit RAG questions list")
            elif self.exclusion_reason is None or not self.exclusion_reason.strip():
                raise ValueError("excluded requires a human reason")
        return self


class Annotations(Wire):
    schema_version: Literal["zoop-corpus-review-annotations-1"]
    inputs_sha256: SHA
    cases: list[Annotation] = Field(min_length=1, max_length=MAX_REVIEW)


def _pin(pin, maximum=MAX_BINDINGS):
    raw = read_file(Path(pin.path), maximum)
    if byte_hash(raw) != pin.sha256:
        fail("pin_changed")
    return raw


def _selector(observation):
    return {"schemaVersion": "zoop-ingestion-s2-1", **{k: observation[k] for k in
            ("roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion")}}


def _order(record):
    s = record.native_export
    return (s.round_id, s.source_id, s.page, s.ordinal, s.document_id, s.raw_version, s.document_version)


def _metadata(selection, observation, policy):
    parts = urlsplit(observation["url"])
    known = next((name for name, route in ROUTES.items() if parts.path == route[1]), None)
    if parts.hostname in {"www.korea.kr", "m.korea.kr"} and known is not None:
        if selection.channel != known:
            fail("channel_mismatch")
        collection = observation.get("collection")
        if collection and collection["documentKind"] != "news":
            fail("channel_mismatch")
    elif selection.channel_basis == "portal-path":
        fail("channel_unbound")
    declared = (observation.get("collection") or {}).get("published")
    native_day = declared["date"] if declared and declared["precision"] in {"day", "instant"} else None
    if native_day is None and observation["publishedAt"] is not None:
        native_day = timestamp(observation["publishedAt"]).date().isoformat()
    if native_day != selection.publication_day:
        fail("publication_day_mismatch")
    if native_day is None and not policy.allow_unknown_date:
        fail("unknown_date_disallowed")


def choose(records, policy):
    groups = defaultdict(list)
    for record in sorted(records, key=_order):
        day = record.selection.publication_day
        week = "unknown" if day is None else "%04d-W%02d" % date.fromisoformat(day).isocalendar()[:2]
        groups[(record.selection.channel, week)].append(record.case_id)
    keys = sorted(groups)
    selected = []
    for turn in range(policy.per_stratum_quota):
        for key in keys:
            if len(selected) < policy.max_review_documents and turn < len(groups[key]):
                selected.append(groups[key][turn])
    included = set(selected)
    return Selection.model_validate({"policy": policy.wire(), "algorithm": "channel-iso-week-round-robin-observation-order-1",
        "strata": [{"channel": k[0], "publicationWeek": k[1], "availableCaseIds": groups[k],
                    "selectedCaseIds": [i for i in groups[k] if i in included], "availableCount": len(groups[k]),
                    "selectedCount": sum(i in included for i in groups[k])} for k in keys], "selectedCaseIds": selected})


def _evidence(binding):
    evidence = binding.authority_evidence
    if (binding.native_export.source_id == "korea-portal"
            and binding.native_export.round_id.startswith("item-")
            and evidence.kind != "native-corpus-plan"):
        fail("corpus_plan_required")
    _pin(evidence.rights_evidence, 2_000_000)
    if evidence.kind == "native-corpus-plan":
        # The source runner's immutable PLAN names the external current-evidence boundary.
        from .korea_corpus import Config
        plan = decode(_pin(evidence.plan_file))
        if (set(plan) != {"config", "rightsSha256", "gateVersion"}
                or plan["gateVersion"] not in {"korea-portal-static-2", "korea-portal-static-3"}):
            fail("plan_invalid")
        config = Config.model_validate(plan["config"])
        if (config.rights_evidence.wire() != evidence.rights_evidence.wire()
                or config.exclusion_manifest.wire() != evidence.exclusion_manifest.wire()
                or plan["rightsSha256"] != evidence.rights_evidence.sha256):
            fail("plan_evidence_mismatch")
        _pin(evidence.exclusion_manifest, 2_000_000)
        registry = Authority(Path(binding.source_registry_file.path)).registry
        source = next((s for s in registry.sources if s.source_id == binding.native_export.source_id), None)
        if source is None or source.grant.wire() != config.grant.wire():
            fail("plan_grant_mismatch")
        return config, source


def _corpus_proof(binding, exported, store, config, source):
    """Revalidate saved native bytes, not a gate-version assertion or a recovery writer."""
    from .collection import Fetched
    try:
        observation = exported["observation"]
        collected = Collected.model_validate(observation["collection"])
        identifier = article_id(observation["url"], config, binding.selection.channel)
        collection_id = "item-" + identifier
        if (source.adapter != "collected-http" or binding.native_export.round_id != collection_id
                or collected.collection_id != collection_id or observation["publisher"] is None
                or binding.selection.publication_day is None
                or collected.receipt.file != f"collections/{collection_id}/receipts/{collected.receipt.sha256}.json"
                or collected.network != ("synthetic_loopback" if config.policy.synthetic_loopback else "external")):
            fail("native_proof_mismatch")
        root = absolute(source.input_root)
        receipt_raw = read_file(root / collected.receipt.file, 2_000_000)
        if byte_hash(receipt_raw) != collected.receipt.sha256:
            fail("native_proof_mismatch")
        receipt = Receipt.model_validate(decode(receipt_raw))
        row = store.one("SELECT request FROM rounds WHERE id=? AND source=?",
                        (binding.native_export.round_id, binding.native_export.source_id))
        request = Run.model_validate(decode(row["request"]))
        expected = (collection_id, binding.native_export.source_id, request.scope_id, identifier,
                    exported["grant"]["grantId"], exported["grant"]["revision"], observation["url"])
        actual = (receipt.collection_id, receipt.source_id, receipt.scope_id, receipt.candidate_id,
                  receipt.grant_id, receipt.grant_revision, receipt.requested_url)
        observed = (collected.final_url, collected.fetched_at, collected.http_status, collected.content_type,
                    observation["mediaType"], collected.body_sha256, collected.network)
        received = (receipt.final_url, receipt.fetched_at, receipt.http_status, receipt.content_type,
                    receipt.media_type, receipt.body_sha256, receipt.network)
        if (expected != actual or observed != received or receipt.redirects
                or request.scope_id != identifier or exported["locatorMetadata"]["rawHash"] != collected.body_sha256):
            fail("native_proof_mismatch")
        body = read_file(root / "collections" / collection_id / "bodies" / (collected.body_sha256 + ".bin"),
                         min(MAX_RAW, config.policy.max_response_bytes))
        if byte_hash(body) != collected.body_sha256 or len(body) != receipt.body_bytes:
            fail("native_proof_mismatch")
        rights = decode(read_file(absolute(config.state_dir) / "items" / identifier / "rights.json", 2_000_000))
        candidate = {"newsId": identifier, "channel": binding.selection.channel, "url": observation["url"],
                     "title": observation["title"], "publisher": observation["publisher"],
                     "publicationDay": binding.selection.publication_day}
        fetched = Fetched(receipt.requested_url, receipt.final_url, receipt.http_status, receipt.content_type,
                          receipt.media_type, body, {}, [], [], 0, fetched_at=receipt.fetched_at)
        if canonical(rights) != canonical(validate_article(fetched, candidate, config)):
            fail("native_proof_mismatch")
    except (OSError, ValueError, TypeError, KeyError, IndexError, IngestionFailure) as exc:
        raise IngestionFailure("review_native_proof_mismatch") from exc


def _native(binding, policy):
    _pin(binding.source_registry_file, 2_000_000)
    boundary = _evidence(binding)
    store = Store(Path(binding.ingestion_state_dir), existing=True)
    try:
        current = Ingestor(store, Authority(Path(binding.source_registry_file.path))).export(binding.native_export, require_store=True)
        raw = _pin(binding.original_export, MAX_EXPORT)
        exported = decode(raw)
        NativeDocument.model_validate(exported)
        if _selector(exported["observation"]) != binding.native_export.wire():
            fail("selector_mismatch")
        _metadata(binding.selection, exported["observation"], policy)
        if canonical(exported) != canonical(current):
            fail("stale_export")
        if boundary is not None:
            _corpus_proof(binding, current, store, *boundary)
    finally:
        store.close()
    _pin(binding.source_registry_file, 2_000_000)
    _evidence(binding)
    return raw, exported


def _reference(file, raw):
    return {"file": file, "sha256": byte_hash(raw), "bytes": len(raw)}


def _line(value):
    return (canonical(value) + "\n").encode("utf-8")


def _write(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())


def _directory(path):
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _publish(source, target, parent):
    # The opened parent, not a pathname that could be rebound, owns both names.
    libc = ctypes.CDLL(None, use_errno=True)
    a, b = os.fsencode(source.name), os.fsencode(target.name)
    if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        failed = libc.renameatx_np(parent, a, parent, b, 4) != 0
    elif hasattr(libc, "renameat2"):
        failed = libc.renameat2(parent, a, parent, b, 1) != 0
    else:
        fail("publication_unsupported")
    if failed:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _reclaim(source, parent, owned):
    quarantine = source.with_name(".review-quarantine-" + os.urandom(16).hex())
    try:
        _publish(source, quarantine, parent)
    except FileNotFoundError:
        return None
    moved = os.stat(quarantine.name, dir_fd=parent, follow_symlinks=False)
    if (moved.st_dev, moved.st_ino) != (owned.st_dev, owned.st_ino):
        # This was a foreign replacement. Restore only if its original name is free.
        try:
            _publish(quarantine, source, parent)
        except FileExistsError:
            pass  # Leave the observable quarantine intact rather than clobber either owner.
        return None
    os.fsync(parent)
    return quarantine


def _same_inode(actual, expected):
    return (actual.st_dev, actual.st_ino) == (expected.st_dev, expected.st_ino)


def _empty_owned(directory):
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                try:
                    identity = os.fstat(child)
                    if not _same_inode(entry.stat(follow_symlinks=False), identity):
                        continue
                    _empty_owned(child)
                    if _same_inode(os.stat(entry.name, dir_fd=directory, follow_symlinks=False), identity):
                        os.rmdir(entry.name, dir_fd=directory)
                finally:
                    os.close(child)
            else:
                os.unlink(entry.name, dir_fd=directory)


def _remove_owned(parent, path, owned):
    try:
        directory = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    except FileNotFoundError:
        return
    try:
        if not _same_inode(os.fstat(directory), owned):
            return
        _empty_owned(directory)
        try:
            visible = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        if _same_inode(visible, owned):
            os.rmdir(path.name, dir_fd=parent)
    finally:
        os.close(directory)


def _namespace(output, bindings_path, bindings):
    paths = [bindings_path]
    for b in bindings.documents:
        paths += [Path(b.ingestion_state_dir), Path(b.original_export.path).parent, Path(b.source_registry_file.path), Path(b.authority_evidence.rights_evidence.path)]
        _pin(b.source_registry_file, 2_000_000)
        authority = Authority(Path(b.source_registry_file.path))
        source = next((s for s in authority.registry.sources if s.source_id == b.native_export.source_id), None)
        if source is not None:
            paths.append(absolute(source.input_root))
        if b.authority_evidence.plan_file:
            paths += [Path(b.authority_evidence.plan_file.path).parent, Path(b.authority_evidence.exclusion_manifest.path)]
    checkout = Path(__file__).resolve().parents[4]
    for p in [checkout, *reserved_state_roots(), *paths]:
        if output == p or output.is_relative_to(p) or p.is_relative_to(output):
            fail("namespace_overlap")
    if os.path.lexists(output):
        fail("output_exists")


def prepare(bindings_path: Path, output: Path):
    bindings_path, output = absolute(str(bindings_path)), absolute(str(output))
    raw_bindings = read_file(bindings_path, MAX_BINDINGS)
    bindings = Bindings.model_validate(decode(raw_bindings))
    _namespace(output, bindings_path, bindings)
    parent = _directory(output.parent)
    staging = None
    published = False
    owned = None
    try:
        staging = Path(tempfile.mkdtemp(prefix=".review-stage-", dir=output.parent))
        owned = os.stat(staging.name, dir_fd=parent, follow_symlinks=False)
        (staging / "documents").mkdir(mode=0o700)
        records, total, seen = [], 0, set()
        for binding in bindings.documents:
            raw, exported = _native(binding, bindings.selection_policy)
            case_id = "case-" + digest(binding.native_export.wire())
            if case_id in seen:
                fail("duplicate_observation")
            seen.add(case_id)
            total += len(raw)
            if total > MAX_TOTAL:
                fail("total_size")
            filename = "documents/" + byte_hash(raw) + ".json"
            _write(staging / filename, raw)
            e = binding.authority_evidence
            records.append(Record.model_validate({"caseId": case_id, "export": _reference(filename, raw),
                "nativeExport": binding.native_export.wire(), "observation": exported["observation"], "grant": exported["grant"],
                "authorityPins": {"registrySha256": binding.source_registry_file.sha256, "rightsEvidenceSha256": e.rights_evidence.sha256,
                    "planSha256": e.plan_file.sha256 if e.plan_file else None, "exclusionSha256": e.exclusion_manifest.sha256 if e.exclusion_manifest else None, "kind": e.kind},
                "selection": binding.selection.wire()}))
        records.sort(key=_order)
        source_sha = byte_hash(raw_bindings)
        inputs = Inputs(schemaVersion="zoop-corpus-review-inputs-1", sourceInputSha256=source_sha,
                        documents=records, selection=choose(records, bindings.selection_policy))
        inputs_raw = _line(inputs.wire())
        if len(inputs_raw) > MAX_JSON:
            fail("inputs_size")
        inputs_sha = byte_hash(inputs_raw)
        _write(staging / "inputs.json", inputs_raw)
        template = {"schemaVersion": "zoop-corpus-review-annotations-1", "inputsSha256": inputs_sha,
                    "cases": [{"caseId": case_id, "status": "unreviewed", "reviewerId": None, "reviewedAt": None,
                               "graphNotes": None, "ragQuestions": None, "exclusionReason": None, "evidenceSpans": None}
                              for case_id in inputs.selection.selected_case_ids]}
        _write(staging / "annotations.template.json", _line(template))
        manifest = Manifest(schemaVersion="zoop-corpus-review-pack-1", createdAt=now(), sourceInputSha256=source_sha,
            immutableInputsSha256=inputs_sha, inputs=FileReference.model_validate(_reference("inputs.json", inputs_raw)),
            documentCount=len(records), reviewCount=len(template["cases"]), limits=LIMITS)
        _write(staging / "manifest.json", _line(manifest.wire()))
        for folder in (staging / "documents", staging):
            fd = _directory(folder)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

        def guard():
            if read_file(bindings_path, MAX_BINDINGS) != raw_bindings:
                fail("bindings_changed")
            # Connections are opened and closed one at a time, including the final live-rights pass.
            for binding in bindings.documents:
                _native(binding, bindings.selection_policy)

        guard()
        _publish(staging, output, parent)
        published = True
        visible = os.stat(output.name, dir_fd=parent, follow_symlinks=False)
        if (visible.st_dev, visible.st_ino) != (owned.st_dev, owned.st_ino):
            fail("output_ownership_changed")
        os.fsync(parent)
        guard()
        return _summary(manifest, "prepared")
    except BaseException:
        if published:
            reclaimed = _reclaim(output, parent, owned)
            if reclaimed is not None:
                staging = reclaimed
                published = False
        raise
    finally:
        try:
            if staging is not None and not published and owned is not None:
                reclaimed = _reclaim(staging, parent, owned)
                if reclaimed is not None:
                    _remove_owned(parent, reclaimed, owned)
        finally:
            os.close(parent)


def _summary(manifest, state):
    return {"state": state, "documents": manifest.document_count, "reviewDocuments": manifest.review_count,
            "sourceInputSha256": manifest.source_input_sha256, "inputsSha256": manifest.immutable_inputs_sha256}


def _read_ref(root, ref):
    raw = read_file(root / ref.file, MAX_JSON)
    if len(raw) != ref.bytes or byte_hash(raw) != ref.sha256:
        fail("file_integrity")
    return raw


def _verify(root):
    root = absolute(str(root))
    fd = _directory(root)
    os.close(fd)
    # The mutable template is deliberately neither opened nor stat'ed, and may be removed.
    if not {"manifest.json", "inputs.json", "documents"} <= set(os.listdir(root)) <= {"manifest.json", "inputs.json", "documents", "annotations.template.json"}:
        fail("pack_shape")
    manifest = Manifest.model_validate(decode(read_file(root / "manifest.json", MAX_JSON)))
    timestamp(manifest.created_at)
    if manifest.limits != LIMITS or manifest.inputs.file != "inputs.json" or manifest.inputs.sha256 != manifest.immutable_inputs_sha256:
        fail("manifest_binding")
    inputs = Inputs.model_validate(decode(_read_ref(root, manifest.inputs)))
    if inputs.source_input_sha256 != manifest.source_input_sha256 or len(inputs.documents) != manifest.document_count:
        fail("inputs_binding")
    if inputs.selection != choose(inputs.documents, inputs.selection.policy) or len(inputs.selection.selected_case_ids) != manifest.review_count:
        fail("selection_binding")
    if inputs.documents != sorted(inputs.documents, key=_order):
        fail("observation_order")
    seen, files, documents, total = set(), set(), {}, 0
    for record in inputs.documents:
        if record.case_id != "case-" + digest(record.native_export.wire()) or record.case_id in seen:
            fail("case_identity")
        seen.add(record.case_id)
        name = "documents/" + record.export.sha256 + ".json"
        if record.export.file != name or name in files:
            fail("document_path")
        files.add(name)
        raw = _read_ref(root, record.export)
        total += len(raw)
        if len(raw) > MAX_EXPORT or total > MAX_TOTAL:
            fail("total_size")
        data = decode(raw)
        native = NativeDocument.model_validate(data)
        if (_selector(data["observation"]) != record.native_export.wire() or data["observation"] != record.observation
                or native.grant != record.grant):
            fail("observation_binding")
        pins = record.authority_pins
        if (pins.kind == "native-corpus-plan") != (pins.plan_sha256 is not None and pins.exclusion_sha256 is not None):
            fail("evidence_binding")
        if pins.kind == "legacy-operator-evidence" and (pins.plan_sha256 is not None or pins.exclusion_sha256 is not None):
            fail("evidence_binding")
        _metadata(record.selection, record.observation, inputs.selection.policy)
        documents[record.case_id] = native.document
    fd = _directory(root / "documents")
    os.close(fd)
    if set(os.listdir(root / "documents")) != {Path(f).name for f in files}:
        fail("documents_shape")
    return manifest, inputs, documents


def verify(root):
    manifest, _, _ = _verify(root)
    return {**_summary(manifest, "verified"), "scope": "portable-integrity-only; not current authorization or publisher authenticity; annotations unread"}


def annotations_check(root, annotations_path):
    root, annotations_path = absolute(str(root)), absolute(str(annotations_path))
    if annotations_path == root or annotations_path.is_relative_to(root):
        fail("annotations_require_separate_path")
    manifest, inputs, documents = _verify(root)
    annotations = Annotations.model_validate(decode(read_file(annotations_path, MAX_JSON)))
    if annotations.inputs_sha256 != manifest.immutable_inputs_sha256:
        fail("annotations_binding")
    expected = set(inputs.selection.selected_case_ids)
    ids = [row.case_id for row in annotations.cases]
    if len(set(ids)) != len(ids) or set(ids) != expected:
        fail("annotation_cases")
    counts = {"unreviewed": 0, "reviewed": 0, "excluded": 0}
    for row in annotations.cases:
        counts[row.status] += 1
        document = documents[row.case_id]
        for span in row.evidence_spans or []:
            if (span.document_id != document.document_id or span.document_version != document.document_version
                    or not 0 <= span.start < span.end <= len(document.text)
                    or document.text[span.start:span.end] != span.quote
                    or not any(r.start <= span.start < span.end <= r.end for r in document.raw_locators)):
                fail("evidence_span")
    return {"state": "checked", "inputsSha256": manifest.immutable_inputs_sha256, "counts": counts,
            "scope": "operator claims and exact evidence bindings only; no quality scores or verified human adjudication"}
