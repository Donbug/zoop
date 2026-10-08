"""Observe an already-running isolated BFF; no model, admin, database or market API calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

BASE = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8864")
    parser.add_argument("--state-dir", type=Path, default=Path("/tmp/zoop-diagram-2026-10-08"))
    args = parser.parse_args()
    if args.url != "http://127.0.0.1:8864" or not str(args.state_dir).startswith("/tmp/zoop-diagram-"):
        parser.error("Only the assigned isolated port and /tmp state are permitted")
    calls = []
    payloads = {}
    for path in ("/api/health", "/openapi.json", "/api/graph?mode=all", "/api/companies"):
        with urlopen(args.url + path, timeout=20) as response:
            payload = json.load(response)
            calls.append({"method": "GET", "path": path, "status": response.status})
            payloads[path] = payload
    health = payloads["/api/health"]
    schema = payloads["/openapi.json"]
    graph = payloads["/api/graph?mode=all"]
    assert health["source"]["mode"] == "snapshot" and health["source"]["connected"]
    assert "/api/health" in schema["paths"] and "/api/graph" in schema["paths"]
    assert not any(p.startswith("/api/v1/") for p in schema["paths"])
    state = args.state_dir
    with sqlite3.connect(f"file:{state / 'zoop-admin.sqlite3'}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        version = dict(conn.execute("SELECT id, file, sha256, kind FROM graph_versions WHERE id=?", (health["graphVersion"],)).fetchone())
    matches = list(state.rglob(version["file"]))
    assert len(matches) == 1
    snapshot = matches[0]
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert digest == version["sha256"]
    report = {
        "status": "passed",
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "scope": "Isolated synthetic seed; public GET requests only. Runtime and source inspection are separate evidence.",
        "url": args.url,
        "stateDir": str(state),
        "disabled": ["briefing scheduler", "quote provider", "metrics provider"],
        "calls": calls,
        "health": health,
        "schema": {"title": schema["info"]["title"], "pathCount": len(schema["paths"]), "apiV1PathCount": sum(p.startswith('/api/v1/') for p in schema['paths'])},
        "publicGraph": {"metadata": graph.get("metadata"), "nodeCount": len(graph.get("nodes", [])), "edgeCount": len(graph.get("edges", []))},
        "snapshot": {"path": str(snapshot), "version": version["id"], "kind": version["kind"], "sha256MatchesSQLite": digest == version["sha256"], "bytes": snapshot.stat().st_size},
        "notExercised": ["production data", "admin ledger / PostgreSQL / Neo4j", "publication", "chat or briefing generation", "LLM / embedding / Jev", "external market HTTP", "frontend interactions", "target /api/v1", "cloud deployment"],
    }
    output = BASE / "out" / "api-observation.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
