"""Current-authority reader for the operator-owned grant registry.

This is the service's own read of the same registry file the runtime registers with `--grants`. It is a consumer-side guard
that mirrors the strict `SourceGrant` shape and the runtime/BFF authorization rule, so that content is never delivered from a
stale execution snapshot. It never writes the registry and never trusts the grant echoed by a runtime `get`.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "zoop-ai-s1-1"
MAX_REGISTRY_BYTES = 1_000_000
KINDS = frozenset({"document-summary", "document-sentiment", "semantic-verification", "briefing-outlook"})
OPERATIONS = frozenset({"read", "store", "model-send", "quote-display"})
RIGHTS = frozenset({"known", "unknown", "denied"})
REQUIRED_OPERATIONS = OPERATIONS
FIELDS = frozenset({"grantId", "revision", "sourceId", "enabled", "rights", "allowedOperations",
                    "recipients", "purposes", "evidence", "expiresAt"})
NAVER_SEARCH = frozenset({"naver-search", "naver-developers-search"})


class GrantRegistryError(Exception):
    """Carries a stable code only; never registry content or a path."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Registry:
    digest: str
    grants: dict[str, dict[str, Any]]

    def current(self, grant_id: str) -> dict[str, Any] | None:
        return self.grants.get(grant_id)


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _expiry(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def _valid(grant: Any) -> bool:
    return (isinstance(grant, dict) and set(grant) == FIELDS
            and all(isinstance(grant[k], str) and grant[k] for k in ("grantId", "revision", "sourceId"))
            and isinstance(grant["enabled"], bool) and isinstance(grant["rights"], str) and grant["rights"] in RIGHTS
            and _strings(grant["allowedOperations"]) and set(grant["allowedOperations"]) <= OPERATIONS
            and _strings(grant["recipients"]) and _strings(grant["purposes"]) and set(grant["purposes"]) <= KINDS
            and _strings(grant["evidence"]) and _expiry(grant["expiresAt"]))


def parse(data: bytes) -> Registry:
    if len(data) > MAX_REGISTRY_BYTES:
        raise GrantRegistryError("grant_registry_too_large")
    try:
        registry = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise GrantRegistryError("grant_registry_unreadable") from None
    if not isinstance(registry, dict) or registry.get("schemaVersion") != SCHEMA or not isinstance(registry.get("grants"), list):
        raise GrantRegistryError("grant_registry_schema_invalid")
    current: dict[str, dict[str, Any]] = {}
    history: dict[tuple[str, str], dict[str, Any]] = {}
    for grant in registry["grants"]:
        if not _valid(grant):
            raise GrantRegistryError("grant_registry_schema_invalid")
        key = (grant["grantId"], grant["revision"])
        # The runtime refuses a changed payload under an already registered revision; the registry file itself must not contain one.
        if key in history and history[key] != grant:
            raise GrantRegistryError("grant_revision_conflict")
        history[key] = grant
        current[grant["grantId"]] = grant
    return Registry(hashlib.sha256(data).hexdigest(), current)


def load(path: Path) -> Registry:
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_REGISTRY_BYTES + 1)
    except OSError:
        raise GrantRegistryError("grant_registry_unreadable") from None
    return parse(data)


def evaluate(grant: dict[str, Any] | None, *, source_id: str, revision: str, purposes: list[str],
             recipients: list[str], now: datetime | None = None) -> str | None:
    """Return a stable denial code, or None when current authority covers delivery. Same order as the runtime and BFF rule."""
    if grant is None or grant["rights"] != "known" or not grant["enabled"] or not grant["evidence"]:
        return "source_rights_unknown_or_denied"
    if grant["revision"] != revision or grant["sourceId"] != source_id:
        return "grant_revision_or_source_changed"
    if grant["sourceId"].lower().replace("_", "-") in NAVER_SEARCH:
        return "naver_search_ai_prohibited"
    if grant["expiresAt"] and datetime.fromisoformat(grant["expiresAt"]) <= (now or datetime.now(UTC)):
        return "source_grant_expired"
    if not REQUIRED_OPERATIONS <= set(grant["allowedOperations"]):
        return "source_operation_denied"
    # An empty recipient list is never an authorization: some recipient must be named and every one must be granted.
    if (not recipients or any(purpose not in grant["purposes"] for purpose in purposes)
            or any(r not in grant["recipients"] for r in recipients)):
        return "source_purpose_or_recipient_denied"
    return None
