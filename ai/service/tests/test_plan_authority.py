"""Deterministic SQLite authority tests; actual installed-CLI/HTTP proof lives in pipeline_tests."""
from __future__ import annotations

import copy
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from zoop_ai_service.config import ConfigError, ExtractionConfig, Principal, RelationConfig, ServiceConfig
from zoop_ai_service.extraction_ledger import ExtractionLedger, Pins
from zoop_ai_service.jobs import ApiError
from zoop_ai_service.plan_authority import FILE, PlanAuthority, canonical, digest, etag, startup_mode
from zoop_ai_service.plan_verify import sha
from zoop_ai_service.relation_ledger import RelationLedger
from zoop_ai_service.relation_wire import RelationSubmit


@pytest.fixture
def world(tmp_path):
    for name in ("service", "worker", "ingestion", "extraction", "relation", "plans"):
        (tmp_path / name).mkdir(mode=0o700)
    producer, relation, verifier, registry = (tmp_path / name for name in ("producer.json", "relation.json", "verifier.json", "sources.json"))
    for path in (producer, relation, verifier, registry):
        path.write_bytes(b"{}\n")
    command = Path(sys.executable).resolve()
    extraction = ExtractionConfig(command, tmp_path / "extraction", tmp_path / "ingestion", registry, producer, None, None, {})
    relations = RelationConfig(command, tmp_path / "relation", extraction.state_dir, extraction.ingestion_state_dir,
                               registry, relation, verifier, None, {})
    config = ServiceConfig((Principal("app", ("a" * 64,), frozenset({"plan.admit", "extraction.submit", "relation.submit"})),
                            Principal("operator", ("b" * 64,), frozenset({"plan.policy"}))),
                           tmp_path / "service", tmp_path / "worker", command, registry, None, 8797, False, {},
                           relation=relations, extraction=extraction, plan_root=tmp_path / "plans")
    from zoop_ai_service.ledger import ProcessLock
    with ProcessLock(config.state_dir):
        pass
    clock = [1000.0]
    authority = PlanAuthority(config, clock=lambda: clock[0])
    policy = {"schemaVersion": "zoop-ai-plan-policy-1", "enabled": True, "principal": "app", "sourceIds": ["synthetic"],
              "sourceKind": "synthetic", "expiresAt": "1970-01-01T00:33:20Z", "promptVersion": "test-prompt",
              "catalogueDigest": "c" * 64, "snapshotDigest": "d" * 64, "topic": None,
              "runtime": {"kind": "replay", "producerReplayDigest": sha(producer.read_bytes()), "topicReplayDigest": None,
                          "relationReplayDigest": sha(relation.read_bytes()), "relationVerifierReplayDigest": sha(verifier.read_bytes())},
              "limits": {"maxPlans": 5, "maxUnits": 5}}
    yield SimpleNamespace(root=tmp_path, config=config, clock=clock, authority=authority, policy=policy)
    authority.close()


def install(world, key="first", document=None):
    current = world.authority.current()
    return world.authority.set_policy("operator", key, document or world.policy, etag(*current[:2]))


def inputs(world, number=1):
    job = "s2p-" + digest({"job": number})
    plan_id, plan_digest = "s2plan-" + digest({"plan": number}), digest({"planDigest": number})
    request = {"schemaVersion": "zoop-extraction-s2-2", "jobId": job,
               "provenance": {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"},
               "topic": None}
    approved = digest(request)
    producer = world.policy["runtime"]["producerReplayDigest"]
    input_digest = digest({"request": request, "replayFixtureHash": producer})
    s3 = "s3p-" + digest({"format": "zoop-plan-admission-relation-job-1", "planId": plan_id, "planDigest": plan_digest,
                           "upstream": {"jobId": job, "inputDigest": input_digest}})
    submission = {"schemaVersion": "zoop-relation-s3", "jobId": s3, "provenance": request["provenance"],
                  "upstream": {"jobId": job, "inputDigest": input_digest}}
    approval = {"principal": "app", "jobId": job, "approvedRequestDigest": approved, "request": request,
                "producerReplayDigest": producer, "topicReplayDigest": None}
    manifest = {"schemaVersion": "zoop-ai-plan-manifest-1", "planId": plan_id, "planDigest": plan_digest,
                "receiptSha256": "e" * 64, "principal": "app", "round": {"sourceId": "synthetic", "roundId": str(number),
                "ingestionInputDigest": "f" * 64}, "provenance": request["provenance"], "units": [{"unitKey": job,
                "extractionSubmit": {"schemaVersion": "zoop-extraction-s2-2", "jobId": job, "approvedRequestDigest": approved},
                "extractionInputDigest": input_digest, "relationSubmit": submission}]}
    manifest["manifestDigest"] = digest(manifest)
    grants = [{"s2": job, "s3": s3, "approval": approval, "submission": submission}]
    return manifest, grants


def admit(world, number=1, captured=None, check=lambda: None):
    manifest, grants = inputs(world, number)
    return world.authority.commit("app", captured or world.authority.capture("app"), manifest, {"syntheticVerification": True}, grants, check)


def test_default_policy_is_unconfigured_and_cannot_admit(world):
    state = world.authority.policy_status()
    assert state == {"schemaVersion": "zoop-ai-plan-policy-state-1", "revision": 0, "policyDigest": None, "policy": None,
                     "status": "unconfigured", "usage": {"plans": 0, "units": 0}}
    with pytest.raises(ApiError, match="admission_disabled"):
        world.authority.capture("app")


def test_exact_admission_identity_replay_manifest_and_pair_are_immutable(world):
    install(world)
    created, accepted = admit(world)
    assert created
    expected = "pa-" + digest({"format": "zoop-plan-admission-identity-1", "principal": "app",
                               "planId": accepted["manifest"]["planId"], "planDigest": accepted["manifest"]["planDigest"]})
    assert accepted["admissionId"] == expected
    world.clock[0] += 1
    repeated, result = admit(world)
    assert not repeated and result == accepted
    assert world.authority.policy_status()["usage"] == {"plans": 1, "units": 1}
    manifest, grants = inputs(world)
    approval = world.authority.resolve_s2("app", grants[0]["s2"], grants[0]["approval"]["approvedRequestDigest"])
    relation = world.authority.resolve_s3("app", grants[0]["s3"], RelationSubmit.model_validate(grants[0]["submission"]))
    assert approval.authority_ref == relation.authority_ref == expected
    assert world.authority.find("app", manifest["planId"], manifest["planDigest"], query=True) == accepted
    with pytest.raises(sqlite3.IntegrityError):
        world.authority._db.execute("UPDATE grants SET owner='operator'")
    with pytest.raises(sqlite3.IntegrityError):
        world.authority._db.execute("UPDATE admissions SET manifest='{}'")


def test_other_principal_query_is_indistinguishable_and_digest_cannot_change(world):
    install(world)
    _, accepted = admit(world)
    manifest = accepted["manifest"]
    with pytest.raises(ApiError, match="admission_not_found"):
        world.authority.find("operator", manifest["planId"], manifest["planDigest"], query=True)
    with pytest.raises(ApiError, match="idempotency_conflict"):
        world.authority.find("app", manifest["planId"], "0" * 64)
    with pytest.raises(ApiError, match="policy_denied"):
        world.authority.capture("operator")


def test_policy_cas_historical_receipt_and_changed_expected_etag(world):
    first = install(world)
    disabled = {"schemaVersion": "zoop-ai-plan-policy-1", "enabled": False}
    second = install(world, "disable", disabled)
    assert second["revision"] == 2
    assert world.authority.set_policy("operator", "first", world.policy, etag(0, None)) == first
    assert world.authority.current()[0] == 2
    with pytest.raises(ApiError, match="idempotency_conflict"):
        world.authority.set_policy("operator", "first", world.policy, etag(2, digest(disabled)))
    with pytest.raises(ApiError, match="policy_conflict") as caught:
        world.authority.set_policy("operator", "new-stale", world.policy, etag(0, None))
    assert caught.value.status == 412
    same = install(world, "disabled-again", disabled)
    assert not same["changed"] and same["revision"] == 2


def test_revisions_retire_all_admissions_without_refund_or_regrant(world):
    install(world)
    _, accepted = admit(world)
    install(world, "disable", {"schemaVersion": "zoop-ai-plan-policy-1", "enabled": False})
    install(world, "restore")
    created, history = admit(world)
    assert not created and history["admissionId"] == accepted["admissionId"]
    assert history["policyRevision"] == 1 and history["authority"] == {"state": "inactive", "reason": "policy_disabled"}
    assert world.authority.policy_status()["usage"] == {"plans": 1, "units": 1}
    assert admit(world, 2)[1]["policyRevision"] == 3


def test_observed_expiry_is_terminal_across_clock_rollback_and_restart(world):
    first = install(world)
    _, accepted = admit(world)
    world.clock[0] = 2000
    with pytest.raises(ApiError, match="policy_expired"):
        world.authority.capture("app")
    world.clock[0] = 900
    assert world.authority.policy_status()["status"] == "expired"
    second = PlanAuthority(world.config, clock=lambda: world.clock[0])
    try:
        assert second.find("app", accepted["manifest"]["planId"], accepted["manifest"]["planDigest"])["authority"]["reason"] == "policy_expired"
        with pytest.raises(ApiError, match="policy_expired"):
            second.capture("app")
        # A historical install receipt remains history, even after expiry.
        assert second.set_policy("operator", "first", world.policy, etag(0, None)) == first
    finally:
        second.close()


def test_policy_change_during_verification_cannot_commit(world):
    install(world)
    captured = world.authority.capture("app")
    changed = copy.deepcopy(world.policy)
    changed["sourceIds"].append("second")
    install(world, "replace", changed)
    with pytest.raises(ApiError, match="policy_changed"):
        admit(world, captured=captured)
    assert world.authority.policy_status()["usage"] == {"plans": 0, "units": 0}
    assert world.authority._db.execute("SELECT COUNT(*) FROM grants").fetchone()[0] == 0


def test_final_quota_slot_is_atomic_across_connections_and_revisions(world):
    world.policy["limits"] = {"maxPlans": 1, "maxUnits": 1}
    install(world)
    other = PlanAuthority(world.config, clock=lambda: world.clock[0])
    barrier = Barrier(2)
    def compete(authority, number):
        captured = authority.capture("app")
        manifest, grants = inputs(world, number)
        barrier.wait()
        try:
            return authority.commit("app", captured, manifest, {}, grants, lambda: None)[0]
        except ApiError as error:
            return error.code
    try:
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(compete, world.authority, 1), pool.submit(compete, other, 2)]
            outcomes = [future.result() for future in futures]
        assert outcomes.count(True) == 1 and outcomes.count("quota_exhausted") == 1
        install(world, "disable", {"schemaVersion": "zoop-ai-plan-policy-1", "enabled": False})
        install(world, "restore")
        with pytest.raises(ApiError, match="quota_exhausted"):
            admit(world, 3)
        assert world.authority.policy_status()["usage"] == {"plans": 1, "units": 1}
    finally:
        other.close()


def test_refused_recheck_rolls_back_every_admission_grant_and_debit(world):
    install(world)
    def changed():
        raise ApiError(409, "plan_verification_failed")
    with pytest.raises(ApiError, match="plan_verification_failed"):
        admit(world, check=changed)
    assert world.authority._db.execute("SELECT COUNT(*) FROM admissions").fetchone()[0] == 0
    assert world.authority._db.execute("SELECT COUNT(*) FROM grants").fetchone()[0] == 0
    assert world.authority.policy_status()["usage"] == {"plans": 0, "units": 0}
    assert admit(world)[0]


def test_nonallocated_relation_id_and_changed_upstream_are_denied(world):
    install(world)
    admit(world)
    _, grants = inputs(world)
    submission = grants[0]["submission"]
    with pytest.raises(ApiError, match="upstream_not_allowed"):
        world.authority.resolve_s3("app", "arbitrary-second-job", RelationSubmit.model_validate({**submission, "jobId": "arbitrary-second-job"}))
    changed = {**submission, "upstream": {**submission["upstream"], "inputDigest": "0" * 64}}
    with pytest.raises(ApiError, match="upstream_not_allowed"):
        world.authority.resolve_s3("app", submission["jobId"], RelationSubmit.model_validate(changed))


def test_service_reservations_and_dispatch_claims_keep_immutable_origin(world):
    install(world)
    _, accepted = admit(world)
    manifest, grants = inputs(world)
    grant = grants[0]
    extraction = ExtractionLedger(world.config.state_dir, world.config.extraction.state_dir)
    relation = RelationLedger(world.config.state_dir, world.config.relation.state_dir)
    try:
        pins = Pins(grant["approval"]["approvedRequestDigest"], grant["approval"]["producerReplayDigest"], None,
                    manifest["units"][0]["extractionInputDigest"])
        origin = accepted["admissionId"]
        e = extraction.reserve(grant["s2"], "app", "a" * 64, pins, origin)
        extraction.accept(e.job_id, "app", 100)
        claim = extraction.claim_next()
        assert claim.authority_ref == e.authority_ref == origin and world.authority.refuse_s2(claim) is None
        r = relation.reserve(grant["s3"], "app", "b" * 64, e.job_id, e.input_digest, authority_ref=origin)
        relation.accept(r.job_id, "app", "c" * 64, 100)
        assert relation.claim_next().authority_ref == origin
        with pytest.raises(sqlite3.IntegrityError):
            extraction._db.execute("UPDATE extraction_jobs SET authority_ref='other'")
        with pytest.raises(sqlite3.IntegrityError):
            relation._db.execute("UPDATE relation_jobs SET authority_ref='other'")
        old = extraction.reserve("manual-job", "app", "d" * 64, pins)
        assert extraction.reserve(old.job_id, "app", "d" * 64, pins, origin).authority_ref is None
        install(world, "disable", {"schemaVersion": "zoop-ai-plan-policy-1", "enabled": False})
        assert world.authority.refuse_s2(claim) == "policy_disabled"
    finally:
        extraction.close()
        relation.close()


def test_populated_manual_and_online_profiles_cannot_switch_origins(world, tmp_path):
    with pytest.raises(ConfigError, match="ZOOP_AI_SERVICE_STATE_DIR") as caught:
        startup_mode(replace(world.config, plan_root=None))
    assert caught.value.reason == "authority_mode_mismatch"
    manual = tmp_path / "manual"
    manual.mkdir(mode=0o700)
    (manual / "service.sqlite3").write_bytes(b"manual history")
    with pytest.raises(ConfigError) as caught:
        startup_mode(replace(world.config, state_dir=manual))
    assert caught.value.reason == "authority_mode_mismatch"


def test_missing_authority_store_never_resets_usage(world):
    install(world)
    admit(world)
    (world.config.state_dir / FILE).unlink()
    with pytest.raises(ConfigError) as caught:
        startup_mode(world.config)
    assert caught.value.reason == "authority_unavailable"
    with pytest.raises(ApiError, match="authority_unavailable"):
        world.authority.policy_status()


def test_corrupt_or_foreign_store_cannot_be_initialized_as_empty(world, tmp_path):
    corrupt = tmp_path / "corrupt"
    corrupt.mkdir(mode=0o700)
    (corrupt / FILE).write_bytes(b"not sqlite")
    with pytest.raises(ConfigError) as caught:
        PlanAuthority(replace(world.config, state_dir=corrupt))
    assert caught.value.reason == "authority_unavailable"
    altered = replace(world.config, plan_root=world.config.extraction.ingestion_state_dir)
    with pytest.raises(ConfigError) as caught:
        PlanAuthority(altered)
    assert caught.value.reason == "authority_unavailable"


def test_sqlite_failure_after_admission_insert_rolls_back_the_entire_pair(world):
    install(world)
    world.authority._db.execute("CREATE TRIGGER fail_pair BEFORE INSERT ON grants BEGIN SELECT RAISE(ABORT,'synthetic write failure'); END")
    with pytest.raises(ApiError, match="authority_unavailable"):
        admit(world)
    assert world.authority._db.execute("SELECT COUNT(*) FROM admissions").fetchone()[0] == 0
    assert world.authority._db.execute("SELECT COUNT(*) FROM grants").fetchone()[0] == 0
    assert world.authority.policy_status()["usage"] == {"plans": 0, "units": 0}
    world.authority._db.execute("DROP TRIGGER fail_pair")
    assert admit(world)[0]


def test_committed_admission_survives_lost_reply_and_reopens_without_second_debit(world):
    install(world)
    _, original = admit(world)
    reopened = PlanAuthority(world.config, clock=lambda: world.clock[0])
    try:
        manifest, grants = inputs(world)
        created, recovered = reopened.commit("app", reopened.capture("app"), manifest, {"changedAfterReplyLoss": True}, grants, lambda: None)
        assert not created and recovered == original
        assert reopened.policy_status()["usage"] == {"plans": 1, "units": 1}
        assert reopened._db.execute("SELECT COUNT(*) FROM grants").fetchone()[0] == 1
    finally:
        reopened.close()


def test_policy_rejects_unknown_owner_and_already_expired_new_install(world):
    unknown = {**world.policy, "principal": "unknown"}
    with pytest.raises(ApiError, match="invalid_request"):
        install(world, document=unknown)
    expired = {**world.policy, "expiresAt": "1970-01-01T00:00:01Z"}
    with pytest.raises(ApiError, match="policy_expired"):
        install(world, document=expired)
    assert world.authority.current() == (0, None, None)
    assert world.authority._db.execute("SELECT COUNT(*) FROM policy_operations").fetchone()[0] == 0


def test_online_facade_never_follows_a_plan_reference_symlink(world):
    from zoop_ai_service.jobs import Observation
    from zoop_ai_service.plan_admission import PlanAdmissionService
    from zoop_ai_service.plan_wire import PlanReference
    install(world)
    manifest, _ = inputs(world)
    external = world.root / "outside-plan"
    external.mkdir()
    (world.config.plan_root / manifest["planId"]).symlink_to(external, target_is_directory=True)
    service = PlanAdmissionService(world.config, world.authority)
    reference = PlanReference.model_validate({"schemaVersion": "zoop-ai-plan-admission-1",
                                              "planId": manifest["planId"], "planDigest": manifest["planDigest"]})
    with pytest.raises(ApiError, match="plan_not_found") as caught:
        service.admit("app", reference, Observation())
    assert caught.value.status == 404
    assert world.authority.policy_status()["usage"] == {"plans": 0, "units": 0}


def test_missing_store_constructor_cannot_recreate_an_online_profile(world):
    (world.config.state_dir / FILE).unlink()
    with pytest.raises(ConfigError) as caught:
        PlanAuthority(world.config)
    assert caught.value.reason == "authority_unavailable"
    assert not (world.config.state_dir / FILE).exists()


def test_policy_history_capacity_cannot_prevent_disable_or_replacement(world, monkeypatch):
    from zoop_ai_service import plan_authority
    monkeypatch.setattr(plan_authority, "MAX_RECORDS", 2)
    install(world)
    unchanged = install(world, "no-op")
    assert not unchanged["changed"]
    disabled = install(world, "disable-at-capacity", {"schemaVersion": "zoop-ai-plan-policy-1", "enabled": False})
    assert disabled["changed"] and disabled["revision"] == 2
    replaced = install(world, "restore-after-capacity")
    assert replaced["changed"] and replaced["revision"] == 3
    assert world.authority._db.execute("SELECT COUNT(*) FROM policy_operations").fetchone()[0] == 4
    assert world.authority.set_policy("operator", "first", world.policy, etag(0, None))["revision"] == 1


def test_missing_online_process_lock_is_refused_without_creating_a_replacement(world):
    from zoop_ai_service.ledger import ProcessLock
    from zoop_ai_service.main import build_service
    original = ProcessLock(world.config.state_dir)
    path = world.config.state_dir / "service.lock"
    original_identity = path.stat().st_ino
    path.unlink()
    try:
        with pytest.raises(ConfigError):
            build_service(world.config)
        assert not path.exists(), "a populated online profile must not create a second lock inode"
        assert original_identity > 0
    finally:
        original.close()


def test_s3_receipt_pins_close_fixture_swap_back_and_provenance_races(world):
    install(world)
    _, accepted = admit(world)
    _, grants = inputs(world)
    grant = grants[0]
    row = SimpleNamespace(owner="app", job_id=grant["s3"], authority_ref=accepted["admissionId"])
    runtime = world.policy["runtime"]
    raw = {"jobId": row.job_id, "inputDigest": digest(grant["submission"]), "provenance": grant["submission"]["provenance"],
           "binding": {"upstream": grant["submission"]["upstream"]},
           "calls": [{"stage": "relation", "fixtureHash": runtime["relationReplayDigest"]},
                     {"stage": "verify-relation", "fixtureHash": runtime["relationVerifierReplayDigest"]}]}
    assert world.authority.refuse_s3_result(row, raw) is None
    altered = copy.deepcopy(raw)
    altered["calls"][0]["fixtureHash"] = "0" * 64
    assert world.authority.refuse_s3_result(row, altered) == "fixture_changed"
    altered = copy.deepcopy(raw)
    altered["calls"][1]["fixtureHash"] = "0" * 64
    assert world.authority.refuse_s3_result(row, altered) == "fixture_changed"
    altered = copy.deepcopy(raw)
    altered["provenance"]["sourceKind"] = "actual"
    assert world.authority.refuse_s3_result(row, altered) == "runtime_binding_mismatch"


def test_replacement_lock_inode_cannot_rebind_an_existing_authority_profile(world):
    from zoop_ai_service.ledger import ProcessLock
    install(world)
    admit(world)
    path = world.config.state_dir / "service.lock"
    retained = world.config.state_dir / "original-lock"
    original = path.stat()
    path.rename(retained)
    try:
        with ProcessLock(world.config.state_dir) as replacement:
            assert replacement.identity != (original.st_dev, original.st_ino)
            with pytest.raises(ConfigError) as caught:
                PlanAuthority(world.config)
            assert caught.value.reason == "authority_unavailable"
        path.unlink()
    finally:
        retained.rename(path)
    assert world.authority.policy_status()["usage"] == {"plans": 1, "units": 1}
