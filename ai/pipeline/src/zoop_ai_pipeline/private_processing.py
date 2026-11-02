"""Private corpus permissions and separate finite-set execution bindings; never public grants."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, ValidationError, model_validator

from .ingestion_contracts import (
    Authority, IngestionFailure, Item, MAX_INPUT, NAVER_SEARCH, Registry, Run, Wire,
    byte_hash, canonical, read_file, timestamp,
)

Hash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")]


class Pin(Wire):
    path: str = Field(min_length=1)
    sha256: Hash

    @model_validator(mode="after")
    def absolute(self):
        if not Path(self.path).is_absolute():
            raise ValueError("absolute pinned path required")
        return self


class Actor(Wire):
    kind: Literal["user-private-experiment"]
    accepted_by: Literal["Main"]
    decided_at: str
    statement: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def decision(self):
        timestamp(self.decided_at)
        if not self.statement.strip():
            raise ValueError("decision statement required")
        return self


class Use(Wire):
    public_use: Literal[False]
    redistribution: Literal[False]
    publication: Literal["not-published"]


class Send(Wire):
    purpose: str = Field(min_length=1, max_length=200)
    recipient: str = Field(pattern=r"^(?:openai-compatible|typesafe-native):[a-f0-9]{64}$")


class Execution(Wire):
    set_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,200}$")
    funding_policy: Literal["zoop-set-funding-2", "zoop-set-funding-3"]


class PrivateInput(Wire):
    kind: Literal["private-record"]
    state_dir: str = Field(min_length=1)
    private_id: str = Field(min_length=1, max_length=200)
    record_schema: Literal["zoop-private-news-record-1", "zoop-private-news-record-2", "zoop-private-news-record-3", "zoop-official-source-record-1"]
    record_sha256: Hash
    body_sha256: Hash

    @model_validator(mode="after")
    def absolute(self):
        if not Path(self.state_dir).is_absolute():
            raise ValueError("absolute retained path required")
        return self


class HttpInput(Wire):
    kind: Literal["collected-http"]
    candidate_id: str = Field(min_length=1, max_length=200)
    receipt_sha256: Hash
    body_sha256: Hash


class Observation(Wire):
    round_id: str = Field(min_length=1, max_length=200)
    page: int = Field(ge=0)
    ordinal: int = Field(ge=0)
    document_id: str = Field(min_length=1, max_length=200)
    raw_version: Hash
    document_version: Hash


class PublisherRights(Wire):
    status: Literal["unconfirmed", "unknown", "known"]
    evidence: list[Pin] = Field(max_length=100)

    @model_validator(mode="after")
    def known_evidence(self):
        if self.status == "known" and not self.evidence:
            raise ValueError("known rights require pinned evidence")
        return self


class Acquisition(Wire):
    """Original native authority/proofs stay current independently of copied corpus registries."""
    registry: Pin
    proofs: list[Pin] = Field(min_length=1, max_length=100)


class Member(Wire):
    source_id: str = Field(min_length=1, max_length=200)
    scope_id: str = Field(min_length=1, max_length=200)
    input: Annotated[PrivateInput | HttpInput, Field(discriminator="kind")]
    observation: Observation | None
    text_sha256: Hash | None
    publisher_rights: PublisherRights
    acquisition: Acquisition | None

    @model_validator(mode="after")
    def rights(self):
        if isinstance(self.input, PrivateInput) and self.publisher_rights.status != "unconfirmed":
            raise ValueError("retained publisher rights remain unconfirmed")
        if isinstance(self.input, HttpInput) != (self.acquisition is not None):
            raise ValueError("native members require original acquisition pins")
        return self


class Segment(Wire):
    schema_version: Literal["zoop-private-processing-1"]
    authorization_id: Identifier
    phase: Literal["import", "process"]
    registry: Pin
    actor: Actor
    use: Use
    sends: list[Send] = Field(max_length=100)
    members: list[Member] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def phase_fields(self):
        processing = self.phase == "process"
        if any((m.observation is not None) != processing or (m.text_sha256 is not None) != processing for m in self.members):
            raise ValueError("phase membership conflict")
        if not processing and self.sends:
            raise ValueError("imports never send")
        identities = [canonical([m.source_id, m.scope_id, m.input.wire(), m.observation.wire() if m.observation else None]) for m in self.members]
        if len(set(identities)) != len(identities) or len({(s.purpose, s.recipient) for s in self.sends}) != len(self.sends):
            raise ValueError("duplicate member or send")
        return self


class ExecutionReceipt(Wire):
    schema_version: Literal["zoop-private-execution-1"]
    execution_id: Identifier
    execution: Execution | None
    runtime_identities: list[Hash] = Field(max_length=100)
    registry: Pin
    segments: list[Pin] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def runtime_scope(self):
        if self.execution is None and self.runtime_identities or self.execution is not None and not self.runtime_identities:
            raise ValueError("execution runtime binding required")
        if len(set(self.runtime_identities)) != len(self.runtime_identities):
            raise ValueError("duplicate runtime identity")
        return self


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def input_identity(item: Item, body_hash: str) -> dict:
    if item.private is not None:
        retained = item.private
        return {"kind": "private-record", "stateDir": retained.state_dir, "privateId": retained.private_id,
                "recordSchema": retained.record_schema, "recordSha256": retained.record.sha256, "bodySha256": body_hash}
    if item.collection is not None:
        return {"kind": "collected-http", "candidateId": item.candidate_id,
                "receiptSha256": item.collection.receipt.sha256, "bodySha256": body_hash}
    raise IngestionFailure("private_processing_input_invalid")


def _observation(row, candidate):
    return {"roundId": row["id"], "page": candidate["page"], "ordinal": candidate["ordinal"],
            "documentId": candidate["document"], "rawVersion": candidate["raw_version"], "documentVersion": candidate["version"]}


class PrivateAuthority(Authority):
    public = False

    def __init__(self, path: Path):
        self.path = Path(path)
        self.raw = read_file(self.path, MAX_INPUT)
        self._files = {str(self.path): self.raw}
        self.receipt = None
        self.segments = []
        try:
            document = _json(self.raw)
            if document.get("schemaVersion") == "zoop-private-execution-1":
                self.receipt = ExecutionReceipt.model_validate(document)
                registry_pin = self.receipt.registry
                for pin in self.receipt.segments:
                    raw = self._pinned(pin, "private_processing_segment_mismatch")
                    segment = Segment.model_validate(_json(raw))
                    if segment.phase != "process":
                        raise IngestionFailure("private_processing_phase_denied")
                    self.segments.append((segment, byte_hash(raw)))
            else:
                segment = Segment.model_validate(document)
                if segment.phase != "import":
                    raise IngestionFailure("private_processing_execution_required")
                registry_pin = segment.registry
                self.segments = [(segment, byte_hash(self.raw))]
            self.registry = Registry.model_validate(_json(self._pinned(registry_pin, "private_processing_registry_mismatch")))
            identifiers, observations = set(), set()
            self._members = {}
            for segment, revision in self.segments:
                if segment.authorization_id in identifiers:
                    raise IngestionFailure("private_processing_member_ambiguous")
                identifiers.add(segment.authorization_id)
                original = Registry.model_validate(_json(self._pinned(segment.registry, "private_processing_registry_mismatch")))
                for member in segment.members:
                    source, scope = self._scope(self.registry, member.source_id, member.scope_id)
                    prior_source, prior_scope = self._scope(original, member.source_id, member.scope_id)
                    if source.configuration(scope) != prior_source.configuration(prior_scope):
                        raise IngestionFailure("scope_configuration_conflict")
                    if source.grant.rights == "denied" or prior_source.grant.rights == "denied":
                        raise IngestionFailure("source_rights_denied")
                    if (source.adapter == "retained-private") != isinstance(member.input, PrivateInput):
                        raise IngestionFailure("private_processing_input_invalid")
                    for pin in member.publisher_rights.evidence:
                        self._pinned(pin, "private_processing_evidence_mismatch")
                    if member.observation is not None:
                        key = canonical([member.source_id, member.observation.wire()])
                        if key in observations:
                            raise IngestionFailure("private_processing_member_ambiguous")
                        observations.add(key)
                        self._members[key] = (member, segment, revision)
            self._current()
        except (ValidationError, ValueError, KeyError, TypeError) as exc:
            raise IngestionFailure("private_processing_invalid") from exc

    def _pinned(self, pin, code):
        raw = read_file(Path(pin.path), MAX_INPUT)
        if byte_hash(raw) != pin.sha256:
            raise IngestionFailure(code)
        previous = self._files.setdefault(pin.path, raw)
        if previous != raw:
            raise IngestionFailure("registry_changed")
        return raw

    def _current(self):
        if any(read_file(Path(path), MAX_INPUT) != raw for path, raw in self._files.items()):
            raise IngestionFailure("registry_changed")

    @staticmethod
    def _scope(registry, source_id, scope_id):
        source = next((s for s in registry.sources if s.source_id == source_id), None)
        scope = next((s for s in source.scopes if s.scope_id == scope_id), None) if source else None
        if source is None or scope is None:
            raise IngestionFailure("source_unauthorized")
        return source, scope

    def check(self, source_id, scope_id, operations=("read", "store"), config=None, *, purpose=None, recipient=None):
        self._current()
        if (purpose is None) != (recipient is None):
            raise ValueError("purpose and recipient are checked together")
        source, scope = self._scope(self.registry, source_id, scope_id)
        if source.grant.rights == "denied":
            raise IngestionFailure("source_rights_denied")
        if source.adapter == "collected-http" and not source.grant.enabled:
            raise IngestionFailure("source_unauthorized")
        if config is not None and source.configuration(scope) != config:
            raise IngestionFailure("scope_configuration_conflict")
        members = [(m, s) for s, _ in self.segments for m in s.members if (m.source_id, m.scope_id) == (source_id, scope_id)]
        if not members:
            raise IngestionFailure("private_processing_member_unknown")
        permitted = {"read", "quote-display"} if self.receipt is not None else {"read", "store"}
        if not set(operations) <= permitted or purpose is not None and self.receipt is None:
            raise IngestionFailure("private_processing_phase_denied")
        if purpose is not None:
            if source_id.lower().replace("_", "-") in NAVER_SEARCH:
                raise IngestionFailure("naver_search_ai_prohibited")
            execution = self.receipt.execution
            if execution is None or os.environ.get("ZOOP_AI_PIPELINE_LIVE_SET_ID") != execution.set_id:
                raise IngestionFailure("private_processing_set_mismatch")
            if not any((purpose, recipient) in {(s.purpose, s.recipient) for s in segment.sends} for _, segment in members):
                raise IngestionFailure("source_purpose_or_recipient_denied")
        return source, scope

    def _acquisition(self, member, item):
        """Recheck the original files for this exact admitted member, never revive its old send window."""
        if member.acquisition is None:
            return
        pin = member.acquisition.registry
        try:
            raw = read_file(Path(pin.path), MAX_INPUT)
            if byte_hash(raw) != pin.sha256:
                raise IngestionFailure("private_processing_acquisition_changed")
            original = Registry.model_validate(_json(raw))
            source, scope = self._scope(original, member.source_id, member.scope_id)
            if source.adapter != "collected-http":
                raise IngestionFailure("private_processing_input_invalid")
            if source.grant.rights == "denied":
                raise IngestionFailure("source_rights_denied")
            if not source.grant.enabled:
                raise IngestionFailure("source_unauthorized")
            current, current_scope = self._scope(self.registry, member.source_id, member.scope_id)
            if source.configuration(scope) != current.configuration(current_scope):
                raise IngestionFailure("scope_configuration_conflict")
            receipt_path = str(Path(source.input_root) / item.collection.receipt.file)
            if not any(proof.path == receipt_path and proof.sha256 == member.input.receipt_sha256
                       for proof in member.acquisition.proofs):
                raise IngestionFailure("private_processing_input_invalid")
            for proof in member.acquisition.proofs:
                if byte_hash(read_file(Path(proof.path), MAX_INPUT)) != proof.sha256:
                    raise IngestionFailure("private_processing_acquisition_changed")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise IngestionFailure("private_processing_acquisition_changed") from exc

    def admit(self, source_id, scope_id, item, body_hash):
        self.check(source_id, scope_id)
        identity = input_identity(item, body_hash)
        member = next((m for segment, _ in self.segments for m in segment.members
                       if m.source_id == source_id and m.scope_id == scope_id and m.input.wire() == identity), None)
        if member is None:
            raise IngestionFailure("private_processing_member_unknown")
        self._acquisition(member, item)

    def _member(self, row, candidate):
        if self.receipt is None:
            raise IngestionFailure("private_processing_phase_denied")
        key = canonical([row["source"], _observation(row, candidate)])
        match = self._members.get(key)
        if match is None:
            raise IngestionFailure("private_processing_member_unknown")
        return match

    def member(self, row, candidate, content, *, purpose=None, recipient=None):
        scope_id = Run.model_validate_json(row["request"]).scope_id
        self.check(row["source"], scope_id, ("read",), json.loads(row["config"]), purpose=purpose, recipient=recipient)
        item = Item.model_validate_json(candidate["data"])
        if self.receipt is None:
            identity = input_identity(item, content["rawHash"])
            member = next((m for segment, _ in self.segments for m in segment.members
                           if m.source_id == row["source"] and m.scope_id == scope_id and m.input.wire() == identity), None)
            if member is None:
                raise IngestionFailure("private_processing_member_unknown")
            self._acquisition(member, item)
            return
        member, segment, _ = self._member(row, candidate)
        if (member.scope_id != scope_id or member.input.wire() != input_identity(item, content["rawHash"])
                or member.text_sha256 != byte_hash(content["text"].encode("utf-8"))):
            raise IngestionFailure("private_processing_member_mismatch")
        self._acquisition(member, item)
        if purpose is not None and (purpose, recipient) not in {(s.purpose, s.recipient) for s in segment.sends}:
            raise IngestionFailure("source_purpose_or_recipient_denied")

    def reference(self, source, row, candidate):
        self._current()
        _, segment, revision = self._member(row, candidate)
        return {"grantId": "private-processing:" + segment.authorization_id, "revision": revision}

    def check_runtime(self, binding):
        self._current()
        if self.receipt is None or binding.get("identity") not in self.receipt.runtime_identities:
            raise IngestionFailure("private_processing_runtime_unbound")


def select_authority(sources: Path | None, private_processing: Path | None):
    if (sources is None) == (private_processing is None):
        raise IngestionFailure("source_authority_selection_invalid")
    return PrivateAuthority(private_processing) if private_processing is not None else Authority(sources)


def runtime_factory(authority):
    """Keep construction lazy; inspect/replay never read runtime configuration or credentials."""
    def build(*, need_send=False):
        from .live_runtime import LiveRuntime
        runtime = LiveRuntime.from_env(need_send=need_send)
        authority.check_runtime(runtime.binding())
        return runtime
    return build
