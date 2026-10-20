package com.zoop.admin.members.repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcAdminMemberRepository implements AdminMemberRepository {
    private final NamedParameterJdbcTemplate jdbc;

    public JdbcAdminMemberRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public List<MemberSummary> list(String status, String queryId, String queryEmailKey, Instant asOf,
            Instant afterCreatedAt, String afterId, int limit) {
        return jdbc.query("""
                SELECT m.id, m.email, m.signup_method, m.created_at, m.status, m.status_revision,
                       (SELECT count(*) FROM member_sessions s
                        WHERE s.member_id = m.id AND s.kind = 'member' AND s.created_at < :asOf) AS sessions,
                       (SELECT max(s.created_at) FROM member_sessions s
                        WHERE s.member_id = m.id AND s.kind = 'member' AND s.created_at < :asOf) AS last_active_at
                FROM members m
                WHERE m.created_at < :asOf
                  AND (CAST(:status AS text) IS NULL OR m.status = CAST(:status AS text))
                  AND (CAST(:queryId AS text) IS NULL OR m.id = CAST(:queryId AS text)
                       OR m.email_key = CAST(:queryEmailKey AS text))
                  AND (CAST(:afterCreatedAt AS timestamptz) IS NULL
                       OR m.created_at < CAST(:afterCreatedAt AS timestamptz)
                       OR (m.created_at = CAST(:afterCreatedAt AS timestamptz)
                           AND m.id < CAST(:afterId AS text)))
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT :limit
                """, new MapSqlParameterSource()
                .addValue("status", status)
                .addValue("queryId", queryId)
                .addValue("queryEmailKey", queryEmailKey)
                .addValue("asOf", Timestamp.from(asOf))
                .addValue("afterCreatedAt", afterCreatedAt == null ? null : Timestamp.from(afterCreatedAt))
                .addValue("afterId", afterId)
                .addValue("limit", limit), (rs, rowNum) -> summary(rs));
    }

    @Override
    public MemberCounts countsAt(Instant asOf) {
        return jdbc.queryForObject("""
                SELECT count(*) AS all_count,
                       count(*) FILTER (WHERE status = 'active') AS active_count,
                       count(*) FILTER (WHERE status = 'blocked') AS blocked_count
                FROM members WHERE created_at < :asOf
                """, new MapSqlParameterSource("asOf", Timestamp.from(asOf)), (rs, rowNum) ->
                new MemberCounts(rs.getLong("all_count"), rs.getLong("active_count"),
                        rs.getLong("blocked_count")));
    }

    @Override
    public Optional<MemberDetailData> findDetail(String memberId, Instant asOf) {
        var rows = jdbc.query("""
                SELECT m.id, m.email, m.signup_method, m.created_at, m.status, m.status_revision,
                       m.completed, m.tutorial_completed,
                       (SELECT count(*) FROM member_sessions s
                        WHERE s.member_id = m.id AND s.kind = 'member' AND s.created_at < :asOf) AS sessions,
                       (SELECT max(s.created_at) FROM member_sessions s
                        WHERE s.member_id = m.id AND s.kind = 'member' AND s.created_at < :asOf) AS last_active_at,
                       (SELECT count(*) FROM member_watchlist w WHERE w.member_id = m.id) AS watchlist_count,
                       EXISTS (SELECT 1 FROM member_portfolio_connections p WHERE p.member_id = m.id)
                           AS account_connected
                FROM members m
                WHERE m.id = :memberId AND m.created_at < :asOf
                """, new MapSqlParameterSource("memberId", memberId)
                .addValue("asOf", Timestamp.from(asOf)), (rs, rowNum) -> new MemberDetailData(
                        summary(rs), rs.getBoolean("completed"), rs.getBoolean("tutorial_completed"),
                        rs.getLong("watchlist_count"), rs.getBoolean("account_connected")));
        return rows.stream().findFirst();
    }

    @Override
    public List<MemberActionData> history(String memberId) {
        return jdbc.query("""
                SELECT occurred_at, action, reason, actor_email_snapshot
                FROM audit_logs
                WHERE target_type = 'member' AND target_id = :memberId
                  AND action IN ('member.block', 'member.unblock') AND outcome = 'succeeded'
                ORDER BY occurred_at DESC, id DESC
                """, new MapSqlParameterSource("memberId", memberId), (rs, rowNum) ->
                new MemberActionData(rs.getTimestamp("occurred_at").toInstant(), rs.getString("action"),
                        rs.getString("reason"), rs.getString("actor_email_snapshot")));
    }

    @Override
    public Optional<MemberStatusRow> findStatusForUpdate(String memberId) {
        return jdbc.query("""
                SELECT id, status, status_revision FROM members WHERE id = :memberId FOR UPDATE
                """, new MapSqlParameterSource("memberId", memberId), (rs, rowNum) ->
                new MemberStatusRow(rs.getString("id"), rs.getString("status"),
                        rs.getLong("status_revision"))).stream().findFirst();
    }

    @Override
    public boolean updateStatus(String memberId, long expectedRevision, String targetStatus,
            Instant blockedAt, Instant now) {
        return jdbc.update("""
                UPDATE members
                SET status = :targetStatus, blocked_at = :blockedAt,
                    status_revision = status_revision + 1, updated_at = :now
                WHERE id = :memberId AND status_revision = :expectedRevision
                """, new MapSqlParameterSource("targetStatus", targetStatus)
                .addValue("blockedAt", blockedAt == null ? null : Timestamp.from(blockedAt))
                .addValue("now", Timestamp.from(now))
                .addValue("memberId", memberId)
                .addValue("expectedRevision", expectedRevision)) == 1;
    }

    @Override
    public int revokeActiveSessions(String memberId, Instant now) {
        return jdbc.update("""
                UPDATE member_sessions SET revoked_at = :now
                WHERE member_id = :memberId AND kind = 'member'
                  AND revoked_at IS NULL AND expires_at > :now
                """, new MapSqlParameterSource("memberId", memberId)
                .addValue("now", Timestamp.from(now)));
    }

    @Override
    public boolean claimIdempotency(String id, String adminId, String path, String key,
            String requestHash, Instant createdAt) {
        return jdbc.update("""
                INSERT INTO idempotency_records
                  (id, principal_kind, principal_id, method, path, idem_key, request_hash,
                   status, resource_type, resource_id, owner_token, lease_until,
                   response_status, response_body, created_at, expires_at)
                VALUES (:id, 'admin', :adminId, 'POST', :path, :key, :requestHash,
                        'processing', 'member', NULL, NULL, NULL, NULL, NULL, :createdAt, NULL)
                ON CONFLICT (principal_kind, principal_id, method, path, idem_key) DO NOTHING
                """, new MapSqlParameterSource("id", id).addValue("adminId", adminId)
                .addValue("path", path).addValue("key", key).addValue("requestHash", requestHash)
                .addValue("createdAt", Timestamp.from(createdAt))) == 1;
    }

    @Override
    public Optional<IdempotencyRow> findIdempotencyForUpdate(String adminId, String path, String key) {
        return jdbc.query("""
                SELECT id, request_hash, status, response_status, response_body::text AS response_body
                FROM idempotency_records
                WHERE principal_kind = 'admin' AND principal_id = :adminId
                  AND method = 'POST' AND path = :path AND idem_key = :key
                FOR UPDATE
                """, new MapSqlParameterSource("adminId", adminId).addValue("path", path).addValue("key", key),
                (rs, rowNum) -> new IdempotencyRow(rs.getString("id"), rs.getString("request_hash"),
                        rs.getString("status"), nullableInt(rs, "response_status"),
                        rs.getString("response_body"))).stream().findFirst();
    }

    @Override
    public void completeIdempotency(String id, int responseStatus, String responseBody) {
        int changed = jdbc.update("""
                UPDATE idempotency_records
                SET status = 'completed', response_status = :responseStatus,
                    response_body = CAST(:responseBody AS jsonb)
                WHERE id = :id AND status = 'processing'
                """, new MapSqlParameterSource("id", id).addValue("responseStatus", responseStatus)
                .addValue("responseBody", responseBody));
        if (changed != 1) throw new IllegalStateException("Idempotency record was not completed");
    }

    private static MemberSummary summary(ResultSet rs) throws SQLException {
        Timestamp lastActive = rs.getTimestamp("last_active_at");
        return new MemberSummary(rs.getString("id"), rs.getString("email"),
                rs.getString("signup_method"), rs.getTimestamp("created_at").toInstant(),
                lastActive == null ? null : lastActive.toInstant(), rs.getString("status"),
                rs.getLong("status_revision"), rs.getLong("sessions"));
    }

    private static Integer nullableInt(ResultSet rs, String column) throws SQLException {
        int value = rs.getInt(column);
        return rs.wasNull() ? null : value;
    }
}
