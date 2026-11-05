"""Closed resource and installed-runtime wire views; service never selects a job policy."""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class ResourceWire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid", strict=True)

    def wire(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Code = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,64}$")]
Effort = Literal["none", "low", "medium", "high", "xhigh", "max"]
STAGES = ("chat-router", "chat-answer", "chat-verification", "chat-agent")
TIME_MODEL = {"workerProcessMarginMs": 5000, "workerTerminationGraceMs": 5000, "serviceSlotWaitMs": 1000,
              "httpTransportDecodeMs": 2000, "applicationModelRecordingMs": 6000, "applicationGuardMs": 1000}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class LunaResources(ResourceWire):
    max_input_tokens: int = Field(ge=1, le=922000)
    max_output_tokens: int = Field(ge=32000, le=128000)
    max_visible_output_tokens: int = Field(ge=4000, le=64000)
    max_answer_chars: int = Field(ge=12000, le=96000)
    generated_text_max_chars: int = Field(ge=10976, le=94976)
    reasoning_effort: Effort

    @model_validator(mode="after")
    def bounds(self):
        if (self.max_input_tokens + self.max_output_tokens > 1050000
                or self.max_visible_output_tokens >= self.max_output_tokens
                or self.generated_text_max_chars != self.max_answer_chars - 1024):
            raise ValueError("chat_resource_policy_invalid")
        return self


class Resources(ResourceWire):
    schema_version: Literal["zoop-chat-resource-1"]
    policy_revision: str = Field(pattern=r"^[A-Za-z0-9._-]{1,96}$")
    policy_digest: Sha256
    runtime_fingerprint: Sha256
    provider_timeout_ms: int = Field(ge=1, le=2147483647)
    finalizing: bool
    luna: LunaResources | None
    allocation_digest: Sha256


class ResourceBinding(ResourceWire):
    schema_version: Literal["zoop-chat-resource-binding-1"]
    policy_digest: Sha256
    runtime_fingerprint: Sha256
    allocation_digest: Sha256


class ModelLimits(ResourceWire):
    context_window_tokens: Literal[1050000]
    max_input_tokens: Literal[922000]
    max_output_tokens: Literal[128000]


class StructuralLimits(ResourceWire):
    max_sections: Literal[12]
    max_claims_per_section: Literal[20]
    max_citations: Literal[20]
    max_answer_chars: Literal[96000]
    server_added_text_reserve_chars: Literal[1024]


class TimeModel(ResourceWire):
    worker_process_margin_ms: Literal[5000]
    worker_termination_grace_ms: Literal[5000]
    service_slot_wait_ms: Literal[1000]
    http_transport_decode_ms: Literal[2000]
    application_model_recording_ms: Literal[6000]
    application_guard_ms: Literal[1000]


class StageCapability(ResourceWire):
    provider: Literal["openai-compatible", "typesafe-native"]
    model: Literal["gpt-6-luna", "jev-1.14.0"]
    api: Literal["responses", "systemone"]
    adapter_revision: str = Field(pattern=r"^[A-Za-z0-9._-]{1,96}$")
    adapter_digest: Sha256
    provider_revision: Sha256 | None
    mcp_server_revision: Sha256 | None
    fixed_input_overhead_bytes: int = Field(ge=0, le=2147483647)


class CapabilitiesRuntime(ResourceWire):
    worker_contract_revision: Literal["zoop-chat-worker-resource-1"]
    stage_schema_version: Literal["zoop-ai-chat-6"]
    resource_schema_version: Literal["zoop-chat-resource-1"]
    model_limits: ModelLimits
    structural_limits: StructuralLimits
    supported_reasoning_efforts: list[Effort]
    default_reasoning_effort: Literal["medium"]
    stages: dict[str, StageCapability]
    time_model: TimeModel

    @model_validator(mode="after")
    def contract(self):
        if set(self.stages) != set(STAGES) or self.supported_reasoning_efforts != ["none", "low", "medium", "high", "xhigh", "max"]:
            raise ValueError("chat_runtime_contract_mismatch")
        for stage, descriptor in self.stages.items():
            luna = stage in ("chat-answer", "chat-agent")
            expected = ("openai-compatible", "gpt-6-luna", "responses", "zoop-" + stage + "-resource-1") if luna else (
                "typesafe-native", "jev-1.14.0", "systemone", "zoop-jev-chat-10")
            if (descriptor.provider, descriptor.model, descriptor.api, descriptor.adapter_revision) != expected:
                raise ValueError("chat_runtime_contract_mismatch")
            if (not luna and descriptor.fixed_input_overhead_bytes != 0) or (luna and descriptor.fixed_input_overhead_bytes == 0):
                raise ValueError("chat_runtime_contract_mismatch")
            if stage != "chat-agent" and descriptor.mcp_server_revision is not None:
                raise ValueError("chat_runtime_contract_mismatch")
        return self


class ChatCapabilities(ResourceWire):
    schema_version: Literal["zoop-ai-chat-6"]
    capabilities_schema_version: Literal["zoop-chat-capabilities-1"]
    runtime_fingerprint: Sha256
    runtime: CapabilitiesRuntime
    configuration_errors: dict[str, Code | None]

    @model_validator(mode="after")
    def identity(self):
        if set(self.configuration_errors) != set(STAGES) or digest(self.runtime.wire()) != self.runtime_fingerprint:
            raise ValueError("chat_runtime_contract_mismatch")
        return self
