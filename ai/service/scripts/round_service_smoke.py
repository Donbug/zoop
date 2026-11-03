#!/usr/bin/env python3
"""Run the credential-free native round HTTP scenario in a new private root."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline_tests"))
from round_service_support import run_scenario


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="New directory; all synthetic state and reports stay below it")
    args = parser.parse_args()
    print(json.dumps(run_scenario(args.root), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
