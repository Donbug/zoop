package com.zoop.auth.repository;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.Optional;
import java.util.regex.Pattern;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcOAuthPendingRepository implements OAuthPendingRepository {
    private static final Pattern SHA256 = Pattern.compile("[0-9a-f]{64}");
    private static final String RESERVED_CSRF_KEY = "reserved";

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcOAuthPendingRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public void insert(String id, String cookieTokenHash, String authFlowJson,
            Instant createdAt, Instant expiresAt) {
        requireHash(cookieTokenHash);
        requireLifetime(createdAt, expiresAt);
        jdbc.update("""
                INSERT INTO member_sessions
                  (id, member_id, kind, analytics_key, token_hash, csrf_key_id,
                   csrf_version, tutorial_completed, auth_flow, created_at, expires_at, revoked_at)
                VALUES (:id, NULL, 'oauth_pending', NULL, :tokenHash, :csrfKeyId,
                        1, false, CAST(:authFlow AS jsonb), :createdAt, :expiresAt, NULL)
                """, new MapSqlParameterSource()
                .addValue("id", id)
                .addValue("tokenHash", cookieTokenHash)
                .addValue("csrfKeyId", RESERVED_CSRF_KEY)
                .addValue("authFlow", authFlowJson)
                .addValue("createdAt", Timestamp.from(createdAt))
                .addValue("expiresAt", Timestamp.from(expiresAt)));
    }

    @Override
    public Optional<OAuthPendingRow> claimAuthorization(String cookieTokenHash, String stateHash,
            String provider, Instant now) {
        requireHash(cookieTokenHash);
        requireHash(stateHash);
        requireProvider(provider);
        return returning("""
                UPDATE member_sessions
                SET auth_flow = jsonb_set(auth_flow, '{phase}', to_jsonb('callback_processing'::text))
                WHERE token_hash = :tokenHash AND kind = 'oauth_pending'
                  AND revoked_at IS NULL AND expires_at > :now
                  AND auth_flow->>'phase' = 'authorization_pending'
                  AND auth_flow->>'provider' = :provider
                  AND auth_flow->>'stateHash' = :stateHash
                RETURNING id, token_hash, auth_flow::text AS auth_flow, created_at, expires_at
                """, new MapSqlParameterSource()
                .addValue("tokenHash", cookieTokenHash)
                .addValue("stateHash", stateHash)
                .addValue("provider", provider)
                .addValue("now", Timestamp.from(now)));
    }

    @Override
    public Optional<OAuthPendingRow> completeVerification(String id, String cookieTokenHash,
            String authFlowJson, Instant now) {
        requireHash(cookieTokenHash);
        return returning("""
                UPDATE member_sessions
                SET auth_flow = CAST(:authFlow AS jsonb)
                WHERE id = :id AND token_hash = :tokenHash AND kind = 'oauth_pending'
                  AND revoked_at IS NULL AND expires_at > :now
                  AND auth_flow->>'phase' = 'callback_processing'
                  AND CAST(:authFlow AS jsonb)->>'schemaVersion' = auth_flow->>'schemaVersion'
                  AND CAST(:authFlow AS jsonb)->>'provider' = auth_flow->>'provider'
                  AND CAST(:authFlow AS jsonb)->>'stateHash' = auth_flow->>'stateHash'
                  AND CAST(:authFlow AS jsonb)->>'phase' = 'identity_verified'
                RETURNING id, token_hash, auth_flow::text AS auth_flow, created_at, expires_at
                """, new MapSqlParameterSource()
                .addValue("id", id)
                .addValue("tokenHash", cookieTokenHash)
                .addValue("authFlow", authFlowJson)
                .addValue("now", Timestamp.from(now)));
    }

    @Override
    public Optional<OAuthPendingRow> rotateToConsent(String id, String previousTokenHash,
            String nextTokenHash, String authFlowJson, Instant now, Instant expiresAt) {
        requireHash(previousTokenHash);
        requireHash(nextTokenHash);
        requireLifetime(now, expiresAt);
        return returning("""
                UPDATE member_sessions
                SET token_hash = :nextTokenHash,
                    auth_flow = CAST(:authFlow AS jsonb),
                    expires_at = :expiresAt
                WHERE id = :id AND token_hash = :previousTokenHash AND kind = 'oauth_pending'
                  AND revoked_at IS NULL AND expires_at > :now
                  AND auth_flow->>'phase' = 'identity_verified'
                  AND CAST(:authFlow AS jsonb)->>'schemaVersion' = auth_flow->>'schemaVersion'
                  AND CAST(:authFlow AS jsonb)->>'provider' = auth_flow->>'provider'
                  AND CAST(:authFlow AS jsonb)->>'stateHash' = auth_flow->>'stateHash'
                  AND CAST(:authFlow AS jsonb)->>'phase' = 'consent_pending'
                RETURNING id, token_hash, auth_flow::text AS auth_flow, created_at, expires_at
                """, new MapSqlParameterSource()
                .addValue("id", id)
                .addValue("previousTokenHash", previousTokenHash)
                .addValue("nextTokenHash", nextTokenHash)
                .addValue("authFlow", authFlowJson)
                .addValue("now", Timestamp.from(now))
                .addValue("expiresAt", Timestamp.from(expiresAt)));
    }

    @Override
    public Optional<OAuthPendingRow> consumeConsent(String cookieTokenHash, Instant now) {
        requireHash(cookieTokenHash);
        return returning("""
                DELETE FROM member_sessions
                WHERE token_hash = :tokenHash AND kind = 'oauth_pending'
                  AND revoked_at IS NULL AND expires_at > :now
                  AND auth_flow->>'phase' = 'consent_pending'
                RETURNING id, token_hash, auth_flow::text AS auth_flow, created_at, expires_at
                """, new MapSqlParameterSource()
                .addValue("tokenHash", cookieTokenHash)
                .addValue("now", Timestamp.from(now)));
    }

    @Override
    public Optional<OAuthPendingRow> consumeIdentityVerified(String id, String cookieTokenHash, Instant now) {
        requireHash(cookieTokenHash);
        return returning("""
                DELETE FROM member_sessions
                WHERE id = :id AND token_hash = :tokenHash AND kind = 'oauth_pending'
                  AND revoked_at IS NULL AND expires_at > :now
                  AND auth_flow->>'phase' = 'identity_verified'
                RETURNING id, token_hash, auth_flow::text AS auth_flow, created_at, expires_at
                """, new MapSqlParameterSource().addValue("id", id).addValue("tokenHash", cookieTokenHash)
                .addValue("now", Timestamp.from(now)));
    }

    @Override
    public boolean consumeClaimedCallback(String id, String cookieTokenHash, Instant now) {
        requireHash(cookieTokenHash);
        int changed = jdbc.update("""
                DELETE FROM member_sessions
                WHERE id = :id AND token_hash = :tokenHash AND kind = 'oauth_pending'
                  AND revoked_at IS NULL AND expires_at > :now
                  AND auth_flow->>'phase' = 'callback_processing'
                """, new MapSqlParameterSource()
                .addValue("id", id)
                .addValue("tokenHash", cookieTokenHash)
                .addValue("now", Timestamp.from(now)));
        return changed == 1;
    }

    @Override
    public void deleteByTokenHash(String cookieTokenHash) {
        requireHash(cookieTokenHash);
        jdbc.update("DELETE FROM member_sessions WHERE token_hash = :tokenHash AND kind = 'oauth_pending'",
                new MapSqlParameterSource("tokenHash", cookieTokenHash));
    }

    @Override
    public int purgeExpired(Instant before) {
        return jdbc.update("""
                DELETE FROM member_sessions
                WHERE kind = 'oauth_pending' AND expires_at <= :before
                """, new MapSqlParameterSource("before", Timestamp.from(before)));
    }

    private Optional<OAuthPendingRow> returning(String sql, MapSqlParameterSource parameters) {
        var rows = jdbc.query(sql, parameters, (rs, index) -> new OAuthPendingRow(
                rs.getString("id"), rs.getString("token_hash"), rs.getString("auth_flow"),
                rs.getTimestamp("created_at").toInstant(), rs.getTimestamp("expires_at").toInstant()));
        return rows.stream().findFirst();
    }

    private static void requireHash(String value) {
        if (value == null || !SHA256.matcher(value).matches()) {
            throw new IllegalArgumentException("OAuth pending hashes must be lowercase SHA-256 hex");
        }
    }

    private static void requireProvider(String value) {
        if (!"google".equals(value) && !"kakao".equals(value)) {
            throw new IllegalArgumentException("Unsupported social provider");
        }
    }

    private static void requireLifetime(Instant createdAt, Instant expiresAt) {
        if (createdAt == null || expiresAt == null || !expiresAt.isAfter(createdAt)) {
            throw new IllegalArgumentException("OAuth pending expiry must follow its creation time");
        }
    }
}
