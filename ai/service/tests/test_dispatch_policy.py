"""Every row of the dispatch policy table, the `next` ordering and the receipt proof: pure functions over recorded-shape runtime output."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from support import document_jobs, outlook_job, semantic_job_and_entry
from zoop_ai_service.config import ServiceConfig
from zoop_ai_service.dispatch import MAX_BACKOFF, MAX_UNKNOWN, busy_delay, execution_unavailable, policy
from zoop_ai_service.runtime import Outcome
from zoop_ai_service.wire import JobView, continuation_would_send, next_action, receipts_complete, required_stages, unreceipted_attempts

USAGE = {"providerAttempts": 0, "replayCalls": 0, "inputTokens": None, "outputTokens": None, "cachedTokens": None,
         "reasoningTokens": None, "cost": None}


def call(stage: str, state: str) -> dict:
    return {"attemptId": f"attempt-{stage}", "stage": stage, "state": state, "mode": "live", "startedAt": "2026-10-12T00:00:00+00:00",
            "receivedAt": None if state in ("started", "unknown") else "2026-10-12T00:00:01+00:00", "inputDigest": "d" * 64,
            "config": {"provider": "openai-compatible", "providerRevision": "r", "model": "m", "reasoningEffort": None,
                       "promptVersion": "p", "schemaVersion": "zoop-ai-s1-1", "policyVersion": "g"},
            "usage": None, "error": None, "durationMs": None}


def submit_for(kind: str) -> dict:
    """A real, contract-valid Submit of the requested kind (repository-authored fixture text)."""
    if kind == "briefing-outlook":
        return outlook_job()
    if kind == "semantic-verification":
        return semantic_job_and_entry()[0]
    job = document_jobs()[0 if kind == "document-summary" else 1]
    job["kind"] = kind
    return job


def view(state="queued", phase="input.persisted", resume="unsent_only", calls=(), kind="document-summary") -> JobView:
    return JobView.model_validate({
        "schemaVersion": "zoop-ai-s1-1", "jobId": "j", "inputDigest": "i" * 64, "state": state, "phase": phase, "attemptId": None,
        "artifactIds": [], "artifacts": [], "failure": None, "resumeMode": resume, "usage": USAGE, "grant": None,
        "input": submit_for(kind), "calls": list(calls)})


def result(**kwargs) -> tuple[Outcome, JobView]:
    parsed = view(**kwargs)
    return Outcome("result", result=parsed.wire(), exit_code=0), parsed


def decide(command, outcome, parsed=None, *, unknown=0, busy=0, fresh=True):
    return policy(command, outcome, parsed, unknown_count=unknown, busy_count=busy, fresh=fresh)


def row(update):
    return (update.state, update.command, update.last_outcome, update.runtime_code, update.delay, update.unknown_count, update.busy_count)


@pytest.mark.parametrize("command", ["run", "resume"])
@pytest.mark.parametrize("state", ["queued", "running"])
def test_runtime_handing_back_a_live_job_means_another_process_holds_it_so_back_off(command, state):
    outcome, parsed = result(state=state)
    assert row(decide(command, outcome, parsed, busy=0)) == ("pending", command, "busy", None, 1.0, 0, 1)
    assert row(decide(command, outcome, parsed, busy=3)) == ("pending", command, "busy", None, 8.0, 0, 4)
    assert decide(command, outcome, parsed, busy=20).delay == MAX_BACKOFF == busy_delay(99)
    assert decide(command, outcome, parsed, unknown=2, busy=0).unknown_count == 0  # a clean answer resets the unknown streak


def test_save_only_resumes_automatically_only_when_every_receipt_is_already_stored():
    complete = [call("document-summary", "received"), call("semantic-verification", "received")]
    outcome, parsed = result(state="persisting", phase="artifact.validated", resume="save_only", calls=complete)
    assert row(decide("run", outcome, parsed)) == ("pending", "resume", "exited", None, 0.0, 0, 0)
    # Receipts missing a stage: a resume could build a provider client and send, so a person must ask for it.
    partial = [call("document-summary", "received")]
    outcome, parsed = result(state="persisting", phase="storage.failed", resume="save_only", calls=partial)
    assert row(decide("run", outcome, parsed)) == ("idle", None, "exited", None, 0.0, 0, 0)
    outcome, parsed = result(state="persisting", phase="storage.failed", resume="save_only", calls=[])
    assert decide("run", outcome, parsed).state == "idle"
    stuck = [*complete[:1], call("semantic-verification", "unknown")]
    outcome, parsed = result(state="persisting", resume="save_only", calls=stuck)
    assert decide("run", outcome, parsed).state == "idle"
    outcome, parsed = result(state="persisting", resume="validate_only", calls=complete)
    assert decide("run", outcome, parsed).state == "idle"
    outcome, parsed = result(state="persisting", resume="save_only", calls=complete)
    assert row(decide("resume", outcome, parsed)) == ("idle", None, "exited", None, 0.0, 0, 0)  # never loops


@pytest.mark.parametrize("state,resume", [("ready", "none"), ("failed", "none"), ("failed", "unsent_only"), ("cancelled", "none"),
                                          ("reconciling", "reconcile_only"), ("persisting", "save_only")])
@pytest.mark.parametrize("command", ["run", "resume"])
def test_terminal_and_waiting_states_end_the_dispatch_and_a_failed_job_is_never_resumed_automatically(state, resume, command):
    outcome, parsed = result(state=state, resume=resume, calls=[call("document-summary", "unknown")] if state == "reconciling" else [])
    assert row(decide(command, outcome, parsed)) == ("idle", None, "exited", None, 0.0, 0, 0)


def test_a_runtime_error_code_ends_the_dispatch_as_registered_but_blocked():
    update = decide("run", Outcome("error", code="replay_fixture_required", exit_code=2))
    assert row(update) == ("idle", None, "runtime_error", "replay_fixture_required", 0.0, 0, 0)


@pytest.mark.parametrize("kind", ["timeout", "abnormal"])
@pytest.mark.parametrize("command", ["run", "resume"])
def test_unknown_outcomes_are_redispatched_at_most_three_times_and_never_resolved_by_the_service(kind, command):
    assert row(decide(command, Outcome(kind), unknown=0)) == ("pending", command, "transport_unknown", None, 1.0, 1, 0)
    assert row(decide(command, Outcome(kind), unknown=1)) == ("pending", command, "transport_unknown", None, 1.0, 2, 0)
    assert row(decide(command, Outcome(kind), unknown=MAX_UNKNOWN - 1)) == ("idle", None, "transport_unknown", None, 0.0, MAX_UNKNOWN, 0)


def test_spawn_failure_or_oversized_output_is_not_retried():
    assert row(decide("run", Outcome("unavailable"))) == ("idle", None, "runtime_unavailable", None, 0.0, 0, 0)


@pytest.mark.parametrize("state,resume,dispatch,expected", [
    ("queued", "unsent_only", "pending", "wait"), ("ready", "none", "in_flight", "wait"), ("reconciling", "reconcile_only", "pending", "wait"),
    ("ready", "none", "idle", "fetch_result"),
    ("reconciling", "reconcile_only", "idle", "operator_reconcile"),
    ("cancelled", "none", "idle", "none"), ("failed", "none", "idle", "none"),
    ("failed", "unsent_only", "idle", "recover"), ("queued", "unsent_only", "idle", "recover"), ("running", "unsent_only", "idle", "recover"),
    ("persisting", "save_only", "idle", "recover"),
])
def test_next_action_is_ordered_and_pure(state, resume, dispatch, expected):
    assert next_action(state, resume, dispatch) == expected


def test_required_stages_and_the_receipt_proof_per_kind():
    assert required_stages("document-summary") == ("document-summary", "semantic-verification")
    assert required_stages("semantic-verification") == ("semantic-verification",)
    assert required_stages("briefing-outlook") == ("briefing-outlook",)
    one = [call("semantic-verification", "validated")]
    assert receipts_complete(view(kind="semantic-verification", calls=one))
    assert receipts_complete(view(kind="briefing-outlook", calls=[call("briefing-outlook", "received")]))
    assert not receipts_complete(view(kind="briefing-outlook", calls=[call("briefing-outlook", "failed")]))
    assert not receipts_complete(view(kind="document-sentiment", calls=[call("document-sentiment", "received")]))
    assert not receipts_complete(view(phase="artifact.cache_hit", kind="semantic-verification", calls=one))
    assert not receipts_complete(view(kind="semantic-verification", calls=[*one, call("document-summary", "started")]))


def test_unreceipted_attempts_count_unknown_outcomes_but_a_cache_hit_has_no_call_of_its_own():
    calls = [call("document-summary", "received"), call("semantic-verification", "started"), call("briefing-outlook", "unknown")]
    assert unreceipted_attempts(view(calls=calls)) == 2
    assert unreceipted_attempts(view(phase="artifact.cache_hit", state="ready", calls=copy.deepcopy(calls))) == 0
    assert unreceipted_attempts(view(calls=[])) == 0


def test_execution_availability_follows_current_server_configuration():
    def config(live: bool, replay: bool) -> ServiceConfig:
        return ServiceConfig((), Path("/s"), Path("/w"), Path("/c"), Path("/g"), Path("/r") if replay else None, 8797, live, {})
    assert execution_unavailable(config(False, True), "live") and not execution_unavailable(config(True, False), "live")
    assert execution_unavailable(config(True, False), "replay") and not execution_unavailable(config(False, True), "replay")


@pytest.mark.parametrize("kind,done", [("document-summary", "document-summary"), ("document-sentiment", "document-sentiment"),
                                       ("document-summary", "semantic-verification")])
@pytest.mark.parametrize("state,resume", [("running", "unsent_only"), ("queued", "unsent_only"), ("persisting", "save_only")])
@pytest.mark.parametrize("command", ["run", "resume"])
def test_an_automatic_redispatch_that_hands_back_some_but_not_all_receipts_is_held_for_an_explicit_recover(kind, done, state, resume, command):
    calls = [call(done, "received")]
    assert continuation_would_send(view(state=state, resume=resume, calls=calls, kind=kind))
    outcome, parsed = result(state=state, resume=resume, calls=calls, kind=kind)
    assert row(decide(command, outcome, parsed, fresh=False)) == ("idle", None, "needs_recover", None, 0.0, 0, 0)
    # The original intent and an explicit recover (fresh) are not held by this rule.
    assert decide(command, outcome, parsed, fresh=True).last_outcome != "needs_recover"


def test_automatic_redispatch_results_that_cannot_send_are_not_held():
    complete = [call("document-summary", "received"), call("semantic-verification", "validated")]
    outcome, parsed = result(state="persisting", resume="save_only", calls=complete)
    assert row(decide("run", outcome, parsed, fresh=False)) == ("pending", "resume", "exited", None, 0.0, 0, 0)
    outcome, parsed = result(state="queued", calls=[])
    assert decide("run", outcome, parsed, fresh=False).last_outcome == "busy"
    for stuck in ("started", "unknown", "failed"):
        outcome, parsed = result(state="running", calls=[call("document-summary", "received"), call("semantic-verification", stuck)])
        assert decide("run", outcome, parsed, fresh=False).last_outcome == "busy"  # an orphan or reconcile, never a held send
    outcome, parsed = result(state="running", calls=[call("document-summary", "started")])
    assert decide("run", outcome, parsed, fresh=False).last_outcome == "busy"
    outcome, parsed = result(kind="briefing-outlook", state="running", calls=[call("briefing-outlook", "received")])
    assert decide("run", outcome, parsed, fresh=False).last_outcome == "busy"


def test_a_finished_state_ends_the_dispatch_even_when_automatic():
    for state, resume in (("ready", "none"), ("cancelled", "none"), ("failed", "unsent_only"), ("reconciling", "reconcile_only")):
        outcome, parsed = result(state=state, resume=resume, calls=[call("document-summary", "received")])
        assert row(decide("run", outcome, parsed, fresh=False)) == ("idle", None, "exited", None, 0.0, 0, 0)
