package com.zoop.admin.review;

import com.zoop.common.json.StrictJson;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import java.nio.charset.StandardCharsets;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * {@code review_targets} (the filter projection of the AI source), the append-only {@code review_decisions} and the
 * {@code review_decision_intents} written before each AI review call.
 */
@Repository
public class JdbcReviewRepository {
    private static final String TARGET = """
            SELECT id, target_type, source_job_id, external_id, source_version, candidate_id, current_revision, status,
                   source_revision, is_current, active
            FROM review_targets
            """;

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcReviewRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public record Target(String id, String type, String sourceJobId, String externalId, String sourceVersion,
            String candidateId, long revision, String status, String sourceRevision, boolean current, boolean active) {
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

    /**
     * Registers a target of an S3 job, or refreshes its projection when this reading is newer. The key is the source identity
     * ({@code target_type}, job, external id, source version), so the identity columns are never touched. A reading only replaces
     * the stored one when its AI source revision is greater: an older reading that arrives late, or one taken before a decision
     * this app settled, never moves the status back. The display values (the S2 content the unit pinned by hash, so the same for
     * every reading of one job) are also written when only they differ, so a row synced before they existed gets them.
     *
     * @return true when a row was inserted or refreshed
     */
    public boolean upsertTarget(String sourceJobId, String sourceVersion, ReviewTargetReader.Row row, Instant at) {
        ReviewTargetReader.Display display = row.display();
        return jdbc.update("""
                INSERT INTO review_targets (id, target_type, source_job_id, external_id, source_version, candidate_id, status,
                                            company_ids, relation_types, source_revision, updated_at, issue_id, title, action,
                                            target, event_time, evidence_count, companies, reasons, operator_approved)
                VALUES (:id, :type, :job, :external, :version, :candidate, :status, CAST(:companyIds AS text[]),
                        CAST(:types AS text[]), :revision, :at, :issue, :title, :action, :target, :eventTime, :evidence,
                        CAST(:named AS jsonb), CAST(:reasons AS text[]), :approved)
                ON CONFLICT (target_type, source_job_id, external_id, source_version) DO UPDATE
                   SET status = CASE WHEN """ + NEWER + """
                                     THEN EXCLUDED.status ELSE review_targets.status END,
                       company_ids = CASE WHEN """ + NEWER + """
                                          THEN EXCLUDED.company_ids ELSE review_targets.company_ids END,
                       relation_types = CASE WHEN """ + NEWER + """
                                             THEN EXCLUDED.relation_types ELSE review_targets.relation_types END,
                       source_revision = CASE WHEN """ + NEWER + """
                                              THEN EXCLUDED.source_revision ELSE review_targets.source_revision END,
                       reasons = CASE WHEN """ + NEWER + """
                                       OR review_targets.reasons IS NULL THEN EXCLUDED.reasons ELSE review_targets.reasons END,
                       operator_approved = CASE WHEN """ + NEWER + """
                                                      OR """ + FILL_APPROVAL + """
                                                 THEN EXCLUDED.operator_approved ELSE review_targets.operator_approved END,
                       issue_id = EXCLUDED.issue_id, title = EXCLUDED.title, action = EXCLUDED.action, target = EXCLUDED.target,
                       event_time = EXCLUDED.event_time, evidence_count = EXCLUDED.evidence_count,
                       companies = EXCLUDED.companies, updated_at = EXCLUDED.updated_at
                 WHERE """ + NEWER + """
                    OR (review_targets.issue_id, review_targets.title, review_targets.action, review_targets.target, review_targets.event_time,
                        review_targets.evidence_count, review_targets.companies)
                       IS DISTINCT FROM (EXCLUDED.issue_id, EXCLUDED.title, EXCLUDED.action, EXCLUDED.target, EXCLUDED.event_time,
                        EXCLUDED.evidence_count, EXCLUDED.companies)
                    OR review_targets.reasons IS NULL
                    OR """ + FILL_APPROVAL + """
                """, new MapSqlParameterSource("id", "rt-" + UUID.randomUUID()).addValue("type", row.type())
                .addValue("job", sourceJobId).addValue("external", row.externalId()).addValue("version", sourceVersion)
                .addValue("candidate", row.candidateId()).addValue("status", row.status())
                .addValue("companyIds", row.companyIds().toArray(String[]::new))
                .addValue("types", row.relationTypes().toArray(String[]::new))
                .addValue("revision", row.sourceRevision()).addValue("at", Timestamp.from(at))
                .addValue("issue", display.issueId()).addValue("title", display.title())
                .addValue("action", display.action()).addValue("target", display.target()).addValue("eventTime", display.eventTime())
                .addValue("evidence", display.evidenceCount()).addValue("named", companiesJson(display.companies()))
                .addValue("reasons", display.reasons().toArray(String[]::new))
                .addValue("approved", row.operatorApproved())) == 1;
    }

    /** The incoming reading is a later AI source revision than the stored one. */
    private static final String NEWER =
            " CAST(EXCLUDED.source_revision AS numeric) > CAST(review_targets.source_revision AS numeric) ";

    /**
     * A row synced before {@code operator_approved} existed gets it from a reading of the same AI revision; an older reading
     * never overwrites it.
     */
    private static final String FILL_APPROVAL = " (review_targets.operator_approved IS NULL AND EXCLUDED.operator_approved IS NOT NULL"
            + " AND CAST(EXCLUDED.source_revision AS numeric) = CAST(review_targets.source_revision AS numeric)) ";

    private static String companiesJson(List<ReviewTargetReader.Company> companies) {
        ArrayNode array = StrictJson.newArray();
        for (ReviewTargetReader.Company company : companies) {
            ObjectNode node = array.addObject();
            node.put("sourceId", company.sourceId());
            node.put("name", company.name());
            node.put("role", company.role());
        }
        return new String(StrictJson.write(array), StandardCharsets.UTF_8);
    }

    /**
     * Marks which relation targets of an S3 job are in its latest complete reading: a relation that left it (back to no verdict,
     * or no longer in the result) is inactive rather than listed with its last status, and active again when it comes back.
     *
     * @return the rows whose {@code active} flag changed
     */
    public int markPresentRelations(String sourceJobId, String sourceVersion, List<String> relationIds, Instant at) {
        return jdbc.update("""
                UPDATE review_targets SET active = (external_id = ANY(CAST(:ids AS text[]))), updated_at = :at
                WHERE target_type = 'relation' AND source_job_id = :job AND source_version = :version
                  AND active IS DISTINCT FROM (external_id = ANY(CAST(:ids AS text[])))
                """, new MapSqlParameterSource("ids", relationIds.toArray(String[]::new)).addValue("job", sourceJobId)
                .addValue("version", sourceVersion).addValue("at", Timestamp.from(at)));
    }

    /**
     * Derives each candidate target of an S3 job from its active current relation targets: HOLD while any is, else ALLOW while
     * any is, else REJECT; a candidate with none left is inactive. Run after the sync wrote the relations and after a decision
     * settled one, so the candidate follows both without waiting for the next reading.
     *
     * @return the candidate rows that changed
     */
    public int refreshCandidates(String sourceJobId, Instant at) {
        return jdbc.update("""
                UPDATE review_targets c SET status = d.status, active = d.active, updated_at = :at
                FROM (SELECT c2.id,
                             CASE WHEN bool_or(r.status = 'HOLD') THEN 'HOLD' WHEN bool_or(r.status = 'ALLOW') THEN 'ALLOW'
                                  WHEN count(r.id) > 0 THEN 'REJECT' ELSE c2.status END AS status,
                             count(r.id) > 0 AS active
                      FROM review_targets c2
                      LEFT JOIN review_targets r ON r.target_type = 'relation' AND r.active AND r.is_current
                           AND r.source_job_id = c2.source_job_id AND r.candidate_id = c2.candidate_id
                      WHERE c2.target_type = 'candidate' AND c2.source_job_id = :job AND c2.is_current
                      GROUP BY c2.id, c2.status) d
                WHERE c.id = d.id AND (c.status, c.active) IS DISTINCT FROM (d.status, d.active)
                """, new MapSqlParameterSource("job", sourceJobId).addValue("at", Timestamp.from(at)));
    }

    /**
     * An analyze-plan unit whose S3 result the worker observed: what the review-target sync reads. {@code s2ResultSha256} is the
     * S2 result content hash the unit recorded, so the S2 result read again can be proven to be that content.
     */
    public record SyncUnit(String planId, int ordinal, String s3JobId, String s3InputDigest, String s2JobId,
            String s2InputDigest, String s2ResultSha256) {
    }

    private static final String SYNC_UNIT = """
            SELECT u.plan_id, u.ordinal, u.s3_job_id, u.s3_input_digest, u.s2_job_id, u.s2_input_digest,
                   u.s2_checkpoint->>'resultContentSha256' AS s2_result_sha256
            FROM analysis_plan_units u
            WHERE u.s3_checkpoint->>'state' = 'result_observed' AND u.s3_input_digest IS NOT NULL
              AND u.s2_checkpoint->>'resultContentSha256' IS NOT NULL
            """;

    /**
     * Observed units with no review target yet (never synced, or a sync that failed or found nothing decided), oldest first,
     * except the S3 jobs in {@code skipJobIds}: units tried a moment ago that yielded nothing must not hold the pass forever.
     */
    public List<SyncUnit> unsyncedUnits(int limit, Collection<String> skipJobIds) {
        return jdbc.query(SYNC_UNIT + """
                  AND NOT EXISTS (SELECT 1 FROM review_targets t WHERE t.source_job_id = u.s3_job_id)
                  AND NOT (u.s3_job_id = ANY(CAST(:skip AS text[])))
                ORDER BY u.s3_checkpoint->>'resultObservedAt', u.plan_id, u.ordinal LIMIT :limit
                """, new MapSqlParameterSource("limit", limit).addValue("skip", skipJobIds.toArray(String[]::new)),
                JdbcReviewRepository::syncUnit);
    }

    /** The observed unit that ran this S3 job, if any. */
    public Optional<SyncUnit> unitOf(String s3JobId) {
        return jdbc.query(SYNC_UNIT + " AND u.s3_job_id = :job", new MapSqlParameterSource("job", s3JobId),
                JdbcReviewRepository::syncUnit).stream().findFirst();
    }

    /** Observed units after ({@code planId}, {@code ordinal}) in key order: one page of the round-robin refresh. */
    public List<SyncUnit> unitsAfter(String planId, int ordinal, int limit) {
        return jdbc.query(SYNC_UNIT + """
                  AND (u.plan_id, u.ordinal) > (:plan, :ordinal)
                ORDER BY u.plan_id, u.ordinal LIMIT :limit
                """, new MapSqlParameterSource("plan", planId).addValue("ordinal", ordinal).addValue("limit", limit),
                JdbcReviewRepository::syncUnit);
    }

    /**
     * Records the document the unit's S2 job analysed, once: a unit that already names it keeps it, and one naming another document
     * is an error (the S2 result is fixed by its recorded hash, so the same job can never analyse two). No unit for this S3 job
     * (a job the plan worker did not run) records nothing.
     *
     * @return true when the unit had no document yet and now has this one
     */
    public boolean recordDocument(String s3JobId, ReviewTargetReader.Document document) {
        var params = new MapSqlParameterSource("job", s3JobId).addValue("id", document.documentId())
                .addValue("raw", document.rawVersion()).addValue("version", document.documentVersion());
        if (jdbc.update("""
                UPDATE analysis_plan_units SET s2_document_id = :id, s2_raw_version = :raw, s2_document_version = :version
                 WHERE s3_job_id = :job AND s2_document_id IS NULL
                """, params) == 1) return true;
        boolean other = Boolean.TRUE.equals(jdbc.queryForObject("""
                SELECT EXISTS (SELECT 1 FROM analysis_plan_units WHERE s3_job_id = :job
                                 AND (s2_document_id, s2_raw_version, s2_document_version) <> (:id, :raw, :version))
                """, params, Boolean.class));
        if (other) throw new IllegalStateException("the unit already names another analysed document");
        return false;
    }

    private static SyncUnit syncUnit(ResultSet rs, int rowNumber) throws SQLException {
        return new SyncUnit(rs.getString("plan_id"), rs.getInt("ordinal"), rs.getString("s3_job_id"),
                rs.getString("s3_input_digest"), rs.getString("s2_job_id"), rs.getString("s2_input_digest"),
                rs.getString("s2_result_sha256"));
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

    /** How many intents are still open (pending or blocked) and were created before {@code before}. */
    public long countOpenIntents(Instant before) {
        Long count = jdbc.queryForObject("""
                SELECT count(*) FROM review_decision_intents WHERE status IN ('pending', 'blocked') AND created_at < :before
                """, new MapSqlParameterSource("before", Timestamp.from(before)), Long.class);
        return count == null ? 0 : count;
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
                rs.getBoolean("is_current"), rs.getBoolean("active"));
    }
}
