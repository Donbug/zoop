"""Exact monetary authority and non-invasive native capture, using authored state only."""
from __future__ import annotations

import copy
import json
import os
import sqlite3
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE / "scripts"))
import overnight_receipts as receipts
from scripts import overnight_run as runner, overnight_collect as collector
import collection_revision
from overnight_inputs import bind_execution, encoded, file_pin, load, prepare_item, save, sha, verify_item
from tests.live_support import environment
from tests.test_overnight_history import ACTOR, make_original, runtimes
from tests.test_private_processing import exported, retained_fixture
from zoop_ai_pipeline import live_budget, live_funding as funding, live_runtime as live
from zoop_ai_pipeline.ingestion import Store
from zoop_ai_pipeline.ingestion_contracts import MAX_LEDGER_COPY
from zoop_ai_pipeline.live_budget import Budget, BudgetError
from zoop_ai_pipeline.relation_contracts import digest

START, END, FINISH = "2026-10-29T00:00:00Z", "2026-10-29T08:05:00Z", "2026-10-29T08:30:00Z"
CAPS = {"shared": 3_500_000_000, "personal": 500_000_000}


def config(root):
    return {"schemaVersion": "zoop-private-run-4", "runId": "capped-copy-control", "root": str(root),
            "admitFrom": START, "admitUntil": END, "finishBy": FINISH, "graphPort": 32829, "maxCalls": 100000,
            "processingActor": ACTOR, "funding": {"totalMaxUsd": "4", "sharedMaxUsd": "3.5", "personalMaxUsd": "0.5"}}


@pytest.fixture
def capped(tmp_path, monkeypatch):
    clock = ["2026-10-29T01:00:00+00:00"]
    monkeypatch.setattr(live_budget, "_now", lambda: clock[0])
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(clock[0])
    monkeypatch.setattr(funding, "datetime", Clock)
    control = config(tmp_path / "run")
    policy = funding.run_policy(control)
    budget = Budget(Path(control["root"]) / "modelbudget", 4_000_000_000, 100000,
                    funding=policy, bucket_caps=CAPS, finish_by=FINISH)
    budget.admit_set("set-one", "a" * 64, {"extract": 8, "verify-relation": 8, "topic": 8})
    return control, budget, clock


def reserve(budget, name, amount, *, verifier=False):
    role, stage = ("personal-typesafe", "verify-relation") if verifier else ("shared-openai", "extract")
    budget.reserve(name, stage, budget.funding["roles"][role]["recipient"], digest(name), amount,
                   account_role=role, set_id="set-one")


def test_exact_caps_unknown_holds_plus_one_and_drain_deadline(capped):
    control, budget, clock = capped
    reserve(budget, "shared-held", 3_500_000_000)
    with pytest.raises(BudgetError, match="live_budget_exhausted_shared"):
        reserve(budget, "shared-over", 1)
    reserve(budget, "verifier-held", 500_000_000, verifier=True)
    snapshot = budget.snapshot()
    assert snapshot["maxUsd"] == snapshot["chargedUsd"] == "4.000000000"
    assert snapshot["states"] == {"reserved": 2}
    assert snapshot["buckets"]["shared"]["unknownUsd"] == "3.500000000"
    assert snapshot["buckets"]["personal"]["unknownUsd"] == "0.500000000"
    with pytest.raises(BudgetError, match="live_budget_exhausted_usd"):
        reserve(budget, "personal-over", 1, verifier=True)
    assert budget.snapshot()["verificationBlocked"]
    with pytest.raises(BudgetError, match="live_set_reconcile_only"):
        budget.resume_set("set-one", "a" * 64)
    assert budget.snapshot()["chargedUsd"] == "4.000000000"


def test_personal_bucket_plus_one_refuses_without_borrowing_shared(capped):
    _, budget, _ = capped
    reserve(budget, "personal-only", 500_000_000, verifier=True)
    with pytest.raises(BudgetError, match="live_budget_exhausted_personal"):
        reserve(budget, "personal-over", 1, verifier=True)
    assert budget.snapshot()["buckets"]["shared"]["remainingUsd"] == "3.500000000"
    assert budget.snapshot()["chargedUsd"] == "0.500000000"


def test_admitted_set_drains_only_inside_finish_window(capped):
    _, budget, clock = capped
    reserve(budget, "before", 1)
    budget.settle("before", 1)
    clock[0] = "2026-10-29T08:05:00+00:00"
    with pytest.raises(BudgetError, match="live_set_admission_closed"):
        budget.admit_set("late", "b" * 64, {"extract": 1})
    reserve(budget, "drain", 1)
    budget.check_send("drain")
    budget.settle("drain", 1)
    clock[0] = "2026-10-29T08:22:00+00:00"
    with pytest.raises(BudgetError, match="live_finish_deadline"):
        reserve(budget, "too-late", 1)
    assert budget.snapshot()["calls"] == 2


@pytest.mark.parametrize("change", [
    lambda p: p.update(totalMaxNanoUsd=4_000_000_001),
    lambda p: p.update(totalMaxNanoUsd=4.0),
    lambda p: p["bucketMaxNanoUsd"].update(shared=True),
    lambda p: p["bucketMaxNanoUsd"].update(personal=1_000_000),
    lambda p: p.update(totalMaxNanoUsd=20_000_000_001),
    lambda p: p.update(extra="not-authorized"),
    lambda p: p.pop("totalMaxNanoUsd"),
    lambda p: p["bucketMaxNanoUsd"].update(extra=0),
])
def test_policy_mutations_refuse(capped, change):
    policy = copy.deepcopy(capped[1].funding)
    change(policy)
    with pytest.raises(ValueError, match="live_funding_config_invalid"):
        funding.validate_policy(policy)


@pytest.mark.parametrize("amounts", [(20_000_000_000, CAPS), (4_000_000_000, None),
                                     (4_000_000_000, {"shared": 10_000_000_000, "personal": 10_000_000_000})])
def test_capped_budget_cannot_default_or_substitute_ceilings(capped, amounts):
    _, budget, _ = capped
    with pytest.raises(BudgetError, match="live_funding_config_invalid"):
        Budget(budget.path.parent, *amounts[:1], 100000, funding=budget.funding, bucket_caps=amounts[1])


def test_policy_meta_tampering_and_historical_upgrade_refuse(capped, tmp_path):
    _, budget, _ = capped
    with sqlite3.connect(budget.path) as db:
        assert dict(db.execute("SELECT key,value FROM meta WHERE key IN ('max_nano','bucket_shared','bucket_personal')")) == {
            "max_nano": 4_000_000_000, "bucket_shared": 3_500_000_000, "bucket_personal": 500_000_000}
        db.execute("UPDATE meta SET value=value-1 WHERE key='bucket_shared'")
    with pytest.raises(BudgetError, match="live_budget_policy_mismatch"):
        budget.snapshot()
    old = funding.set_funding_policy("capped-copy-control", START, END)
    with pytest.raises(BudgetError, match="live_budget_policy_mismatch"):
        Budget(budget.path.parent, 20_000_000_000, 100000, funding=old).snapshot()
    old_budget = Budget(tmp_path / "historical", 20_000_000_000, 100000, funding=old)
    old_budget.snapshot()
    with pytest.raises(BudgetError, match="live_budget_policy_mismatch"):
        Budget(old_budget.path.parent, 4_000_000_000, 100000, funding=budget.funding, bucket_caps=CAPS).snapshot()


@pytest.mark.parametrize("amount", [4, True, "4.0000000001", " 4", "4e0", "-4"])
def test_config_requires_exact_decimal_strings(tmp_path, amount):
    control = config(tmp_path)
    control["funding"]["totalMaxUsd"] = amount
    with pytest.raises(ValueError, match="live_funding_config_invalid"):
        funding.run_policy(control)


def test_all_config_readers_bind_same_caps_and_refuse_run3(capped, monkeypatch, tmp_path):
    control, budget, _ = capped
    path = tmp_path / "run.json"
    save(path, control)
    for name in ("RUN_CONFIG", "RUN_CONFIG_PATH", "ROOT", "RUN_ID", "ADMIT_UNTIL", "GRAPH_PORT", "MAX_CALLS"):
        monkeypatch.setattr(runner, name, getattr(runner, name))
    args = runner.parse(["--check", "--run-config", str(path)])
    runner.configure(args)
    with runner.environment(runner.profile_env(args.root, "luna")):
        binding = live.LiveRuntime.from_env().binding()
    assert binding["funding"] == budget.funding
    assert runner.funding(args.root).snapshot() == budget.snapshot()
    manifest = {"options": {"fundingConfig": collector.ref(path), "stopNewWorkAt": END}}
    borrowed = collector.acquisition_budget(args.root / "collection", manifest)
    assert borrowed.max_nano == 4_000_000_000 and borrowed.bucket_caps == CAPS
    assert collection_revision.budget_snapshot(control)["fundingPolicy"] == budget.funding
    for profile in (funding.SET_PROFILE, funding.FINISH_PROFILE):
        with runner.environment({**runner.profile_env(args.root, "luna"), live.PROFILE_VAR: profile}):
            with pytest.raises(live.LiveFailure, match="live_profile_unsupported"):
                live.LiveRuntime.from_env()
    for missing in (live.MAX_USD_VAR, live.SHARED_MAX_VAR, live.PERSONAL_MAX_VAR):
        env = runner.profile_env(args.root, "luna")
        del env[missing]
        with runner.environment(env), pytest.raises(live.LiveFailure, match="live_funding_config_invalid"):
            live.LiveRuntime.from_env()
    tampered = copy.deepcopy(binding)
    tampered["funding"]["totalMaxNanoUsd"] += 1
    with pytest.raises(live.LiveFailure, match="live_binding_mismatch"):
        live.LiveRuntime.from_binding(tampered)
    old = {key: value for key, value in control.items() if key != "funding"}
    old["schemaVersion"] = "zoop-private-run-3"
    save(path, old)
    with pytest.raises(runner.Refused, match="run_config_invalid"):
        runner.configure(args)
    with pytest.raises(ValueError, match="collection_funding_config_mismatch"):
        collector.validate_run_config(collector.ref(path), args.root / "collection", END)
    with pytest.raises(ValueError, match="live_funding_config_invalid"):
        collection_revision.budget_snapshot(old)


@pytest.fixture
def native(tmp_path, monkeypatch):
    environment(monkeypatch, tmp_path / "budget")
    item, first = make_original(tmp_path / "originals", "native", tmp_path / "originals/raw", monkeypatch)
    return item, first


def test_native_copy_never_opens_original_sqlite_or_lock_and_writer_is_unblocked(native, tmp_path):
    item, first = native
    original = Path(item["owningIngestionStateDir"])
    before = {p.name: receipts._metadata(p.lstat()) for p in original.iterdir()}
    active, opened = [True], []
    def audit(event, args):
        if active[0] and event in {"open", "sqlite3.connect"}:
            path = str(args[0])
            if str(original) in path:
                opened.append((event, path))
                assert "ingestion.lock" not in path
                assert event != "sqlite3.connect"
    sys.addaudithook(audit)
    try:
        unit = prepare_item(item, tmp_path / "new", "copy-test", runtimes(), actor=ACTOR)
        verify_item(unit)
        output = exported(unit)
        old = load(item["exportPath"])
        assert {k: v for k, v in output.items() if k != "grant"} == {k: v for k, v in old.items() if k != "grant"}
        assert all(not Path(pin["path"]).is_relative_to(original) for pin in unit["originalPins"])
        copied = Path(unit["ingestionStateDir"]) / "ingestion.sqlite3"
        assert copied.read_bytes() == (original / "ingestion.sqlite3").read_bytes()
        assert stat.S_IMODE(copied.stat().st_mode) == 0o400
        assert (copied.parent / "ingestion.lock").read_bytes() == b""
        assert {p.name: receipts._metadata(p.lstat()) for p in original.iterdir()} == before
    finally:
        active[0] = False
    assert opened and all(event == "open" for event, _ in opened)
    reader = Store(copied.parent, existing=True)
    try:
        writer = Store(original)
        writer.close()
        assert reader.one("SELECT COUNT(*) AS n FROM rounds")["n"] == 1
    finally:
        reader.close()
    copied.chmod(0o600)
    with copied.open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="ingestion_state_copy_pin_changed"):
        verify_item(unit)


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_empty_sidecars_leave_no_partial_checkpoint_and_retry_after_quiescence(native, tmp_path, suffix):
    item, _ = native
    original = Path(item["owningIngestionStateDir"])
    sidecar = original / ("ingestion.sqlite3" + suffix)
    sidecar.touch()
    root = tmp_path / "retry"
    with pytest.raises(ValueError, match="ingestion_state_not_quiescent"):
        prepare_item(item, root, "copy-test", runtimes(), actor=ACTOR)
    assert list((root / "processing").iterdir()) == []
    sidecar.unlink()
    unit = prepare_item(item, root, "copy-test", runtimes(), actor=ACTOR)
    assert exported(unit)["document"] == load(item["exportPath"])["document"]


@pytest.mark.parametrize("phase", [1, 2, 3], ids=["initial-hash", "copy", "final-hash"])
def test_growing_source_reads_at_most_pinned_size_plus_sentinel(native, tmp_path, monkeypatch, phase):
    from contextlib import contextmanager
    item, _ = native
    database = Path(item["owningIngestionStateDir"]) / "ingestion.sqlite3"
    initial_size = database.stat().st_size
    source_file = receipts._source_file
    observed = {"opens": 0, "bytes": 0, "grown": False}

    class GrowingReader:
        def __init__(self, reader):
            self.reader = reader

        def read(self, size=-1):
            data = self.reader.read(size)
            self.observe(len(data))
            return data

        def readinto(self, buffer):
            count = self.reader.readinto(buffer)
            self.observe(count)
            return count

        def observe(self, count):
            observed["bytes"] += count
            if not observed["grown"]:
                with database.open("r+b") as writer:
                    writer.truncate(MAX_LEDGER_COPY + 1)
                observed["grown"] = True

        def __getattr__(self, name):
            return getattr(self.reader, name)

    @contextmanager
    def growing_source(path, expected):
        with source_file(path, expected) as reader:
            observed["opens"] += 1
            yield GrowingReader(reader) if observed["opens"] == phase else reader

    monkeypatch.setattr(receipts, "_source_file", growing_source)
    root = tmp_path / "growing"
    with pytest.raises(ValueError, match="ingestion_state_changed"):
        prepare_item(item, root, "copy-test", runtimes(), actor=ACTOR)
    assert observed["grown"] and observed["bytes"] == initial_size + 1
    assert database.stat().st_size == MAX_LEDGER_COPY + 1
    assert list((root / "processing").iterdir()) == []


@pytest.mark.parametrize("mutation", ["mtime", "wal"])
def test_change_during_capture_is_refused_without_checkpoint(native, tmp_path, monkeypatch, mutation):
    item, _ = native
    original = Path(item["owningIngestionStateDir"]) / "ingestion.sqlite3"
    capture = receipts._capture
    def change(source, target, expected):
        capture(source, target, expected)
        if mutation == "mtime":
            info = source.stat()
            os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns + 1))
        else:
            source.with_name(source.name + "-wal").touch()
    monkeypatch.setattr(receipts, "_capture", change)
    root = tmp_path / "changed"
    with pytest.raises(ValueError, match="ingestion_state_changed"):
        prepare_item(item, root, "copy-test", runtimes(), actor=ACTOR)
    assert list((root / "processing").iterdir()) == []


@pytest.mark.parametrize("kind", ["symlink", "parent-symlink", "fifo", "unexpected", "oversize"])
def test_invalid_capture_namespace_refuses_before_open(tmp_path, kind):
    root = tmp_path / "original"
    root.mkdir()
    database = root / "ingestion.sqlite3"
    database.write_bytes(b"authored")
    (root / "ingestion.lock").touch()
    if kind == "symlink":
        database.unlink()
        database.symlink_to(root / "ingestion.lock")
    elif kind == "parent-symlink":
        link = tmp_path / "link"
        link.symlink_to(root, target_is_directory=True)
        database = link / "ingestion.sqlite3"
    elif kind == "fifo":
        database.unlink()
        os.mkfifo(database)
    elif kind == "unexpected":
        (root / "foreign").touch()
    else:
        with database.open("wb") as stream:
            stream.truncate(MAX_LEDGER_COPY + 1)
    with pytest.raises(ValueError, match="ingestion_state_not_regular|state_namespace_conflict|ingestion_state_too_large"):
        receipts.capture_quiescent_sqlite(database, tmp_path / "copy")
    assert not (tmp_path / "copy").exists()


@pytest.mark.parametrize("excluded_entry", [
    {"state": "excluded"},
    {"state": "awaiting-check"},
    {"state": "preparation-blocked", "code": "excluded-preparation-refusal"},
    {"state": "rights-blocked", "code": "excluded-rights-refusal"},
    {"state": "queued", "consumerMetadataError": {"code": "excluded-metadata-refusal"}},
])
def test_mixed_manifest_coverage_distinguishes_ready_awaiting_excluded_and_blocked(native, tmp_path, excluded_entry):
    item, unit = native
    retained = retained_fixture(tmp_path / "retained")
    excluded = {**retained, "privateId": "excluded"}
    blocked = {**retained, "privateId": "blocked"}
    queue = {runner.item_id(item): {"state": "queued", "unit": unit},
             runner.item_id(retained): {"state": "awaiting-check"},
             runner.item_id(excluded): excluded_entry,
             runner.item_id(blocked): {"state": "preparation-blocked", "code": "ingestion_state_not_quiescent"}}
    before = copy.deepcopy(queue)
    assert runner.input_coverage([item, retained, excluded, blocked], queue, {runner.item_id(excluded)}) == {
        "manifestItems": 4, "excluded": 1, "prepared": {"native": 1, "retained": 1}, "awaitingHistory": 1,
        "blocked": {"ingestion_state_not_quiescent": 1}}
    assert queue == before


def test_resumed_check_coverage_uses_current_exclusions_without_rewriting_queue(tmp_path, monkeypatch):
    control = config(tmp_path / "run")
    Path(control["root"]).mkdir(mode=0o700)
    current = datetime.now(timezone.utc)
    control.update(admitFrom=(current - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   admitUntil=(current + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   finishBy=(current + timedelta(hours=1, minutes=25)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    config_path, index = tmp_path / "operator-config.json", tmp_path / "INDEX.json"
    save(config_path, control)
    for name in ("RUN_CONFIG", "RUN_CONFIG_PATH", "ROOT", "RUN_ID", "ADMIT_UNTIL", "GRAPH_PORT", "MAX_CALLS"):
        monkeypatch.setattr(runner, name, getattr(runner, name))
    args = runner.parse(["--check", "--run-config", str(config_path), "--collection-index", str(index)])
    runner.configure(args)
    # Match the existing controller fixture: replace only external Neo4j startup.
    monkeypatch.setattr(runner.Controller, "provision_graph", lambda self: None)
    monkeypatch.setattr(runner, "read_named_env", lambda *args: pytest.fail("CHECK must not read credentials"))
    with runner.environment(runner.profile_env(args.root, "luna")):
        originals = tmp_path / "originals"
        native_items = [make_original(originals, name, originals / "raw", monkeypatch)[0]
                        for name in ("excluded-native", "ready-native")]
        retained_items = [retained_fixture(tmp_path / name, suffix="-" + name)
                          for name in ("completed", "unknown", "ready")]
        save(index, {"schemaVersion": "zoop-overnight-collection-index-1",
                     "nativeItems": native_items, "privateItems": retained_items})
        controller = runner.Controller(args)
        first = controller.check()
        initial = load(controller.root / "control/CHECK.json")
        assert first["units"] == 5
        assert initial["pins"]["inputAuthorization"]["coverage"] == {
            "manifestItems": 5, "excluded": 0, "prepared": {"native": 2, "retained": 3},
            "awaitingHistory": 0, "blocked": {}}
        excluded = [runner.item_id(item) for item in (native_items[0], *retained_items[:2])]
        for key, state in zip(excluded[1:], ("completed", "unknown")):
            controller.queue[key].update(state=state, setId="authored-" + state)
        controller.queue["e" * 24] = {"state": "unknown", "setId": "authored-outside-manifest"}
        controller.persist_queue()
        preserved = {key: copy.deepcopy(controller.queue[key]) for key in [*excluded, "e" * 24]}
        history_before = {path: path.read_bytes() for path in
                          (controller.root / "control/history-preparations/v2/chunks").glob("*/complete.json")}

        args.exclude_unit = ["e" * 24, "f" * 24]
        absent = runner.Controller(args).check()
        assert absent["units"] == 5
        assert absent["inputAuthorization"]["coverage"] == initial["pins"]["inputAuthorization"]["coverage"]
        args.exclude_unit += [*excluded, excluded[0]]
        resumed = runner.Controller(args)
        result = resumed.check()
        checked = load(resumed.root / "control/CHECK.json")
        scope = checked["pins"]["inputAuthorization"]
        ready_ids = {runner.item_id(native_items[1]), runner.item_id(retained_items[2])}
        assert result["units"] == 2
        assert set(scope["readyUnitIds"]) == ready_ids
        assert {unit["unitId"] for unit in checked["pins"]["units"]} == ready_ids
        assert scope["excludedUnitIds"] == sorted(set(args.exclude_unit))
        assert {key: resumed.queue[key] for key in preserved} == preserved
        assert {key: load(resumed.queue_path)[key] for key in preserved} == preserved
        assert {path: path.read_bytes() for path in history_before} == history_before
        assert checked["pins"]["runtimeBindings"] == initial["pins"]["runtimeBindings"]
        assert checked["pins"]["funding"] == initial["pins"]["funding"]
        assert checked["budget"] == initial["budget"]
        assert checked["budget"]["calls"] == 0
        assert checked["pins"]["keysLoaded"] is False and checked["pins"]["paidCalls"] == 0
        assert scope["coverage"] == {
            "manifestItems": 5, "excluded": 3, "prepared": {"native": 1, "retained": 1},
            "awaitingHistory": 0, "blocked": {}}
