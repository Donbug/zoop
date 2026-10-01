"""Snapshot-only publication boundary; exclusion metadata is not a runtime filter."""

from __future__ import annotations

import copy
import json

import pytest

from zoop_bff.config import BFF_ROOT
from zoop_bff.dataset import edge_id, evidence_id

SOURCE = "issue-48bcf76304253fea001492e3"
TARGET = "issue-f571b945ddcd229404238448"
RELATION = "relation-021ae4e61e1b08cd14affc58"
CANDIDATE = "candidate-bc3b351eee049193db9ec42b"
SMALL = BFF_ROOT / "fixtures/reviewed-follows-regression.json"
REAL = BFF_ROOT / "fixtures/poc-real-inspect.json"
SNAPSHOTS = [
    pytest.param(SMALL, id="deterministic-synthetic"),
    pytest.param(REAL, id="local-reviewed-real", marks=pytest.mark.skipif(
        not REAL.exists(), reason="local reviewed snapshot not present"
    )),
]


def _audit_relation(payload):
    audit = next(c for c in payload["candidates"] if c["candidate"]["candidate_id"] == CANDIDATE)
    assert audit["status"] == "ALLOW" and audit["active"] is True
    return next(r for r in audit["candidate"]["relations"] if r["relation_id"] == RELATION)


@pytest.mark.parametrize("path", SNAPSHOTS)
def test_reviewed_fixture_removes_public_relation_but_preserves_audit(path):
    payload = json.loads(path.read_text())
    exclusion = next(e for e in payload["review_exclusions"] if e["relation_id"] == RELATION)
    assert (exclusion["source"], exclusion["target"]) == (SOURCE, TARGET)
    assert exclusion["candidate_ids"] == [CANDIDATE]
    assert exclusion["authority_decision"] == "ALLOW"
    assert exclusion["publication_decision"] == "EXCLUDED_AFTER_MANUAL_REVIEW"
    assert {SOURCE, TARGET} <= {i["issue_id"] for i in payload["issues"]}
    for issue in payload["issues"]:
        for relation in issue["relations"]:
            assert relation["relation_id"] != RELATION
            assert (relation["relation_type"], relation["source"], relation["target"]) != (
                "FOLLOWS", SOURCE, TARGET
            )
    relation = _audit_relation(payload)
    assert (relation["relation_type"], relation["source"], relation["target"]) == (
        "FOLLOWS", SOURCE, TARGET
    )
    assert relation["evidence"]


@pytest.mark.parametrize("path", SNAPSHOTS)
def test_snapshot_public_graph_and_event_details_do_not_restore_excluded_follows(path, make_client):
    client = make_client(json.loads(path.read_text()))
    excluded_edge = edge_id("FOLLOWS", SOURCE, TARGET)
    company = "SYNTH-REVIEW-COMPANY" if path == SMALL else "KRX:005930"
    for query in ("", f"?companyId={company}", f"?companyId={company}&depth=1"):
        response = client.get("/api/graph" + query)
        assert response.status_code == 200
        graph = response.json()
        assert graph["metadata"]["sourceMode"] == "snapshot"
        assert all(e["id"] != excluded_edge for e in graph["edges"])
        if query:
            assert SOURCE not in {n["id"] for n in graph["nodes"]}
    assert client.get(f"/api/graph/edges/{excluded_edge}").status_code == 404
    for id, direction, other in ((SOURCE, "previous", TARGET), (TARGET, "next", SOURCE)):
        response = client.get(f"/api/events/{id}")
        assert response.status_code == 200
        event = response.json()
        assert all(r["id"] != RELATION for r in event["relations"])
        assert all(r["id"] != other for r in event["follows"][direction])
        # Original mention evidence remains available; suppressing a relation is not article withdrawal.
        assert event["evidenceIds"]
        for evidence in event["evidenceIds"]:
            result = client.get(f"/api/evidence/{evidence}")
            assert result.status_code == 200
            assert id in result.json()["eventIds"]


def test_audit_only_evidence_and_excluded_path_are_not_public(make_client):
    payload = json.loads(SMALL.read_text())
    client = make_client(payload)
    relation = _audit_relation(payload)
    audit = relation["evidence"][1]
    id = evidence_id(audit["article_id"], audit["article_version"], audit["start"], audit["end"])
    assert client.get(f"/api/evidence/{id}").status_code == 404
    graph = client.get("/api/graph").json()
    assert {SOURCE, TARGET} <= {n["id"] for n in graph["nodes"]}
    # The browser's path input consists of public edges, treated as undirected and non-derived.
    adjacent = {}
    for edge in graph["edges"]:
        if not edge["derived"]:
            adjacent.setdefault(edge["source"], set()).add(edge["target"])
            adjacent.setdefault(edge["target"], set()).add(edge["source"])
    reached, pending = {SOURCE}, [SOURCE]
    while pending:
        for next_id in adjacent.get(pending.pop(), set()) - reached:
            reached.add(next_id)
            pending.append(next_id)
    assert TARGET not in reached


def test_snapshot_exclusion_is_migrated_to_a_review_record_that_filters_a_reintroduced_relation(make_client):
    # A snapshot's review_exclusions are registered once as relation rejections (origin
    # "snapshot-migration"), so a relation re-added to the snapshot stays off the user graph.
    payload = json.loads(SMALL.read_text())
    relation = copy.deepcopy(_audit_relation(payload))
    next(i for i in payload["issues"] if i["issue_id"] == SOURCE)["relations"].append(relation)
    client = make_client(payload)
    assert client.get(f"/api/graph/edges/{edge_id('FOLLOWS', SOURCE, TARGET)}").status_code == 404
    assert client.get(f"/api/events/{SOURCE}").json()["follows"]["previous"] == []
    state = client.app.state.zoop.admin
    migrated = state.reviews.current("relation", RELATION)
    assert migrated is not None and (migrated.decision, migrated.origin) == ("reject", "snapshot-migration")
