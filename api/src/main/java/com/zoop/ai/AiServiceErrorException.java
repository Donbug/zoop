package com.zoop.ai;

import java.time.Duration;
import java.util.Objects;
import java.util.Optional;

/**
 * The AI service answered with its error envelope, which this client decoded: the service's own code, retry advice and
 * request id. The caller decides what to do from {@link #code()}, {@link #retryable()}, {@link #retryAfter()} and, for 409
 * answers that carry one, {@link #status()}.
 *
 * <p><b>This is not proof that nothing happened.</b> The service can commit a mutation in its runtime and still answer a
 * 5xx envelope (for example {@code 503 runtime_unavailable} after the runtime may have registered a submit, or after a cancel
 * reached the runtime). For a mutating operation {@link #requestMaybeProcessed()} is therefore true for every 5xx and false
 * only for a 4xx answer. Recover as for {@link AiTransportException}: read {@code status(jobId)} first; never mint a new job
 * id. The client never retries; {@code retryable()} is only the service's advice, and a submit retry must reuse the same job
 * id and body.
 */
public final class AiServiceErrorException extends AiClientException {
    private final int httpStatus;
    private final String code;
    private final boolean retryable;
    private final Optional<String> runtimeCode;
    private final Optional<String> field;
    private final Optional<Duration> retryAfter;
    private final Optional<AnalysisJobStatus> status;

    public AiServiceErrorException(AiOperation operation, String requestId, int httpStatus, String code, boolean retryable,
                                      Optional<String> runtimeCode, Optional<String> field, Optional<Duration> retryAfter,
                                      Optional<AnalysisJobStatus> status) {
        super("AI " + operation + " rejected: http=" + httpStatus + " code=" + code + " retryable=" + retryable
                + " requestId=" + requestId, operation, requestId);
        this.httpStatus = httpStatus;
        this.code = Objects.requireNonNull(code, "code");
        this.retryable = retryable;
        this.runtimeCode = runtimeCode;
        this.field = field;
        this.retryAfter = retryAfter;
        this.status = status;
    }

    /** True for a mutating operation answered with a 5xx; see the class comment. */
    @Override
    public boolean requestMaybeProcessed() {
        return operation().mutating() && httpStatus >= 500;
    }

    public int httpStatus() {
        return httpStatus;
    }

    /** Lowercase AI service code such as {@code idempotency_conflict}, {@code job_not_found}, {@code scope_denied}. */
    public String code() {
        return code;
    }

    public boolean retryable() {
        return retryable;
    }

    public Optional<String> runtimeCode() {
        return runtimeCode;
    }

    /** The request field the AI service blames (for example {@code Idempotency-Key}), when it names one. */
    public Optional<String> field() {
        return field;
    }

    public Optional<Duration> retryAfter() {
        return retryAfter;
    }

    /** The job status that accompanies {@code job_already_terminal}, {@code reconcile_required} and {@code job_not_recoverable}. */
    public Optional<AnalysisJobStatus> status() {
        return status;
    }
}
