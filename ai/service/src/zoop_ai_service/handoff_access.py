"""Server-owned map of which principal may read which AI handoff bundle, pinned to the exact bytes the operator reviewed.

A handoff is a versioned, immutable AI-side artifact (`zoop-ai-handoff`), and a handoff id is only a label. A caller naming one proves nothing, so the
operator lists, per principal, the exact `{handoffId, manifestDigest, bundleDigest}`: the SHA-256 of the manifest the handoff was frozen from and the SHA-256
of the canonical bundle bytes. Both pins are required: a listing without a digest could adopt whatever bundle the ledger holds under that id. A handoff
that is not listed is refused before any ledger or child process is touched, with one answer for "unknown", "exists but not yours" and "listed for
another principal". The same entry is read again before anything of the answer is used, and the digests the producer reports and the digests of the
bytes this service received must equal the listed ones.
The file is re-read for every use, so removing or changing an entry takes effect on the next request; a file that cannot be read fails closed.
"""
from __future__ import annotations

import json
import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = "zoop-ai-handoff-exports-1"
MAX_BYTES = 1_000_000
HANDOFF_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}")
DIGEST = re.compile(r"[0-9a-f]{64}")
ENTRY_KEYS = frozenset({"principal", "handoffId", "manifestDigest", "bundleDigest"})


class AccessError(Exception):
    """A stable reason code only; never a path, a handoff id or file content."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Entry:
    principal: str
    handoff_id: str
    manifest_digest: str
    bundle_digest: str


@dataclass(frozen=True)
class Access:
    entries: dict[tuple[str, str], Entry]

    def find(self, principal: str, handoff_id: str) -> Entry | None:
        return self.entries.get((principal, handoff_id))


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
    if not isinstance(raw, dict) or set(raw) != ENTRY_KEYS:
        raise AccessError("handoff_allowlist_entry_shape")
    principal, handoff_id, manifest, bundle = raw["principal"], raw["handoffId"], raw["manifestDigest"], raw["bundleDigest"]
    if not (isinstance(principal, str) and isinstance(handoff_id, str) and isinstance(manifest, str) and isinstance(bundle, str)
            and HANDOFF_ID.fullmatch(handoff_id) and DIGEST.fullmatch(manifest) and DIGEST.fullmatch(bundle)):
        raise AccessError("handoff_allowlist_entry_invalid")
    if principal not in principals:
        raise AccessError("handoff_allowlist_unknown_principal")
    return Entry(principal, handoff_id, manifest, bundle)


def load(path: Path, principals: Collection[str]) -> Access:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
    except OSError:
        raise AccessError("handoff_allowlist_unreadable") from None
    if len(raw) > MAX_BYTES:
        raise AccessError("handoff_allowlist_too_large")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_free, parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise AccessError("handoff_allowlist_not_json") from None
    if not isinstance(document, dict) or set(document) != {"schemaVersion", "handoffs"} or document["schemaVersion"] != SCHEMA \
            or not isinstance(document["handoffs"], list):
        raise AccessError("handoff_allowlist_shape")
    entries: dict[tuple[str, str], Entry] = {}
    for item in document["handoffs"]:
        entry = _entry(item, principals)
        key = (entry.principal, entry.handoff_id)
        if key in entries:
            raise AccessError("handoff_allowlist_duplicate")
        entries[key] = entry
    return Access(entries)
