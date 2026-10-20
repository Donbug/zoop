"""Operator-only AI -> backend public graph HANDOFF (`zoop-ai-handoff`). Never a BFF route, S1 command, app writer, activator, publisher or FS081 withdrawal.

stdin: one JSON object (<= 65,536 bytes): the manifest for `freeze`, `{schemaVersion, handoffId}` for the others. stdout: one canonical JSON object.
Exit 0 for a ledger result or a current export; exit 2 for an error or a withheld export (`delivery.status=withheld`, no content). No network, model or
provider call; no source ledger is written. No credential, path or message is ever printed.

A handoff stored under an older bundle contract is history: it is recognised from the ledger alone, before any operator file, source ledger, grant, artifact or
writable ledger is touched, and is answered read-only (`inspect` history, `export` withheld, `recover`/`freeze` refused: `handoff_contract_changed`).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from pydantic import ValidationError

from .handoff import Handoff, HandoffPaths, Store, open_legacy_history
from .handoff_contracts import MAX_COMMAND, SCHEMA, ExtractionFailure, Manifest, Selector, canonical
from .ingestion_contracts import IngestionFailure

COMMANDS = ("freeze", "recover", "inspect", "export")
SOURCED = frozenset({"freeze", "export"})                  # commands that consult the source ledgers, grants and the operator files
WRITERS = {"freeze": "create", "recover": "write"}          # everything else opens the ledger read-only


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
    parser.add_argument("--decisions", type=Path, help="operator public-projection decisions (zoop-public-decisions-1)")
    parser.add_argument("--bindings", type=Path, help="server-owned app document bindings (zoop-app-document-bindings-1)")
    args = parser.parse_args()
    store = None
    try:
        sourced = args.command in SOURCED
        flags = (args.relation_state_dir, args.extraction_state_dir, args.ingestion_state_dir, args.sources, args.canonical, args.decisions, args.bindings)
        if (any(f is not None for f in flags) and not sourced) or (sourced and any(f is None for f in flags)):
            raise ExtractionFailure("input_or_configuration_invalid")
        raw = sys.stdin.buffer.read(MAX_COMMAND + 1)
        if len(raw) > MAX_COMMAND:
            raise ExtractionFailure("command_input_limit")
        # Every hostile or malformed input is refused here, before any ledger is opened or any state is touched.
        request = (Manifest if args.command == "freeze" else Selector).model_validate(json.loads(raw))
        paths = HandoffPaths(*flags) if sourced else None
        roots = (paths.relation, paths.extraction, paths.ingestion) if paths else ()
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
