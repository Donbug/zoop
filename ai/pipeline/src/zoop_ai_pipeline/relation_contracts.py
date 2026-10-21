"""Prototype-owned offline S3 relation/impact wire contracts. Not an S1 schema alias, HTTP route or application relation API.

Relation candidates, impact candidates and the S2 event/topic candidates they cite are separate identities (rc-/ic- vs evc-/tp-).
Nothing here is approved or published: `eligible` only means the automatic evidence gate passed for a later, separate step.
All text offsets are Python Unicode code points over the exact prepared ingestion text (never bytes/UTF-16).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .extraction_contracts import CitationFailure, ExtractionFailure, Provenance, ReplyInvalid, canonical, digest
from .ingestion_contracts import Wire

__all__ = ["CitationFailure", "ExtractionFailure", "ReplyInvalid", "canonical", "digest"]

SCHEMA = "zoop-relation-s3"
LEDGER_VERSION = "zoop-relation-ledger-1"
CANDIDATE_VERSION = "zoop-relation-candidate-1"
IMPACT_CANDIDATE_VERSION = "zoop-impact-candidate-1"
POLICY = "zoop-relation-policy-1"
REVALIDATION_POLICY = "zoop-relation-revalidation-policy-1"
IMPACT_POLICY = "zoop-impact-policy-1"

PRODUCER = "zoop-relation-producer-1"
VERIFIER = "zoop-relation-verifier-1"
IMPACT_PRODUCER = "zoop-impact-producer-1"
IMPACT_VERIFIER = "zoop-impact-verifier-1"
REQUEST = "zoop-relation-request-1"
RESPONSE = "zoop-relation-response-1"
VERIFY_REQUEST = "zoop-relation-verify-request-1"
VERIFY_RESPONSE = "zoop-relation-verify-response-1"
IMPACT_REQUEST = "zoop-impact-request-1"
IMPACT_RESPONSE = "zoop-impact-response-1"
IMPACT_VERIFY_REQUEST = "zoop-impact-verify-request-1"
IMPACT_VERIFY_RESPONSE = "zoop-impact-verify-response-1"
REPLAY = "zoop-relation-replay-1"

MAX_COMMAND = 2_000_000
MAX_RELATIONS = 100
MAX_DOCUMENTS = 50
MAX_CITATIONS = 20
MAX_PATH = 2
LABEL_NOTE = "textual impact direction of cited statements; not a price direction, probability or forecast"

# type -> (subject kind, object kind, direction). Event and topic are different endpoint kinds and never aliases of each other.
TYPES: dict[str, tuple[str, str, str]] = {
    "SUPPLIES": ("company", "company", "directed"),            # supplier -> customer
    "INVESTS_IN": ("company", "company", "directed"),          # investor -> investee
    "COMPETES_WITH": ("company", "company", "symmetric"),      # canonical sorted pair
    "PARTICIPATES_IN": ("company", "event", "directed"),       # direct participation in an explicit event
    "RELATES_TO_TOPIC": ("company", "topic", "directed"),      # only an existing bound topic candidate
}
INDIRECT_TYPES = frozenset({"SUPPLIES", "INVESTS_IN"})
# Co-occurrence and identity signals are never relationship proof (they are not part of this vocabulary).
NON_PROOF = frozenset({"SAME", "FOLLOWS", "SHARES_ISSUE", "CO_MENTION", "INVOLVES", "STRUCTURALLY_RELATED_TO"})
VOCABULARY = {t: {"subject": s, "object": o, "direction": d} for t, (s, o, d) in sorted(TYPES.items())}

LABELS = ("positive", "negative", "mixed", "undetermined")
ID = r"^[A-Za-z0-9._:-]{1,200}$"
RC = r"^rc-[a-f0-9]{64}$"
HASH = r"^[a-f0-9]{64}$"


class Upstream(Wire):
    job_id: str = Field(pattern=ID)
    input_digest: str = Field(pattern=HASH)


class Submit(Wire):
    schema_version: Literal["zoop-relation-s3"]
    job_id: str = Field(pattern=ID)
    provenance: Provenance
    upstream: Upstream


class Selector(Wire):
    schema_version: Literal["zoop-relation-s3"]
    job_id: str = Field(pattern=ID)


class Review(Wire):
    """Append-only HOLD review at the CURRENT revision. `allow` is the operator's FINAL semantic approval (effect `approved`): it re-runs only the
    deterministic gate, never a model, verifier or impact call. `reject` excludes. Neither is a publication decision."""
    schema_version: Literal["zoop-relation-s3"]
    job_id: str = Field(pattern=ID)
    relation_candidate_id: str = Field(pattern=RC)
    expected_revision: int = Field(ge=1)
    decision: Literal["allow", "reject"]
    reviewer: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=2000)


# Review effects. `revalidation-requested` only exists in ledgers written before the final-approval cutover: it is readable history, never an approval.
EFFECT_APPROVED = "approved"
EFFECT_EXCLUDED = "excluded"
EFFECT_LEGACY_REVALIDATION = "revalidation-requested"
EFFECT_OF = {"allow": EFFECT_APPROVED, "reject": EFFECT_EXCLUDED}
BASIS_AUTOMATIC = "automatic-verifier"
BASIS_OPERATOR = "operator-final-approval"


# ---- Producer contract (generation) ---------------------------------------------------------------------------------

class Endpoint(Wire):
    kind: Literal["company", "event", "topic"]
    ref: str = Field(min_length=1, max_length=200)


class Citation(Wire):
    document_id: str = Field(min_length=1, max_length=200)
    document_version: str = Field(pattern=HASH)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=20_000)


def _day(value: str | None) -> str | None:
    if value is not None:
        if len(value) != 10:
            raise ValueError("ISO date required")
        date.fromisoformat(value)
    return value


class Validity(Wire):
    """Dates only from cited evidence. Absent values stay unknown (null); nothing is inferred or defaulted."""
    from_: str | None = Field(alias="from")
    until: str | None
    citations: list[Citation] = Field(max_length=MAX_CITATIONS)

    @field_validator("from_", "until")
    @classmethod
    def _dates(cls, value: str | None) -> str | None:
        return _day(value)


class Step(Wire):
    type: str = Field(min_length=1, max_length=100)
    subject: Endpoint
    object: Endpoint
    citations: list[Citation] = Field(max_length=MAX_CITATIONS)


class Proposal(Wire):
    type: str = Field(min_length=1, max_length=100)  # an unsupported type is a private hold, not a malformed reply
    subject: Endpoint
    object: Endpoint
    connection: Literal["direct", "indirect"]
    business_scope: str | None = Field(max_length=500)
    product_scope: str | None = Field(max_length=500)
    validity: Validity
    countries: list[str] = Field(max_length=10)
    reason: str = Field(min_length=1, max_length=2000)
    citations: list[Citation] = Field(max_length=MAX_CITATIONS)
    path: list[Step] = Field(max_length=4)

    @field_validator("countries")
    @classmethod
    def _countries(cls, value: list[str]) -> list[str]:
        if any(len(c) != 2 or not c.isascii() or not c.isupper() or not c.isalpha() for c in value):
            raise ValueError("ISO 3166 alpha-2 country codes")
        return value


class RelationResponse(Wire):
    schema_version: Literal["zoop-relation-response-1"]
    producer_version: Literal["zoop-relation-producer-1"]
    relations: list[Proposal] = Field(max_length=MAX_RELATIONS)


class ImpactProposal(Wire):
    impacted_company_id: str = Field(min_length=1, max_length=200)
    direction: Literal["positive", "negative", "mixed", "undetermined"]
    reason: str = Field(min_length=1, max_length=2000)
    supporting: list[Citation] = Field(max_length=MAX_CITATIONS)
    opposing: list[Citation] = Field(max_length=MAX_CITATIONS)
    limitations: str | None = Field(max_length=1000)


class ImpactResponse(Wire):
    schema_version: Literal["zoop-impact-response-1"]
    producer_version: Literal["zoop-impact-producer-1"]
    impacts: list[ImpactProposal] = Field(max_length=2)


# ---- Independent verifier contracts (fixed facts + quotes in; per-claim verdicts out) ---------------------------------

class ClaimVerdict(Wire):
    claim_id: str = Field(min_length=1, max_length=100)
    verdict: Literal["supported", "contradicted", "insufficient", "reversed"]
    quote_ids: list[str] = Field(max_length=50)


class VerifierResponse(Wire):
    schema_version: Literal["zoop-relation-verify-response-1"]
    verifier_version: Literal["zoop-relation-verifier-1"]
    claims: list[ClaimVerdict] = Field(max_length=50)


class QuoteEffect(Wire):
    quote_id: str = Field(min_length=1, max_length=100)
    effect: Literal["positive", "negative", "neutral", "uncertain"]


class ImpactVerifierResponse(Wire):
    schema_version: Literal["zoop-impact-verify-response-1"]
    verifier_version: Literal["zoop-impact-verifier-1"]
    target: Literal["supported", "contradicted", "insufficient"]
    quotes: list[QuoteEffect] = Field(max_length=100)


# ---- Authored replay (one fixture per role; producer and verifier fixtures are independent files) --------------------

ROLE_STAGES = {"producer": {"relation", "impact"}, "verifier": {"verify-relation", "verify-impact"}}


class ReplayRecord(Wire):
    stage: Literal["relation", "impact", "verify-relation", "verify-impact"]
    request_digest: str = Field(pattern=HASH)
    response: dict[str, Any]


class Replay(Wire):
    format: Literal["zoop-relation-replay-1"]
    role: Literal["producer", "verifier"]
    synthetic: bool
    recording_kind: Literal["authored-test"]
    records: list[ReplayRecord] = Field(max_length=2000)

    @model_validator(mode="after")
    def valid(self):
        keys = [(r.stage, r.request_digest) for r in self.records]
        if len(set(keys)) != len(keys) or any(r.stage not in ROLE_STAGES[self.role] for r in self.records):
            raise ValueError("replay records")
        return self
