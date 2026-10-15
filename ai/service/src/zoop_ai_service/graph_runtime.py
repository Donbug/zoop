"""The only door to the graph projection: two fixed `zoop-ai-graph` commands, `read` and `focus`, stdin JSON in, one canonical stdout JSON out.

The same rules as the other doors (`runtime.py`, whose generic child runner this reuses): request data reaches the child only through an anonymous
stdin file, argv/environment/working directory are server-owned, stderr is discarded, the child runs in its own session. Differences that matter:

  * the argv carries server-owned paths only. The Neo4j target (URI and database) is bound inside the graph ledger by the operator's `init` and is
    never an argument, an environment value or a request field here; the credentials are in this child's environment and no other child's;
  * both commands open every ledger read-only (shared locks) and write nothing: no graph ledger write, no Neo4j write, no source write, no model;
  * the pipeline exits 2 BOTH for an error object and for a complete result whose delivery is withheld, so a withheld result is a `result`
    outcome and only an object with an `error` key is an `error` outcome. An error outcome keeps its parsed object (`Outcome.result`), because a
    `version_not_ready` error carries the version's state in its detail.
"""
from __future__ import annotations

import json
from typing import Any

from .config import ServiceConfig
from .runtime import CODE, Deadlines, Outcome, WorkerProcess

RUNTIME_SCHEMA = "zoop-graph-projection-1"


def interpret(code: int, raw: bytes) -> Outcome:
    if code not in (0, 2):
        return Outcome("abnormal", exit_code=code)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return Outcome("abnormal", exit_code=code)
    if not isinstance(value, dict) or value.get("schemaVersion") != RUNTIME_SCHEMA:
        return Outcome("abnormal", exit_code=code)
    if "error" in value:
        error = value["error"]
        name = error.get("code") if isinstance(error, dict) else None
        if code != 2 or not isinstance(name, str) or not CODE.fullmatch(name):
            return Outcome("abnormal", exit_code=code)
        return Outcome("error", result=value, code=name, exit_code=2)
    delivery = value.get("delivery")
    status = delivery.get("status") if isinstance(delivery, dict) else None
    if not isinstance(value.get("versionId"), str) or status != ("current" if code == 0 else "withheld"):
        return Outcome("abnormal", exit_code=code)
    return Outcome("result", result=value, exit_code=code)


class GraphProcess:
    def __init__(self, config: ServiceConfig, deadlines: Deadlines = Deadlines()):
        assert config.graph is not None
        self._graph, self._deadlines = config.graph, deadlines
        self._runner = WorkerProcess(config, deadlines, env=config.graph.child_env)

    def _argv(self, command: str) -> list[str]:
        graph = self._graph
        return [str(graph.command), command, "--state-dir", str(graph.state_dir),
                "--relation-state-dir", str(graph.relation_state_dir), "--extraction-state-dir", str(graph.extraction_state_dir),
                "--ingestion-state-dir", str(graph.ingestion_state_dir), "--sources", str(graph.sources_path),
                "--canonical", str(graph.canonical_path)]

    def _run(self, command: str, body: dict[str, Any]) -> Outcome:
        return self._runner.execute(self._argv(command), {"schemaVersion": RUNTIME_SCHEMA, **body}, self._deadlines.read, interpret=interpret)

    def read(self, version_id: str) -> Outcome:
        """The full gate chain over one version; the service keeps only identity, state, delivery and digests of the result."""
        return self._run("read", {"versionId": version_id})

    def focus(self, version_id: str, company_id: str, depth: int) -> Outcome:
        return self._run("focus", {"versionId": version_id, "companyId": company_id, "depth": depth})
