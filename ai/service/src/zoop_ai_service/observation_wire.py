"""Closed native ingestion export wire with exact selector and content-hash checks."""
from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

from .handoff_runtime import canonical

SCHEMA = "zoop-ingestion-s2-1"
MAX_INPUT = 2_000_000
Hash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Name = Annotated[str, StringConstraints(min_length=1)]


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class NativeWire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, extra="forbid", strict=True)

    def wire(self) -> dict:
        return self.model_dump(by_alias=True, mode="json", exclude_unset=True)


class ObservationExportRequest(NativeWire):
    schema_version: Literal["zoop-ingestion-s2-1"]
    round_id: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=200)
    page: int = Field(ge=0)
    ordinal: int = Field(ge=0)
    document_id: Name
    raw_version: Name
    document_version: Name


class NativeFileRef(NativeWire):
    file: str = Field(min_length=1, max_length=500)
    sha256: Hash


class NativePublished(NativeWire):
    raw: str | None
    precision: Literal["instant", "day", "unresolved", "unknown"]
    date: str | None
    basis: str = Field(min_length=1, max_length=200)


class NativeCollection(NativeWire):
    provenance: Literal["collected_http"]
    collection_id: str = Field(min_length=1, max_length=100)
    receipt: NativeFileRef
    fetched_at: str
    final_url: str = Field(min_length=1, max_length=4000)
    http_status: int = Field(ge=200, le=299)
    content_type: str = Field(max_length=200)
    body_sha256: Hash
    document_kind: Literal["news", "disclosure"]
    network: Literal["external", "synthetic_loopback"]
    published: NativePublished


class NativeObservation(NativeWire):
    round_id: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=200)
    page: int = Field(ge=0)
    ordinal: int = Field(ge=0)
    page_id: str = Field(min_length=1, max_length=200)
    observed_at: str
    document_id: Name
    raw_version: Name
    document_version: Name
    url: str = Field(min_length=1, max_length=4000)
    title: str = Field(max_length=2000)
    published_at: str | None
    modified_at: str | None
    source_revision: str | None
    media_type: Literal["text/html", "application/pdf"]
    publisher: str | None = Field(default=None, min_length=1, max_length=200)
    language: str | None = Field(default=None, min_length=2, max_length=35)
    provenance: Literal["collected_http"] | None = None
    collection: NativeCollection | None = None

    @model_validator(mode="after")
    def optional_fields(self):
        for key in ("publisher", "language", "provenance", "collection"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError("optional native fields are absent, never null")
        if (self.provenance is None) != (self.collection is None):
            raise ValueError("collection provenance required together")
        return self


class NativeGrant(NativeWire):
    grant_id: Name
    revision: Name


class NativeLocator(NativeWire):
    locator_id: Name
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class NativeProjection(NativeWire):
    document_id: Name
    document_version: Name
    source_id: Name
    text_artifact_id: Name
    input_kind: Literal["body"]
    cleaner_version: Literal["exact-copy-1"]
    text: str = Field(min_length=1, max_length=500_000)
    source_hash: Hash
    raw_locators: list[NativeLocator] = Field(min_length=1)


class NativeParserProfile(NativeWire):
    parser: Name
    lxml: Name
    pypdf: Name
    mapping_version: Name
    html_decoding: Name
    html_scope: Name
    pdf_extraction: Name
    article_xpath: str | None = Field(alias="articleXPath")


class NativeLocatorMetadata(NativeWire):
    raw_artifact_id: Name
    raw_hash: Hash
    raw_version: Name
    representation_hash: Hash
    mapping_hash: Hash
    parser_profile: NativeParserProfile
    limitations: list[str]
    page_count: int | None = Field(default=None, ge=1)
    empty_page_count: int | None = Field(default=None, ge=0)


class ObservationExport(NativeWire):
    schema_version: Literal["zoop-ingestion-s2-1"]
    observation: NativeObservation
    grant: NativeGrant
    document: NativeProjection
    locator_metadata: NativeLocatorMetadata

    @model_validator(mode="after")
    def integrity(self):
        o, d, m = self.observation, self.document, self.locator_metadata
        if any(getattr(o, key) != getattr(d, key) for key in ("document_id", "document_version", "source_id")) or o.raw_version != m.raw_version:
            raise ValueError("native identity mismatch")
        if d.text_artifact_id != "text-" + d.document_version or m.raw_artifact_id != "raw-" + m.raw_hash:
            raise ValueError("native artifact mismatch")
        if digest(d.text) != d.source_hash:
            raise ValueError("native source hash mismatch")
        if digest([d.document_id, m.raw_version, m.parser_profile.wire(), d.cleaner_version, d.source_hash, m.mapping_hash]) != d.document_version:
            raise ValueError("native document version mismatch")
        previous = 0
        for locator in d.raw_locators:
            if not previous <= locator.start < locator.end <= len(d.text):
                raise ValueError("native locator bounds mismatch")
            run = {"start": locator.start, "end": locator.end}
            if locator.locator_id != "loc-" + digest([d.document_version, run, m.mapping_hash]):
                raise ValueError("native locator hash mismatch")
            previous = locator.end
        return self
