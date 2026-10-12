package com.zoop.common.exception;

public record ErrorResponse(Error error) {
    public static ErrorResponse of(ErrorCode code, String requestId) {
        return new ErrorResponse(new Error(code.name(), code.getMessage(), requestId, code.isRetryable()));
    }

    public record Error(String code, String message, String requestId, boolean retryable) {
    }
}
