from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ..admin_auth import ADMIN_COOKIE, SessionView
from ..admin_schemas import AdminInfo, AdminLoginRequest, AdminSession
from ..deps import State
from ..statedb import utc_iso
from . import ADMIN_ERROR_RESPONSES

router = APIRouter(prefix="/api/admin/auth", tags=["admin-auth"])


def session_model(state: State, view: SessionView | None, expired: str | None) -> AdminSession:
    auth = state.admin.auth
    return AdminSession(
        authenticated=view is not None,
        expired=expired is not None,
        expired_reason=expired,  # type: ignore[arg-type]
        admin=AdminInfo(id=view.admin.id, email=view.admin.email, display_name=view.admin.display_name, role="admin")
        if view
        else None,
        expires_at=utc_iso(view.expires_at) if view else None,
        idle_expires_at=utc_iso(view.idle_expires_at) if view else None,
        idle_timeout_seconds=int(auth.idle.total_seconds()),
        absolute_timeout_seconds=int(auth.absolute.total_seconds()),
    )


@router.get("/session", response_model=AdminSession)
def get_session(request: Request, state: State) -> AdminSession:
    """Always 200. Reading the session does not extend the idle window."""
    view, expired = state.admin.auth.inspect(request.cookies.get(ADMIN_COOKIE), touch=False)
    return session_model(state, view, expired)


@router.post(
    "/login",
    response_model=AdminSession,
    responses={k: v for k, v in ADMIN_ERROR_RESPONSES.items() if k in (401, 422)},
)
def login(body: AdminLoginRequest, request: Request, response: Response, state: State) -> AdminSession:
    token, view = state.admin.auth.login(body.email, body.password)  # a failed attempt leaves a live session alone
    state.admin.auth.discard(request.cookies.get(ADMIN_COOKIE))  # the replaced session must not stay valid
    response.set_cookie(
        ADMIN_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=state.settings.cookie_secure,
        path="/",
    )
    return session_model(state, view, None)


@router.post("/logout", status_code=204, response_class=Response)
def logout(request: Request, state: State) -> Response:
    state.admin.auth.logout(request.cookies.get(ADMIN_COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return response
