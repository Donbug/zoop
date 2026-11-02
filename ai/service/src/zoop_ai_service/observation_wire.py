"""Closed native ingestion export wire, independent of the installed pipeline package.

The service checks the exact selector and native content hashes, then returns the original
JSON, retaining absent optional fields. Rights remain the installed CLI's responsibility.
"""
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


ProjectionProfile = Literal["korea-kogl1-caption-boundary-1", "eu-commission-pdf-body-ranges-1"]


class NativeProjectionDescriptor(NativeWire):
    profile: ProjectionProfile
    descriptor_hash: Hash


class NativeProjectionProvenance(NativeProjectionDescriptor):
    parent_document_version: Hash
    boundary_decision_revision: str = Field(min_length=1, max_length=200)
    rights_receipt_hash: Hash


class NativeExcludedSlot(NativeWire):
    dom_path: str = Field(min_length=1)
    slot: Literal["text", "tail"]


class NativeCaptionProjection(NativeProjectionProvenance):
    profile: Literal["korea-kogl1-caption-boundary-1"]
    excluded_source_slots: list[NativeExcludedSlot] = Field(min_length=1)


class NativeRetainedRange(NativeWire):
    page_number: int = Field(gt=0)
    page_text_hash: Hash
    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)
    text_utf8_sha256: Hash
    review_unit_id: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def bounds(self):
        if self.source_start >= self.source_end:
            raise ValueError("positive source interval required")
        return self


class NativePdfProjection(NativeProjectionProvenance):
    profile: Literal["eu-commission-pdf-body-ranges-1"]
    parent_document_id: Name
    parent_raw_version: Hash
    selection_hash: Hash
    retained_source_ranges: list[NativeRetainedRange] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def selection(self):
        previous = None
        for span in self.retained_source_ranges:
            if previous and (span.page_number < previous.page_number or
                             (span.page_number == previous.page_number and span.source_start < previous.source_end)):
                raise ValueError("disjoint source-ordered ranges required")
            previous = span
        if digest([span.wire() for span in self.retained_source_ranges]) != self.selection_hash:
            raise ValueError("native selection hash mismatch")
        return self


NativeTextProjection = Annotated[NativeCaptionProjection | NativePdfProjection, Field(discriminator="profile")]


class NativeParserProfile(NativeWire):
    parser: Name
    lxml: Name
    pypdf: Name
    mapping_version: Name
    html_decoding: Name
    html_scope: Name
    pdf_extraction: Name
    article_xpath: str | None = Field(alias="articleXPath")
    text_projection: NativeProjectionDescriptor | None = None


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
    text_projection: NativeTextProjection | None = None


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
        descriptor, projection = m.parser_profile.text_projection, m.text_projection
        if ("text_projection" in m.parser_profile.model_fields_set and descriptor is None or
                "text_projection" in m.model_fields_set and projection is None or
                (descriptor is None) != (projection is None)):
            raise ValueError("native projection metadata required together")
        if projection is not None:
            if (descriptor.profile, descriptor.descriptor_hash) != (projection.profile, projection.descriptor_hash):
                raise ValueError("native projection descriptor mismatch")
            if isinstance(projection, NativePdfProjection):
                if (o.media_type != "application/pdf" or projection.parent_document_id != d.document_id or
                        projection.parent_raw_version != m.raw_version or m.page_count is None or
                        any(span.page_number > m.page_count for span in projection.retained_source_ranges)):
                    raise ValueError("native PDF projection identity mismatch")
            elif o.media_type != "text/html":
                raise ValueError("native caption projection media mismatch")
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
