"""Backend handoff document: the FastAPI-generated schema plus authored semantics and examples.

The route and model schemas come from the application itself (`app.openapi()`), so they cannot drift from the code. What is
authored here is only what code cannot say: the security scheme, the references to the worker's own wire contract
(`ai-contract.schema.json` stays the single authority for Submit/JobResult; it is referenced, never copied), and request/recovery
examples. Every example is built through the real wire models, so an example that stops validating fails at generation.
"""
from __future__ import annotations

import hashlib
import json

from typing import Any

from . import chat_doc, extraction_doc, graph_doc, handoff_doc
from .handoff_exposure_wire import ExposureQuery
from .observation_wire import ObservationExportRequest
from .relation_ledger import OperationRow
from .relation_review import operation_status
from .relation_wire import (SCHEMA as RELATION_SCHEMA, RelationErrorEnvelope, RelationJobContent, RelationJobStatus, RelationOperationStatus,
                            RelationResultEnvelope, RelationReview, RelationSubmit, next_action as relation_next)
from .wire import SCHEMA, ErrorBody, ErrorEnvelope, JobStatus, ResultEnvelope, next_action
from .plan_wire import (PLAN_ID_PATTERN, PlanAdmissionEnvelope, PlanErrorEnvelope, PlanPolicyDisabled,
                        PlanPolicyEnabled, PlanPolicyState, PlanPolicyUpdate, PlanReference)
from .round_wire import ROUND_ID_PATTERN, HandoffRequest, HandoffStatus, RunRequest, RunStatus

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

**Network.** The service defaults to `127.0.0.1`. `ZOOP_AI_SERVICE_HOST` accepts an explicit literal bind IP for an operator-managed
container deployment behind approved TLS ingress. The ingress must cap bodies at 2,000,000 bytes, protect Authorization,
and restrict callers to the app backend. Configuration does not deploy or authorize that ingress.

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

**S3 relation jobs (`/internal/v1/relation-jobs`, schema `zoop-ai-internal-relation-1`, scopes `relation.*`).** A separate family over the
installed `zoop-ai-relation` pipeline: it shares nothing with the S1 wire contract or state machine. It is off unless its
all-or-nothing server configuration group is set (otherwise every route answers 409 `execution_unavailable` after authentication). A caller
cannot name a path, fixture or registry. The body is the S3 `Submit` (`zoop-relation-s3`) naming an operator-prepared S2 extraction
job as `upstream {jobId, inputDigest}`; that pair must be listed for the calling principal in a server-owned allowlist, otherwise 403
`upstream_not_allowed` before anything is stored. `provenance.executionMode` is `replay` (authored fixtures, no network) or `live`
(`recordingKind: provider`: a real model call that costs money). A live job needs the service's live group (409 `live_unavailable` otherwise) AND an
allowlist entry that pins the runtime identity the operator approved (403 `live_not_approved` otherwise); the pipeline must freeze the job under exactly
that identity (409 `live_binding_mismatch` otherwise), and the pin is re-read before every live child and every delivery. The principal owns the job it
submits: another principal's job answers like a missing one.
The initial dispatch runs once, under the pipeline's own under-lock initial-only restriction (a job that already took its first dispatch is refused with no
effect). A child that timed out, died or answered unreadably, and a dispatch left in flight by a restarted service,
are never run again automatically (`next=recover`); a call the pipeline reserved but never saw answered ends `reconciling` and is never
resent. Only an explicit `recover` dispatches again (and, for a live job, spends again). Cancel refuses a ready job (409 `job_already_terminal`); the pipeline would otherwise withhold it for good. Status never carries content.
`GET /{jobId}/result` returns candidates only for a ready job while the owner is still the principal the allowlist lists for that upstream and the
pipeline reports delivery current (it re-reads the operator source registry on every call); otherwise `delivery.state` is `withheld` with a
reason code. Delivery is checked at one instant: content already sent cannot be recalled, and a revocation after the check is not observed.

**Review (`relation.review`).** `POST /{jobId}/reviews` records one `allow` or `reject` decision on one relation candidate that is on HOLD. `allow` is the
operator's FINAL approval: it is not a re-verification, it appends the event with effect `approved`, it runs no verifier or model call, and the operation is
terminal (200, `revalidation.state=not_requested`, `next=none`). The pipeline still re-runs the deterministic checks (schema, endpoints, exact citations)
and re-reads the current source rights, so an approval can never override an unsupported candidate, an invalid citation or a withdrawn source
(409 `review_candidate_ineligible`, or the pipeline's own refusal), and it is refused while a model call for the job is in flight (409 `review_call_in_flight`).
The earlier automatic verdict and claim distributions stay in the history unchanged. `reject` excludes. The result then shows
`eligibility.approvalBasis` (`automatic-verifier` or `operator-final-approval` with the reviewer, the deciding event's revision and time): internal audit
metadata, never an application approval or a publication.
The `Idempotency-Key` is the stable operation id and the body is exactly `{relationCandidateId, expectedSourceVersion, expectedSourceRevision, decision}`; the
reviewer is always the authenticated principal and cannot be sent. `sourceVersion` is the job's `inputDigest` and `sourceRevision` is the relation's runtime
event-chain revision as a decimal string, both read from `GET /{jobId}/result`. They are runtime values, never the application's own review revision (the
public decision API's `expectedRevision`), which this service does not see and which must never be forwarded. A new decision is checked against both values
exactly, the revision inside the pipeline's own append transaction, and anything that does not match records nothing: 409 `source_version_conflict` or
`source_revision_conflict`, and a relation that is not on hold is `review_target_not_hold`. The same key and body return the existing operation even after the
relation has moved on; another body is `idempotency_conflict`, another principal's key is `operation_id_unavailable`. `review` says whether the decision is
recorded: `unconfirmed` means the request was reserved but the service has no proof yet that the event was appended (a lost reply included), so retry the same
request, which reads the chain for a marker only this operation can have written and never appends twice. `publication` is always `not_published`.
Operation status is read from the service ledger and carries no content. An operation recorded under the EARLIER contract (where `allow` asked for an
automatic revalidation) is history: it stays readable with `limitation=review_contract_changed`, its `revalidation` is `verified`/`superseded` only where its
stored history settled it and `contract_changed` otherwise, it is never dispatched or resent and never read as an approval, and its key answers 409
`review_contract_changed` while unconfirmed: a NEW decision with a new key at the relation's current revision is how to proceed. This slice has no list route.
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


RELATION_JOB = "relation-synthetic-SYNTH-1"
RELATION_ID = "rc-" + "1" * 64
UPSTREAM = {"jobId": "s2-synthetic-extraction", "inputDigest": "2" * 64}
RELATION_USAGE = {"replayCalls": 0, "startedWithoutReceipt": 0, "providerCalls": 0, "modelCalls": 0}
RELATION_SUBMIT = {"schemaVersion": "zoop-relation-s3", "jobId": RELATION_JOB,
                   "provenance": {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"}, "upstream": UPSTREAM}
RELATION_REVIEW = {"relationCandidateId": "rc-" + "1" * 64, "expectedSourceVersion": DIGEST, "expectedSourceRevision": "1", "decision": "allow"}
OPERATION = "review-decision-0001"


def relation_status(**overrides: Any) -> dict[str, Any]:
    """An authored RelationJobStatus built through the wire model; `next` is derived, so an example cannot contradict the rule."""
    dispatch = {"state": "idle", "dispatchCount": 1, "lastOutcome": "exited", "lastRuntimeCode": None, "updatedAt": STAMP, **overrides.pop("dispatch", {})}
    base = {"schemaVersion": RELATION_SCHEMA, "jobId": RELATION_JOB, "inputDigest": DIGEST, "provenance": RELATION_SUBMIT["provenance"],
            "upstream": UPSTREAM, "state": "ready", "phase": "complete", "resumeMode": "none", "failure": None, "usage": {**RELATION_USAGE, "replayCalls": 4},
            "delivery": {"state": "available", "reason": None}, "dispatch": dispatch, "acceptedAt": STAMP, "observedAt": STAMP, **overrides}
    base["next"] = relation_next(base["state"], dispatch["state"])
    return RelationJobStatus.model_validate(base).wire()


def relation_error(code: str, *, retryable: bool = False, runtime_code: str | None = None, field: str | None = None,
                   job_status: dict[str, Any] | None = None, operation: dict[str, Any] | None = None) -> dict[str, Any]:
    body = ErrorBody(code=code, retryable=retryable, request_id="req-0001", runtime_code=runtime_code, field=field)
    return RelationErrorEnvelope(error=body, status=None if job_status is None else RelationJobStatus.model_validate(job_status),
                                 operation=None if operation is None else RelationOperationStatus.model_validate(operation)).wire()


def relation_operation(**overrides: Any) -> dict[str, Any]:
    """An authored operation status built through the real derivation from a ledger row, so an example cannot contradict the rules."""
    row = {"operation_id": OPERATION, "owner": "app", "job_id": RELATION_JOB, "relation_candidate_id": RELATION_ID, "decision": "allow",
           "expected_source_version": DIGEST, "expected_source_revision": 1, "request_digest": DIGEST, "review_state": "applied", "review_attempts": 1,
           "reserved_at": STAMP, "applied_at": STAMP, "applied_event_at": STAMP, "reval_state": None, "reval_count": 0, "busy_count": 0,
           "last_outcome": None, "last_runtime_code": None, "reval_updated_at": None, "settled": None, "settled_eligibility": None, "settled_at": None,
           "contract": "final-approval"}
    return operation_status(OperationRow(**{**row, **overrides}), STAMP).wire()


def relation_content() -> dict[str, Any]:
    """One delivered relation, authored synthetic text, validated through the allowlisted projection."""
    citation = {"documentId": "document-synthetic-1", "documentVersion": "3" * 64, "start": 0, "end": 17, "quote": "합성부품은 합성기업에 배터리 부품을 공급한다."}
    reason = {"code": "claim_supported"}
    relation = {
        "relationCandidateId": RELATION_ID, "sourceVersion": DIGEST, "sourceRevision": "1", "type": "SUPPLIES", "direction": "directed",
        "subject": {"kind": "company", "ref": "SYNTH-3"},
        "object": {"kind": "company", "ref": "SYNTH-1"}, "reordered": False, "connection": "direct", "businessScope": None,
        "productScope": "배터리 부품", "validity": {"from": None, "until": None, "fromStatus": "unknown", "untilStatus": "unknown", "citations": []},
        "countries": [], "context": {"market": "unknown", "check": "unknown", "knownCountries": []}, "citations": [citation], "path": [],
        "generatorReasons": ["authored producer reason"], "proposalCount": 1, "precheck": {"state": "pending", "reasons": []}, "approved": False,
        "eligibility": {"status": "eligible", "reasons": [], "revision": 1, "reviewPending": False,
                        "approvalBasis": {"kind": "automatic-verifier", "revision": 1, "reviewer": None, "decidedAt": STAMP}},
        "history": [{"seq": 1, "kind": "verdict", "createdAt": STAMP, "eligibility": "eligible", "reasons": [reason], "decision": None, "effect": None}],
        "impact": {"status": "not-applicable", "labelNote": "textual impact direction of cited statements; not a price direction, probability or forecast",
                   "candidates": []}}
    content = {"jobId": RELATION_JOB, "inputDigest": DIGEST,
               "counts": {"relations": 1, "eligibility": {"pending": 0, "eligible": 1, "hold": 0, "reject": 0},
                          "impactLabels": {"positive": 0, "negative": 0, "mixed": 0, "undetermined": 0}, "impactCandidates": 0},
               "relations": [relation]}
    return RelationJobContent.model_validate(content).wire()


def relation_examples() -> dict[str, dict[str, Any]]:
    queued = relation_status(state="queued", phase="relation", resumeMode="resume", usage=dict(RELATION_USAGE),
                             delivery={"state": "withheld", "reason": "job_not_ready"}, dispatch={"state": "pending", "dispatchCount": 0, "lastOutcome": None})
    ready = relation_status()
    stopped = relation_status(state="stopped", phase="relation", resumeMode="resume", usage=dict(RELATION_USAGE),
                              failure={"code": "producer_replay_missing"}, delivery={"state": "withheld", "reason": "job_not_ready"})
    reconciling = relation_status(state="reconciling", phase="relation", resumeMode="reconcile_only", failure={"code": "replay_response_unknown"},
                                  usage={**RELATION_USAGE, "startedWithoutReceipt": 1}, delivery={"state": "withheld", "reason": "job_not_ready"})
    interrupted = relation_status(state="running", phase="relation", resumeMode="resume", usage=dict(RELATION_USAGE),
                                  delivery={"state": "withheld", "reason": "job_not_ready"},
                                  dispatch={"lastOutcome": "service_restarted"})
    revoked = relation_status(delivery={"state": "withheld", "reason": "source_unauthorized"})
    unlisted = relation_status(delivery={"state": "withheld", "reason": "upstream_not_allowed"})
    cancelled = relation_status(state="cancelled", phase="cancelled", resumeMode="none", usage=dict(RELATION_USAGE),
                                delivery={"state": "withheld", "reason": "job_cancelled"}, dispatch={"lastOutcome": "cancelled"})
    recovering = relation_status(state="stopped", phase="relation", resumeMode="resume", usage=dict(RELATION_USAGE), failure={"code": "producer_replay_missing"},
                                 delivery={"state": "withheld", "reason": "job_not_ready"}, dispatch={"state": "pending", "dispatchCount": 1})
    receipt = {"stage": "relation", "state": "received", "verdict": None}
    available = RelationResultEnvelope.model_validate({"schemaVersion": RELATION_SCHEMA, "status": ready, "delivery": {"state": "available", "reason": None},
                                                       "job": relation_content(), "receipts": [receipt]}).wire()
    withheld = RelationResultEnvelope.model_validate({"schemaVersion": RELATION_SCHEMA, "status": revoked, "delivery": {"state": "withheld", "reason": "source_unauthorized"},
                                                      "job": None, "receipts": [receipt]}).wire()
    approved_review = relation_operation()
    rejected_review = relation_operation(decision="reject")
    unconfirmed_review = relation_operation(review_state="reserved", applied_at=None, applied_event_at=None)
    legacy = {"contract": "legacy-revalidation", "reval_state": "idle", "reval_count": 1, "reval_updated_at": STAMP}
    legacy_verified = relation_operation(**legacy, last_outcome="exited", settled="verified", settled_eligibility="eligible", settled_at=STAMP)
    legacy_unsettled = relation_operation(**legacy, last_outcome="transport_unknown")
    legacy_unconfirmed = relation_operation(contract="legacy-revalidation", review_state="reserved", applied_at=None, applied_event_at=None)
    return {
        "submit.202": {"queuedJob": {"summary": "Newly accepted: the pipeline froze the upstream as a queued job, one initial dispatch is pending", "value": queued}},
        "submit.200": {"readyReplay": {"summary": "Same key and body sent again: the actual current state", "value": ready}},
        "status.200": {
            "ready": {"summary": "Finished: fetch the result", "value": ready},
            "stoppedForMissingFixture": {"summary": "Stopped (for example the server-owned replay file has no record for this request). Fix the server input, then call recover", "value": stopped},
            "interrupted": {"summary": "The service restarted or lost the child while it ran: nothing is run again automatically; call recover", "value": interrupted},
            "reconciling": {"summary": "A replay call was reserved but never answered: it is never resent; stop and escalate", "value": reconciling},
            "sourceRevoked": {"summary": "The operator source registry no longer permits delivery: ready, but content-free", "value": revoked},
            "upstreamNotListed": {"summary": "The upstream allowlist no longer lists this job's upstream for its owner", "value": unlisted},
        },
        "result.200": {"available": {"summary": "Every delivery gate held at this moment", "value": available},
                       "withheld": {"summary": "Current source rights no longer cover delivery: no content, accounting receipts only", "value": withheld}},
        "cancel.200": {"cancelled": {"summary": "Cancelled (also when it already was); an in-flight child is not killed", "value": cancelled}},
        "recover.202": {"enqueued": {"summary": "A dispatch was enqueued", "value": recovering}},
        "recover.200": {"coalesced": {"summary": "A dispatch is already pending or in flight", "value": recovering}},
        "review.200": {"allowApproved": {"summary": "An allow is the operator's final approval, recorded in the runtime ledger: terminal, nothing is revalidated, queued or called, nothing is published", "value": approved_review},
                       "rejectRecorded": {"summary": "A reject is recorded and the relation is excluded", "value": rejected_review},
                       "replay": {"summary": "The same key and body again: the existing operation, whatever the relation did since", "value": approved_review},
                       "legacyReplay": {"summary": "A key recorded under the earlier contract (allow meant revalidate): history only, its stored settlement is shown and never reinterpreted as an approval", "value": legacy_verified}},
        "operation.200": {
            "approved": {"summary": "A recorded final approval: revalidation not_requested, next none", "value": approved_review},
            "rejected": {"summary": "A recorded exclusion", "value": rejected_review},
            "unconfirmed": {"summary": "Reserved but not proven in the chain (a crash or a lost reply): retry the same POST", "value": unconfirmed_review},
            "legacySettled": {"summary": "Recorded under the earlier contract and settled by its own stored history", "value": legacy_verified},
            "legacyUnsettled": {"summary": "Recorded under the earlier contract and never settled: contract_changed, nothing is dispatched or resent", "value": legacy_unsettled}},
        "errors": {
            "401": {"summary": "Missing, malformed or unknown bearer token", "value": relation_error("authentication_required")},
            "403.scope": {"summary": "Principal lacks the route's scope", "value": relation_error("scope_denied")},
            "403.upstream": {"summary": "The upstream job and digest are not listed for this principal; the same answer whether or not they exist", "value": relation_error("upstream_not_allowed")},
            "404": {"summary": "Unknown job, another principal's job, or never accepted", "value": relation_error("job_not_found")},
            "409.executionUnavailable": {"summary": "The relation configuration group is not enabled", "value": relation_error("execution_unavailable")},
            "409.idempotencyConflict": {"summary": "Same key, different body; the pipeline was not called", "value": relation_error("idempotency_conflict")},
            "409.jobIdUnavailable": {"summary": "The jobId is owned by another principal or already exists in the pipeline ledger", "value": relation_error("job_id_unavailable")},
            "409.upstreamUnavailable": {"summary": "The pipeline refused the upstream (not ready, changed, rights); nothing was registered", "value": relation_error("upstream_unavailable", runtime_code="upstream_not_ready")},
            "409.reconcileRequired": {"summary": "Recover of a reconciling job", "value": relation_error("reconcile_required", job_status=reconciling)},
            "409.jobNotRecoverable": {"summary": "Recover of a ready or cancelled job", "value": relation_error("job_not_recoverable", job_status=ready)},
            "409.jobAlreadyTerminal": {"summary": "Cancel of a ready job (it would be permanently withheld)", "value": relation_error("job_already_terminal", job_status=ready)},
            "409.sourceVersion": {"summary": "The job's sourceVersion is not the expected one; nothing was recorded", "value": relation_error("source_version_conflict")},
            "409.sourceRevision": {"summary": "The relation moved past the expected sourceRevision (another decision or a verdict); nothing was recorded", "value": relation_error("source_revision_conflict")},
            "409.notOnHold": {"summary": "Only a relation on HOLD can be reviewed", "value": relation_error("review_target_not_hold", runtime_code="review_target_not_hold")},
            "409.operationIdUnavailable": {"summary": "The operation key belongs to another principal", "value": relation_error("operation_id_unavailable")},
            "409.reviewContractChanged": {"summary": "The key was reserved under the earlier revalidation contract and never confirmed: history only, use a new key", "value": relation_error("review_contract_changed", operation=legacy_unconfirmed)},
            "409.reviewCallInFlight": {"summary": "A model call for this job has no answer yet: nothing is approved until it is reconciled", "value": relation_error("review_call_in_flight", runtime_code="review_call_in_flight")},
            "409.candidateIneligible": {"summary": "The deterministic checks or the current source rights no longer hold for this candidate: a human decision cannot override them", "value": relation_error("review_candidate_ineligible", runtime_code="review_candidate_ineligible")},
            "403.liveNotApproved": {"summary": "A live job needs an allowlist entry pinning the runtime identity", "value": relation_error("live_not_approved")},
            "409.liveUnavailable": {"summary": "The service has no live group", "value": relation_error("live_unavailable")},
            "404.operation": {"summary": "Unknown operation, another principal's, or another job's", "value": relation_error("operation_not_found")},
            "404.candidate": {"summary": "The relation candidate is not in this job", "value": relation_error("relation_candidate_not_found", runtime_code="relation_candidate_not_found")},
            "503.unconfirmed": {"summary": "The review could not be proven in the chain either way yet: retry the same key and body", "value": relation_error("review_unconfirmed", retryable=True)},
            "422": {"summary": "Header, path or JSON envelope validation", "value": relation_error("invalid_request", field="body")},
            "503": {"summary": "The pipeline is busy: retry with the same key and body", "value": relation_error("runtime_busy", retryable=True)},
        },
    }


def _document_relation(spec: dict[str, Any], sample: dict[str, dict[str, Any]]) -> None:
    paths = spec["paths"]
    schemas = spec["components"]["schemas"]
    request = RelationSubmit.model_json_schema(by_alias=True, ref_template="#/components/schemas/{model}")
    for name, definition in request.pop("$defs", {}).items():
        schemas.setdefault(name, definition)
    schemas["RelationSubmit"] = request
    for code, key in (("401", "401"), ("404", "404"), ("422", "422"), ("503", "503")):
        for path in (p for p in paths if p.startswith("/internal/v1/relation-jobs")):
            for operation in paths[path].values():
                if code in operation["responses"]:
                    _attach(operation, code, {"example": sample["errors"][key]})
    base = paths["/internal/v1/relation-jobs"]["post"]
    base["requestBody"] = {"required": True, "content": {"application/json": {
        "schema": {"$ref": "#/components/schemas/RelationSubmit"},
        "examples": {"relationJob": {"summary": "S3 Submit over an allowlisted S2 upstream; Idempotency-Key must equal jobId", "value": RELATION_SUBMIT}}}}}
    base["responses"]["202"]["description"] = "Newly accepted: the pipeline registered the job and the owner binding and the one initial dispatch intent are durable."
    _attach(base, "202", sample["submit.202"])
    _attach(base, "200", sample["submit.200"])
    for code in ("200", "202"):
        base["responses"][code]["headers"] = {
            "Location": {"description": "Status URL of the job.", "schema": {"type": "string"}},
            "Retry-After": {"description": "Seconds to wait before polling; present while next is wait.", "schema": {"type": "integer"}}}
    _attach(base, "403", {"scopeDenied": sample["errors"]["403.scope"], "upstreamNotAllowed": sample["errors"]["403.upstream"],
                          "liveNotApproved": sample["errors"]["403.liveNotApproved"]})
    _attach(base, "409", {"executionUnavailable": sample["errors"]["409.executionUnavailable"], "idempotencyConflict": sample["errors"]["409.idempotencyConflict"],
                          "jobIdUnavailable": sample["errors"]["409.jobIdUnavailable"], "upstreamUnavailable": sample["errors"]["409.upstreamUnavailable"],
                          "liveUnavailable": sample["errors"]["409.liveUnavailable"]})
    for path, method in (("/internal/v1/relation-jobs/{jobId}", "get"), ("/internal/v1/relation-jobs/{jobId}/result", "get"),
                         ("/internal/v1/relation-jobs/{jobId}/cancel", "post"), ("/internal/v1/relation-jobs/{jobId}/recover", "post")):
        _attach(paths[path][method], "403", {"example": sample["errors"]["403.scope"]})
        _attach(paths[path][method], "409", {"example": sample["errors"]["409.executionUnavailable"]})
    status_op = paths["/internal/v1/relation-jobs/{jobId}"]["get"]
    status_op["responses"]["200"]["description"] = "Current job status read from the pipeline during this request. It never carries candidates, citations, quotes or digests of content."
    _attach(status_op, "200", sample["status.200"])
    result_op = paths["/internal/v1/relation-jobs/{jobId}/result"]["get"]
    result_op["responses"]["200"]["description"] = "Candidates of a ready job; content is withheld unless every delivery gate holds at this moment."
    _attach(result_op, "200", sample["result.200"])
    cancel = paths["/internal/v1/relation-jobs/{jobId}/cancel"]["post"]
    cancel["responses"]["200"]["description"] = "The job is cancelled (also when it already was). A ready job is refused with 409."
    _attach(cancel, "200", sample["cancel.200"])
    _attach(cancel, "409", {"jobAlreadyTerminal": sample["errors"]["409.jobAlreadyTerminal"], "executionUnavailable": sample["errors"]["409.executionUnavailable"]})
    recover = paths["/internal/v1/relation-jobs/{jobId}/recover"]["post"]
    recover["responses"]["202"]["description"] = "A dispatch was enqueued."
    _attach(recover, "202", sample["recover.202"])
    _attach(recover, "200", sample["recover.200"])
    _attach(recover, "409", {"reconcileRequired": sample["errors"]["409.reconcileRequired"], "jobNotRecoverable": sample["errors"]["409.jobNotRecoverable"],
                             "executionUnavailable": sample["errors"]["409.executionUnavailable"]})

    review_request = RelationReview.model_json_schema(by_alias=True, ref_template="#/components/schemas/{model}")
    for name, definition in review_request.pop("$defs", {}).items():
        schemas.setdefault(name, definition)
    schemas["RelationReview"] = review_request
    review = paths["/internal/v1/relation-jobs/{jobId}/reviews"]["post"]
    review["requestBody"] = {"required": True, "content": {"application/json": {
        "schema": {"$ref": "#/components/schemas/RelationReview"},
        "examples": {"allow": {"summary": "Allow: the operator's FINAL approval of a HOLD relation (no revalidation). Quote the values read from the result; the reviewer is the authenticated principal", "value": RELATION_REVIEW},
                     "reject": {"summary": "Reject: exclude the relation", "value": {**RELATION_REVIEW, "decision": "reject"}}}}}}
    review["responses"]["200"]["description"] = "The decision is recorded in the runtime ledger and is terminal: an allow is the final approval (nothing is revalidated or called), a reject an exclusion. Also the answer to the same key and body sent again (the existing operation, whatever the relation did since)."
    _attach(review, "200", sample["review.200"])
    review["responses"]["200"]["headers"] = {"Location": {"description": "Status URL of the operation.", "schema": {"type": "string"}}}
    _attach(review, "403", {"scopeDenied": sample["errors"]["403.scope"], "upstreamNotAllowed": sample["errors"]["403.upstream"]})
    _attach(review, "404", {"jobNotFound": sample["errors"]["404"], "relationCandidateNotFound": sample["errors"]["404.candidate"]})
    _attach(review, "409", {"sourceVersionConflict": sample["errors"]["409.sourceVersion"], "sourceRevisionConflict": sample["errors"]["409.sourceRevision"],
                            "reviewTargetNotHold": sample["errors"]["409.notOnHold"], "reviewCallInFlight": sample["errors"]["409.reviewCallInFlight"],
                            "reviewCandidateIneligible": sample["errors"]["409.candidateIneligible"],
                            "reviewContractChanged": sample["errors"]["409.reviewContractChanged"], "idempotencyConflict": sample["errors"]["409.idempotencyConflict"],
                            "operationIdUnavailable": sample["errors"]["409.operationIdUnavailable"],
                            "upstreamUnavailable": sample["errors"]["409.upstreamUnavailable"], "executionUnavailable": sample["errors"]["409.executionUnavailable"]})
    _attach(review, "503", {"runtimeBusy": sample["errors"]["503"], "reviewUnconfirmed": sample["errors"]["503.unconfirmed"]})
    lookup = paths["/internal/v1/relation-jobs/{jobId}/reviews/{operationId}"]["get"]
    lookup["responses"]["200"]["description"] = "The operation, identified exactly by its key: candidate, decision, reviewer and the two expectations sent, plus acceptance, the (legacy-only) revalidation state and publication. Read from the service ledger; no content."
    _attach(lookup, "200", sample["operation.200"])
    _attach(lookup, "403", {"example": sample["errors"]["403.scope"]})
    _attach(lookup, "404", {"jobNotFound": sample["errors"]["404"], "operationNotFound": sample["errors"]["404.operation"]})
    _attach(lookup, "409", {"example": sample["errors"]["409.executionUnavailable"]})


def plan_examples() -> dict[str, Any]:
    """Synthetic, model-validated references and receipts; never a source grant."""
    def digest(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                         allow_nan=False).encode("utf-8")).hexdigest()

    reference = PlanReference(schema_version="zoop-ai-plan-admission-1", plan_id="s2plan-" + DIGEST, plan_digest=DIGEST).wire()
    provenance = {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"}
    upstream = {"jobId": "synthetic-plan-unit-1", "inputDigest": DIGEST}
    relation_id = "s3p-" + digest({"format": "zoop-plan-admission-relation-job-1", "planId": reference["planId"],
                                  "planDigest": DIGEST, "upstream": upstream})
    manifest = {"schemaVersion": "zoop-ai-plan-manifest-1", "planId": reference["planId"], "planDigest": DIGEST,
                "receiptSha256": DIGEST, "principal": "synthetic-app",
                "round": {"sourceId": "synthetic-source", "roundId": "synthetic-round-1", "ingestionInputDigest": DIGEST},
                "provenance": provenance, "units": [{
                    "unitKey": upstream["jobId"],
                    "extractionSubmit": {"schemaVersion": "zoop-extraction-s2-2", "jobId": upstream["jobId"], "approvedRequestDigest": DIGEST},
                    "extractionInputDigest": DIGEST,
                    "relationSubmit": {"schemaVersion": "zoop-relation-s3", "jobId": relation_id,
                                       "provenance": provenance, "upstream": upstream}}]}
    manifest["manifestDigest"] = digest(manifest)
    admitted = PlanAdmissionEnvelope.model_validate({
        "schemaVersion": "zoop-ai-plan-admission-1",
        "admissionId": "pa-" + digest({"format": "zoop-plan-admission-identity-1", "principal": "synthetic-app",
                                      "planId": reference["planId"], "planDigest": DIGEST}),
        "acceptedAt": STAMP, "policyRevision": 1, "policyDigest": DIGEST,
        "manifest": manifest, "authority": {"state": "active", "reason": None}}).wire()
    disabled = PlanPolicyDisabled(schema_version="zoop-ai-plan-policy-1", enabled=False).wire()
    unconfigured = PlanPolicyState(revision=0, policy_digest=None, policy=None, status="unconfigured",
                                   usage={"plans": 0, "units": 0}).wire()
    update = PlanPolicyUpdate(operation_id="synthetic-policy-disable-1", revision=1,
                              policy_digest=digest(disabled), changed=True).wire()
    return {"reference": reference, "admitted": admitted, "disabled": disabled, "unconfigured": unconfigured, "update": update}


def _document_plans(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]
    for model in (PlanReference, PlanPolicyDisabled, PlanPolicyEnabled):
        schema = model.model_json_schema(by_alias=True, ref_template="#/components/schemas/{model}")
        for name, definition in schema.pop("$defs", {}).items():
            schemas.setdefault(name, definition)
        schemas[model.__name__] = schema
    sample = plan_examples()
    paths = spec["paths"]
    admit = paths["/internal/v1/plan-admissions"]["post"]
    admit["requestBody"] = {"required": True, "content": {"application/json": {
        "schema": {"$ref": "#/components/schemas/PlanReference"},
        "examples": {"exactReference": {"summary": "Synthetic exact reference; Idempotency-Key equals planId", "value": sample["reference"]}}}}}
    admit["description"] = (
        "Scope plan.admit. Resolve only the configured plan root and completely verify the installed plan. "
        "Admission atomically persists paired S2/S3 references and cumulative quota, but never submits or dispatches either job. "
        "201 is a first commit; 200 is the original immutable receipt, including inactive history, without regeneration or quota debit. "
        "An admission is not present source-rights proof, readiness, spending permission, publication or activation. "
        "Manual and online authorities are exclusive; absent online configuration returns execution_unavailable after authentication. "
        "Requests are bounded at 2,000,000 bytes. Complete replies are bounded at 16,000,000 bytes; units are never truncated. "
        "Revisions, counters and limits are signed 64-bit nonnegative integers (positive for a revision or policy limit).")
    lookup = paths["/internal/v1/plan-admissions/{planId}"]["get"]
    lookup["description"] = "Scope plan.read. Exactly one planDigest query is required; no listing/search. Unknown and other-principal records answer alike. The manifest is persisted immutable history; only current admission-policy authority changes. No dispatch."
    for operation in (admit, lookup):
        for code in ("200", "201"):
            if code in operation["responses"]:
                _attach(operation, code, {"admitted": {"summary": "Immutable synthetic admission and current policy authority", "value": sample["admitted"]}})
                operation["responses"][code]["headers"] = {
                    "Location": {"description": "Exact query URL including planDigest.", "schema": {"type": "string"}}}
    policy_get = paths["/internal/v1/plan-admission-policy"]["get"]
    policy_put = paths["/internal/v1/plan-admission-policy"]["put"]
    policy_get["description"] = "Scope plan.policy, never assigned to the application admission/execution principal. Current policy status and cumulative usage; initial revision zero has no policy. ETag is quoted plan-policy-<revision>-<digest or none>."
    policy_get["responses"]["200"]["headers"] = {
        "ETag": {"description": 'Exact quoted current policy identity; initially \"plan-policy-0-none\".', "schema": {"type": "string"}}}
    _attach(policy_get, "200", {"unconfigured": {"summary": "Default: no policy", "value": sample["unconfigured"]}})
    policy_put["requestBody"] = {"required": True, "content": {"application/json": {
        "schema": {"oneOf": [{"$ref": "#/components/schemas/PlanPolicyDisabled"}, {"$ref": "#/components/schemas/PlanPolicyEnabled"}]},
        "examples": {"disabled": {"summary": "Synthetic disable operation, not an operating grant", "value": sample["disabled"]}}}}}
    policy_put["description"] = (
        "Scope plan.policy. Raw closed policy document; exact If-Match and stable operation Idempotency-Key are required. "
        "Exact operator/key/body/If-Match retries return their historical receipt, even after another update. "
        "Changed body or If-Match with the same key conflicts (409); a new stale CAS conflicts (412). "
        "Identical current bytes do not renew revision/expiry or reset usage. A changed policy terminally retires all prior admissions. "
        "A replay receipt is not current state: GET current policy rather than treating it as the latest revision. "
        "Policy changes never refund usage and never authorize source/model spending. Application clients have no policy-write method.")
    _attach(policy_put, "200", {"disabled": {"summary": "Historical operation receipt, not current policy", "value": sample["update"]}})
    # A historical PUT receipt must never acquire a later current-state ETag.
    for path in ("/internal/v1/plan-admissions", "/internal/v1/plan-admissions/{planId}", "/internal/v1/plan-admission-policy"):
        for operation in paths[path].values():
            for parameter in operation.get("parameters", []):
                if parameter["name"] == "Idempotency-Key":
                    parameter.update(required=True, schema={"type": "string", "pattern": PLAN_ID_PATTERN if operation is admit else r"^[A-Za-z0-9_.-]{1,120}$"},
                                     description="Must equal body.planId." if operation is admit else "Stable operator-scoped operation id; retry identical body and If-Match.")
                elif parameter["name"] == "If-Match":
                    parameter.update(required=True, schema={"type": "string"}, description='Exact quoted policy ETag from GET; initially \"plan-policy-0-none\".')
                elif parameter["name"] == "planDigest":
                    parameter.update(required=True, schema={"type": "string", "pattern": r"^[0-9a-f]{64}$"})
            for code, response in operation["responses"].items():
                if int(code) >= 400:
                    error_code = {401: "authentication_required", 403: "scope_denied", 404: "admission_not_found", 409: "admission_disabled",
                                  412: "policy_conflict", 413: "request_too_large", 415: "unsupported_media_type",
                                  422: "invalid_request", 500: "internal_error", 503: "authority_unavailable"}[int(code)]
                    value = PlanErrorEnvelope(error=ErrorBody(code=error_code, retryable=int(code) == 503, request_id="req-plan-0001")).wire()
                    response["content"]["application/json"]["examples"] = {"error": {"summary": error_code, "value": value}}


def _document_rounds(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]
    for model in (RunRequest, HandoffRequest, RunStatus, HandoffStatus):
        definition = model.model_json_schema(by_alias=True, ref_template="#/components/schemas/{model}")
        for name, nested in definition.pop("$defs", {}).items():
            schemas.setdefault(name, nested)
        schemas[model.__name__] = definition
    for family, request, status_model in (("runs", RunRequest, RunStatus), ("handoffs", HandoffRequest, HandoffStatus)):
        path = "/internal/v1/round-" + family
        post, get = spec["paths"][path]["post"], spec["paths"][path + "/{roundId}"]["get"]
        post["requestBody"] = {"required": True, "content": {"application/json": {
            "schema": {"$ref": "#/components/schemas/" + request.__name__}}}}
        post["description"] = (
            "Requires round.run. New admissions return 202 after original UTF-8 bytes are durably saved. "
            "Idempotency-Key equals app roundId. Same principal/family/id and identical original bytes return 200, "
            "including running and terminal states, without requeue. Changed bytes return 409 request_conflict. "
            "A distinct identity while any profile command is reserved/running returns retryable 409 round_busy without admission or files. "
            "Dormant analysis_incomplete records release the execution slot; only the background dispatcher may reacquire it atomically. "
            + ("Body limit 1,024 bytes. Valid nonfuture outside-window/off-cadence slots return no_new_material with "
               "outside_operating_window/not_due, without native mutation. Invalid or future dates return 422 invalid_request. "
               "Selection fixes asOf and an operator-required maxAgeSeconds; baseline maximum eight units per 30-minute round. 18:05 is freeze-only."
               if family == "runs" else
               "Full bindings object required; body limit 4,001,024 bytes and canonical bindings limit 4,000,000 bytes. "
               "Before admission the owned plan and own-round native jobs must be ready or cancelled; otherwise retryable 409 analysis_incomplete "
               "creates no row, private bindings or native write. A later known nonmutating readiness race may become accepted analysis_incomplete. "
               "window_empty, including all-withheld selection, returns no_public_material with the exact selection report and no handoff/grant. "
               "Ready pins and the principal read grant commit atomically."))
        get["description"] = (
            "Requires round.read. Unknown/other-principal admission is 404 round_not_found. GET never dispatches, requeues or creates directories. "
            "Ready plans and handoffs recheck current read authority; a later denial does not trigger replacement freeze. "
            "A started uncertain command remains failed/round_outcome_unknown across restart and exact replay. "
            "Java recovery uses the saved endpoint/principal/credential binding and GET first; only decoded scoped 404 round_not_found permits exact-byte POST. "
            "Ready means an AI artifact, not app import, composition or activation.")
        for operation in (post, get):
            for parameter in operation.get("parameters", []):
                if parameter["name"] == "Idempotency-Key":
                    parameter.update(required=True, schema={"type": "string", "pattern": ROUND_ID_PATTERN},
                                     description="Must equal body.roundId; retransmit the saved original bytes exactly.")
            for code, response in operation["responses"].items():
                if int(code) < 400:
                    response["description"] = "Exact admitted operation with freshly observed state."
                    response["content"]["application/json"]["schema"] = {"$ref": "#/components/schemas/" + status_model.__name__}
                else:
                    error_code = {401: "authentication_required", 403: "scope_denied", 404: "round_not_found",
                                  409: "request_conflict", 413: "request_too_large", 415: "unsupported_media_type",
                                  422: "invalid_request", 500: "internal_error", 503: "execution_unavailable"}[int(code)]
                    response["content"]["application/json"]["examples"] = {"error": {"value": error(error_code)}}
            operation["responses"]["503"]["description"] = "execution_unavailable for a disabled round profile; service_busy or runtime_unavailable."
        waiting = status_model.model_validate({"roundId": "round-20261031T0905", "state": "running", "observedAt": STAMP}).wire()
        _attach(post, "202", {"admitted": {"value": waiting}})
        _attach(get, "200", {"running": {"value": waiting}})


def build(app: Any, submit_example: dict[str, Any]) -> dict[str, Any]:
    """The full document. `submit_example` is a worker-fixture Submit body (repository-authored synthetic text)."""
    spec = app.openapi()
    sample = examples()
    spec["info"] = {"title": "Zoop internal AI analysis transport", "version": "1.0.0",
                    "description": (DESCRIPTION + "\n" + extraction_doc.DESCRIPTION + "\n" + graph_doc.DESCRIPTION + "\n" + handoff_doc.DESCRIPTION + "\n"
                                    + chat_doc.DESCRIPTION).strip()}
    spec["servers"] = [{"url": "http://127.0.0.1:8797", "description": "Default loopback development address; deployment endpoint is operator-owned HTTPS ingress."}]
    spec["tags"] = [{"name": "analysis-jobs", "description": "S1 analysis jobs over the installed zoop-ai runtime."},
                    {"name": "relation-jobs", "description": "S3 relation/impact candidate jobs over an operator-prepared S2 upstream, through the installed zoop-ai-relation pipeline (replay, or live for an operator-pinned upstream)."},
                    {"name": "extraction-jobs", "description": "S2 event/topic candidate jobs over an operator-approved request, through the installed zoop-ai-extract pipeline (replay, or live for an operator-pinned approval)."},
                    {"name": "graph-versions", "description": "Read-only, nonpublic S3 graph version status and company focus over operator-listed versions, through the installed zoop-ai-graph pipeline (no write, no model)."},
                    {"name": "graph-handoffs", "description": "Read-only, nonpublic AI handoff status and whole-bundle delivery over operator-pinned handoffs, through the installed zoop-ai-handoff export command (no write, no model, no network)."},
                    {"name": "chat-stages", "description": "One chatbot model stage (router, answer or verification) per request, synchronously, through the installed zoop-ai-chat runtime (replay, or live behind the chat gate)."},
                    {"name": "plan-admissions", "description": "Bounded exact plan admission and immutable reference reads; no dispatch."},
                    {"name": "observations", "description": "Synchronous native ingestion export with current read/store/quote-display rights; no ingestion writes or model permission."},
                    {"name": "plan-admission-policy", "description": "Separate operator-only policy CAS control; never application authority."},
                    {"name": "round-runs", "description": "Durable app-round to native-ingestion/plan orchestration."},
                    {"name": "round-handoffs", "description": "Bounded native freeze and atomic principal read grants."}]
    components = spec["components"]
    components["securitySchemes"] = {"bearerAuth": {"type": "http", "scheme": "bearer",
                                                    "description": "Operator-issued token; the service holds only its SHA-256 digest. Roles are the route scopes."}}
    components["schemas"]["ResultEnvelope"]["properties"]["job"] = {
        "description": "The runtime `get` payload for the importer, present only when delivery.state is available.",
        "oneOf": [{"$ref": f"{CONTRACT}#/$defs/JobResult"}, {"type": "null"}]}
    scopes = {"submitAnalysisJob": "analysis.submit", "getAnalysisJobStatus": "analysis.read", "getAnalysisJobResult": "analysis.read",
              "cancelAnalysisJob": "analysis.cancel", "recoverAnalysisJob": "analysis.recover",
              "submitRelationJob": "relation.submit", "getRelationJobStatus": "relation.read", "getRelationJobResult": "relation.read",
              "cancelRelationJob": "relation.cancel", "recoverRelationJob": "relation.recover", "submitRelationReview": "relation.review",
              "getRelationReviewOperation": "relation.read",
              "submitExtractionJob": "extraction.submit", "getExtractionJobStatus": "extraction.read", "getExtractionJobResult": "extraction.read",
              "cancelExtractionJob": "extraction.cancel", "recoverExtractionJob": "extraction.recover",
              "getGraphVersionStatus": "graph.read", "getGraphVersionFocus": "graph.read",
              "getGraphHandoffStatus": "handoff.read", "getGraphHandoffBundle": "handoff.read", "queryGraphHandoffExposure": "handoff.exposure",
              "invokeChatStage": "chat.invoke", "probeChatMcp": "chat.invoke", "admitPlan": "plan.admit", "getPlanAdmission": "plan.read",
              "getPlanAdmissionPolicy": "plan.policy", "setPlanAdmissionPolicy": "plan.policy", "exportObservation": "observation.read",
              "requestRoundRun": "round.run", "getRoundRun": "round.read", "requestRoundHandoff": "round.run", "getRoundHandoff": "round.read"}
    for path in spec["paths"].values():
        for operation in path.values():
            operation["security"] = [{"bearerAuth": [scopes[operation["operationId"]]]}]
            for parameter in operation.get("parameters", []):
                if parameter["name"] == "Idempotency-Key":
                    chat = operation["operationId"] == "invokeChatStage"
                    parameter.update(required=True,
                                     schema={"type": "string", "pattern": "^[A-Za-z0-9_.:-]{8,96}$" if chat else "^[A-Za-z0-9_.-]{1,120}$"},
                                     description=("The stable id of this review operation: retry any ambiguous request with the same key and body."
                                                  if operation["operationId"] == "submitRelationReview"
                                                  else "Must equal body.invocationId." if chat else "Must equal body.jobId."))
                elif parameter["name"] == "X-Request-ID":
                    parameter.update(description="Optional correlation id, echoed on every response and never used as an idempotency key.",
                                     schema={"type": "string", "pattern": "^[A-Za-z0-9._-]{1,128}$"})
            for code in ("401", "403", "404", "422", "503"):
                if code in operation["responses"] and not any(name in operation["operationId"] for name in ("Relation", "Extraction", "Graph", "Plan")):
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
    _document_relation(spec, relation_examples())
    extraction_doc.document(spec)
    graph_doc.document(spec)
    handoff_doc.document(spec)
    request = ExposureQuery.model_json_schema(by_alias=True, ref_template="#/components/schemas/{model}")
    for name, definition in request.pop("$defs", {}).items():
        components["schemas"].setdefault(name, definition)
    components["schemas"]["ExposureQuery"] = request
    exposure = spec["paths"]["/internal/v1/graph-handoffs/exposure"]["post"]
    exposure["requestBody"] = {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ExposureQuery"}}}}
    exposure["description"] = (
        "Requires handoff.exposure, independent of handoff.read. One explicit selection of 1–20 unique handoff IDs; request at most 65,536 UTF-8 bytes. "
        "No query parameters, idempotency requirement, job, cache, retry or partial result. Invokes zoop-ai-handoff-exposure directly, never ordinary export. "
        "Source rights are not evaluated: frozen identity reads remain possible after source revocation, but every allowlist entry must remain unchanged. "
        "A complete allowlist snapshot is checked before the child, after any gate wait, after the child before errors are interpreted, and before response. "
        "These are separate observations, not atomic revocation. Closed canonical report limit: 6 MiB including newline; model/provider calls are zero. "
        "The CLI validates frozen artifacts; the service compares reported manifest/bundle pins to the allowlist, not hashes of bundle bytes it did not receive. "
        "The app must reconcile handoffId, manifestDigest, bundleDigest and contentDigest with its receipt. This endpoint changes no exclusion, revision or "
        "activation state; errors and empty/smaller reports never clear exclusions.")
    exposure["responses"]["200"]["description"] = "Complete unchanged identity-only report in the handoff envelope; not current delivery authority or import readiness."
    chat_doc.document(spec)
    _document_plans(spec)
    _document_rounds(spec)
    components["schemas"]["ObservationExportRequest"] = ObservationExportRequest.model_json_schema(
        by_alias=True, ref_template="#/components/schemas/{model}")
    export = spec["paths"]["/internal/v1/observations/export"]["post"]
    export["requestBody"] = {"required": True, "content": {"application/json": {
        "schema": {"$ref": "#/components/schemas/ObservationExportRequest"}}}}
    export["description"] = (
        "Requires observation.read, explicitly granted to operator-selected internal importer principals. This scope permits exact reads across the server's "
        "configured registry or inventory; it is not per-observation ownership. One complete seven-field native selector plus required schemaVersion "
        "zoop-ingestion-s2-1; unknown fields are refused. "
        "Every request runs installed zoop-ai-ingest export --require-store with a credential-filtered environment and server-owned paths. "
        "The native CLI checks current read, store and quote-display grants and frozen source configuration. "
        "The service additionally validates selector identity, text sourceHash, document version and locator hashes before returning the unchanged native JSON. "
        "Single-context mode reads its configured registry; multicontext mode resolves only an exact selector in the pinned handoff inventory, "
        "checked before and after export. Unknown routes are 404; changed or invalid inventory fails closed. "
        "One request returns one observation synchronously with 200; batch and asynchronous (202) delivery are open design items of issue #407. "
        "Authorized document.text is intentionally present only in a 200 response. No status route, cache, job, ingestion write, retry or recovery. "
        "No query parameters, client paths/CLI arguments, observationId or requireStore option. Idempotency-Key is not required and conveys no authority; "
        "a repeated request rechecks current rights rather than replaying a cached result. Input limit 2,000,000 bytes; stdout/response limit 16 MiB; "
        "45-second child deadline; at most two concurrent exports. Ingestion writer contention is 503 runtime_busy with runtimeCode ingestion_busy. "
        "Disabled configuration is 503 execution_unavailable after authentication. Error codes contain no text, path, key or raw diagnostics. "
        "All responses use Cache-Control: no-store. This read does not grant model-send, publication, activation or perpetual rights. "
        "Rights checks and HTTP delivery are separate observations, not atomic revocation or recall of already delivered text.")
    export["responses"]["200"]["description"] = "Exact native CLI export JSON, including authorized document.text and optional native provenance; no wrapper or omitted fields."
    for response in export["responses"].values():
        response.setdefault("headers", {})["Cache-Control"] = {"schema": {"type": "string", "const": "no-store"}}
    export["responses"]["503"]["headers"]["Retry-After"]["description"] = "Seconds before another explicit read; the service never retries automatically."
    return spec
