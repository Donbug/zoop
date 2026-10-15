package com.zoop.ai.extraction;

/**
 * App-side client of the internal S2 extraction-job transport ({@code /internal/v1/extraction-jobs}, runtime contract
 * {@code zoop-extraction-s2-2}, response schema {@code zoop-ai-internal-extraction-1}). The app is the authenticated service
 * principal; the transport has no end-user identity, and the S2 request itself is the operator's approval, not the caller's.
 *
 * <p>Every method sends exactly one HTTP request with no redirect and no automatic retry, and throws
 * {@link com.zoop.ai.ExtractionServiceErrorException} for a decoded service refusal or {@link com.zoop.ai.AiTransportException}
 * when there is no usable answer. Calls block the calling thread up to the configured request timeout.
 */
public interface ExtractionClient {

    /** {@code POST /internal/v1/extraction-jobs}, {@code Idempotency-Key = submission.jobId()}. Scope {@code extraction.submit}. */
    ExtractionAcknowledgement submit(ExtractionSubmission submission);

    /** {@code GET .../{jobId}}: the live pipeline state read inside the request, no content. Scope {@code extraction.read}. */
    ExtractionJobStatus status(String jobId);

    /** {@code GET .../{jobId}/result}: candidates only while every server-side gate holds. Scope {@code extraction.read}. */
    ExtractionResult result(String jobId);

    /**
     * {@code POST .../{jobId}/cancel}: idempotent. A running child is not killed. A {@code READY} job is refused with
     * {@code job_already_terminal} and stays ready. Scope {@code extraction.cancel}.
     */
    ExtractionJobStatus cancel(String jobId);

    /** {@code POST .../{jobId}/recover}: explicit resume, idempotent; the only way a stopped or ambiguous job continues. Scope {@code extraction.recover}. */
    ExtractionAcknowledgement recover(String jobId);
}
