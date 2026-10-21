package com.zoop.admin.insights;

import com.zoop.common.exception.ErrorCode;
import com.zoop.common.exception.ErrorResponse;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.dao.TransientDataAccessException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** Maps transient database unavailability without hiding SQL or mapping defects. */
@Order(Ordered.HIGHEST_PRECEDENCE)
@RestControllerAdvice(assignableTypes = AdminInsightsController.class)
public class AdminInsightsReadExceptionHandler {
    @ExceptionHandler({DataAccessResourceFailureException.class, TransientDataAccessException.class})
    public ResponseEntity<ErrorResponse> unavailable(RuntimeException error, HttpServletRequest request) {
        return ResponseEntity.status(ErrorCode.SOURCE_UNAVAILABLE.getStatus())
                .body(ErrorResponse.of(ErrorCode.SOURCE_UNAVAILABLE, RequestIdFilter.currentId(request)));
    }
}
