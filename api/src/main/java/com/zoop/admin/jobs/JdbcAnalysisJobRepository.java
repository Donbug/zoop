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
            flush::text AS flush, error::text AS error, ledger_before::text AS ledger_before, ledger_after::text AS ledger_after,
            plan_id, checkpoint::text AS checkpoint
            """;

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcAnalysisJobRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public record JobRow(String id, String kind, String scope, String label, String status, String reason, String requestedBy,
            Instant requestedAt, Instant startedAt, Instant finishedAt, String retryOf, String commandKey, String input,
            boolean cancelRequested, boolean recovered, String report, String ingest, String flush, String error,
            String ledgerBefore, String ledgerAfter, String planId, String checkpoint) {
    }

    public record IdempotencyRow(String id, String requestHash, String status, Integer responseStatus, String responseBody) {
    }

    /** One page of administrator jobs, newest request first, after the keyset ({@code ix_analysis_jobs_admin_latest}). */
    public List<JobRow> page(String status, Instant afterAt, String afterId, int limit) {
        return jdbc.query("SELECT " + COLUMNS + """
                 FROM analysis_jobs
                WHERE scope = 'admin'
                  AND (CAST(:status AS text) IS NULL OR status = :status)
                  AND (CAST(:afterAt AS timestamptz) IS NULL OR (requested_at, id) < (:afterAt, :afterId))
                ORDER BY requested_at DESC, id DESC
                LIMIT :limit
                """, new MapSqlParameterSource("status", status)
                .addValue("afterAt", afterAt == null ? null : Timestamp.from(afterAt)).addValue("afterId", afterId)
                .addValue("limit", limit), JdbcAnalysisJobRepository::row);
    }

    public Optional<JobRow> adminJob(String id) {
        return jdbc.query("SELECT " + COLUMNS + " FROM analysis_jobs WHERE id = :id AND scope = 'admin'",
                new MapSqlParameterSource("id", id), JdbcAnalysisJobRepository::row).stream().findFirst();
    }

    /** The administrator job holding the run slot, if any ({@code uq_analysis_jobs_admin_running} allows one). */
    public Optional<JobRow> running() {
        return jdbc.query("SELECT " + COLUMNS + " FROM analysis_jobs WHERE scope = 'admin' AND status = 'running'",
                JdbcAnalysisJobRepository::row).stream().findFirst();
    }

    public record DashboardCounts(long running, long queued, long failed24h) { }

    public DashboardCounts dashboardCountsAt(Instant asOf) {
        return jdbc.queryForObject("""
                SELECT count(*) FILTER (WHERE status = 'running') AS running,
                       count(*) FILTER (WHERE status = 'queued') AS queued,
                       count(*) FILTER (WHERE status = 'failed'
                           AND finished_at >= :start AND finished_at < :asOf) AS failed24h
                FROM analysis_jobs
                WHERE scope = 'admin' AND requested_at <= :asOf
                """, new MapSqlParameterSource("asOf", Timestamp.from(asOf))
                .addValue("start", Timestamp.from(asOf.minusSeconds(86_400))),
                (rs, rowNum) -> new DashboardCounts(rs.getLong("running"), rs.getLong("queued"),
                        rs.getLong("failed24h")));
    }

    public List<JobRow> dashboardRecentAt(Instant asOf, int limit) {
        return jdbc.query("SELECT " + COLUMNS + """
                 FROM analysis_jobs
                WHERE scope = 'admin' AND requested_at <= :asOf
                ORDER BY requested_at DESC, id DESC
                LIMIT :limit
                """, new MapSqlParameterSource("asOf", Timestamp.from(asOf)).addValue("limit", limit),
                JdbcAnalysisJobRepository::row);
    }

    public Optional<JobRow> dashboardRunningAt(Instant asOf) {
        return jdbc.query("SELECT " + COLUMNS + """
                 FROM analysis_jobs
                WHERE scope = 'admin' AND status = 'running' AND requested_at <= :asOf
                """, new MapSqlParameterSource("asOf", Timestamp.from(asOf)),
                JdbcAnalysisJobRepository::row).stream().findFirst();
    }

    /** The newest administrator ingest that finished normally: the next run's baseline. */
    public Optional<JobRow> latestSucceededIngest() {
        return jdbc.query("SELECT " + COLUMNS + """
                 FROM analysis_jobs
                WHERE scope = 'admin' AND kind = 'ingest' AND status = 'succeeded'
                ORDER BY finished_at DESC, id DESC
                LIMIT 1
                """, JdbcAnalysisJobRepository::row).stream().findFirst();
    }

    /**
     * What the retry judgement of {@code jobs} needs, and nothing more: their retries ({@code retry_of}) and, for the failed or
     * cancelled ones, succeeded jobs of the same kind and input ({@code ix_analysis_jobs_admin_succeeded_input}).
     */
    public List<JobRow> retryContext(List<JobRow> jobs) {
        if (jobs.isEmpty()) return List.of();
        List<JobRow> settled = jobs.stream().filter(j -> "failed".equals(j.status()) || "cancelled".equals(j.status()))
                .toList();
        return jdbc.query("SELECT " + COLUMNS + """
                 FROM analysis_jobs
                WHERE scope = 'admin'
                  AND (retry_of IN (:ids)
                       OR (status = 'succeeded' AND (kind, md5(input::text)) IN (
                           SELECT k, md5(i::text) FROM unnest(CAST(:kinds AS text[]), CAST(:inputs AS jsonb[])) AS t(k, i))))
                """, new MapSqlParameterSource("ids", jobs.stream().map(JobRow::id).toList())
                .addValue("kinds", settled.stream().map(JobRow::kind).toArray(String[]::new))
                .addValue("inputs", settled.stream().map(JobRow::input).toArray(String[]::new)),
                JdbcAnalysisJobRepository::row);
    }

    /** Locks one administrator job; an internal projection job is not an admin resource and reads as absent. */
    public Optional<JobRow> lockAdmin(String id) {
        return jdbc.query("SELECT " + COLUMNS + " FROM analysis_jobs WHERE id = :id AND scope = 'admin' FOR UPDATE",
                new MapSqlParameterSource("id", id), JdbcAnalysisJobRepository::row).stream().findFirst();
    }

    public void insertQueued(String id, String kind, String label, String reason, String requestedBy, Instant requestedAt,
            String retryOf, String commandKey, String input, String planId) {
        jdbc.update("""
                INSERT INTO analysis_jobs
                  (id, kind, scope, label, status, reason, requested_by, requested_at, retry_of, command_key, input, plan_id,
                   checkpoint)
                VALUES (:id, :kind, 'admin', :label, 'queued', :reason, :requestedBy, :requestedAt, :retryOf, :commandKey,
                        CAST(:input AS jsonb), :planId, CASE WHEN :kind = 'analyze_plan' THEN
                        '{"schemaVersion":"zoop-app-analyze-plan-checkpoint-1","phase":"awaiting_admission","activeOrdinal":null,"terminalSummary":null,"lastFailureCategory":null}'::jsonb ELSE NULL END)
                """, new MapSqlParameterSource("id", id).addValue("kind", kind).addValue("label", label)
                .addValue("reason", reason).addValue("requestedBy", requestedBy)
                .addValue("requestedAt", Timestamp.from(requestedAt)).addValue("retryOf", retryOf)
                .addValue("commandKey", commandKey).addValue("input", input).addValue("planId", planId));
    }

    public Optional<JobRow> rootForCommand(String commandKey) {
        return jdbc.query("SELECT " + COLUMNS + " FROM analysis_jobs WHERE scope = 'admin' AND command_key = :key",
                new MapSqlParameterSource("key", commandKey), JdbcAnalysisJobRepository::row).stream().findFirst();
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
                rs.getString("ledger_after"), rs.getString("plan_id"), rs.getString("checkpoint"));
    }

    private static Instant instant(ResultSet rs, String column) throws SQLException {
        Timestamp value = rs.getTimestamp(column);
        return value == null ? null : value.toInstant();
    }
}
