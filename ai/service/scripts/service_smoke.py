#!/usr/bin/env python3
"""Real-process smoke for the internal AI HTTP service: real uvicorn on 127.0.0.1, the real installed `zoop-ai` CLI, fresh temp state.

Replay part: all four S1 kinds, auth/owner/idempotency refusals, result equal to the runtime's own `get`, and recovery of a
blocked job; it makes 0 provider calls. Loopback part: a counting provider on 127.0.0.1 proves cancel and a service kill/restart
never send anything twice. Credentials are synthetic and exist only in memory; temp state, servers and runtime children are removed.
Run with the service's own environment: `make service-smoke`.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from support import (ProviderStub, ServiceProcess, Workspace, cli, combined_replay, document_jobs, document_replay,  # noqa: E402
                     live_job, live_workspace, outlook_job, reference, remove_tree, semantic_job_and_entry, terminate_runtime)


class SmokeFailure(Exception):
    pass


def check(condition: object, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def replay_part(root: Path, started: list[ServiceProcess]) -> str:
    workspace = Workspace(root / "replay", replay=combined_replay())
    service = ServiceProcess(workspace).start()
    started.append(service)
    verify, _ = semantic_job_and_entry()
    jobs = [*document_jobs(), outlook_job(), verify]
    check([service.submit(job).status_code for job in jobs] == [202] * len(jobs), "every kind is accepted with 202")
    statuses = [service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"}, timeout=90) for job in jobs]
    check({s["kind"] for s in statuses} == {"document-summary", "document-sentiment", "semantic-verification", "briefing-outlook"}, "four kinds")
    attempts = sum(s["usage"]["providerAttempts"] for s in statuses)
    calls = sum(s["usage"]["replayCalls"] for s in statuses)
    check(attempts == 0 and calls == 10, f"replay accounting providerAttempts={attempts} replayCalls={calls}")
    for job in jobs:
        body = service.result(job["jobId"]).json()
        check(body["delivery"]["state"] == "available" and body["job"] == cli(workspace, "get", reference(job["jobId"]))[1],
              f"result equals the runtime get for {job['jobId']}")
    first = jobs[0]
    check(service.submit(first).status_code == 200, "idempotent replay is 200")
    check(service.submit(first, as_=None, token="x" * 43).status_code == 401, "unknown token is 401")
    check(service.submit(first, as_="reader").status_code == 403, "missing scope is 403")
    check(service.status(first["jobId"], as_="beta").status_code == 404 and service.submit(first, as_="beta").status_code == 409,
          "another owner gets 404 and a conflict")
    check(service.submit(first, key="different-key").status_code == 422, "key mismatch is 422")
    check(service.submit({**first, "kind": "document-sentiment"}).status_code == 409, "same key, other body is 409")
    check(service.cancel(first["jobId"]).status_code == 409 and service.recover(first["jobId"]).status_code == 409, "terminal job")
    log = service.logs()
    check(not any(secret in log for secret in workspace.private_strings()), "logs hold no private value")
    return f"replay: status=passed, kinds=4, providerAttempts={attempts}, replayCalls={calls}"


def recover_part(root: Path, started: list[ServiceProcess]) -> str:
    broken = document_replay()
    broken["recordingKind"] = "provider"
    workspace = Workspace(root / "recover", replay=broken)
    service = ServiceProcess(workspace).start()
    started.append(service)
    job = document_jobs()[0]
    check(service.submit(job).status_code == 202, "accepted while blocked")
    blocked = service.wait_state(job["jobId"], {"queued"}, dispatch={"idle"})
    check(blocked["dispatch"]["lastRuntimeCode"] == "replay_fixture_invalid" and blocked["next"] == "recover", "blocked is reported honestly")
    workspace.replay_path.write_text(json.dumps(document_replay(), ensure_ascii=False), encoding="utf-8")
    check(service.recover(job["jobId"]).status_code == 202, "recover is 202")
    final = service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})
    check(final["usage"]["providerAttempts"] == 0 and final["usage"]["replayCalls"] == 2, "recovered with replay only")
    return "recover: status=passed, providerAttempts=0"


def loopback_part(root: Path, started: list[ServiceProcess]) -> list[str]:
    stub = ProviderStub()
    try:
        workspace, env = live_workspace(root / "live", stub)
        service = ServiceProcess(workspace, env=workspace.env(**env)).start()
        started.append(service)
        gate = stub.gate("document_summary")
        held = live_job(job_id="smoke-cancel")
        check(service.submit(held).status_code == 202 and gate.entered.wait(30), "live job reached the loopback provider")
        check(service.cancel(held["jobId"]).json()["state"] == "cancelled", "cancel while the call is held")
        gate.release()
        done = service.wait_state(held["jobId"], {"cancelled"}, dispatch={"idle"}, timeout=60)
        check(done["usage"]["providerAttempts"] == 1 and done["artifactIds"] == [] and stub.requests == ["document_summary"],
              f"cancel kept the receipt and never sent verify: {stub.requests}")
        stub.delay = 1.0
        restart = live_job(document_jobs()[1], job_id="smoke-restart")
        check(service.submit(restart).status_code == 202, "second live job accepted")
        service.kill()
        again = ServiceProcess(workspace, env=workspace.env(**env)).start()
        started.append(again)
        final = again.wait_state(restart["jobId"], {"ready"}, dispatch={"idle"}, timeout=90)
        check(final["usage"]["providerAttempts"] == 2 and stub.requests == ["document_summary", "document_sentiment", "semantic_verification"],
              f"kill/restart sent each stage exactly once: {stub.requests}")
        return [f"cancel: status=passed, loopbackRequests=1", f"restart: status=passed, loopbackRequests=2, providerAttempts={final['usage']['providerAttempts']}"]
    finally:
        stub.close()


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="zoop-ai-service-smoke-")).resolve()
    started: list[ServiceProcess] = []
    try:
        lines = [replay_part(root, started), recover_part(root, started), *loopback_part(root, started)]
    except (SmokeFailure, AssertionError, OSError) as error:
        print(f"status=failed: {error}")
        return 1
    finally:
        for service in started:
            service.close()
        for service in started:
            terminate_runtime(service.workspace.worker)
        remove_tree(root)
    print("\n".join(lines))
    print("status=passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
