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
            boolean pointerChanged, String reason, String mode, String requestId, Instant occurredAt);

    /** An analysis-job action of a system actor (the round scheduler): {@code actor_kind = system}, no admin. */
    void recordSystemAnalysisJobAction(String actor, String action, String jobId, String beforeStatus, String afterStatus,
            String createdJobId, String reason, String requestId, Instant occurredAt);

    /** An admin's action on a graph round (#55 A-ADM-03): a retry or a manual start. */
    void recordGraphRoundAction(String adminId, String email, String action, String roundId, String requestId, Instant occurredAt);

    /** DB-only create/cancel/retry actions; {@code createdJobId} identifies a newly created root or retry row. */
    void recordAnalysisJobAction(String adminId, String email, String action, String jobId, String beforeStatus,
            String afterStatus, String createdJobId, String reason, String requestId, Instant occurredAt);

    /**
     * Written in the decision's own transaction and never changed: the AI source version and revision the decision was made on
     * (ERD v6 section 27), so a later source change never reads as approved by it.
     */
    void recordReviewDecision(String adminId, String email, String targetId, long reviewDecisionId, String decision,
            String sourceVersion, String sourceRevision, long revision, long globalRevision, String reason, String requestId,
            Instant occurredAt);

    /** A publication rule switch, with the rule's own revision and the app-wide rule log revision it was given. */
    void recordPublicationRuleSwitch(String adminId, String email, String ruleId, long changeId, boolean beforeEnabled,
            boolean afterEnabled, long revision, long logRevision, String reason, String requestId, Instant occurredAt);
}
