"""Wire models of the chatbot model stage family (`/internal/v1/chat-stages`). The service never imports `zoop_ai`: these mirror the worker's
`zoop-ai-chat-2` contract as an allowlisted view (unknown keys are dropped on output, missing ones fail closed), and the field-for-field agreement is
tested. The stage input stays an opaque object for the service: the installed `zoop-ai-chat` validates it completely."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

CHAT_SCHEMA = "zoop-ai-chat-2"
ChatStage = Literal["chat-router", "chat-answer", "chat-verification", "chat-agent"]
STAGES: tuple[str, ...] = ("chat-router", "chat-answer", "chat-verification", "chat-agent")
# The caller's invocation id. The service prefixes it with the principal before the child sees it, so two principals never share a ledger row.
INVOCATION_ID = re.compile(r"[A-Za-z0-9_.:-]{8,96}")


class ChatWire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid", strict=True)

    def wire(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class ChatView(ChatWire):
    """Output projection: keys the runtime adds later are dropped, never relayed."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore", strict=True)


class ChatStageRequest(ChatWire):
    schema_version: Literal["zoop-ai-chat-2"]
    invocation_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{8,96}$",
                               description="Identifies one stage of one attempt; must equal Idempotency-Key. The same id and input never send twice.")
    stage: ChatStage
    mode: Literal["replay", "live"]
    input: dict[str, Any] = Field(description="The closed zoop-ai-chat-2 stage input (RouterInput, AnswerInput, VerificationInput or AgentInput).")


class ChatUsage(ChatView):
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    reasoning_tokens: int | None


class ChatReceipt(ChatView):
    provider: str
    provider_revision: str
    model: str
    prompt_version: str
    execution_mode: Literal["replay", "live"]
    usage: ChatUsage
    sent_at: str
    received_at: str | None


class ChatStageFailure(ChatView):
    code: str = Field(pattern=r"^[a-z0-9_]{1,64}$")
    sent: bool = Field(description="A request left the runtime for this invocation.")
    unknown: bool = Field(description="Sent, and its outcome is unknown (timeout or disconnect): it is never sent again.")


class ChatMcpHealth(ChatView):
    """Whether the operator's ZOOP MCP server answered a content-free probe at its configured URL (`zoop-ai-chat probe-mcp`): an MCP ping
    with no grant that the endpoint itself must refuse as unauthenticated. Nothing is run and no model is called."""
    schema_version: Literal["zoop-ai-chat-2"]
    mcp: Literal["reachable", "unreachable"]
    reason: Literal["mcp_timeout", "mcp_connect_failed", "mcp_status_unexpected"] | None = Field(
        default=None, description="Why it is unreachable: no answer in time, no connection, or an answer that is not the endpoint's own refusal.")

    @model_validator(mode="after")
    def reason_when_unreachable(self):
        if (self.mcp == "unreachable") != (self.reason is not None):
            raise ValueError("an unreachable server has a reason and a reachable one none")
        return self


QueryType = Literal["Q01", "Q02", "Q03", "Q04", "Q05", "Q06", "Q07", "Q08"]


class RoutedRequirement(ChatWire):
    """Closed like every stage answer: a key the worker contract does not define is refused, never relayed."""
    requirement_id: str
    types: dict[QueryType, float]
    capabilities: dict[str, float]
    prohibited_advice: float


class RouterAnswer(ChatWire):
    requirements: list[RoutedRequirement]


class AnswerSection(ChatWire):
    basis: Literal["general_knowledge", "zoop_documented", "evidence_grounded"]
    text: str
    requirement_ids: list[str]
    evidence_ids: list[str]


class ChatAnswer(ChatWire):
    sections: list[AnswerSection]
    insufficient_requirement_ids: list[str]
    graph_target_ids: list[str]


class SectionVerdict(ChatWire):
    support: Literal["supported", "contradicted", "hold"] | None
    prohibited_advice: Literal["no", "yes", "hold"]


class VerificationAnswer(ChatWire):
    sections: list[SectionVerdict]


class ApprovalRequest(ChatWire):
    """A tool call the model proposed and the provider holds for the application's decision. The service relays it; it never decides."""
    approval_request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    tool_name: str = Field(pattern=r"^[A-Za-z0-9_]{1,64}$")
    arguments: dict[str, Any]


class McpCallSummary(ChatWire):
    tool_name: str = Field(pattern=r"^[A-Za-z0-9_]{1,64}$")
    failed: bool


class AgentAnswer(ChatWire):
    """One `chat-agent` step: `approval_required` with the held tool calls and no answer, or `completed` with the final answer. `responseId` is
    the stored provider response the next step resumes with the application's decisions."""
    response_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    status: Literal["approval_required", "completed"]
    approval_requests: list[ApprovalRequest]
    mcp_calls: list[McpCallSummary]
    answer: ChatAnswer | None

    @model_validator(mode="after")
    def outcome(self):
        if (self.status == "approval_required") != bool(self.approval_requests) or (self.status == "completed") != (self.answer is not None):
            raise ValueError("approval requests exactly when approval is required, an answer exactly when completed")
        return self


ANSWERS: dict[str, type[ChatWire]] = {"chat-router": RouterAnswer, "chat-answer": ChatAnswer, "chat-verification": VerificationAnswer,
                                      "chat-agent": AgentAnswer}


class ChatStageResult(ChatView):
    """The outcome. Besides the field shapes the door checks the invariants: `succeeded` has an answer of its own stage's model, no failure and a
    receipt; `failed` has a failure and no answer; `unknown` implies `sent`; a receipt is present exactly when something was sent and names the
    requested mode."""
    schema_version: Literal["zoop-ai-chat-2"]
    invocation_id: str
    stage: ChatStage
    status: Literal["succeeded", "failed"]
    answer: RouterAnswer | ChatAnswer | VerificationAnswer | AgentAnswer | None = Field(
        description="The typed stage answer when succeeded: RouterAnswer (chat-router), ChatAnswer (chat-answer), VerificationAnswer "
                    "(chat-verification) or AgentAnswer (chat-agent).")
    failure: ChatStageFailure | None
    receipt: ChatReceipt | None = Field(description="Who received the request and what they reported; present once a request was sent.")
