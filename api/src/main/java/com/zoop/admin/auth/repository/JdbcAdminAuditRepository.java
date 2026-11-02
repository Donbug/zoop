package com.zoop.admin.auth.repository;

import java.sql.Timestamp;
import java.time.Instant;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcAdminAuditRepository implements AdminAuditRepository {
    private final NamedParameterJdbcTemplate jdbc;

    public JdbcAdminAuditRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public void recordProvisioning(String adminId, String outcome, String reason,
            String requestId, Instant occurredAt) {
        jdbc.update("""
                INSERT INTO audit_logs
                  (actor_kind, admin_id, actor_id, actor_email_snapshot, action,
                   target_type, target_id, outcome, purpose, reason, request_id, detail, occurred_at)
                VALUES ('system', NULL, 'admin-provision', NULL, 'admin.provision',
                        'admin', :adminId, :outcome, NULL, :reason, :requestId,
                        jsonb_build_object('role', 'admin'), :occurredAt)
                """, new MapSqlParameterSource("adminId", adminId)
                .addValue("outcome", outcome)
                .addValue("reason", reason)
                .addValue("requestId", requestId)
                .addValue("occurredAt", Timestamp.from(occurredAt)));
    }

    @Override
    public void recordLoginFailure(String requestId, String reason, Instant occurredAt) {
        jdbc.update("""
                INSERT INTO audit_logs
                  (actor_kind, admin_id, actor_id, actor_email_snapshot, action,
                   target_type, target_id, outcome, purpose, reason, request_id, detail, occurred_at)
                VALUES ('anonymous', NULL, 'unknown', NULL, 'auth.login_failed',
                        'admin_session', NULL, 'denied', NULL, :reason,
                        :requestId, '{}'::jsonb, :occurredAt)
                """, new MapSqlParameterSource("requestId", requestId)
                .addValue("reason", reason)
                .addValue("occurredAt", Timestamp.from(occurredAt)));
    }

    @Override
    public void recordAdminAction(String adminId, String email, String action,
            String targetId, String requestId, Instant occurredAt) {
        jdbc.update("""
                INSERT INTO audit_logs
                  (actor_kind, admin_id, actor_id, actor_email_snapshot, action,
                   target_type, target_id, outcome, purpose, reason, request_id, detail, occurred_at)
                VALUES ('admin', :adminId, :adminId, :email, :action,
                        'admin_session', :targetId, 'succeeded', NULL, NULL,
                        :requestId, '{}'::jsonb, :occurredAt)
                """, new MapSqlParameterSource("adminId", adminId)
                .addValue("email", email)
                .addValue("action", action)
                .addValue("targetId", targetId)
                .addValue("requestId", requestId)
                .addValue("occurredAt", Timestamp.from(occurredAt)));
    }

    @Override
    public void recordMemberStatusAction(String adminId, String email, String action,
            String memberId, String reason, String beforeStatus, String afterStatus,
            long beforeRevision, long afterRevision, String requestId, Instant occurredAt) {
        jdbc.update("""
                INSERT INTO audit_logs
                  (actor_kind, admin_id, actor_id, actor_email_snapshot, action,
                   target_type, target_id, outcome, purpose, reason, request_id, detail, occurred_at)
                VALUES ('admin', :adminId, :adminId, :email, :action,
                        'member', :memberId, 'succeeded', 'member_access_management', :reason,
                        :requestId, jsonb_build_object(
                            'beforeStatus', :beforeStatus,
                            'afterStatus', :afterStatus,
                            'beforeRevision', :beforeRevision,
                            'afterRevision', :afterRevision), :occurredAt)
                """, new MapSqlParameterSource("adminId", adminId)
                .addValue("email", email).addValue("action", action)
                .addValue("memberId", memberId).addValue("reason", reason)
                .addValue("beforeStatus", beforeStatus).addValue("afterStatus", afterStatus)
                .addValue("beforeRevision", beforeRevision).addValue("afterRevision", afterRevision)
                .addValue("requestId", requestId).addValue("occurredAt", Timestamp.from(occurredAt)));
    }

    @Override
    public void recordGraphActivation(String adminId, String email, String versionId, String previousVersionId,
            boolean pointerChanged, String reason, String mode, String requestId, Instant occurredAt) {
        jdbc.update("""
                INSERT INTO audit_logs
                  (actor_kind, admin_id, actor_id, actor_email_snapshot, action,
                   target_type, target_id, outcome, purpose, reason, request_id, detail, occurred_at)
                VALUES ('admin', :adminId, :adminId, :email, 'graph.version.activate',
                        'graph_version', :versionId, 'succeeded', 'graph_publication', :reason,
                        :requestId, jsonb_build_object(
                            'previousVersionId', CAST(:previousVersionId AS text),
                            'pointerChanged', :pointerChanged, 'mode', CAST(:mode AS text)), :occurredAt)
                """, new MapSqlParameterSource("adminId", adminId)
                .addValue("email", email).addValue("versionId", versionId)
                .addValue("previousVersionId", previousVersionId).addValue("pointerChanged", pointerChanged)
                .addValue("reason", reason).addValue("mode", mode).addValue("requestId", requestId)
                .addValue("occurredAt", Timestamp.from(occurredAt)));
    }

    @Override
    public void recordSystemAnalysisJobAction(String actor, String action, String jobId, String beforeStatus, String afterStatus,
            String createdJobId, String reason, String requestId, Instant occurredAt) {
        jdbc.update("""
                INSERT INTO audit_logs
                  (actor_kind, admin_id, actor_id, actor_email_snapshot, action,
                   target_type, target_id, outcome, purpose, reason, request_id, detail, occurred_at)
                VALUES ('system', NULL, :actor, 'system', :action,
                        'analysis_job', :jobId, 'succeeded', 'analysis_operations', :reason,
                        :requestId, jsonb_strip_nulls(jsonb_build_object(
                            'beforeStatus', CAST(:beforeStatus AS text),
                            'afterStatus', CAST(:afterStatus AS text),
                            'createdJobId', CAST(:createdJobId AS text))), :occurredAt)
                """, new MapSqlParameterSource("actor", actor)
                .addValue("action", action).addValue("jobId", jobId)
                .addValue("beforeStatus", beforeStatus).addValue("afterStatus", afterStatus)
                .addValue("createdJobId", createdJobId).addValue("reason", reason).addValue("requestId", requestId)
                .addValue("occurredAt", Timestamp.from(occurredAt)));
    }

    @Override
    public void recordGraphRoundAction(String adminId, String email, String action, String roundId, String requestId,
            Instant occurredAt) {
        jdbc.update("""
                INSERT INTO audit_logs
                  (actor_kind, admin_id, actor_id, actor_email_snapshot, action,
                   target_type, target_id, outcome, purpose, reason, request_id, detail, occurred_at)
                VALUES ('admin', :adminId, :adminId, :email, :action,
                        'graph_round', :roundId, 'succeeded', 'graph_operations', NULL,
                        :requestId, '{}'::jsonb, :occurredAt)
                """, new MapSqlParameterSource("adminId", adminId)
                .addValue("email", email).addValue("action", action).addValue("roundId", roundId)
                .addValue("requestId", requestId).addValue("occurredAt", Timestamp.from(occurredAt)));
    }

    @Override
    public void recordAnalysisJobAction(String adminId, String email, String action, String jobId, String beforeStatus,
            String afterStatus, String createdJobId, String reason, String requestId, Instant occurredAt) {
        jdbc.update("""
                INSERT INTO audit_logs
                  (actor_kind, admin_id, actor_id, actor_email_snapshot, action,
                   target_type, target_id, outcome, purpose, reason, request_id, detail, occurred_at)
                VALUES ('admin', :adminId, :adminId, :email, :action,
                        'analysis_job', :jobId, 'succeeded', 'analysis_operations', :reason,
                        :requestId, jsonb_strip_nulls(jsonb_build_object(
                            'beforeStatus', CAST(:beforeStatus AS text),
                            'afterStatus', CAST(:afterStatus AS text),
                            'createdJobId', CAST(:createdJobId AS text))), :occurredAt)
                """, new MapSqlParameterSource("adminId", adminId)
                .addValue("email", email).addValue("action", action).addValue("jobId", jobId)
                .addValue("beforeStatus", beforeStatus).addValue("afterStatus", afterStatus)
                .addValue("createdJobId", createdJobId).addValue("reason", reason).addValue("requestId", requestId)
                .addValue("occurredAt", Timestamp.from(occurredAt)));
    }

    @Override
    public void recordReviewDecision(String adminId, String email, String targetId, long reviewDecisionId, String decision,
            String sourceVersion, String sourceRevision, long revision, long globalRevision, String reason, String requestId,
            Instant occurredAt) {
        jdbc.update("""
                INSERT INTO audit_logs
                  (actor_kind, admin_id, actor_id, actor_email_snapshot, action,
                   target_type, target_id, outcome, purpose, reason, request_id, detail, occurred_at)
                VALUES ('admin', :adminId, :adminId, :email, 'review.decision',
                        'review_target', :targetId, 'succeeded', 'review', :reason,
                        :requestId, jsonb_build_object(
                            'reviewDecisionId', CAST(:reviewDecisionId AS bigint),
                            'decision', CAST(:decision AS text),
                            'sourceVersion', CAST(:sourceVersion AS text),
                            'sourceRevision', CAST(:sourceRevision AS text),
                            'revision', CAST(:revision AS bigint),
                            'globalRevision', CAST(:globalRevision AS bigint)), :occurredAt)
                """, new MapSqlParameterSource("adminId", adminId)
                .addValue("email", email).addValue("targetId", targetId).addValue("reviewDecisionId", reviewDecisionId)
                .addValue("decision", decision).addValue("sourceVersion", sourceVersion)
                .addValue("sourceRevision", sourceRevision).addValue("revision", revision)
                .addValue("globalRevision", globalRevision).addValue("reason", reason).addValue("requestId", requestId)
                .addValue("occurredAt", Timestamp.from(occurredAt)));
    }

    @Override
    public void recordPublicationRuleSwitch(String adminId, String email, String ruleId, long changeId,
            boolean beforeEnabled, boolean afterEnabled, long revision, long logRevision, String reason, String requestId,
            Instant occurredAt) {
        jdbc.update("""
                INSERT INTO audit_logs
                  (actor_kind, admin_id, actor_id, actor_email_snapshot, action,
                   target_type, target_id, outcome, purpose, reason, request_id, detail, occurred_at)
                VALUES ('admin', :adminId, :adminId, :email, 'publication.rule.switch',
                        'publication_rule', :ruleId, 'succeeded', 'graph_publication', :reason,
                        :requestId, jsonb_build_object(
                            'changeId', CAST(:changeId AS bigint),
                            'beforeEnabled', CAST(:beforeEnabled AS boolean),
                            'afterEnabled', CAST(:afterEnabled AS boolean),
                            'revision', CAST(:revision AS bigint),
                            'logRevision', CAST(:logRevision AS bigint)), :occurredAt)
                """, new MapSqlParameterSource("adminId", adminId)
                .addValue("email", email).addValue("ruleId", ruleId).addValue("changeId", changeId)
                .addValue("beforeEnabled", beforeEnabled).addValue("afterEnabled", afterEnabled)
                .addValue("revision", revision).addValue("logRevision", logRevision).addValue("reason", reason)
                .addValue("requestId", requestId).addValue("occurredAt", Timestamp.from(occurredAt)));
    }
}
