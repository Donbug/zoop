"""Operator-only ISSUE SUMMARY job process (`zoop-ai-issue-summary`; authored replay or the bound live runtime). Never a BFF route, S1 command, handoff
writer, app writer or publisher: it reads the handoff inputs through the planner and writes only its own ledger.

stdin: one JSON object (<= 65,536 bytes): `{schemaVersion: "zoop-issue-summary-1", jobId, issueId, mode: "replay"|"live", manifest}` for `submit`/`run` (the
`manifest` is exactly the handoff `zoop-ai-handoff freeze` request; `issueId` is a PUBLIC issue of it) and `{schemaVersion, jobId}` for the others. stdout: one
canonical JSON object. Exit 0 for a ledger result, exit 2 for an error. A key and a model are touched only by `run`/`resume` of a LIVE job (the runtime is built
lazily from the environment); `submit`, `inspect`, `export` and `live-binding` never read keys and never call a model.

* `submit`: freeze the exact input as a `queued` job (registration only; nothing is executed or called). An issue with a HOLD/REJECT time verdict or too many quotes
  is refused before any row exists. * `run`: submit then resume. * `resume`: execute from the stored receipts; a started call without a receipt is never resent.
* `inspect`: the job record (read-only ledger + a fresh read-only plan). * `export`: the finished result's pin fields and its exact bundle `summary` (read-only, `ready` jobs
  only). Like the S2/S3 results, the stored result text is shown ONLY while the CURRENT source read/quote-display rights, the pinned sources/files and the frozen basis
  still prove; otherwise the output keeps identity, state and usage, carries `delivery: {status: withheld, code}` (exit 2) and no summary, outcome or digest. Model-send rights
  gate send, reply and completion only, never a later read. `ready` is not deliverable by itself.
* `cancel`: release a `queued` or `stopped` job that cannot finish (e.g. its manifest's pinned files moved): it becomes `failed` (`job_cancelled`, terminal) and a new
  job under the current manifest may be submitted; no source, key or model is touched, a `ready` or `failed` job is refused.
A writer that died leaves committed data in the WAL: a reader refuses it (`issue_summary_recovery_required`) until `resume` has settled the ledger. A ledger directory that is
not absent or empty but lacks its database or lock is `issue_summary_state_partial`: a writer never recreates lost history.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from pydantic import ValidationError

from .extraction_contracts import ExtractionFailure
from .handoff import HandoffPaths, plan_summary_input
from .handoff_contexts import configured, source_flags
from .ingestion_contracts import IngestionFailure, read_file
from .issue_summary import MAX_COMMAND, MAX_FIXTURE, Engine, Fixtures, Selector, Store, Submit
from .issue_summary_contracts import SCHEMA, canonical, digest
from .live_runtime import ISSUE_SUMMARY, LiveFailure, LiveRuntime

COMMANDS = ("submit", "run", "resume", "inspect", "export", "cancel", "live-binding")
SOURCED = frozenset({"submit", "run", "resume", "inspect", "export"})   # commands that consult the source ledgers, grants and the operator files
EXECUTING = frozenset({"run", "resume"})
READERS = frozenset({"inspect", "export"})


def _error(code: str, detail: dict | None = None) -> int:
    print(canonical({"schemaVersion": SCHEMA, "error": {"code": code, **({"detail": detail} if detail else {})}}))
    return 2


def _exported(result: dict) -> dict:
    """The pin fields (what an operator's decisions file needs) and the exact bundle `summary` of a `ready` job whose result is deliverable NOW. A `ready` job whose
    source rights or frozen basis no longer prove is `delivery: withheld` with a stable code: identity, state and usage only (no pin fields, outcome or text)."""
    if result["state"] != "ready":
        raise ExtractionFailure("issue_summary_not_ready", {"state": result["state"]})
    if result["result"] is None:
        return {"schemaVersion": SCHEMA, **{key: result[key] for key in ("jobId", "inputDigest", "issueId", "state", "delivery", "usage")}}
    return {"schemaVersion": SCHEMA, "jobId": result["jobId"], "inputDigest": result["inputDigest"], "resultDigest": result["result"]["resultDigest"],
            "issueId": result["issueId"], "outcome": result["result"]["outcome"], "provenance": result["provenance"], "summary": result["result"]["summary"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--relation-state-dir", type=Path)
    parser.add_argument("--extraction-state-dir", type=Path)
    parser.add_argument("--ingestion-state-dir", type=Path)
    parser.add_argument("--sources", type=Path, help="S1/S2 source and grant registry, consumed only through the owner seams")
    source_flags(parser)
    parser.add_argument("--canonical", type=Path, help="server-owned canonical decision registry (zoop-graph-canonical-1)")
    parser.add_argument("--decisions", type=Path, help="operator public-projection decisions (read through the planner; its summary pins are ignored)")
    parser.add_argument("--bindings", type=Path, help="server-owned app document bindings (zoop-app-document-bindings-1)")
    parser.add_argument("--fixture", type=Path, help="authored replay fixture (zoop-issue-summary-fixture-1; replay jobs only)")
    args = parser.parse_args()
    store = None
    try:
        if args.command == "live-binding":
            # Offline and keyless: the exact non-secret runtime configuration a live issue-summary job would freeze.
            if any(getattr(args, name) is not None for name in vars(args) if name != "command"):
                raise ExtractionFailure("input_or_configuration_invalid")
            binding = LiveRuntime.from_env(need_send=False, family=ISSUE_SUMMARY).binding()
            print(canonical({"schemaVersion": SCHEMA, "binding": binding, "bindingDigest": digest(binding)}))
            return 0
        sourced = args.command in SOURCED
        flags = (args.relation_state_dir, args.extraction_state_dir, args.ingestion_state_dir, args.sources, args.canonical, args.decisions, args.bindings)
        if args.state_dir is None or not configured(args, sourced=sourced) \
                or (sourced and any(f is None for f in flags[4:])) or (not sourced and any(f is not None for f in flags[4:])):
            raise ExtractionFailure("input_or_configuration_invalid")
        if args.fixture is not None and args.command not in EXECUTING:
            raise ExtractionFailure("fixture_not_allowed")
        raw = sys.stdin.buffer.read(MAX_COMMAND + 1)
        if len(raw) > MAX_COMMAND:
            raise ExtractionFailure("command_input_limit")
        # Every hostile or malformed input is refused here, before any ledger is opened or any state is touched.
        request = (Submit if args.command in {"submit", "run"} else Selector).model_validate(json.loads(raw))
        if args.command == "cancel":
            if not (args.state_dir / "issue-summary.sqlite3").is_file():
                raise ExtractionFailure("issue_summary_state_missing")          # a writer, but never the one that creates a ledger
            store = Store(args.state_dir)         # releases a queued/stopped job: no source, key or call
            print(canonical(Engine(store, None).cancel(request.job_id)))
            return 0
        paths = HandoffPaths(*flags, source_contexts=args.source_contexts, source_contexts_sha256=args.source_contexts_sha256)
        plan = lambda manifest, issue_id: plan_summary_input(paths, manifest, issue_id)  # noqa: E731
        if args.command in READERS:
            # Read-only ledger + a fresh read-only plan: the stored result is shown only while its source rights and frozen basis still prove (see Engine._delivery).
            store = Store(args.state_dir, *paths.roots(), mode="read")
            result = Engine(store, plan).inspect(request.job_id)
            out = _exported(result) if args.command == "export" else result
        else:
            fixtures = Fixtures(read_file(args.fixture, MAX_FIXTURE) if args.fixture else None)
            store = Store(args.state_dir, *paths.roots())
            factory = lambda need_send: LiveRuntime.from_env(need_send=need_send, family=ISSUE_SUMMARY)  # noqa: E731 - built lazily, only for a live job
            engine = Engine(store, plan, factory)
            if args.command == "run":
                out = engine.run(request, fixtures)
            elif args.command == "submit":
                # Registration only: freeze, then report the stored job. No execution, call or state change for an existing job.
                engine.freeze(request)
                out = engine.inspect(request.job_id)
            else:
                out = engine.resume(request.job_id, fixtures)
        print(canonical(out))
        return 2 if out.get("delivery", {}).get("status") == "withheld" else 0
    except (ExtractionFailure, IngestionFailure, LiveFailure) as exc:
        return _error(exc.code, getattr(exc, "detail", None))
    except (ValidationError, ValueError, TypeError, KeyError, OSError, AttributeError):
        return _error("input_or_configuration_invalid")
    except sqlite3.Error:
        return _error("persistence_failed")
    except Exception:  # noqa: BLE001 - never dump bodies, paths or provider text from an unexpected failure
        return _error("issue_summary_internal_failure")
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
