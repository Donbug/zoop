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

    /**
     * Written in the decision's own transaction and never changed: the AI source version and revision the decision was made on
     * (ERD v6 section 27), so a later source change never reads as approved by it.
     */
    void recordReviewDecision(String adminId, String email, String targetId, long reviewDecisionId, String decision,
            String sourceVersion, String sourceRevision, long revision, long globalRevision, String reason, String requestId,
            Instant occurredAt);
}
