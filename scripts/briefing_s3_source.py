"""Source identity and immutable files shared by offline preparation and live review.

Standard library only: importing these helpers never loads provider libraries or keys.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def native_version(value):
    """Lossless public version wrapper -> the native pipeline's SHA-256 identity."""
    raw = value.removeprefix('sha256-')
    if len(raw) != 64 or any(c not in '0123456789abcdef' for c in raw):
        raise RuntimeError('document_version_not_sha256')
    return raw


def once(path, value):
    raw = value if isinstance(value, bytes) else canonical(value)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise RuntimeError('immutable_result_conflict')
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
