package com.zoop.admin.review;

import java.sql.Array;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import com.zoop.admin.review.AnalysisCandidates.ReviewDecisionOut;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * Reads of the candidate list and detail over {@code review_targets} (the projection the review-target sync writes) and
 * {@code review_decisions}. A candidate is a current {@code candidate} row; its relations are the current {@code relation} rows
 * of the same S3 job and candidate id.
 */
@Repository
public class JdbcCandidateRepository {
    private static final String CANDIDATE = """
            SELECT t.id, t.source_job_id, t.source_version, t.candidate_id, t.status, t.active, t.issue_id, t.title, t.action,
                   t.target, t.event_time, t.evidence_count, CAST(t.companies AS text) AS companies, t.relation_types,
                   t.reasons, t.updated_at, u.s2_job_id
              FROM review_targets t
              LEFT JOIN analysis_plan_units u ON u.s3_job_id = t.source_job_id
            """;

    /**
     * Whether the current candidate row {@code alias} is the newest analysis of its event: false when another S3 job has a current
     * candidate row for the same AI event ({@code issue_id}, the S2 {@code targetEventId}) whose S3 result was observed later. A
     * re-analysis (a new plan, so a new S2 and S3 job) keeps the older job's rows, which stay decidable and keep their history;
     * the list and the overview show the newest only. Rows without an event id (a new event, a company-to-company relation) have
     * nothing to match across jobs and are always shown. Ties and rows with no plan unit fall back to the S3 job id.
     */
    public static String newestAnalysis(String alias) {
        return """
                NOT EXISTS (SELECT 1 FROM review_targets n
                              LEFT JOIN analysis_plan_units nu ON nu.s3_job_id = n.source_job_id
                              LEFT JOIN analysis_plan_units au ON au.s3_job_id = %1$s.source_job_id
                             WHERE n.target_type = 'candidate' AND n.is_current AND n.issue_id = %1$s.issue_id
                               AND n.source_job_id <> %1$s.source_job_id
                               AND (COALESCE(CAST(nu.s3_checkpoint->>'resultObservedAt' AS timestamptz), '-infinity'),
                                    n.source_job_id)
                                 > (COALESCE(CAST(au.s3_checkpoint->>'resultObservedAt' AS timestamptz), '-infinity'),
                                    %1$s.source_job_id))""".formatted(alias);
    }

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcCandidateRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** One current candidate row; {@code s2JobId} is null when no analyze-plan unit owns the S3 job. */
    public record Candidate(String id, String s3JobId, String sourceVersion, String candidateId, String status,
            boolean active, String issueId, String title, String action, String target, String eventTime,
            Integer evidenceCount, String companiesJson, List<String> relationTypes, List<String> reasons, Instant updatedAt,
            String s2JobId) {
    }

    /** One current relation row of a candidate. */
    public record Relation(String id, String s3JobId, String candidateId, String relationCandidateId, String sourceVersion,
            String sourceRevision, String status, List<String> relationTypes, Integer evidenceCount, long revision,
            boolean operatorApproved) {
    }

    /**
     * The list filters as the contract names them, all optional. {@code shownRelations}/{@code shownEvents} are the published
     * keys ({@link PublishedCandidates.Shown}) and must be set when {@code published} is.
     */
    public record Filter(String status, String decision, Boolean active, Boolean published, String query,
            List<String[]> shownRelations, List<String[]> shownEvents) {
    }

    public List<Candidate> page(Filter filter, Instant afterAt, String afterId, int limit) {
        StringBuilder sql = new StringBuilder(CANDIDATE).append(" WHERE t.target_type = 'candidate' AND t.is_current AND ")
                .append(newestAnalysis("t"));
        MapSqlParameterSource params = new MapSqlParameterSource("limit", limit);
        if (filter.status() != null) {
            sql.append(" AND t.status = :status");
            params.addValue("status", filter.status());
        }
        if (filter.active() != null) {
            sql.append(" AND t.active = :active");
            params.addValue("active", filter.active());
        }
        if (filter.decision() != null) {
            String latest = """
                    (SELECT d.decision FROM review_decisions d JOIN review_targets r ON r.id = d.target_id
                      WHERE r.target_type = 'relation' AND r.is_current AND r.active
                        AND r.source_job_id = t.source_job_id AND r.candidate_id = t.candidate_id
                      ORDER BY d.id DESC LIMIT 1)""";
            if (filter.decision().equals("none")) sql.append(" AND ").append(latest).append(" IS NULL");
            else {
                sql.append(" AND ").append(latest).append(" = :decision");
                params.addValue("decision", filter.decision());
            }
        }
        if (filter.published() != null) {
            sql.append(filter.published() ? " AND (" : " AND NOT (").append("""
                    EXISTS (SELECT 1 FROM review_targets r
                              JOIN unnest(CAST(:relJobs AS text[]), CAST(:relIds AS text[])) AS p(job, id)
                                ON p.job = r.source_job_id AND p.id = r.external_id
                             WHERE r.target_type = 'relation' AND r.is_current AND r.active AND r.source_job_id = t.source_job_id
                               AND r.candidate_id = t.candidate_id)
                    OR EXISTS (SELECT 1 FROM unnest(CAST(:evJobs AS text[]), CAST(:evIds AS text[])) AS e(job, id)
                                WHERE e.job = u.s2_job_id AND e.id = t.candidate_id))""");
            params.addValue("relJobs", column(filter.shownRelations(), 0)).addValue("relIds", column(filter.shownRelations(), 1))
                    .addValue("evJobs", column(filter.shownEvents(), 0)).addValue("evIds", column(filter.shownEvents(), 1));
        }
        if (filter.query() != null) {
            sql.append(" AND ").append("""
                    (t.title ILIKE :q ESCAPE '\\' OR t.candidate_id ILIKE :q ESCAPE '\\'
                     OR t.issue_id ILIKE :q ESCAPE '\\'
                     OR EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(t.companies, '[]'::jsonb)) AS c
                                 WHERE c->>'name' ILIKE :q ESCAPE '\\' OR c->>'sourceId' ILIKE :q ESCAPE '\\'))""");
            params.addValue("q", "%" + filter.query().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%");
        }
        if (afterAt != null) {
            sql.append(" AND (t.updated_at, t.id) < (:afterAt, :afterId)");
            params.addValue("afterAt", Timestamp.from(afterAt)).addValue("afterId", afterId);
        }
        sql.append(" ORDER BY t.updated_at DESC, t.id DESC LIMIT :limit");
        return jdbc.query(sql.toString(), params, JdbcCandidateRepository::candidate);
    }

    public Optional<Candidate> candidate(String id) {
        return jdbc.query(CANDIDATE + " WHERE t.id = :id AND t.target_type = 'candidate' AND t.is_current",
                new MapSqlParameterSource("id", id), JdbcCandidateRepository::candidate).stream().findFirst();
    }

    /**
     * Current relation rows of these candidates still in their job's latest complete reading ({@code active}, set by the sync's
     * markPresentRelations), keyed by candidate row id, in external id order: the ones the candidate's status is derived from.
     */
    public Map<String, List<Relation>> relations(List<Candidate> candidates) {
        Map<String, List<Relation>> byCandidate = new LinkedHashMap<>();
        if (candidates.isEmpty()) return byCandidate;
        Map<String, String> owner = new HashMap<>();
        for (Candidate c : candidates) {
            owner.put(c.s3JobId() + "\n" + c.candidateId(), c.id());
            byCandidate.put(c.id(), new ArrayList<>());
        }
        jdbc.query("""
                SELECT r.id, r.source_job_id, r.candidate_id, r.external_id, r.source_version, r.source_revision, r.status,
                       r.relation_types, r.evidence_count, r.current_revision, r.operator_approved
                  FROM review_targets r
                  JOIN unnest(CAST(:jobs AS text[]), CAST(:ids AS text[])) AS c(job, id)
                    ON c.job = r.source_job_id AND c.id = r.candidate_id
                 WHERE r.target_type = 'relation' AND r.is_current AND r.active
                 ORDER BY r.external_id
                """, new MapSqlParameterSource("jobs", candidates.stream().map(Candidate::s3JobId).toArray(String[]::new))
                .addValue("ids", candidates.stream().map(Candidate::candidateId).toArray(String[]::new)), rs -> {
                    Relation relation = new Relation(rs.getString("id"), rs.getString("source_job_id"),
                            rs.getString("candidate_id"), rs.getString("external_id"), rs.getString("source_version"),
                            rs.getString("source_revision"), rs.getString("status"), strings(rs.getArray("relation_types")),
                            (Integer) rs.getObject("evidence_count"), rs.getLong("current_revision"),
                            rs.getBoolean("operator_approved"));
                    byCandidate.get(owner.get(relation.s3JobId() + "\n" + relation.candidateId())).add(relation);
                });
        return byCandidate;
    }

    /** All decisions on these target rows, newest first, keyed by target row id. */
    public Map<String, List<ReviewDecisionOut>> decisions(List<String> targetIds) {
        Map<String, List<ReviewDecisionOut>> byTarget = new LinkedHashMap<>();
        if (targetIds.isEmpty()) return byTarget;
        jdbc.query("""
                SELECT d.id, d.target_id, t.target_type, t.external_id, d.decision, d.reason, d.admin_email_snapshot,
                       d.decided_at, d.revision, d.origin
                  FROM review_decisions d JOIN review_targets t ON t.id = d.target_id
                 WHERE d.target_id IN (:ids)
                 ORDER BY d.id DESC
                """, new MapSqlParameterSource("ids", targetIds), rs -> {
                    byTarget.computeIfAbsent(rs.getString("target_id"), key -> new ArrayList<>()).add(new ReviewDecisionOut(
                            rs.getLong("id"), rs.getString("target_type"), rs.getString("external_id"), rs.getString("decision"),
                            rs.getString("reason"), email(rs.getString("admin_email_snapshot")),
                            rs.getTimestamp("decided_at").toInstant(), rs.getLong("revision"), rs.getString("origin")));
                });
        return byTarget;
    }

    /** Current candidates per status (active ones) and the inactive ones under {@code inactive}, newest analysis only. */
    public Map<String, Integer> counts() {
        Map<String, Integer> counts = new LinkedHashMap<>(Map.of("ALLOW", 0, "HOLD", 0, "REJECT", 0, "inactive", 0));
        jdbc.query("""
                SELECT CASE WHEN active THEN status ELSE 'inactive' END AS bucket, count(*) AS n
                  FROM review_targets t WHERE target_type = 'candidate' AND is_current AND %s GROUP BY 1
                """.formatted(newestAnalysis("t")), rs -> {
                    counts.put(rs.getString("bucket"), rs.getInt("n"));
                });
        return counts;
    }

    /** A decision without an admin ({@code snapshot-migration}) has no email; it shows the system marker, as activations do. */
    private static String email(String snapshot) {
        return snapshot == null ? "system" : snapshot;
    }

    private static String[] column(List<String[]> pairs, int index) {
        return pairs.stream().map(pair -> pair[index]).toArray(String[]::new);
    }

    private static List<String> strings(Array array) throws SQLException {
        if (array == null) return List.of();
        return List.of((String[]) array.getArray());
    }

    private static Candidate candidate(ResultSet rs, int rowNumber) throws SQLException {
        return new Candidate(rs.getString("id"), rs.getString("source_job_id"), rs.getString("source_version"),
                rs.getString("candidate_id"), rs.getString("status"), rs.getBoolean("active"), rs.getString("issue_id"),
                rs.getString("title"), rs.getString("action"), rs.getString("target"), rs.getString("event_time"),
                (Integer) rs.getObject("evidence_count"), rs.getString("companies"), strings(rs.getArray("relation_types")),
                strings(rs.getArray("reasons")), rs.getTimestamp("updated_at").toInstant(), rs.getString("s2_job_id"));
    }
}
