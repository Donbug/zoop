#!/usr/bin/env python3
"""Content-free, offline measurements for the single-writer overnight controller.

Only events.jsonl is read. Source documents, provider bodies and credentials are
never opened. Measurements are observations, not gold-labelled accuracy scores.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "zoop-overnight-event-1"
MAX_EVENT_BYTES = 16_384
MAX_JOURNAL_BYTES = 128 * 1024 * 1024
MAX_EVENTS = 100_000
MAX_SAMPLE_INDEX = 300
SAMPLES_PER_STRATUM = 3
STATUSES = ("ok", "empty", "refused", "error", "unknown", "reused", "blocked")
KINDS = ("phase", "attempt", "record", "budget", "batch", "context")
PROVENANCES = ("cli_wall", "http_request", "stage_wall", "batch_wall", "unknown")
COUNT_KEYS = frozenset((
    "discovery", "requested", "requests", "retained", "prepared", "schemaValid", "duplicate", "rightsBlocked",
    "documents", "candidates", "SAME", "NEW", "HOLD", "ALLOW", "REJECT", "pending", "eligible", "stored",
    "summaryEligible", "summaryAvailable", "summaryFailed", "truncated", "refused", "unknown", "excluded",
    "supported", "insufficient", "contradicted", "present", "absent", "uncertain", "nodes", "edges",
))
USAGE_KEYS = ("inputTokens", "outputTokens", "cachedTokens", "reasoningTokens", "cacheWriteTokens")
COST_KEYS = ("estimatedNanoUsd", "chargedNanoUsd", "reservedNanoUsd", "unknownExposureNanoUsd", "invoiceNanoUsd", "allowanceNanoUsd", "providerBillableNanoUsd", "providerListNanoUsd")
BUDGET_KEYS = ("maxNanoUsd", "chargedNanoUsd", "actualNanoUsd", "reservedNanoUsd", "unknownExposureNanoUsd", "remainingNanoUsd", "calls", "maxCalls")
CHECK_KEYS = ("schema", "citationExact", "identity", "graphIntegrity", "summaryCoverage")
ID_KEYS = ("sourceId", "reasonCode", "requestedModel", "reportedModel", "fundingBucket", "accountRole", "attemptId")
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+-]{0,199}\Z")
REF = re.compile(r"[A-Za-z0-9_./-]{1,512}\Z")
UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)\Z")
SECRET_PREFIX = re.compile(r"(?:sk-|tsk-|Bearer|ghp_|github_pat_)", re.I)


class MetricsError(ValueError):
    """Stable, metadata-only error; never includes rejected input."""


def _fail(code: str) -> None:
    raise MetricsError(code)


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _object(value: Any, keys: Any) -> dict:
    if not isinstance(value, dict) or not value.keys() <= set(keys):
        _fail("event_fields_invalid")
    return value


def _token(value: Any, *, nullable: bool = True) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not TOKEN.fullmatch(value) or SECRET_PREFIX.match(value):
        _fail("event_identifier_invalid")
    return value


def _number(value: Any, *, integer: bool = False) -> int | float | None:
    if value is None:
        return None
    if type(value) not in ((int,) if integer else (int, float)) or not 0 <= value <= 2**53 - 1:
        _fail("event_number_invalid")
    return value


def _enum(value: Any, values: Any) -> str:
    if value not in values:
        _fail("event_enum_invalid")
    return value


def _time(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not UTC.fullmatch(value):
        _fail("event_timestamp_invalid")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail("event_timestamp_invalid")
    return value


def _publication_instant(value: Any) -> str | None:
    """Normalize source offsets only; keep existing UTC receipt bytes hash-stable."""
    if value is None or isinstance(value, str) and UTC.fullmatch(value):
        return _time(value)
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?[+-](?:\d{2}:\d{2}|(?:[01]\d|2[0-3])[0-5]\d)", value):
        _fail("event_publication_invalid")
    try:
        return datetime.fromisoformat(value).astimezone(timezone.utc).isoformat()
    except ValueError:
        _fail("event_publication_invalid")


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ref(value: Any) -> str:
    if not isinstance(value, str) or not REF.fullmatch(value):
        _fail("event_artifact_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in (".", "..") for part in value.split("/")) or str(path) != value:
        _fail("event_artifact_invalid")
    return value


def _numbers(value: Any, keys: Any) -> dict:
    return {key: _number(val, integer=True) for key, val in _object(value, keys).items()}


def normalize_event(event: dict) -> dict:
    """Validate the metadata allowlist; optional unknown values remain null."""
    fields = {"schemaVersion", "eventId", "runId", "cohort", "phase", "unitId", "status", "kind", "freshness",
              "startUtc", "endUtc", "durationMs", "durationProvenance", "attemptState", "httpStatus", "counts", "bytes",
              "usage", "cost", "checks", "artifacts", "sample", "publication", "context", "budget", *ID_KEYS}
    raw = _object(event, fields)
    if raw.get("schemaVersion", SCHEMA) != SCHEMA:
        _fail("event_schema_invalid")
    out = {"schemaVersion": SCHEMA}
    for key in ("eventId", "runId", "cohort", "phase", "unitId"):
        out[key] = _token(raw.get(key), nullable=False)
    out["status"] = _enum(raw.get("status"), STATUSES)
    out["kind"] = _enum(raw.get("kind", "phase"), KINDS)
    out["freshness"] = _enum(raw.get("freshness", "unknown"), ("fresh", "backfill", "reused", "unknown"))
    for key in ID_KEYS:
        out[key] = _token(raw.get(key))
    for key in ("startUtc", "endUtc"):
        out[key] = _time(raw.get(key))
    if out["startUtc"] and out["endUtc"] and _instant(out["endUtc"]) < _instant(out["startUtc"]):
        _fail("event_interval_invalid")
    out["durationMs"] = _number(raw.get("durationMs"))
    out["durationProvenance"] = _enum(raw.get("durationProvenance", "unknown"), PROVENANCES)
    if out["durationMs"] is not None and out["durationProvenance"] == "unknown":
        _fail("event_duration_provenance_required")
    out["attemptState"] = _enum(raw.get("attemptState"), (None, "started", "received", "released", "reused", "unknown"))
    out["httpStatus"] = _number(raw.get("httpStatus"), integer=True)
    if out["httpStatus"] is not None and not 100 <= out["httpStatus"] <= 599:
        _fail("event_http_status_invalid")
    out["counts"] = _numbers(raw.get("counts", {}), COUNT_KEYS)
    out["bytes"] = _numbers(raw.get("bytes", {}), ("input", "output", "retained"))
    usage = _object(raw.get("usage", {}), USAGE_KEYS)
    # Keep legacy serialized receipts hash-stable; absent cache-write measurements remain unknown.
    out["usage"] = {key: _number(usage.get(key), integer=True) for key in USAGE_KEYS
                    if key != "cacheWriteTokens" or key in usage}
    cost = _object(raw.get("cost", {}), (*COST_KEYS, "basis", "state"))
    out["cost"] = {key: _number(cost.get(key), integer=True) for key in COST_KEYS}
    out["cost"]["basis"] = _enum(cost.get("basis", "unknown"), ("cash_estimate", "opencode_allowance", "loopback", "unknown"))
    out["cost"]["state"] = _enum(cost.get("state", "unknown"), ("reserved", "settled", "released", "unknown"))
    checks = _object(raw.get("checks", {}), CHECK_KEYS)
    out["checks"] = {}
    for name, check in checks.items():
        check = _object(check, ("passed", "total"))
        passed, total = (_number(check.get(key), integer=True) for key in ("passed", "total"))
        if passed is None or total is None or passed > total:
            _fail("event_check_invalid")
        out["checks"][name] = {"passed": passed, "total": total}
    artifacts = raw.get("artifacts", [])
    if not isinstance(artifacts, list) or len(artifacts) > 32:
        _fail("event_artifact_invalid")
    out["artifacts"] = [_ref(item) for item in artifacts]
    out["sample"] = None
    if raw.get("sample") is not None:
        sample = _object(raw["sample"], ("recordId", "artifact", "recordType", "decision"))
        out["sample"] = {key: _token(sample.get(key), nullable=False) for key in ("recordId", "recordType", "decision")}
        out["sample"]["artifact"] = _ref(sample.get("artifact"))
    out["publication"] = None
    if raw.get("publication") is not None:
        publication = _object(raw["publication"], ("precision", "publishedAt", "collectedAt"))
        precision = _enum(publication.get("precision"), ("instant", "day", "unknown"))
        published = publication.get("publishedAt")
        if precision == "instant":
            published = _publication_instant(published)
        elif precision == "day" and published is not None:
            try:
                if not isinstance(published, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published):
                    _fail("event_publication_invalid")
                datetime.strptime(published, "%Y-%m-%d")
            except ValueError:
                _fail("event_publication_invalid")
        elif precision == "unknown" and published is not None:
            _fail("event_publication_invalid")
        out["publication"] = {"precision": precision, "publishedAt": published, "collectedAt": _time(publication.get("collectedAt"))}
    out["context"] = {}
    context = _object(raw.get("context", {}), ("machine", "concurrency", "cpuCount", "memoryBytes", "platform", "architecture",
                                              "powerSource", "batteryPercent", "concurrentWorkloads", "load1", "load5", "load15",
                                              "codeRevision", "configDigest", "promptDigest"))
    integer_keys = ("concurrency", "cpuCount", "memoryBytes")
    for key, value in context.items():
        if key == "concurrentWorkloads":
            if value is not None and type(value) is not bool:
                _fail("event_context_invalid")
            out["context"][key] = value
        else:
            out["context"][key] = _number(value, integer=key in integer_keys) if key in (*integer_keys, "batteryPercent", "load1", "load5", "load15") else _token(value)
        if key == "batteryPercent" and value is not None and value > 100:
            _fail("event_context_invalid")
    out["budget"] = _numbers(raw.get("budget", {}), BUDGET_KEYS)
    if out["kind"] == "attempt" and not out["attemptId"]:
        _fail("event_attempt_identity_required")
    if out["kind"] != "attempt" and (any(value is not None for value in out["usage"].values()) or any(out["cost"][key] is not None for key in COST_KEYS)):
        _fail("event_attempt_kind_required")
    if out["budget"] and (out["kind"] != "budget" or out["fundingBucket"] is None):
        _fail("event_budget_identity_required")
    if len(_json(out)) > MAX_EVENT_BYTES - 512:
        _fail("event_too_large")
    return out


def record_event(path: str | Path, event: dict) -> dict:
    """Append one fsynced 0600 JSON line; never repairs an interrupted tail.

    The controller owns the only writer. The file lock refuses concurrent append;
    duplicate event/attempt observations are reconciled by summarize, not resent.
    """
    out = normalize_event(event)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            _fail("journal_not_private_regular_file")
        if info.st_size and os.pread(fd, 1, info.st_size - 1) != b"\n":
            _fail("journal_partial_tail")
        out["append"] = {"byteOffset": info.st_size, "recordedAtUtc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                         "eventSha256": hashlib.sha256(_json(out)).hexdigest()}
        encoded = _json(out) + b"\n"
        if len(encoded) > MAX_EVENT_BYTES or info.st_size + len(encoded) > MAX_JOURNAL_BYTES:
            _fail("journal_limit_exceeded")
        view = memoryview(encoded)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                _fail("journal_write_failed")
            view = view[written:]
        os.fsync(fd)
    except BlockingIOError:
        _fail("journal_writer_busy")
    finally:
        os.close(fd)
    return out


def _pairs(pairs: list) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            _fail("journal_duplicate_json_key")
        out[key] = value
    return out


def _decode(line: bytes, offset: int) -> dict:
    try:
        raw = json.loads(line, object_pairs_hook=_pairs, parse_constant=lambda _: _fail("journal_nonfinite_number"))
        if not isinstance(raw, dict):
            _fail("event_fields_invalid")
        append = _object(raw.pop("append", None), ("byteOffset", "recordedAtUtc", "eventSha256"))
        out = normalize_event(raw)
        if type(append.get("byteOffset")) is not int or append["byteOffset"] != offset or _time(append.get("recordedAtUtc")) is None:
            _fail("journal_append_metadata_invalid")
        if append.get("eventSha256") != hashlib.sha256(_json(out)).hexdigest():
            _fail("journal_event_digest_mismatch")
        return out
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, OverflowError):
        _fail("journal_json_invalid")


def _read_events(path: Path) -> tuple[list[dict], dict]:
    integrity = {"status": "complete", "lines": 0, "uniqueEvents": 0, "duplicateEvents": 0, "issues": [], "partialTail": None}
    events, seen = [], {}
    if not path.exists():
        integrity["status"] = "incomplete"
        integrity["issues"].append({"code": "journal_missing"})
        return events, integrity
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_size > MAX_JOURNAL_BYTES:
            _fail("journal_limit_exceeded")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            offset = 0
            while True:
                line = stream.readline(MAX_EVENT_BYTES + 1)
                if not line:
                    break
                integrity["lines"] += 1
                if integrity["lines"] > MAX_EVENTS or len(line) > MAX_EVENT_BYTES:
                    _fail("journal_limit_exceeded")
                if not line.endswith(b"\n"):
                    integrity["partialTail"] = {"byteOffset": offset, "bytes": len(line), "sha256": hashlib.sha256(line).hexdigest()}
                    integrity["status"] = "incomplete"
                    break
                try:
                    event = _decode(line, offset)
                    key = event["eventId"]
                    if key in seen:
                        if seen[key] != event:
                            _fail("journal_event_id_conflict")
                        integrity["duplicateEvents"] += 1
                    else:
                        seen[key] = event
                        events.append(event)
                except MetricsError as exc:
                    integrity["status"] = "incomplete"
                    if len(integrity["issues"]) < 100:
                        integrity["issues"].append({"code": str(exc), "line": integrity["lines"], "byteOffset": offset, "sha256": hashlib.sha256(line).hexdigest()})
                    else:
                        _fail("journal_too_many_errors")
                offset += len(line)
    finally:
        os.close(fd)
    integrity["uniqueEvents"] = len(events)
    return events, integrity


def _ratio(num: int, den: int) -> dict:
    return {"num": num, "den": den, "value": num / den if den else None}


def _measure(values: list) -> dict:
    known = [value for value in values if value is not None]
    return {"known": len(known), "unknown": len(values) - len(known), "knownTotal": sum(known) if known else None,
            "total": sum(known) if known and len(known) == len(values) else None}


def _distribution(values: list[float], unknown: int = 0) -> dict:
    ordered = sorted(values)
    size = len(ordered)
    return {"sampleN": size, "unknownN": unknown, "p50": ordered[math.ceil(size * .50) - 1] if size else None,
            "p95": ordered[math.ceil(size * .95) - 1] if size else None, "min": ordered[0] if size else None,
            "max": ordered[-1] if size else None, "p50SmallSample": size < 10, "p95SmallSample": size < 20}


def _latency(events: list[dict]) -> dict:
    result = {}
    for provenance in PROVENANCES:
        selected = [event for event in events if event["durationProvenance"] == provenance]
        if not selected:
            continue
        result[provenance] = {"allOutcomes": _distribution([e["durationMs"] for e in selected if e["durationMs"] is not None], sum(e["durationMs"] is None for e in selected)),
                              "byStatus": {status: _distribution([e["durationMs"] for e in selected if e["status"] == status and e["durationMs"] is not None],
                                                                  sum(e["status"] == status and e["durationMs"] is None for e in selected)) for status in STATUSES}}
    return result


def _checks(events: list[dict]) -> dict:
    result = {}
    for name in CHECK_KEYS:
        checks = [event["checks"][name] for event in events if name in event["checks"]]
        result[name] = {**_ratio(sum(c["passed"] for c in checks), sum(c["total"] for c in checks)), "measuredUnits": len(checks), "unmeasuredUnits": len(events) - len(checks)}
    return result


def _lag(events: list[dict]) -> dict:
    values, precision, unknown, negative = [], Counter(), 0, 0
    for event in events:
        publication = event["publication"] or {}
        precision[publication.get("precision", "unknown")] += 1
        if publication.get("precision") != "instant" or not publication.get("publishedAt") or not publication.get("collectedAt"):
            unknown += 1
            continue
        lag = (_instant(publication["collectedAt"]) - _instant(publication["publishedAt"])).total_seconds()
        if lag < 0:
            negative += 1
        else:
            values.append(lag)
    return {"seconds": _distribution(values, unknown + negative), "precisionCounts": dict(precision), "negativeLagN": negative}


def _decisions(counts: dict) -> dict:
    result = {}
    for name, keys in (("merge", ("SAME", "NEW", "HOLD")), ("verdict", ("ALLOW", "HOLD", "REJECT")),
                       ("claim", ("supported", "insufficient", "contradicted"))):
        totals = {key: counts.get(key, {}).get("total") for key in keys}
        denominator = sum(totals.values()) if all(value is not None for value in totals.values()) else None
        result[name] = {key: {"num": value, "den": denominator, "value": value / denominator if denominator else None}
                        for key, value in totals.items()}
    return result


def _work_group(events: list[dict]) -> dict:
    statuses = Counter(event["status"] for event in events)
    counts = {key: _measure([event["counts"].get(key) for event in events]) for key in sorted(set().union(*(event["counts"] for event in events)))}
    timed = [event for event in events if event["startUtc"] and event["endUtc"]]
    wall = ((_instant(max((e["endUtc"] for e in timed), key=_instant)) - _instant(min((e["startUtc"] for e in timed), key=_instant))).total_seconds() * 1000) if timed else None
    complete_wall = wall if len(timed) == len(events) else None
    return {"units": len(events), "statusCounts": {key: statuses[key] for key in STATUSES}, "reasonCounts": dict(sorted(Counter(e["reasonCode"] for e in events if e["reasonCode"]).items())),
            "failureRate": _ratio(statuses["error"] + statuses["refused"] + statuses["blocked"] + statuses["unknown"], len(events)),
            "counts": counts, "distributions": _decisions(counts),
            "bytes": {key: _measure([event["bytes"].get(key) for event in events]) for key in ("input", "output", "retained")},
            "latencyMs": _latency(events), "observedEnvelopeWallMs": wall, "envelopeWallMs": complete_wall,
            "wallProvenance": "utc_observation_envelope_not_summed_durations",
            "throughput": {"unitsPerSecond": len(events) * 1000 / complete_wall if complete_wall else None,
                           "successfulUnitsPerSecond": statuses["ok"] * 1000 / complete_wall if complete_wall else None,
                           "includesFailedWork": True, "timedUnits": len(timed), "untimedUnits": len(events) - len(timed)},
            "checks": _checks(events), "publicationLag": _lag(events)}


def _group(events: list[dict], keys: tuple, aggregate: Any) -> list[dict]:
    groups = defaultdict(list)
    for event in events:
        groups[tuple(event[key] for key in keys)].append(event)
    return [{**dict(zip(keys, key)), **aggregate(items)} for key, items in sorted(groups.items(), key=lambda pair: _json(pair[0]))]


def _attempts(events: list[dict], integrity: dict) -> dict:
    observations = [event for event in events if event["kind"] == "attempt"]
    chosen, identities, conflicts = {}, {}, set()
    identity_keys = ("runId", "cohort", "phase", "requestedModel", "fundingBucket", "accountRole")
    for event in observations:
        attempt = event["attemptId"]
        identity = tuple(event[key] for key in identity_keys)
        if attempt in identities and identity != identities[attempt]:
            conflicts.add(attempt)
        identities[attempt] = identity
        previous = chosen.get(attempt)
        reused = event["status"] == "reused" or event["attemptState"] == "reused"
        if previous and not reused and previous["attemptState"] == event["attemptState"] == "received":
            if any(previous[key] != event[key] for key in ("usage", "cost", "reportedModel", "httpStatus")):
                conflicts.add(attempt)
        rank = {None: 1, "reused": 0, "unknown": 1, "started": 1, "received": 2, "released": 2}
        if previous is None or (not reused and rank[event["attemptState"]] >= rank[previous["attemptState"]]):
            chosen[attempt] = event
    if conflicts:
        integrity["status"] = "incomplete"
        integrity["issues"].append({"code": "attempt_identity_conflict", "attemptCount": len(conflicts)})
    selected = [event for attempt, event in chosen.items() if attempt not in conflicts]
    reuse_only = [event for event in selected if event["status"] == "reused" or event["attemptState"] == "reused"]
    selected = [event for event in selected if event["status"] != "reused" and event["attemptState"] != "reused"]

    def aggregate(items: list[dict]) -> dict:
        return {"uniqueAttempts": len(items), "received": sum(e["attemptState"] == "received" for e in items),
                "released": sum(e["attemptState"] == "released" for e in items),
                "unknownOutcome": sum(e["attemptState"] in (None, "started", "unknown") for e in items),
                "statusCounts": dict(Counter(e["status"] for e in items)), "latencyMs": _latency(items),
                "usage": {key: _measure([e["usage"].get(key) for e in items]) for key in USAGE_KEYS},
                "cost": {key: _measure([e["cost"][key] for e in items]) for key in COST_KEYS},
                "billingBasisCounts": dict(Counter(e["cost"]["basis"] for e in items))}

    return {"observations": len(observations), "reusedObservations": sum(e["status"] == "reused" or e["attemptState"] == "reused" for e in observations),
            "conflictingAttempts": len(conflicts), "reuseOnly": len(reuse_only), **aggregate(selected),
            "groups": _group(selected, ("runId", "cohort", "phase", "requestedModel", "reportedModel", "fundingBucket", "accountRole"), aggregate),
            "costSemantics": "receipt_estimate_and_budget_charge_not_invoice; reservation_is_not_additional_spend; allowance_is_nominal_plan_dollars_not_cash"}


def _sample_index(root: Path, events: list[dict]) -> dict:
    strata, seen = defaultdict(list), set()
    for event in events:
        sample = event["sample"]
        if not sample:
            continue
        identity = (sample["artifact"], sample["recordId"])
        if identity in seen:
            continue
        seen.add(identity)
        path = (root / sample["artifact"]).resolve()
        exists = path.is_relative_to(root.resolve()) and path.is_file()
        key = (event["cohort"], event["sourceId"], event["phase"], event["freshness"], sample["recordType"], sample["decision"])
        item = {"eventId": event["eventId"], "unitId": event["unitId"], **sample, "artifactExists": exists,
                "selectionHash": hashlib.sha256(_json((event["runId"], identity))).hexdigest()}
        strata[key].append(item)
    selected, population = [], 0
    for key, items in sorted(strata.items(), key=lambda pair: _json(pair[0])):
        population += len(items)
        chosen = sorted(items, key=lambda item: item["selectionHash"])[:SAMPLES_PER_STRATUM]
        selected.append({"stratum": dict(zip(("cohort", "sourceId", "phase", "freshness", "recordType", "decision"), key)),
                         "populationN": len(items), "records": chosen})
    # Round-robin across strata avoids allocating the entire cap to early sources.
    slots = MAX_SAMPLE_INDEX
    for rank in range(SAMPLES_PER_STRATUM):
        for stratum in selected:
            if rank < len(stratum["records"]):
                if slots:
                    slots -= 1
                else:
                    stratum["records"][rank] = None
    for stratum in selected:
        stratum["records"] = [item for item in stratum["records"] if item is not None]
    return {"method": "deterministic_sha256_within_stratum_round_robin_cap", "populationN": population,
            "selectedN": MAX_SAMPLE_INDEX - slots, "perStratumLimit": SAMPLES_PER_STRATUM, "limit": MAX_SAMPLE_INDEX,
            "recordIdentityProvenance": "controller_reported_record_id; artifact_existence_checked_without_opening_body",
            "humanLabels": "unmeasured", "strata": selected}


def summarize(root: str | Path) -> dict:
    """Read bounded event metadata and return JSON-safe facts, without writes."""
    root = Path(root)
    events, integrity = _read_events(root / "events.jsonl")
    attempts = _attempts(events, integrity)
    latest = {}
    for event in events:
        if event["kind"] in ("phase", "record", "batch"):
            key = tuple(event[key] for key in ("runId", "cohort", "kind", "phase", "unitId", "sourceId"))
            if key not in latest or event["status"] != "reused":
                latest[key] = event
    work = list(latest.values())
    budgets = {}
    for event in events:
        if event["kind"] == "budget":
            budgets[(event["runId"], event["fundingBucket"], event["accountRole"])] = {key: event[key] for key in ("eventId", "runId", "fundingBucket", "accountRole", "endUtc", "budget", "artifacts")}
    contexts = [{key: event[key] for key in ("eventId", "runId", "cohort", "startUtc", "context", "artifacts")} for event in events if event["context"]]
    return {"schemaVersion": "zoop-overnight-summary-1", "integrity": integrity,
            "provenance": {"input": "events.jsonl", "providerBodiesRead": False, "networkCalls": 0,
                           "metricAuthority": "controller_observations_and_referenced_receipts_not_independent_ground_truth"},
            "observationStatuses": dict(Counter(event["status"] for event in events)),
            "groups": _group(work, ("runId", "cohort", "kind", "phase", "sourceId", "freshness", "requestedModel", "reportedModel"), _work_group),
            "attempts": attempts, "latestBudgets": list(budgets.values()), "budgetSemantics": "latest_snapshot_per_bucket_account; never_sum_with_receipt_costs",
            "contexts": contexts, "sampleIndex": _sample_index(root, work),
            "quality": {"accuracy": None, "falseMerge": None, "overHold": None, "status": "unmeasured_requires_independent_gold_or_human_labels",
                        "verdictDistributionsAreAccuracy": False, "causalModelComparison": False}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    summary = sub.add_parser("summarize")
    summary.add_argument("--root", required=True, type=Path)
    summary.add_argument("--output", help="New JSON artifact relative to root; never replaces existing evidence")
    args = parser.parse_args(argv)
    try:
        result = summarize(args.root)
        encoded = _json(result) + b"\n"
        if args.output:
            relative = _ref(args.output)
            target = args.root / relative
            if not target.parent.resolve().is_relative_to(args.root.resolve()):
                _fail("summary_output_outside_root")
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        sys.stdout.buffer.write(encoded)
        return 0 if result["integrity"]["status"] == "complete" else 2
    except (MetricsError, OSError) as exc:
        code = str(exc) if isinstance(exc, MetricsError) else "metrics_io_error"
        print(json.dumps({"schemaVersion": "zoop-overnight-summary-1", "status": "refused", "error": code}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
