from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query

from ..admin_schemas import (
    ActivateResponse,
    ActivationOut,
    CandidateDetail,
    CandidateList,
    DecisionRequest,
    DecisionResponse,
    GraphDbVersionState,
    GraphVersionList,
    GraphVersionOut,
    Overview,
    PublishResponse,
    ReasonRequest,
    RuleList,
    RuleSwitchRequest,
    RuleSwitchResponse,
)
from ..deps import Admin, State, require_admin
from ..errors import ApiError
from ..graph_versions import GraphVersion
from . import ADMIN_ERROR_RESPONSES

router = APIRouter(
    prefix="/api/admin",
    tags=["admin-pipeline"],
    dependencies=[Depends(require_admin)],
    responses=ADMIN_ERROR_RESPONSES,
)

CandidateId = Annotated[str, Path(max_length=200)]


def version_out(state: State, v: GraphVersion) -> GraphVersionOut:
    graphs = state.admin.graphs
    activated = graphs.activated_at(v.id)
    gd = v.graph_db
    return GraphVersionOut(
        id=v.id,
        sequence=v.sequence,
        kind=v.kind,  # type: ignore[arg-type]
        created_at=v.created_at,
        created_by=v.created_by,
        reason=v.reason,
        source_label=v.source_label,
        policy_version=v.policy_version,
        issue_count=v.issue_count,
        relation_count=v.relation_count,
        article_count=v.article_count,
        candidate_count=v.candidate_count,
        synthetic=v.synthetic,
        sha256=v.sha256,
        bytes=v.bytes,
        active=activated is not None,
        activated_at=activated,
        graph_db=GraphDbVersionState(
            status=gd.get("status", "unknown"),
            pending_jobs_at_creation=gd.get("pendingJobsAtCreation"),
            note=gd.get("note"),
        ),
    )


@router.get("/pipeline/overview", response_model=Overview)
def overview(state: State, _: Admin) -> Overview:
    """Ledger counts (PoC ``inspect()``), active policy, review state, GraphDB projection and past runs."""
    usage = state.admin.usage.response("all", state.admin.jobs.all_data())
    return state.admin.pipeline.overview(usage.past_runs)


@router.get("/pipeline/candidates", response_model=CandidateList)
def candidates(
    state: State,
    _: Admin,
    status: Literal["ALLOW", "HOLD", "REJECT"] | None = None,
    decision: Literal["none", "allow", "reject"] | None = None,
    active: bool | None = None,
    published: bool | None = None,
    rule: bool | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> CandidateList:
    return state.admin.pipeline.candidates(
        status=status, decision=decision, active=active, published=published, rule=rule, q=q, limit=limit, cursor=cursor
    )


@router.get("/pipeline/candidates/{candidate_id}", response_model=CandidateDetail)
def candidate(candidate_id: CandidateId, state: State, _: Admin) -> CandidateDetail:
    return state.admin.pipeline.candidate(candidate_id)


@router.post("/pipeline/candidates/{candidate_id}/decision", response_model=DecisionResponse)
def decide(candidate_id: CandidateId, body: DecisionRequest, state: State, admin: Admin) -> DecisionResponse:
    """allow/reject a candidate or one of its relations. Repeating the effective decision is a no-op."""
    return state.admin.pipeline.decide(candidate_id, body, admin.actor)


@router.get("/pipeline/rules", response_model=RuleList)
def rules(state: State, _: Admin) -> RuleList:
    """Publication rules (e.g. ``R1@2``): switch, what they cover, what they published, switch history."""
    return state.admin.pipeline.rules()


@router.put("/pipeline/rules/{rule_id}", response_model=RuleSwitchResponse)
def switch_rule(
    rule_id: Annotated[str, Path(max_length=64)], body: RuleSwitchRequest, state: State, admin: Admin
) -> RuleSwitchResponse:
    """Turn a rule on or off (reason required, audited). Asking for the state it is already in writes nothing."""
    return state.admin.pipeline.switch_rule(rule_id, body, admin.actor)


@router.get("/graph/versions", response_model=GraphVersionList)
def versions(state: State, _: Admin) -> GraphVersionList:
    graphs = state.admin.graphs
    graphs.ensure_seed()
    return GraphVersionList(
        active_version_id=graphs.active_id(),
        items=[version_out(state, v) for v in graphs.versions()],
        activations=[
            ActivationOut(
                version_id=a.version_id,
                previous_version_id=a.previous_version_id,
                at=a.at,
                admin_email=a.admin_email,
                reason=a.reason,
                action=a.action,  # type: ignore[arg-type]
            )
            for a in graphs.activations()
        ],
    )


@router.post("/graph/versions", response_model=PublishResponse, status_code=201)
def publish(body: ReasonRequest, state: State, admin: Admin) -> PublishResponse:
    """Store the PoC ledger as a new immutable version and make it the one users see."""
    state.admin.graphs.ensure_seed()
    version, previous = state.admin.pipeline.publish(admin.actor, body.reason)
    return PublishResponse(version=version_out(state, version), previous_active_version_id=previous)


@router.post("/graph/versions/{version_id}/activate", response_model=ActivateResponse)
def activate(
    version_id: Annotated[str, Path(max_length=64)], body: ReasonRequest, state: State, admin: Admin
) -> ActivateResponse:
    """Roll back to (or forward to) an existing version. Re-activating the active one is a no-op."""
    graphs = state.admin.graphs
    graphs.ensure_seed()
    previous, idempotent = graphs.activate(version_id, admin=admin.actor, reason=body.reason)
    if not idempotent:
        state.admin.audit.record(
            admin.actor,
            "graph.activate",
            "graph-version",
            version_id,
            reason=body.reason,
            detail={"previousActiveVersionId": previous},
        )
    active = graphs.active_id()
    if active is None:  # unreachable: ensure_seed registered one
        raise ApiError(503, "source_unavailable", "게시된 그래프 버전이 없습니다.")
    return ActivateResponse(active_version_id=active, previous_active_version_id=previous, idempotent=idempotent)
