"""Wire models of the chatbot model stage family (`/internal/v1/chat-stages`). The service never imports `zoop_ai`: these mirror the worker's
`zoop-ai-chat-1` contract as an allowlisted view (unknown keys are dropped on output, missing ones fail closed), and the field-for-field agreement is
tested. The stage input stays an opaque object for the service: the installed `zoop-ai-chat` validates it completely."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

CHAT_SCHEMA = "zoop-ai-chat-1"
ChatStage = Literal["chat-router", "chat-answer", "chat-verification"]
STAGES: tuple[str, ...] = ("chat-router", "chat-answer", "chat-verification")
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
    schema_version: Literal["zoop-ai-chat-1"]
    invocation_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{8,96}$",
                               description="Identifies one stage of one attempt; must equal Idempotency-Key. The same id and input never send twice.")
    stage: ChatStage
    mode: Literal["replay", "live"]
    input: dict[str, Any] = Field(description="The stage input of the zoop-ai-chat-1 contract (RouterInput, AnswerInput or VerificationInput).")


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


class ChatStageResult(ChatView):
    schema_version: Literal["zoop-ai-chat-1"]
    invocation_id: str
    stage: ChatStage
    status: Literal["succeeded", "failed"]
    answer: dict[str, Any] | None = Field(description="The typed stage answer (RouterAnswer, ChatAnswer or VerificationAnswer) when succeeded.")
    failure: ChatStageFailure | None
    receipt: ChatReceipt | None = Field(description="Who received the request and what they reported; present once a request was sent.")
