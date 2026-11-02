#!/usr/bin/env python3
"""Review retained EC response bytes and complete DOM units without native admission."""
from __future__ import annotations

import argparse
from pathlib import Path

from zoop_ai_pipeline.ingestion_contracts import MAX_RAW, IngestionFailure, canonical, read_file
from zoop_ai_pipeline.ingestion_parsers import review_html_body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--media-type", choices=("application/json", "text/html"), required=True)
    parser.add_argument("--article-xpath", required=True)
    parser.add_argument("--unit-path", action="append", required=True)
    parser.add_argument("--expected-reference")
    parser.add_argument("--expected-language")
    args = parser.parse_args()
    try:
        result = review_html_body(read_file(args.raw, MAX_RAW), args.media_type, args.article_xpath, args.unit_path,
            expected_reference=args.expected_reference, expected_language=args.expected_language)
    except IngestionFailure as exc:
        print(canonical({"status": "refused", "code": exc.code}))
        return 2
    except OSError:
        print(canonical({"status": "refused", "code": "review_input_unavailable"}))
        return 2
    print(canonical(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
