"""Versioned process contract of the chatbot model stages (`zoop-ai-chat`), separate from the S1 document contract.

Three stages, each one provider call (ZOOP-AIG-001 6.3.2: router and post-verification keep their own question sets, policy
versions, purposes, receipts and failure states apart from S1):

- `chat-router`: native Jev, typed Noul probabilities per requirement for the Q01-Q08 tags, the bound capabilities and
  prohibited advice.
- `chat-answer`: Luna `answer-generator`, a strict JSON answer by sections over the branch context.
- `chat-verification`: native Jev, per section a support Choice (evidence sections only) and a prohibited-advice Noul.

The application never sends member ids, emails, account data or full article texts. Quoted spans carry their `sourceId` so the
operator chat grant registry decides whether they may be sent to a recipient.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from .contracts import Wire

CHAT_SCHEMA_VERSION = "zoop-ai-chat-1"
ChatStage = Literal["chat-router", "chat-answer", "chat-verification"]
QueryType = Literal["Q01", "Q02", "Q03", "Q04", "Q05", "Q06", "Q07", "Q08"]
Basis = Literal["general_knowledge", "evidence_grounded"]

MAX_REQUIREMENTS = 6
MAX_SECTIONS = 12
MAX_CITATIONS = 20
MAX_QUESTION = 4000
MAX_TEXT = 12000


class ChatGrant(Wire):
    """One entry of the operator chat grant registry: may text of `source_id` be sent to a recipient for a chat stage."""
    grant_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    enabled: bool
    rights: Literal["known", "unknown", "denied"]
    allowed_operations: list[Literal["read", "model-send", "quote-display"]]
    recipients: list[str]
    purposes: list[ChatStage]
    evidence: list[str]
    expires_at: str | None

    @model_validator(mode="after")
    def expiry_valid(self):
        if self.expires_at is not None and datetime.fromisoformat(self.expires_at).tzinfo is None:
            raise ValueError("grant expiry requires timezone")
        return self


class ChatGrantRegistry(Wire):
    schema_version: Literal["zoop-ai-chat-1"]
    grants: list[ChatGrant]


class Turn(Wire):
    """One question of the clarification chain, root first. `choice_label` is the picked option, null for free text."""
    text: str = Field(min_length=1, max_length=MAX_QUESTION)
    choice_label: str | None = None


class RouterRequirement(Wire):
    requirement_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    text: str = Field(min_length=1, max_length=MAX_QUESTION)
    explicit: bool


class Capability(Wire):
    capability_id: str = Field(pattern=r"^[A-Za-z]+(\.[A-Za-z]+)+$")
    description: str = Field(min_length=1, max_length=300)


class RouterInput(Wire):
    turns: list[Turn] = Field(min_length=1, max_length=3)
    requirements: list[RouterRequirement] = Field(min_length=1, max_length=MAX_REQUIREMENTS)
    capabilities: list[Capability] = Field(max_length=20)

    @model_validator(mode="after")
    def distinct(self):
        if len({r.requirement_id for r in self.requirements}) != len(self.requirements):
            raise ValueError("requirement ids must be distinct")
        if len({c.capability_id for c in self.capabilities}) != len(self.capabilities):
            raise ValueError("capability ids must be distinct")
        return self


class RoutedRequirement(Wire):
    requirement_id: str
    types: dict[QueryType, float]
    capabilities: dict[str, float]
    prohibited_advice: float


class RouterAnswer(Wire):
    requirements: list[RoutedRequirement]


class Quote(Wire):
    """A quoted span the answer may cite. `source_id` selects the grant; the text itself is the minimum span, never the article."""
    evidence_id: str = Field(pattern=r"^ev-[0-9a-f]{64}$")
    source_id: str = Field(min_length=1)
    quote: str = Field(min_length=1, max_length=2000)
    article_title: str | None = Field(default=None, max_length=500)
    published_at: str | None = None


class BranchItem(Wire):
    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=300)


class Branch(Wire):
    requirement_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    label: str = Field(min_length=1, max_length=MAX_QUESTION)
    general: bool
    none_found: bool
    items: list[BranchItem] = Field(max_length=50)
    evidence: list[Quote] = Field(max_length=MAX_CITATIONS)


class AnswerInput(Wire):
    turns: list[Turn] = Field(min_length=1, max_length=3)
    branches: list[Branch] = Field(min_length=1, max_length=MAX_REQUIREMENTS)
    max_citations: int = Field(ge=0, le=MAX_CITATIONS)


class AnswerSection(Wire):
    basis: Basis
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    requirement_ids: list[str] = Field(min_length=1, max_length=MAX_REQUIREMENTS)
    evidence_ids: list[str] = Field(max_length=MAX_CITATIONS)


class ChatAnswer(Wire):
    sections: list[AnswerSection] = Field(max_length=MAX_SECTIONS)
    insufficient_requirement_ids: list[str] = Field(max_length=MAX_REQUIREMENTS)
    graph_target_ids: list[str] = Field(max_length=50)


class VerifySection(Wire):
    basis: Basis
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    evidence_ids: list[str] = Field(max_length=MAX_CITATIONS)


class VerificationInput(Wire):
    sections: list[VerifySection] = Field(min_length=1, max_length=MAX_SECTIONS)
    citations: list[Quote] = Field(max_length=MAX_CITATIONS)

    @model_validator(mode="after")
    def cited_exist(self):
        known = {c.evidence_id for c in self.citations}
        for section in self.sections:
            if section.basis == "general_knowledge" and section.evidence_ids:
                raise ValueError("a general section cites nothing")
            if not set(section.evidence_ids) <= known:
                raise ValueError("a section cites evidence that is not provided")
        return self


class SectionVerdict(Wire):
    support: Literal["supported", "contradicted", "hold"] | None
    prohibited_advice: Literal["no", "yes", "hold"]


class VerificationAnswer(Wire):
    sections: list[SectionVerdict]


INPUTS: dict[str, type[Wire]] = {"chat-router": RouterInput, "chat-answer": AnswerInput,
                                 "chat-verification": VerificationInput}


class StageRequest(Wire):
    """What the application asks of one stage. `invocation_id` identifies the attempt's stage: the same id with the same input
    returns the stored outcome and never sends again; the same id with another input is refused."""
    schema_version: Literal["zoop-ai-chat-1"]
    invocation_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{8,160}$")
    stage: ChatStage
    mode: Literal["replay", "live"]
    input: dict[str, Any]

    def parsed(self) -> Wire:
        return INPUTS[self.stage].model_validate(self.input)

    def quotes(self) -> list[Quote]:
        parsed = self.parsed()
        if isinstance(parsed, AnswerInput):
            return [q for branch in parsed.branches for q in branch.evidence]
        if isinstance(parsed, VerificationInput):
            return list(parsed.citations)
        return []


class Usage(Wire):
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    reasoning_tokens: int | None


class Receipt(Wire):
    """Who received the request and what they reported. Present once a request was sent, whatever the outcome."""
    provider: str
    provider_revision: str
    model: str
    prompt_version: str
    execution_mode: Literal["replay", "live"]
    usage: Usage
    sent_at: str
    received_at: str | None


class StageFailure(Wire):
    """`code` is a stable machine code. `sent` says a request left this process; `unknown` says its fate is unknown (timeout or
    disconnect after sending), so the caller must never send it again."""
    code: str = Field(pattern=r"^[a-z0-9_]{1,64}$")
    sent: bool
    unknown: bool


class StageResult(Wire):
    schema_version: Literal["zoop-ai-chat-1"]
    invocation_id: str
    stage: ChatStage
    status: Literal["succeeded", "failed"]
    answer: dict[str, Any] | None
    failure: StageFailure | None
    receipt: Receipt | None
