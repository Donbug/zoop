package com.zoop.admin.briefings;

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

@Order(Ordered.HIGHEST_PRECEDENCE)
@RestControllerAdvice(assignableTypes = AdminBriefingController.class)
public class AdminBriefingReadExceptionHandler {
    @ExceptionHandler({DataAccessException.class, TransactionException.class})
    public ResponseEntity<ErrorResponse> unavailable(RuntimeException error, HttpServletRequest request) {
        return ResponseEntity.status(ErrorCode.SOURCE_UNAVAILABLE.getStatus())
                .body(ErrorResponse.of(ErrorCode.SOURCE_UNAVAILABLE, RequestIdFilter.currentId(request)));
    }
}
