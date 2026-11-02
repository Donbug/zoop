"""Round -> operator service plan: the offline, self-contained counterpart of `enqueue-round` for the HTTP S2/S3 doors.

`plan-round` reads a COMPLETE ingestion round through the ordinary enqueue planner and writes ONE immutable plan directory, and nothing else: no
extraction ledger is opened, no job is frozen, no provider, replay or network call is made, and no installed service file is touched. The operator
reviews the directory before the separate offline service installer merges its registries. Deployment and model-budget approval remain separate
decisions this plan never makes. The directory holds

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
import math
import os
import re
import shutil
import stat
import sys
import tempfile
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from . import extraction_replay as analysis
from .extraction import Fixtures, LiveAccess, Sources, doc_key
from .extraction_contracts import EnqueueRound, ExtractionFailure, ObservationRef, Submit, canonical, digest
from .extraction_enqueue import _read_round, plan
from .ingestion_contracts import Authority, IngestionFailure, Wire, byte_hash, timestamp

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


class RoundSelection(Wire):
    """Explicit immutable policy and queue snapshot for one 30-minute planning round."""
    schema_version: Literal["zoop-extraction-round-selection-1"]
    as_of: str
    max_age_seconds: int = Field(gt=0)
    limit: int = Field(default=8, gt=0, le=8)
    cadence_minutes: Literal[30] = 30
    carryover: list[ObservationRef] = Field(default_factory=list)
    in_flight: list[ObservationRef] = Field(default_factory=list)
    settled: list[ObservationRef] = Field(default_factory=list)

    @field_validator("as_of")
    @classmethod
    def valid_time(cls, value):
        timestamp(value)
        return value


class ExplicitRoundSelection(Wire):
    """A bounded working page; every omitted candidate remains in the native inventory."""
    schema_version: Literal["zoop-extraction-round-selection-2"]
    as_of: str
    max_age_seconds: int = Field(gt=0)
    limit: int = Field(default=8, gt=0, le=8)
    cadence_minutes: Literal[30] = 30
    observations: list[ObservationRef] = Field(max_length=8)

    @field_validator("as_of")
    @classmethod
    def valid_time(cls, value):
        timestamp(value)
        return value


def parse_selection(value):
    model = ExplicitRoundSelection if value.get("schemaVersion") == "zoop-extraction-round-selection-2" else RoundSelection
    return model.model_validate(value)


def _select(request, head, entries, selection, ingestion_dir, authority):
    """Oldest eligible carry first; original observations and slots remain owner-derived."""
    checks, reports, carried = [], [], []
    explicit = isinstance(selection, ExplicitRoundSelection)
    groups = {}
    for ref in selection.observations if explicit else selection.carryover:
        groups.setdefault((ref.round_id, ref.source_id), []).append(ref)
    for (round_id, source_id), refs in groups.items():
        descriptor = request.model_copy(update={"round_id": round_id, "source_id": source_id})
        try:
            old_head, old_refs, scope, saved, operations = _read_round(descriptor, ingestion_dir, authority)
        except IngestionFailure as exc:
            if exc.code != "source_unauthorized":
                raise
            reports.extend({"observation": ref.wire(), "slot": None, "code": "current_rights_withheld", "detail": exc.code} for ref in refs)
            continue
        checks.append((source_id, scope, operations, saved))
        indexed = {canonical(e.ref.wire()): e for e in plan(descriptor, old_head, old_refs) if e.ref is not None}
        window = old_head["checkedWindow"]
        for ref in refs:
            entry = indexed.get(canonical(ref.wire()))
            if entry is None:
                raise ExtractionFailure("carryover_observation_mismatch")
            carried.append((entry, window["through"] if window else None))
    window = head["checkedWindow"]
    current = [] if explicit else [(e, window["through"] if window else None) for e in entries]
    carried.sort(key=lambda pair: (timestamp(pair[1]) if pair[1] is not None else timestamp(selection.as_of),
                                   pair[0].ref.source_id, pair[0].ref.round_id, pair[0].page, pair[0].ordinal))
    excluded = {}
    if not explicit:
        excluded = {canonical(ref.wire()): "in_flight" for ref in selection.in_flight}
        excluded.update({canonical(ref.wire()): "already_settled" for ref in selection.settled})
    seen, selected, carryover, output = set(), 0, [], []
    now = timestamp(selection.as_of)
    reader = Sources(ingestion_dir, authority)
    for original, slot in [*carried, *current]:
        entry = replace(original)
        if entry.ref is None:
            output.append(entry)
            continue
        key = canonical(entry.ref.wire())
        code, detail = entry.skip if entry.skip is not None and entry.skip[0] != "duplicate_in_round" else (None, None)
        if key in excluded:
            code = excluded[key]
        elif key in seen:
            code = "duplicate_observation"
        elif code is None:
            if slot is None:
                code = "round_slot_unavailable"
            elif timestamp(slot) > now:
                code = "round_slot_future"
            elif (now - timestamp(slot)).total_seconds() > selection.max_age_seconds:
                code = "too_old"
            else:
                reader.export(entry.ref)
                if selected == selection.limit:
                    code = "round_limit"
                    carryover.append(entry.ref.wire())
                else:
                    selected += 1
        seen.add(key)
        entry.skip = (code, detail) if code is not None else None
        reports.append({"observation": entry.ref.wire(), "slot": slot, "code": code, "detail": detail})
        output.append(entry)
    return output, checks, {"selection": selection.wire(), "selectionReport": reports, "carryover": carryover}


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


def build(request: EnqueueRound, entries: list, head: dict, fixtures: Fixtures, principal: str, live_identity: str | None,
          selection: dict | None = None) -> dict[str, bytes]:
    """Pure: the bytes of every file of the plan directory. Raises before returning anything when a bound or a rule is violated."""
    planned = [entry for entry in entries if entry.skip is None]
    if not planned:
        raise ExtractionFailure("plan_has_no_units", selection)
    live = live_identity is not None
    topic_digest = byte_hash(fixtures.topic_raw) if fixtures.topic_raw is not None else None
    pins = {"producerReplayDigest": fixtures.replay_hash, "topicReplayDigest": topic_digest, "liveRuntimeIdentity": live_identity}
    round_identity = {"roundId": request.round_id, "sourceId": request.source_id, "ingestionInputDigest": head["inputDigest"]}
    plan_id = "s2plan-" + digest({
        "format": PLAN_FORMAT, "principal": principal, "enqueueId": request.enqueue_id, "round": round_identity, "provenance": request.provenance.wire(),
        "promptVersion": request.prompt_version, "catalogue": request.catalogue.wire(), "snapshot": request.snapshot.wire(),
        "topic": request.topic.wire() if request.topic else None, "pins": pins,
        "observations": [entry.ref.wire() for entry in planned], **({"selection": selection["selection"]} if selection is not None else {})})
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
    if selection is not None:
        manifest.update(selection)
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


def _prepare(request: EnqueueRound, fixtures: Fixtures, principal: str, ingestion_dir: Path, sources: Authority | Path,
             live: LiveAccess | None = None, selection: RoundSelection | ExplicitRoundSelection | None = None) -> tuple[dict[str, bytes], list, Authority, list]:
    """Shared read-only planning path; publication and source export authority remain separate operations."""
    if not PRINCIPAL.fullmatch(principal):
        raise ExtractionFailure("plan_principal_invalid")
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
    authority = sources if isinstance(sources, Authority) else Authority(sources)
    head, refs, scope_id, saved, operations = _read_round(request, ingestion_dir, authority)
    entries = plan(request, head, refs)
    checks = [(request.source_id, scope_id, operations, saved)]
    report = None
    if selection is not None:
        entries, carried_checks, report = _select(request, head, entries, selection, ingestion_dir, authority)
        checks.extend(carried_checks)
    files = build(request, entries, head, fixtures, principal, identity, report)
    return files, entries, authority, checks


def plan_round(request: EnqueueRound, fixtures: Fixtures, principal: str, ingestion_dir: Path, sources: Path, output: Path,
               live: LiveAccess | None = None, *, selection: RoundSelection | ExplicitRoundSelection | None = None) -> dict:
    """Publish one immutable plan without opening an extraction ledger or freezing a job."""
    if selection is None:
        raise ExtractionFailure("plan_selection_policy_required")
    if not PRINCIPAL.fullmatch(principal):
        raise ExtractionFailure("plan_principal_invalid")
    target = _output(output)
    files, _, authority, checks = _prepare(request, fixtures, principal, ingestion_dir, sources, live, selection)
    try:
        for check in checks:
            authority.check(*check)
    except OSError as exc:
        raise IngestionFailure("registry_changed") from exc
    outcome = commit(target, files)
    return {**json.loads(files["receipt.json"]), "outcome": outcome}


VERIFICATION_SCHEMA = "zoop-extraction-service-plan-verification-1"
MAX_RECEIPT = 4_096


def strict_json(raw: bytes):
    """Duplicate-free finite JSON; neither parser coercion nor last-key-wins is plan authority."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("nonfinite value")

    def finite(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("nonfinite value")
        return parsed

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=constant, parse_float=finite)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ExtractionFailure("plan_input_invalid") from exc


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _directory_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode)


class _PlanFiles:
    """Pin each no-follow path component and regular leaf; recheck names, identities and bytes before returning."""

    def __init__(self, path: Path):
        self.path = path
        self.stack = ExitStack()
        self.links = []
        self.leaves = {}

    def _own(self, fd):
        self.stack.callback(os.close, fd)
        return fd

    def __enter__(self):
        try:
            if ".." in self.path.parts:
                raise ExtractionFailure("plan_path_invalid")
            absolute = Path(os.path.abspath(self.path))
            parent = self._own(os.open("/", os.O_RDONLY | os.O_DIRECTORY))
            for part in absolute.parts[1:]:
                child = self._own(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent))
                self.links.append((parent, part, child, _directory_identity(os.fstat(child))))
                parent = child
            self.directory = parent
            limits = {"approvals.json": MAX_APPROVALS, "relation-upstreams.json": MAX_UPSTREAMS,
                      "manifest.json": MAX_MANIFEST, "receipt.json": MAX_RECEIPT}
            if set(os.listdir(parent)) != set(limits):
                raise ExtractionFailure("plan_input_invalid")
            files = {}
            for name, maximum in limits.items():
                fd = self._own(os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent))
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= maximum:
                    raise ExtractionFailure("plan_input_invalid")
                raw = os.pread(fd, maximum + 1, 0)
                if len(raw) != info.st_size or _stamp(os.fstat(fd)) != _stamp(info):
                    raise ExtractionFailure("plan_files_changed")
                files[name] = raw
                self.leaves[name] = (fd, _stamp(info), maximum, raw)
            self.files = files
            self.check()
            return self
        except OSError as exc:
            self.stack.close()
            raise ExtractionFailure("plan_path_invalid") from exc
        except BaseException:
            self.stack.close()
            raise

    def check(self):
        try:
            for parent, part, child, stamp in self.links:
                if (_directory_identity(os.stat(part, dir_fd=parent, follow_symlinks=False)) != stamp
                        or _directory_identity(os.fstat(child)) != stamp):
                    raise ExtractionFailure("plan_files_changed")
            if set(os.listdir(self.directory)) != set(self.leaves):
                raise ExtractionFailure("plan_files_changed")
            for name, (fd, stamp, maximum, raw) in self.leaves.items():
                if (_stamp(os.stat(name, dir_fd=self.directory, follow_symlinks=False)) != stamp
                        or _stamp(os.fstat(fd)) != stamp or os.pread(fd, maximum + 1, 0) != raw
                        or _stamp(os.fstat(fd)) != stamp):
                    raise ExtractionFailure("plan_files_changed")
        except OSError as exc:
            raise ExtractionFailure("plan_files_changed") from exc

    def __exit__(self, *_):
        self.stack.close()


def _receipt(files: dict[str, bytes], expected: str) -> dict:
    if not isinstance(expected, str) or re.fullmatch(r"[a-f0-9]{64}", expected) is None:
        raise ExtractionFailure("plan_input_invalid")
    if byte_hash(files["receipt.json"]) != expected:
        raise ExtractionFailure("plan_receipt_mismatch")
    docs = {name: strict_json(raw) for name, raw in files.items()}
    receipt = docs["receipt.json"]
    if (not isinstance(receipt, dict) or set(receipt) != {"schemaVersion", "planId", "planDigest", "files"}
            or receipt["schemaVersion"] != RECEIPT_SCHEMA or not isinstance(receipt["files"], dict)
            or set(receipt["files"]) != set(files) - {"receipt.json"}):
        raise ExtractionFailure("plan_input_invalid")
    for name, pin in receipt["files"].items():
        if (not isinstance(pin, dict) or set(pin) != {"sha256", "bytes"} or type(pin["bytes"]) is not int
                or pin["bytes"] != len(files[name]) or pin["sha256"] != byte_hash(files[name])):
            raise ExtractionFailure("plan_receipt_mismatch")
    return docs


def read_plan(plan_dir: Path) -> dict:
    """The manifest of one immutable plan directory, proven self-consistent and nothing more: the pinned leaf files are exactly the four plan files, the receipt names
    each file's size and SHA-256, and the manifest's plan digest is recomputed. No ledger, source registry or fixture is consulted (that is `verify_plan`)."""
    with _PlanFiles(plan_dir) as pinned:
        docs = _receipt(pinned.files, byte_hash(pinned.files["receipt.json"]))
        manifest, receipt = docs["manifest.json"], docs["receipt.json"]
        try:
            body = {key: value for key, value in manifest.items() if key != "planDigest"}
            consistent = (manifest["schemaVersion"] == PLAN_SCHEMA and (receipt["planId"], receipt["planDigest"]) == (manifest["planId"], manifest["planDigest"])
                          and digest(body) == manifest["planDigest"])
        except (AttributeError, KeyError, TypeError):
            consistent = False
        if not consistent:
            raise ExtractionFailure("plan_content_mismatch")
        pinned.check()
        return manifest


def verify_plan(plan_dir: Path, expected_receipt_sha256: str, fixtures: Fixtures, ingestion_dir: Path, sources: Path,
                live: LiveAccess | None = None) -> dict:
    """Reconstruct exact original bytes and current read-only source bindings. Never freeze or confer send/publication authority."""
    with _PlanFiles(plan_dir) as pinned:
        docs = _receipt(pinned.files, expected_receipt_sha256)
        try:
            manifest = docs["manifest.json"]
            approvals = docs["approvals.json"]["approvals"]
            if not isinstance(approvals, list) or not approvals:
                raise ExtractionFailure("plan_has_no_units")
            first = Submit.model_validate(approvals[0]["request"])
            shared = first.wire()
            request = EnqueueRound.model_validate({
                **{key: shared[key] for key in ("schemaVersion", "provenance", "promptVersion", "catalogue", "snapshot", "topic")},
                "enqueueId": manifest["enqueueId"], "roundId": manifest["round"]["roundId"], "sourceId": manifest["round"]["sourceId"]})
            principal = manifest["principal"]
            if not isinstance(principal, str):
                raise ExtractionFailure("plan_principal_invalid")
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise ExtractionFailure("plan_input_invalid") from exc
        authority = Authority(sources)
        selection = parse_selection(manifest["selection"]) if "selection" in manifest else None
        files, entries, _, checks = _prepare(request, fixtures, principal, ingestion_dir, authority, live, selection)
        if files != pinned.files:
            raise ExtractionFailure("plan_content_mismatch")
        refs = {doc_key(e.ref): e.ref for e in entries if e.skip is None}
        for event in request.snapshot.events:
            for member in event.members:
                refs[doc_key(member.observation)] = member.observation
        reader = Sources(ingestion_dir, authority)
        synthetic = request.provenance.source_kind == "synthetic"

        def bindings():
            result = []
            for key, ref in sorted(refs.items()):
                exported = reader.export(ref)
                result.append({"observation": ref.wire(), "binding": analysis.bind(exported, analysis.article(exported, synthetic))})
            return digest({"format": "zoop-extraction-service-plan-source-bindings-1", "documents": result})

        source_digest = bindings()
        if bindings() != source_digest:
            raise ExtractionFailure("plan_sources_changed")
        for check in checks:
            authority.check(*check)
        pinned.check()
        receipt = docs["receipt.json"]
        return {"schemaVersion": VERIFICATION_SCHEMA, "planId": receipt["planId"], "planDigest": receipt["planDigest"],
                "receiptSha256": expected_receipt_sha256, "principal": principal, "mode": manifest["mode"],
                "pins": manifest["pins"], "files": receipt["files"], "counts": manifest["counts"],
                "sourceRegistrySha256": byte_hash(authority.raw), "sourceBindingsDigest": source_digest}
