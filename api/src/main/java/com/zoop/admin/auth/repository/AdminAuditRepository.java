package com.zoop.admin.auth.repository;

import java.time.Instant;

public interface AdminAuditRepository {
    void recordProvisioning(String adminId, String outcome, String reason,
            String requestId, Instant occurredAt);

    void recordLoginFailure(String requestId, Instant occurredAt);

    void recordAdminAction(String adminId, String email, String action,
            String targetId, String requestId, Instant occurredAt);
}
