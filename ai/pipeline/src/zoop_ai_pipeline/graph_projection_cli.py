"""Operator-only nonpublic S3 -> Neo4j version projection (FS080 slice). Never a BFF route, S1 command, publisher, activator or FS081 withdrawal.

stdin: one JSON object (<= 65,536 bytes). stdout: one canonical JSON object. Exit 0 for a ledger result or a current read; exit 2 for an error or a
withheld read. Neo4j credentials come only from the environment (ZOOP_GRAPH_AUTH=none|basic, ZOOP_GRAPH_USER, ZOOP_GRAPH_PASSWORD); the target
is chosen once by `init --graph-uri` and then only read from the ledger. No credential, URI, path or message is ever printed.

`preflight` takes the same stdin and `--graph-uri` as `init` plus the intended `--state-dir`, and is the only command that never touches a ledger: it
creates, opens, locks and chmods nothing, runs no DDL and no write transaction, and answers only whether the target is a reachable (TLS-verified when
`bolt+s`), authenticated, empty Neo4j 5 database that `init` could then bind. It is not a promise that `init` will succeed (DDL permission and later
changes are not provable read-only), and it never replaces the idempotent `init` re-run as the check of an existing binding.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from neo4j.exceptions import DriverError, Neo4jError
from pydantic import ValidationError

from . import graph_neo4j as neo
from .graph_projection import Paths, Projector, Store, open_legacy_history, preflight, preflight_analysis
from .graph_projection_contracts import MAX_COMMAND, SCHEMA, ExtractionFailure, Focus, Freeze, Init, Selector, canonical
from .ingestion_contracts import IngestionFailure

COMMANDS = ("init", "preflight", "freeze", "project", "recover", "inspect", "read", "focus")
SOURCED = frozenset({"freeze", "project", "read", "focus"})   # commands that consult the source ledgers, grants and the canonical registry
TARGETED = frozenset({"init", "preflight"})   # commands that take the Neo4j target (`--graph-uri`) and the Init request
WRITERS = {"init": "create", "freeze": "write", "project": "write", "recover": "write"}   # everything else opens the ledger read-only


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
    authority_options = parser.add_mutually_exclusive_group()
    authority_options.add_argument("--sources", type=Path, help="public source/grant registry")
    authority_options.add_argument("--private-processing", type=Path, help="private execution receipt; never public handoff authority")
    parser.add_argument("--canonical", type=Path, help="server-owned canonical decision registry (zoop-graph-canonical-1)")
    parser.add_argument("--graph-uri", help="init and preflight only: bolt://<loopback>:<port> or bolt+s://<host>:<port>")
    args = parser.parse_args()
    store = None
    try:
        sourced = args.command in SOURCED
        flags = (args.relation_state_dir, args.extraction_state_dir, args.ingestion_state_dir, args.sources or args.private_processing, args.canonical)
        if (any(f is not None for f in flags) and not sourced) or (sourced and any(f is None for f in flags)) or (args.graph_uri is not None) != (args.command in TARGETED):
            raise ExtractionFailure("input_or_configuration_invalid")
        raw = sys.stdin.buffer.read(MAX_COMMAND + 1)
        if len(raw) > MAX_COMMAND:
            raise ExtractionFailure("command_input_limit")
        # Every hostile or malformed input is refused here, before any ledger is opened or any state is touched.
        request = {"init": Init, "preflight": Init, "freeze": Freeze, "focus": Focus}.get(args.command, Selector).model_validate(json.loads(raw))
        uri = neo.validate_uri(args.graph_uri) if args.command in TARGETED else None
        if args.command == "preflight":
            # Before any Store: this command must never create, open, lock or chmod a ledger.
            print(canonical(preflight(request, uri, args.state_dir)))
            return 0
        paths = Paths(args.relation_state_dir, args.extraction_state_dir, args.ingestion_state_dir,
                      args.sources, args.canonical, args.private_processing) if sourced else None
        roots = (paths.relation, paths.extraction, paths.ingestion) if paths else ()
        # A version frozen under an earlier plan contract is history: decided from the ledger alone, read-only, BEFORE any writer (chmod, WAL checkpoint, DDL)
        # is opened. `init` has no version yet.
        legacy = None if args.command == "init" else open_legacy_history(args.state_dir, *roots, version_id=request.version_id)
        if legacy is None and args.command in {"freeze", "project", "recover"}:
            preflight_analysis(args.state_dir, paths, request)
        store = legacy if legacy is not None else Store(args.state_dir, *roots, mode=WRITERS.get(args.command, "read"))
        projector = Projector(store, paths)
        if args.command == "init":
            result = projector.init(request, uri)
        elif args.command == "freeze":
            result = projector.freeze(request)
        elif args.command == "project":
            result = projector.project(request)
        elif args.command == "recover":
            result = projector.recover(request)
        elif args.command == "inspect":
            result = projector.inspect(request)
        else:
            result = projector.read(request)
        print(canonical(result))
        return 2 if result.get("delivery", {}).get("status") == "withheld" else 0
    except (ExtractionFailure, IngestionFailure) as exc:
        return _error(exc.code, getattr(exc, "detail", None))
    except (DriverError, Neo4jError) as exc:
        failure = neo.translate(exc)
        return _error(failure.code, failure.detail)
    except (ValidationError, ValueError, TypeError, KeyError, OSError, AttributeError):
        return _error("input_or_configuration_invalid")
    except sqlite3.Error:
        return _error("persistence_failed")
    except Exception:  # noqa: BLE001 - never dump bodies, paths, URIs or driver messages from an unexpected failure
        return _error("graph_internal_failure")
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
