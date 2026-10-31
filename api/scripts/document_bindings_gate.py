#!/usr/bin/env python3
"""Cross-language gate for the app's document bindings export.

Reads one `zoop-app-document-bindings-1` file the Spring operator command wrote (api/docs/DOCUMENT_BINDINGS.md) with the AI
pipeline's own strict contract (`zoop_ai_pipeline.handoff_contracts.Bindings`: exact keys, shapes, uniqueness, limits), so a
contract change on either side shows up here before a freeze refuses the file. It also checks the invariants the Java side
promises beyond the contract: sorted `(articleId, articleVersion)`, `documentId == articleId`, `documentVersion == articleVersion`
and, when `--result` names the run's result file, that its `count`, `bytes` and `sha256` describe exactly these bytes.

Run with the installed pipeline environment (`make pipeline-install` first):
    ai/pipeline/.venv/bin/python api/scripts/document_bindings_gate.py /abs/bindings.json [--result /abs/bindings-result.json]

Exit 0 when the file is valid, 1 with one line per finding otherwise, 2 when the pipeline package is not importable.
No network, no database, no model call.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

try:
    from zoop_ai_pipeline.handoff_contracts import MAX_OPERATOR_FILE, Bindings
except ImportError as error:  # pragma: no cover - environment, not logic
    print(f"zoop_ai_pipeline is not importable ({error.__class__.__name__}); run with ai/pipeline/.venv/bin/python",
          file=sys.stderr)
    sys.exit(2)

RESULT_SCHEMA = "zoop-document-bindings-result-1"


def findings(raw: bytes, result_raw: bytes | None) -> list[str]:
    """Every way the file (and, if given, the result) fails; empty when both are exactly what the contract and the app promise."""
    out: list[str] = []
    if len(raw) > MAX_OPERATOR_FILE:
        out.append(f"file is {len(raw)} bytes, over MAX_OPERATOR_FILE={MAX_OPERATOR_FILE}")
    try:
        parsed = Bindings.model_validate_json(raw)
    except Exception as error:  # pydantic ValidationError or a decode error: report the first line, never guess
        out.append(f"contract rejects the file: {error.__class__.__name__}: {str(error).splitlines()[0]}")
        return out
    keys = [(b.article_id, b.article_version) for b in parsed.bindings]
    if keys != sorted(keys):
        out.append("bindings are not sorted by (articleId, articleVersion)")
    for index, binding in enumerate(parsed.bindings):
        if binding.document_id != binding.article_id or binding.document_version != binding.article_version:
            out.append(f"bindings[{index}]: document identity differs from article identity")
    if result_raw is not None:
        out.extend(result_findings(raw, len(parsed.bindings), result_raw))
    return out


def result_findings(raw: bytes, count: int, result_raw: bytes) -> list[str]:
    try:
        result = json.loads(result_raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        return [f"result file is not JSON: {error.__class__.__name__}"]
    if not isinstance(result, dict) or result.get("schemaVersion") != RESULT_SCHEMA or result.get("status") != "succeeded":
        return [f"result file is not a succeeded {RESULT_SCHEMA}"]
    out: list[str] = []
    if result.get("count") != count:
        out.append(f"result count {result.get('count')} != {count} bindings in the file")
    if result.get("bytes") != len(raw):
        out.append(f"result bytes {result.get('bytes')} != {len(raw)} bytes in the file")
    if result.get("sha256") != hashlib.sha256(raw).hexdigest():
        out.append("result sha256 differs from the file's")
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bindings", type=Path, help="the zoop-app-document-bindings-1 file the app wrote")
    parser.add_argument("--result", type=Path, default=None, help=f"the run's {RESULT_SCHEMA} file")
    args = parser.parse_args(argv)
    raw = args.bindings.read_bytes()
    result_raw = args.result.read_bytes() if args.result is not None else None
    problems = findings(raw, result_raw)
    for problem in problems:
        print(problem)
    if not problems:
        count = len(Bindings.model_validate_json(raw).bindings)
        print(f"ok: {count} binding(s), {len(raw)} byte(s), sha256 {hashlib.sha256(raw).hexdigest()}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
