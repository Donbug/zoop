"""Operator-only offline S3 relation/impact candidate process; never a BFF route, S1 command, graph writer or publisher."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from pydantic import ValidationError

from .extraction import Sources
from .extraction_contracts import MAX_REPLAY
from .ingestion_contracts import Authority, IngestionFailure, read_file
from .relation import Engine, Fixtures, Store
from .relation_contracts import MAX_COMMAND, SCHEMA, ExtractionFailure, Review, Revalidate, Selector, Submit, canonical


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "submit", "inspect", "resume", "review", "revalidate", "cancel"))
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--extraction-state-dir", required=True, type=Path)
    parser.add_argument("--ingestion-state-dir", required=True, type=Path)
    parser.add_argument("--sources", required=True, type=Path)
    parser.add_argument("--replay", type=Path, help="authored producer fixture (relation/impact stages)")
    parser.add_argument("--verifier-replay", type=Path, help="independent authored verifier fixture (verify-relation/verify-impact stages)")
    args = parser.parse_args()
    store = None
    try:
        raw = sys.stdin.buffer.read(MAX_COMMAND + 1)
        if len(raw) > MAX_COMMAND:
            raise ExtractionFailure("command_input_limit")
        incoming = json.loads(raw)
        if args.command in {"run", "submit"}:
            provenance = incoming.get("provenance") if isinstance(incoming, dict) else None
            if isinstance(provenance, dict) and provenance.get("executionMode") == "live":
                # No live path or fake fallback exists in the offline seam.
                raise ExtractionFailure("live_mode_unsupported")
        request = {"run": Submit, "submit": Submit, "review": Review, "revalidate": Revalidate}.get(args.command, Selector).model_validate(incoming)
        if args.command in {"inspect", "cancel", "review", "submit"} and (args.replay or args.verifier_replay):
            # Fixtures are per-call inputs of a later `run`/`resume`/`revalidate`; a submit freezes none of them.
            raise ExtractionFailure("fixture_not_allowed")
        fixtures = Fixtures(read_file(args.replay, MAX_REPLAY) if args.replay else None,
                            read_file(args.verifier_replay, MAX_REPLAY) if args.verifier_replay else None)
        authority = Authority(args.sources)
        store = Store(args.state_dir, args.extraction_state_dir, args.ingestion_state_dir)
        engine = Engine(store, Sources(args.ingestion_state_dir, authority), args.extraction_state_dir, args.ingestion_state_dir)
        if args.command == "run":
            result = engine.run(request, fixtures)
        elif args.command == "submit":
            # Registration only: freeze, then report the stored job. No execution, replay call or state change for an existing job.
            engine.freeze(request)
            result = engine.inspect(request.job_id)
        elif args.command == "resume":
            result = engine.resume(request.job_id, fixtures)
        elif args.command == "inspect":
            result = engine.inspect(request.job_id)
        elif args.command == "cancel":
            result = engine.cancel(request.job_id)
        elif args.command == "review":
            result = engine.review(request)
        else:
            result = engine.revalidate(request, fixtures)
        print(canonical(result))
        return 2 if result.get("delivery", {}).get("status") == "withheld" else 0
    except (ExtractionFailure, IngestionFailure) as exc:
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
