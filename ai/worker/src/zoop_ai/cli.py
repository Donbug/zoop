"""Internal JSON process protocol. No env file is loaded implicitly and no command retries HTTP."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from .contracts import SCHEMA_VERSION, SourceGrant, Submit, canonical
from .provider import OpenAICompatibleProvider, ProviderError, ReplayProvider
from .runner import Runner
from .store import Store, WorkerFailure


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("submit", "run", "get", "resume", "cancel"))
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--grants", type=Path, help="Operator-owned current grant registry, never submitted model authority")
    parser.add_argument("--replay", type=Path, help="Exact authored synthetic replay recording")
    parser.add_argument("--initial-only", action="store_true",
                        help="Internal automatic-redispatch permission for run/resume. Under the job lock the runner may only start a "
                             "job that has never made a call; once any call record exists it may only persist already stored "
                             "receipts and never reserves or sends a stage.")
    args = parser.parse_args()
    store = provider = None
    try:
        incoming = json.load(sys.stdin)
        if args.initial_only and args.command not in {"run", "resume"}:
            raise WorkerFailure("command_input_invalid")
        store = Store(args.state_dir)
        if args.grants and args.command in {"submit", "run", "resume"}:
            registry = json.loads(args.grants.read_text(encoding="utf-8"))
            if registry.get("schemaVersion") != SCHEMA_VERSION:
                raise WorkerFailure("grant_registry_schema_invalid")
            store.register_grants([SourceGrant.model_validate(g) for g in registry["grants"]])
        runner = Runner(store, live_enabled=os.environ.get("ZOOP_AI_LIVE_ENABLED") == "1",
                        max_calls=int(os.environ.get("ZOOP_AI_GLOBAL_MAX_CALLS", "0")))
        if args.command == "submit":
            result = runner.submit(Submit.model_validate(incoming))
        else:
            if set(incoming) != {"schemaVersion", "jobId"} or incoming["schemaVersion"] != SCHEMA_VERSION:
                raise WorkerFailure("command_input_invalid")
            job_id = incoming["jobId"]
            request = runner.get(job_id).input
            # Get/cancel never construct a model client. Resume is receipt-only whenever receipts already exist.
            if args.command in {"run", "resume"} and runner.get(job_id).state not in {"ready", "reconciling", "cancelled"}:
                calls = store.calls(job_id)
                required = {request.kind} if request.kind in {"semantic-verification", "briefing-outlook"} else {request.kind, "semantic-verification"}
                received = {c["stage"] for c in calls if c["receipt"] is not None}
                empty_outlook = request.kind == "briefing-outlook" and not request.input.issues
                # initial-only: no provider is even built once a call record exists (the runner re-checks this under the job lock).
                if (not empty_outlook and not required <= received and not (args.initial_only and calls)
                        and not any(c["state"] in {"started", "unknown", "failed"} for c in calls)):
                    if request.mode == "replay":
                        if not args.replay:
                            raise WorkerFailure("replay_fixture_required")
                        provider = ReplayProvider(args.replay)
                    else:
                        if not runner.live_enabled or runner.max_calls <= 0:
                            raise WorkerFailure("live_opt_in_and_budget_required")
                        provider = OpenAICompatibleProvider(base_url=os.environ.get("ZOOP_AI_BASE_URL", "https://api.openai.com/v1"),
                                                            api_key=os.environ.get("ZOOP_AI_API_KEY", ""))
                    runner.provider = provider
            result = (getattr(runner, args.command)(job_id, initial_only=True) if args.initial_only
                      else getattr(runner, args.command)(job_id))
        print(canonical(result.wire()))
        return 0
    except (WorkerFailure, ProviderError) as exc:
        print(canonical({"schemaVersion": SCHEMA_VERSION, "error": {"code": exc.code}}))
        return 2
    except (ValidationError, ValueError, KeyError, TypeError, OSError):
        print(canonical({"schemaVersion": SCHEMA_VERSION, "error": {"code": "input_or_configuration_invalid"}}))
        return 2
    finally:
        if provider:
            provider.close()
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
