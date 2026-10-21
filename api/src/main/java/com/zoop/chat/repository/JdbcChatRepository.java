package com.zoop.chat.repository;

import java.sql.Array;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;

import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcChatRepository implements ChatRepository {
    private static final String SESSION_COLUMNS = "id, member_id, created_at, updated_at";
    static final String JOB_SELECT = """
            SELECT j.id, j.session_id, s.member_id, j.seq, j.question, j.request_hash, j.asked_at,
                   j.frozen_context::text AS frozen_context, j.frozen_selection::text AS frozen_selection,
                   j.context_company_ids, j.graph_version_id, j.status, j.phase,
                   j.outcome, j.resolves_job_id, j.resolves_choice_id, j.clarification_depth, j.result::text AS result,
                   j.failure::text AS failure, j.runs, j.attempts::text AS attempts, j.created_at, j.updated_at,
                   j.finished_at
              FROM chat_jobs j JOIN chat_sessions s ON s.id = j.session_id
            """;

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcChatRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<ChatSessionRow> findSession(String sessionId) {
        return jdbc.query("SELECT " + SESSION_COLUMNS + " FROM chat_sessions WHERE id = :id",
                new MapSqlParameterSource("id", sessionId), SESSION).stream().findFirst();
    }

    @Override
    public Optional<ChatSessionRow> lockSession(String sessionId) {
        return jdbc.query("SELECT " + SESSION_COLUMNS + " FROM chat_sessions WHERE id = :id FOR UPDATE",
                new MapSqlParameterSource("id", sessionId), SESSION).stream().findFirst();
    }

    @Override
    public boolean insertSession(ChatSessionRow session) {
        return jdbc.update("""
                INSERT INTO chat_sessions (id, member_id, created_at, updated_at)
                VALUES (:id, :memberId, :createdAt, :updatedAt)
                ON CONFLICT (id) DO NOTHING
                """, new MapSqlParameterSource().addValue("id", session.id()).addValue("memberId", session.memberId())
                .addValue("createdAt", Timestamp.from(session.createdAt()))
                .addValue("updatedAt", Timestamp.from(session.updatedAt()))) == 1;
    }

    @Override
    public void touchSession(String sessionId, Instant at) {
        jdbc.update("UPDATE chat_sessions SET updated_at = GREATEST(updated_at, :at) WHERE id = :id",
                new MapSqlParameterSource().addValue("id", sessionId).addValue("at", Timestamp.from(at)));
    }

    @Override
    public Optional<ChatSessionRow> latestSession(String memberId) {
        return jdbc.query("SELECT " + SESSION_COLUMNS + " FROM chat_sessions WHERE member_id = :memberId "
                        + "ORDER BY updated_at DESC, id DESC LIMIT 1",
                new MapSqlParameterSource("memberId", memberId), SESSION).stream().findFirst();
    }

    @Override
    public int countJobs(String sessionId) {
        Integer count = jdbc.queryForObject("SELECT count(*) FROM chat_jobs WHERE session_id = :id",
                new MapSqlParameterSource("id", sessionId), Integer.class);
        return count == null ? 0 : count;
    }

    @Override
    public List<ChatJobRow> jobs(String sessionId) {
        return jdbc.query(JOB_SELECT + " WHERE j.session_id = :id ORDER BY j.seq",
                new MapSqlParameterSource("id", sessionId), JOB);
    }

    @Override
    public Optional<ChatJobRow> findJob(String jobId) {
        return jdbc.query(JOB_SELECT + " WHERE j.id = :id", new MapSqlParameterSource("id", jobId), JOB)
                .stream().findFirst();
    }

    @Override
    public Optional<ChatJobRow> activeJob(String sessionId) {
        return jdbc.query(JOB_SELECT + " WHERE j.session_id = :id AND j.status IN ('queued', 'running')",
                new MapSqlParameterSource("id", sessionId), JOB).stream().findFirst();
    }

    @Override
    public int nextSeq(String sessionId) {
        Integer next = jdbc.queryForObject("SELECT COALESCE(max(seq), 0) + 1 FROM chat_jobs WHERE session_id = :id",
                new MapSqlParameterSource("id", sessionId), Integer.class);
        return next == null ? 1 : next;
    }

    @Override
    public boolean insertJob(NewChatJob job) {
        Array companyIds = jdbc.getJdbcTemplate().execute((ConnectionCallback<Array>) connection ->
                connection.createArrayOf("text", job.contextCompanyIds().toArray()));
        return jdbc.update("""
                INSERT INTO chat_jobs (id, session_id, seq, question, request_hash, asked_at, frozen_context,
                    frozen_selection, context_company_ids, graph_version_id, status, resolves_job_id, resolves_choice_id,
                    clarification_depth, attempts, created_at, updated_at)
                VALUES (:id, :sessionId, :seq, :question, :requestHash, :askedAt, CAST(:frozenContext AS jsonb),
                    CAST(:frozenSelection AS jsonb),
                    :companyIds, :graphVersionId, 'queued', :resolvesJobId, :resolvesChoiceId,
                    :depth, CAST(:attempts AS jsonb), :askedAt, :askedAt)
                ON CONFLICT DO NOTHING
                """, new MapSqlParameterSource().addValue("id", job.id()).addValue("sessionId", job.sessionId())
                .addValue("seq", job.seq()).addValue("question", job.question())
                .addValue("requestHash", job.requestHash()).addValue("askedAt", Timestamp.from(job.askedAt()))
                .addValue("frozenContext", job.frozenContext())
                .addValue("frozenSelection", job.frozenSelection()).addValue("companyIds", companyIds)
                .addValue("graphVersionId", job.graphVersionId()).addValue("resolvesJobId", job.resolvesJobId())
                .addValue("resolvesChoiceId", job.resolvesChoiceId()).addValue("depth", job.clarificationDepth())
                .addValue("attempts", job.attempts())) == 1;
    }

    @Override
    public boolean cancel(String jobId, Instant at, String attempts) {
        return jdbc.update("""
                UPDATE chat_jobs SET status = 'cancelled', phase = NULL, owner_token = NULL, lease_until = NULL,
                    deadline_at = NULL, cancel_requested = true, attempts = CAST(:attempts AS jsonb),
                    finished_at = :at, updated_at = :at
                 WHERE id = :id AND status IN ('queued', 'running')
                """, new MapSqlParameterSource().addValue("id", jobId).addValue("at", Timestamp.from(at))
                .addValue("attempts", attempts)) == 1;
    }

    @Override
    public boolean requeue(String jobId, Instant at, String attempts) {
        return jdbc.update("""
                UPDATE chat_jobs SET status = 'queued', failure = NULL, finished_at = NULL,
                    attempts = CAST(:attempts AS jsonb), updated_at = :at
                 WHERE id = :id AND status = 'failed'
                """, new MapSqlParameterSource().addValue("id", jobId).addValue("at", Timestamp.from(at))
                .addValue("attempts", attempts)) == 1;
    }

    private static final RowMapper<ChatSessionRow> SESSION = (rs, index) -> new ChatSessionRow(rs.getString("id"),
            rs.getString("member_id"), instant(rs, "created_at"), instant(rs, "updated_at"));

    static final RowMapper<ChatJobRow> JOB = (rs, index) -> new ChatJobRow(rs.getString("id"),
            rs.getString("session_id"), rs.getString("member_id"), rs.getInt("seq"), rs.getString("question"),
            rs.getString("request_hash"), instant(rs, "asked_at"), rs.getString("frozen_context"),
            rs.getString("frozen_selection"),
            strings(rs.getArray("context_company_ids")), rs.getString("graph_version_id"), rs.getString("status"),
            rs.getString("phase"), rs.getString("outcome"), rs.getString("resolves_job_id"),
            rs.getString("resolves_choice_id"), rs.getInt("clarification_depth"), rs.getString("result"),
            rs.getString("failure"), rs.getInt("runs"), rs.getString("attempts"), instant(rs, "created_at"),
            instant(rs, "updated_at"), instant(rs, "finished_at"));

    private static Instant instant(ResultSet rs, String column) throws SQLException {
        Timestamp value = rs.getTimestamp(column);
        return value == null ? null : value.toInstant();
    }

    private static List<String> strings(Array array) throws SQLException {
        return array == null ? List.of() : Arrays.asList((String[]) array.getArray());
    }
}
