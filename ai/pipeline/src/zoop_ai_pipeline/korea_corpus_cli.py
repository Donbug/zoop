"""Bounded operator Korea portal run/status; module entrypoint needs no package reinstall."""
import argparse
from pathlib import Path

from pydantic import ValidationError

from .ingestion_contracts import IngestionFailure, canonical
from .korea_corpus import load_config, run, status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "status"))
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        result = run(config) if args.command == "run" else status(config)
        # Full bounded per-item details live in PACKAGE.json; stdout stays a compact summary.
        print(canonical({k: v for k, v in result.items() if k not in {"documents", "dispositions"}}))
        return 0 if result["state"] == "completed" else 2
    except IngestionFailure as exc:
        print(canonical({"state": "refused", "error": {"code": exc.code}}))
        return 2
    except (OSError, ValueError, ValidationError, KeyError, TypeError):
        print(canonical({"state": "refused", "error": {"code": "corpus_input_or_state_invalid"}}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
