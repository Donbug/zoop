package com.zoop.ai;

import java.time.Duration;
import java.util.Objects;
import java.util.Optional;

/**
 * The AI service answered a request with its own error envelope, which this client decoded: the service's code, retry advice and
 * request id. One subclass per transport family carries that family's typed job or operation status for the 409 answers that
 * include one ({@link AiServiceErrorException} for S1, {@link ExtractionServiceErrorException} and
 * {@link RelationServiceErrorException} for S2 and S3). A sealed hierarchy outside a named module must live in one package, which
 * is why the three exceptions sit here while the S2 and S3 domain types live in {@code com.zoop.ai.extraction} and
 * {@code com.zoop.ai.relation}.
 *
 * <p><b>This is not proof that nothing happened.</b> The service can commit a mutation in its runtime and still answer a 5xx
 * envelope (for example {@code 503 runtime_unavailable} after the runtime may have registered a submit, or after a cancel reached
 * the runtime). For a mutating operation {@link #requestMaybeProcessed()} is therefore true for every 5xx and false only for a
 * 4xx answer. Recover as for {@link AiTransportException}: read the status (or, for a review, the operation) first; never mint a
 * new job id or operation id. The client never retries; {@code retryable()} is only the service's advice.
 */
public abstract sealed class AiServiceRejectionException extends AiClientException
        permits AiServiceErrorException, ExtractionServiceErrorException, RelationServiceErrorException, PlanAdmissionServiceErrorException,
                HandoffServiceErrorException, RoundServiceErrorException {
    private final int httpStatus;
    private final String code;
    private final boolean retryable;
    private final Optional<String> runtimeCode;
    private final Optional<String> field;
    private final Optional<Duration> retryAfter;

    protected AiServiceRejectionException(AiOperation operation, String requestId, int httpStatus, String code, boolean retryable,
                                          Optional<String> runtimeCode, Optional<String> field, Optional<Duration> retryAfter) {
        super("AI " + operation + " rejected: http=" + httpStatus + " code=" + code + " retryable=" + retryable
                + " requestId=" + requestId, operation, requestId);
        this.httpStatus = httpStatus;
        this.code = Objects.requireNonNull(code, "code");
        this.retryable = retryable;
        this.runtimeCode = runtimeCode;
        this.field = field;
        this.retryAfter = retryAfter;
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
}
