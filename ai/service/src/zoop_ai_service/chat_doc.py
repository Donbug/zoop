"""Authored OpenAPI semantics and examples of the chatbot model stage family. Every example is built through the real wire models, so an example that
stops validating fails at generation; the route and model schemas themselves come from the application (`app.openapi()`)."""
from __future__ import annotations

from typing import Any

from .chat_wire import ChatStageRequest, ChatStageResult

DESCRIPTION = """\
**Chat stages (`/internal/v1/chat-stages/{stage}`, contract `zoop-ai-chat-1`, scope `chat.invoke`).** A fifth, separate family that runs ONE chatbot model
stage synchronously through the installed `zoop-ai-chat invoke`: `chat-router` (native Jev, typed probabilities per requirement), `chat-answer` (Luna, a strict
JSON answer by sections) or `chat-verification` (native Jev, per-section support and prohibited-advice verdicts). It is off unless its all-or-nothing server
configuration group is set (otherwise 409 `execution_unavailable` after authentication). The application decides everything a stage only proposes.

**Once per invocation.** `invocationId` (equal to `Idempotency-Key`) names one stage of one attempt. The runtime sends it at most once: the same id and input
return the stored outcome, another input under the same id is the stage failure `invocation_conflict`, and a request whose outcome is unknown stays `unknown`.
The id is bound to the calling principal. A **200** carries the stage outcome: `status=succeeded` with the typed `answer`, or `status=failed` with a stable
`failure.code`, whether a request was `sent` and whether its fate is `unknown`. A **502/504 `stage_outcome_unknown`** means the runtime may have sent the
request: never resend that invocation. A **503** means nothing was sent.

**Live and rights.** Nothing reaches a provider unless the chat gate is open (`ZOOP_AI_CHAT_LIVE_ENABLED=1` and a positive `ZOOP_AI_CHAT_MAX_CALLS`, shared by
the three stages and separate from the S1 and pipeline gates), and quoted spans are sent only under the operator chat grant registry (`model-send`, the stage
as purpose and the exact recipient). Stage time limits: router 4 s, answer 25 s, verification 6 s.
"""

EV = "ev-" + "1" * 64


def examples() -> dict[str, Any]:
    request = ChatStageRequest.model_validate({
        "schemaVersion": "zoop-ai-chat-1", "invocationId": "job-00000001:1:chat-router", "stage": "chat-router", "mode": "replay",
        "input": {"turns": [{"text": "HBM이 뭐야?"}], "requirements": [{"requirementId": "r1", "text": "HBM이 뭐야", "explicit": True}],
                  "capabilities": []}})
    receipt = {"provider": "authored-replay", "providerRevision": "authored-replay-1", "model": "authored-synthetic-chat-router",
               "promptVersion": "zoop-jev-chat-router-0123456789abcdef", "executionMode": "replay",
               "usage": {"inputTokens": None, "outputTokens": None, "cachedTokens": None, "reasoningTokens": None},
               "sentAt": "2026-10-22T03:00:00+00:00", "receivedAt": "2026-10-22T03:00:01+00:00"}
    succeeded = ChatStageResult.model_validate({
        "schemaVersion": "zoop-ai-chat-1", "invocationId": "job-00000001:1:chat-router", "stage": "chat-router", "status": "succeeded",
        "answer": {"requirements": [{"requirementId": "r1", "types": {"Q01": 0.02, "Q02": 0.95, "Q03": 0.04, "Q04": 0.01, "Q05": 0.01,
                                                                      "Q06": 0.01, "Q07": 0.01, "Q08": 0.01},
                                     "capabilities": {}, "prohibitedAdvice": 0.02}]},
        "failure": None, "receipt": receipt})
    failed = ChatStageResult.model_validate({
        "schemaVersion": "zoop-ai-chat-1", "invocationId": "job-00000001:1:chat-answer", "stage": "chat-answer", "status": "failed",
        "answer": None, "failure": {"code": "source_grant_denied", "sent": False, "unknown": False}, "receipt": None})
    return {"request": request.wire(), "succeeded": succeeded.wire(), "failed": failed.wire()}


def document(spec: dict[str, Any]) -> None:
    sample = examples()
    schemas = spec["components"]["schemas"]
    request = ChatStageRequest.model_json_schema(by_alias=True, ref_template="#/components/schemas/{model}")
    for name, definition in request.pop("$defs", {}).items():
        schemas.setdefault(name, definition)
    schemas["ChatStageRequest"] = request
    operation = spec["paths"]["/internal/v1/chat-stages/{stage}"]["post"]
    operation["requestBody"] = {"required": True, "content": {"application/json": {
        "schema": {"$ref": "#/components/schemas/ChatStageRequest"},
        "examples": {"router": {"summary": "chat-router replay request (synthetic question)", "value": sample["request"]}}}}}
    operation["responses"]["200"]["content"]["application/json"]["examples"] = {
        "succeeded": {"summary": "Router probabilities", "value": sample["succeeded"]},
        "notSent": {"summary": "A quote without a matching chat grant: nothing was sent", "value": sample["failed"]}}
