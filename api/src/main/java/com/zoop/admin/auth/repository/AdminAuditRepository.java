package com.zoop.admin.auth.repository;

import java.time.Instant;

public interface AdminAuditRepository {
    void recordProvisioning(String adminId, String outcome, String reason,
            String requestId, Instant occurredAt);

    void recordLoginFailure(String requestId, String reason, Instant occurredAt);

    void recordAdminAction(String adminId, String email, String action,
            String targetId, String requestId, Instant occurredAt);

    void recordMemberStatusAction(String adminId, String email, String action,
            String memberId, String reason, String beforeStatus, String afterStatus,
            long beforeRevision, long afterRevision, String requestId, Instant occurredAt);

    void recordGraphActivation(String adminId, String email, String versionId, String previousVersionId,
            boolean pointerChanged, String reason, String requestId, Instant occurredAt);

    /** {@code action} is {@code analysis.job.cancel} or {@code analysis.job.retry}; {@code createdJobId} only for a retry. */
    void recordAnalysisJobAction(String adminId, String email, String action, String jobId, String beforeStatus,
            String afterStatus, String createdJobId, String reason, String requestId, Instant occurredAt);
}
