"""Prototype-owned S2-2 wire contracts (authored replay and live provider). Not an S1 schema alias, HTTP route or application document API.

All text offsets are Python Unicode code points over the exact prepared ingestion text (never bytes/UTF-16).
Event candidates, topic candidates and prepared documents are separate identities; none is an approved result.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ingestion_contracts import SCHEMA as INGESTION_SCHEMA
from .ingestion_contracts import Wire, canonical, digest

__all__ = ["canonical", "digest"]

SCHEMA = "zoop-extraction-s2-2"
LEDGER_VERSION = "zoop-extraction-ledger-1"
ADAPTER_VERSION = "zoop-extraction-native-replay-1"  # article projection, request preimages, quote resolution, strict parse/grounding and effective/disposition rules: any change MUST bump it
# The live adapter shares every rule above with replay (same projection, preimages, grounding, SAME/disposition). It only adds the provider call path, so a
# change to a shared rule MUST bump BOTH versions, and a change to the live call/decode/persistence path bumps this one.
LIVE_ADAPTER_VERSION = "zoop-extraction-native-live-1"
REPLAY_FORMAT = "zoop-analysis-replay-1"
ARTICLE_PROJECTION = "zoop-article-projection-1"
CANDIDATE_VERSION = "zoop-event-candidate-1"
ENQUEUE_FORMAT = "zoop-round-enqueue-1"  # the digest preimage of a round-enqueued job id: changing it re-identifies every enqueued job

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
MAX_COMPARISONS = 499  # one extraction plus 499 comparisons per job
# Candidate ID namespaces. A client-owned snapshot eventId may never collide with a produced identity.
RESERVED_PREFIXES = ("mc-", "evc-", "tp-")


class ExtractionFailure(Exception):
    def __init__(self, code: str, detail: dict | None = None):
        self.code = code
        self.detail = detail
        super().__init__(code)


class Provenance(Wire):
    """Truthful source/execution provenance. `executionMode` and `recordingKind` are one pair: replay is authored-test, live is provider."""
    source_kind: Literal["synthetic", "actual"]
    execution_mode: Literal["replay", "live"]
    recording_kind: Literal["authored-test", "provider"]

    @model_validator(mode="after")
    def paired(self):
        if (self.execution_mode, self.recording_kind) not in {("replay", "authored-test"), ("live", "provider")}:
            raise ValueError("execution mode and recording kind conflict")
        return self


class ReplyInvalid(ExtractionFailure):
    """The received reply (not the environment) violates a contract; it stays auditable and is never reusable."""


class ProviderResponseUnknown(ExtractionFailure):
    """A live request may have reached the provider but no reply was received. Never resent automatically; the job reconciles."""


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
    # Mention JSON of this module's native `Mention` (snake_case). It is strictly parsed and grounded against the exact document by extraction_replay.
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


def enqueue_job_id(enqueue_id: str, observation: ObservationRef) -> str:
    """The job id of one observation under one enqueue label: only the label and the exact observation (round, source, page, ordinal, document and
    raw/document versions) enter it. The descriptor (prompt, catalogue, snapshot, topic, provenance) and the replay/live input never do, so changing
    any of them for the same label and observation is a `job_input_conflict`, never a second job."""
    return "s2r-" + digest({"format": ENQUEUE_FORMAT, "enqueueId": enqueue_id, "observation": observation.wire()})


class EnqueueRound(Wire):
    """Registration of one job per planned observation of a COMPLETE ingestion round, under one explicit descriptor. The caller supplies the catalogue
    and snapshot; nothing is inferred or defaulted. `enqueueId` is scoped to (sourceId, roundId), it is not a global batch."""
    schema_version: Literal["zoop-extraction-s2-2"]
    enqueue_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,120}$")
    round_id: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=200)
    provenance: Provenance
    prompt_version: str = Field(min_length=1, max_length=200)
    catalogue: Catalogue
    snapshot: Snapshot
    topic: TopicConfig | None

    def observation(self, page: int, ordinal: int, document_id: str, raw_version: str, document_version: str) -> ObservationRef:
        return ObservationRef.model_validate({"roundId": self.round_id, "sourceId": self.source_id, "page": page, "ordinal": ordinal,
                                              "documentId": document_id, "rawVersion": raw_version, "documentVersion": document_version})

    def submit(self, observation: ObservationRef) -> Submit:
        """The one ordinary `Submit` this descriptor means for an observation, byte-identical to a hand-written submit of the same content."""
        return Submit.model_validate({"schemaVersion": self.schema_version, "jobId": enqueue_job_id(self.enqueue_id, observation), "provenance": self.provenance.wire(),
                                      "promptVersion": self.prompt_version, "incoming": observation.wire(), "catalogue": self.catalogue.wire(),
                                      "snapshot": self.snapshot.wire(), "topic": self.topic.wire() if self.topic else None})


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


# ---- Native strict analysis domain (snake_case JSON, the shape authored mentions/decisions are written in) ----

class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Article(Record):
    """The exact analysed text. `version` is the digest of every field; it never includes collection time."""
    article_id: str
    url: str
    title: str
    body: str
    publisher: str
    published_at: str | None = None
    language: str = "ko"
    input_kind: Literal["body", "summary"] = "body"
    origin_id: str | None = None
    withdrawn: bool = False
    allow_model_send: bool = False
    synthetic: bool = False

    @property
    def version(self) -> str:
        return digest(self.model_dump(mode="json"))


class Evidence(Record):
    article_id: str
    article_version: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)

    def matches(self, article: Article) -> bool:
        return (self.article_id == article.article_id and self.article_version == article.version and self.end > self.start
                and article.body[self.start:self.end] == self.quote)


class Participant(Record):
    company_id: str | None = None
    name: str
    role: str


class Mention(Record):
    mention_id: str
    article_id: str
    article_version: str
    title: str
    event_type: str
    action: str
    target: str | None = None
    event_time: str | None = None
    period: str | None = None
    assertion_status: Literal["occurred", "announced", "planned", "forecast", "cancelled", "unknown"]
    participants: list[Participant]
    evidence: list[Evidence]
    keywords: list[str] = Field(default_factory=list)
    background: bool = False
    countries: list[str] = Field(default_factory=list)


class Extraction(Record):
    mentions: list[Mention]


class PairDecision(Record):
    relation: Literal["SAME", "DIFFERENT", "FOLLOWS", "CONFLICT", "HOLD"]
    reason: str
    evidence: list[Evidence] = Field(default_factory=list)


# ---- Native authored replay: responses keyed by the exact request digest (no input text is copied into the fixture). ----

class AnalysisReplayRecord(Wire):
    stage: Literal["extract", "compare"]
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    response: dict[str, Any]


class AnalysisReplay(Wire):
    format: Literal["zoop-analysis-replay-1"]
    synthetic: bool
    recording_kind: Literal["authored-test"]
    prompt_version: str = Field(min_length=1, max_length=200)
    analysis_version: str = Field(min_length=1, max_length=200)
    records: list[AnalysisReplayRecord] = Field(max_length=2000)

    @model_validator(mode="after")
    def unique(self):
        keys = [(r.stage, r.request_digest) for r in self.records]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate replay request")
        return self
