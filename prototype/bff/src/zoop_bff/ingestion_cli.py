"""Operator-only offline source preparation; never a BFF route or S1 command."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .ingestion import Ingestor, Store
from .ingestion_contracts import SCHEMA, MAX_INPUT, Authority, IngestionFailure, Inspect, Resume, Run, canonical


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "resume", "inspect"))
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--sources", required=True, type=Path)
    parser.add_argument("--fixture-manifest", type=Path)
    args = parser.parse_args()
    store = None
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise IngestionFailure("command_input_limit")
        incoming = json.loads(raw)
        authority = Authority(args.sources)
        model = {"run": Run, "resume": Resume, "inspect": Inspect}[args.command]
        request = model.model_validate(incoming)
        if args.command == "run" and args.fixture_manifest is None:
            raise IngestionFailure("fixture_manifest_required")
        if args.command != "run" and args.fixture_manifest is not None:
            raise IngestionFailure("fixture_manifest_not_allowed")
        store = Store(args.state_dir)
        runner = Ingestor(store, authority)
        if args.command == "run":
            result = runner.run(request, args.fixture_manifest)
        elif args.command == "resume":
            result = runner.resume(request.round_id, request.source_id)
        else:
            result = runner.inspect(request)
        print(canonical(result))
        return 0
    except IngestionFailure as exc:
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": exc.code}}))
        return 2
    except (ValidationError, ValueError, TypeError, KeyError, OSError):
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": "input_or_configuration_invalid"}}))
        return 2
    except Exception:
        # Parser/configuration failures are fail-closed, never body/path dumps.
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": "ingestion_internal_failure"}}))
        return 2
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
