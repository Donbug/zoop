package com.zoop.admin.audit;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Optional;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * Admin POST idempotency over {@code idempotency_records}: the same key and request hash replay the stored response, another
 * hash under the same key is a conflict. The graph activation and analysis job repositories still carry their own copy of
 * these statements; new admin writes use this one.
 */
@Repository
public class JdbcAdminIdempotencyStore {
    private final NamedParameterJdbcTemplate jdbc;

    public JdbcAdminIdempotencyStore(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public record Record(String id, String requestHash, String status, Integer responseStatus, String responseBody) {
    }

    public boolean claim(String adminId, String path, String key, String requestHash, String resourceType, String resourceId,
            Instant createdAt) {
        return jdbc.update("""
                INSERT INTO idempotency_records
                  (id, principal_kind, principal_id, method, path, idem_key, request_hash,
                   status, resource_type, resource_id, owner_token, lease_until,
                   response_status, response_body, created_at, expires_at)
                VALUES (:id, 'admin', :adminId, 'POST', :path, :key, :requestHash,
                        'processing', :resourceType, :resourceId, NULL, NULL, NULL, NULL, :createdAt, NULL)
                ON CONFLICT (principal_kind, principal_id, method, path, idem_key) DO NOTHING
                """, new MapSqlParameterSource("id", java.util.UUID.randomUUID().toString()).addValue("adminId", adminId)
                .addValue("path", path).addValue("key", key).addValue("requestHash", requestHash).addValue("resourceType", resourceType)
                .addValue("resourceId", resourceId).addValue("createdAt", Timestamp.from(createdAt))) == 1;
    }

    /** {@code lock}: FOR UPDATE, waiting for a concurrent holder of the same key to commit. */
    public Optional<Record> find(String adminId, String path, String key, boolean lock) {
        return jdbc.query("""
                SELECT id, request_hash, status, response_status, response_body::text AS response_body
                FROM idempotency_records
                WHERE principal_kind = 'admin' AND principal_id = :adminId
                  AND method = 'POST' AND path = :path AND idem_key = :key
                """ + (lock ? " FOR UPDATE" : ""),
                new MapSqlParameterSource("adminId", adminId).addValue("path", path).addValue("key", key),
                JdbcAdminIdempotencyStore::record).stream().findFirst();
    }

    public Optional<Record> findById(String id) {
        return jdbc.query("""
                SELECT id, request_hash, status, response_status, response_body::text AS response_body
                FROM idempotency_records WHERE id = :id
                """, new MapSqlParameterSource("id", id), JdbcAdminIdempotencyStore::record).stream().findFirst();
    }

    public void complete(String id, int responseStatus, String responseBody) {
        int changed = jdbc.update("""
                UPDATE idempotency_records
                SET status = 'completed', response_status = :responseStatus, response_body = CAST(:responseBody AS jsonb)
                WHERE id = :id AND status = 'processing'
                """, new MapSqlParameterSource("id", id).addValue("responseStatus", responseStatus)
                .addValue("responseBody", responseBody));
        if (changed != 1) throw new IllegalStateException("Idempotency record was not completed");
    }

    private static Record record(ResultSet rs, int rowNum) throws SQLException {
        int status = rs.getInt("response_status");
        return new Record(rs.getString("id"), rs.getString("request_hash"), rs.getString("status"),
                rs.wasNull() ? null : status, rs.getString("response_body"));
    }

    /** A definite failure: the same key and request replay it instead of running again. */
    public void fail(String id, int responseStatus, String responseBody) {
        int changed = jdbc.update("""
                UPDATE idempotency_records
                SET status = 'failed', response_status = :responseStatus, response_body = CAST(:responseBody AS jsonb)
                WHERE id = :id AND status = 'processing'
                """, new MapSqlParameterSource("id", id).addValue("responseStatus", responseStatus)
                .addValue("responseBody", responseBody));
        if (changed != 1) throw new IllegalStateException("Idempotency record was not failed");
    }
}
