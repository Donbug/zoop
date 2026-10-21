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
}
