"""Interrupted work is never continued blindly, and a failed outcome write never strands a dispatch.

R1: after a restart, an abnormal child or a busy poll, the service may not run/resume a job whose generation receipt is stored but
whose verification stage was never reserved: that would send a new model request nobody asked for. Only an explicit recover may.
R2: if the ledger write that records a finished child fails once, the outcome is kept and only that write is retried; the worker
is never run again for it.
The "died between two stages" ledger state is produced with the real worker Runner against the real worker ledger; the provider
is the loopback request counter. No external credential is involved.
"""
from __future__ import annotations

import os
import time

import httpx
import pytest

from support import (Workspace, crash_between_stages, document_jobs, document_replay, live_job, reference, cli, wait_for)
from zoop_ai_service.config import load
from zoop_ai_service.jobs import Observation
from zoop_ai_service.ledger import Update
from zoop_ai_service.main import build_service
from zoop_ai_service.runtime import Outcome


def submit_then_crash_at_claim(start, workspace, env):
    """Accept a live job, then kill the service right after its dispatch is claimed and before any child starts."""
    crashing = start(workspace=workspace, env=env, launcher=True, launcher_env={"ZOOP_TEST_CRASH_AT": "after_claim"})
    job = live_job()
    try:
        crashing.submit(job)
    except httpx.TransportError:
        pass
    crashing.exited()
    return job


def test_restart_between_stages_never_sends_the_unstarted_verification_until_recover(start, provider, live):
    workspace, env = live()
    job = submit_then_crash_at_claim(start, workspace, env)
    crash_between_stages(workspace, env, provider, job["jobId"])
    assert provider.requests == ["document_summary"]
    service = start(workspace=workspace, env=env)
    held = service.wait_state(job["jobId"], {"running"}, dispatch={"idle"}, timeout=30)
    assert (held["dispatch"]["lastOutcome"], held["next"], held["unreceiptedAttempts"]) == ("needs_recover", "recover", 0)
    time.sleep(1.5)  # a wrongly automatic redispatch would have sent verification by now
    assert provider.requests == ["document_summary"]
    assert service.status(job["jobId"]).json()["dispatch"]["dispatchCount"] == 2  # the claim before the crash and the one held after
    assert service.recover(job["jobId"]).status_code == 202  # the explicit, authorized continuation
    final = service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"}, timeout=60)
    assert final["usage"]["providerAttempts"] == 2 and provider.requests == ["document_summary", "semantic_verification"]


@pytest.fixture
def inprocess(tmp_path, provider, live):
    """The real service components (real ledger, real worker CLI) with the dispatcher stepped by hand, so timing is deterministic."""
    workspace, env = live()
    built = build_service(load(workspace.env(**env)))
    built.workspace, built.env = workspace, env
    yield built
    built.ledger.close()
    os.close(built.lock._fd)


def test_abnormal_child_redispatch_does_not_send_a_later_stage(inprocess, provider):
    service, job = inprocess, live_job()
    assert service.jobs.submit("alpha", job["jobId"], job, Observation()).status == 202
    service.worker.run = lambda job_id, stop=None, **_: Outcome("abnormal")  # the child died: nothing reached the runtime
    assert service.dispatcher.step() and service.ledger.dispatch(job["jobId"]).last_outcome == "transport_unknown"
    crash_between_stages(service.workspace, service.env, provider, job["jobId"])  # in truth it died between the two stages
    del service.worker.run
    time.sleep(1.2)
    assert service.dispatcher.step()
    row = service.ledger.dispatch(job["jobId"])
    assert (row.state, row.last_outcome) == ("idle", "needs_recover") and provider.requests == ["document_summary"]
    assert service.jobs.recover("alpha", job["jobId"], Observation()).status == 202
    assert service.dispatcher.step()
    assert provider.requests == ["document_summary", "semantic_verification"]
    assert service.jobs.status("alpha", job["jobId"], Observation()).body.state == "ready"


def test_a_never_started_job_is_still_run_after_an_interruption(inprocess, provider):
    service, job = inprocess, live_job()
    service.jobs.submit("alpha", job["jobId"], job, Observation())
    service.ledger.claim_next()
    assert service.ledger.requeue_in_flight() == 1  # a restart left it claimed, no child ever ran: nothing was sent yet
    assert service.dispatcher.step()
    assert provider.requests == ["document_summary", "semantic_verification"]
    assert service.ledger.dispatch(job["jobId"]).state == "idle"


def test_a_failed_outcome_write_is_retried_alone_and_the_worker_is_not_run_again(start):
    service = start(replay=document_replay(), launcher=True, launcher_env={"ZOOP_TEST_CRASH_AT": "finish_fails_once"})
    job = document_jobs()[0]
    assert service.submit(job).status_code == 202
    final = service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"}, timeout=30)
    assert final["dispatch"]["dispatchCount"] == 1 and final["usage"]["replayCalls"] == 2 and final["dispatch"]["lastOutcome"] == "exited"
    assert '"event":"dispatcher_error"' in service.logs("out")
    second = document_jobs()[1]
    service.submit(second)
    assert service.wait_state(second["jobId"], {"ready"}, dispatch={"idle"})["dispatch"]["dispatchCount"] == 1  # supervision carried on


def test_a_receipt_committed_after_any_earlier_look_still_cannot_get_a_new_stage_sent(inprocess, provider):
    """The deterministic interleaving: the service has decided to redispatch automatically; after that decision and before the
    runtime starts, an orphan commits the generation receipt and dies before reserving verification. The runtime itself, under
    its job lock, must refuse to send the unsent stage. The unrestricted run (what the old get-then-run guard allowed) would."""
    service = inprocess
    racing, control = live_job(job_id="live-racing"), live_job(document_jobs()[1], job_id="live-control")
    for job in (racing, control):
        assert service.jobs.submit("alpha", job["jobId"], job, Observation()).status == 202
    # The control job shows the hazard is real: the same state with an unrestricted run sends verification.
    crash_between_stages(service.workspace, service.env, provider, control["jobId"])
    assert provider.requests == ["document_sentiment"]
    assert service.worker.run(control["jobId"]).kind == "result"
    assert provider.requests == ["document_sentiment", "semantic_verification"]
    # The racing job: an automatic (non-fresh) dispatch whose runtime state changes after the service committed to redispatching.
    claimed = service.ledger.claim_next()
    assert claimed.job_id == racing["jobId"]
    service.ledger.finish(racing["jobId"], Update("pending", "run", "busy", None, 0.0, 0, 1))
    real_run = service.worker.run

    def raced(job_id, stop=None, *, initial_only=False):
        crash_between_stages(service.workspace, service.env, provider, job_id)  # the orphan's receipt lands now
        return real_run(job_id, stop, initial_only=initial_only)

    service.worker.run = raced
    assert service.dispatcher.step()
    row = service.ledger.dispatch(racing["jobId"])
    assert (row.state, row.last_outcome) == ("idle", "needs_recover")
    assert provider.requests == ["document_sentiment", "semantic_verification", "document_summary"]  # no verification for it
    del service.worker.run
    assert service.jobs.recover("alpha", racing["jobId"], Observation()).status == 202  # explicit continuation is ordinary
    while service.ledger.active_count():  # the control job is queued ahead of the recovered one
        assert service.dispatcher.step()
    assert provider.requests[-1] == "semantic_verification"
    assert service.jobs.status("alpha", racing["jobId"], Observation()).body.state == "ready"
