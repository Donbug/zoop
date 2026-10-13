"""The real chain over ONE service process, ONE shared gate and ONE operator ledger: an S2 job is built through the S2 HTTP door, an operator explicitly lists
it as an S3 upstream, and an S3 job over it is built through the S3 HTTP door. Both pipelines are the installed commands; nothing is mocked.

Nothing in the S2 result authorizes S3 by itself: the S3 upstream allowlist is a separate server-owned file that only the operator writes, and removing an
S2 approval does not edit it (nor the other way round) - each family answers to its own authority and to the pipeline's source registry."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from extraction_support import JOB, PLAIN, extraction_processes
from relation_support import JOB as RELATION_JOB
from relation_support import relation_processes


def settled(call, *args, **kwargs):
    """An idempotent request retried while the shared gate is busy (`503 runtime_busy` is the documented, retryable answer)."""
    for _ in range(60):
        response = call(*args, **kwargs)
        if response.status_code != 503 or response.json()["error"]["code"] != "runtime_busy":
            return response
        time.sleep(1.0)
    return response


def test_an_s2_job_becomes_an_s3_upstream_only_by_an_explicit_operator_decision(start_extraction, world):
    service = start_extraction(chain=True)
    workspace = service.workspace
    assert service.esubmit().status_code == 202
    ready = service.ewait(states={"ready"}, dispatch={"idle"})
    assert ready["delivery"]["state"] == "available" and ready["inputDigest"] == world.upstream["inputDigest"]
    upstream = {"jobId": JOB, "inputDigest": ready["inputDigest"]}
    assert upstream == world.upstream

    # A ready, deliverable S2 job is NOT thereby an S3 upstream: the allowlist is empty and the S3 door refuses before a ledger row or a child.
    refused = service.rsubmit(upstream=upstream)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "upstream_not_allowed"
    assert not workspace.relation_state.exists() and not relation_processes(workspace)

    workspace.write_upstreams([("alpha", upstream["jobId"], upstream["inputDigest"])])   # the explicit, server-owned operator decision
    accepted = service.rsubmit(upstream=upstream)
    assert accepted.status_code == 202 and accepted.json()["upstream"] == upstream
    done = service.rwait(states={"ready"}, dispatch={"idle"})
    assert done["dispatch"]["dispatchCount"] == 1 and done["usage"]["replayCalls"] == world.replay_calls and done["usage"]["providerCalls"] == 0
    envelope = service.rresult().json()
    assert envelope["delivery"] == {"state": "available", "reason": None} and envelope["job"]["counts"] == world.counts
    assert {r["relationCandidateId"]: r["eligibility"]["status"] for r in envelope["job"]["relations"]} == world.relations
    assert all(r["approved"] is False for r in envelope["job"]["relations"])

    # The S2 result itself is unchanged by the S3 job built over it, and the S3 child read the S2 ledger the S2 child wrote.
    assert service.eresult().json()["delivery"]["state"] == "available"
    assert workspace.network_attempts() == ""
    service.close()
    assert not extraction_processes(workspace) and not relation_processes(workspace)


def test_the_two_families_answer_to_their_own_authority(start_extraction, world):
    service = start_extraction(chain=True)
    workspace = service.workspace
    service.esubmit()
    service.ewait(states={"ready"}, dispatch={"idle"})
    workspace.write_upstreams([("alpha", world.upstream["jobId"], world.upstream["inputDigest"])])
    service.rsubmit()
    service.rwait(states={"ready"}, dispatch={"idle"})
    both = (service.eresult().json()["delivery"]["state"], service.rresult().json()["delivery"]["state"])
    assert both == ("available", "available")

    workspace.write_entries([])                       # the S2 approval is removed: S2 content stops; the S3 allowlist is a separate file
    assert service.eresult().json()["delivery"] == {"state": "withheld", "reason": "approval_revoked"}
    assert service.rresult().json()["delivery"]["state"] == "available"
    workspace.refresh_approvals()
    workspace.write_upstreams([])                     # the S3 allowlist entry is removed: S3 content stops; S2 is unaffected
    assert service.rresult().json()["delivery"] == {"state": "withheld", "reason": "upstream_not_allowed"}
    assert service.eresult().json()["delivery"]["state"] == "available"
    workspace.write_upstreams([("alpha", world.upstream["jobId"], world.upstream["inputDigest"])])
    workspace.revoke_source(False)                    # the shared source registry: both pipelines withhold on their own current check
    assert service.eresult().json()["delivery"] == {"state": "withheld", "reason": "source_unauthorized"}
    assert service.rresult().json()["delivery"] == {"state": "withheld", "reason": "source_unauthorized"}
    workspace.revoke_source(True)
    assert service.eresult().json()["delivery"]["state"] == "available" and service.rresult().json()["delivery"]["state"] == "available"


def test_s2_and_s3_children_share_one_gate_and_never_collide_on_the_ledger(start_extraction, world):
    """An S3 job runs (reading the S2 ledger under a shared lock) while S2 jobs are being registered and executed (writing it under an exclusive one). The
    pipeline's locks do not wait, so a collision would surface as an `extraction_busy` refusal or a failed dispatch: the single gate prevents it."""
    service = start_extraction(chain=True, hold=True)
    workspace = service.workspace
    assert service.esubmit().status_code == 202
    workspace.go()
    service.ewait(states={"ready"}, dispatch={"idle"})
    workspace.write_upstreams([("alpha", world.upstream["jobId"], world.upstream["inputDigest"])])
    with ThreadPoolExecutor(3) as pool:
        relation = pool.submit(settled, service.rsubmit)
        plain = pool.submit(settled, service.esubmit, PLAIN)
        extra = pool.submit(settled, service.estatus)
        responses = [relation.result(), plain.result(), extra.result()]
    assert [r.status_code for r in responses[:2]] == [202, 202] and responses[2].status_code == 200
    s3 = service.rwait(states={"ready"}, dispatch={"idle"})
    s2 = service.ewait(PLAIN, states={"ready"}, dispatch={"idle"})
    for done in (s3, s2):
        assert done["dispatch"]["dispatchCount"] == 1 and done["dispatch"]["lastOutcome"] == "exited" and done["dispatch"]["lastRuntimeCode"] is None
    assert service.rresult().json()["delivery"]["state"] == "available" and service.eresult(PLAIN).json()["delivery"]["state"] == "available"
    assert RELATION_JOB == s3["jobId"]
