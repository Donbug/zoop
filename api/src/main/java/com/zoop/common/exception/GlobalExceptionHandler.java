package com.zoop.common.exception;

import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.BindException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingRequestValueException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import com.zoop.common.request.RequestIdFilter;
import com.zoop.auth.service.RateLimitedException;
import org.springframework.http.HttpHeaders;

@RestControllerAdvice
public class GlobalExceptionHandler {
    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(CustomException.class)
    public ResponseEntity<ErrorResponse> handleCustom(CustomException exception, HttpServletRequest request) {
        return response(exception.getErrorCode(), request);
    }

    @ExceptionHandler(RateLimitedException.class)
    public ResponseEntity<ErrorResponse> handleRateLimited(RateLimitedException exception,
            HttpServletRequest request) {
        return ResponseEntity.status(ErrorCode.RATE_LIMITED.getStatus())
                .header(HttpHeaders.RETRY_AFTER, Long.toString(exception.retryAfterSeconds()))
                .body(ErrorResponse.of(ErrorCode.RATE_LIMITED, RequestIdFilter.currentId(request)));
    }

    @ExceptionHandler({MethodArgumentNotValidException.class, BindException.class,
            HttpMessageNotReadableException.class, MethodArgumentTypeMismatchException.class,
            MissingRequestValueException.class})
    public ResponseEntity<ErrorResponse> handleInvalidRequest(Exception exception, HttpServletRequest request) {
        return response(ErrorCode.INVALID_REQUEST, request);
    }

    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<ErrorResponse> handleMissingResource(NoResourceFoundException exception,
            HttpServletRequest request) {
        return response(ErrorCode.RESOURCE_NOT_FOUND, request);
    }

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<ErrorResponse> handleMethodNotAllowed(HttpRequestMethodNotSupportedException exception,
            HttpServletRequest request) {
        return ResponseEntity.status(exception.getStatusCode())
                .body(ErrorResponse.of(ErrorCode.INVALID_REQUEST, RequestIdFilter.currentId(request)));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> handleUnexpected(Exception exception, HttpServletRequest request) {
        log.error("Unexpected request failure (requestId={})", RequestIdFilter.currentId(request), exception);
        return response(ErrorCode.INTERNAL_ERROR, request);
    }

    private ResponseEntity<ErrorResponse> response(ErrorCode code, HttpServletRequest request) {
        return ResponseEntity.status(code.getStatus())
                .body(ErrorResponse.of(code, RequestIdFilter.currentId(request)));
    }
}
