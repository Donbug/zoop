package com.zoop.admin.review;

import com.zoop.graph.version.JdbcGraphVersionRepository;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Optional;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/** {@code review_targets} (the filter projection of the AI source) and the append-only {@code review_decisions}. */
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

    /** The public candidate id is the app id of the candidate's current target row. */
    public Optional<Target> currentCandidate(String candidateTargetId) {
        return jdbc.query(TARGET + " WHERE id = :id AND target_type = 'candidate' AND is_current",
                new MapSqlParameterSource("id", candidateTargetId), JdbcReviewRepository::target).stream().findFirst();
    }

    /** A relation target of that candidate (same S3 job), current only; {@code lock} takes the row for the decision. */
    public Optional<Target> currentRelation(Target candidate, String relationId, boolean lock) {
        return jdbc.query(TARGET + """
                 WHERE target_type = 'relation' AND is_current AND source_job_id = :job AND candidate_id = :candidate
                   AND external_id = :relation
                """ + (lock ? " FOR UPDATE" : ""), new MapSqlParameterSource("job", candidate.sourceJobId())
                .addValue("candidate", candidate.candidateId()).addValue("relation", relationId),
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

    /** {@code current_revision = expected} is the compare-and-set: 0 rows means another decision got there first. */
    public boolean advance(String targetId, long expectedRevision, String status, Instant at) {
        return jdbc.update("""
                UPDATE review_targets SET current_revision = current_revision + 1, status = :status, updated_at = :at
                WHERE id = :id AND is_current AND current_revision = :expected
                """, new MapSqlParameterSource("id", targetId).addValue("expected", expectedRevision)
                .addValue("status", status).addValue("at", Timestamp.from(at))) == 1;
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

    /** The current app-wide review revision (0 before any decision): RuleSwitchResponse, dashboards. */
    public long currentGlobalRevision() {
        Long max = jdbc.getJdbcTemplate().queryForObject("SELECT COALESCE(MAX(global_revision), 0) FROM review_decisions",
                Long.class);
        return max == null ? 0 : max;
    }

    private static Target target(ResultSet rs, int rowNumber) throws SQLException {
        return new Target(rs.getString("id"), rs.getString("target_type"), rs.getString("source_job_id"),
                rs.getString("external_id"), rs.getString("source_version"), rs.getString("candidate_id"),
                rs.getLong("current_revision"), rs.getString("status"), rs.getString("source_revision"),
                rs.getBoolean("is_current"));
    }
}
