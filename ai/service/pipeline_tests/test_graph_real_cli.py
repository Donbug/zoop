"""The graph door over the REAL installed `zoop-ai-graph` (no stand-in), without a Neo4j.

Without a database only the refusals that happen before the pipeline consults a source or Neo4j can be driven: a version that is not `ready`, a `ready`
row whose stored plan does not verify, an absent version, a busy or damaged ledger. They prove what a stand-in cannot: that the argv the service builds
is accepted by the real command (a wrong flag would be `input_or_configuration_invalid`), that the real exit codes and error objects are interpreted as
documented, and that the real command leaves the operator's ledger untouched. A version that actually verifies against Neo4j (focus 1..3, source
revocation, canonical change, corruption, outage) is `scripts/graph_service_smoke.py`, which needs a real, empty Neo4j and fails without one.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
from pathlib import Path
from typing import Callable

import pytest

from graph_support import GraphWorkspace, focus_url, status_url, version_entry
from relation_support import PIPELINE, PIPELINE_BIN, PIPELINE_PYTHON, tree
from support import ServiceProcess, remove_tree

GRAPH_CLI = PIPELINE_BIN / "zoop-ai-graph"
BUILD_LEDGER = Path(__file__).resolve().parent / "build_graph_ledger.py"
STATES = {"ver-frozen": "frozen", "ver-reserved": "reserved", "ver-unknown": "unknown", "ver-failed": "failed", "ver-damaged": "ready"}


@pytest.fixture
def real_graph(tmp_path: Path) -> Callable[..., tuple[GraphWorkspace, ServiceProcess]]:
    """A service over the real `zoop-ai-graph` and a ledger with one version per state. `ver-absent` is listed but not in the ledger and `ver-other` is
    in the ledger but listed for nobody."""
    assert GRAPH_CLI.is_file() and os.access(GRAPH_CLI, os.X_OK), f"{GRAPH_CLI} is missing: run `make pipeline-install`"
    started: list[ServiceProcess] = []

    def factory(*, extra: dict[str, str] | None = None) -> tuple[GraphWorkspace, ServiceProcess]:
        root = tmp_path / f"real{len(started)}"
        listed = [version_entry(version=name) for name in (*STATES, "ver-absent")]
        ws = GraphWorkspace(root, command=GRAPH_CLI, auth={"ZOOP_GRAPH_AUTH": "none"}, versions=listed)
        states = {**STATES, "ver-other": "frozen"}
        done = subprocess.run([str(PIPELINE_PYTHON), str(BUILD_LEDGER), str(ws.graph_state), str(ws.relation_state), str(ws.extraction_state),
                               str(ws.ingestion_state), json.dumps(states)], capture_output=True, text=True, timeout=120,
                              env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8",
                                   "PYTHONDONTWRITEBYTECODE": "1", "ZOOP_STATE_DIR": str(ws.app_state), "ZOOP_AI_WORKER_STATE_DIR": str(ws.worker)})
        assert done.returncode == 0, done.stderr[-3000:]
        service = ServiceProcess(ws, env=ws.env(**(extra or {})))
        started.append(service)
        return ws, service.start()

    yield factory
    for service in started:
        service.close()
    for service in started:
        remove_tree(service.workspace.root)


def error_of(response) -> dict:
    return response.json()["error"]


@pytest.mark.parametrize("name", ["ver-frozen", "ver-reserved", "ver-unknown", "ver-failed"])
def test_a_version_that_is_not_ready_is_withheld_with_its_real_state_and_nothing_is_written(real_graph, name):
    ws, service = real_graph()
    before = tree(ws.graph_state)
    for url in (status_url(name), focus_url(name, "kr-000100", 2)):
        response = service.request("GET", url, as_="grapher")
        wire = response.json()
        assert response.status_code == 200, response.text
        assert (wire["state"], wire["delivery"], wire["publication"]) == (STATES[name], {"state": "withheld", "reason": "version_not_ready"}, "not-published")
        assert wire["verification"] is None and wire.get("graph") is None and wire.get("evidence") is None
    assert tree(ws.graph_state) == before   # the real command opened the ledger read-only, immutable, and wrote nothing
    assert not (ws.graph_state / "graph.sqlite3-wal").exists()


def test_a_ready_row_whose_plan_does_not_verify_is_a_server_state_fault_never_content(real_graph):
    _, service = real_graph()
    response = service.request("GET", status_url("ver-damaged"), as_="grapher")
    assert response.status_code == 503 and error_of(response)["code"] == "service_configuration_invalid" and error_of(response)["retryable"] is True
    assert "graph" not in response.json()


def test_a_listed_version_the_ledger_does_not_have_is_404_and_an_unlisted_one_is_the_same_403_as_an_unknown_one(real_graph):
    ws, service = real_graph()
    absent = service.request("GET", status_url("ver-absent"), as_="grapher")
    assert absent.status_code == 404 and error_of(absent)["code"] == "version_not_found"
    unlisted = service.request("GET", status_url("ver-other"), as_="grapher")      # exists in the ledger, listed for nobody
    unknown = service.request("GET", status_url("ver-never"), as_="grapher")
    assert unlisted.status_code == unknown.status_code == 403
    assert {k: v for k, v in error_of(unlisted).items() if k != "requestId"} == {k: v for k, v in error_of(unknown).items() if k != "requestId"}
    assert "ver-other" not in unlisted.text and "frozen" not in unlisted.text


def test_an_operator_writer_holding_the_ledger_is_a_busy_503_and_releasing_it_restores_service(real_graph):
    ws, service = real_graph()
    descriptor = os.open(ws.graph_state / "graph.lock", os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)   # what a `project` or `recover` command holds
        response = service.request("GET", status_url("ver-frozen"), as_="grapher")
        error = error_of(response)
        assert response.status_code == 503 and (error["code"], error["runtimeCode"], error["retryable"]) == ("runtime_busy", "graph_busy", True)
        assert response.headers["retry-after"] and "state" not in response.json()   # busy is never an empty or stale answer
    finally:
        os.close(descriptor)
    assert service.request("GET", status_url("ver-frozen"), as_="grapher").status_code == 200


def test_a_foreign_file_in_the_graph_namespace_is_a_server_state_fault(real_graph):
    ws, service = real_graph()
    (ws.graph_state / "stray.txt").write_text("not part of the ledger")
    response = service.request("GET", status_url("ver-frozen"), as_="grapher")
    assert response.status_code == 503 and error_of(response)["code"] == "service_configuration_invalid"
    (ws.graph_state / "stray.txt").unlink()
    assert service.request("GET", status_url("ver-frozen"), as_="grapher").status_code == 200


def test_the_real_command_never_starts_a_model_or_leaves_a_process_behind(real_graph):
    ws, service = real_graph()
    for name in STATES:
        service.request("GET", status_url(name), as_="grapher")
    leftovers = subprocess.run(["pgrep", "-f", f"zoop-ai-graph.*{ws.graph_state}"], capture_output=True, text=True)
    assert leftovers.returncode == 1 and leftovers.stdout.strip() == ""   # pgrep exit 1 is a genuine no-match
    assert str(PIPELINE) not in service.logs()
