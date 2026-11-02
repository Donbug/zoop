"""Local handoff routing configuration; the subprocess verifies native bindings and current rights."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from .handoff_access import _duplicate_free, _no_constant

FIELDS = {"contextId", "relationStateDirectory", "extractionStateDirectory", "ingestionStateDirectory", "sources", "sourcePins", "observations"}
PATHS = ("relationStateDirectory", "extractionStateDirectory", "ingestionStateDirectory", "sources")
HASH = re.compile(r"[a-f0-9]{64}")
JOB = re.compile(r"[A-Za-z0-9._:-]{1,200}")


def _load(path: Path, sha256: str):
    if not HASH.fullmatch(sha256):
        raise ValueError("source_contexts_invalid")
    if any(part.is_symlink() for part in (path, *path.parents)) or path.stat().st_mode & 0o022:
        raise ValueError("source_contexts_invalid")
    with path.open("rb") as stream:
        raw = stream.read(2_000_001)
    if len(raw) > 2_000_000 or hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("source_contexts_changed")
    doc = json.loads(raw, object_pairs_hook=_duplicate_free, parse_constant=_no_constant)
    if set(doc) != {"schemaVersion", "contexts"} or doc["schemaVersion"] != "zoop-handoff-source-contexts-1" or not isinstance(doc["contexts"], list) or not doc["contexts"]:
        raise ValueError("source_contexts_invalid")
    ids, pins, jobs, observations, upstreams, routes = set(), set(), {}, {}, {}, []
    for context in doc["contexts"]:
        if set(context) != FIELDS:
            raise ValueError("source_contexts_invalid")
        cid = context["contextId"]
        if not isinstance(cid, str) or not 1 <= len(cid) <= 200 or cid in ids:
            raise ValueError("source_contexts_invalid")
        ids.add(cid)
        paths = tuple(Path(context[key]) for key in PATHS)
        if any(not p.is_absolute() or os.path.normpath(str(p)) != str(p) for p in paths):
            raise ValueError("source_contexts_invalid")
        routes.append(paths)
        if not isinstance(context["sourcePins"], list) or not context["sourcePins"] or not isinstance(context["observations"], list) or not context["observations"]:
            raise ValueError("source_contexts_invalid")
        for pin in context["sourcePins"]:
            if set(pin) != {"relation", "upstream", "reviewDigest"} or not HASH.fullmatch(pin["reviewDigest"]):
                raise ValueError("source_contexts_invalid")
            for name, fields in (("relation", {"jobId", "inputDigest"}), ("upstream", {"jobId", "inputDigest", "digest"})):
                part = pin[name]
                if set(part) != fields or not JOB.fullmatch(part["jobId"]) or any(not HASH.fullmatch(part[key]) for key in fields - {"jobId"}):
                    raise ValueError("source_contexts_invalid")
            key = json.dumps(pin, sort_keys=True, separators=(",", ":"))
            owner = (cid, pin["relation"]["inputDigest"], json.dumps(pin["upstream"], sort_keys=True, separators=(",", ":")))
            if key in pins or (pin["relation"]["jobId"] in jobs and jobs[pin["relation"]["jobId"]] != owner):
                raise ValueError("source_contexts_invalid")
            pins.add(key)
            jobs[pin["relation"]["jobId"]] = owner
            upstream = pin["upstream"]
            owner = (cid, upstream["inputDigest"], upstream["digest"])
            if upstream["jobId"] in upstreams and upstreams[upstream["jobId"]] != owner:
                raise ValueError("source_contexts_invalid")
            upstreams[upstream["jobId"]] = owner
        for ref in context["observations"]:
            if set(ref) != {"roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion"}:
                raise ValueError("source_contexts_invalid")
            if any(not isinstance(ref[k], str) or not 1 <= len(ref[k]) <= 200 for k in ("roundId", "sourceId", "documentId")) \
                    or any(type(ref[k]) is not int or ref[k] < 0 for k in ("page", "ordinal")) \
                    or any(not HASH.fullmatch(ref[k]) for k in ("rawVersion", "documentVersion")):
                raise ValueError("source_contexts_invalid")
            key = tuple(ref[k] for k in sorted(ref))
            if key in observations:
                raise ValueError("source_contexts_invalid")
            observations[key] = paths[2:]
    return tuple(routes), observations


def load(path: Path, sha256: str) -> tuple[tuple[Path, Path, Path, Path], ...]:
    return _load(path, sha256)[0]


def observation_route(path: Path, sha256: str, selector: dict) -> tuple[Path, Path] | None:
    """Resolve only the full selector in freshly verified inventory bytes."""
    return _load(path, sha256)[1].get(tuple(selector[key] for key in sorted(selector)))
