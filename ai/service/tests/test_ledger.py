"""The service ledger against real SQLite: durable owner intent, immutability, release rules and dispatch bookkeeping."""
from __future__ import annotations

import fcntl
import os
import sqlite3
from pathlib import Path

import pytest

from zoop_ai_service.config import ConfigError
from zoop_ai_service.ledger import ProcessLock, ServiceLedger, Update


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def ledger(tmp_path: Path):
    clock = Clock()
    state = tmp_path / "service"
    state.mkdir()
    instance = ServiceLedger(state, tmp_path / "worker", clock)
    instance.clock = clock
    yield instance
    instance.close()


def reserve(ledger, job_id="job-a", owner="alpha", digest="d1", kind="document-summary", mode="replay"):
    return ledger.reserve(job_id, owner, digest, kind, mode)


def test_reservation_binds_owner_and_digest_before_the_runtime_is_asked(ledger):
    row = reserve(ledger)
    assert (row.state, row.owner, row.request_digest, row.submit_attempts, row.input_digest) == ("reserved", "alpha", "d1", 0, None)
    other = reserve(ledger, owner="beta", digest="d2")
    assert other.owner == "alpha" and other.request_digest == "d1"  # the first claim stands; a later reserve cannot take it over
    assert ledger.dispatch("job-a") is None and ledger.pending_count() == 0
    assert ledger.begin_attempt("job-a") == 1 and ledger.begin_attempt("job-a") == 2


def test_accept_records_the_runtime_digest_and_creates_exactly_one_dispatch_row(ledger):
    reserve(ledger)
    assert ledger.accept("job-a", "alpha", "i" * 64, 10) == "accepted"
    row = ledger.job("job-a")
    assert row.state == "accepted" and row.input_digest == "i" * 64 and row.accepted_at
    dispatch = ledger.dispatch("job-a")
    assert (dispatch.state, dispatch.command, dispatch.dispatch_count) == ("pending", "run", 0)
    assert ledger.accept("job-a", "alpha", "i" * 64, 10) == "conflict" and ledger.accept("job-a", "beta", "x" * 64, 10) == "conflict"  # one transition only
    assert ledger.pending_count() == 1


def test_accept_by_another_owner_or_of_an_unknown_job_does_nothing(ledger):
    reserve(ledger)
    assert ledger.accept("job-a", "beta", "i" * 64, 10) == "conflict" and ledger.accept("missing", "alpha", "i" * 64, 10) == "conflict"
    assert ledger.job("job-a").state == "reserved" and ledger.dispatch("job-a") is None


def test_release_only_drops_a_first_attempt_reservation_of_the_same_request(ledger):
    reserve(ledger)
    ledger.begin_attempt("job-a")
    assert not ledger.release("job-a", "beta", "d1") and not ledger.release("job-a", "alpha", "other-digest")
    assert ledger.release("job-a", "alpha", "d1") and ledger.job("job-a") is None
    reserve(ledger, job_id="job-b")
    ledger.begin_attempt("job-b")
    ledger.begin_attempt("job-b")  # an earlier attempt may have registered the job: the claim must survive
    assert not ledger.release("job-b", "alpha", "d1") and ledger.job("job-b").owner == "alpha"
    reserve(ledger, job_id="job-c")
    assert not ledger.release("job-c", "alpha", "d1")  # never attempted: nothing definitive was learned
    reserve(ledger, job_id="job-d")
    ledger.begin_attempt("job-d")
    ledger.accept("job-d", "alpha", "i" * 64, 10)
    assert not ledger.release("job-d", "alpha", "d1") and ledger.job("job-d").state == "accepted"


def test_rows_are_immutable_in_the_database_itself(ledger):
    reserve(ledger)
    ledger.begin_attempt("job-a")
    ledger.accept("job-a", "alpha", "i" * 64, 10)
    db = ledger._db
    for statement in ("UPDATE analysis_jobs SET owner='beta'", "UPDATE analysis_jobs SET request_digest='x'",
                      "UPDATE analysis_jobs SET kind='briefing-outlook'", "UPDATE analysis_jobs SET state='reserved', input_digest=NULL, accepted_at=NULL",
                      "UPDATE analysis_jobs SET input_digest='y'", "DELETE FROM analysis_jobs", "DELETE FROM analysis_dispatch"):
        with pytest.raises(sqlite3.DatabaseError):
            db.execute(statement)
    reserve(ledger, job_id="job-b", owner="beta")
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE analysis_jobs SET owner='alpha' WHERE job_id='job-b'")
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("DELETE FROM analysis_jobs WHERE job_id='job-b'")  # attempts == 0: release requires the counted first attempt
    assert ledger.job("job-a").owner == "alpha" and ledger.job("job-b").owner == "beta"


def accepted(ledger, *job_ids):
    for job_id in job_ids:
        reserve(ledger, job_id=job_id)
        ledger.begin_attempt(job_id)
        assert ledger.accept(job_id, "alpha", "i" * 64, 10) == "accepted"


def test_claims_follow_submission_order_and_respect_not_before(ledger):
    accepted(ledger, "first", "second", "third")
    claim = ledger.claim_next()
    assert (claim.job_id, claim.command, claim.mode) == ("first", "run", "replay")
    assert ledger.dispatch("first").state == "in_flight" and ledger.dispatch("first").dispatch_count == 1
    assert ledger.finish("first", Update("pending", "run", "busy", None, 5.0, 0, 1))
    assert ledger.claim_next().job_id == "second"  # `first` is backing off
    assert ledger.claim_next().job_id == "third" and ledger.claim_next() is None
    ledger.clock.now += 4.9
    assert ledger.claim_next() is None
    ledger.clock.now += 0.2
    claim = ledger.claim_next()
    assert claim.job_id == "first" and claim.busy_count == 1 and ledger.dispatch("first").dispatch_count == 2


def test_finish_only_applies_to_an_in_flight_row(ledger):
    accepted(ledger, "job-a")
    assert not ledger.finish("job-a", Update("idle", None, "exited"))  # still pending: nothing was claimed
    ledger.claim_next()
    assert ledger.finish("job-a", Update("idle", None, "runtime_error", "replay_fixture_required"))
    row = ledger.dispatch("job-a")
    assert (row.state, row.last_outcome, row.last_runtime_code, row.command) == ("idle", "runtime_error", "replay_fixture_required", "run")
    assert not ledger.finish("job-a", Update("idle", None, "exited"))


def test_enqueue_is_explicit_and_coalesces_into_pending_or_in_flight(ledger):
    accepted(ledger, "job-a")
    assert ledger.enqueue("job-a", "resume", 10) == "coalesced"  # pending
    ledger.claim_next()
    assert ledger.enqueue("job-a", "resume", 10) == "coalesced"  # in flight
    ledger.finish("job-a", Update("idle", None, "exited", unknown_count=2, busy_count=3))
    assert ledger.enqueue("job-a", "resume", 10) == "enqueued"
    row = ledger.dispatch("job-a")
    assert (row.state, row.command, row.unknown_count, row.busy_count, row.not_before) == ("pending", "resume", 0, 0, None)
    assert ledger.enqueue("job-a", "run", 10) == "coalesced" and ledger.dispatch("job-a").command == "resume"


def test_cancel_ends_a_pending_dispatch_but_never_an_in_flight_one(ledger):
    accepted(ledger, "queued-job", "running-job")
    ledger.claim_next()  # queued-job is claimed first (lowest seq)
    ledger.cancel_pending("queued-job")
    assert ledger.dispatch("queued-job").state == "in_flight"
    ledger.cancel_pending("running-job")
    row = ledger.dispatch("running-job")
    assert (row.state, row.last_outcome) == ("idle", "cancelled") and ledger.claim_next() is None


def test_in_flight_rows_return_to_pending_at_service_start(ledger):
    accepted(ledger, "job-a", "job-b")
    ledger.claim_next()
    assert ledger.requeue_in_flight() == 1
    row = ledger.dispatch("job-a")
    assert (row.state, row.last_outcome, row.dispatch_count) == ("pending", "service_restarted", 1)
    assert ledger.dispatch("job-b").state == "pending"


def test_ledger_is_bound_to_one_worker_ledger_and_one_schema(tmp_path):
    state = tmp_path / "service"
    state.mkdir()
    ServiceLedger(state, tmp_path / "worker-a").close()
    ServiceLedger(state, tmp_path / "worker-a").close()
    with pytest.raises(ConfigError) as caught:
        ServiceLedger(state, tmp_path / "worker-b")
    assert (caught.value.field, caught.value.reason) == ("ZOOP_AI_WORKER_STATE_DIR", "worker_ledger_binding_mismatch")
    db = sqlite3.connect(state / "service.sqlite3")
    db.execute("UPDATE meta SET value='zoop-ai-service-ledger-0' WHERE key='schema'")
    db.commit()
    db.close()
    with pytest.raises(ConfigError) as caught:
        ServiceLedger(state, tmp_path / "worker-a")
    assert caught.value.reason == "ledger_schema_mismatch"


def test_ledger_files_are_private_and_hold_no_content_columns(ledger, tmp_path):
    assert oct((tmp_path / "service" / "service.sqlite3").stat().st_mode & 0o777) == "0o600"
    columns = {row[1] for table in ("analysis_jobs", "analysis_dispatch") for row in ledger._db.execute(f"PRAGMA table_info({table})")}
    assert columns.isdisjoint({"body", "request", "payload", "text", "input", "result", "artifact", "grant", "receipt", "content"})


def test_process_lock_is_exclusive_and_dies_with_the_process(tmp_path):
    first = ProcessLock(tmp_path)
    with pytest.raises(ConfigError) as caught:
        ProcessLock(tmp_path)
    assert caught.value.reason == "service_state_busy"
    assert not os.get_inheritable(first._fd)
    fcntl.flock(first._fd, fcntl.LOCK_UN)
    ProcessLock(tmp_path)


def test_the_cap_is_enforced_inside_accept_and_enqueue_and_counts_running_work(ledger):
    accepted(ledger, "job-a")
    reserve(ledger, job_id="job-b")
    ledger.begin_attempt("job-b")
    assert ledger.accept("job-b", "alpha", "i" * 64, 1) == "full"  # at the cap: the claim is kept, nothing is accepted
    assert ledger.job("job-b").state == "reserved" and ledger.dispatch("job-b") is None
    ledger.claim_next()
    assert ledger.active_count() == 1 and ledger.pending_count() == 0
    assert ledger.accept("job-b", "alpha", "i" * 64, 1) == "full"  # in-flight work keeps its slot
    ledger.finish("job-a", Update("idle", None, "exited"))
    assert ledger.accept("job-b", "alpha", "i" * 64, 1) == "accepted"
    assert ledger.enqueue("job-a", "run", 1) == "full" and ledger.dispatch("job-a").state == "idle"
    assert ledger.enqueue("job-b", "run", 1) == "coalesced"  # already pending: absorbed even at the cap
    ledger.claim_next()
    assert ledger.enqueue("job-a", "run", 1) == "full"  # job-b is running
    ledger.finish("job-b", Update("idle", None, "exited"))
    assert ledger.enqueue("job-a", "run", 1) == "enqueued"


@pytest.mark.parametrize("update", [Update("pending", "run", "busy", None, 1.0, 0, 1),
                                    Update("pending", "run", "transport_unknown", None, 1.0, 1, 0)])
def test_a_claimed_job_can_always_requeue_without_exceeding_the_cap(ledger, update):
    accepted(ledger, "job-a")
    ledger.claim_next()  # job-a is running; its slot is reserved
    reserve(ledger, job_id="job-b")
    ledger.begin_attempt("job-b")
    assert ledger.accept("job-b", "alpha", "i" * 64, 1) == "full"  # B cannot take A's slot
    assert ledger.finish("job-a", update)  # busy / unknown outcome: A goes back to pending, accepted intent is never dropped
    assert ledger.pending_count() == 1 and ledger.active_count() == 1 <= 1
    assert ledger.dispatch("job-a").state == "pending"


def test_service_restart_requeue_cannot_exceed_the_cap(ledger):
    accepted(ledger, "job-a")
    ledger.claim_next()
    reserve(ledger, job_id="job-b")
    ledger.begin_attempt("job-b")
    assert ledger.accept("job-b", "alpha", "i" * 64, 1) == "full"
    assert ledger.requeue_in_flight() == 1  # the process died with A in flight
    assert ledger.pending_count() == 1 and ledger.active_count() == 1
    assert ledger.accept("job-b", "alpha", "i" * 64, 1) == "full"  # and B still has no room
