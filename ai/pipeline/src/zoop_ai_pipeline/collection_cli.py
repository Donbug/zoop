"""Operator-only one-off document URL collection. The only pipeline command that fetches source documents over HTTP.

stdin: one canonical-JSON `zoop-collection-1` request (explicit URLs + declared metadata). stdout: canonical JSON. Exit 0 only when
every URL was collected; 2 for any refusal, partial or failed collection (a partial result still names its ingestion manifest).
It reads no `.env` and no API key, ignores proxy environment variables and never retries.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .collection import collect
from .collection_contracts import MAX_POLICY, SCHEMA, Policy, Request
from .ingestion_contracts import MAX_INPUT, IngestionFailure, canonical, read_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run",))
    parser.add_argument("--sources", required=True, type=Path, help="source registry (zoop-ingestion-s2-1) naming a `collected-http` source")
    parser.add_argument("--policy", required=True, type=Path, help="read-only operator policy: user agent and every fetch budget")
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise IngestionFailure("command_input_limit")
        request = Request.model_validate(json.loads(raw))
        policy = Policy.model_validate_json(read_file(args.policy, MAX_POLICY))
        result = collect(args.sources, policy, request)
        print(canonical(result))
        return 0 if result["state"] == "complete" else 2
    except IngestionFailure as exc:
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": exc.code}}))
        return 2
    except (ValidationError, ValueError, TypeError, KeyError, OSError):
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": "input_or_configuration_invalid"}}))
        return 2
    except Exception:
        # Never a traceback: it could carry a URL, a header or part of a body.
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": "collection_internal_failure"}}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
