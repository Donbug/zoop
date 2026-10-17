package com.zoop.admin.auth.service;

import java.time.Clock;
import java.time.Instant;

import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AdminAuthAuditService implements AdminSessionService.AdminSessionAudit {
    private final AdminAuditRepository repository;
    private final Clock clock;

    public AdminAuthAuditService(AdminAuditRepository repository, Clock clock) {
        this.repository = repository;
        this.clock = clock;
    }

    @Override
    public void record(String adminId, String email, String action, String sessionId,
            String requestId, Instant at) {
        repository.recordAdminAction(adminId, email, action, sessionId, requestId, at);
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void loginFailed(String requestId) {
        try {
            repository.recordLoginFailure(requestId, clock.instant());
        } catch (RuntimeException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }
}
