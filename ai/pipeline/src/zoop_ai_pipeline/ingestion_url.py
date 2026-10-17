"""Source URL identity. One canonical form for ingestion, export and the one-off collector.

A URL is an identifier here, never a license: it names where bytes were (or were not) acquired. Only http/https without
credentials, control characters or ambiguous path escapes are accepted. Scheme-default ports are dropped. An explicit
non-default port is accepted only for the loopback names the synthetic local test servers use; every collector fetch is
additionally gated by its own policy (see collection.py), so naming a loopback URL here grants nothing.
"""
from __future__ import annotations

import re
from urllib.parse import unquote_to_bytes, urlsplit, urlunsplit

import httpx

from .ingestion_contracts import IngestionFailure

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1"})
_BAD_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def _reject_ambiguous_path(path: str) -> None:
    for segment in path.split("/"):
        if "%" not in segment:
            continue
        if _BAD_ESCAPE.search(segment):
            raise ValueError("malformed percent escape")
        decoded = unquote_to_bytes(segment)
        if decoded in {b".", b".."} or any(byte in decoded for byte in (b"/", b"\\", b"%")):
            raise ValueError("ambiguous encoded path")


def canonical_url(value: str) -> tuple[str, str]:
    """Return (normalized URL, lowercase IDNA host) or raise IngestionFailure('source_url_invalid')."""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None
                or any(ord(c) < 33 or ord(c) == 127 for c in value) or "\\" in value):
            raise ValueError("unsupported URL")
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        port = parsed.port
        authority = f"[{host}]" if ":" in host else host
        if port not in (None, 443 if parsed.scheme == "https" else 80):
            if host not in LOOPBACK_HOSTS:
                raise ValueError("non-default port")
            authority = f"{authority}:{port}"
        _reject_ambiguous_path(parsed.path)
        return str(httpx.URL(urlunsplit((parsed.scheme, authority, parsed.path or "/", parsed.query, "")))), host
    except (httpx.InvalidURL, ValueError, UnicodeError) as exc:
        raise IngestionFailure("source_url_invalid") from exc
