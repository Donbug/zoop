"""Finite Hacker News discovery metadata snapshots; no article fetch, model send or ingestion."""
import argparse
from pathlib import Path

from pydantic import ValidationError

from .hn_discovery import load_config, run, status
from .ingestion_contracts import IngestionFailure, canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "status"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        result = run(config, args.output) if args.command == "run" else status(config, args.output)
        # Do not echo link targets, titles or rejected upstream values into shell logs.
        summary = {key: result[key] for key in ("schemaVersion", "configDigest", "state", "provenance", "sourceRequests", "sourceBytes", "stopCode", "replayed")}
        summary.update({"selectedStories": len(result["selectedStoryIds"]), "candidates": len(result["candidates"]),
                        "dispositions": len(result["dispositions"])})
        print(canonical(summary))
        return 0 if result["state"] == "completed" else 2
    except IngestionFailure as exc:
        print(canonical({"state": "refused", "error": {"code": exc.code}}))
        return 2
    except (OSError, ValueError, ValidationError, TypeError, KeyError, OverflowError):
        print(canonical({"state": "refused", "error": {"code": "discovery_input_or_state_invalid"}}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
