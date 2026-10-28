"""Operator-only S2-2 candidate process (authored replay or live provider); never a BFF route, S1 command or application publisher."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from pydantic import ValidationError

from .extraction import Extractor, Fixtures, Sources, Store, open_legacy_history
from .extraction_contracts import MAX_COMMAND, MAX_REPLAY, SCHEMA, EnqueueRound, ExtractionFailure, Selector, Submit, canonical
from .extraction_enqueue import enqueue_round
from .extraction_plan import plan_round, strict_json, verify_plan
from .ingestion_contracts import Authority, IngestionFailure, read_file


def enqueue(args, incoming) -> int:
    """`enqueue-round`: register one job per planned observation of a complete ingestion round, never execute it. The replay fixture is the frozen input of
    every replay job (required), a live job takes none; the topic fixture belongs to a later stage-time `resume`, never to registration."""
    request = EnqueueRound.model_validate(incoming)
    if args.initial_only:
        raise ExtractionFailure("initial_only_not_allowed")
    live = request.provenance.execution_mode == "live"
    if args.topic_replay or (live and args.replay):
        raise ExtractionFailure("fixture_not_allowed")
    if args.replay is None and not live:
        raise ExtractionFailure("replay_fixture_required")
    fixtures = Fixtures(read_file(args.replay, MAX_REPLAY) if args.replay else None, None)
    body, code = enqueue_round(request, fixtures, args.state_dir, args.ingestion_state_dir, args.sources)
    print(canonical(body))
    return code


def plan_service(args, incoming) -> int:
    """`plan-round`: write the immutable operator service plan of one complete round (see `extraction_plan`). It opens no extraction ledger (so it takes
    no `--state-dir`), freezes nothing and calls no model. A replay plan pins the replay fixture (and the topic fixture exactly when the descriptor asks
    for a topic stage); a live plan takes no fixture and pins the current live runtime identity."""
    request = EnqueueRound.model_validate(incoming)
    if args.initial_only or args.state_dir is not None:
        raise ExtractionFailure("plan_option_not_allowed")
    if args.principal is None or args.output is None:
        raise ExtractionFailure("plan_principal_and_output_required")
    live = request.provenance.execution_mode == "live"
    if live and (args.replay or args.topic_replay):
        raise ExtractionFailure("fixture_not_allowed")
    if args.replay is None and not live:
        raise ExtractionFailure("replay_fixture_required")
    fixtures = Fixtures(read_file(args.replay, MAX_REPLAY) if args.replay else None, read_file(args.topic_replay, MAX_REPLAY) if args.topic_replay else None)
    print(canonical(plan_round(request, fixtures, args.principal, args.ingestion_state_dir, args.sources, args.output)))
    return 0


def verify_service(args, incoming) -> int:
    """Read-only proof of the exact operator plan and current source-read authority, never a job or send grant."""
    if (incoming != {} or not isinstance(incoming, dict) or args.state_dir is not None or args.principal is not None
            or args.output is not None or args.initial_only or args.plan_dir is None or args.expected_receipt_sha256 is None):
        raise ExtractionFailure("plan_option_not_allowed")
    fixtures = Fixtures(read_file(args.replay, MAX_REPLAY) if args.replay else None,
                        read_file(args.topic_replay, MAX_REPLAY) if args.topic_replay else None)
    print(canonical(verify_plan(args.plan_dir, args.expected_receipt_sha256, fixtures, args.ingestion_state_dir, args.sources)))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "submit", "resume", "inspect", "cancel", "enqueue-round", "plan-round", "verify-plan"))
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--ingestion-state-dir", required=True, type=Path)
    parser.add_argument("--sources", required=True, type=Path)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--topic-replay", type=Path)
    parser.add_argument("--principal", help="plan-round only: the service principal the plan is written for")
    parser.add_argument("--output", type=Path, help="plan-round only: the new plan directory (must not exist unless it already holds this exact plan)")
    parser.add_argument("--plan-dir", type=Path, help="verify-plan only: exact existing operator plan directory")
    parser.add_argument("--expected-receipt-sha256", help="verify-plan only: operator-pinned receipt bytes SHA-256")
    parser.add_argument("--initial-only", action="store_true", help="automatic dispatch: refuse (initial_dispatch_taken) unless nothing has dispatched this job")
    args = parser.parse_args()
    if args.command not in {"plan-round", "verify-plan"} and (args.state_dir is None or args.principal is not None or args.output is not None):
        parser.error("--state-dir is required, and --principal/--output belong to plan-round only")
    store = None
    try:
        raw = sys.stdin.buffer.read(MAX_COMMAND + 1)
        if len(raw) > MAX_COMMAND:
            raise ExtractionFailure("command_input_limit")
        if args.command != "verify-plan" and (args.plan_dir is not None or args.expected_receipt_sha256 is not None):
            raise ExtractionFailure("plan_option_not_allowed")
        incoming = strict_json(raw) if args.command == "verify-plan" else json.loads(raw)
        if args.command == "verify-plan":
            return verify_service(args, incoming)
        if args.command == "plan-round":
            return plan_service(args, incoming)
        if args.command == "enqueue-round":
            return enqueue(args, incoming)
        if args.command in {"run", "submit"}:
            # Live is inferred from the request's provenance (the pair executionMode live / recordingKind provider); the provider runtime reads its own
            # environment lazily, so a replay job and inspect/cancel never need a gate, key or endpoint.
            request = Submit.model_validate(incoming)
        else:
            request = Selector.model_validate(incoming)
        if args.initial_only and args.command not in {"run", "resume"}:
            raise ExtractionFailure("initial_only_not_allowed")
        live = isinstance(request, Submit) and request.provenance.execution_mode == "live"
        if (args.command in {"inspect", "cancel"} or live) and (args.replay or args.topic_replay):
            raise ExtractionFailure("fixture_not_allowed")
        if args.command == "submit" and args.topic_replay:
            # The topic fixture is not part of the frozen job; only its stage-time `resume` may name it.
            raise ExtractionFailure("fixture_not_allowed")
        legacy = open_legacy_history(args.state_dir, args.ingestion_state_dir, request.job_id)
        if legacy is not None:
            # A stored pre-cutover job is history. Decide that from the ledger alone, BEFORE any fixture is required or parsed, any source authority is
            # read, or a writer is opened: inspect and the refusals use the read-only store, cancel (the one allowed change) takes the writer lock and
            # re-checks the identity there. No fixture, registry or source is consulted on this path.
            fixtures = Fixtures(None, None)
            if args.command == "cancel":
                legacy.close()
                store = Store(args.state_dir, args.ingestion_state_dir)
                extractor = Extractor(store, Sources(args.ingestion_state_dir, None))
                extractor.require_legacy(request.job_id)
            else:
                store = legacy
                extractor = Extractor(store, Sources(args.ingestion_state_dir, None))
        else:
            if args.command in {"run", "submit"} and args.replay is None and not live:
                raise ExtractionFailure("replay_fixture_required")
            fixtures = Fixtures(read_file(args.replay, MAX_REPLAY) if args.replay else None,
                                read_file(args.topic_replay, MAX_REPLAY) if args.topic_replay else None)
            authority = Authority(args.sources)
            store = Store(args.state_dir, args.ingestion_state_dir)
            extractor = Extractor(store, Sources(args.ingestion_state_dir, authority))
        if args.command == "run":
            result = extractor.run(request, fixtures, initial_only=args.initial_only)
        elif args.command == "submit":
            # Registration only: freeze, then report the stored job. No execution, replay call or state change for an existing job.
            extractor.freeze(request, fixtures)
            result = extractor.inspect(request.job_id)
        elif args.command == "resume":
            result = extractor.resume(request.job_id, fixtures, initial_only=args.initial_only)
        elif args.command == "inspect":
            result = extractor.inspect(request.job_id)
        else:
            result = extractor.cancel(request.job_id)
        print(canonical(result))
        return 2 if result.get("delivery", {}).get("status") == "withheld" else 0
    except (ExtractionFailure, IngestionFailure) as exc:
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": exc.code}}))
        return 2
    except (ValidationError, ValueError, TypeError, KeyError, OSError, AttributeError):
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": "input_or_configuration_invalid"}}))
        return 2
    except sqlite3.Error:
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": "persistence_failed"}}))
        return 2
    except Exception:
        # Never dump bodies, paths or provider text from an unexpected failure.
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": "extraction_internal_failure"}}))
        return 2
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
