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
ZOOP_TEST_RELATION_CRASH_AT = after_reserve  S3: after the owner reservation commits, before the pipeline is asked to register
                     after_registration  after the real pipeline registered the job, before the service accepts it
                     before_response   after accepted + dispatch intent commit, before any response is sent
                     after_claim       after the relation dispatcher marks a row in flight, before any child starts
                     after_child       after the real `resume` child exited, before its outcome is recorded
                     after_review_reserve  review: after the operation reservation commits, before the pipeline is asked to append the event
                     after_review_child    review: after the real `review` child appended the event, before the service records it
                     after_review_applied  review: after the operation is recorded (and its revalidation queued), before any response is sent
                     after_revalidation_child  revalidation: after the real `revalidate` child exited, before its outcome is recorded
ZOOP_TEST_RELATION_HOLD_FILE = path    the relation dispatcher claims nothing until this file exists (keeps accepted jobs queued)
ZOOP_TEST_EXTRACTION_CRASH_AT = after_reserve  S2: after the owner reservation commits, before the pipeline is asked to register
                     after_registration  after the real pipeline registered the job, before the service accepts it
                     before_response   after accepted + dispatch intent commit, before any response is sent
                     after_claim       after the extraction dispatcher marks a row in flight, before any child starts
                     after_child       after the real `resume` child exited, before its outcome is recorded
ZOOP_TEST_EXTRACTION_HOLD_FILE = path  the extraction dispatcher claims nothing until this file exists (keeps accepted jobs queued)
"""
from __future__ import annotations

import os
import signal
import time
import sqlite3
import sys

from zoop_ai_service import main as entry
from zoop_ai_service.config import ConfigError, load
from zoop_ai_service.runtime import Deadlines


def die() -> None:
    """SIGKILL this process, and never return to the caller. `kill` to the own pid is process-directed: the kernel may deliver it on another
    thread (the idle main thread), so the calling thread can run on for a moment. Every hook sits at a boundary that must be the LAST thing this
    process does before the next durable write (for example, after a child exited and before its outcome is recorded), so the calling thread parks
    here until the kill lands instead of racing it to the ledger."""
    os.kill(os.getpid(), signal.SIGKILL)
    while True:
        time.sleep(60)


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
    relation_crash = os.environ.get("ZOOP_TEST_RELATION_CRASH_AT")
    if relation_crash is not None:
        assert service.relation is not None and service.relation_ledger is not None
        process, ledger = service.relation.process, service.relation_ledger
        if relation_crash == "after_reserve":
            process.submit = lambda body: die()
        elif relation_crash == "after_registration":
            real_register = process.submit
            process.submit = lambda body: (real_register(body), die())[0]
        elif relation_crash == "before_response":
            real_relation_accept = ledger.accept
            ledger.accept = lambda *args: (real_relation_accept(*args), die())[0]
        elif relation_crash == "after_claim":
            real_relation_claim = ledger.claim_next
            ledger.claim_next = lambda: (lambda claim: die() if claim else claim)(real_relation_claim())
        elif relation_crash == "after_child":
            real_resume = process.resume
            process.resume = lambda *args, **kwargs: (real_resume(*args, **kwargs), die())[0]
        elif relation_crash == "after_review_reserve":
            process.review = lambda *args, **kwargs: die()
        elif relation_crash == "after_review_child":
            real_review = process.review
            process.review = lambda *args, **kwargs: (real_review(*args, **kwargs), die())[0]
        elif relation_crash == "after_review_applied":
            real_apply = ledger.apply_operation
            ledger.apply_operation = lambda *args: (real_apply(*args), die())[0]
        elif relation_crash == "after_revalidation_child":
            real_revalidate = process.revalidate
            process.revalidate = lambda *args, **kwargs: (real_revalidate(*args, **kwargs), die())[0]
    hold = os.environ.get("ZOOP_TEST_RELATION_HOLD_FILE")
    if hold:
        assert service.relation_ledger is not None
        real_hold_claim = service.relation_ledger.claim_next
        service.relation_ledger.claim_next = lambda: real_hold_claim() if os.path.exists(hold) else None
    extraction_crash = os.environ.get("ZOOP_TEST_EXTRACTION_CRASH_AT")
    if extraction_crash is not None:
        assert service.extraction is not None and service.extraction_ledger is not None
        extraction_process, extraction_ledger = service.extraction.process, service.extraction_ledger
        if extraction_crash == "after_reserve":
            extraction_process.submit = lambda body: die()
        elif extraction_crash == "after_registration":
            real_extraction_submit = extraction_process.submit
            extraction_process.submit = lambda body: (real_extraction_submit(body), die())[0]
        elif extraction_crash == "before_response":
            real_extraction_accept = extraction_ledger.accept
            extraction_ledger.accept = lambda *args: (real_extraction_accept(*args), die())[0]
        elif extraction_crash == "after_claim":
            real_extraction_claim = extraction_ledger.claim_next
            extraction_ledger.claim_next = lambda: (lambda claim: die() if claim else claim)(real_extraction_claim())
        elif extraction_crash == "after_child":
            real_extraction_resume = extraction_process.resume
            extraction_process.resume = lambda *args, **kwargs: (real_extraction_resume(*args, **kwargs), die())[0]
    extraction_hold = os.environ.get("ZOOP_TEST_EXTRACTION_HOLD_FILE")
    if extraction_hold:
        assert service.extraction_ledger is not None
        real_extraction_hold_claim = service.extraction_ledger.claim_next
        service.extraction_ledger.claim_next = lambda: real_extraction_hold_claim() if os.path.exists(extraction_hold) else None
    entry.serve(service)
    return 0


if __name__ == "__main__":
    sys.exit(main())
