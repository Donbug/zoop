"""Internal JSON process protocol. No env file is loaded implicitly and no command retries HTTP."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from .contracts import SCHEMA_VERSION, SourceGrant, StageConfig, Submit, canonical
from .doctor import PROFILES, build_report, render_text
from .provider import (DEFAULT_BASE_URL, NATIVE_DEFAULT_BASE_URL, NATIVE_PROVIDER, NativeJevProvider, OpenAICompatibleProvider,
                       ProviderError, ReplayProvider)
from .runner import Runner
from .store import Store, WorkerFailure


def live_provider(name: str):
    """The one place a live client is built. Keys come only from this process's environment and only for the named provider."""
    if name == NATIVE_PROVIDER:
        return NativeJevProvider(base_url=os.environ.get("TYPESAFE_BASE_URL", NATIVE_DEFAULT_BASE_URL),
                                 api_key=os.environ.get("TYPESAFE_API_KEY", ""))
    if name == "openai-compatible":
        return OpenAICompatibleProvider(base_url=os.environ.get("ZOOP_AI_BASE_URL", DEFAULT_BASE_URL),
                                        api_key=os.environ.get("ZOOP_AI_API_KEY", ""))
    raise ProviderError("provider_unsupported")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("submit", "run", "get", "resume", "cancel", "config-check"))
    parser.add_argument("--state-dir", type=Path, help="Worker ledger directory; required for every command except config-check")
    parser.add_argument("--grants", type=Path, help="Operator-owned current grant registry, never submitted model authority")
    parser.add_argument("--replay", type=Path, help="Exact authored synthetic replay recording")
    parser.add_argument("--initial-only", action="store_true",
                        help="Internal automatic-redispatch permission for run/resume. Under the job lock the runner may only start a "
                             "job that has never made a call; once any call record exists it may only persist already stored "
                             "receipts and never reserves or sends a stage.")
    parser.add_argument("--profile", choices=PROFILES, default="s1-openai-compatible",
                        help="config-check only. The default expects every S1 stage on the OpenAI-compatible adapter; native-jev expects "
                             "semantic-verification on the native Jev adapter (ZOOP_AI_VERIFY_PROVIDER=typesafe-native)")
    parser.add_argument("--format", choices=("json", "text"), default="json", help="config-check output")
    parser.add_argument("--require-live-prerequisites", action="store_true",
                        help="config-check only: exit 2 also when a live prerequisite (gate flag, positive ceiling, key, stage model) is missing")
    args = parser.parse_args()
    if args.command == "config-check":
        # Offline: reads this process's environment only; never touches stdin, state, grants or the network.
        if args.state_dir or args.grants or args.replay or args.initial_only:
            parser.error("config-check accepts only --profile, --format and --require-live-prerequisites")
        report = build_report(args.profile)
        print(canonical(report) if args.format == "json" else render_text(report))
        return 0 if report["configValid"] and (report["liveEnvironmentReady"] or not args.require_live_prerequisites) else 2
    if args.state_dir is None:
        parser.error("the following arguments are required: --state-dir")
    if args.profile != "s1-openai-compatible" or args.format != "json" or args.require_live_prerequisites:
        parser.error("--profile, --format and --require-live-prerequisites are config-check only")
    store, opened = None, []
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
                frozen = {k: StageConfig.model_validate(v) for k, v in json.loads(store.job(job_id)["configs"]).items()}
                received = {c["stage"] for c in calls if c["receipt"] is not None}
                empty_outlook = request.kind == "briefing-outlook" and not request.input.issues
                # initial-only: no provider is even built once a call record exists (the runner re-checks this under the job lock).
                if (not empty_outlook and not frozen.keys() <= received and not (args.initial_only and calls)
                        and not any(c["state"] in {"started", "unknown", "failed"} for c in calls)):
                    if request.mode == "replay":
                        if not args.replay:
                            raise WorkerFailure("replay_fixture_required")
                        runner.provider = ReplayProvider(args.replay)
                        opened.append(runner.provider)
                    else:
                        if not runner.live_enabled or runner.max_calls <= 0:
                            raise WorkerFailure("live_opt_in_and_budget_required")
                        # Only a stage that still needs a call gets a client, built for the provider the job was FROZEN with: a key
                        # is needed only for those, and today's environment never re-routes a stored job.
                        for name in sorted({frozen[stage].provider for stage in frozen.keys() - received}):
                            client = live_provider(name)
                            opened.append(client)
                            if name == NATIVE_PROVIDER:
                                runner.verifier = client
                            else:
                                runner.provider = client
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
        for client in opened:
            client.close()
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
