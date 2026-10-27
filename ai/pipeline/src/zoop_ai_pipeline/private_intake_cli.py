"""Bounded private news run/resume/status. Article content is never printed."""
import argparse
from pathlib import Path

from pydantic import ValidationError

from .ingestion_contracts import IngestionFailure, canonical
from .private_intake import load_config, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "resume", "status"))
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        result = run(config, args.command)
        print(canonical(result))
        return 0 if result["state"] == "completed" else 2
    except IngestionFailure as exc:
        print(canonical({"state": "refused", "error": {"code": exc.code}}))
        return 2
    except (OSError, ValueError, ValidationError, TypeError, KeyError, OverflowError, RecursionError):
        print(canonical({"state": "refused", "error": {"code": "private_input_or_state_invalid"}}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
