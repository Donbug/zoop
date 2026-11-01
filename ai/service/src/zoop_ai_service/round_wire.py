"""Closed #387 round wire; application slot ids never stand in for ingestion ids."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from .handoff_wire import ARTICLE_ID_PATTERN
from .wire import Wire

ROUND_ID_PATTERN = r"^round-[0-9]{8}T[0-9]{4}$"
RoundId = Annotated[str, StringConstraints(pattern=ROUND_ID_PATTERN)]
Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Name = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,200}$")]
PlanId = Annotated[str, StringConstraints(pattern=r"^s2plan-[0-9a-f]{64}$")]
Code = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class RoundWire(Wire):
    model_config = ConfigDict(alias_generator=Wire.model_config["alias_generator"], populate_by_name=False, extra="forbid", strict=True)

    def wire(self):
        return self.model_dump(by_alias=True, mode="json", exclude_none=True)


class RunRequest(RoundWire):
    schema_version: Literal["zoop-ai-round-run-1"]
    round_id: RoundId


class DocumentBinding(RoundWire):
    document_id: str = Field(min_length=1, max_length=200)
    document_version: Hash
    article_id: Annotated[str, StringConstraints(pattern=ARTICLE_ID_PATTERN)]
    article_version: Hash
    text_sha256: Hash
    offset_unit: Literal["unicode_code_point"]


class DocumentBindings(RoundWire):
    schema_version: Literal["zoop-app-document-bindings-1"]
    bindings: list[DocumentBinding] = Field(max_length=20000)

    @model_validator(mode="after")
    def unique(self):
        if len({(b.document_id, b.document_version) for b in self.bindings}) != len(self.bindings) or len({
                (b.article_id, b.article_version) for b in self.bindings}) != len(self.bindings):
            raise ValueError("duplicate binding")
        return self


class HandoffRequest(RoundWire):
    schema_version: Literal["zoop-ai-round-handoff-1"]
    round_id: RoundId
    ingestion_round_id: Name | None = None
    plan_id: PlanId | None = None
    bindings: DocumentBindings


class RunStatus(RoundWire):
    schema_version: Literal["zoop-ai-round-run-1"] = "zoop-ai-round-run-1"
    round_id: RoundId
    state: Literal["running", "ready", "no_new_material", "failed"]
    ingestion_round_id: Name | None = None
    plan_id: PlanId | None = None
    plan_digest: Hash | None = None
    code: Code | None = None
    observed_at: str

    @model_validator(mode="after")
    def pins(self):
        if (self.plan_id is None) != (self.plan_digest is None) or ((self.state == "ready") != (self.plan_id is not None)):
            raise ValueError("plan pins")
        if self.state == "ready" and self.ingestion_round_id is None or self.state in {"failed", "no_new_material"} and self.code is None:
            raise ValueError("state fields")
        return self


class HandoffStatus(RoundWire):
    schema_version: Literal["zoop-ai-round-handoff-1"] = "zoop-ai-round-handoff-1"
    round_id: RoundId
    state: Literal["running", "ready", "analysis_incomplete", "no_public_material", "failed"]
    handoff_id: Name | None = None
    manifest_digest: Hash | None = None
    bundle_digest: Hash | None = None
    selection: dict[str, Any] | None = None
    code: Code | None = None
    observed_at: str

    @model_validator(mode="after")
    def pins(self):
        pins = (self.handoff_id, self.manifest_digest, self.bundle_digest)
        if self.state == "ready" and any(p is None for p in pins) or self.state != "ready" and any(p is not None for p in pins):
            raise ValueError("handoff pins")
        if self.state in {"failed", "analysis_incomplete", "no_public_material"} and self.code is None:
            raise ValueError("state code")
        if self.state == "no_public_material" and (self.code != "window_empty" or self.selection is None):
            raise ValueError("empty selection")
        return self
