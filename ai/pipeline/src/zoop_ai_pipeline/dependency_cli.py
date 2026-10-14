"""Operator-only offline S4 dependents report: which stored S2/S3 jobs and candidates rest on a changed document/source/grant.

Read-only identity lookup over the ingestion and extraction ledgers (and optionally one relation ledger). It evaluates no authority,
registry, rights or delivery, writes nothing, calls no model and revokes/withholds/regenerates/publishes nothing; never a BFF route or S1 command.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import ExitStack, closing
from pathlib import Path

from pydantic import ValidationError

from . import extraction, ingestion, relation
from .dependency_contracts import (BASIS, CONSISTENCY, EFFECT, MAX_COMMAND, MAX_REPORT_ENTRIES, NOT_COVERED, SCHEMA, ExtractionFailure, Query,
    matcher)
from .ingestion_contracts import IngestionFailure, canonical

# Codes that are ambiguous without naming the ledger they came from.
_LEDGER_CODES = {"state_namespace_conflict", "state_namespace_invalid", "ledger_version_unknown", "dependency_record_invalid"}


def _counts(extracted: dict, related: dict | None) -> dict:
    jobs = extracted["jobs"]
    return {"extraction": {"jobs": len(jobs), **{name: sum(len(j[name]) for j in jobs)
                                                 for name in ("matchedDocuments", "snapshotEvents", "eventCandidates", "comparisons", "topicCandidates")}},
            "relation": None if related is None else {"jobs": len(related["jobs"]), "unresolvedJobs": len(related["unresolved"]),
                                                      **{name: sum(len(j[name]) for j in related["jobs"]) for name in ("relationCandidates", "impactCandidates")}}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ingestion-state-dir", required=True, type=Path)
    parser.add_argument("--extraction-state-dir", required=True, type=Path)
    parser.add_argument("--relation-state-dir", type=Path, help="optional; when omitted the report's relation section is null, never an empty result")
    args = parser.parse_args()
    ledger = "input"
    try:
        raw = sys.stdin.buffer.read(MAX_COMMAND + 1)
        if len(raw) > MAX_COMMAND:
            raise ExtractionFailure("command_input_limit")
        query = Query.model_validate(json.loads(raw))
        changed = query.changed.wire()
        # Every opened ledger keeps its shared lock from the first read until the report is written (closed in reverse order), and every
        # pipeline writer takes an exclusive non-blocking lock, so no ledger can change under this read; a writer that starts meanwhile fails busy.
        with ExitStack() as stack:
            ledger = "ingestion"
            ingestion_store = stack.enter_context(closing(ingestion.Store(args.ingestion_state_dir, existing=True)))
            ledger = "extraction"
            extraction_store = stack.enter_context(closing(extraction.Store(args.extraction_state_dir, args.ingestion_state_dir, existing=True)))
            relation_store = None
            if args.relation_state_dir is not None:
                ledger = "relation"
                relation_store = stack.enter_context(closing(relation.Store(args.relation_state_dir, args.extraction_state_dir, args.ingestion_state_dir, existing=True)))
            ledger = "ingestion"
            recorded = ingestion.recorded(ingestion_store, changed)
            ledger = "extraction"
            extracted, index = extraction.dependents(extraction_store, matcher(query.changed))
            bound = bool(extracted["jobs"])
            if not bound and not recorded:
                # A typo or foreign identity must never become a success-empty report.
                raise ExtractionFailure("changed_identity_unknown")
            related = None
            if relation_store is not None:
                ledger = "relation"
                related = relation.dependents(relation_store, index)
            counts = _counts(extracted, related)
            entries = sum(sum(group.values()) for group in counts.values() if group is not None)
            if entries > MAX_REPORT_ENTRIES:
                # Never truncated: a partial list could be read as complete.
                raise ExtractionFailure("dependency_report_limit", {"entries": entries, "limit": MAX_REPORT_ENTRIES})
            print(canonical({"schemaVersion": SCHEMA, "changed": changed, "identity": {"bound": bound, "recordedInIngestion": recorded},
                             "basis": BASIS, "consistency": CONSISTENCY, "notCovered": list(NOT_COVERED), "extraction": extracted, "relation": related,
                             "counts": counts, "effect": EFFECT, "usage": {"providerCalls": 0, "modelCalls": 0}}))
            sys.stdout.flush()
        return 0
    except (ExtractionFailure, IngestionFailure) as exc:
        detail = getattr(exc, "detail", None) or ({"ledger": ledger} if exc.code in _LEDGER_CODES else None)
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": exc.code, **({"detail": detail} if detail else {})}}))
        return 2
    except (ValidationError, ValueError, TypeError, KeyError, OSError, AttributeError):
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": "input_or_configuration_invalid"}}))
        return 2
    except sqlite3.Error:
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": "persistence_failed"}}))
        return 2
    except Exception:
        # Never dump bodies, paths or stored text from an unexpected failure.
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": "dependency_internal_failure"}}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
