package com.zoop.graph.publication;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Base64;
import java.util.Optional;
import com.zoop.common.json.Canonical;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * The round path's preparation journal ({@code graph_publication_preparations}, #55 PR-P3): one row per attempt. The request and
 * decision bytes commit before the composition ({@link #begin}); the result is written once ({@link #complete}). An attempt that
 * never composed is written whole ({@link #record}). The table's trigger refuses every other change and every delete.
 */
public final class JdbcGraphPublicationPreparationRepository {
    /** One attempt. {@code code} is the outcome of a succeeded attempt and the failure code of a failed one; empty until written. */
    public record Preparation(long id, Optional<String> roundId, long triggerSequence, Optional<Long> recoveryOf, Instant createdAt,
            Optional<String> activeVersionId, Optional<byte[]> request, Optional<byte[]> decisions, Optional<String> status,
            Optional<String> code, Optional<Instant> completedAt) {
        public boolean composedWithoutResult() {
            return request.isPresent() && status.isEmpty();
        }
    }

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcGraphPublicationPreparationRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public Optional<Preparation> latest() {
        return jdbc.query(SELECT + " ORDER BY id DESC LIMIT 1", new MapSqlParameterSource(), JdbcGraphPublicationPreparationRepository::row)
                .stream().findFirst();
    }

    public Optional<Preparation> find(long id) {
        return jdbc.query(SELECT + " WHERE id = :id", new MapSqlParameterSource("id", id), JdbcGraphPublicationPreparationRepository::row)
                .stream().findFirst();
    }

    /** How many recovery attempts name {@code id}. */
    public int recoveries(long id) {
        Integer count = jdbc.queryForObject("SELECT count(*) FROM graph_publication_preparations WHERE recovery_of = :id",
                new MapSqlParameterSource("id", id), Integer.class);
        return count == null ? 0 : count;
    }

    /** How many first attempts (not recoveries) answered the import {@code trigger}. */
    public int attempts(long trigger) {
        Integer count = jdbc.queryForObject(
                "SELECT count(*) FROM graph_publication_preparations WHERE trigger_sequence = :trigger AND recovery_of IS NULL",
                new MapSqlParameterSource("trigger", trigger), Integer.class);
        return count == null ? 0 : count;
    }

    /** Keeps the fixed inputs of an attempt about to compose, before it does; returns the row id. */
    public long begin(String roundId, long trigger, Long recoveryOf, String activeVersionId, byte[] request, byte[] decisions, Instant at) {
        Long id = jdbc.queryForObject("""
                INSERT INTO graph_publication_preparations (round_id, trigger_sequence, recovery_of, created_at, active_version_id,
                    request, request_sha256, decisions, decisions_sha256)
                VALUES (:round, :trigger, :recovery, :at, :active, :request, :requestSha, :decisions, :decisionsSha)
                RETURNING id
                """, new MapSqlParameterSource("round", roundId).addValue("trigger", trigger).addValue("recovery", recoveryOf)
                .addValue("at", stamp(at)).addValue("active", activeVersionId).addValue("request", request)
                .addValue("requestSha", Canonical.sha256(request)).addValue("decisions", decisions)
                .addValue("decisionsSha", Canonical.sha256(decisions)), Long.class);
        return id;
    }

    /** Writes the result of a begun attempt, once (the trigger refuses a second write). */
    public void complete(long id, ObjectNode result, Instant at) {
        jdbc.update("""
                UPDATE graph_publication_preparations SET status = :status, code = :code, graph_version_id = :version,
                    result = CAST(:result AS jsonb), completed_at = :at
                WHERE id = :id
                """, resultArgs(result, at).addValue("id", id));
    }

    /** An attempt that did not compose (it stopped before, or found nothing): its fixed inputs, if it made a request, and its result. */
    public long record(String roundId, long trigger, ObjectNode result, Instant at) {
        byte[] request = result.has("request") ? Canonical.bytes(result.get("request")) : null;
        byte[] decisions = result.has("decisionsBase64") ? Base64.getDecoder().decode(result.get("decisionsBase64").asString()) : null;
        JsonNode active = result.get("activeVersionId");
        Long id = jdbc.queryForObject("""
                INSERT INTO graph_publication_preparations (round_id, trigger_sequence, created_at, active_version_id,
                    request, request_sha256, decisions, decisions_sha256, status, code, graph_version_id, result, completed_at)
                VALUES (:round, :trigger, :at, :active, :request, :requestSha, :decisions, :decisionsSha,
                    :status, :code, :version, CAST(:result AS jsonb), :at)
                RETURNING id
                """, resultArgs(result, at).addValue("round", roundId).addValue("trigger", trigger)
                .addValue("active", active == null || active.isNull() ? null : active.asString())
                .addValue("request", request).addValue("requestSha", request == null ? null : Canonical.sha256(request))
                .addValue("decisions", decisions).addValue("decisionsSha", decisions == null ? null : Canonical.sha256(decisions)), Long.class);
        return id;
    }

    /** The code a result settles on: the outcome when it succeeded, the failure code otherwise. */
    public static String code(ObjectNode result) {
        boolean succeeded = "succeeded".equals(result.path("status").asString(""));
        return result.path(succeeded ? "outcome" : "code").asString("internal_error");
    }

    private static MapSqlParameterSource resultArgs(ObjectNode result, Instant at) {
        boolean succeeded = "succeeded".equals(result.path("status").asString(""));
        JsonNode version = result.get("graphVersionId");
        return new MapSqlParameterSource("status", succeeded ? "succeeded" : "failed").addValue("code", code(result))
                .addValue("version", version == null || version.isNull() ? null : version.asString())
                .addValue("result", new String(Canonical.bytes(result), java.nio.charset.StandardCharsets.UTF_8)).addValue("at", stamp(at));
    }

    private static final String SELECT = """
            SELECT id, round_id, trigger_sequence, recovery_of, created_at, active_version_id, request, decisions, status, code,
                completed_at FROM graph_publication_preparations""";

    private static Preparation row(ResultSet rs, int ignored) throws SQLException {
        long recovery = rs.getLong("recovery_of");
        Optional<Long> recoveryOf = rs.wasNull() ? Optional.empty() : Optional.of(recovery);
        return new Preparation(rs.getLong("id"), Optional.ofNullable(rs.getString("round_id")), rs.getLong("trigger_sequence"),
                recoveryOf, rs.getTimestamp("created_at").toInstant(), Optional.ofNullable(rs.getString("active_version_id")),
                Optional.ofNullable(rs.getBytes("request")), Optional.ofNullable(rs.getBytes("decisions")),
                Optional.ofNullable(rs.getString("status")), Optional.ofNullable(rs.getString("code")),
                Optional.ofNullable(rs.getTimestamp("completed_at")).map(Timestamp::toInstant));
    }

    private static Timestamp stamp(Instant at) {
        return Timestamp.from(at);
    }
}
