"""Closed online plan-admission wire contract and stateless request parsing.

No authority, clock, filesystem or pipeline access belongs here. The core alone
checks configured principals, current policy, expiry, CAS, quota and identity.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, TypeAdapter, model_validator

from .extraction_wire import ExtractionSubmit
from .jobs import ApiError
from .relation_wire import HASH_PATTERN, JOB_ID_PATTERN, RelationProvenance, RelationSubmit, Request
from .wire import ErrorBody, Safe

SCHEMA = "zoop-ai-plan-admission-1"
PLAN_ID_PATTERN = r"^s2plan-[0-9a-f]{64}$"
POLICY_ETAG_PATTERN = r'^"plan-policy-(?:0-none|[1-9][0-9]*-[0-9a-f]{64})"$'
MAX_BODY = 2_000_000
MAX_REPLY = 16_000_000
Hash = Annotated[str, Field(pattern=HASH_PATTERN)]
MAX_COUNTER = 9_223_372_036_854_775_807
PlanId = Annotated[str, Field(pattern=PLAN_ID_PATTERN)]
Identifier = Annotated[str, Field(min_length=1, max_length=200)]


class PlanReference(Request):
    schema_version: Literal["zoop-ai-plan-admission-1"]
    plan_id: PlanId
    plan_digest: Hash


class PlanRound(Request):
    source_id: Identifier
    round_id: Identifier
    ingestion_input_digest: Hash


class PlanUnit(Request):
    unit_key: str = Field(pattern=JOB_ID_PATTERN)
    extraction_submit: ExtractionSubmit
    extraction_input_digest: Hash
    relation_submit: RelationSubmit

    @model_validator(mode="after")
    def bindings(self) -> PlanUnit:
        if (self.unit_key != self.extraction_submit.job_id
                or self.relation_submit.upstream.job_id != self.unit_key
                or self.relation_submit.upstream.input_digest != self.extraction_input_digest
                or not re.fullmatch(r"s3p-[0-9a-f]{64}", self.relation_submit.job_id)):
            raise ValueError("unit binding mismatch")
        return self


class PublicManifest(Request):
    schema_version: Literal["zoop-ai-plan-manifest-1"]
    plan_id: PlanId
    plan_digest: Hash
    receipt_sha256: Hash
    principal: str = Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")
    round: PlanRound
    provenance: RelationProvenance
    units: list[PlanUnit]
    manifest_digest: Hash

    @model_validator(mode="after")
    def bindings(self) -> PublicManifest:
        if len({unit.unit_key for unit in self.units}) != len(self.units):
            raise ValueError("duplicate unit")
        if any(unit.relation_submit.provenance != self.provenance for unit in self.units):
            raise ValueError("provenance mismatch")
        return self


class PlanAuthorityState(Request):
    state: Literal["active", "inactive"]
    reason: Safe | None

    @model_validator(mode="after")
    def reason_matches(self) -> PlanAuthorityState:
        if (self.state == "active") != (self.reason is None):
            raise ValueError("authority reason mismatch")
        return self


class PlanAdmissionEnvelope(Request):
    schema_version: Literal["zoop-ai-plan-admission-1"] = SCHEMA
    admission_id: str = Field(pattern=r"^pa-[0-9a-f]{64}$")
    accepted_at: str
    policy_revision: int = Field(gt=0, le=MAX_COUNTER)
    policy_digest: Hash
    manifest: PublicManifest
    authority: PlanAuthorityState


class PlanErrorEnvelope(Request):
    schema_version: Literal["zoop-ai-plan-admission-1"] = SCHEMA
    error: ErrorBody


class PlanPolicyDisabled(Request):
    schema_version: Literal["zoop-ai-plan-policy-1"]
    enabled: Literal[False]

    @model_validator(mode="before")
    @classmethod
    def strict_enabled(cls, value: Any) -> Any:
        if isinstance(value, dict) and type(value.get("enabled")) is not bool:
            raise ValueError("enabled must be boolean")
        return value


class PlanPolicyTopic(Request):
    producer_version: Literal["zoop-topic-replay-producer-1"]


class PlanReplayRuntime(Request):
    kind: Literal["replay"]
    producer_replay_digest: Hash
    topic_replay_digest: Hash | None
    relation_replay_digest: Hash
    relation_verifier_replay_digest: Hash


class PlanLiveRuntime(Request):
    kind: Literal["live"]
    live_runtime_identity: Hash


class PlanPolicyLimits(Request):
    max_plans: int = Field(gt=0, le=MAX_COUNTER)
    max_units: int = Field(gt=0, le=MAX_COUNTER)


class PlanPolicyEnabled(Request):
    schema_version: Literal["zoop-ai-plan-policy-1"]
    enabled: Literal[True]
    principal: str = Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")
    source_ids: list[Identifier] = Field(min_length=1, max_length=10_000, json_schema_extra={"uniqueItems": True})
    source_kind: Literal["synthetic", "actual"]
    expires_at: str
    prompt_version: Identifier
    catalogue_digest: Hash
    snapshot_digest: Hash
    topic: PlanPolicyTopic | None
    runtime: Annotated[PlanReplayRuntime | PlanLiveRuntime, Field(discriminator="kind")]
    limits: PlanPolicyLimits

    @model_validator(mode="before")
    @classmethod
    def strict_enabled(cls, value: Any) -> Any:
        if isinstance(value, dict) and type(value.get("enabled")) is not bool:
            raise ValueError("enabled must be boolean")
        return value

    @model_validator(mode="after")
    def structure(self) -> PlanPolicyEnabled:
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("duplicate source")
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)", self.expires_at):
            raise ValueError("expiry must be UTC")
        datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        if isinstance(self.runtime, PlanReplayRuntime) and ((self.topic is None) != (self.runtime.topic_replay_digest is None)):
            raise ValueError("topic runtime mismatch")
        return self


PlanPolicy = Annotated[PlanPolicyDisabled | PlanPolicyEnabled, Field(discriminator="enabled")]
_POLICY = TypeAdapter(PlanPolicy)


class PlanPolicyUsage(Request):
    plans: int = Field(ge=0, le=MAX_COUNTER)
    units: int = Field(ge=0, le=MAX_COUNTER)


class PlanPolicyState(Request):
    schema_version: Literal["zoop-ai-plan-policy-state-1"] = "zoop-ai-plan-policy-state-1"
    revision: int = Field(ge=0, le=MAX_COUNTER)
    policy_digest: Hash | None
    policy: PlanPolicy | None
    status: Literal["unconfigured", "enabled", "disabled", "expired"]
    usage: PlanPolicyUsage

    @model_validator(mode="after")
    def revision_matches(self) -> PlanPolicyState:
        if (self.revision == 0) != (self.policy is None and self.policy_digest is None and self.status == "unconfigured"):
            raise ValueError("policy state mismatch")
        if self.revision > 0 and (self.policy is None or self.policy_digest is None or self.status == "unconfigured"):
            raise ValueError("policy state missing")
        return self


class PlanPolicyUpdate(Request):
    schema_version: Literal["zoop-ai-plan-policy-update-1"] = "zoop-ai-plan-policy-update-1"
    operation_id: str = Field(pattern=JOB_ID_PATTERN)
    revision: int = Field(gt=0, le=MAX_COUNTER)
    policy_digest: Hash
    changed: bool


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _constant(_: str) -> Any:
    raise ValueError("non-finite number")


def _float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite number")
    return number


def _document(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_BODY:
        raise ApiError(413, "request_too_large")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float)
        if not isinstance(document, dict):
            raise ValueError("object required")
        # JSON escapes must not smuggle lone surrogates past the strict UTF-8 boundary.
        json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return document
    except (UnicodeError, ValueError, RecursionError):
        raise ApiError(422, "invalid_request", field="body") from None


def parse_plan_reference(raw: bytes, key: str) -> PlanReference:
    try:
        # Validate aliases only at the HTTP boundary, not Python attribute spellings.
        reference = PlanReference.model_validate(_document(raw), by_alias=True, by_name=False)
    except (ValueError, RecursionError):
        raise ApiError(422, "invalid_request", field="body") from None
    if reference.plan_id != key:
        raise ApiError(422, "invalid_request", field="Idempotency-Key")
    return reference


def parse_plan_policy_document(document: dict[str, Any]) -> dict[str, Any]:
    try:
        return _POLICY.validate_python(document, by_alias=True, by_name=False).wire()
    except (ValueError, RecursionError):
        raise ApiError(422, "invalid_request", field="body") from None


def parse_plan_policy(raw: bytes) -> dict[str, Any]:
    return parse_plan_policy_document(_document(raw))
