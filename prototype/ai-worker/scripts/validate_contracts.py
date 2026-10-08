#!/usr/bin/env python3
"""Validate the generated S1 JSON Schema subset and portable fixture without dependencies.

This validator intentionally handles the keywords emitted by contracts.py, not arbitrary JSON Schema.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/contracts/synthetic-document"


def validate(value, node, root):
    if "$ref" in node:
        target = root
        for segment in node["$ref"].removeprefix("#/").split("/"):
            target = target[segment.replace("~1", "/").replace("~0", "~")]
        validate(value, target, root)
        return
    if "anyOf" in node:
        for branch in node["anyOf"]:
            try:
                validate(value, branch, root)
                return
            except (ValueError, KeyError, TypeError):
                pass
        raise ValueError("anyOf mismatch")
    if "const" in node and value != node["const"]:
        raise ValueError("const mismatch")
    if "enum" in node and value not in node["enum"]:
        raise ValueError("enum mismatch")
    kind = node.get("type")
    checks = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
              "string": lambda v: isinstance(v, str), "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
              "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
              "boolean": lambda v: isinstance(v, bool), "null": lambda v: v is None}
    if kind and not checks[kind](value):
        raise ValueError("type mismatch")
    if isinstance(value, dict):
        if not set(node.get("required", [])) <= value.keys():
            raise ValueError("required field missing")
        props = node.get("properties", {})
        if node.get("additionalProperties") is False and not value.keys() <= props.keys():
            raise ValueError("additional property")
        for key, item in value.items():
            if key in props:
                validate(item, props[key], root)
            elif isinstance(node.get("additionalProperties"), dict):
                validate(item, node["additionalProperties"], root)
    if isinstance(value, list):
        if len(value) < node.get("minItems", 0) or "maxItems" in node and len(value) > node["maxItems"]:
            raise ValueError("array length mismatch")
        for item in value:
            validate(item, node.get("items", {}), root)
    if isinstance(value, str):
        if len(value) < node.get("minLength", 0) or "maxLength" in node and len(value) > node["maxLength"]:
            raise ValueError("string length mismatch")
        if "pattern" in node and re.search(node["pattern"], value) is None:
            raise ValueError("string pattern mismatch")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in node and value < node["minimum"] or "exclusiveMinimum" in node and value <= node["exclusiveMinimum"]:
            raise ValueError("minimum mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, action="append", default=[])
    args = parser.parse_args()
    schema = json.loads((ROOT / "docs/api/ai-contract.schema.json").read_text())
    checks = 0
    definitions = {"document-summary": "SummaryAnswer", "document-sentiment": "SentimentAnswer",
                   "semantic-verification": "VerificationAnswer", "briefing-outlook": "OutlookAnswer"}
    for fixture in (FIXTURE, FIXTURE.parent / "synthetic-outlook"):
        for request in json.loads((fixture / "jobs.json").read_text())["jobs"]:
            validate(request, {"$ref": "#/$defs/Submit"}, schema)
            checks += 1
        for grant in json.loads((fixture / "grants.json").read_text())["grants"]:
            validate(grant, {"$ref": "#/$defs/SourceGrant"}, schema)
            checks += 1
        for entry in json.loads((fixture / "replay.json").read_text())["responses"]:
            validate(entry["response"], {"$ref": "#/$defs/" + definitions[entry["stage"]]}, schema)
            checks += 1
    for path in args.result:
        validate(json.loads(path.read_text()), {"$ref": "#/$defs/JobResult"}, schema)
        checks += 1
    print(json.dumps({"status": "passed", "validatedRecords": checks, "schemaVersion": "zoop-ai-s1-1"}))


if __name__ == "__main__":
    main()
