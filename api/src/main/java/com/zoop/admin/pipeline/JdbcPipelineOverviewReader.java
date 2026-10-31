package com.zoop.admin.pipeline;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

import com.zoop.admin.pipeline.PipelineOverviewResponse.CandidateCounts;
import com.zoop.admin.review.JdbcCandidateRepository;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/** The app-side counts behind {@code getPipelineOverview}: review targets, decisions and graph versions. */
@Repository
public class JdbcPipelineOverviewReader {
    private final NamedParameterJdbcTemplate jdbc;

    public JdbcPipelineOverviewReader(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** Current candidate targets, newest analysis of each event only; the status counts are of the active ones only. */
    public CandidateCounts candidates() {
        return jdbc.getJdbcTemplate().queryForObject("""
                SELECT count(*) AS total, count(*) FILTER (WHERE active) AS active, count(*) FILTER (WHERE NOT active) AS inactive,
                       count(*) FILTER (WHERE active AND status = 'ALLOW') AS allow,
                       count(*) FILTER (WHERE active AND status = 'HOLD') AS hold,
                       count(*) FILTER (WHERE active AND status = 'REJECT') AS reject
                FROM review_targets t WHERE target_type = 'candidate' AND is_current AND %s
                """.formatted(JdbcCandidateRepository.newestAnalysis("t")), (rs, row) -> new CandidateCounts(rs.getLong("total"), rs.getLong("active"), rs.getLong("inactive"),
                rs.getLong("allow"), rs.getLong("hold"), rs.getLong("reject")));
    }

    public record Decisions(long revision, long total, long allowed, long rejected, long holdPending) {
    }

    /**
     * The administrators' decisions ({@code origin='admin'}; a migrated decision is not a review) and the HOLD relations still
     * waiting for one (active, current, under the newest analysis of their event). {@code revision} is the app-wide global revision, whatever the origin.
     */
    public Decisions decisions() {
        return jdbc.getJdbcTemplate().queryForObject("""
                SELECT COALESCE((SELECT max(global_revision) FROM review_decisions), 0) AS revision,
                       (SELECT count(*) FROM review_decisions WHERE origin = 'admin') AS total,
                       (SELECT count(*) FROM review_decisions WHERE origin = 'admin' AND decision = 'allow') AS allowed,
                       (SELECT count(*) FROM review_decisions WHERE origin = 'admin' AND decision = 'reject') AS rejected,
                       (SELECT count(*) FROM review_targets r
                         WHERE r.target_type = 'relation' AND r.is_current AND r.active AND r.status = 'HOLD'
                           AND NOT EXISTS (SELECT 1 FROM review_targets t
                                            WHERE t.target_type = 'candidate' AND t.is_current
                                              AND t.source_job_id = r.source_job_id AND t.candidate_id = r.candidate_id
                                              AND NOT %s)) AS hold_pending
                """.formatted(JdbcCandidateRepository.newestAnalysis("t")), (rs, row) -> new Decisions(rs.getLong("revision"), rs.getLong("total"), rs.getLong("allowed"),
                rs.getLong("rejected"), rs.getLong("hold_pending")));
    }

    /** {@code graphDbStatus} is the projection state recorded with the version (unchecked text); the app never updates it. */
    public record ActiveVersion(String id, String policyVersion, long issues, long relations, long articles,
            String graphDbStatus) {
    }

    public Optional<ActiveVersion> activeVersion() {
        return jdbc.getJdbcTemplate().query("""
                SELECT id, policy_version, issue_count, relation_count, article_count,
                       graph_db_state->>'status' AS graph_db_status
                FROM graph_versions WHERE active
                """, (rs, row) -> new ActiveVersion(rs.getString("id"), rs.getString("policy_version"), rs.getLong("issue_count"),
                rs.getLong("relation_count"), rs.getLong("article_count"), rs.getString("graph_db_status")))
                .stream().findFirst();
    }

    /** The most recently imported version (import order), active or not. */
    public Optional<String> latestImportedVersionId() {
        return jdbc.getJdbcTemplate().queryForList("""
                SELECT id FROM graph_versions WHERE kind = 'snapshot' ORDER BY sequence DESC LIMIT 1
                """, String.class).stream().findFirst();
    }

    /**
     * The status counts of the current, active relation targets of each plan's S3 jobs ({@code ALLOW}/{@code HOLD}/
     * {@code REJECT} → count); a plan whose results produced no target yet has no entry.
     */
    public Map<String, Map<String, Long>> relationStatusesByPlan(List<String> planIds) {
        if (planIds.isEmpty()) return Map.of();
        return jdbc.query("""
                SELECT u.plan_id, t.status, count(*) AS n
                FROM analysis_plan_units u
                JOIN review_targets t ON t.source_job_id = u.s3_job_id
                WHERE u.plan_id IN (:plans) AND t.target_type = 'relation' AND t.is_current AND t.active
                GROUP BY u.plan_id, t.status
                """, new MapSqlParameterSource("plans", planIds), (rs, row) -> new Object[] {
                rs.getString("plan_id"), rs.getString("status"), rs.getLong("n")}).stream()
                .collect(Collectors.groupingBy(r -> (String) r[0],
                        Collectors.toMap(r -> (String) r[1], r -> (Long) r[2])));
    }
}
