from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Response

from ..admin_schemas import JobCreate, JobCreated, JobList, JobOut, JobRetry, ReasonRequest
from ..deps import Admin, State, require_admin
from . import ADMIN_ERROR_RESPONSES

router = APIRouter(
    prefix="/api/admin/jobs",
    tags=["admin-jobs"],
    dependencies=[Depends(require_admin)],
    responses=ADMIN_ERROR_RESPONSES,
)

JobId = Annotated[str, Path(max_length=64)]


@router.get("", response_model=JobList)
def list_jobs(
    state: State,
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> JobList:
    """Recent jobs (each with ``retry`` = whether it can run again and why not), the single-run lock, call
    limits, the sandbox/policy check and ``ingest`` = the article baseline the next run starts from."""
    return state.admin.jobs.listing(status, limit)


@router.post("", response_model=JobCreated, status_code=202)
def create_job(body: JobCreate, response: Response, state: State, admin: Admin) -> JobCreated:
    """Start a PoC job. One job runs at a time: the same kind returns the running one (200, deduplicated)."""
    job, deduplicated = state.admin.jobs.create(
        kind=body.kind,
        reason=body.reason,
        max_model_calls=body.max_model_calls,
        confirm_paid=body.confirm_paid,
        admin=admin.actor,
        dataset=body.dataset,
    )
    if deduplicated:
        response.status_code = 200
    return JobCreated(job=job, deduplicated=deduplicated)


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: JobId, state: State) -> JobOut:
    return state.admin.jobs.get(job_id)


@router.post("/{job_id}/retry", response_model=JobCreated, status_code=202)
def retry_job(job_id: JobId, body: JobRetry, response: Response, state: State, admin: Admin) -> JobCreated:
    """Run a failed or cancelled job again (``retryOf`` links it). Refused 409 ``job_not_retryable`` (details.reason)
    when the job is done, still running, already succeeded in a later run or has a newer attempt. The same job
    already running returns that job (200, deduplicated); a different running job is 409 ``job_in_progress``. A
    job never publishes: users keep seeing the active graph version until an admin publishes a new one."""
    job, deduplicated = state.admin.jobs.retry(
        job_id,
        reason=body.reason,
        max_model_calls=body.max_model_calls,
        confirm_paid=body.confirm_paid,
        admin=admin.actor,
    )
    if deduplicated:
        response.status_code = 200
    return JobCreated(job=job, deduplicated=deduplicated)


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: JobId, body: ReasonRequest, state: State, admin: Admin) -> JobOut:
    return state.admin.jobs.cancel(job_id, reason=body.reason, admin=admin.actor)
