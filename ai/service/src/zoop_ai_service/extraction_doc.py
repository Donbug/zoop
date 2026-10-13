"""Authored OpenAPI semantics and examples of the S2 extraction-job family. Every example is built through the real wire models, so an example that
stops validating fails at generation; the route and model schemas themselves come from the application (`app.openapi()`)."""
from __future__ import annotations

from typing import Any

from .extraction_wire import (SCHEMA, ExtractionErrorEnvelope, ExtractionJobContent, ExtractionJobStatus, ExtractionResultEnvelope, ExtractionSubmit,
                              next_action)
from .wire import ErrorBody

STAMP = "2026-10-12T03:00:00Z"
DIGEST = "0" * 64
JOB = "extraction-synthetic-SYNTH-1"
SUBMIT = {"schemaVersion": "zoop-extraction-s2-2", "jobId": JOB, "approvedRequestDigest": "4" * 64}
PROVENANCE = {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"}
USAGE = {"replayCalls": 0, "startedWithoutReceipt": 0, "providerCalls": 0, "paidModelCalls": 0}
PENDING = [{"stage": "extract", "state": "pending"}, {"stage": "compare", "state": "pending"}, {"stage": "topic", "state": "pending"}]
COMPLETE = [{"stage": "extract", "state": "complete"}, {"stage": "compare", "state": "complete"}, {"stage": "topic", "state": "complete"}]

DESCRIPTION = """\
**S2 extraction jobs (`/internal/v1/extraction-jobs`, schema `zoop-ai-internal-extraction-1`, scopes `extraction.*`).** A separate family over the
installed `zoop-ai-extract` pipeline, replay only: it shares no wire contract, ledger or state machine with S1 or S3, but its children run behind the same
single gate as S3's, so an S2 write and an S3 read of its ledger can never overlap. It is off unless its own all-or-nothing server configuration group is
set (otherwise every route answers 409 `execution_unavailable` after authentication). A caller never sends the S2 `Submit`: the body is exactly
`{schemaVersion: "zoop-extraction-s2-2", jobId, approvedRequestDigest}`. The operator's server-owned approval file maps `principal + jobId +
approvedRequestDigest` to the exact S2 request (snapshot, catalogue, incoming observation, topic request) and the digests of the authored replay
fixtures it runs against; anything not listed is 403 `request_not_approved` before a ledger row or child exists, and the same answer whether or not the
job exists. An approval only narrows what the pipeline allows: the pipeline still re-reads the operator source registry on every content-bearing command.
The principal owns the job it submits (another principal's job answers like a missing one) and a job id that already exists in the pipeline ledger is
`job_id_unavailable`: an operator's job is never adopted.

The first reservation freezes the approved digest, the producer fixture digest, the optional topic fixture digest and the `inputDigest` the pipeline must
report (computed from the approved bytes, not echoed). The same request again keeps all of it; the same job with another approved digest is
`idempotency_conflict`; an approval entry or fixture file that has since changed is `approval_changed` / `fixture_changed` (or a withheld result) and the
job id is never rebound. The approval is re-read, and the fixtures re-hashed, at submit, at every dispatch, at recover and at delivery.

The initial dispatch runs once. A child that timed out, died or answered unreadably, and a dispatch left in flight by a restarted service, are never run
again automatically (`next=recover`); a pipeline `extraction_busy`/`ingestion_busy` refusal before any effect is retried a few times, but a job that the
pipeline recorded as `stopped` (for example `ingestion_busy` during execution) waits for an explicit recover. A call the pipeline reserved but never saw
answered ends `reconciling` and is never resent (`reconcile_required`). Cancel makes a queued, running, stopped or reconciling job `cancelled` for good and
is idempotent; a ready job is refused with 409 `job_already_terminal` and stays ready. Status never carries content. `GET /{jobId}/result` returns event
candidates (with their comparisons, citations and disposition) and topic candidates only for a ready job while the pipeline reports delivery current, the
approval is still the reserved one, the fixtures are still the pinned bytes and every receipt was answered by them; otherwise `delivery.state` is
`withheld` with a reason code. Nothing is ever approved by this family: every candidate carries `approved: false`. Delivery is checked at one instant: content
already sent cannot be recalled. Listing a delivered S2 job as an S3 upstream is a separate, explicit operator decision in the S3 allowlist; an S2 result never
widens S3 authority by itself.
"""


def status(**overrides: Any) -> dict[str, Any]:
    dispatch = {"state": "idle", "dispatchCount": 1, "lastOutcome": "exited", "lastRuntimeCode": None, "updatedAt": STAMP, **overrides.pop("dispatch", {})}
    base = {"schemaVersion": SCHEMA, "jobId": JOB, "inputDigest": "2" * 64, "approval": {"approvedRequestDigest": SUBMIT["approvedRequestDigest"]},
            "provenance": PROVENANCE, "state": "ready", "phase": "complete", "resumeMode": "none", "failure": None, "usage": {**USAGE, "replayCalls": 3},
            "stages": COMPLETE, "delivery": {"state": "available", "reason": None}, "dispatch": dispatch, "acceptedAt": STAMP, "observedAt": STAMP, **overrides}
    base["next"] = next_action(base["state"], dispatch["state"])
    return ExtractionJobStatus.model_validate(base).wire()


def error(code: str, *, retryable: bool = False, runtime_code: str | None = None, field: str | None = None,
          job_status: dict[str, Any] | None = None) -> dict[str, Any]:
    body = ErrorBody(code=code, retryable=retryable, request_id="req-0001", runtime_code=runtime_code, field=field)
    return ExtractionErrorEnvelope(error=body, status=None if job_status is None else ExtractionJobStatus.model_validate(job_status)).wire()


def content() -> dict[str, Any]:
    """One delivered event candidate and one topic candidate, authored synthetic text, validated through the allowlisted projection."""
    citation = {"evidenceId": "ev-" + "5" * 32, "documentId": "document-synthetic-1", "documentVersion": "3" * 64, "start": 0, "end": 21,
                "quote": "합성기업은 공급 계약을 발표했다.", "offsetUnit": "unicode_code_point"}
    document = {"documentId": "document-synthetic-1", "documentVersion": "3" * 64}
    candidate = {
        "eventCandidateId": "evc-" + "7" * 64, "mentionCandidateId": "mc-" + "8" * 64, "localMentionId": "m-main", "document": document, "state": "candidate",
        "reason": None, "approved": False,
        "mention": {"mentionId": "m-main", "title": "합성 공급 계약", "eventType": "contract", "action": "공급 계약 발표", "target": None, "eventTime": None,
                    "period": None, "assertionStatus": "announced", "participants": [{"companyId": "SYNTH-1", "name": "합성기업", "role": "subject"}],
                    "keywords": ["공급"], "background": False, "countries": []},
        "citations": [citation],
        "comparisons": [{"eventCandidateId": "evc-" + "7" * 64, "targetEventId": "event-1", "targetRevision": "r1",
                         "original": {"relation": "DIFFERENT", "reason": "다른 사건"}, "effective": {"relation": "DIFFERENT", "reason": "다른 사건", "rule": None},
                         "citations": []}],
        "disposition": {"status": "new-event-candidate", "reason": "no_same_in_frozen_snapshot", "targetEventId": None, "sameTargets": [], "follows": [],
                        "heldBy": [], "comparedEvents": 1}}
    topic = {"topicCandidateId": "tp-" + "9" * 64, "status": "candidate", "approved": False, "producerVersion": "zoop-topic-replay-producer-1",
             "label": "합성기업 계약", "criteria": "같은 기업의 사건", "rationale": "authored replay",
             "members": [{"kind": "event-candidate", "ref": "evc-" + "7" * 64, "revision": None}, {"kind": "snapshot-event", "ref": "event-1", "revision": "r1"}],
             "citations": [citation]}
    counts = {"documents": 2, "snapshotEvents": 1, "eventCandidates": {"total": 1, "candidate": 1, "rejected": 0}, "comparisons": 1,
              "effectiveRelations": {"SAME": 0, "DIFFERENT": 1, "FOLLOWS": 0, "CONFLICT": 0, "HOLD": 0},
              "dispositions": {"new-event-candidate": 1}, "topicCandidates": 1}
    return ExtractionJobContent.model_validate({"jobId": JOB, "inputDigest": "2" * 64, "counts": counts, "eventCandidates": [candidate],
                                                "topicCandidates": [topic]}).wire()


def examples() -> dict[str, Any]:
    queued = status(state="queued", phase="extract", resumeMode="resume", usage=dict(USAGE), stages=PENDING,
                    delivery={"state": "withheld", "reason": "job_not_ready"}, dispatch={"state": "pending", "dispatchCount": 0, "lastOutcome": None})
    stopped = status(state="stopped", phase="topic", resumeMode="resume", failure={"code": "topic_replay_missing"}, usage={**USAGE, "replayCalls": 2},
                     stages=[*COMPLETE[:2], PENDING[2]], delivery={"state": "withheld", "reason": "job_not_ready"})
    reconciling = status(state="reconciling", phase="extract", resumeMode="reconcile_only", failure={"code": "replay_response_unknown"},
                         usage={**USAGE, "startedWithoutReceipt": 1}, stages=PENDING, delivery={"state": "withheld", "reason": "job_not_ready"})
    interrupted = status(state="running", phase="compare", resumeMode="resume", usage={**USAGE, "replayCalls": 1}, stages=[COMPLETE[0], *PENDING[1:]],
                         delivery={"state": "withheld", "reason": "job_not_ready"}, dispatch={"lastOutcome": "service_restarted"})
    cancelled = status(state="cancelled", phase="cancelled", resumeMode="none", usage=dict(USAGE), stages=PENDING,
                       delivery={"state": "withheld", "reason": "job_cancelled"}, dispatch={"lastOutcome": "cancelled"})
    revoked = status(delivery={"state": "withheld", "reason": "approval_revoked"})
    receipt = {"stage": "extract", "state": "received", "verdict": None}
    available = ExtractionResultEnvelope.model_validate({"schemaVersion": SCHEMA, "status": status(), "delivery": {"state": "available", "reason": None},
                                                         "job": content(), "receipts": [receipt]}).wire()
    withheld = ExtractionResultEnvelope.model_validate({"schemaVersion": SCHEMA, "status": revoked, "delivery": {"state": "withheld", "reason": "approval_revoked"},
                                                        "job": None, "receipts": [receipt]}).wire()
    return {
        "submit.202": {"queued": {"summary": "Registered: the pipeline froze the approved request as a queued job and the one initial dispatch is pending", "value": queued}},
        "submit.200": {"replay": {"summary": "The same request again: the existing job, whatever it did since", "value": status()}},
        "status.200": {
            "ready": {"summary": "Ready; the approval and the fixtures are still the reserved ones", "value": status()},
            "interrupted": {"summary": "The service restarted while the child was in flight: not run again automatically", "value": interrupted},
            "stopped": {"summary": "The pipeline stopped the job (a replay record was missing): recover is explicit", "value": stopped},
            "reconciling": {"summary": "A call was reserved but never answered: never resent", "value": reconciling},
            "revoked": {"summary": "Ready, but the approval entry was removed: delivery withheld", "value": revoked}},
        "result.200": {"available": {"summary": "Candidates of a ready job (every delivery gate holds)", "value": available},
                       "withheld": {"summary": "The approval was removed: no candidates, only accounting receipts", "value": withheld}},
        "cancel.200": {"cancelled": {"summary": "Cancelled (also when it already was)", "value": cancelled}},
        "recover.202": {"queued": {"summary": "A dispatch was enqueued", "value": queued}},
        "recover.200": {"coalesced": {"summary": "A dispatch is already pending or in flight", "value": queued}},
        "errors": {
            "401": {"summary": "Missing, malformed or unknown bearer token", "value": error("authentication_required")},
            "403.scope": {"summary": "Principal lacks the route's scope", "value": error("scope_denied")},
            "403.approval": {"summary": "No approval is listed for this principal, job id and digest; the same answer whether or not the job exists", "value": error("request_not_approved")},
            "404": {"summary": "Unknown job, another principal's job, or never accepted", "value": error("job_not_found")},
            "409.executionUnavailable": {"summary": "The extraction configuration group is not enabled", "value": error("execution_unavailable")},
            "409.idempotencyConflict": {"summary": "Same key, different body; the pipeline was not called", "value": error("idempotency_conflict")},
            "409.jobIdUnavailable": {"summary": "The jobId is owned by another principal or already exists in the pipeline ledger", "value": error("job_id_unavailable")},
            "409.approvalChanged": {"summary": "The approval entry no longer matches what the job was reserved under; the id is never rebound", "value": error("approval_changed")},
            "409.requestUnavailable": {"summary": "The pipeline refused the approved request (rights, binding); nothing was registered", "value": error("request_unavailable", runtime_code="source_not_authorized")},
            "409.reconcileRequired": {"summary": "Recover of a reconciling job", "value": error("reconcile_required", job_status=reconciling)},
            "409.jobNotRecoverable": {"summary": "Recover of a ready or cancelled job", "value": error("job_not_recoverable", job_status=status())},
            "409.jobAlreadyTerminal": {"summary": "Cancel of a ready job: it stays ready", "value": error("job_already_terminal", job_status=status())},
            "422": {"summary": "Header, path or JSON envelope validation (a snapshot, catalogue, path or fixture in the body is an unknown field)", "value": error("invalid_request", field="body")},
            "503": {"summary": "The pipeline is busy: retry with the same key and body", "value": error("runtime_busy", retryable=True)},
        },
    }


def _attach(operation: dict[str, Any], code: str, mapping: dict[str, Any]) -> None:
    operation["responses"][code]["content"]["application/json"]["examples"] = mapping


def document(spec: dict[str, Any]) -> None:
    paths, schemas = spec["paths"], spec["components"]["schemas"]
    sample = examples()
    request = ExtractionSubmit.model_json_schema(by_alias=True, ref_template="#/components/schemas/{model}")
    for name, definition in request.pop("$defs", {}).items():
        schemas.setdefault(name, definition)
    schemas["ExtractionSubmit"] = request
    family = [p for p in paths if p.startswith("/internal/v1/extraction-jobs")]
    for code, key in (("401", "401"), ("404", "404"), ("422", "422"), ("503", "503")):
        for path in family:
            for operation in paths[path].values():
                if code in operation["responses"]:
                    _attach(operation, code, {"example": sample["errors"][key]})
    base = paths["/internal/v1/extraction-jobs"]["post"]
    base["requestBody"] = {"required": True, "content": {"application/json": {
        "schema": {"$ref": "#/components/schemas/ExtractionSubmit"},
        "examples": {"extractionJob": {"summary": "A reference to an operator-approved S2 request; Idempotency-Key must equal jobId", "value": SUBMIT}}}}}
    base["responses"]["202"]["description"] = "Newly accepted: the pipeline registered the approved request and the owner binding, the frozen approval identity and the one initial dispatch intent are durable."
    _attach(base, "202", sample["submit.202"])
    _attach(base, "200", sample["submit.200"])
    for code in ("200", "202"):
        base["responses"][code]["headers"] = {
            "Location": {"description": "Status URL of the job.", "schema": {"type": "string"}},
            "Retry-After": {"description": "Seconds to wait before polling; present while next is wait.", "schema": {"type": "integer"}}}
    _attach(base, "403", {"scopeDenied": sample["errors"]["403.scope"], "requestNotApproved": sample["errors"]["403.approval"]})
    _attach(base, "409", {"executionUnavailable": sample["errors"]["409.executionUnavailable"], "idempotencyConflict": sample["errors"]["409.idempotencyConflict"],
                          "jobIdUnavailable": sample["errors"]["409.jobIdUnavailable"], "approvalChanged": sample["errors"]["409.approvalChanged"],
                          "requestUnavailable": sample["errors"]["409.requestUnavailable"]})
    for path, method in (("/internal/v1/extraction-jobs/{jobId}", "get"), ("/internal/v1/extraction-jobs/{jobId}/result", "get"),
                         ("/internal/v1/extraction-jobs/{jobId}/cancel", "post")):
        _attach(paths[path][method], "403", {"example": sample["errors"]["403.scope"]})
        _attach(paths[path][method], "409", {"example": sample["errors"]["409.executionUnavailable"]})
    status_op = paths["/internal/v1/extraction-jobs/{jobId}"]["get"]
    status_op["responses"]["200"]["description"] = "Current job status read from the pipeline during this request. It never carries candidates, citations, quotes or digests of content."
    _attach(status_op, "200", sample["status.200"])
    result_op = paths["/internal/v1/extraction-jobs/{jobId}/result"]["get"]
    result_op["responses"]["200"]["description"] = "Candidates of a ready job; content is withheld unless every delivery gate holds at this moment."
    _attach(result_op, "200", sample["result.200"])
    cancel = paths["/internal/v1/extraction-jobs/{jobId}/cancel"]["post"]
    cancel["responses"]["200"]["description"] = "The job is cancelled (also when it already was). A ready job is refused with 409."
    _attach(cancel, "200", sample["cancel.200"])
    _attach(cancel, "409", {"jobAlreadyTerminal": sample["errors"]["409.jobAlreadyTerminal"], "executionUnavailable": sample["errors"]["409.executionUnavailable"]})
    recover = paths["/internal/v1/extraction-jobs/{jobId}/recover"]["post"]
    recover["responses"]["202"]["description"] = "A dispatch was enqueued."
    _attach(recover, "202", sample["recover.202"])
    _attach(recover, "200", sample["recover.200"])
    _attach(recover, "403", {"scopeDenied": sample["errors"]["403.scope"], "requestNotApproved": sample["errors"]["403.approval"]})
    _attach(recover, "409", {"reconcileRequired": sample["errors"]["409.reconcileRequired"], "jobNotRecoverable": sample["errors"]["409.jobNotRecoverable"],
                             "approvalChanged": sample["errors"]["409.approvalChanged"], "executionUnavailable": sample["errors"]["409.executionUnavailable"]})
