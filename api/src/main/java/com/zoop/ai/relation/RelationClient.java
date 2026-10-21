package com.zoop.ai.relation;

/**
 * App-side client of the internal S3 relation-job transport ({@code /internal/v1/relation-jobs}, runtime contract
 * {@code zoop-relation-s3}, response schema {@code zoop-ai-internal-relation-1}). The app is the authenticated service principal;
 * the transport has no end-user identity, and the S2 upstream is allowed by the operator's server-side allowlist, not by the
 * caller.
 *
 * <p>Every method sends exactly one HTTP request with no redirect and no automatic retry, and throws
 * {@link com.zoop.ai.RelationServiceErrorException} for a decoded service refusal or {@link com.zoop.ai.AiTransportException}
 * when there is no usable answer. Calls block the calling thread up to the configured request timeout.
 */
public interface RelationClient {

    /** {@code POST /internal/v1/relation-jobs}, {@code Idempotency-Key = submission.jobId()}. Scope {@code relation.submit}. */
    RelationAcknowledgement submit(RelationSubmission submission);

    /** {@code GET .../{jobId}}: the live pipeline state read inside the request, no content. Scope {@code relation.read}. */
    RelationJobStatus status(String jobId);

    /** {@code GET .../{jobId}/result}: candidates only while every server-side gate holds. Scope {@code relation.read}. */
    RelationResult result(String jobId);

    /**
     * {@code POST .../{jobId}/cancel}: idempotent. A {@code READY} job is refused with {@code job_already_terminal} and is not
     * touched. Scope {@code relation.cancel}.
     */
    RelationJobStatus cancel(String jobId);

    /** {@code POST .../{jobId}/recover}: explicit resume, idempotent. Scope {@code relation.recover}. */
    RelationAcknowledgement recover(String jobId);

    /**
     * {@code POST .../{jobId}/reviews}, {@code Idempotency-Key = request.operationId()}: records one decision on a relation candidate
     * that is on HOLD if and only if {@code expectedSourceVersion} and {@code expectedSourceRevision} still match the runtime. An
     * {@code ALLOW} is the operator's FINAL approval (terminal: no revalidation, no model call) and a {@code REJECT} an exclusion; the
     * pipeline re-runs its deterministic checks and current-rights checks, so a human decision never overrides them. A mismatch
     * ({@code source_version_conflict}, {@code source_revision_conflict}) records nothing and releases the operation id. After an
     * ambiguous outcome call {@link #operation} with the same key first, then repeat the same request. Scope {@code relation.review}.
     */
    RelationOperationAcknowledgement review(String jobId, RelationReviewRequest request);

    /** {@code GET .../{jobId}/reviews/{operationId}}: the operation by its exact key, from the service ledger. Scope {@code relation.read}. */
    RelationOperationStatus operation(String jobId, String operationId);
}
