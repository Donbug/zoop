#!/usr/bin/env python3
"""Actual installed exposure CLI and loopback HTTP over fresh synthetic replay state; no external calls.

Run: ai/service/.venv/bin/python ai/service/scripts/handoff_exposure_service_smoke.py
Existing service/pipeline installs are required. Owned temporary state only; no environment credentials are read.
"""
import json
import sys
import tempfile
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE / "tests"), str(SERVICE / "pipeline_tests")]
from real_exposure_support import build, exercise
from support import remove_tree


def main():
    root = Path(tempfile.mkdtemp(prefix="zoop-exposure-service-")).resolve()
    try:
        result = exercise(root / "service", build(root / "world"))
    except Exception as error:
        print(json.dumps({"status": "failed", "errorClass": type(error).__name__, "retained": str(root)}))
        return 1
    remove_tree(root)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
