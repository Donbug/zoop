package com.zoop.chat.repository;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcChatExecutionRepository implements ChatExecutionRepository {
    /** The fence of every write a run makes. */
    private static final String OWNED = "status = 'running' AND owner_token = :token AND lease_until > :at";
    private static final String RELEASE = "phase = NULL, owner_token = NULL, lease_until = NULL, deadline_at = NULL";

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
                .addValue("attempts", attempts)) == 1;
    }

    @Override
    public boolean fail(String jobId, String ownerToken, Instant at, String failure, String attempts) {
        return jdbc.update("UPDATE chat_jobs SET status = 'failed', failure = CAST(:failure AS jsonb), "
                + "attempts = CAST(:attempts AS jsonb), finished_at = :at, updated_at = :at, " + RELEASE
                + " WHERE id = :id AND " + OWNED, params(jobId, ownerToken, at).addValue("failure", failure)
                .addValue("attempts", attempts)) == 1;
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
                .addValue("failure", failure).addValue("attempts", attempts)) == 1;
    }

    private static MapSqlParameterSource params(String jobId, String ownerToken, Instant at) {
        return new MapSqlParameterSource().addValue("id", jobId).addValue("token", ownerToken)
                .addValue("at", Timestamp.from(at));
    }
}
