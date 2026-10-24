"""Round -> operator service plan: the offline, self-contained counterpart of `enqueue-round` for the HTTP S2/S3 doors.

`plan-round` reads a COMPLETE ingestion round through the ordinary enqueue planner and writes ONE immutable plan directory, and nothing else: no
extraction ledger is opened, no job is frozen, no provider, replay or network call is made, and no installed service file is touched. The operator
reviews the directory and installs its two registry files by hand; deploying them and approving a model budget are separate decisions this plan
never makes. The directory holds

  * `approvals.json`           `zoop-ai-extraction-approvals-1` (what `zoop_ai_service.extraction_access.load` reads): one entry per planned unit,
  * `relation-upstreams.json`  `zoop-ai-relation-upstreams-1` (what `relation_access.load` reads): the same `{jobId, inputDigest}` pairs,
  * `manifest.json`            the app-side import: `planId`, `planDigest` and per-unit S2 submit bodies, no request body, secret or source text,
  * `receipt.json`             the digest of every other file, written last.

Job ids live in their own namespace (`s2p-`, derived from the plan id and the exact observation), never `s2r-` of `enqueue-round`: the service
never adopts a job an operator CLI created, so a plan unit can never collide with one. Everything is a pure function of the round, the descriptor,
the pins (replay fixture hashes or the live runtime identity) and the principal: no clock, no randomness. Rerunning identical input leaves an
identical directory untouched; any other input for an existing output path is refused."""
from __future__ import annotations

import ctypes
import errno
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path

from . import extraction_replay as analysis
from .extraction import Fixtures, LiveAccess
from .extraction_contracts import EnqueueRound, ExtractionFailure, Submit, canonical, digest
from .extraction_enqueue import _read_round, plan
from .ingestion_contracts import Authority, IngestionFailure, byte_hash

PLAN_SCHEMA = "zoop-extraction-service-plan-1"
RECEIPT_SCHEMA = "zoop-extraction-service-plan-receipt-1"
PLAN_FORMAT = "zoop-extraction-service-plan-id-1"
JOB_FORMAT = "zoop-extraction-service-job-1"
APPROVALS_SCHEMA = "zoop-ai-extraction-approvals-1"      # ai/service extraction_access.SCHEMA
UPSTREAMS_SCHEMA = "zoop-ai-relation-upstreams-1"        # ai/service relation_access.SCHEMA
# The service re-reads and bounds these files on every use (extraction_access.MAX_BYTES, relation_access.MAX_BYTES); a larger plan could never be installed.
MAX_APPROVALS = 16_000_000
MAX_UPSTREAMS = 1_000_000
MAX_MANIFEST = 8_000_000
PRINCIPAL = re.compile(r"[A-Za-z0-9._:@-]{1,120}")


def _line(value: dict) -> bytes:
    return (canonical(value) + "\n").encode("utf-8")


def _bounded(parts: list[dict], overhead: int, maximum: int, code: str) -> None:
    """Fail before any output when the serialized file (as a JSON array of `parts` plus `overhead` envelope bytes) could not be loaded by the service."""
    size = overhead + max(len(parts) - 1, 0) + sum(len(canonical(part).encode("utf-8")) for part in parts)
    if size > maximum:
        raise ExtractionFailure(code)


def _output(path: Path) -> Path:
    """The explicit output directory: an existing, non-symlink parent directory; the final component is never followed."""
    absolute = Path(os.path.abspath(path))
    if absolute.parent == absolute or absolute.parent.is_symlink() or not absolute.parent.is_dir() or absolute.is_symlink():
        raise ExtractionFailure("plan_output_invalid")
    return absolute


def build(request: EnqueueRound, entries: list, head: dict, fixtures: Fixtures, principal: str, live_identity: str | None) -> dict[str, bytes]:
    """Pure: the bytes of every file of the plan directory. Raises before returning anything when a bound or a rule is violated."""
    planned = [entry for entry in entries if entry.skip is None]
    if not planned:
        raise ExtractionFailure("plan_has_no_units")
    live = live_identity is not None
    topic_digest = byte_hash(fixtures.topic_raw) if fixtures.topic_raw is not None else None
    pins = {"producerReplayDigest": fixtures.replay_hash, "topicReplayDigest": topic_digest, "liveRuntimeIdentity": live_identity}
    round_identity = {"roundId": request.round_id, "sourceId": request.source_id, "ingestionInputDigest": head["inputDigest"]}
    plan_id = "s2plan-" + digest({
        "format": PLAN_FORMAT, "principal": principal, "enqueueId": request.enqueue_id, "round": round_identity, "provenance": request.provenance.wire(),
        "promptVersion": request.prompt_version, "catalogue": request.catalogue.wire(), "snapshot": request.snapshot.wire(),
        "topic": request.topic.wire() if request.topic else None, "pins": pins,
        "observations": [entry.ref.wire() for entry in planned]})
    approvals, upstreams, units = [], [], []
    approvals_size, translated = 0, {}  # translated: the enqueue-namespace id the planner derived -> this plan's unit id
    for entry in planned:
        job_id = "s2p-" + digest({"format": JOB_FORMAT, "planId": plan_id, "observation": entry.ref.wire()})
        translated[entry.submit.job_id] = job_id
        wire = Submit.model_validate({**entry.submit.wire(), "jobId": job_id}).wire()
        approved = digest(wire)
        input_digest = digest({"request": wire, "liveBindingDigest": live_identity} if live else {"request": wire, "replayFixtureHash": fixtures.replay_hash})
        approval = {"principal": principal, "jobId": job_id, "approvedRequestDigest": approved, "request": wire,
                    "producerReplayDigest": None if live else fixtures.replay_hash,
                    "topicReplayDigest": None if live or wire["topic"] is None else topic_digest}
        upstream = {"principal": principal, "jobId": job_id, "inputDigest": input_digest}
        if live:
            approval["liveRuntimeIdentity"] = upstream["liveRuntimeIdentity"] = live_identity
        approvals_size += len(canonical(approval).encode("utf-8"))
        if approvals_size > MAX_APPROVALS:  # fail while building, before the whole plan is held in memory
            raise ExtractionFailure("plan_approvals_too_large")
        approvals.append(approval)
        upstreams.append(upstream)
        units.append({"jobId": job_id, "inputDigest": input_digest, "approvedRequestDigest": approved, "page": entry.page, "ordinal": entry.ordinal,
                      "documentId": entry.document_id, "rawVersion": entry.ref.raw_version, "documentVersion": entry.version,
                      "submit": {"schemaVersion": wire["schemaVersion"], "jobId": job_id, "approvedRequestDigest": approved}})
    envelope = len(canonical({"schemaVersion": APPROVALS_SCHEMA, "approvals": []}).encode("utf-8")) + 1
    _bounded(approvals, envelope, MAX_APPROVALS, "plan_approvals_too_large")
    _bounded(upstreams, len(canonical({"schemaVersion": UPSTREAMS_SCHEMA, "upstreams": []}).encode("utf-8")) + 1, MAX_UPSTREAMS, "plan_upstreams_too_large")
    files = {"approvals.json": _line({"schemaVersion": APPROVALS_SCHEMA, "approvals": approvals}),
             "relation-upstreams.json": _line({"schemaVersion": UPSTREAMS_SCHEMA, "upstreams": upstreams})}
    skipped = [{"page": e.page, "ordinal": e.ordinal, "documentId": e.document_id, "documentVersion": e.version, "code": e.skip[0],
                "detail": translated[e.skip[1]] if e.skip[0] == "duplicate_in_round" else e.skip[1]} for e in entries if e.skip is not None]
    manifest = {"schemaVersion": PLAN_SCHEMA, "planId": plan_id, "principal": principal, "enqueueId": request.enqueue_id, "round": round_identity,
                "provenance": request.provenance.wire(), "promptVersion": request.prompt_version, "mode": "live" if live else "replay",
                "pins": {key: value for key, value in pins.items() if value is not None},
                "registryFiles": {name: {"sha256": byte_hash(raw), "bytes": len(raw)} for name, raw in files.items()},
                "units": units, "skipped": skipped, "counts": {"units": len(units), "skipped": len(skipped)}}
    manifest = {**manifest, "planDigest": digest(manifest)}
    files["manifest.json"] = _line(manifest)
    if len(files["manifest.json"]) > MAX_MANIFEST:
        raise ExtractionFailure("plan_manifest_too_large")
    receipt = {"schemaVersion": RECEIPT_SCHEMA, "planId": plan_id, "planDigest": manifest["planDigest"],
               "files": {name: {"sha256": byte_hash(raw), "bytes": len(raw)} for name, raw in sorted(files.items())}}
    files["receipt.json"] = _line(receipt)
    return files


def _same(output: Path, files: dict[str, bytes]) -> bool:
    """The existing path is exactly this plan: a real directory holding precisely these files with precisely these bytes."""
    try:
        if output.is_symlink() or not output.is_dir() or sorted(p.name for p in output.iterdir()) != sorted(files):
            return False
        return all(not (output / name).is_symlink() and (output / name).is_file() and (output / name).read_bytes() == raw for name, raw in files.items())
    except OSError:
        return False


def _rename_noreplace(source: Path, target: Path) -> None:
    """Atomically move a directory to a path that must not exist (an EMPTY existing directory is refused too, which a plain `rename` would replace).
    The kernel primitive is `renamex_np(RENAME_EXCL)` on macOS and `renameat2(RENAME_NOREPLACE)` on Linux; without one there is no safe publication."""
    libc = ctypes.CDLL(None, use_errno=True)
    a, b = os.fsencode(source), os.fsencode(target)
    if sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        failed = libc.renamex_np(a, b, 0x4) != 0  # RENAME_EXCL
    elif hasattr(libc, "renameat2"):
        failed = libc.renameat2(-100, a, -100, b, 1) != 0  # AT_FDCWD, RENAME_NOREPLACE
    else:
        raise ExtractionFailure("plan_publication_unsupported")
    if failed:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))


def commit(output: Path, files: dict[str, bytes]) -> str:
    """Write the directory aside, flush it and publish it with a no-replace rename: the output path is either absent or complete. An existing identical
    plan (including one a concurrent identical run published first) is left byte- and mtime-untouched (`existing`); anything else at the path is
    `plan_output_conflict` and nothing is replaced."""
    if os.path.lexists(output):
        if _same(output, files):
            return "existing"
        raise ExtractionFailure("plan_output_conflict")
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", suffix=".partial", dir=output.parent))
    try:
        for name, raw in files.items():
            fd = os.open(staging / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        os.chmod(staging, stat.S_IRWXU)
        _sync(staging)
        try:
            _rename_noreplace(staging, output)
        except OSError as exc:
            if exc.errno not in (errno.ENOTEMPTY, errno.EEXIST, errno.ENOTDIR, errno.EISDIR):
                raise
            if _same(output, files):  # a concurrent identical run won
                return "existing"
            raise ExtractionFailure("plan_output_conflict") from exc
        _sync(output.parent)
        return "created"
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _sync(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def plan_round(request: EnqueueRound, fixtures: Fixtures, principal: str, ingestion_dir: Path, sources: Path, output: Path,
               live: LiveAccess | None = None) -> dict:
    """Plan one complete round into `output`. Returns the stdout body (the receipt plus `outcome` created|existing). Every refusal raises before any
    file exists; the ledger of any extraction state is never opened."""
    if not PRINCIPAL.fullmatch(principal):
        raise ExtractionFailure("plan_principal_invalid")
    target = _output(output)
    live = live or LiveAccess()
    identity = None
    if request.provenance.execution_mode == "live":
        if fixtures.replay_hash is not None or fixtures.topic_raw is not None:
            raise ExtractionFailure("fixture_not_allowed")
        identity = live.config().binding()["identity"]  # environment names only, never a key; sending needs `sender`, which is never built here
    else:
        analysis.identity(fixtures.require(), request.provenance, request.prompt_version)
        if (request.topic is None) != (fixtures.topic_raw is None):
            raise ExtractionFailure("fixture_not_allowed" if request.topic is None else "topic_replay_required")
    authority = Authority(sources)
    head, refs, scope_id, saved, operations = _read_round(request, ingestion_dir, authority)
    entries = plan(request, head, refs)
    files = build(request, entries, head, fixtures, principal, identity)
    try:
        authority.check(request.source_id, scope_id, operations, saved)  # the round's authority must still hold when the plan is written
    except OSError as exc:
        raise IngestionFailure("registry_changed") from exc
    outcome = commit(target, files)
    return {**json.loads(files["receipt.json"]), "outcome": outcome}
