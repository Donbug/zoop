"""Versioned, camelCase process contract; offsets are Python Unicode code points."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

SCHEMA_VERSION = "zoop-ai-s1-1"
PROMPT_VERSION = "zoop-document-2026-10-08-2"
POLICY_VERSION = "zoop-document-gate-2"
Kind = Literal["document-summary", "document-sentiment", "semantic-verification", "briefing-outlook"]
Label = Literal["positive", "negative", "mixed", "undetermined"]


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat()


class Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid", strict=True)

    def wire(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class Provenance(Wire):
    source_kind: Literal["synthetic", "actual"]
    execution_mode: Literal["replay", "live"]
    recording_kind: Literal["authored-test", "provider"]


class SourceGrant(Wire):
    grant_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    enabled: bool
    rights: Literal["known", "unknown", "denied"]
    allowed_operations: list[Literal["read", "store", "model-send", "quote-display"]]
    recipients: list[str]
    purposes: list[Kind]
    evidence: list[str]
    expires_at: str | None

    @model_validator(mode="after")
    def expiry_valid(self):
        if self.expires_at is not None and datetime.fromisoformat(self.expires_at).tzinfo is None:
            raise ValueError("grant expiry requires timezone")
        return self


class RawLocator(Wire):
    locator_id: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class Document(Wire):
    document_id: str = Field(min_length=1)
    document_version: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    text_artifact_id: str = Field(min_length=1)
    input_kind: Literal["body", "summary"]
    cleaner_version: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_hash: str = Field(min_length=1)
    raw_locators: list[RawLocator] = Field(min_length=1)

    @model_validator(mode="after")
    def immutable_text(self):
        if self.source_hash != digest(self.text):
            raise ValueError("source_hash_mismatch")
        ids = [r.locator_id for r in self.raw_locators]
        if len(set(ids)) != len(ids) or any(not 0 <= r.start < r.end <= len(self.text) for r in self.raw_locators):
            raise ValueError("raw_locator_invalid")
        return self


class Company(Wire):
    company_id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class EvidenceRef(Wire):
    evidence_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version: str = Field(min_length=1)
    text_artifact_id: str = Field(min_length=1)
    offset_unit: Literal["unicode_code_point"]
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)
    input_kind: Literal["body", "summary"]
    raw_locator_ids: list[str] = Field(min_length=1)


class Claim(Wire):
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    assertion_kind: Literal["fact", "interpretation", "limitation"]
    evidence_ids: list[str]


class SummaryAnswer(Wire):
    text: str = Field(min_length=1)
    claims: list[Claim] = Field(min_length=1)
    citations: list[EvidenceRef] = Field(min_length=1)
    limitations: list[str]


class SentimentAnswer(Wire):
    label: Label
    rationale: str = Field(min_length=1)
    claims: list[Claim] = Field(min_length=1)
    citations: list[EvidenceRef] = Field(min_length=1)
    limitations: list[str]


class ClaimVerdict(Wire):
    claim_id: str
    decision: Literal["supported", "contradicted", "insufficient"]
    reason: str = Field(min_length=1)


class VerificationAnswer(Wire):
    claims: list[ClaimVerdict] = Field(min_length=1)
    prohibited_advice: bool
    unsupported_causality: bool


class JobInput(Wire):
    document: Document
    company: Company
    grant_id: str
    grant_revision: str
    candidate: SummaryAnswer | SentimentAnswer | None


class OutlookAnswer(Wire):
    label: Label
    rationale: str = Field(min_length=1, max_length=1000)
    issue_ids: list[str] = Field(min_length=1, max_length=3)


class OutlookIssue(Wire):
    event_id: str = Field(min_length=1)
    title: str
    event_time: str | None
    companies: list[dict[str, Any]]


class OutlookInput(Wire):
    round_id: str = Field(min_length=1)
    scheduled_at: str
    graph_version: str
    review_revision: int
    rule_revision: int
    issues: list[OutlookIssue]
    document_sentiments: list[dict[str, Any]]
    market_variables: dict[str, Any]
    source_id: str = Field(min_length=1)
    grant_id: str
    grant_revision: str


class Submit(Wire):
    schema_version: Literal["zoop-ai-s1-1"]
    job_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    kind: Kind
    input: JobInput | OutlookInput
    mode: Literal["replay", "live"]
    provenance: Provenance

    @model_validator(mode="after")
    def boundary(self):
        p = self.provenance
        if p.execution_mode != self.mode:
            raise ValueError("provenance_mode_mismatch")
        if self.mode == "replay" and (p.source_kind != "synthetic" or p.recording_kind != "authored-test"):
            raise ValueError("authored_replay_requires_synthetic")
        if self.mode == "live" and p.recording_kind != "provider":
            raise ValueError("live_recording_invalid")
        if self.kind == "briefing-outlook":
            if not isinstance(self.input, OutlookInput):
                raise ValueError("outlook_input_required")
        elif not isinstance(self.input, JobInput):
            raise ValueError("document_input_required")
        elif (self.kind == "semantic-verification") != (self.input.candidate is not None):
            raise ValueError("candidate_scope_invalid")
        return self


class StageConfig(Wire):
    provider: str
    provider_revision: str
    model: str
    reasoning_effort: str | None
    prompt_version: str
    schema_version: str
    policy_version: str


class Validation(Wire):
    exact: bool
    semantic: Literal["supported", "hold", "reject"] | None
    eligible: bool
    reason: str | None


class AnalysisArtifact(Wire):
    schema_version: Literal["zoop-ai-s1-1"]
    artifact_id: str
    kind: Kind
    result_version: str
    job_id: str
    attempt_id: str
    input_digest: str
    source_refs: list[Document]
    dependency_refs: list[str]
    model_config_revision: str
    prompt_version: str
    policy_version: str
    produced_at: str
    provenance: Provenance
    company_id: str | None
    grant_id: str
    grant_revision: str
    claims: list[Claim]
    validation: Validation
    result: SummaryAnswer | SentimentAnswer | VerificationAnswer | OutlookAnswer


class Failure(Wire):
    code: str
    stage: Kind | None


class Usage(Wire):
    provider_attempts: int
    replay_calls: int
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    reasoning_tokens: int | None
    cost: float | None


class JobResult(Wire):
    schema_version: Literal["zoop-ai-s1-1"]
    job_id: str
    input_digest: str
    state: Literal["queued", "running", "reconciling", "persisting", "ready", "failed", "cancelled"]
    phase: str
    attempt_id: str | None
    artifact_ids: list[str]
    artifacts: list[AnalysisArtifact]
    failure: Failure | None
    resume_mode: Literal["none", "validate_only", "save_only", "unsent_only", "reconcile_only"]
    usage: Usage
    grant: SourceGrant | None
    input: Submit
    calls: list[dict[str, Any]]


def exact(candidate: SummaryAnswer | SentimentAnswer, doc: Document) -> None:
    refs = {e.evidence_id: e for e in candidate.citations}
    claims = {c.claim_id for c in candidate.claims}
    if len(refs) != len(candidate.citations) or len(claims) != len(candidate.claims):
        raise ValueError("duplicate_reference")
    for e in refs.values():
        if (e.document_id, e.document_version, e.text_artifact_id, e.input_kind) != (
            doc.document_id, doc.document_version, doc.text_artifact_id, doc.input_kind
        ) or not 0 <= e.start < e.end <= len(doc.text) or doc.text[e.start:e.end] != e.quote:
            raise ValueError("quote_mismatch")
        locators = {r.locator_id: r for r in doc.raw_locators}
        if not set(e.raw_locator_ids) <= locators.keys() or not any(
            locators[r].start <= e.start < e.end <= locators[r].end for r in e.raw_locator_ids
        ):
            raise ValueError("raw_locator_mismatch")
    for c in candidate.claims:
        if not set(c.evidence_ids) <= refs.keys() or (c.assertion_kind != "limitation" and not c.evidence_ids):
            raise ValueError("claim_citation_missing")
    limitation_texts = [c.text for c in candidate.claims if c.assertion_kind == "limitation"]
    if candidate.limitations != limitation_texts:
        raise ValueError("limitation_claim_coverage_invalid")
    rendered = "\n".join(c.text for c in candidate.claims if c.assertion_kind != "limitation")
    if isinstance(candidate, SummaryAnswer) and candidate.text != rendered:
        raise ValueError("summary_unattributed_text")
    if isinstance(candidate, SentimentAnswer) and candidate.rationale != rendered:
        raise ValueError("rationale_unattributed_text")
