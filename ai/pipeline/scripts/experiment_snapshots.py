#!/usr/bin/env python3
"""Offline metadata snapshots. Only snapshots/ is writable; producer stores stay live.

snapshot records an actual baseline/manual observation; watch follows Seoul :00/:30
and closes at 17:30, then observes (never stops) the owners' finite drain. finalize
records the cutoff if due and a separate closing row only after both owners finish.
Missing scheduled observations contain no reconstructed historical measurements.
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import math
import os
import re
import sqlite3
import stat
import time
import uuid
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from . import overnight_metrics as journal
except ImportError:
    import overnight_metrics as journal

SCHEMA = "zoop-experiment-snapshot-1"
SEOUL = ZoneInfo("Asia/Seoul")
UTC = timezone.utc
LIMIT = 128 * 1024 * 1024
MAX_FILES = 100_000
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+-]{0,199}\Z")
SECRET = re.compile(r"(?:sk-|tsk-|Bearer|ghp_|github_pat_)", re.I)
COLLECTION_KEYS = ("discovered", "fetched", "prepared", "new", "reused", "blocked", "failed", "queued", "requests", "bytes", "fresh", "backfill", "unclassifiedNew")
TOKEN_KEYS = ("inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens", "reasoningTokens")
RELATIONS = ("SAME", "DIFFERENT", "FOLLOWS", "CONFLICT", "HOLD")
FRESHNESS_KEYS = ("fresh", "backfill", "reused", "unknown")
SELECTOR_KEYS = ("schemaVersion", "roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion")


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def instant(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone_required")
    return result.astimezone(UTC)


def stamp(value):
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def now():
    return datetime.now(UTC)


def identifier(value):
    if value is None:
        return None
    if isinstance(value, str) and TOKEN.fullmatch(value) and not SECRET.search(value):
        return value
    return "redacted-" + digest(value)[:20]


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def token_count(value):
    return value if type(value) is int and value >= 0 else None


def measure(values):
    values = list(values)
    known = [number(v) for v in values if number(v) is not None]
    return {"knownN": len(known), "missingN": len(values) - len(known),
            "knownTotal": sum(known) if known else None,
            "total": sum(known) if values and len(known) == len(values) else None}


def distribution(values):
    values = list(values)
    ordered = sorted(number(v) for v in values if number(v) is not None)
    n = len(ordered)
    return {"n": n, "missingN": len(values) - n,
            "p50": ordered[math.ceil(n * .50) - 1] if n else None,
            "p95": ordered[math.ceil(n * .95) - 1] if n else None}


def usd_nano(value):
    try:
        result = Decimal(str(value)) * 1_000_000_000
        return int(result) if result.is_finite() and result >= 0 and result == result.to_integral_value() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=pairs)


def read_bytes(path, *, limit=LIMIT):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("artifact_not_bounded_regular_file")
        raw = source.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("artifact_limit")
        return raw


class Reader:
    """One pass pins the same bytes used for each projection, never a sidecar hash."""

    def __init__(self, root):
        self.root = root
        self.vector = {}
        self.issues = []
        self.cache = {}

    def read(self, path, *, required=False, parse=True, expected=None):
        path = Path(path)
        if not path.is_absolute():
            path = self.root / path
        label = str(path.relative_to(self.root)) if path.is_relative_to(self.root) else "external/" + digest(str(path))
        if len(self.vector) >= MAX_FILES:
            raise ValueError("artifact_count_limit")
        # No source/native SQLite, WAL or SHM may enter this reader, even via refs.
        if path.suffix in (".db", ".sqlite", ".sqlite3") or path.name.endswith(("-wal", "-shm")):
            self.issues.append({"code": "source_database_ref_refused", "ref": label})
            return None
        if label in self.cache:
            raw = self.cache[label]
        else:
            try:
                raw = read_bytes(path)
                self.vector[label] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
            except FileNotFoundError:
                raw = None
                self.vector[label] = {"status": "missing"}
                if required:
                    self.issues.append({"code": "artifact_missing", "ref": label})
            except (OSError, ValueError):
                raw = None
                self.vector[label] = {"status": "unreadable"}
                self.issues.append({"code": "artifact_unreadable", "ref": label})
            self.cache[label] = raw
        if raw is None:
            return None
        if expected is not None and self.vector[label]["sha256"] != expected:
            self.issues.append({"code": "artifact_pin_mismatch", "ref": label})
        if not parse:
            return self.vector[label]
        try:
            return decode(raw)
        except (ValueError, UnicodeError):
            self.issues.append({"code": "artifact_json_invalid", "ref": label})
            return None


def receipt_projection(receipt):
    """Allowlist used for legacy journal receipts and SQL-extracted provider fields."""
    usage = receipt.get("usage") or {}
    cost = receipt.get("cost") or {}
    model = receipt.get("model") or {}
    timing = receipt.get("timing") or {}
    return {"requestedModel": identifier(model.get("requested")), "reportedModel": identifier(model.get("reported")),
            "usage": {key: token_count(usage.get(key, usage.get("cachedTokens") if key == "cacheReadTokens" else None)) for key in TOKEN_KEYS},
            "estimatedNanoUsd": usd_nano(cost.get("estimatedUsd")),
            "durationMs": number(timing.get("durationMs")) if timing.get("provenance") == "http-transport-monotonic" else None,
            "usageRejected": bool(cost.get("usageRejected"))}


def read_budget(path):
    """WAL-aware normal readonly transaction, SELECTs only, no Budget constructor.

    Do not use immutable=1: it silently ignores the live WAL. The digest is over
    committed metadata rows from ONE transaction, not over mutable DB/WAL bytes.
    json_extract projects receipt metadata inside SQLite; provider bodies and
    arbitrary errors are not selected into Python or snapshot output.
    """
    empty = {"status": "missing", "reservations": None, "providerAttempts": None, "sets": None, "caps": {}, "funding": None, "rawVerifier": None}
    if not path.exists():
        return empty
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        return {**empty, "status": "unreadable"}
    if path.with_name(path.name + "-wal").exists() and not path.with_name(path.name + "-shm").exists():
        return {**empty, "status": "wal_shared_memory_missing_no_recovery"}
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=.2, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"meta", "reservations"} <= tables:
                return {**empty, "status": "schema_missing"}
            caps = dict(db.execute("SELECT key,value FROM meta WHERE key IN ('max_nano','max_calls','bucket_shared','bucket_personal')"))
            reservations = [dict(r) for r in db.execute("SELECT attempt_id,stage,recipient,state,reserved_nano,charged_nano,usage_known,created_at,updated_at FROM reservations ORDER BY attempt_id")]
            funding = [dict(r) for r in db.execute("SELECT attempt_id,account_role,bucket FROM reservation_funding ORDER BY attempt_id")] if "reservation_funding" in tables else None
            sets = [dict(r) for r in db.execute("SELECT set_id,state,admitted_at,finished_at FROM admitted_sets ORDER BY set_id")] if "admitted_sets" in tables else None
            attempts = None
            if "provider_attempts" in tables:
                attempts = []
                for row in db.execute("""SELECT attempt_id,logical_id,ordinal,profile,state,
                    json_extract(receipt,'$.usage') AS usage,
                    json_extract(receipt,'$.cost') AS cost,
                    json_extract(receipt,'$.model') AS model,
                    json_extract(receipt,'$.timing') AS timing,
                    json_extract(CASE WHEN json_valid(json_extract(receipt,'$.http.bodyText'))
                        THEN json_extract(receipt,'$.http.bodyText') ELSE '{}' END,
                        '$.usage.prompt_tokens_details.cache_write_tokens') AS raw_cache_write,
                    json_extract(CASE WHEN json_valid(json_extract(receipt,'$.http.bodyText'))
                        THEN json_extract(receipt,'$.http.bodyText') ELSE '{}' END,
                        '$.prompt_cache_retention') AS raw_cache_retention
                    FROM provider_attempts ORDER BY attempt_id"""):
                    item = dict(row)
                    projected = receipt_projection({key: json.loads(item.pop(key) or "{}") for key in ("usage", "cost", "model", "timing")})
                    raw_write = token_count(item.pop("raw_cache_write"))
                    if projected["usage"]["cacheWriteTokens"] is None and not projected["usageRejected"]:
                        projected["usage"]["cacheWriteTokens"] = raw_write
                    projected["cacheRetention"] = identifier(item.pop("raw_cache_retention"))
                    attempts.append({**{key: identifier(value) if isinstance(value, str) else value for key, value in item.items()}, **projected})
            raw_verifier = None
            if {"provider_attempts", "provider_invocations"} <= tables:
                raw_verifier = []
                for row in db.execute("""SELECT p.attempt_id, i.stage, a.key,
                    json_extract(a.value,'$.choice') AS choice,
                    json_extract(a.value,'$.confidence') AS confidence,
                    json_extract(a.value,'$.probabilities') AS probabilities
                    FROM provider_attempts p JOIN provider_invocations i USING(logical_id),
                    json_each(CASE WHEN json_valid(json_extract(p.receipt,'$.http.bodyText'))
                        THEN json_extract(json_extract(p.receipt,'$.http.bodyText'),'$.answers')
                        ELSE '{}' END) a
                    WHERE i.stage LIKE 'verify-%' ORDER BY p.attempt_id,a.key"""):
                    probabilities = json.loads(row["probabilities"] or "{}")
                    choice = row["choice"]
                    raw_verifier.append({"attemptId": identifier(row["attempt_id"]), "stage": identifier(row["stage"]),
                        "questionId": identifier(row["key"]), "choice": identifier(choice),
                        "confidence": number(row["confidence"]), "selectedProbability": number(probabilities.get(choice))})
            db.execute("ROLLBACK")
        for row in reservations:
            for key in ("attempt_id", "stage", "recipient"):
                row[key] = identifier(row[key])
        return {"status": "complete", "caps": caps, "reservations": reservations,
                "providerAttempts": attempts, "funding": funding, "sets": sets, "rawVerifier": raw_verifier}
    except (sqlite3.Error, ValueError, TypeError, OSError):
        return {**empty, "status": "transaction_unavailable"}


def journal_events(reader):
    pin = reader.read("events.jsonl", required=True, parse=False)
    if not pin:
        return [], {"status": "missing", "invalidN": None, "partialTail": None}
    raw = reader.cache["events.jsonl"]
    events, seen, invalid = [], {}, 0
    partial = None
    offset = 0
    for line in raw.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            partial = {"bytes": len(line), "sha256": hashlib.sha256(line).hexdigest()}
            break
        try:
            event = journal._decode(line, offset)
            old = seen.get(event["eventId"])
            if old is not None and old != event:
                raise ValueError("event_conflict")
            if old is None:
                events.append(event)
                seen[event["eventId"]] = event
        except (ValueError, UnicodeError):
            invalid += 1
        offset += len(line)
    return events, {"status": "incomplete" if invalid or partial else "complete", "invalidN": invalid, "partialTail": partial}


def money_metrics(budget, events, *, journal_complete=True):
    observations = {}
    conflicts = set()
    rank = {None: 0, "reused": 0, "started": 1, "unknown": 1, "received": 2, "released": 2}
    for event in events:
        if event["kind"] != "attempt" or event["attemptState"] == "reused":
            continue
        key = event["attemptId"]
        previous = observations.get(key)
        if previous and previous["attemptState"] == event["attemptState"] == "received" and any(previous[k] != event[k] for k in ("usage", "cost", "requestedModel", "reportedModel")):
            conflicts.add(key)
        if previous is None or rank[event["attemptState"]] >= rank[previous["attemptState"]]:
            observations[key] = event
    reservations = budget["reservations"]
    physical = budget["providerAttempts"]
    ledger_ids = {r["attempt_id"] for r in reservations} if reservations is not None else None
    physical_ids = {r["attempt_id"] for r in physical} if physical is not None else None
    journal_ids = set(observations)
    all_ids = (ledger_ids or set()) | (physical_ids or set()) | journal_ids
    by_physical = {r["attempt_id"]: r for r in physical or []}
    by_reservation = {r["attempt_id"]: r for r in reservations or []}
    by_funding = {r["attempt_id"]: r for r in budget["funding"] or []}
    attempts = []
    for key in sorted(all_ids):
        event = observations.get(key)
        row = by_physical.get(key)
        reserve = by_reservation.get(key)
        projection = receipt_projection({"usage": event["usage"], "model": {"requested": event["requestedModel"], "reported": event["reportedModel"]}}) if event else receipt_projection({})
        if event:
            projection["estimatedNanoUsd"] = event["cost"]["estimatedNanoUsd"]
            projection["durationMs"] = event["durationMs"] if event["durationProvenance"] == "http_request" else None
        if row:
            projection = {k: v for k, v in row.items() if k not in ("attempt_id", "logical_id", "ordinal", "profile", "state")}
        if row and event and row["state"] == event["attemptState"] == "received":
            if any(row["usage"].get(k) != receipt_projection({"usage": event["usage"]})["usage"].get(k) for k in ("inputTokens", "outputTokens", "cacheReadTokens", "reasoningTokens")):
                conflicts.add(key)
        if key in conflicts:
            projection["usage"] = {k: None for k in TOKEN_KEYS}
            projection["estimatedNanoUsd"] = None
        attempts.append({"attemptId": identifier(key), "state": row["state"] if row else event["attemptState"] if event else "unknown",
                         "cohort": identifier(event["cohort"]) if event else None,
                         "profile": row["profile"] if row else None,
                         "bucket": identifier(by_funding.get(key, {}).get("bucket")),
                         "accountRole": identifier(by_funding.get(key, {}).get("account_role")),
                         "reservationState": reserve["state"] if reserve else None, **projection})
    def aggregate(items):
        return {"attempts": len(items), "states": dict(Counter(i["state"] for i in items)),
                "usage": {k: measure(i["usage"].get(k) for i in items) for k in TOKEN_KEYS},
                "knownUsageEstimatedNanoUsd": measure(i["estimatedNanoUsd"] for i in items),
                "usageRejectedN": sum(i["usageRejected"] for i in items),
                "cacheRetentionCounts": dict(Counter(i.get("cacheRetention") or "unknown" for i in items)),
                "httpDurationMs": distribution(i["durationMs"] for i in items)}
    groups = defaultdict(list)
    for item in attempts:
        groups[(item["cohort"], item["profile"], item["requestedModel"], item["reportedModel"], item["bucket"], item["accountRole"])].append(item)
    monetary = {}
    for bucket in ("total", "shared", "personal"):
        selected = reservations if bucket == "total" else ([r for r in reservations if by_funding.get(r["attempt_id"], {}).get("bucket") == bucket] if reservations is not None and budget["funding"] is not None else None)
        cap = budget["caps"].get("max_nano" if bucket == "total" else "bucket_" + bucket)
        if selected is None:
            monetary[bucket] = {k: None for k in ("chargedNanoUsd", "reservedNanoUsd", "unknownExposureNanoUsd", "knownUsageNanoUsd", "remainingNanoUsd", "calls")}
        else:
            charged = sum(r["charged_nano"] for r in selected if r["state"] != "released")
            monetary[bucket] = {"chargedNanoUsd": charged,
                "reservedNanoUsd": sum(r["charged_nano"] for r in selected if r["state"] == "reserved"),
                "unknownExposureNanoUsd": sum(r["charged_nano"] for r in selected if not r["usage_known"] and r["state"] != "released"),
                "knownUsageNanoUsd": sum(r["charged_nano"] for r in selected if r["usage_known"]),
                "remainingNanoUsd": max(0, cap - charged) if cap is not None else None,
                "calls": sum(r["state"] != "released" for r in selected)}
        monetary[bucket]["maxNanoUsd"] = cap
    def gap(left, right):
        return len(left - right) if left is not None and right is not None else None
    union = aggregate(attempts)
    if not attempts and reservations is None and physical is None and not journal_complete:
        union["attempts"] = None
    return {"status": budget["status"], "journalAttempts": len(journal_ids) if journal_complete else None,
            "observedJournalAttempts": len(journal_ids),
            "ledgerAttempts": len(ledger_ids) if ledger_ids is not None else None,
            "physicalProviderAttempts": len(physical_ids) if physical_ids is not None else None,
            "ledgerMissingJournal": gap(ledger_ids, journal_ids), "journalMissingLedger": gap(journal_ids, ledger_ids),
            "physicalMissingJournal": gap(physical_ids, journal_ids), "physicalMissingLedger": gap(physical_ids, ledger_ids),
            "ledgerWithoutPhysicalRecord": gap(ledger_ids, physical_ids),
            "conflictingAttempts": len(conflicts), "attemptIdDigest": digest(sorted(all_ids)),
            "union": union, "rawVerifier": budget["rawVerifier"],
            "models": [{**dict(zip(("cohort", "profile", "requestedModel", "reportedModel", "bucket", "accountRole"), key)), **aggregate(items)} for key, items in sorted(groups.items(), key=lambda x: encoded(x[0]))],
            "money": monetary, "admittedSetsRemaining": sum(s["state"] == "admitted" for s in budget["sets"]) if budget["sets"] is not None else None,
            "setStates": dict(Counter(s["state"] for s in budget["sets"])) if budget["sets"] is not None else None,
            "invoiceNanoUsd": None, "semantics": "reservation_included_in_charge; unknown_exposure_overlaps_reservation; estimates_not_invoice"}


def safe_ids(value, prefix=""):
    """Only runtime/prompt/version identity leaves, never payload/config/key values."""
    out = {}
    if not isinstance(value, dict):
        return out
    for key, item in value.items():
        if key.lower() in ("identity", "promptversion", "promptdigest", "schemaversion", "model", "version", "bindingidentity") and isinstance(item, str):
            out[prefix + identifier(key)] = identifier(item)
        elif isinstance(item, dict) and key.lower() not in ("funding", "credentials", "headers", "payload", "catalogue", "runconfig"):
            out.update(safe_ids(item, prefix + identifier(key) + "."))
    return out


def item_freshness(index, kind, item):
    """Producer-assigned record labels, never the enclosing batch/window label."""
    metadata = ((index.get("itemFreshness") or {}).get(item.get("recordPath")) or {}) if kind == "private" else item
    category = metadata.get("freshness")
    return {"freshness": category if category in FRESHNESS_KEYS else "unknown",
            "publicationDay": identifier(metadata.get("publicationDay"))}


def selector_metadata(value):
    if not isinstance(value, dict):
        return None
    return {key: number(value[key]) if key in ("page", "ordinal") else identifier(value[key])
            for key in SELECTOR_KEYS if key in value}


def file_reference(reader, path, declared=None, *, observe=False):
    """Retain resolvable file references, not their payloads or configuration."""
    if path is None:
        return None
    if not isinstance(path, str) or not path or "\x00" in path or "\n" in path:
        reader.issues.append({"code": "reference_path_invalid"})
        return {"path": None, "declaredSha256": identifier(declared), "status": "invalid"}
    absolute = Path(path)
    if not absolute.is_absolute():
        absolute = reader.root / absolute
    label = str(absolute.relative_to(reader.root)) if absolute.is_relative_to(reader.root) else "external/" + digest(str(absolute))
    if observe:
        reader.read(absolute, required=True, parse=False, expected=declared)
    observed = reader.vector.get(label, {})
    return {"path": str(absolute), "vectorKey": label, "declaredSha256": identifier(declared),
            "observedSha256": observed.get("sha256"), "bytes": observed.get("bytes"),
            "status": "observed" if observed.get("sha256") else observed.get("status", "unobserved")}


def reference_sets(reader, index, queue):
    """Self-contained allowlisted membership sets survive mutable pointer updates."""
    corpus = []
    for kind, field, path_key, hash_key in (
        ("native", "nativeItems", "exportPath", "fileSha256"),
        ("private", "privateItems", "recordPath", "recordSha256"),
    ):
        for item in (index or {}).get(field, []):
            corpus.append({
                "kind": kind, "sourceItemSha256": digest(item),
                **{key: identifier(item.get(key)) for key in ("sourceId", "sourceScopeId", "sourceKind", "planId", "newsId",
                                                            "privateId", "documentId", "rawVersion", "documentVersion")},
                "artifact": file_reference(reader, item.get(path_key), item.get(hash_key)),
                "observation": selector_metadata(item.get("observation")),
                **item_freshness(index, kind, item),
                "fileRefs": [file_reference(reader, ref.get("path"), ref.get("sha256")) for ref in item.get("fileRefs", [])],
            })
    queued = []
    for key, entry in (queue or {}).items():
        unit = entry.get("unit") or {}
        queued.append({
            "queueKey": identifier(key), "sourceEntrySha256": digest(entry),
            **{name: identifier(entry.get(name)) for name in ("state", "cohort", "queueKind", "setId", "unitDigest")},
            **{name: identifier(unit.get(name, entry.get(name))) for name in ("unitId", "sourceId", "scopeId")},
            "observation": selector_metadata(unit.get("observation")),
            "export": file_reference(reader, unit.get("export"), unit.get("exportSha256"), observe=True),
            "originalPins": [file_reference(reader, pin.get("path"), pin.get("sha256"), observe=True) for pin in unit.get("originalPins", [])],
        })
    result = {
        "schemaVersion": "zoop-experiment-reference-sets-1",
        "corpus": {"status": "observed" if index is not None else "missing",
                   "indexSha256": reader.vector.get("collection/INDEX.json", {}).get("sha256"),
                   "checkpointId": identifier((index or {}).get("checkpointId")),
                   "members": corpus if index is not None else None},
        "queue": {"status": "observed" if queue is not None else "missing",
                  "queueSha256": reader.vector.get("control/queue.json", {}).get("sha256"),
                  "members": queued if queue is not None else None},
    }
    for name in ("corpus", "queue"):
        result[name]["sha256"] = digest(result[name])
    return result


def collection_metrics(reader, index, ledger, queue):
    rows = index.get("sourceMatrix") if isinstance(index, dict) else None
    if rows is not None:
        reader.vector["collection:sourceMatrix"] = {"sha256": digest(rows), "rows": len(rows)}
    prepared_backends = defaultdict(Counter)
    freshness_counts = defaultdict(Counter)
    refs = []
    for kind, field, hash_key in (("native", "nativeItems", "fileSha256"), ("private", "privateItems", "recordSha256")):
        for item in (index or {}).get(field, []):
            path = item.get("exportPath" if kind == "native" else "recordPath")
            if not path:
                reader.issues.append({"code": "committed_record_ref_missing"})
                continue
            for ref in item.get("fileRefs", []):
                if ref.get("path") in (item.get("exportPath"), item.get("recordPath")):
                    reader.read(ref["path"], required=True, parse=False, expected=ref.get("sha256"))
            value = reader.read(path, required=True, parse=kind == "private", expected=item.get(hash_key))
            backend = "native" if kind == "native" else identifier((value or {}).get("extractionBackend", "native")) if value is not None else "unknown"
            source = identifier(item.get("sourceId"))
            freshness = item_freshness(index, kind, item)
            freshness_counts[source][freshness["freshness"]] += 1
            prepared_backends[source][backend] += 1
            refs.append({"sourceId": source, "kind": kind, "backend": backend,
                         "declaredSha256": identifier(item.get(hash_key)), "referenceId": digest(str(path)),
                         "documentVersion": identifier(item.get("documentVersion")), "recordId": identifier(item.get("privateId")), **freshness})
    queue_rows = list(queue.values()) if isinstance(queue, dict) else None
    output, cohorts = [], []
    for row in rows or []:
        source = identifier(row.get("sourceId"))
        aliases = set(row.get("adapterSourceIds", [])) | {row.get("sourceId"), row.get("adapterSourceId")}
        aliases.discard(None)
        selected = [e for e in queue_rows if (e.get("unit") or {}).get("sourceId", e.get("sourceId")) in aliases] if queue_rows is not None else None
        counts = row.get("counts") or {}
        values = {key: number(counts.get("newCollection" if key == "new" else key)) for key in COLLECTION_KEYS}
        values["queued"] = sum(e.get("state") == "queued" for e in selected) if selected is not None else None
        backends, freshness = Counter(), Counter()
        for alias in aliases:
            backends.update(prepared_backends[identifier(alias)])
            freshness.update(freshness_counts[identifier(alias)])
        output.append({"sourceId": source, "status": identifier(row.get("status")), "counts": values,
                       "attempted": row.get("attemptStatus") == "attempted" if row.get("attemptStatus") else None,
                       "analysisAdmitted": any(e.get("setId") for e in selected) if selected is not None else None,
                       "itemFreshnessCounts": {key: freshness[key] for key in FRESHNESS_KEYS},
                       "preparedBackendCounts": dict(backends), "backendBasis": "committed_records_not_requests"})
        for part in row.get("coverage", []):
            cohorts.append({"sourceId": source, "cohort": identifier(part.get("freshness")), "planId": identifier(part.get("planId")),
                            "counts": {key: number((part.get("counts") or {}).get("newCollection" if key == "new" else key)) for key in COLLECTION_KEYS},
                            "fetchedCountBasis": identifier(part.get("fetchedCountBasis"))})
    totals = {key: measure(r["counts"][key] for r in output) for key in COLLECTION_KEYS}
    attempts = []
    for plan_id, record in (ledger or {}).get("plans", {}).items():
        summary = record.get("summary") or {}
        backends = summary.get("extractionBackendCounts")
        attempts.append({"planId": identifier(plan_id),
                         "backendCounts": {identifier(k): number(v) for k, v in backends.items()} if isinstance(backends, dict) else None,
                         "state": identifier(record.get("status"))})
    observations = (index or {}).get("observations")
    cli = distribution(o.get("durationMs") if o.get("durationProvenance") == "cli_wall" else None for o in observations or [])
    http = distribution(o.get("durationMs") for o in observations or [] if o.get("durationProvenance") == "http_request")
    http["missingN"] = max(0, totals["requests"]["total"] - http["n"]) if totals["requests"]["total"] is not None else None
    return {"status": "observed" if rows is not None else "missing", "sources": output, "byCohort": cohorts,
            "itemFreshnessCounts": {key: sum(counts[key] for counts in freshness_counts.values()) for key in FRESHNESS_KEYS} if index is not None else None,
            "freshnessSemantics": "exact_producer_item_labels; source_counts_fresh_backfill_are_new_only; batch_selection_is_not_item_freshness",
            "totals": totals, "sourceStates": dict(Counter(r["status"] for r in output)),
            "coverage": {"offered": len(rows) if rows is not None else None,
                         "attempted": measure(int(r["attempted"]) if r["attempted"] is not None else None for r in output),
                         "analysisAdmitted": measure(int(r["analysisAdmitted"]) if r["analysisAdmitted"] is not None else None for r in output)},
            "backendAttemptsByPlan": attempts, "preparedBackendCounts": dict(sum(prepared_backends.values(), Counter())),
            "records": refs, "cliDurationMs": cli, "httpDurationMs": http,
            "durationObservationN": len(observations) if observations is not None else None,
            "sourceSearchRankingIsTruth": False}


def analysis_metrics(reader, queue, pins):
    entries = list(queue.values()) if isinstance(queue, dict) else None
    groups, versions, unit_rows = defaultdict(list), {}, []
    unique_nodes, unique_edges = set(), set()
    graph_identity_complete = True
    graph_missing = 0
    for entry in entries or []:
        unit = entry.get("unit") or {}
        unit_id, cohort = unit.get("unitId"), entry.get("cohort")
        row = {"unitId": identifier(unit_id), "cohort": identifier(cohort), "queueKind": identifier(entry.get("queueKind", "ordinary")),
               "state": identifier(entry.get("state")), "sourceId": identifier(unit.get("sourceId", entry.get("sourceId"))),
               "eventCandidates": None, "topicCandidates": None, "comparisons": None,
               "effectiveRelations": None, "relations": None, "rawVerdicts": None, "confidenceGate": None,
               "summaries": None, "runtimeIds": {}}
        if unit_id and cohort and TOKEN.fullmatch(unit_id) and TOKEN.fullmatch(cohort):
            directory = Path("analysis") / cohort / unit_id
            s2 = reader.read(directory / "s2-result.json")
            s3 = reader.read(directory / ("s3-fallback-result.json" if entry.get("stageProfiles", {}).get("s3") == "deepseek" and cohort == "mixed-luna-deepseek" else "s3-result.json"))
            for name in ("unit.json", "comparison-coverage.json", "summary-runtime.json", "summary-queue.json", "summary-outcomes.json"):
                artifact = reader.read(directory / name)
                if name == "summary-runtime.json" and artifact:
                    row["runtimeIds"].update(safe_ids(artifact, "summary."))
                if name == "comparison-coverage.json" and artifact:
                    row["comparisonCoverage"] = {k: number(artifact.get(k)) for k in ("eligibleBeforeDedupAndBounds", "selectedEvents", "selectedMembers")}
                if name == "summary-outcomes.json" and isinstance(artifact, dict):
                    row["summaries"] = dict(Counter(identifier(v) for v in artifact.values()))
            for stage, value in (("s2", s2), ("s3", s3)):
                if value is not None:
                    command = reader.read(directory / (stage + "-result.command.json"), required=True)
                    if command is None or command.get("exitCode") != 0:
                        reader.issues.append({"code": "analysis_result_not_successfully_reaped", "unitId": identifier(unit_id), "stage": stage})
                    row["runtimeIds"].update(safe_ids(value.get("binding", {}), stage + "."))
            if isinstance(s2, dict):
                counts = s2.get("counts", {})
                row["eventCandidates"] = number((counts.get("eventCandidates") or {}).get("total"))
                row["topicCandidates"] = number(counts.get("topicCandidates"))
                row["comparisons"] = number(counts.get("comparisons"))
                relations = counts.get("effectiveRelations")
                if isinstance(relations, dict):
                    row["effectiveRelations"] = {key: number(relations.get(key)) for key in RELATIONS}
            if isinstance(s3, dict) and isinstance(s3.get("relations"), list):
                candidates = s3["relations"]
                row["relations"] = dict(Counter(identifier((r.get("eligibility") or {}).get("status")) for r in candidates))
                claims = [c for r in candidates for h in r.get("history", []) if h.get("kind") == "verdict" for c in h.get("claims") or []]
                row["rawVerdicts"] = dict(Counter(identifier(c["rawVerdict"]) for c in claims if c.get("rawVerdict") is not None)) if any("rawVerdict" in c for c in claims) else None
                row["effectiveClaimVerdicts"] = dict(Counter(identifier(c.get("verdict")) for c in claims))
                row["confidenceGate"] = {"observedN": sum("confidence" in c or "probability" in c for c in claims),
                                         "changedN": sum(c.get("rawVerdict") != c.get("verdict") for c in claims if c.get("rawVerdict") is not None) if any(c.get("rawVerdict") is not None for c in claims) else None,
                                         "missingRawN": sum(c.get("rawVerdict") is None for c in claims)}
            graph = entry.get("graph") or {}
            if graph.get("status") == "projected":
                readback = reader.read(directory / "graph-read.json", required=True)
                command = reader.read(directory / "graph-read.command.json", required=True)
                if (not isinstance(readback, dict) or not command or command.get("exitCode") != 0 or
                    readback.get("versionId") != graph.get("versionId") or readback.get("publication") != "not-published" or
                    readback.get("verification", {}).get("marker") != "matched" or readback.get("delivery", {}).get("status") != "current"):
                    reader.issues.append({"code": "graph_readback_not_committed", "unitId": identifier(unit_id)})
                    graph_missing += 1
                    graph_identity_complete = False
                else:
                    verification = readback["verification"]
                    version_id = identifier(readback["versionId"])
                    version = {"versionId": version_id, "nodes": number(verification.get("nodes")), "edges": number(verification.get("edges")),
                               "graphDigest": identifier(verification.get("graphDigest")),
                               "payloadDigest": identifier(readback.get("digests", {}).get("payload")), "publicUse": False,
                               "readbackSha256": reader.vector[str(directory / "graph-read.json")]["sha256"]}
                    if version_id in versions and versions[version_id] != version:
                        reader.issues.append({"code": "graph_version_conflict", "versionId": version_id})
                        graph_missing += 1
                        graph_identity_complete = False
                    versions[version_id] = version
                    body = readback.get("graph") or {}
                    if not isinstance(body.get("nodes"), list) or not isinstance(body.get("edges"), list):
                        graph_identity_complete = False
                    else:
                        unique_nodes.update(digest((n.get("kind"), n.get("id"))) for n in body["nodes"])
                        # A version-local edge ID is NOT a globally unique relation identity.
                        for edge in body["edges"]:
                            if all(key in edge for key in ("type", "subject", "object")):
                                unique_edges.add(digest({k: edge[k] for k in ("type", "subject", "object")}))
                            else:
                                graph_identity_complete = False
        if row["summaries"] is None and isinstance(entry.get("summaries"), dict):
            row["summaries"] = {identifier(k): number(v) for k, v in entry["summaries"].get("counts", {}).items()}
        if row["summaries"] is not None:
            statuses = row["summaries"]
            row["summaries"] = {key: statuses.get(key, 0) for key in ("available", "verifier-hold", "verifier-reject")}
            row["summaries"]["error"] = sum(value for key, value in statuses.items() if key not in row["summaries"] and value is not None)
        unit_rows.append(row)
        groups[(row["cohort"], row["queueKind"])].append(row)
    def aggregate(items):
        return {"units": len(items) if entries is not None else None, "states": dict(Counter(i["state"] for i in items)),
                **{k: measure(i[k] for i in items) for k in ("eventCandidates", "topicCandidates", "comparisons")},
                "effectiveRelations": {k: measure(i["effectiveRelations"].get(k) if i["effectiveRelations"] is not None else None for i in items) for k in RELATIONS},
                "relationEligibility": {k: measure(i["relations"].get(k, 0) if i["relations"] is not None else None for i in items) for k in ("eligible", "hold", "reject", "pending")},
                "privateSummary": {k: measure(i["summaries"].get(k, 0) if i["summaries"] is not None else None for i in items) for k in ("available", "verifier-hold", "verifier-reject", "error")}}
    return {"status": "observed" if entries is not None else "missing", "totals": aggregate(unit_rows), "units": unit_rows,
            "byCohort": [{"cohort": key[0], "queueKind": key[1], **aggregate(items)} for key, items in groups.items()],
            "runtimeIds": safe_ids((pins or {}).get("pins", pins or {}).get("runtimeBindings", {})),
            "graph": {"semantics": "logical_immutable_version_manifest_not_database_copy", "publicUse": False,
                      "versions": list(versions.values()), "observedVersions": len(versions) if entries is not None else None,
                      "missingReadbacks": graph_missing, "completedVersions": len(versions) if entries is not None and not graph_missing else None,
                      "nonemptyVersions": sum(v["nodes"] > 0 and v["edges"] > 0 for v in versions.values()) if entries is not None and not graph_missing and all(v["nodes"] is not None and v["edges"] is not None for v in versions.values()) else None,
                      "versionLocalNodes": sum(v["nodes"] for v in versions.values()) if entries is not None and not graph_missing and all(v["nodes"] is not None for v in versions.values()) else None,
                      "versionLocalEdges": sum(v["edges"] for v in versions.values()) if entries is not None and not graph_missing and all(v["edges"] is not None for v in versions.values()) else None,
                      "uniqueNodes": len(unique_nodes) if graph_identity_complete and entries is not None else None,
                      "uniqueEndpointTypeEdges": len(unique_edges) if graph_identity_complete and entries is not None else None,
                      "uniqueEdgeSemantics": "endpoint_type_identity_not_version_local_edge_ids"}}


def lock_owner(path):
    """Probe an EXISTING owner lock without waiting, creating it, or signaling PIDs."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unknown"
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return "active"
        return "absent"
    finally:
        os.close(fd)


def capture_pass(root):
    reader = Reader(root)
    index = reader.read("collection/INDEX.json", required=True)
    reader.read("run-config.json")
    if index is not None:
        reader.vector["collection:checkpoint"] = {k: identifier(index.get(k)) for k in ("checkpointId", "publishedAt", "generatedAt")}
    ledger = reader.read("collection/LEDGER.json", required=True)
    reader.read("collection/SOURCE_ADMISSION.json")
    queue = reader.read("control/queue.json", required=True)
    pins = reader.read("control/CHECK.json", required=True)
    final = reader.read("control/RUN.json")
    events, integrity = journal_events(reader)
    budget = read_budget(root / "modelbudget/live-budget.sqlite3")
    reader.vector["budget:committed-metadata-transaction"] = {"sha256": digest(budget), "status": budget["status"]}
    collection = collection_metrics(reader, index, ledger, queue)
    analysis = analysis_metrics(reader, queue, pins)
    references = reference_sets(reader, index, queue)
    money = money_metrics(budget, events, journal_complete=integrity["status"] == "complete")
    policies = []
    for bindings in (pins or {}).get("pins", pins or {}).get("runtimeBindings", {}).values():
        for binding in bindings.values():
            policy = binding.get("verifier", {}).get("policy", {})
            if number(policy.get("choiceProbability")) is not None and number(policy.get("choiceConfidence")) is not None:
                policies.append((policy["choiceProbability"], policy["choiceConfidence"]))
    thresholds = policies[0] if policies and all(p == policies[0] for p in policies) else None
    raw_verifier = money["rawVerifier"]
    money["verifierGateObservations"] = {
        "rawChoices": dict(Counter(r["choice"] for r in raw_verifier)) if raw_verifier is not None else None,
        "observedN": len(raw_verifier) if raw_verifier is not None else None,
        "belowPinnedThresholdN": sum(r["confidence"] < thresholds[1] or r["selectedProbability"] < thresholds[0]
            for r in raw_verifier if r["confidence"] is not None and r["selectedProbability"] is not None) if thresholds and raw_verifier is not None else None,
        "missingProbabilityOrConfidenceN": sum(r["confidence"] is None or r["selectedProbability"] is None for r in raw_verifier) if raw_verifier is not None else None,
        "pinnedThresholds": {"choiceProbability": thresholds[0], "choiceConfidence": thresholds[1]} if thresholds else None,
        "semantics": "raw_provider_choices_and_pinned_numeric_gate_not_reconstructed_effective_verdicts"}
    owners = {"collection": {"finished": bool((ledger or {}).get("endedAt")) and (index or {}).get("status") == "finished",
                              "lock": lock_owner(root / "collection/.controller.lock")},
              "analysis": {"finished": bool((final or {}).get("finishedAt")), "lock": lock_owner(root / "control/controller.lock")}}
    owners["remainingAdmittedSets"] = money["admittedSetsRemaining"]
    owners["drained"] = all(owners[key]["finished"] and owners[key]["lock"] != "active" for key in ("collection", "analysis")) and money["admittedSetsRemaining"] == 0
    reader.vector["owners:observed-status"] = {"sha256": digest(owners)}
    if integrity["status"] != "complete":
        reader.issues.append({"code": "journal_incomplete"})
    if budget["status"] != "complete":
        reader.issues.append({"code": "budget_incomplete"})
    for key in ("ledgerMissingJournal", "journalMissingLedger", "physicalMissingJournal", "physicalMissingLedger", "conflictingAttempts"):
        if money[key]:
            reader.issues.append({"code": key, "n": money[key]})
    latest = {}
    for event in events:
        if event["kind"] in ("phase", "record", "batch"):
            latest[(event["cohort"], event["kind"], event["phase"], event["unitId"], event["sourceId"])] = event
    duration_groups = defaultdict(list)
    for event in latest.values():
        duration_groups[(event["cohort"], event["phase"], event["durationProvenance"])].append(event["durationMs"])
    metrics = {"schemaVersion": SCHEMA, "collection": collection, "analysis": analysis, "providers": money,
               "referenceSets": references,
               "durations": [{"cohort": identifier(k[0]), "phase": identifier(k[1]), "provenance": k[2], **distribution(v)} for k, v in duration_groups.items()],
               "journal": integrity, "owners": owners,
               "quality": {"accuracy": None, "falseMerge": None, "overHold": None, "goldN": None, "status": "unmeasured_without_gold"},
               "networkCalls": 0, "publicUse": False}
    metrics["cumulative"] = counters(metrics)
    return metrics, reader.vector, reader.issues


def counters(metrics):
    out = {}
    collection, analysis, providers = (metrics[k] for k in ("collection", "analysis", "providers"))
    for key, value in collection["totals"].items():
        out["collection.total." + key] = value["total"]
    for source in collection["sources"]:
        for key, value in source["counts"].items():
            out["collection.source." + str(source["sourceId"]) + "." + key] = value
        for key, value in source["preparedBackendCounts"].items():
            out["collection.source." + str(source["sourceId"]) + ".backend." + key] = value
        for key, value in source["itemFreshnessCounts"].items():
            out["collection.source." + str(source["sourceId"]) + ".itemFreshness." + key] = value
    for key in FRESHNESS_KEYS:
        out["collection.itemFreshness." + key] = collection["itemFreshnessCounts"][key] if collection["itemFreshnessCounts"] is not None else None
    for cohort in collection["byCohort"]:
        for key, value in cohort["counts"].items():
            out["collection.cohort." + str(cohort["sourceId"]) + "." + str(cohort["cohort"]) + "." + str(cohort["planId"]) + "." + key] = value
    for key, value in collection["preparedBackendCounts"].items():
        out["collection.backend." + key] = value
    for key in ("offered",):
        out["coverage." + key] = collection["coverage"][key]
    for key in ("attempted", "analysisAdmitted"):
        out["coverage." + key] = collection["coverage"][key]["total"]
    out["analysis.units"] = analysis["totals"]["units"] if analysis["status"] == "observed" else None
    for key in ("eventCandidates", "topicCandidates", "comparisons"):
        out["analysis." + key] = analysis["totals"][key]["total"]
    for key in ("effectiveRelations", "relationEligibility", "privateSummary"):
        for label, value in analysis["totals"][key].items():
            out["analysis." + key + "." + label] = value["total"]
    for cohort in analysis["byCohort"]:
        prefix = "analysis.cohort." + str(cohort["cohort"]) + "." + str(cohort["queueKind"]) + "."
        out[prefix + "units"] = cohort["units"]
        for key in ("eventCandidates", "topicCandidates", "comparisons"):
            out[prefix + key] = cohort[key]["total"]
    for model in providers["models"]:
        prefix = "providers.model." + digest([model[k] for k in ("cohort", "profile", "requestedModel", "reportedModel", "bucket", "accountRole")])[:20] + "."
        out[prefix + "attempts"] = model["attempts"]
        for key in TOKEN_KEYS:
            out[prefix + key] = model["usage"][key]["total"]
    for key, value in analysis["graph"].items():
        if type(value) is int or value is None:
            out["graph." + key] = value
    for key in ("journalAttempts", "ledgerAttempts", "physicalProviderAttempts"):
        out["providers." + key] = providers[key]
    for key in TOKEN_KEYS:
        out["tokens." + key] = providers["union"]["usage"][key]["total"]
    for bucket, values in providers["money"].items():
        for key, value in values.items():
            out["money." + bucket + "." + key] = value
    return out


def capture(root, *, repeats=3, clock=now):
    started = clock()
    previous = None
    changed = []
    for attempt in range(repeats + 1):
        metrics, vector, issues = capture_pass(root)
        if previous is not None:
            changed = sorted(k for k in vector.keys() | previous.keys() if vector.get(k) != previous.get(k))
            if not changed:
                break
        previous = vector
    stable = not changed and attempt > 0
    status = "complete" if stable and not issues else "incomplete" if stable else "stale"
    return {"metrics": metrics, "vector": vector, "issues": issues,
            "status": status, "stable": stable, "passes": attempt + 1, "changed": changed,
            "startedAt": stamp(started), "endedAt": stamp(clock()), "globallyAtomic": False}


def delta(current, previous):
    if previous is None:
        return {"values": {k: None for k in current}, "gaugeChanges": {}, "issues": [], "status": "baseline"}
    values, gauges, issues = {}, {}, []
    for key in sorted(current.keys() | previous.keys()):
        before, after = previous.get(key), current.get(key)
        if before is None or after is None:
            values[key] = None
        elif key.endswith((".queued", ".remainingNanoUsd", ".reservedNanoUsd", ".unknownExposureNanoUsd", ".chargedNanoUsd")):
            gauges[key] = after - before
            values[key] = None
        elif after < before:
            values[key] = None
            issues.append({"metric": key, "code": "counter_decrease_or_reset", "before": before, "after": after})
        else:
            values[key] = after - before
    return {"values": values, "gaugeChanges": gauges, "issues": issues, "status": "conflict" if issues else "observed"}


def next_tick(value):
    local = value.astimezone(SEOUL)
    base = local.replace(minute=0 if local.minute < 30 else 30, second=0, microsecond=0)
    return (base + timedelta(minutes=30)).astimezone(UTC)


def cutoff_for(value):
    return value.astimezone(SEOUL).replace(hour=17, minute=30, second=0, microsecond=0).astimezone(UTC)


def snapshot_key(kind, scheduled):
    return kind if kind in ("baseline", "on_time_final", "late_drain_final") else kind + ":" + stamp(scheduled)


def history(root):
    rows = []
    for path in sorted((root / "snapshots").glob("*/manifest.json")):
        if path.parent.name.startswith("."):
            continue
        manifest = decode(read_bytes(path))
        raw = read_bytes(path.parent / "metrics.json")
        if hashlib.sha256(raw).hexdigest() != manifest["metricsSha256"]:
            raise ValueError("existing_snapshot_integrity_failed")
        rows.append({"manifest": manifest, "metrics": decode(raw), "path": path.parent})
    return sorted(rows, key=lambda r: (r["manifest"]["observedAt"], r["path"].name))


@contextmanager
def writer(root):
    directory = root / "snapshots"
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink():
        raise ValueError("snapshot_symlink_refused")
    fd = os.open(directory / ".writer.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("snapshot_writer_busy") from None
        yield
    finally:
        os.close(fd)


CSV_KEYS = ("observedAt", "scheduledAt", "kind", "status", "discovered", "prepared", "new", "reused", "units", "graphs", "nodes", "edges", "attempts", "missingJournal", "chargedUSD", "unknownUSD", "network")


def csv_row(manifest, metrics):
    counts = metrics.get("cumulative", {})
    def val(key):
        return counts.get(key)
    money = metrics.get("providers", {}).get("money", {}).get("total", {})
    values = [manifest["observedAt"], manifest["scheduledAt"], manifest["kind"], manifest["status"],
              *[val("collection.total." + k) for k in ("discovered", "prepared", "new", "reused")],
              val("analysis.units"), val("graph.completedVersions"), val("graph.versionLocalNodes"), val("graph.versionLocalEdges"),
              val("providers.ledgerAttempts"), metrics.get("providers", {}).get("ledgerMissingJournal"),
              money.get("chargedNanoUsd") / 1e9 if money.get("chargedNanoUsd") is not None else None,
              money.get("unknownExposureNanoUsd") / 1e9 if money.get("unknownExposureNanoUsd") is not None else None, 0]
    stream = io.StringIO()
    csv.writer(stream, lineterminator="\n").writerows((CSV_KEYS, ["NA" if v is None else v for v in values]))
    return stream.getvalue()


def analysis_table(rows):
    lines = ["rows complete incomplete stale missed network", "%d %d %d %d %d 0" % (len(rows), *[sum(r["manifest"]["status"] == s for r in rows) for s in ("complete", "incomplete", "stale", "missed")]),
             "KST prepared units graphs nodes edges attempts chargedUSD"]
    for row in rows:
        m = row["metrics"].get("cumulative", {})
        keys = ("collection.total.prepared", "analysis.units", "graph.completedVersions", "graph.versionLocalNodes", "graph.versionLocalEdges", "providers.ledgerAttempts", "money.total.chargedNanoUsd")
        values = [m.get(k) for k in keys]
        if values[-1] is not None:
            values[-1] = round(values[-1] / 1e9, 9)
        lines.append(instant(row["manifest"]["observedAt"]).astimezone(SEOUL).strftime("%H:%M:%S") + " " + " ".join("NA" if v is None else str(v) for v in values))
    latest = rows[-1]["metrics"].get("cumulative", {})
    sections = (
        ("collection", ["collection.total." + k for k in ("discovered", "fetched", "prepared", "new", "reused", "blocked", "failed", "queued", "requests", "bytes")]),
        ("itemFreshness", ["collection.itemFreshness." + key for key in FRESHNESS_KEYS]),
        ("coverage", ["coverage." + k for k in ("offered", "attempted", "analysisAdmitted")]),
        ("analysis", ["analysis." + k for k in ("eventCandidates", "topicCandidates", "comparisons")]),
        ("comparison", ["analysis.effectiveRelations." + k for k in RELATIONS]),
        ("relation", ["analysis.relationEligibility." + k for k in ("eligible", "hold", "reject", "pending")]),
        ("summary", ["analysis.privateSummary." + k for k in ("available", "verifier-hold", "verifier-reject", "error")]),
        ("tokens", ["tokens." + k for k in TOKEN_KEYS]),
        ("moneyNanoUSD", ["money.total." + k for k in ("chargedNanoUsd", "reservedNanoUsd", "unknownExposureNanoUsd")]),
    )
    for title, keys in sections:
        lines.append(title + " " + " ".join(k.rsplit(".", 1)[-1] for k in keys))
        lines.append(" ".join("NA" if latest.get(k) is None else str(latest[k]) for k in keys))
    lines.append("accuracy falseMerge overHold: NA NA NA")
    return "\n".join(lines) + "\n"


def emit(root, kind, scheduled, *, clock=now, missed=False, reason=None, repeats=3):
    with writer(root):
        existing = history(root)
        key = snapshot_key(kind, scheduled)
        for row in existing:
            if row["manifest"]["snapshotKey"] == key:
                return row
        observed = clock()
        if scheduled > observed:
            raise ValueError("future_snapshot_refused")
        captured = capture(root, repeats=repeats, clock=clock) if not missed else None
        metrics = captured["metrics"] if captured else {"schemaVersion": SCHEMA, "cumulative": {}, "networkCalls": 0, "publicUse": False}
        observed_rows = [row for row in existing if row["manifest"]["status"] != "missed"]
        previous = observed_rows[-1] if observed_rows else None
        difference = delta(metrics["cumulative"], previous["metrics"]["cumulative"] if previous and not missed else None)
        seconds = (observed - instant(previous["manifest"]["observedAt"])).total_seconds() if previous and not missed else None
        scheduled_seconds = (scheduled - instant(previous["manifest"]["scheduledAt"])).total_seconds() if previous and not missed else None
        metrics["sincePreviousSnapshot"] = {**difference, "observedSeconds": seconds, "scheduledSeconds": scheduled_seconds,
                                            "previousSnapshot": previous["manifest"]["snapshotKey"] if previous else None}
        metrics["last30Minutes"] = {"status": "observed_adjacent_grid" if scheduled_seconds == 1800 and not missed else "unmeasured_exact_window",
                                    "values": difference["values"] if scheduled_seconds == 1800 and not missed else {k: None for k in metrics["cumulative"]}}
        if kind == "late_drain_final":
            if not metrics.get("owners", {}).get("drained"):
                raise ValueError("owners_or_admitted_sets_not_finished")
            cutoff = next((row for row in existing if row["manifest"]["kind"] == "on_time_final"), None)
            metrics["delta_after_cutoff"] = delta(metrics["cumulative"], cutoff["metrics"]["cumulative"] if cutoff and cutoff["manifest"]["status"] != "missed" else None)
            metrics["delta_after_cutoff"]["cutoffObserved"] = bool(cutoff and cutoff["manifest"]["status"] != "missed")
        manifest = {"schemaVersion": SCHEMA, "snapshotKey": key, "kind": kind, "scheduledAt": stamp(scheduled), "observedAt": stamp(observed),
                    "status": "missed" if missed else captured["status"], "reason": reason,
                    "observationDelaySeconds": (observed - scheduled).total_seconds(),
                    "cutoffSemantics": "scheduled_grid_observed_interval_not_reconstructed_exact_instant",
                    "observationInterval": {"startedAt": captured["startedAt"], "endedAt": captured["endedAt"]} if captured else None,
                    "globallyAtomic": False, "checkpointVector": captured["vector"] if captured else None,
                    "stabilization": {k: captured[k] for k in ("stable", "passes", "changed")} if captured else None,
                    "issues": captured["issues"] if captured else [{"code": "scheduled_observation_missed_no_historical_read"}],
                    "networkCalls": 0, "publicUse": False}
        data = encoded(metrics) + b"\n"
        manifest["metricsSha256"] = hashlib.sha256(data).hexdigest()
        row_text = csv_row(manifest, metrics).encode()
        manifest["rowSha256"] = hashlib.sha256(row_text).hexdigest()
        label = observed.strftime("%Y%m%dT%H%M%S.%fZ") + "-" + kind + "-" + digest(key)[:10]
        destination = root / "snapshots" / label
        staging = destination.with_name(".pending-" + uuid.uuid4().hex)
        staging.mkdir(mode=0o700)
        files = {"manifest.json": encoded(manifest) + b"\n", "metrics.json": data, "row.csv": row_text}
        row = {"manifest": manifest, "metrics": metrics, "path": destination}
        if kind in ("on_time_final", "late_drain_final", "drain_blocked"):
            files["analysis.txt"] = analysis_table([*existing, row]).encode()
        for name, content in files.items():
            with (staging / name).open("xb") as target:
                os.fchmod(target.fileno(), 0o400)
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
        staging.chmod(0o500)
        os.rename(staging, destination)
        fd = os.open(root / "snapshots", os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return row


def due_rows(root, cutoff, *, clock=now, lateness=60, repeats=3):
    existing = history(root)
    emitted = []
    if not existing:
        emitted.append(emit(root, "baseline", clock(), clock=clock, repeats=repeats))
        existing = history(root)
    baseline = next(row for row in existing if row["manifest"]["kind"] == "baseline")
    tick = next_tick(instant(baseline["manifest"]["observedAt"]))
    seen = {row["manifest"]["snapshotKey"] for row in existing}
    while tick <= min(clock(), cutoff):
        kind = "on_time_final" if tick == cutoff else "scheduled"
        if snapshot_key(kind, tick) not in seen:
            emitted.append(emit(root, kind, tick, clock=clock, missed=(clock() - tick).total_seconds() > lateness, repeats=repeats))
        tick += timedelta(minutes=30)
    if clock() >= cutoff and not any(row["manifest"]["kind"] == "on_time_final" for row in history(root)):
        emitted.append(emit(root, "on_time_final", cutoff, clock=clock, missed=True, reason="watch_started_after_cutoff", repeats=repeats))
    return emitted


def finalize(root, cutoff, *, clock=now, lateness=60, repeats=3):
    due_rows(root, cutoff, clock=clock, lateness=lateness, repeats=repeats)
    if clock() < cutoff:
        raise ValueError("cutoff_not_reached")
    return emit(root, "late_drain_final", clock(), clock=clock, repeats=repeats)


def watch(root, cutoff, *, clock=now, sleep=time.sleep, poll=5, grace=7200, owner_grace=120, lateness=60, repeats=3, output=print):
    missing_since = None
    while True:
        for row in due_rows(root, cutoff, clock=clock, lateness=lateness, repeats=repeats):
            output(csv_row(row["manifest"], row["metrics"]).rstrip())
        current = clock()
        if current >= cutoff:
            captured = capture(root, repeats=repeats, clock=clock)
            owners = captured["metrics"]["owners"]
            if owners["drained"]:
                result = finalize(root, cutoff, clock=clock, lateness=lateness, repeats=repeats)
                output(csv_row(result["manifest"], result["metrics"]).rstrip())
                return result
            missing = any(not owners[key]["finished"] and owners[key]["lock"] != "active" for key in ("collection", "analysis"))
            missing_since = current if missing and missing_since is None else missing_since if missing else None
            if current >= cutoff + timedelta(seconds=grace) or missing_since is not None and (current - missing_since).total_seconds() >= owner_grace:
                reason = "drain_deadline_owners_not_finished" if current >= cutoff + timedelta(seconds=grace) else "owner_absent_or_crashed"
                result = emit(root, "drain_blocked", current, clock=clock, reason=reason, repeats=repeats)
                output(csv_row(result["manifest"], result["metrics"]).rstrip())
                return result
        wake = min(next_tick(current), cutoff) if current < cutoff else current + timedelta(seconds=poll)
        sleep(max(.01, min(poll, (wake - current).total_seconds())))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("snapshot", "watch", "finalize"))
    parser.add_argument("--root", type=Path, required=True, help="explicitly authorized private run root")
    parser.add_argument("--cutoff", help="timezone-aware 17:30 Asia/Seoul instant; default today")
    parser.add_argument("--grace-seconds", type=int, default=7200)
    parser.add_argument("--owner-grace-seconds", type=int, default=120)
    parser.add_argument("--poll-seconds", type=float, default=5)
    parser.add_argument("--lateness-seconds", type=int, default=60)
    parser.add_argument("--stabilization-repeats", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        root = args.root.absolute()
        if root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o077:
            raise ValueError("authorized_private_existing_root_required")
        cutoff = instant(args.cutoff) if args.cutoff else cutoff_for(now())
        local = cutoff.astimezone(SEOUL)
        if (local.hour, local.minute, local.second, local.microsecond) != (17, 30, 0, 0):
            raise ValueError("cutoff_must_be_1730_seoul")
        if not (1 <= args.stabilization_repeats <= 5 and 0 <= args.lateness_seconds <= 60 and
                1 <= args.grace_seconds <= 86400 and 1 <= args.owner_grace_seconds <= args.grace_seconds and 0 < args.poll_seconds <= 30):
            raise ValueError("observer_bounds_invalid")
        kwargs = {"lateness": args.lateness_seconds, "repeats": args.stabilization_repeats}
        if args.command == "snapshot":
            kind = "baseline" if not history(root) else "manual"
            row = emit(root, kind, now(), repeats=args.stabilization_repeats)
        elif args.command == "finalize":
            row = finalize(root, cutoff, **kwargs)
        else:
            row = watch(root, cutoff, poll=args.poll_seconds, grace=args.grace_seconds, owner_grace=args.owner_grace_seconds, **kwargs)
        if args.command != "watch":
            print(csv_row(row["manifest"], row["metrics"]).rstrip())
        return 2 if row["manifest"]["kind"] == "drain_blocked" else 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        code = str(exc) if isinstance(exc, ValueError) and TOKEN.fullmatch(str(exc)) else "snapshot_observation_failed"
        print(json.dumps({"status": "blocked", "code": code, "networkCalls": 0}, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
