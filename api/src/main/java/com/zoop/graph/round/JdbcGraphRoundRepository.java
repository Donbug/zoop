package com.zoop.graph.round;

import java.nio.charset.StandardCharsets;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import com.zoop.graph.round.GraphRound.Lease;
import com.zoop.graph.round.GraphRoundEvent.Outcome;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** {@code graph_rounds} and {@code graph_round_events} over the app database. */
@Repository
public class JdbcGraphRoundRepository implements GraphRoundRepository {
    static final int MAX_DETAIL_BYTES = 8 * 1024;
    private static final String COLUMNS = """
            round_id, slot_at, stage, plan_id, plan_digest, ingestion_round_id, analysis_job_id, handoff_id, manifest_digest,
            bundle_digest,
            graph_version_id, version_committed_at, activated_version_id, activation_note, failure_code, attempts,
            next_attempt_at,
            lease_owner, lease_until, lease_token, started_by, created_at, updated_at
            """;
    private static final String SELECT = "SELECT " + COLUMNS + " FROM graph_rounds ";
    private static final String TERMINAL = "('imported', 'skipped', 'failed')";
    /** Finished for good; a failed round is still taken for a retry. */
    private static final String FINISHED = "('imported', 'skipped')";

    private final NamedParameterJdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final TransactionTemplate tx;

    public JdbcGraphRoundRepository(NamedParameterJdbcTemplate jdbc, ObjectMapper mapper,
            PlatformTransactionManager transactions) {
        this.jdbc = jdbc;
        this.mapper = mapper;
        this.tx = new TransactionTemplate(transactions);
    }

    @Override
    public GraphRound create(String roundId, Instant slotAt, String startedBy, Instant now) {
        return jdbc.query("""
                INSERT INTO graph_rounds (round_id, slot_at, stage, attempts, started_by, created_at, updated_at)
                VALUES (:id, :slot, 'scheduled', 0, :by, :now, :now)
                RETURNING
                """ + COLUMNS, new MapSqlParameterSource("id", roundId).addValue("slot", stamp(slotAt)).addValue("by", startedBy)
                .addValue("now", stamp(now)), JdbcGraphRoundRepository::round).getFirst();
    }

    @Override
    public Optional<GraphRound> find(String roundId) {
        return first(jdbc.query(SELECT + "WHERE round_id = :id", new MapSqlParameterSource("id", roundId),
                JdbcGraphRoundRepository::round));
    }

    @Override
    public Optional<GraphRound> findBySlot(Instant slotAt) {
        return first(jdbc.query(SELECT + "WHERE slot_at = :slot", new MapSqlParameterSource("slot", stamp(slotAt)),
                JdbcGraphRoundRepository::round));
    }

    @Override
    public List<GraphRound> due(Instant now, int limit) {
        return jdbc.query(SELECT + """
                WHERE stage NOT IN """ + TERMINAL + """
                  AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
                ORDER BY slot_at LIMIT :limit
                """, new MapSqlParameterSource("now", stamp(now)).addValue("limit", limit), JdbcGraphRoundRepository::round);
    }

    /**
     * A finished row ({@code imported}, {@code skipped}) is never taken: it has nothing left to do and keeps no lease; a failed
     * one is taken for its retry. A new lease gets the next token of {@code graph_round_lease_tokens}; the holder renewing an
     * unexpired lease keeps its token.
     */
    @Override
    public Optional<GraphRound> claim(String roundId, String owner, Duration lease, Instant now) {
        return first(jdbc.query("""
                UPDATE graph_rounds SET
                    lease_token = CASE WHEN lease_owner = :owner AND lease_until >= :now THEN lease_token
                                       ELSE nextval('graph_round_lease_tokens') END,
                    lease_owner = :owner, lease_until = :until, updated_at = :now
                WHERE round_id = :id AND stage NOT IN """ + FINISHED + """
                  AND (lease_owner IS NULL OR lease_owner = :owner OR lease_until < :now)
                RETURNING
                """ + COLUMNS, new MapSqlParameterSource("id", roundId).addValue("owner", owner)
                .addValue("until", stamp(now.plus(lease))).addValue("now", stamp(now)), JdbcGraphRoundRepository::round));
    }

    @Override
    public void release(String roundId, String owner) {
        jdbc.update("""
                UPDATE graph_rounds SET lease_owner = NULL, lease_until = NULL, lease_token = NULL
                WHERE round_id = :id AND lease_owner = :owner
                """, new MapSqlParameterSource("id", roundId).addValue("owner", owner));
    }

    /**
     * Fenced on the expected stage and the lease token: a row that moved on, or whose lease another holder took, is left as it is
     * and no event is written. The lease is kept while the round stays open and dropped with a terminal stage.
     */
    @Override
    public Optional<GraphRound> advance(GraphRound expected, GraphRoundPatch patch, Outcome outcome, String code,
            String requestId, JsonNode detail, Instant at) {
        long token = token(expected);
        String detailJson = detail == null ? null : mapper.writeValueAsString(detail);
        if (detailJson != null && detailJson.getBytes(StandardCharsets.UTF_8).length > MAX_DETAIL_BYTES) {
            throw new IllegalArgumentException("round event detail exceeds " + MAX_DETAIL_BYTES + " bytes");
        }
        String roundId = expected.roundId();
        return tx.execute(ignored -> {
            List<GraphRound> updated = jdbc.query("""
                    UPDATE graph_rounds SET
                        stage = :stage,
                        plan_id = COALESCE(:planId, plan_id),
                        plan_digest = COALESCE(:planDigest, plan_digest),
                        ingestion_round_id = COALESCE(:ingestionRoundId, ingestion_round_id),
                        analysis_job_id = COALESCE(:jobId, analysis_job_id),
                        handoff_id = COALESCE(:handoffId, handoff_id),
                        manifest_digest = COALESCE(:manifestDigest, manifest_digest),
                        bundle_digest = COALESCE(:bundleDigest, bundle_digest),
                        graph_version_id = CASE WHEN :clearVersion THEN NULL ELSE COALESCE(:versionId, graph_version_id) END,
                        version_committed_at = COALESCE(version_committed_at, CAST(:committedAt AS timestamptz)),
                        failure_code = :failureCode,
                        attempts = CASE WHEN :reset THEN 0 ELSE attempts END + CASE WHEN :count THEN 1 ELSE 0 END,
                        next_attempt_at = CASE WHEN :clearNext THEN NULL ELSE COALESCE(:nextAt, next_attempt_at) END,
                        lease_owner = CASE WHEN :terminal THEN NULL ELSE lease_owner END,
                        lease_until = CASE WHEN :terminal THEN NULL ELSE lease_until END,
                        lease_token = CASE WHEN :terminal THEN NULL ELSE lease_token END,
                        updated_at = :at
                    WHERE round_id = :id AND stage = :expectedStage AND lease_token = :token
                    RETURNING
                    """ + COLUMNS, new MapSqlParameterSource("id", roundId).addValue("stage", patch.stage().wire())
                    .addValue("expectedStage", expected.stage().wire()).addValue("token", token)
                    .addValue("planId", patch.planId()).addValue("planDigest", patch.planDigest())
                    .addValue("ingestionRoundId", patch.ingestionRoundId())
                    .addValue("jobId", patch.analysisJobId()).addValue("handoffId", patch.handoffId())
                    .addValue("manifestDigest", patch.manifestDigest()).addValue("bundleDigest", patch.bundleDigest())
                    .addValue("versionId", patch.graphVersionId()).addValue("clearVersion", patch.clearGraphVersion())
                    .addValue("committedAt", stamp(patch.graphVersionId() == null ? null : at))
                    .addValue("failureCode", patch.failureCode())
                    .addValue("reset", patch.resetAttempts()).addValue("count", patch.countAttempt())
                    .addValue("clearNext", patch.clearNextAttempt()).addValue("nextAt", stamp(patch.nextAttemptAt()))
                    .addValue("terminal", patch.stage().terminal()).addValue("at", stamp(at)), JdbcGraphRoundRepository::round);
            if (updated.isEmpty()) {
                if (find(roundId).isEmpty()) throw new IllegalStateException("round not found: " + roundId);
                return Optional.empty();
            }
            jdbc.update("""
                    INSERT INTO graph_round_events (round_id, at, stage, outcome, code, request_id, detail)
                    VALUES (:id, :at, :stage, :outcome, :code, :requestId, CAST(:detail AS jsonb))
                    """, new MapSqlParameterSource("id", roundId).addValue("at", stamp(at)).addValue("stage", patch.stage().wire())
                    .addValue("outcome", outcome.wire()).addValue("code", code).addValue("requestId", requestId)
                    .addValue("detail", detailJson));
            return Optional.of(updated.getFirst());
        });
    }

    /**
     * Runs in the caller's transaction (no template of its own): the import's, so the link commits with the version. The
     * commit record ({@code version_committed_at}) is set with the first link of the slot and kept by every later one.
     */
    @Override
    public boolean link(GraphRound expected, String graphVersionId, Instant at) {
        long token = token(expected);
        if (!TransactionSynchronizationManager.isActualTransactionActive()) {
            throw new IllegalStateException("link must run inside the import transaction");
        }
        return jdbc.update("""
                UPDATE graph_rounds SET graph_version_id = :versionId,
                    version_committed_at = COALESCE(version_committed_at, :at), updated_at = :at
                WHERE round_id = :id AND stage = :expectedStage AND lease_token = :token
                """, new MapSqlParameterSource("id", expected.roundId()).addValue("versionId", graphVersionId)
                .addValue("expectedStage", expected.stage().wire()).addValue("token", token).addValue("at", stamp(at))) == 1;
    }

    private static long token(GraphRound expected) {
        return expected.lease().orElseThrow(() -> new IllegalArgumentException("the round must be claimed first")).token();
    }

    @Override
    public void recordActivation(String roundId, String activatedVersionId, String note, Instant at) {
        jdbc.update("""
                UPDATE graph_rounds SET activated_version_id = :version, activation_note = :note, updated_at = :at
                WHERE round_id = :id
                """, new MapSqlParameterSource("id", roundId).addValue("version", activatedVersionId).addValue("note", note)
                .addValue("at", stamp(at)));
    }

    @Override
    public List<GraphRoundEvent> events(String roundId) {
        return jdbc.query("""
                SELECT id, round_id, at, stage, outcome, code, request_id, detail::text AS detail
                FROM graph_round_events WHERE round_id = :id ORDER BY id
                """, new MapSqlParameterSource("id", roundId), this::event);
    }

    @Override
    public List<GraphRound> page(GraphRoundStage stage, Instant beforeSlot, int limit) {
        StringBuilder where = new StringBuilder("WHERE TRUE");
        MapSqlParameterSource params = new MapSqlParameterSource("limit", limit);
        if (stage != null) {
            where.append(" AND stage = :stage");
            params.addValue("stage", stage.wire());
        }
        if (beforeSlot != null) {
            where.append(" AND slot_at < :before");
            params.addValue("before", stamp(beforeSlot));
        }
        return jdbc.query(SELECT + where + " ORDER BY slot_at DESC LIMIT :limit", params, JdbcGraphRoundRepository::round);
    }

    @Override
    public long openCount() {
        Long count = jdbc.queryForObject("SELECT count(*) FROM graph_rounds WHERE stage NOT IN " + TERMINAL,
                new MapSqlParameterSource(), Long.class);
        return count == null ? 0 : count;
    }

    @Override
    public Optional<GraphRound> newestImported() {
        return first(jdbc.query(SELECT
                + "WHERE stage = 'imported' OR version_committed_at IS NOT NULL ORDER BY slot_at DESC LIMIT 1",
                new MapSqlParameterSource(), JdbcGraphRoundRepository::round));
    }

    private static GraphRound round(ResultSet rs, int row) throws SQLException {
        String leaseOwner = rs.getString("lease_owner");
        Timestamp leaseUntil = rs.getTimestamp("lease_until");
        return new GraphRound(rs.getString("round_id"), rs.getTimestamp("slot_at").toInstant(),
                GraphRoundStage.parse(rs.getString("stage")), text(rs, "plan_id"), text(rs, "plan_digest"),
                text(rs, "ingestion_round_id"), text(rs, "analysis_job_id"), text(rs, "handoff_id"), text(rs, "manifest_digest"), text(rs, "bundle_digest"),
                text(rs, "graph_version_id"), instant(rs, "version_committed_at"), text(rs, "activated_version_id"),
                text(rs, "activation_note"),
                text(rs, "failure_code"), rs.getInt("attempts"), instant(rs, "next_attempt_at"),
                leaseOwner == null ? Optional.empty()
                        : Optional.of(new Lease(leaseOwner, leaseUntil.toInstant(), rs.getLong("lease_token"))),
                rs.getString("started_by"), rs.getTimestamp("created_at").toInstant(), rs.getTimestamp("updated_at").toInstant());
    }

    private GraphRoundEvent event(ResultSet rs, int row) throws SQLException {
        String detail = rs.getString("detail");
        return new GraphRoundEvent(rs.getLong("id"), rs.getString("round_id"), rs.getTimestamp("at").toInstant(),
                GraphRoundStage.parse(rs.getString("stage")), Outcome.parse(rs.getString("outcome")), text(rs, "code"),
                text(rs, "request_id"), detail == null ? Optional.empty() : Optional.of(mapper.readTree(detail)));
    }

    private static Optional<String> text(ResultSet rs, String column) throws SQLException {
        return Optional.ofNullable(rs.getString(column));
    }

    private static Optional<Instant> instant(ResultSet rs, String column) throws SQLException {
        Timestamp value = rs.getTimestamp(column);
        return value == null ? Optional.empty() : Optional.of(value.toInstant());
    }

    private static Timestamp stamp(Instant at) {
        return at == null ? null : Timestamp.from(at);
    }

    private static <T> Optional<T> first(List<T> rows) {
        return rows.isEmpty() ? Optional.empty() : Optional.of(rows.getFirst());
    }
}
