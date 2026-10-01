from __future__ import annotations

from fastapi import APIRouter

from ..deps import State
from ..errors import SourceUnavailable
from ..schemas import ErrorBody, HealthCounts, HealthResponse, SourceHealth

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(state: State) -> HealthResponse:
    """BFF liveness (always 200) plus the state of the active published graph version."""
    try:
        ds = state.provider.get()
    except SourceUnavailable as exc:
        return HealthResponse(
            status="unavailable",
            source=SourceHealth(
                mode="snapshot",
                label="graph-version",
                connected=False,
                error=ErrorBody(code=exc.code, message=exc.message, details=exc.details),
            ),
        )
    return HealthResponse(
        status="degraded" if ds.source_errors or ds.warnings else "ok",
        source=SourceHealth(mode=ds.source_mode, label=ds.source_label, connected=True),
        dataset_kind=ds.dataset_kind,
        as_of=ds.as_of,
        graph_version=ds.graph_version,
        counts=HealthCounts(
            issues=len(ds.issues),
            companies=len(ds.companies),
            approved_edges=sum(not e.derived for e in ds.edges.values()),
            derived_edges=sum(e.derived for e in ds.edges.values()),
            evidence=len(ds.evidence),
        ),
        source_errors=list(ds.source_errors),
        warnings=list(ds.warnings),
    )
