package com.zoop.ai;

import java.util.Objects;

/**
 * Failure of one AI transport call. Messages and fields hold only the operation, the HTTP status, stable machine codes and
 * the request id: never a request or response body, a token, a URL or a lower-level exception message.
 *
 * <p>These exceptions use the AI service's own lowercase codes ({@code job_not_found}, {@code runtime_unavailable}, ...).
 * They are not the public {@code ErrorCode} enum, and nothing maps them to it automatically: a feature that exposes AI calls
 * to users chooses that mapping. Left unhandled, {@code GlobalExceptionHandler} answers {@code INTERNAL_ERROR}.
 */
public abstract sealed class AiClientException extends RuntimeException permits AiServiceRejectionException, AiTransportException {
    private final AiOperation operation;
    private final String requestId;

    protected AiClientException(String message, AiOperation operation, String requestId) {
        super(message);
        this.operation = Objects.requireNonNull(operation, "operation");
        this.requestId = Objects.requireNonNull(requestId, "requestId");
    }

    public AiOperation operation() {
        return operation;
    }

    /**
     * Whether the AI service may have acted on the request although the caller has no confirmation. Always false for reads.
     * For a mutating operation it is false only when the request provably never left this process or the service gave a
     * definitive 4xx answer; every transport failure after sending and every 5xx is conservatively true. Resolve it by reading
     * {@code status(jobId)} first, then repeating a submit with the same job id and body only if the job is still unknown.
     */
    public abstract boolean requestMaybeProcessed();

    /** The validated {@code X-Request-ID} sent with the call; the AI service logs the same id. */
    public String requestId() {
        return requestId;
    }
}
