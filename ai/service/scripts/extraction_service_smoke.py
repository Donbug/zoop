#!/usr/bin/env python3
"""Real-process smoke for the S2 extraction-job routes and the S2 -> S3 chain: real uvicorn on 127.0.0.1, the real installed `zoop-ai-extract` and
`zoop-ai-relation`, a fresh synthetic operator world (actual ingestion + authored fixtures) and fresh private service state. No model, no network.

Parts: submit -> status -> result byte-identical in identity to the pipeline's own `inspect` (the service-built job has the operator job's input digest);
the caller can send only a reference to a server-approved request (spoofed snapshot/catalogue/path/fixture bodies are 422, an unapproved digest is 403, a
job an operator registered is never adopted); ownership and idempotency; approval and source revocation withhold content; producer/topic fixture rotation
and a rotation between the check and the child's read fail closed; a child killed after reserving a call is never resent and ends `reconciling`; a stored
receipt is reused after an explicit recover; a crash after the pipeline registered the job and before the service acknowledged it loses and duplicates
nothing; the initial dispatch runs once across a service kill/restart; a busy ledger is retried only before any effect and a stopped job only by an explicit
recover; and the CHAIN: an S2 job built over HTTP becomes an S3 upstream only when the operator lists it, then the S3 job is built over HTTP on the same
service and the same gate. The operator's ingestion directory is proven byte-identical afterwards.
Needs the installed pipeline (`make pipeline-install`) and the service environment: `make service-pipeline-smoke`.
"""
from __future__ import annotations

import fcntl
import sys
import tempfile
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline_tests"))

from extraction_support import (CONTENT_PRIVATE, CRASH_AFTER_EXTRACT_STAGE, CRASH_AFTER_FIRST_RECEIPT, CRASH_UNKNOWN, JOB, PLAIN, PRIVATE_KEYS, ExtractionService,  # noqa: E402
                                ExtractionWorkspace, dispatch_row, inspect_direct, ledger_rows, make_service, operator_submit, terminate_extraction, walk_keys)
from relation_support import World, build_world, terminate_relation, tree  # noqa: E402
from support import remove_tree  # noqa: E402


class SmokeFailure(Exception):
    pass


def check(condition: object, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def launch(root: Path, name: str, world: World, *, wrapper: str | None = None, hold: bool = False, crash: str | None = None, chain: bool = False,
           **kwargs) -> ExtractionService:
    workspace = ExtractionWorkspace(root / name, world, chain=chain, **kwargs)
    if wrapper is not None:
        workspace.write_wrapper(wrapper)
    env = {"ZOOP_TEST_EXTRACTION_HOLD_FILE": str(workspace.root / "extract-go")} if hold else {}
    if crash is not None:
        env["ZOOP_TEST_EXTRACTION_CRASH_AT"] = crash
    return make_service(workspace, env=workspace.env(), launcher=bool(env), launcher_env=env).start()


def flow_part(root: Path, world: World, started: list[ExtractionService]) -> str:
    service = launch(root, "flow", world)
    started.append(service)
    workspace = service.workspace
    accepted = service.esubmit()
    check(accepted.status_code == 202 and accepted.json()["inputDigest"] == world.upstream["inputDigest"], "accepted; the input digest equals the operator job's")
    done = service.ewait(states={"ready"}, dispatch={"idle"})
    check(done["usage"] == {"replayCalls": world.s2_replay_calls, "startedWithoutReceipt": 0, "providerCalls": 0, "paidModelCalls": 0, "receivedCalls": 0,
                            "unsentCalls": 0, "inputTokens": None, "outputTokens": None, "reasoningTokens": None, "estimatedUsd": None, "chargedUsd": None},
          "replay accounting")
    check(done["dispatch"]["dispatchCount"] == 1 and done["next"] == "fetch_result", "one dispatch, then fetch_result")
    envelope = service.eresult().json()
    job = envelope["job"]
    check(envelope["delivery"]["state"] == "available" and job["counts"] == world.s2_counts, "result counts equal the authored reference")
    check(not set(walk_keys(envelope)) & CONTENT_PRIVATE and not set(walk_keys(done)) & PRIVATE_KEYS, "no private pipeline field is relayed")
    check(all(e["approved"] is False for e in job["eventCandidates"]) and job["topicCandidates"], "candidates, none approved, topic present")
    quotes = [c["quote"] for e in job["eventCandidates"] for c in e["citations"]]
    service.close()
    code, direct = inspect_direct(workspace)
    check(code == 0 and direct["inputDigest"] == job["inputDigest"] and direct["usage"]["providerCalls"] == 0, "result identity equals the pipeline's own inspect")
    service = make_service(workspace).start()
    started.append(service)
    check(service.esubmit().status_code == 200, "an exact repeat is 200")
    check(service.esubmit(PLAIN, digest_="0" * 64).status_code == 403, "an unapproved digest is 403")
    check(service.esubmit(JOB, digest_=workspace.approved_digest(PLAIN)).status_code == 409, "same key, another request is 409")
    spoof = service.request("POST", "/internal/v1/extraction-jobs", as_="alpha", body=workspace.requests[JOB], key=JOB)
    check(spoof.status_code == 422, "the approved Submit itself is not accepted from a caller")
    check(service.request("POST", "/internal/v1/extraction-jobs", as_="alpha", key="hostile", body={
        "schemaVersion": "zoop-extraction-s2-2", "jobId": "hostile", "approvedRequestDigest": workspace.approved_digest(), "replay": "/etc/passwd"}).status_code == 422,
          "a request cannot name a path")
    check(service.estatus(as_="beta").status_code == 404 and service.eresult(as_="beta").status_code == 404 and service.esubmit(as_="beta").status_code == 403,
          "another principal gets 404 on reads and the same 403 as before the job existed on submit (beta is not approved for it)")
    check(service.ecancel().status_code == 409 and service.erecover().status_code == 409, "a ready job is terminal")
    workspace.write_entries([])
    check(service.eresult().json()["delivery"] == {"state": "withheld", "reason": "approval_revoked"} and service.eresult().json()["job"] is None,
          "a removed approval withholds")
    check(service.erecover().status_code == 403, "a removed approval refuses a recovery")
    workspace.refresh_approvals()
    workspace.revoke_source(False)
    check(service.eresult().json()["delivery"] == {"state": "withheld", "reason": "source_unauthorized"}, "a revoked source withholds")
    workspace.revoke_source(True)
    topic = workspace.s2_topic.read_bytes()
    workspace.rotate_topic()
    check(service.eresult().json()["delivery"] == {"state": "withheld", "reason": "fixture_changed"}, "a rotated fixture withholds")
    workspace.s2_topic.write_bytes(topic)
    workspace.s2_topic.unlink()
    check(service.eresult().json()["delivery"] == {"state": "withheld", "reason": "fixture_unavailable"}, "a missing fixture withholds")
    workspace.s2_topic.write_bytes(topic)
    check(service.eresult().json()["delivery"]["state"] == "available", "delivery returns with the pinned bytes")
    log = service.logs()
    check(not any(private in log for private in workspace.private_strings()) and not any(quote in log for quote in quotes), "logs hold no private value or cited text")
    check(workspace.network_attempts() == "", "no network attempt was made")
    return f"flow: status=passed, eventCandidates={len(job['eventCandidates'])}, replayCalls={done['usage']['replayCalls']}, providerCalls=0, networkAttempts=0"


def adoption_part(root: Path, world: World, started: list[ExtractionService]) -> str:
    service = launch(root, "adopt", world, hold=True)
    started.append(service)
    workspace = service.workspace
    code, registered = operator_submit(workspace, workspace.requests[PLAIN])
    check(code == 0 and registered["state"] == "queued", "an operator registered a job")
    refused = service.esubmit(PLAIN)
    check(refused.status_code == 409 and refused.json()["error"]["code"] == "job_id_unavailable", "the operator's job is not adopted")
    check(service.estatus(PLAIN).status_code == 404, "and is not readable through the service")
    service.stop()
    check(ledger_rows(workspace, "SELECT COUNT(*) FROM extraction_jobs") == [(0,)], "the reservation was released")
    return "adoption: status=passed, adopted=0"


def rotation_part(root: Path, world: World, started: list[ExtractionService]) -> str:
    service = launch(root, "toctou", world, hold=True)
    started.append(service)
    workspace = service.workspace
    original = workspace.s2_topic.read_bytes()
    workspace.write_wrapper(f"open({str(workspace.s2_topic)!r}, 'ab').write(b'\\n')", "resume")
    check(service.esubmit().status_code == 202, "accepted")
    workspace.arm()
    workspace.go()
    seen = service.ewait(dispatch={"idle"})
    check(seen["dispatch"]["lastRuntimeCode"] == "fixture_changed", "a rotation between the check and the child's read is detected after the fact")
    workspace.s2_topic.write_bytes(original)
    check(service.eresult().json()["delivery"] == {"state": "withheld", "reason": "fixture_changed"}, "the foreign receipt stays withheld")
    pre = launch(root, "predispatch", world, hold=True)
    started.append(pre)
    check(pre.esubmit().status_code == 202, "accepted while held")
    pre.workspace.rotate_topic()
    pre.workspace.go()
    refused = pre.ewait(dispatch={"idle"})
    check(refused["dispatch"]["lastRuntimeCode"] == "fixture_changed" and refused["usage"]["replayCalls"] == 0, "no child starts over rotated fixtures")
    return "rotation: status=passed, childStartedOverRotatedFixture=0"


def ambiguity_part(root: Path, world: World, started: list[ExtractionService]) -> list[str]:
    service = launch(root, "unknown", world, wrapper=CRASH_UNKNOWN)
    started.append(service)
    service.workspace.arm()
    check(service.esubmit().status_code == 202, "accepted")
    ambiguous = service.ewait(dispatch={"idle"})
    check(ambiguous["dispatch"]["lastOutcome"] == "transport_unknown" and ambiguous["usage"]["startedWithoutReceipt"] == 1, "a dead child is ambiguous")
    time.sleep(2.5)
    check(service.ewait()["dispatch"]["dispatchCount"] == 1, "nothing is run again automatically")
    check(service.erecover().status_code == 202, "explicit recover")
    reconciling = service.ewait(states={"reconciling"}, dispatch={"idle"})
    check(reconciling["usage"]["replayCalls"] == 0 and reconciling["next"] == "operator_reconcile", "an unanswered call is never resent")
    check(service.erecover().status_code == 409, "reconciling is refused")
    stage = launch(root, "stage", world, wrapper=CRASH_AFTER_EXTRACT_STAGE)
    started.append(stage)
    stage.workspace.arm()
    stage.esubmit()
    interrupted = stage.ewait(dispatch={"idle"})
    check(interrupted["usage"]["replayCalls"] == 1 and interrupted["next"] == "recover", "a stored stage waits for recover")
    stage.erecover()
    done = stage.ewait(states={"ready"}, dispatch={"idle"})
    receipts = stage.eresult().json()["receipts"]
    check(done["usage"]["replayCalls"] == world.s2_replay_calls and sum(r["stage"] == "extract" for r in receipts) == 1, "the stored receipt was reused, not called again")
    receipt = launch(root, "receipt", world, wrapper=CRASH_AFTER_FIRST_RECEIPT)
    started.append(receipt)
    receipt.workspace.arm()
    receipt.esubmit()
    saved = receipt.ewait(dispatch={"idle"})
    check(saved["usage"]["replayCalls"] == 1 and saved["stages"][0]["state"] == "pending", "a receipt saved before its stage completed")
    receipt.erecover()
    finished = receipt.ewait(states={"ready"}, dispatch={"idle"})
    again = receipt.eresult().json()["receipts"]
    check(finished["usage"]["replayCalls"] == world.s2_replay_calls and sum(r["stage"] == "extract" for r in again) == 1, "the saved response was reused, no extra call")
    return ["ambiguity: status=passed, resent=0", "recover: status=passed, extractCalls=1", "saved receipt before stage: status=passed, extraCalls=0"]


def restart_part(root: Path, world: World, started: list[ExtractionService]) -> list[str]:
    service = launch(root, "restart", world, hold=True)
    started.append(service)
    check(service.esubmit().status_code == 202, "accepted while held")
    service.kill()
    again = make_service(service.workspace).start()
    started.append(again)
    done = again.ewait(states={"ready"}, dispatch={"idle"})
    check(done["dispatch"]["dispatchCount"] == 1, "the initial dispatch ran once after the restart")
    again.kill()
    crashing = launch(root, "registered", world, crash="after_registration", requests=(PLAIN,), topic=False)
    started.append(crashing)
    try:
        crashing.esubmit(PLAIN)
    except httpx.TransportError:
        pass
    crashing.exited()
    code, registered = inspect_direct(crashing.workspace, PLAIN)
    check(code == 0 and registered["state"] == "queued" and registered["calls"] == [], "the pipeline holds the job the service never acknowledged")
    service = make_service(crashing.workspace).start()
    started.append(service)
    check(service.esubmit(PLAIN, as_="beta").status_code == 409, "the owner claim survived the crash")
    check(service.esubmit(PLAIN).status_code == 202, "the owner's retry completes it")
    ready = service.ewait(PLAIN, states={"ready"}, dispatch={"idle"})
    check(ready["dispatch"]["dispatchCount"] == 1, "one dispatch, no duplicate job")
    return ["restart: status=passed, dispatches=1", "crash after registration: status=passed, lost=0, duplicated=0"]


def busy_part(root: Path, world: World, started: list[ExtractionService]) -> str:
    service = launch(root, "busy", world, hold=True)
    started.append(service)
    workspace = service.workspace
    check(service.esubmit().status_code == 202, "accepted")
    with open(workspace.extraction_state / "extraction.lock", "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            check(service.estatus().json()["error"]["code"] == "runtime_busy", "a busy ledger is reported busy, never stale")
            workspace.go()
            time.sleep(3.0)
            state, count, busy, outcome, code = dispatch_row(workspace)
            check(outcome == "busy" and code == "extraction_busy" and busy >= 1, "a busy refusal before any effect is retried")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    done = service.ewait(states={"ready"}, dispatch={"idle"}, timeout=180)
    check(done["usage"]["replayCalls"] == world.s2_replay_calls, "one execution after the retries")
    stopped = launch(root, "stopped", world, hold=True)
    started.append(stopped)
    stopped.esubmit()
    with open(world.ingestion / "ingestion.lock", "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            stopped.workspace.go()
            seen = stopped.ewait(states={"stopped"}, dispatch={"idle"}, timeout=120)
            check(seen["failure"] == {"code": "ingestion_busy"}, "a busy reader inside an execution stops the job")
            time.sleep(2.5)
            check(stopped.ewait()["dispatch"]["dispatchCount"] == 1, "and the service does not retry it")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    stopped.erecover()
    check(stopped.ewait(states={"ready"}, dispatch={"idle"})["dispatch"]["dispatchCount"] == 2, "an explicit recover resumes it")
    return "busy: status=passed, refusalRetried=true, stoppedRetriedByService=false"


def chain_part(root: Path, world: World, started: list[ExtractionService]) -> str:
    service = launch(root, "chain", world, chain=True)
    started.append(service)
    workspace = service.workspace
    check(service.esubmit().status_code == 202, "S2 accepted over HTTP")
    s2 = service.ewait(states={"ready"}, dispatch={"idle"})
    upstream = {"jobId": JOB, "inputDigest": s2["inputDigest"]}
    check(s2["delivery"]["state"] == "available" and upstream == world.upstream, "S2 ready over HTTP with the operator job's identity")
    refused = service.rsubmit(upstream=upstream)
    check(refused.status_code == 403 and refused.json()["error"]["code"] == "upstream_not_allowed", "a ready S2 job is not an S3 upstream by itself")
    workspace.write_upstreams([("alpha", upstream["jobId"], upstream["inputDigest"])])
    check(service.rsubmit(upstream=upstream).status_code == 202, "S3 accepted after the explicit operator decision")
    s3 = service.rwait(states={"ready"}, dispatch={"idle"})
    envelope = service.rresult().json()
    check(s3["usage"]["replayCalls"] == world.replay_calls and envelope["delivery"]["state"] == "available" and envelope["job"]["counts"] == world.counts,
          "S3 ready over HTTP on the same service and gate")
    check({r["relationCandidateId"]: r["eligibility"]["status"] for r in envelope["job"]["relations"]} == world.relations, "relation identities and eligibility")
    check(service.eresult().json()["delivery"]["state"] == "available" and workspace.network_attempts() == "", "S2 unchanged, no network attempt")
    return (f"chain: status=passed, s2=ready, s3=ready, relations={len(envelope['job']['relations'])}, s2Replay={s2['usage']['replayCalls']}, "
            f"s3Replay={s3['usage']['replayCalls']}, providerCalls=0, autoAuthorization=none")


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="zoop-ai-extraction-service-smoke-")).resolve()
    started: list[ExtractionService] = []
    try:
        world = build_world(root / "world")
        before = {"ingestion": tree(world.ingestion)}
        lines = [flow_part(root, world, started), adoption_part(root, world, started), rotation_part(root, world, started),
                 *ambiguity_part(root, world, started), *restart_part(root, world, started), busy_part(root, world, started), chain_part(root, world, started)]
        check({"ingestion": tree(world.ingestion)} == before, "operator ingestion ledger is byte-identical")
        lines.append("operator state: status=passed, unchanged=true")
    except (SmokeFailure, AssertionError, OSError, httpx.HTTPError) as error:
        print(f"status=failed: {error}")
        return 1
    finally:
        for service in started:
            service.close()
        for workspace in {id(s.workspace): s.workspace for s in started}.values():
            terminate_extraction(workspace)
            if workspace.chain:
                terminate_relation(workspace)
        remove_tree(root)
    print("\n".join(lines))
    print("status=passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
