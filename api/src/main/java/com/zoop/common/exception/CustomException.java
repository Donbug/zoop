package com.zoop.common.exception;

import java.util.Objects;

public class CustomException extends RuntimeException {
    private final ErrorCode errorCode;
    private final boolean retryable;

    public CustomException(ErrorCode errorCode) {
        this(errorCode, errorCode.isRetryable());
    }

    public CustomException(ErrorCode errorCode, boolean retryable) {
        super(Objects.requireNonNull(errorCode).getMessage());
        this.errorCode = errorCode;
        this.retryable = retryable;
    }

    public CustomException(ErrorCode errorCode, Throwable cause) {
        super(Objects.requireNonNull(errorCode).getMessage(), cause);
        this.errorCode = errorCode;
        this.retryable = errorCode.isRetryable();
    }

    public ErrorCode getErrorCode() {
        return errorCode;
    }

    public boolean isRetryable() {
        return retryable;
    }
}
