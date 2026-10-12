"""Backpressure refusals happen before any reservation or runtime registration, using the real components in this process.

The dispatcher is deliberately not started, so accepted jobs stay pending. The real installed `zoop-ai` still performs every submit.
"""
from __future__ import annotations

import os
import threading

import pytest

from support import Workspace, cli, document_jobs, document_replay, reference
from zoop_ai_service import jobs
from zoop_ai_service.config import load
from zoop_ai_service.jobs import ApiError, Observation
from zoop_ai_service.main import build_service


@pytest.fixture
def service(tmp_path):
    workspace = Workspace(tmp_path / "ws", replay=document_replay())
    built = build_service(load(workspace.env()))
    built.workspace = workspace
    yield built
    built.ledger.close()
    os.close(built.lock._fd)


def refused(call, *args) -> ApiError:
    with pytest.raises(ApiError) as caught:
        call(*args, Observation())
    return caught.value


def test_a_full_dispatch_queue_refuses_before_reserving_or_registering(service, monkeypatch):
    monkeypatch.setattr(jobs, "MAX_PENDING", 1)
    first, second = document_jobs()[:2]
    accepted = service.jobs.submit("alpha", first["jobId"], first, Observation())
    assert accepted.status == 202 and service.ledger.pending_count() == 1
    error = refused(service.jobs.submit, "alpha", second["jobId"], second)
    assert (error.status, error.code, error.headers["Retry-After"]) == (503, "queue_full", "30")
    assert error.envelope("req-1").error.retryable is True
    assert service.ledger.job(second["jobId"]) is None  # no owner claim was made for a refused request
    assert cli(service.workspace, "get", reference(second["jobId"]))[0] == 2  # and nothing was registered in the runtime


def test_all_cli_slots_busy_refuses_without_side_effects(service):
    first, second = document_jobs()[:2]
    assert service.jobs.submit("alpha", first["jobId"], first, Observation()).status == 202
    held = [service.jobs._slots.acquire() for _ in range(jobs.CLI_SLOTS)]
    try:
        for call, args in ((service.jobs.submit, ("alpha", second["jobId"], second)), (service.jobs.status, ("alpha", first["jobId"])),
                           (service.jobs.result, ("alpha", first["jobId"])), (service.jobs.cancel, ("alpha", first["jobId"])),
                           (service.jobs.recover, ("alpha", first["jobId"]))):
            error = refused(call, *args)
            assert (error.status, error.code, error.headers["Retry-After"]) == (503, "service_busy", "1")
        assert service.ledger.job(second["jobId"]) is None
        assert service.ledger.dispatch(first["jobId"]).state == "pending"  # recover/cancel did not touch the dispatch row
    finally:
        for _ in held:
            service.jobs._slots.release()
    assert service.jobs.status("alpha", first["jobId"], Observation()).status == 200


def test_the_service_never_serves_a_job_it_has_not_accepted(service):
    first = document_jobs()[0]
    service.ledger.reserve(first["jobId"], "alpha", "digest", first["kind"], first["mode"])
    for call in (service.jobs.status, service.jobs.result, service.jobs.cancel, service.jobs.recover):
        error = refused(call, "alpha", first["jobId"])
        assert (error.status, error.code) == (404, "job_not_found")


# ---- atomic pending-queue cap across distinct jobs and explicit recovery ----

def blocked_service(tmp_path):
    """A service whose replay fixture is unusable: every dispatched job ends idle/`runtime_error`, i.e. registered and recoverable."""
    broken = document_replay()
    broken["recordingKind"] = "provider"
    workspace = Workspace(tmp_path / "blocked", replay=broken)
    built = build_service(load(workspace.env()))
    built.workspace = workspace
    return built


def run_concurrently(calls):
    from concurrent.futures import ThreadPoolExecutor
    barrier = threading.Barrier(len(calls))

    def go(call):
        barrier.wait()
        try:
            return call()
        except ApiError as error:
            return error

    with ThreadPoolExecutor(len(calls)) as pool:
        return list(pool.map(go, calls))


def test_concurrent_distinct_submissions_cannot_exceed_the_pending_cap(service, monkeypatch):
    monkeypatch.setattr(jobs, "MAX_PENDING", 1)
    cli(service.workspace, "get", reference("warm-up"))  # create the runtime ledger first: its one-time creation is not under test
    batch = document_jobs()
    results = run_concurrently([lambda j=j: service.jobs.submit("alpha", j["jobId"], j, Observation()) for j in batch])
    accepted = [r for r in results if not isinstance(r, ApiError)]
    refusals = [r for r in results if isinstance(r, ApiError)]
    assert len(accepted) == 1 and accepted[0].status == 202 and service.ledger.pending_count() == 1
    assert {(r.status, r.code) for r in refusals} == {(503, "queue_full")} and len(refusals) == len(batch) - 1
    # A refused job's owner claim is kept (the runtime may hold it) and its retry completes once there is room.
    loser = next(j for j, r in zip(batch, results) if isinstance(r, ApiError))
    assert service.ledger.job(loser["jobId"]).state == "reserved"
    assert refused(service.jobs.submit, "alpha", loser["jobId"], loser).code == "queue_full"
    assert service.dispatcher.step()  # the accepted job is claimed, so pending drops to zero
    assert service.jobs.submit("alpha", loser["jobId"], loser, Observation()).status == 202
    assert service.ledger.job(loser["jobId"]).state == "accepted" and service.ledger.pending_count() == 1


def test_recovery_obeys_the_same_cap_and_coalesced_requests_cost_nothing(tmp_path, monkeypatch):
    service = blocked_service(tmp_path)
    try:
        first, second, third = document_jobs()[:3]
        for job in (first, second):
            assert service.jobs.submit("alpha", job["jobId"], job, Observation()).status == 202
        for _ in range(2):
            assert service.dispatcher.step()
        for job in (first, second):
            assert service.ledger.dispatch(job["jobId"]).state == "idle"  # registered, blocked, recoverable
        monkeypatch.setattr(jobs, "MAX_PENDING", 1)
        assert service.jobs.submit("alpha", third["jobId"], third, Observation()).status == 202  # pending is now at the cap
        full = refused(service.jobs.recover, "alpha", first["jobId"])
        assert (full.status, full.code, full.headers["Retry-After"]) == (503, "queue_full", "30")
        assert service.ledger.dispatch(first["jobId"]).state == "idle"  # nothing was enqueued
        coalesced = service.jobs.recover("alpha", third["jobId"], Observation())  # already pending: absorbed, never rejected
        assert coalesced.status == 200 and service.ledger.pending_count() == 1
        assert service.dispatcher.step() and service.ledger.pending_count() == 0
        results = run_concurrently([lambda j=j: service.jobs.recover("alpha", j["jobId"], Observation()) for j in (first, second)])
        assert sorted(r.status if not isinstance(r, ApiError) else r.status for r in results) == [202, 503]
        assert service.ledger.pending_count() == 1
        again = [r for r in results if not isinstance(r, ApiError)][0]
        assert again.status == 202
        enqueued = first if service.ledger.dispatch(first["jobId"]).state == "pending" else second
        assert service.jobs.recover("alpha", enqueued["jobId"], Observation()).status == 200  # coalesced into the pending one
        assert service.ledger.pending_count() == 1
    finally:
        service.ledger.close()
        os.close(service.lock._fd)
