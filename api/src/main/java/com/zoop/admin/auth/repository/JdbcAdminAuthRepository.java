package com.zoop.admin.auth.repository;

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
public class JdbcAdminAuthRepository implements AdminAuthRepository {
    private final NamedParameterJdbcTemplate jdbc;

    public JdbcAdminAuthRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<AdminAccountRow> findAccountByEmailKey(String emailKey) {
        return first(jdbc.query("""
                SELECT id, email, email_key, display_name, password_hash,
                       external_subject, role, status, created_at
                FROM admins
                WHERE email_key = :emailKey
                """, new MapSqlParameterSource("emailKey", emailKey),
                JdbcAdminAuthRepository::accountRow));
    }

    @Override
    public boolean insertPasswordAccount(String id, String email, String emailKey,
            String displayName, String passwordHash, Instant createdAt) {
        int inserted = jdbc.update("""
                INSERT INTO admins
                  (id, email, email_key, display_name, password_hash, external_subject,
                   role, status, created_at)
                VALUES (:id, :email, :emailKey, :displayName, :passwordHash, NULL,
                        'admin', 'active', :createdAt)
                ON CONFLICT (email_key) DO NOTHING
                """, new MapSqlParameterSource("id", id)
                .addValue("email", email)
                .addValue("emailKey", emailKey)
                .addValue("displayName", displayName)
                .addValue("passwordHash", passwordHash)
                .addValue("createdAt", Timestamp.from(createdAt)));
        return inserted == 1;
    }

    @Override
    public Optional<AdminSessionRow> findSessionByTokenHash(String tokenHash) {
        return first(jdbc.query("""
                SELECT s.id, s.admin_id, s.token_hash, s.csrf_key_id, s.csrf_version,
                       s.created_at, s.last_seen_at, s.idle_expires_at, s.expires_at, s.revoked_at,
                       a.email, a.display_name, a.role, a.status AS admin_status
                FROM admin_sessions s
                JOIN admins a ON a.id = s.admin_id
                WHERE s.token_hash = :tokenHash
                """, new MapSqlParameterSource("tokenHash", tokenHash),
                JdbcAdminAuthRepository::sessionRow));
    }

    @Override
    public boolean insertSession(String id, String adminId, String tokenHash, String csrfKeyId,
            Instant createdAt, Instant idleExpiresAt, Instant expiresAt) {
        int inserted = jdbc.update("""
                INSERT INTO admin_sessions
                  (id, admin_id, token_hash, csrf_key_id, csrf_version, created_at,
                   last_seen_at, idle_expires_at, expires_at, revoked_at)
                SELECT :id, a.id, :tokenHash, :csrfKeyId, 1, :createdAt,
                       :createdAt, :idleExpiresAt, :expiresAt, NULL
                FROM admins a
                WHERE a.id = :adminId AND a.status = 'active' AND a.role = 'admin'
                """, sessionParameters(id, adminId, tokenHash, csrfKeyId,
                        createdAt, idleExpiresAt, expiresAt));
        return inserted == 1;
    }

    @Override
    public boolean touchSession(String id, Instant seenAt, Instant idleExpiresAt) {
        int updated = jdbc.update("""
                UPDATE admin_sessions s
                SET last_seen_at = GREATEST(last_seen_at, :seenAt),
                    idle_expires_at = LEAST(expires_at, GREATEST(idle_expires_at, :idleExpiresAt))
                FROM admins a
                WHERE s.id = :id AND a.id = s.admin_id
                  AND a.status = 'active' AND a.role = 'admin'
                  AND s.revoked_at IS NULL
                  AND s.idle_expires_at > :seenAt AND s.expires_at > :seenAt
                """, new MapSqlParameterSource("id", id)
                .addValue("seenAt", Timestamp.from(seenAt))
                .addValue("idleExpiresAt", Timestamp.from(idleExpiresAt)));
        return updated == 1;
    }

    @Override
    public boolean revokeSession(String tokenHash, String adminId, Instant revokedAt) {
        int updated = jdbc.update("""
                UPDATE admin_sessions
                SET revoked_at = :revokedAt
                WHERE token_hash = :tokenHash AND admin_id = :adminId AND revoked_at IS NULL
                """, new MapSqlParameterSource("tokenHash", tokenHash)
                .addValue("adminId", adminId)
                .addValue("revokedAt", Timestamp.from(revokedAt)));
        return updated == 1;
    }

    private static MapSqlParameterSource sessionParameters(String id, String adminId,
            String tokenHash, String csrfKeyId, Instant createdAt,
            Instant idleExpiresAt, Instant expiresAt) {
        return new MapSqlParameterSource("id", id)
                .addValue("adminId", adminId)
                .addValue("tokenHash", tokenHash)
                .addValue("csrfKeyId", csrfKeyId)
                .addValue("createdAt", Timestamp.from(createdAt))
                .addValue("idleExpiresAt", Timestamp.from(idleExpiresAt))
                .addValue("expiresAt", Timestamp.from(expiresAt));
    }

    private static AdminAccountRow accountRow(ResultSet rs, int rowNumber) throws SQLException {
        return new AdminAccountRow(rs.getString("id"), rs.getString("email"),
                rs.getString("email_key"), rs.getString("display_name"),
                rs.getString("password_hash"), rs.getString("external_subject"),
                rs.getString("role"), rs.getString("status"),
                rs.getTimestamp("created_at").toInstant());
    }

    private static AdminSessionRow sessionRow(ResultSet rs, int rowNumber) throws SQLException {
        Timestamp revokedAt = rs.getTimestamp("revoked_at");
        return new AdminSessionRow(rs.getString("id"), rs.getString("admin_id"),
                rs.getString("token_hash"), rs.getString("csrf_key_id"),
                rs.getLong("csrf_version"), rs.getTimestamp("created_at").toInstant(),
                rs.getTimestamp("last_seen_at").toInstant(),
                rs.getTimestamp("idle_expires_at").toInstant(),
                rs.getTimestamp("expires_at").toInstant(),
                revokedAt == null ? null : revokedAt.toInstant(),
                rs.getString("email"), rs.getString("display_name"),
                rs.getString("role"), rs.getString("admin_status"));
    }

    private static <T> Optional<T> first(List<T> rows) {
        return rows.stream().findFirst();
    }
}
