"""Server-owned map of which principal may build an S3 relation job on which operator-prepared S2 extraction job.

The S2 job and its ingestion are written by an operator process this service never controls, so a caller naming an upstream
`{jobId, inputDigest}` proves nothing. The operator lists the exact pairs per principal; a pair that is not listed is refused
before the service touches a ledger or a child process, and the same list is checked again when a result would be delivered.
The file is re-read for every use, so removing an entry takes effect on the next request; a file that cannot be read fails closed.
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
    entries: frozenset[tuple[str, str, str]]

    def allows(self, principal: str, job_id: str, input_digest: str) -> bool:
        return (principal, job_id, input_digest) in self.entries


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
    entries: set[tuple[str, str, str]] = set()
    for entry in document["upstreams"]:
        if not isinstance(entry, dict) or set(entry) != {"principal", "jobId", "inputDigest"}:
            raise AccessError("upstream_allowlist_entry_shape")
        principal, job_id, digest = entry["principal"], entry["jobId"], entry["inputDigest"]
        if not (isinstance(principal, str) and isinstance(job_id, str) and isinstance(digest, str)
                and UPSTREAM_ID.fullmatch(job_id) and DIGEST.fullmatch(digest)):
            raise AccessError("upstream_allowlist_entry_invalid")
        if principal not in principals:
            raise AccessError("upstream_allowlist_unknown_principal")
        key = (principal, job_id, digest)
        if key in entries:
            raise AccessError("upstream_allowlist_duplicate")
        entries.add(key)
    return Access(frozenset(entries))


def refusal(path: Path, principals: Collection[str], owner: str, job_id: str, input_digest: str) -> str | None:
    """None when the owner may still use the upstream, otherwise a stable code. The file is read fresh; one that cannot be read refuses."""
    try:
        access = load(path, principals)
    except AccessError:
        return "service_configuration_invalid"
    return None if access.allows(owner, job_id, input_digest) else "upstream_not_allowed"
