#!/usr/bin/env python3
"""Validate a content-free PostgreSQL inventory and its registered graph artifacts against an approved dataset manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

EXPECTATION_SCHEMA = "zoop-chat-data-expectation-1"
INVENTORY_SCHEMA = "zoop-chat-data-inventory-1"
REPORT_SCHEMA = "zoop-chat-data-readiness-1"
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}")
STORE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
SHA256 = re.compile(r"[0-9a-f]{64}")
COUNT_KEYS = {
    "companies", "articles", "availableArticles", "articleVersions", "evidence", "verifiedEvidence",
    "publishedBriefings", "nonFixtureGraphVersions",
}
GRAPH_COUNT_KEYS = {"issueCount", "relationCount", "articleCount"}
EXPECTATION_KEYS = {
    "schemaVersion", "datasetId", "activeGraphVersionId", "requirePreviousNonFixture", "expectedArtifactStoreId",
    "minimumCounts", "minimumActiveGraphCounts", "requiredCompanyIds",
}
INVENTORY_KEYS = {
    "schemaVersion", "database", "counts", "companyIds", "activeGraph", "previousNonFixtureGraph",
}
GRAPH_KEYS = {
    "id", "sequence", "kind", "active", "publishedAt", "issueCount", "relationCount", "articleCount", "snapshot",
    "sourceArtifacts",
}
ARTIFACT_KEYS = {"storageUri", "sha256", "bytes"}
SOURCE_ARTIFACT_KEYS = ARTIFACT_KEYS | {"role", "ordinal"}


class InvalidInput(ValueError):
    pass


def exact(value: dict[str, Any], keys: set[str], name: str) -> None:
    extra = set(value) - keys
    missing = keys - set(value)
    if extra or missing:
        raise InvalidInput(f"{name} keys differ: missing={sorted(missing)} extra={sorted(extra)}")


def load_object(path: Path, name: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InvalidInput(f"{name} is not readable JSON") from error
    if not isinstance(value, dict):
        raise InvalidInput(f"{name} must be an object")
    return value


def nonnegative_counts(value: Any, allowed: set[str], name: str) -> dict[str, int]:
    if not isinstance(value, dict) or not set(value).issubset(allowed):
        raise InvalidInput(f"{name} has unknown count keys")
    if any(type(count) is not int or count < 0 for count in value.values()):
        raise InvalidInput(f"{name} counts must be non-negative integers")
    return value


def expectation(path: Path) -> dict[str, Any]:
    value = load_object(path, "expectation")
    exact(value, EXPECTATION_KEYS, "expectation")
    if value["schemaVersion"] != EXPECTATION_SCHEMA:
        raise InvalidInput("unsupported expectation schemaVersion")
    if not isinstance(value["datasetId"], str) or not ID.fullmatch(value["datasetId"]):
        raise InvalidInput("datasetId is invalid")
    if not isinstance(value["activeGraphVersionId"], str) or not ID.fullmatch(value["activeGraphVersionId"]):
        raise InvalidInput("activeGraphVersionId is invalid")
    if type(value["requirePreviousNonFixture"]) is not bool:
        raise InvalidInput("requirePreviousNonFixture must be boolean")
    if not isinstance(value["expectedArtifactStoreId"], str) or not STORE_ID.fullmatch(value["expectedArtifactStoreId"]):
        raise InvalidInput("expectedArtifactStoreId is invalid")
    nonnegative_counts(value["minimumCounts"], COUNT_KEYS, "minimumCounts")
    nonnegative_counts(value["minimumActiveGraphCounts"], GRAPH_COUNT_KEYS, "minimumActiveGraphCounts")
    companies = value["requiredCompanyIds"]
    if not isinstance(companies, list) or not companies or len(companies) != len(set(companies)):
        raise InvalidInput("requiredCompanyIds must be a non-empty unique array")
    if any(not isinstance(company, str) or not ID.fullmatch(company) for company in companies):
        raise InvalidInput("requiredCompanyIds contains an invalid id")
    return value


def artifact(value: Any, name: str, *, source: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidInput(f"{name} must be an object")
    exact(value, SOURCE_ARTIFACT_KEYS if source else ARTIFACT_KEYS, name)
    if not isinstance(value["storageUri"], str) or not value["storageUri"].startswith("artifact-root:"):
        raise InvalidInput(f"{name}.storageUri is invalid")
    relative = value["storageUri"].removeprefix("artifact-root:")
    parts = relative.split("/")
    if len(parts) != 2 or any(not part or part in {".", ".."} for part in parts):
        raise InvalidInput(f"{name}.storageUri is invalid")
    if not isinstance(value["sha256"], str) or not SHA256.fullmatch(value["sha256"]):
        raise InvalidInput(f"{name}.sha256 is invalid")
    if type(value["bytes"]) is not int or value["bytes"] < 0 or value["bytes"] > 16 * 1024 * 1024:
        raise InvalidInput(f"{name}.bytes is invalid")
    if source and (value["role"] not in {"receipt", "bundle"} or type(value["ordinal"]) is not int
                   or value["ordinal"] < 0):
        raise InvalidInput(f"{name} source identity is invalid")
    return value


def graph(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidInput(f"{name} must be an object")
    exact(value, GRAPH_KEYS, name)
    if not isinstance(value["id"], str) or not ID.fullmatch(value["id"]):
        raise InvalidInput(f"{name}.id is invalid")
    if type(value["sequence"]) is not int or value["sequence"] < 0:
        raise InvalidInput(f"{name}.sequence is invalid")
    if value["kind"] not in {"fixture", "snapshot"} or type(value["active"]) is not bool:
        raise InvalidInput(f"{name} state is invalid")
    if value["publishedAt"] is not None and not isinstance(value["publishedAt"], str):
        raise InvalidInput(f"{name}.publishedAt is invalid")
    nonnegative_counts({key: value[key] for key in GRAPH_COUNT_KEYS}, GRAPH_COUNT_KEYS, name)
    artifact(value["snapshot"], f"{name}.snapshot")
    if not isinstance(value["sourceArtifacts"], list):
        raise InvalidInput(f"{name}.sourceArtifacts must be an array")
    for index, item in enumerate(value["sourceArtifacts"]):
        artifact(item, f"{name}.sourceArtifacts[{index}]", source=True)
    return value


def inventory(path: Path) -> dict[str, Any]:
    value = load_object(path, "inventory")
    exact(value, INVENTORY_KEYS, "inventory")
    if value["schemaVersion"] != INVENTORY_SCHEMA:
        raise InvalidInput("unsupported inventory schemaVersion")
    database = value["database"]
    if not isinstance(database, dict) or set(database) != {"postgresVersion", "latestMigration"}:
        raise InvalidInput("inventory.database is invalid")
    if not all(item is None or isinstance(item, str) for item in database.values()):
        raise InvalidInput("inventory.database values are invalid")
    counts = nonnegative_counts(value["counts"], COUNT_KEYS, "inventory.counts")
    if set(counts) != COUNT_KEYS:
        raise InvalidInput("inventory.counts is incomplete")
    companies = value["companyIds"]
    if not isinstance(companies, list) or len(companies) != len(set(companies)):
        raise InvalidInput("inventory.companyIds must be a unique array")
    if any(not isinstance(company, str) or not ID.fullmatch(company) for company in companies):
        raise InvalidInput("inventory.companyIds contains an invalid id")
    if value["activeGraph"] is not None:
        graph(value["activeGraph"], "inventory.activeGraph")
    if value["previousNonFixtureGraph"] is not None:
        graph(value["previousNonFixtureGraph"], "inventory.previousNonFixtureGraph")
    return value


def verify_file(root: Path, metadata: dict[str, Any]) -> str | None:
    relative = metadata["storageUri"].removeprefix("artifact-root:")
    target = root.joinpath(*relative.split("/"))
    try:
        resolved_root = root.resolve(strict=True)
        resolved = target.resolve(strict=True)
        resolved.relative_to(resolved_root)
        size = resolved.stat().st_size
    except (OSError, ValueError):
        return "artifact_missing_or_outside_root"
    if size != metadata["bytes"]:
        return "artifact_size_mismatch"
    try:
        content = resolved.read_bytes()
    except OSError:
        return "artifact_missing_or_outside_root"
    if len(content) != size:
        return "artifact_size_changed_during_read"
    if hashlib.sha256(content).hexdigest() != metadata["sha256"]:
        return "artifact_hash_mismatch"
    return None


def evaluate(expected: dict[str, Any], observed: dict[str, Any], artifact_root: Path) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []

    def fail(check: str, actual: Any = None, wanted: Any = None) -> None:
        item = {"check": check}
        if actual is not None:
            item["actual"] = actual
        if wanted is not None:
            item["expected"] = wanted
        failures.append(item)

    active = observed["activeGraph"]
    if active is None:
        fail("active_graph_missing")
    else:
        if active["id"] != expected["activeGraphVersionId"]:
            fail("active_graph_version", active["id"], expected["activeGraphVersionId"])
        if active["kind"] != "snapshot":
            fail("active_graph_nonfixture", active["kind"], "snapshot")
        if not active["active"] or active["publishedAt"] is None:
            fail("active_graph_not_published")
        for key, minimum in expected["minimumActiveGraphCounts"].items():
            if active[key] < minimum:
                fail(f"active_graph_count:{key}", active[key], minimum)
    previous = observed["previousNonFixtureGraph"]
    if expected["requirePreviousNonFixture"] and previous is None:
        fail("previous_nonfixture_graph_missing")
    if previous is not None and (previous["kind"] != "snapshot" or previous["publishedAt"] is None):
        fail("previous_nonfixture_graph_invalid")
    for key, minimum in expected["minimumCounts"].items():
        if observed["counts"][key] < minimum:
            fail(f"count:{key}", observed["counts"][key], minimum)
    missing_companies = sorted(set(expected["requiredCompanyIds"]) - set(observed["companyIds"]))
    if missing_companies:
        fail("required_companies_missing", missing_companies)

    marker = artifact_root / ".zoop-artifact-store-id"
    try:
        actual_store_id = marker.read_text(encoding="utf-8").strip()
    except OSError:
        actual_store_id = None
    if actual_store_id != expected["expectedArtifactStoreId"]:
        fail("artifact_store_id", actual_store_id, expected["expectedArtifactStoreId"])

    checked = 0
    for graph_name, value in (("active", active), ("previous", previous)):
        if value is None:
            continue
        items = [("snapshot", value["snapshot"])] + [
            (f"source:{item['role']}:{item['ordinal']}", item) for item in value["sourceArtifacts"]
        ]
        for artifact_name, metadata in items:
            checked += 1
            reason = verify_file(artifact_root, metadata)
            if reason:
                fail(f"{graph_name}_artifact:{artifact_name}:{reason}")

    return {
        "schemaVersion": REPORT_SCHEMA,
        "datasetId": expected["datasetId"],
        "status": "passed" if not failures else "failed",
        "activeGraphVersionId": None if active is None else active["id"],
        "previousNonFixtureGraphVersionId": None if previous is None else previous["id"],
        "artifactFilesChecked": checked,
        "counts": observed["counts"],
        "failures": failures,
    }


def write_new(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expectation", type=Path)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = evaluate(expectation(args.expectation), inventory(args.inventory), args.artifact_root)
        write_new(args.output, report)
    except (InvalidInput, FileExistsError, OSError) as error:
        print(f"invalid: {error}", file=sys.stderr)
        return 64
    print(json.dumps({key: report[key] for key in ("status", "datasetId", "activeGraphVersionId",
                                                   "artifactFilesChecked")}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
