package com.zoop.briefing.controller;

import com.zoop.common.exception.ErrorCode;
import com.zoop.common.exception.ErrorResponse;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.dao.DataAccessException;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.TransactionException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** Transaction acquisition can fail before the service method executes its database-error guard. */
@Order(Ordered.HIGHEST_PRECEDENCE)
@RestControllerAdvice(assignableTypes = BriefingController.class)
public class BriefingReadExceptionHandler {
    @ExceptionHandler({DataAccessException.class, TransactionException.class})
    public ResponseEntity<ErrorResponse> unavailable(RuntimeException error, HttpServletRequest request) {
        return ResponseEntity.status(ErrorCode.SOURCE_UNAVAILABLE.getStatus())
                .body(ErrorResponse.of(ErrorCode.SOURCE_UNAVAILABLE, RequestIdFilter.currentId(request)));
    }
}
