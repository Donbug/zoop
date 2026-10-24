"""Exercise the offline installer smoke through its actual CLI and HTTP surfaces.

The session's synthetic operator world is reused, but no service state, approvals or
installation journal is shared between scenarios. Evidence survives workspace cleanup.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from plan_install_service_smoke import crash_recovery, flow, refusals  # noqa: E402
from support import remove_tree  # noqa: E402


def test_exact_plan_installation_http_and_crash_recovery(tmp_path, world):
    work = tmp_path / "work"
    evidence = tmp_path / "evidence"
    work.mkdir()
    evidence.mkdir()
    owned = []
    try:
        results = [flow(work, evidence, world, owned), refusals(work, evidence, world, owned),
                   crash_recovery(work, evidence, world, owned, foreign=False),
                   crash_recovery(work, evidence, world, owned, foreign=True)]
        assert {result["case"] for result in results} == {"flow", "refusals", "crash-recover", "crash-foreign"}
    finally:
        errors = []
        try:
            for scenario in owned:
                try:
                    scenario.close()
                except Exception as error:
                    errors.append(error)
        finally:
            remove_tree(work)
        if errors:
            raise errors[0]
