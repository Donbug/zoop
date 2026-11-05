"""Content-free installed-worker contract and per-invocation resource admission."""
from __future__ import annotations

import os
from typing import Any

from . import chat_agent, chat_jev, chat_luna
from .chat_contracts import CHAT_SCHEMA_VERSION, INPUTS, AgentInput, ChatAnswer, StageRequest
from .contracts import canonical, digest
from .provider import DEFAULT_BASE_URL, NATIVE_DEFAULT_BASE_URL, ProviderError, native_revision, validate_base_url

EFFORTS = ["none", "low", "medium", "high", "xhigh", "max"]
TIME_MODEL = {"workerProcessMarginMs": 5000, "workerTerminationGraceMs": 5000,
              "serviceSlotWaitMs": 1000, "httpTransportDecodeMs": 2000,
              "applicationModelRecordingMs": 6000, "applicationGuardMs": 1000}
OPTIONS = {"chat-answer": {"api": "responses", "store": False, "tools": "none"},
           "chat-agent": {"api": "responses", "store": True, "serverLabel": "zoop", "requireApproval": "always"}}


def validate_endpoint(base: str) -> None:
    url = validate_base_url(base)
    if not url.host or url.username or url.password or url.query or url.fragment:
        raise ProviderError("provider_requires_https")


def adapter(stage: str) -> dict[str, Any]:
    module = chat_luna if stage == "chat-answer" else chat_agent
    options = OPTIONS[stage]
    answer_schema = ChatAnswer.model_json_schema(by_alias=True)
    identity = {"stage": stage, "adapterRevision": module.PROMPT_REVISION, "promptTemplate": module.PROMPT,
                "inputSchema": INPUTS[stage].model_json_schema(by_alias=True), "answerSchema": answer_schema,
                "providerOptions": options}
    overhead = len((module.PROMPT + canonical(answer_schema) + canonical(options)).encode("utf-8")) + 4096
    if stage == "chat-agent":
        overhead += 65536
    return {"adapterDigest": digest(identity), "fixedInputOverheadBytes": overhead}


def capabilities(env: dict[str, str] | None = None) -> dict[str, Any]:
    # Import locally so the manifest remains owned by the worker, without a service dependency.
    from .chat_runtime import LiveSender, stage_config

    env = os.environ if env is None else env
    stages, errors = {}, {}
    for stage in INPUTS:
        luna = stage in OPTIONS
        module = chat_luna if stage == "chat-answer" else chat_agent
        descriptor = {"provider": "openai-compatible" if luna else "typesafe-native",
                      "model": "gpt-6-luna" if luna else chat_jev.MODEL,
                      "api": "responses" if luna else "systemone",
                      "adapterRevision": module.PROMPT_REVISION if luna else chat_jev.ADAPTER_REVISION,
                      "adapterDigest": adapter(stage)["adapterDigest"] if luna else chat_jev.identity(stage),
                      "providerRevision": None, "mcpServerRevision": None,
                      "fixedInputOverheadBytes": adapter(stage)["fixedInputOverheadBytes"] if luna else 0}
        error = None
        try:
            config = stage_config(stage, "live", env)
            descriptor["providerRevision"] = config.provider_revision
            if config.mcp_server_url is not None:
                descriptor["mcpServerRevision"] = digest({"serverUrl": config.mcp_server_url})
            LiveSender(env).preflight(None, config)
        except ProviderError as invalid:
            error = invalid.code
        try:
            base = (env.get("ZOOP_AI_BASE_URL", "").strip() or DEFAULT_BASE_URL) if luna else (
                env.get("TYPESAFE_BASE_URL", "").strip() or NATIVE_DEFAULT_BASE_URL)
            validate_endpoint(base)
            if not luna and "/systemone" in base:
                raise ProviderError("native_base_url_includes_endpoint_path")
            descriptor["providerRevision"] = digest({"endpoint": base}) if luna else native_revision(base)
        except ProviderError:
            pass  # The stage configuration below supplies the stable readiness error.
        if stage == "chat-agent":
            try:
                descriptor["mcpServerRevision"] = digest({"serverUrl": chat_agent.server_url(
                    env.get("ZOOP_AI_CHAT_MCP_SERVER_URL", ""))})
            except ValueError:
                pass  # Invalid operator URLs remain readiness errors, never fingerprinted raw values.
        stages[stage], errors[stage] = descriptor, error
    runtime = {"workerContractRevision": "zoop-chat-worker-resource-1", "stageSchemaVersion": CHAT_SCHEMA_VERSION,
               "resourceSchemaVersion": "zoop-chat-resource-1",
               "modelLimits": {"contextWindowTokens": 1050000, "maxInputTokens": 922000, "maxOutputTokens": 128000},
               "structuralLimits": {"maxSections": 12, "maxClaimsPerSection": 20, "maxCitations": 20,
                                    "maxAnswerChars": 96000, "serverAddedTextReserveChars": 1024},
               "supportedReasoningEfforts": EFFORTS, "defaultReasoningEffort": "medium",
               "stages": stages, "timeModel": TIME_MODEL}
    return {"schemaVersion": CHAT_SCHEMA_VERSION, "capabilitiesSchemaVersion": "zoop-chat-capabilities-1",
            "runtimeFingerprint": digest(runtime), "runtime": runtime, "configurationErrors": errors}


def validate(request: StageRequest, env: dict[str, str] | None = None) -> None:
    resources = request.resources
    if request.schema_version != CHAT_SCHEMA_VERSION or resources is None:
        raise ProviderError("chat_runtime_contract_mismatch")
    values = resources.wire()
    values.pop("allocationDigest")
    expected = digest({"schemaVersion": "zoop-chat-resource-allocation-1", "stage": request.stage,
                       "mode": request.mode, "resources": values})
    luna = request.stage in OPTIONS
    if (expected != resources.allocation_digest or luna != (resources.luna is not None)
            or (not luna and resources.finalizing) or (request.stage == "chat-answer" and not resources.finalizing)):
        raise ProviderError("chat_resource_policy_invalid")
    payload = request.parsed()
    if (resources.finalizing and isinstance(payload, AgentInput) and payload.continuation is not None
            and any(item.approve for item in payload.continuation.decisions)):
        raise ProviderError("chat_resource_policy_invalid")
    current = capabilities(env)
    error = current["configurationErrors"][request.stage]
    if error is not None and not (request.mode == "replay" and error in ("provider_key_required", "provider_key_invalid")):
        raise ProviderError(error)
    if current["runtimeFingerprint"] != resources.runtime_fingerprint:
        raise ProviderError("chat_runtime_contract_mismatch")


def check_fixed_material(stage: str, body: dict[str, Any]) -> None:
    fixed = body["instructions"] + canonical(ChatAnswer.model_json_schema(by_alias=True)) + canonical(OPTIONS[stage])
    if len(fixed.encode("utf-8")) > adapter(stage)["fixedInputOverheadBytes"]:
        raise ProviderError("chat_runtime_contract_mismatch")
