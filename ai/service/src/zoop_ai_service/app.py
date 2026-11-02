"""The five S1 `/internal/v1/analysis-jobs` routes, the five S2 `/internal/v1/extraction-jobs` routes, the eight S3 `/internal/v1/relation-jobs` routes (five job routes, three review-operation routes) the two read-only `/internal/v1/graph-versions` routes, the two read-only `/internal/v1/graph-handoffs` routes, the synchronous `/internal/v1/chat-stages/{stage}` route and the content-free `/internal/v1/chat-mcp-health` probe. HTTP framing only: auth, headers, bounded strict body parsing, error envelope, request id.

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
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, FastAPI, Header, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth import authenticate
from .chat_stages import ChatStages
from .chat_wire import STAGES, ChatMcpHealth, ChatStageRequest, ChatStageResult
from .config import Principal
from .jobs import ApiError, JobService, Observation, Reply
from .logs import emit
from .extraction_jobs import ExtractionError, ExtractionJobs
from .extraction_wire import ExtractionErrorEnvelope, ExtractionJobStatus, ExtractionResultEnvelope, ExtractionSubmit
from .graph_reads import GraphError, GraphReads
from .graph_wire import COMPANY_ID_PATTERN, VERSION_ID_PATTERN, GraphErrorEnvelope, GraphFocusResult, GraphVersionStatus
from .handoff_reads import HandoffError, HandoffReads
from .handoff_wire import HANDOFF_ID_PATTERN, HdBundle, HdErrorEnvelope, HdStatus
from .handoff_exposure_reads import HandoffExposureReads
from .handoff_exposure_wire import MAX_COMMAND as EXPOSURE_MAX_BODY, ExposureQuery, HdExposure
from .observation_reads import ObservationError, ObservationReads
from .observation_wire import MAX_INPUT as OBSERVATION_MAX_BODY, ObservationExport, ObservationExportRequest
from .relation_jobs import RelationError, RelationJobs
from .relation_wire import RelationErrorEnvelope, RelationJobStatus, RelationOperationStatus, RelationResultEnvelope, RelationReview, RelationSubmit
from .wire import KINDS, ErrorBody, ErrorEnvelope, JobStatus, ResultEnvelope
from .plan_wire import (MAX_BODY as PLAN_MAX_BODY, MAX_COUNTER, PLAN_ID_PATTERN, POLICY_ETAG_PATTERN, PlanAdmissionEnvelope,
                        PlanErrorEnvelope, PlanPolicyState, PlanPolicyUpdate, parse_plan_policy, parse_plan_reference)
from .round_service import RoundService
from .round_wire import ROUND_ID_PATTERN, HandoffRequest, HandoffStatus, RunRequest, RunStatus

if TYPE_CHECKING:
    from .plan_admission import PlanAdmissionService

JOB_ID = re.compile(r"[A-Za-z0-9_.-]{1,120}")
REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
MAX_BODY = 2_000_000
DRAIN_LIMIT = 8 * 1024 * 1024
DRAIN_SECONDS = 2.0
SUBMIT_KEYS = frozenset({"schemaVersion", "jobId", "kind", "mode", "input", "provenance"})
JOB_ID_PATTERN = JOB_ID.pattern
PATH_JOB_ID = Path(alias="jobId", description="Runtime job id; equals the Idempotency-Key used at submit.",
                   json_schema_extra={"pattern": "^" + JOB_ID_PATTERN + "$"})
PATH_OPERATION_ID = Path(alias="operationId", description="The review operation's id: the Idempotency-Key of the POST that created it.",
                         json_schema_extra={"pattern": "^" + JOB_ID_PATTERN + "$"})
PATH_VERSION_ID = Path(alias="versionId", description="An allowlisted graph version id.", json_schema_extra={"pattern": VERSION_ID_PATTERN})
PATH_HANDOFF_ID = Path(alias="handoffId", description="An allowlisted handoff id.", json_schema_extra={"pattern": HANDOFF_ID_PATTERN})
RELATION_PREFIX = "/internal/v1/relation-jobs"
EXTRACTION_PREFIX = "/internal/v1/extraction-jobs"
GRAPH_PREFIX = "/internal/v1/graph-versions"
HANDOFF_PREFIX = "/internal/v1/graph-handoffs"
VERSION_ID = re.compile(VERSION_ID_PATTERN)
PLAN_PREFIX = "/internal/v1/plan-admissions"
POLICY_PATH = "/internal/v1/plan-admission-policy"
PLAN_ID = re.compile(PLAN_ID_PATTERN)
POLICY_ETAG = re.compile(POLICY_ETAG_PATTERN)
HANDOFF_ID = re.compile(HANDOFF_ID_PATTERN)


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


async def read_body(request: Request, maximum: int = MAX_BODY) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isascii() or not declared.isdigit()):
        raise invalid("Content-Length")
    if declared is not None and int(declared) > maximum:
        # The refusal is already determined: answer now. Never wait on a body the client may never send; the gateway drains a
        # little of it after the response has gone out, only so that a client that is mid-upload can still read the 413.
        raise ApiError(413, "request_too_large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > maximum:
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


def parse_chat_stage(raw: bytes, key: str) -> ChatStageRequest:
    """Strict UTF-8 JSON object without duplicate keys and exactly the envelope keys; the installed `zoop-ai-chat` validates the stage input."""
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_free, parse_constant=_no_constant)
        request = ChatStageRequest.model_validate(value)
    except (UnicodeDecodeError, ValueError, RecursionError, ValidationError):
        raise invalid("body") from None
    if request.invocation_id != key:
        raise invalid("Idempotency-Key")
    return request


def parse_relation_submit(raw: bytes, key: str) -> RelationSubmit:
    """Strict UTF-8 JSON object without duplicate keys, then the strict S3 Submit model. Unlike S1 the service validates the content
    itself: it needs the upstream identity for authorization before it may touch a ledger or a child process."""
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_free, parse_constant=_no_constant)
        body = RelationSubmit.model_validate(value)
    except (UnicodeDecodeError, ValueError, RecursionError, ValidationError):  # pydantic's ValidationError is a ValueError
        raise invalid("body") from None
    if body.job_id != key:
        raise invalid("Idempotency-Key")
    return body


def parse_extraction_submit(raw: bytes, key: str) -> ExtractionSubmit:
    """Strict UTF-8 JSON object without duplicate keys, then the strict S2 submit reference: only schemaVersion, jobId and approvedRequestDigest.
    A snapshot, catalogue, observation, path or fixture in the body is an unknown field and is refused."""
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_free, parse_constant=_no_constant)
        body = ExtractionSubmit.model_validate(value)
    except (UnicodeDecodeError, ValueError, RecursionError, ValidationError):  # pydantic's ValidationError is a ValueError
        raise invalid("body") from None
    if body.job_id != key:
        raise invalid("Idempotency-Key")
    return body


def parse_relation_review(raw: bytes) -> RelationReview:
    """Strict UTF-8 JSON object without duplicate keys, then the strict review model. The reviewer is never part of it."""
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_free, parse_constant=_no_constant)
        return RelationReview.model_validate(value)
    except (UnicodeDecodeError, ValueError, RecursionError, ValidationError):  # pydantic's ValidationError is a ValueError
        raise invalid("body") from None


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
                body = ErrorBody(code="internal_error", retryable=False, request_id=request_id)
                if str(scope.get("path", "")).startswith(RELATION_PREFIX):
                    envelope: Any = RelationErrorEnvelope(error=body)
                elif str(scope.get("path", "")).startswith(EXTRACTION_PREFIX):
                    envelope = ExtractionErrorEnvelope(error=body)
                elif str(scope.get("path", "")).startswith(GRAPH_PREFIX):
                    envelope = GraphErrorEnvelope(error=body)
                elif str(scope.get("path", "")).startswith(HANDOFF_PREFIX):
                    envelope = HdErrorEnvelope(error=body)
                elif str(scope.get("path", "")).startswith((PLAN_PREFIX, POLICY_PATH)):
                    envelope = PlanErrorEnvelope(error=body)
                else:
                    envelope = ErrorEnvelope(error=body)
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
                "durationMs": round((time.monotonic() - began) * 1000, 1),
                **({"operationId": context["operationId"]} if "operationId" in context else {}),
                **({"versionId": context["versionId"]} if "versionId" in context else {}),
                **({"handoffId": context["handoffId"]} if "handoffId" in context else {})})


def _error_response(error: ApiError, request: Request) -> JSONResponse:
    context = _context(request)
    context["error"] = error.code
    if request.url.path.startswith(("/internal/v1/round-runs", "/internal/v1/round-handoffs")):
        body = ErrorBody(code=error.code, retryable=error.code in {
            "round_busy", "service_busy", "runtime_busy", "runtime_unavailable", "plan_verifier_unavailable", "analysis_incomplete"},
            request_id=context["requestId"], runtime_code=error.runtime_code, field=error.field)
        return JSONResponse(ErrorEnvelope(error=body, status=None).wire(), status_code=error.status, headers=error.headers)
    if request.url.path.startswith((PLAN_PREFIX, POLICY_PATH)):
        body = ErrorBody(code=error.code, retryable=error.code in {
            "service_busy", "plan_verifier_unavailable", "service_configuration_invalid", "authority_unavailable"},
            request_id=context["requestId"], runtime_code=error.runtime_code, field=error.field)
        return JSONResponse(PlanErrorEnvelope(error=body).wire(), status_code=error.status, headers=error.headers)
    if request.url.path.startswith(RELATION_PREFIX) and not isinstance(error, RelationError):
        # Framework-level refusals (auth, headers, body, unknown route) on the relation family use its own envelope schema.
        error = RelationError(error.status, error.code, runtime_code=error.runtime_code, field=error.field, headers=error.headers)
    elif request.url.path.startswith(EXTRACTION_PREFIX) and not isinstance(error, ExtractionError):
        error = ExtractionError(error.status, error.code, runtime_code=error.runtime_code, field=error.field, headers=error.headers)
    elif request.url.path.startswith(GRAPH_PREFIX) and not isinstance(error, GraphError):
        error = GraphError(error.status, error.code, runtime_code=error.runtime_code, field=error.field, headers=error.headers)
    elif request.url.path.startswith(HANDOFF_PREFIX) and not isinstance(error, HandoffError):
        error = HandoffError(error.status, error.code, runtime_code=error.runtime_code, field=error.field, headers=error.headers)
    return JSONResponse(error.envelope(context["requestId"]).wire(), status_code=error.status, headers=error.headers)


ERRORS = {
    401: {"model": ErrorEnvelope, "description": "authentication_required: missing, malformed or unknown bearer token."},
    403: {"model": ErrorEnvelope, "description": "scope_denied: the principal lacks this route's scope."},
    404: {"model": ErrorEnvelope, "description": "job_not_found: unknown job, another principal's job, or a reservation that was never accepted."},
    422: {"model": ErrorEnvelope, "description": "invalid_request: header, path, JSON envelope or runtime input validation."},
    500: {"model": ErrorEnvelope, "description": "runtime_binding_mismatch or internal_error."},
    503: {"model": ErrorEnvelope, "description": "runtime_unavailable, service_configuration_invalid, service_busy or queue_full (retryable)."},
}

RELATION_ERRORS = {
    401: {"model": RelationErrorEnvelope, "description": "authentication_required: missing, malformed or unknown bearer token."},
    403: {"model": RelationErrorEnvelope, "description": "scope_denied: the principal lacks this route's scope."},
    404: {"model": RelationErrorEnvelope, "description": "job_not_found: unknown job, another principal's job, or a reservation that was never accepted."},
    409: {"model": RelationErrorEnvelope, "description": "execution_unavailable: the relation configuration group is not enabled."},
    422: {"model": RelationErrorEnvelope, "description": "invalid_request: header, path or JSON envelope validation."},
    500: {"model": RelationErrorEnvelope, "description": "runtime_binding_mismatch or internal_error."},
    503: {"model": RelationErrorEnvelope, "description": "runtime_unavailable, runtime_busy, service_configuration_invalid, service_busy or queue_full (retryable)."},
}

EXTRACTION_ERRORS = {
    401: {"model": ExtractionErrorEnvelope, "description": "authentication_required: missing, malformed or unknown bearer token."},
    403: {"model": ExtractionErrorEnvelope, "description": "scope_denied: the principal lacks this route's scope."},
    404: {"model": ExtractionErrorEnvelope, "description": "job_not_found: unknown job, another principal's job, or a reservation that was never accepted."},
    409: {"model": ExtractionErrorEnvelope, "description": "execution_unavailable: the extraction configuration group is not enabled."},
    422: {"model": ExtractionErrorEnvelope, "description": "invalid_request: header, path or JSON envelope validation."},
    500: {"model": ExtractionErrorEnvelope, "description": "runtime_binding_mismatch or internal_error."},
    503: {"model": ExtractionErrorEnvelope, "description": "runtime_unavailable, runtime_busy, service_configuration_invalid, service_busy or queue_full (retryable)."},
}

GRAPH_ERRORS = {
    401: {"model": GraphErrorEnvelope, "description": "authentication_required: missing, malformed or unknown bearer token."},
    403: {"model": GraphErrorEnvelope, "description": "scope_denied: the principal lacks `graph.read`; or version_not_allowed: the version is not listed for this principal (unknown and unlisted answer alike)."},
    404: {"model": GraphErrorEnvelope, "description": "version_not_found: the operator listed the version but the graph ledger has none (an operator configuration gap), or route_not_found."},
    409: {"model": GraphErrorEnvelope, "description": "execution_unavailable: the graph configuration group is not enabled."},
    422: {"model": GraphErrorEnvelope, "description": "invalid_request: path, query parameter (unknown, duplicate, missing or out of range) or header validation."},
    500: {"model": GraphErrorEnvelope, "description": "runtime_binding_mismatch or internal_error."},
    503: {"model": GraphErrorEnvelope, "description": "runtime_unavailable, runtime_busy, service_configuration_invalid or service_busy (retryable); never an empty graph."},
}

CHAT_ERRORS = {
    401: {"model": ErrorEnvelope, "description": "authentication_required: missing, malformed or unknown bearer token."},
    403: {"model": ErrorEnvelope, "description": "scope_denied: the principal lacks `chat.invoke`."},
    409: {"model": ErrorEnvelope, "description": "execution_unavailable: the chat configuration group is not enabled, or a replay request without a configured fixture."},
    422: {"model": ErrorEnvelope, "description": "invalid_request: header, path, envelope, or the stage input the runtime refused. Nothing was sent."},
    500: {"model": ErrorEnvelope, "description": "internal_error."},
    502: {"model": ErrorEnvelope, "description": "stage_outcome_unknown: the runtime ended abnormally or its output was unreadable. It may have sent the request: never resend this invocation."},
    503: {"model": ErrorEnvelope, "description": "runtime_unavailable, service_busy or service_configuration_invalid (retryable): nothing was sent."},
    504: {"model": ErrorEnvelope, "description": "stage_outcome_unknown: the stage deadline passed. It may have sent the request: never resend this invocation."},
}

CHAT_PROBE_ERRORS = {
    401: CHAT_ERRORS[401],
    403: CHAT_ERRORS[403],
    409: CHAT_ERRORS[409],
    422: {"model": ErrorEnvelope, "description": "invalid_request: query parameters are not accepted."},
    500: CHAT_ERRORS[500],
    502: {"model": ErrorEnvelope, "description": "probe_failed: the probe child ended abnormally or returned an invalid result."},
    503: {"model": ErrorEnvelope, "description": "runtime_unavailable, service_busy or service_configuration_invalid (retryable)."},
    504: {"model": ErrorEnvelope, "description": "probe_failed: the content-free MCP probe deadline passed."},
}

HANDOFF_ERRORS = {
    401: {"model": HdErrorEnvelope, "description": "authentication_required: missing, malformed or unknown bearer token."},
    403: {"model": HdErrorEnvelope, "description": "scope_denied: the principal lacks `handoff.read`; or handoff_not_allowed: the handoff is not listed for this principal (unknown, unlisted and another principal's answer alike)."},
    404: {"model": HdErrorEnvelope, "description": "handoff_not_found: the operator listed the handoff but the handoff ledger has none (an operator configuration gap), or route_not_found."},
    409: {"model": HdErrorEnvelope, "description": "execution_unavailable: the handoff configuration group is not enabled."},
    422: {"model": HdErrorEnvelope, "description": "invalid_request: path, query parameter (any is refused) or header validation."},
    500: {"model": HdErrorEnvelope, "description": "runtime_contract_mismatch, runtime_binding_mismatch or internal_error (not retryable)."},
    503: {"model": HdErrorEnvelope, "description": "runtime_unavailable, runtime_busy, service_configuration_invalid or service_busy (retryable); never an empty bundle."},
}


EXPOSURE_ERRORS = {
    **HANDOFF_ERRORS,
    403: {"model": HdErrorEnvelope, "description": "scope_denied: requires handoff.exposure, independent of handoff.read; handoff_not_allowed: any selected entry absent or changed."},
    409: {"model": HdErrorEnvelope, "description": "execution_unavailable, handoff_selection_unmappable or handoff_pin_mismatch; no partial report."},
    413: {"model": HdErrorEnvelope, "description": "request_too_large: declared or streamed body exceeds 65,536 bytes."},
    415: {"model": HdErrorEnvelope, "description": "unsupported_media_type: requires application/json with UTF-8."},
    422: {"model": HdErrorEnvelope, "description": "invalid_request, changed_identity_unknown, changed_relation_unused or exposure_report_limit."},
}
EXPOSURE_ERRORS.pop(404)

PLAN_ERRORS = {
    code: {"model": PlanErrorEnvelope, "description": description}
    for code, description in {
        401: "authentication_required.",
        403: "scope_denied or policy_denied.",
        404: "admission_not_found or plan_not_found; other-principal records are indistinguishable from missing.",
        409: "execution_unavailable, admission_disabled, policy_expired, policy_changed, policy_mismatch, quota_exhausted, authority_collision, idempotency_conflict or plan_verification_failed.",
        412: "policy_conflict: a new policy operation used a stale If-Match.",
        413: "request_too_large: body exceeds 2,000,000 bytes.",
        415: "unsupported_media_type: requires application/json with UTF-8.",
        422: "invalid_request: exact body, header, path or query shape.",
        500: "internal_error; no diagnostic text is disclosed.",
        503: "service_busy, plan_verifier_unavailable, service_configuration_invalid or authority_unavailable.",
    }.items()
}


OBSERVATION_ERRORS = {
    code: {"model": ErrorEnvelope, "description": description}
    for code, description in {
        401: "authentication_required: missing, malformed or unknown bearer token.",
        403: "scope_denied or source_unauthorized: current read/store/quote-display rights are required.",
        404: "round_not_found, observation_not_found or document_version_not_in_round.",
        409: "registry_changed, scope_configuration_conflict or preparation_profile_unbound; never recover automatically.",
        413: "request_too_large: declared or streamed body exceeds 2,000,000 bytes.",
        415: "unsupported_media_type: requires application/json with UTF-8.",
        422: "invalid_request: exact closed native selector; no query parameters.",
        500: "runtime_contract_mismatch, runtime_binding_mismatch or internal_error; no content is returned.",
        503: "execution_unavailable (group disabled), runtime_busy, service_busy, runtime_unavailable or service_configuration_invalid.",
    }.items()
}


def create_app(service: JobService | None = None, relation: RelationJobs | None = None, extraction: ExtractionJobs | None = None,
               graph: GraphReads | None = None, handoff: HandoffReads | None = None,
               handoff_exposure: HandoffExposureReads | None = None, chat: ChatStages | None = None, *,
               plans: PlanAdmissionService | None = None, observation: ObservationReads | None = None,
               rounds: RoundService | None = None) -> FastAPI:
    """With no service this builds the route skeleton only (OpenAPI export); a service makes it serve requests. `relation` is the
    S3 relation-job family, `extraction` the S2 extraction-job family, `graph` the read-only graph-version family and `handoff` the read-only handoff family; without one, every
    route of that family answers 409 `execution_unavailable` after authentication."""
    app = FastAPI(title="Zoop internal AI analysis transport", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None,
                  redirect_slashes=False)
    app.state.service, app.state.relation, app.state.extraction, app.state.graph, app.state.handoff, app.state.log = service, relation, extraction, graph, handoff, emit
    app.state.handoff_exposure = handoff_exposure
    app.state.chat = chat
    app.state.plans = plans
    app.state.observation = observation
    app.state.rounds = rounds
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

    def relation_service(request: Request) -> RelationJobs:
        relation = request.app.state.relation
        if relation is None:
            raise RelationError(409, "execution_unavailable")  # the all-or-nothing relation configuration group is not enabled
        return relation

    async def relation_call(request: Request, operation: str, principal: Principal, job_id: str) -> JSONResponse:
        relation = relation_service(request)
        context = _context(request)
        seen = context["seen"] = Observation()
        if not JOB_ID.fullmatch(job_id):
            raise invalid("jobId")
        context["jobId"] = job_id
        reply = await run_in_threadpool(getattr(relation, operation), principal.name, job_id, seen)
        return respond(reply)

    @app.post("/internal/v1/relation-jobs", operation_id="submitRelationJob", tags=["relation-jobs"], status_code=202,
              response_model=RelationJobStatus, summary="Register and queue an S3 relation job over an allowlisted S2 upstream",
              responses={**{code: model for code, model in RELATION_ERRORS.items() if code != 404},
                         200: {"model": RelationJobStatus, "description": "Idempotent replay of an already accepted job."},
                         403: {"model": RelationErrorEnvelope, "description": "scope_denied, or upstream_not_allowed: the upstream job and digest are not listed for this principal."},
                         409: {"model": RelationErrorEnvelope, "description": "idempotency_conflict, job_id_unavailable, job_input_conflict, upstream_unavailable or execution_unavailable."},
                         413: {"model": RelationErrorEnvelope, "description": "request_too_large"},
                         415: {"model": RelationErrorEnvelope, "description": "unsupported_media_type"}})
    async def relation_submit(request: Request, principal: Annotated[Principal, Depends(require("relation.submit"))],
                              idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", description="Must equal body.jobId.")] = None,
                              x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        relation = relation_service(request)
        check_content_type(request)
        key = request.headers.get("idempotency-key", "")
        if not JOB_ID.fullmatch(key):
            raise invalid("Idempotency-Key")
        body = parse_relation_submit(await read_body(request), key)
        context = _context(request)
        context["jobId"] = key
        seen = context["seen"] = Observation()
        reply = await run_in_threadpool(relation.submit, principal.name, key, body, seen)
        return respond(reply)

    @app.get("/internal/v1/relation-jobs/{jobId}", operation_id="getRelationJobStatus", tags=["relation-jobs"],
             response_model=RelationJobStatus, summary="Current relation job status (no content fields)", responses=RELATION_ERRORS)
    async def relation_status(request: Request, principal: Annotated[Principal, Depends(require("relation.read"))],
                              job_id: Annotated[str, PATH_JOB_ID], x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        return await relation_call(request, "status", principal, job_id)

    @app.get("/internal/v1/relation-jobs/{jobId}/result", operation_id="getRelationJobResult", tags=["relation-jobs"],
             response_model=RelationResultEnvelope, summary="Relation candidates, only while every delivery gate holds", responses=RELATION_ERRORS)
    async def relation_result(request: Request, principal: Annotated[Principal, Depends(require("relation.read"))],
                              job_id: Annotated[str, PATH_JOB_ID], x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        return await relation_call(request, "result", principal, job_id)

    @app.post("/internal/v1/relation-jobs/{jobId}/cancel", operation_id="cancelRelationJob", tags=["relation-jobs"],
              response_model=RelationJobStatus, summary="Cancel a relation job (idempotent; a ready job is refused)",
              responses={**RELATION_ERRORS, 409: {"model": RelationErrorEnvelope, "description": "job_already_terminal: the job is ready."}})
    async def relation_cancel(request: Request, principal: Annotated[Principal, Depends(require("relation.cancel"))],
                              job_id: Annotated[str, PATH_JOB_ID], x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        return await relation_call(request, "cancel", principal, job_id)

    @app.post("/internal/v1/relation-jobs/{jobId}/recover", operation_id="recoverRelationJob", tags=["relation-jobs"],
              status_code=202, response_model=RelationJobStatus, summary="Explicitly resume a stopped, queued or interrupted relation job (idempotent)",
              responses={**RELATION_ERRORS, 200: {"model": RelationJobStatus, "description": "A dispatch is already pending or in flight; the request was coalesced."},
                         409: {"model": RelationErrorEnvelope, "description": "reconcile_required or job_not_recoverable."}})
    async def relation_recover(request: Request, principal: Annotated[Principal, Depends(require("relation.recover"))],
                               job_id: Annotated[str, PATH_JOB_ID], x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        return await relation_call(request, "recover", principal, job_id)

    async def relation_operation_call(request: Request, operation: str, principal: Principal, job_id: str, operation_id: str) -> JSONResponse:
        relation = relation_service(request)
        context = _context(request)
        seen = context["seen"] = Observation()
        if not JOB_ID.fullmatch(job_id):
            raise invalid("jobId")
        if not JOB_ID.fullmatch(operation_id):
            raise invalid("operationId")
        context["jobId"], context["operationId"] = job_id, operation_id
        reply = await run_in_threadpool(getattr(relation, operation), principal.name, job_id, operation_id, seen)
        return respond(reply)

    @app.post("/internal/v1/relation-jobs/{jobId}/reviews", operation_id="submitRelationReview", tags=["relation-jobs"], status_code=200,
              response_model=RelationOperationStatus, summary="Record one allow (final approval) / reject (exclusion) review of a HOLD relation candidate (one operation per Idempotency-Key)",
              responses={**{code: model for code, model in RELATION_ERRORS.items() if code not in (403, 404, 409)},
                         200: {"model": RelationOperationStatus, "description": "The decision is recorded in the AI relation ledger and is terminal: an allow is the operator's final approval (revalidation not_requested, next none), a reject an exclusion. Also the answer to a replay of an existing operation, including one recorded under the earlier revalidation contract (its `limitation` says so)."},
                         403: {"model": RelationErrorEnvelope, "description": "scope_denied, or upstream_not_allowed: the job's upstream is not (any more) listed for this principal."},
                         404: {"model": RelationErrorEnvelope, "description": "job_not_found (unknown or another principal's job) or relation_candidate_not_found."},
                         409: {"model": RelationErrorEnvelope, "description": "source_version_conflict, source_revision_conflict, review_target_not_hold, review_call_in_flight, review_candidate_ineligible, review_contract_changed, job_cancelled, idempotency_conflict, operation_id_unavailable, upstream_unavailable or execution_unavailable. A refusal records nothing."},
                         413: {"model": RelationErrorEnvelope, "description": "request_too_large"},
                         415: {"model": RelationErrorEnvelope, "description": "unsupported_media_type"}})
    async def relation_review(request: Request, principal: Annotated[Principal, Depends(require("relation.review"))],
                              job_id: Annotated[str, PATH_JOB_ID],
                              idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", description="The stable id of this review operation.")] = None,
                              x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        relation = relation_service(request)
        check_content_type(request)
        if not JOB_ID.fullmatch(job_id):
            raise invalid("jobId")
        key = request.headers.get("idempotency-key", "")
        if not JOB_ID.fullmatch(key):
            raise invalid("Idempotency-Key")
        body = parse_relation_review(await read_body(request))
        context = _context(request)
        context["jobId"], context["operationId"] = job_id, key
        seen = context["seen"] = Observation()
        reply = await run_in_threadpool(relation.review, principal.name, job_id, key, body, seen)
        return respond(reply)

    @app.get("/internal/v1/relation-jobs/{jobId}/reviews/{operationId}", operation_id="getRelationReviewOperation", tags=["relation-jobs"],
             response_model=RelationOperationStatus, summary="Look up one review operation by its key (content-free, from the service ledger)",
             responses={**{code: model for code, model in RELATION_ERRORS.items() if code != 404},
                        404: {"model": RelationErrorEnvelope, "description": "job_not_found or operation_not_found: unknown, another principal's, or another job's."}})
    async def relation_operation(request: Request, principal: Annotated[Principal, Depends(require("relation.read"))],
                                 job_id: Annotated[str, PATH_JOB_ID], operation_id: Annotated[str, PATH_OPERATION_ID],
                                 x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        return await relation_operation_call(request, "operation", principal, job_id, operation_id)

    def extraction_service(request: Request) -> ExtractionJobs:
        extraction_jobs = request.app.state.extraction
        if extraction_jobs is None:
            raise ExtractionError(409, "execution_unavailable")  # the all-or-nothing extraction configuration group is not enabled
        return extraction_jobs

    async def extraction_call(request: Request, operation: str, principal: Principal, job_id: str) -> JSONResponse:
        extraction_jobs = extraction_service(request)
        context = _context(request)
        seen = context["seen"] = Observation()
        if not JOB_ID.fullmatch(job_id):
            raise invalid("jobId")
        context["jobId"] = job_id
        reply = await run_in_threadpool(getattr(extraction_jobs, operation), principal.name, job_id, seen)
        return respond(reply)

    @app.post("/internal/v1/extraction-jobs", operation_id="submitExtractionJob", tags=["extraction-jobs"], status_code=202,
              response_model=ExtractionJobStatus, summary="Register and queue an operator-approved S2 extraction job",
              responses={**{code: model for code, model in EXTRACTION_ERRORS.items() if code != 404},
                         200: {"model": ExtractionJobStatus, "description": "Idempotent replay of an already accepted job."},
                         403: {"model": ExtractionErrorEnvelope, "description": "scope_denied, or request_not_approved: no approval is listed for this principal, job id and digest."},
                         409: {"model": ExtractionErrorEnvelope, "description": "idempotency_conflict, job_id_unavailable, job_input_conflict, approval_changed, request_unavailable or execution_unavailable."},
                         413: {"model": ExtractionErrorEnvelope, "description": "request_too_large"},
                         415: {"model": ExtractionErrorEnvelope, "description": "unsupported_media_type"}})
    async def extraction_submit(request: Request, principal: Annotated[Principal, Depends(require("extraction.submit"))],
                                idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", description="Must equal body.jobId.")] = None,
                                x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        extraction_jobs = extraction_service(request)
        check_content_type(request)
        key = request.headers.get("idempotency-key", "")
        if not JOB_ID.fullmatch(key):
            raise invalid("Idempotency-Key")
        body = parse_extraction_submit(await read_body(request), key)
        context = _context(request)
        context["jobId"] = key
        seen = context["seen"] = Observation()
        reply = await run_in_threadpool(extraction_jobs.submit, principal.name, key, body, seen)
        return respond(reply)

    @app.get("/internal/v1/extraction-jobs/{jobId}", operation_id="getExtractionJobStatus", tags=["extraction-jobs"],
             response_model=ExtractionJobStatus, summary="Current extraction job status (no content fields)", responses=EXTRACTION_ERRORS)
    async def extraction_status(request: Request, principal: Annotated[Principal, Depends(require("extraction.read"))],
                                job_id: Annotated[str, PATH_JOB_ID], x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        return await extraction_call(request, "status", principal, job_id)

    @app.get("/internal/v1/extraction-jobs/{jobId}/result", operation_id="getExtractionJobResult", tags=["extraction-jobs"],
             response_model=ExtractionResultEnvelope, summary="Event and topic candidates, only while every delivery gate holds", responses=EXTRACTION_ERRORS)
    async def extraction_result(request: Request, principal: Annotated[Principal, Depends(require("extraction.read"))],
                                job_id: Annotated[str, PATH_JOB_ID], x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        return await extraction_call(request, "result", principal, job_id)

    @app.post("/internal/v1/extraction-jobs/{jobId}/cancel", operation_id="cancelExtractionJob", tags=["extraction-jobs"],
              response_model=ExtractionJobStatus, summary="Cancel an extraction job (idempotent; a ready job is refused)",
              responses={**EXTRACTION_ERRORS, 409: {"model": ExtractionErrorEnvelope, "description": "job_already_terminal: the job is ready."}})
    async def extraction_cancel(request: Request, principal: Annotated[Principal, Depends(require("extraction.cancel"))],
                                job_id: Annotated[str, PATH_JOB_ID], x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        return await extraction_call(request, "cancel", principal, job_id)

    @app.post("/internal/v1/extraction-jobs/{jobId}/recover", operation_id="recoverExtractionJob", tags=["extraction-jobs"],
              status_code=202, response_model=ExtractionJobStatus, summary="Explicitly resume a stopped, queued or interrupted extraction job (idempotent)",
              responses={**{code: model for code, model in EXTRACTION_ERRORS.items() if code not in (403, 409)},
                         200: {"model": ExtractionJobStatus, "description": "A dispatch is already pending or in flight; the request was coalesced."},
                         403: {"model": ExtractionErrorEnvelope, "description": "scope_denied, or request_not_approved: the approval was removed or changed."},
                         409: {"model": ExtractionErrorEnvelope, "description": "reconcile_required, job_not_recoverable, approval_changed, fixture_changed or execution_unavailable."}})
    async def extraction_recover(request: Request, principal: Annotated[Principal, Depends(require("extraction.recover"))],
                                 job_id: Annotated[str, PATH_JOB_ID], x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        return await extraction_call(request, "recover", principal, job_id)

    def graph_service(request: Request) -> GraphReads:
        graph_reads = request.app.state.graph
        if graph_reads is None:
            raise GraphError(409, "execution_unavailable")  # the all-or-nothing graph configuration group is not enabled
        return graph_reads

    def graph_query(request: Request, names: tuple[str, ...]) -> None:
        """Exactly the named query parameters, each once: anything else (an unknown or repeated key) is refused, never ignored."""
        if sorted(key for key, _ in request.query_params.multi_items()) != sorted(names):
            raise invalid("query")

    @app.get("/internal/v1/graph-versions/{versionId}", operation_id="getGraphVersionStatus", tags=["graph-versions"],
             response_model=GraphVersionStatus, summary="Verified, content-free status of one allowlisted graph version", responses=GRAPH_ERRORS)
    async def graph_status(request: Request, principal: Annotated[Principal, Depends(require("graph.read"))],
                           version_id: Annotated[str, PATH_VERSION_ID], x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        graph_reads = graph_service(request)
        graph_query(request, ())
        if not VERSION_ID.fullmatch(version_id):
            raise invalid("versionId")
        context = _context(request)
        context["versionId"] = version_id
        seen = context["seen"] = Observation()
        return respond(await run_in_threadpool(graph_reads.status, principal.name, version_id, seen))

    @app.get("/internal/v1/graph-versions/{versionId}/focus", operation_id="getGraphVersionFocus", tags=["graph-versions"],
             response_model=GraphFocusResult, summary="One company's neighbourhood (depth 1 to 3) of an allowlisted graph version, only while it verifies now",
             responses=GRAPH_ERRORS)
    async def graph_focus(request: Request, principal: Annotated[Principal, Depends(require("graph.read"))],
                          version_id: Annotated[str, PATH_VERSION_ID],
                          company_id: Annotated[str, Query(alias="companyId", pattern=COMPANY_ID_PATTERN, description="A company id of the version's canonical namespace.")],
                          depth: Annotated[str, Query(alias="depth", pattern=r"^[1-3]$", description="Hop depth: exactly 1, 2 or 3.")],
                          x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        graph_reads = graph_service(request)
        graph_query(request, ("companyId", "depth"))
        if not VERSION_ID.fullmatch(version_id):
            raise invalid("versionId")
        context = _context(request)
        context["versionId"] = version_id
        seen = context["seen"] = Observation()
        return respond(await run_in_threadpool(graph_reads.focus, principal.name, version_id, company_id, int(depth), seen))

    def handoff_service(request: Request) -> HandoffReads:
        handoff_reads = request.app.state.handoff
        if handoff_reads is None:
            raise HandoffError(409, "execution_unavailable")  # the all-or-nothing handoff configuration group is not enabled
        return handoff_reads

    async def handoff_call(request: Request, operation: str, principal: Principal, handoff_id: str) -> JSONResponse:
        handoff_reads = handoff_service(request)
        graph_query(request, ())
        if not HANDOFF_ID.fullmatch(handoff_id):
            raise invalid("handoffId")
        context = _context(request)
        context["handoffId"] = handoff_id
        seen = context["seen"] = Observation()
        return respond(await run_in_threadpool(getattr(handoff_reads, operation), principal.name, handoff_id, seen))

    @app.post("/internal/v1/graph-handoffs/exposure", operation_id="queryGraphHandoffExposure", tags=["graph-handoffs"],
              response_model=HdExposure, summary="Identity-only exposure of an explicit complete handoff selection", responses=EXPOSURE_ERRORS)
    async def handoff_exposure_query(request: Request, principal: Annotated[Principal, Depends(require("handoff.exposure"))],
                                     x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        reads = request.app.state.handoff_exposure
        if reads is None:
            raise HandoffError(409, "execution_unavailable")
        graph_query(request, ())
        check_content_type(request)
        raw = await read_body(request, EXPOSURE_MAX_BODY)
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_free, parse_constant=_no_constant)
            query = ExposureQuery.model_validate(value)
        except (UnicodeError, ValueError, RecursionError):
            raise invalid("body") from None
        seen = _context(request)["seen"] = Observation()
        return respond(await run_in_threadpool(reads.query, principal.name, query, seen))

    @app.get("/internal/v1/graph-handoffs/{handoffId}", operation_id="getGraphHandoffStatus", tags=["graph-handoffs"],
             response_model=HdStatus, summary="Verified, content-free status of one allowlisted AI handoff", responses=HANDOFF_ERRORS)
    async def handoff_status(request: Request, principal: Annotated[Principal, Depends(require("handoff.read"))],
                             handoff_id: Annotated[str, PATH_HANDOFF_ID], x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        return await handoff_call(request, "status", principal, handoff_id)

    @app.get("/internal/v1/graph-handoffs/{handoffId}/bundle", operation_id="getGraphHandoffBundle", tags=["graph-handoffs"],
             response_model=HdBundle, summary="The whole bundle of an allowlisted AI handoff, only while it verifies now and matches the operator's pins",
             responses=HANDOFF_ERRORS)
    async def handoff_bundle(request: Request, principal: Annotated[Principal, Depends(require("handoff.read"))],
                             handoff_id: Annotated[str, PATH_HANDOFF_ID], x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        return await handoff_call(request, "bundle", principal, handoff_id)

    @app.get("/internal/v1/chat-mcp-health", operation_id="probeChatMcp", tags=["chat-stages"], status_code=200,
             response_model=ChatMcpHealth, summary="Probe the configured ZOOP MCP endpoint without a grant or model call",
             responses={**CHAT_PROBE_ERRORS, 200: {"model": ChatMcpHealth,
                                                    "description": "The endpoint answered its own unauthenticated refusal, or the probe classified why it was unreachable."}})
    async def chat_mcp_health(request: Request, _principal: Annotated[Principal, Depends(require("chat.invoke"))],
                              x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        chat_stages = request.app.state.chat
        if chat_stages is None:
            raise ApiError(409, "execution_unavailable")
        graph_query(request, ())
        context = _context(request)
        seen = context["seen"] = Observation()
        result = await run_in_threadpool(chat_stages.probe_mcp, seen)
        return JSONResponse(result.wire(), status_code=200)

    @app.post("/internal/v1/observations/export", operation_id="exportObservation", tags=["observations"],
              response_model=ObservationExport, summary="Export one exact observation with current read/store/quote-display rights",
              responses=OBSERVATION_ERRORS)
    async def observation_export(request: Request, principal: Annotated[Principal, Depends(require("observation.read"))],
                                 x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> Response:
        reads = request.app.state.observation
        if reads is None:
            raise ObservationError(503, "execution_unavailable", retry_after=30)
        graph_query(request, ())
        plan_headers(request)
        check_content_type(request)
        raw = await read_body(request, OBSERVATION_MAX_BODY)
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_free, parse_constant=_no_constant)
            selector = ObservationExportRequest.model_validate(value)
        except (UnicodeError, ValueError, RecursionError):
            raise invalid("body") from None
        seen = _context(request)["seen"] = Observation()
        exported = await run_in_threadpool(reads.export, selector, seen)
        return Response(exported, media_type="application/json")

    @app.post("/internal/v1/chat-stages/{stage}", operation_id="invokeChatStage", tags=["chat-stages"], status_code=200,
              response_model=ChatStageResult, summary="Run one chatbot model stage synchronously: router, answer, verification or agent",
              responses={**CHAT_ERRORS, 200: {"model": ChatStageResult,
                                                "description": "The stage ran (or its stored outcome was returned). `status=failed` is a stage outcome, not a transport error."}})
    async def chat_stage(request: Request, principal: Annotated[Principal, Depends(require("chat.invoke"))],
                         stage: Annotated[str, Path(description="chat-router, chat-answer, chat-verification or chat-agent.",
                                                    json_schema_extra={"enum": list(STAGES)})],
                         idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", description="Must equal body.invocationId.")] = None,
                         x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        chat_stages = request.app.state.chat
        if chat_stages is None:
            raise ApiError(409, "execution_unavailable")  # the all-or-nothing chat configuration group is not enabled
        if stage not in STAGES:
            raise invalid("stage")
        check_content_type(request)
        key = request.headers.get("idempotency-key", "")
        body = parse_chat_stage(await read_body(request), key)
        context = _context(request)
        context["jobId"] = key
        seen = context["seen"] = Observation()
        status, result = await run_in_threadpool(chat_stages.invoke, principal.name, stage, body, seen)
        return JSONResponse(result.wire(), status_code=status)

    def plan_service(request: Request) -> PlanAdmissionService:
        facade = request.app.state.plans
        if facade is None:
            raise ApiError(409, "execution_unavailable")
        return facade

    def plan_headers(request: Request, *required: str) -> None:
        # Headers with authority/framing meaning must occur exactly once, never
        # use a proxy/framework's arbitrary choice among duplicate values.
        for name in ("content-type", "content-length", "idempotency-key", "if-match"):
            values = request.headers.getlist(name)
            if len(values) > 1 or (name in required and len(values) != 1):
                raise invalid(name)
        if "transfer-encoding" in request.headers and "content-length" in request.headers:
            raise invalid("Content-Length")

    @app.post(PLAN_PREFIX, operation_id="admitPlan", tags=["plan-admissions"], status_code=201,
              response_model=PlanAdmissionEnvelope, summary="Admit one exact verified plan; never dispatch",
              responses={**{code: value for code, value in PLAN_ERRORS.items() if code != 412},
                         200: {"model": PlanAdmissionEnvelope, "description": "Original immutable admission, including an inactive historical admission."}})
    async def plan_admit(request: Request, principal: Annotated[Principal, Depends(require("plan.admit"))],
                         idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
                         x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        facade = plan_service(request)
        graph_query(request, ())
        plan_headers(request, "idempotency-key")
        key = request.headers.get("idempotency-key", "")
        if not PLAN_ID.fullmatch(key):
            raise invalid("Idempotency-Key")
        check_content_type(request)
        reference = parse_plan_reference(await read_body(request, PLAN_MAX_BODY), key)
        seen = _context(request)["seen"] = Observation()
        return respond(await run_in_threadpool(facade.admit, principal.name, reference, seen))

    @app.get(PLAN_PREFIX + "/{planId}", operation_id="getPlanAdmission", tags=["plan-admissions"],
             response_model=PlanAdmissionEnvelope, summary="Read an immutable exact admission and current policy authority",
             responses={code: value for code, value in PLAN_ERRORS.items() if code not in (412, 413, 415)})
    async def plan_status(request: Request, principal: Annotated[Principal, Depends(require("plan.read"))],
                          plan_id: Annotated[str, Path(alias="planId", json_schema_extra={"pattern": PLAN_ID_PATTERN})],
                          plan_digest: Annotated[str | None, Query(alias="planDigest", description="Required exact lowercase SHA-256 plan digest.")] = None,
                          x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        facade = plan_service(request)
        graph_query(request, ("planDigest",))
        plan_headers(request)
        if not PLAN_ID.fullmatch(plan_id):
            raise invalid("planId")
        if plan_digest is None or not re.fullmatch(r"[0-9a-f]{64}", plan_digest):
            raise invalid("planDigest")
        seen = _context(request)["seen"] = Observation()
        return respond(await run_in_threadpool(facade.status, principal.name, plan_id, plan_digest, seen))

    @app.get(POLICY_PATH, operation_id="getPlanAdmissionPolicy", tags=["plan-admission-policy"],
             response_model=PlanPolicyState, summary="Operator-only current policy and cumulative usage",
             responses={code: value for code, value in PLAN_ERRORS.items() if code not in (404, 412, 413, 415)})
    async def plan_policy_status(request: Request, principal: Annotated[Principal, Depends(require("plan.policy"))],
                                 x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        facade = plan_service(request)
        graph_query(request, ())
        plan_headers(request)
        seen = _context(request)["seen"] = Observation()
        return respond(await run_in_threadpool(facade.policy_status, principal.name, seen))

    @app.put(POLICY_PATH, operation_id="setPlanAdmissionPolicy", tags=["plan-admission-policy"],
             response_model=PlanPolicyUpdate, summary="Operator-only idempotent policy CAS; retires prior admissions",
             responses={code: value for code, value in PLAN_ERRORS.items() if code != 404})
    async def plan_policy_update(request: Request, principal: Annotated[Principal, Depends(require("plan.policy"))],
                                 idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
                                 if_match: Annotated[str | None, Header(alias="If-Match")] = None,
                                 x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> JSONResponse:
        facade = plan_service(request)
        graph_query(request, ())
        plan_headers(request, "idempotency-key", "if-match")
        key = request.headers.get("idempotency-key", "")
        expected = request.headers.get("if-match", "")
        if not JOB_ID.fullmatch(key):
            raise invalid("Idempotency-Key")
        if len(expected) > 100 or not POLICY_ETAG.fullmatch(expected) or int(expected.split("-")[2]) > MAX_COUNTER:
            raise invalid("If-Match")
        check_content_type(request)
        document = parse_plan_policy(await read_body(request, PLAN_MAX_BODY))
        seen = _context(request)["seen"] = Observation()
        return respond(await run_in_threadpool(facade.set_policy, principal.name, key, document, expected, seen))

    def round_service(request: Request) -> RoundService:
        if request.app.state.rounds is None:
            raise ApiError(503, "execution_unavailable")
        return request.app.state.rounds

    async def round_submit(request: Request, principal: Principal, family: str):
        facade = round_service(request)
        graph_query(request, ())
        plan_headers(request, "idempotency-key")
        key = request.headers.get("idempotency-key", "")
        if not re.fullmatch(ROUND_ID_PATTERN, key):
            raise invalid("Idempotency-Key")
        check_content_type(request)
        raw = await read_body(request, 4_001_024 if family == "handoff" else 1024)
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_free, parse_constant=_no_constant)
            model = HandoffRequest if family == "handoff" else RunRequest
            body = model.model_validate(value).wire()
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise invalid("body") from None
        if body["roundId"] != key:
            raise invalid("Idempotency-Key")
        if family == "handoff" and len(json.dumps(body["bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()) > 4_000_000:
            raise ApiError(413, "request_too_large")
        seen = _context(request)["seen"] = Observation()
        return respond(await run_in_threadpool(facade.submit, principal.name, family, body, raw, seen))

    async def round_status(request: Request, principal: Principal, family: str, round_id: str):
        facade = round_service(request)
        graph_query(request, ())
        plan_headers(request)
        if not re.fullmatch(ROUND_ID_PATTERN, round_id):
            raise invalid("roundId")
        seen = _context(request)["seen"] = Observation()
        return respond(await run_in_threadpool(facade.status, principal.name, family, round_id, seen))

    round_errors = {**ERRORS, 404: {"model": ErrorEnvelope, "description": "round_not_found: no exact admission for this principal."},
                    409: {"model": ErrorEnvelope, "description": "request_conflict, round_busy, round_binding_mismatch or analysis_incomplete."},
                    413: {"model": ErrorEnvelope, "description": "request_too_large."},
                    415: {"model": ErrorEnvelope, "description": "unsupported_media_type."}}

    @app.post("/internal/v1/round-runs", operation_id="requestRoundRun", tags=["round-runs"], status_code=202,
              response_model=RunStatus, responses={**round_errors, 200: {"model": RunStatus}})
    async def request_round_run(request: Request, principal: Annotated[Principal, Depends(require("round.run"))],
                                idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
        return await round_submit(request, principal, "run")

    @app.get("/internal/v1/round-runs/{roundId}", operation_id="getRoundRun", tags=["round-runs"],
             response_model=RunStatus, responses=round_errors)
    async def get_round_run(request: Request, principal: Annotated[Principal, Depends(require("round.read"))],
                            round_id: Annotated[str, Path(alias="roundId", pattern=ROUND_ID_PATTERN)]):
        return await round_status(request, principal, "run", round_id)

    @app.post("/internal/v1/round-handoffs", operation_id="requestRoundHandoff", tags=["round-handoffs"], status_code=202,
              response_model=HandoffStatus, responses={**round_errors, 200: {"model": HandoffStatus}})
    async def request_round_handoff(request: Request, principal: Annotated[Principal, Depends(require("round.run"))],
                                    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
        return await round_submit(request, principal, "handoff")

    @app.get("/internal/v1/round-handoffs/{roundId}", operation_id="getRoundHandoff", tags=["round-handoffs"],
             response_model=HandoffStatus, responses=round_errors)
    async def get_round_handoff(request: Request, principal: Annotated[Principal, Depends(require("round.read"))],
                                round_id: Annotated[str, Path(alias="roundId", pattern=ROUND_ID_PATTERN)]):
        return await round_status(request, principal, "handoff", round_id)

    return app
