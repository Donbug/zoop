"""Graph selection (market / ego) and edge detail over the normalized dataset."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from .dataset import COMPANY_LINKS, Dataset, EdgeRec, IssueRec, sort_recent
from .errors import not_found
from .schemas import (
    EdgeDetail,
    EndpointRef,
    GraphEdge,
    GraphNode,
    Verification,
    ViaIssue,
)
from .summaries import edge_summary
from .views import basis_out, company_name, meta

DERIVED_EXPLANATION = "두 기업이 같은 사건에 함께 등장했다는 뜻이에요. 직접 거래나 영향 관계는 아니에요."
EXPLANATIONS = {
    "INVOLVES": "기사에 이 기업의 역할이 직접 적혀 있어요.",
    "STRUCTURALLY_RELATED_TO": "공급·생산 같은 사업 관계로 이 사건과 이어져 있어요. 직접 참여했다는 뜻은 아니에요.",
    "FOLLOWS": "앞 사건에 이어 일어난 사건이에요.",
}


@dataclass(frozen=True)
class GraphSelection:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool


def _issue_node(issue: IssueRec) -> GraphNode:
    return GraphNode(
        id=issue.id,
        kind="issue",
        label=issue.title,
        event_time=issue.event_time,
        time_precision=issue.time_precision,
        action=issue.action,
        target=issue.target,
        evidence_count=len(issue.evidence_ids),
    )


def _follow_closure(ds: Dataset, issues: dict[str, IssueRec]) -> dict[str, IssueRec]:
    """``issues`` plus every issue linked to them through FOLLOWS, however far."""
    result = dict(issues)
    stack = list(issues)
    while stack:
        current = stack.pop()
        for neighbour in (*ds.follows_previous.get(current, ()), *ds.follows_next.get(current, ())):
            if neighbour not in result:
                result[neighbour] = ds.issues[neighbour]
                stack.append(neighbour)
    return result


def _ego_issues(ds: Dataset, focus: Sequence[str], depth: int | None) -> list[IssueRec]:
    """Issues reached from the focus companies; each hop adds issues then their companies.

    ``depth=None`` keeps hopping until nothing new is reachable: the whole connected component,
    where a FOLLOWS link joins an issue to its predecessor/successor within the same hop.
    """
    ordered: dict[str, IssueRec] = {}
    seen = set(focus)
    frontier = list(focus)
    hops = 0
    while frontier and (depth is None or hops < depth):
        fresh = {
            i.id: i
            for company_id in frontier
            for i in ds.issues_of_company(company_id)
            if i.id not in ordered
        }
        if depth is None:
            fresh = {k: i for k, i in _follow_closure(ds, fresh).items() if k not in ordered}
        level = sort_recent(list(fresh.values()))
        ordered.update((i.id, i) for i in level)
        frontier = []
        for issue in level:
            for company_id in issue.company_ids:
                if company_id not in seen:
                    seen.add(company_id)
                    frontier.append(company_id)
        hops += 1
    return list(ordered.values())


def select_graph(
    ds: Dataset,
    *,
    focus: Sequence[str] | None,
    depth: int | None,
    limit: int,
    holding_ids: Collection[str] = (),
    watch_ids: Collection[str] = (),
) -> GraphSelection:
    """``focus=None`` selects the whole approved market graph, otherwise an ego graph."""
    candidates = sort_recent(list(ds.issues.values())) if focus is None else _ego_issues(ds, focus, depth)
    nodes: dict[str, GraphNode] = {}
    truncated = False

    def company_node(company_id: str, is_focus: bool = False) -> GraphNode:
        rec = ds.companies.get(company_id)
        return GraphNode(
            id=company_id,
            kind="company",
            label=company_name(ds, company_id),
            is_focus=is_focus,
            holding=company_id in holding_ids,
            watch=company_id in watch_ids,
            brand_color=rec.brand_color if rec else None,
            logo_url=rec.logo_url if rec else None,
        )

    for company_id in focus or ():
        if len(nodes) >= limit:
            truncated = True
            break
        nodes[company_id] = company_node(company_id, True)
    for issue in candidates:
        missing = [c for c in issue.company_ids if c not in nodes]
        if len(nodes) + 1 + len(missing) > limit:
            truncated = True
            continue
        nodes[issue.id] = _issue_node(issue)
        for company_id in missing:
            nodes[company_id] = company_node(company_id)
    # A follow-up stays visible next to the issue it follows (TC-08), without pulling in more companies.
    for issue_id in [i for i, n in nodes.items() if n.kind == "issue"]:
        for neighbour in (*ds.follows_previous.get(issue_id, ()), *ds.follows_next.get(issue_id, ())):
            if neighbour in nodes:
                continue
            if len(nodes) >= limit:
                truncated = True
            else:
                nodes[neighbour] = _issue_node(ds.issues[neighbour])

    edges = [
        GraphEdge(
            id=e.id,
            source=e.source,
            target=e.target,
            relation_type=e.relation_type,  # type: ignore[arg-type]
            role=e.role,
            summary=edge_summary(e),
            assertion_status=e.assertion_status,
            derived=e.derived,
            via=list(e.via),
            evidence_ids=list(e.evidence_ids),
        )
        for e in ds.edges.values()
        if e.source in nodes
        and e.target in nodes
        and (not e.derived or any(v in nodes for v in e.via))
    ]
    return GraphSelection(list(nodes.values()), edges, truncated)


def _ref(ds: Dataset, node_id: str) -> EndpointRef:
    if node_id in ds.issues:
        return EndpointRef(id=node_id, kind="issue", label=ds.issues[node_id].title)
    return EndpointRef(id=node_id, kind="company", label=company_name(ds, node_id))


def edge_evidence_via(ds: Dataset, edge: EdgeRec) -> dict[str, tuple[str, ...]]:
    """For a derived edge: shared issue id -> evidence ids on that issue's links to both companies."""
    result: dict[str, tuple[str, ...]] = {}
    for issue_id in edge.via:
        linked = [
            e
            for e in ds.issue_company_edges.get(issue_id, ())
            if e.target in (edge.source, edge.target) and e.relation_type in COMPANY_LINKS
        ]
        result[issue_id] = tuple(dict.fromkeys(ev for e in linked for ev in e.evidence_ids))
    return result


def edge_detail(ds: Dataset, edge_id: str) -> EdgeDetail:
    edge = ds.edges.get(edge_id)
    if edge is None:
        raise not_found("edge_not_found", "간선을 찾을 수 없습니다.")
    via = []
    for issue_id, evidence_ids in edge_evidence_via(ds, edge).items() if edge.derived else ():
        issue = ds.issues[issue_id]
        via.append(
            ViaIssue(
                id=issue.id,
                title=issue.title,
                event_time=issue.event_time,
                time_precision=issue.time_precision,
                evidence_ids=list(evidence_ids),
            )
        )
    return EdgeDetail(
        id=edge.id,
        relation_type=edge.relation_type,  # type: ignore[arg-type]
        derived=edge.derived,
        directed=not edge.derived,
        source=_ref(ds, edge.source),
        target=_ref(ds, edge.target),
        role=edge.role,
        summary=edge_summary(edge),
        roles=list(edge.roles),
        assertion_status=edge.assertion_status,
        evidence_ids=list(edge.evidence_ids),
        basis=[basis_out(b) for b in edge.basis],
        relation_ids=list(edge.relation_ids),
        verification=Verification(status="not_applicable", note="파생 연결은 검증 대상이 아닙니다.")
        if edge.derived
        else Verification(status="ALLOW"),
        via=via,
        explanation=DERIVED_EXPLANATION if edge.derived else EXPLANATIONS[edge.relation_type],
        metadata=meta(ds),
    )
