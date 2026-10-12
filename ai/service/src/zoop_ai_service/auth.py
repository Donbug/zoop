"""Operator-issued bearer tokens, matched by SHA-256 digest only.

The service holds digests, never tokens, never generates a secret, and compares the presented digest against every configured
digest without stopping early, so response timing does not reveal which principal (or how many) matched.
"""
from __future__ import annotations

import hashlib
import hmac
import re

from .config import Principal

HEADER = re.compile(r"Bearer ([A-Za-z0-9._~+/-]{32,512}=*)", re.ASCII)


def authenticate(principals: tuple[Principal, ...], header: str | None) -> Principal | None:
    """The principal whose configured digest matches the presented bearer token, else None (missing, malformed or unknown alike)."""
    match = HEADER.fullmatch(header or "")
    candidate = hashlib.sha256((match.group(1) if match else "").encode("ascii")).hexdigest()
    found: Principal | None = None
    for principal in principals:
        for digest in principal.digests:
            if hmac.compare_digest(candidate, digest) and match:
                found = principal
    return found
