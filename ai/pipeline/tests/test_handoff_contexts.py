"""Consumer-visible composition over two independent loopback operating ledgers."""
from __future__ import annotations

import copy
import fcntl
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from scripts import graph_handoff_smoke as hs
from scripts.relation_smoke import tree
from zoop_ai_pipeline.handoff_contracts import Manifest
from pydantic import ValidationError


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    world = hs.build_context_world(tmp_path_factory.mktemp("native-contexts").resolve() / "owned")
    operator = hs.Operator(world)
    operator.cli("freeze", hs.manifest_doc(world, "contexts", hs.file_hashes(world.root)))
    return world


def exported(world, expected=0):
    operator = hs.Operator(world)
    return operator.cli("export", operator.sel("contexts"), expected=expected)


def exposure(world, changed, expected=0):
    env = {"PATH": os.defpath, "HOME": str(Path.home()), "PYTHONDONTWRITEBYTECODE": "1", **hs.ownership_env()}
    command = [sys.executable, "-c", hs.GUARD + "runpy.run_module('zoop_ai_pipeline.handoff_exposure_cli', run_name='__main__')",
               "--state-dir", str(world.root / "handoff"), "--source-contexts", str(world.context_file), "--source-contexts-sha256", world.context_sha]
    request = {"schemaVersion": "zoop-handoff-exposure-1", "handoffIds": ["contexts"], "changed": changed}
    child = subprocess.run(command, input=hs.json_bytes(request), capture_output=True, env=env, timeout=60)
    assert child.returncode == expected, child.stdout.decode() + child.stderr.decode()
    return json.loads(child.stdout)


@contextmanager
def inventory(world, change, *, repin=True):
    raw, pin = world.context_file.read_bytes(), world.context_sha
    doc = json.loads(raw)
    change(doc)
    world.context_file.write_bytes(hs.json_bytes(doc))
    if repin:
        world.context_sha = hs.digest_text(world.context_file.read_text())
    try:
        yield
    finally:
        world.context_file.write_bytes(raw)
        world.context_sha = pin


def test_two_native_owners_deliver_one_bundle_preserving_runtime_identity(world):
    before = [(tree(c.paths.relation), tree(c.paths.extraction), tree(c.paths.ingestion), tree(c.metering)) for c in world.native_contexts]
    result = exported(world)
    assert result["bundle"]["schemaVersion"] == "zoop-graph-handoff-bundle-8"
    assert {issue["id"] for issue in result["bundle"]["issues"]} == {"issue:context-0", "issue:context-1"}
    assert len(result["bundle"]["sources"]) == 2
    identities = {binding["live"]["runtime"]["identity"] for binding in world.runtime_bindings}
    assert len(identities) == 2
    assert [(tree(c.paths.relation), tree(c.paths.extraction), tree(c.paths.ingestion), tree(c.metering)) for c in world.native_contexts] == before


@pytest.mark.parametrize("context", [0, 1])
def test_revocation_withholds_export_but_exposure_reaches_both_sources_and_only_the_changed_grant(world, context):
    changed = {"kind": "source", "sourceId": "synthetic-source"}
    before = exposure(world, changed)
    leaf = world.native_contexts[context].paths.sources
    raw = leaf.read_bytes()
    doc = json.loads(raw)
    grant = doc["sources"][0]["grant"]
    grant["enabled"] = False
    leaf.write_bytes(hs.json_bytes(doc))
    try:
        refused = exported(world, expected=2)
        assert refused["delivery"]["status"] == "withheld"
        assert exposure(world, changed) == before
        assert {issue["id"] for issue in before["handoffs"][0]["issues"]} == {"issue:context-0", "issue:context-1"}
        scoped = exposure(world, {"kind": "grant", "grantId": grant["grantId"], "revision": grant["revision"]})
        assert {issue["id"] for issue in scoped["handoffs"][0]["issues"]} == {f"issue:context-{context}"}
    finally:
        leaf.write_bytes(raw)


@pytest.mark.parametrize("change,code", [
    (lambda doc: doc["contexts"].append(copy.deepcopy(doc["contexts"][0])), "source_context_route_duplicate"),
    (lambda doc: doc["contexts"][0]["sourcePins"].append(copy.deepcopy(doc["contexts"][0]["sourcePins"][0])), "source_context_route_duplicate"),
    (lambda doc: doc["contexts"][1]["observations"].append(copy.deepcopy(doc["contexts"][0]["observations"][0])), "source_context_route_duplicate"),
    (lambda doc: doc["contexts"][0]["sourcePins"][0].update(reviewDigest="0" * 64), "source_context_pin_missing"),
    (lambda doc: doc["contexts"][0]["observations"][0].update(roundId="foreign-round"), "source_context_observation_missing"),
    (lambda doc: doc["contexts"][0].update(observations=doc["contexts"][1].pop("observations")) , "source_contexts_invalid"),
])
def test_invalid_or_missing_routes_refuse_the_consumer(world, change, code):
    with inventory(world, change):
        assert exported(world, expected=2)["error"]["code"] == code


def test_complete_observation_routes_cannot_be_swapped_between_owners(world):
    def swap(doc):
        left, right = doc["contexts"]
        left["observations"], right["observations"] = right["observations"], left["observations"]
    with inventory(world, swap):
        assert exported(world, expected=2)["error"]["code"] == "source_context_observation_misrouted"
        assert exposure(world, {"kind": "source", "sourceId": "synthetic-source"}, expected=2)["error"]["code"] == "source_context_observation_misrouted"


def test_operator_pin_detects_context_file_drift(world):
    with inventory(world, lambda doc: doc["contexts"][0].update(contextId="changed"), repin=False):
        assert exported(world, expected=2)["error"]["code"] == "source_contexts_changed"


@pytest.mark.parametrize("context", [0, 1])
def test_every_selected_relation_owner_keeps_busy_and_hot_wal_failures(world, context):
    root = world.native_contexts[context].paths.relation
    descriptor = os.open(root / "relation.lock", os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert exported(world, expected=2)["error"]["code"] == "relation_busy"
    finally:
        os.close(descriptor)
    wal = root / "relation.sqlite3-wal"
    original = wal.read_bytes() if wal.exists() else None
    wal.write_bytes(b"uncheckpointed")
    try:
        assert exported(world, expected=2)["error"]["code"] == "relation_recovery_required"
    finally:
        if original is None:
            wal.unlink()
        else:
            wal.write_bytes(original)


def test_manifest_not_inventory_owns_the_twenty_source_limit(world):
    manifest = hs.manifest_doc(world, "twenty", hs.file_hashes(world.root))
    pin = manifest["sources"][0]
    manifest["sources"] = [{**pin, "relation": {**pin["relation"], "jobId": f"job-{i}"}} for i in range(20)]
    assert len(Manifest.model_validate(manifest).sources) == 20
    manifest["sources"].append({**pin, "relation": {**pin["relation"], "jobId": "job-20"}})
    with pytest.raises(ValidationError):
        Manifest.model_validate(manifest)
    def extras(doc):
        for i in range(21):
            doc["contexts"][0]["sourcePins"].append({**pin, "relation": {**pin["relation"], "jobId": f"extra-{i}"}})
    with inventory(world, extras):
        assert len(exported(world)["bundle"]["sources"]) == 2


def test_summary_inputs_authorize_each_observation_through_its_own_current_grant(world):
    from zoop_ai_pipeline.extraction_contracts import ExtractionFailure, ObservationRef
    from zoop_ai_pipeline.handoff import HandoffPaths, plan_summary_input

    root = world.root
    paths = HandoffPaths(None, None, None, None, root / "canonical.json", root / "decisions.json", root / "bindings.json",
                         source_contexts=world.context_file, source_contexts_sha256=world.context_sha)
    planned = plan_summary_input(paths, Manifest.model_validate(hs.manifest_doc(world, "contexts", hs.file_hashes(root))), "issue:context-1")
    leaf = world.native_contexts[1].paths.sources
    registry = json.loads(leaf.read_bytes())
    grant = registry["sources"][0]["grant"]
    ref = ObservationRef.model_validate(world.native_contexts[1].refs[0])
    planned.sources.authorize_model_send(ref, grant["purposes"][0], grant["recipients"][0])
    raw = leaf.read_bytes()
    grant["allowedOperations"].remove("model-send")
    leaf.write_bytes(hs.json_bytes(registry))
    try:
        with pytest.raises(ExtractionFailure):
            planned.sources.authorize_model_send(ref, grant["purposes"][0], grant["recipients"][0])
        assert planned.sources.export(ref)["document"]["documentId"] == ref.document_id
    finally:
        leaf.write_bytes(raw)


def test_route_mutation_during_rebuild_refuses_before_delivery(world, monkeypatch):
    from contextlib import closing
    from zoop_ai_pipeline.extraction_contracts import ExtractionFailure
    from zoop_ai_pipeline.handoff import Handoff, HandoffPaths, Planner, Selector, Store

    root = world.root
    paths = HandoffPaths(None, None, None, None, root / "canonical.json", root / "decisions.json", root / "bindings.json",
                         source_contexts=world.context_file, source_contexts_sha256=world.context_sha)
    original = world.context_file.read_bytes()
    run = Planner.run
    def mutate(planner):
        result = run(planner)
        world.context_file.write_bytes(original + b" ")
        return result
    monkeypatch.setattr(Planner, "run", mutate)
    try:
        with closing(Store(root / "handoff", *paths.roots(), mode="read")) as store:
            with pytest.raises(ExtractionFailure) as caught:
                Handoff(store, paths).export(Selector.model_validate(hs.Operator(world).sel("contexts")))
            assert caught.value.code == "source_contexts_changed"
    finally:
        world.context_file.write_bytes(original)


def test_missing_context_refuses_the_whole_exposure_selection(world):
    with inventory(world, lambda doc: doc["contexts"].pop()):
        result = exposure(world, {"kind": "source", "sourceId": "synthetic-source"}, expected=2)
        assert result["error"]["code"] == "source_context_pin_missing"
        assert set(result) == {"schemaVersion", "error"}
