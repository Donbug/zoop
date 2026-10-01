from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends

from ..admin_schemas import AiUsageResponse
from ..deps import State, require_admin
from . import ADMIN_ERROR_RESPONSES

router = APIRouter(
    prefix="/api/admin/ai-usage",
    tags=["admin-ai"],
    dependencies=[Depends(require_admin)],
    responses=ADMIN_ERROR_RESPONSES,
)


@router.get("", response_model=AiUsageResponse)
def ai_usage(state: State, window: Literal["24h", "7d", "30d", "all"] = "7d") -> AiUsageResponse:
    """Per-feature requests, failures, latency, calls and tokens. Cost stays unavailable (no price source)."""
    return state.admin.usage.response(window, state.admin.jobs.all_data())
