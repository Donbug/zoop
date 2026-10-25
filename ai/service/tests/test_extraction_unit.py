"""S2 extraction jobs, everything that needs no installed pipeline: the all-or-nothing configuration group (and its sharing with S3), the strict approvals
manifest, the authority table, the service ledger's frozen identity, the dispatch policy, the exit-code interpretation, the strict caller body, the
allowlisted projection and the disabled-feature routes.

The behavior that needs the real `zoop-ai-extract` (lifecycle, isolation, rotation, crash recovery, the S2 -> S3 chain) lives in `ai/service/pipeline_tests`
and runs with `make service-pipeline-test`.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from support import Workspace, document_replay
from zoop_ai_service import extraction_access, extraction_doc, relation_access
from zoop_ai_service.config import EXTRACTION_OWN, EXTRACTION_TOPIC, EXTRACTION_VARS, RELATION_VARS, ConfigError, load
from zoop_ai_service.extraction_access import SCHEMA as APPROVALS_SCHEMA
from zoop_ai_service.extraction_dispatch import BUSY_CODES, call_pin_problem
from zoop_ai_service.extraction_ledger import LEDGER_SCHEMA, MIGRATES_FROM, ExtractionLedger, Pins
from zoop_ai_service.extraction_runtime import interpret
from zoop_ai_service.extraction_wire import (ExtractionErrorEnvelope, ExtractionJobContent, ExtractionJobStatus, ExtractionResultEnvelope,
                                             ExtractionSubmit, ExtractionView)
from zoop_ai_service.relation_dispatch import policy
from zoop_ai_service.relation_ledger import Update
from zoop_ai_service.relation_runtime import interpret as relation_interpret
from zoop_ai_service.runtime import Outcome

PRODUCER, TOPIC = "a" * 64, "b" * 64
REQUEST = {"schemaVersion": "zoop-extraction-s2-2", "jobId": "s2-job",
           "provenance": {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"}, "promptVersion": "prompt-1",
           "incoming": {"roundId": "r", "sourceId": "s", "page": 0, "ordinal": 0, "documentId": "d", "rawVersion": "c" * 64, "documentVersion": "d" * 64},
           "catalogue": {"revision": "c1", "companies": []}, "snapshot": {"revision": "snapshot-1", "events": []},
           "topic": {"producerVersion": "zoop-topic-replay-producer-1"}}
PLAIN = {**REQUEST, "jobId": "s2-plain", "topic": None}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def entry(request: dict[str, Any] = REQUEST, principal: str = "alpha", **overrides: Any) -> dict[str, Any]:
    base = {"principal": principal, "jobId": request["jobId"], "approvedRequestDigest": digest(request), "request": request,
            "producerReplayDigest": PRODUCER, "topicReplayDigest": TOPIC if request["topic"] is not None else None}
    return {**base, **overrides}


def document(*entries: dict[str, Any], **top: Any) -> str:
    return json.dumps({"schemaVersion": APPROVALS_SCHEMA, "approvals": list(entries), **top})


def extraction_env(ws: Workspace, root: Path, **overrides: str | None) -> dict[str, str]:
    """A complete S2 group over throwaway files. The command is never run by `load`, so any executable file serves."""
    for name in ("extraction", "ingestion", "app"):
        (root / name).mkdir(exist_ok=True)
    for name in ("sources.json", "s2-replay.json", "s2-topic.json"):
        (root / name).write_text("{}")
    (root / "approvals.json").write_text(document(entry(), entry(PLAIN), entry(PLAIN, "beta")))
    env = ws.env()
    env.update({
        "ZOOP_AI_SERVICE_EXTRACTION_COMMAND": sys.executable, "ZOOP_AI_EXTRACTION_STATE_DIR": str(root / "extraction"),
        "ZOOP_AI_INGESTION_STATE_DIR": str(root / "ingestion"), "ZOOP_AI_SERVICE_SOURCES": str(root / "sources.json"),
        "ZOOP_AI_SERVICE_EXTRACTION_REPLAY": str(root / "s2-replay.json"), "ZOOP_AI_SERVICE_EXTRACTION_TOPIC_REPLAY": str(root / "s2-topic.json"),
        "ZOOP_AI_SERVICE_EXTRACTION_APPROVALS": str(root / "approvals.json"), "ZOOP_STATE_DIR": str(root / "app")})
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def relation_part(root: Path) -> dict[str, str]:
    for name in ("producer.json", "verifier.json"):
        (root / name).write_text("{}")
    (root / "upstreams.json").write_text(json.dumps({"schemaVersion": relation_access.SCHEMA, "upstreams": []}))
    return {"ZOOP_AI_SERVICE_RELATION_COMMAND": sys.executable, "ZOOP_AI_RELATION_STATE_DIR": str(root / "relation"),
            "ZOOP_AI_SERVICE_RELATION_REPLAY": str(root / "producer.json"), "ZOOP_AI_SERVICE_RELATION_VERIFIER_REPLAY": str(root / "verifier.json"),
            "ZOOP_AI_SERVICE_RELATION_UPSTREAMS": str(root / "upstreams.json")}


def refused(env: dict[str, str]) -> ConfigError:
    with pytest.raises(ConfigError) as caught:
        load(env)
    return caught.value


# ---- configuration: all or nothing, shared with S3 ----------------------------------------------------------------------------

def test_without_any_extraction_variable_the_feature_is_off(tmp_path):
    config = load(Workspace(tmp_path, replay=document_replay()).env())
    assert config.extraction is None and config.relation is None


def test_a_complete_group_loads_and_hands_the_child_only_ownership_roots(tmp_path):
    ws = Workspace(tmp_path, replay=document_replay())
    config = load(extraction_env(ws, tmp_path))
    extraction = config.extraction
    assert config.relation is None and extraction is not None
    assert extraction.state_dir == tmp_path / "extraction" and extraction.topic_replay == tmp_path / "s2-topic.json"
    assert dict(extraction.child_env) == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
                                          "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1", "ZOOP_STATE_DIR": str(tmp_path / "app"),
                                          "ZOOP_AI_WORKER_STATE_DIR": str(ws.worker)}


def test_no_provider_key_url_model_or_live_switch_ever_reaches_the_child(tmp_path):
    ws = Workspace(tmp_path, replay=document_replay())
    live = {"ZOOP_AI_LIVE_ENABLED": "1", "ZOOP_AI_GLOBAL_MAX_CALLS": "5", "ZOOP_AI_API_KEY": "k-secret", "ZOOP_AI_BASE_URL": "http://127.0.0.1:1",
            "ZOOP_AI_PROVIDER": "openai", "ZOOP_AI_DOCUMENT_SUMMARY_MODEL": "m", "OPENAI_API_KEY": "k-other", "HTTPS_PROXY": "http://127.0.0.1:2",
            "ZOOP_AI_VERIFY_PROVIDER": "typesafe-native", "TYPESAFE_API_KEY": "k-jev-secret", "TYPESAFE_BASE_URL": "http://127.0.0.1:3/v1",
            "TYPESAFE_VALIDATION_MODEL": "jev-1.14.0"}
    extraction = load(extraction_env(ws, tmp_path, **live)).extraction
    assert extraction is not None
    assert not set(extraction.child_env) & (set(live) | {"HOME", "OPENAI_BASE_URL"}) and "k-secret" not in json.dumps(dict(extraction.child_env))


@pytest.mark.parametrize("name", EXTRACTION_VARS)
def test_a_partial_group_refuses_to_start_and_names_the_missing_variable(tmp_path, name):
    error = refused(extraction_env(Workspace(tmp_path, replay=document_replay()), tmp_path, **{name: None}))
    assert (error.field, error.reason) == (name, "extraction_group_incomplete")


def test_the_optional_topic_fixture_alone_is_an_incomplete_group_and_its_absence_is_fine(tmp_path):
    ws = Workspace(tmp_path, replay=document_replay())
    only = ws.env()
    only[EXTRACTION_TOPIC] = str(tmp_path / "x.json")
    error = refused(only)
    assert error.reason == "extraction_group_incomplete" and error.field in EXTRACTION_VARS
    env = extraction_env(ws, tmp_path, **{EXTRACTION_TOPIC: None})
    (tmp_path / "approvals.json").write_text(document(entry(PLAIN)))  # no request asks for a topic stage
    config = load(env).extraction
    assert config is not None and config.topic_replay is None


def test_every_member_of_the_group_is_validated_when_any_is_present(tmp_path):
    ws = Workspace(tmp_path, replay=document_replay())
    assert refused(extraction_env(ws, tmp_path, ZOOP_STATE_DIR=None)).field == "ZOOP_STATE_DIR"
    assert refused(extraction_env(ws, tmp_path, ZOOP_STATE_DIR="relative")).field == "ZOOP_STATE_DIR"
    assert refused(extraction_env(ws, tmp_path, ZOOP_AI_SERVICE_EXTRACTION_COMMAND=str(tmp_path / "sources.json"))).reason == "file_unusable"
    assert refused(extraction_env(ws, tmp_path, ZOOP_AI_SERVICE_EXTRACTION_COMMAND="relative/cli")).reason == "not_absolute_normalized"
    assert refused(extraction_env(ws, tmp_path, ZOOP_AI_EXTRACTION_STATE_DIR=str(tmp_path / "absent"))).reason == "directory_missing"
    assert refused(extraction_env(ws, tmp_path, ZOOP_AI_INGESTION_STATE_DIR=str(tmp_path / "absent"))).reason == "directory_missing"
    for name in ("ZOOP_AI_SERVICE_SOURCES", "ZOOP_AI_SERVICE_EXTRACTION_REPLAY", "ZOOP_AI_SERVICE_EXTRACTION_TOPIC_REPLAY",
                 "ZOOP_AI_SERVICE_EXTRACTION_APPROVALS"):
        error = refused(extraction_env(ws, tmp_path, **{name: str(tmp_path / "absent.json")}))
        assert (error.field, error.reason) == (name, "file_unusable")
    link = tmp_path / "linked"
    link.symlink_to(tmp_path / "extraction", target_is_directory=True)
    assert refused(extraction_env(ws, tmp_path, ZOOP_AI_EXTRACTION_STATE_DIR=str(link))).reason == "symlinked_component"


def test_the_five_state_roots_may_not_overlap_each_other(tmp_path):
    ws = Workspace(tmp_path, replay=document_replay())
    extraction_env(ws, tmp_path)
    (tmp_path / "ingestion" / "inner").mkdir()
    for name, value in (("ZOOP_AI_EXTRACTION_STATE_DIR", str(tmp_path / "ingestion" / "inner")),
                        ("ZOOP_AI_INGESTION_STATE_DIR", str(tmp_path / "extraction")), ("ZOOP_STATE_DIR", str(tmp_path / "extraction"))):
        assert refused(extraction_env(ws, tmp_path, **{name: value})).reason in {"extraction_roots_overlap", "overlaps_app_state"}, (name, value)


def test_both_groups_share_one_set_of_roots_and_either_can_be_on_alone(tmp_path):
    ws = Workspace(tmp_path, replay=document_replay())
    env = extraction_env(ws, tmp_path)
    both = load({**env, **relation_part(tmp_path)})
    assert both.extraction is not None and both.relation is not None
    assert (both.extraction.state_dir, both.extraction.ingestion_state_dir, both.extraction.sources_path) == (
        both.relation.extraction_state_dir, both.relation.ingestion_state_dir, both.relation.sources_path)
    only_s3 = {name: value for name, value in {**env, **relation_part(tmp_path)}.items()
               if name not in {"ZOOP_AI_SERVICE_EXTRACTION_COMMAND", "ZOOP_AI_SERVICE_EXTRACTION_REPLAY", "ZOOP_AI_SERVICE_EXTRACTION_TOPIC_REPLAY",
                               "ZOOP_AI_SERVICE_EXTRACTION_APPROVALS"}}
    config = load(only_s3)
    assert config.extraction is None and config.relation is not None
    # The S3 group keeps its own all-or-nothing rule: a shared variable alone (no S2 variable) is still an incomplete relation group.
    shared_only = ws.env()
    shared_only["ZOOP_AI_SERVICE_SOURCES"] = str(tmp_path / "sources.json")
    assert (refused(shared_only).field, refused(shared_only).reason) == ("ZOOP_AI_SERVICE_RELATION_COMMAND", "relation_group_incomplete")
    # A relation variable of its own with the S2 group complete is an incomplete S3 group, not silently ignored.
    assert refused({**env, "ZOOP_AI_RELATION_STATE_DIR": str(tmp_path / "relation")}).reason == "relation_group_incomplete"
    assert set(RELATION_VARS) & set(EXTRACTION_VARS) == {"ZOOP_AI_EXTRACTION_STATE_DIR", "ZOOP_AI_INGESTION_STATE_DIR", "ZOOP_AI_SERVICE_SOURCES"}
    assert set(EXTRACTION_OWN).isdisjoint(RELATION_VARS)


# ---- the approvals manifest is strict and fails closed -------------------------------------------------------------------------

def approvals_error(text: str, *, topic: bool = True, principals: tuple[str, ...] = ("alpha", "beta"), tmp: Path) -> str:
    path = tmp / "a.json"
    path.write_text(text)
    with pytest.raises(extraction_access.AccessError) as caught:
        extraction_access.load(path, principals, topic_available=topic)
    return caught.value.code


def mutated(**changes: Any) -> dict[str, Any]:
    return {**entry(), **changes}


def request_with(**changes: Any) -> dict[str, Any]:
    return entry({**REQUEST, **changes})


@pytest.mark.parametrize("text,reason", [
    ("{not json", "extraction_approvals_not_json"),
    ("[]", "extraction_approvals_shape"),
    (json.dumps({"schemaVersion": "wrong", "approvals": []}), "extraction_approvals_shape"),
    (document(extra=1), "extraction_approvals_shape"),
    ('{"schemaVersion":"%s","approvals":[],"approvals":[]}' % APPROVALS_SCHEMA, "extraction_approvals_not_json"),
    (document({"principal": "alpha"}), "extraction_approval_entry_shape"),
    (document({**entry(), "extra": 1}), "extraction_approval_entry_shape"),
    (document(mutated(jobId="bad id")), "extraction_approval_entry_invalid"),
    (document(mutated(approvedRequestDigest="short")), "extraction_approval_entry_invalid"),
    (document(mutated(producerReplayDigest="short")), "extraction_approval_entry_invalid"),
    (document(mutated(topicReplayDigest="short")), "extraction_approval_entry_invalid"),
    (document(entry(principal="nobody")), "extraction_approval_unknown_principal"),
    (document(mutated(request=[])), "extraction_approval_request_invalid"),
    (document(request_with(schemaVersion="other")), "extraction_approval_request_invalid"),
    (document(mutated(jobId="other-job")), "extraction_approval_request_invalid"),                       # request.jobId must equal the entry's jobId
    (document(request_with(provenance={"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "authored-test"})),
     "extraction_approval_request_invalid"),
    (document(mutated(approvedRequestDigest="0" * 64)), "extraction_approval_digest_mismatch"),             # the digest is verified, never trusted
    (document(mutated(topicReplayDigest=None)), "extraction_approval_topic_pin_mismatch"),
    (document(entry(PLAIN, topicReplayDigest=TOPIC)), "extraction_approval_topic_pin_mismatch"),
    (document(entry(), entry()), "extraction_approval_duplicate"),
])
def test_the_approvals_manifest_is_strict_and_fails_closed(tmp_path, text, reason):
    assert approvals_error(text, tmp=tmp_path) == reason


def test_an_approval_that_asks_for_a_topic_needs_the_topic_fixture_to_be_configured(tmp_path):
    assert approvals_error(document(entry()), topic=False, tmp=tmp_path) == "extraction_approval_topic_replay_unconfigured"


def test_a_missing_or_oversized_manifest_is_unreadable_and_a_valid_one_exposes_exact_pins(tmp_path):
    missing = tmp_path / "none.json"
    with pytest.raises(extraction_access.AccessError) as caught:
        extraction_access.load(missing, ["alpha"], topic_available=True)
    assert caught.value.code == "extraction_approvals_unreadable"
    path = tmp_path / "ok.json"
    path.write_text(document(entry(), entry(PLAIN), entry(PLAIN, "beta")))
    approvals = extraction_access.load(path, ["alpha", "beta"], topic_available=True)
    found = approvals.find("alpha", "s2-job")
    assert found is not None and found.pins == (digest(REQUEST), PRODUCER, TOPIC, None) and found.request == REQUEST
    assert approvals.find("beta", "s2-job") is None and approvals.find("alpha", "unknown") is None
    # The input digest the pipeline must report is computed from the approved bytes and the pinned producer digest.
    assert found.input_digest == digest({"request": REQUEST, "replayFixtureHash": PRODUCER})
    plain = approvals.find("alpha", "s2-plain")
    assert plain is not None and plain.topic_digest is None


LIVE_IDENTITY = "9" * 64
LIVE_REQUEST = {**REQUEST, "jobId": "s2-live", "provenance": {"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"}}


def live_entry(request: dict[str, Any] = LIVE_REQUEST, **overrides: Any) -> dict[str, Any]:
    return {**entry(request, producerReplayDigest=None, topicReplayDigest=None, liveRuntimeIdentity=LIVE_IDENTITY), **overrides}


def live_error(text: str, tmp: Path, *, live: bool = True) -> str:
    path = tmp / "live.json"
    path.write_text(text)
    with pytest.raises(extraction_access.AccessError) as caught:
        extraction_access.load(path, ["alpha"], topic_available=True, live_available=live)
    return caught.value.code


def test_a_live_approval_pins_the_runtime_identity_and_carries_no_fixture(tmp_path):
    path = tmp_path / "live.json"
    path.write_text(document(entry(), live_entry()))
    approvals = extraction_access.load(path, ["alpha"], topic_available=True, live_available=True)
    found = approvals.find("alpha", "s2-live")
    assert found is not None and found.live and found.pins == (digest(LIVE_REQUEST), None, None, LIVE_IDENTITY)
    # The input digest the pipeline must report binds the request and the approved runtime identity (no fixture exists).
    assert found.input_digest == digest({"request": LIVE_REQUEST, "liveBindingDigest": LIVE_IDENTITY})
    assert not approvals.find("alpha", "s2-job").live
    # Without the live group a live entry is refused at start, never silently kept as a request that could not run.
    assert live_error(document(live_entry()), tmp_path, live=False) == "extraction_approval_live_unconfigured"


@pytest.mark.parametrize("text,reason", [
    (document(live_entry(liveRuntimeIdentity=None)), "extraction_approval_live_pin_mismatch"),
    (document(live_entry(producerReplayDigest=PRODUCER)), "extraction_approval_live_pin_mismatch"),
    (document(live_entry(topicReplayDigest=TOPIC)), "extraction_approval_live_pin_mismatch"),
    (document(live_entry(liveRuntimeIdentity="short")), "extraction_approval_entry_invalid"),
    (document(entry(liveRuntimeIdentity=LIVE_IDENTITY)), "extraction_approval_request_invalid"),             # a replay request never carries a runtime pin
    (document(entry(LIVE_REQUEST)), "extraction_approval_live_pin_mismatch"),                               # a live request cannot name replay fixtures
    (document(live_entry({**LIVE_REQUEST, "provenance": {**LIVE_REQUEST["provenance"], "recordingKind": "authored-test"}})),
     "extraction_approval_request_invalid"),
])
def test_a_live_approval_is_strict(tmp_path, text, reason):
    assert live_error(text, tmp_path) == reason


# ---- authority: re-read on every call ---------------------------------------------------------------------------------------

def authority(tmp_path: Path, *, topic: bool = True) -> tuple[extraction_access.Authority, Path, Path, Path]:
    producer, topic_path, approvals = tmp_path / "p.json", tmp_path / "t.json", tmp_path / "a.json"
    producer.write_bytes(b"producer")
    topic_path.write_bytes(b"topic")
    pinned_producer, pinned_topic = hashlib.sha256(b"producer").hexdigest(), hashlib.sha256(b"topic").hexdigest()
    approvals.write_text(document(entry(producerReplayDigest=pinned_producer, topicReplayDigest=pinned_topic)))
    return extraction_access.Authority(approvals, ["alpha", "beta"], producer, topic_path if topic else None), producer, topic_path, approvals


def test_the_authority_names_exactly_what_moved(tmp_path):
    auth, producer, topic, approvals = authority(tmp_path)
    pins = (digest(REQUEST), hashlib.sha256(b"producer").hexdigest(), hashlib.sha256(b"topic").hexdigest(), None)
    assert auth.refusal("alpha", "s2-job", pins) is None
    assert auth.refusal("beta", "s2-job", pins) == "approval_revoked"                       # another principal's approval does not count
    assert auth.refusal("alpha", "s2-job", (digest(PLAIN), *pins[1:])) == "approval_revoked"  # the job was reserved under another digest
    assert auth.refusal("alpha", "s2-job", (pins[0], "f" * 64, pins[2], None)) == "approval_changed"  # the entry's own pins moved
    assert auth.refusal("alpha", "s2-job", (*pins[:3], LIVE_IDENTITY)) == "approval_changed"      # a replay approval can never be turned live
    topic.write_bytes(b"rotated")
    assert auth.refusal("alpha", "s2-job", pins) == "fixture_changed"
    topic.unlink()
    assert auth.refusal("alpha", "s2-job", pins) == "fixture_unavailable"
    topic.write_bytes(b"topic")
    producer.write_bytes(b"rotated")
    assert auth.refusal("alpha", "s2-job", pins) == "fixture_changed"
    producer.unlink()
    assert auth.refusal("alpha", "s2-job", pins) == "fixture_unavailable"
    producer.write_bytes(b"producer")
    assert auth.refusal("alpha", "s2-job", pins) is None
    approvals.write_text(document())
    assert auth.refusal("alpha", "s2-job", pins) == "approval_revoked"
    approvals.write_text("{not json")
    assert auth.refusal("alpha", "s2-job", pins) == "service_configuration_invalid"        # unreadable: fail closed, never open
    approvals.unlink()
    assert auth.refusal("alpha", "s2-job", pins) == "service_configuration_invalid"


def test_a_live_job_is_authorized_by_its_identity_and_never_by_a_fixture(tmp_path):
    approvals = tmp_path / "a.json"
    approvals.write_text(document(live_entry()))
    auth = extraction_access.Authority(approvals, ["alpha"], tmp_path / "no-such-producer.json", None, True)   # the fixture files do not even exist
    pins = (digest(LIVE_REQUEST), None, None, LIVE_IDENTITY)
    assert auth.refusal("alpha", "s2-live", pins) is None
    assert auth.refusal("alpha", "s2-live", (*pins[:3], "8" * 64)) == "approval_changed"       # the operator rotated the runtime identity
    assert auth.refusal("alpha", "s2-live", (*pins[:3], None)) == "approval_changed"
    approvals.write_text(document(live_entry(liveRuntimeIdentity="8" * 64)))
    assert auth.refusal("alpha", "s2-live", pins) == "approval_changed"
    approvals.write_text(document())
    assert auth.refusal("alpha", "s2-live", pins) == "approval_revoked"
    no_live = extraction_access.Authority(approvals, ["alpha"], tmp_path / "p", None, False)
    approvals.write_text(document(live_entry()))
    assert no_live.refusal("alpha", "s2-live", pins) == "service_configuration_invalid"           # the live group is off: fail closed


# ---- the service ledger freezes the identity and never rebinds ------------------------------------------------------------

PINS = Pins(digest(REQUEST), PRODUCER, TOPIC, digest({"request": REQUEST, "replayFixtureHash": PRODUCER}))
LIVE_PINS = Pins(digest(LIVE_REQUEST), None, None, digest({"request": LIVE_REQUEST, "liveBindingDigest": LIVE_IDENTITY}), LIVE_IDENTITY)


def test_a_reservation_is_frozen_and_only_a_release_removes_it(tmp_path):
    ledger = ExtractionLedger(tmp_path, tmp_path / "extraction")
    row = ledger.reserve("j1", "alpha", "rd", PINS)
    assert (row.state, row.pins, row.input_digest, row.submit_attempts) == ("reserved", PINS, PINS.input_digest, 0)
    assert ledger.reserve("j1", "beta", "other", Pins("1" * 64, "2" * 64, None, "3" * 64)).owner == "alpha"  # first claim wins; nothing is overwritten
    assert ledger.begin_attempt("j1") == 1
    database = sqlite3.connect(tmp_path / "extraction-jobs.sqlite3", isolation_level=None)
    for column, value in (("approved_digest", "x"), ("producer_digest", "x"), ("topic_digest", None), ("input_digest", "x"), ("owner", "beta"),
                          ("request_digest", "x"), ("live_binding", "x")):
        with pytest.raises(sqlite3.IntegrityError):
            database.execute(f"UPDATE extraction_jobs SET {column}=? WHERE job_id='j1'", (value,))   # no rotation can rebind the pinned identity
    assert ledger.release("j1", "beta", "rd") is False and ledger.release("j1", "alpha", "other") is False
    assert ledger.accept("j1", "alpha", 1000) == "accepted"
    accepted = ledger.job("j1")
    assert accepted is not None and accepted.state == "accepted" and accepted.accepted_at and accepted.pins == PINS
    assert ledger.release("j1", "alpha", "rd") is False                                  # an accepted job is never released
    with pytest.raises(sqlite3.IntegrityError):
        database.execute("DELETE FROM extraction_jobs WHERE job_id='j1'")
    with pytest.raises(sqlite3.IntegrityError):
        database.execute("UPDATE extraction_jobs SET approved_digest='x' WHERE job_id='j1'")
    database.close()
    ledger.close()


def test_dispatch_is_claimed_once_interrupted_never_requeued_and_recovered_explicitly(tmp_path):
    ledger = ExtractionLedger(tmp_path, tmp_path / "extraction")
    ledger.reserve("j1", "alpha", "rd", PINS)
    assert ledger.accept("j1", "alpha", 1000) == "accepted"
    dispatch = ledger.dispatch("j1")
    assert dispatch is not None and (dispatch.state, dispatch.dispatch_count) == ("pending", 0)
    claim = ledger.claim_next()
    assert claim is not None and (claim.job_id, claim.owner, claim.pins) == ("j1", "alpha", PINS) and ledger.claim_next() is None
    assert ledger.interrupt_in_flight() == 1
    idle = ledger.dispatch("j1")
    assert idle is not None and (idle.state, idle.last_outcome, idle.dispatch_count) == ("idle", "service_restarted", 1)
    assert ledger.claim_next() is None                                                    # never requeued by a restart
    assert ledger.enqueue("j1", 1000) == "enqueued" and ledger.enqueue("j1", 1000) == "coalesced"
    claim = ledger.claim_next()
    assert claim is not None
    assert ledger.finish("j1", Update("idle", "exited"))
    assert ledger.enqueue("j1", 0) == "full"                                              # the cap is checked in the same transaction
    ledger.close()


def test_a_live_reservation_pins_the_runtime_and_its_first_dispatch_is_never_explicit(tmp_path):
    ledger = ExtractionLedger(tmp_path, tmp_path / "extraction")
    row = ledger.reserve("live", "alpha", "rd", LIVE_PINS)
    assert row.pins == LIVE_PINS and row.pins.producer_digest is None and row.pins.live_binding == LIVE_IDENTITY
    assert ledger.reserve("live", "alpha", "rd", Pins(LIVE_PINS.approved_digest, None, None, LIVE_PINS.input_digest, "8" * 64)).pins == LIVE_PINS
    database = sqlite3.connect(tmp_path / "extraction-jobs.sqlite3", isolation_level=None)
    with pytest.raises(sqlite3.IntegrityError):
        database.execute("UPDATE extraction_jobs SET live_binding='8' WHERE job_id='live'")
    database.close()
    assert ledger.accept("live", "alpha", 1000) == "accepted"
    first = ledger.claim_next()
    assert first is not None and first.pins == LIVE_PINS and first.explicit is False   # the automatic dispatch runs under the pipeline's initial-only restriction
    assert ledger.finish("live", Update("idle", "transport_unknown"))
    assert ledger.enqueue("live", 1000) == "enqueued"
    again = ledger.claim_next()
    assert again is not None and again.explicit is True                                  # only an operator's recover runs without it
    ledger.close()


class _NoLiveExtraction:
    live_available = False

    def __init__(self):
        self.resumes: list[tuple] = []

    def resume(self, *args, **kwargs):
        self.resumes.append((args, kwargs))
        raise AssertionError("a live job must not start a child when the service has no live group")


class _OpenGate:
    def acquire(self, timeout: float) -> bool:
        return True

    def release(self) -> None:
        pass


def test_a_pending_live_extraction_dispatch_survives_a_restart_without_live_and_ends_idle_unavailable_with_no_child(tmp_path):
    from zoop_ai_service.extraction_dispatch import ExtractionDispatcher
    first = ExtractionLedger(tmp_path, tmp_path / "extraction")
    first.reserve("live", "alpha", "rd", LIVE_PINS)
    assert first.accept("live", "alpha", 1000) == "accepted"
    first.close()
    ledger = ExtractionLedger(tmp_path, tmp_path / "extraction")   # the restart
    process, logged = _NoLiveExtraction(), []
    dispatcher = ExtractionDispatcher(ledger, process, _OpenGate(), logged.append, lambda *args: pytest.fail("authority is not even asked"))
    assert dispatcher.step() is True
    row = ledger.dispatch("live")
    assert (row.state, row.last_outcome, row.last_runtime_code) == ("idle", "runtime_error", "live_unavailable") and process.resumes == []
    assert dispatcher.step() is False
    assert ledger.enqueue("live", 1000) == "enqueued"
    ledger.close()


def test_a_first_schema_ledger_gains_its_columns_in_place_and_reads_every_old_job_as_replay(tmp_path):
    ledger = ExtractionLedger(tmp_path, tmp_path / "extraction")
    ledger.reserve("old", "alpha", "rd", PINS)
    assert ledger.accept("old", "alpha", 1000) == "accepted"
    ledger.close()
    database = sqlite3.connect(tmp_path / "extraction-jobs.sqlite3")  # what a `-1` ledger looks like
    database.execute("DROP TRIGGER extraction_jobs_immutable")
    database.execute("ALTER TABLE extraction_jobs DROP COLUMN live_binding")
    database.execute("ALTER TABLE extraction_jobs DROP COLUMN authority_ref")
    database.execute("ALTER TABLE extraction_dispatch DROP COLUMN explicit")
    database.execute("UPDATE meta SET value=? WHERE key='schema'", (MIGRATES_FROM[0],))
    database.commit()
    database.close()
    migrated = ExtractionLedger(tmp_path, tmp_path / "extraction")
    old = migrated.job("old")
    assert old is not None and old.pins == PINS and old.pins.live_binding is None and old.state == "accepted" and old.authority_ref is None
    claim = migrated.claim_next()
    assert claim is not None and claim.explicit is False
    migrated.close()
    database = sqlite3.connect(tmp_path / "extraction-jobs.sqlite3")
    assert database.execute("SELECT value FROM meta WHERE key='schema'").fetchone() == (LEDGER_SCHEMA,)
    database.close()


def test_the_ledger_is_bound_to_its_extraction_root_and_schema(tmp_path):
    ledger = ExtractionLedger(tmp_path, tmp_path / "extraction")
    ledger.close()
    assert ExtractionLedger(tmp_path, tmp_path / "extraction")
    with pytest.raises(ConfigError) as caught:
        ExtractionLedger(tmp_path, tmp_path / "another-extraction")
    assert (caught.value.field, caught.value.reason) == ("ZOOP_AI_EXTRACTION_STATE_DIR", "extraction_ledger_binding_mismatch")
    database = sqlite3.connect(tmp_path / "extraction-jobs.sqlite3")
    database.execute("UPDATE meta SET value='zoop-ai-extraction-jobs-ledger-9' WHERE key='schema'")
    database.commit()
    database.close()
    with pytest.raises(ConfigError) as foreign:
        ExtractionLedger(tmp_path, tmp_path / "extraction")
    assert foreign.value.reason == "extraction_ledger_schema_mismatch" and LEDGER_SCHEMA == "zoop-ai-extraction-jobs-ledger-3"


# ---- dispatch policy: S2's busy codes, nothing else is retried ----------------------------------------------------------------

def test_only_the_pre_effect_busy_refusals_are_retried_and_the_s3_code_is_not_one_of_them():
    for code in sorted(BUSY_CODES):
        first = policy(Outcome("error", code=code, exit_code=2), None, busy_count=0, busy_codes=BUSY_CODES)
        assert (first.state, first.last_outcome, first.runtime_code, first.delay) == ("pending", "busy", code, 1.0)
    other = policy(Outcome("error", code="relation_busy", exit_code=2), None, busy_count=0, busy_codes=BUSY_CODES)
    assert (other.state, other.last_outcome) == ("idle", "runtime_error")
    for kind in ("timeout", "abnormal"):
        assert policy(Outcome(kind), None, busy_count=0, busy_codes=BUSY_CODES).last_outcome == "transport_unknown"
    # A job the pipeline recorded as stopped (a busy ingestion reader INSIDE an execution) is an ordinary result: idle, explicit recover only.
    stopped = policy(Outcome("result", result={}, exit_code=0), object(), busy_count=0, busy_codes=BUSY_CODES)
    assert (stopped.state, stopped.last_outcome) == ("idle", "exited")


def test_the_analysis_contract_refusal_is_a_server_configuration_fault_in_s2_and_s3_and_the_retired_poc_codes_are_not():
    from zoop_ai_service import extraction_jobs, relation_jobs
    for module in (extraction_jobs, relation_jobs):
        assert module.is_config_code("analysis_contract_changed") and module.is_config_code("ledger_version_unknown")
        assert not module.is_config_code("poc_contract_changed") and not module.is_config_code("pinned_poc_unavailable") and not module.is_config_code("job_input_conflict")
    assert extraction_jobs.is_config_code("replay_fixture_invalid")


# ---- the exit-code interpretation of the S2 pipeline -------------------------------------------------------------------------

def payload(state: str = "ready", **overrides: Any) -> dict[str, Any]:
    base = {"schemaVersion": "zoop-extraction-s2-2", "jobId": "s2-job", "inputDigest": "2" * 64, "state": state, "phase": "complete", "resumeMode": "none",
            "failure": None, "provenance": {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"},
            "stages": {"extract": {"state": "complete", "mentions": 1}, "compare": {"state": "complete"}, "topic": {"state": "pending"}},
            "usage": {"executionMode": "replay", "replayCalls": 2, "startedWithoutReceipt": 0, "providerCalls": 0, "paidModelCalls": 0, "creatorJobId": "s2-job"},
            "calls": [{"stage": "extract", "state": "received", "requestDigest": "e" * 64, "fixtureHash": PRODUCER, "responseDigest": "f" * 64, "verdict": None},
                      {"stage": "topic", "state": "received", "requestDigest": "e" * 64, "fixtureHash": TOPIC, "responseDigest": "f" * 64, "verdict": None}],
            "delivery": {"status": "current", "authority": "read+quote-display verified for every bound document at delivery"}}
    return {**base, **overrides}


def raw(value: Any) -> bytes:
    return json.dumps(value).encode()


def test_exit_two_with_an_error_object_is_an_error_and_with_a_withheld_result_is_a_result():
    error = interpret(2, raw({"schemaVersion": "zoop-extraction-s2-2", "error": {"code": "extraction_busy", "detail": {"x": 1}}}))
    assert (error.kind, error.code, error.exit_code, error.result) == ("error", "extraction_busy", 2, None)
    withheld = interpret(2, raw(payload(delivery={"status": "withheld", "code": "source_unauthorized"})))
    assert withheld.kind == "result" and withheld.result is not None and withheld.exit_code == 2
    assert interpret(0, raw(payload())).kind == "result"


@pytest.mark.parametrize("code,body", [
    (1, raw(payload())), (-9, b""), (0, b"not json"), (0, raw([1])), (2, raw({"schemaVersion": "other", "error": {"code": "x"}})),
    (0, raw({"schemaVersion": "zoop-extraction-s2-2", "error": {"code": "extraction_busy"}})),    # an error object must come with exit 2
    (2, raw({"schemaVersion": "zoop-extraction-s2-2", "error": {"code": "Not A Code"}})),
    (2, raw(payload())),                                                                          # exit 2 with a current delivery contradicts itself
    (0, raw(payload(delivery={"status": "withheld", "code": "x"}))),                               # exit 0 with a withheld delivery likewise
    (0, raw({k: v for k, v in payload().items() if k != "jobId"})),
    (0, raw(payload(schemaVersion="zoop-relation-s3"))),                                           # another pipeline's contract is never accepted
])
def test_unreadable_or_contradictory_output_is_abnormal(code, body):
    assert interpret(code, body).kind == "abnormal"


def test_the_two_doors_do_not_accept_each_others_schema():
    assert relation_interpret(0, raw(payload())).kind == "abnormal"
    relation_payload = {**payload(), "schemaVersion": "zoop-relation-s3"}
    assert interpret(0, raw(relation_payload)).kind == "abnormal" and relation_interpret(0, raw(relation_payload)).kind == "result"


# ---- the strict caller body --------------------------------------------------------------------------------------------------

SUBMIT = {"schemaVersion": "zoop-extraction-s2-2", "jobId": "s2-job", "approvedRequestDigest": digest(REQUEST)}


def test_the_caller_body_is_exactly_three_fields():
    assert ExtractionSubmit.model_validate(SUBMIT).wire() == SUBMIT
    for extra in ({"snapshot": {}}, {"catalogue": {}}, {"incoming": {}}, {"provenance": {}}, {"topic": None}, {"replay": "/x"}, {"path": "/x"},
                  {"fixtures": []}, {"request": REQUEST}, {"mode": "live"}, {"executionMode": "live"}):
        with pytest.raises(ValidationError):
            ExtractionSubmit.model_validate({**SUBMIT, **extra})
    for missing in SUBMIT:
        with pytest.raises(ValidationError):
            ExtractionSubmit.model_validate({k: v for k, v in SUBMIT.items() if k != missing})
    for bad in ({"schemaVersion": "zoop-ai-s1-1"}, {"jobId": "bad id"}, {"approvedRequestDigest": "short"}, {"approvedRequestDigest": "A" * 64},
                {"approvedRequestDigest": None}, {"jobId": 5}):
        with pytest.raises(ValidationError):
            ExtractionSubmit.model_validate({**SUBMIT, **bad})


# ---- projections --------------------------------------------------------------------------------------------------------------

def test_the_status_view_drops_every_pipeline_key_it_does_not_name_and_fails_closed_on_a_missing_one():
    view = ExtractionView.model_validate(payload())
    assert view.job_id == "s2-job" and view.usage.paid_model_calls == 0 and view.calls[0].fixture_hash == PRODUCER
    assert call_pin_problem(view, PINS) is None
    assert call_pin_problem(view, Pins(PINS.approved_digest, "9" * 64, TOPIC, PINS.input_digest)) == "fixture_changed"
    assert call_pin_problem(view, Pins(PINS.approved_digest, PRODUCER, "9" * 64, PINS.input_digest)) == "fixture_changed"
    assert call_pin_problem(view, Pins(PINS.approved_digest, PRODUCER, None, PINS.input_digest)) == "fixture_changed"  # a topic call with no pinned topic fixture
    for key in ("jobId", "inputDigest", "state", "usage", "calls", "delivery", "stages", "provenance"):
        with pytest.raises(ValidationError):
            ExtractionView.model_validate({k: v for k, v in payload().items() if k != key})
    with pytest.raises(ValidationError):
        ExtractionView.model_validate(payload(state="invented"))
    with pytest.raises(ValidationError):
        ExtractionView.model_validate(payload(provenance={"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "authored-test"}))
    status = extraction_doc.status()
    assert "calls" not in status and "binding" not in json.dumps(status) and "fixtureHash" not in json.dumps(status)


def test_the_content_projection_relays_meaningful_candidates_and_nothing_the_pipeline_adds():
    sample = extraction_doc.content()
    candidate = sample["eventCandidates"][0]
    assert candidate["approved"] is False and candidate["citations"][0]["quote"] and candidate["comparisons"][0]["effective"]["relation"] == "DIFFERENT"
    assert candidate["disposition"]["status"] == "new-event-candidate" and sample["topicCandidates"][0]["members"][1]["ref"] == "event-1"
    assert sample["counts"]["eventCandidates"] == {"total": 1, "candidate": 1, "rejected": 0}
    # A pipeline payload that carries extra stored identity is parsed with the extras dropped; a stray `approved: true` or a bad relation fails closed.
    noisy = copy.deepcopy(sample)
    noisy["binding"] = {"x": 1}
    noisy["eventCandidates"][0]["citations"][0].update(textArtifactId="art", rawLocatorIds=["l1"], sourceSegments=[{"x": 1}], rawVersion="r")
    noisy["eventCandidates"][0]["comparisons"][0].update(groupDigest="g", snapshotDigest="s", requestKey="k", original={"relation": "SAME", "reason": "r",
                                                         "evidence": [{"quote": "unmatched generator text"}]})
    noisy["eventCandidates"][0]["mention"]["evidence"] = [{"quote": "unmatched generator text", "start": 0, "end": 1}]
    parsed = ExtractionJobContent.model_validate(noisy).wire()
    text = json.dumps(parsed, ensure_ascii=False)
    for private in ("binding", "textArtifactId", "rawLocatorIds", "sourceSegments", "groupDigest", "snapshotDigest", "requestKey", "unmatched generator text"):
        assert private not in text, private
    for bad in (lambda c: c["eventCandidates"][0].update(approved=True), lambda c: c["topicCandidates"][0].update(approved=True),
                lambda c: c["eventCandidates"][0]["comparisons"][0]["effective"].update(relation="MAYBE"),
                lambda c: c["eventCandidates"][0].pop("citations"), lambda c: c["eventCandidates"][0]["citations"][0].pop("quote"),
                lambda c: c["counts"].pop("comparisons"), lambda c: c["eventCandidates"][0].update(state="approved")):
        broken = copy.deepcopy(sample)
        bad(broken)
        with pytest.raises(ValidationError):
            ExtractionJobContent.model_validate(broken)


def test_authored_examples_are_built_through_the_real_models_and_tell_the_documented_story():
    sample = extraction_doc.examples()
    assert sample["submit.202"]["queued"]["value"]["next"] == "wait" and sample["submit.202"]["queued"]["value"]["delivery"]["reason"] == "job_not_ready"
    assert sample["status.200"]["stopped"]["value"]["next"] == "recover" and sample["status.200"]["reconciling"]["value"]["next"] == "operator_reconcile"
    assert sample["status.200"]["interrupted"]["value"]["dispatch"]["lastOutcome"] == "service_restarted"
    assert sample["status.200"]["revoked"]["value"]["delivery"] == {"state": "withheld", "reason": "approval_revoked"}
    available, withheld = sample["result.200"]["available"]["value"], sample["result.200"]["withheld"]["value"]
    assert available["job"]["eventCandidates"] and withheld["job"] is None and withheld["delivery"]["reason"] == "approval_revoked"
    ExtractionResultEnvelope.model_validate(available)
    ExtractionJobStatus.model_validate(sample["cancel.200"]["cancelled"]["value"])
    envelope = sample["errors"]["409.reconcileRequired"]["value"]
    ExtractionErrorEnvelope.model_validate(envelope)
    assert set(envelope["error"]) == {"code", "retryable", "requestId", "runtimeCode", "field"} and "message" not in envelope["error"]
    assert SUBMIT["schemaVersion"] == extraction_doc.SUBMIT["schemaVersion"] and set(extraction_doc.SUBMIT) == set(SUBMIT)


# ---- the disabled family answers like the other disabled family ---------------------------------------------------------------

def test_a_service_without_the_group_answers_409_after_authentication_with_its_own_envelope(start):
    service = start(replay=document_replay())
    routes = [("POST", "/internal/v1/extraction-jobs"), ("GET", "/internal/v1/extraction-jobs/j1"), ("GET", "/internal/v1/extraction-jobs/j1/result"),
              ("POST", "/internal/v1/extraction-jobs/j1/cancel"), ("POST", "/internal/v1/extraction-jobs/j1/recover")]
    for method, path in routes:
        submit = method == "POST" and path.endswith("jobs")
        denied = service.request(method, path, as_=None)
        assert denied.status_code == 401 and denied.json()["schemaVersion"] == "zoop-ai-internal-extraction-1"
        assert service.request(method, path, as_="reader").status_code == 403 and service.request(method, path, as_="submitter").status_code == 403
        if submit:  # reading is not writing
            assert service.request(method, path, as_="viewer").status_code == 403
        disabled = service.request(method, path, as_="alpha", body=SUBMIT if submit else None, key="s2-job" if submit else None)
        assert disabled.status_code == 409 and disabled.json()["error"]["code"] == "execution_unavailable", (method, path)
        ExtractionErrorEnvelope.model_validate(disabled.json())
    s3 = service.request("GET", "/internal/v1/relation-jobs/j1", as_=None)
    assert s3.status_code == 401 and s3.json()["schemaVersion"] == "zoop-ai-internal-relation-1"
    s1 = service.request("GET", "/internal/v1/analysis-jobs/j1", as_=None)
    assert s1.status_code == 401 and s1.json()["schemaVersion"] == "zoop-ai-internal-1"
    assert service.request("GET", "/internal/v1/extraction-jobs/bad id!", as_="alpha").json()["schemaVersion"] == "zoop-ai-internal-extraction-1"


# ---- live: the opt-in group, the per-command child environment and the pinned runtime ---------------------------------------------------

LIVE_ENV = {"ZOOP_AI_SERVICE_PIPELINE_LIVE": "1", "ZOOP_AI_PIPELINE_LIVE_ENABLED": "1", "ZOOP_AI_PIPELINE_LIVE_MODEL": "gpt-6-luna",
            "ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT": "high", "TYPESAFE_VALIDATION_MODEL": "jev-1.14.0", "ZOOP_AI_PIPELINE_LIVE_MAX_USD": "10",
            "ZOOP_AI_PIPELINE_LIVE_MAX_CALLS": "20", "ZOOP_AI_API_KEY": "k-openai-secret", "TYPESAFE_API_KEY": "k-jev-secret"}


def live_env(ws: Workspace, root: Path, **overrides: str | None) -> dict[str, str]:
    return extraction_env(ws, root, **{"ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR": str(root / "budget"), **LIVE_ENV, **overrides})


def test_pipeline_live_is_off_unless_the_service_switch_and_the_pipeline_gate_are_both_on(tmp_path):
    ws = Workspace(tmp_path, replay=document_replay())
    assert load(live_env(ws, tmp_path)).pipeline_live is not None
    for off in ({"ZOOP_AI_SERVICE_PIPELINE_LIVE": None}, {"ZOOP_AI_SERVICE_PIPELINE_LIVE": "0"}):
        assert load(live_env(ws, tmp_path, **off)).pipeline_live is None            # the gate and keys alone forward nothing
    error = refused(live_env(ws, tmp_path, ZOOP_AI_PIPELINE_LIVE_ENABLED=None))
    assert (error.field, error.reason) == ("ZOOP_AI_PIPELINE_LIVE_ENABLED", "pipeline_live_gate_missing")
    for name in ("ZOOP_AI_PIPELINE_LIVE_MODEL", "ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT", "TYPESAFE_VALIDATION_MODEL", "ZOOP_AI_PIPELINE_LIVE_MAX_USD",
                 "ZOOP_AI_PIPELINE_LIVE_MAX_CALLS", "ZOOP_AI_API_KEY", "TYPESAFE_API_KEY", "ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR"):
        missing = refused(live_env(ws, tmp_path, **{name: None}) if name != "ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR"
                          else {k: v for k, v in live_env(ws, tmp_path).items() if k != name})
        assert (missing.field, missing.reason) == (name, "pipeline_live_incomplete")
    for name, value in (("ZOOP_AI_PIPELINE_LIVE_MAX_USD", "0"), ("ZOOP_AI_PIPELINE_LIVE_MAX_USD", "nan"), ("ZOOP_AI_PIPELINE_LIVE_MAX_CALLS", "0"),
                        ("ZOOP_AI_PIPELINE_LIVE_MAX_CALLS", "x"), ("ZOOP_AI_PIPELINE_LIVE_MODEL", " gpt")):
        assert refused(live_env(ws, tmp_path, **{name: value})).reason == "pipeline_live_invalid"
    assert refused(live_env(ws, tmp_path, ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR=str(tmp_path / "extraction" / "b"))).reason == "pipeline_live_budget_overlaps_state"
    # A switch with no S2 or S3 group at all is an error, not a silent no-op.
    bare = {k: v for k, v in Workspace(tmp_path, replay=document_replay()).env().items()} | {k: v for k, v in LIVE_ENV.items() if v is not None}
    bare["ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR"] = str(tmp_path / "budget")
    assert (refused(bare).field, refused(bare).reason) == ("ZOOP_AI_SERVICE_PIPELINE_LIVE", "pipeline_live_without_group")


def test_the_live_environment_is_split_by_what_each_command_needs_and_never_reaches_a_replay_command(tmp_path):
    from zoop_ai_service.extraction_runtime import ExtractionProcess
    ws = Workspace(tmp_path, replay=document_replay())
    config = load(live_env(ws, tmp_path, ZOOP_AI_BASE_URL="http://127.0.0.1:1"))
    assert config.extraction is not None and config.pipeline_live is not None
    process = ExtractionProcess(config)
    seen: list[tuple[list[str], dict[str, str] | None]] = []
    process._runner.execute = lambda argv, payload, deadline, stop=None, interpret=None, env=None: (seen.append((argv, env)), Outcome("unavailable"))[1]  # type: ignore[method-assign]
    process.submit({"x": 1}, live=True)
    process.resume("j", topic=True, live=True, initial_only=True)
    process.inspect("j")
    process.cancel("j")
    process.submit({"x": 1})
    process.resume("j", topic=True, initial_only=True)
    (live_submit, live_env_), (live_resume, send_env), (inspect, inspect_env), (cancel, cancel_env), (replay_submit, replay_submit_env), (replay_resume, replay_env) = seen
    assert "--replay" not in live_submit and "--replay" not in live_resume and "--topic-replay" not in live_resume and "--initial-only" in live_resume
    assert live_env_ is not None and live_env_["ZOOP_AI_PIPELINE_LIVE_ENABLED"] == "1" and live_env_["ZOOP_AI_BASE_URL"] == "http://127.0.0.1:1"
    assert not {"ZOOP_AI_API_KEY", "TYPESAFE_API_KEY", "ZOOP_AI_PIPELINE_LIVE_MAX_USD", "ZOOP_AI_PIPELINE_LIVE_MAX_CALLS"} & set(live_env_)  # registering needs no key or cap
    assert live_env_["ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR"] == str(tmp_path / "budget")   # the binding pins the directory's realpath
    assert send_env is not None and send_env["ZOOP_AI_API_KEY"] == "k-openai-secret" and send_env["TYPESAFE_API_KEY"] == "k-jev-secret"
    assert send_env["ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR"] == str(tmp_path / "budget") and send_env["ZOOP_AI_PIPELINE_LIVE_MAX_CALLS"] == "20"
    assert set(send_env) - set(config.extraction.child_env) == set(LIVE_ENV) - {"ZOOP_AI_SERVICE_PIPELINE_LIVE"} | {
        "ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR", "ZOOP_AI_BASE_URL"}   # exactly the documented names: nothing else of the service environment
    assert "ZOOP_AI_SERVICE_PIPELINE_LIVE" not in send_env and "HOME" not in send_env and "OPENAI_API_KEY" not in send_env
    assert (inspect_env, cancel_env, replay_submit_env, replay_env) == (None, None, None, None)   # the fixed replay-only environment
    assert "--replay" in replay_submit and "--replay" in replay_resume and "--topic-replay" in replay_resume and "--initial-only" in replay_resume
    assert "--initial-only" not in live_submit + replay_submit + inspect + cancel


def live_view(*, digest_: str | None = LIVE_IDENTITY, fixture: str | None = None, calls: bool = True) -> ExtractionView:
    value = payload(provenance={"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"},
                    binding={"adapter": {"version": "x"}, "live": {"runtime": {"secret": "no"}, "bindingDigest": digest_}} if digest_ else {"adapter": {}},
                    calls=[{"stage": "extract", "state": "received", "requestDigest": "e" * 64, "fixtureHash": fixture, "responseDigest": "f" * 64,
                            "verdict": None}] if calls else [],
                    usage={"executionMode": "live", "replayCalls": 0, "startedWithoutReceipt": 0, "providerCalls": 1, "paidModelCalls": 1, "receivedCalls": 1,
                           "unsentCalls": 0, "inputTokens": 10, "outputTokens": 20, "reasoningTokens": 5, "estimatedUsd": "0.000123", "chargedUsd": None})
    return ExtractionView.model_validate(value)


def test_a_live_job_is_checked_against_its_pinned_runtime_identity_not_against_fixtures():
    assert call_pin_problem(live_view(), LIVE_PINS) is None
    assert call_pin_problem(live_view(calls=False), LIVE_PINS) is None
    assert call_pin_problem(live_view(digest_="8" * 64), LIVE_PINS) == "live_binding_changed"      # frozen under another runtime than the approved one
    assert call_pin_problem(live_view(digest_=None), LIVE_PINS) == "live_binding_changed"          # no live binding reported at all
    assert call_pin_problem(live_view(fixture="f" * 64), LIVE_PINS) == "live_binding_changed"     # a live call answered by a fixture contradicts itself
    view = live_view()
    assert (view.usage.received_calls, view.usage.input_tokens, view.usage.estimated_usd, view.usage.charged_usd) == (1, 10, "0.000123", None)
    dumped = json.dumps(view.wire())
    assert "secret" not in dumped  # the runtime binding's other keys are dropped


def test_an_unknown_live_outcome_and_the_unsent_state_are_relayed_as_stopped_states_without_interpretation():
    unknown = payload("reconciling", resumeMode="reconcile_only", failure={"code": "live_response_unknown"},
                      calls=[{"stage": "extract", "state": "started", "requestDigest": "e" * 64, "fixtureHash": None, "responseDigest": None, "verdict": None}])
    view = ExtractionView.model_validate(unknown)
    assert (view.state, view.failure.code, view.calls[0].state) == ("reconciling", "live_response_unknown", "started")
    from zoop_ai_service.extraction_jobs import UNANSWERED
    assert "live_response_unknown" in UNANSWERED and "replay_response_unknown" in UNANSWERED
