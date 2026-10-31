#!/usr/bin/env python3
"""Offline, actual-process observation export acceptance; no dependency installation."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE / "src"), str(SERVICE / "pipeline_tests")]
from observation_support import smoke


def main():
    with tempfile.TemporaryDirectory(prefix="zoop-observation-http-") as temporary:
        report = smoke(Path(temporary).resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
