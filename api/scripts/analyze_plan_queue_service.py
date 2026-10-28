#!/usr/bin/env python3
"""Test-owned real-service launcher: kill AFTER actual S2 reservation commits.

The reserved-only row is made by the real public AI submit path, not SQL-seeded.
The production consumer must reconcile its real 404 with the identical stored POST.
"""
from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

from zoop_ai_service import main as entry
from zoop_ai_service.config import load
from zoop_ai_service.extraction_ledger import ExtractionLedger


def main():
    root = Path(sys.argv[1])
    actual = ExtractionLedger.reserve

    def reserve(self, *args, **kwargs):
        result = actual(self, *args, **kwargs)
        arm = root / "reserve-arm"
        if arm.exists():
            arm.unlink()
            (root / "reserve-committed").touch()
            os.kill(os.getpid(), signal.SIGKILL)
        return result

    ExtractionLedger.reserve = reserve
    service = entry.build_service(load(os.environ))
    entry.serve(service)


if __name__ == "__main__":
    main()
