"""Operator-only nonpublic S3 -> Neo4j version projection (FS080 slice). Never a BFF route, S1 command, publisher, activator or FS081 withdrawal.

stdin: one JSON object (<= 65,536 bytes). stdout: one canonical JSON object. Exit 0 for a ledger result or a current read; exit 2 for an error or a
withheld read. Neo4j credentials come only from the environment (ZOOP_GRAPH_AUTH=none|basic, ZOOP_GRAPH_USER, ZOOP_GRAPH_PASSWORD); the target
is chosen once by `init --graph-uri` and then only read from the ledger. No credential, URI, path or message is ever printed.
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
from .graph_projection import Paths, Projector, Store
from .graph_projection_contracts import MAX_COMMAND, SCHEMA, ExtractionFailure, Focus, Freeze, Init, Selector, canonical
from .ingestion_contracts import IngestionFailure

COMMANDS = ("init", "freeze", "project", "recover", "inspect", "read", "focus")
SOURCED = frozenset({"freeze", "project", "read", "focus"})   # commands that consult the source ledgers, grants and the canonical registry
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
    parser.add_argument("--sources", type=Path, help="S1/S2 source and grant registry, consumed only through the S3 owner seam")
    parser.add_argument("--canonical", type=Path, help="server-owned canonical decision registry (zoop-graph-canonical-1)")
    parser.add_argument("--graph-uri", help="init only: bolt://<loopback>:<port> or bolt+s://<host>:<port>")
    args = parser.parse_args()
    store = None
    try:
        sourced = args.command in SOURCED
        flags = (args.relation_state_dir, args.extraction_state_dir, args.ingestion_state_dir, args.sources, args.canonical)
        if (any(f is not None for f in flags) and not sourced) or (sourced and any(f is None for f in flags)) or (args.graph_uri is not None) != (args.command == "init"):
            raise ExtractionFailure("input_or_configuration_invalid")
        raw = sys.stdin.buffer.read(MAX_COMMAND + 1)
        if len(raw) > MAX_COMMAND:
            raise ExtractionFailure("command_input_limit")
        # Every hostile or malformed input is refused here, before any ledger is opened or any state is touched.
        request = {"init": Init, "freeze": Freeze, "focus": Focus}.get(args.command, Selector).model_validate(json.loads(raw))
        uri = neo.validate_uri(args.graph_uri) if args.command == "init" else None
        paths = Paths(args.relation_state_dir, args.extraction_state_dir, args.ingestion_state_dir, args.sources, args.canonical) if sourced else None
        roots = (paths.relation, paths.extraction, paths.ingestion) if paths else ()
        store = Store(args.state_dir, *roots, mode=WRITERS.get(args.command, "read"))
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
