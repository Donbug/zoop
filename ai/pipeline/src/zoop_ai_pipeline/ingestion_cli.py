"""Operator-only offline source preparation; never a BFF route or S1 command."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .ingestion import Ingestor, Store
from .ingestion_contracts import SCHEMA, MAX_INPUT, Authority, Export, IngestionFailure, Inspect, Resume, Run, Tick, canonical
from .ingestion_schedule import clock, latest_slot, not_due, tick


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "resume", "inspect", "export", "tick"))
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--sources", required=True, type=Path)
    parser.add_argument("--fixture-manifest", type=Path)
    parser.add_argument("--require-store", action="store_true", help="export only: also require the current grant to allow `store` (for consumers that persist the text)")
    args = parser.parse_args()
    store = None
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise IngestionFailure("command_input_limit")
        incoming = json.loads(raw)
        if args.command == "tick":
            if args.require_store:
                raise IngestionFailure("require_store_not_allowed")
            request = Tick.model_validate(incoming)
            now = clock(request)
            slot, reason = latest_slot(now)
            if slot is None:
                # Not due: no registry, manifest or state is touched.
                print(canonical(not_due(now, reason)))
                return 0
            store = Store(args.state_dir)
            body, code = tick(request, now, slot, store, Authority(args.sources), args.fixture_manifest)
            print(canonical(body))
            return code
        authority = Authority(args.sources)
        model = {"run": Run, "resume": Resume, "inspect": Inspect, "export": Export}[args.command]
        request = model.model_validate(incoming)
        if args.command == "run" and args.fixture_manifest is None:
            raise IngestionFailure("fixture_manifest_required")
        if args.command != "run" and args.fixture_manifest is not None:
            raise IngestionFailure("fixture_manifest_not_allowed")
        if args.require_store and args.command != "export":
            raise IngestionFailure("require_store_not_allowed")
        store = Store(args.state_dir, existing=args.command == "export")
        runner = Ingestor(store, authority)
        if args.command == "run":
            result = runner.run(request, args.fixture_manifest)
        elif args.command == "resume":
            result = runner.resume(request.round_id, request.source_id)
        elif args.command == "export":
            result = runner.export(request, require_store=args.require_store)
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
