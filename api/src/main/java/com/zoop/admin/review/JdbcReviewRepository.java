package com.zoop.admin.review;

import com.zoop.graph.version.JdbcGraphVersionRepository;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * {@code review_targets} (the filter projection of the AI source), the append-only {@code review_decisions} and the
 * {@code review_decision_intents} written before each AI review call.
 */
@Repository
public class JdbcReviewRepository {
    private static final String TARGET = """
            SELECT id, target_type, source_job_id, external_id, source_version, candidate_id, current_revision, status,
                   source_revision, is_current
            FROM review_targets
            """;

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcReviewRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public record Target(String id, String type, String sourceJobId, String externalId, String sourceVersion,
            String candidateId, long revision, String status, String sourceRevision, boolean current) {
    }

    /** One decision command as fixed before the AI call; {@code status} pending|applied|refused|blocked. */
    public record Intent(String id, String operationId, String idempotencyRecordId, String adminId, String adminEmail,
            String requestId, String candidateId, String targetId, String sourceJobId, String relationCandidateId,
            String decision, String reason, long expectedRevision, String expectedSourceVersion,
            String expectedSourceRevision, String status, String sourceCode, Long decisionId, Instant createdAt) {
    }

    private static final String INTENT = """
            SELECT id, operation_id, idempotency_record_id, admin_id, admin_email_snapshot, request_id, candidate_id, target_id,
                   source_job_id, relation_candidate_id, decision, reason, expected_revision, expected_source_version,
                   expected_source_revision, status, source_code, decision_id, created_at
            FROM review_decision_intents
            """;

    /** The public candidate id is the app id of the candidate's current target row. */
    public Optional<Target> currentCandidate(String candidateTargetId) {
        return jdbc.query(TARGET + " WHERE id = :id AND target_type = 'candidate' AND is_current",
                new MapSqlParameterSource("id", candidateTargetId), JdbcReviewRepository::target).stream().findFirst();
    }

    /** A relation target of that candidate (same S3 job), current only. */
    public Optional<Target> currentRelation(Target candidate, String relationId) {
        return jdbc.query(TARGET + """
                 WHERE target_type = 'relation' AND is_current AND source_job_id = :job AND candidate_id = :candidate
                   AND external_id = :relation
                """, new MapSqlParameterSource("job", candidate.sourceJobId())
                .addValue("candidate", candidate.candidateId()).addValue("relation", relationId),
                JdbcReviewRepository::target).stream().findFirst();
    }

    /** Any target row by its app id, current or not (an intent's target stays fixed while the sync moves on). */
    public Optional<Target> target(String id, boolean lock) {
        return jdbc.query(TARGET + " WHERE id = :id" + (lock ? " FOR UPDATE" : ""), new MapSqlParameterSource("id", id),
                JdbcReviewRepository::target).stream().findFirst();
    }

    /** The shared publication lock: decisions get their global revision in commit order (ERD v6 section 27). */
    public void lockPublication() {
        jdbc.getJdbcTemplate().execute("SELECT pg_advisory_xact_lock(" + JdbcGraphVersionRepository.PUBLICATION_LOCK + ")");
    }

    /** Read after the lock, never from a snapshot taken before waiting for it. */
    public long nextGlobalRevision() {
        Long max = jdbc.getJdbcTemplate().queryForObject("SELECT COALESCE(MAX(global_revision), 0) FROM review_decisions",
                Long.class);
        return (max == null ? 0 : max) + 1;
    }

    /**
     * Settles an intent the AI source applied: under the target row lock, its revision +1 whether or not the row is still the
     * current one, since the AI source, not the projection, decides whether the decision exists.
     */
    public void settleTarget(String targetId, long lockedRevision, String status, Instant at) {
        int changed = jdbc.update("""
                UPDATE review_targets SET current_revision = current_revision + 1, status = :status, updated_at = :at
                WHERE id = :id AND current_revision = :expected
                """, new MapSqlParameterSource("id", targetId).addValue("expected", lockedRevision)
                .addValue("status", status).addValue("at", Timestamp.from(at)));
        if (changed != 1) throw new IllegalStateException("Locked review target was not advanced");
    }

    public long insertDecision(String targetId, String decision, String reason, String adminId, String adminEmail,
            Instant decidedAt, long revision, long globalRevision) {
        Long id = jdbc.queryForObject("""
                INSERT INTO review_decisions
                  (target_id, decision, reason, admin_id, admin_email_snapshot, decided_at, revision, global_revision, origin)
                VALUES (:target, :decision, :reason, :admin, :email, :at, :revision, :global, 'admin')
                RETURNING id
                """, new MapSqlParameterSource("target", targetId).addValue("decision", decision).addValue("reason", reason)
                .addValue("admin", adminId).addValue("email", adminEmail).addValue("at", Timestamp.from(decidedAt))
                .addValue("revision", revision).addValue("global", globalRevision), Long.class);
        if (id == null) throw new IllegalStateException("Decision id was not returned");
        return id;
    }

    public void insertIntent(Intent intent) {
        jdbc.update("""
                INSERT INTO review_decision_intents
                  (id, operation_id, idempotency_record_id, admin_id, admin_email_snapshot, request_id, candidate_id, target_id,
                   source_job_id, relation_candidate_id, decision, reason, expected_revision, expected_source_version,
                   expected_source_revision, status, created_at, updated_at)
                VALUES (:id, :operation, :record, :admin, :email, :requestId, :candidate, :target, :job, :relation, :decision,
                        :reason, :revision, :version, :sourceRevision, 'pending', :at, :at)
                """, new MapSqlParameterSource("id", intent.id()).addValue("operation", intent.operationId())
                .addValue("record", intent.idempotencyRecordId()).addValue("admin", intent.adminId())
                .addValue("email", intent.adminEmail()).addValue("requestId", intent.requestId())
                .addValue("candidate", intent.candidateId()).addValue("target", intent.targetId())
                .addValue("job", intent.sourceJobId()).addValue("relation", intent.relationCandidateId())
                .addValue("decision", intent.decision()).addValue("reason", intent.reason())
                .addValue("revision", intent.expectedRevision()).addValue("version", intent.expectedSourceVersion())
                .addValue("sourceRevision", intent.expectedSourceRevision())
                .addValue("at", Timestamp.from(intent.createdAt())));
    }

    public Optional<Intent> intentForRecord(String idempotencyRecordId, boolean lock) {
        return jdbc.query(INTENT + " WHERE idempotency_record_id = :record" + (lock ? " FOR UPDATE" : ""),
                new MapSqlParameterSource("record", idempotencyRecordId), JdbcReviewRepository::intent).stream().findFirst();
    }

    public Optional<Intent> intent(String id, boolean lock) {
        return jdbc.query(INTENT + " WHERE id = :id" + (lock ? " FOR UPDATE" : ""), new MapSqlParameterSource("id", id),
                JdbcReviewRepository::intent).stream().findFirst();
    }

    /** Pending and blocked intents created before {@code before}, least recently touched first. */
    public List<Intent> openIntents(Instant before, int limit) {
        return jdbc.query(INTENT + """
                 WHERE status IN ('pending', 'blocked') AND created_at < :before
                ORDER BY updated_at, id
                LIMIT :limit
                """, new MapSqlParameterSource("before", Timestamp.from(before)).addValue("limit", limit),
                JdbcReviewRepository::intent);
    }

    /** Sends an open intent to the back of {@link #openIntents} after a lookup that did not settle it. */
    public void touch(String intentId, Instant at) {
        jdbc.update("""
                UPDATE review_decision_intents SET updated_at = :at WHERE id = :id AND status IN ('pending', 'blocked')
                """, new MapSqlParameterSource("id", intentId).addValue("at", Timestamp.from(at)));
    }

    public void markApplied(String intentId, long decisionId, Instant at) {
        int changed = jdbc.update("""
                UPDATE review_decision_intents SET status = 'applied', decision_id = :decision, updated_at = :at
                WHERE id = :id AND status IN ('pending', 'blocked')
                """, new MapSqlParameterSource("id", intentId).addValue("decision", decisionId)
                .addValue("at", Timestamp.from(at)));
        if (changed != 1) throw new IllegalStateException("Review intent was not open");
    }

    /** {@code status}: pending keeps the intent open with the last code; refused or blocked stops it being resent. */
    public void markUnsettled(String intentId, String status, String sourceCode, Instant at) {
        int changed = jdbc.update("""
                UPDATE review_decision_intents SET status = :status, source_code = :code, updated_at = :at
                WHERE id = :id AND status = 'pending'
                """, new MapSqlParameterSource("id", intentId).addValue("status", status).addValue("code", sourceCode)
                .addValue("at", Timestamp.from(at)));
        if (changed != 1) throw new IllegalStateException("Review intent was not pending");
    }

    /** The current app-wide review revision (0 before any decision): RuleSwitchResponse, dashboards. */
    public long currentGlobalRevision() {
        Long max = jdbc.getJdbcTemplate().queryForObject("SELECT COALESCE(MAX(global_revision), 0) FROM review_decisions",
                Long.class);
        return max == null ? 0 : max;
    }

    private static Intent intent(ResultSet rs, int rowNumber) throws SQLException {
        long decisionId = rs.getLong("decision_id");
        Long decision = rs.wasNull() ? null : decisionId;
        return new Intent(rs.getString("id"), rs.getString("operation_id"), rs.getString("idempotency_record_id"),
                rs.getString("admin_id"), rs.getString("admin_email_snapshot"), rs.getString("request_id"),
                rs.getString("candidate_id"), rs.getString("target_id"), rs.getString("source_job_id"),
                rs.getString("relation_candidate_id"), rs.getString("decision"), rs.getString("reason"),
                rs.getLong("expected_revision"), rs.getString("expected_source_version"),
                rs.getString("expected_source_revision"), rs.getString("status"), rs.getString("source_code"), decision,
                rs.getTimestamp("created_at").toInstant());
    }

    private static Target target(ResultSet rs, int rowNumber) throws SQLException {
        return new Target(rs.getString("id"), rs.getString("target_type"), rs.getString("source_job_id"),
                rs.getString("external_id"), rs.getString("source_version"), rs.getString("candidate_id"),
                rs.getLong("current_revision"), rs.getString("status"), rs.getString("source_revision"),
                rs.getBoolean("is_current"));
    }
}
