"""Operator-only S3 relation/impact candidate process (authored replay or the bound live runtime); never a BFF route, S1 command, graph writer or publisher.

Model keys exist only for `run`/`submit`/`resume` of a LIVE job (the runtime is built lazily from the environment); `inspect`, `review`, `cancel` and
`live-binding` never read keys and never call a model. `review allow` is the operator's final approval of a HOLD: no model, verifier or impact call."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from pydantic import ValidationError

from .extraction import Sources
from .extraction_contracts import MAX_REPLAY
from .ingestion_contracts import IngestionFailure, read_file
from .live_runtime import LiveFailure, LiveRuntime
from .relation import Engine, Fixtures, Store
from .relation_contracts import MAX_COMMAND, SCHEMA, ExtractionFailure, Review, Selector, Submit, canonical, digest
from .private_processing import runtime_factory, select_authority


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "submit", "inspect", "resume", "review", "cancel", "live-binding"))
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--extraction-state-dir", type=Path)
    parser.add_argument("--ingestion-state-dir", type=Path)
    authority_options = parser.add_mutually_exclusive_group()
    authority_options.add_argument("--sources", type=Path)
    authority_options.add_argument("--private-processing", type=Path)
    parser.add_argument("--replay", type=Path, help="authored producer fixture (relation/impact stages; replay jobs only)")
    parser.add_argument("--verifier-replay", type=Path, help="independent authored verifier fixture (verify-relation/verify-impact stages; replay jobs only)")
    parser.add_argument("--initial-only", action="store_true", help="resume only if this job has not taken its first dispatch (initial_dispatch_taken otherwise)")
    args = parser.parse_args()
    if args.initial_only and args.command != "resume":
        parser.error("--initial-only is only valid with resume")
    if args.command != "live-binding" and not all((args.state_dir, args.extraction_state_dir, args.ingestion_state_dir, args.sources or args.private_processing)):
        parser.error("--state-dir, --extraction-state-dir, --ingestion-state-dir and one source authority are required")
    store = None
    try:
        if args.command == "live-binding":
            if args.private_processing is not None:
                raise IngestionFailure("private_processing_not_public")
            # Offline and keyless: the exact non-secret runtime configuration a live job would freeze.
            binding = LiveRuntime.from_env(need_send=False).binding()
            print(canonical({"schemaVersion": SCHEMA, "binding": binding, "bindingDigest": digest(binding)}))
            return 0
        raw = sys.stdin.buffer.read(MAX_COMMAND + 1)
        if len(raw) > MAX_COMMAND:
            raise ExtractionFailure("command_input_limit")
        incoming = json.loads(raw)
        request = {"run": Submit, "submit": Submit, "review": Review}.get(args.command, Selector).model_validate(incoming)
        if args.command in {"inspect", "cancel", "review", "submit"} and (args.replay or args.verifier_replay):
            # Fixtures are per-call inputs of a later `run`/`resume`; a submit freezes none of them.
            raise ExtractionFailure("fixture_not_allowed")
        fixtures = Fixtures(read_file(args.replay, MAX_REPLAY) if args.replay else None,
                            read_file(args.verifier_replay, MAX_REPLAY) if args.verifier_replay else None)
        authority = select_authority(args.sources, args.private_processing)
        store = Store(args.state_dir, args.extraction_state_dir, args.ingestion_state_dir)
        factory = runtime_factory(authority) if args.command in {"run", "submit", "resume"} else None
        engine = Engine(store, Sources(args.ingestion_state_dir, authority), args.extraction_state_dir, args.ingestion_state_dir, factory)
        if args.command == "run":
            result = engine.run(request, fixtures)
        elif args.command == "submit":
            # Registration only: freeze, then report the stored job. No execution, call or state change for an existing job.
            engine.freeze(request)
            result = engine.inspect(request.job_id)
        elif args.command == "resume":
            result = engine.resume(request.job_id, fixtures, initial_only=args.initial_only)
        elif args.command == "inspect":
            result = engine.inspect(request.job_id)
        elif args.command == "cancel":
            result = engine.cancel(request.job_id)
        else:
            result = engine.review(request)
        print(canonical(result))
        return 2 if result.get("delivery", {}).get("status") == "withheld" else 0
    except (ExtractionFailure, IngestionFailure, LiveFailure) as exc:
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": exc.code, **({"detail": exc.detail} if getattr(exc, "detail", None) else {})}}))
        return 2
    except (ValidationError, ValueError, TypeError, KeyError, OSError, AttributeError):
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": "input_or_configuration_invalid"}}))
        return 2
    except sqlite3.Error:
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": "persistence_failed"}}))
        return 2
    except Exception:
        # Never dump bodies, paths or provider text from an unexpected failure.
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": "relation_internal_failure"}}))
        return 2
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
