"""Private acquisition, content-free status/catalogue and streaming immutable record pins."""
import argparse
import sqlite3
from pathlib import Path

from pydantic import ValidationError

from .ingestion_contracts import IngestionFailure, canonical
from .private_intake import load_config, retained_items, run
from .news_sources import source_catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "resume", "status", "sources", "records"))
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "sources":
            print(canonical({"schemaVersion": "zoop-private-news-sources-1", "sources": source_catalog()}))
            return 0
        if args.config is None:
            parser.error("--config is required for acquisition/status/records")
        config = load_config(args.config)
        if args.command == "records":
            for item in retained_items(config):
                print(canonical(item))
            return 0
        result = run(config, args.command)
        print(canonical(result))
        return 0 if result["state"] == "completed" else 2
    except IngestionFailure as exc:
        print(canonical({"state": "refused", "error": {"code": exc.code}}))
        return 2
    except (OSError, ValueError, ValidationError, TypeError, KeyError, OverflowError, RecursionError, sqlite3.DatabaseError):
        print(canonical({"state": "refused", "error": {"code": "private_input_or_state_invalid"}}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
