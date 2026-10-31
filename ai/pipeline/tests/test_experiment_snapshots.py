"""Real temporary producer files and a live WAL ledger; no production-root access."""
from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))
from scripts import experiment_snapshots as snapshots
from scripts import overnight_metrics as journal

START = snapshots.instant("2026-10-28T07:00:00Z")
CUTOFF = snapshots.instant("2026-10-28T08:30:00Z")


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    temporary.write_bytes(json.dumps(value, sort_keys=True).encode())
    os.replace(temporary, path)


def load(path):
    return json.loads(path.read_bytes())


def pin(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def event(root, key="a1", **changes):
    value = {"eventId": "event-" + key, "runId": "test-run", "cohort": "luna", "phase": "extract", "unitId": "unit-a",
             "sourceId": "source-a", "status": "ok", "kind": "attempt", "attemptId": key,
             "attemptState": "received", "requestedModel": "gpt-test", "reportedModel": "gpt-test",
             "startUtc": "2026-10-28T07:00:00Z", "endUtc": "2026-10-28T07:00:01Z",
             "durationMs": 10, "durationProvenance": "http_request",
             "usage": {"inputTokens": 100, "outputTokens": 20, "cachedTokens": 60, "reasoningTokens": 5},
             "cost": {"estimatedNanoUsd": 100, "chargedNanoUsd": 100}, **changes}
    journal.record_event(root / "events.jsonl", value)


def reserve(db, key="a1", *, state="settled", charged=100, known=1, bucket="shared", receipt=True, stage="extract", cache_write=25):
    db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?,?,?,?,?)", (key, stage, "test-provider", "digest", state, 500, charged, known, "2026-10-28T07:00:00Z", "2026-10-28T07:00:01Z"))
    db.execute("INSERT INTO reservation_funding VALUES(?,?,?)", (key, "test-" + bucket, bucket))
    if receipt:
        payload = {"usage": {"inputTokens": 100, "outputTokens": 20, "cachedTokens": 60, "reasoningTokens": 5},
                   "cost": {"estimatedUsd": "0.000000100", "chargedUsd": "0.000000100"},
                   "model": {"requested": "gpt-test", "reported": "gpt-test"},
                   "timing": {"durationMs": 10, "provenance": "http-transport-monotonic"},
                   "http": {"bodyText": json.dumps({"usage": {"prompt_tokens_details": {"cache_write_tokens": cache_write}},
                                                   "prompt_cache_retention": "24h", "privateArticleBody": "PRIVATE_BODY_SENTINEL",
                                                   "answers": {"claim-0": {"type": "choice", "choice": "supported", "confidence": .7,
                                                                          "probabilities": {"supported": .95, "insufficient": .04, "contradicted": .01}}}})}}
        db.execute("INSERT INTO provider_invocations VALUES(?,?,?,?,?)", ("logical-" + key, "set-1", stage, "digest", "identity"))
        db.execute("INSERT INTO provider_attempts VALUES(?,?,?,?,?,?,?,?)", (key, "logical-" + key, 1, "luna", "digest", "received", json.dumps(payload), None))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("snapshot attempted network")
    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(socket, "getaddrinfo", fail)


@pytest.fixture
def run(tmp_path):
    tmp_path.chmod(0o700)
    (tmp_path / "modelbudget").mkdir()
    db = sqlite3.connect(tmp_path / "modelbudget/live-budget.sqlite3", isolation_level=None)
    assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    db.execute("PRAGMA wal_autocheckpoint=0")
    db.executescript("""
        CREATE TABLE meta(key TEXT PRIMARY KEY, value INTEGER);
        INSERT INTO meta VALUES('max_nano',20000000000),('max_calls',1000),('bucket_shared',10000000000),('bucket_personal',10000000000);
        CREATE TABLE reservations(attempt_id TEXT PRIMARY KEY,stage TEXT,recipient TEXT,request_digest TEXT,state TEXT,reserved_nano INTEGER,charged_nano INTEGER,usage_known INTEGER,created_at TEXT,updated_at TEXT);
        CREATE TABLE reservation_funding(attempt_id TEXT PRIMARY KEY,account_role TEXT,bucket TEXT);
        CREATE TABLE admitted_sets(set_id TEXT PRIMARY KEY,state TEXT,admitted_at TEXT,finished_at TEXT);
        CREATE TABLE provider_invocations(logical_id TEXT PRIMARY KEY,set_id TEXT,stage TEXT,prepared_digest TEXT,binding_identity TEXT);
        CREATE TABLE provider_attempts(attempt_id TEXT PRIMARY KEY,logical_id TEXT,ordinal INTEGER,profile TEXT,request_digest TEXT,state TEXT,receipt TEXT,error TEXT);
        INSERT INTO admitted_sets VALUES('set-1','admitted','2026-10-28T07:00:00Z',NULL);
    """)
    reserve(db)
    event(tmp_path)
    record = tmp_path / "collection/records/a.json"
    atomic(record, {"extractionBackend": "defuddle", "prepared": {"text": "PRIVATE_BODY_SENTINEL"}})
    native = tmp_path / "collection/records/b.json"
    atomic(native, {"documentVersion": "doc-v1", "body": "PRIVATE_BODY_SENTINEL"})
    counts = {"discovered": 5, "fetched": 3, "prepared": 2, "newCollection": 1, "reused": 1, "requests": 4, "bytes": 800}
    source = {"sourceId": "source-a", "adapterSourceIds": ["source-a"], "status": "partial", "attemptStatus": "attempted", "counts": counts,
              "coverage": [{"freshness": "fresh", "planId": "plan-fresh", "counts": {"discovered": 3, "fetched": 2, "prepared": 1}},
                           {"freshness": "backfill", "planId": "plan-old", "counts": {"discovered": 2, "fetched": 1, "prepared": 1}}]}
    atomic(tmp_path / "collection/INDEX.json", {"runId": "test-run", "status": "running", "checkpointId": "checkpoint-1", "publishedAt": "2026-10-28T07:00:00Z",
        "sourceMatrix": [source], "privateItems": [{"sourceId": "source-a", "recordPath": str(record), "recordSha256": pin(record), "privateId": "private-a"}],
        "nativeItems": [{"sourceId": "source-a", "exportPath": str(native), "fileSha256": pin(native), "documentVersion": "doc-v1"}],
        "observations": [{"durationMs": 100, "durationProvenance": "cli_wall"}, {"durationMs": None, "durationProvenance": "cli_wall"}]})
    atomic(tmp_path / "collection/SOURCE_ADMISSION.json", {"sources": [source]})
    atomic(tmp_path / "collection/LEDGER.json", {"startedAt": "2026-10-28T07:00:00Z", "endedAt": None,
        "plans": {"plan-fresh": {"status": "running", "summary": {"extractionBackendCounts": {"defuddle": 2, "deepseek-fetch": 1}}}}})
    atomic(tmp_path / "control/queue.json", {"unit-a": {"state": "started", "cohort": "luna", "setId": "set-1",
        "unit": {"unitId": "unit-a", "sourceId": "source-a"}}})
    atomic(tmp_path / "control/CHECK.json", {"pins": {"runtimeBindings": {"luna": {"pipeline": {"identity": "runtime-1", "stages": {"extract": {"promptVersion": "prompt-1"}},
        "verifier": {"policy": {"choiceProbability": .9, "choiceConfidence": .8}}}}}}})
    yield tmp_path, db
    db.close()


def finish(root, db):
    index = load(root / "collection/INDEX.json")
    index["status"] = "finished"
    atomic(root / "collection/INDEX.json", index)
    ledger = load(root / "collection/LEDGER.json")
    ledger["endedAt"] = "2026-10-28T08:31:00Z"
    atomic(root / "collection/LEDGER.json", ledger)
    atomic(root / "control/RUN.json", {"finishedAt": "2026-10-28T08:31:00Z", "finalization": {"scope": "controller-owned-sets", "outstandingSharedSets": 0}})
    db.execute("UPDATE admitted_sets SET state='completed',finished_at='2026-10-28T08:31:00Z'")


def graph(root, unit="unit-a", version="version-a"):
    queue = load(root / "control/queue.json")
    queue[unit] = {"state": "started", "cohort": "luna", "setId": "set-1", "unit": {"unitId": unit, "sourceId": "source-a"},
                   "graph": {"status": "projected", "versionId": version, "publication": "not-published"}}
    atomic(root / "control/queue.json", queue)
    directory = root / "analysis/luna" / unit
    atomic(directory / "graph-read.json", {"versionId": version, "publication": "not-published", "delivery": {"status": "current"},
        "verification": {"marker": "matched", "nodes": 2, "edges": 1, "graphDigest": "digest-" + version},
        "digests": {"payload": "payload-" + version}, "evidence": [{"quote": "PRIVATE_BODY_SENTINEL"}],
        "graph": {"nodes": [{"kind": "company", "id": "c1"}, {"kind": "company", "id": "c2"}],
                  "edges": [{"relationId": "local-" + version, "type": "SUPPLIES", "subject": {"kind": "company", "id": "c1"}, "object": {"kind": "company", "id": "c2"}}]}})
    atomic(directory / "graph-read.command.json", {"exitCode": 0})


def test_missing_is_not_zero_and_no_source_database_open(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    def forbidden(*args, **kwargs):
        pytest.fail("missing budget/source databases must not be opened")
    monkeypatch.setattr(snapshots.sqlite3, "connect", forbidden)
    result = snapshots.capture(tmp_path)
    metrics = result["metrics"]
    assert result["status"] == "incomplete"
    assert metrics["collection"]["totals"]["prepared"]["total"] is None
    assert metrics["analysis"]["totals"]["units"] is None
    assert metrics["analysis"]["graph"]["completedVersions"] is None
    assert metrics["providers"]["ledgerAttempts"] is None
    assert metrics["providers"]["journalAttempts"] is None
    assert metrics["providers"]["union"]["attempts"] is None
    assert metrics["providers"]["money"]["total"]["chargedNanoUsd"] is None
    assert metrics["quality"]["accuracy"] is None
    assert not (tmp_path / "modelbudget").exists()


def test_real_wal_is_visible_and_snapshot_selects_do_not_write(run, monkeypatch):
    root, writer = run
    path = root / "modelbudget/live-budget.sqlite3"
    assert path.with_name(path.name + "-wal").stat().st_size > 0
    before = {p.name: pin(p) for p in (path, path.with_name(path.name + "-wal"))}
    real_connect = sqlite3.connect
    statements, actions = [], []
    def connect(database, **kwargs):
        assert database == path.as_uri() + "?mode=ro"
        db = real_connect(database, **kwargs)
        db.set_trace_callback(statements.append)
        def authorize(action, *rest):
            actions.append(action)
            return sqlite3.SQLITE_OK if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_TRANSACTION) else sqlite3.SQLITE_DENY
        db.set_authorizer(authorize)
        return db
    monkeypatch.setattr(snapshots.sqlite3, "connect", connect)
    result = snapshots.read_budget(path)
    assert result["status"] == "complete"
    assert len(result["reservations"]) == 1
    assert result["providerAttempts"][0]["usage"]["cacheWriteTokens"] == 25
    assert statements[0] == "BEGIN" and statements[-1] == "ROLLBACK"
    assert all(not s.lstrip().upper().startswith(("PRAGMA", "INSERT", "UPDATE", "DELETE", "CREATE")) for s in statements)
    assert before == {p.name: pin(p) for p in (path, path.with_name(path.name + "-wal"))}


def test_one_budget_transaction_excludes_midread_commit(run, monkeypatch):
    root, writer = run
    path = root / "modelbudget/live-budget.sqlite3"
    real_connect = sqlite3.connect
    committed = []
    def connect(database, **kwargs):
        db = real_connect(database, **kwargs)
        def trace(statement):
            if statement.startswith("SELECT attempt_id,stage") and not committed:
                reserve(writer, "a2", state="reserved", charged=500, known=0, receipt=False)
                committed.append(True)
        db.set_trace_callback(trace)
        return db
    monkeypatch.setattr(snapshots.sqlite3, "connect", connect)
    first = snapshots.read_budget(path)
    second = snapshots.read_budget(path)
    assert len(first["reservations"]) == 1
    assert len(second["reservations"]) == 2
    assert committed == [True]


def test_ledger_journal_gap_retains_unknown_cost_and_token_denominator(run):
    root, db = run
    reserve(db, "a2", state="reserved", charged=500, known=0, receipt=False, bucket="personal")
    reserve(db, "a3", charged=100, bucket="personal")
    result = snapshots.capture(root)
    providers = result["metrics"]["providers"]
    assert result["status"] == "incomplete"
    assert (providers["ledgerAttempts"], providers["journalAttempts"], providers["physicalProviderAttempts"]) == (3, 1, 2)
    assert providers["ledgerMissingJournal"] == 2 and providers["physicalMissingJournal"] == 1
    assert providers["union"]["attempts"] == 3
    assert providers["union"]["states"]["unknown"] == 1
    assert providers["union"]["usage"]["inputTokens"] == {"knownN": 2, "missingN": 1, "knownTotal": 200, "total": None}
    assert providers["union"]["usage"]["cacheWriteTokens"]["knownTotal"] == 50
    assert providers["union"]["knownUsageEstimatedNanoUsd"]["total"] is None
    assert providers["money"]["total"]["chargedNanoUsd"] == 700
    assert providers["money"]["total"]["reservedNanoUsd"] == 500
    assert providers["money"]["total"]["unknownExposureNanoUsd"] == 500
    assert providers["money"]["personal"]["remainingNanoUsd"] == 10_000_000_000 - 600
    assert providers["invoiceNanoUsd"] is None


def test_cache_write_not_added_to_input_and_raw_verifier_not_effective_truth(run):
    root, db = run
    reserve(db, "verifier", stage="verify-relation", bucket="personal")
    event(root, "verifier", phase="verify-relation")
    metrics = snapshots.capture(root)["metrics"]
    usage = metrics["providers"]["union"]["usage"]
    assert usage["inputTokens"]["total"] == 200
    assert usage["cacheReadTokens"]["total"] == 120
    assert usage["cacheWriteTokens"]["total"] == 50
    assert metrics["providers"]["union"]["cacheRetentionCounts"] == {"24h": 2}
    verdict = metrics["providers"]["verifierGateObservations"]
    assert verdict["rawChoices"] == {"supported": 1}
    assert verdict["belowPinnedThresholdN"] == 1
    assert metrics["quality"]["overHold"] is None
    assert "PRIVATE_BODY_SENTINEL" not in json.dumps(metrics)


def test_partial_usage_is_unknown_not_zero(run):
    root, db = run
    reserve(db, "partial", cache_write=None)
    event(root, "partial")
    result = snapshots.capture(root)["metrics"]["providers"]["union"]["usage"]
    assert result["cacheWriteTokens"] == {"knownN": 1, "missingN": 1, "knownTotal": 25, "total": None}
    assert result["inputTokens"]["total"] == 200


@pytest.mark.parametrize("raw", [1.5, "25", -1, None])
def test_invalid_cache_write_metadata_stays_unknown(run, raw):
    root, db = run
    reserve(db, "invalid-cache", cache_write=raw)
    event(root, "invalid-cache")
    usage = snapshots.capture(root)["metrics"]["providers"]["union"]["usage"]
    assert usage["cacheWriteTokens"]["knownN"] == 1
    assert usage["cacheWriteTokens"]["missingN"] == 1
    assert usage["cacheWriteTokens"]["total"] is None


def test_explicit_usage_rejection_is_not_bypassed_by_raw_cache_write(run):
    root, db = run
    receipt = json.loads(db.execute("SELECT receipt FROM provider_attempts WHERE attempt_id='a1'").fetchone()[0])
    receipt["usage"]["cacheWriteTokens"] = None
    receipt["cost"]["usageRejected"] = "cache_write_invalid"
    db.execute("UPDATE provider_attempts SET receipt=? WHERE attempt_id='a1'", (json.dumps(receipt),))
    providers = snapshots.capture(root)["metrics"]["providers"]
    assert providers["union"]["usage"]["cacheWriteTokens"]["total"] is None
    assert providers["union"]["usageRejectedN"] == 1


def test_cohorts_backends_latency_and_full_source_counts(run):
    root, db = run
    metrics = snapshots.capture(root)["metrics"]
    collection = metrics["collection"]
    assert collection["coverage"]["offered"] == 1
    assert collection["coverage"]["attempted"]["total"] == 1
    assert collection["coverage"]["analysisAdmitted"]["total"] == 1
    assert collection["totals"]["new"]["total"] == 1 and collection["totals"]["reused"]["total"] == 1
    assert collection["totals"]["blocked"]["total"] is None
    assert collection["preparedBackendCounts"] == {"defuddle": 1, "native": 1}
    assert collection["backendAttemptsByPlan"][0]["backendCounts"] == {"defuddle": 2, "deepseek-fetch": 1}
    assert collection["cliDurationMs"] == {"n": 1, "missingN": 1, "p50": 100, "p95": 100}
    assert collection["httpDurationMs"] == {"n": 0, "missingN": 4, "p50": None, "p95": None}
    assert metrics["cumulative"]["collection.cohort.source-a.fresh.plan-fresh.discovered"] == 3
    assert metrics["cumulative"]["collection.cohort.source-a.backfill.plan-old.discovered"] == 2
    assert metrics["analysis"]["runtimeIds"]["luna.pipeline.stages.extract.promptVersion"] == "prompt-1"


def test_mixed_full_window_item_freshness_and_source_counts_are_separate(run):
    root, db = run
    index = load(root / "collection/INDEX.json")
    original = index["privateItems"][0]
    index["itemFreshness"] = {original["recordPath"]: {"freshness": "fresh", "publicationDay": "2026-10-28"}}
    for suffix, category, day in (("old", "backfill", "2026-07-28"), ("reused", "reused", None), ("undated", "unknown", None)):
        path = root / "collection/records" / (suffix + ".json")
        atomic(path, {"extractionBackend": "defuddle", "publicationDay": day, "prepared": {"text": "PRIVATE_BODY_SENTINEL"}})
        index["privateItems"].append({"sourceId": "source-a", "recordPath": str(path), "recordSha256": pin(path), "privateId": suffix})
        index["itemFreshness"][str(path)] = {"freshness": category, "publicationDay": day}
    index["nativeItems"][0]["freshness"] = "backfill"
    source = index["sourceMatrix"][0]
    source["counts"].update(prepared=5, newCollection=4, reused=1, fresh=1, backfill=2, unclassifiedNew=1)
    source["coverage"] = [{"freshness": "unknown", "selectionMode": "fresh-first", "planId": "full-window",
                           "fromDay": "2026-07-28", "throughDay": "2026-10-28", "counts": {"prepared": 5}}]
    atomic(root / "collection/INDEX.json", index)
    first = snapshots.emit(root, "baseline", START, clock=lambda: START)
    collection = first["metrics"]["collection"]
    expected = {"fresh": 1, "backfill": 2, "reused": 1, "unknown": 1}
    assert collection["itemFreshnessCounts"] == expected
    assert collection["sources"][0]["itemFreshnessCounts"] == expected
    assert collection["byCohort"][0]["cohort"] == "unknown"
    assert collection["totals"]["fresh"]["total"] == 1
    assert collection["totals"]["backfill"]["total"] == 2
    assert collection["totals"]["unclassifiedNew"]["total"] == 1
    assert first["metrics"]["referenceSets"]["corpus"]["members"][1]["publicationDay"] == "2026-10-28"
    extra = root / "collection/records/extra.json"
    atomic(extra, {"extractionBackend": "defuddle", "publicationDay": "2026-10-28"})
    index["privateItems"].append({"sourceId": "source-a", "recordPath": str(extra), "recordSha256": pin(extra), "privateId": "extra"})
    index["itemFreshness"][str(extra)] = {"freshness": "fresh", "publicationDay": "2026-10-28"}
    source["counts"].update(prepared=6, newCollection=5, fresh=2)
    atomic(root / "collection/INDEX.json", index)
    tick = START + timedelta(minutes=30)
    later = snapshots.emit(root, "scheduled", tick, clock=lambda: tick)
    delta = later["metrics"]["last30Minutes"]["values"]
    assert delta["collection.itemFreshness.fresh"] == 1
    assert delta["collection.source.source-a.itemFreshness.fresh"] == 1
    assert delta["collection.total.fresh"] == 1
    assert delta["collection.itemFreshness.backfill"] == 0
    assert delta["collection.itemFreshness.reused"] == 0


def test_missing_item_freshness_is_unknown_despite_batch_and_record_date(run):
    root, db = run
    index = load(root / "collection/INDEX.json")
    path = Path(index["privateItems"][0]["recordPath"])
    atomic(path, {"publicationDay": "2026-10-28", "extractionBackend": "defuddle"})
    index["privateItems"][0]["recordSha256"] = pin(path)
    index["privateItems"][0]["freshness"] = "fresh"  # Not the private-item metadata seam.
    index["sourceMatrix"][0]["coverage"] = [{"freshness": "unknown", "selectionMode": "fresh-first", "counts": {"prepared": 2}}]
    atomic(root / "collection/INDEX.json", index)
    metrics = snapshots.capture(root)["metrics"]
    assert metrics["collection"]["itemFreshnessCounts"] == {"fresh": 0, "backfill": 0, "reused": 0, "unknown": 2}
    assert metrics["collection"]["totals"]["fresh"]["total"] is None
    assert metrics["collection"]["totals"]["backfill"]["total"] is None
    assert all(member["freshness"] == "unknown" for member in metrics["referenceSets"]["corpus"]["members"])


def test_immutable_reference_sets_survive_actual_index_and_queue_overwrite(run):
    root, db = run
    index = load(root / "collection/INDEX.json")
    selector = {"schemaVersion": "zoop-ingestion-s2-1", "roundId": "round-a", "sourceId": "source-a",
                "page": 1, "ordinal": 2, "documentId": "doc-a", "rawVersion": "raw-a", "documentVersion": "doc-v1"}
    original = Path(index["nativeItems"][0]["exportPath"])
    index["nativeItems"][0].update(observation=selector, documentId="doc-a", rawVersion="raw-a",
                                   fileRefs=[{"path": str(original), "sha256": pin(original)}])
    index["doNotCopy"] = {"articleBody": "PRIVATE_BODY_SENTINEL", "authConfiguration": "AUTH_CONFIG_SENTINEL"}
    atomic(root / "collection/INDEX.json", index)
    export = root / "processing/unit-a/export.json"
    atomic(export, {"body": "PRIVATE_BODY_SENTINEL", "observation": selector})
    queue = load(root / "control/queue.json")
    queue["unit-a"].update(unitDigest="unit-digest-a", body="PRIVATE_BODY_SENTINEL")
    queue["unit-a"]["unit"].update(observation=selector, export=str(export), exportSha256=pin(export),
        originalPins=[{"path": str(original), "sha256": pin(original)}], importRequest={"secret": "AUTH_CONFIG_SENTINEL"})
    atomic(root / "control/queue.json", queue)
    graph(root)  # Keep existing logical graph manifests under the same queue identity.
    with_graph = load(root / "control/queue.json")
    queue["unit-a"]["graph"] = with_graph["unit-a"]["graph"]
    atomic(root / "control/queue.json", queue)
    index_hash, queue_hash = pin(root / "collection/INDEX.json"), pin(root / "control/queue.json")
    first = snapshots.emit(root, "baseline", START, clock=lambda: START)
    saved = {path.name: path.read_bytes() for path in first["path"].iterdir()}
    refs = first["metrics"]["referenceSets"]
    assert refs["corpus"]["indexSha256"] == index_hash
    assert refs["queue"]["queueSha256"] == queue_hash
    corpus = refs["corpus"]["members"][0]
    assert corpus["observation"] == selector
    assert corpus["artifact"]["path"] == str(original)
    assert corpus["artifact"]["observedSha256"] == pin(original)
    assert corpus["fileRefs"][0]["declaredSha256"] == pin(original)
    selected = refs["queue"]["members"][0]
    assert selected["queueKey"] == "unit-a"
    assert selected["setId"] == "set-1" and selected["unitDigest"] == "unit-digest-a"
    assert selected["observation"] == selector
    assert selected["export"]["path"] == str(export) and selected["export"]["observedSha256"] == pin(export)
    assert selected["originalPins"][0]["path"] == str(original)
    assert selected["originalPins"][0]["observedSha256"] == pin(original)
    for name in ("corpus", "queue"):
        assert refs[name]["sha256"] == snapshots.digest({key: value for key, value in refs[name].items() if key != "sha256"})
    atomic(root / "collection/INDEX.json", {"checkpointId": "replacement", "nativeItems": [], "privateItems": [], "sourceMatrix": [], "observations": []})
    atomic(root / "control/queue.json", {})
    tick = START + timedelta(minutes=30)
    later = snapshots.emit(root, "scheduled", tick, clock=lambda: tick)
    assert later["metrics"]["referenceSets"]["corpus"]["members"] == []
    assert later["metrics"]["referenceSets"]["queue"]["members"] == []
    recovered = next(row for row in snapshots.history(root) if row["manifest"]["kind"] == "baseline")
    assert recovered["metrics"]["referenceSets"] == refs
    assert recovered["metrics"]["analysis"]["graph"]["versions"][0]["versionId"] == "version-a"
    assert saved == {path.name: path.read_bytes() for path in first["path"].iterdir()}
    serialized = json.dumps(recovered["metrics"])
    assert "PRIVATE_BODY_SENTINEL" not in serialized and "AUTH_CONFIG_SENTINEL" not in serialized


def test_atomic_update_between_passes_pins_actual_new_index(run, monkeypatch):
    root, db = run
    original = snapshots.capture_pass
    calls = []
    def updating(path):
        result = original(path)
        calls.append(True)
        if len(calls) == 1:
            index = load(root / "collection/INDEX.json")
            index["sourceMatrix"][0]["counts"]["prepared"] = 7
            index["checkpointId"] = "checkpoint-2"
            atomic(root / "collection/INDEX.json", index)
            atomic(root / "collection/INDEX.sha256", {"sha256": "wrong-generation"})
        return result
    monkeypatch.setattr(snapshots, "capture_pass", updating)
    result = snapshots.capture(root)
    assert result["passes"] == 3 and result["stable"]
    assert result["metrics"]["collection"]["totals"]["prepared"]["total"] == 7
    assert result["vector"]["collection/INDEX.json"]["sha256"] == pin(root / "collection/INDEX.json")
    assert result["vector"]["collection:checkpoint"]["checkpointId"] == "checkpoint-2"
    assert not result["globallyAtomic"]


def test_churning_atomic_producer_yields_stale_bounded_vector(run, monkeypatch):
    root, db = run
    original = snapshots.capture_pass
    def updating(path):
        result = original(path)
        index = load(root / "collection/INDEX.json")
        index["sourceMatrix"][0]["counts"]["prepared"] += 1
        atomic(root / "collection/INDEX.json", index)
        return result
    monkeypatch.setattr(snapshots, "capture_pass", updating)
    result = snapshots.capture(root, repeats=2)
    assert result["status"] == "stale" and result["passes"] == 3
    assert "collection/INDEX.json" in result["changed"]
    assert result["vector"]["collection/INDEX.json"]["sha256"] != pin(root / "collection/INDEX.json")


def test_pin_mismatch_and_partial_journal_are_explicit(run):
    root, db = run
    atomic(root / "collection/records/a.json", {"extractionBackend": "deepseek-fetch"})
    with (root / "events.jsonl").open("ab") as stream:
        stream.write(b'{"unfinished":')
    result = snapshots.capture(root)
    assert result["status"] == "incomplete"
    assert {issue["code"] for issue in result["issues"]} >= {"artifact_pin_mismatch", "journal_incomplete"}
    assert result["metrics"]["journal"]["partialTail"]["bytes"] == 14
    assert result["metrics"]["providers"]["journalAttempts"] is None


def test_same_tick_is_idempotent_and_prior_snapshots_remain_immutable(run):
    root, db = run
    first = snapshots.emit(root, "baseline", START, clock=lambda: START)
    tick = START + timedelta(minutes=30)
    second = snapshots.emit(root, "scheduled", tick, clock=lambda: tick)
    before = {p: p.read_bytes() for row in (first, second) for p in row["path"].iterdir()}
    index = load(root / "collection/INDEX.json")
    index["sourceMatrix"][0]["counts"]["prepared"] = 12
    atomic(root / "collection/INDEX.json", index)
    same = snapshots.emit(root, "scheduled", tick, clock=lambda: tick + timedelta(seconds=5))
    assert same["path"] == second["path"]
    assert len(snapshots.history(root)) == 2
    assert before == {p: p.read_bytes() for p in before}
    assert second["path"].stat().st_mode & 0o777 == 0o500
    assert (second["path"] / "manifest.json").stat().st_mode & 0o777 == 0o400
    assert second["metrics"]["last30Minutes"]["status"] == "observed_adjacent_grid"


def test_missed_ticks_do_not_fabricate_historical_measurements(run):
    root, db = run
    baseline = START + timedelta(minutes=7)
    snapshots.due_rows(root, CUTOFF, clock=lambda: baseline)
    observed = START + timedelta(hours=1, minutes=2)
    rows = snapshots.due_rows(root, CUTOFF, clock=lambda: observed)
    assert len(rows) == 2
    assert [r["manifest"]["scheduledAt"] for r in rows] == ["2026-10-28T07:30:00.000000Z", "2026-10-28T08:00:00.000000Z"]
    assert all(r["manifest"]["status"] == "missed" and r["manifest"]["checkpointVector"] is None and not r["metrics"]["cumulative"] for r in rows)
    assert all(r["manifest"]["observedAt"] == snapshots.stamp(observed) for r in rows)
    assert snapshots.due_rows(root, CUTOFF, clock=lambda: observed) == []


def test_counter_reset_is_not_negative_growth(run):
    root, db = run
    snapshots.emit(root, "baseline", START, clock=lambda: START)
    index = load(root / "collection/INDEX.json")
    index["sourceMatrix"][0]["counts"]["discovered"] = 1
    atomic(root / "collection/INDEX.json", index)
    second = snapshots.emit(root, "scheduled", START + timedelta(minutes=30), clock=lambda: START + timedelta(minutes=30))
    delta = second["metrics"]["sincePreviousSnapshot"]
    assert delta["values"]["collection.total.discovered"] is None
    assert any(i["metric"] == "collection.total.discovered" and i["code"] == "counter_decrease_or_reset" for i in delta["issues"])


def test_graph_manifest_counts_versions_and_unique_identities_without_db_open(run):
    root, db = run
    graph(root)
    graph(root, "unit-b", "version-b")
    (root / "analysis/luna/unit-a/extraction").mkdir()
    (root / "analysis/luna/unit-a/extraction/extraction.sqlite3-wal").write_bytes(b"HOT_UNTOUCHED")
    result = snapshots.capture(root)
    metrics = result["metrics"]["analysis"]["graph"]
    assert (metrics["completedVersions"], metrics["nonemptyVersions"], metrics["versionLocalNodes"], metrics["versionLocalEdges"]) == (2, 2, 4, 2)
    assert (metrics["uniqueNodes"], metrics["uniqueEndpointTypeEdges"]) == (2, 1)
    assert not metrics["publicUse"]
    assert "analysis/luna/unit-a/graph-read.json" in result["vector"]
    assert not any("sqlite3-wal" in key for key in result["vector"])
    assert (root / "analysis/luna/unit-a/extraction/extraction.sqlite3-wal").read_bytes() == b"HOT_UNTOUCHED"
    assert "PRIVATE_BODY_SENTINEL" not in json.dumps(result)


def test_claimed_graph_without_committed_readback_is_unknown_not_zero(run):
    root, db = run
    queue = load(root / "control/queue.json")
    queue["unit-a"]["graph"] = {"status": "projected", "versionId": "unavailable"}
    atomic(root / "control/queue.json", queue)
    result = snapshots.capture(root)
    assert result["status"] == "incomplete"
    assert result["metrics"]["analysis"]["graph"]["completedVersions"] is None
    assert result["metrics"]["analysis"]["graph"]["missingReadbacks"] == 1


def test_analysis_candidates_effective_comparisons_and_private_summaries(run):
    root, db = run
    directory = root / "analysis/luna/unit-a"
    atomic(directory / "s2-result.json", {"counts": {"eventCandidates": {"total": 4}, "topicCandidates": 2, "comparisons": 5,
        "effectiveRelations": {"SAME": 1, "DIFFERENT": 1, "FOLLOWS": 1, "HOLD": 2, "CONFLICT": 0}}, "binding": {"promptVersion": "p2"}})
    atomic(directory / "s3-result.json", {"relations": [{"eligibility": {"status": status}, "history": [{"kind": "verdict", "claims": [{"verdict": "insufficient"}]}]} for status in ("eligible", "hold", "reject")]})
    for stage in ("s2", "s3"):
        atomic(directory / (stage + "-result.command.json"), {"exitCode": 0})
    atomic(directory / "comparison-coverage.json", {"eligibleBeforeDedupAndBounds": 12, "selectedEvents": 5, "selectedMembers": 8})
    atomic(directory / "summary-outcomes.json", {"c1": "available", "c2": "verifier-hold", "c3": "live_response_unknown"})
    result = snapshots.capture(root)["metrics"]["analysis"]
    assert result["totals"]["eventCandidates"]["total"] == 4
    assert result["totals"]["effectiveRelations"]["FOLLOWS"]["total"] == 1
    assert result["totals"]["relationEligibility"]["eligible"]["total"] == 1
    assert result["totals"]["privateSummary"]["error"]["total"] == 1
    assert result["units"][0]["comparisonCoverage"]["selectedEvents"] == 5
    assert result["units"][0]["rawVerdicts"] is None
    assert result["units"][0]["confidenceGate"]["changedN"] is None


def test_cutoff_ongoing_set_then_late_drain_even_zero_delta(run):
    root, db = run
    snapshots.emit(root, "baseline", CUTOFF - timedelta(minutes=30), clock=lambda: CUTOFF - timedelta(minutes=30))
    on_time = snapshots.due_rows(root, CUTOFF, clock=lambda: CUTOFF)[0]
    before = (on_time["path"] / "metrics.json").read_bytes()
    assert on_time["manifest"]["kind"] == "on_time_final"
    assert on_time["metrics"]["owners"]["remainingAdmittedSets"] == 1
    with pytest.raises(ValueError, match="owners_or_admitted_sets_not_finished"):
        snapshots.finalize(root, CUTOFF, clock=lambda: CUTOFF + timedelta(seconds=5))
    finish(root, db)
    late = snapshots.finalize(root, CUTOFF, clock=lambda: CUTOFF + timedelta(minutes=1))
    assert late["manifest"]["kind"] == "late_drain_final"
    assert late["metrics"]["delta_after_cutoff"]["values"]["collection.total.prepared"] == 0
    assert late["metrics"]["delta_after_cutoff"]["cutoffObserved"]
    assert (on_time["path"] / "metrics.json").read_bytes() == before
    assert (on_time["path"] / "analysis.txt").exists() and (late["path"] / "analysis.txt").exists()


def test_watch_crosses_1730_without_signaling_owner_and_closes_later(run):
    root, db = run
    current = [CUTOFF - timedelta(seconds=5)]
    outputs = []
    collection_lock = (root / "collection/.controller.lock").open("w")
    analysis_lock = (root / "control/controller.lock").open("w")
    fcntl.flock(collection_lock, fcntl.LOCK_EX)
    fcntl.flock(analysis_lock, fcntl.LOCK_EX)
    def sleep(seconds):
        current[0] += timedelta(seconds=seconds)
        if current[0] >= CUTOFF + timedelta(seconds=10):
            finish(root, db)
            collection_lock.close()
            analysis_lock.close()
    try:
        result = snapshots.watch(root, CUTOFF, clock=lambda: current[0], sleep=sleep, poll=5, grace=60, owner_grace=20, output=outputs.append)
    finally:
        collection_lock.close()
        analysis_lock.close()
    assert result["manifest"]["kind"] == "late_drain_final"
    rows = snapshots.history(root)
    assert [r["manifest"]["kind"] for r in rows] == ["baseline", "on_time_final", "late_drain_final"]
    assert rows[1]["metrics"]["owners"]["remainingAdmittedSets"] == 1
    assert len(outputs) == 3


def test_watch_reports_dead_owner_and_finite_drain_block(run):
    root, db = run
    current = [CUTOFF - timedelta(seconds=1)]
    def sleep(seconds):
        current[0] += timedelta(seconds=seconds)
    row = snapshots.watch(root, CUTOFF, clock=lambda: current[0], sleep=sleep, poll=5, grace=60, owner_grace=10, output=lambda _: None)
    assert row["manifest"]["kind"] == "drain_blocked"
    assert row["manifest"]["reason"] == "owner_absent_or_crashed"
    assert (current[0] - CUTOFF).total_seconds() == 10
    assert db.execute("SELECT state FROM admitted_sets").fetchone()[0] == "admitted"


def test_late_start_preserves_missing_cutoff_not_fake_historical_row(run):
    root, db = run
    finish(root, db)
    current = CUTOFF + timedelta(hours=1)
    result = snapshots.finalize(root, CUTOFF, clock=lambda: current)
    cutoff = next(r for r in snapshots.history(root) if r["manifest"]["kind"] == "on_time_final")
    assert cutoff["manifest"]["status"] == "missed"
    assert cutoff["manifest"]["observedAt"] == snapshots.stamp(current)
    assert result["metrics"]["delta_after_cutoff"]["cutoffObserved"] is False
    assert result["metrics"]["delta_after_cutoff"]["values"]["collection.total.prepared"] is None


def test_cli_offline_two_numeric_lines_and_source_files_unchanged(run):
    root, db = run
    before = {p: pin(p) for p in root.rglob("*") if p.is_file() and not p.name.endswith("-shm")}
    code = """import runpy,sys
calls=[]
def audit(event,args):
    if event.startswith('socket.'):
        calls.append(event)
        raise RuntimeError('network_forbidden')
sys.addaudithook(audit)
sys.argv=['experiment_snapshots.py','snapshot','--root',sys.argv[1]]
runpy.run_module('scripts.experiment_snapshots',run_name='__main__')
"""
    # The child uses the actual script entry point and an audit hook; no fake CLI.
    result = subprocess.run([sys.executable, "-c", code, str(root)], cwd=PIPELINE, text=True, capture_output=True, check=False,
                            env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 0, result.stderr + result.stdout
    lines = list(csv.reader(io.StringIO(result.stdout)))
    assert len(lines) == 2 and len(result.stdout) < 600
    assert lines[0] == list(snapshots.CSV_KEYS)
    assert lines[1][4:8] == ["5", "2", "1", "1"]
    assert lines[1][-1] == "0"
    assert before == {p: pin(p) for p in before}
    assert "PRIVATE_BODY_SENTINEL" not in "".join(p.read_text() for p in (root / "snapshots").glob("*/*.json"))


def test_append_only_integrity_refuses_corrupted_existing_snapshot(run):
    root, db = run
    row = snapshots.emit(root, "baseline", START, clock=lambda: START)
    path = row["path"] / "metrics.json"
    path.chmod(0o600)
    path.write_text("{}")
    with pytest.raises(ValueError, match="existing_snapshot_integrity_failed"):
        snapshots.emit(root, "scheduled", START + timedelta(minutes=30), clock=lambda: START + timedelta(minutes=30))
