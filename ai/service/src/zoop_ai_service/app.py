"""The five `/internal/v1` routes. HTTP framing only: auth, headers, bounded strict body parsing, error envelope, request id.

Order is fixed: authentication and scope, then headers, then body. Documentation, CORS, proxy headers and the server header are
off. An unexpected exception becomes a bare `internal_error` envelope; its text is never sent or logged.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Path, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth import authenticate
from .config import Principal
from .jobs import ApiError, JobService, Observation, Reply
from .logs import emit
from .wire import KINDS, ErrorBody, ErrorEnvelope, JobStatus, ResultEnvelope

JOB_ID = re.compile(r"[A-Za-z0-9_.-]{1,120}")
REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
MAX_BODY = 2_000_000
DRAIN_LIMIT = 8 * 1024 * 1024
DRAIN_SECONDS = 2.0
SUBMIT_KEYS = frozenset({"schemaVersion", "jobId", "kind", "mode", "input", "provenance"})
JOB_ID_PATTERN = JOB_ID.pattern
PATH_JOB_ID = Path(alias="jobId", description="Runtime job id; equals the Idempotency-Key used at submit.",
                   json_schema_extra={"pattern": "^" + JOB_ID_PATTERN + "$"})


def invalid(field: str) -> ApiError:
    return ApiError(422, "invalid_request", field=field)


def _context(request: Request) -> dict[str, Any]:
    return request.scope["zoop"]


def require(scope_name: str) -> Callable[[Request], Principal]:
    def dependency(request: Request) -> Principal:
        principal = authenticate(request.app.state.service.config.principals, request.headers.get("authorization"))
        if principal is None:
            raise ApiError(401, "authentication_required", headers={"WWW-Authenticate": "Bearer"})
        _context(request)["principal"] = principal.name
        if scope_name not in principal.scopes:
            raise ApiError(403, "scope_denied")
        return principal
    return dependency


def _duplicate_free(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _no_constant(_: str) -> Any:
    raise ValueError("non-finite number")


def check_content_type(request: Request) -> None:
    media, _, parameters = request.headers.get("content-type", "").partition(";")
    allowed = {"", "charset=utf-8", 'charset="utf-8"'}
    if media.strip().lower() != "application/json" or not {p.strip().lower() for p in parameters.split(";")} <= allowed:
        raise ApiError(415, "unsupported_media_type")


async def read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isascii() or not declared.isdigit()):
        raise invalid("Content-Length")
    if declared is not None and int(declared) > MAX_BODY:
        # The refusal is already determined: answer now. Never wait on a body the client may never send; the gateway drains a
        # little of it after the response has gone out, only so that a client that is mid-upload can still read the 413.
        raise ApiError(413, "request_too_large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            raise ApiError(413, "request_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


def parse_submit(raw: bytes, key: str) -> dict[str, Any]:
    """Strict UTF-8 JSON object without duplicate keys; the runtime does the contract validation of the content."""
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_free, parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise invalid("body") from None
    if (not isinstance(value, dict) or set(value) != SUBMIT_KEYS or value["schemaVersion"] != "zoop-ai-s1-1"
            or value["kind"] not in KINDS or value["mode"] not in ("replay", "live")
            or not isinstance(value["input"], dict) or not isinstance(value["provenance"], dict)):
        raise invalid("body")
    if value["jobId"] != key:
        raise invalid("Idempotency-Key")
    return value


def respond(reply: Reply) -> JSONResponse:
    return JSONResponse(reply.body.wire(), status_code=reply.status, headers=reply.headers)


async def drain(receive: Callable[[], Awaitable[dict[str, Any]]]) -> None:
    """After a 413 has been sent: read (and discard) a bounded amount of the rest of the upload for a bounded time."""
    async def consume() -> None:
        taken = 0
        while taken <= DRAIN_LIMIT:
            message = await receive()
            if message["type"] == "http.disconnect" or not message.get("more_body", False):
                return
            taken += len(message.get("body", b""))

    try:
        await asyncio.wait_for(consume(), DRAIN_SECONDS)
    except Exception:  # timeout or a broken connection: the refusal is already sent
        pass


class Gateway:
    """Outermost ASGI layer: request id, hardening headers, the access log line and a catch-all that never leaks exception text."""

    def __init__(self, app: Callable[..., Awaitable[None]]):
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        raw = next((value for name, value in scope["headers"] if name == b"x-request-id"), b"").decode("latin-1")
        request_id = raw if REQUEST_ID.fullmatch(raw) else str(uuid.uuid4())
        context: dict[str, Any] = {"requestId": request_id}
        scope["zoop"] = context
        started, status, began = False, 500, time.monotonic()
        body_done = False

        async def watch(*_: Any) -> dict[str, Any]:
            nonlocal body_done
            message = await receive()
            if message["type"] == "http.disconnect" or not message.get("more_body", False):
                body_done = True
            return message

        async def relay(message: dict[str, Any]) -> None:
            nonlocal started, status
            if message["type"] == "http.response.start":
                started, status = True, message["status"]
                drop = {b"x-request-id", b"cache-control", b"server"}
                headers = [(k, v) for k, v in message["headers"] if k.lower() not in drop]
                headers += [(b"x-request-id", request_id.encode("ascii")), (b"cache-control", b"no-store"),
                            (b"x-content-type-options", b"nosniff")]
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, watch, relay)
        except Exception as error:
            context["errorClass"] = type(error).__name__
            if not started:
                envelope = ErrorEnvelope(error=ErrorBody(code="internal_error", retryable=False, request_id=request_id))
                await JSONResponse(envelope.wire(), status_code=500)(scope, watch, relay)
        finally:
            if status == 413 and not body_done:
                await drain(watch)
            route = getattr(scope.get("route"), "path", None)
            seen = context.get("seen")
            scope["app"].state.log({
                "event": "request", "requestId": request_id, "principal": context.get("principal"),
                "method": scope["method"], "route": route or "unmatched", "jobId": context.get("jobId"), "status": status,
                "error": context.get("error"), "errorClass": context.get("errorClass"),
                "runtime": seen.runtime if seen else [], "problem": seen.problem if seen else None,
                "durationMs": round((time.monotonic() - began) * 1000, 1)})


def _error_response(error: ApiError, request: Request) -> JSONResponse:
    context = _context(request)
    context["error"] = error.code
    return JSONResponse(error.envelope(context["requestId"]).wire(), status_code=error.status, headers=error.headers)


ERRORS = {
    401: {"model": ErrorEnvelope, "description": "authentication_required: missing, malformed or unknown bearer token."},
    403: {"model": ErrorEnvelope, "description": "scope_denied: the principal lacks this route's scope."},
    404: {"model": ErrorEnvelope, "description": "job_not_found: unknown job, another principal's job, or a reservation that was never accepted."},
    422: {"model": ErrorEnvelope, "description": "invalid_request: header, path, JSON envelope or runtime input validation."},
    500: {"model": ErrorEnvelope, "description": "runtime_binding_mismatch or internal_error."},
    503: {"model": ErrorEnvelope, "description": "runtime_unavailable, service_configuration_invalid, service_busy or queue_full (retryable)."},
}


def create_app(service: JobService | None = None) -> FastAPI:
    """With no service this builds the route skeleton only (OpenAPI export); a service makes it serve requests."""
    app = FastAPI(title="Zoop internal AI analysis transport", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None,
                  redirect_slashes=False)
    app.state.service, app.state.log = service, emit
    app.add_middleware(Gateway)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        return _error_response(error, request)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        location = error.errors()[0]["loc"] if error.errors() else ()
        return _error_response(invalid(str(location[-1]) if location else "request"), request)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = {404: "route_not_found", 405: "method_not_allowed"}.get(error.status_code, "internal_error")
        return _error_response(ApiError(error.status_code, code, headers=dict(error.headers or {})), request)

    async def call(request: Request, operation: str, principal: Principal, job_id: str | None = None, *args: Any) -> JSONResponse:
        context = _context(request)
        seen = context["seen"] = Observation()
        if job_id is not None:
            if not JOB_ID.fullmatch(job_id):
                raise invalid("jobId")
            context["jobId"] = job_id
        reply = await run_in_threadpool(getattr(request.app.state.service, operation), principal.name, job_id, *args, seen)
        return respond(reply)

    @app.post("/internal/v1/analysis-jobs", operation_id="submitAnalysisJob", tags=["analysis-jobs"], status_code=202,
              response_model=JobStatus, summary="Register and queue an S1 analysis job",
              responses={**{code: model for code, model in ERRORS.items() if code != 404}, 200: {"model": JobStatus, "description": "Idempotent replay of an already accepted job."},
                         409: {"model": ErrorEnvelope, "description": "idempotency_conflict, job_id_unavailable, job_input_conflict or execution_unavailable."},
                         413: {"model": ErrorEnvelope, "description": "request_too_large"},
                         415: {"model": ErrorEnvelope, "description": "unsupported_media_type"}})
    async def submit(request: Request, principal: Annotated[Principal, Depends(require("analysis.submit"))],
                     idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", description="Must equal body.jobId.")] = None,
                     x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        check_content_type(request)
        key = request.headers.get("idempotency-key", "")
        if not JOB_ID.fullmatch(key):
            raise invalid("Idempotency-Key")
        body = parse_submit(await read_body(request), key)
        context = _context(request)
        context["jobId"] = key
        seen = context["seen"] = Observation()
        reply = await run_in_threadpool(request.app.state.service.submit, principal.name, key, body, seen)
        return respond(reply)

    @app.get("/internal/v1/analysis-jobs/{jobId}", operation_id="getAnalysisJobStatus", tags=["analysis-jobs"],
             response_model=JobStatus, summary="Current job status (no content fields)", responses=ERRORS)
    async def status(request: Request, principal: Annotated[Principal, Depends(require("analysis.read"))],
                     job_id: Annotated[str, PATH_JOB_ID], x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        return await call(request, "status", principal, job_id)

    @app.get("/internal/v1/analysis-jobs/{jobId}/result", operation_id="getAnalysisJobResult", tags=["analysis-jobs"],
             response_model=ResultEnvelope, summary="Job result for the importer, gated by current source rights", responses=ERRORS)
    async def result(request: Request, principal: Annotated[Principal, Depends(require("analysis.read"))],
                     job_id: Annotated[str, PATH_JOB_ID], x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        return await call(request, "result", principal, job_id)

    @app.post("/internal/v1/analysis-jobs/{jobId}/cancel", operation_id="cancelAnalysisJob", tags=["analysis-jobs"],
              response_model=JobStatus, summary="Cancel a job (idempotent)",
              responses={**ERRORS, 409: {"model": ErrorEnvelope, "description": "job_already_terminal: the job is ready or failed."}})
    async def cancel(request: Request, principal: Annotated[Principal, Depends(require("analysis.cancel"))],
                     job_id: Annotated[str, PATH_JOB_ID], x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        return await call(request, "cancel", principal, job_id)

    @app.post("/internal/v1/analysis-jobs/{jobId}/recover", operation_id="recoverAnalysisJob", tags=["analysis-jobs"],
              status_code=202, response_model=JobStatus, summary="Explicitly re-dispatch a recoverable job (idempotent)",
              responses={**ERRORS, 200: {"model": JobStatus, "description": "A dispatch is already pending or in flight; the request was coalesced."},
                         409: {"model": ErrorEnvelope, "description": "reconcile_required or job_not_recoverable."}})
    async def recover(request: Request, principal: Annotated[Principal, Depends(require("analysis.recover"))],
                      job_id: Annotated[str, PATH_JOB_ID], x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        return await call(request, "recover", principal, job_id)

    return app
