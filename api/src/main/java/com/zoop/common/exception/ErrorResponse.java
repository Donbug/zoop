package com.zoop.common.exception;

public record ErrorResponse(Error error) {
    public static ErrorResponse of(ErrorCode code, String requestId) {
        return of(code, requestId, code.isRetryable());
    }

    public static ErrorResponse of(ErrorCode code, String requestId, boolean retryable) {
        return new ErrorResponse(new Error(code.name(), code.getMessage(), requestId, retryable));
    }

    public record Error(String code, String message, String requestId, boolean retryable) {
    }
}
