"""`zoop-ai-extract plan-round`: the offline operator service plan of a COMPLETE round (`extraction_plan`).

Real ingestion rounds from the actual ingestion CLI, the real planner and authority; no extraction ledger, model, replay call or network is involved,
and the plan is accepted by the actual service loaders in `ai/service/pipeline_tests/test_extraction_plan.py`."""
from __future__ import annotations

import hashlib
import json
import shutil
from types import SimpleNamespace

import pytest

from tests.test_round_enqueue import OK_BODY, descriptor, ingest_round, job_ids, make_round, simple_round, tree, url, world  # noqa: F401 - `world` is a fixture
from zoop_ai_pipeline import extraction_plan
from zoop_ai_pipeline.extraction import Fixtures
from zoop_ai_pipeline.extraction_contracts import EnqueueRound, ExtractionFailure, digest
from zoop_ai_pipeline.extraction_plan import plan_round


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def make(world, out, rid, *, principal="alpha", topic=None, live=None, label="batch-1", **body):
    request = EnqueueRound.model_validate(descriptor(rid, label, events=[world.event], **body))
    fixtures = Fixtures(None if live else world.replay.read_bytes(), topic)
    kit = world.kit
    return plan_round(request, fixtures, principal, kit.root / "ingestion", kit.registry_path, out, live)


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


def test_a_duplicate_skip_names_the_exported_unit_not_an_enqueue_id(world, tmp_path):
    kit = world.kit
    rid, _ = ingest_round(kit, "dups", [[kit.item("c0", "supplier-dup", url("dups", "0")), kit.item("c1", "supplier-dup", url("dups", "1"))]], {"html": OK_BODY})
    out = tmp_path / "plan"
    make(world, out, rid)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    (skipped,) = manifest["skipped"]
    assert skipped["code"] == "duplicate_in_round" and skipped["detail"] in {unit["jobId"] for unit in manifest["units"]}
    assert skipped["detail"].startswith("s2p-")
