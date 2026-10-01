"""What the graph screen relies on: whole-component selection, edge summaries, brand fields."""

from __future__ import annotations

import json
from typing import Any

import pytest

from .conftest import fresh

LONG_KOREAN_ROLE = "협약 당사자, AI 가전·B2B 통합 운영 솔루션 공급사"


def _relation(issue_id: str, target: str, relation_type: str, role: str | None = None, basis: list | None = None):
    return {
        "relation_id": f"rel-{issue_id}-{target}-{relation_type}",
        "source": issue_id,
        "target": target,
        "relation_type": relation_type,
        "role": role,
        "assertion_status": "announced",
        "evidence": [],
        "basis": basis or [],
    }


def _issue(number: int, event_time: str, relations: list[dict[str, Any]], names: dict[str, str]):
    return {
        "issue_id": f"issue-{number}",
        "mentions": [
            {
                "mention_id": f"m{number}",
                "article_id": "chain-article",
                "title": f"사건 {number}",
                "action": "발표",
                "event_time": event_time,
                "background": False,
                "participants": [{"company_id": cid, "name": name, "role": "참여"} for cid, name in names.items()],
                "evidence": [],
            }
        ],
        "articles": [],
        "relations": relations,
        "field_decisions": [],
        "source_support": {"article_count": 0},
    }


def chain_payload() -> dict[str, Any]:
    """A-i1-B-i2-C-i3-D(structural); E is reached only through i4 FOLLOWS i3; A and B also share i5."""
    names = {c: f"기업{c}" for c in "ABCE"}

    def involves(number: int, company: str, role: str | None) -> dict[str, Any]:
        return _relation(f"issue-{number}", company, "INVOLVES", role)

    supplies = [
        {"edge_id": "b1", "relation_type": "supplies"},
        {"edge_id": "b2", "relation_type": "PRODUCES"},
        {"edge_id": "b3", "relation_type": "unknown-kind"},
    ]
    issues = [
        _issue(1, "2026-04-01", [involves(1, "A", "technology provider"), involves(1, "B", "발표자")], names),
        _issue(2, "2026-03-01", [involves(2, "B", "collaborator"), involves(2, "C", "something-unmapped")], names),
        _issue(
            3,
            "2026-02-01",
            [involves(3, "C", None), _relation("issue-3", "D", "STRUCTURALLY_RELATED_TO", basis=supplies)],
            names,
        ),
        _issue(4, "2026-01-01", [involves(4, "E", LONG_KOREAN_ROLE), _relation("issue-4", "issue-3", "FOLLOWS")], names),
        _issue(5, "2026-05-01", [involves(5, "A", "submitter/system developer"), involves(5, "B", "발표자")], names),
    ]
    return {"issues": issues, "candidates": [], "errors": []}


def _graph(client, query: str = ""):
    response = client.get(f"/api/graph?{query}")
    assert response.status_code == 200, response.text
    return response.json()


def _ids(graph, kind: str) -> set[str]:
    return {n["id"] for n in graph["nodes"] if n["kind"] == kind}


def test_graph_without_depth_reaches_every_hop_and_explicit_depth_still_limits(make_client):
    client = make_client(chain_payload())

    whole = _graph(client, "companyId=A")
    assert whole["metadata"]["depth"] is None and whole["metadata"]["truncated"] is False
    assert _ids(whole, "company") == {"A", "B", "C", "D", "E"}  # D is 3 hops away, E only through FOLLOWS
    assert _ids(whole, "issue") == {f"issue-{n}" for n in range(1, 6)}
    assert {e["relationType"] for e in whole["edges"]} >= {"FOLLOWS", "STRUCTURALLY_RELATED_TO", "SHARES_ISSUE"}

    one = _graph(client, "companyId=A&depth=1")
    assert one["metadata"]["depth"] == 1
    assert _ids(one, "company") == {"A", "B"} and _ids(one, "issue") == {"issue-1", "issue-5"}
    two = _graph(client, "companyId=A&depth=2")
    assert _ids(two, "company") == {"A", "B", "C"}

    market = _graph(client)
    assert market["metadata"]["depth"] is None
    assert _ids(market, "company") == {"A", "B", "C", "D", "E"}


def test_graph_limit_truncates_newest_events_first(make_client):
    client = make_client(chain_payload())

    graph = _graph(client, "companyId=A&limit=5")

    assert graph["metadata"]["truncated"] is True and graph["metadata"]["limit"] == 5
    assert len(graph["nodes"]) <= 5
    # The focus, then the newest issues (i5 2026-05, i1 2026-04) with their companies; older ones are cut.
    assert _ids(graph, "issue") == {"issue-5", "issue-1"}
    assert _ids(graph, "company") == {"A", "B"}
    assert client.get("/api/graph?limit=1001").status_code == 422
    assert client.get("/api/graph?depth=7").status_code == 422


def test_edge_summaries_reflect_role_basis_follow_and_shared_issue_count(make_client):
    client = make_client(chain_payload())
    graph = _graph(client, "companyId=A")

    def summary(source: str, target: str, relation_type: str) -> str:
        edge = next(
            e
            for e in graph["edges"]
            if e["relationType"] == relation_type and {e["source"], e["target"]} == {source, target}
        )
        return edge["summary"]

    assert summary("issue-1", "A", "INVOLVES") == "기술 제공사"  # known English role, mapped
    assert summary("issue-1", "B", "INVOLVES") == "발표자"  # Korean role kept as written
    assert summary("issue-2", "C", "INVOLVES") == "직접 관련"  # unmapped role is not guessed
    assert summary("issue-3", "C", "INVOLVES") == "직접 관련"  # no role at all
    assert summary("issue-5", "A", "INVOLVES") == "제출자·시스템 개발사"
    assert summary("issue-4", "E", "INVOLVES") == "협약 당사자"  # first clause of a long Korean role
    assert summary("issue-3", "D", "STRUCTURALLY_RELATED_TO") == "공급·생산"  # unknown basis kind is dropped
    assert summary("issue-4", "issue-3", "FOLLOWS") == "후속 사건"
    assert summary("A", "B", "SHARES_ISSUE") == "같은 사건 2건"  # i1 and i5
    assert summary("B", "C", "SHARES_ISSUE") == "같은 사건 1건"  # i2

    for edge in graph["edges"]:
        detail = client.get(f"/api/graph/edges/{edge['id']}").json()
        assert detail["summary"] == edge["summary"]



@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("presenter", "발표자"),
        ("adopter", "도입사"),
        ("technology provider and collaborator", "기술 제공사·협력사"),
        ("developer and rollout provider", "개발사·출시 제공사"),
    ],
)
def test_real_news_roles_have_korean_graph_labels(make_client, role, expected):
    payload = chain_payload()
    payload["issues"][0]["relations"][0]["role"] = role
    graph = _graph(make_client(payload))
    edge = next(e for e in graph["edges"] if e["source"] == "issue-1" and e["target"] == "A")
    assert edge["summary"] == expected


BAD_COLOR = "blue-ish"
TRAVERSAL = "../secret.svg"
BRAND_CASES = [
    {
        "company_id": "A",
        "name": "기업A",
        "brand_color": "#76B900",
        "logo": "nvidia.svg",
        "brand_source": "https://example.test/brand",
    },
    {"company_id": "B", "name": "기업B", "brand_color": BAD_COLOR, "logo": "b.svg"},
    {"company_id": "C", "name": "기업C", "brand_color": "#123456", "logo": TRAVERSAL},
    {"company_id": "D", "name": "기업D", "brand_color": "#GGGGGG", "logo": "sub/dir.svg"},
    {"company_id": "E", "name": "기업E", "logo": "x.svg?a=1"},
]


@pytest.mark.parametrize("via", ["catalog", "extension"])
def test_only_well_formed_brand_fields_are_exposed(make_client, tmp_path, via):
    payload = chain_payload()
    settings: dict[str, Any] = {}
    if via == "catalog":
        path = tmp_path / "companies.json"
        path.write_text(json.dumps({"companies": BRAND_CASES}), encoding="utf-8")
        settings["company_catalog"] = path
    else:
        payload["zoop"] = {"companies": fresh(BRAND_CASES)}
    client = make_client(payload, **settings)

    expected = {
        "A": ("#76B900", "/logos/nvidia.svg"),
        "B": (None, "/logos/b.svg"),
        "C": ("#123456", None),  # each field is judged on its own
        "D": (None, None),
        "E": (None, None),
    }
    graph = _graph(client)
    nodes = {n["id"]: n for n in graph["nodes"]}
    listed = {c["id"]: c for c in client.get("/api/companies").json()["items"]}
    for company_id, (color, logo_url) in expected.items():
        detail = client.get(f"/api/companies/{company_id}").json()
        for view in (nodes[company_id], listed[company_id], detail):
            assert (view["brandColor"], view["logoUrl"]) == (color, logo_url), (company_id, view)
    issues = [n for n in graph["nodes"] if n["kind"] == "issue"]
    assert issues and all(n["brandColor"] is None and n["logoUrl"] is None for n in issues)

    everything = "\n".join(client.get(url).text for url in ("/api/graph", "/api/companies", "/api/health"))
    for rejected in (BAD_COLOR, TRAVERSAL, "#GGGGGG", "sub/dir.svg", "x.svg?a=1"):
        assert rejected not in everything, rejected
    warnings = client.get("/api/health").json()["warnings"]
    assert len(warnings) == 5 and all("invalid format" in w for w in warnings)  # B color, C logo, D color+logo, E logo
