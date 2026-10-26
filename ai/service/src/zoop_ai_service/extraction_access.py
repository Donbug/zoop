"""Server-owned preapproval of exact S2 `Submit` requests, and the one authority object every content-bearing S2 use consults.

A caller of the S2 door sends only `{schemaVersion, jobId, approvedRequestDigest}`. The operator lists, per principal and job id, the exact S2
`Submit` body (snapshot, catalogue, incoming observation and topic request) the service may send to the pipeline, the SHA-256 digest of its
canonical JSON, and EITHER the digests of the authored replay fixtures that body is to run against (a replay request) OR the identity of the live
runtime binding it may spend money under (`liveRuntimeIdentity`, a live request: `executionMode: live`, `recordingKind: provider`, no fixture).
A caller therefore chooses among requests the operator already approved; it can never supply a snapshot, a catalogue, an observation reference,
a path or a fixture, and it can never turn a replay approval into a live one. The approval only NARROWS what the pipeline would allow anyway:
the pipeline still re-reads the operator source registry on every content-bearing command (and, for a live request, the model-send rights of
every document it transmits), so an approval never grants a read or a send the registry does not.

The file is re-read for every use, so removing or changing an entry takes effect on the next request or dispatch; a file that cannot be read
fails closed. Fixture digests are pinned in the approval and checked against the fixture files on every use (the files are server
configuration and are never named by a caller).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .relation_access import AccessError, _duplicate_free, _no_constant

SCHEMA = "zoop-ai-extraction-approvals-1"
RUNTIME_SCHEMA = "zoop-extraction-s2-2"
MAX_BYTES = 16_000_000
MAX_REPLAY = 20_000_000  # the pipeline's own fixture size limit
JOB_ID = re.compile(r"[A-Za-z0-9_.-]{1,120}")
DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Approval:
    principal: str
    job_id: str
    approved_digest: str            # digest of the canonical request JSON: what the caller must name
    request: dict[str, Any]         # the exact S2 Submit wire body the service sends to the pipeline
    producer_digest: str | None     # sha256 of the producer replay fixture bytes; None for a live request (no fixture exists)
    topic_digest: str | None        # sha256 of the topic fixture bytes; present exactly when a REPLAY request asks for a topic stage
    live_identity: str | None = None  # the live runtime binding identity this request may run under; None for a replay request

    @property
    def live(self) -> bool:
        return self.live_identity is not None

    @property
    def input_digest(self) -> str:
        """The pipeline's `inputDigest`: `digest({"request": wire, "replayFixtureHash": sha256(replay bytes)})` for a replay request,
        `digest({"request": wire, "liveBindingDigest": identity})` for a live one."""
        if self.live_identity is not None:
            return request_digest({"request": self.request, "liveBindingDigest": self.live_identity})
        return request_digest({"request": self.request, "replayFixtureHash": self.producer_digest})

    @property
    def pins(self) -> tuple[str, str | None, str | None, str | None]:
        return (self.approved_digest, self.producer_digest, self.topic_digest, self.live_identity)


@dataclass(frozen=True)
class Approvals:
    entries: dict[tuple[str, str], Approval]

    def find(self, principal: str, job_id: str) -> Approval | None:
        return self.entries.get((principal, job_id))


def request_digest(body: Any) -> str:
    """The pipeline's canonical digest (`ingestion_contracts.digest`); the same rule as `jobs.request_digest`, kept here because `config` imports
    this module and `jobs` imports `config`."""
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load(path: Path, principals: Collection[str], *, topic_available: bool, live_available: bool = False) -> Approvals:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
    except OSError:
        raise AccessError("extraction_approvals_unreadable") from None
    return parse(raw, principals, topic_available=topic_available, live_available=live_available)


def parse(raw: bytes, principals: Collection[str], *, topic_available: bool, live_available: bool = False) -> Approvals:
    """Validate bounded registry bytes without opening or creating a file."""
    if len(raw) > MAX_BYTES:
        raise AccessError("extraction_approvals_too_large")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_free, parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise AccessError("extraction_approvals_not_json") from None
    if not isinstance(document, dict) or set(document) != {"schemaVersion", "approvals"} or document["schemaVersion"] != SCHEMA \
            or not isinstance(document["approvals"], list):
        raise AccessError("extraction_approvals_shape")
    entries: dict[tuple[str, str], Approval] = {}
    required = {"principal", "jobId", "approvedRequestDigest", "request", "producerReplayDigest", "topicReplayDigest"}
    for entry in document["approvals"]:
        if not isinstance(entry, dict) or not required <= set(entry) <= {*required, "liveRuntimeIdentity"}:
            raise AccessError("extraction_approval_entry_shape")
        principal, job_id, approved, request = entry["principal"], entry["jobId"], entry["approvedRequestDigest"], entry["request"]
        producer, topic, live = entry["producerReplayDigest"], entry["topicReplayDigest"], entry.get("liveRuntimeIdentity")
        if not (isinstance(principal, str) and isinstance(job_id, str) and JOB_ID.fullmatch(job_id) and isinstance(approved, str)
                and DIGEST.fullmatch(approved) and (producer is None or (isinstance(producer, str) and DIGEST.fullmatch(producer)))
                and (topic is None or (isinstance(topic, str) and DIGEST.fullmatch(topic)))
                and (live is None or (isinstance(live, str) and DIGEST.fullmatch(live)))):
            raise AccessError("extraction_approval_entry_invalid")
        if principal not in principals:
            raise AccessError("extraction_approval_unknown_principal")
        provenance = request.get("provenance") if isinstance(request, dict) else None
        if not isinstance(request, dict) or request.get("schemaVersion") != RUNTIME_SCHEMA or request.get("jobId") != job_id \
                or not isinstance(provenance, dict) or "topic" not in request:
            raise AccessError("extraction_approval_request_invalid")
        modes = (provenance.get("executionMode"), provenance.get("recordingKind"))
        if request_digest(request) != approved:
            raise AccessError("extraction_approval_digest_mismatch")
        if modes == ("live", "provider"):
            # A live approval pins the runtime identity and carries no fixture at all (the pipeline refuses one for a live job).
            if live is None or producer is not None or topic is not None:
                raise AccessError("extraction_approval_live_pin_mismatch")
            if not live_available:
                raise AccessError("extraction_approval_live_unconfigured")
        elif modes == ("replay", "authored-test"):
            if live is not None or producer is None:
                raise AccessError("extraction_approval_request_invalid")
            if (request["topic"] is None) != (topic is None):
                raise AccessError("extraction_approval_topic_pin_mismatch")
            if topic is not None and not topic_available:
                raise AccessError("extraction_approval_topic_replay_unconfigured")
        else:
            raise AccessError("extraction_approval_request_invalid")
        key = (principal, job_id)
        if key in entries:
            raise AccessError("extraction_approval_duplicate")
        entries[key] = Approval(principal, job_id, approved, request, producer, topic, live)
    return Approvals(entries)


def file_digest(path: Path) -> str | None:
    """SHA-256 of a fixture file's current bytes, or None when it cannot be read within the pipeline's own size limit."""
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_REPLAY + 1)
    except OSError:
        return None
    return None if len(raw) > MAX_REPLAY else hashlib.sha256(raw).hexdigest()


class Authority:
    """Everything that decides whether the service may still put an approved request to use, re-read on every call. Stable codes only."""

    def __init__(self, approvals_path: Path, principals: Collection[str], producer_replay: Path, topic_replay: Path | None, live_available: bool = False):
        self._approvals, self._names = approvals_path, list(principals)
        self._producer, self._topic = producer_replay, topic_replay
        self._live_available = live_available

    def approvals(self) -> Approvals:
        return load(self._approvals, self._names, topic_available=self._topic is not None, live_available=self._live_available)

    def fixtures(self, producer_digest: str | None, topic_digest: str | None) -> str | None:
        """None when the fixture files on disk are exactly the pinned bytes now (a live request has none to check). The child reads them again
        afterwards, so this is a check, not a hand-over: see the module note on the residual window and the post-hoc checks on the input digest
        and every receipt."""
        if producer_digest is None:
            return None
        found = file_digest(self._producer)
        if found is None:
            return "fixture_unavailable"
        if found != producer_digest:
            return "fixture_changed"
        if topic_digest is not None:
            if self._topic is None:
                return "fixture_unavailable"
            found = file_digest(self._topic)
            if found is None:
                return "fixture_unavailable"
            if found != topic_digest:
                return "fixture_changed"
        return None

    def refusal(self, owner: str, job_id: str, pins: tuple[str, str | None, str | None, str | None]) -> str | None:
        """None when the owner's approval for this job is still exactly the one the job was reserved under AND the fixtures are still the pinned
        bytes. `approval_revoked`: no entry any more (or another digest); `approval_changed`: the entry's pins moved (a live approval's runtime
        identity included); fixture codes as above; `service_configuration_invalid`: the approvals file cannot be read."""
        try:
            approval = self.approvals().find(owner, job_id)
        except AccessError:
            return "service_configuration_invalid"
        if approval is None or approval.approved_digest != pins[0]:
            return "approval_revoked"
        if approval.pins != pins:
            return "approval_changed"
        return self.fixtures(pins[1], pins[2])
