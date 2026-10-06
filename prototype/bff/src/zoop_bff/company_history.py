"""Conservative as-of view for the detail and map (FS040/FS041/FS0??).

The snapshot has article publication and structural verification/validity times, not an
issue publication ledger. An enriched issue is withheld until its latest source article
is public; unknown publication times are withheld. This is not a historical version replay.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from .dataset import COMPANY_LINKS, Dataset, EdgeRec
from .graph import GraphSelection

KST = timezone(timedelta(hours=9))


def moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)


def as_of_dataset(ds: Dataset, as_of: datetime) -> Dataset:
    articles = {
        key: tuple(a for a in versions if (when := moment(a.published_at)) is not None and when <= as_of)
        for key, versions in ds.articles_by_id.items()
    }
    articles = {key: versions for key, versions in articles.items() if versions}
    evidence = {key: ev for key, ev in ds.evidence.items() if ev.article_id in articles}
    issues = {
        key: issue for key, issue in ds.issues.items()
        if (when := moment(issue.latest_published_at)) is not None and when <= as_of
        and issue.article_ids and all(a in articles for a in issue.article_ids)
    }

    def valid(edge: EdgeRec) -> bool:
        if edge.source in ds.issues and edge.source not in issues:
            return False
        if edge.target in ds.issues and edge.target not in issues:
            return False
        if edge.derived:
            return any(v in issues for v in edge.via)
        if not edge.evidence_ids or not all(e in evidence for e in edge.evidence_ids):
            return False
        if not edge.basis:
            return edge.relation_type != "STRUCTURALLY_RELATED_TO"
        return any(
            (not b.verified_at or ((when := moment(b.verified_at)) is not None and when <= as_of))
            and (not b.valid_from or ((start := moment(b.valid_from)) is not None and start <= as_of))
            and (not b.valid_until or ((end := moment(b.valid_until)) is not None and as_of < end))
            for b in edge.basis
        )

    edges = {key: edge for key, edge in ds.edges.items() if valid(edge)}
    # Derived company pairs only survive while both evidence-backed issue links survive.
    edges = {
        key: edge for key, edge in edges.items()
        if not edge.derived or any(
            any(e.source == v and e.target == edge.source and e.relation_type in COMPANY_LINKS for e in edges.values())
            and any(e.source == v and e.target == edge.target and e.relation_type in COMPANY_LINKS for e in edges.values())
            for v in edge.via if v in issues
        )
    }
    issue_edges = {key: tuple(e for e in edges.values() if e.source == key and e.relation_type in COMPANY_LINKS) for key in issues}
    company_edges = {key: tuple(e for e in edges.values() if e.target == key and e.relation_type in COMPANY_LINKS) for key in ds.companies}
    issues = {key: replace(issue, company_ids=tuple(e.target for e in issue_edges[key])) for key, issue in issues.items()}
    return replace(
        ds, as_of=as_of.isoformat(), articles_by_id=articles, evidence=evidence, issues=issues, edges=edges,
        issue_company_edges=issue_edges, company_edges=company_edges,
        follows_previous={key: tuple(e.source for e in edges.values() if e.target == key and e.relation_type == "FOLLOWS") for key in issues},
        follows_next={key: tuple(e.target for e in edges.values() if e.source == key and e.relation_type == "FOLLOWS") for key in issues},
    )


def company_neighborhood(graph: GraphSelection, company_id: str, depth: int) -> GraphSelection:
    """Literal undirected 1/2 edge hops, matching the shared canvas focus rules."""
    seen = {company_id}
    frontier = {company_id}
    for _ in range(depth):
        fresh = {end for edge in graph.edges for start, end in ((edge.source, edge.target), (edge.target, edge.source)) if start in frontier} - seen
        seen.update(fresh)
        frontier = fresh
    return GraphSelection(
        [n for n in graph.nodes if n.id in seen],
        [e for e in graph.edges if e.source in seen and e.target in seen and (not e.derived or any(v in seen for v in e.via))],
        graph.truncated,
    )
