"""Proposed partitions are checked against real replay-owned S2/S3 membership."""
from __future__ import annotations

import copy
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import graph_handoff_smoke as hs
from scripts.relation_smoke import co, converge, ev, proposal, tree, world_cite
from zoop_ai_pipeline import handoff, handoff_partition
from zoop_ai_pipeline.graph_projection import review_state
from zoop_ai_pipeline.ingestion_contracts import byte_hash, digest


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(hs.json_bytes(value))
    return {"path": str(path), "sha256": byte_hash(path.read_bytes())}


def partition(case, directory, manifest=None, decisions=None, canonical=None):
    spec = dict(case.files)
    for name, value in (("decisions", decisions), ("canonical", canonical)):
        if value is not None:
            spec[name] = save(directory / f"{name}.json", value)
    wire = copy.deepcopy(manifest if manifest is not None else case.manifest)
    wire["files"] = {name: spec[name]["sha256"] for name in ("canonical", "decisions", "bindings")}
    return {**spec, "manifest": save(directory / "manifest.json", wire)}


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    root = tmp_path_factory.mktemp("handoff-partitions").resolve()
    world = hs.build_world(root / "native")
    hs.write_operator(world)
    files = {name: {"path": str(world.root / f"{name}.json"), "sha256": value} for name, value in hs.file_hashes(world.root).items()}
    manifest = hs.manifest_doc(world, "partition", {name: value["sha256"] for name, value in files.items()})
    contexts = {"schemaVersion": "zoop-handoff-source-contexts-1", "contexts": [{
        "contextId": "synthetic", "relationStateDirectory": str(world.root / "relation"),
        "extractionStateDirectory": str(world.root / "extraction"), "ingestionStateDirectory": str(world.root / "ingestion"),
        "sources": str(world.kit.registry_path), "sourcePins": manifest["sources"], "observations": list(world.refs.values())}]}
    config = {"schemaVersion": "zoop-partition-check-1", "scope": "Original authored two-job collection", "sourceKind": "synthetic",
              "universe": save(root / "universe.json", {"sources": manifest["sources"]}), "canonical": files["canonical"],
              "contexts": save(root / "contexts.json", contexts), "partitions": []}
    case = SimpleNamespace(world=world, files=files, manifest=manifest, contexts=contexts, config=config)
    config["partitions"] = [partition(case, root / "valid")]
    return case


def run(case, config, status, codes=()):
    roots = [case.world.root / name for name in ("ingestion", "extraction", "relation")]
    before = [tree(root) for root in roots]
    authority = case.world.kit.registry_path.read_bytes()
    env = {"PATH": os.defpath, "HOME": str(Path.home()), "PYTHONDONTWRITEBYTECODE": "1", **hs.ownership_env()}
    child = subprocess.run([sys.executable, "-c", hs.GUARD + "runpy.run_module('zoop_ai_pipeline.handoff_cli', run_name='__main__')", "partition-check"],
                           input=hs.json_bytes(config), capture_output=True, env=env, timeout=180)
    result = json.loads(child.stdout)
    assert child.returncode == {"valid": 0, "invalid": 1, "blocked": 2}[status], (result, child.stderr.decode())
    assert result["status"] == status
    assert set(codes) <= {finding["code"] for finding in result["findings"]}
    assert [tree(root) for root in roots] == before
    assert case.world.kit.registry_path.read_bytes() == authority
    return result


def test_connected_partition_preserves_original_jobs_and_exact_member_inventory(case):
    result = run(case, case.config, "valid")
    assert result["counts"] == {"originalS3Jobs": 2, "readS3Jobs": 2, "partitions": 1, "actualMembers": 5,
                                "mappedCanonicalIssues": 3, "unmappedMembers": 0}
    assert result["memberInventoryComplete"] is True
    assert [(item["jobs"], item["uniqueSourceEvents"], item["uniqueMentions"]) for item in result["components"]] == [(["rel-a", "rel-b"], 5, 4)]
    assert [row["sourcePin"] for row in result["memberInventory"]] == case.manifest["sources"]


@pytest.mark.parametrize("damage,status,codes", [
    ("split", "invalid", ["cross_manifest_issue", "issue_representative_invalid", "structural_source_outside_partition"]),
    ("jobs", "invalid", ["missing_job", "duplicate_job", "unexpected_job", "manifest_invalid"]),
    ("representative", "invalid", ["issue_representative_invalid"]),
    ("verdict", "invalid", ["field_verdict_unbound"]),
    ("pin", "invalid", ["job_pin_mismatch"]),
    ("file-pin", "blocked", ["operator_file_pin_mismatch"]),
    ("unreadable", "blocked", ["relation_state_missing"]),
    ("denied", "blocked", ["source_unauthorized"]),
    ("canonical", "invalid", ["canonical_membership_mismatch"]),
    ("population-duplicate", "blocked", ["original_job_duplicate", "original_universe_ambiguous"]),
    ("review", "blocked", ["review_revision_changed"]),
])
def test_invalid_partition_and_blocked_source_have_distinct_verdicts(case, tmp_path, damage, status, codes):
    config = copy.deepcopy(case.config)
    manifest = copy.deepcopy(case.manifest)
    authority = case.world.kit.registry_path.read_bytes()
    if damage == "split":
        config["partitions"] = [partition(case, tmp_path / str(index), {**manifest, "sources": [pin]}) for index, pin in enumerate(manifest["sources"])]
    elif damage == "jobs":
        unexpected = copy.deepcopy(manifest["sources"][0])
        unexpected["relation"]["jobId"] = "unexpected-s3"
        config["partitions"] = [partition(case, tmp_path, {**manifest, "sources": [manifest["sources"][0], manifest["sources"][0], unexpected]})]
    elif damage in {"representative", "verdict"}:
        decisions = json.loads(Path(case.files["decisions"]["path"]).read_bytes())
        if damage == "representative":
            decisions["issues"][0]["representative"]["ref"] = "missing-representative"
        else:
            decisions["issues"][0]["fieldVerdicts"] = [hs.field_verdict(case.world, "b", "m-b", "period", "2026Q4", "ALLOW", "stated", [hs.QB])]
        config["partitions"] = [partition(case, tmp_path, decisions=decisions)]
    elif damage == "pin":
        manifest["sources"][0]["reviewDigest"] = "f" * 64
        config["partitions"] = [partition(case, tmp_path, manifest)]
    elif damage == "file-pin":
        manifest["files"]["canonical"] = "f" * 64
        config["partitions"][0]["manifest"] = save(tmp_path / "manifest.json", manifest)
    elif damage == "unreadable":
        contexts = copy.deepcopy(case.contexts)
        contexts["contexts"][0]["relationStateDirectory"] = str(tmp_path / "missing")
        config["contexts"] = save(tmp_path / "contexts.json", contexts)
    elif damage == "denied":
        registry = json.loads(authority)
        registry["sources"][0]["grant"]["enabled"] = False
        case.world.kit.registry_path.write_bytes(hs.json_bytes(registry))
    elif damage == "canonical":
        canonical = json.loads(Path(case.files["canonical"]["path"]).read_bytes())
        next(entry for entry in canonical["entries"] if entry["kind"] == "event")["canonicalId"] = "issue:other"
        config["partitions"] = [partition(case, tmp_path, canonical=canonical)]
    elif damage == "population-duplicate":
        config["universe"] = save(tmp_path / "universe.json", {"sources": [*manifest["sources"], manifest["sources"][0]]})
    elif damage == "review":
        manifest["sources"][0]["reviewDigest"] = "f" * 64
        config["universe"] = save(tmp_path / "universe.json", {"sources": manifest["sources"]})
        contexts = copy.deepcopy(case.contexts)
        contexts["contexts"][0]["sourcePins"] = manifest["sources"]
        config["contexts"] = save(tmp_path / "contexts.json", contexts)
        config["partitions"] = [partition(case, tmp_path, manifest)]
    try:
        result = run(case, config, status, codes)
        if status == "blocked":
            assert result["memberInventoryComplete"] is False
    finally:
        if damage == "denied":
            case.world.kit.registry_path.write_bytes(authority)


@pytest.mark.parametrize("change", ["revoke", "expire"])
def test_final_owner_gate_withholds_staged_inventory_after_authority_changes(case, monkeypatch, change):
    authority = case.world.kit.registry_path
    original = authority.read_bytes()
    fields = handoff.Planner.fields
    locks_held = []

    def change_during_analysis(decision, members):
        result = fields(decision, members)
        if not locks_held:
            with (case.world.root / "relation/relation.lock").open("rb") as lock:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    locks_held.append(True)
                else:
                    locks_held.append(False)
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            registry = json.loads(original)
            grant = registry["sources"][0]["grant"]
            if change == "revoke":
                grant["enabled"] = False
            else:
                grant["expiresAt"] = "1970-01-01T00:00:00+00:00"
            authority.write_bytes(hs.json_bytes(registry))
        return result

    monkeypatch.setattr(handoff.Planner, "fields", staticmethod(change_during_analysis))
    try:
        result = handoff_partition.check(hs.json_bytes(case.config))
    finally:
        authority.write_bytes(original)
    assert result["status"] == "blocked"
    assert result["findings"] == [{"code": "source_unauthorized", "effect": "source-blocked"}]
    assert result["memberInventoryComplete"] is False
    assert set(result) == {"schemaVersion", "status", "scope", "inputs", "findings", "usage", "memberInventoryComplete"}
    assert locks_held == [True]


def test_twenty_one_genuine_s3_jobs_form_one_unsplittable_component(case, tmp_path):
    world = case.world
    source = SimpleNamespace(kit=world.kit, refs=world.refs, art=world.art, s2=world.s2["a"])
    jobs = dict(world.jobs)
    for index in range(19):
        job = f"partition-extra-{index}"
        jobs[job] = converge(source, job, [proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(world.evc["a"]), [world_cite(source, "a", hs.EVT_A)])])
    pins = [{"relation": {"jobId": job, "inputDigest": value["inputDigest"]}, "upstream": value["binding"]["upstream"],
             "reviewDigest": digest(review_state(value))} for job, value in sorted(jobs.items())]
    config = copy.deepcopy(case.config)
    config["universe"] = save(tmp_path / "universe.json", {"sources": pins})
    contexts = copy.deepcopy(case.contexts)
    contexts["contexts"][0]["sourcePins"] = pins
    config["contexts"] = save(tmp_path / "contexts.json", contexts)
    config["partitions"] = [partition(case, tmp_path / str(index), {**case.manifest, "sources": selected})
                            for index, selected in enumerate((pins[:20], pins[20:]))]
    result = run(case, config, "invalid", ["component_exceeds_manifest_limit", "cross_manifest_issue"])
    assert result["counts"]["readS3Jobs"] == 21
    assert [item["uniqueS3Jobs"] for item in result["components"]] == [21]
    assert next(item for item in result["findings"] if item["code"] == "component_exceeds_manifest_limit")["limit"] == 20
