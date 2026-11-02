"""Offline, known-trace acceptance tests; no provider, source body or network."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))
from scripts import overnight_metrics as metrics


START = "2026-10-27T13:00:00Z"
END = "2026-10-27T13:00:01Z"


def event(event_id="event-1", **changes):
    return {"eventId": event_id, "runId": "night-1", "cohort": "primary", "phase": "extract",
            "unitId": event_id, "sourceId": "native", "status": "ok", "freshness": "fresh",
            "startUtc": START, "endUtc": END, **changes}


def append(root, value):
    return metrics.record_event(root / "events.jsonl", value)


def attempt(event_id, attempt_id, **changes):
    return event(event_id, kind="attempt", attemptId=attempt_id, requestedModel="gpt-6-luna", reportedModel="gpt-6-luna",
                 fundingBucket="shared", accountRole="shared-openai", attemptState="received", **changes)


def test_cache_write_tokens_preserve_old_receipt_hashes_and_input_totals(tmp_path):
    legacy = append(tmp_path, attempt("legacy", "attempt-old", usage={"inputTokens": 20, "outputTokens": 3}))
    assert "cacheWriteTokens" not in legacy["usage"]
    original = (tmp_path / "events.jsonl").read_bytes()
    append(tmp_path, attempt("current", "attempt-new",
                           usage={"inputTokens": 10, "outputTokens": 2, "cacheWriteTokens": 7}))
    assert (tmp_path / "events.jsonl").read_bytes().startswith(original)
    result = subprocess.run(
        [sys.executable, str(PIPELINE / "scripts/overnight_metrics.py"), "summarize", "--root", str(tmp_path)],
        capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout
    measured = json.loads(result.stdout)
    assert measured["integrity"]["status"] == "complete"
    assert measured["attempts"]["usage"]["inputTokens"]["total"] == 30
    assert measured["attempts"]["usage"]["cacheWriteTokens"] == {
        "known": 1, "unknown": 1, "knownTotal": 7, "total": None}


def group(summary, **match):
    return next(item for item in summary["groups"] if all(item[key] == value for key, value in match.items()))


def test_known_trace_keeps_failures_unknowns_and_latency_denominators(tmp_path):
    cases = [("ok", 10), ("empty", 20), ("error", 100), ("refused", 200), ("unknown", None), ("blocked", 300)]
    for index, (status, duration) in enumerate(cases):
        append(tmp_path, event(f"event-{index}", status=status, durationMs=duration, durationProvenance="cli_wall",
                               reasonCode="timeout" if status == "unknown" else None,
                               counts={"documents": 1, "retained": 1 if status == "ok" else None}))
    result = metrics.summarize(tmp_path)
    measured = result["groups"][0]
    assert measured["units"] == 6
    assert measured["statusCounts"] == {"ok": 1, "empty": 1, "error": 1, "refused": 1, "unknown": 1, "reused": 0, "blocked": 1}
    assert measured["failureRate"] == {"num": 4, "den": 6, "value": 4 / 6}
    timing = measured["latencyMs"]["cli_wall"]
    assert timing["allOutcomes"] == {"sampleN": 5, "unknownN": 1, "p50": 100, "p95": 300, "min": 10, "max": 300,
                                     "p50SmallSample": True, "p95SmallSample": True}
    assert timing["byStatus"]["error"]["p50"] == 100
    assert timing["byStatus"]["unknown"]["sampleN"] == 0
    assert measured["counts"]["retained"] == {"known": 1, "unknown": 5, "knownTotal": 1, "total": None}
    assert measured["counts"]["documents"]["total"] == 6
    assert measured["envelopeWallMs"] == 1000
    assert measured["throughput"]["unitsPerSecond"] == 6
    assert measured["throughput"]["successfulUnitsPerSecond"] == 1
    assert measured["reasonCounts"] == {"timeout": 1}
    assert result["quality"]["accuracy"] is None


def test_cli_http_and_fresh_backfill_model_cohorts_never_mix(tmp_path):
    append(tmp_path, event("primary-cli", durationMs=900, durationProvenance="cli_wall", requestedModel="gpt-6-luna"))
    append(tmp_path, event("fallback-cli", cohort="fallback", freshness="backfill", durationMs=500, durationProvenance="cli_wall", requestedModel="deepseek-v4.1-flash"))
    append(tmp_path, event("source-http", phase="acquisition", durationMs=50, durationProvenance="http_request"))
    append(tmp_path, attempt("primary-call", "attempt-primary", durationMs=100, durationProvenance="http_request"))
    result = metrics.summarize(tmp_path)
    assert len(result["groups"]) == 3
    assert group(result, cohort="primary", phase="extract")["latencyMs"]["cli_wall"]["allOutcomes"]["p50"] == 900
    assert group(result, cohort="fallback")["freshness"] == "backfill"
    assert result["attempts"]["latencyMs"]["http_request"]["allOutcomes"]["p50"] == 100
    assert "cli_wall" not in result["attempts"]["latencyMs"]
    assert result["quality"]["causalModelComparison"] is False


def test_append_metadata_duplicate_events_and_latest_phase_snapshot(tmp_path):
    first = event(counts={"retained": 2})
    recorded = append(tmp_path, first)
    append(tmp_path, first)
    append(tmp_path, event("snapshot-2", unitId="event-1", counts={"retained": 3}))
    append(tmp_path, event("snapshot-reused", unitId="event-1", status="reused", counts={"retained": 999}))
    result = metrics.summarize(tmp_path)
    assert recorded["append"]["byteOffset"] == 0
    assert len(recorded["append"]["eventSha256"]) == 64
    assert (tmp_path / "events.jsonl").stat().st_mode & 0o777 == 0o600
    assert result["integrity"]["duplicateEvents"] == 1
    assert result["integrity"]["uniqueEvents"] == 3
    assert result["groups"][0]["counts"]["retained"]["total"] == 3
    assert result["groups"][0]["units"] == 1
    assert result["observationStatuses"]["reused"] == 1


def test_attempt_lifecycle_reuse_unknown_and_costs_are_counted_once(tmp_path):
    started = attempt("call-start", "attempt-1")
    started.update(status="unknown", attemptState="started", reportedModel=None,
                   cost={"state": "reserved", "chargedNanoUsd": 100, "reservedNanoUsd": 100, "unknownExposureNanoUsd": 100})
    append(tmp_path, started)
    received = attempt("call-received", "attempt-1", usage={"inputTokens": 10, "outputTokens": 2},
                       cost={"basis": "cash_estimate", "state": "settled", "estimatedNanoUsd": 30, "chargedNanoUsd": 30,
                             "reservedNanoUsd": 100, "unknownExposureNanoUsd": 0})
    append(tmp_path, received)
    append(tmp_path, received)
    append(tmp_path, {**received, "eventId": "call-reused", "status": "reused", "attemptState": "reused"})
    append(tmp_path, {**started, "eventId": "late-start"})
    unknown = attempt("call-unknown", "attempt-2")
    unknown.update(status="unknown", attemptState="started", cost={"chargedNanoUsd": 80, "reservedNanoUsd": 80, "unknownExposureNanoUsd": 80})
    append(tmp_path, unknown)
    append(tmp_path, {**received, "eventId": "historical-reuse", "attemptId": "old-attempt", "status": "reused", "attemptState": "reused"})
    result = metrics.summarize(tmp_path)
    measured = result["attempts"]
    assert result["integrity"]["status"] == "complete"
    assert measured["uniqueAttempts"] == 2
    assert measured["received"] == 1 and measured["unknownOutcome"] == 1
    assert measured["reusedObservations"] == 2 and measured["reuseOnly"] == 1
    assert measured["cost"]["chargedNanoUsd"]["total"] == 110
    assert measured["cost"]["reservedNanoUsd"]["total"] == 180
    assert measured["cost"]["unknownExposureNanoUsd"]["total"] == 80
    assert measured["usage"]["inputTokens"] == {"known": 1, "unknown": 1, "knownTotal": 10, "total": None}
    assert measured["cost"]["invoiceNanoUsd"]["total"] is None


def test_attempt_cannot_move_to_another_funding_account(tmp_path):
    append(tmp_path, attempt("first", "same-attempt"))
    changed = attempt("changed", "same-attempt")
    changed.update(fundingBucket="personal", accountRole="personal-opencode", cohort="fallback")
    append(tmp_path, changed)
    result = metrics.summarize(tmp_path)
    assert result["integrity"]["status"] == "incomplete"
    assert result["attempts"]["conflictingAttempts"] == 1
    assert result["attempts"]["uniqueAttempts"] == 0
    assert result["attempts"]["cost"]["chargedNanoUsd"]["total"] is None


def test_allowance_is_not_cash_and_budget_snapshots_are_not_summed(tmp_path):
    paid = attempt("go-call", "go-attempt", cost={"basis": "opencode_allowance", "state": "settled", "chargedNanoUsd": 100,
                                                  "estimatedNanoUsd": 100, "allowanceNanoUsd": 80, "providerBillableNanoUsd": 0})
    paid.update(cohort="fallback", fundingBucket="personal", accountRole="personal-opencode", requestedModel="deepseek-v4.1-flash", reportedModel="deepseek-v4.1-flash")
    append(tmp_path, paid)
    for index, charged in enumerate((100, 170)):
        append(tmp_path, event(f"budget-{index}", kind="budget", fundingBucket="personal",
                               budget={"chargedNanoUsd": charged, "reservedNanoUsd": 70, "unknownExposureNanoUsd": 70, "maxNanoUsd": 10_000_000_000}))
    result = metrics.summarize(tmp_path)
    assert len(result["latestBudgets"]) == 1
    assert result["latestBudgets"][0]["budget"]["chargedNanoUsd"] == 170
    assert result["attempts"]["cost"]["chargedNanoUsd"]["total"] == 100
    assert result["attempts"]["cost"]["allowanceNanoUsd"]["total"] == 80
    assert result["attempts"]["cost"]["providerBillableNanoUsd"]["total"] == 0
    assert result["attempts"]["cost"]["invoiceNanoUsd"]["total"] is None


def test_technical_checks_distributions_and_zero_denominators_are_not_accuracy(tmp_path):
    append(tmp_path, event(counts={"SAME": 0, "NEW": 0, "HOLD": 0, "ALLOW": 0, "REJECT": 0},
                           checks={"schema": {"passed": 0, "total": 0}, "citationExact": {"passed": 2, "total": 3},
                                   "identity": {"passed": 1, "total": 1}, "graphIntegrity": {"passed": 4, "total": 4}}))
    measured = metrics.summarize(tmp_path)
    value = measured["groups"][0]
    assert value["checks"]["schema"]["value"] is None
    assert value["checks"]["citationExact"]["value"] == 2 / 3
    assert value["checks"]["summaryCoverage"]["unmeasuredUnits"] == 1
    assert value["checks"]["summaryCoverage"]["value"] is None
    assert value["distributions"]["merge"]["SAME"] == {"num": 0, "den": 0, "value": None}
    assert value["distributions"]["claim"]["supported"] == {"num": None, "den": None, "value": None}
    assert measured["quality"]["verdictDistributionsAreAccuracy"] is False


def test_known_verdict_distribution_and_missing_counts_remain_distinct(tmp_path):
    append(tmp_path, event(counts={"SAME": 1, "NEW": 2, "HOLD": 1, "ALLOW": 3, "REJECT": 0}))
    value = metrics.summarize(tmp_path)["groups"][0]["distributions"]
    assert value["merge"]["NEW"] == {"num": 2, "den": 4, "value": .5}
    assert value["verdict"]["ALLOW"] == {"num": 3, "den": 4, "value": .75}


@pytest.mark.parametrize("published", [
    "2026-07-27T16:30:00+09:00",
    "2026-07-27T02:30:00-05:00",
    "2026-07-27T16:30:00+0900",
    "2026-07-27T02:30:00-0500",
])
def test_offset_publication_instants_preserve_the_measured_lag(tmp_path, published):
    legacy = append(tmp_path, event("legacy", publication={
        "precision": "instant", "publishedAt": START, "collectedAt": END}))
    retained = (tmp_path / "events.jsonl").read_bytes()
    observed = append(tmp_path, event("offset", publication={
        "precision": "instant", "publishedAt": published, "collectedAt": "2026-07-27T07:30:01Z"}))
    assert legacy["publication"]["publishedAt"] == START
    assert (tmp_path / "events.jsonl").read_bytes().startswith(retained)
    assert observed["publication"]["publishedAt"] == "2026-07-27T07:30:00+00:00"
    result = metrics.summarize(tmp_path)
    assert result["integrity"]["status"] == "complete"
    lag = result["groups"][0]["publicationLag"]
    assert lag["seconds"]["sampleN"] == 2
    assert lag["seconds"]["p50"] == 1
    assert lag["negativeLagN"] == 0


def test_cnbc_basic_iso_publication_normalizes_without_rewriting_utc_receipt(tmp_path):
    legacy = append(tmp_path, event("utc", publication={
        "precision": "instant", "publishedAt": START, "collectedAt": END}))
    retained = (tmp_path / "events.jsonl").read_bytes()
    assert legacy["append"]["eventSha256"] == hashlib.sha256(
        json.dumps({key: value for key, value in legacy.items() if key != "append"},
                   ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    observed = append(tmp_path, event("cnbc", publication={
        "precision": "instant", "publishedAt": "2026-10-28T03:33:53+0000",
        "collectedAt": "2026-10-28T03:33:54Z"}))
    assert observed["publication"]["publishedAt"] == "2026-10-28T03:33:53+00:00"
    assert (tmp_path / "events.jsonl").read_bytes().startswith(retained)
    measured = metrics.summarize(tmp_path)
    assert measured["integrity"]["status"] == "complete"
    assert measured["groups"][0]["publicationLag"]["seconds"]["p50"] == 1


@pytest.mark.parametrize("offset", ["+2400", "+0060", "-2499", "+00", "+0:00"])
def test_malformed_basic_publication_offsets_are_refused_without_journal(tmp_path, offset):
    with pytest.raises(metrics.MetricsError):
        append(tmp_path, event(publication={"precision": "instant",
                                          "publishedAt": "2026-10-28T03:33:53" + offset, "collectedAt": END}))
    assert not (tmp_path / "events.jsonl").exists()


def test_day_precision_never_becomes_midnight_lag(tmp_path):
    append(tmp_path, event("day", publication={"precision": "day", "publishedAt": "2026-10-27", "collectedAt": END}))
    append(tmp_path, event("instant", publication={"precision": "instant", "publishedAt": START, "collectedAt": END}))
    append(tmp_path, event("negative", publication={"precision": "instant", "publishedAt": END, "collectedAt": START}))
    result = metrics.summarize(tmp_path)["groups"][0]["publicationLag"]
    assert result["precisionCounts"] == {"day": 1, "instant": 2}
    assert result["seconds"]["sampleN"] == 1 and result["seconds"]["unknownN"] == 2
    assert result["seconds"]["p50"] == 1
    assert result["negativeLagN"] == 1


def test_partial_tail_is_reported_preserved_and_blocks_append(tmp_path):
    append(tmp_path, event())
    path = tmp_path / "events.jsonl"
    tail = b'{"eventId":"interrupted'
    with path.open("ab") as stream:
        stream.write(tail)
    before = path.read_bytes()
    result = metrics.summarize(tmp_path)
    assert result["integrity"]["status"] == "incomplete"
    assert result["integrity"]["partialTail"] == {"byteOffset": len(before) - len(tail), "bytes": len(tail), "sha256": hashlib.sha256(tail).hexdigest()}
    assert result["groups"][0]["units"] == 1
    with pytest.raises(metrics.MetricsError, match="journal_partial_tail"):
        append(tmp_path, event("later"))
    assert path.read_bytes() == before
    assert "interrupted" not in json.dumps(result)


def test_complete_corruption_is_explicit_not_silently_dropped(tmp_path):
    append(tmp_path, event())
    with (tmp_path / "events.jsonl").open("ab") as stream:
        stream.write(b'{"body":"must-not-appear"}\n')
    result = metrics.summarize(tmp_path)
    assert result["integrity"]["status"] == "incomplete"
    assert result["integrity"]["issues"][0]["line"] == 2
    assert "must-not-appear" not in json.dumps(result)


def test_conflicting_event_identity_and_tampered_digest_are_evidence(tmp_path):
    append(tmp_path, event(counts={"retained": 1}))
    append(tmp_path, event(counts={"retained": 2}))
    result = metrics.summarize(tmp_path)
    assert result["integrity"]["issues"][0]["code"] == "journal_event_id_conflict"
    path = tmp_path / "events.jsonl"
    raw = path.read_bytes().replace(b'"retained":1', b'"retained":9', 1)
    path.write_bytes(raw)
    result = metrics.summarize(tmp_path)
    assert result["integrity"]["issues"][0]["code"] == "journal_event_digest_mismatch"


@pytest.mark.parametrize("change", [
    {"body": "not-metadata"}, {"headers": {}}, {"reasonCode": "private freeform error"}, {"unitId": "sk-not-an-id"},
    {"artifacts": ["../outside.json"]}, {"artifacts": ["https://example.invalid/path"]},
    {"durationMs": float("nan")}, {"durationMs": 5}, {"counts": {"retained": True}},
    {"startUtc": "2026-10-27"}, {"startUtc": END, "endUtc": START},
    {"startUtc": "2026-10-27T22:00:00+09:00"},
    {"startUtc": "2026-10-27T13:00:00+0000"},
    {"endUtc": "2026-10-27T13:00:01+0000"},
    {"publication": {"precision": "instant", "publishedAt": "2026-07-27T07:30:00", "collectedAt": END}},
    {"checks": {"identity": {"passed": 2, "total": 1}}}, {"cost": {"chargedNanoUsd": 1}},
    {"kind": "attempt"}, {"publication": {"precision": "day", "publishedAt": START}},
])
def test_invalid_metadata_is_refused_before_writing(tmp_path, change):
    with pytest.raises(metrics.MetricsError):
        append(tmp_path, event(**change))
    assert not (tmp_path / "events.jsonl").exists()


def test_bounded_event_and_journal_are_refused(tmp_path, monkeypatch):
    with pytest.raises(metrics.MetricsError, match="event_too_large"):
        append(tmp_path, event(artifacts=[f"{index}-" + "x" * 498 for index in range(32)]))
    append(tmp_path, event())
    monkeypatch.setattr(metrics, "MAX_JOURNAL_BYTES", 1)
    with pytest.raises(metrics.MetricsError, match="journal_limit_exceeded"):
        metrics.summarize(tmp_path)


def test_empty_and_missing_journal_are_not_successful_zero_latency(tmp_path):
    missing = metrics.summarize(tmp_path)
    assert missing["integrity"]["status"] == "incomplete"
    path = tmp_path / "events.jsonl"
    path.touch(mode=0o600)
    empty = metrics.summarize(tmp_path)
    assert empty["integrity"]["status"] == "complete"
    assert empty["groups"] == [] and empty["attempts"]["uniqueAttempts"] == 0
    assert empty["attempts"]["usage"]["inputTokens"]["total"] is None


def test_stratified_index_is_deterministic_content_free_and_references_records(tmp_path):
    artifact = tmp_path / "actual-records.json"
    artifact.write_text(json.dumps({"records": [{"id": f"record-{i}", "body": "PRIVATE BODY NOT FOR INDEX"} for i in range(8)]}))
    for index in range(8):
        append(tmp_path, event(f"sample-{index}", kind="record", cohort="primary" if index < 4 else "fallback",
                               sample={"recordId": f"record-{index}", "artifact": artifact.name, "recordType": "candidate", "decision": "HOLD"}))
    first = metrics.summarize(tmp_path)["sampleIndex"]
    second = metrics.summarize(tmp_path)["sampleIndex"]
    assert first == second
    assert first["populationN"] == 8 and first["selectedN"] == 6
    assert len(first["strata"]) == 2
    assert all(record["artifactExists"] for item in first["strata"] for record in item["records"])
    assert "PRIVATE BODY" not in json.dumps(first)
    assert first["humanLabels"] == "unmeasured"


def test_actual_cli_summary_smoke_preserves_journal_and_refuses_overwrite(tmp_path):
    append(tmp_path, event("ok", durationMs=12, durationProvenance="cli_wall", counts={"prepared": 1}))
    append(tmp_path, event("failed", status="error", reasonCode="schema_invalid", durationMs=20, durationProvenance="cli_wall"))
    before = (tmp_path / "events.jsonl").read_bytes()
    command = [sys.executable, "-B", str(PIPELINE / "scripts/overnight_metrics.py"), "summarize", "--root", str(tmp_path), "--output", "summary.json"]
    done = subprocess.run(command, capture_output=True, text=True, timeout=30, env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"})
    assert done.returncode == 0 and done.stderr == ""
    result = json.loads(done.stdout)
    assert result["groups"][0]["statusCounts"]["error"] == 1
    assert result["provenance"]["networkCalls"] == 0
    assert result == json.loads((tmp_path / "summary.json").read_text())
    assert (tmp_path / "events.jsonl").read_bytes() == before
    again = subprocess.run(command, capture_output=True, text=True, timeout=30, env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"})
    assert again.returncode == 2 and json.loads(again.stdout)["error"] == "metrics_io_error"
    with (tmp_path / "events.jsonl").open("ab") as stream:
        stream.write(b'{"unfinished":')
    partial = subprocess.run(command[:-2], capture_output=True, text=True, timeout=30, env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"})
    assert partial.returncode == 2
    assert json.loads(partial.stdout)["integrity"]["partialTail"]["bytes"] == 14


def test_observed_machine_context_preserves_concurrent_load_caveat(tmp_path):
    context = {"machine": "AppleM5", "cpuCount": 10, "memoryBytes": 25769803776, "platform": "darwin27.2",
               "architecture": "arm64", "powerSource": "ac", "batteryPercent": 80, "concurrentWorkloads": True,
               "concurrency": 1, "load1": 3.2, "load5": None, "load15": None}
    append(tmp_path, event(kind="context", context=context))
    result = metrics.summarize(tmp_path)
    assert result["contexts"][0]["context"] == context
    assert result["groups"] == []
    with pytest.raises(metrics.MetricsError, match="event_context_invalid"):
        append(tmp_path, event("invalid-context", context={"concurrentWorkloads": 1}))
