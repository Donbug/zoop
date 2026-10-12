package com.zoop.common.exception;

import java.util.Objects;

public class CustomException extends RuntimeException {
    private final ErrorCode errorCode;

    public CustomException(ErrorCode errorCode) {
        super(Objects.requireNonNull(errorCode).getMessage());
        this.errorCode = errorCode;
    }

    public CustomException(ErrorCode errorCode, Throwable cause) {
        super(Objects.requireNonNull(errorCode).getMessage(), cause);
        this.errorCode = errorCode;
    }

    public ErrorCode getErrorCode() {
        return errorCode;
    }
}
