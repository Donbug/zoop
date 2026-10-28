"""Prepare/verify portable local human-review inputs; never a model or scorer."""
import argparse
from pathlib import Path

from pydantic import ValidationError

from .corpus_review import annotations_check, prepare, verify
from .ingestion_contracts import IngestionFailure, canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("prepare")
    create.add_argument("--bindings", required=True, type=Path)
    create.add_argument("--output", required=True, type=Path)
    check = commands.add_parser("verify")
    check.add_argument("--pack", required=True, type=Path)
    annotate = commands.add_parser("annotations-check")
    annotate.add_argument("--pack", required=True, type=Path)
    annotate.add_argument("--annotations", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.bindings, args.output)
        elif args.command == "verify":
            result = verify(args.pack)
        else:
            result = annotations_check(args.pack, args.annotations)
        print(canonical(result))
        return 0
    except IngestionFailure as exc:
        print(canonical({"state": "refused", "error": {"code": exc.code}}))
        return 2
    except (OSError, ValueError, ValidationError, KeyError, TypeError, RecursionError):
        # Validation exceptions may include source text; never print their values or a traceback.
        print(canonical({"state": "refused", "error": {"code": "review_input_or_pack_invalid"}}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
