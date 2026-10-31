"""Versioned process contract of the chatbot model stages (`zoop-ai-chat`), separate from the S1 document contract.

Four stages, each one provider call (ZOOP-AIG-001 6.3.2: router and post-verification keep their own question sets, policy
versions, purposes, receipts and failure states apart from S1):

- `chat-router`: native Jev, typed Noul probabilities per requirement for the Q01-Q08 tags, the bound capabilities and
  prohibited advice.
- `chat-answer`: Luna `answer-generator`, a strict JSON answer by sections over the branch context.
- `chat-verification`: native Jev, per grounded section a support Choice over quotes and server observations, and a
  prohibited-advice Noul for every section.
- `chat-agent`: one step of a Luna Responses run that calls the ZOOP MCP tools (ZOOP-AIG-001 v0.11 6.3, MCP actions contract
  3.4). Every tool call is held for the application's approval (`require_approval=always`): a step ends either at approval
  requests or with the final answer, and the application resumes the stored response with its decisions. This runtime never
  approves anything on its own.

The application never sends member ids, emails, account data or full article texts. Quoted spans carry their `sourceId` so the
operator chat grant registry decides whether they may be sent to a recipient.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from .contracts import Wire

CHAT_SCHEMA_VERSION = "zoop-ai-chat-4"
ChatStage = Literal["chat-router", "chat-answer", "chat-verification", "chat-agent"]
QueryType = Literal["Q01", "Q02", "Q03", "Q04", "Q05", "Q06", "Q07", "Q08"]
# `zoop_documented` rests on ZOOP's own approved documents (policies), `evidence_grounded` on public evidence,
# `web_reported` on what a supplementary web search returned (a snippet, never ZOOP's own verified fact).
Basis = Literal["general_knowledge", "zoop_documented", "evidence_grounded", "web_reported"]
# A web hit's id is the application's own (`web-` and a hash of provider and URL), never an evidence id.
WEB_RESULT_ID = r"^web-[0-9a-f]{32}$"

MAX_REQUIREMENTS = 6
MAX_SECTIONS = 12
MAX_CITATIONS = 20
MAX_QUESTION = 4000
MAX_TEXT = 12000
MAX_PATHS = 20
MAX_PATH_STEPS = 6
# ZOOP-AIG-001 6.3.3: Luna's accumulated input and the final answer, whose length does not count reasoning. The provider's output
# cap does count it, so it leaves reasoning a share of its own, provisional until the live spike measures it.
MAX_INPUT_TOKENS = 24000
MAX_ANSWER_TOKENS = 2000
MAX_OUTPUT_TOKENS = 8000
INPUT_BUDGET_EXCEEDED = "input_budget_exceeded"
OUTPUT_BUDGET_EXCEEDED = "output_budget_exceeded"


def estimated_tokens(text: str) -> int:
    """A generous estimate before sending, with no tokenizer at hand: about 4 ASCII characters and 1.3 others to a token."""
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    return ascii_chars // 4 + (len(text) - ascii_chars) * 3 // 4


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


class RouterDependency(Wire):
    """Run this requirement on companies found by an earlier requirement when its checkpoint matches."""
    requirement_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    cardinality: Literal["exactly", "atLeast", "atMost"]
    count: int = Field(ge=1, le=5)


class RoutedRequirement(Wire):
    requirement_id: str
    types: dict[QueryType, float]
    capabilities: dict[str, float]
    prohibited_advice: float
    depends_on: RouterDependency | None


class RouterAnswer(Wire):
    requirements: list[RoutedRequirement]


class Quote(Wire):
    """A quoted span the answer may cite. `source_id` selects the grant; the text itself is the minimum span, never the article."""
    evidence_id: str = Field(pattern=r"^(ev-[0-9a-f]{64}|web-[0-9a-f]{32})$")
    source_id: str = Field(min_length=1)
    quote: str = Field(min_length=1, max_length=2000)
    article_title: str | None = Field(default=None, max_length=500)
    published_at: str | None = None


class BranchItem(Wire):
    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=300)


class PathStep(Wire):
    """One stored graph edge of a found path, in path order: its stored direction, relation type, display role and the
    evidence (quoted in the same branch) that supports this edge."""
    edge_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    relation: str = Field(min_length=1, max_length=100)
    role: str | None = Field(default=None, max_length=300)
    evidence_ids: list[str] = Field(max_length=MAX_CITATIONS)


class PathResult(Wire):
    """One pair of a path read. `found` has its steps; `none` was proven unconnected within the hop limit; `cut` reached
    the limit, so a longer connection may exist and it must never be reported as none."""
    from_id: str = Field(min_length=1)
    to_id: str = Field(min_length=1)
    status: Literal["found", "none", "cut"]
    steps: list[PathStep] = Field(max_length=MAX_PATH_STEPS)

    @model_validator(mode="after")
    def steps_match_status(self):
        if (self.status == "found") == (not self.steps):
            raise ValueError("a found path has steps, a none or cut pair has none")
        return self


class Branch(Wire):
    requirement_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    label: str = Field(min_length=1, max_length=MAX_QUESTION)
    general: bool
    none_found: bool
    items: list[BranchItem] = Field(max_length=50)
    evidence: list[Quote] = Field(max_length=MAX_CITATIONS)
    paths: list[PathResult] = Field(default_factory=list, max_length=MAX_PATHS)

    @model_validator(mode="after")
    def step_evidence_quoted(self):
        quoted = {q.evidence_id for q in self.evidence}
        for path in self.paths:
            for step in path.steps:
                if not set(step.evidence_ids) <= quoted:
                    raise ValueError("a path step names evidence that is not quoted in its branch")
        return self


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


MAX_AGENT_TOOLS = 13
MAX_APPROVALS = 8
MAX_MCP_CALLS = 16
TOOL_NAME = r"^[A-Za-z0-9_]{1,64}$"
PROVIDER_ID = r"^[A-Za-z0-9_-]{1,128}$"
REQUIREMENT_ID = r"^[A-Za-z0-9_-]{1,32}$"


class AgentRequirement(Wire):
    """One requirement the agent run answers. `general` marks a stable concept part that may be explained without evidence.
    `targets` are the ids the server already resolved for it (companies, issues); the model reads them, it never guesses ids."""
    requirement_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    label: str = Field(min_length=1, max_length=MAX_QUESTION)
    general: bool
    targets: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def target_ids(self):
        if any(not re.fullmatch(r"[A-Za-z0-9:._-]{1,128}", target) for target in self.targets):
            raise ValueError("a target is an id")
        return self


class McpConnection(Wire):
    """The run's access to the ZOOP MCP server: the job-scoped grant token the application issued (sent as the MCP tool's
    `authorization` on every request; this runtime never stores or logs it) and the tools the run may use. The server's URL is
    no part of a request: it is the operator's `ZOOP_AI_CHAT_MCP_SERVER_URL`, so no caller can send the grant elsewhere.

    `recipient` is the recipient the application checked its tool results' send grants for: the results go from its MCP server
    to the provider directly, never through this runtime's grant check. A step is sent only when it is exactly this stage's
    own recipient (`<provider>:<revision>` live, `authored-replay` in replay); otherwise `mcp_recipient_mismatch`, nothing sent.
    It is no credential and is part of the step's identity; it is never sent to the provider."""
    authorization: str = Field(min_length=16, max_length=4096, pattern=r"^[A-Za-z0-9._-]+$")
    allowed_tools: list[str] = Field(min_length=1, max_length=MAX_AGENT_TOOLS)
    recipient: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")

    @model_validator(mode="after")
    def tool_names(self):
        if any(not re.fullmatch(TOOL_NAME, name) for name in self.allowed_tools):
            raise ValueError("an allowed tool is an MCP tool name")
        if len(set(self.allowed_tools)) != len(self.allowed_tools):
            raise ValueError("allowed tools must be distinct")
        return self


class ApprovalDecision(Wire):
    """The application's decision on one approval request. This runtime only relays it; it never approves on its own."""
    approval_request_id: str = Field(pattern=PROVIDER_ID)
    approve: bool


class Continuation(Wire):
    """Resumes the stored provider response `previous_response_id` with the application's decisions on its approval requests."""
    previous_response_id: str = Field(pattern=PROVIDER_ID)
    decisions: list[ApprovalDecision] = Field(min_length=1, max_length=MAX_APPROVALS)

    @model_validator(mode="after")
    def distinct(self):
        if len({d.approval_request_id for d in self.decisions}) != len(self.decisions):
            raise ValueError("one decision per approval request")
        return self


class AgentInput(Wire):
    """One step of a Luna Responses run with the ZOOP MCP tools: the first step (no `continuation`) or a continuation with the
    application's approval decisions. The application sends no evidence here: the tools return it."""
    turns: list[Turn] = Field(min_length=1, max_length=3)
    requirements: list[AgentRequirement] = Field(min_length=1, max_length=MAX_REQUIREMENTS)
    mcp: McpConnection
    max_citations: int = Field(ge=0, le=MAX_CITATIONS)
    continuation: Continuation | None = None

    @model_validator(mode="after")
    def distinct(self):
        if len({r.requirement_id for r in self.requirements}) != len(self.requirements):
            raise ValueError("requirement ids must be distinct")
        return self


class ApprovalRequest(Wire):
    """A tool call the model proposes and the provider holds until the application decides (`require_approval=always`).
    `requirement_ids` are the requirements the model says the call serves, taken out of its `requirementIds` argument and empty
    when that is missing or malformed: the application decides what they are worth, and `arguments` are the rest."""
    approval_request_id: str = Field(pattern=PROVIDER_ID)
    tool_name: str = Field(pattern=TOOL_NAME)
    arguments: dict[str, Any]
    requirement_ids: list[Annotated[str, Field(pattern=REQUIREMENT_ID)]] = Field(max_length=MAX_REQUIREMENTS)


class McpCallSummary(Wire):
    """An MCP call the provider made in this step (after an approval): its tool and whether the server answered an error."""
    tool_name: str = Field(pattern=TOOL_NAME)
    failed: bool


class AgentAnswer(Wire):
    """The outcome of one agent step. `approval_required`: the run stopped at the listed approval requests, no answer;
    `completed`: the final answer, no requests. `response_id` is the stored provider response a continuation resumes."""
    response_id: str = Field(pattern=PROVIDER_ID)
    status: Literal["approval_required", "completed"]
    approval_requests: list[ApprovalRequest] = Field(max_length=MAX_APPROVALS)
    mcp_calls: list[McpCallSummary] = Field(max_length=MAX_MCP_CALLS)
    answer: ChatAnswer | None

    @model_validator(mode="after")
    def outcome(self):
        if (self.status == "approval_required") != bool(self.approval_requests):
            raise ValueError("approval requests exactly when approval is required")
        if (self.status == "completed") != (self.answer is not None):
            raise ValueError("an answer exactly when completed")
        return self


class RequestBinding(Wire):
    """Application invocation, not a member identifier; the service validates it before principal namespacing."""
    invocation_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{8,96}$")
    graph_version_id: str | None = Field(max_length=200)
    as_of: str | None

    @model_validator(mode="after")
    def dated(self):
        if self.as_of is not None and datetime.fromisoformat(self.as_of).tzinfo is None:
            raise ValueError("asOf requires timezone")
        return self


class MemberCompany(Wire):
    company_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=300)
    held: bool
    watched: bool

    @model_validator(mode="after")
    def membership(self):
        if not self.held and not self.watched:
            raise ValueError("a member company is held or watched")
        if ":" not in self.company_id or self.company_id.startswith("member:"):
            raise ValueError("company id required")
        return self


class PortfolioFact(Wire):
    kind: Literal["portfolio_scope"]
    requirement_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    timing: Literal["current_request_read"]
    query_scope: Literal["current_member", "named_companies"]
    company_ids: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(max_length=5)
    companies: list[MemberCompany] = Field(max_length=5)
    truncated: bool
    company_limit: Literal[5]

    @model_validator(mode="after")
    def scoped(self):
        ids = [c.company_id for c in self.companies]
        if len(set(ids)) != len(ids) or len(set(self.company_ids)) != len(self.company_ids):
            raise ValueError("company ids must be distinct")
        if self.query_scope == "current_member" and self.company_ids:
            raise ValueError("current member scope has no named targets")
        if self.query_scope == "named_companies" and (
                not self.company_ids or not set(ids) <= set(self.company_ids)):
            raise ValueError("named membership is limited to queried companies")
        if any(":" not in i or i.startswith("member:") for i in self.company_ids):
            raise ValueError("company id required")
        return self


class GraphChange(Wire):
    id: str = Field(min_length=1, max_length=200)
    kind: Literal["company", "issue", "edge"]
    name: str = Field(min_length=1, max_length=300)
    change: Literal["added", "removed"]


class ComparisonFact(Wire):
    kind: Literal["graph_comparison"]
    requirement_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    from_version: str = Field(min_length=1, max_length=200)
    to_version: str = Field(min_length=1, max_length=200)
    as_of: str | None
    since: str | None
    query_scope: Literal["whole_graph", "targets"]
    target_ids: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(max_length=5)
    evidence_limit: int = Field(ge=1, le=MAX_CITATIONS)
    change_limit: Literal[40]
    evidence_restricted: bool
    changes: list[GraphChange] = Field(max_length=40)
    truncated: bool

    @model_validator(mode="after")
    def scoped(self):
        if (self.query_scope == "whole_graph") != (not self.target_ids):
            raise ValueError("comparison targets must match query scope")
        if len(set(self.target_ids)) != len(self.target_ids) or any(
                i.startswith(("member:", "ev-")) or i == "graph:public" for i in self.target_ids):
            raise ValueError("comparison target ids invalid")
        for value in (self.as_of, self.since):
            if value is not None and datetime.fromisoformat(value).tzinfo is None:
                raise ValueError("comparison time requires timezone")
        if self.from_version == self.to_version and self.changes:
            raise ValueError("one version cannot differ from itself")
        return self


class PublicationRule(Wire):
    rule_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}@[1-9][0-9]{0,8}$")
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1000)


class PublicationFact(Wire):
    """Why an issue is on the map at the request's pinned graph version (Q08): the last review decision's kind, time and
    path up to the version's review revision, and the rules the version was filtered with. No decider, no decider's note."""
    kind: Literal["publication_record"]
    requirement_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    issue_id: str = Field(min_length=1, max_length=200)
    issue_title: str = Field(min_length=1, max_length=300)
    graph_version: str = Field(min_length=1, max_length=200)
    review_revision: int = Field(ge=0)
    rule_revision: int | None = Field(ge=0)
    decision: Literal["allow", "reject"] | None
    decision_path: Literal["admin_review", "snapshot_migration", "none"]
    decided_at: str | None
    rules: list[PublicationRule] = Field(max_length=10)

    @model_validator(mode="after")
    def recorded(self):
        if (self.decision_path == "none") != (self.decision is None) or (self.decision is None) != (self.decided_at is None):
            raise ValueError("a decision has its path and time, and no decision has neither")
        if self.decided_at is not None and datetime.fromisoformat(self.decided_at).tzinfo is None:
            raise ValueError("decidedAt requires timezone")
        if len({r.rule_id for r in self.rules}) != len(self.rules):
            raise ValueError("rule ids must be distinct")
        return self


class BriefingSelectionFact(Wire):
    """Why a published briefing round picked an issue (Q08): its rank and the selection reason the round recorded."""
    kind: Literal["briefing_selection"]
    requirement_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    issue_id: str = Field(min_length=1, max_length=200)
    issue_title: str = Field(min_length=1, max_length=300)
    round_id: str = Field(min_length=1, max_length=256)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    edition: Literal["morning", "evening"]
    rank: int = Field(ge=1, le=20)
    reason: str = Field(min_length=1, max_length=1000)


ServerFact = Annotated[PortfolioFact | ComparisonFact | PublicationFact | BriefingSelectionFact,
                       Field(discriminator="kind")]


class VerifySection(Wire):
    section_id: str = Field(pattern=r"^s([0-9]|1[01])$")
    requirement_ids: list[Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")]] = Field(
        min_length=1, max_length=MAX_REQUIREMENTS)
    basis: Basis
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    evidence_ids: list[str] = Field(max_length=MAX_CITATIONS)
    server_facts: list[ServerFact] = Field(max_length=72)


class VerificationInput(Wire):
    request_binding: RequestBinding
    sections: list[VerifySection] = Field(min_length=1, max_length=MAX_SECTIONS)
    citations: list[Quote] = Field(max_length=MAX_CITATIONS)

    @model_validator(mode="after")
    def cited_exist(self):
        known = {c.evidence_id for c in self.citations}
        if len(known) != len(self.citations):
            raise ValueError("citation ids must be distinct")
        for index, section in enumerate(self.sections):
            if section.section_id != f"s{index}":
                raise ValueError("section ids must match their ordered positions")
            if len(set(section.requirement_ids)) != len(section.requirement_ids):
                raise ValueError("section requirement ids must be distinct")
            if section.basis != "evidence_grounded" and section.server_facts:
                raise ValueError("only evidence sections may use server facts")
            for fact in section.server_facts:
                if fact.requirement_id not in section.requirement_ids:
                    raise ValueError("server fact belongs to another branch")
                if isinstance(fact, ComparisonFact) and (
                        fact.to_version != self.request_binding.graph_version_id
                        or fact.as_of != self.request_binding.as_of):
                    raise ValueError("comparison belongs to another version or asOf")
                if isinstance(fact, PublicationFact) and fact.graph_version != self.request_binding.graph_version_id:
                    raise ValueError("publication record belongs to another version")
        for section in self.sections:
            if section.basis == "general_knowledge" and section.evidence_ids:
                raise ValueError("a general section cites nothing")
            if not set(section.evidence_ids) <= known:
                raise ValueError("a section cites evidence that is not provided")
            web = [e.startswith("web-") for e in section.evidence_ids]
            if section.basis == "web_reported" and (not web or not all(web)):
                raise ValueError("a web section cites web hits only, at least one")
            if section.basis != "web_reported" and any(web):
                raise ValueError("only a web section cites web hits")
        for citation in self.citations:
            if citation.evidence_id.startswith("web-") != citation.source_id.startswith("web-search:"):
                raise ValueError("a web hit is quoted under its web provider's grant, and only it")
        return self


class SectionVerdict(Wire):
    support: Literal["supported", "contradicted", "hold"] | None
    prohibited_advice: Literal["no", "yes", "hold"]


class VerificationAnswer(Wire):
    sections: list[SectionVerdict]


INPUTS: dict[str, type[Wire]] = {"chat-router": RouterInput, "chat-answer": AnswerInput,
                                 "chat-verification": VerificationInput, "chat-agent": AgentInput}


class StageRequest(Wire):
    """What the application asks of one stage. `invocation_id` identifies the attempt's stage: the same id with the same input
    returns the stored outcome and never sends again; the same id with another input is refused."""
    schema_version: Literal["zoop-ai-chat-4"]
    invocation_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{8,160}$")
    stage: ChatStage
    mode: Literal["replay", "live"]
    input: dict[str, Any]

    def parsed(self) -> Wire:
        parsed = INPUTS[self.stage].model_validate(self.input)
        if isinstance(parsed, VerificationInput):
            invocation = parsed.request_binding.invocation_id
            if self.invocation_id != invocation and self.invocation_id.partition(":")[2] != invocation:
                raise ValueError("verification belongs to another invocation")
        return parsed

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
    schema_version: Literal["zoop-ai-chat-4"]
    invocation_id: str
    stage: ChatStage
    status: Literal["succeeded", "failed"]
    answer: dict[str, Any] | None
    failure: StageFailure | None
    receipt: Receipt | None
