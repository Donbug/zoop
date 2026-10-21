"""Server-owned map of which principal may build an S3 relation job on which operator-prepared S2 extraction job.

The S2 job and its ingestion are written by an operator process this service never controls, so a caller naming an upstream
`{jobId, inputDigest}` proves nothing. The operator lists the exact pairs per principal; a pair that is not listed is refused
before the service touches a ledger or a child process, and the same list is checked again when a result would be delivered.
The file is re-read for every use, so removing an entry takes effect on the next request; a file that cannot be read fails closed.

A pair may carry one optional `liveRuntimeIdentity` (the sha256 identity of the pipeline's frozen live runtime binding, as printed by
`python -m zoop_ai_pipeline.live_runtime binding`). Only such a pair may run a LIVE relation job, and only under exactly that runtime identity:
the pin is what the operator approved to spend money on, and it is re-read before every live child. A pair without it is replay-only.
"""
from __future__ import annotations

import json
import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = "zoop-ai-relation-upstreams-1"
MAX_BYTES = 1_000_000
UPSTREAM_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}")
DIGEST = re.compile(r"[0-9a-f]{64}")


class AccessError(Exception):
    """A stable reason code only; never a path, a job id or file content."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Access:
    entries: dict[tuple[str, str, str], str | None]

    def allows(self, principal: str, job_id: str, input_digest: str) -> bool:
        return (principal, job_id, input_digest) in self.entries

    def live_identity(self, principal: str, job_id: str, input_digest: str) -> str | None:
        """The runtime identity the operator approved for a live job on this upstream, or None (replay only / not listed)."""
        return self.entries.get((principal, job_id, input_digest))


def _duplicate_free(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _no_constant(_: str) -> Any:
    raise ValueError("non-finite number")


def load(path: Path, principals: Collection[str]) -> Access:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
    except OSError:
        raise AccessError("upstream_allowlist_unreadable") from None
    if len(raw) > MAX_BYTES:
        raise AccessError("upstream_allowlist_too_large")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_free, parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise AccessError("upstream_allowlist_not_json") from None
    if not isinstance(document, dict) or set(document) != {"schemaVersion", "upstreams"} or document["schemaVersion"] != SCHEMA \
            or not isinstance(document["upstreams"], list):
        raise AccessError("upstream_allowlist_shape")
    entries: dict[tuple[str, str, str], str | None] = {}
    for entry in document["upstreams"]:
        if not isinstance(entry, dict) or not {"principal", "jobId", "inputDigest"} <= set(entry) <= {"principal", "jobId", "inputDigest", "liveRuntimeIdentity"}:
            raise AccessError("upstream_allowlist_entry_shape")
        principal, job_id, digest, identity = entry["principal"], entry["jobId"], entry["inputDigest"], entry.get("liveRuntimeIdentity")
        if not (isinstance(principal, str) and isinstance(job_id, str) and isinstance(digest, str)
                and UPSTREAM_ID.fullmatch(job_id) and DIGEST.fullmatch(digest)
                and (identity is None or (isinstance(identity, str) and DIGEST.fullmatch(identity)))):
            raise AccessError("upstream_allowlist_entry_invalid")
        if principal not in principals:
            raise AccessError("upstream_allowlist_unknown_principal")
        key = (principal, job_id, digest)
        if key in entries:
            raise AccessError("upstream_allowlist_duplicate")
        entries[key] = identity
    return Access(entries)


def refusal(path: Path, principals: Collection[str], owner: str, job_id: str, input_digest: str, live_identity: str | None = None) -> str | None:
    """None when the owner may still use the upstream, otherwise a stable code. The file is read fresh; one that cannot be read refuses. With
    `live_identity` the entry must also still pin exactly that runtime identity (`live_not_approved` otherwise)."""
    try:
        access = load(path, principals)
    except AccessError:
        return "service_configuration_invalid"
    if not access.allows(owner, job_id, input_digest):
        return "upstream_not_allowed"
    if live_identity is not None and access.live_identity(owner, job_id, input_digest) != live_identity:
        return "live_not_approved"
    return None
