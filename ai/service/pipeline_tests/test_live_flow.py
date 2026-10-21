"""The LIVE capability over real HTTP: a real uvicorn service, the real installed `zoop-ai-extract` / `zoop-ai-relation` running their live path, and the
pipeline's OFFLINE provider simulator on loopback (a deterministic stand-in for the HTTP peer, not an AI). No external host is contacted, every key is a fake
and no test here makes a paid call.

What is proven: a live job is only ever started from an operator-pinned approval (a runtime identity the service re-reads at every use), the live child gets
the model settings and keys only when it may send, the automatic dispatch runs once under the pipeline's initial-only restriction and every later dispatch is
an explicit recover, an unanswered call is never resent, and a live S3 job needs its own pin in the upstream allowlist.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from extraction_support import JOB, STATUS_KEYS, extraction_processes, terminate_extraction, walk_keys  # noqa: F401
from live_support import LiveWorkspace, LiveWorldProcess, live_service
from relation_support import terminate_relation
from support import remove_tree

FIRST, SECOND, THIRD = "live-svc-1", "live-svc-2", "live-svc-3"
LIVE = {"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"}


@pytest.fixture(scope="module")
def live(tmp_path_factory: pytest.TempPathFactory):
    world = LiveWorldProcess(tmp_path_factory.mktemp("live-world"))
    yield world
    world.close()


@pytest.fixture
def start_live(tmp_path: Path, live: LiveWorldProcess):
    started = []

    def factory(*, chain: bool = False, hold: bool = False, workspace: LiveWorkspace | None = None):
        if workspace is None:
            workspace = LiveWorkspace(tmp_path / f"lws{len(started)}", live, chain=chain)
        service = live_service(workspace, hold=hold)
        started.append(service)
        return service

    yield factory
    for service in started:
        service.close()
    for workspace in {id(service.workspace): service.workspace for service in started}.values():
        terminate_extraction(workspace)
        if workspace.chain:
            terminate_relation(workspace)
    for workspace in {id(service.workspace): service.workspace for service in started}.values():
        remove_tree(workspace.root)


def clean(live: LiveWorldProcess, service, *texts: str) -> None:
    """No key, source text or private path in what a caller saw or in the service log."""
    corpus = [*texts, service.logs()]
    for value in [*service.workspace.private_strings(), *live.source_texts]:
        for text in corpus:
            assert value not in text, value


def test_a_live_job_runs_once_from_its_pinned_approval_and_is_delivered_with_exact_accounting(start_live, live):
    service = start_live()
    before = live.seen()["count"]
    submitted = service.esubmit(FIRST)
    assert submitted.status_code == 202, submitted.text
    assert submitted.json()["provenance"] == LIVE and submitted.json()["state"] == "queued"
    done = service.ewait(FIRST, {"ready"}, dispatch={"idle"}, timeout=180)
    assert set(done) == STATUS_KEYS and done["provenance"] == LIVE and done["next"] == "fetch_result" and done["failure"] is None
    assert done["dispatch"]["dispatchCount"] == 1 and done["dispatch"]["lastOutcome"] == "exited" and done["dispatch"]["lastRuntimeCode"] is None
    usage = done["usage"]
    assert (usage["providerCalls"], usage["receivedCalls"], usage["paidModelCalls"], usage["startedWithoutReceipt"], usage["unsentCalls"],
            usage["replayCalls"]) == (3, 3, 3, 0, 0, 0)
    assert (usage["inputTokens"], usage["outputTokens"]) == (3 * 1200, 3 * 300) and usage["estimatedUsd"] is not None  # the provider's own numbers, never a guess
    assert [stage["state"] for stage in done["stages"]] == ["complete"] * 3
    # What the simulated provider actually received: exactly one request per stage slot, authorized with the world's key, no model-send flag in the text.
    seen = live.seen()
    assert seen["count"] - before == 3 and seen["stages"][before:] == ["extract", "compare", "topic"]
    assert set(seen["authorizations"][before:]) == {"Bearer " + live.env["ZOOP_AI_API_KEY"]} and seen["allowModelSend"] is False
    envelope = service.eresult(FIRST).json()
    assert envelope["delivery"] == {"state": "available", "reason": None} and [r["state"] for r in envelope["receipts"]] == ["received"] * 3
    job = envelope["job"]
    assert job["eventCandidates"] and all(candidate["approved"] is False for candidate in job["eventCandidates"])  # candidates only: nothing is approved here
    clean(live, service, json.dumps(done), json.dumps(envelope))
    assert not {"binding", "fixtureHash", "requestDigest", "responseDigest", "recipient", "purpose"} & set(walk_keys(done))
    # Nothing continues, and nothing can send again for a finished job.
    time.sleep(2.0)
    assert live.seen()["count"] == seen["count"]
    assert service.esubmit(FIRST).status_code == 200  # the same request: the stored job
    assert service.erecover(FIRST).json()["error"]["code"] == "job_not_recoverable" and live.seen()["count"] == seen["count"]


def test_a_live_approval_is_re_read_at_every_use_and_a_moved_pin_sends_nothing(start_live, live):
    service = start_live(hold=False)
    workspace = service.workspace
    start = live.seen()["count"]
    # An approval pinned to ANOTHER runtime identity than the one the pipeline freezes the job under is refused before it is ever used.
    workspace.write_live_approvals({"alpha": [SECOND]}, identity="8" * 64)
    refused = service.esubmit(SECOND)
    # The input digest the service computed from the approved request AND the pinned identity is not the one the pipeline froze the job under.
    assert refused.status_code == 500 and refused.json()["error"]["code"] == "runtime_binding_mismatch", refused.text
    assert live.seen()["count"] == start
    # The honest approval works; then the operator moves the pin and removes the entry: delivery is withheld, a recover is refused, nothing is sent.
    workspace.write_live_approvals({"alpha": [THIRD]})
    assert service.esubmit(THIRD).status_code == 202
    service.ewait(THIRD, {"ready"}, dispatch={"idle"}, timeout=180)
    after = live.seen()["count"]
    assert after - start == 3
    workspace.write_live_approvals({"alpha": [THIRD]}, identity="7" * 64)
    withheld = service.eresult(THIRD).json()
    assert withheld["delivery"] == {"state": "withheld", "reason": "approval_changed"} and withheld["job"] is None
    recover = service.erecover(THIRD)
    assert recover.status_code == 409 and recover.json()["error"]["code"] == "approval_changed"
    workspace.write_live_approvals({"alpha": []})
    assert service.eresult(THIRD).json()["delivery"] == {"state": "withheld", "reason": "approval_revoked"}
    assert service.esubmit("live-not-listed", digest_="a" * 64).status_code == 403 and live.seen()["count"] == after
    workspace.write_live_approvals({"alpha": [THIRD]})
    assert service.eresult(THIRD).json()["delivery"]["state"] == "available"  # restored: delivered again, no call
    assert live.seen()["count"] == after


def test_an_unanswered_live_call_is_never_resent_and_stays_a_reconcile(start_live, live):
    service = start_live()
    start = live.seen()["count"]
    live.mode("silent")  # the provider reads the request and closes the connection without a reply
    try:
        assert service.esubmit(SECOND).status_code == 202
        stuck = service.ewait(SECOND, {"reconciling"}, dispatch={"idle"}, timeout=180)
    finally:
        live.mode("ok")
    assert stuck["failure"] == {"code": "live_response_unknown"} and stuck["resumeMode"] == "reconcile_only" and stuck["next"] == "operator_reconcile"
    assert stuck["usage"]["startedWithoutReceipt"] == 1 and stuck["usage"]["providerCalls"] == 1 and stuck["usage"]["estimatedUsd"] is None  # unknown, not zero
    assert live.seen()["count"] == start + 1
    time.sleep(2.5)
    assert live.seen()["count"] == start + 1 and service.ewait(SECOND)["dispatch"]["dispatchCount"] == 1  # nothing continues on its own
    again = service.erecover(SECOND)
    assert again.status_code == 409 and again.json()["error"]["code"] == "reconcile_required"  # an explicit recover cannot send it again either
    assert live.seen()["count"] == start + 1
    assert service.ecancel(SECOND).status_code == 200 and live.seen()["count"] == start + 1
    clean(live, service, again.text)


def test_a_live_approval_without_the_services_live_group_refuses_to_start(live, tmp_path):
    """The live approval alone is nothing: the service has to be switched on for live, and otherwise it refuses to start, naming the file and a reason
    code only (never a value)."""
    from extraction_support import ExtractionService
    workspace = LiveWorkspace(tmp_path / "off", live)
    off = ExtractionService(workspace, env=workspace.env(**{"ZOOP_AI_SERVICE_PIPELINE_LIVE": None}))
    try:
        off.start(wait=False)
        assert off.exited(30) != 0
        output = off.logs()
        assert "extraction_approval_live_unconfigured" in output and "ZOOP_AI_SERVICE_EXTRACTION_APPROVALS" in output
        assert live.env["ZOOP_AI_API_KEY"] not in output and live.env["TYPESAFE_API_KEY"] not in output
    finally:
        off.close()
        remove_tree(workspace.root)


def test_a_live_relation_job_needs_its_own_pin_and_a_matching_runtime(start_live, live):
    service = start_live(chain=True, hold=True)  # the S3 dispatcher is held: nothing here may reach the provider
    workspace = service.workspace
    assert service.esubmit(FIRST).status_code == 202
    done = service.ewait(FIRST, {"ready"}, dispatch={"idle"}, timeout=180)
    upstream = {"jobId": FIRST, "inputDigest": done["inputDigest"]}
    calls = live.seen()["count"]
    # Listed, but replay only (no pin): a live relation job is refused before anything is stored.
    workspace.write_live_upstreams([("alpha", FIRST, upstream["inputDigest"], None)])
    unpinned = service.rsubmit("rel-live-0", upstream=upstream, provenance=LIVE)
    assert unpinned.status_code == 403 and unpinned.json()["error"]["code"] == "live_not_approved"
    # Pinned to a runtime the pipeline does not freeze it under: the job exists in the pipeline but is never accepted, dispatched or delivered.
    workspace.write_live_upstreams([("alpha", FIRST, upstream["inputDigest"], "6" * 64)])
    mismatched = service.rsubmit("rel-live-1", upstream=upstream, provenance=LIVE)
    assert mismatched.status_code == 409 and mismatched.json()["error"]["code"] == "live_binding_mismatch", mismatched.text
    # Pinned to the world's runtime: accepted, truthfully live, queued behind the hold with no call.
    workspace.write_live_upstreams([("alpha", FIRST, upstream["inputDigest"], live.identity)])
    accepted = service.rsubmit("rel-live-2", upstream=upstream, provenance=LIVE)
    assert accepted.status_code == 202, accepted.text
    body = accepted.json()
    assert body["provenance"] == LIVE and body["state"] == "queued" and body["dispatch"]["state"] == "pending" and body["usage"]["providerCalls"] == 0
    time.sleep(1.5)
    assert live.seen()["count"] == calls  # nothing was sent: registering a job is not a call
    # The pin is re-read before every use: removing it withholds delivery and refuses a recover; the job can still be cancelled.
    workspace.write_live_upstreams([("alpha", FIRST, upstream["inputDigest"], None)])
    assert service.rrecover("rel-live-2").status_code in (200, 403)  # pending: coalesced, or refused for the moved pin; never a send
    cancelled = service.rcancel("rel-live-2")
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
    assert live.seen()["count"] == calls
    clean(live, service, accepted.text, unpinned.text, mismatched.text)


# ---- live S3 end to end: HTTP -> installed zoop-ai-relation -> the real LiveRuntime -> loopback OpenAI-chat + native Jev providers ---------------------
# The providers are the offline simulators of `build_live_world.py` (deterministic, grounded in the exact projection the runtime sent; not AIs). Nothing below
# is a CLI stub: the service starts the installed commands, which build the real requests, reserve the real budget and decode the real receipts.

def live_chain(service, live: LiveWorldProcess) -> dict[str, str]:
    """A real live S2 job through the service, then the operator's pinned upstream entry for it: the only way a live S3 job can exist."""
    assert service.esubmit(FIRST).status_code == 202
    done = service.ewait(FIRST, {"ready"}, dispatch={"idle"}, timeout=240)
    upstream = {"jobId": FIRST, "inputDigest": done["inputDigest"]}
    service.workspace.write_live_upstreams([("alpha", FIRST, upstream["inputDigest"], live.identity)])
    return upstream


def new_requests(live: LiveWorldProcess, before: dict) -> tuple[list[str], int]:
    """(chat stages, number of native Jev requests) the providers received since `before`, after checking their authorization and path."""
    after = live.seen()
    stages = after["stages"][before["count"]:]
    native = after["jev"]["count"] - before["jev"]["count"]
    assert set(after["authorizations"][before["count"]:]) <= {"Bearer " + live.env["ZOOP_AI_API_KEY"]}
    assert set(after["jev"]["authorizations"][before["jev"]["count"]:]) <= {"Bearer " + live.env["TYPESAFE_API_KEY"]}   # each key reaches only its own provider
    assert set(after["jev"]["paths"][before["jev"]["count"]:]) <= {"/v1/systemone"}
    return stages, native


def test_a_live_relation_job_runs_through_the_installed_pipeline_and_is_delivered_with_real_receipts(start_live, live):
    service = start_live(chain=True)
    upstream = live_chain(service, live)
    live.jev("ok")
    before = live.seen()
    accepted = service.rsubmit("rel-live-ok", upstream=upstream, provenance=LIVE)
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["provenance"] == LIVE and accepted.json()["usage"]["providerCalls"] == 0   # registering is not a call
    done = service.rwait("rel-live-ok", {"ready"}, dispatch={"idle"}, timeout=240)
    stages, native = new_requests(live, before)
    assert stages and stages[0] == "relation" and set(stages) <= {"relation", "impact"} and native >= 1, (stages, native)
    total = len(stages) + native
    usage = done["usage"]
    assert done["provenance"] == LIVE and done["failure"] is None and done["next"] == "fetch_result"
    assert (usage["providerCalls"], usage["modelCalls"], usage["startedWithoutReceipt"], usage["replayCalls"]) == (total, total, 0, 0), usage
    assert done["dispatch"]["dispatchCount"] == 1 and done["dispatch"]["lastOutcome"] == "exited" and done["dispatch"]["lastRuntimeCode"] is None
    envelope = service.rresult("rel-live-ok").json()
    assert envelope["delivery"] == {"state": "available", "reason": None}
    assert len(envelope["receipts"]) == total and all(receipt["state"] == "received" for receipt in envelope["receipts"])   # one stored, answered receipt per real request
    relations = envelope["job"]["relations"]
    assert relations and relations[0]["eligibility"]["status"] == "eligible"
    assert relations[0]["eligibility"]["approvalBasis"]["kind"] == "automatic-verifier" and relations[0]["eligibility"]["approvalBasis"]["reviewer"] is None
    clean(live, service, json.dumps(done))
    time.sleep(2.0)   # nothing continues on its own, and a finished job can never send again
    assert live.seen()["count"] == before["count"] + len(stages) and live.seen()["jev"]["count"] == before["jev"]["count"] + native
    assert service.rrecover("rel-live-ok").status_code == 409 and live.seen()["jev"]["count"] == before["jev"]["count"] + native


def test_a_valid_simulated_jev_hold_is_finally_approved_by_one_http_allow_with_no_further_provider_request(start_live, live):
    service = start_live(chain=True)
    upstream = live_chain(service, live)
    before = live.seen()
    live.jev("hold")   # a VALID verifier judgment: every claim is `insufficient`, so the relation is held for a human
    try:
        assert service.rsubmit("rel-live-hold", upstream=upstream, provenance=LIVE).status_code == 202
        done = service.rwait("rel-live-hold", {"ready"}, dispatch={"idle"}, timeout=240)
    finally:
        live.jev("ok")
    assert done["failure"] is None
    held = service.rresult("rel-live-hold").json()["job"]["relations"][0]
    assert held["eligibility"]["status"] == "hold" and held["eligibility"]["approvalBasis"] is None
    stages, native = new_requests(live, before)
    sent = live.seen()
    assert native >= 1
    # ONE human allow at the relation's current source revision is the final approval: no revalidation, no dispatch, no provider request.
    key = "final-allow-live-1"
    review = service.rreview(key, held["relationCandidateId"], decision="allow", revision=held["sourceRevision"], job_id="rel-live-hold")
    assert review.status_code == 200, review.text
    operation = review.json()
    assert operation["review"]["state"] == "applied" and operation["revalidation"]["state"] == "not_requested"
    assert operation["next"] == "none" and operation["limitation"] is None and operation["publication"] == {"state": "not_published"}
    approved = service.result_relation(held["relationCandidateId"], "rel-live-hold")
    assert approved["eligibility"]["status"] == "eligible" and approved["eligibility"]["approvalBasis"]["kind"] == "operator-final-approval"
    assert approved["eligibility"]["approvalBasis"]["reviewer"] == "alpha" and approved["impact"]["status"] == "not-applicable"
    time.sleep(2.0)
    final = live.seen()
    assert (final["count"], final["jev"]["count"]) == (sent["count"], sent["jev"]["count"]), "the final approval sent nothing to either provider"
    status = service.rstatus("rel-live-hold").json()
    assert status["state"] == "ready" and status["dispatch"]["dispatchCount"] == 1 and status["usage"]["providerCalls"] == done["usage"]["providerCalls"]
    replay = service.rreview(key, held["relationCandidateId"], decision="allow", revision=held["sourceRevision"], job_id="rel-live-hold")
    assert replay.status_code == 200 and replay.json()["operationId"] == key and live.seen()["jev"]["count"] == sent["jev"]["count"]   # idempotent, still no call
    clean(live, service, json.dumps(operation))


def test_an_unanswered_live_relation_call_is_never_resent_automatically_or_by_recover(start_live, live):
    service = start_live(chain=True)
    upstream = live_chain(service, live)
    before = live.seen()
    live.mode("silent")   # the chat provider reads the relation request and closes the connection without a reply
    try:
        assert service.rsubmit("rel-live-lost", upstream=upstream, provenance=LIVE).status_code == 202
        stuck = service.rwait("rel-live-lost", dispatch={"idle"}, timeout=240)
    finally:
        live.mode("ok")
    assert stuck["failure"] == {"code": "live_response_unknown"}, stuck
    assert stuck["state"] == "reconciling" and stuck["resumeMode"] == "reconcile_only" and stuck["next"] == "operator_reconcile", stuck
    assert stuck["usage"]["startedWithoutReceipt"] == 1 and stuck["usage"]["providerCalls"] == 1
    after = live.seen()
    assert after["count"] == before["count"] + 1 and after["stages"][-1] == "relation" and after["jev"]["count"] == before["jev"]["count"]
    time.sleep(2.5)
    assert live.seen()["count"] == after["count"] and service.rwait("rel-live-lost")["dispatch"]["dispatchCount"] == 1   # no automatic re-dispatch, no initial-only retry
    again = service.rrecover("rel-live-lost")
    assert again.status_code == 409 and again.json()["error"]["code"] == "reconcile_required" and live.seen()["count"] == after["count"]
    assert service.rcancel("rel-live-lost").status_code == 200 and live.seen()["count"] == after["count"]
    clean(live, service, again.text)


def test_a_pending_live_relation_dispatch_survives_a_restart_without_live_and_sends_nothing(start_live, live):
    """The real service and the real RelationProcess path (no stub): a live S3 job is accepted and left pending, the service restarts WITHOUT the live group
    (no gate, no key, no budget in its environment), and the claimed dispatch ends idle `live_unavailable` with no child; a recover is refused the same way."""
    from extraction_support import ExtractionService
    service = start_live(chain=True, hold=True)   # the S3 dispatcher is held: the job stays pending behind it
    workspace = service.workspace
    upstream = live_chain(service, live)
    before = live.seen()
    assert service.rsubmit("rel-live-restart", upstream=upstream, provenance=LIVE).status_code == 202
    time.sleep(1.5)
    assert service.rwait("rel-live-restart")["dispatch"]["state"] == "pending" and live.seen()["count"] == before["count"]
    service.close()
    workspace.write_live_approvals({"alpha": []})   # a live S2 approval cannot even be loaded by a service without the live group
    without_live = {name: None for name in (*live.env, "ZOOP_AI_SERVICE_PIPELINE_LIVE")}
    restarted = ExtractionService(workspace, env=workspace.env(**without_live)).start()
    try:
        status = restarted.rwait("rel-live-restart", dispatch={"idle"}, timeout=60)
        assert status["dispatch"]["lastOutcome"] == "runtime_error" and status["dispatch"]["lastRuntimeCode"] == "live_unavailable", status["dispatch"]
        assert status["state"] == "queued" and status["usage"]["providerCalls"] == 0 and status["provenance"] == LIVE
        recover = restarted.rrecover("rel-live-restart")
        assert recover.status_code == 409 and recover.json()["error"]["code"] == "live_unavailable", recover.text
        time.sleep(1.5)
        assert restarted.rwait("rel-live-restart")["dispatch"]["state"] == "idle"   # not stuck in flight, and nothing was re-claimed
        after = live.seen()
        assert (after["count"], after["jev"]["count"]) == (before["count"], before["jev"]["count"])
        for name in (live.env["ZOOP_AI_API_KEY"], live.env["TYPESAFE_API_KEY"]):
            assert name not in restarted.logs()
    finally:
        restarted.close()
