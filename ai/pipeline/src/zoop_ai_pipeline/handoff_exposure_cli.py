"""Operator-only, read-only handoff EXPOSURE report (`zoop-ai-handoff-exposure`): which public issues, relations, evidence and articles of the explicitly
selected frozen handoffs rest on one changed source identity or one retracted S3 relation.

stdin: one JSON object (<= 65,536 bytes), see `handoff_exposure_contracts.Query`. stdout: one canonical JSON line (<= 6 MiB, never truncated). Exit 0 for a
report, exit 2 for an error; no error lists affected IDs. It evaluates no authority, registry, rights or delivery, writes no ledger, calls no model or network,
and neither excludes, revises, overlays nor activates anything: an empty or smaller report never clears an exclusion and is not a safety statement.

Only the CURRENT bundle contract is read. A selected handoff that is history, missing, unready, damaged or not resolvable in the scanned source ledgers refuses
the WHOLE report (`handoff_selection_unmappable`); there is no partial success. A history-only selection never reads an artifact or opens a source ledger.
A source change needs the ingestion and extraction ledgers (the S2 scan); a relation retraction is answered from the bundles alone and forbids them.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import ExitStack, closing
from pathlib import Path

from pydantic import ValidationError

from . import extraction, ingestion
from .dependency_cli import _LEDGER_CODES
from .dependency_contracts import matcher
from .handoff import Store, contract_current, open_legacy_history, read_bundle, read_manifest, receipt_of
from .handoff_exposure import close, relation_seeds, source_seeds, unresolved
from .handoff_exposure_contracts import (BASIS, BUNDLE, CAUSES, CONSISTENCY, EFFECT, MAX_COMMAND, MAX_OUTPUT, NOT_COVERED, SCHEMA, SOURCE_KINDS,
    ExtractionFailure, Query)
from .ingestion_contracts import IngestionFailure, canonical, timestamp


def _flags_valid(changed, flags: tuple) -> bool:
    """The two source ledgers are required for a source change and forbidden for a relation retraction."""
    return all(f is not None for f in flags) if changed.kind in SOURCE_KINDS else all(f is None for f in flags)


def _receipt_intact(row, bundle: dict, manifest) -> bool:
    """The stored receipt of a CURRENT handoff is exactly the closed record the freeze wrote: every fact equals what the row, the frozen manifest and the validated
    bundle say (no key missing or extra), and its own `frozenAt` is a well-formed timezone-aware timestamp. `frozenAt` is the one fact that cannot be recomputed, so
    it is checked only by grammar, never against the clock or the row times."""
    try:
        stored = json.loads(row["receipt"])
        frozen_at = stored.get("frozenAt")
        timestamp(frozen_at)
        rebuilt = receipt_of(manifest, row["input_digest"], bundle, row["bundle_digest"], row["bundle_bytes"])
    except (ValueError, TypeError, KeyError, AttributeError):
        return False
    # Canonical JSON, not `==`: Python equates True with 1 and 1.0 with 1, which the wire contract does not.
    return canonical({k: v for k, v in stored.items() if k != "frozenAt"}) == canonical({k: v for k, v in rebuilt.items() if k != "frozenAt"})


def _report(query: Query, args, ledger: list) -> str:
    changed, ids = query.changed, sorted(query.handoff_ids)
    sourced = changed.kind in SOURCE_KINDS
    roots = (args.extraction_state_dir, args.ingestion_state_dir) if sourced else ()
    failures: dict[str, dict] = {}

    ledger[0] = "handoff"
    # Ledger-only history preflight first: an old-contract handoff is answered without reading its artifact, a source ledger or a writable open.
    for handoff_id in ids:
        try:
            view = open_legacy_history(args.state_dir, *roots, handoff_id=handoff_id)
        except ExtractionFailure as exc:
            if exc.code != "handoff_state_invalid":
                raise
            view = None                 # a damaged receipt is judged per handoff below; a damaged ledger fails again at the ordinary open
        if view is not None:
            view.close()
            failures[handoff_id] = {"code": "handoff_contract_changed"}
    pending = [i for i in ids if i not in failures]

    with ExitStack() as stack:
        loaded: dict[str, tuple] = {}
        if pending:
            store = stack.enter_context(closing(Store(args.state_dir, *roots, mode="read")))
            for handoff_id in pending:
                row = store.handoff(handoff_id)
                if row is None:
                    failures[handoff_id] = {"code": "handoff_not_found"}
                    continue
                try:
                    if not contract_current(row):
                        failures[handoff_id] = {"code": "handoff_contract_changed"}
                        continue
                except ExtractionFailure as exc:
                    failures[handoff_id] = {"code": exc.code}
                    continue
                if row["state"] != "ready":
                    failures[handoff_id] = {"code": "handoff_not_ready", "state": row["state"]}
                    continue
                try:
                    bundle = read_bundle(store.root, row)
                    manifest, _ = read_manifest(row, bundle)
                except ExtractionFailure as exc:
                    failures[handoff_id] = {"code": exc.code}
                    continue
                if not _receipt_intact(row, bundle, manifest):
                    failures[handoff_id] = {"code": "handoff_state_invalid"}
                    continue
                loaded[handoff_id] = (row, bundle)

        recorded, extracted, index = None, None, None
        # Every opened ledger keeps its shared lock until the report is written; a writer that starts meanwhile fails busy.
        if sourced and loaded:
            ledger[0] = "ingestion"
            ingestion_store = stack.enter_context(closing(ingestion.Store(args.ingestion_state_dir, existing=True)))
            ledger[0] = "extraction"
            extraction_store = stack.enter_context(closing(extraction.Store(args.extraction_state_dir, args.ingestion_state_dir, existing=True)))
            ledger[0] = "ingestion"
            recorded = ingestion.recorded(ingestion_store, changed.wire())
            ledger[0] = "extraction"
            extracted, index = extraction.dependents(extraction_store, matcher(changed))
            for handoff_id in sorted(loaded):
                found = unresolved(loaded[handoff_id][1], index)
                if found is not None:
                    failures[handoff_id] = {"code": "handoff_source_unresolved", "jobId": found[0], "reason": found[1]}
                    del loaded[handoff_id]
        if failures:
            raise ExtractionFailure("handoff_selection_unmappable", {"handoffs": [{"handoffId": i, **failures[i]} for i in sorted(failures)]})

        handoffs, bound_any = [], False
        for handoff_id in ids:
            row, bundle = loaded[handoff_id]
            seeds = (source_seeds(bundle, extracted, index) if sourced
                     else relation_seeds(bundle, changed.job_id, changed.relation_candidate_id))
            found = close(bundle, seeds)
            bound_any = bound_any or seeds.bound
            handoffs.append({"handoffId": handoff_id, "bundleSchema": BUNDLE, "manifestDigest": row["input_digest"], "bundleDigest": row["bundle_digest"],
                             "contentDigest": row["content_digest"], "bound": seeds.bound,
                             "exposed": any(found[k] for k in ("articles", "issues", "relations", "evidenceIds")), **found,
                             "counts": {"articles": len(found["articles"]), "issues": len(found["issues"]), "relations": len(found["relations"]),
                                        "evidence": len(found["evidenceIds"])}})
        ledger[0] = "input"
        if not bound_any:
            if sourced and not recorded:
                # A typo or foreign identity must never become a success-empty report.
                raise ExtractionFailure("changed_identity_unknown")
            if not sourced:
                raise ExtractionFailure("changed_relation_unused")
        line = canonical({"schemaVersion": SCHEMA, "changed": changed.wire(), "cause": CAUSES[changed.kind],
                          "identity": {"boundInSelection": bound_any, "recordedInIngestion": recorded},
                          "scope": {"selection": "explicit", "handoffIds": ids, "notCovered": list(NOT_COVERED)},
                          "basis": BASIS[CAUSES[changed.kind]], "consistency": CONSISTENCY, "effect": EFFECT, "handoffs": handoffs,
                          "usage": {"providerCalls": 0, "modelCalls": 0}})
        size = len(line.encode("utf-8")) + 1
        if size > MAX_OUTPUT:
            # Never truncated: a partial list could be read as complete.
            raise ExtractionFailure("exposure_report_limit", {"bytes": size, "limit": MAX_OUTPUT})
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
        return line


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path, help="the handoff ledger (read-only)")
    parser.add_argument("--ingestion-state-dir", type=Path, help="required for a document/source/grant change, forbidden for s3-relation")
    parser.add_argument("--extraction-state-dir", type=Path, help="as --ingestion-state-dir")
    args = parser.parse_args()
    ledger = ["input"]
    try:
        raw = sys.stdin.buffer.read(MAX_COMMAND + 1)
        if len(raw) > MAX_COMMAND:
            raise ExtractionFailure("command_input_limit")
        query = Query.model_validate(json.loads(raw))
        if not _flags_valid(query.changed, (args.ingestion_state_dir, args.extraction_state_dir)):
            raise ExtractionFailure("input_or_configuration_invalid")
        _report(query, args, ledger)
        return 0
    except (ExtractionFailure, IngestionFailure) as exc:
        detail = getattr(exc, "detail", None) or ({"ledger": ledger[0]} if exc.code in _LEDGER_CODES else None)
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": exc.code, **({"detail": detail} if detail else {})}}))
        return 2
    except (ValidationError, ValueError, TypeError, KeyError, OSError, AttributeError):
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": "input_or_configuration_invalid"}}))
        return 2
    except sqlite3.Error:
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": "persistence_failed"}}))
        return 2
    except Exception:  # noqa: BLE001 - never dump bodies, paths or stored text from an unexpected failure
        print(canonical({"schemaVersion": SCHEMA, "error": {"code": "exposure_internal_failure"}}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
