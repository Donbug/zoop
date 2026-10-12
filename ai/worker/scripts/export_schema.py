#!/usr/bin/env python3
"""Generate the language-neutral S1 JSON Schema (docs/api/ai-contract.schema.json) from the worker contracts.

Pure worker tool: it imports only the installed zoop_ai package and writes one file. Portable fixtures are produced by
the BFF-owned prototype/bff/scripts/export_contracts.py because they need BFF and PoC inputs.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from zoop_ai.contracts import AnalysisArtifact, JobResult, SourceGrant, Submit

ROOT = Path(__file__).resolve().parents[3]


def generate() -> dict:
    schema = TypeAdapter(Submit | JobResult | AnalysisArtifact | SourceGrant).json_schema(by_alias=True)
    schema.update({"$schema": "https://json-schema.org/draft/2020-12/schema",
                   "$id": "https://zoop.local/contracts/ai-s1-1.schema.json",
                   "title": "Zoop S1 AI process contract"})
    schema["$defs"]["AnalysisJob"] = {"$ref": "#/$defs/Submit"}
    target = ROOT / "docs" / "api" / "ai-contract.schema.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")
    return schema


if __name__ == "__main__":
    generate()
