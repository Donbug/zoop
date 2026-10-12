package com.zoop.ai;

import java.util.Objects;
import java.util.OptionalInt;

/**
 * No usable AI answer: the call failed in transport or the response could not be trusted. For a mutating operation this is
 * an <b>unknown outcome</b> when {@link #requestMaybeProcessed()} is true.
 *
 * <p><b>Recovery.</b> Do not mint a new job id and do not retry a generation blindly. Read {@code status(jobId)} first:
 * <ul>
 *   <li>200: the job exists; follow {@code next}.</li>
 *   <li>404 {@code job_not_found}: either nothing was registered, or the service reserved the id and has not accepted it yet.
 *       Only then repeat the submit with the <em>same</em> job id and the <em>same</em> body: the AI service makes that
 *       idempotent and never registers a second job.</li>
 *   <li>Another transport failure: stop and retry the status read later.</li>
 * </ul>
 * For cancel and recover, read the status and decide again; both are idempotent.
 */
public final class AiTransportException extends AiClientException {
    private final Failure failure;
    private final OptionalInt httpStatus;
    private final String causeType;

    public AiTransportException(AiOperation operation, String requestId, Failure failure, OptionalInt httpStatus, String causeType) {
        super("AI " + operation + " transport failure: " + failure + (httpStatus.isPresent() ? " http=" + httpStatus.getAsInt() : "")
                + " requestId=" + requestId, operation, requestId);
        this.failure = Objects.requireNonNull(failure, "failure");
        this.httpStatus = httpStatus;
        this.causeType = causeType;
    }

    public Failure failure() {
        return failure;
    }

    public OptionalInt httpStatus() {
        return httpStatus;
    }

    /** Simple class name of the lower-level cause, never its message. */
    public String causeType() {
        return causeType;
    }

    /**
     * Same meaning as {@link AiClientException#requestMaybeProcessed()}: always false for a read; for a mutating operation
     * false only when the request provably never left this process (connection could not be established) and true for every
     * other failure, because the service may or may not have acted.
     */
    @Override
    public boolean requestMaybeProcessed() {
        return operation().mutating() && failure != Failure.CONNECT_FAILED && failure != Failure.CONNECT_TIMEOUT;
    }

    public enum Failure {
        CONNECT_FAILED,
        CONNECT_TIMEOUT,
        /** The total request deadline passed: the service may still be working. */
        TIMEOUT,
        IO_ERROR,
        INTERRUPTED,
        RESPONSE_TOO_LARGE,
        /** Syntax, schema, enum, type, identity or request-id echo violation in a response. */
        RESPONSE_MALFORMED,
        /** A redirect was received; it is never followed and the bearer token is never re-sent. */
        REDIRECT_REFUSED,
        /** A status or body that is neither a documented success nor a decodable AI error envelope. */
        UNEXPECTED_RESPONSE
    }
}
