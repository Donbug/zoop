from dataclasses import replace
from datetime import datetime, timedelta

import httpx

from zoop_bff.company_history import as_of_dataset, company_neighborhood, moment
from zoop_bff.dataset import BasisRec
from zoop_bff.graph import GraphSelection
from zoop_bff.market_data import KST, Listing, TtlCache
from zoop_bff.quote_yahoo import YahooProvider
from zoop_bff.schemas import GraphEdge, GraphNode


def test_issue_is_not_visible_before_its_source_publication(make_client):
    client = make_client()
    ds = client.app.state.zoop.provider.get()
    issue = next(i for i in ds.issues.values() if i.latest_published_at and i.article_ids)
    published = moment(issue.latest_published_at)
    assert published is not None
    assert issue.id not in as_of_dataset(ds, published - timedelta(seconds=1)).issues
    assert issue.id in as_of_dataset(ds, published).issues
    company_id = issue.company_ids[0]
    before = client.get(f"/api/companies/{company_id}/graph", params={"asOf": (published - timedelta(seconds=1)).isoformat(), "depth": 2})
    assert before.status_code == 200
    assert issue.id not in {n["id"] for n in before.json()["nodes"]}
    events = client.get("/api/events", params={"companyId": company_id, "to": (published - timedelta(seconds=1)).isoformat()}).json()
    assert issue.id not in {i["id"] for i in [*events["items"], *events["unknownTimeItems"]]}
    assert client.get(f"/api/events/{issue.id}", params={"asOf": (published - timedelta(seconds=1)).isoformat()}).status_code == 404


def test_structural_relation_validity_has_exclusive_end(make_client):
    ds = make_client().app.state.zoop.provider.get()
    edge = next(e for e in ds.edges.values() if not e.derived and e.evidence_ids)
    basis = BasisRec("basis", "SUPPLIES", None, "2027-01-01T00:00:00+09:00", "2027-01-02T00:00:00+09:00", "2027-01-03T00:00:00+09:00", ())
    edge = replace(edge, relation_type="STRUCTURALLY_RELATED_TO", basis=(basis,))
    ds = replace(ds, edges={edge.id: edge})
    assert edge.id not in as_of_dataset(ds, datetime(2027, 1, 1, tzinfo=KST)).edges
    assert edge.id in as_of_dataset(ds, datetime(2027, 1, 2, tzinfo=KST)).edges
    assert edge.id not in as_of_dataset(ds, datetime(2027, 1, 3, tzinfo=KST)).edges


def test_company_neighborhood_never_exceeds_requested_edge_hops():
    nodes = [GraphNode(id=str(i), kind="company" if i % 2 == 0 else "issue", label=str(i)) for i in range(5)]
    edges = [GraphEdge(id=f"e{i}", source=str(i), target=str(i + 1), relation_type="INVOLVES", summary="관계", derived=False) for i in range(4)]
    graph = GraphSelection(nodes, edges, False)
    assert [n.id for n in company_neighborhood(graph, "0", 1).nodes] == ["0", "1"]
    two = company_neighborhood(graph, "0", 2)
    assert [n.id for n in two.nodes] == ["0", "1", "2"]
    assert [e.id for e in two.edges] == ["e0", "e1"]


def test_yahoo_week_and_year_request_supported_resolutions_and_historical_bounds():
    seen = []
    stamp = int(datetime(2026, 10, 5, 9, tzinfo=KST).timestamp())
    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"chart": {"result": [{"meta": {"currency": "KRW", "gmtoffset": 32400}, "timestamp": [stamp], "indicators": {"quote": [{"open": [100], "high": [100], "low": [100], "close": [100], "volume": [1]}]}}], "error": None}})
    yahoo = YahooProvider(base_url="https://yahoo.test", timeout=1, cache=TtlCache(), transport=httpx.MockTransport(handler))
    start, end = datetime(2026, 10, 1, tzinfo=KST), datetime(2026, 10, 6, tzinfo=KST)
    _, week = yahoo.series(Listing("KRX", "005930"), "1w", start=start, end=end)
    _, year = yahoo.series(Listing("KRX", "005930"), "1y", start=start, end=end)
    assert week.interval == "1h" and year.interval == "1wk"
    assert seen[0] == {"period1": str(int(start.timestamp())), "period2": str(int(end.timestamp()) + 1), "interval": "1h"}
    assert seen[1]["interval"] == "1wk"


def test_company_graph_rejects_depth_above_two(make_client):
    client = make_client()
    company_id = next(iter(client.app.state.zoop.provider.get().companies))
    assert client.get(f"/api/companies/{company_id}/graph", params={"asOf": "2026-10-06T12:00:00+09:00", "depth": 3}).status_code == 422


def test_yahoo_does_not_append_current_price_samples_as_candles():
    first = int(datetime(2026, 10, 6, 9, tzinfo=KST).timestamp())
    def handler(request):
        return httpx.Response(200, json={"chart": {"result": [{
            "meta": {"currency": "KRW", "gmtoffset": 32400},
            "timestamp": [first, first + 300, first + 313],
            "indicators": {"quote": [{"open": [100, 101, 102], "high": [100, 101, 102],
                "low": [100, 101, 102], "close": [100, 101, 102], "volume": [10, 10, 0]}]},
        }], "error": None}})
    yahoo = YahooProvider(base_url="https://yahoo.test", timeout=1, cache=TtlCache(), transport=httpx.MockTransport(handler))
    _, day = yahoo.series(Listing("KRX", "005930"), "1d")
    _, week = yahoo.series(Listing("KRX", "005930"), "1w", start=datetime(2026, 10, 1, tzinfo=KST), end=datetime(2026, 10, 6, 12, tzinfo=KST))
    assert [bar.close for bar in day.bars] == [100, 101]
    assert [bar.close for bar in week.bars] == [100]


def test_timeline_two_hop_scope_matches_the_public_company_graph(make_client):
    client = make_client()
    ds = client.app.state.zoop.provider.get()
    company_id = next(i.company_ids[0] for i in ds.issues.values() if i.company_ids)
    as_of = "2026-10-06T12:00:00+09:00"
    graph = client.get(f"/api/companies/{company_id}/graph", params={"asOf": as_of, "depth": 2}).json()
    timeline = client.get("/api/events", params={"companyId": company_id, "to": as_of, "depth": 2}).json()
    expected = {node["id"] for node in graph["nodes"] if node["kind"] == "issue"}
    actual = {issue["id"] for issue in [*timeline["items"], *timeline["unknownTimeItems"]]}
    assert actual == expected
    assert client.get("/api/events", params={"companyId": company_id, "depth": 3}).status_code == 422
