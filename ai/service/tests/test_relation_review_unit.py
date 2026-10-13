"""The review decision tree of `RelationJobs`, without an installed pipeline: a scripted stand-in for the one door to the pipeline, a real service
ledger and the real configuration loader. What is proven here is every branch of "did my append land?": which outcome releases the reservation,
which keeps it, when the chain is read before anything is written, and that an event is adopted only when every field of it is the operation's.

The same flows against the real installed `zoop-ai-relation` live in `ai/service/pipeline_tests` (`make service-pipeline-test`).
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from support import Workspace, document_replay
from test_relation_unit import RC, UPSTREAM_DIGEST, payload, relation_env, review_event, verdict_event
from zoop_ai_service import relation_access
from zoop_ai_service.config import load
from zoop_ai_service.jobs import Observation
from zoop_ai_service.relation_dispatch import RelationDispatcher
from zoop_ai_service.relation_jobs import RelationError, RelationJobs
from zoop_ai_service.relation_ledger import RelationLedger, Update
from zoop_ai_service.relation_review import marker, operation_status
from zoop_ai_service.relation_runtime import RelationGate
from zoop_ai_service.relation_wire import RelationReview
from zoop_ai_service.runtime import Outcome

JOB_DIGEST = "c" * 64  # the job's inputDigest = its `sourceVersion`: valid hex, and distinct from the upstream digest ("d" * 64) and the other values used here
BINDING = {"schema": "x", "upstream": {"jobId": "s2-job", "inputDigest": UPSTREAM_DIGEST, "digest": "u" * 64}}


class Scripted:
    """Stands in for `RelationProcess`: each command answers from its own queue, and every call is recorded in order."""

    def __init__(self, **queues: list[Outcome]):
        self.queues, self.calls, self.review_args = {name: list(items) for name, items in queues.items()}, [], None

    def _answer(self, name: str) -> Outcome:
        self.calls.append(name)
        assert self.queues.get(name), f"unscripted {name}"
        return self.queues[name].pop(0)

    def review(self, *args: Any) -> Outcome:
        self.review_args = args
        return self._answer("review")

    def inspect(self, job_id: str) -> Outcome:
        return self._answer("inspect")

    def revalidate(self, *args: Any) -> Outcome:
        self.revalidate_args = args
        return self._answer("revalidate")


def view(*events: dict[str, Any], state: str = "ready", revision: int | None = None, pending: bool = False, **extra: Any) -> Outcome:
    raw = {**payload(state, binding=BINDING, inputDigest=JOB_DIGEST, **extra), "relations": [{
        "relationCandidateId": RC, "eligibility": {"status": "hold", "revision": len(events) if revision is None else revision, "reviewPending": pending},
        "history": list(events)}]}
    return Outcome("result", result=raw, exit_code=0)


def withheld(code: str = "source_unauthorized") -> Outcome:
    return Outcome("result", result=payload("ready", binding=BINDING, inputDigest=JOB_DIGEST, delivery={"status": "withheld", "code": code}), exit_code=2)


def landed(*extra: dict[str, Any]) -> Outcome:
    """The chain after our allow was appended: the initial verdict, then the review carrying this operation's marker."""
    return view(verdict_event(1), review_event(2), *extra, pending=not extra)


def body(*, decision: str = "allow", revision: str = "1", version: str = JOB_DIGEST) -> RelationReview:
    return RelationReview.model_validate({"relationCandidateId": RC, "expectedSourceVersion": version, "expectedSourceRevision": revision, "decision": decision})


@pytest.fixture
def harness(tmp_path):
    ws = Workspace(tmp_path, replay=document_replay())
    config = load(relation_env(ws, tmp_path))
    assert config.relation is not None
    ledger = RelationLedger(config.state_dir, config.relation.state_dir)
    ledger.reserve("job", "alpha", "a" * 64, "s2-job", UPSTREAM_DIGEST)
    assert ledger.accept("job", "alpha", JOB_DIGEST, 100) == "accepted"
    assert ledger.claim_next() is not None and ledger.finish("job", Update("idle", "exited"))
    woke = SimpleNamespace(count=0)
    waker = SimpleNamespace(wake=lambda: setattr(woke, "count", woke.count + 1))

    def build(process: Scripted) -> RelationJobs:
        return RelationJobs(config, ledger, process, waker, RelationGate(), busy_wait=0.5)  # type: ignore[arg-type]

    yield SimpleNamespace(build=build, ledger=ledger, woke=woke, root=tmp_path, config=config)
    ledger.close()


def run(jobs: RelationJobs, key: str = "op-1", review: RelationReview | None = None, owner: str = "alpha"):
    return jobs.review(owner, "job", key, review or body(), Observation())


def refused(jobs: RelationJobs, *args: Any, **kwargs: Any) -> RelationError:
    with pytest.raises(RelationError) as caught:
        run(jobs, *args, **kwargs)
    return caught.value


def test_a_review_the_pipeline_appended_is_adopted_from_the_chain_and_queues_one_revalidation(harness):
    process = Scripted(review=[landed()])
    jobs = harness.build(process)
    reply = run(jobs)
    assert reply.status == 202 and reply.headers["Location"] == "/internal/v1/relation-jobs/job/reviews/op-1" and reply.headers["Retry-After"] == "2"
    status = reply.body
    assert (status.review.state, status.review.resulting_source_revision, status.revalidation.state, status.next) == ("applied", "2", "queued", "wait")
    assert process.calls == ["review"] and harness.woke.count == 1
    # reviewer = the authenticated principal, note = the operation marker, revision = the expected SOURCE revision as an integer: nothing from the request body's text.
    assert process.review_args == ("job", RC, 1, "allow", "alpha", marker("op-1"))
    row = harness.ledger.operation("op-1")
    assert row is not None and (row.applied_event_at, row.reval_state, row.review_attempts) == ("2026-10-13T00:00:02+00:00", "pending", 1)


def test_a_reject_is_recorded_and_queues_nothing(harness):
    process = Scripted(review=[view(verdict_event(1), review_event(2, decision="reject"), revision=2)])
    reply = run(harness.build(process), review=body(decision="reject"))
    assert reply.status == 200 and (reply.body.revalidation.state, reply.body.next) == ("not_requested", "none")
    assert harness.ledger.operation("op-1").reval_state is None and harness.ledger.claim_next() is None


@pytest.mark.parametrize("code,status,mapped", [
    ("review_revision_conflict", 409, "source_revision_conflict"), ("review_target_not_hold", 409, "review_target_not_hold"),
    ("review_already_pending", 409, "review_already_pending"), ("job_cancelled", 409, "job_cancelled"),
    ("relation_candidate_not_found", 404, "relation_candidate_not_found"), ("source_unauthorized", 409, "upstream_unavailable"),
])
def test_a_refusal_before_the_append_releases_the_reservation_and_records_nothing(harness, code, status, mapped):
    process = Scripted(review=[Outcome("error", code=code, exit_code=2)])
    error = refused(harness.build(process))
    assert (error.status, error.code, error.runtime_code) == (status, mapped, code) and process.calls == ["review"]  # no chain read was needed
    assert harness.ledger.operation("op-1") is None and harness.woke.count == 0


def test_a_refusal_frees_the_key_for_a_corrected_request(harness):
    process = Scripted(review=[Outcome("error", code="review_revision_conflict", exit_code=2), landed()])
    jobs = harness.build(process)
    assert refused(jobs, review=body(revision="2")).code == "source_revision_conflict"
    assert run(jobs).status == 202 and process.calls == ["review", "review"]  # the first attempt left nothing to read first


def test_a_busy_pipeline_keeps_the_reservation_and_the_retry_reads_the_chain_before_it_writes(harness):
    process = Scripted(review=[Outcome("error", code="relation_busy", exit_code=2)], inspect=[landed()])
    jobs = harness.build(process)
    error = refused(jobs)
    assert (error.status, error.code, error.headers["Retry-After"]) == (503, "runtime_busy", "2")
    assert harness.ledger.operation("op-1").review_attempts == 1 and harness.ledger.operation("op-1").review_state == "reserved"
    assert run(jobs).status == 202 and process.calls == ["review", "inspect"]  # an event found by the read is adopted, never appended again


def test_a_retry_proves_absence_first_and_then_appends_exactly_once(harness):
    process = Scripted(review=[Outcome("timeout"), landed()], inspect=[view(verdict_event(1)), view(verdict_event(1))])
    jobs = harness.build(process)
    error = refused(jobs)
    assert (error.status, error.code) == (503, "review_unconfirmed")
    assert error.headers["Retry-After"] == "2" and harness.ledger.operation("op-1").review_state == "reserved"
    assert run(jobs).status == 202
    # write (lost) -> read (nothing there) | retry: read (nothing there) -> write: the second write happens only after the chain proved the first never landed
    assert process.calls == ["review", "inspect", "inspect", "review"]
    assert harness.ledger.operation("op-1").review_attempts == 2


# ---- regression: an orphaned child appends between the retry's read and its write ---------------------------------------------------------
#
# A dead or timed-out service can leave a `zoop-ai-relation review` child alive but not yet holding the pipeline's ledger lock. The retry
# reads the chain (nothing there), the orphan then takes the lock and appends THIS operation's exact event, and the retry's own child is
# refused with `review_revision_conflict`. That refusal is not proof the event is absent: the retry must read the chain again after it and
# adopt the exact event. Only a chain that can never take the event (the relation moved on without our marker) releases the reservation.
# The first attempt of an operation has no earlier child that could have written, so its refusal stays definitive (see the refusal test above).

CONFLICT = Outcome("error", code="review_revision_conflict", exit_code=2)


def retried_after_a_lost_child(harness, *, post_refusal_chain: Outcome, refusal: Outcome = CONFLICT, then_review: tuple[Outcome, ...] = ()):
    """First call: the child is lost and the chain shows nothing (the reservation stays, one attempt counted). Second call: the read before
    the write shows nothing either, then the pipeline refuses the retry's own write with `refusal`, then `post_refusal_chain` is what the chain
    says. `then_review` scripts later review children (a reuse of the key). Returns (process, jobs)."""
    process = Scripted(review=[Outcome("timeout"), refusal, *then_review], inspect=[view(verdict_event(1)), view(verdict_event(1)), post_refusal_chain])
    jobs = harness.build(process)
    first = refused(jobs)
    assert (first.status, first.code) == (503, "review_unconfirmed") and harness.ledger.operation("op-1").review_attempts == 1
    return process, jobs


def test_a_retry_conflict_caused_by_an_orphan_that_appended_the_exact_event_is_adopted_not_released(harness):
    process, jobs = retried_after_a_lost_child(harness, post_refusal_chain=landed())
    reply = run(jobs)
    assert reply.status == 202 and (reply.body.review.state, reply.body.review.resulting_source_revision, reply.body.revalidation.state) == (
        "applied", "2", "queued")
    row = harness.ledger.operation("op-1")
    assert row is not None and (row.review_state, row.reval_state, row.review_attempts) == ("applied", "pending", 2)
    assert row.applied_event_at == "2026-10-13T00:00:02+00:00" and harness.woke.count == 1  # the queued revalidation survives, the key stays bound
    claim = harness.ledger.claim_next()
    assert claim is not None and claim.operation_id == "op-1"  # and the dispatcher really has the revalidation to run


@pytest.mark.parametrize("post_refusal_chain,status,code", [
    (Outcome("error", code="relation_busy", exit_code=2), 503, "review_unconfirmed"),
    (Outcome("timeout"), 503, "review_unconfirmed"),
    (withheld(), 503, "review_unconfirmed"),
    (view(verdict_event(1), review_event(2, reviewer="beta"), pending=True), 500, "runtime_binding_mismatch"),   # the marker, but not our event
    (view(verdict_event(1)), 503, "review_unconfirmed"),   # a revision conflict with a chain still at the expected revision contradicts itself
])
def test_a_retry_conflict_with_an_unreadable_or_contradictory_chain_keeps_the_reservation(harness, post_refusal_chain, status, code):
    process, jobs = retried_after_a_lost_child(harness, post_refusal_chain=post_refusal_chain)
    error = refused(jobs)
    assert (error.status, error.code) == (status, code)
    row = harness.ledger.operation("op-1")
    assert row is not None and (row.review_state, row.review_attempts) == ("reserved", 2) and harness.woke.count == 0  # nothing proven, nothing released
    assert harness.ledger.claim_next() is None  # and no revalidation was queued for an unproven event
    assert refused(jobs, review=body(decision="reject", revision="2")).code == "idempotency_conflict"  # the key is still bound to the original request


def test_a_retry_conflict_with_a_foreign_event_in_the_chain_releases_the_reservation_and_the_key_is_reusable(harness):
    foreign = view(verdict_event(1), review_event(2, reviewer="operator", note="operator note"), pending=True)
    reused_chain = view(verdict_event(1), review_event(2, reviewer="operator", note="operator note"), review_event(3, decision="reject"), revision=3)
    process, jobs = retried_after_a_lost_child(harness, post_refusal_chain=foreign, then_review=(reused_chain,))
    error = refused(jobs)  # permanent absence is proven: the relation moved past the expected revision without our marker
    assert (error.status, error.code) == (409, "source_revision_conflict")
    assert harness.ledger.operation("op-1") is None and harness.woke.count == 0  # actually released: nothing bound, nothing queued
    # Reusable under the safe CURRENT revision (2, the operator's allow is pending): a reject on top. A retained reservation would answer
    # idempotency_conflict here, because this body differs from the original one.
    reused = run(jobs, review=body(decision="reject", revision="2"))
    assert reused.status == 200 and (reused.body.decision, reused.body.review.state, reused.body.review.resulting_source_revision) == ("reject", "applied", "3")
    row = harness.ledger.operation("op-1")
    assert row is not None and (row.decision, row.expected_source_revision, row.review_attempts) == ("reject", 2, 1)  # a fresh operation, not the old one


@pytest.mark.parametrize("code", ["review_target_not_hold", "review_already_pending", "job_cancelled", "relation_candidate_not_found"])
def test_a_retry_refusal_that_is_a_pure_function_of_the_chain_releases_once_the_chain_shows_no_event_of_ours(harness, code):
    refusal = Outcome("error", code=code, exit_code=2)
    process, jobs = retried_after_a_lost_child(harness, post_refusal_chain=view(verdict_event(1)), refusal=refusal, then_review=(landed(),))
    error = refused(jobs)
    assert error.runtime_code == code and error.status in (404, 409)
    assert harness.ledger.operation("op-1") is None  # released: no child, orphaned or not, can append at a revision that refuses it
    assert run(jobs).status == 202  # and the key is reusable at the unchanged revision


@pytest.mark.parametrize("outcome", [Outcome("timeout"), Outcome("abnormal", exit_code=75), Outcome("unavailable"),
                                     Outcome("error", code="persistence_failed", exit_code=2), withheld()])
def test_an_ambiguous_review_whose_event_is_in_the_chain_is_adopted(harness, outcome):
    process = Scripted(review=[outcome], inspect=[landed()])
    reply = run(harness.build(process))
    assert reply.status == 202 and process.calls == ["review", "inspect"] and harness.ledger.operation("op-1").review_state == "applied"


def test_an_ambiguous_review_whose_relation_moved_without_our_event_is_refused_and_released(harness):
    foreign = view(verdict_event(1), review_event(2, reviewer="operator", note="operator note"), pending=True)
    process = Scripted(review=[Outcome("timeout")], inspect=[foreign])
    error = refused(harness.build(process))
    assert (error.status, error.code) == (409, "source_revision_conflict") and harness.ledger.operation("op-1") is None


@pytest.mark.parametrize("probe", [Outcome("error", code="relation_busy", exit_code=2), Outcome("timeout"), withheld()])
def test_when_the_chain_cannot_be_read_nothing_is_decided(harness, probe):
    process = Scripted(review=[Outcome("timeout")], inspect=[probe])
    error = refused(harness.build(process))
    assert (error.status, error.code) == (503, "review_unconfirmed") and error.envelope("req-1").error.retryable is True
    assert harness.ledger.operation("op-1").review_state == "reserved" and harness.woke.count == 0


def test_an_event_with_the_marker_that_is_not_exactly_the_operations_is_never_adopted(harness):
    process = Scripted(review=[Outcome("timeout")], inspect=[view(verdict_event(1), review_event(2, reviewer="beta"), pending=True)])
    error = refused(harness.build(process))
    assert (error.status, error.code) == (500, "runtime_binding_mismatch") and harness.ledger.operation("op-1").review_state == "reserved"


def test_a_success_that_does_not_show_the_event_contradicts_the_pipeline_and_adopts_nothing(harness):
    process = Scripted(review=[view(verdict_event(1))])
    error = refused(harness.build(process))
    assert (error.status, error.code) == (500, "runtime_binding_mismatch") and harness.ledger.operation("op-1").review_state == "reserved"


def test_a_candidate_missing_from_the_readable_chain_releases_the_reservation(harness):
    other = Outcome("result", result={**view(verdict_event(1)).result, "relations": []}, exit_code=0)
    process = Scripted(review=[Outcome("timeout")], inspect=[other])
    error = refused(harness.build(process))
    assert (error.status, error.code) == (404, "relation_candidate_not_found") and harness.ledger.operation("op-1") is None


def test_replays_conflicts_and_foreign_keys_never_reach_the_pipeline(harness):
    process = Scripted(review=[landed()])
    jobs = harness.build(process)
    assert run(jobs).status == 202
    again = run(jobs)
    assert again.status == 200 and again.body.review.state == "applied" and process.calls == ["review"]
    for other in (body(decision="reject"), body(revision="2"), body(version="0" * 64)):
        assert refused(jobs, review=other).code == "idempotency_conflict"
    assert refused(jobs, owner="beta").code == "job_not_found"  # beta does not own the job: the same answer as for a job that never existed
    harness.ledger.reserve("beta-job", "beta", "b" * 64, "s2-job", UPSTREAM_DIGEST)
    assert harness.ledger.accept("beta-job", "beta", JOB_DIGEST, 100) == "accepted"
    with pytest.raises(RelationError) as caught:
        jobs.review("beta", "beta-job", "op-1", body(), Observation())
    assert (caught.value.status, caught.value.code) == (409, "operation_id_unavailable")
    for owner, job_id, key in (("beta", "job", "op-1"), ("alpha", "job", "never"), ("alpha", "beta-job", "op-1"), ("beta", "beta-job", "op-1")):
        with pytest.raises(RelationError) as missing:
            jobs.operation(owner, job_id, key, Observation())
        assert missing.value.status == 404 and missing.value.code in {"job_not_found", "operation_not_found"}
    assert jobs.operation("alpha", "job", "op-1", Observation()).body.operation_id == "op-1" and process.calls == ["review"]


def test_a_stale_source_version_is_refused_before_anything_is_reserved(harness):
    process = Scripted()
    error = refused(harness.build(process), review=body(version="0" * 64))
    assert (error.status, error.code) == (409, "source_version_conflict") and process.calls == [] and harness.ledger.operation("op-1") is None


def test_a_new_review_needs_the_upstream_listed_now(harness):
    (harness.root / "upstreams.json").write_text(json.dumps({"schemaVersion": relation_access.SCHEMA, "upstreams": []}))
    process = Scripted()
    error = refused(harness.build(process))
    assert (error.status, error.code) == (403, "upstream_not_allowed") and process.calls == [] and harness.ledger.operation("op-1") is None
    (harness.root / "upstreams.json").write_text("{broken")
    assert refused(harness.build(process)).code == "service_configuration_invalid" and process.calls == []


def test_a_full_queue_refuses_a_new_allow_before_the_pipeline_is_asked(harness):
    import zoop_ai_service.relation_jobs as module
    process = Scripted()
    original, module.MAX_PENDING = module.MAX_PENDING, 0
    try:
        error = refused(harness.build(process))
    finally:
        module.MAX_PENDING = original
    assert (error.status, error.code, error.headers["Retry-After"]) == (503, "queue_full", "30") and process.calls == []
    assert harness.ledger.operation("op-1") is None


# ---- recovery -----------------------------------------------------------------------------------------------------------------------------

def applied_allow(harness, key: str = "op-1", *, outcome: str | None = "transport_unknown", decision: str = "allow") -> None:
    """An accepted review whose revalidation dispatch already ended (or none for a reject)."""
    assert harness.ledger.reserve_operation(key, "alpha", "job", RC, decision, JOB_DIGEST, 1, "d" * 64, 100) is not None
    assert harness.ledger.apply_operation(key, "2026-10-13T00:00:02+00:00")
    if outcome is not None:
        claim = harness.ledger.claim_next()
        assert claim is not None and claim.operation_id == key
        assert harness.ledger.finish_operation(key, Update("idle", outcome if outcome in {"transport_unknown", "service_restarted"} else "runtime_error"))


def recover(jobs: RelationJobs, key: str = "op-1", owner: str = "alpha"):
    return jobs.recover_operation(owner, "job", key, Observation())


def test_recover_settles_from_a_verdict_that_is_already_in_the_chain_without_dispatching(harness):
    applied_allow(harness)
    process = Scripted(inspect=[landed(verdict_event(3, "eligible", "revalidation"))])
    reply = recover(harness.build(process))
    assert reply.status == 200 and (reply.body.revalidation.state, reply.body.revalidation.verdict) == ("verified", "eligible")
    assert process.calls == ["inspect"] and harness.ledger.claim_next() is None and harness.ledger.operation("op-1").settled == "verified"


def test_recover_settles_a_superseded_allow_and_never_dispatches(harness):
    applied_allow(harness)
    process = Scripted(inspect=[landed(review_event(3, decision="reject", reviewer="beta", note="other"))])
    reply = recover(harness.build(process))
    assert reply.status == 200 and reply.body.revalidation.state == "superseded" and harness.ledger.claim_next() is None


def test_recover_queues_the_revalidation_again_only_while_the_relation_waits_at_the_revision_the_review_left(harness):
    applied_allow(harness)
    process = Scripted(inspect=[landed()])
    reply = recover(harness.build(process))
    assert reply.status == 202 and reply.body.revalidation.state == "queued" and harness.woke.count == 1
    assert harness.ledger.operation("op-1").reval_state == "pending"
    again = recover(harness.build(Scripted()))  # pending: coalesced without touching the pipeline
    assert again.status == 200 and again.body.revalidation.state == "queued"


@pytest.mark.parametrize("chain,code", [
    (view(verdict_event(1), review_event(2), review_event(3, reviewer="operator", note="x"), review_event(4, reviewer="operator", note="y"), pending=True), "operation_not_recoverable"),
    (landed(), None),
])
def test_recover_refuses_a_relation_that_no_longer_waits_for_this_operation(harness, chain, code):
    applied_allow(harness)
    process = Scripted(inspect=[chain])
    if code is None:
        assert recover(harness.build(process)).status == 202
        return
    with pytest.raises(RelationError) as caught:
        recover(harness.build(process))
    assert (caught.value.status, caught.value.code) == (409, code) and caught.value.operation is not None and harness.ledger.claim_next() is None


def test_recover_never_resends_a_call_the_pipeline_cannot_account_for(harness):
    applied_allow(harness)
    reconciling = landed().result
    reconciling = {**reconciling, "state": "reconciling", "failure": {"code": "replay_response_unknown"}}
    process = Scripted(inspect=[Outcome("result", result=reconciling, exit_code=0)])
    with pytest.raises(RelationError) as caught:
        recover(harness.build(process))
    error = caught.value
    assert (error.status, error.code) == (409, "reconcile_required") and error.operation is not None and error.relation_status is not None
    assert harness.ledger.operation("op-1").reval_state == "idle" and harness.ledger.claim_next() is None


def test_recover_refuses_a_cancelled_job_and_a_withheld_chain_with_stable_codes(harness):
    applied_allow(harness)
    cancelled = Outcome("result", result={**landed().result, "state": "cancelled", "delivery": {"status": "withheld", "code": "job_cancelled"}}, exit_code=2)
    with pytest.raises(RelationError) as caught:
        recover(harness.build(Scripted(inspect=[cancelled])))
    assert (caught.value.status, caught.value.code) == (409, "job_cancelled")
    with pytest.raises(RelationError) as caught:
        recover(harness.build(Scripted(inspect=[withheld()])))
    assert (caught.value.status, caught.value.code, caught.value.runtime_code) == (409, "upstream_unavailable", "source_unauthorized")


def test_recover_has_nothing_to_do_for_a_reject_an_unconfirmed_review_or_a_waiting_revalidation(harness):
    harness.ledger.reserve_operation("unconfirmed", "alpha", "job", RC, "allow", JOB_DIGEST, 1, "e" * 64, 100)
    applied_allow(harness, "rejected", outcome=None, decision="reject")
    applied_allow(harness, "waiting", outcome=None)
    process = Scripted()
    jobs = harness.build(process)
    with pytest.raises(RelationError) as caught:
        recover(jobs, "unconfirmed")
    assert (caught.value.status, caught.value.code) == (409, "review_not_confirmed") and caught.value.operation.next == "retry_review"
    with pytest.raises(RelationError) as caught:
        recover(jobs, "rejected")
    assert (caught.value.status, caught.value.code) == (409, "operation_not_recoverable")
    assert recover(jobs, "waiting").status == 200 and process.calls == []  # pending: coalesced, and no authority or child is needed to say so


def test_recover_needs_the_upstream_listed_now_but_a_settled_operation_does_not(harness):
    applied_allow(harness)
    (harness.root / "upstreams.json").write_text(json.dumps({"schemaVersion": relation_access.SCHEMA, "upstreams": []}))
    process = Scripted()
    with pytest.raises(RelationError) as caught:
        recover(harness.build(process))
    assert (caught.value.status, caught.value.code) == (403, "upstream_not_allowed") and process.calls == []
    assert harness.ledger.settle_operation("op-1", "superseded", None)
    assert recover(harness.build(process)).body.revalidation.state == "superseded" and process.calls == []


# ---- regression R2: the probe that settles a moved revalidation must be bound to the claim ------------------------------------------------
#
# When `revalidate` answers "the relation moved" the dispatcher reads the chain (`inspect`) to settle what happened. Relation candidate ids repeat
# across jobs that share an upstream, so a probe that is a perfectly valid chain of ANOTHER job (or of another input digest, or another upstream)
# can show the very verdict or reject the claimed operation is waiting for. Settlement is write-once and terminal, so such a probe must never
# settle: the operation stays an unsettled, recoverable failure (`runtime_binding_mismatch`), exactly as every other read of the pipeline is bound
# to the accepted job.

VERDICT_CHAIN = landed(verdict_event(3, "eligible", "revalidation"))
REJECT_CHAIN = landed(review_event(3, decision="reject", reviewer="beta", note="other"))


def probe_of(chain: Outcome, **changes: Any) -> Outcome:
    return Outcome("result", result={**chain.result, **changes}, exit_code=0)


def dispatch_once(harness, revalidate: Outcome, probe: Outcome | None = None):
    """One dispatcher step over an accepted allow whose revalidation is pending. Returns the scripted process and the operation row afterwards."""
    applied_allow(harness, outcome=None)
    process = Scripted(revalidate=[revalidate], inspect=[] if probe is None else [probe])
    dispatcher = RelationDispatcher(harness.ledger, process, RelationGate(), lambda record: None, lambda owner, job_id, digest: None)
    assert dispatcher.step() is True
    row = harness.ledger.operation("op-1")
    assert row is not None
    return process, row


def assert_an_unsettled_recoverable_failure(harness, row) -> None:
    assert row.settled is None and row.settled_eligibility is None and row.settled_at is None
    assert (row.reval_state, row.last_outcome, row.last_runtime_code) == ("idle", "runtime_error", "runtime_binding_mismatch")
    status = operation_status(row, "2026-10-13T00:00:00Z")
    assert (status.revalidation.state, status.revalidation.verdict, status.next) == ("failed", None, "recover")
    assert harness.ledger.enqueue_operation("op-1", 100) == "enqueued"  # a false terminal state would answer "coalesced": it could never run again


@pytest.mark.parametrize("moved", ["review_revision_conflict", "revalidation_not_requested"])
@pytest.mark.parametrize("chain", [VERDICT_CHAIN, REJECT_CHAIN], ids=["verdict", "reject"])
@pytest.mark.parametrize("changes", [{"jobId": "other-job"}, {"inputDigest": "e" * 64}, {"jobId": "other-job", "inputDigest": "e" * 64}],
                         ids=["other-job", "other-inputDigest", "both"])
def test_a_probe_of_another_job_or_input_digest_never_settles_a_moved_revalidation(harness, changes, chain, moved):
    _, row = dispatch_once(harness, Outcome("error", code=moved, exit_code=2), probe_of(chain, **changes))
    assert_an_unsettled_recoverable_failure(harness, row)


@pytest.mark.parametrize("chain", [VERDICT_CHAIN, REJECT_CHAIN], ids=["verdict", "reject"])
@pytest.mark.parametrize("upstream", [{"jobId": "other-s2", "inputDigest": UPSTREAM_DIGEST, "digest": "u" * 64},
                                      {"jobId": "s2-job", "inputDigest": "e" * 64, "digest": "u" * 64}], ids=["other-upstream-job", "other-upstream-digest"])
def test_a_probe_bound_to_another_upstream_never_settles_a_moved_revalidation(harness, upstream, chain):
    probe = probe_of(chain, binding={"schema": "x", "upstream": upstream})
    _, row = dispatch_once(harness, CONFLICT, probe)
    assert_an_unsettled_recoverable_failure(harness, row)


@pytest.mark.parametrize("chain,settled", [(VERDICT_CHAIN, ("verified", "eligible")), (REJECT_CHAIN, ("superseded", None))], ids=["verdict", "reject"])
def test_a_probe_bound_to_the_claim_settles_a_moved_revalidation(harness, chain, settled):
    _, row = dispatch_once(harness, CONFLICT, chain)
    assert (row.settled, row.settled_eligibility) == settled and row.settled_at
    assert (row.reval_state, row.last_outcome, row.last_runtime_code) == ("idle", "runtime_error", "review_revision_conflict")


def test_a_revalidate_result_of_another_job_never_settles(harness):
    foreign = probe_of(VERDICT_CHAIN, jobId="other-job")
    _, row = dispatch_once(harness, foreign)
    assert_an_unsettled_recoverable_failure(harness, row)
