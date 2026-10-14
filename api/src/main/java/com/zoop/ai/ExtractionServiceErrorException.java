package com.zoop.ai;

import java.time.Duration;
import java.util.Optional;

import com.zoop.ai.extraction.ExtractionJobStatus;

/**
 * The S2 extraction service answered with its error envelope (schema {@code zoop-ai-internal-extraction-1}). Codes are the
 * service's own lowercase ones ({@code request_not_approved}, {@code approval_changed}, {@code fixture_changed},
 * {@code job_already_terminal}, {@code reconcile_required}, ...). Not proof that nothing happened for a mutating operation: see
 * {@link AiServiceRejectionException}.
 */
public final class ExtractionServiceErrorException extends AiServiceRejectionException {
    private final Optional<ExtractionJobStatus> status;

    public ExtractionServiceErrorException(AiOperation operation, String requestId, int httpStatus, String code, boolean retryable,
                                           Optional<String> runtimeCode, Optional<String> field, Optional<Duration> retryAfter,
                                           Optional<ExtractionJobStatus> status) {
        super(operation, requestId, httpStatus, code, retryable, runtimeCode, field, retryAfter);
        this.status = status;
    }

    /** The job status that accompanies {@code job_already_terminal}, {@code reconcile_required} and {@code job_not_recoverable}. */
    public Optional<ExtractionJobStatus> status() {
        return status;
    }
}
