from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ..admin_ledger import LedgerUnavailable
from ..admin_schemas import (
    AuditEntry,
    AuditPage,
    Dashboard,
    DashboardAi,
    DashboardAiFeature,
    DashboardAudit,
    DashboardBriefings,
    DashboardCandidates,
    DashboardGraph,
    DashboardJobs,
    DashboardLedger,
    DashboardMembers,
    ErrorInfo,
)
from ..deps import State, require_admin
from ..errors import ApiError
from ..statedb import utc_iso
from . import ADMIN_ERROR_RESPONSES
from .admin_pipeline import version_out

router = APIRouter(
    prefix="/api/admin",
    tags=["admin-dashboard"],
    dependencies=[Depends(require_admin)],
    responses=ADMIN_ERROR_RESPONSES,
)


@router.get("/dashboard", response_model=Dashboard)
def dashboard(state: State) -> Dashboard:
    """One screen of operating state. A dead ledger only blanks its own sections (the response stays 200)."""
    admin = state.admin
    now = admin.clock.now()
    admin.graphs.ensure_seed()

    ledger = DashboardLedger(status="connected", error=None)
    candidates: DashboardCandidates | None = None
    graph_db = None
    try:
        counts = admin.pipeline.ledger_counts()
        by = counts.candidates
        candidates = DashboardCandidates(
            allow=by["allow"],
            hold=by["hold"],
            reject=by["reject"],
            inactive=by["inactive"],
            hold_pending_review=admin.pipeline.hold_pending_review(),
        )
        graph_db = admin.pipeline.projection_status()
    except LedgerUnavailable as exc:
        ledger = DashboardLedger(status="unavailable", error=ErrorInfo(code=exc.code, message=exc.message))

    active = admin.graphs.active()
    effective = admin.reviews.effective()
    graph = DashboardGraph(
        active_version_id=active.id if active else None,
        activated_at=admin.graphs.activated_at(active.id) if active else None,
        version_count=len(admin.graphs.versions()),
        active_version=version_out(state, active) if active else None,
        review_revision=admin.reviews.revision(),
        review_decisions=len(effective),
        graph_db=graph_db,
    )

    since = utc_iso(now - timedelta(hours=24))
    job_counts = admin.jobs.counts(since)
    jobs = DashboardJobs(
        running=job_counts["running"],
        queued=job_counts["queued"],
        failed24h=job_counts["failed24h"],
        active=admin.jobs.active_out(),
        recent=admin.jobs.recent(5),
    )

    usage = admin.usage.response("7d", admin.jobs.all_data())
    ai = DashboardAi(
        window="7d",
        requests=sum(f.requests for f in usage.features),
        succeeded=sum(f.succeeded for f in usage.features),
        failed=sum(f.failed for f in usage.features),
        features=[
            DashboardAiFeature(feature=f.feature, label=f.label, requests=f.requests, failed=f.failed)
            for f in usage.features
        ],
    )

    latest = admin.briefings.latest_rounds(4)
    briefings = DashboardBriefings(
        latest=latest,
        delayed_or_failed=sum(1 for r in latest if r.status in ("failed", "missing") or r.delayed),
    )

    members = state.accounts.summary()
    return Dashboard(
        generated_at=utc_iso(now),
        ledger=ledger,
        graph=graph,
        candidates=candidates,
        jobs=jobs,
        ai=ai,
        briefings=briefings,
        members=DashboardMembers(
            registered=members["registered"],
            active_member_sessions=members["member_sessions"],
            active_guest_sessions=members["guest_sessions"],
            source="bff-mock",
        ),
        audit=DashboardAudit(last24h=admin.audit.count_since(now - timedelta(hours=24))),
    )


@router.get("/audit-log", response_model=AuditPage)
def audit_log(
    state: State,
    action: Annotated[str | None, Query(max_length=80)] = None,
    actor: Annotated[str | None, Query(max_length=200)] = None,
    target_type: Annotated[str | None, Query(alias="targetType", max_length=80)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> AuditPage:
    """Who did what, when and why (newest first). Passwords and cookies are never recorded."""
    try:
        before = int(cursor) if cursor else None
    except ValueError as exc:
        raise ApiError(422, "invalid_cursor", "cursor 값이 올바르지 않습니다.") from exc
    items, next_id = state.admin.audit.page(
        action=action, actor=actor, target_type=target_type, q=q, limit=limit, cursor=before
    )
    return AuditPage(
        items=[
            AuditEntry(
                id=i["id"],
                at=i["at"],
                actor_kind=i["actor_kind"],
                actor_id=i["actor_id"],
                actor_email=i["actor_email"],
                action=i["action"],
                target_type=i["target_type"],
                target_id=i["target_id"],
                reason=i["reason"],
                outcome=i["outcome"],
                detail=i["detail"],
            )
            for i in items
        ],
        next_cursor=str(next_id) if next_id is not None else None,
    )
