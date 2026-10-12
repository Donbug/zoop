"""Backend handoff document: the FastAPI-generated schema plus authored semantics and examples.

The route and model schemas come from the application itself (`app.openapi()`), so they cannot drift from the code. What is
authored here is only what code cannot say: the security scheme, the references to the worker's own wire contract
(`ai-contract.schema.json` stays the single authority for Submit/JobResult; it is referenced, never copied), and request/recovery
examples. Every example is built through the real wire models, so an example that stops validating fails at generation.
"""
from __future__ import annotations

from typing import Any

from .wire import SCHEMA, ErrorBody, ErrorEnvelope, JobStatus, ResultEnvelope, next_action

CONTRACT = "ai-contract.schema.json"
STAMP = "2026-10-12T03:00:00Z"
JOB = "synthetic-SYNTH-A-document-summary"
DIGEST = "0" * 64
IDLE_USAGE = {"providerAttempts": 0, "replayCalls": 0, "inputTokens": None, "outputTokens": None, "cachedTokens": None,
              "reasoningTokens": None, "cost": None}

DESCRIPTION = """\
Internal app-to-AI transport for the S1 analysis family (`zoop-ai-s1-1`): document-summary, document-sentiment,
semantic-verification and briefing-outlook. It is a thin, durable HTTP layer over the installed `zoop-ai` CLI; the runtime ledger
stays the only source of job state, and every state shown here is read from the runtime during the same request.

**Network.** The service binds `127.0.0.1` only. Production reach is an HTTPS reverse proxy co-located with it (same host or network
namespace) that terminates TLS, caps bodies at 2,000,000 bytes, never logs `Authorization`, and is reachable only from the app
backend's security group. That proxy is an assumption: nothing here was deployed or observed.

**Authentication.** `Authorization: Bearer <token>`. Tokens are operator-issued; the service stores only SHA-256 digests. The
authenticated principal is the owner of every job it registers; there is no end-user identity in v1. A job owned by another
principal answers exactly like a missing job (404).

**Idempotency.** `Idempotency-Key` is required on submit and must equal `body.jobId`. Retry any ambiguous submit with the *same* key
and body; never mint a new jobId to retry. 202 = newly accepted (the runtime registered the job and the service made its owner
binding and dispatch intent durable); 200 = idempotent replay of an accepted job.

**Lifecycle.** `202` does not mean the job is authorized, budgeted or that any model call happened. Poll `GET /{jobId}` and follow
`next`: `wait` (a dispatch is pending or running), `fetch_result`, `recover` (call the recover route), `operator_reconcile` (stop and
escalate: an attempt has an unknown provider outcome that may have been charged; starting a new jobId accepts that cost) or `none`.
A job interrupted between two stages (some receipt stored, a later stage never sent) is never continued automatically: its dispatch
ends idle with `lastOutcome=needs_recover`, and only an explicit recover sends the next stage.
Internal `ready` is not the public `completed`: the app import must still succeed and re-check its own current authority.

**Results.** `GET /{jobId}/result` returns the runtime's `get` payload (`job`, see `ai-contract.schema.json#/$defs/JobResult`) only
while the server's *current* grant registry still permits delivery; otherwise `delivery.state` is `withheld`, `job` is null and only
content-free per-attempt `receipts` are returned for usage accounting. A live job is withheld with `reason=recipient_unproven` until the
runtime has recorded an attempt for every stage it needs, because only then is the recipient provable. `job.grant` is an execution snapshot, never current authority.
"""


def status(**overrides: Any) -> dict[str, Any]:
    """An authored JobStatus built through the wire model; `next` is derived, so an example cannot contradict the rule."""
    dispatch = {"state": "idle", "command": "run", "dispatchCount": 1, "lastOutcome": "exited", "lastRuntimeCode": None, "updatedAt": STAMP,
                **overrides.pop("dispatch", {})}
    base = {"schemaVersion": SCHEMA, "jobId": JOB, "kind": "document-summary", "mode": "replay", "inputDigest": DIGEST, "state": "ready",
            "phase": "artifact.persisted", "resumeMode": "none", "failure": None, "artifactIds": [], "usage": dict(IDLE_USAGE),
            "unreceiptedAttempts": 0, "dispatch": dispatch, "acceptedAt": STAMP, "observedAt": STAMP, **overrides}
    base["next"] = next_action(base["state"], base["resumeMode"], dispatch["state"])
    return JobStatus.model_validate(base).wire()


def error(code: str, *, retryable: bool = False, runtime_code: str | None = None, field: str | None = None,
          job_status: dict[str, Any] | None = None) -> dict[str, Any]:
    body = ErrorBody(code=code, retryable=retryable, request_id="req-0001", runtime_code=runtime_code, field=field)
    return ErrorEnvelope(error=body, status=None if job_status is None else JobStatus.model_validate(job_status)).wire()


def examples() -> dict[str, dict[str, Any]]:
    """name -> {summary, value} per response, keyed by operation then label."""
    queued = status(state="queued", phase="input.persisted", resumeMode="unsent_only",
                    usage=dict(IDLE_USAGE), artifactIds=[], dispatch={"state": "pending", "dispatchCount": 0, "lastOutcome": None})
    ready = status(artifactIds=["artifact-0001", "artifact-0002"], usage={**IDLE_USAGE, "replayCalls": 2})
    blocked = status(state="queued", phase="input.persisted", resumeMode="unsent_only",
                     dispatch={"lastOutcome": "runtime_error", "lastRuntimeCode": "replay_fixture_required"})
    reconciling = status(state="reconciling", phase="provider.response_unknown", resumeMode="reconcile_only", mode="live",
                         failure={"code": "provider_response_unknown", "stage": "document-summary"}, unreceiptedAttempts=1,
                         usage={**IDLE_USAGE, "providerAttempts": 1})
    exhausted = status(state="failed", phase="authorization_or_budget.failed", resumeMode="unsent_only", mode="live",
                       failure={"code": "global_budget_exhausted", "stage": "semantic-verification"},
                       usage={**IDLE_USAGE, "providerAttempts": 1})
    recovering = status(state="queued", phase="input.persisted", resumeMode="unsent_only",
                        dispatch={"state": "pending", "dispatchCount": 1, "lastOutcome": "runtime_error", "lastRuntimeCode": "replay_fixture_required"})
    cancelled = status(state="cancelled", phase="cancel.requested", dispatch={"state": "idle", "lastOutcome": "cancelled"})
    receipt = {"attemptId": "attempt-0001", "stage": "document-summary", "state": "received", "mode": "live",
               "startedAt": STAMP, "receivedAt": STAMP, "inputDigest": DIGEST,
               "config": {"provider": "openai-compatible", "providerRevision": DIGEST, "model": "example-model", "reasoningEffort": None,
                          "promptVersion": "zoop-document-2026-10-08-2", "schemaVersion": "zoop-ai-s1-1", "policyVersion": "zoop-document-gate-2"},
               "usage": {"inputTokens": 11, "outputTokens": 7, "cachedTokens": 0, "reasoningTokens": 0}, "error": None, "durationMs": 412.5}
    withheld = ResultEnvelope.model_validate({"schemaVersion": SCHEMA, "status": ready, "delivery": {"state": "withheld",
                                              "reason": "source_rights_unknown_or_denied"}, "job": None, "receipts": [receipt]}).wire()
    return {
        "submit.202": {"queuedJob": {"summary": "Newly accepted: registered in the runtime, dispatch pending", "value": queued}},
        "submit.200": {"readyReplay": {"summary": "Same key and body sent again: the actual current state", "value": ready}},
        "status.200": {
            "ready": {"summary": "Finished: fetch the result", "value": ready},
            "blockedByRuntimeConfiguration": {"summary": "Registered but blocked (for example the replay fixture is missing): not a background success. Fix the server input, then call recover",
                                              "value": blocked},
            "reconciling": {"summary": "An attempt has an unknown provider outcome that may have been charged: stop and escalate", "value": reconciling},
            "budgetExhausted": {"summary": "Failed before sending the verify stage: recover re-sends only under the durable ceiling", "value": exhausted},
        },
        "result.200": {"withheld": {"summary": "Current source rights no longer cover delivery: no content, accounting receipts only", "value": withheld}},
        "cancel.200": {"cancelled": {"summary": "Cancelled; an in-flight child is not killed, so its late receipt is still recorded", "value": cancelled}},
        "recover.202": {"enqueued": {"summary": "A dispatch was enqueued", "value": recovering}},
        "recover.200": {"coalesced": {"summary": "A dispatch is already pending or in flight", "value": recovering}},
        "errors": {
            "401": {"summary": "Missing, malformed or unknown bearer token", "value": error("authentication_required")},
            "403": {"summary": "Principal lacks the route's scope", "value": error("scope_denied")},
            "404": {"summary": "Unknown job, another principal's job, or never accepted", "value": error("job_not_found")},
            "409.idempotencyConflict": {"summary": "Same key, different body; the runtime was not called", "value": error("idempotency_conflict")},
            "409.jobIdUnavailable": {"summary": "The jobId is owned by another principal", "value": error("job_id_unavailable")},
            "409.reconcileRequired": {"summary": "Recover of a reconciling job", "value": error("reconcile_required", job_status=reconciling)},
            "409.jobNotRecoverable": {"summary": "Recover of a finished or cancelled job", "value": error("job_not_recoverable", job_status=ready)},
            "409.jobAlreadyTerminal": {"summary": "Cancel of a ready or failed job", "value": error("job_already_terminal", job_status=ready)},
            "422": {"summary": "Runtime validation of the submitted input", "value": error("invalid_request", runtime_code="input_or_configuration_invalid")},
            "503": {"summary": "Runtime unavailable: retry with the same key and body", "value": error("runtime_unavailable", retryable=True)},
        },
    }


def _attach(operation: dict[str, Any], code: str, mapping: dict[str, Any]) -> None:
    operation["responses"][code]["content"]["application/json"]["examples"] = mapping


def build(app: Any, submit_example: dict[str, Any]) -> dict[str, Any]:
    """The full document. `submit_example` is a worker-fixture Submit body (repository-authored synthetic text)."""
    spec = app.openapi()
    sample = examples()
    spec["info"] = {"title": "Zoop internal AI analysis transport", "version": "1.0.0", "description": DESCRIPTION.strip()}
    spec["servers"] = [{"url": "http://127.0.0.1:8797", "description": "Loopback only. Never exposed directly; reach it through a co-located TLS proxy."}]
    spec["tags"] = [{"name": "analysis-jobs", "description": "S1 analysis jobs over the installed zoop-ai runtime."}]
    components = spec["components"]
    components["securitySchemes"] = {"bearerAuth": {"type": "http", "scheme": "bearer",
                                                    "description": "Operator-issued token; the service holds only its SHA-256 digest. Roles are the route scopes."}}
    components["schemas"]["ResultEnvelope"]["properties"]["job"] = {
        "description": "The runtime `get` payload for the importer, present only when delivery.state is available.",
        "oneOf": [{"$ref": f"{CONTRACT}#/$defs/JobResult"}, {"type": "null"}]}
    scopes = {"submitAnalysisJob": "analysis.submit", "getAnalysisJobStatus": "analysis.read", "getAnalysisJobResult": "analysis.read",
              "cancelAnalysisJob": "analysis.cancel", "recoverAnalysisJob": "analysis.recover"}
    for path in spec["paths"].values():
        for operation in path.values():
            operation["security"] = [{"bearerAuth": [scopes[operation["operationId"]]]}]
            for parameter in operation.get("parameters", []):
                if parameter["name"] == "Idempotency-Key":
                    parameter.update(required=True, description="Must equal body.jobId.",
                                     schema={"type": "string", "pattern": "^[A-Za-z0-9_.-]{1,120}$"})
                elif parameter["name"] == "X-Request-ID":
                    parameter.update(description="Optional correlation id, echoed on every response and never used as an idempotency key.",
                                     schema={"type": "string", "pattern": "^[A-Za-z0-9._-]{1,128}$"})
            for code in ("401", "403", "404", "422", "503"):
                if code in operation["responses"]:
                    _attach(operation, code, {"example": {"summary": sample["errors"][code]["summary"], "value": sample["errors"][code]["value"]}})
    base = spec["paths"]["/internal/v1/analysis-jobs"]["post"]
    base["requestBody"] = {"required": True, "content": {"application/json": {
        "schema": {"$ref": f"{CONTRACT}#/$defs/Submit"},
        "examples": {"documentSummary": {"summary": "document-summary job (synthetic fixture text); Idempotency-Key must equal jobId",
                                         "value": submit_example}}}}}
    base["responses"]["202"]["description"] = "Newly accepted: the runtime registered the job and the owner binding and dispatch intent are durable."
    _attach(base, "202", sample["submit.202"])
    _attach(base, "200", sample["submit.200"])
    for code in ("200", "202"):
        base["responses"][code]["headers"] = {
            "Location": {"description": "Status URL of the job.", "schema": {"type": "string"}},
            "Retry-After": {"description": "Seconds to wait before polling; present while next is wait.", "schema": {"type": "integer"}}}
    _attach(base, "409", {"idempotencyConflict": sample["errors"]["409.idempotencyConflict"], "jobIdUnavailable": sample["errors"]["409.jobIdUnavailable"]})
    for path in spec["paths"].values():
        for operation in path.values():
            operation["responses"]["401"]["headers"] = {"WWW-Authenticate": {"description": "Bearer", "schema": {"type": "string"}}}
            operation["responses"]["503"]["headers"] = {"Retry-After": {"description": "Seconds before retrying with the same key and body.", "schema": {"type": "integer"}}}
    status_op = spec["paths"]["/internal/v1/analysis-jobs/{jobId}"]["get"]
    status_op["responses"]["200"]["description"] = "Current job status read from the runtime during this request. It never carries input, artifacts, grants or calls."
    _attach(status_op, "200", sample["status.200"])
    result_op = spec["paths"]["/internal/v1/analysis-jobs/{jobId}/result"]["get"]
    result_op["responses"]["200"]["description"] = "Job result for the importer; content is withheld when current source rights no longer permit delivery."
    _attach(result_op, "200", sample["result.200"])
    cancel = spec["paths"]["/internal/v1/analysis-jobs/{jobId}/cancel"]["post"]
    cancel["responses"]["200"]["description"] = "The job is cancelled (also when it already was)."
    _attach(cancel, "200", sample["cancel.200"])
    _attach(cancel, "409", {"jobAlreadyTerminal": sample["errors"]["409.jobAlreadyTerminal"]})
    recover = spec["paths"]["/internal/v1/analysis-jobs/{jobId}/recover"]["post"]
    recover["responses"]["202"]["description"] = "A dispatch was enqueued."
    _attach(recover, "202", sample["recover.202"])
    _attach(recover, "200", sample["recover.200"])
    _attach(recover, "409", {"reconcileRequired": sample["errors"]["409.reconcileRequired"], "jobNotRecoverable": sample["errors"]["409.jobNotRecoverable"]})
    return spec
