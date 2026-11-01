"""`zoop-ai-extract plan-round`: the offline operator service plan of a COMPLETE round (`extraction_plan`).

Real ingestion rounds from the actual ingestion CLI, the real planner and authority; no extraction ledger, model, replay call or network is involved,
and the plan is accepted by the actual service loaders in `ai/service/pipeline_tests/test_extraction_plan.py`."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_round_enqueue import OK_BODY, descriptor, ingest_round, job_ids, make_round, simple_round as ingest_simple_round, tree, url, world  # noqa: F401
from zoop_ai_pipeline import extraction_plan
from zoop_ai_pipeline.extraction import Fixtures
from zoop_ai_pipeline.extraction_contracts import EnqueueRound, ExtractionFailure, digest
from zoop_ai_pipeline.extraction_plan import RoundSelection, plan_round

SLOT = "2026-10-31T09:00:00+09:00"


def policy(**overrides):
    return RoundSelection.model_validate({"schemaVersion": "zoop-extraction-round-selection-1", "asOf": SLOT,
                                         "maxAgeSeconds": 3600, **overrides})


def simple_round(kit, name, suppliers, body=OK_BODY):
    return ingest_simple_round(kit, name, suppliers, body, slot=SLOT)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def make(world, out, rid, *, principal="alpha", topic=None, live=None, label="batch-1", selection=None, **body):
    request = EnqueueRound.model_validate(descriptor(rid, label, events=[world.event], **body))
    fixtures = Fixtures(None if live else world.replay.read_bytes(), topic)
    kit = world.kit
    return plan_round(request, fixtures, principal, kit.root / "ingestion", kit.registry_path, out, live, selection=selection or policy())


def read(out):
    return {p.name: p.read_bytes() for p in out.iterdir()}


def test_a_replay_plan_is_self_contained_deterministic_and_writes_no_ledger(world, tmp_path):
    rid, _ = simple_round(world.kit, "plan", ["supplier-a"])
    out = tmp_path / "plan"
    receipt = make(world, out, rid)
    assert receipt["outcome"] == "created" and sorted(read(out)) == ["approvals.json", "manifest.json", "receipt.json", "relation-upstreams.json"]
    files = read(out)
    manifest, approvals, upstreams = (json.loads(files[n]) for n in ("manifest.json", "approvals.json", "relation-upstreams.json"))
    (unit,) = manifest["units"]
    (entry,) = approvals["approvals"]
    (upstream,) = upstreams["upstreams"]
    assert manifest["planId"].startswith("s2plan-") and receipt["planId"] == manifest["planId"] and receipt["planDigest"] == manifest["planDigest"]
    assert manifest["planDigest"] == digest({k: v for k, v in manifest.items() if k != "planDigest"})
    # Its own namespace, never an `enqueue-round` id; the entry is the exact submit the pipeline would freeze, only with the plan's job id.
    assert unit["jobId"].startswith("s2p-") and unit["jobId"] == entry["jobId"] == upstream["jobId"]
    assert unit["jobId"] not in job_ids(world.kit, rid, "batch-1")
    assert entry["approvedRequestDigest"] == digest(entry["request"]) == unit["approvedRequestDigest"]
    assert unit["submit"] == {"schemaVersion": "zoop-extraction-s2-2", "jobId": unit["jobId"], "approvedRequestDigest": entry["approvedRequestDigest"]}
    assert entry["producerReplayDigest"] == sha(world.replay.read_bytes()) and entry["topicReplayDigest"] is None and "liveRuntimeIdentity" not in entry
    assert upstream == {"principal": "alpha", "jobId": unit["jobId"], "inputDigest": digest({"request": entry["request"], "replayFixtureHash": entry["producerReplayDigest"]})}
    assert unit["inputDigest"] == upstream["inputDigest"] and manifest["pins"] == {"producerReplayDigest": entry["producerReplayDigest"]}
    # The app manifest never carries the request body, snapshot or catalogue.
    text = files["manifest.json"].decode()
    assert "request" not in unit and '"snapshot"' not in text and '"catalogue"' not in text
    assert not (world.kit.root / "extraction").exists()
    # Identical rerun: same receipt body, directory untouched.
    before = tree(out)
    assert make(world, out, rid) == {**receipt, "outcome": "existing"} and tree(out) == before


def test_a_different_input_for_an_existing_output_is_refused_without_a_clobber(world, tmp_path):
    rid, _ = simple_round(world.kit, "plan", ["supplier-a"])
    out = tmp_path / "plan"
    make(world, out, rid)
    before = tree(out)
    for change in ({"principal": "beta"}, {"label": "batch-2"}):
        with pytest.raises(ExtractionFailure) as refused:
            make(world, out, rid, **change)
        assert refused.value.code == "plan_output_conflict" and tree(out) == before
    (out / "extra").write_text("x")
    with pytest.raises(ExtractionFailure) as refused:
        make(world, out, rid)
    assert refused.value.code == "plan_output_conflict"


def test_every_bound_fails_before_any_output_exists(world, tmp_path, monkeypatch):
    rid, _ = simple_round(world.kit, "plan", ["supplier-a"])
    outs = tmp_path / "outs"
    outs.mkdir()
    out = outs / "plan"
    for code, call in (("plan_principal_invalid", lambda: make(world, out, rid, principal="bad principal")),
                       ("plan_output_invalid", lambda: make(world, outs / "missing-parent" / "plan", rid)),
                       ("plan_has_no_units", lambda: make(world, out, make_round(world.kit, "held"))),
                       ("fixture_not_allowed", lambda: make(world, out, rid, topic=b"{}"))):
        with pytest.raises(ExtractionFailure) as refused:
            call()
        assert refused.value.code == code
    monkeypatch.setattr(extraction_plan, "MAX_UPSTREAMS", 50)
    with pytest.raises(ExtractionFailure) as refused:
        make(world, out, rid)
    assert refused.value.code == "plan_upstreams_too_large"
    monkeypatch.setattr(extraction_plan, "MAX_UPSTREAMS", 1_000_000)
    monkeypatch.setattr(extraction_plan, "MAX_APPROVALS", 100)
    with pytest.raises(ExtractionFailure) as refused:
        make(world, out, rid)
    assert refused.value.code == "plan_approvals_too_large"
    assert list(outs.iterdir()) == []  # not even a staging directory remains


def test_a_live_plan_pins_the_runtime_identity_and_no_fixture(world, tmp_path):
    rid, _ = simple_round(world.kit, "plan", ["supplier-a"])
    identity = "a" * 64
    live = SimpleNamespace(config=lambda: SimpleNamespace(binding=lambda: {"identity": identity}))
    out = tmp_path / "plan"
    make(world, out, rid, live=live, mode="live")
    files = read(out)
    (entry,) = json.loads(files["approvals.json"])["approvals"]
    (upstream,) = json.loads(files["relation-upstreams.json"])["upstreams"]
    assert entry["liveRuntimeIdentity"] == upstream["liveRuntimeIdentity"] == identity
    assert entry["producerReplayDigest"] is None and entry["topicReplayDigest"] is None
    assert upstream["inputDigest"] == digest({"request": entry["request"], "liveBindingDigest": identity})
    assert json.loads(files["manifest.json"])["mode"] == "live"


def test_publication_never_replaces_a_competitor_and_accepts_an_identical_winner(world, tmp_path, monkeypatch):
    rid, _ = simple_round(world.kit, "plan", ["supplier-a"])
    original = extraction_plan._sync

    def compete(effect):
        def hooked(directory):
            if directory.name.endswith(".partial"):  # the staging directory is complete: the competitor appears just before the rename
                effect(directory)
            return original(directory)
        monkeypatch.setattr(extraction_plan, "_sync", hooked)

    empty = tmp_path / "empty-competitor"
    compete(lambda staging: empty.mkdir())
    with pytest.raises(ExtractionFailure) as refused:
        make(world, empty, rid)
    assert refused.value.code == "plan_output_conflict" and empty.is_dir() and list(empty.iterdir()) == []
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []

    winner = tmp_path / "identical-winner"
    compete(lambda staging: shutil.copytree(staging, winner))
    assert make(world, winner, rid)["outcome"] == "existing"
    assert sorted(read(winner)) == ["approvals.json", "manifest.json", "receipt.json", "relation-upstreams.json"]


def test_distinct_observations_of_the_same_document_are_not_conflated(world, tmp_path):
    kit = world.kit
    rid, _ = ingest_round(kit, "dups", [[kit.item("c0", "supplier-dup", url("dups", "0")), kit.item("c1", "supplier-dup", url("dups", "1"))]],
                          {"html": OK_BODY}, slot=SLOT)
    out = tmp_path / "plan"
    make(world, out, rid)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert [u["ordinal"] for u in manifest["units"]] == [0, 1]
    assert len({u["documentVersion"] for u in manifest["units"]}) == 1
    assert manifest["skipped"] == []


def cli_plan(world, out, rid, selection):
    import os
    import subprocess
    import sys
    from scripts.graph_handoff_smoke import GUARD
    from scripts.ingestion_smoke import ownership_env
    args = ["plan-round", "--ingestion-state-dir", str(world.kit.root / "ingestion"), "--sources", str(world.kit.registry_path),
            "--replay", str(world.replay), "--principal", "alpha", "--output", str(out)]
    if selection is not None:
        path = out.with_suffix(".selection.json")
        path.write_text(json.dumps(selection.wire()), encoding="utf-8")
        args += ["--selection", str(path)]
    done = subprocess.run([sys.executable, "-c", GUARD + "\nrunpy.run_module('zoop_ai_pipeline.extraction_cli', run_name='__main__')", *args],
                          input=json.dumps(descriptor(rid, events=[world.event])).encode(), capture_output=True, timeout=60,
                          env={"PATH": os.defpath, "HOME": str(Path.home()), "PYTHONDONTWRITEBYTECODE": "1", **ownership_env()})
    assert done.stderr == b"" and done.stdout.count(b"\n") == 1
    return done.returncode, json.loads(done.stdout)


def test_actual_cli_bounds_and_carries_exact_observations_before_new_work(world, tmp_path):
    kit = world.kit
    old_id, _ = simple_round(kit, "ten", [f"old-{n}" for n in range(10)])
    old_out = tmp_path / "first"
    code, receipt = cli_plan(world, old_out, old_id, policy())
    assert code == 0, receipt
    first = json.loads((old_out / "manifest.json").read_bytes())
    assert [u["ordinal"] for u in first["units"]] == list(range(8))
    assert [r["ordinal"] for r in first["carryover"]] == [8, 9]
    assert first["selection"]["limit"] == 8 and first["selection"]["cadenceMinutes"] == 30
    second_slot = "2026-10-31T09:30:00+09:00"
    new_id, _ = ingest_simple_round(kit, "nine", [f"new-{n}" for n in range(9)], slot=second_slot)
    from tests.test_round_enqueue import candidates, observation
    new_refs = [observation(new_id, row) for row in candidates(kit, new_id)]
    settled, carry = first["carryover"]
    selected_policy = policy(asOf=second_slot, carryover=[settled, carry, carry, new_refs[1]],
                             inFlight=[new_refs[0]], settled=[settled])
    second_out = tmp_path / "second"
    code, second = cli_plan(world, second_out, new_id, selected_policy)
    assert code == 0, second
    manifest = json.loads((second_out / "manifest.json").read_bytes())
    approvals = json.loads((second_out / "approvals.json").read_bytes())["approvals"]
    assert [a["request"]["incoming"] for a in approvals] == [carry, *new_refs[1:8]]
    assert manifest["carryover"] == [new_refs[8]]
    assert [r["code"] for r in manifest["selectionReport"]].count("duplicate_observation") == 2
    assert next(r for r in manifest["selectionReport"] if r["observation"] == carry)["slot"] == SLOT
    verified = extraction_plan.verify_plan(second_out, sha((second_out / "receipt.json").read_bytes()), Fixtures(world.replay.read_bytes(), None),
                                           kit.root / "ingestion", kit.registry_path)
    assert verified["planId"] == second["planId"] and verified["counts"]["units"] == 8
    before = tree(second_out)
    assert cli_plan(world, second_out, new_id, selected_policy) == (0, {**second, "outcome": "existing"})
    assert tree(second_out) == before


def test_explicit_age_policy_and_missing_windows_skip_without_consuming_slots(world, tmp_path):
    kit = world.kit
    old_id, _ = ingest_simple_round(kit, "old", ["old"], slot="2026-10-31T08:00:00+09:00")
    untimed_id, _ = ingest_simple_round(kit, "untimed", ["untimed"])
    current_id, _ = simple_round(kit, "current", ["current"])
    from tests.test_round_enqueue import candidates, observation
    carried = [observation(rid, candidates(kit, rid)[0]) for rid in (old_id, untimed_id)]
    out = tmp_path / "aged"
    code, receipt = cli_plan(world, out, current_id, policy(maxAgeSeconds=1800, limit=1, carryover=carried))
    assert code == 0, receipt
    manifest = json.loads((out / "manifest.json").read_bytes())
    assert [r["code"] for r in manifest["selectionReport"]] == ["too_old", "round_slot_unavailable", None]
    assert manifest["counts"]["units"] == 1 and manifest["carryover"] == []
    missing = tmp_path / "missing-policy"
    assert cli_plan(world, missing, current_id, None) == (2, {"schemaVersion": "zoop-extraction-s2-2",
                                                           "error": {"code": "plan_selection_policy_required"}})
    assert not missing.exists()


def test_current_rights_are_rechecked_at_publication(world, tmp_path, monkeypatch):
    kit = world.kit
    rid, _ = simple_round(kit, "rights", ["one"])
    original = extraction_plan.build

    def revoke(*args, **kwargs):
        files = original(*args, **kwargs)
        registry = json.loads(kit.registry_path.read_bytes())
        registry["sources"][0]["grant"]["enabled"] = False
        kit.registry_path.write_text(json.dumps(registry), encoding="utf-8")
        return files

    monkeypatch.setattr(extraction_plan, "build", revoke)
    from zoop_ai_pipeline.ingestion_contracts import IngestionFailure
    out = tmp_path / "revoked"
    with pytest.raises(IngestionFailure, match="registry_changed"):
        make(world, out, rid)
    assert not out.exists()
    code, result = cli_plan(world, out, rid, policy())
    assert code == 2 and result["error"]["code"] == "source_unauthorized"


def test_historical_unbounded_plan_verifies_with_original_identity(world, tmp_path):
    rid, _ = ingest_simple_round(world.kit, "historical", [f"old-{n}" for n in range(10)])
    request = EnqueueRound.model_validate(descriptor(rid, events=[world.event]))
    fixtures = Fixtures(world.replay.read_bytes(), None)
    files, _, _, _ = extraction_plan._prepare(request, fixtures, "alpha", world.kit.root / "ingestion", world.kit.registry_path)
    out = tmp_path / "historical-plan"
    extraction_plan.commit(out, files)
    receipt = json.loads(files["receipt.json"])
    assert extraction_plan.verify_plan(out, sha(files["receipt.json"]), fixtures, world.kit.root / "ingestion",
                                      world.kit.registry_path)["planId"] == receipt["planId"]
    assert json.loads(files["manifest.json"])["counts"]["units"] == 10


def test_readonly_inventory_pages_age_eligible_pending_and_explicit_plan_keeps_the_remainder(world, tmp_path):
    from zoop_ai_pipeline.ingestion_contracts import Authority
    from zoop_ai_pipeline.ingestion_inventory import Inventory, inventory
    kit = world.kit
    ingest_simple_round(kit, "expired", ["expired"], slot="2026-10-31T07:00:00+09:00")
    old_id, _ = simple_round(kit, "pending", [f"pending-{i}" for i in range(10)])
    current_id, _ = ingest_simple_round(kit, "current", ["current"], slot="2026-10-31T09:30:00+09:00")
    request = {"schemaVersion": "zoop-ingestion-round-inventory-1", "sourceId": "synthetic-source", "scopeId": "body",
               "asOf": "2026-10-31T09:30:00+09:00", "maxAgeSeconds": 3600, "limit": 3}
    before = tree(kit.root / "ingestion")
    refs = []
    while True:
        page = inventory(Inventory.model_validate(request), kit.root / "ingestion", Authority(kit.registry_path))
        assert len(page["observations"]) <= 3
        refs.extend(item["observation"] for item in page["observations"])
        if page["next"] is None:
            break
        request.update(after=page["next"], checkpointRevision=page["checkpoint"]["revision"])
    assert len(refs) == 11 and [ref["roundId"] for ref in refs] == [old_id] * 10 + [current_id]
    assert tree(kit.root / "ingestion") == before
    selected = extraction_plan.parse_selection({"schemaVersion": "zoop-extraction-round-selection-2",
        "asOf": request["asOf"], "maxAgeSeconds": request["maxAgeSeconds"], "limit": 8, "cadenceMinutes": 30, "observations": refs[:8]})
    out = tmp_path / "explicit"
    receipt = make(world, out, current_id, selection=selected)
    manifest = json.loads((out / "manifest.json").read_bytes())
    assert manifest["selection"]["observations"] == refs[:8] and manifest["counts"]["units"] == 8
    assert extraction_plan.verify_plan(out, sha((out / "receipt.json").read_bytes()), Fixtures(world.replay.read_bytes(), None),
                                      kit.root / "ingestion", kit.registry_path)["planId"] == receipt["planId"]
    remaining = extraction_plan.parse_selection({**selected.wire(), "observations": refs[8:]})
    next_out = tmp_path / "remaining"
    make(world, next_out, current_id, label="next", selection=remaining)
    assert json.loads((next_out / "manifest.json").read_bytes())["counts"]["units"] == 3
    assert tree(kit.root / "ingestion") == before


def test_inventory_pristine_checkpoint_differs_from_partial_busy_or_hot_wal(world, tmp_path):
    from zoop_ai_pipeline.ingestion import Store
    from zoop_ai_pipeline.ingestion_contracts import Authority, IngestionFailure
    from zoop_ai_pipeline.ingestion_inventory import Inventory, inventory
    request = Inventory.model_validate({"schemaVersion": "zoop-ingestion-round-inventory-1", "sourceId": "synthetic-source",
        "scopeId": "body", "asOf": SLOT, "maxAgeSeconds": 3600, "limit": 0})
    authority = Authority(world.kit.registry_path)
    absent = tmp_path / "pristine"
    assert inventory(request, absent, authority)["checkpoint"] == {"revision": 0, "through": None}
    assert not absent.exists()
    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / "ingestion.sqlite3").write_bytes(b"partial")
    with pytest.raises(IngestionFailure, match="ingestion_state_missing"):
        inventory(request, partial, authority)
    root = world.kit.root / "ingestion"
    with_writer = Store(root)
    try:
        with pytest.raises(IngestionFailure, match="ingestion_busy"):
            inventory(request, root, authority)
    finally:
        with_writer.close()
    wal = root / "ingestion.sqlite3-wal"
    wal.write_bytes(b"unrecovered-test-wal")
    before = tree(root)
    with pytest.raises(IngestionFailure, match="ingestion_recovery_required"):
        inventory(request, root, authority)
    assert tree(root) == before
