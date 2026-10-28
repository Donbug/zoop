package com.zoop.chat.repository;

import java.sql.Array;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcChatExecutionRepository implements ChatExecutionRepository {
    /** The fence of every write a run makes. */
    private static final String OWNED = "status = 'running' AND owner_token = :token AND lease_until > :at";
    private static final String RELEASE = "phase = NULL, owner_token = NULL, lease_until = NULL, deadline_at = NULL";
    /**
     * Closes a job's open tool calls when the job ends: a reserved call never ran ({@code cancelled}); a running one ended
     * without its result being observed ({@code unknown}, never counted as failed or as not called).
     */
    static final String CLOSE_TOOL_CALLS = """
            UPDATE chat_tool_calls SET status = CASE status WHEN 'reserved' THEN 'cancelled' ELSE 'unknown' END,
                finished_at = GREATEST(:at, started_at)
             WHERE chat_job_id = :id AND status IN ('reserved', 'running')
            """;
    /** The fence of a tool-call write: the call's job is still owned by the run. */
    private static final String TOOL_CALL_OWNED = "EXISTS (SELECT 1 FROM chat_jobs j WHERE j.id = c.chat_job_id AND "
            + "j.status = 'running' AND j.owner_token = :token AND j.lease_until > :at)";

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcChatExecutionRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<ChatJobRow> lockNextQueued() {
        return jdbc.query(JdbcChatRepository.JOB_SELECT
                        + " WHERE j.status = 'queued' ORDER BY j.updated_at, j.id LIMIT 1 FOR UPDATE OF j SKIP LOCKED",
                new MapSqlParameterSource(), JdbcChatRepository.JOB).stream().findFirst();
    }

    @Override
    public boolean start(String jobId, String ownerToken, Instant deadline, Instant leaseUntil, String attempts, Instant at) {
        return jdbc.update("""
                UPDATE chat_jobs SET status = 'running', phase = 'planning', owner_token = :token,
                    deadline_at = :deadline, lease_until = :lease, attempts = CAST(:attempts AS jsonb), updated_at = :at
                 WHERE id = :id AND status = 'queued'
                """, params(jobId, ownerToken, at).addValue("deadline", Timestamp.from(deadline))
                .addValue("lease", Timestamp.from(leaseUntil)).addValue("attempts", attempts)) == 1;
    }

    @Override
    public Optional<ChatJobRow> lockOwned(String jobId, String ownerToken, Instant at) {
        return jdbc.query(JdbcChatRepository.JOB_SELECT + " WHERE j.id = :id AND j.status = 'running' AND j.owner_token = :token"
                        + " AND j.lease_until > :at FOR UPDATE OF j", params(jobId, ownerToken, at), JdbcChatRepository.JOB).stream().findFirst();
    }

    @Override
    public Optional<ChatRunningJob> findRunning(String jobId, Instant at) {
        String select = JdbcChatRepository.JOB_SELECT.replaceFirst("SELECT ",
                "SELECT j.owner_token AS run_owner_token, j.deadline_at AS run_deadline_at, ");
        return jdbc.query(select + " WHERE j.id = :id AND j.status = 'running' AND j.lease_until > :at",
                new MapSqlParameterSource().addValue("id", jobId).addValue("at", Timestamp.from(at)),
                (rs, index) -> new ChatRunningJob(JdbcChatRepository.JOB.mapRow(rs, index),
                        rs.getString("run_owner_token"), rs.getTimestamp("run_deadline_at").toInstant()))
                .stream().findFirst();
    }

    @Override
    public boolean phase(String jobId, String ownerToken, String phase, Instant at) {
        return jdbc.update("UPDATE chat_jobs SET phase = :phase, updated_at = :at WHERE id = :id AND " + OWNED,
                params(jobId, ownerToken, at).addValue("phase", phase)) == 1;
    }

    @Override
    public void recordModelCall(String jobId, int runs, String attempts, Instant at) {
        jdbc.update("UPDATE chat_jobs SET runs = :runs, attempts = CAST(:attempts AS jsonb), updated_at = :at WHERE id = :id",
                new MapSqlParameterSource().addValue("id", jobId).addValue("runs", runs).addValue("attempts", attempts)
                        .addValue("at", Timestamp.from(at)));
    }

    @Override
    public boolean complete(String jobId, String ownerToken, Instant at, String outcome, String messageId, String result,
            String resultSchemaVersion, String routeSummary, String routeSchemaVersion, String attempts) {
        return jdbc.update("UPDATE chat_jobs SET status = 'completed', outcome = :outcome, message_id = :messageId, "
                + "result = CAST(:result AS jsonb), result_schema_version = :resultVersion, "
                + "route_summary = CAST(:route AS jsonb), route_schema_version = :routeVersion, "
                + "attempts = CAST(:attempts AS jsonb), finished_at = :at, updated_at = :at, " + RELEASE
                + " WHERE id = :id AND " + OWNED, params(jobId, ownerToken, at).addValue("outcome", outcome)
                .addValue("messageId", messageId).addValue("result", result).addValue("resultVersion", resultSchemaVersion)
                .addValue("route", routeSummary).addValue("routeVersion", routeSchemaVersion)
                .addValue("attempts", attempts)) == 1 && closeToolCalls(jobId, at);
    }

    @Override
    public boolean fail(String jobId, String ownerToken, Instant at, String failure, String attempts) {
        return jdbc.update("UPDATE chat_jobs SET status = 'failed', failure = CAST(:failure AS jsonb), "
                + "attempts = CAST(:attempts AS jsonb), finished_at = :at, updated_at = :at, " + RELEASE
                + " WHERE id = :id AND " + OWNED, params(jobId, ownerToken, at).addValue("failure", failure)
                .addValue("attempts", attempts)) == 1 && closeToolCalls(jobId, at);
    }

    @Override
    public List<String> expired(Instant at, int limit) {
        return jdbc.queryForList("""
                SELECT id FROM chat_jobs WHERE status = 'running' AND lease_until <= :at ORDER BY lease_until, id LIMIT :limit
                """, new MapSqlParameterSource().addValue("at", Timestamp.from(at)).addValue("limit", limit), String.class);
    }

    @Override
    public Optional<ChatJobRow> lockExpired(String jobId, Instant at) {
        return jdbc.query(JdbcChatRepository.JOB_SELECT
                        + " WHERE j.id = :id AND j.status = 'running' AND j.lease_until <= :at FOR UPDATE OF j",
                new MapSqlParameterSource().addValue("id", jobId).addValue("at", Timestamp.from(at)),
                JdbcChatRepository.JOB).stream().findFirst();
    }

    @Override
    public boolean failExpired(String jobId, Instant at, String failure, String attempts) {
        return jdbc.update("UPDATE chat_jobs SET status = 'failed', failure = CAST(:failure AS jsonb), "
                + "attempts = CAST(:attempts AS jsonb), finished_at = :at, updated_at = :at, " + RELEASE
                + " WHERE id = :id AND status = 'running' AND lease_until <= :at", new MapSqlParameterSource().addValue("id", jobId).addValue("at", Timestamp.from(at))
                .addValue("failure", failure).addValue("attempts", attempts)) == 1 && closeToolCalls(jobId, at);
    }

    @Override
    public void limitWait(Duration wait) {
        jdbc.queryForObject("SELECT set_config('statement_timeout', :ms, true)",
                new MapSqlParameterSource("ms", Long.toString(Math.max(1, wait.toMillis()))), String.class);
    }

    @Override
    public int countToolCalls(String jobId, int attemptNo) {
        Integer count = jdbc.queryForObject(
                "SELECT count(*) FROM chat_tool_calls WHERE chat_job_id = :id AND attempt_no = :attempt",
                new MapSqlParameterSource().addValue("id", jobId).addValue("attempt", attemptNo), Integer.class);
        return count == null ? 0 : count;
    }

    @Override
    public void reserveToolCalls(List<NewChatToolCall> calls, Instant at) {
        for (NewChatToolCall call : calls) {
            jdbc.update("""
                    INSERT INTO chat_tool_calls (id, chat_job_id, attempt_no, plan_revision, call_index, tool_call_id,
                        registry_version, registry_group, capability_id, tool_id, schema_version, input_digest, request_meta,
                        status, started_at)
                    VALUES (:id, :jobId, :attempt, :revision, :index, :toolCallId, :registryVersion, :registryGroup,
                        :capabilityId, :toolId, :schemaVersion, :inputDigest, CAST(:requestMeta AS jsonb), 'reserved', :at)
                    """, new MapSqlParameterSource().addValue("id", call.id()).addValue("jobId", call.jobId())
                    .addValue("attempt", call.attemptNo()).addValue("revision", call.planRevision())
                    .addValue("index", call.callIndex()).addValue("toolCallId", call.toolCallId())
                    .addValue("registryVersion", call.registryVersion()).addValue("registryGroup", call.registryGroup())
                    .addValue("capabilityId", call.capabilityId()).addValue("toolId", call.toolId())
                    .addValue("schemaVersion", call.schemaVersion()).addValue("inputDigest", call.inputDigest())
                    .addValue("requestMeta", call.requestMeta()).addValue("at", Timestamp.from(at)));
        }
    }

    @Override
    public Optional<String> findReservedToolCall(String jobId, int attemptNo, String capabilityId, String inputDigest) {
        return jdbc.queryForList("""
                SELECT tool_call_id FROM chat_tool_calls
                 WHERE chat_job_id = :id AND attempt_no = :attempt AND capability_id = :capability
                   AND input_digest = :digest AND status = 'reserved'
                 ORDER BY call_index LIMIT 1
                """, new MapSqlParameterSource().addValue("id", jobId).addValue("attempt", attemptNo)
                .addValue("capability", capabilityId).addValue("digest", inputDigest), String.class)
                .stream().findFirst();
    }

    @Override
    public boolean startToolCall(String jobId, String ownerToken, int attemptNo, String toolCallId, Instant at) {
        return jdbc.update("UPDATE chat_tool_calls c SET status = 'running', started_at = :at"
                + " WHERE c.chat_job_id = :id AND c.attempt_no = :attempt AND c.tool_call_id = :toolCallId"
                + " AND c.status = 'reserved' AND " + TOOL_CALL_OWNED, params(jobId, ownerToken, at)
                .addValue("attempt", attemptNo).addValue("toolCallId", toolCallId)) == 1;
    }

    @Override
    public boolean finishToolCall(String jobId, String ownerToken, int attemptNo, String toolCallId, ChatToolCallEnd end,
            Instant at) {
        Array evidenceIds = jdbc.getJdbcTemplate().execute((ConnectionCallback<Array>) connection ->
                connection.createArrayOf("text", end.evidenceIds().toArray()));
        return jdbc.update("UPDATE chat_tool_calls c SET status = :status, error_code = :error, data_version = :dataVersion,"
                + " evidence_ids = :evidenceIds, truncated = :truncated, next_allowed = :nextAllowed,"
                + " finished_at = GREATEST(:at, c.started_at)"
                + " WHERE c.chat_job_id = :id AND c.attempt_no = :attempt AND c.tool_call_id = :toolCallId"
                + " AND c.status = 'running' AND " + TOOL_CALL_OWNED, params(jobId, ownerToken, at)
                .addValue("attempt", attemptNo).addValue("toolCallId", toolCallId).addValue("status", end.status())
                .addValue("error", end.errorCode()).addValue("dataVersion", end.dataVersion())
                .addValue("evidenceIds", evidenceIds).addValue("truncated", end.truncated())
                .addValue("nextAllowed", end.nextAllowed())) == 1;
    }

    private boolean closeToolCalls(String jobId, Instant at) {
        jdbc.update(CLOSE_TOOL_CALLS, new MapSqlParameterSource().addValue("id", jobId).addValue("at", Timestamp.from(at)));
        return true;
    }

    private static MapSqlParameterSource params(String jobId, String ownerToken, Instant at) {
        return new MapSqlParameterSource().addValue("id", jobId).addValue("token", ownerToken)
                .addValue("at", Timestamp.from(at));
    }
}
