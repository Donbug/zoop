"""Prototype-owned offline S2-2 wire contracts. Not an S1 schema alias, HTTP route or application document API.

All text offsets are Python Unicode code points over the exact prepared ingestion text (never bytes/UTF-16).
Event candidates, topic candidates and prepared documents are separate identities; none is an approved result.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from .ingestion_contracts import SCHEMA as INGESTION_SCHEMA
from .ingestion_contracts import Wire, canonical, digest

__all__ = ["canonical", "digest"]

SCHEMA = "zoop-extraction-s2-2"
LEDGER_VERSION = "zoop-extraction-ledger-1"
ADAPTER_VERSION = "zoop-extraction-poc-adapter-1"
ARTICLE_PROJECTION = "zoop-article-projection-1"
CANDIDATE_VERSION = "zoop-event-candidate-1"
POC_COMMIT = "fa446e7c72edfa06ec1a0e8e999199a21d31c695"
# Pinned prompt/schema fingerprint of installed extraction+compare contracts (investmate.prompts).
ANALYSIS_FINGERPRINT = "da15369acc6aad52ebf877d341bb08041195ad9f6e0874bda1ed18b7e95eabb4"
CONTEXT_REVISION = "role-context-3"

TOPIC_PRODUCER = "zoop-topic-replay-producer-1"
TOPIC_REQUEST = "zoop-topic-request-1"
TOPIC_RESPONSE = "zoop-topic-response-1"
TOPIC_REPLAY = "zoop-topic-replay-1"
TOPIC_CANDIDATE = "zoop-topic-candidate-1"

MAX_COMMAND = 2_000_000
MAX_REPLAY = 20_000_000
MAX_COMPANIES = 500
MAX_EVENTS = 50
MAX_MEMBERS = 20
MAX_DOCUMENTS = 200
MAX_COMPARISONS = 499  # plus one extraction call stays within the installed per-run replay budget (500)
# Candidate ID namespaces. A client-owned snapshot eventId may never collide with a produced identity.
RESERVED_PREFIXES = ("mc-", "evc-", "tp-")


class ExtractionFailure(Exception):
    def __init__(self, code: str, detail: dict | None = None):
        self.code = code
        self.detail = detail
        super().__init__(code)


class Provenance(Wire):
    source_kind: Literal["synthetic", "actual"]
    execution_mode: Literal["replay"]
    recording_kind: Literal["authored-test"]


class ReplyInvalid(ExtractionFailure):
    """The received reply (not the environment) violates a contract; it stays auditable and is never reusable."""


class CitationFailure(ReplyInvalid):
    """A quote/locator is not an exact whole-run mapped interval of the prepared text."""


class ObservationRef(Wire):
    """Exact ingestion candidate observation: round/source/page/ordinal plus immutable document identities."""
    round_id: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=200)
    page: int = Field(ge=0)
    ordinal: int = Field(ge=0)
    document_id: str = Field(min_length=1, max_length=200)
    raw_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    document_version: str = Field(pattern=r"^[a-f0-9]{64}$")

    def export_wire(self) -> dict:
        return {"schemaVersion": INGESTION_SCHEMA, **self.wire()}


class CatalogueCompany(Wire):
    company_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    aliases: list[str] = Field(max_length=50)
    ticker: str | None


class Catalogue(Wire):
    revision: str = Field(min_length=1, max_length=200)
    companies: list[CatalogueCompany] = Field(max_length=MAX_COMPANIES)

    @model_validator(mode="after")
    def unique(self):
        if len({c.company_id for c in self.companies}) != len(self.companies):
            raise ValueError("duplicate company")
        return self


class SnapshotMember(Wire):
    observation: ObservationRef
    # Original investmate Mention JSON. It is strictly parsed and grounded against the exact document by the adapter.
    mention: dict[str, Any]


class SnapshotEvent(Wire):
    event_id: str = Field(min_length=1, max_length=200)
    revision: str = Field(min_length=1, max_length=200)
    members: list[SnapshotMember] = Field(min_length=1, max_length=MAX_MEMBERS)

    @model_validator(mode="after")
    def reserved(self):
        if self.event_id.startswith(RESERVED_PREFIXES):
            raise ValueError("reserved identity namespace")
        return self


class Snapshot(Wire):
    revision: str = Field(min_length=1, max_length=200)
    events: list[SnapshotEvent] = Field(max_length=MAX_EVENTS)

    @model_validator(mode="after")
    def unique(self):
        if len({e.event_id for e in self.events}) != len(self.events):
            raise ValueError("duplicate event")
        return self


class TopicConfig(Wire):
    producer_version: Literal["zoop-topic-replay-producer-1"]


class Submit(Wire):
    schema_version: Literal["zoop-extraction-s2-2"]
    job_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,200}$")
    provenance: Provenance
    prompt_version: str = Field(min_length=1, max_length=200)
    incoming: ObservationRef
    catalogue: Catalogue
    snapshot: Snapshot
    topic: TopicConfig | None


class Selector(Wire):
    schema_version: Literal["zoop-extraction-s2-2"]
    job_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,200}$")


# ---- Distinct topic producer contract: events + documents in, explicit membership + exact citations out. ----

class TopicMember(Wire):
    kind: Literal["event-candidate", "snapshot-event"]
    ref: str = Field(min_length=1, max_length=200)


class TopicCitation(Wire):
    document_id: str = Field(min_length=1, max_length=200)
    document_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=20_000)


class TopicProposal(Wire):
    label: str = Field(min_length=1, max_length=200)
    criteria: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=2000)
    members: list[TopicMember] = Field(min_length=1, max_length=200)
    citations: list[TopicCitation] = Field(min_length=1, max_length=50)


class TopicResponse(Wire):
    schema_version: Literal["zoop-topic-response-1"]
    producer_version: Literal["zoop-topic-replay-producer-1"]
    topics: list[TopicProposal] = Field(max_length=50)


class TopicReplayRecord(Wire):
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    response: dict[str, Any]


class TopicReplay(Wire):
    format: Literal["zoop-topic-replay-1"]
    synthetic: bool
    recording_kind: Literal["authored-test"]
    producer_version: Literal["zoop-topic-replay-producer-1"]
    records: list[TopicReplayRecord] = Field(max_length=1000)

    @model_validator(mode="after")
    def unique(self):
        if len({r.request_digest for r in self.records}) != len(self.records):
            raise ValueError("duplicate topic replay request")
        return self
