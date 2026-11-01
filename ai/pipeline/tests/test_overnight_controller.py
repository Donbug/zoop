"""Controller canary routing: deterministic native-CLI boundary, no keys or network.

The authored CLI peer records a genuine pre-send-style refusal in a local SQLite
call ledger. Controller gate, routing, receipt reading, queue persistence and
metrics are real; this does not claim to test the native producer or provider.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE / "scripts"))
sys.path.insert(0, str(PIPELINE))
from scripts import overnight_run as runner
import overnight_inputs as inputs
from zoop_ai_pipeline import live_budget, live_runtime as live

PROVISION_GRAPH = runner.Controller.provision_graph
ACTOR = {"kind": "user-private-experiment", "acceptedBy": "Main", "decidedAt": "2026-10-28T00:10:00Z",
         "statement": "Authored offline fixture authorization; no real collection or provider calls."}


def write_ready_canary(root, check, profile, unit):
    """Synthetic provider evidence: immutable report, input CHECK and source pins."""
    check_path = root / "control/retained" / ("CHECK-" + runner.sha(runner.encoded(check)) + ".json")
    runner.save(check_path, check, immutable=True)
    unit_path = root / "analysis/readiness-fixtures" / profile / "unit.json"
    runner.save(unit_path, unit, immutable=True)
    report = {"status": "completed", "mode": "canary", "canaryProfile": profile,
              "completionScope": "deepseek-diagnostic" if profile == "deepseek-diagnostic" else "ordinary",
              "checkDigest": check["checkDigest"], "receiptCoverage": "complete",
              "providerApprovalDigest": runner.provider_approval_digest(check["pins"]),
              **runner.frozen_provider_approval(check["pins"]),
              "inputAuthorization": {"checkDigest": check["checkDigest"], "check": runner.file_pin(check_path)},
              "canaryUnitPins": [{**runner.file_pin(unit_path), "unitId": unit["unitId"], "sourceIdentity": runner.source_identity(unit)}],
              "physicalProviderCalls": {"personal-deepseek": 1, "shared-openai": int(profile == "luna")}}
    runner.save(root / "control" / ("CANARY-" + profile + ".json"), runner.seal_canary_report(root, report))


@pytest.fixture
def prepared_controller(tmp_path, monkeypatch):
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-27T20:00:00+00:00")
    monkeypatch.setattr(runner, "remaining", lambda _: 3600)
    from datetime import datetime
    from zoop_ai_pipeline import live_funding
    class FundingClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(live_budget._now())
    monkeypatch.setattr(live_funding, "datetime", FundingClock)
    # External graph startup and documented credential files are not exercised.
    monkeypatch.setattr(runner.Controller, "provision_graph", lambda self: None)
    monkeypatch.setattr(runner, "read_named_env", lambda path, names: {
        name: {"OPENAI_BASE_URL": "https://opencode.ai/zen/go/v1", "OPENAI_MODEL": "deepseek-v4.1-flash",
               "OPENAI_OPENCODE_SESSION": "true"}.get(name, "synthetic-test-not-a-provider-key") for name in names})
    # These routing controls stop at their first native CLI refusal; real history
    # ingestion/grounding is exercised by the separate native history suite.
    monkeypatch.setattr(runner.history, "snapshot_for", lambda unit, catalogue, **limits: {
        "snapshot": unit["snapshot"], "canonicalMappings": {},
        "coverage": {"selectedEvents": 0, "eligibleBeforeDedupAndBounds": 0, "excluded": {}, **limits}})
    def verify_fixture(unit):
        # This subprocess-routing fixture isolates native authority; retain exact
        # file-pin gates while the private-authority suite exercises real grants.
        for key in ("registry", "export"):
            if runner.sha(Path(unit[key]).read_bytes()) != unit[key + "Sha256"]:
                raise ValueError("processing_pin_changed")
    monkeypatch.setattr(runner, "verify_item", verify_fixture)

    def create(profile="luna", *, mode="canary", enabled=None, day=False):
        root = tmp_path / (mode + "-" + profile)
        root.mkdir()
        index = root / "collection/INDEX.json"
        runner.save(index, {"schemaVersion": "zoop-overnight-collection-index-1", "nativeItems": [], "observations": []})
        if day:
            config = {"schemaVersion": "zoop-private-run-4", "funding": {"totalMaxUsd": "4", "sharedMaxUsd": "3.5", "personalMaxUsd": "0.5"}, "runId": "day-controller-test", "root": str(root),
                      "admitFrom": "2026-10-28T00:15:00Z", "admitUntil": "2026-10-28T08:30:00Z", "finishBy": "2026-10-28T09:30:00Z",
                      "graphPort": 32819, "maxCalls": 100000, "processingActor": ACTOR}
            monkeypatch.setattr(runner, "RUN_CONFIG", config)
            monkeypatch.setattr(runner, "RUN_ID", config["runId"])
            monkeypatch.setattr(runner, "ADMIT_UNTIL", config["admitUntil"])
            monkeypatch.setattr(runner, "MAX_CALLS", config["maxCalls"])
            monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:00:00+00:00")
        registry, export = root / "registry.json", root / "export.json"
        runner.save(registry, {})
        runner.save(export, {})
        unit = {"unitId": "test-unit", "sourceId": "test-source", "registry": str(registry), "export": str(export),
                "registrySha256": runner.sha(registry.read_bytes()), "exportSha256": runner.sha(export.read_bytes()),
                "originalPins": [], "ingestionStateDir": str(root / "ingestion"),
                "observation": {"roundId": "test-round", "sourceId": "test-source", "page": 0, "ordinal": 0,
                                "documentId": "test-document", "rawVersion": "a" * 64, "documentVersion": "b" * 64},
                "snapshot": {"revision": "explicit-empty-test", "events": []}}
        cat, cat_pin = runner.catalogue(runner.REPO)
        bindings = {cohort: {name: runner.runtime_for(root, cohort, summary=summary).binding()
                            for name, summary in (("pipeline", False), ("summary", True))}
                    for cohort in ("luna", "deepseek")}
        pins = {"codePins": runner.code_pins(), "catalogue": cat, "cataloguePin": cat_pin,
                "runtimeBindings": bindings, "units": [unit]}
        if day:
            pins["runConfig"] = runner.RUN_CONFIG
            policy = bindings["luna"]["pipeline"]["funding"]
            pins["funding"] = {"policyVersion": policy["version"], "policyIdentity": runner.sha(runner.encoded(policy)),
                               "totalMaxNanoUsd": policy["totalMaxNanoUsd"], "bucketMaxNanoUsd": policy["bucketMaxNanoUsd"], "maxCalls": 100000}
            pins["identityPolicy"] = runner.POLICY
            pins["inputAuthorization"] = {"collectionIndexPath": str(index), "excludedUnitIds": []}
        digest = runner.sha(runner.encoded(pins))
        runner.save(root / "control/CHECK.json", {"pins": pins, "checkDigest": digest})
        approval = {"checkDigest": digest, "mode": mode, "approvedBy": "Main", "identityPolicy": runner.POLICY}
        if mode == "canary":
            approval["canaryProfile"] = profile
        else:
            approval["enabledProfiles"] = enabled
            for cohort in ("luna", "deepseek-diagnostic"):
                runner.save(root / "control" / ("CANARY-" + cohort + ".json"), {"status": "completed", "checkDigest": digest})
        if day:
            check = {"pins": pins, "checkDigest": digest}
            approval = runner.v2_greenlight(check, mode, profile)
            for cohort in ("luna", "deepseek-diagnostic"):
                write_ready_canary(root, check, cohort, unit)
        runner.save(root / "control/greenlight.json", approval)
        args = runner.parse(["--" + mode, "--root", str(root), "--collection-index", str(index),
                             "--unit", unit["unitId"], "--canary-profile", profile])
        args.credential_env = root / "authored-not-read.env"
        controller = runner.Controller(args)
        return controller, unit

    return create


def refusing_native_peer(monkeypatch, controller, refusal):
    """Replace only the external native CLI boundary; retain actual ledger observation."""
    models = []

    def cli(label, module, arguments, payload, unit, directory, *, paid=False, env=None):
        assert module == "extract" and paid is True
        models.append(env[live.MODEL_VAR])
        state = Path(arguments[arguments.index("--state-dir") + 1])
        state.mkdir(parents=True)
        with sqlite3.connect(state / "extraction.sqlite3") as db:
            db.execute("CREATE TABLE calls(attempt_id TEXT,job_id TEXT,stage TEXT,state TEXT,response TEXT,started_at TEXT,received_at TEXT,verdict TEXT)")
            db.execute("INSERT INTO calls VALUES(?,?,?,'unsent',NULL,?,NULL,?)",
                       ("attempt-" + str(len(models)), payload["jobId"], "extract", runner.now(), refusal))
        controller.child_reaped = True  # authored CLI boundary returned; no process is left writing this fixture.
        return {"jobId": payload["jobId"], "state": "stopped", "failure": {"code": refusal}, "delivery": {"status": "current"}}

    monkeypatch.setattr(controller, "cli", cli)
    return models


def test_luna_canary_shared_refusal_never_calls_go_and_keeps_failure(prepared_controller, monkeypatch):
    controller, unit = prepared_controller("luna")
    controller.gate("canary")
    models = refusing_native_peer(monkeypatch, controller, "live_budget_exhausted_shared")
    entry = {"state": "queued", "unit": unit, "cohort": None}
    controller.queue[unit["unitId"]] = entry
    with pytest.raises(runner.Refused) as caught:
        controller.process(entry)
    assert caught.value.code == "live_budget_exhausted_shared"
    assert controller.enabled_profiles == ["luna"]
    assert models == ["gpt-6-luna"]
    assert "deepseek-v4.1-flash" not in models
    receipts = list((controller.root / "analysis/luna" / unit["unitId"] / "receipts").glob("*.json"))
    assert len(receipts) == 1
    assert runner.load(receipts[0])["provenUnsent"] is True
    assert runner.load(receipts[0])["verdict"] == "live_budget_exhausted_shared"
    assert not (controller.root / "analysis/deepseek").exists()


def test_go_diagnostic_never_calls_luna_even_with_shared_headroom(prepared_controller, monkeypatch):
    controller, unit = prepared_controller("deepseek-diagnostic")
    controller.gate("canary")
    models = refusing_native_peer(monkeypatch, controller, "live_budget_exhausted_personal")
    entry = {"state": "queued", "unit": unit, "cohort": None, "queueKind": "deepseek-diagnostic"}
    controller.queue[unit["unitId"] + ":deepseek-diagnostic"] = entry
    with pytest.raises(runner.Refused) as caught:
        controller.process(entry)
    assert caught.value.code == "live_budget_exhausted_personal"
    assert controller.enabled_profiles == ["deepseek"]
    assert models == ["deepseek-v4.1-flash"]
    assert "gpt-6-luna" not in models
    assert not (controller.root / "analysis/luna").exists()


@pytest.mark.parametrize("enabled", [["luna"], ["luna", "deepseek"]])
def test_run_keeps_main_enabled_profiles(prepared_controller, enabled):
    controller, _ = prepared_controller(mode="run", enabled=enabled)
    controller.gate("run")
    assert controller.enabled_profiles == enabled


def test_run_does_not_gain_go_only_authority(prepared_controller):
    controller, _ = prepared_controller(mode="run", enabled=["deepseek"])
    with pytest.raises(runner.Refused) as caught:
        controller.gate("run")
    assert caught.value.code == "explicit_enabled_profiles_required"


def selector():
    return {"roundId": "original-round", "sourceId": "korea-portal", "page": 0, "ordinal": 0,
            "documentId": "original-document", "rawVersion": "a" * 64, "documentVersion": "b" * 64}


def test_ready_index_versioned_observation_preserves_exact_selector():
    original = {**selector(), "observedAt": "2026-10-27T06:00:00Z", "title": "not-a-selector"}
    indexed = {"schemaVersion": "zoop-ingestion-s2-1", **selector()}
    assert inputs.observation_selector(original, indexed) == selector()
    assert indexed["schemaVersion"] == "zoop-ingestion-s2-1"


@pytest.mark.parametrize("change", [
    {"schemaVersion": "wrong"}, {"extra": "not-allowed"}, {"page": False},
])
def test_index_selector_rejects_wrong_schema_extra_fields_and_coercion(change):
    indexed = {"schemaVersion": "zoop-ingestion-s2-1", **selector(), **change}
    with pytest.raises(ValueError, match="^collection_observation_schema_invalid$"):
        inputs.observation_selector(selector(), indexed)


def test_index_selector_rejects_changed_native_identity():
    indexed = {"schemaVersion": "zoop-ingestion-s2-1", **selector(), "documentVersion": "c" * 64}
    with pytest.raises(ValueError, match="^collection_observation_mismatch$"):
        inputs.observation_selector(selector(), indexed)


def test_index_schema_failure_is_not_reported_as_source_rights_denial(prepared_controller):
    controller, _ = prepared_controller(day=True)
    export = controller.root / "new-export.json"
    runner.save(export, {"observation": selector()})
    item = {"sourceId": "korea-portal", "exportPath": str(export),
            "observation": {"schemaVersion": "wrong", **selector()}}
    runner.save(controller.root / "collection/INDEX.json",
                {"schemaVersion": "zoop-overnight-collection-index-1", "nativeItems": [item], "observations": []})
    controller.refresh()
    entry = next(iter(controller.queue.values()))
    assert entry["state"] == "preparation-blocked"
    assert entry["code"] == "collection_observation_schema_invalid"
    event = json.loads((controller.root / "events.jsonl").read_text().splitlines()[-1])
    assert event["reasonCode"] == "collection_observation_schema_invalid"
    assert "rightsBlocked" not in event["counts"]


@pytest.mark.parametrize("paid", [False, True])
def test_changed_corpus_pin_prevents_native_dispatch_before_keys_or_spawn(prepared_controller, monkeypatch, paid):
    controller, unit = prepared_controller()
    controller.gate("canary")
    original_pin = unit["registrySha256"]
    runner.save(Path(unit["registry"]), {"changed": True})
    key_reads, spawned = [], []

    def keys(*args):
        key_reads.append(args)
        raise AssertionError("credential loader must not run")

    def spawn(*args, **kwargs):
        spawned.append(args)
        raise AssertionError("native process must not spawn")

    monkeypatch.setattr(runner, "read_named_env", keys)
    monkeypatch.setattr(runner.subprocess, "Popen", spawn)
    with pytest.raises(runner.Refused) as caught:
        controller.cli("changed-input", "extract", ["submit"], {}, unit, controller.root / "analysis", paid=paid)
    assert caught.value.code == "processing_pin_changed"
    assert key_reads == spawned == []
    assert unit["registrySha256"] == original_pin
    assert runner.load(Path(unit["registry"])) == {"changed": True}


@pytest.mark.parametrize("paid", [False, True])
def test_changed_code_pin_prevents_native_dispatch_before_keys_or_spawn(prepared_controller, monkeypatch, paid):
    controller, unit = prepared_controller()
    controller.gate("canary")
    source = controller.root / "runtime-source.py"
    source.write_text("def send(): return 'approved'\n")
    monkeypatch.setattr(runner, "code_pins", lambda: [{"path": "runtime-source.py", "sha256": runner.sha(source.read_bytes())}])
    controller.dispatch_code_pins = runner.code_pins()
    approved = list(controller.dispatch_code_pins)
    source.write_text("def send(): return 'changed-after-gate'\n")
    key_reads, spawned = [], []

    def keys(*args):
        key_reads.append(args)
        raise AssertionError("credential loader must not run")

    def spawn(*args, **kwargs):
        spawned.append(args)
        raise AssertionError("native process must not spawn")

    monkeypatch.setattr(runner, "read_named_env", keys)
    monkeypatch.setattr(runner.subprocess, "Popen", spawn)
    with pytest.raises(runner.Refused) as caught:
        controller.cli("changed-code", "extract", ["submit"], {}, unit, controller.root / "analysis", paid=paid)
    assert caught.value.code == "checked_code_changed"
    assert key_reads == spawned == []
    assert controller.dispatch_code_pins == approved


def graph_facts(controller, owned, *, exit_code=0, dynamic=False):
    return {"id": owned, "runLabel": runner.RUN_ID, "image": "sha256:" + "a" * 64, "running": False,
            "exitCode": exit_code, "oomKilled": False,
            "portBindings": {"7687/tcp": [{"HostIp": "127.0.0.1", "HostPort": "" if dynamic else str(runner.GRAPH_PORT)}]},
            "mounts": [{"Type": "bind", "Destination": destination, "Source": str(controller.root / source)}
                       for destination, source in (("/data", "analysis/neo4j-data"), ("/logs", "analysis/neo4j-logs"))]}


def fixed_graph_descriptor(controller, owned):
    return {"format": "zoop-overnight-graph-runtime-2", "containerId": owned, "containerName": "authored-fixed-container",
            "runId": runner.RUN_ID, "imageId": "sha256:" + "a" * 64, "database": "neo4j",
            "uri": f"bolt://127.0.0.1:{runner.GRAPH_PORT}", "hostPort": runner.GRAPH_PORT,
            "data": str(controller.root / "analysis/neo4j-data"), "predecessor": None}


@pytest.mark.parametrize("failure_point", ["created-before-port", "verified-before-start"])
def test_graph_startup_failure_stops_only_registered_owned_container_and_retains_data(prepared_controller, monkeypatch, failure_point):
    controller, unit = prepared_controller()
    monkeypatch.setattr(controller, "provision_graph", PROVISION_GRAPH.__get__(controller, runner.Controller))
    owned = "c" * 64
    stopped = []
    data = controller.root / "analysis/neo4j-data"
    data.mkdir(parents=True)
    retained = data / "retained-record"
    retained.write_text("keep")
    if failure_point == "verified-before-start":
        runner.save(controller.root / "control/neo4j-v2.json", fixed_graph_descriptor(controller, owned))

    def command(argv, **kwargs):
        operation = argv[3]
        if operation == "image":
            return "sha256:" + "a" * 64
        if operation == "run":
            assert argv[argv.index("-p") + 1] == f"127.0.0.1:{runner.GRAPH_PORT}:7687"
            return owned
        if operation == "inspect":
            return json.dumps(graph_facts(controller, owned))
        if operation in {"port", "start"}:
            assert controller.graph["containerId"] == owned
            raise runner.Refused("authored_graph_startup_failure")
        raise AssertionError("unexpected external command")

    def stop(argv, **kwargs):
        if argv[3] == "inspect":
            return SimpleNamespace(returncode=0, stdout=runner.encoded(graph_facts(controller, owned)))
        stopped.append(argv)
        assert argv == ["docker", "--context", "orbstack", "stop", "--time", "45", owned]
        assert kwargs["timeout"] == 60
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(controller, "command", command)
    monkeypatch.setattr(runner.subprocess, "run", stop)
    with pytest.raises(runner.Refused) as caught:
        controller.run("canary")
    assert caught.value.code == "authored_graph_startup_failure"
    assert len(stopped) == 1
    assert retained.read_text() == "keep"
    assert Path(unit["registry"]).exists() and Path(unit["export"]).exists()
    assert runner.load(controller.root / "control/graph-stop.json")["dataRetained"] is True


@pytest.mark.parametrize("freshness", ["fresh", "backfill", "reused", "unknown"])
def test_input_freshness_survives_processing_sample_and_attempt_events(prepared_controller, freshness):
    controller, unit = prepared_controller()
    unit["freshness"] = inputs.input_freshness({"freshness": freshness})
    controller.event("prepare", "ok", unit=unit)
    controller.event("event-candidate", "ok", unit={**unit, "unitId": "candidate-one"}, kind="record",
                     sample={"recordId": "candidate-one", "recordType": "event-candidate", "decision": "candidate",
                             "artifact": "analysis/result.json"})
    controller.event("extract", "refused", unit=unit, kind="attempt", attemptId="attempt-one", attemptState="released")
    events = [json.loads(line) for line in (controller.root / "events.jsonl").read_text().splitlines()]
    assert [event["freshness"] for event in events] == [freshness] * 3
    assert inputs.input_freshness({}) == "unknown"


def test_freshness_proof_revision_preserves_original_failed_gate_evidence(tmp_path):
    original = {"unitId": "old-unit", "originalPreserved": True}
    runner.save(tmp_path / "proof.json", original, immutable=True)
    before = (tmp_path / "proof.json").read_bytes()
    mtime = (tmp_path / "proof.json").stat().st_mtime_ns
    revised = inputs.preparation_proof(tmp_path, original, "reused")
    assert (tmp_path / "proof.json").read_bytes() == before
    assert (tmp_path / "proof.json").stat().st_mtime_ns == mtime
    assert revised["freshness"] == "reused"
    assert revised["priorProof"] == {"path": str(tmp_path / "proof.json"), "sha256": runner.sha(before)}
    assert runner.load(tmp_path / "proof-v2.json") == revised


@pytest.mark.parametrize("bad", [None, "today", 1])
def test_unrecognized_acquisition_freshness_is_rejected(bad):
    with pytest.raises(ValueError, match="^collection_freshness_invalid$"):
        inputs.input_freshness({"freshness": bad})


def test_code_change_during_key_loading_is_caught_before_spawn(prepared_controller, monkeypatch):
    controller, unit = prepared_controller()
    controller.gate("canary")
    source = controller.root / "runtime-source.py"
    source.write_text("def send(): return 'approved'\n")
    monkeypatch.setattr(runner, "code_pins", lambda: [{"path": "runtime-source.py", "sha256": runner.sha(source.read_bytes())}])
    controller.dispatch_code_pins = runner.code_pins()
    read_keys = runner.read_named_env
    spawned = []

    def keys(*args):
        source.write_text("def send(): return 'changed-while-loading-keys'\n")
        return read_keys(*args)

    def spawn(*args, **kwargs):
        spawned.append(args)
        raise AssertionError("native process must not spawn")

    monkeypatch.setattr(runner, "read_named_env", keys)
    monkeypatch.setattr(runner.subprocess, "Popen", spawn)
    with pytest.raises(runner.Refused) as caught:
        controller.cli("changed-during-keys", "extract", ["submit"], {}, unit, controller.root / "analysis", paid=True)
    assert caught.value.code == "checked_code_changed"
    assert spawned == []


def test_snapshot_event_reuses_exact_prior_private_identity_not_new_job_identity():
    prior = {"jobId": "prior-s2", "inputDigest": "a" * 64}
    candidate = "evc-prior"
    prior_id = "private-event-" + runner.sha(runner.encoded({"upstream": prior, "ref": candidate}))
    s2 = {"jobId": "new-s2", "inputDigest": "b" * 64, "eventCandidates": [], "topicCandidates": [],
          "binding": {"snapshot": {"events": [{"eventId": "night-history-prior"}]}}}
    relation = {"eligibility": {"status": "eligible", "reviewPending": False, "approvalBasis": {"kind": "automatic-verifier"}},
                "subject": {"kind": "company", "ref": "KRX:005930"},
                "object": {"kind": "event", "ref": "night-history-prior"}, "path": []}
    catalogue, _ = runner.catalogue(runner.REPO)
    mapping = {"night-history-prior": {"canonicalId": prior_id, "upstream": prior, "eventCandidateId": candidate}}
    registry = inputs.canonical_registry(s2, {"relations": [relation]}, catalogue, runner.POLICY, mapping)
    event = next(row for row in registry["entries"] if row["kind"] == "event")
    assert event["canonicalId"] == prior_id
    assert event["upstream"] == {"jobId": "new-s2", "inputDigest": "b" * 64}
    changed = {"night-history-prior": {**mapping["night-history-prior"], "canonicalId": "invented-union"}}
    with pytest.raises(ValueError, match="^history_canonical_mapping_changed$"):
        inputs.canonical_registry(s2, {"relations": [relation]}, catalogue, runner.POLICY, changed)


def test_diagnostic_gate_never_starts_ordinary_graph(prepared_controller, monkeypatch):
    controller, _ = prepared_controller("deepseek-diagnostic")

    def forbidden():
        raise AssertionError("diagnostic gate must not start an ordinary graph container")

    monkeypatch.setattr(controller, "provision_graph", forbidden)
    controller.gate("canary")
    assert controller.enabled_profiles == ["deepseek"]
    assert controller.graph is None


def test_legacy_dynamic_graph_is_replaced_without_starting_or_deleting_predecessor(prepared_controller, monkeypatch):
    controller, _ = prepared_controller()
    monkeypatch.setattr(controller, "provision_graph", PROVISION_GRAPH.__get__(controller, runner.Controller))
    old, new = "b" * 64, "c" * 64
    data = controller.root / "analysis/neo4j-data"
    data.mkdir(parents=True)
    marker = data / "retained-database-marker"
    marker.write_text("same database")
    legacy = {key: value for key, value in fixed_graph_descriptor(controller, old).items() if key not in {"format", "hostPort", "predecessor"}}
    legacy_path = controller.root / "control/neo4j.json"
    runner.save(legacy_path, legacy, immutable=True)
    before = legacy_path.read_bytes()
    calls, stopped = [], []

    def command(argv, **kwargs):
        calls.append(argv)
        operation = argv[3]
        if operation == "image":
            return legacy["imageId"]
        if operation == "inspect":
            assert argv[-1] == old
            return json.dumps(graph_facts(controller, old, dynamic=True))
        if operation == "run":
            assert argv[argv.index("-p") + 1] == f"127.0.0.1:{runner.GRAPH_PORT}:7687"
            assert str(data) + ":/data" in argv
            assert str(controller.root / "analysis/neo4j-logs") + ":/logs" in argv
            assert argv[-1] == legacy["imageId"]
            return new
        if operation == "port":
            assert controller.graph["containerId"] == new
            raise runner.Refused("authored_post_create_failure")
        raise AssertionError("must not restart or delete the predecessor")

    def stop(argv, **kwargs):
        if argv[3] == "inspect":
            return SimpleNamespace(returncode=0, stdout=runner.encoded(graph_facts(controller, new)))
        assert argv[-1] == new
        stopped.append(argv)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(controller, "command", command)
    monkeypatch.setattr(runner.subprocess, "run", stop)
    with pytest.raises(runner.Refused, match="authored_post_create_failure"):
        controller.run("canary")
    assert len(stopped) == 1
    assert all(argv[3] not in {"rm", "kill", "start"} for argv in calls)
    assert legacy_path.read_bytes() == before
    assert marker.read_text() == "same database"


def test_fixed_restart_rejects_changed_actual_mapping_before_connection(prepared_controller, monkeypatch):
    controller, _ = prepared_controller()
    monkeypatch.setattr(controller, "provision_graph", PROVISION_GRAPH.__get__(controller, runner.Controller))
    owned = "c" * 64
    runner.save(controller.root / "control/neo4j-v2.json", fixed_graph_descriptor(controller, owned))
    calls = []

    def command(argv, **kwargs):
        calls.append(argv)
        if argv[3] == "inspect":
            return json.dumps(graph_facts(controller, owned))
        if argv[3] == "start":
            return owned
        if argv[3] == "port":
            return "127.0.0.1:32811"
        raise AssertionError("unexpected command")

    monkeypatch.setattr(controller, "command", command)
    with pytest.raises(runner.Refused, match="graph_endpoint_mismatch"):
        controller.provision_graph()
    assert any(argv[3] == "start" for argv in calls)
    observation = runner.load(controller.root / "control/graph-endpoint-observation.json")
    assert observation["expected"] == f"127.0.0.1:{runner.GRAPH_PORT}"
    assert observation["actual"] == "127.0.0.1:32811"


@pytest.mark.parametrize("container_exit,termination", [(0, "graceful-exit-0"), (137, "forced-137")])
def test_graph_stop_records_real_exit_not_just_docker_command_success(prepared_controller, monkeypatch, container_exit, termination):
    controller, _ = prepared_controller()
    owned = "c" * 64
    controller.graph = {"containerId": owned}
    previous = b'{ \"containerId\": \"old\", \"exitCode\": 0, \"dataRetained\": true }\\n'
    old_receipt = controller.root / "control/graph-stop.json"
    old_receipt.write_bytes(previous)

    def command(argv, **kwargs):
        if argv[3] == "stop":
            assert argv[-2:] == ["45", owned] and kwargs["timeout"] == 60
            return SimpleNamespace(returncode=0)
        assert argv[3] == "inspect" and argv[-1] == owned
        return SimpleNamespace(returncode=0, stdout=runner.encoded(graph_facts(controller, owned, exit_code=container_exit)))

    monkeypatch.setattr(runner.subprocess, "run", command)
    controller.stop_owned_graph()
    receipt = runner.load(old_receipt)
    assert receipt["exitCode"] == 0
    assert receipt["containerExitCode"] == container_exit
    assert receipt["termination"] == termination
    assert receipt["containerStopped"] is True and receipt["dataRetained"] is True
    assert Path(receipt["previousReceipt"]["path"]).read_bytes() == previous


def test_refresh_crossing_admission_cutoff_preserves_queued_unit_without_dispatch(prepared_controller, monkeypatch):
    controller, unit = prepared_controller(mode="run", enabled=["luna"])
    controller.queue[unit["unitId"]] = {"state": "queued", "unit": unit, "cohort": None}
    controller.persist_queue()
    runner.save(controller.root / "MANIFEST.json", {"schemaVersion": "zoop-overnight-manifest-1", "runId": runner.RUN_ID})
    runner.save(controller.root / "collection/INDEX.json",
                {"schemaVersion": "zoop-overnight-collection-index-1", "nativeItems": [], "observations": []})
    expired = False
    read_index = runner.indexed_items
    dispatches = []

    def remaining(deadline):
        return -1 if expired and deadline == runner.ADMIT_UNTIL else 3600

    def delayed_index(path, **kwargs):
        nonlocal expired
        items = read_index(path, **kwargs)
        expired = True
        return items

    def forbidden_dispatch(entry):
        dispatches.append(entry)
        raise AssertionError("no unit may be admitted after refresh crosses the cutoff")

    monkeypatch.setattr(runner, "remaining", remaining)
    monkeypatch.setattr(runner, "indexed_items", delayed_index)
    monkeypatch.setattr(controller, "process", forbidden_dispatch)
    result = controller.run("run")
    assert expired and dispatches == []
    assert result["admitted"] == 0 and result["completed"] == 0
    assert controller.queue[unit["unitId"]]["state"] == "queued"
    assert runner.load(controller.queue_path)[unit["unitId"]]["state"] == "queued"
    assert result["budget"]["calls"] == 0
    assert result["budget"]["notAfter"] == runner.SEND_UNTIL == "2026-10-27T20:50:00Z"


def test_check_archives_exact_root_manifest_before_replacing_it(prepared_controller, monkeypatch):
    controller, _ = prepared_controller(day=True)
    master = controller.root / "MANIFEST.json"
    original = b'{\n  "status": "original master", "retained": true\n}\n'
    master.write_bytes(original)
    decoy = controller.root / "control/MANIFEST.json"
    decoy.write_bytes(b'{"status":"control-path-decoy"}\n')
    expected_archive = controller.root / "control/retained" / ("MANIFEST-" + runner.sha(original) + ".json")
    write_json = runner.save
    replaced = False

    def observe_write(path, value, **kwargs):
        nonlocal replaced
        if Path(path) == master:
            assert expected_archive.read_bytes() == original
            assert master.read_bytes() == original
            replaced = True
        return write_json(path, value, **kwargs)

    def preparation_child(argv, **kwargs):
        assert argv[-1] == "--prepare-history"
        assert kwargs["payload"]["items"] == kwargs["payload"]["units"] == []
        return {"units": []}

    monkeypatch.setattr(runner, "save", observe_write)
    monkeypatch.setattr(runner, "indexed_items", lambda path, **kwargs: ([], {}) if kwargs.get("with_metadata") else [])
    monkeypatch.setattr(controller, "command", preparation_child)
    result = controller.check()
    assert result["status"] == "check-ready-for-main"
    assert replaced
    assert expected_archive.read_bytes() == original
    assert master.read_bytes() != original
    assert decoy.read_bytes() == b'{"status":"control-path-decoy"}\n'


def minimal_ready_peer(monkeypatch, controller, *, during_second_call=None):
    """Finite three-call S2/S3/summary peer, retaining real admission and controller lifecycle."""
    calls = []
    original_command = controller.command
    elapsed = [controller.started_monotonic]
    monkeypatch.setattr(runner.time, "monotonic", lambda: elapsed[0])

    class Child:
        next_pid = 900000
        def __init__(self, argv, **kwargs):
            self.argv = argv
            self.pid = Child.next_pid
            Child.next_pid += 1
            self.returncode = None
            self.ticks = 0
            self.killed = False
            self.terminated = False
            assert kwargs["env"][live.SET_ID_VAR] == controller.active_set

        def communicate(self, input=None, timeout=None):
            self.ticks += 1
            elapsed[0] += 301
            if self.ticks == 1:
                calls.append(self)
                if len(calls) == 2 and during_second_call:
                    during_second_call()
                # More than 300 seconds of modeled CLI wall time is harmless:
                # these repeated observations must NEVER terminate this child.
                raise runner.subprocess.TimeoutExpired(self.argv, timeout)
            self.returncode = -9 if self.killed else 0
            return b'{"status":"ok"}', b""

        def terminate(self):
            self.terminated = True
            raise AssertionError("ordinary stop must never terminate a paid child")

        def kill(self):
            self.killed = True

    monkeypatch.setattr(runner.subprocess, "Popen", Child)
    frozen_pins = runner.load(controller.root / "control/CHECK.json")["pins"]["codePins"]
    monkeypatch.setattr(runner, "code_pins", lambda: frozen_pins)

    def cli(label, module, arguments, payload, unit, directory, *, paid=False, env=None):
        if paid:
            original_command(["authored-native-child", label], paid=True, source_unit=unit,
                             output=directory / (label + "-transport.json"))
        if module == "extract":
            return {"jobId": payload["jobId"], "inputDigest": "a" * 64, "state": "ready",
                    "delivery": {"status": "current"}, "provenance": runner.PROVENANCE,
                    "usage": {"executionMode": "live", "replayCalls": 0}, "eventCandidates": [],
                    "counts": {"comparisons": 0, "effectiveRelations": {}}}
        return {"jobId": payload["jobId"], "state": "ready", "delivery": {"status": "current"}, "relations": []}

    def summaries(unit, directory, s2, env):
        original_command(["authored-native-child", "summary"], paid=True, source_unit=unit,
                         output=directory / "summary-transport.json")
        return {"technicalComplete": True}

    monkeypatch.setattr(controller, "cli", cli)
    monkeypatch.setattr(controller, "record_history", lambda *args: {"status": "recorded"})
    monkeypatch.setattr(controller, "project_graph", lambda entry, *args: entry.update(graph={"status": "projected"}))
    monkeypatch.setattr(controller, "summaries", summaries)
    return calls


def test_softstop_during_second_call_drains_current_set_rejects_next_and_cleans_graph(prepared_controller, monkeypatch):
    controller, unit = prepared_controller(mode="run", enabled=["luna"], day=True)
    controller.args.unit = None
    controller.queue[unit["unitId"]] = {"state": "queued", "unit": unit, "cohort": None}
    second = {**unit, "unitId": "test-unit-two"}
    controller.queue[second["unitId"]] = {"state": "queued", "unit": second, "cohort": None}
    controller.persist_queue()
    runner.save(controller.root / "MANIFEST.json", {"runId": runner.RUN_ID})
    monkeypatch.setattr(controller, "refresh", lambda: None)
    calls = minimal_ready_peer(monkeypatch, controller, during_second_call=controller.stop)
    owned = "c" * 64
    data = controller.root / "analysis/neo4j-data/retained"
    data.parent.mkdir(parents=True)
    data.write_text("retained graph")
    controller.graph = {"containerId": owned}
    stopped = []

    def docker(argv, **kwargs):
        if argv[3] == "stop":
            stopped.append(argv[-1])
            assert all(child.returncode is not None for child in calls)
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=0, stdout=runner.encoded(graph_facts(controller, owned)))

    monkeypatch.setattr(runner.subprocess, "run", docker)
    controller.run("run")
    assert len(calls) == 3 and all(not child.terminated and not child.killed for child in calls)
    assert controller.queue[unit["unitId"]]["state"] == "completed"
    assert controller.queue[second["unitId"]]["state"] == "queued"
    assert runner.load(controller.stop_path)["forced"] is False
    assert runner.funding(controller.root).snapshot()["sets"] == {"completed": 1}
    assert stopped == [owned] and data.read_text() == "retained graph"
    assert runner.load(controller.root / "control/graph-stop.json")["containerStopped"] is True


def test_cutoff_between_calls_drains_without_admitting_next_set(prepared_controller, monkeypatch):
    controller, unit = prepared_controller(mode="run", enabled=["luna"], day=True)
    controller.args.unit = None
    controller.queue[unit["unitId"]] = {"state": "queued", "unit": unit, "cohort": None}
    controller.queue["z-next"] = {"state": "queued", "unit": {**unit, "unitId": "z-next"}, "cohort": None}
    runner.save(controller.root / "MANIFEST.json", {"runId": runner.RUN_ID})
    monkeypatch.setattr(controller, "refresh", lambda: None)

    def boundary():
        monkeypatch.setattr(runner, "remaining", lambda deadline: 3600 if deadline == runner.RUN_CONFIG["finishBy"] else 0)
        monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:30:00+00:00")

    calls = minimal_ready_peer(monkeypatch, controller, during_second_call=boundary)
    controller.run("run")
    assert len(calls) == 3
    assert controller.queue["z-next"]["state"] == "queued"
    assert runner.funding(controller.root).snapshot()["stopIntent"]["reason"] == "admission_cutoff"
    assert runner.funding(controller.root).snapshot()["sets"] == {"completed": 1}


def test_first_signal_after_cutoff_is_not_an_emergency(prepared_controller):
    controller, _ = prepared_controller(day=True)
    controller.close_admission("admission_cutoff")
    child = SimpleNamespace(kill=lambda: pytest.fail("first signal must not kill"))
    controller.child = child
    controller.stop()
    assert not controller.force_requested
    killed = []
    child.kill = lambda: killed.append(True)
    controller.stop()
    controller.sync_stop()
    assert killed == [True]
    assert runner.funding(controller.root).snapshot()["stopIntent"]["forced"] is True


def test_same_admitted_set_resumes_known_native_stages_without_new_admission(prepared_controller, monkeypatch):
    controller, unit = prepared_controller(day=True)
    controller.gate("canary")
    selected = runner.history.snapshot_for(unit, controller.catalogue)
    unit = {**unit, "snapshot": selected["snapshot"], "comparisonCoverage": selected["coverage"],
            "snapshotCanonicalMappings": selected["canonicalMappings"]}
    entry = {"state": "started", "unit": unit, "cohort": "luna", "setId": "already-admitted",
             "unitDigest": runner.sha(runner.encoded(unit)), "child": {"pid": 900000, "reaped": True}}
    controller.queue[unit["unitId"]] = entry
    controller.persist_queue()
    budget = runner.funding(controller.root)
    budget.admit_set(entry["setId"], entry["unitDigest"], runner.set_plan(unit))
    # A settled producer receipt exists before restart; no second admission or
    # reservation is permitted for that request, but missing native stages may run.
    route = budget.funding["roles"]["shared-openai"]
    budget.reserve("prior-receipt", "extract", route["recipient"], "a" * 64, 100, account_role="shared-openai", set_id=entry["setId"])
    budget.settle("prior-receipt", 10)
    monkeypatch.setattr(runner, "remaining", lambda deadline: 3540 if deadline == runner.RUN_CONFIG["finishBy"] else 0)
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:31:00+00:00")
    calls = minimal_ready_peer(monkeypatch, controller)
    controller.process(entry)
    assert entry["state"] == "completed" and entry["setId"] == "already-admitted"
    assert len(calls) == 3
    assert budget.snapshot()["calls"] == 1 and budget.snapshot()["sets"] == {"admitted": 1}
    assert budget.snapshot()["chargedUsd"] == "0.000000010"


def test_alive_previous_child_blocks_restart_before_graph_or_dispatch(prepared_controller, monkeypatch):
    controller, unit = prepared_controller(day=True)
    controller.queue[unit["unitId"]] = {"state": "started", "unit": unit, "cohort": "luna",
                                       "child": {"pid": 123, "reaped": False}}
    monkeypatch.setattr(runner.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(controller, "gate", lambda mode: pytest.fail("must not touch graph before prior child exits"))
    with pytest.raises(runner.Refused, match="prior_child_still_running_reconcile_only"):
        controller.run("canary")
    assert controller.queue[unit["unitId"]]["state"] == "started"


def test_source_month_selection_is_fair_and_has_no_2000_unit_cap(prepared_controller):
    controller, unit = prepared_controller(day=True)
    for i in range(2103):
        source = "first" if i < 2100 else "second"
        month = "2026-07" if i % 2 else "2026-10"
        ident = str(i)
        controller.queue[ident] = {"state": "queued", "unit": {**unit, "unitId": ident, "sourceId": source,
                                                             "publication": {"publishedAt": month + "-01T00:00:00Z"}}}
    selected = []
    for _ in range(4):
        key, entry = controller.fair_queue([(k, e) for k, e in controller.queue.items() if e["state"] == "queued"])[0]
        entry.update(state="completed", setId="set-" + key)
        selected.append((entry["unit"]["sourceId"], entry["unit"]["publication"]["publishedAt"][:7]))
    assert [source for source, _ in selected] == ["first", "second", "first", "second"]
    assert selected[0][1] != selected[2][1] and selected[1][1] != selected[3][1]
    assert len(controller.queue) == 2103


def test_real_subprocess_softstop_is_reaped_normally_before_receipt_collection(prepared_controller):
    import threading
    import time

    controller, unit = prepared_controller(day=True)
    controller.gate("canary")
    set_id = "actual-local-child"
    runner.funding(controller.root).admit_set(set_id, "a" * 64, runner.set_plan(unit))
    entry = {"state": "started", "unit": unit, "cohort": "luna", "setId": set_id}
    controller.queue[unit["unitId"]] = entry
    controller.active_set, controller.active_entry = set_id, entry
    controller.active = unit
    ready, release = controller.root / "child-ready", controller.root / "child-release"
    script = (
        "import json,sys,time\nfrom pathlib import Path\n"
        "ready,release=map(Path,sys.argv[1:])\nready.write_text('second-call')\n"
        "end=time.monotonic()+5\n"
        "while not release.exists() and time.monotonic()<end: time.sleep(.01)\n"
        "assert release.exists(), 'controller did not release local child'\n"
        "print(json.dumps({'drained':True}))\n")
    observations = []

    def request_stop():
        deadline = time.monotonic() + 4
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if ready.exists():
            controller.stop()
            observations.append(controller.child.poll())
            release.write_text("finish admitted local work")

    observer = threading.Thread(target=request_stop)
    observer.start()
    try:
        result = controller.command([sys.executable, "-B", "-c", script, str(ready), str(release)],
                                    paid=True, source_unit=unit, output=controller.root / "child-result.json")
    finally:
        observer.join(6)
    assert not observer.is_alive()
    assert observations == [None]
    assert result == {"drained": True}
    assert controller.child is None and controller.child_reaped
    assert entry["child"]["reaped"] is True and entry["child"]["exitCode"] == 0
    assert runner.load(controller.stop_path)["forced"] is False


def test_run_config_requires_explicit_new_namespace_and_preserves_old_window(tmp_path, monkeypatch):
    from zoop_ai_pipeline import live_funding

    root, config_path = tmp_path / "day", tmp_path / "run.json"
    config = {"schemaVersion": "zoop-private-run-4", "funding": {"totalMaxUsd": "4", "sharedMaxUsd": "3.5", "personalMaxUsd": "0.5"}, "runId": "new-run", "root": str(root),
              "admitFrom": "2026-10-28T00:17:00Z", "admitUntil": "2026-10-28T08:30:00Z", "finishBy": "2026-10-28T09:30:00Z",
              "graphPort": 32820, "maxCalls": 100000, "processingActor": ACTOR}
    for name in ("RUN_CONFIG", "RUN_CONFIG_PATH", "ROOT", "RUN_ID", "ADMIT_UNTIL", "GRAPH_PORT", "MAX_CALLS"):
        monkeypatch.setattr(runner, name, getattr(runner, name))
    runner.save(config_path, config)
    args = runner.parse(["--check", "--run-config", str(config_path)])
    runner.configure(args)
    assert args.root == root and runner.RUN_CONFIG == config
    assert runner.profile_env(root, "luna")[live.PROFILE_VAR] == live_funding.CAPPED_PROFILE
    assert live.NOT_AFTER_VAR not in runner.profile_env(root, "luna")
    assert runner.SEND_UNTIL == "2026-10-27T20:50:00Z"
    runner.save(config_path, {**config, "root": str(runner.IMMUTABLE_OLD_ROOT)})
    with pytest.raises(runner.Refused, match="new_day_namespace_required"):
        runner.configure(args)


def test_collector_recovers_every_physical_attempt_when_native_receipt_was_not_saved(prepared_controller, monkeypatch):
    import httpx
    from tests.live_support import Fake, environment, extract_payload, json_response, no_authorization
    from zoop_ai_pipeline import direct_deepseek

    controller, unit = prepared_controller(day=True)
    values = runner.profile_env(controller.root, "luna")
    values.update({live.SET_ID_VAR: "collector-set", direct_deepseek.KEY_VAR: "synthetic-direct-test"})
    environment(monkeypatch, controller.root, **values)
    peer = Fake(lambda request: json_response({"error": "capacity"}, 503)
                if request.url.host == "api.openai.com" else httpx.ReadTimeout("authored"))
    runtime = live.LiveRuntime.from_env(transport=peer.transport)
    budget = runner.funding(controller.root)
    budget.admit_set("collector-set", "a" * 64, runner.set_plan(unit))
    with pytest.raises(live.LiveFailure) as caught:
        runtime.send(runtime.prepare("extract", extract_payload()), attempt_id="logical-lost",
                     authorize=no_authorization, authorize_fallback=no_authorization)
    assert caught.value.uncertain and caught.value.receipt is not None
    directory = controller.root / "analysis/luna" / unit["unitId"]
    state = directory / "extraction"
    state.mkdir(parents=True)
    database = state / "extraction.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE calls(attempt_id TEXT,job_id TEXT,stage TEXT,state TEXT,response TEXT,started_at TEXT,received_at TEXT,verdict TEXT)")
        db.execute("INSERT INTO calls VALUES('logical-lost','lost-job','extract','started',NULL,?,NULL,NULL)", (runner.now(),))
    original = database.read_bytes()
    controller.child_reaped = True
    rows = controller.collect_calls(directory, "extraction", "lost-job", unit)
    assert len(rows) == 1 and rows[0]["response"] is None
    events = [json.loads(line) for line in (controller.root / "events.jsonl").read_text().splitlines()]
    attempts = [event for event in events if event.get("kind") == "attempt"]
    assert len(attempts) == 2
    assert [event["attemptState"] for event in attempts] == ["received", "unknown"]
    assert [event["fundingBucket"] for event in attempts] == ["shared", "personal"]
    assert attempts[0]["reasonCode"] == "live_http_503"
    assert attempts[1]["cost"]["reservedNanoUsd"] > 0
    assert database.read_bytes() == original
    assert budget.snapshot()["calls"] == 2


def test_child_retains_controller_lock_across_parent_descriptor_close(tmp_path):
    import fcntl
    import subprocess

    lock_path = tmp_path / "controller.lock"
    parent = lock_path.open("a+")
    fcntl.flock(parent.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    script = "import sys\nprint('ready',flush=True)\nsys.stdin.buffer.read(1)\n"
    child = subprocess.Popen([sys.executable, "-B", "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             pass_fds=(parent.fileno(),))
    try:
        assert child.stdout.readline() == b"ready\n"
        parent.close()
        with lock_path.open("a+") as restarted:
            with pytest.raises(BlockingIOError):
                fcntl.flock(restarted.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        child.communicate(b"x", timeout=5)
        with lock_path.open("a+") as restarted:
            fcntl.flock(restarted.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        parent.close()
        if child.poll() is None:
            child.kill()
            child.wait()


def test_paid_summary_unknown_exports_attempt_and_closes_set_unknown(prepared_controller, monkeypatch):
    controller, unit = prepared_controller(day=True)
    controller.queue[unit["unitId"]] = {"state": "queued", "unit": unit, "cohort": None}
    runner.save(controller.root / "MANIFEST.json", {"runId": runner.RUN_ID})
    minimal_ready_peer(monkeypatch, controller)
    actual_summaries = runner.Controller.summaries.__get__(controller)
    candidate = {"eventCandidateId": "summary-uncertain", "state": "candidate"}
    def summaries(unit, directory, s2, env):
        return actual_summaries(unit, directory, {"eventCandidates": [candidate]}, env)
    def unknown_summary(argv, **kwargs):
        directory = Path(argv[argv.index("--private-summary") + 1])
        folder = directory / "candidate-summaries" / runner.sha(candidate["eventCandidateId"].encode())[:24]
        runner.save(folder / "issue-summary-intent.json", {"attemptId": "summary-unknown", "stage": "issue-summary",
                                                         "startedAt": runner.now()}, immutable=True)
        budget = runner.funding(controller.root)
        budget.reserve("summary-unknown", "issue-summary", budget.funding["roles"]["shared-openai"]["recipient"],
                       "b" * 64, 100, account_role="shared-openai", set_id=controller.active_set)
        raise runner.Refused("live_response_unknown", unknown=True)
    monkeypatch.setattr(controller, "summaries", summaries)
    monkeypatch.setattr(controller, "command", unknown_summary)
    controller.run("canary")
    entry = controller.queue[unit["unitId"]]
    assert entry["state"] == "unknown"
    assert entry["summaries"]["unknown"] is True
    budget = runner.funding(controller.root)
    assert budget.set_status(entry["setId"]) == "unknown"
    assert budget.snapshot()["states"] == {"reserved": 1}
    events = [json.loads(line) for line in (controller.root / "events.jsonl").read_text().splitlines()]
    assert any(event.get("attemptId") == "summary-unknown" and event["attemptState"] == "unknown" for event in events)


def test_reconcile_restart_exports_settled_and_reserved_before_terminalization(prepared_controller, monkeypatch):
    controller, unit = prepared_controller(day=True)
    selected = runner.history.snapshot_for(unit, {})
    unit = {**unit, "snapshot": selected["snapshot"], "comparisonCoverage": selected["coverage"],
            "snapshotCanonicalMappings": selected["canonicalMappings"]}
    set_id, job = "restart-set", runner.RUN_ID + "-luna-" + unit["unitId"] + "-s2"
    directory = controller.root / "analysis/luna" / unit["unitId"]
    state = directory / "extraction"
    state.mkdir(parents=True)
    budget = runner.funding(controller.root)
    budget.admit_set(set_id, runner.source_identity(unit), runner.set_plan(unit))
    route = budget.funding["roles"]["shared-openai"]
    budget.reserve("known", "extract", route["recipient"], "a" * 64, 100, account_role="shared-openai", set_id=set_id)
    budget.settle("known", 10)
    budget.reserve("unknown", "extract", route["recipient"], "b" * 64, 100, account_role="shared-openai", set_id=set_id)
    receipt = {"funding": {"accountRole": "shared-openai", "bucket": "shared"},
               "cost": {"chargedUsd": "0.000000010", "reservedUsd": "0.000000100", "settled": True}}
    database = state / "extraction.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE calls(attempt_id TEXT,job_id TEXT,stage TEXT,state TEXT,response TEXT,started_at TEXT,received_at TEXT,verdict TEXT)")
        db.execute("INSERT INTO calls VALUES('known',?,'extract','received',?,?,?,NULL)",
                   (job, json.dumps(receipt), runner.now(), runner.now()))
        db.execute("INSERT INTO calls VALUES('unknown',?,'extract','started',NULL,?,NULL,NULL)", (job, runner.now()))
    original = database.read_bytes()
    entry = {"state": "started", "unit": unit, "cohort": "luna", "setId": set_id,
             "analysisDirectory": str(directory), "unitDigest": runner.source_identity(unit),
             "jobs": {"s2": {"jobId": job, "stateName": "extraction"}},
             "child": {"pid": 900000, "reaped": True}}
    controller.queue[unit["unitId"]] = entry
    controller.persist_queue()
    runner.save(controller.root / "MANIFEST.json", {"runId": runner.RUN_ID})
    monkeypatch.setattr(controller, "command", lambda *args, **kwargs: pytest.fail("reconcile-only must not launch any child"))
    controller.run("canary")
    events_path = controller.root / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    attempts = {event["attemptId"]: event["attemptState"] for event in events if event.get("kind") == "attempt"}
    assert attempts == {"known": "received", "unknown": "unknown"}
    assert entry["state"] == "unknown" and budget.set_status(set_id) == "unknown"
    assert entry["receiptExport"]["status"] == "complete"
    assert database.read_bytes() == original
    assert budget.snapshot()["calls"] == 2 and budget.snapshot()["states"] == {"reserved": 1, "settled": 1}


def test_finite_keyless_chunk_drains_after_softstop_without_whole_cli_timeout(prepared_controller, monkeypatch):
    controller, unit = prepared_controller(day=True)
    controller.dispatch_code_pins = runner.code_pins()
    units = [{**unit, "unitId": f"u-{index:03d}"} for index in range(129)]
    clock = [controller.started_monotonic]
    children = []
    monkeypatch.setattr(runner.time, "monotonic", lambda: clock[0])
    class Child:
        pid = 900001
        returncode = None
        def __init__(self, argv, **kwargs):
            self.argv, self.calls, self.payload = argv, 0, json.loads(kwargs["stdin"].read())
            children.append(self)
            assert live.OPENAI_KEY_VAR not in kwargs["env"] and "DEEPSEEK_API_KEY" not in kwargs["env"]
        def communicate(self, input=None, timeout=None):
            self.calls += 1
            clock[0] += 301
            if self.calls == 1:
                controller.stop()
                raise runner.subprocess.TimeoutExpired(self.argv, timeout)
            self.returncode = 0
            return runner.encoded({"units": self.payload["units"]}), b""
        def terminate(self):
            pytest.fail("finite preparation must not terminate at a whole-child wall timeout")
        def kill(self):
            pytest.fail("first stop must drain preparation")
    monkeypatch.setattr(runner.subprocess, "Popen", Child)
    with pytest.raises(runner.Refused, match="history_preparation_stopped"):
        controller.prepare_history([{"item": i} for i in range(129)], units, [])
    assert len(children) == 1 and len(children[0].payload["units"]) == 128
    assert Path(children[0].payload["preparationRoot"]).parent == controller.root / "preparation-v2"
    checkpoints = list((controller.root / "control/history-preparations/v2/chunks").glob("*/complete.json"))
    assert len(checkpoints) == 1 and runner.load(checkpoints[0])["childReaped"] is True
    progress = runner.load(Path(controller.preparation_status["plan"]["path"]).parent / "progress.json")
    assert progress["completedChunks"] == 1 and progress["totalChunks"] == 2 and progress["state"] == "stopped"


def test_finite_preparation_reentry_reuses_only_completed_exact_chunks(prepared_controller, monkeypatch):
    controller, unit = prepared_controller(day=True)
    controller.dispatch_code_pins = runner.code_pins()
    units = [{**unit, "unitId": f"u-{index:03d}"} for index in range(129)]
    items = [{"item": i} for i in range(129)]
    calls, fail = [], [True]
    old = controller.root / "processing/history/retained-partial/ingestion.sqlite3-wal"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"retained interrupted fixture")
    def command(argv, **kwargs):
        assert kwargs["finite_work"] is True and kwargs.get("paid", False) is False
        ids = [item["unitId"] for item in kwargs["payload"]["units"]]
        calls.append(ids)
        if ids == ["u-128"] and fail[0]:
            raise runner.Refused("authored_local_dispatch_refused")
        controller.child_reaped = True
        result = {"units": kwargs["payload"]["units"]}
        runner.save(kwargs["output"], result)
        return result
    monkeypatch.setattr(controller, "command", command)
    with pytest.raises(runner.Refused, match="authored_local_dispatch_refused"):
        controller.prepare_history(items, units, [])
    fail[0] = False
    result = controller.prepare_history(items, units, [])
    assert [len(chunk) for chunk in calls] == [128, 1, 1]
    assert [unit["unitId"] for unit in result] == [unit["unitId"] for unit in units]
    assert old.read_bytes() == b"retained interrupted fixture"


def test_v2_rejects_old_luna_only_approval_shape(prepared_controller):
    controller, _ = prepared_controller(mode="run", enabled=["luna"], day=True)
    check = runner.load(controller.root / "control/CHECK.json")
    runner.save(controller.root / "control/greenlight.json",
                {"checkDigest": check["checkDigest"], "mode": "run", "approvedBy": "Main",
                 "identityPolicy": runner.POLICY, "enabledProfiles": ["luna"]})
    with pytest.raises(runner.Refused, match="explicit_provider_chain_required"):
        controller.gate("run")


@pytest.mark.parametrize("mode", ["canary", "run"])
def test_v2_ordinary_chain_requires_observed_successful_direct_diagnostic(prepared_controller, monkeypatch, mode):
    controller, _ = prepared_controller(mode=mode, enabled=["luna"], day=True)
    path = controller.root / "control/CANARY-deepseek-diagnostic.json"
    canary = runner.load(path)
    runner.save(path, {**canary, "physicalProviderCalls": {}})
    monkeypatch.setattr(runner, "read_named_env", lambda *args: pytest.fail("gate must not load keys"))
    with pytest.raises(runner.Refused, match="successful_provider_chain_canary_required"):
        controller.gate(mode)


def test_v2_approval_and_usage_report_do_not_claim_fallback_disabled(prepared_controller):
    controller, unit = prepared_controller(day=True)
    controller.gate("canary")
    approval = runner.load(controller.root / "control/greenlight.json")
    assert approval["providerChain"]["primary"]["model"] == "gpt-6-luna"
    assert approval["providerChain"]["fallback"]["endpoint"] == "https://api.deepseek.com"
    assert approval["providerChain"]["maxPhysicalAttempts"] == 2
    assert approval["verifier"]["model"] == "jev-1.14.0"
    assert "enabledProfiles" not in approval
    controller.attempt_event(unit, "ds-actual", "extract",
        {"funding": {"bucket": "personal", "accountRole": "personal-deepseek"},
         "model": {"requested": "deepseek-flash", "reported": "deepseek-flash"}},
        runner.now(), runner.now(), "received", controller.root / "retained.json")
    assert controller.physical_provider_calls == {"personal-deepseek": 1}
    assert controller.reported_models == {"deepseek-flash": 1}


def test_controller_freshness_view_updates_without_changing_unit_or_funding_identity(prepared_controller, monkeypatch):
    controller, unit = prepared_controller(day=True)
    item = {"sourceId": unit["sourceId"], "stateDir": str(controller.root / "private"),
            "recordPath": "retained/one.json", "recordSha256": "a" * 64, "privateId": "private-one", "planId": "plan-one"}
    key = runner.item_id(item)
    unit = {**unit, "unitId": key, "freshness": "unknown"}
    entry = {"state": "started", "unit": unit, "setId": "already-admitted", "cohort": "luna"}
    controller.queue[key] = entry
    before, identity = runner.encoded(unit), runner.source_identity(unit)
    mapping = {item["recordPath"]: {"freshness": "backfill", "publicationDay": "2026-08-20"}}
    monkeypatch.setattr(runner, "indexed_items", lambda path, **kwargs: ([item], mapping))
    controller.refresh()
    first = entry["consumerMetadata"]
    proof = Path(first["proofPath"]).read_bytes()
    controller.event("prepare", "ok", unit=unit)
    mapping[item["recordPath"]] = {"freshness": "fresh", "publicationDay": "2026-10-28"}
    controller.refresh()
    controller.event("event-candidate", "ok", unit=unit)
    assert entry["consumerMetadata"]["freshness"] == "fresh"
    assert entry["consumerMetadata"]["proofPath"] != first["proofPath"]
    assert Path(first["proofPath"]).read_bytes() == proof
    assert runner.encoded(unit) == before and runner.source_identity(unit) == identity
    assert entry["state"] == "started" and entry["setId"] == "already-admitted"
    events = [json.loads(line) for line in (controller.root / "events.jsonl").read_text().splitlines()]
    assert [event["freshness"] for event in events] == ["backfill", "fresh"]


def test_canary_provider_usage_excludes_receipts_exported_from_earlier_terminal_sets(prepared_controller, monkeypatch):
    controller, unit = prepared_controller(day=True)
    controller.queue[unit["unitId"]] = {"state": "queued", "unit": unit, "cohort": None}
    old_unit = {**unit, "unitId": "old-diagnostic"}
    old_job = runner.RUN_ID + "-deepseek-diagnostic-old-diagnostic-s2"
    old_directory = controller.root / "analysis/deepseek-diagnostic/old-diagnostic"
    state = old_directory / "extraction"
    state.mkdir(parents=True)
    receipt = {"funding": {"accountRole": "personal-deepseek", "bucket": "personal"},
               "model": {"requested": "deepseek-flash", "reported": "deepseek-flash"}}
    with sqlite3.connect(state / "extraction.sqlite3") as db:
        db.execute("CREATE TABLE calls(attempt_id TEXT,job_id TEXT,stage TEXT,state TEXT,response TEXT,started_at TEXT,received_at TEXT,verdict TEXT)")
        db.execute("INSERT INTO calls VALUES('old-ds',?,'extract','received',?,?,?,NULL)",
                   (old_job, json.dumps(receipt), runner.now(), runner.now()))
    budget = runner.funding(controller.root)
    budget.admit_set("old-diagnostic-set", runner.source_identity(old_unit), runner.set_plan(old_unit))
    budget.finish_set("old-diagnostic-set", "completed")
    controller.queue["old"] = {"state": "completed", "unit": old_unit, "cohort": "deepseek-diagnostic",
                               "queueKind": "deepseek-diagnostic", "setId": "old-diagnostic-set",
                               "analysisDirectory": str(old_directory),
                               "jobs": {"s2": {"jobId": old_job, "stateName": "extraction"}}}
    runner.save(controller.root / "MANIFEST.json", {"runId": runner.RUN_ID})
    minimal_ready_peer(monkeypatch, controller)
    result = controller.run("canary")
    assert result["status"] == "completed"
    assert result["physicalProviderCalls"] == {}
    assert result["canaryLabel"] == "openai-primary-with-direct-deepseek-fallback"
    assert result["providerUsageScope"] == "physical-attempts-of-sets-processed-in-this-batch"
    events = [json.loads(line) for line in (controller.root / "events.jsonl").read_text().splitlines()]
    assert sum(event.get("attemptId") == "old-ds" for event in events) == 1


def test_preparation_chunk_limit_preserves_full_diverse_plan_and_resumes_only_new_chunks(prepared_controller, monkeypatch):
    controller, unit = prepared_controller(day=True)
    controller.args.check, controller.args.preparation_chunks = True, 1
    controller.dispatch_code_pins = runner.code_pins()
    units = [{**unit, "unitId": f"u-{index:03d}", "sourceId": "second" if index >= 128 else "first"}
             for index in range(130)]
    items = [{"item": index} for index in range(130)]
    calls = []
    def command(argv, **kwargs):
        payload = kwargs["payload"]
        assert kwargs["finite_work"] is True
        assert Path(payload["preparationRoot"]) == controller.root / "preparation-v2" / payload["planId"]
        calls.append([unit["unitId"] for unit in payload["units"]])
        controller.child_reaped = True
        result = {"units": payload["units"]}
        runner.save(kwargs["output"], result)
        return result
    monkeypatch.setattr(controller, "command", command)
    first = controller.prepare_history(items, units, [])
    first_status = dict(controller.preparation_status)
    plan_bytes = Path(first_status["plan"]["path"]).read_bytes()
    assert len(first) == 128 and {unit["sourceId"] for unit in first} == {"first", "second"}
    assert first_status["plannedUnits"] == 130 and first_status["pendingUnits"] == 2
    assert len(runner.load(Path(first_status["plan"]["path"]))["unitIds"]) == 130
    second = controller.prepare_history(items, units, [])
    assert len(second) == 130 and controller.preparation_status["pendingUnits"] == 0
    assert controller.preparation_status["planId"] == first_status["planId"]
    assert [len(call) for call in calls] == [128, 2]
    assert Path(first_status["plan"]["path"]).read_bytes() == plan_bytes
    assert len({unit["unitId"] for unit in second}) == 130


def test_prefix_check_pins_full_manifest_but_authorizes_only_validated_ready_units(prepared_controller, monkeypatch):
    controller, unit = prepared_controller(day=True)
    controller.args.check, controller.args.preparation_chunks = True, 1
    items = [{"id": index} for index in range(129)]
    monkeypatch.setattr(runner, "indexed_items", lambda *args, **kwargs: (items, {}))
    monkeypatch.setattr(runner, "item_id", lambda item: f"u-{item['id']:03d}")
    def prepare(item, *args, **kwargs):
        return {**unit, "unitId": runner.item_id(item),
                "publication": {"precision": "unknown", "publishedAt": None, "collectedAt": None},
                "proofPath": str(controller.root / "authored-proof.json"),
                "history": {"proofPath": str(controller.root / "authored-history-proof.json")}}
    monkeypatch.setattr(runner, "prepare_item", prepare)
    def command(argv, **kwargs):
        controller.child_reaped = True
        result = {"units": kwargs["payload"]["units"]}
        runner.save(kwargs["output"], result)
        return result
    monkeypatch.setattr(controller, "command", command)
    monkeypatch.setattr(controller, "cli", lambda *args, **kwargs:
                        {"state": "queued", "delivery": {"status": "current"}, "usage": {"providerCalls": 0}})
    approval_before = (controller.root / "control/greenlight.json").read_bytes()
    result = controller.check()
    checked = runner.load(controller.root / "control/CHECK.json")
    scope = checked["pins"]["inputAuthorization"]
    assert result["units"] == 128
    assert scope["preparation"]["plannedUnits"] == 129 and scope["preparation"]["pendingUnits"] == 1
    assert len(runner.load(Path(scope["inputManifest"]["path"]))["items"]) == 129
    assert len(scope["readyUnitIds"]) == 128
    assert controller.queue["u-128"]["state"] == "awaiting-check"
    assert (controller.root / "control/greenlight.json").read_bytes() == approval_before
    controller.authorized_units = {item["unitId"]: item for item in checked["pins"]["units"]}
    with pytest.raises(runner.Refused, match="input_not_in_current_check"):
        controller.process(controller.queue["u-128"])
    old_plan = runner.load(Path(scope["preparation"]["plan"]["path"]))
    old_chunks = {path: path.read_bytes() for path in (controller.root / "control/history-preparations/v2/chunks").glob("*/complete.json")}
    prepared_ids = []
    def prepare_new(item, *args, **kwargs):
        prepared_ids.append(item["id"])
        return prepare(item, *args, **kwargs)
    monkeypatch.setattr(runner, "prepare_item", prepare_new)
    items.append({"id": 129})
    second = controller.check()
    next_check = runner.load(controller.root / "control/CHECK.json")
    assert prepared_ids == [129]
    assert second["units"] == 129
    assert next_check["checkDigest"] != checked["checkDigest"]
    assert next_check["pins"]["inputAuthorization"]["preparation"]["pendingUnits"] == 1
    assert {path: path.read_bytes() for path in old_chunks} == old_chunks
    next_plan = runner.load(Path(next_check["pins"]["inputAuthorization"]["preparation"]["plan"]["path"]))
    assert next_plan["chunks"][:len(old_plan["chunks"])] == old_plan["chunks"]
    controller.authorized_units = {item["unitId"]: item for item in next_check["pins"]["units"]}
    with pytest.raises(runner.Refused, match="input_not_in_current_check"):
        controller.process(controller.queue["u-129"])
    assert (controller.root / "control/greenlight.json").read_bytes() == approval_before


def test_provider_readiness_reuses_immutable_canaries_across_input_prefix_expansion(prepared_controller):
    import copy
    controller, unit = prepared_controller(day=True)
    original = runner.load(controller.root / "control/CHECK.json")
    pointer = controller.root / "control/CANARY-deepseek-diagnostic.json"
    before = pointer.read_bytes()
    original_report = runner.load(pointer)
    receipt_path = Path(original_report["readinessReceipt"]["path"])
    receipt_before = receipt_path.read_bytes()
    expanded = copy.deepcopy(original)
    expanded["pins"]["units"].append({**unit, "unitId": "newly-validated"})
    expanded["pins"]["consumerMetadata"] = {"newly-validated": {"freshness": "fresh"}}
    expanded["checkDigest"] = runner.sha(runner.encoded(expanded["pins"]))
    assert expanded["checkDigest"] != original["checkDigest"]
    assert runner.provider_approval_digest(expanded["pins"]) == runner.provider_approval_digest(original["pins"])
    runner.require_v2_canaries(controller.root, expanded, "run", None)
    approval = runner.v2_greenlight(expanded, "run")
    assert approval["checkDigest"] == expanded["checkDigest"]
    assert approval["providerApprovalDigest"] == original_report["providerApprovalDigest"]
    assert pointer.read_bytes() == before and receipt_path.read_bytes() == receipt_before
    assert original_report["inputAuthorization"]["checkDigest"] == original["checkDigest"]


@pytest.mark.parametrize("field", ["codePins", "runtimeBindings", "runConfig", "funding"])
def test_provider_readiness_invalidates_changed_code_runtime_config_or_budget(prepared_controller, field):
    import copy
    controller, _ = prepared_controller(day=True)
    original = runner.load(controller.root / "control/CHECK.json")
    changed = copy.deepcopy(original)
    if field == "codePins":
        changed["pins"][field][0]["sha256"] = "0" * 64
    elif field == "runtimeBindings":
        changed["pins"][field]["luna"]["pipeline"]["generation"]["fallback"]["version"] = "different-failure-policy"
    elif field == "runConfig":
        changed["pins"][field]["maxCalls"] -= 1
    else:
        changed["pins"][field]["personalUsd"] = "9"
    changed["checkDigest"] = runner.sha(runner.encoded(changed["pins"]))
    with pytest.raises(runner.Refused, match="successful_provider_chain_canary_required"):
        runner.require_v2_canaries(controller.root, changed, "run", None)


@pytest.mark.parametrize("status", ["blocked", "unknown"])
def test_provider_readiness_never_reuses_failed_or_unknown_canary(prepared_controller, status):
    controller, _ = prepared_controller(day=True)
    checked = runner.load(controller.root / "control/CHECK.json")
    path = controller.root / "control/CANARY-deepseek-diagnostic.json"
    observed = runner.load(path)
    report = runner.load(Path(observed["readinessReceipt"]["path"]))
    runner.save(path, runner.seal_canary_report(controller.root, {**report, "status": status}))
    with pytest.raises(runner.Refused, match="successful_provider_chain_canary_required"):
        runner.require_v2_canaries(controller.root, checked, "canary", "luna")


def test_provider_readiness_requires_retained_original_source_pins_to_remain_valid(prepared_controller):
    controller, unit = prepared_controller(day=True)
    checked = runner.load(controller.root / "control/CHECK.json")
    runner.save(Path(unit["registry"]), {"changed": "revoked-or-reconfigured"})
    with pytest.raises(runner.Refused, match="successful_provider_chain_canary_required"):
        runner.require_v2_canaries(controller.root, checked, "canary", "luna")


def test_v2_refresh_discovers_new_input_without_authorizing_or_preparing_it(prepared_controller, monkeypatch):
    controller, unit = prepared_controller(day=True)
    item = {"sourceId": unit["sourceId"], "stateDir": str(controller.root / "retained"),
            "recordPath": "new/one.json", "recordSha256": "a" * 64, "privateId": "one", "planId": "collection"}
    monkeypatch.setattr(runner, "indexed_items", lambda *args, **kwargs: ([item], {}))
    monkeypatch.setattr(runner, "prepare_item", lambda *args, **kwargs: pytest.fail("new input needs a current explicit keyless CHECK"))
    controller.refresh()
    entry = controller.queue[runner.item_id(item)]
    assert entry["state"] == "awaiting-check" and entry["inputRef"] == item
    assert "setId" not in entry and "unit" not in entry


@pytest.mark.parametrize("end", ["checked-batch", "unit-limit", "checkpoint-pause"])
def test_finite_batch_end_keeps_global_admission_open(prepared_controller, monkeypatch, end):
    controller, unit = prepared_controller(mode="run", enabled=["luna"], day=True)
    controller.args.unit = None
    controller.args.batch_units = 1 if end == "unit-limit" else None
    controller.queue[unit["unitId"]] = {"state": "queued", "unit": unit, "cohort": None}
    controller.queue["unseen"] = {"state": "awaiting-check", "inputRef": {"new": "not-authorized"}}
    if end == "unit-limit":
        second = {**unit, "unitId": "z-next-checked"}
        controller.queue[second["unitId"]] = {"state": "queued", "unit": second, "cohort": None}
        checked = runner.load(controller.root / "control/CHECK.json")
        checked["pins"]["units"].append(second)
        checked["checkDigest"] = runner.sha(runner.encoded(checked["pins"]))
        runner.save(controller.root / "control/CHECK.json", checked)
        runner.save(controller.root / "control/greenlight.json", runner.v2_greenlight(checked, "run"))
    runner.save(controller.root / "MANIFEST.json", {"runId": runner.RUN_ID})
    calls = minimal_ready_peer(monkeypatch, controller,
                               during_second_call=controller.pause if end == "checkpoint-pause" else None)
    monkeypatch.setattr(runner.time, "sleep", lambda _: pytest.fail("a checked finite batch must exit, not wait for new input"))
    result = controller.run("run")
    assert len(calls) == 3 and all(child.returncode == 0 and not child.killed for child in calls)
    assert result["admitted"] == result["completed"] == 1
    assert result["batchEnd"] == ("checkpoint-pause" if end == "checkpoint-pause" else "checked-batch-end")
    assert controller.queue["unseen"]["state"] == "awaiting-check"
    if end == "unit-limit":
        assert controller.queue["z-next-checked"]["state"] == "queued"
    assert not controller.stop_path.exists()
    budget = runner.funding(controller.root)
    assert budget.snapshot()["stopIntent"] is None
    budget.admit_set("next-checked-batch", "c" * 64, runner.set_plan(unit))
    assert budget.set_status("next-checked-batch") == "admitted"


def test_local_pause_cannot_clear_global_stop(prepared_controller):
    controller, _ = prepared_controller(day=True)
    controller.close_admission("operator-stop")
    original = controller.stop_path.read_bytes()
    controller.pause()
    controller.sync_stop()
    assert controller.stop_path.read_bytes() == original
    assert runner.funding(controller.root).snapshot()["stopIntent"]["reason"] == "operator-stop"


def test_selected_revision_requires_current_check_and_unknown_exclusion_is_not_prepared(prepared_controller, monkeypatch):
    controller, _ = prepared_controller(day=True)
    controller.args.exclude_unit = ["2" * 24]
    selected = controller.root / "collection-revisions/new/INDEX.json"
    item = {"recordPath": "retained-unknown.json", "sourceId": "unknown-source"}
    runner.save(selected, {"schemaVersion": "zoop-overnight-collection-index-1", "nativeItems": [], "privateItems": [item]})
    original = selected.read_bytes()
    controller.collection_index = selected
    monkeypatch.setattr(runner, "item_id", lambda _: "2" * 24)
    monkeypatch.setattr(runner, "prepare_item", lambda *args, **kwargs: pytest.fail("preserved unknown must not be re-prepared"))
    result = controller.check()
    assert result["units"] == 0
    checked = runner.load(controller.root / "control/CHECK.json")
    scope = checked["pins"]["inputAuthorization"]
    assert scope["excludedUnitIds"] == ["2" * 24] and scope["collectionIndexPath"] == str(selected)
    manifest = runner.load(scope["inputManifest"]["path"])
    assert manifest["items"] == [item] and Path(manifest["collectionIndex"]["path"]).read_bytes() == original
    assert selected.read_bytes() == original
    runner.save(controller.root / "control/greenlight.json", runner.v2_greenlight(checked, "canary", "luna"))
    controller.collection_index = controller.root / "collection/INDEX.json"
    with pytest.raises(runner.Refused, match="collection_index_requires_current_check"):
        controller.gate("canary")


def test_partial_history_database_is_never_adopted(prepared_controller, monkeypatch):
    controller, unit = prepared_controller(day=True)
    controller.dispatch_code_pins = runner.code_pins()
    def interrupted(argv, **kwargs):
        path = Path(kwargs["payload"]["preparationRoot"]) / "partial.sqlite3"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"unsealed-database")
        raise runner.Refused("authored_interruption")
    monkeypatch.setattr(controller, "command", interrupted)
    with pytest.raises(runner.Refused, match="authored_interruption"):
        controller.prepare_history([{"item": "one"}], [unit], [])
    monkeypatch.setattr(controller, "command", lambda *args, **kwargs: pytest.fail("partial database must not be reused"))
    with pytest.raises(runner.Refused, match="history_partial_checkpoint_reconcile_only"):
        controller.prepare_history([{"item": "one"}], [unit], [])


def test_finish_deadline_reaps_real_owned_child_and_preserves_unknown_reservation(prepared_controller, monkeypatch):
    controller, unit = prepared_controller(day=True)
    controller.gate("canary")
    budget = runner.funding(controller.root)
    set_id = "finish-owned-child"
    budget.admit_set(set_id, runner.source_identity(unit), runner.set_plan(unit))
    route = budget.funding["roles"]["shared-openai"]
    budget.reserve("unfinished-request", "extract", route["recipient"], "a" * 64, 1000,
                   account_role="shared-openai", set_id=set_id)
    entry = {"state": "started", "unit": unit, "cohort": "luna", "setId": set_id}
    controller.queue[unit["unitId"]] = entry
    controller.active, controller.active_set, controller.active_entry = unit, set_id, entry
    sync = controller.sync_stop
    def deadline():
        if controller.child is not None:
            monkeypatch.setattr(runner, "remaining", lambda _: runner.FINISH_RESERVE_SECONDS - 1)
        sync()
    monkeypatch.setattr(controller, "sync_stop", deadline)
    with pytest.raises(runner.Refused, match="controller_finish_deadline") as stopped:
        controller.command([sys.executable, "-c", "import sys,time; time.sleep(30); sys.stdin.buffer.read()"], paid=True,
                           payload={"text": "synthetic delayed reader\n" * 50000},
                           source_unit=unit, output=controller.root / "finished-child.json")
    assert stopped.value.unknown is True
    assert controller.child is None and controller.child_reaped
    assert entry["child"]["reaped"] is True and entry["child"]["exitCode"] == -15
    assert runner.load(controller.root / "finished-child.failure.json")["unknown"] is True
    assert budget.snapshot()["states"] == {"reserved": 1}
    assert budget.snapshot()["buckets"]["shared"]["reservedUsd"] == "0.000001000"
    assert budget.snapshot()["stopIntent"]["reason"] == "finish_deadline"


def test_source_metadata_projection_preserves_original_ids_and_retained_journal_prefix(prepared_controller):
    import hashlib
    import overnight_metrics as metrics

    controller, unit = prepared_controller(day=True)
    source = "sk-telecom-newsroom"
    projected = "redacted-" + hashlib.sha256(json.dumps(source).encode()).hexdigest()[:20]
    prior = {"eventId": "acquisition-prior", "runId": "daytime-20261028", "cohort": "collection-private",
             "phase": "acquisition", "unitId": "day-prior", "sourceId": "prior-newsroom", "status": "ok"}
    inherited = {**prior, "eventId": "acquisition-sk-telecom", "unitId": "day-sk-telecom", "sourceId": source}
    with pytest.raises(metrics.MetricsError, match="event_identifier_invalid"):
        metrics.normalize_event(inherited)
    runner.save(controller.collection_index, {"schemaVersion": "zoop-overnight-collection-index-1",
                "nativeItems": [], "observations": [prior, inherited]})
    index_bytes = controller.collection_index.read_bytes()
    journal = controller.root / "events.jsonl"
    metrics.record_event(journal, prior)
    prefix = journal.read_bytes()
    controller.collection_events()
    assert journal.read_bytes().startswith(prefix)
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    assert [event["sourceId"] for event in events] == ["prior-newsroom", projected]
    assert events[-1]["unitId"] == "day-sk-telecom" and events[-1]["eventId"] == inherited["eventId"]
    assert controller.collection_index.read_bytes() == index_bytes
    complete = journal.read_bytes()
    controller.collection_events()
    assert journal.read_bytes() == complete
    original_unit = {**unit, "sourceId": source}
    controller.event("prepare", "ok", unit=original_unit)
    assert json.loads(journal.read_text().splitlines()[-1])["sourceId"] == projected
    assert original_unit["sourceId"] == source
    retained = journal.read_bytes()
    runner.save(controller.collection_index, {"schemaVersion": "zoop-overnight-collection-index-1",
                "nativeItems": [], "observations": [prior, {**inherited, "sourceId": "changed-newsroom"}]})
    with pytest.raises(runner.Refused, match="collection_event_changed"):
        controller.collection_events()
    assert journal.read_bytes() == retained


def test_large_stdin_is_delivered_once_with_eof_after_first_observation_timeout(prepared_controller):
    import hashlib
    import stat

    controller, _ = prepared_controller(day=True)
    payload = {"text": "bounded synthetic input\n" * 50000}
    expected = runner.encoded(payload)
    script = (
        "import hashlib,json,os,signal,stat,sys,time\n"
        "signal.alarm(4)\n"
        "time.sleep(.75)\n"
        "raw=sys.stdin.buffer.read()\n"
        "print(json.dumps({'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),"
        "'eof':sys.stdin.buffer.read(1)==b'',"
        "'regular':stat.S_ISREG(os.fstat(0).st_mode),"
        "'mode':stat.S_IMODE(os.fstat(0).st_mode)}))\n")
    out = controller.command([sys.executable, "-B", "-c", script], payload=payload, finite_work=True,
                             output=controller.root / "large-input-result.json")
    assert len(expected) > 1024 * 1024
    assert out == {"bytes": len(expected), "sha256": hashlib.sha256(expected).hexdigest(),
                   "eof": True, "regular": True, "mode": stat.S_IRUSR | stat.S_IWUSR}
    assert controller.child is None and controller.child_reaped
    assert runner.load(controller.root / "large-input-result.command.json")["exitCode"] == 0
