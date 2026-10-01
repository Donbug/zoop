from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.routing import APIRoute

from ..dataset import Dataset
from ..deps import Session, State
from ..errors import ApiError
from ..insights_schemas import TelemetryAccepted, TelemetryBatch
from ..telemetry import MAX_BODY_BYTES
from . import ERROR_RESPONSES


class BodyLimitedRoute(APIRoute):
    """Refuses an oversized body with 413 before it is parsed (``Content-Length``, or the read body without it)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def limited(request: Request) -> Response:
            length = request.headers.get("content-length")
            size = int(length) if length and length.isdigit() else len(await request.body())
            if size > MAX_BODY_BYTES:
                raise ApiError(413, "payload_too_large", f"한 번에 {MAX_BODY_BYTES // 1024}KiB까지만 보낼 수 있습니다.")
            return await handler(request)

        return limited


router = APIRouter(
    prefix="/api/telemetry",
    tags=["telemetry"],
    route_class=BodyLimitedRoute,
    responses={
        **ERROR_RESPONSES,
        413: {"description": "payload_too_large: a batch is at most 16 KiB"},
        429: {"description": "rate_limited: too many events from this session"},
    },
)


def optional_dataset(state: State) -> Dataset | None:
    """The active graph, or None when the source is unreadable (statistics then classify ids as 'other')."""
    try:
        return state.provider.get()
    except ApiError:
        return None


@router.post("", response_model=TelemetryAccepted, status_code=202)
def collect(body: TelemetryBatch, principal: Session, state: State) -> TelemetryAccepted:
    """Behaviour events of the signed-in member or guest session (graph selections, briefing reads, screen views).

    Only the whitelisted event types and fields of ``TelemetryEvent`` are accepted; the subject is stored as a
    member id or a keyed hash of the guest session, never as a name, e-mail address or IP. Fire-and-forget:
    clients ignore failures.
    """
    subject = state.insights.keys.subject(principal.kind, principal.principal_id)
    accepted = state.insights.telemetry.record(subject, body.events, optional_dataset(state))
    return TelemetryAccepted(accepted=accepted)
