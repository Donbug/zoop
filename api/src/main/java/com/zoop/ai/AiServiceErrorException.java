package com.zoop.ai;

import java.time.Duration;
import java.util.Optional;

/**
 * The S1 AI service answered with its error envelope, which this client decoded: the service's own code, retry advice and
 * request id. The caller decides what to do from {@link #code()}, {@link #retryable()}, {@link #retryAfter()} and, for 409
 * answers that carry one, {@link #status()}.
 *
 * <p><b>This is not proof that nothing happened.</b> See {@link AiServiceRejectionException}: for a mutating operation
 * {@link #requestMaybeProcessed()} is true for every 5xx and false only for a 4xx answer. Recover as for
 * {@link AiTransportException}: read {@code status(jobId)} first; never mint a new job id. The client never retries; a submit
 * retry must reuse the same job id and body.
 */
public final class AiServiceErrorException extends AiServiceRejectionException {
    private final Optional<AnalysisJobStatus> status;

    public AiServiceErrorException(AiOperation operation, String requestId, int httpStatus, String code, boolean retryable,
                                      Optional<String> runtimeCode, Optional<String> field, Optional<Duration> retryAfter,
                                      Optional<AnalysisJobStatus> status) {
        super(operation, requestId, httpStatus, code, retryable, runtimeCode, field, retryAfter);
        this.status = status;
    }

    /** The job status that accompanies {@code job_already_terminal}, {@code reconcile_required} and {@code job_not_recoverable}. */
    public Optional<AnalysisJobStatus> status() {
        return status;
    }
}
