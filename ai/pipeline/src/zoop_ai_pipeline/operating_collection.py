"""Pinned completed public collections as ordinary, registration-only operating inputs."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from .collection_contracts import COLLECTION_ID
from .extraction_contracts import Catalogue, ObservationRef, Provenance, Snapshot, Submit, TopicConfig
from .ingestion import Ingestor, Store
from .ingestion_contracts import (MAX_INPUT, Authority, Export, FileRef, IngestionFailure, Item, Manifest,
                                 Run, Wire, canonical, digest, read_file, reserved_state_roots, timestamp)
from .ingestion_parsers import normalize_url
from .live_funding import stage_allowances

REQUEST = "zoop-operating-collection-registration-1"
RESULT = "zoop-operating-collection-registration-result-1"
Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
OperatingId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,200}$")]
CollectionId = Annotated[str, StringConstraints(pattern=COLLECTION_ID)]


class SetRequest(Wire):
    candidate_id: str = Field(min_length=1, max_length=200)
    set_id: OperatingId
    extraction_job_id: OperatingId
    relation_job_id: OperatingId
    stage_allowances: dict[str, int]

    @field_validator("stage_allowances")
    @classmethod
    def allowances(cls, value):
        return stage_allowances(value)


class Request(Wire):
    schema_version: Literal["zoop-operating-collection-registration-1"]
    sources: str
    ingestion_state_directory: str
    source_id: str = Field(min_length=1, max_length=200)
    scope_id: str = Field(min_length=1, max_length=200)
    collection: FileRef
    round_id: str = Field(min_length=1, max_length=200)
    checkpoint_revision: int = Field(ge=0)
    provenance: Provenance
    prompt_version: str = Field(min_length=1, max_length=200)
    catalogue: Catalogue
    snapshot: Snapshot
    topic: TopicConfig | None
    sets: list[SetRequest] = Field(min_length=1, max_length=50)

    @field_validator("sources", "ingestion_state_directory")
    @classmethod
    def absolute(cls, value):
        path = Path(value)
        if not path.is_absolute() or path.resolve() != path:
            raise ValueError("operating_path_invalid")
        return value

    @model_validator(mode="after")
    def identity(self):
        parts = self.collection.file.split("/")
        if len(parts) != 3 or parts[0] != "collections" or parts[2] != "collection.json":
            raise ValueError("collection result path required")
        if re.fullmatch(COLLECTION_ID, parts[1]) is None:
            raise ValueError("collection identity invalid")
        if self.provenance.execution_mode != "live":
            raise ValueError("operating_live_input_required")
        jobs = [job for unit in self.sets for job in (unit.extraction_job_id, unit.relation_job_id)]
        if (len({unit.candidate_id for unit in self.sets}) != len(self.sets)
                or len({unit.set_id for unit in self.sets}) != len(self.sets) or len(set(jobs)) != len(jobs)):
            raise ValueError("operating_manifest_duplicate")
        return self

    @property
    def collection_id(self):
        return self.collection.file.split("/")[1]

    @property
    def context(self):
        return {"sources": self.sources, "ingestionStateDirectory": self.ingestion_state_directory}

    @property
    def binding_name(self):
        return "collection-batch:" + digest({"sourceId": self.source_id, "collectionId": self.collection_id})


class GrantRef(Wire):
    grant_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)


class TargetResult(Wire):
    candidate_id: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=4000)
    outcome: Literal["collected", "failed"]
    code: str | None
    body_sha256: Sha256 | None
    receipt_sha256: Sha256 | None


class Usage(Wire):
    requests: int = Field(ge=0)
    bytes: int = Field(ge=0)
    targets: int = Field(ge=1, le=50)
    collected: int = Field(ge=0, le=50)


class Collection(Wire):
    schema_version: Literal["zoop-collection-1"]
    collection_id: CollectionId
    request_digest: Sha256
    source_id: str
    scope_id: str
    provenance: Literal["collected_http"]
    state: Literal["complete", "partial", "failed"]
    started_at: str
    completed_at: str
    grant: GrantRef
    manifest: FileRef
    targets: list[TargetResult] = Field(min_length=1, max_length=50)
    usage: Usage
    user_agent: str | None = Field(default=None, min_length=1)

    @field_validator("started_at", "completed_at")
    @classmethod
    def instant(cls, value):
        timestamp(value)
        return value

    @field_validator("user_agent")
    @classmethod
    def optional_agent(cls, value):
        if value is None:
            raise ValueError("userAgent may be omitted, not null")
        return value


class PagePayload(Wire):
    items: list[Item] = Field(min_length=1, max_length=50)
    more: bool
    next_cursor: None


class Error(Wire):
    code: str


class Refusal(Wire):
    schema_version: Literal["zoop-operating-collection-registration-result-1"]
    error: Error


class Withheld(Refusal):
    local_progress_may_exist: Literal[True]


class CollectionPin(Wire):
    collection_id: CollectionId
    result_sha256: Sha256
    manifest_sha256: Sha256
    state: Literal["complete"]


class Registration(Wire):
    registered: list[OperatingId]
    interrupted_set_id: OperatingId | None
    not_attempted: list[OperatingId]


class Unit(Wire):
    set_id: OperatingId
    extraction: Submit
    relation_job_id: OperatingId
    stage_allowances: dict[str, int]
    ingestion_state_directory: str
    sources: str


class OperatingManifest(Wire):
    schema_version: Literal["zoop-operating-input-manifest-1"]
    sets: list[Unit] = Field(min_length=1, max_length=50)


class Result(Wire):
    schema_version: Literal["zoop-operating-collection-registration-result-1"]
    status: Literal["registered", "incomplete"]
    request_digest: Sha256
    collection: CollectionPin
    # Native result/disposition metadata retains the ingestion owner's wire format.
    ingestion: dict | None
    manifest: OperatingManifest | None
    registration: Registration
    error: Error | None


def refusal(code: str, *, progress: bool = False) -> dict:
    value = {"schemaVersion": RESULT, "error": {"code": code}}
    if progress:
        return Withheld.model_validate({**value, "localProgressMayExist": True}).wire()
    return Refusal.model_validate(value).wire()


def request(value: dict) -> Request:
    if len(canonical(value).encode("utf-8")) > MAX_INPUT:
        raise IngestionFailure("input_size_or_type_invalid")
    return Request.model_validate(value)


def boundaries(batch: Request, config: dict, *, files: tuple[Path, ...] = (), input_root: str | None = None):
    ingestion = Path(batch.ingestion_state_directory)
    forbidden = [Path(config[key]) for key in ("ledgerDirectory", "stateDirectory")]
    forbidden += [Path(batch.sources), *files, *reserved_state_roots()]
    if input_root is not None:
        forbidden.append(Path(input_root).resolve())
    if any(ingestion == path or ingestion.is_relative_to(path) or path.is_relative_to(ingestion) for path in forbidden):
        raise IngestionFailure("operating_namespace_conflict")


def read_batch(path: Path, config: dict, config_path: Path) -> dict:
    value = json.loads(read_file(path, MAX_INPUT))
    batch = request(value)
    boundaries(batch, config, files=(path.resolve(), config_path.resolve()))
    return value


def load_collection(batch: Request, authority: Authority, config: dict) -> tuple[Collection, Path, list[Item]]:
    source, scope = authority.check(batch.source_id, batch.scope_id)
    if source.adapter != "collected-http":
        raise IngestionFailure("source_adapter_mismatch")
    boundaries(batch, config, input_root=source.input_root)
    collection = Collection.model_validate_json(authority.fixture(source, batch.collection, MAX_INPUT))
    if collection.state != "complete":
        raise IngestionFailure("operating_collection_not_complete")
    base = f"collections/{batch.collection_id}"
    if ((collection.source_id, collection.scope_id, collection.collection_id) != (batch.source_id, batch.scope_id, batch.collection_id)
            or collection.manifest.file != f"{base}/manifest.json"
            or [target.candidate_id for target in collection.targets] != [unit.candidate_id for unit in batch.sets]
            or collection.usage.targets != len(batch.sets) or collection.usage.collected != len(batch.sets)):
        raise IngestionFailure("operating_collection_invalid")
    for target in collection.targets:
        if target.outcome != "collected" or target.code is not None or target.body_sha256 is None or target.receipt_sha256 is None:
            raise IngestionFailure("operating_collection_not_complete")
    manifest = Manifest.model_validate_json(authority.fixture(source, collection.manifest, MAX_INPUT))
    if (manifest.source_id, manifest.scope_id) != (batch.source_id, batch.scope_id) or len(manifest.pages) != 1:
        raise IngestionFailure("operating_collection_invalid")
    page = manifest.pages[0]
    if (page.page_id != f"collection-{batch.collection_id}" or page.cursor != scope.initial_cursor
            or page.status != "ok" or not page.terminal or page.next_cursor is not None or page.coverage_through is not None
            or page.response.file != f"{base}/page-0.json"):
        raise IngestionFailure("operating_collection_invalid")
    payload = PagePayload.model_validate_json(authority.fixture(source, page.response, MAX_INPUT))
    if payload.more or len(payload.items) != len(collection.targets):
        raise IngestionFailure("operating_collection_invalid")
    urls, documents = set(), {}
    for target, item in zip(collection.targets, payload.items):
        acquired = item.collection
        url = normalize_url(item.url, source.allowed_hosts)
        if (target.url != url or url in urls or item.candidate_id != target.candidate_id or item.private is not None
                or acquired is None or acquired.collection_id != batch.collection_id
                or acquired.body_sha256 != target.body_sha256 or item.body_ref != target.body_sha256
                or acquired.receipt.wire() != {"file": f"{base}/receipts/{target.receipt_sha256}.json", "sha256": target.receipt_sha256}):
            raise IngestionFailure("operating_collection_invalid")
        if acquired.network == "synthetic_loopback" and batch.provenance.source_kind != "synthetic":
            raise IngestionFailure("collection_provenance_conflict")
        urls.add(url)
        documents[item.body_ref] = {"file": f"{base}/bodies/{target.body_sha256}.bin", "sha256": target.body_sha256}
    if {key: ref.wire() for key, ref in manifest.documents.items()} != documents:
        raise IngestionFailure("operating_collection_invalid")
    authority.check(batch.source_id, batch.scope_id, config=source.configuration(scope))
    return collection, Path(source.input_root) / collection.manifest.file, payload.items


def prepare(batch: Request, collection: Collection, path: Path, authority: Authority) -> dict:
    run = Run.model_validate({"schemaVersion": "zoop-ingestion-s2-1", "roundId": batch.round_id,
        "sourceId": batch.source_id, "scopeId": batch.scope_id, "window": None,
        "checkpointRevision": batch.checkpoint_revision, "fixtureManifestHash": collection.manifest.sha256,
        "cleanerVersion": "exact-copy-1"})
    store = Store(Path(batch.ingestion_state_directory))
    try:
        engine = Ingestor(store, authority)
        result = engine.run(run, path)
        # Keep the complete native inventory even if its default result page size changes.
        while result["pagination"]["nextOffset"] is not None:
            page = engine.result(batch.round_id, batch.source_id, offset=result["pagination"]["nextOffset"])
            result["documentRefs"].extend(page["documentRefs"])
            result["pages"].extend(page["pages"])
            result["pagination"]["nextOffset"] = page["pagination"]["nextOffset"]
        result["pagination"]["limit"] = max(result["pagination"]["limit"], len(result["documentRefs"]), len(result["pages"]))
        return result
    finally:
        store.close()


def observations(batch: Request, collection: Collection, items: list[Item], result: dict, authority: Authority) -> list[ObservationRef]:
    counts = result["counts"]
    if (result["state"] != "complete" or result["checkedWindow"] is not None or result["failure"] is not None
            or counts["discoveredCandidates"] != len(items) or counts["textReady"] != len(items)
            or counts["held"] or counts["unfinished"] or len(result["documentRefs"]) != len(items)
            or result["pages"] != [{"ordinal": 0, "pageId": f"collection-{batch.collection_id}", "status": "ok", "complete": True}]):
        raise IngestionFailure(result["failure"]["code"] if result["failure"] else "operating_collection_observations_incomplete")
    refs = []
    store = Store(Path(batch.ingestion_state_directory), existing=True)
    try:
        engine = Ingestor(store, authority)
        for ordinal, (row, target, item) in enumerate(zip(result["documentRefs"], collection.targets, items)):
            if (row["page"] != 0 or row["ordinal"] != ordinal
                    or any(row[key] is not None for key in ("hold", "error", "ambiguity", "failure"))
                    or any(row[key] is None for key in ("documentId", "rawVersion", "documentVersion"))):
                raise IngestionFailure("operating_collection_observations_incomplete")
            ref = ObservationRef.model_validate({"roundId": batch.round_id, "sourceId": batch.source_id,
                **{key: row[key] for key in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")}})
            exported = engine.export(Export.model_validate(ref.export_wire()), require_store=True)
            observation = exported["observation"]
            if observation["url"] != target.url or observation.get("collection") != item.collection.wire():
                raise IngestionFailure("operating_collection_observations_incomplete")
            refs.append(ref)
        return refs
    finally:
        store.close()


def authorize(batch: Request, authority: Authority, refs: list[ObservationRef]) -> None:
    """Recheck exact current rights, including existing S2 jobs whose admission returns early."""
    authority.check(batch.source_id, batch.scope_id, ("read", "store", "quote-display"))
    refs = [*refs, *(member.observation for event in batch.snapshot.events for member in event.members)]
    if not refs:
        return
    store = Store(Path(batch.ingestion_state_directory), existing=True)
    try:
        engine = Ingestor(store, authority)
        seen = set()
        for ref in refs:
            key = canonical(ref.wire())
            if key not in seen:
                engine.export(Export.model_validate(ref.export_wire()), require_store=True)
                seen.add(key)
        authority.check(batch.source_id, batch.scope_id, ("read", "store", "quote-display"))
    finally:
        store.close()


def operating_manifest(batch: Request, refs: list[ObservationRef]) -> dict:
    # Import at the owner boundary, after operating has finished defining its unchanged manifest validator.
    from .operating import MANIFEST, MAX_MANIFEST_BYTES, manifest

    value = {"schemaVersion": MANIFEST, "sets": [{"setId": unit.set_id,
        "extraction": {"schemaVersion": "zoop-extraction-s2-2", "jobId": unit.extraction_job_id,
            "provenance": batch.provenance.wire(), "promptVersion": batch.prompt_version,
            "incoming": ref.wire(), "catalogue": batch.catalogue.wire(), "snapshot": batch.snapshot.wire(),
            "topic": batch.topic.wire() if batch.topic is not None else None},
        "relationJobId": unit.relation_job_id, "stageAllowances": unit.stage_allowances,
        **batch.context} for unit, ref in zip(batch.sets, refs)]}
    if len(canonical(value).encode("utf-8")) > MAX_MANIFEST_BYTES:
        raise IngestionFailure("operating_input_limit")
    manifest(value)
    return value
