"""Operator-only AI -> backend public graph HANDOFF (`zoop-ai-handoff`). Never a BFF route, S1 command, app writer, activator, publisher or FS081 withdrawal.

stdin: one JSON object (<= 65,536 bytes): the manifest for `freeze`, `{schemaVersion, handoffId}` for the others. stdout: one canonical JSON object.
Exit 0 for a ledger result or a current export; exit 2 for an error or a withheld export (`delivery.status=withheld`, no content). No network, model or
provider call; no source ledger is written (a freeze whose decisions pin an issue-summary result reads that job ledger read-only; export never opens it). No credential,
path or message is ever printed.

`freeze-round --round-id R [--plan-id P --plan-root DIR] --files-dir DIR` reads no stdin: it recomputes the 20-job S3 window from the ledgers, narrows the master
`--canonical`/`--decisions` files to it, freezes the result through the same strict path as `freeze` and installs the narrowed files in `--files-dir`
(the files `export` is then given). It prints the handoff result with the selection report (`handoff_round`).

A handoff stored under an older bundle contract is history: it is recognised from the ledger alone, before any operator file, source ledger, grant, artifact or
writable ledger is touched, and is answered read-only (`inspect` history, `export` withheld, `recover`/`freeze` refused: `handoff_contract_changed`).
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

from pydantic import ValidationError

from .handoff import Handoff, HandoffPaths, Store, open_legacy_history
from .handoff_contracts import MAX_COMMAND, SCHEMA, ExtractionFailure, Manifest, Selector, canonical
from .handoff_round import RoundPaths, freeze_round
from .ingestion_contracts import IngestionFailure

COMMANDS = ("freeze", "freeze-round", "recover", "inspect", "export")
SOURCED = frozenset({"freeze", "export"})                  # commands that consult the source ledgers, grants and the operator files
WRITERS = {"freeze": "create", "recover": "write"}          # everything else opens the ledger read-only
PLAN_ID = re.compile(r"s2plan-[0-9a-f]{64}")
ROUND_FLAGS = ("round_id", "plan_id", "plan_root", "files_dir")


def _error(code: str, detail: dict | None = None) -> int:
    print(canonical({"schemaVersion": SCHEMA, "error": {"code": code, **({"detail": detail} if detail else {})}}))
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--relation-state-dir", type=Path)
    parser.add_argument("--extraction-state-dir", type=Path)
    parser.add_argument("--ingestion-state-dir", type=Path)
    parser.add_argument("--sources", type=Path, help="S1/S2 source and grant registry, consumed only through the owner seams")
    parser.add_argument("--canonical", type=Path, help="server-owned canonical decision registry (zoop-graph-canonical-1)")
    parser.add_argument("--decisions", type=Path, help="operator public-projection decisions (zoop-public-decisions-3, with per-issue fieldVerdicts and summary pin)")
    parser.add_argument("--bindings", type=Path, help="server-owned app document bindings (zoop-app-document-bindings-1)")
    parser.add_argument("--issue-summary-state-dir", type=Path,
                        help="freeze and freeze-round only, and only when the decisions pin an issue-summary result: the `zoop-ai-issue-summary` ledger it is read from (read-only; export never needs it)")
    parser.add_argument("--round-id", help="freeze-round: the observation round this freeze belongs to (its S3 jobs must all be done)")
    parser.add_argument("--plan-id", help="freeze-round: the immutable plan (s2plan-...) admitted for that round; omitted for a slot without a new plan")
    parser.add_argument("--plan-root", type=Path, help="freeze-round: the directory holding the plan directories (with --plan-id)")
    parser.add_argument("--files-dir", type=Path, help="freeze-round: where the narrowed canonical.json and decisions.json of the handoff are installed (--canonical/--decisions are then the MASTER files)")
    args = parser.parse_args()
    store = None
    try:
        rounded = args.command == "freeze-round"
        sourced = args.command in SOURCED or rounded
        flags = (args.relation_state_dir, args.extraction_state_dir, args.ingestion_state_dir, args.sources, args.canonical, args.decisions, args.bindings)
        round_args = tuple(getattr(args, name) for name in ROUND_FLAGS)
        if (any(f is not None for f in flags) and not sourced) or (sourced and any(f is None for f in flags)) \
                or (args.issue_summary_state_dir is not None and args.command not in ("freeze", "freeze-round")) \
                or (any(a is not None for a in round_args) and not rounded) \
                or (rounded and (not args.round_id or len(args.round_id) > 200 or args.files_dir is None or (args.plan_id is None) != (args.plan_root is None)
                                 or (args.plan_id is not None and not PLAN_ID.fullmatch(args.plan_id)))):
            raise ExtractionFailure("input_or_configuration_invalid")
        if rounded:
            roots = (args.relation_state_dir, args.extraction_state_dir, args.ingestion_state_dir, *([args.issue_summary_state_dir] if args.issue_summary_state_dir else []))
            store = Store(args.state_dir, *roots, mode="create")
            paths = RoundPaths(*flags, files_dir=args.files_dir, plan_root=args.plan_root, summaries=args.issue_summary_state_dir)
            print(canonical(freeze_round(store, paths, args.round_id, args.plan_id)))
            return 0
        raw = sys.stdin.buffer.read(MAX_COMMAND + 1)
        if len(raw) > MAX_COMMAND:
            raise ExtractionFailure("command_input_limit")
        # Every hostile or malformed input is refused here, before any ledger is opened or any state is touched.
        request = (Manifest if args.command == "freeze" else Selector).model_validate(json.loads(raw))
        paths = HandoffPaths(*flags, summaries=args.issue_summary_state_dir) if sourced else None
        roots = (paths.relation, paths.extraction, paths.ingestion, *([paths.summaries] if paths.summaries is not None else [])) if paths else ()
        legacy = open_legacy_history(args.state_dir, *roots, handoff_id=request.handoff_id)
        store = legacy if legacy is not None else Store(args.state_dir, *roots, mode=WRITERS.get(args.command, "read"))
        handoff = Handoff(store, paths)
        if args.command == "export":
            result, line = handoff.export(request, serialized=True)
            print(line)
        else:
            result = getattr(handoff, args.command)(request)
            print(canonical(result))
        return 2 if result.get("delivery", {}).get("status") == "withheld" else 0
    except (ExtractionFailure, IngestionFailure) as exc:
        return _error(exc.code, getattr(exc, "detail", None))
    except (ValidationError, ValueError, TypeError, KeyError, OSError, AttributeError):
        return _error("input_or_configuration_invalid")
    except sqlite3.Error:
        return _error("persistence_failed")
    except Exception:  # noqa: BLE001 - never dump bodies, paths or messages from an unexpected failure
        return _error("handoff_internal_failure")
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
