"""HTTP routers, one module per API area."""

from ..schemas import ErrorResponse

ERROR_RESPONSES: dict[int | str, dict] = {
    code: {"model": ErrorResponse, "description": desc}
    for code, desc in {
        401: "unauthenticated",
        403: "forbidden (guest session or foreign resource)",
        404: "not found",
        409: "conflict",
        422: "validation error",
        503: "source_unavailable: the approved-issue source could not be read",
    }.items()
}

ADMIN_ERROR_RESPONSES: dict[int | str, dict] = {
    code: {"model": ErrorResponse, "description": desc}
    for code, desc in {
        401: "admin_auth_required / admin_session_expired: admin login needed",
        403: "admin_forbidden: a member or guest session cannot use admin APIs",
        404: "not found",
        409: "conflict (state does not allow the change)",
        422: "validation error",
        503: "ledger_unavailable / source_unavailable",
    }.items()
}
