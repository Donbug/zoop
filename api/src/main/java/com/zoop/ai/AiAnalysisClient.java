package com.zoop.ai;

/**
 * App-side client of the internal S1 AI analysis transport ({@code docs/api/internal-ai-openapi.yaml}, contract
 * {@code zoop-ai-s1-1}). The app is the authenticated service principal; the transport has no end-user identity.
 *
 * <p>Every method sends exactly one HTTP request with no redirect and no automatic retry, and throws
 * {@link AiServiceErrorException} for a decoded service refusal or {@link AiTransportException} when there is no usable
 * answer. Calls block the calling thread up to the configured request timeout.
 */
public interface AiAnalysisClient {

    /** {@code POST /internal/v1/analysis-jobs}, {@code Idempotency-Key = submission.jobId()}. Scope {@code analysis.submit}. */
    AnalysisAcknowledgement submit(AnalysisSubmission submission);

    /** {@code GET /internal/v1/analysis-jobs/{jobId}}: the live runtime state, no content. Scope {@code analysis.read}. */
    AnalysisJobStatus status(String jobId);

    /** {@code GET .../{jobId}/result}: content only while current source rights allow it. Scope {@code analysis.read}. */
    AnalysisResult result(String jobId);

    /**
     * {@code POST .../{jobId}/cancel}: idempotent. A running provider call is not killed; its late receipt is still stored and
     * counts as usage, so the returned status is never proof of zero cost. A ready or failed job answers
     * {@code job_already_terminal}. Scope {@code analysis.cancel}.
     */
    AnalysisJobStatus cancel(String jobId);

    /** {@code POST .../{jobId}/recover}: explicit re-dispatch, idempotent. Scope {@code analysis.recover}. */
    AnalysisAcknowledgement recover(String jobId);
}
