"""Round -> S2 registration: one `queued` job per planned observation of a COMPLETE ingestion round, under one explicit descriptor.

This is registration only, exactly like `submit`: nothing is executed, no provider or replay call is made and the ingestion checkpoint is never
touched. Every prepared observation of the round is checked against the S2 ledger BEFORE any filter can hide an existing binding, so a changed
descriptor, replay fixture or live runtime can never slip past through a skipped observation. A planned job is registered by the ordinary
`Extractor.freeze` in its own transaction; the first failure stops the batch (the durable prefix stays, nothing is rolled back or retried) and an
identical rerun registers exactly the remainder. The batch is NOT all-or-none."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from . import extraction_replay as analysis
from .extraction import Extractor, Fixtures, LiveAccess, Sources, Store
from .extraction_contracts import SCHEMA, EnqueueRound, ExtractionFailure, ObservationRef, Submit
from .ingestion import Ingestor
from .ingestion import Store as IngestionStore
from .ingestion_contracts import Authority, IngestionFailure

PAGE = 100  # refs read per ingestion result page


@dataclass
class Entry:
    """One ingestion candidate of the round. `ref`/`submit` exist exactly for a prepared observation (a held one has no document version)."""
    page: int
    ordinal: int
    document_id: str
    version: str | None
    ref: ObservationRef | None = None
    submit: Submit | None = None
    skip: tuple[str, str | None] | None = None  # (code, detail) of the first matching filter, else the entry is planned
    registration: str | None = None  # planned entries only: new (pending) | existing | registered | failed | not-attempted


def _refs_consistent(head: dict, refs: list[dict]) -> bool:
    """A complete round has every candidate decided: held, or prepared with its document identities, and none unfinished, failed or in error. The
    refs are read in (page, ordinal) order and must be exactly the discovered candidates."""
    keys = [(r["page"], r["ordinal"]) for r in refs]
    return (head["counts"]["unfinished"] == 0 and len(refs) == head["counts"]["discoveredCandidates"]
            and all(a < b for a, b in zip(keys, keys[1:]))
            and all(r["error"] is None and r["failure"] is None and isinstance(r["documentId"], str)
                    and (isinstance(r["hold"], str) or (isinstance(r["documentVersion"], str) and isinstance(r["rawVersion"], str))) for r in refs))


def plan(request: EnqueueRound, head: dict, refs: list[dict]) -> list[Entry]:
    """Pure. Gate the round, derive the job id of EVERY prepared observation (ambiguous, in-snapshot and duplicate ones included, before any filter
    applies) and then mark the first matching skip: held, ambiguous, in_snapshot (the document version is any snapshot member's, which is what the
    extractor refuses as `snapshot_member_invalid`), duplicate_in_round (same document id and version as an earlier planned one). Nothing is invented."""
    if head["state"] != "complete":
        raise ExtractionFailure("round_not_complete")
    if not _refs_consistent(head, refs):
        raise ExtractionFailure("round_refs_inconsistent")
    in_snapshot = {member.observation.document_version for event in request.snapshot.events for member in event.members}
    kept: dict[tuple[str, str], str] = {}
    entries = []
    for r in refs:
        entry = Entry(r["page"], r["ordinal"], r["documentId"], r["documentVersion"])
        if r["documentVersion"] is not None:
            try:
                entry.ref = request.observation(r["page"], r["ordinal"], r["documentId"], r["rawVersion"], r["documentVersion"])
            except ValidationError as exc:
                raise ExtractionFailure("round_refs_inconsistent") from exc
            entry.submit = request.submit(entry.ref)
        if r["hold"] is not None:
            entry.skip = ("held", r["hold"])
        elif r["ambiguity"] is not None:
            entry.skip = ("ambiguous", r["ambiguity"])
        elif entry.version in in_snapshot:
            entry.skip = ("in_snapshot", None)
        elif (entry.document_id, entry.version) in kept:
            entry.skip = ("duplicate_in_round", kept[(entry.document_id, entry.version)])
        else:
            kept[(entry.document_id, entry.version)] = entry.submit.job_id
        entries.append(entry)
    return entries


def _read_round(request: EnqueueRound, ingestion_dir: Path, authority: Authority) -> tuple[dict, list[dict], str, dict, tuple[str, ...]]:
    """Under one shared read-only ingestion lock: authorize the saved round for read + store FIRST (before any summary or reference is read, even for
    a zero or all-held round), read every page, and when any observation is prepared also authorize quote-display. The ingestion store is closed
    before the extraction ledger lock is ever taken. Returns the first page's round summary, all refs, and the saved scope and config that the final
    recheck verifies again with the same operations."""
    store = IngestionStore(ingestion_dir, existing=True)
    try:
        ingestor = Ingestor(store, authority)
        operations = ("read", "store")
        scope_id, saved = ingestor.authorize_round(request.round_id, request.source_id, operations)
        head, refs, offset = None, [], 0
        while offset is not None:
            page = ingestor.result(request.round_id, request.source_id, offset, PAGE)
            head = head or page
            refs += page["documentRefs"]
            offset = page["pagination"]["nextOffset"]
        if any(r["documentVersion"] is not None for r in refs):
            operations = ("read", "store", "quote-display")
            ingestor.authorize_round(request.round_id, request.source_id, operations)
        return head, refs, scope_id, saved, operations
    finally:
        store.close()


def _absent(root: Path) -> bool:
    """Genuinely no extraction state: the directory does not exist, or is an empty (owned) directory. A populated directory that lacks its lock or
    database, one holding a foreign file or a WAL, a symlink or a non-directory is damaged or foreign state, never 'no prior jobs'."""
    if root.is_symlink():
        return False
    return not root.exists() or (root.is_dir() and not any(root.iterdir()))


def _open_ledger(state_dir: Path, ingestion_dir: Path, entries: list[Entry]) -> Store | None:
    """Planned jobs need the exclusive writer (preflight and registration under one lock). With only filtered prepared observations the ledger is read
    only: genuinely absent or empty state means there are no prior jobs, while a busy writer, an unrecovered WAL or any partial or foreign state
    refuses. With no prepared observation it is never touched."""
    if any(e.skip is None for e in entries):
        return Store(state_dir, ingestion_dir)
    if any(e.ref is not None for e in entries):
        try:
            return Store(state_dir, ingestion_dir, existing=True)
        except ExtractionFailure as exc:
            if exc.code != "extraction_state_missing" or not _absent(state_dir):
                raise
    return None


def _failure_code(exc: Exception) -> str:
    if isinstance(exc, (ExtractionFailure, IngestionFailure)):
        return exc.code
    return "persistence_failed" if isinstance(exc, (sqlite3.Error, OSError)) else "extraction_internal_failure"


def _close(store: Store | None) -> str | None:
    """Close the ledger. Returns the code of a failing close, sanitized like any other failure here, or None when it closed cleanly."""
    if store is None:
        return None
    try:
        store.close()
    except Exception as exc:  # noqa: BLE001
        return _failure_code(exc)
    return None


def _preflight(extractor: Extractor | None, entries: list[Entry], fixtures: Fixtures) -> None:
    """Every id of EVERY prepared observation, in plan order, before the first write. An existing job for a filtered observation is refused too: the
    admission raises `job_input_conflict` for another input and `analysis_contract_changed` for a legacy binding, and the same input is
    `enqueue_plan_conflict` (this enqueue would never have registered it). Filtered ids with no stored job need no context. Planned ids get their
    source context and grounded snapshot members checked now; registration re-verifies them under current rights."""
    for entry in entries:
        if entry.ref is None:
            continue
        if entry.skip is None:
            entry.registration = "existing" if extractor.admission(entry.submit, fixtures) == "existing" else "new"
        elif extractor is not None and extractor.store.one("SELECT 1 FROM jobs WHERE job_id=?", (entry.submit.job_id,)) is not None:
            if extractor.admission(entry.submit, fixtures) == "existing":
                raise ExtractionFailure("enqueue_plan_conflict")


def _register(extractor: Extractor | None, entries: list[Entry], fixtures: Fixtures) -> tuple[int, str | None]:
    """Freeze the new planned jobs in order, each in its own transaction, stopping at the first failure; later ones are not attempted. Existing jobs are
    left untouched (never resumed). Returns how many jobs this call committed and the first failure's code."""
    committed, failure = 0, None
    for entry in entries:
        if entry.skip is not None or entry.registration == "existing":
            continue
        if failure is not None:
            entry.registration = "not-attempted"
            continue
        try:
            extractor.freeze(entry.submit, fixtures)
        except Exception as exc:  # noqa: BLE001 - a durable prefix may exist: report it honestly instead of losing it to a generic envelope
            entry.registration, failure = "failed", _failure_code(exc)
        else:
            entry.registration = "registered"
            committed += 1
    return committed, failure


def enqueue_round(request: EnqueueRound, fixtures: Fixtures, state_dir: Path, ingestion_dir: Path, sources: Path, live: LiveAccess | None = None) -> tuple[dict, int]:
    """Register the planned jobs of one complete round. Returns `(body, exit code)`: 0 when every planned job is registered or already existing, 2 for an
    incomplete batch (full report) or for a refusal after registration started whose authority no longer holds (error only, no ids). Refusals before
    the first write raise `ExtractionFailure`/`IngestionFailure` (the CLI's ordinary error body)."""
    live = live or LiveAccess()
    # 1. Pure and key/network free, whatever the round holds: the replay header or the live runtime configuration is validated even for zero jobs.
    if request.provenance.execution_mode == "live":
        if fixtures.replay_hash is not None or fixtures.topic_raw is not None:
            raise ExtractionFailure("fixture_not_allowed")
        live.config()
    else:
        analysis.identity(fixtures.require(), request.provenance, request.prompt_version)
    authority = Authority(sources)
    # 2-4. Authorize, read, gate and plan.
    head, refs, scope_id, saved, operations = _read_round(request, ingestion_dir, authority)
    entries = plan(request, head, refs)
    # 4-5. Preflight every prepared id, then register the new planned ones.
    store = _open_ledger(state_dir, ingestion_dir, entries)
    try:
        extractor = Extractor(store, Sources(ingestion_dir, authority), live) if store is not None else None
        _preflight(extractor, entries, fixtures)
        committed, failure = _register(extractor, entries, fixtures)
    except BaseException:
        _close(store)  # a failing close never replaces the refusal (or interrupt) already propagating; a refusal registered nothing
        raise
    closed = _close(store)
    failure = failure or closed  # a close that fails after jobs committed is the batch's error, reported with their real counts
    # 6. No report of any kind (complete, incomplete or zero) without the authority still holding now. It names no job and no round data.
    try:
        authority.check(request.source_id, scope_id, operations, saved)
    except IngestionFailure as exc:
        return {"schemaVersion": SCHEMA, "error": {"code": exc.code, "partialRegistration": committed > 0}}, 2
    except OSError:
        return {"schemaVersion": SCHEMA, "error": {"code": "registry_changed", "partialRegistration": committed > 0}}, 2
    return report(request, head, entries, failure), 2 if failure else 0


def report(request: EnqueueRound, head: dict, entries: list[Entry], failure: str | None) -> dict:
    planned = [e for e in entries if e.skip is None]
    jobs = [{"jobId": e.submit.job_id, "page": e.page, "ordinal": e.ordinal, "documentId": e.document_id, "rawVersion": e.ref.raw_version,
             "documentVersion": e.version, "registration": e.registration} for e in planned]
    skipped = [{"page": e.page, "ordinal": e.ordinal, "documentId": e.document_id, "documentVersion": e.version, "code": e.skip[0], "detail": e.skip[1]}
               for e in entries if e.skip is not None]
    states = [job["registration"] for job in jobs]
    return {"schemaVersion": SCHEMA, "enqueueId": request.enqueue_id,
            "round": {"roundId": request.round_id, "sourceId": request.source_id, "inputDigest": head["inputDigest"], "provenance": head["provenance"],
                      "completion": head["completion"]},
            "outcome": "incomplete" if failure else "complete", "jobs": jobs, "skipped": skipped,
            "counts": {"refs": len(entries), "jobs": len(jobs), "registered": states.count("registered"), "existing": states.count("existing"),
                       "failed": states.count("failed"), "notAttempted": states.count("not-attempted"), "skipped": len(skipped)},
            "error": {"code": failure} if failure else None}
