#!/usr/bin/env python3
"""Real-process smoke for the S3 relation-job routes: real uvicorn on 127.0.0.1, the real installed `zoop-ai-relation`, a fresh synthetic
operator world (actual ingestion + a READY S2 job + authored S3 replay fixtures) and fresh private service state.

Parts: submit -> status -> result equal to the pipeline's own `inspect`; idempotency, ownership, upstream allowlist and request strictness;
delivery withheld when the source grant or the allowlist entry goes away; a child killed after reserving a call is never resent and ends
`reconciling`; a stored stage is reused after an explicit recover; the initial dispatch runs once across a service kill/restart; cancel
refuses a ready job. Review: allow = the operator's FINAL approval of a HOLD relation (terminal 200, source revision 1->2, approvalBasis
operator-final-approval, no verifier/producer/impact call, nothing dispatched, never published), reject, stale sourceVersion/sourceRevision recording
nothing, duplicate key, another principal, revoked access, and a crash after the pipeline appended the review and before the service recorded it (one
event, adopted by marker; the lost reply never replays the approval). 0 model/provider calls; the operator's ingestion and
extraction directories are proven byte-identical afterwards.
Needs the installed pipeline (`make pipeline-install`) and the service environment: `make service-pipeline-smoke`.
"""
from __future__ import annotations

import sys
import tempfile
from collections import Counter
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline_tests"))

from relation_support import (CRASH_AFTER_RELATION_STAGE, CRASH_UNKNOWN, JOB, MARKER, OPERATION_PRIVATE,  # noqa: E402
                              PRIVATE_KEYS, RelationService, RelationWorkspace, World, build_world, delivered_keys, direct_relation, inspect_direct,
                              ledger_rows, review_into_an_orphan, terminate_relation, tree, walk_keys)
from support import remove_tree  # noqa: E402


class SmokeFailure(Exception):
    pass


def check(condition: object, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def launch(root: Path, name: str, world: World, *, wrapper: str | None = None, hold: bool = False, crash: str | None = None,
           review_gate: bool = False, **kwargs) -> RelationService:
    workspace = RelationWorkspace(root / name, world, **kwargs)
    if wrapper is not None:
        workspace.write_wrapper(wrapper)
    if review_gate:
        workspace.write_review_gate_wrapper()
    env = {"ZOOP_TEST_RELATION_HOLD_FILE": str(workspace.root / "go")} if hold else {}
    if crash is not None:
        env["ZOOP_TEST_RELATION_CRASH_AT"] = crash
    return RelationService(workspace, launcher=bool(env), launcher_env=env).start()


def flow_part(root: Path, world: World, started: list[RelationService]) -> str:
    service = launch(root, "flow", world)
    started.append(service)
    workspace = service.workspace
    check(service.rsubmit().status_code == 202, "accepted with 202")
    done = service.rwait(states={"ready"}, dispatch={"idle"})
    check(done["usage"] == {"replayCalls": world.replay_calls, "startedWithoutReceipt": 0, "providerCalls": 0, "modelCalls": 0}, "replay accounting")
    check(done["dispatch"]["dispatchCount"] == 1 and done["next"] == "fetch_result", "one dispatch, then fetch_result")
    envelope = service.rresult().json()
    job = envelope["job"]
    check(envelope["delivery"]["state"] == "available" and job["counts"] == world.counts, "result counts equal the authored reference")
    check({r["relationCandidateId"]: r["eligibility"]["status"] for r in job["relations"]} == world.relations, "relation identities and eligibility")
    check(not set(delivered_keys(envelope)) & PRIVATE_KEYS, "no private pipeline field is relayed (approvalBasis alone may name the approving principal)")
    code, direct = inspect_direct(workspace, JOB)
    check(code == 0 and job["counts"] == direct["counts"] and direct["usage"]["providerCalls"] == 0, "result equals the pipeline's own inspect")
    check(service.rsubmit().status_code == 200, "idempotent replay is 200")
    check(service.rsubmit(provenance={"sourceKind": "actual", "executionMode": "replay", "recordingKind": "authored-test"}).status_code == 409, "same key, other body is 409")
    check(service.rstatus(as_="beta").status_code == 404 and service.rresult(as_="beta").status_code == 404 and service.rsubmit(as_="beta").status_code == 409,
          "another principal gets 404 and a conflict")
    check(service.rsubmit("unlisted", upstream={**world.upstream, "inputDigest": "0" * 64}).status_code == 403, "an unlisted upstream is 403")
    check(service.rsubmit("hostile", extra={"replay": "/etc/passwd"}).status_code == 422, "a request cannot name a path")
    check(service.rcancel().status_code == 409 and service.rrecover().status_code == 409, "a ready job is terminal")
    workspace.revoke_source(False)
    withheld = service.rresult().json()
    check(withheld["delivery"] == {"state": "withheld", "reason": "source_unauthorized"} and withheld["job"] is None, "revoked source withholds")
    workspace.revoke_source(True)
    check(service.rresult().json()["delivery"]["state"] == "available", "delivery returns with the grant")
    log = service.logs()
    check(not any(private in log for private in [*workspace.private_strings(), *world.source_texts]), "logs hold no private value or source text")
    return f"flow: status=passed, relations={len(job['relations'])}, replayCalls={done['usage']['replayCalls']}, providerCalls=0"


def ambiguity_part(root: Path, world: World, started: list[RelationService]) -> list[str]:
    service = launch(root, "unknown", world, wrapper=CRASH_UNKNOWN)
    started.append(service)
    service.workspace.arm()
    check(service.rsubmit().status_code == 202, "accepted")
    ambiguous = service.rwait(dispatch={"idle"})
    check(ambiguous["dispatch"]["lastOutcome"] == "transport_unknown" and ambiguous["usage"]["startedWithoutReceipt"] == 1, "a dead child is ambiguous")
    check(service.stay(JOB, 2.5)["dispatch"]["dispatchCount"] == 1, "nothing is run again automatically")
    check(service.rrecover().status_code == 202, "explicit recover")
    reconciling = service.rwait(states={"reconciling"}, dispatch={"idle"})
    check(reconciling["usage"]["replayCalls"] == 0 and reconciling["next"] == "operator_reconcile", "an unanswered call is never resent")
    check(service.rrecover().status_code == 409, "reconciling is refused")
    stage = launch(root, "stage", world, wrapper=CRASH_AFTER_RELATION_STAGE)
    started.append(stage)
    stage.workspace.arm()
    stage.rsubmit()
    interrupted = stage.rwait(dispatch={"idle"})
    check(interrupted["usage"]["replayCalls"] == 1 and interrupted["next"] == "recover", "a stored stage waits for recover")
    stage.rrecover()
    done = stage.rwait(states={"ready"}, dispatch={"idle"})
    receipts = stage.rresult().json()["receipts"]
    check(done["usage"]["replayCalls"] == world.replay_calls and sum(r["stage"] == "relation" for r in receipts) == 1, "the stored receipt was reused, not called again")
    return ["ambiguity: status=passed, resent=0", "recover: status=passed, relationCalls=1"]


def restart_part(root: Path, world: World, started: list[RelationService]) -> str:
    service = launch(root, "restart", world, hold=True)
    started.append(service)
    check(service.rsubmit().status_code == 202, "accepted while held")
    service.kill()
    again = RelationService(service.workspace).start()
    started.append(again)
    done = again.rwait(states={"ready"}, dispatch={"idle"})
    check(done["dispatch"]["dispatchCount"] == 1, "the initial dispatch ran once after the restart")
    again.kill()
    third = RelationService(service.workspace).start()
    started.append(third)
    check(third.stay(JOB, 2.5)["dispatch"]["dispatchCount"] == 1, "a later restart does not run it again")
    return "restart: status=passed, dispatches=1"



KEY = "smoke-decision-allow-0001"


def stages(service: RelationService) -> Counter:
    return Counter(receipt["stage"] for receipt in service.rresult().json()["receipts"])


def ready(service: RelationService) -> dict:
    check(service.rsubmit().status_code == 202, "accepted with 202")
    return service.rwait(states={"ready"}, dispatch={"idle"})


def review_flow_part(root: Path, world: World, started: list[RelationService]) -> list[str]:
    service = launch(root, "review", world)
    started.append(service)
    workspace = service.workspace
    status = ready(service)
    version = status["inputDigest"]
    before, calls = direct_relation(workspace, world.held), stages(service)
    check(service.result_relation(world.held)["sourceVersion"] == version and service.result_relation(world.held)["sourceRevision"] == str(world.held_revision),
          "the result carries the sourceVersion and sourceRevision a review must quote")
    # Stale expectations record nothing anywhere.
    check(service.rreview("k-version", world.held, version="0" * 64).json()["error"]["code"] == "source_version_conflict", "a stale sourceVersion is refused")
    check(service.rreview("k-revision", world.held, revision=2).json()["error"]["code"] == "source_revision_conflict", "a stale sourceRevision is refused")
    check(service.roperation("k-version").status_code == 404 and service.roperation("k-revision").status_code == 404, "a refusal creates no operation")
    check(direct_relation(workspace, world.held) == before and service.rstatus().json()["dispatch"]["dispatchCount"] == 1, "a refusal appends nothing")
    # Another principal sees nothing of it.
    check(service.rreview("k-beta", world.held, as_="beta", version=version).status_code == 404, "another principal's job is invisible to a review")
    # allow = final approval: terminal, no revalidation, no call. Acceptance, approval basis and publication are separate.
    accepted = service.rreview(KEY, world.held)
    body = accepted.json()
    check(accepted.status_code == 200 and body["reviewer"] == "alpha" and body["review"]["resultingSourceRevision"] == "2", "an allow is recorded with 200")
    check(body["revalidation"]["state"] == "not_requested" and body["next"] == "none" and body["limitation"] is None, "terminal: nothing to wait for")
    check(body["publication"] == {"state": "not_published"} and not set(walk_keys(body)) & OPERATION_PRIVATE, "nothing is published and nothing private is relayed")
    quiet = service.stay(JOB, 2.0)
    check(quiet["dispatch"]["dispatchCount"] == 1 and quiet["state"] == "ready", "nothing was dispatched for the approval")
    relation = service.result_relation(world.held)
    basis = relation["eligibility"]["approvalBasis"]
    check(relation["sourceRevision"] == "2" and relation["eligibility"]["status"] == "eligible" and relation["approved"] is False, "eligible is not published")
    check(basis["kind"] == "operator-final-approval" and basis["reviewer"] == "alpha" and basis["revision"] == 2, "the approval basis names the operator")
    check(stages(service) == calls, "no verifier, producer or impact call")
    chain = direct_relation(workspace, world.held)["history"]
    check([e["kind"] for e in chain] == ["verdict", "review"] and (chain[1]["reviewer"], chain[1]["note"], chain[1]["effect"]) == ("alpha", MARKER + KEY, "approved"),
          "one review event, written by the principal with the operation marker")
    # Duplicate key: the existing operation, although the relation has moved since; another body is a conflict.
    replay = service.rreview(KEY, world.held)
    check(replay.status_code == 200 and replay.json()["revalidation"]["state"] == "not_requested", "the same key and body return the operation")
    check(service.rreview(KEY, world.held, decision="reject").status_code == 409, "the same key with another body is a conflict")
    check(service.roperation(KEY, as_="beta").status_code == 404, "an operation is invisible to another principal")
    # Revoked access.
    both = [(name, world.upstream["jobId"], world.upstream["inputDigest"]) for name in ("alpha", "beta")]
    workspace.write_upstreams([entry for entry in both if entry[0] == "beta"])
    check(service.rreview("k-unlisted", world.held, revision=2, version=version).status_code == 403, "an unlisted upstream refuses a review")
    workspace.write_upstreams(both)
    workspace.revoke_source(False)
    check(service.rreview("k-revoked", world.held, revision=2, version=version).status_code == 409, "a revoked source grant refuses a review")
    workspace.revoke_source(True)
    check(service.roperation("k-unlisted").status_code == 404 and service.roperation("k-revoked").status_code == 404, "refusals create no operation")
    log = service.logs()
    check(not any(private in log for private in [*workspace.private_strings(), *world.source_texts, MARKER]), "logs hold no private value, source text or marker")
    # reject
    other = launch(root, "reject", world)
    started.append(other)
    ready(other)
    rejected = other.rreview("smoke-decision-reject-0001", world.held, decision="reject")
    check(rejected.status_code == 200 and rejected.json()["revalidation"]["state"] == "not_requested", "a reject is recorded without a revalidation")
    closed = other.result_relation(world.held)
    check(closed["eligibility"]["status"] == "reject" and closed["sourceRevision"] == "2" and stages(other) == calls, "a reject closes the relation and calls nothing")
    return ["review: status=passed, sourceRevision=1->2, approvalBasis=operator-final-approval, modelCalls=0, published=false",
            "review refusals: status=passed, recorded=0 (stale version, stale revision, another principal, unlisted upstream, revoked grant)",
            "review idempotency: status=passed, same key replays, other body conflicts", "review reject: status=passed, revalidations=0"]


def review_crash_part(root: Path, world: World, started: list[RelationService]) -> list[str]:
    crashing = launch(root, "crash-review", world, crash="after_review_child")
    started.append(crashing)
    status = ready(crashing)
    try:
        crashing.rreview(KEY, world.held)
    except httpx.TransportError:
        pass  # the service died after the pipeline appended the event and before it recorded anything
    crashing.exited()
    check([e["kind"] for e in direct_relation(crashing.workspace, world.held)["history"]] == ["verdict", "review"], "the event is in the chain")
    service = RelationService(crashing.workspace).start()
    started.append(service)
    found = service.roperation(KEY).json()
    check(found["review"]["state"] == "unconfirmed" and found["next"] == "retry_review" and found["expectedSourceVersion"] == status["inputDigest"], "the operation is found, unproven")
    check(service.rreview("k-other", world.held).status_code == 409, "another key cannot adopt the unproven event")
    retried = service.rreview(KEY, world.held)
    check(retried.status_code == 200 and retried.json()["review"]["state"] == "applied" and retried.json()["next"] == "none", "the same request adopts the event by its marker")
    check(service.stay(JOB, 2.0)["dispatch"]["dispatchCount"] == 1, "the approval dispatched nothing")
    service.close()
    chain = direct_relation(crashing.workspace, world.held)["history"]
    check([e["kind"] for e in chain] == ["verdict", "review"] and [e["note"] for e in chain if e["kind"] == "review"] == [MARKER + KEY], "exactly one review event")
    return ["review crash after append: status=passed, reviewEvents=1, adopted=by-marker"]



def review_orphan_part(root: Path, world: World, started: list[RelationService]) -> list[str]:
    """A review child paused BEFORE it takes the pipeline's ledger lock outlives its SIGKILLed service (a real orphan, no hook in the service or
    the pipeline) and appends the operation's event after the retry has read the chain; and the foreign control: an operator's event appended at
    the same moment releases the reservation, which is then actually reusable at the current revision."""
    first = launch(root, "orphan", world, review_gate=True)
    started.append(first)
    workspace = first.workspace
    version = ready(first)["inputDigest"]
    pid = review_into_an_orphan(first, KEY, world.held, version)
    check([e["kind"] for e in direct_relation(workspace, world.held)["history"]] == ["verdict"] and not workspace.orphan_done(),
          "the orphan is alive and has appended nothing (it holds no ledger lock)")
    service = RelationService(workspace).start()
    started.append(service)
    check(service.roperation(KEY).json()["review"]["state"] == "unconfirmed", "the operation is found, unproven")
    workspace.release_orphan_before_next_review()
    retried = service.rreview(KEY, world.held, version=version)
    check(retried.status_code == 200 and retried.json()["review"]["state"] == "applied", "the retry adopts the orphan's exact event")
    check(workspace.orphan_done(), "the orphan finished and appended before the retry's own child ran")
    check(service.stay(JOB, 2.0)["dispatch"]["dispatchCount"] == 1, "the approval dispatched nothing")
    service.close()
    check(pid > 0 and '"code":"review_revision_conflict"' in service.logs("out"), "the retry's own child was refused: the race was exercised")
    chain = direct_relation(workspace, world.held)["history"]
    check([e["kind"] for e in chain] == ["verdict", "review"] and [e["note"] for e in chain if e["kind"] == "review"] == [MARKER + KEY],
          "exactly one review event, the orphan's")

    crashing = launch(root, "foreign", world, review_gate=True, crash="after_review_reserve")
    started.append(crashing)
    foreign_version = ready(crashing)["inputDigest"]
    try:
        crashing.rreview(KEY, world.held)
    except httpx.TransportError:
        pass
    crashing.exited()
    crashing.workspace.foreign_review_before_next_review(world.held)
    other = RelationService(crashing.workspace).start()
    started.append(other)
    refused = other.rreview(KEY, world.held, version=foreign_version)
    check(refused.status_code == 409 and refused.json()["error"]["code"] == "source_revision_conflict", "a foreign event is a revision conflict")
    check(other.roperation(KEY).status_code == 404 and ledger_rows(crashing.workspace, "SELECT COUNT(*) FROM relation_operations") == [(0,)],
          "the reservation is released")
    reused = other.rreview(KEY, world.held, decision="reject", revision=2, version=foreign_version)
    check(reused.status_code == 409 and reused.json()["error"]["code"] == "review_target_not_hold" and other.roperation(KEY).status_code == 404,
          "the key is free again and the relation (approved by the operator) takes no reversal")
    return ["review orphan: status=passed, orphanAppendedAfterRetryRead=true, adopted=by-marker, reviewEvents=1",
            "review foreign control: status=passed, released=true"]


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="zoop-ai-relation-service-smoke-")).resolve()
    started: list[RelationService] = []
    try:
        world = build_world(root / "world")
        before = {"ingestion": tree(world.ingestion), "extraction": tree(world.extraction)}
        lines = [flow_part(root, world, started), *ambiguity_part(root, world, started), restart_part(root, world, started),
                 *review_flow_part(root, world, started), *review_crash_part(root, world, started), *review_orphan_part(root, world, started)]
        check({"ingestion": tree(world.ingestion), "extraction": tree(world.extraction)} == before, "operator ledgers are byte-identical")
        lines.append("operator state: status=passed, unchanged=true")
    except (SmokeFailure, AssertionError, OSError, httpx.HTTPError) as error:
        print(f"status=failed: {error}")
        return 1
    finally:
        for service in started:
            service.close()
        for workspace in {id(s.workspace): s.workspace for s in started}.values():
            terminate_relation(workspace)
        remove_tree(root)
    print("\n".join(lines))
    print("status=passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
