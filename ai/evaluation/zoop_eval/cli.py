"""Command line: validate | controls | score | compare. JSON on stdout (exit 0 ok, 2 rejected), text with --format text."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .bench import DEFAULT_CORPUS, load_bench
from .compare import compare_scores
from .contracts import Rejected, read_json
from .controls import write_controls
from .report import render_compare, render_score
from .run import parse_run
from .scoring import score_run


def _emit(document: dict[str, Any], fmt: str, renderer, out: Path | None) -> None:
    if out:
        out.write_text(json.dumps(document, indent=1, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
    if fmt == "text":
        print(renderer(document))
    elif out is None:
        print(json.dumps(document, indent=1, ensure_ascii=False))


def _score_file(bench, path: str) -> dict[str, Any]:
    return score_run(bench, parse_run(read_json(Path(path)), bench))


def _validate(args) -> dict[str, Any]:
    bench = load_bench(args.corpus)
    return {
        "ok": True, "corpusId": bench.corpus_id, "corpusRevision": bench.corpus_revision, "goldRevision": bench.gold_revision,
        "inputsSha256": bench.inputs_sha256, "goldSha256": bench.gold_sha256,
        "goldProvenance": bench.gold_provenance,
        "counts": {
            "entities": len(bench.entities), "documents": len(bench.doc_split), "passages": len(bench.passages),
            "graphTasks": {s: len(bench.cases("graph", s)) for s in ("dev", "test")},
            "questions": {s: len(bench.cases("qa", s)) for s in ("dev", "test")},
            "goldEdges": len(bench.edges),
            "questionsByHop": {str(h): sum(1 for g in bench.gold_questions.values() if g["hop"] == h) for h in (1, 2, 3)},
            "questionsByKind": {k: sum(1 for g in bench.gold_questions.values() if g["kind"] == k)
                                for k in sorted({g["kind"] for g in bench.gold_questions.values()})},
        },
        "checks": ["schema/revision agreement", "unique ids and dangling references", "gold labels exactly cover tasks",
                   "dev/test document, origin-family and entity separation", "gold paths walk from anchor to answer",
                   "gold facts equal gold edges"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zoop_eval", description="Deterministic offline scoring of recorded outputs against authored gold. Makes no model, network or database calls.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "controls", "score", "compare"):
        p = sub.add_parser(name)
        p.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS, help="corpus directory (corpus.json, tasks.json, gold.json)")
        if name != "validate" and name != "controls":
            p.add_argument("--format", choices=("json", "text"), default="json")
            p.add_argument("--out", type=Path, help="also write the JSON document here")
        if name == "controls":
            p.add_argument("--out-dir", type=Path, required=True)
        if name == "score":
            p.add_argument("run", help="run file (zoop-bench-run-1)")
        if name == "compare":
            p.add_argument("runs", nargs="+", help="two or more run files")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            print(json.dumps(_validate(args), indent=1, ensure_ascii=False))
        elif args.command == "controls":
            bench = load_bench(args.corpus)
            print(json.dumps({"ok": True, "written": [str(p) for p in write_controls(bench, args.out_dir)],
                              "note": "authored controls: scorer sanity inputs, never measurements"}, indent=1))
        elif args.command == "score":
            bench = load_bench(args.corpus)
            _emit(_score_file(bench, args.run), args.format, render_score, args.out)
        else:
            bench = load_bench(args.corpus)
            _emit(compare_scores([_score_file(bench, p) for p in args.runs]), args.format, render_compare, args.out)
    except Rejected as exc:
        print(json.dumps({"ok": False, "error": exc.to_json()}, indent=1, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
