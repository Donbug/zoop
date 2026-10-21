package com.zoop.auth.repository;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.Optional;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

@Repository
public class JdbcMemberSessionRepository implements MemberSessionRepository {
    private final NamedParameterJdbcTemplate jdbc;

    public JdbcMemberSessionRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<MemberSessionRow> findByTokenHash(String tokenHash) {
        var rows = jdbc.query("""
                SELECT s.id, s.member_id, s.kind, s.token_hash, s.csrf_key_id,
                       s.csrf_version, s.created_at, s.expires_at, s.revoked_at,
                       m.status AS member_status, m.email, m.display_name,
                       m.completed, m.tutorial_completed, COALESCE(m.analytics_key, s.analytics_key) AS analytics_key
                FROM member_sessions s
                LEFT JOIN members m ON m.id = s.member_id
                WHERE s.token_hash = :tokenHash
                """, new MapSqlParameterSource("tokenHash", tokenHash), (rs, index) ->
                new MemberSessionRow(rs.getString("id"), rs.getString("member_id"),
                        rs.getString("kind"), rs.getString("token_hash"),
                        rs.getString("csrf_key_id"), rs.getLong("csrf_version"),
                        rs.getTimestamp("created_at").toInstant(),
                        rs.getTimestamp("expires_at").toInstant(),
                        rs.getTimestamp("revoked_at") == null ? null : rs.getTimestamp("revoked_at").toInstant(),
                        rs.getString("member_status"), rs.getString("email"),
                        rs.getString("display_name"), rs.getBoolean("completed"),
                        rs.getBoolean("tutorial_completed"), rs.getString("analytics_key")));
        return rows.stream().findFirst();
    }

    @Override
    @Transactional
    public boolean insertMemberSession(String id, String memberId, String tokenHash,
            String csrfKeyId, Instant createdAt, Instant expiresAt) {
        var memberStatus = jdbc.query("""
                SELECT status FROM members WHERE id = :memberId FOR UPDATE
                """, new MapSqlParameterSource("memberId", memberId),
                (rs, rowNum) -> rs.getString("status")).stream().findFirst();
        if (memberStatus.isEmpty() || !"active".equals(memberStatus.get())) return false;

        return jdbc.update("""
                INSERT INTO member_sessions
                  (id, member_id, kind, analytics_key, token_hash, csrf_key_id,
                   csrf_version, tutorial_completed, auth_flow, created_at, expires_at, revoked_at)
                VALUES (:id, :memberId, 'member', NULL, :tokenHash, :csrfKeyId,
                        1, false, NULL, :createdAt, :expiresAt, NULL)
                """, new MapSqlParameterSource()
                .addValue("id", id).addValue("memberId", memberId)
                .addValue("tokenHash", tokenHash).addValue("csrfKeyId", csrfKeyId)
                .addValue("createdAt", Timestamp.from(createdAt))
                .addValue("expiresAt", Timestamp.from(expiresAt))) == 1;
    }

    @Override
    public void insertGuestSession(String id, String analyticsKey, String tokenHash,
            String csrfKeyId, Instant createdAt, Instant expiresAt) {
        jdbc.update("""
                INSERT INTO member_sessions
                  (id, member_id, kind, analytics_key, token_hash, csrf_key_id,
                   csrf_version, tutorial_completed, auth_flow, created_at, expires_at, revoked_at)
                VALUES (:id, NULL, 'guest', :analyticsKey, :tokenHash, :csrfKeyId,
                        1, false, NULL, :createdAt, :expiresAt, NULL)
                """, new MapSqlParameterSource()
                .addValue("id", id).addValue("analyticsKey", analyticsKey)
                .addValue("tokenHash", tokenHash).addValue("csrfKeyId", csrfKeyId)
                .addValue("createdAt", Timestamp.from(createdAt))
                .addValue("expiresAt", Timestamp.from(expiresAt)));
    }

    @Override
    public void revokeMemberSession(String tokenHash, String memberId, Instant at) {
        jdbc.update("""
                UPDATE member_sessions SET revoked_at = :at
                WHERE token_hash = :tokenHash AND member_id = :memberId
                  AND kind = 'member' AND revoked_at IS NULL AND expires_at > :at
                """, new MapSqlParameterSource()
                .addValue("at", Timestamp.from(at))
                .addValue("tokenHash", tokenHash).addValue("memberId", memberId));
    }

    @Override
    public void revokeGuestSession(String tokenHash, Instant at) {
        jdbc.update("""
                UPDATE member_sessions SET revoked_at = :at
                WHERE token_hash = :tokenHash AND kind = 'guest'
                  AND revoked_at IS NULL AND expires_at > :at
                """, new MapSqlParameterSource()
                .addValue("at", Timestamp.from(at)).addValue("tokenHash", tokenHash));
    }
}
