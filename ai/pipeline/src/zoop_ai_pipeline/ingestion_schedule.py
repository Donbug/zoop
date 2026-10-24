"""Offline round controller (FS058): one `tick` maps a clock reading to the latest due KST slot and drives exactly one ingestion round for it.

Slots are every calendar day (no weekday or holiday rule) at fixed UTC+09 09:05, 09:35, ... 17:35, accepted only while 09:00 <= now < 18:00.
The controller never retries: a terminal same-slot round is replayed from its stored result, and a crashed `running` round is resumed once.
Nothing here claims provider coverage; the window and its `catchUp` flag only describe what this controller asked the engine to cover."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from .ingestion import Ingestor, Store
from .ingestion_contracts import CLEANER, MAX_INPUT, SCHEMA, Authority, IngestionFailure, Run, Tick, byte_hash, digest, read_file, timestamp

KST = timezone(timedelta(hours=9))
FIRST_SLOT_SECONDS, SLOT_SECONDS, LAST_SLOT_INDEX = 5 * 60, 30 * 60, 17     # 09:05 + 30 min * k, k = 0..17 -> 17:35
CATCH_UP_AFTER = timedelta(minutes=30)


def latest_slot(now: datetime) -> tuple[datetime | None, str | None]:
    """The latest due slot (KST) for an aware instant, else `(None, reason)`. Seconds count: 09:04:59 is not due, 09:05:00 is."""
    local = now.astimezone(KST)
    since_open = (local - local.replace(hour=9, minute=0, second=0, microsecond=0)).total_seconds()
    if since_open < 0 or local.hour >= 18:
        return None, "outside_operating_window"
    if since_open < FIRST_SLOT_SECONDS:
        return None, "before_first_slot"
    index = min(int((since_open - FIRST_SLOT_SECONDS) // SLOT_SECONDS), LAST_SLOT_INDEX)
    return local.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(seconds=FIRST_SLOT_SECONDS + index * SLOT_SECONDS), None


def slot_text(slot: datetime) -> str:
    return slot.astimezone(KST).strftime("%Y-%m-%dT%H:%M:00+09:00")


def round_id(source_id: str, scope_id: str, slot: datetime) -> str:
    """Bounded and deterministic for any source/scope length; the readable slot travels in the output, not in the id."""
    return "slot-" + digest({"sourceId": source_id, "scopeId": scope_id, "slot": slot_text(slot)})


def catch_up(window_from: datetime, slot: datetime) -> bool:
    return slot - window_from > CATCH_UP_AFTER


def clock(request: Tick, actual: datetime | None = None) -> datetime:
    actual = actual or datetime.now(UTC)
    now = timestamp(request.now) if request.now is not None else actual
    if now > actual:
        raise IngestionFailure("clock_in_future")
    return now


def output(now: datetime, slot: datetime | None, rid: str | None, reason: str | None, catching: bool | None, result: dict | None):
    return {"schemaVersion": SCHEMA, "tick": {"action": "not-due", "at": now.astimezone(KST).isoformat(), "slot": slot and slot_text(slot), "roundId": rid,
            "reason": reason, "catchUp": catching}, "round": result}


def not_due(now: datetime, reason: str) -> dict:
    return output(now, None, None, reason, None, None)


def tick(request: Tick, now: datetime, slot: datetime, store: Store, authority: Authority, manifest_path: Path | None) -> tuple[dict, int]:
    """Drive the round for a due slot. The caller holds the exclusive Store lock for the whole call (so any stored `running` round is a dead process)."""
    authority.check(request.source_id, request.scope_id)
    rid, runner = round_id(request.source_id, request.scope_id, slot), Ingestor(store, authority)
    existing = store.one("SELECT * FROM rounds WHERE id=? AND source=?", (rid, request.source_id))
    if existing:
        stored = Run.model_validate_json(existing["request"])
        if (stored.round_id, stored.source_id, stored.scope_id, stored.cleaner_version) != (rid, request.source_id, request.scope_id, CLEANER) or stored.window is None or timestamp(stored.window.through) != slot:
            raise IngestionFailure("slot_input_conflict")
        if manifest_path is not None and byte_hash(read_file(manifest_path, MAX_INPUT)) != stored.fixture_manifest_hash:
            raise IngestionFailure("slot_input_conflict")
        if request.initial_from is not None and timestamp(request.initial_from) != timestamp(stored.window.from_):
            raise IngestionFailure("slot_input_conflict")
        catching = catch_up(timestamp(stored.window.from_), slot)
        runner._authorize(existing)
        if existing["state"] == "running":
            action, result = "recovered", runner.resume(rid, request.source_id)
        else:
            action, result = "replayed", runner.result(rid, request.source_id)
    else:
        checkpoint = store.one("SELECT revision,through_time FROM scopes WHERE source=? AND scope=?", (request.source_id, request.scope_id))
        through = checkpoint["through_time"] if checkpoint else None
        if through is not None and request.initial_from is not None:
            raise IngestionFailure("initial_baseline_conflict")
        if through is None and request.initial_from is None:
            raise IngestionFailure("initial_baseline_required")
        baseline = timestamp(through) if through is not None else timestamp(request.initial_from)
        if baseline >= slot:
            raise IngestionFailure("slot_not_after_baseline")
        if manifest_path is None:
            raise IngestionFailure("fixture_manifest_required")
        run = Run.model_validate({"schemaVersion": SCHEMA, "roundId": rid, "sourceId": request.source_id, "scopeId": request.scope_id,
            "window": {"from": through if through is not None else baseline.isoformat(), "through": slot_text(slot)},
            "checkpointRevision": checkpoint["revision"] if checkpoint else 0,
            "fixtureManifestHash": byte_hash(read_file(manifest_path, MAX_INPUT)), "cleanerVersion": CLEANER})
        catching = catch_up(baseline, slot)
        action, result = "started", runner.run(run, manifest_path)
    body = output(now, slot, rid, None, catching, result)
    body["tick"]["action"] = action
    return body, 0 if result["state"] == "complete" else 3
