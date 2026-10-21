"""The review decision tree of `RelationJobs`, without an installed pipeline: a scripted stand-in for the one door to the pipeline, a real service
ledger and the real configuration loader. What is proven here is every branch of "did my append land?": which outcome releases the reservation,
which keeps it, when the chain is read before anything is written, that an event is adopted only when every field of it is the operation's, that
an `allow` is the operator's FINAL approval (terminal, nothing dispatched, no call) and that an operation recorded under the earlier revalidation
contract is history that is never dispatched, resent or read as an approval.

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
from zoop_ai_service.jobs import Observation, request_digest
from zoop_ai_service.relation_jobs import RelationError, RelationJobs
from zoop_ai_service.relation_ledger import RelationLedger, Update
from zoop_ai_service.relation_review import marker, operation_status
from zoop_ai_service.relation_runtime import RelationGate
from zoop_ai_service.relation_wire import RelationReview
from zoop_ai_service.runtime import Outcome

JOB_DIGEST = "c" * 64  # the job's inputDigest = its `sourceVersion`: valid hex, and distinct from the upstream digest ("d" * 64) and the other values used here
BINDING = {"schema": "x", "upstream": {"jobId": "s2-job", "inputDigest": UPSTREAM_DIGEST, "digest": "u" * 64}}


class Scripted:
    """Stands in for `RelationProcess`: each command answers from its own queue, and every call is recorded in order. There is no `revalidate`:
    the service has no such command any more, so a test that needed one would fail on the missing attribute."""

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


def view(*events: dict[str, Any], state: str = "ready", revision: int | None = None, status: str = "hold", pending: bool = False, **extra: Any) -> Outcome:
    raw = {**payload(state, binding=BINDING, inputDigest=JOB_DIGEST, **extra), "relations": [{
        "relationCandidateId": RC, "eligibility": {"status": status, "revision": len(events) if revision is None else revision, "reviewPending": pending},
        "history": list(events)}]}
    return Outcome("result", result=raw, exit_code=0)


def withheld(code: str = "source_unauthorized") -> Outcome:
    return Outcome("result", result=payload("ready", binding=BINDING, inputDigest=JOB_DIGEST, delivery={"status": "withheld", "code": code}), exit_code=2)


def landed(*extra: dict[str, Any]) -> Outcome:
    """The chain after our allow was appended: the initial HOLD verdict, then the review carrying this operation's marker and the effect `approved`."""
    return view(verdict_event(1), review_event(2), *extra, status="eligible")


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


def test_a_review_the_pipeline_appended_is_adopted_from_the_chain_as_a_terminal_final_approval(harness):
    process = Scripted(review=[landed()])
    jobs = harness.build(process)
    reply = run(jobs)
    assert reply.status == 200 and reply.headers == {"Location": "/internal/v1/relation-jobs/job/reviews/op-1"}  # terminal: nothing to wait for
    status = reply.body
    assert (status.review.state, status.review.resulting_source_revision, status.revalidation.state, status.next, status.limitation) == (
        "applied", "2", "not_requested", "none", None)
    assert process.calls == ["review"] and harness.woke.count == 0
    # reviewer = the authenticated principal, note = the operation marker, revision = the expected SOURCE revision as an integer: nothing from the request body's text.
    assert process.review_args == ("job", RC, 1, "allow", "alpha", marker("op-1"))
    row = harness.ledger.operation("op-1")
    assert row is not None and (row.applied_event_at, row.reval_state, row.review_attempts, row.contract) == (
        "2026-10-13T00:00:02+00:00", None, 1, "final-approval")
    assert harness.ledger.claim_next() is None  # an approval schedules no dispatch of any kind


def test_a_reject_is_recorded_and_queues_nothing(harness):
    process = Scripted(review=[view(verdict_event(1), review_event(2, decision="reject"), revision=2, status="reject")])
    reply = run(harness.build(process), review=body(decision="reject"))
    assert reply.status == 200 and (reply.body.revalidation.state, reply.body.next) == ("not_requested", "none")
    assert harness.ledger.operation("op-1").reval_state is None and harness.ledger.claim_next() is None


def test_an_event_carrying_the_old_effect_is_never_adopted_as_the_approval(harness):
    old = view(verdict_event(1), review_event(2, effect="revalidation-requested"), pending=True)
    error = refused(harness.build(Scripted(review=[old])))
    assert (error.status, error.code) == (500, "runtime_binding_mismatch")
    assert harness.ledger.operation("op-1").review_state == "reserved"


@pytest.mark.parametrize("code,status,mapped", [
    ("review_revision_conflict", 409, "source_revision_conflict"), ("review_target_not_hold", 409, "review_target_not_hold"),
    ("review_call_in_flight", 409, "review_call_in_flight"), ("review_candidate_ineligible", 409, "review_candidate_ineligible"),
    ("job_cancelled", 409, "job_cancelled"), ("relation_candidate_not_found", 404, "relation_candidate_not_found"),
    ("source_unauthorized", 409, "upstream_unavailable"), ("upstream_changed", 409, "upstream_unavailable"),
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
    assert run(jobs).status == 200 and process.calls == ["review", "review"]  # the first attempt left nothing to read first


def test_a_busy_pipeline_keeps_the_reservation_and_the_retry_reads_the_chain_before_it_writes(harness):
    process = Scripted(review=[Outcome("error", code="relation_busy", exit_code=2)], inspect=[landed()])
    jobs = harness.build(process)
    error = refused(jobs)
    assert (error.status, error.code, error.headers["Retry-After"]) == (503, "runtime_busy", "2")
    assert harness.ledger.operation("op-1").review_attempts == 1 and harness.ledger.operation("op-1").review_state == "reserved"
    assert run(jobs).status == 200 and process.calls == ["review", "inspect"]  # an event found by the read is adopted, never appended again


def test_a_lost_reply_is_reconciled_from_the_chain_and_never_replays_the_approval(harness):
    """The approval was committed but the reply was lost (here: the child timed out): the exact marker/reviewer/revision/effect is found in the chain and
    adopted, and the same request again answers from the stored operation without a second child."""
    process = Scripted(review=[Outcome("timeout")], inspect=[landed()])
    jobs = harness.build(process)
    reply = run(jobs)
    assert reply.status == 200 and process.calls == ["review", "inspect"] and harness.ledger.operation("op-1").review_state == "applied"
    again = run(jobs)
    assert again.status == 200 and process.calls == ["review", "inspect"]


def test_a_retry_proves_absence_first_and_then_appends_exactly_once(harness):
    process = Scripted(review=[Outcome("timeout"), landed()], inspect=[view(verdict_event(1)), view(verdict_event(1))])
    jobs = harness.build(process)
    error = refused(jobs)
    assert (error.status, error.code) == (503, "review_unconfirmed")
    assert error.headers["Retry-After"] == "2" and harness.ledger.operation("op-1").review_state == "reserved"
    assert run(jobs).status == 200
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
    assert reply.status == 200 and (reply.body.review.state, reply.body.review.resulting_source_revision, reply.body.revalidation.state) == (
        "applied", "2", "not_requested")
    row = harness.ledger.operation("op-1")
    assert row is not None and (row.review_state, row.reval_state, row.review_attempts) == ("applied", None, 2)
    assert row.applied_event_at == "2026-10-13T00:00:02+00:00" and harness.woke.count == 0  # the key stays bound, nothing is queued


@pytest.mark.parametrize("post_refusal_chain,status,code", [
    (Outcome("error", code="relation_busy", exit_code=2), 503, "review_unconfirmed"),
    (Outcome("timeout"), 503, "review_unconfirmed"),
    (withheld(), 503, "review_unconfirmed"),
    (view(verdict_event(1), review_event(2, reviewer="beta"), status="eligible"), 500, "runtime_binding_mismatch"),   # the marker, but not our event
    (view(verdict_event(1)), 503, "review_unconfirmed"),   # a revision conflict with a chain still at the expected revision contradicts itself
])
def test_a_retry_conflict_with_an_unreadable_or_contradictory_chain_keeps_the_reservation(harness, post_refusal_chain, status, code):
    process, jobs = retried_after_a_lost_child(harness, post_refusal_chain=post_refusal_chain)
    error = refused(jobs)
    assert (error.status, error.code) == (status, code)
    row = harness.ledger.operation("op-1")
    assert row is not None and (row.review_state, row.review_attempts) == ("reserved", 2) and harness.woke.count == 0  # nothing proven, nothing released
    assert refused(jobs, review=body(decision="reject", revision="2")).code == "idempotency_conflict"  # the key is still bound to the original request


def test_a_retry_conflict_with_a_foreign_event_in_the_chain_releases_the_reservation_and_the_key_is_reusable(harness):
    foreign = view(verdict_event(1), review_event(2, reviewer="operator", note="operator note"), status="eligible")
    reused_chain = view(verdict_event(1), review_event(2, reviewer="operator", note="operator note"), review_event(3, decision="reject"), revision=3)
    process, jobs = retried_after_a_lost_child(harness, post_refusal_chain=foreign, then_review=(reused_chain,))
    error = refused(jobs)  # permanent absence is proven: the relation moved past the expected revision without our marker
    assert (error.status, error.code) == (409, "source_revision_conflict")
    assert harness.ledger.operation("op-1") is None and harness.woke.count == 0  # actually released: nothing bound
    reused = run(jobs, review=body(decision="reject", revision="2"))
    assert reused.status == 200 and (reused.body.decision, reused.body.review.state, reused.body.review.resulting_source_revision) == ("reject", "applied", "3")
    row = harness.ledger.operation("op-1")
    assert row is not None and (row.decision, row.expected_source_revision, row.review_attempts) == ("reject", 2, 1)  # a fresh operation, not the old one


@pytest.mark.parametrize("code", ["review_target_not_hold", "job_cancelled", "relation_candidate_not_found"])
def test_a_retry_refusal_that_is_a_pure_function_of_the_chain_releases_once_the_chain_shows_no_event_of_ours(harness, code):
    refusal = Outcome("error", code=code, exit_code=2)
    process, jobs = retried_after_a_lost_child(harness, post_refusal_chain=view(verdict_event(1)), refusal=refusal, then_review=(landed(),))
    error = refused(jobs)
    assert error.runtime_code == code and error.status in (404, 409)
    assert harness.ledger.operation("op-1") is None  # released: no child, orphaned or not, can append at a revision that refuses it
    assert run(jobs).status == 200  # and the key is reusable at the unchanged revision


@pytest.mark.parametrize("code", ["review_call_in_flight", "review_candidate_ineligible"])
def test_a_retry_refusal_that_depends_on_the_moment_never_releases_the_reservation(harness, code):
    """An in-flight call or a rights change can clear: the chain showing no event proves nothing about a later append, so the key stays bound."""
    process, jobs = retried_after_a_lost_child(harness, post_refusal_chain=view(verdict_event(1)), refusal=Outcome("error", code=code, exit_code=2))
    assert refused(jobs).code == "review_unconfirmed" and harness.ledger.operation("op-1") is not None


@pytest.mark.parametrize("outcome", [Outcome("timeout"), Outcome("abnormal", exit_code=75), Outcome("unavailable"),
                                     Outcome("error", code="persistence_failed", exit_code=2), withheld()])
def test_an_ambiguous_review_whose_event_is_in_the_chain_is_adopted(harness, outcome):
    process = Scripted(review=[outcome], inspect=[landed()])
    reply = run(harness.build(process))
    assert reply.status == 200 and process.calls == ["review", "inspect"] and harness.ledger.operation("op-1").review_state == "applied"


def test_an_ambiguous_review_whose_relation_moved_without_our_event_is_refused_and_released(harness):
    foreign = view(verdict_event(1), review_event(2, reviewer="operator", note="operator note"), status="eligible")
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
    process = Scripted(review=[Outcome("timeout")], inspect=[view(verdict_event(1), review_event(2, reviewer="beta"), status="eligible")])
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
    assert run(jobs).status == 200
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


def test_a_full_dispatch_queue_does_not_refuse_a_review_because_a_review_queues_nothing(harness):
    import zoop_ai_service.relation_jobs as module
    process = Scripted(review=[landed()])
    original, module.MAX_PENDING = module.MAX_PENDING, 0
    try:
        reply = run(harness.build(process))
    finally:
        module.MAX_PENDING = original
    assert reply.status == 200 and process.calls == ["review"]


# ---- operations recorded under the earlier revalidation contract: history only -----------------------------------------------------------

def legacy_operation(harness, key: str = "old", *, applied: bool = True, settled: str | None = None, state: str = "pending") -> None:
    """Exactly what a `-2` ledger held for an `allow`: the row, its revalidation columns and (optionally) its settlement, written with the contract
    the old code wrote. Raw SQL, because no current code path can create such a row any more."""
    db = harness.ledger._db
    columns = ("operation_id,owner,job_id,relation_candidate_id,decision,expected_source_version,expected_source_revision,request_digest,"
               "review_state,reserved_at,applied_at,applied_event_at,reval_state,reval_seq,settled,settled_eligibility,settled_at,contract")
    digest = request_digest({"jobId": "job", **body().wire()})  # the digest a replay of the same request computes
    if applied:
        values = (key, "alpha", "job", RC, "allow", JOB_DIGEST, 1, digest, "applied", "2026-10-13T00:00:00Z", "2026-10-13T00:00:01Z",
                  "2026-10-13T00:00:02+00:00", state, 50, settled, "eligible" if settled == "verified" else None,
                  "2026-10-13T00:00:09Z" if settled else None, "legacy-revalidation")
    else:
        values = (key, "alpha", "job", RC, "allow", JOB_DIGEST, 1, digest, "reserved", "2026-10-13T00:00:00Z", None, None, None, None, None, None,
                  None, "legacy-revalidation")
    db.execute(f"INSERT INTO relation_operations({columns}) VALUES ({','.join('?' * len(values))})", values)


def test_a_legacy_pending_revalidation_is_never_dispatched_and_reads_as_contract_changed(harness):
    legacy_operation(harness)
    assert harness.ledger.claim_next() is None and harness.ledger.interrupt_in_flight() == 0  # nothing to claim, nothing to interrupt
    process = Scripted()
    status = harness.build(process).operation("alpha", "job", "old", Observation()).body
    assert (status.limitation, status.revalidation.state, status.next, status.decision) == ("review_contract_changed", "contract_changed", "none", "allow")
    row = harness.ledger.operation("old")
    stored_seq = harness.ledger._db.execute("SELECT reval_seq FROM relation_operations WHERE operation_id='old'").fetchone()[0]   # a ledger column, not a row field
    assert row is not None and (row.reval_state, stored_seq, row.settled, row.contract) == ("pending", 50, None, "legacy-revalidation")  # preserved, not rewritten
    assert process.calls == []


def test_a_legacy_settlement_stays_readable_history_and_is_not_an_approval(harness):
    legacy_operation(harness, settled="verified", state="idle")
    status = operation_status(harness.ledger.operation("old"), "2026-10-13T00:00:00Z")
    assert (status.limitation, status.revalidation.state, status.revalidation.verdict, status.revalidation.resulting_source_revision) == (
        "review_contract_changed", "verified", "eligible", "3")


def test_replaying_a_confirmed_legacy_key_answers_the_stored_history_and_a_reserved_one_is_refused_without_a_child(harness):
    legacy_operation(harness, "confirmed", state="idle", settled="verified")
    legacy_operation(harness, "unconfirmed", applied=False)
    process = Scripted()
    jobs = harness.build(process)
    replay = run(jobs, "confirmed")
    assert replay.status == 200 and replay.body.limitation == "review_contract_changed" and replay.body.revalidation.state == "verified"
    error = refused(jobs, "unconfirmed")
    assert (error.status, error.code) == (409, "review_contract_changed") and error.operation.limitation == "review_contract_changed"
    assert error.operation.next == "none" and process.calls == []
    assert harness.ledger.operation("unconfirmed").review_state == "reserved"  # kept, never adopted, never resent


def test_a_new_decision_at_the_current_revision_is_allowed_next_to_a_legacy_one(harness):
    legacy_operation(harness)
    process = Scripted(review=[view(verdict_event(1), review_event(2, note=marker("new-key")), status="eligible")])   # the marker of the operation actually posted
    reply = run(harness.build(process), "new-key")
    assert reply.status == 200 and reply.body.limitation is None and reply.body.revalidation.state == "not_requested"
    assert harness.ledger.claim_next() is None


def test_the_service_has_no_revalidate_or_operation_recover_path_any_more():
    from zoop_ai_service import relation_dispatch, relation_runtime
    assert not hasattr(relation_runtime.RelationProcess, "revalidate") and not hasattr(RelationJobs, "recover_operation")
    assert not hasattr(relation_dispatch.RelationDispatcher, "_supervise_operation") and not hasattr(RelationLedger, "enqueue_operation")
