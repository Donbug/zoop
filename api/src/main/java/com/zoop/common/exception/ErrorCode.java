package com.zoop.common.exception;

import org.springframework.http.HttpStatus;

public enum ErrorCode {
    INVALID_REQUEST(HttpStatus.UNPROCESSABLE_CONTENT, "잘못된 요청입니다.", false),
    INVALID_CREDENTIALS(HttpStatus.UNAUTHORIZED, "이메일 또는 비밀번호를 확인해 주세요.", false),
    AUTH_REQUIRED(HttpStatus.UNAUTHORIZED, "로그인이 필요합니다.", false),
    MEMBER_REQUIRED(HttpStatus.FORBIDDEN, "회원 전용 기능입니다.", false),
    MEMBER_BLOCKED(HttpStatus.FORBIDDEN, "차단된 회원입니다.", false),
    ACCESS_DENIED(HttpStatus.FORBIDDEN, "요청이 허용되지 않습니다.", false),
    EMAIL_TAKEN(HttpStatus.CONFLICT, "이미 등록된 이메일입니다.", false),
    SOCIAL_LINK_REQUIRED(HttpStatus.CONFLICT, "기존 계정으로 로그인한 후 소셜 계정을 연결해 주세요.", false),
    TERMS_REQUIRED(HttpStatus.UNPROCESSABLE_CONTENT, "필수 약관 동의를 확인해 주세요.", false),
    RATE_LIMITED(HttpStatus.TOO_MANY_REQUESTS, "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.", true),
    INVALID_CURSOR(HttpStatus.UNPROCESSABLE_CONTENT, "유효하지 않은 커서입니다.", false),
    RESOURCE_NOT_FOUND(HttpStatus.NOT_FOUND, "요청한 리소스를 찾을 수 없습니다.", false),
    SOURCE_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "요청한 정보를 일시적으로 사용할 수 없습니다.", true),
    INTERNAL_ERROR(HttpStatus.INTERNAL_SERVER_ERROR, "서버 오류가 발생했습니다.", false);

    private final HttpStatus status;
    private final String message;
    private final boolean retryable;

    ErrorCode(HttpStatus status, String message, boolean retryable) {
        this.status = status;
        this.message = message;
        this.retryable = retryable;
    }

    public HttpStatus getStatus() {
        return status;
    }

    public String getMessage() {
        return message;
    }

    public boolean isRetryable() {
        return retryable;
    }
}
