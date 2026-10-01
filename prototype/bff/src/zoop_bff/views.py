"""Dataset records -> response models shared by several routers."""

from __future__ import annotations

from .accounts import UserState, utc_now
from .dataset import BasisRec, Dataset, EdgeRec, IssueRec
from .errors import ApiError
from .schemas import (
    BasisOut,
    CompanyLink,
    EventSummary,
    FollowRef,
    Metadata,
    SourceSupportOut,
    Unavailable,
)

SUMMARY_UNAVAILABLE = "요약 생산자(PoC 범위 밖)가 아직 없습니다."
SENTIMENT_UNAVAILABLE = "감성 평가 생산자(PoC 범위 밖)가 아직 없습니다."


def unavailable(reason: str) -> Unavailable:
    return Unavailable(reason=reason)


def meta(ds: Dataset, generated_by: str | None = None) -> Metadata:
    return Metadata(
        dataset_kind=ds.dataset_kind,
        source=ds.source_label,
        as_of=ds.as_of,
        source_mode=ds.source_mode,
        synthetic=ds.synthetic,
        generated_by=generated_by,
        graph_version=ds.graph_version,
    )


def mock_meta(generated_by: str, as_of: str | None = None) -> Metadata:
    """Metadata for BFF-generated mock content that has no PoC producer."""
    return Metadata(
        dataset_kind="synthetic-preview",
        source="bff-mock",
        as_of=as_of or utc_now(),
        source_mode="mock",
        synthetic=True,
        generated_by=generated_by,
    )


def company_name(ds: Dataset, company_id: str) -> str:
    rec = ds.companies.get(company_id)
    return rec.name if rec else company_id


def basis_out(b: BasisRec) -> BasisOut:
    return BasisOut(
        edge_id=b.edge_id,
        relation_type=b.relation_type,
        source_url=b.source_url,
        verified_at=b.verified_at,
        valid_from=b.valid_from,
        valid_until=b.valid_until,
        countries=list(b.countries),
    )


def event_summary(issue: IssueRec) -> EventSummary:
    return EventSummary(
        id=issue.id,
        title=issue.title,
        action=issue.action,
        target=issue.target,
        event_time=issue.event_time,
        time_precision=issue.time_precision,
        period=issue.period,
        company_ids=list(issue.company_ids),
        article_count=issue.article_count,
        reported_at=issue.latest_published_at,
    )


def source_support_out(issue: IssueRec) -> SourceSupportOut:
    s = issue.source_support
    return SourceSupportOut(
        article_count=s.article_count,
        known_lineage_count=s.known_lineage_count,
        unknown_lineage_articles=list(s.unknown_lineage_articles),
        independent_source_count=s.independent_source_count,
        duplicate_groups=[list(g) for g in s.duplicate_groups],
    )


def company_links(ds: Dataset, issue: IssueRec) -> list[CompanyLink]:
    edges: tuple[EdgeRec, ...] = ds.issue_company_edges.get(issue.id, ())
    return [
        CompanyLink(
            id=e.target,
            name=company_name(ds, e.target),
            role=e.role,
            role_unconfirmed=e.role_unconfirmed,
            relation_type=e.relation_type,  # type: ignore[arg-type]
        )
        for e in edges
    ]


def follow_ref(ds: Dataset, issue_id: str) -> FollowRef:
    issue = ds.issues[issue_id]
    return FollowRef(
        id=issue.id, title=issue.title, event_time=issue.event_time, time_precision=issue.time_precision
    )


def user_holding_ids(ds: Dataset, user: UserState) -> list[str]:
    """Company ids of the connected virtual account (empty when not connected)."""
    conn = user.connection
    if conn is None:
        return []
    return [h.company_id for h in conn.holdings]  # frozen at connect time, independent of the active graph version
