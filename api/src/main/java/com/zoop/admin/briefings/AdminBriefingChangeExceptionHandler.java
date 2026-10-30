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
@RestControllerAdvice(assignableTypes = {AdminBriefingChangeController.class, AdminBriefingReprocessController.class})
public class AdminBriefingChangeExceptionHandler {
    @ExceptionHandler({DataAccessException.class, TransactionException.class, com.zoop.artifact.storage.ArtifactStoreException.class})
    public ResponseEntity<ErrorResponse> unavailable(RuntimeException error, HttpServletRequest request) {
        return ResponseEntity.status(503).body(ErrorResponse.of(ErrorCode.SOURCE_UNAVAILABLE, RequestIdFilter.currentId(request)));
    }
    @ExceptionHandler(com.zoop.briefing.usage.BriefingUsageLedger.Rejected.class)
    public ResponseEntity<ErrorResponse> rejected(RuntimeException error,HttpServletRequest request){
        return ResponseEntity.status(409).body(ErrorResponse.of(ErrorCode.VERSION_UNAVAILABLE,RequestIdFilter.currentId(request)));
    }
}

