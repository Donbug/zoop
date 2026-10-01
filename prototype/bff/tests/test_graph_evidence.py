"""The graph carries the evidence behind every event node and edge, and agrees with the detail endpoints."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from zoop_bff.app import create_app
from zoop_bff.config import BFF_ROOT, DEFAULT_SNAPSHOT_PATH, Settings

STRESS = BFF_ROOT / "fixtures" / "synthetic-stress-300.json"
REAL = BFF_ROOT / "fixtures" / "poc-real-inspect.json"  # git-ignored, present on the machines that reviewed real articles

SNAPSHOTS = [
    pytest.param(DEFAULT_SNAPSHOT_PATH, id="poc-synthetic"),
    pytest.param(STRESS, id="stress-300"),
    pytest.param(REAL, id="poc-real", marks=pytest.mark.skipif(not REAL.exists(), reason="local real snapshot not present")),
]


def _client(path, state_dir) -> TestClient:
    settings = Settings(snapshot_path=path, company_catalog=None, state_dir=state_dir, briefing_scheduler=False)
    return TestClient(create_app(settings))


@pytest.fixture(scope="module", params=SNAPSHOTS)
def graph_client(request, tmp_path_factory) -> tuple[TestClient, dict[str, Any]]:
    client = _client(request.param, tmp_path_factory.mktemp("state"))
    response = client.get("/api/graph")
    assert response.status_code == 200, response.text
    return client, response.json()


@pytest.fixture(scope="module")
def stress(tmp_path_factory) -> tuple[TestClient, dict[str, Any]]:
    client = _client(STRESS, tmp_path_factory.mktemp("state"))
    return client, client.get("/api/graph").json()


def test_issue_nodes_count_the_evidence_of_their_event(graph_client):
    client, graph = graph_client

    issue_nodes = [n for n in graph["nodes"] if n["kind"] == "issue"]
    assert issue_nodes
    for node in issue_nodes:
        detail = client.get(f"/api/events/{node['id']}").json()
        assert node["evidenceCount"] == len(detail["evidenceIds"]), node["id"]
    assert any(n["evidenceCount"] for n in issue_nodes)
    assert all(n["evidenceCount"] is None for n in graph["nodes"] if n["kind"] == "company")


def test_edges_list_the_evidence_of_their_detail_and_derived_pairs_have_none(graph_client):
    client, graph = graph_client

    approved = [e for e in graph["edges"] if not e["derived"]]
    assert approved
    for edge in graph["edges"]:
        detail = client.get(f"/api/graph/edges/{edge['id']}").json()
        assert edge["evidenceIds"] == detail["evidenceIds"], edge["id"]
        if edge["derived"]:
            assert edge["evidenceIds"] == []
    assert all(e["evidenceIds"] for e in approved)


def test_stress_snapshot_has_the_shapes_the_graph_screen_is_tested_against(stress):
    client, graph = stress
    meta = graph["metadata"]
    nodes, edges = graph["nodes"], graph["edges"]

    assert 280 <= len(nodes) <= 320 and meta["truncated"] is False
    assert meta["datasetKind"] == "synthetic-preview" and meta["synthetic"] is True

    linked = {end for e in edges if not e["derived"] for end in (e["source"], e["target"])}
    issues = [n for n in nodes if n["kind"] == "issue"]
    isolated = [n for n in issues if n["id"] not in linked]
    assert 0.13 <= len(isolated) / len(issues) <= 0.17

    involved: dict[str, int] = {}
    for e in edges:
        if e["relationType"] == "INVOLVES":
            involved[e["target"]] = involved.get(e["target"], 0) + 1
    top = sorted(involved.values(), reverse=True)
    assert top[2] >= 15 > top[3]  # three hub companies, nobody else close

    by_type: dict[str, list[dict[str, Any]]] = {}
    for e in edges:
        by_type.setdefault(e["relationType"], []).append(e)
    assert len(by_type["FOLLOWS"]) >= 10
    assert any(len(e["via"]) >= 5 for e in by_type["SHARES_ISSUE"])  # a pair that keeps meeting
    structural = [client.get(f"/api/graph/edges/{e['id']}").json() for e in by_type["STRUCTURALLY_RELATED_TO"]]
    assert structural and all(d["basis"] for d in structural)

    event_times = sorted(n["eventTime"][:10] for n in issues if n["eventTime"] and len(n["eventTime"]) == 10)
    assert event_times[0] >= "2026-07-01" and event_times[-1] <= "2026-09-30"
    assert any(n["eventTime"] is None for n in issues)


def test_stress_snapshot_evidence_is_verified_and_held_candidates_stay_hidden(stress):
    client, graph = stress

    evidence_ids = {
        ev
        for n in graph["nodes"]
        if n["kind"] == "issue"
        for ev in client.get(f"/api/events/{n['id']}").json()["evidenceIds"]
    }
    assert len(evidence_ids) == client.get("/api/health").json()["counts"]["evidence"]
    assert all(client.get(f"/api/evidence/{ev}").json()["quoteVerified"] is True for ev in evidence_ids)

    public = client.get("/api/graph").text + client.get("/api/events").text
    assert "stress-held" not in public and "미확인 보도" not in public
