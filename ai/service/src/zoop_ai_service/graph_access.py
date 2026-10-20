"""Server-owned map of which principal may read which graph version, pinned to the exact content the operator reviewed.

The graph ledger and the versions in it are written by an operator process this service never controls, and a version id is only a label.
A caller naming one proves nothing, so the operator lists, per principal, the exact `{versionId, graphDigest, payloadDigest}` (and, when wanted,
the S3 relation job the version was frozen from). A version that is not listed is refused before any ledger or child process is touched, with
one answer for "unknown" and "exists but not yours". The same entry is read again before content would be delivered, and the digests the
pipeline reports for the stored version must equal the listed ones.
The file is re-read for every use, so removing or changing an entry takes effect on the next request; a file that cannot be read fails closed.

Not pinned, because the installed pipeline does not report it on `read`/`focus`: the Neo4j store id. The binding of a version to the one bound
store is verified inside the pipeline (store marker, database id, owner) and any mismatch is withheld there.
"""
from __future__ import annotations

import json
import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = "zoop-ai-graph-versions-1"
MAX_BYTES = 1_000_000
VERSION_ID = re.compile(r"[A-Za-z0-9._:-]{1,120}")
JOB_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}")
DIGEST = re.compile(r"[0-9a-f]{64}")
ENTRY_KEYS = frozenset({"principal", "versionId", "graphDigest", "payloadDigest"})


class AccessError(Exception):
    """A stable reason code only; never a path, a version id or file content."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Entry:
    principal: str
    version_id: str
    graph_digest: str
    payload_digest: str
    source_job_id: str | None = None        # optional pin: the S3 relation job this version was frozen from
    source_input_digest: str | None = None


@dataclass(frozen=True)
class Access:
    entries: dict[tuple[str, str], Entry]

    def find(self, principal: str, version_id: str) -> Entry | None:
        return self.entries.get((principal, version_id))


def _duplicate_free(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _no_constant(_: str) -> Any:
    raise ValueError("non-finite number")


def _entry(raw: Any, principals: Collection[str]) -> Entry:
    if not isinstance(raw, dict) or not ENTRY_KEYS <= set(raw) or not set(raw) <= ENTRY_KEYS | {"sourceRelation"}:
        raise AccessError("version_allowlist_entry_shape")
    principal, version_id, graph, payload = raw["principal"], raw["versionId"], raw["graphDigest"], raw["payloadDigest"]
    if not (isinstance(principal, str) and isinstance(version_id, str) and isinstance(graph, str) and isinstance(payload, str)
            and VERSION_ID.fullmatch(version_id) and DIGEST.fullmatch(graph) and DIGEST.fullmatch(payload)):
        raise AccessError("version_allowlist_entry_invalid")
    if principal not in principals:
        raise AccessError("version_allowlist_unknown_principal")
    pin = raw.get("sourceRelation")
    if "sourceRelation" not in raw:
        return Entry(principal, version_id, graph, payload)
    if not isinstance(pin, dict) or set(pin) != {"jobId", "inputDigest"} or not isinstance(pin["jobId"], str) \
            or not isinstance(pin["inputDigest"], str) or not JOB_ID.fullmatch(pin["jobId"]) or not DIGEST.fullmatch(pin["inputDigest"]):
        raise AccessError("version_allowlist_entry_invalid")
    return Entry(principal, version_id, graph, payload, pin["jobId"], pin["inputDigest"])


def load(path: Path, principals: Collection[str]) -> Access:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
    except OSError:
        raise AccessError("version_allowlist_unreadable") from None
    if len(raw) > MAX_BYTES:
        raise AccessError("version_allowlist_too_large")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_free, parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise AccessError("version_allowlist_not_json") from None
    if not isinstance(document, dict) or set(document) != {"schemaVersion", "versions"} or document["schemaVersion"] != SCHEMA \
            or not isinstance(document["versions"], list):
        raise AccessError("version_allowlist_shape")
    entries: dict[tuple[str, str], Entry] = {}
    for item in document["versions"]:
        entry = _entry(item, principals)
        key = (entry.principal, entry.version_id)
        if key in entries:
            raise AccessError("version_allowlist_duplicate")
        entries[key] = entry
    return Access(entries)
