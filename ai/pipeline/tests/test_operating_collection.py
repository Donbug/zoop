"""Authored public collection artifacts exercise local registration and durable recovery."""
from __future__ import annotations

from copy import deepcopy
import json
import os
import socket
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from subprocess import Popen

import pytest

from scripts.collection_smoke import CollectionKit, NEWS
from scripts.extraction_smoke import Kit
from scripts.ingestion_smoke import PIPELINE, json_bytes, ownership_env, sha
from scripts.operating_smoke import authored_collection, policy
from zoop_ai_pipeline import extraction, extraction_replay, ingestion, live_budget, operating, operating_collection
from zoop_ai_pipeline.extraction_contracts import ExtractionFailure
from zoop_ai_pipeline.ingestion_contracts import Authority, Export, IngestionFailure, digest
from zoop_ai_pipeline.live_budget import Budget
from zoop_ai_pipeline.live_funding import STAGES


@pytest.fixture
def setup(tmp_path, monkeypatch):
    for key in ("ZOOP_AI_PIPELINE_LIVE_MAX_USD", "ZOOP_AI_PIPELINE_LIVE_MAX_CALLS", "ZOOP_AI_PIPELINE_LIVE_ENABLED",
                "ZOOP_AI_API_KEY", "TYPESAFE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    kit = CollectionKit(tmp_path / "source")
    config = {"schemaVersion": operating.CONFIG, "policy": policy(), "ledgerDirectory": str(tmp_path / "metering"),
        "stateDirectory": str(tmp_path / "native"), "runtime": {"model": "gpt-6-luna", "effort": "high", "maxOutputTokens": 24000,
            "openaiEndpoint": "https://synthetic.invalid/v1", "verifierEndpoint": "https://synthetic.invalid/v1", "verifierModel": "jev-1.14.0"}}
    owner = operating.Owner(config, initialize=True)

    def forbidden(*args, **kwargs):
        pytest.fail("registration crossed an acquisition/model/process boundary")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(Budget, "reserve", forbidden)
    return kit, owner, config


def exported(kit, ref):
    store = ingestion.Store(kit.root / "ingestion", existing=True)
    try:
        return ingestion.Ingestor(store, Authority(kit.registry_path)).export(Export.model_validate({"schemaVersion": "zoop-ingestion-s2-1", **ref}), require_store=True)
    finally:
        store.close()


@pytest.mark.parametrize("count", [3, 50])
def test_cli_registers_exact_all_target_inputs_and_replays_without_calls(setup, tmp_path, capsys, count):
    kit, owner, config = setup
    batch = authored_collection(kit, bodies=(NEWS,) * count)
    config_path, batch_path = tmp_path / "config.json", tmp_path / "batch.json"
    config_path.write_bytes(json_bytes(config))
    batch_path.write_bytes(json_bytes(batch))
    originals = {path: path.read_bytes() for path in kit.inputs.rglob("*") if path.is_file()}
    assert operating.main(["register-collection", "--config", str(config_path), "--batch", str(batch_path)]) == 0
    first = json.loads(capsys.readouterr().out)
    second = owner.register_collection(batch)
    assert first["status"] == second["status"] == "registered"
    assert first["manifest"] == second["manifest"]
    assert first["registration"] == {"registered": [unit["setId"] for unit in batch["sets"]], "interruptedSetId": None, "notAttempted": []}
    assert first["ingestion"]["counts"]["discoveredCandidates"] == first["ingestion"]["counts"]["textReady"] == count
    assert first["ingestion"]["checkedWindow"] is None and first["ingestion"]["checkpoint"]["through"] is None
    assert len(first["ingestion"]["documentRefs"]) == count and first["ingestion"]["pagination"]["nextOffset"] is None
    assert len(owner.budget.sets()) == count and owner.budget.snapshot()["calls"] == 0
    for index, unit in enumerate(first["manifest"]["sets"]):
        ref = unit["extraction"]["incoming"]
        document = exported(kit, ref)
        assert (ref["roundId"], ref["page"], ref["ordinal"]) == ("batch", 0, index)
        assert document["observation"]["collection"]["published"]["precision"] == ["unknown", "day", "unresolved"][index % 3]
        assert document["observation"]["publisher"] == "Authored Synthetic Publisher"
        with owner.native(unit, "s2") as store:
            assert store.one("SELECT state FROM jobs WHERE job_id=?", (unit["extraction"]["jobId"],))["state"] == "queued"
            assert store.one("SELECT COUNT(*) n FROM calls")["n"] == 0
    assert not owner.directory("s3").exists()
    assert {path: path.read_bytes() for path in originals} == originals


@pytest.mark.parametrize("damage", ["partial", "unknown", "wrapper", "result-pin", "manifest-pin", "page-pin", "inventory", "missing"])
def test_unusable_producer_artifacts_refuse_before_intent_or_ingestion(setup, damage):
    kit, owner, _ = setup
    batch = authored_collection(kit)
    path = kit.inputs / batch["collection"]["file"]
    result = json.loads(path.read_bytes())
    if damage in {"partial", "unknown"}:
        result["state"] = damage
    elif damage == "wrapper":
        result["manifestPath"] = str(path.parent / "manifest.json")
    elif damage == "manifest-pin":
        result["manifest"]["sha256"] = "0" * 64
    elif damage == "page-pin":
        (path.parent / "page-0.json").write_bytes(b"{}")
    elif damage == "inventory":
        result["targets"].reverse()
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(json_bytes(result))
        batch["collection"]["sha256"] = "0" * 64 if damage == "result-pin" else sha(path.read_bytes())
    result = owner.register_collection(batch)
    assert set(result) == {"schemaVersion", "error"}
    assert owner.budget.bound(operating_collection.Request.model_validate(batch).binding_name) is None
    assert owner.budget.sets() == [] and not (kit.root / "ingestion").exists()


@pytest.mark.parametrize("failure", ["held", "missing-body", "bad-receipt", "grant-revision"])
def test_native_nonready_inventory_is_reported_without_subset_registration(setup, failure, tmp_path, capsys):
    kit, owner, config = setup
    batch = authored_collection(kit, bodies=(NEWS, b"<html><body>no article</body></html>" if failure == "held" else NEWS))
    path = kit.inputs / batch["collection"]["file"]
    stored = json.loads(path.read_bytes())
    if failure == "missing-body":
        (path.parent / "bodies" / f'{stored["targets"][0]["bodySha256"]}.bin').unlink()
    elif failure == "bad-receipt":
        (path.parent / "receipts" / f'{stored["targets"][1]["receiptSha256"]}.json').write_bytes(b"{}")
    elif failure == "grant-revision":
        kit.registry["sources"][0]["grant"]["revision"] = "new-rights"
        kit.save_registry()
    config_path, batch_path = tmp_path / "config.json", tmp_path / "batch.json"
    config_path.write_bytes(json_bytes(config))
    batch_path.write_bytes(json_bytes(batch))
    assert operating.main(["register-collection", "--config", str(config_path), "--batch", str(batch_path)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "incomplete" and result["manifest"] is None
    assert result["ingestion"]["counts"]["discoveredCandidates"] == 2
    assert len(result["ingestion"]["documentRefs"]) == 2 and result["registration"]["registered"] == []
    assert owner.budget.sets() == [] and owner.budget.snapshot()["calls"] == 0
    if failure == "held":
        assert result["ingestion"]["state"] == "complete" and result["ingestion"]["counts"]["held"] == 1
        assert owner.register_collection(batch)["ingestion"]["documentRefs"] == result["ingestion"]["documentRefs"]
    else:
        assert result["ingestion"]["state"] == "incomplete"
        assert result["error"]["code"] == result["ingestion"]["failure"]["code"]


@pytest.mark.parametrize("boundary", ["page", "raw", "prepared"])
def test_hard_ingestion_interruption_resumes_same_round_and_candidates(setup, monkeypatch, boundary):
    kit, owner, _ = setup
    batch = authored_collection(kit)
    with monkeypatch.context() as patch:
        if boundary == "raw":
            def interrupted(*args, **kwargs):
                raise SystemExit(75)
            patch.setattr(ingestion.parsers, "prepare", interrupted)
        else:
            name = "_receive_page" if boundary == "page" else "_candidate"
            original = getattr(ingestion.Ingestor, name)
            def interrupted(*args, **kwargs):
                original(*args, **kwargs)
                raise SystemExit(75)
            patch.setattr(ingestion.Ingestor, name, interrupted)
        with pytest.raises(SystemExit):
            owner.register_collection(batch)
    assert owner.budget.sets() == []
    result = owner.register_collection(batch)
    assert result["status"] == "registered"
    store = ingestion.Store(kit.root / "ingestion", existing=True)
    try:
        assert store.one("SELECT COUNT(*) n FROM rounds")["n"] == 1
        assert store.one("SELECT COUNT(*) n FROM candidates")["n"] == 3
        assert store.one("SELECT COUNT(*) n FROM raw_versions")["n"] == 3
        assert json.loads(store.one("SELECT request FROM rounds")["request"])["checkpointRevision"] == 0
    finally:
        store.close()


def test_partial_admission_binds_every_field_and_recovers_original_ids(setup, monkeypatch):
    kit, owner, _ = setup
    batch = authored_collection(kit)
    freeze = extraction.Extractor.freeze
    with monkeypatch.context() as patch:
        def interrupt(engine, request, fixtures):
            if request.job_id == "batch-s2-1":
                raise ExtractionFailure("synthetic_freeze_interruption")
            return freeze(engine, request, fixtures)
        patch.setattr(extraction.Extractor, "freeze", interrupt)
        result = owner.register_collection(batch)
    assert result["registration"] == {"registered": ["batch-set-0"], "interruptedSetId": "batch-set-1", "notAttempted": ["batch-set-2"]}
    assert [entry["id"] for entry in owner.budget.sets()] == ["batch-set-0", "batch-set-1"]
    assert owner.budget.bound("native:batch-set-1:s2") is None
    mutations = [("promptVersion", "different"), ("roundId", "different"), ("checkpointRevision", 1),
                 ("snapshot", {"revision": "different", "events": []}), ("topic", {"producerVersion": "zoop-topic-replay-producer-1"}),
                 ("ingestionStateDirectory", str(kit.root / "other-ingestion"))]
    changed_requests = [{**deepcopy(batch), key: value} for key, value in mutations]
    for key in ("setId", "extractionJobId", "relationJobId"):
        changed = deepcopy(batch)
        changed["sets"][1][key] = "replacement"
        changed_requests.append(changed)
    changed = deepcopy(batch)
    changed["sets"][1]["stageAllowances"]["extract"] += 1
    changed_requests.append(changed)
    changed = deepcopy(batch)
    changed["collection"]["sha256"] = "0" * 64
    changed_requests.append(changed)
    before = owner.budget.sets()
    for changed in changed_requests:
        assert owner.register_collection(changed)["error"]["code"] == "operating_collection_input_conflict"
        assert owner.budget.sets() == before
    assert owner.register_collection(batch)["status"] == "registered"
    assert len(owner.budget.sets()) == 3 and owner.budget.snapshot()["calls"] == 0


@pytest.mark.parametrize("operation", ["read", "store", "quote-display"])
def test_existing_jobs_recheck_current_rights_and_withhold_metadata(setup, operation):
    kit, owner, _ = setup
    batch = authored_collection(kit)
    assert owner.register_collection(batch)["status"] == "registered"
    before = owner.budget.sets()
    kit.registry["sources"][0]["grant"]["allowedOperations"].remove(operation)
    kit.save_registry()
    assert owner.register_collection(batch) == {"schemaVersion": operating_collection.RESULT,
        "error": {"code": "source_unauthorized"}, "localProgressMayExist": True}
    assert owner.budget.sets() == before


def test_registry_change_after_registration_suppresses_durable_prefix(setup, monkeypatch):
    kit, owner, _ = setup
    batch = authored_collection(kit)
    register = owner._register
    def revoke_after_first(unit, token):
        register(unit, token)
        kit.registry["sources"][0]["grant"]["enabled"] = False
        kit.save_registry()
    monkeypatch.setattr(owner, "_register", revoke_after_first)
    result = owner.register_collection(batch)
    assert result == {"schemaVersion": operating_collection.RESULT, "error": {"code": "registry_changed"}, "localProgressMayExist": True}
    assert [entry["id"] for entry in owner.budget.sets()] == ["batch-set-0"]


def batch_with_snapshot(kit, owner):
    source = deepcopy(kit.registry["sources"][0])
    source["sourceId"] = source["grant"]["sourceId"] = "snapshot-source"
    source["grant"]["grantId"] = "snapshot-grant"
    kit.registry["sources"].append(source)
    kit.save_registry()
    history = authored_collection(kit, "history", bodies=(NEWS,), source_id="snapshot-source")
    first = owner.register_collection(history)
    ref = first["manifest"]["sets"][0]["extraction"]["incoming"]
    article = extraction_replay.article(exported(kit, ref), True)
    mention = Kit.mention(kit, article, "history-mention", [Kit.evidence(article, "둘째 문단")])
    batch = authored_collection(kit)
    batch["snapshot"] = {"revision": "history-1", "events": [Kit.event("history-event", [(ref, mention)])]}
    return batch, source


def test_snapshot_rights_are_rechecked_on_registered_job_replay(setup):
    kit, owner, _ = setup
    batch, source = batch_with_snapshot(kit, owner)
    assert owner.register_collection(batch)["status"] == "registered"
    source["grant"]["allowedOperations"].remove("store")
    kit.save_registry()
    result = owner.register_collection(batch)
    assert result == {"schemaVersion": operating_collection.RESULT, "error": {"code": "source_unauthorized"}, "localProgressMayExist": True}


def test_paused_new_batch_refuses_but_exact_registered_replay_preserves_control_and_jobs(setup):
    kit, owner, _ = setup
    batch = authored_collection(kit)
    owner.budget.control("pause", "synthetic-maintenance")
    assert owner.register_collection(batch)["error"]["code"] == "operating_paused"
    assert not (kit.root / "ingestion").exists()
    owner.budget.control("resume", "synthetic-maintenance-finished")
    first = owner.register_collection(batch)
    unit = first["manifest"]["sets"][0]
    with owner.native(unit, "s2") as store:
        store.db.execute("UPDATE jobs SET state='reconciling',failure='synthetic-unknown' WHERE job_id=?", (unit["extraction"]["jobId"],))
    owner.budget.control("stop", "synthetic-finish-admitted")
    before = owner.budget.snapshot()
    assert owner.register_collection(batch)["status"] == "registered"
    assert owner.budget.snapshot() == before
    with owner.native(unit, "s2") as store:
        row = store.one("SELECT state,failure FROM jobs WHERE job_id=?", (unit["extraction"]["jobId"],))
        assert (row["state"], row["failure"]) == ("reconciling", "synthetic-unknown")


def test_expanded_manifest_enforces_twenty_megabytes_before_set_admission(setup):
    kit, owner, _ = setup
    batch = authored_collection(kit, bodies=(NEWS,) * 50)
    batch["catalogue"]["companies"][0]["aliases"] = ["a" * 450_000]
    assert len(json_bytes(batch)) < 2_000_000
    result = owner.register_collection(batch)
    assert result["status"] == "incomplete" and result["error"]["code"] == "operating_input_limit"
    assert result["ingestion"]["counts"]["textReady"] == 50
    assert result["manifest"] is None and owner.budget.sets() == []


def test_complete_native_round_with_identity_ambiguity_registers_no_subset(setup):
    kit, owner, _ = setup
    assert owner.register_collection(authored_collection(kit, "earlier", bodies=(NEWS,)))["status"] == "registered"
    batch = authored_collection(kit)
    batch["checkpointRevision"] = 1
    before = owner.budget.sets()
    result = owner.register_collection(batch)
    assert result["status"] == "incomplete" and result["error"]["code"] == "operating_collection_observations_incomplete"
    assert result["ingestion"]["state"] == "complete" and result["ingestion"]["counts"]["textReady"] == 3
    assert result["ingestion"]["documentRefs"][0]["ambiguity"] == "source_identity_ambiguous"
    assert result["manifest"] is None and result["registration"]["registered"] == []
    assert owner.budget.sets() == before


@pytest.mark.parametrize("namespace", ["collection-input", "metering", "foreign-context"])
def test_namespace_and_bound_context_refuse_before_other_ingestion_writes(setup, namespace):
    kit, owner, config = setup
    batch = authored_collection(kit)
    if namespace == "collection-input":
        batch["ingestionStateDirectory"] = str(kit.inputs / "other-state")
    elif namespace == "metering":
        batch["ingestionStateDirectory"] = config["ledgerDirectory"] + "/other-state"
    else:
        assert owner.register_collection(batch)["status"] == "registered"
        batch = authored_collection(kit, "another")
        batch["ingestionStateDirectory"] = str(kit.root / "other-state")
    result = owner.register_collection(batch)
    assert result["error"]["code"] == ("operating_source_context_changed" if namespace == "foreign-context" else "operating_namespace_conflict")
    assert owner.budget.bound(operating_collection.Request.model_validate(batch).binding_name) is None
    assert not (kit.inputs / "other-state").exists() and not (kit.root / "other-state").exists()


def test_crash_wal_with_snapshot_recovers_before_exact_export(setup):
    kit, owner, config = setup
    batch, _ = batch_with_snapshot(kit, owner)
    code = """
import json, os, socket, subprocess, sys
from zoop_ai_pipeline import ingestion, operating
from zoop_ai_pipeline.live_budget import Budget
def deny(*args, **kwargs):
    raise AssertionError("registration crossed an acquisition/model/process boundary")
socket.socket.connect = deny
socket.create_connection = deny
subprocess.Popen = deny
Budget.reserve = deny
original = ingestion.Ingestor._candidate
def crash(*args, **kwargs):
    original(*args, **kwargs)
    os._exit(75)
ingestion.Ingestor._candidate = crash
payload = json.load(sys.stdin)
result = operating.Owner(payload["config"]).register_collection(payload["batch"])
raise AssertionError(result)
"""
    environment = {"PATH": os.environ.get("PATH", ""), "HOME": os.path.expanduser("~"),
                   "PYTHONDONTWRITEBYTECODE": "1", **ownership_env()}
    # Only the test harness launches this child; the child retains its own process/send tripwires.
    child = Popen([sys.executable, "-c", code], cwd=PIPELINE, env=environment,
                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, stderr = child.communicate(json_bytes({"config": config, "batch": batch}), timeout=60)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()
        raise
    assert child.returncode == 75 and stdout == b"", (child.returncode, stdout, stderr)
    assert (kit.root / "ingestion" / "ingestion.sqlite3-wal").stat().st_size > 0
    with pytest.raises(IngestionFailure, match="ingestion_recovery_required"):
        ingestion.Store(kit.root / "ingestion", existing=True)
    binding_name = operating_collection.Request.model_validate(batch).binding_name
    intent = owner.budget.bound(binding_name)
    assert intent == {"schemaVersion": operating_collection.REQUEST,
                      "requestDigest": digest(operating_collection.Request.model_validate(batch).wire())}
    result = owner.register_collection(batch)
    assert result["status"] == "registered"
    assert result["manifest"]["sets"][0]["extraction"]["snapshot"] == batch["snapshot"]
    assert owner.budget.bound(binding_name) == intent
    assert owner.register_collection(batch)["manifest"] == result["manifest"]
    store = ingestion.Store(kit.root / "ingestion", existing=True)
    try:
        assert store.one("SELECT COUNT(*) n FROM rounds")["n"] == 2
        assert store.one("SELECT COUNT(*) n FROM candidates WHERE round='batch'")["n"] == 3
        assert store.one("SELECT COUNT(*) n FROM raw_versions")["n"] == 4
        saved = json.loads(store.one("SELECT request FROM rounds WHERE id='batch'")["request"])
        assert (saved["roundId"], saved["checkpointRevision"]) == ("batch", 0)
    finally:
        store.close()
    assert len(owner.budget.sets()) == 4 and owner.budget.snapshot()["calls"] == 0


@pytest.mark.parametrize("mode,code", [
    ("pause", "operating_paused"), ("stop", "operating_stopping"), ("deadline", "operating_deadline"),
])
def test_mixed_replay_finishes_admitted_prefix_under_closed_admission(setup, tmp_path, monkeypatch, mode, code):
    kit, owner, config = setup
    deadline = datetime.now(UTC) + timedelta(minutes=5)
    if mode == "deadline":
        config = deepcopy(config)
        config["ledgerDirectory"] = str(tmp_path / "deadline-metering")
        config["stateDirectory"] = str(tmp_path / "deadline-native")
        config["policy"]["lifecycle"] = {"kind": "deadline", "until": deadline.isoformat()}
        owner = operating.Owner(config, initialize=True)
    batch = authored_collection(kit)
    freeze = extraction.Extractor.freeze
    with monkeypatch.context() as patch:
        def interrupt(engine, request, fixtures):
            if request.job_id == "batch-s2-1":
                raise ExtractionFailure("synthetic_freeze_interruption")
            return freeze(engine, request, fixtures)
        patch.setattr(extraction.Extractor, "freeze", interrupt)
        first = owner.register_collection(batch)
    assert first["registration"] == {"registered": ["batch-set-0"], "interruptedSetId": "batch-set-1", "notAttempted": ["batch-set-2"]}
    assert owner.budget.bound("native:batch-set-1:s2") is None
    if mode == "deadline":
        monkeypatch.setattr(live_budget.time, "time", lambda: deadline.timestamp() + 1)
    else:
        owner.budget.control(mode, "synthetic-close-admission")
    before, attempts, sets = owner.budget.snapshot(), owner.budget.attempts(), owner.budget.sets()
    result = owner.register_collection(batch)
    assert result["status"] == "incomplete" and result["error"] == {"code": code}
    assert result["registration"] == {"registered": ["batch-set-0", "batch-set-1"],
                                      "interruptedSetId": "batch-set-2", "notAttempted": []}
    assert owner.budget.snapshot() == before and owner.budget.attempts() == attempts
    assert owner.budget.sets() == sets
    assert owner.budget.bound("native:batch-set-1:s2")["jobId"] == "batch-s2-1"
    assert owner.budget.bound("job:batch-s2-2") is None and owner.budget.bound("job:batch-s3-2") is None
    with owner.native(first["manifest"]["sets"][1], "s2") as store:
        assert store.one("SELECT state FROM jobs WHERE job_id='batch-s2-1'")["state"] == "queued"
        assert store.one("SELECT COUNT(*) n FROM jobs")["n"] == 2
        assert store.one("SELECT COUNT(*) n FROM calls")["n"] == 0
