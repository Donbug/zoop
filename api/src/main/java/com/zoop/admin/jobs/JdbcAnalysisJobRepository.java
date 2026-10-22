package com.zoop.admin.jobs;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/** {@code analysis_jobs} and the admin job API's own idempotency records. Only {@code scope='admin'} rows are read here. */
@Repository
public class JdbcAnalysisJobRepository {
    private static final String COLUMNS = """
            id, kind, scope, label, status, reason, requested_by, requested_at, started_at, finished_at, retry_of,
            command_key, input::text AS input, cancel_requested, recovered, report::text AS report, ingest::text AS ingest,
            flush::text AS flush, error::text AS error, ledger_before::text AS ledger_before, ledger_after::text AS ledger_after
            """;

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcAnalysisJobRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public record JobRow(String id, String kind, String scope, String label, String status, String reason, String requestedBy,
            Instant requestedAt, Instant startedAt, Instant finishedAt, String retryOf, String commandKey, String input,
            boolean cancelRequested, boolean recovered, String report, String ingest, String flush, String error,
            String ledgerBefore, String ledgerAfter) {
    }

    public record IdempotencyRow(String id, String requestHash, String status, Integer responseStatus, String responseBody) {
    }

    /**
     * Every administrator job, newest request first. The retry judgement of one job looks at the others (its retries, a later
     * success on the same input), so the service reads them together.
     * shortcut: the whole admin set per request; move to per-job queries (retry_of, same input) once the table is large.
     */
    public List<JobRow> adminJobs() {
        return jdbc.query("SELECT " + COLUMNS + " FROM analysis_jobs WHERE scope = 'admin' ORDER BY requested_at DESC, id DESC",
                JdbcAnalysisJobRepository::row);
    }

    /** Locks one administrator job; an internal projection job is not an admin resource and reads as absent. */
    public Optional<JobRow> lockAdmin(String id) {
        return jdbc.query("SELECT " + COLUMNS + " FROM analysis_jobs WHERE id = :id AND scope = 'admin' FOR UPDATE",
                new MapSqlParameterSource("id", id), JdbcAnalysisJobRepository::row).stream().findFirst();
    }

    public void insertQueued(String id, String kind, String label, String reason, String requestedBy, Instant requestedAt,
            String retryOf, String commandKey, String input) {
        jdbc.update("""
                INSERT INTO analysis_jobs
                  (id, kind, scope, label, status, reason, requested_by, requested_at, retry_of, command_key, input)
                VALUES (:id, :kind, 'admin', :label, 'queued', :reason, :requestedBy, :requestedAt, :retryOf, :commandKey,
                        CAST(:input AS jsonb))
                """, new MapSqlParameterSource("id", id).addValue("kind", kind).addValue("label", label)
                .addValue("reason", reason).addValue("requestedBy", requestedBy)
                .addValue("requestedAt", Timestamp.from(requestedAt)).addValue("retryOf", retryOf)
                .addValue("commandKey", commandKey).addValue("input", input));
    }

    /** A queued job never ran: it ends cancelled at once. */
    public void cancelQueued(String id, Instant at) {
        int changed = jdbc.update("""
                UPDATE analysis_jobs SET status = 'cancelled', cancel_requested = true, finished_at = :at
                WHERE id = :id AND scope = 'admin' AND status = 'queued'
                """, new MapSqlParameterSource("id", id).addValue("at", Timestamp.from(at)));
        if (changed != 1) throw new IllegalStateException("Queued job was not cancelled");
    }

    /** A running job is asked to stop; the worker that owns it ends it (an in-flight AI child is not killed). */
    public void requestCancel(String id) {
        int changed = jdbc.update("""
                UPDATE analysis_jobs SET cancel_requested = true
                WHERE id = :id AND scope = 'admin' AND status = 'running'
                """, new MapSqlParameterSource("id", id));
        if (changed != 1) throw new IllegalStateException("Running job cancel was not recorded");
    }

    public boolean claimIdempotency(String id, String adminId, String path, String key, String jobId, String requestHash,
            Instant createdAt) {
        return jdbc.update("""
                INSERT INTO idempotency_records
                  (id, principal_kind, principal_id, method, path, idem_key, request_hash,
                   status, resource_type, resource_id, owner_token, lease_until,
                   response_status, response_body, created_at, expires_at)
                VALUES (:id, 'admin', :adminId, 'POST', :path, :key, :requestHash,
                        'processing', 'analysis_job', :jobId, NULL, NULL, NULL, NULL, :createdAt, NULL)
                ON CONFLICT (principal_kind, principal_id, method, path, idem_key) DO NOTHING
                """, new MapSqlParameterSource("id", id).addValue("adminId", adminId).addValue("path", path)
                .addValue("key", key).addValue("jobId", jobId).addValue("requestHash", requestHash)
                .addValue("createdAt", Timestamp.from(createdAt))) == 1;
    }

    public Optional<IdempotencyRow> findIdempotencyForUpdate(String adminId, String path, String key) {
        return jdbc.query("""
                SELECT id, request_hash, status, response_status, response_body::text AS response_body
                FROM idempotency_records
                WHERE principal_kind = 'admin' AND principal_id = :adminId
                  AND method = 'POST' AND path = :path AND idem_key = :key
                FOR UPDATE
                """, new MapSqlParameterSource("adminId", adminId).addValue("path", path).addValue("key", key),
                (rs, rowNum) -> {
                    int status = rs.getInt("response_status");
                    return new IdempotencyRow(rs.getString("id"), rs.getString("request_hash"), rs.getString("status"),
                            rs.wasNull() ? null : status, rs.getString("response_body"));
                }).stream().findFirst();
    }

    public void completeIdempotency(String id, int responseStatus, String responseBody) {
        int changed = jdbc.update("""
                UPDATE idempotency_records
                SET status = 'completed', response_status = :responseStatus, response_body = CAST(:responseBody AS jsonb)
                WHERE id = :id AND status = 'processing'
                """, new MapSqlParameterSource("id", id).addValue("responseStatus", responseStatus)
                .addValue("responseBody", responseBody));
        if (changed != 1) throw new IllegalStateException("Idempotency record was not completed");
    }

    private static JobRow row(ResultSet rs, int rowNumber) throws SQLException {
        return new JobRow(rs.getString("id"), rs.getString("kind"), rs.getString("scope"), rs.getString("label"),
                rs.getString("status"), rs.getString("reason"), rs.getString("requested_by"), instant(rs, "requested_at"),
                instant(rs, "started_at"), instant(rs, "finished_at"), rs.getString("retry_of"), rs.getString("command_key"),
                rs.getString("input"), rs.getBoolean("cancel_requested"), rs.getBoolean("recovered"), rs.getString("report"),
                rs.getString("ingest"), rs.getString("flush"), rs.getString("error"), rs.getString("ledger_before"),
                rs.getString("ledger_after"));
    }

    private static Instant instant(ResultSet rs, String column) throws SQLException {
        Timestamp value = rs.getTimestamp(column);
        return value == null ? null : value.toInstant();
    }
}
