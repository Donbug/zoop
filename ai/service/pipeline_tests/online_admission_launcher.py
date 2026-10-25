#!/usr/bin/env python3
"""Real service with test-owned crash/clock seams; never imported by production.

The before-commit fault fires at the SQLite COMMIT after all paired grant/quota
writes, not at a mocked admission response. The after-commit fault fires after the
real durable commit returns but before the HTTP handler can receive its result.
"""
from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

from zoop_ai_service import main as entry
from zoop_ai_service.config import load


def die(root, boundary):
    (root / "fault-observed").write_text(boundary)
    os.kill(os.getpid(), signal.SIGKILL)
    while True:
        time.sleep(60)


class CrashConnection:
    def __init__(self, actual, root):
        self.actual, self.root, self.in_admission = actual, root, False

    def __getattr__(self, name):
        return getattr(self.actual, name)

    def execute(self, sql, *args, **kwargs):
        if self.in_admission and sql == "COMMIT":
            die(self.root, "before-commit")
        return self.actual.execute(sql, *args, **kwargs)


def main():
    fault, root = sys.argv[1], Path(sys.argv[2])
    service = entry.build_service(load(os.environ))
    authority = service.plans.authority
    if fault in ("before-commit", "after-commit"):
        original = authority.commit
        proxy = CrashConnection(authority._db, root)
        if fault == "before-commit":
            authority._db = proxy

        def commit(*args, **kwargs):
            armed = (root / "arm-service-fault").exists()
            proxy.in_admission = armed
            try:
                result = original(*args, **kwargs)
                if armed and fault == "after-commit":
                    die(root, fault)
                return result
            finally:
                proxy.in_admission = False
        authority.commit = commit
    elif fault == "clock":
        authority.clock = lambda: time.time() + float((root / "clock-offset").read_text())
    else:
        raise ValueError("unknown test-owned service fault")
    entry.serve(service)


if __name__ == "__main__":
    main()
