"""S3 relation jobs, everything that needs no installed pipeline: all-or-nothing configuration, the upstream allowlist, the dispatch
policy table, the service ledger, the allowlisted projection, the exit-code interpretation and the disabled-feature routes.

The behavior that needs the real `zoop-ai-relation` (flow, isolation, crash recovery, cancel) lives in `ai/service/pipeline_tests`
and runs with `make service-pipeline-test`.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from support import Workspace, document_replay
from zoop_ai_service import relation_access
from zoop_ai_service.config import RELATION_VARS, ConfigError, load
from zoop_ai_service.openapi_doc import RELATION_REVIEW, RELATION_SUBMIT, relation_examples
from zoop_ai_service.relation_dispatch import MAX_BACKOFF, MAX_BUSY, busy_delay, policy
from zoop_ai_service.relation_ledger import LEDGER_SCHEMA, MIGRATES_FROM, OperationRow, RelationLedger, Update
from zoop_ai_service.relation_review import evidence, marker, next_operation_action, operation_status, settlement
from zoop_ai_service.relation_runtime import interpret
from zoop_ai_service.relation_wire import (SCHEMA, RelationChain, RelationErrorEnvelope, RelationJobContent, RelationJobStatus,
                                           RelationOperationStatus, RelationResultEnvelope, RelationReview, RelationSubmit, RelationView,
                                           next_action, with_source_identity)
from zoop_ai_service.runtime import Outcome

UPSTREAM_DIGEST = "d" * 64


def relation_env(ws: Workspace, root: Path, **overrides: str | None) -> dict[str, str]:
    """A complete relation group over throwaway files. The command is never run by `load`, so any executable file serves."""
    for name in ("extraction", "ingestion", "app"):
        (root / name).mkdir(exist_ok=True)
    for name in ("sources.json", "producer.json", "verifier.json"):
        (root / name).write_text("{}")
    (root / "upstreams.json").write_text(json.dumps({"schemaVersion": relation_access.SCHEMA, "upstreams": [
        {"principal": "alpha", "jobId": "s2-job", "inputDigest": UPSTREAM_DIGEST}]}))
    env = ws.env()
    env.update({
        "ZOOP_AI_SERVICE_RELATION_COMMAND": sys.executable, "ZOOP_AI_RELATION_STATE_DIR": str(root / "relation"),
        "ZOOP_AI_EXTRACTION_STATE_DIR": str(root / "extraction"), "ZOOP_AI_INGESTION_STATE_DIR": str(root / "ingestion"),
        "ZOOP_AI_SERVICE_SOURCES": str(root / "sources.json"), "ZOOP_AI_SERVICE_RELATION_REPLAY": str(root / "producer.json"),
        "ZOOP_AI_SERVICE_RELATION_VERIFIER_REPLAY": str(root / "verifier.json"),
        "ZOOP_AI_SERVICE_RELATION_UPSTREAMS": str(root / "upstreams.json"), "ZOOP_STATE_DIR": str(root / "app")})
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def refused(env: dict[str, str]) -> ConfigError:
    with pytest.raises(ConfigError) as caught:
        load(env)
    return caught.value


# ---- configuration: all or nothing -------------------------------------------------------------------------------------

def test_without_any_relation_variable_the_feature_is_off(tmp_path):
    assert load(Workspace(tmp_path, replay=document_replay()).env()).relation is None


def test_a_complete_group_loads_and_hands_the_child_only_ownership_roots(tmp_path):
    ws = Workspace(tmp_path, replay=document_replay())
    config = load(relation_env(ws, tmp_path))
    relation = config.relation
    assert relation is not None and relation.state_dir == tmp_path / "relation" and not relation.state_dir.exists()  # the pipeline creates it
    assert dict(relation.child_env) == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
                                        "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1", "ZOOP_STATE_DIR": str(tmp_path / "app"),
                                        "ZOOP_AI_WORKER_STATE_DIR": str(ws.worker)}


@pytest.mark.parametrize("name", RELATION_VARS)
def test_a_partial_group_refuses_to_start_and_names_the_missing_variable(tmp_path, name):
    error = refused(relation_env(Workspace(tmp_path, replay=document_replay()), tmp_path, **{name: None}))
    assert (error.field, error.reason) == (name, "relation_group_incomplete")


def test_every_member_of_the_group_is_validated_when_any_is_present(tmp_path):
    ws = Workspace(tmp_path, replay=document_replay())
    assert refused(relation_env(ws, tmp_path, ZOOP_STATE_DIR=None)).field == "ZOOP_STATE_DIR"
    assert refused(relation_env(ws, tmp_path, ZOOP_STATE_DIR="relative")).field == "ZOOP_STATE_DIR"
    assert refused(relation_env(ws, tmp_path, ZOOP_AI_SERVICE_RELATION_COMMAND=str(tmp_path / "sources.json"))).reason == "file_unusable"
    assert refused(relation_env(ws, tmp_path, ZOOP_AI_SERVICE_RELATION_COMMAND="relative/cli")).reason == "not_absolute_normalized"
    assert refused(relation_env(ws, tmp_path, ZOOP_AI_RELATION_STATE_DIR="relative")).reason == "not_absolute_normalized"
    assert refused(relation_env(ws, tmp_path, ZOOP_AI_RELATION_STATE_DIR=str(tmp_path / "no" / "relation"))).reason == "parent_missing"
    assert refused(relation_env(ws, tmp_path, ZOOP_AI_RELATION_STATE_DIR=str(tmp_path / "sources.json"))).reason == "not_a_directory"
    assert refused(relation_env(ws, tmp_path, ZOOP_AI_EXTRACTION_STATE_DIR=str(tmp_path / "absent"))).reason == "directory_missing"
    assert refused(relation_env(ws, tmp_path, ZOOP_AI_INGESTION_STATE_DIR=str(tmp_path / "absent"))).reason == "directory_missing"
    for name in ("ZOOP_AI_SERVICE_SOURCES", "ZOOP_AI_SERVICE_RELATION_REPLAY", "ZOOP_AI_SERVICE_RELATION_VERIFIER_REPLAY",
                 "ZOOP_AI_SERVICE_RELATION_UPSTREAMS"):
        error = refused(relation_env(ws, tmp_path, **{name: str(tmp_path / "absent.json")}))
        assert (error.field, error.reason) == (name, "file_unusable")
    link = tmp_path / "linked"
    link.symlink_to(tmp_path / "extraction", target_is_directory=True)
    assert refused(relation_env(ws, tmp_path, ZOOP_AI_EXTRACTION_STATE_DIR=str(link))).reason == "symlinked_component"


def test_the_six_state_roots_may_not_overlap_each_other(tmp_path):
    ws = Workspace(tmp_path, replay=document_replay())
    relation_env(ws, tmp_path)
    for name, value in (("ZOOP_AI_RELATION_STATE_DIR", str(ws.state / "relation")), ("ZOOP_AI_RELATION_STATE_DIR", str(tmp_path / "extraction" / "r")),
                        ("ZOOP_AI_RELATION_STATE_DIR", str(tmp_path / "ingestion")), ("ZOOP_AI_RELATION_STATE_DIR", str(ws.worker)),
                        ("ZOOP_AI_EXTRACTION_STATE_DIR", str(tmp_path / "ingestion" / "inner"))):
        if name == "ZOOP_AI_EXTRACTION_STATE_DIR":
            (tmp_path / "ingestion" / "inner").mkdir()
        error = refused(relation_env(ws, tmp_path, **{name: value}))
        assert error.reason in {"relation_roots_overlap", "overlaps_worker_state"}, (name, value, error.reason)
    assert refused(relation_env(ws, tmp_path, ZOOP_STATE_DIR=str(tmp_path / "extraction"))).reason == "relation_roots_overlap"


@pytest.mark.parametrize("content,reason", [
    ("{not json", "upstream_allowlist_not_json"),
    ("[]", "upstream_allowlist_shape"),
    (json.dumps({"schemaVersion": "wrong", "upstreams": []}), "upstream_allowlist_shape"),
    (json.dumps({"schemaVersion": relation_access.SCHEMA, "upstreams": [], "extra": 1}), "upstream_allowlist_shape"),
    (json.dumps({"schemaVersion": relation_access.SCHEMA, "upstreams": [{"principal": "alpha"}]}), "upstream_allowlist_entry_shape"),
    (json.dumps({"schemaVersion": relation_access.SCHEMA, "upstreams": [{"principal": "alpha", "jobId": "s2", "inputDigest": "short"}]}),
     "upstream_allowlist_entry_invalid"),
    (json.dumps({"schemaVersion": relation_access.SCHEMA, "upstreams": [{"principal": "alpha", "jobId": "bad id", "inputDigest": "d" * 64}]}),
     "upstream_allowlist_entry_invalid"),
    (json.dumps({"schemaVersion": relation_access.SCHEMA, "upstreams": [{"principal": "nobody", "jobId": "s2", "inputDigest": "d" * 64}]}),
     "upstream_allowlist_unknown_principal"),
    (json.dumps({"schemaVersion": relation_access.SCHEMA, "upstreams": [{"principal": "alpha", "jobId": "s2", "inputDigest": "d" * 64}] * 2}),
     "upstream_allowlist_duplicate"),
    ('{"schemaVersion":"%s","upstreams":[],"upstreams":[]}' % relation_access.SCHEMA, "upstream_allowlist_not_json"),
])
def test_the_upstream_allowlist_is_strict_and_fails_closed(tmp_path, content, reason):
    ws = Workspace(tmp_path, replay=document_replay())
    env = relation_env(ws, tmp_path)
    Path(env["ZOOP_AI_SERVICE_RELATION_UPSTREAMS"]).write_text(content)
    error = refused(env)
    assert (error.field, error.reason) == ("ZOOP_AI_SERVICE_RELATION_UPSTREAMS", reason)


def test_the_allowlist_binds_a_principal_to_exact_pairs_and_is_read_fresh(tmp_path):
    path = tmp_path / "upstreams.json"

    def write(entries: list[dict[str, str]]) -> None:
        path.write_text(json.dumps({"schemaVersion": relation_access.SCHEMA, "upstreams": entries}))

    write([{"principal": "alpha", "jobId": "s2", "inputDigest": "a" * 64}])
    access = relation_access.load(path, ["alpha", "beta"])
    assert access.allows("alpha", "s2", "a" * 64)
    assert not access.allows("beta", "s2", "a" * 64) and not access.allows("alpha", "s2", "b" * 64) and not access.allows("alpha", "s3", "a" * 64)
    write([])
    assert not relation_access.load(path, ["alpha"]).allows("alpha", "s2", "a" * 64)  # removing an entry takes effect on the next read
    path.unlink()
    with pytest.raises(relation_access.AccessError) as caught:
        relation_access.load(path, ["alpha"])
    assert caught.value.code == "upstream_allowlist_unreadable"


# ---- dispatch policy ----------------------------------------------------------------------------------------------------

def payload(state: str = "ready", **extra: Any) -> dict[str, Any]:
    """The shape the pipeline prints, including keys the projection must drop."""
    return {"schemaVersion": "zoop-relation-s3", "jobId": "job", "inputDigest": "i" * 64, "state": state, "phase": "complete",
            "resumeMode": "none", "failure": None, "provenance": {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"},
            "binding": {"schema": "x", "upstream": {"jobId": "s2", "inputDigest": UPSTREAM_DIGEST, "digest": "u" * 64}, "documents": {"secret": "raw-hash"}},
            "stages": {"relation": {"state": "pending"}}, "usage": {"executionMode": "replay", "replayCalls": 1, "startedWithoutReceipt": 0,
                                                                   "providerCalls": 0, "modelCalls": 0, "creatorJobId": "job"},
            "calls": [{"stage": "relation", "state": "received", "requestDigest": "r" * 64, "fixtureHash": "f" * 64, "responseDigest": "p" * 64, "verdict": None}],
            "delivery": {"status": "current", "authority": "prose"}, **extra}


def finished(state: str = "ready", **extra: Any) -> tuple[Outcome, RelationView]:
    raw = payload(state, **extra)
    return Outcome("result", result=raw, exit_code=0), RelationView.model_validate(raw)


@pytest.mark.parametrize("state", ["queued", "running", "stopped", "ready", "reconciling", "cancelled"])
def test_any_result_ends_the_dispatch_idle_and_never_continues_it(state):
    outcome, parsed = finished(state)
    update = policy(outcome, parsed, busy_count=0)
    assert (update.state, update.last_outcome, update.delay) == ("idle", "exited", 0.0)


@pytest.mark.parametrize("kind", ["timeout", "abnormal"])
def test_an_ambiguous_child_is_never_run_again_automatically(kind):
    update = policy(Outcome(kind, exit_code=None), None, busy_count=0)
    assert (update.state, update.last_outcome) == ("idle", "transport_unknown")


def test_an_unstartable_child_is_idle_and_unavailable():
    assert policy(Outcome("unavailable"), None, busy_count=0).last_outcome == "runtime_unavailable"


def test_only_the_pre_effect_busy_refusal_is_retried_with_a_bounded_backoff():
    first = policy(Outcome("error", code="relation_busy", exit_code=2), None, busy_count=0)
    assert (first.state, first.last_outcome, first.runtime_code, first.delay, first.busy_count) == ("pending", "busy", "relation_busy", 1.0, 1)
    last = policy(Outcome("error", code="relation_busy", exit_code=2), None, busy_count=MAX_BUSY - 1)
    assert (last.state, last.last_outcome, last.runtime_code) == ("idle", "busy", "relation_busy")
    assert busy_delay(30) == MAX_BACKOFF
    for code in ("extraction_busy", "ingestion_busy", "job_not_found", "persistence_failed", "input_or_configuration_invalid"):
        refusal = policy(Outcome("error", code=code, exit_code=2), None, busy_count=0)
        assert (refusal.state, refusal.last_outcome, refusal.runtime_code) == ("idle", "runtime_error", code)


@pytest.mark.parametrize("state,dispatch,expected", [
    ("queued", "pending", "wait"), ("running", "in_flight", "wait"), ("ready", "pending", "wait"),
    ("ready", "idle", "fetch_result"), ("reconciling", "idle", "operator_reconcile"), ("cancelled", "idle", "none"),
    ("stopped", "idle", "recover"), ("queued", "idle", "recover"), ("running", "idle", "recover"),
])
def test_next_is_a_pure_ordered_rule(state, dispatch, expected):
    assert next_action(state, dispatch) == expected


# ---- the exit-code interpretation of the pipeline ---------------------------------------------------------------------------

def raw(value: Any) -> bytes:
    return json.dumps(value).encode()


def test_exit_two_with_an_error_object_is_an_error_and_with_a_withheld_result_is_a_result():
    error = interpret(2, raw({"schemaVersion": "zoop-relation-s3", "error": {"code": "relation_busy", "detail": {"x": 1}}}))
    assert (error.kind, error.code, error.exit_code, error.result) == ("error", "relation_busy", 2, None)
    withheld = interpret(2, raw(payload("ready", delivery={"status": "withheld", "code": "source_unauthorized"})))
    assert withheld.kind == "result" and withheld.result is not None and withheld.exit_code == 2
    current = interpret(0, raw(payload()))
    assert current.kind == "result" and current.exit_code == 0


@pytest.mark.parametrize("code,body", [
    (1, raw(payload())), (-9, b""), (0, b"not json"), (0, raw([1])), (2, raw({"schemaVersion": "other", "error": {"code": "x"}})),
    (0, raw({"schemaVersion": "zoop-relation-s3", "error": {"code": "relation_busy"}})),       # an error object must come with exit 2
    (2, raw({"schemaVersion": "zoop-relation-s3", "error": {"code": "Not A Code"}})),
    (2, raw({"schemaVersion": "zoop-relation-s3", "error": "text"})),
    (2, raw(payload())),                                                                         # exit 2 with a current delivery contradicts itself
    (0, raw(payload(delivery={"status": "withheld", "code": "x"}))),                              # exit 0 with a withheld delivery likewise
    (0, raw({k: v for k, v in payload().items() if k != "jobId"})),
])
def test_unreadable_or_contradictory_output_is_abnormal(code, body):
    assert interpret(code, body).kind == "abnormal"


# ---- the allowlisted projection --------------------------------------------------------------------------------------------

def test_the_status_view_drops_everything_it_does_not_name():
    view = RelationView.model_validate(payload())
    dumped = json.dumps(view.wire())
    for private in ("raw-hash", "requestDigest", "fixtureHash", "responseDigest", "creatorJobId", "documents", "authority", "prose"):
        assert private not in dumped
    assert view.calls[0].model_dump() == {"stage": "relation", "state": "received", "verdict": None}


def test_a_failure_detail_is_never_relayed_and_free_text_codes_are_redacted():
    view = RelationView.model_validate(payload("stopped", failure={"code": "producer_replay_missing", "detail": {"requestDigest": "r" * 64}}))
    assert view.failure is not None and view.failure.wire() == {"code": "producer_replay_missing"}
    odd = RelationView.model_validate(payload("stopped", failure={"code": "free text with spaces and a /path"}))
    assert odd.failure is not None and odd.failure.code == "redacted"


@pytest.mark.parametrize("mutate", [
    lambda v: v.update(state="unknown-state"), lambda v: v.pop("binding"), lambda v: v.update(schemaVersion="zoop-ai-s1-1"),
    lambda v: v["usage"].update(replayCalls="1"), lambda v: v["provenance"].update(executionMode="live"),
    lambda v: v["delivery"].update(status="maybe"), lambda v: v.pop("calls"),
])
def test_a_missing_or_mistyped_required_field_fails_closed(mutate):
    value = payload()
    mutate(value)
    with pytest.raises(ValidationError):
        RelationView.model_validate(value)


def relation_item(**overrides: Any) -> dict[str, Any]:
    citation = {"evidenceId": "ev-1", "documentId": "doc-1", "documentVersion": "3" * 64, "rawVersion": "4" * 64, "textArtifactId": "text-1",
                "offsetUnit": "unicode_code_point", "start": 0, "end": 5, "quote": "SOURCE-QUOTE", "inputKind": "body", "rawLocatorIds": ["loc"],
                "sourceSegments": [{"locatorId": "loc"}]}
    item = {"relationCandidateId": "rc-" + "1" * 64, "sourceVersion": "i" * 64, "sourceRevision": "3", "relationKey": "k" * 64, "type": "SUPPLIES",
            "direction": "directed",
            "subject": {"kind": "company", "ref": "A"}, "object": {"kind": "company", "ref": "B"}, "reordered": False, "connection": "direct",
            "businessScope": None, "productScope": None,
            "validity": {"from": None, "until": None, "fromStatus": "unknown", "untilStatus": "unknown", "citations": []},
            "countries": [], "context": {"market": "unknown", "check": "unknown", "knownCountries": []}, "citations": [citation], "path": [],
            "generatorReasons": ["why"], "proposalCount": 1, "precheck": {"state": "pending", "reasons": []}, "approved": False,
            "facts": {"private": "claim table"}, "quotes": [{"text": "SOURCE-QUOTE"}], "claims": [{"claimId": "subject"}],
            "eligibility": {"status": "hold", "reasons": [{"code": "claim_insufficient", "at": "type"}], "revision": 3, "reviewPending": True},
            "history": [
                {"seq": 1, "kind": "verdict", "createdAt": "2026-10-13T00:00:00+00:00", "attempt": {"kind": "initial", "seq": 0}, "eligibility": "hold",
                 "reasons": [{"code": "claim_insufficient"}], "claims": [], "verifier": "called", "requestDigest": "q" * 64},
                {"seq": 2, "kind": "review", "createdAt": "2026-10-13T00:01:00+00:00", "decision": "allow", "reviewer": "ops@example.invalid",
                 "note": "free text from an operator", "expectedRevision": 1, "effect": "revalidation-requested"}],
            "impact": {"status": "not-applicable", "labelNote": "note", "candidates": []}, **overrides}
    return item


def content(*items: dict[str, Any]) -> dict[str, Any]:
    return {**payload(), "counts": {"relations": len(items), "eligibility": {"pending": 0, "eligible": 0, "hold": len(items), "reject": 0},
                                    "impactLabels": {"positive": 0, "negative": 0, "mixed": 0, "undetermined": 0}, "impactCandidates": 0},
            "relations": list(items)}


def test_the_content_projection_keeps_citations_and_drops_hashes_claims_and_free_text_history():
    job = RelationJobContent.model_validate(content(relation_item()))
    dumped = json.dumps(job.wire(), ensure_ascii=False)
    assert "SOURCE-QUOTE" in dumped  # delivered only behind every gate, by design
    for private in ("evidenceId", "rawVersion", "textArtifactId", "rawLocatorIds", "sourceSegments", "relationKey", "claim table", "ops@example.invalid",
                    "free text from an operator", "requestDigest", "attempt", "facts", "claims", "quotes"):
        assert private not in dumped, private
    relation = job.wire()["relations"][0]
    assert relation["approved"] is False and relation["history"][1] == {"seq": 2, "kind": "review", "createdAt": "2026-10-13T00:01:00+00:00",
                                                                        "eligibility": None, "reasons": [], "decision": "allow", "effect": "revalidation-requested"}
    assert (relation["sourceVersion"], relation["sourceRevision"]) == ("i" * 64, "3") and relation["eligibility"]["revision"] == 3


def test_an_invalid_citation_never_relays_the_generator_text():
    bad = {"documentId": "doc-1", "documentVersion": "3" * 64, "start": 1, "end": 9, "quote": "FABRICATED-QUOTE", "error": "quote_mismatch"}
    item = relation_item(citations=[bad])
    dumped = json.dumps(RelationJobContent.model_validate(content(item)).wire(), ensure_ascii=False)
    assert "FABRICATED-QUOTE" not in dumped and "quote_mismatch" in dumped


@pytest.mark.parametrize("mutate", [
    lambda item: item.update(approved=True), lambda item: item.pop("eligibility"), lambda item: item.update(relationCandidateId="not-an-id"),
    lambda item: item["citations"][0].pop("quote"), lambda item: item["eligibility"].update(status="published"),
    lambda item: item["subject"].update(kind="person"), lambda item: item.pop("sourceVersion"), lambda item: item.pop("sourceRevision"),
    lambda item: item.update(sourceRevision="2"),      # disagrees with eligibility.revision (3): one number, never two
    lambda item: item.update(sourceRevision="03"), lambda item: item.update(sourceRevision=3),
])
def test_a_content_payload_that_does_not_parse_strictly_is_refused(mutate):
    item = relation_item()
    mutate(item)
    with pytest.raises(ValidationError):
        RelationJobContent.model_validate(content(item))


def test_the_submit_model_is_exact_and_names_no_path_fixture_or_live_mode():
    good = RelationSubmit.model_validate(RELATION_SUBMIT)
    assert good.wire() == RELATION_SUBMIT
    for mutate in (lambda v: v.update(replay="/etc/passwd"), lambda v: v["provenance"].update(executionMode="live"),
                   lambda v: v["upstream"].update(inputDigest="x"), lambda v: v.update(jobId="bad id"), lambda v: v.update(jobId=5),
                   lambda v: v["upstream"].pop("jobId"), lambda v: v.update(schemaVersion="zoop-ai-s1-1"),
                   lambda v: v["provenance"].update(recordingKind="provider")):
        value = json.loads(json.dumps(RELATION_SUBMIT))
        mutate(value)
        with pytest.raises(ValidationError):
            RelationSubmit.model_validate(value)


# ---- the service ledger ------------------------------------------------------------------------------------------------------

@pytest.fixture
def ledger(tmp_path: Path):
    directory = tmp_path / "service"
    directory.mkdir()
    value = RelationLedger(directory, tmp_path / "relation")
    yield value
    value.close()


def reserve(ledger: RelationLedger, job_id: str = "job-1", owner: str = "alpha", digest: str = "a" * 64):
    return ledger.reserve(job_id, owner, digest, "s2", UPSTREAM_DIGEST)


def test_reserve_is_idempotent_and_never_changes_the_first_owner(ledger):
    first = reserve(ledger)
    again = ledger.reserve("job-1", "beta", "b" * 64, "other", "e" * 64)
    assert again == first and again.owner == "alpha" and again.state == "reserved" and again.submit_attempts == 0
    assert ledger.begin_attempt("job-1") == 1 and ledger.begin_attempt("job-1") == 2


def test_accept_records_the_digest_and_creates_exactly_one_pending_dispatch(ledger):
    reserve(ledger)
    assert ledger.accept("job-1", "alpha", "i" * 64, 10) == "accepted"
    row, dispatch = ledger.job("job-1"), ledger.dispatch("job-1")
    assert row.state == "accepted" and row.input_digest == "i" * 64 and row.accepted_at is not None
    assert (dispatch.state, dispatch.dispatch_count, dispatch.last_outcome) == ("pending", 0, None)
    assert ledger.accept("job-1", "alpha", "i" * 64, 10) == "conflict"  # nothing to accept twice
    assert ledger.accept("job-1", "beta", "i" * 64, 10) == "conflict"


def test_the_cap_counts_pending_and_in_flight_and_keeps_the_reservation(ledger):
    for index in range(2):
        reserve(ledger, f"job-{index}")
    assert ledger.accept("job-0", "alpha", "i" * 64, 1) == "accepted"
    assert ledger.accept("job-1", "alpha", "j" * 64, 1) == "full" and ledger.job("job-1").state == "reserved"
    claim = ledger.claim_next()
    assert claim is not None and ledger.accept("job-1", "alpha", "j" * 64, 1) == "full"  # in flight still holds its slot
    ledger.finish("job-0", Update("idle", "exited"))
    assert ledger.accept("job-1", "alpha", "j" * 64, 1) == "accepted"


def test_an_accepted_job_cannot_be_released_edited_or_deleted_and_a_reservation_can(ledger, tmp_path):
    reserve(ledger, "held")
    reserve(ledger, "kept")
    ledger.accept("kept", "alpha", "i" * 64, 10)
    assert ledger.release("held", "beta", "a" * 64) is False and ledger.release("held", "alpha", "x" * 64) is False
    assert ledger.release("held", "alpha", "a" * 64) is True and ledger.job("held") is None
    assert ledger.release("kept", "alpha", "a" * 64) is False
    raw = sqlite3.connect(tmp_path / "service" / "relation-jobs.sqlite3")
    with pytest.raises(sqlite3.DatabaseError):
        raw.execute("UPDATE relation_jobs SET owner='beta' WHERE job_id='kept'")
    with pytest.raises(sqlite3.DatabaseError):
        raw.execute("DELETE FROM relation_jobs WHERE job_id='kept'")
    with pytest.raises(sqlite3.DatabaseError):
        raw.execute("DELETE FROM relation_dispatch WHERE job_id='kept'")
    raw.close()


def test_the_initial_dispatch_is_claimed_once_and_a_busy_retry_waits_for_its_time(ledger):
    clock = [1000.0]
    ledger._clock = lambda: clock[0]
    reserve(ledger)
    ledger.accept("job-1", "alpha", "i" * 64, 10)
    claim = ledger.claim_next()
    assert claim is not None and (claim.job_id, claim.input_digest, claim.busy_count) == ("job-1", "i" * 64, 0)
    assert ledger.claim_next() is None and ledger.dispatch("job-1").state == "in_flight" and ledger.dispatch("job-1").dispatch_count == 1
    assert ledger.finish("job-1", Update("pending", "busy", "relation_busy", 2.0, 1))
    assert ledger.claim_next() is None
    clock[0] += 2.5
    again = ledger.claim_next()
    assert again is not None and again.busy_count == 1 and ledger.dispatch("job-1").dispatch_count == 2
    assert ledger.finish("job-1", Update("idle", "exited")) and not ledger.finish("job-1", Update("idle", "exited"))
    assert ledger.claim_next() is None


def test_a_row_a_dead_process_left_in_flight_ends_idle_and_is_never_made_pending(ledger):
    for name in ("running", "waiting"):
        reserve(ledger, name)
        ledger.accept(name, "alpha", "i" * 64, 10)
    assert ledger.claim_next().job_id == "running"
    assert ledger.interrupt_in_flight() == 1
    running, waiting = ledger.dispatch("running"), ledger.dispatch("waiting")
    assert (running.state, running.last_outcome, running.dispatch_count) == ("idle", "service_restarted", 1)
    assert (waiting.state, waiting.dispatch_count) == ("pending", 0)  # the original intent that never started still runs, once
    assert ledger.claim_next().job_id == "waiting"


def test_explicit_recovery_enqueues_an_idle_row_once_and_coalesces_the_rest(ledger):
    reserve(ledger)
    ledger.accept("job-1", "alpha", "i" * 64, 10)
    assert ledger.enqueue("job-1", 10) == "coalesced"  # pending already
    ledger.claim_next()
    assert ledger.enqueue("job-1", 10) == "coalesced"  # in flight
    ledger.finish("job-1", Update("idle", "transport_unknown"))
    assert ledger.enqueue("job-1", 0) == "full" and ledger.dispatch("job-1").state == "idle"
    assert ledger.enqueue("job-1", 10) == "enqueued" and ledger.dispatch("job-1").state == "pending"
    assert ledger.enqueue("job-1", 10) == "coalesced"
    ledger.cancel_pending("job-1")
    cancelled = ledger.dispatch("job-1")
    assert (cancelled.state, cancelled.last_outcome) == ("idle", "cancelled")


def test_the_ledger_is_bound_to_one_relation_state_directory(tmp_path):
    directory = tmp_path / "service"
    directory.mkdir()
    RelationLedger(directory, tmp_path / "relation").close()
    RelationLedger(directory, tmp_path / "relation").close()
    with pytest.raises(ConfigError) as caught:
        RelationLedger(directory, tmp_path / "other")
    assert (caught.value.field, caught.value.reason) == ("ZOOP_AI_RELATION_STATE_DIR", "relation_ledger_binding_mismatch")


# ---- review operations: the ledger ---------------------------------------------------------------------------------------------

RC = "rc-" + "1" * 64
JOB_DIGEST = "i" * 64


def settled_job(ledger: RelationLedger, job_id: str = "job-1") -> None:
    """An accepted job whose initial dispatch has already ended: the state a review is made against."""
    reserve(ledger, job_id)
    assert ledger.accept(job_id, "alpha", JOB_DIGEST, 100) == "accepted"
    claim = ledger.claim_next()
    assert claim is not None and claim.job_id == job_id and claim.operation_id is None
    assert ledger.finish(job_id, Update("idle", "exited"))


def reserve_operation(ledger: RelationLedger, key: str = "op-1", *, decision: str = "allow", job_id: str = "job-1", revision: int = 1,
                      digest: str = "a" * 64, owner: str = "alpha", limit: int = 100):
    return ledger.reserve_operation(key, owner, job_id, RC, decision, JOB_DIGEST, revision, digest, limit)


def test_an_operation_reservation_is_durable_idempotent_and_keeps_its_identity(ledger, tmp_path):
    settled_job(ledger)
    first = reserve_operation(ledger)
    assert first is not None and (first.review_state, first.review_attempts, first.reval_state, first.settled) == ("reserved", 0, None, None)
    assert (first.owner, first.job_id, first.relation_candidate_id, first.decision, first.expected_source_version,
            first.expected_source_revision) == ("alpha", "job-1", RC, "allow", JOB_DIGEST, 1)
    again = ledger.reserve_operation("op-1", "beta", "other", "rc-" + "2" * 64, "reject", "j" * 64, 5, "b" * 64, 100)
    assert again == first  # an existing key is returned untouched, whoever asks
    assert ledger.begin_review_attempt("op-1") == 1 and ledger.begin_review_attempt("op-1") == 2  # counted before the pipeline is asked
    raw = sqlite3.connect(tmp_path / "service" / "relation-jobs.sqlite3")
    for column, value in (("owner", "'beta'"), ("decision", "'reject'"), ("expected_source_revision", "5"), ("expected_source_version", "'x'"),
                          ("request_digest", "'x'"), ("relation_candidate_id", "'x'"), ("job_id", "'other'")):
        with pytest.raises(sqlite3.DatabaseError):
            raw.execute(f"UPDATE relation_operations SET {column}={value} WHERE operation_id='op-1'")
    raw.close()


def test_confirming_an_allow_records_the_event_and_queues_exactly_one_revalidation(ledger):
    settled_job(ledger)
    reserve_operation(ledger)
    assert ledger.apply_operation("op-1", "2026-10-13T00:01:00Z") is True and ledger.apply_operation("op-1", "x") is False
    row = ledger.operation("op-1")
    assert (row.review_state, row.applied_event_at, row.reval_state, row.reval_count) == ("applied", "2026-10-13T00:01:00Z", "pending", 0) and row.applied_at
    assert ledger.revalidating("job-1") is True
    claim = ledger.claim_next()
    assert claim is not None and claim.operation_id == "op-1" and (claim.job_id, claim.input_digest, claim.relation_candidate_id) == ("job-1", JOB_DIGEST, RC)
    assert (claim.review_revision, claim.expected_revision, claim.owner, claim.upstream_job_id, claim.upstream_input_digest) == (
        1, 2, "alpha", "s2", UPSTREAM_DIGEST)  # the revalidate command must see the revision the review left
    assert ledger.claim_next() is None and ledger.operation("op-1").reval_state == "in_flight" and ledger.operation("op-1").reval_count == 1
    assert ledger.finish_operation("op-1", Update("idle", "exited", settled="verified", settled_eligibility="eligible"))
    done = ledger.operation("op-1")
    assert (done.reval_state, done.settled, done.settled_eligibility, done.last_outcome) == ("idle", "verified", "eligible", "exited") and done.settled_at
    assert not ledger.finish_operation("op-1", Update("idle", "exited")) and ledger.revalidating("job-1") is False
    assert ledger.settle_operation("op-1", "superseded", None) is False  # write-once
    assert ledger.enqueue_operation("op-1", 10) == "coalesced"  # a settled operation has nothing left to run


def test_a_confirmed_reject_has_no_revalidation_at_all(ledger):
    settled_job(ledger)
    reserve_operation(ledger, decision="reject")
    assert ledger.apply_operation("op-1", "2026-10-13T00:01:00Z")
    row = ledger.operation("op-1")
    assert (row.review_state, row.reval_state, row.settled) == ("applied", None, None)
    assert ledger.claim_next() is None and ledger.revalidating("job-1") is False and ledger.enqueue_operation("op-1", 10) == "coalesced"


def test_a_reservation_can_be_released_and_a_confirmed_operation_cannot(ledger, tmp_path):
    settled_job(ledger)
    reserve_operation(ledger, "held")
    reserve_operation(ledger, "kept")
    ledger.apply_operation("kept", "t")
    assert ledger.release_operation("held", "beta", "a" * 64) is False and ledger.release_operation("held", "alpha", "x" * 64) is False
    assert ledger.release_operation("held", "alpha", "a" * 64) is True and ledger.operation("held") is None
    assert ledger.release_operation("kept", "alpha", "a" * 64) is False
    raw = sqlite3.connect(tmp_path / "service" / "relation-jobs.sqlite3")
    for statement in ("DELETE FROM relation_operations WHERE operation_id='kept'",
                      "UPDATE relation_operations SET applied_event_at='x' WHERE operation_id='kept'",
                      "UPDATE relation_operations SET review_state='reserved' WHERE operation_id='kept'"):
        with pytest.raises(sqlite3.DatabaseError):
            raw.execute(statement)
    raw.close()


def test_the_cap_counts_waiting_dispatches_of_both_kinds_and_a_reserved_allow(ledger):
    settled_job(ledger)
    assert reserve_operation(ledger, "a", limit=1) is not None and ledger.active_count() == 1  # a reserved allow will wait to run
    assert reserve_operation(ledger, "b", limit=1) is None  # full: refused before anything is bound
    assert ledger.operation("b") is None and reserve_operation(ledger, "r", decision="reject", limit=1) is not None  # a reject never waits
    assert ledger.apply_operation("a", "t") and ledger.active_count() == 1  # reserved -> pending: the same single slot
    assert reserve_operation(ledger, "c", limit=1) is None
    claim = ledger.claim_next()
    assert claim is not None and claim.operation_id == "a" and ledger.active_count() == 1  # in flight still holds it
    assert ledger.finish_operation("a", Update("idle", "exited")) and ledger.active_count() == 0
    reserve(ledger, "job-2")
    assert ledger.accept("job-2", "alpha", "j" * 64, 0) == "full" and ledger.job("job-2").state == "reserved"  # a job respects the same cap


def test_revalidations_and_job_dispatches_share_one_fifo_sequence(ledger):
    settled_job(ledger)
    reserve(ledger, "job-2")
    assert ledger.accept("job-2", "alpha", "j" * 64, 100) == "accepted"
    reserve_operation(ledger, "op-1")
    ledger.apply_operation("op-1", "t")
    reserve(ledger, "job-3")
    assert ledger.accept("job-3", "alpha", "k" * 64, 100) == "accepted"
    order = []
    for _ in range(3):
        claim = ledger.claim_next()
        assert claim is not None
        order.append(claim.operation_id or claim.job_id)
    assert order == ["job-2", "op-1", "job-3"] and ledger.claim_next() is None


def test_a_busy_revalidation_waits_for_its_time_and_explicit_enqueue_needs_an_idle_unsettled_row(ledger):
    clock = [1000.0]
    ledger._clock = lambda: clock[0]
    settled_job(ledger)
    reserve_operation(ledger)
    ledger.apply_operation("op-1", "t")
    claim = ledger.claim_next()
    assert claim is not None and claim.operation_id == "op-1"
    assert ledger.finish_operation("op-1", Update("pending", "busy", "relation_busy", 2.0, 1))
    assert ledger.claim_next() is None
    clock[0] += 2.5
    again = ledger.claim_next()
    assert again is not None and again.busy_count == 1 and ledger.operation("op-1").reval_count == 2
    assert ledger.finish_operation("op-1", Update("idle", "transport_unknown"))
    assert ledger.enqueue_operation("op-1", 0) == "full" and ledger.operation("op-1").reval_state == "idle"
    assert ledger.enqueue_operation("op-1", 10) == "enqueued" and ledger.enqueue_operation("op-1", 10) == "coalesced"


def test_a_revalidation_a_dead_process_left_in_flight_ends_idle_and_a_cancelled_job_ends_its_queued_ones(ledger):
    settled_job(ledger)
    for key in ("running", "waiting"):
        reserve_operation(ledger, key)
        ledger.apply_operation(key, "t")
    claim = ledger.claim_next()
    assert claim is not None and claim.operation_id == "running"
    assert ledger.interrupt_in_flight() == 1
    running, waiting = ledger.operation("running"), ledger.operation("waiting")
    assert (running.reval_state, running.last_outcome, running.reval_count) == ("idle", "service_restarted", 1)
    assert (waiting.reval_state, waiting.reval_count) == ("pending", 0)  # the original intent that never started still runs, once
    ledger.cancel_pending("job-1")
    cancelled = ledger.operation("waiting")
    assert (cancelled.reval_state, cancelled.last_outcome) == ("idle", "cancelled") and ledger.claim_next() is None


def test_a_ledger_of_the_previous_schema_migrates_forward_and_an_unknown_schema_is_refused(tmp_path):
    directory = tmp_path / "service"
    directory.mkdir()
    first = RelationLedger(directory, tmp_path / "relation")
    reserve(first, "job-1")
    assert first.accept("job-1", "alpha", JOB_DIGEST, 100) == "accepted"
    first.close()
    path = directory / "relation-jobs.sqlite3"
    raw = sqlite3.connect(path)  # what a `-1` ledger looks like: no operations table, the previous schema id
    raw.execute("DROP TABLE relation_operations")
    raw.execute("UPDATE meta SET value=? WHERE key='schema'", (MIGRATES_FROM[0],))
    raw.commit()
    raw.close()
    migrated = RelationLedger(directory, tmp_path / "relation")
    assert migrated.job("job-1").state == "accepted" and migrated.dispatch("job-1").state == "pending"  # nothing older was rewritten
    assert migrated.reserve_operation("op-1", "alpha", "job-1", RC, "allow", JOB_DIGEST, 1, "a" * 64, 10) is not None
    migrated.close()
    raw = sqlite3.connect(path)
    assert raw.execute("SELECT value FROM meta WHERE key='schema'").fetchone() == (LEDGER_SCHEMA,)
    raw.execute("UPDATE meta SET value='zoop-ai-relation-jobs-ledger-9' WHERE key='schema'")
    raw.commit()
    raw.close()
    with pytest.raises(ConfigError) as caught:
        RelationLedger(directory, tmp_path / "relation")
    assert (caught.value.field, caught.value.reason) == ("ZOOP_AI_SERVICE_STATE_DIR", "relation_ledger_schema_mismatch")


# ---- review operations: the chain, the status and the wire --------------------------------------------------------------------------

def operation_row(**overrides: Any) -> OperationRow:
    base: dict[str, Any] = {
        "operation_id": "op-1", "owner": "alpha", "job_id": "job-1", "relation_candidate_id": RC, "decision": "allow",
        "expected_source_version": JOB_DIGEST, "expected_source_revision": 1, "request_digest": "a" * 64, "review_state": "applied",
        "review_attempts": 1, "reserved_at": "2026-10-13T00:00:00Z", "applied_at": "2026-10-13T00:00:01Z",
        "applied_event_at": "2026-10-13T00:00:02+00:00", "reval_state": "pending", "reval_count": 0, "busy_count": 0, "last_outcome": None,
        "last_runtime_code": None, "reval_updated_at": "2026-10-13T00:00:01Z", "settled": None, "settled_eligibility": None, "settled_at": None}
    return OperationRow(**{**base, **overrides})


def verdict_event(seq: int, eligibility: str = "hold", kind: str = "initial") -> dict[str, Any]:
    return {"seq": seq, "kind": "verdict", "createdAt": f"2026-10-13T00:00:0{seq}+00:00", "eligibility": eligibility, "attempt": {"kind": kind}}


def review_event(seq: int, *, decision: str = "allow", reviewer: str = "alpha", note: str = "op-1", expected: int | None = None,
                 effect: str | None = None) -> dict[str, Any]:
    return {"seq": seq, "kind": "review", "createdAt": f"2026-10-13T00:00:0{seq}+00:00", "decision": decision, "reviewer": reviewer,
            "note": marker(note) if note.startswith("op-") else note, "expectedRevision": seq - 1 if expected is None else expected,
            "effect": effect or ("revalidation-requested" if decision == "allow" else "excluded")}


def chain_of(*events: dict[str, Any], relation: str = RC) -> RelationChain:
    return RelationChain.model_validate({"jobId": "job-1", "inputDigest": JOB_DIGEST, "relations": [{
        "relationCandidateId": relation, "eligibility": {"status": "hold", "revision": len(events), "reviewPending": False}, "history": list(events)}]})


@pytest.mark.parametrize("events,kind", [
    ([verdict_event(1)], "absent"),
    ([verdict_event(1), review_event(2)], "applied"),
    ([verdict_event(1), review_event(2, reviewer="operator", note="operator note")], "moved"),     # someone else's event: never adopted
    ([verdict_event(1), review_event(2, reviewer="beta")], "mismatch"),
    ([verdict_event(1), review_event(2, decision="reject")], "mismatch"),
    ([verdict_event(1), review_event(2, expected=0)], "mismatch"),
    ([verdict_event(1), review_event(2, effect="excluded")], "mismatch"),
    ([verdict_event(1), review_event(2, reviewer="operator", note="x"), review_event(3)], "mismatch"),  # the marker at the wrong sequence
])
def test_the_chain_proves_an_operations_event_only_when_every_field_matches(events, kind):
    found = evidence(chain_of(*events), operation_row(review_state="reserved", applied_at=None, applied_event_at=None, reval_state=None))
    assert found.kind == kind
    assert (found.event_at == events[1]["createdAt"]) if kind == "applied" else True


def test_a_candidate_that_is_not_in_the_chain_is_missing():
    found = evidence(chain_of(verdict_event(1), relation="rc-" + "2" * 64), operation_row(review_state="reserved", applied_at=None, applied_event_at=None, reval_state=None))
    assert found.kind == "missing" and settlement(chain_of(verdict_event(1), relation="rc-" + "2" * 64), RC, 1) is None


@pytest.mark.parametrize("events,expected", [
    ([verdict_event(1), review_event(2), verdict_event(3, "eligible", "revalidation")], ("verified", "eligible")),
    ([verdict_event(1), review_event(2), verdict_event(3, "hold", "revalidation")], ("verified", "hold")),
    ([verdict_event(1), review_event(2), verdict_event(3, "reject", "revalidation")], ("verified", "reject")),
    ([verdict_event(1), review_event(2), review_event(3, decision="reject", reviewer="beta", note="other")], ("superseded", None)),
    ([verdict_event(1), review_event(2)], None),
    ([verdict_event(1), review_event(2), verdict_event(3, "eligible", "initial")], None),
    ([verdict_event(1), review_event(2), verdict_event(3, "pending", "revalidation")], None),
    ([verdict_event(1), review_event(2), review_event(3, decision="allow")], None),
])
def test_only_the_event_right_after_an_accepted_allow_settles_its_revalidation(events, expected):
    assert settlement(chain_of(*events), RC, 1) == expected


@pytest.mark.parametrize("overrides,state,next_", [
    ({"review_state": "reserved", "applied_at": None, "applied_event_at": None, "reval_state": None, "reval_updated_at": None}, "not_requested", "retry_review"),
    ({"decision": "reject", "reval_state": None, "reval_updated_at": None}, "not_requested", "none"),
    ({}, "queued", "wait"),
    ({"reval_state": "in_flight", "reval_count": 1}, "running", "wait"),
    ({"reval_state": "idle", "reval_count": 1, "last_outcome": "transport_unknown"}, "interrupted", "recover"),
    ({"reval_state": "idle", "reval_count": 1, "last_outcome": "service_restarted"}, "interrupted", "recover"),
    ({"reval_state": "idle", "reval_count": 1, "last_outcome": "runtime_error", "last_runtime_code": "verifier_replay_missing"}, "failed", "recover"),
    ({"reval_state": "idle", "reval_count": 2, "last_outcome": "runtime_error", "last_runtime_code": "replay_response_unknown"}, "failed", "operator_reconcile"),
    ({"reval_state": "idle", "reval_count": 8, "last_outcome": "busy", "last_runtime_code": "relation_busy"}, "failed", "recover"),
    ({"reval_state": "idle", "reval_count": 1, "last_outcome": "exited"}, "failed", "recover"),
    ({"reval_state": "idle", "last_outcome": "cancelled"}, "cancelled", "none"),
    ({"reval_state": "idle", "reval_count": 1, "last_outcome": "exited", "settled": "verified", "settled_eligibility": "hold", "settled_at": "t"}, "verified", "none"),
    ({"reval_state": "idle", "reval_count": 1, "last_outcome": "runtime_error", "last_runtime_code": "review_revision_conflict", "settled": "superseded",
      "settled_at": "t"}, "superseded", "none"),
])
def test_operation_status_is_derived_from_the_ledger_row_and_next_is_a_pure_rule(overrides, state, next_):
    row = operation_row(**overrides)
    status = operation_status(row, "2026-10-13T00:00:00Z")
    assert (status.revalidation.state, status.next, next_operation_action(row)) == (state, next_, next_)
    assert status.publication.state == "not_published" and status.reviewer == "alpha"
    assert (status.expected_source_version, status.expected_source_revision, status.accepted_at) == (JOB_DIGEST, "1", "2026-10-13T00:00:00Z")
    assert (status.review.state, status.review.resulting_source_revision) == (("unconfirmed", None) if overrides.get("review_state") == "reserved" else ("applied", "2"))
    assert RelationOperationStatus.model_validate(status.wire()).wire() == status.wire()
    if state == "verified":
        assert (status.revalidation.verdict, status.revalidation.resulting_source_revision) == ("hold", "3")


def test_the_review_model_is_exact_and_names_no_reviewer():
    assert RelationReview.model_validate(RELATION_REVIEW).wire() == RELATION_REVIEW
    for mutate in (lambda v: v.update(reviewer="x"), lambda v: v.update(expectedRevision=1), lambda v: v.update(decision="approve"),
                   lambda v: v.update(expectedSourceRevision=1), lambda v: v.update(expectedSourceRevision="0"),
                   lambda v: v.update(expectedSourceRevision="12345678901"), lambda v: v.update(expectedSourceVersion="z" * 64),
                   lambda v: v.pop("relationCandidateId")):
        value = dict(RELATION_REVIEW)
        mutate(value)
        with pytest.raises(ValidationError):
            RelationReview.model_validate(value)


def test_source_identity_is_derived_from_pipeline_fields_and_added_before_the_strict_parse():
    item = relation_item()
    item.pop("sourceVersion")
    item.pop("sourceRevision")
    raw = content(item)
    stamped = with_source_identity(raw)
    assert (stamped["relations"][0]["sourceVersion"], stamped["relations"][0]["sourceRevision"]) == (raw["inputDigest"], "3")
    assert "sourceVersion" not in raw["relations"][0]  # the pipeline payload itself is not mutated
    assert RelationJobContent.model_validate(stamped).relations[0].source_revision == "3"
    with pytest.raises((KeyError, TypeError)):
        with_source_identity({"inputDigest": "i" * 64})  # a payload without relations is unreadable, not empty


# ---- the disabled feature and the documentation -----------------------------------------------------------------------------------

def test_relation_routes_answer_409_after_authentication_when_the_group_is_not_enabled(start):
    service = start(replay=document_replay())
    for method, path in (("POST", "/internal/v1/relation-jobs"), ("GET", "/internal/v1/relation-jobs/j1"),
                         ("GET", "/internal/v1/relation-jobs/j1/result"), ("POST", "/internal/v1/relation-jobs/j1/cancel"),
                         ("POST", "/internal/v1/relation-jobs/j1/recover"), ("POST", "/internal/v1/relation-jobs/j1/reviews"),
                         ("GET", "/internal/v1/relation-jobs/j1/reviews/op-1"), ("POST", "/internal/v1/relation-jobs/j1/reviews/op-1/recover")):
        denied = service.request(method, path, as_=None)
        assert denied.status_code == 401 and denied.json()["schemaVersion"] == SCHEMA
        assert service.request(method, path, as_="reader").status_code == 403
        assert service.request(method, path, as_="submitter").status_code == 403
        if path.endswith("/reviews"):  # reading is not reviewing: a principal with only relation.read is refused the write, even while the group is off
            assert service.request(method, path, as_="viewer").status_code == 403
        disabled = service.request(method, path, as_="alpha", body=RELATION_SUBMIT if method == "POST" and path.endswith("jobs") else None,
                                   key="relation-synthetic-SYNTH-1" if method == "POST" and path.endswith("jobs") else None)
        assert disabled.status_code == 409 and disabled.json()["error"]["code"] == "execution_unavailable", (method, path)
        RelationErrorEnvelope.model_validate(disabled.json())
    # The S1 family keeps its own envelope schema.
    s1 = service.request("GET", "/internal/v1/analysis-jobs/j1", as_=None)
    assert s1.status_code == 401 and s1.json()["schemaVersion"] == "zoop-ai-internal-1"
    framework = service.request("GET", "/internal/v1/relation-jobs/bad id!", as_="alpha")
    assert framework.status_code in (409, 422, 404) and framework.json()["schemaVersion"] == SCHEMA


def test_authored_relation_examples_validate_against_the_models_and_the_next_rule():
    sample = relation_examples()
    for group in ("submit.202", "submit.200", "status.200", "cancel.200", "recover.202", "recover.200"):
        for example in sample[group].values():
            status = RelationJobStatus.model_validate(example["value"])
            assert status.next == next_action(status.state, status.dispatch.state)
    for group in ("review.202", "review.200", "operation.200", "operation.recover.202", "operation.recover.200"):
        for example in sample[group].values():
            operation = RelationOperationStatus.model_validate(example["value"])
            assert operation.publication.state == "not_published" and operation.reviewer == "app" and operation.expected_source_revision == "1"
            assert operation.revalidation.state != "verified" or (operation.revalidation.verdict, operation.revalidation.resulting_source_revision) == ("eligible", "3")
    assert sample["review.202"]["allowQueued"]["value"]["next"] == "wait" and sample["review.200"]["rejectRecorded"]["value"]["revalidation"]["state"] == "not_requested"
    assert sample["operation.200"]["unconfirmed"]["value"]["next"] == "retry_review" and sample["operation.200"]["unansweredCall"]["value"]["next"] == "operator_reconcile"
    assert sample["operation.200"]["interrupted"]["value"]["next"] == "recover"
    assert sample["errors"]["409.reviewNotConfirmed"]["value"]["operation"]["review"]["state"] == "unconfirmed"
    for example in sample["result.200"].values():
        envelope = RelationResultEnvelope.model_validate(example["value"])
        assert (envelope.job is None) == (envelope.delivery.state == "withheld")
        assert set(example["value"]["receipts"][0]) == {"stage", "state", "verdict"}
    for example in sample["errors"].values():
        parsed = RelationErrorEnvelope.model_validate(example["value"])
        assert set(example["value"]["error"]) == {"code", "retryable", "requestId", "runtimeCode", "field"}
        assert parsed.error.code
    assert sample["result.200"]["withheld"]["value"]["job"] is None and sample["result.200"]["available"]["value"]["job"] is not None


# ---- the gateway's catch-all keeps each family's envelope ----------------------------------------------------------------------

def test_an_unexpected_exception_answers_with_the_envelope_of_the_family_that_was_called():
    """An unexpected exception inside a real route reaches the Gateway catch-all. The relation family must answer with its own schema,
    the stable `internal_error` code and no exception text; the S1 family keeps its own schema (control)."""
    import asyncio
    import hashlib
    from types import SimpleNamespace

    import httpx

    from zoop_ai_service.app import create_app
    from zoop_ai_service.config import Principal

    token = "t" + "x" * 40

    class Exploding:
        config = SimpleNamespace(principals=(Principal("alpha", (hashlib.sha256(token.encode()).hexdigest(),),
                                                       frozenset({"analysis.read", "relation.read"})),))

        def status(self, owner, job_id, seen):
            raise RuntimeError("secret text /private/path Traceback")

    app = create_app(Exploding(), Exploding())
    app.state.log = lambda record: None

    async def get(path: str) -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            return await client.get(path, headers={"Authorization": f"Bearer {token}"})

    relation = asyncio.run(get("/internal/v1/relation-jobs/job-1"))
    control = asyncio.run(get("/internal/v1/analysis-jobs/job-1"))
    for response, schema in ((relation, SCHEMA), (control, "zoop-ai-internal-1")):
        assert response.status_code == 500 and response.json()["schemaVersion"] == schema
        error = response.json()["error"]
        assert error["code"] == "internal_error" and error["retryable"] is False and error["requestId"]
        assert set(error) == {"code", "retryable", "requestId", "runtimeCode", "field"}
        assert "secret text" not in response.text and "/private/path" not in response.text and "Traceback" not in response.text
    RelationErrorEnvelope.model_validate(relation.json())
