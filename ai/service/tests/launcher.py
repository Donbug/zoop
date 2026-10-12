"""Test-only entry: the real service, with one process-kill fault injected at a named boundary.

It wraps the real components (the real `zoop-ai` submit still runs, the real ledger still commits); it only SIGKILLs this
process at the chosen point, which is exactly what a crash looks like to the durable state. Production code has no such hook.

ZOOP_TEST_CRASH_AT = after_intent      after the owner reservation commits, before the runtime is asked to register
                     after_registration  after the real runtime registered the job, before the service accepts it
                     before_response   after accepted + dispatch intent commit, before any response is sent
                     after_claim       after the dispatcher marks a row in flight, before any child starts
                     finish_fails_once the first ledger.finish (the dispatch outcome write after a child exits) raises a
                                       transient SQLite error before touching the row; later calls are real
ZOOP_TEST_RUN_DEADLINE = seconds       the internal run/resume deadline seam (not configuration)
"""
from __future__ import annotations

import os
import signal
import sqlite3
import sys

from zoop_ai_service import main as entry
from zoop_ai_service.config import ConfigError, load
from zoop_ai_service.runtime import Deadlines


def die() -> None:
    os.kill(os.getpid(), signal.SIGKILL)


def main() -> int:
    try:
        deadline = os.environ.get("ZOOP_TEST_RUN_DEADLINE")
        service = entry.build_service(load(os.environ), deadlines=Deadlines(long=float(deadline)) if deadline else Deadlines())
    except ConfigError as error:
        return entry.refuse(error)
    crash = os.environ.get("ZOOP_TEST_CRASH_AT")
    if crash == "after_intent":
        service.worker.submit = lambda body: die()
    elif crash == "after_registration":
        real_submit = service.worker.submit
        service.worker.submit = lambda body: (real_submit(body), die())[0]
    elif crash == "before_response":
        real_accept = service.ledger.accept
        service.ledger.accept = lambda *args: (real_accept(*args), die())[0]
    elif crash == "after_claim":
        real_claim = service.ledger.claim_next
        service.ledger.claim_next = lambda: (lambda claim: die() if claim else claim)(real_claim())
    elif crash == "finish_fails_once":
        real_finish, failed = service.ledger.finish, []

        def finish(job_id, update):
            if not failed:
                failed.append(job_id)
                raise sqlite3.OperationalError("database is locked")
            return real_finish(job_id, update)
        service.ledger.finish = finish
    entry.serve(service)
    return 0


if __name__ == "__main__":
    sys.exit(main())
