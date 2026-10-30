"""Authored OpenAPI semantics and examples of the chatbot model stage family. Every example is built through the real wire models, so an example that
stops validating fails at generation; the route and model schemas themselves come from the application (`app.openapi()`)."""
from __future__ import annotations

from typing import Any

from .chat_wire import ChatMcpHealth, ChatStageRequest, ChatStageResult

DESCRIPTION = """\
**Chat stages (`/internal/v1/chat-stages/{stage}`, contract `zoop-ai-chat-2`, scope `chat.invoke`).** A fifth, separate family that runs ONE chatbot model
stage synchronously through the installed `zoop-ai-chat invoke`: `chat-router` (native Jev, typed probabilities per requirement), `chat-answer` (Luna, a strict
JSON answer by sections), `chat-verification` (native Jev, per-section support and prohibited-advice verdicts) or `chat-agent` (one step of a Luna Responses run
that calls the ZOOP MCP tools). It is off unless its all-or-nothing server configuration group is set (otherwise 409 `execution_unavailable` after
authentication). The application decides everything a stage only proposes.

**Agent steps.** Every MCP tool call of a `chat-agent` run is held for the application (`require_approval=always`), and the runtime never approves anything. A step
ends `approval_required` (the held calls, no answer) or `completed` (the final answer). The application decides each request, reserves the calls it approves on its
own ledger and resumes the stored response (`continuation.previousResponseId`, so the provider stores responses) with its decisions in a NEW step with its own
invocation id. The input carries the application's job-scoped MCP grant token; the runtime sends it only to the provider, as the MCP tool's `authorization`,
and keeps it out of every identity and stored answer. The MCP server URL is never part of a request: it is the operator's `ZOOP_AI_CHAT_MCP_SERVER_URL`.
`mcp.recipient` names the recipient the application checked its MCP results' send grants for (those results reach the provider from the application, not
through this runtime); a step is sent only when it is exactly the stage's own recipient, otherwise it fails `mcp_recipient_mismatch` with nothing sent.

**Once per invocation.** `invocationId` (equal to `Idempotency-Key`) names one stage of one attempt. The runtime sends it at most once: the same id and input
return the stored outcome, another input under the same id is the stage failure `invocation_conflict`, and a request whose outcome is unknown stays `unknown`.
The id is bound to the calling principal. A **200** carries the stage outcome: `status=succeeded` with the typed `answer`, or `status=failed` with a stable
`failure.code`, whether a request was `sent` and whether its fate is `unknown`. A **502/504 `stage_outcome_unknown`** means the runtime may have sent the
request: never resend that invocation. A **503** means nothing was sent.

**Verification server facts.** The v2 verification input has `requestBinding` (`invocationId`, pinned `graphVersionId`, `asOf`)
and ordered sections (`sectionId`, `requirementIds`, `basis`, `text`, `evidenceIds`, `serverFacts`). The application alone
derives bounded typed `portfolio_scope`, `graph_comparison`, `publication_record` and `briefing_selection` facts from
successful reads in that request, never from answer text. A publication record is an issue's last review decision (kind,
time and path, never the decider or their note) up to the pinned version's review revision and the rules that version was
filtered with; a briefing selection is a published round's rank and recorded reason for an issue. Facts are scoped to their parent requirement and section, separate from granted article quotes. Membership is current
at the read, not historical asOf membership; a truncated list cannot establish completeness or absence. Graph facts name
the exact baseline, current version, asOf, since, query targets and limits. Missing observations supply no facts. The
service rejects a binding to another invocation before launching the worker; the worker rejects wrong sections,
requirements, versions or extra fields. Old stage envelopes are refused; the independent source-grant registry stays v1.

**Live and rights.** Nothing reaches a provider unless the chat gate is open (`ZOOP_AI_CHAT_LIVE_ENABLED=1` and a positive `ZOOP_AI_CHAT_MAX_CALLS`, shared by
the chat stages and separate from the S1 and pipeline gates), and quoted spans are sent only under the operator chat grant registry (`model-send`, the stage
as purpose and the exact recipient). Stage time limits: router 4 s, answer 25 s, verification 6 s, agent step 30 s.

**MCP preflight (`GET /internal/v1/chat-mcp-health`).** Under the same `chat.invoke` scope, the service runs `zoop-ai-chat probe-mcp` with no request body,
grant, model call, ledger row or live-budget charge. The child sends a content-free JSON-RPC `ping` to the operator-configured MCP URL and treats only that
endpoint's own `401` Bearer challenge as `reachable`. Timeout, connection failure and any other status are a 200 `unreachable` health answer with a closed
reason. A missing or invalid operator URL is 503 configuration error; an unreadable child outcome is `probe_failed`. Callers use this before starting a
Responses run; this route does not itself select a direct path or maintain the application's circuit breaker.
"""

EV = "ev-" + "1" * 64


def examples() -> dict[str, Any]:
    request = ChatStageRequest.model_validate({
        "schemaVersion": "zoop-ai-chat-2", "invocationId": "job-00000001:1:chat-router", "stage": "chat-router", "mode": "replay",
        "input": {"turns": [{"text": "HBM이 뭐야?"}], "requirements": [{"requirementId": "r1", "text": "HBM이 뭐야", "explicit": True}],
                  "capabilities": []}})
    receipt = {"provider": "authored-replay", "providerRevision": "authored-replay-1", "model": "authored-synthetic-chat-router",
               "promptVersion": "zoop-jev-chat-router-0123456789abcdef", "executionMode": "replay",
               "usage": {"inputTokens": None, "outputTokens": None, "cachedTokens": None, "reasoningTokens": None},
               "sentAt": "2026-10-22T03:00:00+00:00", "receivedAt": "2026-10-22T03:00:01+00:00"}
    succeeded = ChatStageResult.model_validate({
        "schemaVersion": "zoop-ai-chat-2", "invocationId": "job-00000001:1:chat-router", "stage": "chat-router", "status": "succeeded",
        "answer": {"requirements": [{"requirementId": "r1", "types": {"Q01": 0.02, "Q02": 0.95, "Q03": 0.04, "Q04": 0.01, "Q05": 0.01,
                                                                      "Q06": 0.01, "Q07": 0.01, "Q08": 0.01},
                                     "capabilities": {}, "prohibitedAdvice": 0.02}]},
        "failure": None, "receipt": receipt})
    failed = ChatStageResult.model_validate({
        "schemaVersion": "zoop-ai-chat-2", "invocationId": "job-00000001:1:chat-answer", "stage": "chat-answer", "status": "failed",
        "answer": None, "failure": {"code": "source_grant_denied", "sent": False, "unknown": False}, "receipt": None})
    agent = ChatStageRequest.model_validate({
        "schemaVersion": "zoop-ai-chat-2", "invocationId": "job-00000001:1:chat-agent:2", "stage": "chat-agent", "mode": "replay",
        "input": {"turns": [{"text": "SK하이닉스 최근 사건 알려줘"}],
                  "requirements": [{"requirementId": "r1", "label": "SK하이닉스 최근 사건", "general": False}],
                  "mcp": {"authorization": "zmcp1.k1.synthetic-grant-token.synthetic-mac", "allowedTools": ["company_read", "issue_read"],
                          "recipient": "authored-replay"},
                  "maxCitations": 20,
                  "continuation": {"previousResponseId": "resp_synthetic_1",
                                   "decisions": [{"approvalRequestId": "mcpr_synthetic_1", "approve": True}]}}})
    held = ChatStageResult.model_validate({
        "schemaVersion": "zoop-ai-chat-2", "invocationId": "job-00000001:1:chat-agent:1", "stage": "chat-agent", "status": "succeeded",
        "answer": {"responseId": "resp_synthetic_1", "status": "approval_required", "answer": None, "mcpCalls": [],
                   "approvalRequests": [{"approvalRequestId": "mcpr_synthetic_1", "toolName": "company_read",
                                         "arguments": {"targets": ["KRX:000660"]}}]},
        "failure": None, "receipt": {**receipt, "model": "authored-synthetic-chat-agent", "promptVersion": "zoop-chat-agent-0123456789abcdef"}})
    reachable = ChatMcpHealth.model_validate({"schemaVersion": "zoop-ai-chat-2", "mcp": "reachable"})
    unreachable = ChatMcpHealth.model_validate({"schemaVersion": "zoop-ai-chat-2", "mcp": "unreachable", "reason": "mcp_timeout"})
    return {"request": request.wire(), "succeeded": succeeded.wire(), "failed": failed.wire(), "agent": agent.wire(), "held": held.wire(),
            "reachable": reachable.wire(), "unreachable": unreachable.wire()}


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
        "examples": {"router": {"summary": "chat-router replay request (synthetic question)", "value": sample["request"]},
                     "agentContinuation": {"summary": "chat-agent continuation step with the application's decision (synthetic token)",
                                           "value": sample["agent"]}}}}}
    operation["responses"]["200"]["content"]["application/json"]["examples"] = {
        "succeeded": {"summary": "Router probabilities", "value": sample["succeeded"]},
        "notSent": {"summary": "A quote without a matching chat grant: nothing was sent", "value": sample["failed"]},
        "agentHeld": {"summary": "chat-agent step held at an approval request", "value": sample["held"]}}
    health = spec["paths"]["/internal/v1/chat-mcp-health"]["get"]
    health["responses"]["200"]["content"]["application/json"]["examples"] = {
        "reachable": {"summary": "The configured endpoint answered its Bearer challenge", "value": sample["reachable"]},
        "unreachable": {"summary": "No answer before the content-free probe deadline", "value": sample["unreachable"]}}
