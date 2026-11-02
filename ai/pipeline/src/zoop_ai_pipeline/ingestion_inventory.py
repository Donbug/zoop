"""Read-only checkpoint and keyset-paged observation metadata for the bound round producer."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from .ingestion import Ingestor, Store
from .ingestion_contracts import Authority, IngestionFailure, Wire, timestamp

SCHEMA = "zoop-ingestion-round-inventory-1"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
OPERATIONS = ("read", "store", "quote-display")


def micros(value):
    return (timestamp(value) - EPOCH) // timedelta(microseconds=1) if value is not None else None


class Cursor(Wire):
    slot: str
    round_id: str = Field(min_length=1, max_length=200)
    page: int = Field(ge=0)
    ordinal: int = Field(ge=0)

    @field_validator("slot")
    @classmethod
    def valid_slot(cls, value):
        timestamp(value)
        return value


class Inventory(Wire):
    schema_version: Literal["zoop-ingestion-round-inventory-1"]
    source_id: str = Field(min_length=1, max_length=200)
    scope_id: str = Field(min_length=1, max_length=200)
    as_of: str
    max_age_seconds: int = Field(gt=0)
    limit: int = Field(default=64, ge=0, le=100)
    after: Cursor | None = None
    checkpoint_revision: int | None = Field(default=None, ge=0)

    @field_validator("as_of")
    @classmethod
    def valid_time(cls, value):
        timestamp(value)
        return value


def inventory(request: Inventory, root: Path, authority: Authority) -> dict:
    """Only complete, timed, prepared, unambiguous observations in the explicit age window are candidates.

    The immutable native inventory retains every undispatched observation. Paging never retires it; the producer's permanent
    exact-observation claims decide which relevant candidates remain available. Missing/foreign/partial state is not adopted.
    """
    authority.check(request.source_id, request.scope_id, OPERATIONS)
    result = {"schemaVersion": SCHEMA, "sourceId": request.source_id, "scopeId": request.scope_id,
              "asOf": request.as_of, "maxAgeSeconds": request.max_age_seconds,
              "checkpoint": {"revision": 0, "through": None}, "observations": [], "next": None}
    try:
        store = Store(root, existing=True)
    except IngestionFailure as error:
        absent = not os.path.lexists(root) or root.is_dir() and not any(root.iterdir())
        if error.code != "ingestion_state_missing" or not absent:
            raise
        if request.checkpoint_revision not in (None, 0) or request.after is not None:
            raise IngestionFailure("checkpoint_stale") from None
        return result
    try:
        checkpoint = store.one("SELECT revision,through_time,config FROM scopes WHERE source=? AND scope=?",
                               (request.source_id, request.scope_id))
        if checkpoint is not None:
            authority.check(request.source_id, request.scope_id, OPERATIONS, json.loads(checkpoint["config"]))
            result["checkpoint"] = {"revision": checkpoint["revision"], "through": checkpoint["through_time"]}
        elif store.one("SELECT 1 FROM rounds WHERE source=? AND json_extract(request,'$.scopeId')=? LIMIT 1",
                       (request.source_id, request.scope_id)) is not None:
            raise IngestionFailure("ingestion_state_invalid")
        revision = result["checkpoint"]["revision"]
        if request.checkpoint_revision is not None and request.checkpoint_revision != revision:
            raise IngestionFailure("checkpoint_stale")
        if request.limit == 0:
            return result
        store.db.create_function("round_slot_micros", 1, micros, deterministic=True)
        query = """
            SELECT c.round,c.source,c.page,c.ordinal,c.document,c.raw_version,c.version,
                   json_extract(r.request,'$.window.through') AS slot
            FROM candidates c JOIN rounds r ON r.id=c.round AND r.source=c.source
            WHERE c.source=? AND json_extract(r.request,'$.scopeId')=? AND r.state='complete'
              AND c.version IS NOT NULL AND c.hold IS NULL AND c.error IS NULL AND c.failure IS NULL AND c.ambiguity IS NULL
              AND round_slot_micros(json_extract(r.request,'$.window.through')) BETWEEN ? AND ?
        """
        now = micros(request.as_of)
        args = [request.source_id, request.scope_id, now - request.max_age_seconds * 1_000_000, now]
        if request.after is not None:
            query += " AND (round_slot_micros(json_extract(r.request,'$.window.through')),c.round,c.page,c.ordinal) > (?,?,?,?)"
            args += [micros(request.after.slot), request.after.round_id, request.after.page, request.after.ordinal]
        query += " ORDER BY round_slot_micros(json_extract(r.request,'$.window.through')),c.round,c.page,c.ordinal LIMIT ?"
        args.append(request.limit + 1)
        rows = store.db.execute(query, args).fetchall()
        runner, checked = Ingestor(store, authority), set()
        for row in rows[:request.limit]:
            if row["round"] not in checked:
                scope, _ = runner.authorize_round(row["round"], request.source_id, OPERATIONS)
                if scope != request.scope_id:
                    raise IngestionFailure("scope_configuration_conflict")
                checked.add(row["round"])
            result["observations"].append({"slot": row["slot"], "observation": {
                "roundId": row["round"], "sourceId": row["source"], "page": row["page"], "ordinal": row["ordinal"],
                "documentId": row["document"], "rawVersion": row["raw_version"], "documentVersion": row["version"]}})
        if len(rows) > request.limit:
            last = rows[request.limit - 1]
            result["next"] = {"slot": last["slot"], "roundId": last["round"], "page": last["page"], "ordinal": last["ordinal"]}
        authority.check(request.source_id, request.scope_id, OPERATIONS,
                        json.loads(checkpoint["config"]) if checkpoint is not None else None)
        return result
    finally:
        store.close()
