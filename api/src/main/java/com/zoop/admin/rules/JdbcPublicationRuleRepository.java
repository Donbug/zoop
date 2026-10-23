package com.zoop.admin.rules;

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

/** {@code publication_rules} and their append-only {@code publication_rule_changes}. */
@Repository
public class JdbcPublicationRuleRepository {
    private static final String COLUMNS = "id, title, summary, default_enabled, enabled, revision, updated_at";

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcPublicationRuleRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public record RuleRow(String id, String title, String summary, boolean defaultEnabled, boolean enabled, long revision,
            Instant updatedAt) {
    }

    public record ChangeRow(long id, String ruleId, long revision, boolean enabled, String reason, String adminEmail,
            Instant changedAt) {
    }

    /** One page of rules in id order, after {@code afterId}. */
    public List<RuleRow> page(String afterId, int limit) {
        return jdbc.query("SELECT " + COLUMNS + """
                 FROM publication_rules
                WHERE CAST(:afterId AS text) IS NULL OR id > :afterId
                ORDER BY id
                LIMIT :limit
                """, new MapSqlParameterSource("afterId", afterId).addValue("limit", limit),
                JdbcPublicationRuleRepository::rule);
    }

    public Optional<RuleRow> find(String id, boolean lock) {
        return jdbc.query("SELECT " + COLUMNS + " FROM publication_rules WHERE id = :id" + (lock ? " FOR UPDATE" : ""),
                new MapSqlParameterSource("id", id), JdbcPublicationRuleRepository::rule).stream().findFirst();
    }

    /** The whole change history of {@code ruleIds} ({@code ReviewRuleOut.history}), newest first within each rule. */
    public List<ChangeRow> history(List<String> ruleIds) {
        if (ruleIds.isEmpty()) return List.of();
        return jdbc.query("""
                SELECT id, rule_id, revision, enabled, reason, admin_email_snapshot, changed_at
                FROM publication_rule_changes
                WHERE rule_id IN (:ids)
                ORDER BY rule_id, revision DESC
                """, new MapSqlParameterSource("ids", ruleIds),
                (rs, n) -> new ChangeRow(rs.getLong("id"), rs.getString("rule_id"), rs.getLong("revision"),
                        rs.getBoolean("enabled"), rs.getString("reason"), rs.getString("admin_email_snapshot"),
                        rs.getTimestamp("changed_at").toInstant()));
    }

    /** The shared publication lock: rule changes, snapshot fixing and graph activation never interleave. */
    public void lockPublication() {
        jdbc.getJdbcTemplate().execute("SELECT pg_advisory_xact_lock(" + JdbcGraphVersionRepository.PUBLICATION_LOCK + ")");
    }

    /** Read after the lock: the app-wide rule counter graph versions and briefings fix as {@code rule_revision}. */
    public long nextLogRevision() {
        Long max = jdbc.getJdbcTemplate().queryForObject(
                "SELECT COALESCE(MAX(log_revision), 0) FROM publication_rule_changes", Long.class);
        return (max == null ? 0 : max) + 1;
    }

    /** Current {@code COALESCE(MAX(global_revision), 0)} (ERD v6 section 27, {@code RuleSwitchResponse.reviewRevision}). */
    public long reviewRevision() {
        Long max = jdbc.getJdbcTemplate().queryForObject(
                "SELECT COALESCE(MAX(global_revision), 0) FROM review_decisions", Long.class);
        return max == null ? 0 : max;
    }

    public void switchRule(String id, long revision, boolean enabled, Instant at) {
        int changed = jdbc.update("""
                UPDATE publication_rules SET enabled = :enabled, revision = :revision, updated_at = :at
                WHERE id = :id AND revision = :revision - 1
                """, new MapSqlParameterSource("id", id).addValue("enabled", enabled).addValue("revision", revision)
                .addValue("at", Timestamp.from(at)));
        if (changed != 1) throw new IllegalStateException("Locked publication rule was not switched");
    }

    public long insertChange(String ruleId, long revision, long logRevision, boolean enabled, String reason, String adminId,
            String adminEmail, Instant at) {
        Long id = jdbc.queryForObject("""
                INSERT INTO publication_rule_changes
                  (rule_id, revision, log_revision, enabled, reason, admin_id, admin_email_snapshot, changed_at)
                VALUES (:ruleId, :revision, :logRevision, :enabled, :reason, :adminId, :adminEmail, :at)
                RETURNING id
                """, new MapSqlParameterSource("ruleId", ruleId).addValue("revision", revision)
                .addValue("logRevision", logRevision).addValue("enabled", enabled).addValue("reason", reason)
                .addValue("adminId", adminId).addValue("adminEmail", adminEmail).addValue("at", Timestamp.from(at)),
                Long.class);
        if (id == null) throw new IllegalStateException("Rule change id was not returned");
        return id;
    }

    private static RuleRow rule(ResultSet rs, int rowNumber) throws SQLException {
        return new RuleRow(rs.getString("id"), rs.getString("title"), rs.getString("summary"), rs.getBoolean("default_enabled"),
                rs.getBoolean("enabled"), rs.getLong("revision"), rs.getTimestamp("updated_at").toInstant());
    }
}
