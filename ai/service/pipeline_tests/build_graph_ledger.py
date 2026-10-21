#!/usr/bin/env python3
"""Operator-side stand-in: a graph ledger (`graph.sqlite3` + `graph.lock`) holding version rows in chosen states, made with the pipeline's own `Store`.

Run with the interpreter of `ai/pipeline/.venv`, never the service's. It needs no Neo4j: only `read`/`focus` of a version that is NOT `ready` (the
pipeline refuses before it consults any source or the database) and of a `ready` row whose plan is damaged (refused while verifying the plan) can be
driven this way. The rows are deliberately NOT real projections: a version that verifies against a real Neo4j is `scripts/graph_service_smoke.py`.

usage: build_graph_ledger.py <graph root> <relation root> <extraction root> <ingestion root> <states JSON {versionId: state}>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from zoop_ai_pipeline.graph_projection import Store
from zoop_ai_pipeline.graph_projection_contracts import PLAN_VERSION

STAMP = "2026-10-12T03:00:00+00:00"


def main() -> None:
    root, relation, extraction, ingestion = (Path(argument).resolve() for argument in sys.argv[1:5])
    states: dict[str, str] = json.loads(sys.argv[5])
    store = Store(root, relation, extraction, ingestion, mode="create")
    try:
        for version_id, state in states.items():
            # A row that is not `ready` is frozen under THIS build's plan contract (the ledger-only preflight reads only the stored plan's `schema`; a
            # plan without it, or of an unknown schema, is a damaged ledger and is refused before the state is ever looked at). A `ready` row keeps
            # the damaged `{}` plan on purpose: it is the one the pipeline refuses while verifying the plan.
            plan = "{}" if state == "ready" else json.dumps({"schema": PLAN_VERSION})
            store.db.execute("INSERT INTO versions(version_id,input_digest,request,plan,payload_digest,graph_digest,state,created_at,updated_at) "
                             "VALUES(?,?,?,?,?,?,?,?,?)", (version_id, "0" * 64, "{}", plan, "1" * 64, "2" * 64, state, STAMP, STAMP))
    finally:
        store.close()
    print(json.dumps({"ok": True, "versions": sorted(states)}))


if __name__ == "__main__":
    main()
