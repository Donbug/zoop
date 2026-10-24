package com.zoop.graph.exclusion;

import java.util.LinkedHashSet;
import java.util.Optional;
import java.util.Set;

import com.zoop.graph.exclusion.ExclusionRequest.Target;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

/**
 * The write side of {@code disclosure_exclusion_*} (the read of the public API is {@code JdbcDisclosureExclusionReader}). Every
 * method runs inside the caller's transaction; a change is written only under {@link #lockPublication()}.
 */
public class JdbcDisclosureExclusionRepository {
    private static final String EXCLUDED = """
            SELECT l.target_kind, l.target_id, l.article_version
            FROM (SELECT DISTINCT ON (target_kind, target_id, article_version) target_kind, target_id, article_version, revision
                  FROM disclosure_exclusion_targets
                  WHERE graph_version_id = :version
                  ORDER BY target_kind, target_id, article_version, revision DESC) l
            JOIN disclosure_exclusion_changes c ON c.revision = l.revision
            WHERE c.action = 'exclude'
            """;

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcDisclosureExclusionRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** The shared publication lock: exclusion changes, rule switches, review decisions and activation never interleave. */
    public void lockPublication() {
        jdbc.getJdbcTemplate().execute("SELECT pg_advisory_xact_lock(" + JdbcGraphVersionRepository.PUBLICATION_LOCK + ")");
    }

    /** The {@code kind} of a graph version ({@code snapshot} or {@code fixture}), or empty when there is none. */
    public Optional<String> versionKind(String versionId) {
        return jdbc.queryForList("SELECT kind FROM graph_versions WHERE id = :id", new MapSqlParameterSource("id", versionId),
                String.class).stream().findFirst();
    }

    /** Every target of this version whose latest change is an exclude, articles included. */
    public Set<Target> excluded(String versionId) {
        return new LinkedHashSet<>(jdbc.query(EXCLUDED, new MapSqlParameterSource("version", versionId),
                (result, index) -> new Target(result.getString("target_kind"), result.getString("target_id"),
                        result.getString("article_version"))));
    }

    public long revision() {
        Long max = jdbc.getJdbcTemplate().queryForObject("SELECT COALESCE(MAX(revision), 0) FROM disclosure_exclusion_changes",
                Long.class);
        return max == null ? 0 : max;
    }

    /** Appends one change at {@code revision}, stamped with the database clock. */
    public void insertChange(long revision, String action, String cause, String reportSha256, String reason, String operator) {
        jdbc.update("""
                INSERT INTO disclosure_exclusion_changes (revision, action, cause, report_sha256, reason, operator, changed_at)
                VALUES (:revision, :action, :cause, :report, :reason, :operator, statement_timestamp())
                """, new MapSqlParameterSource("revision", revision).addValue("action", action).addValue("cause", cause)
                .addValue("report", reportSha256).addValue("reason", reason).addValue("operator", operator));
    }

    public void insertTarget(long revision, String versionId, Target target) {
        jdbc.update("""
                INSERT INTO disclosure_exclusion_targets (revision, graph_version_id, target_kind, target_id, article_version)
                VALUES (:revision, :version, :kind, :id, :articleVersion)
                """, new MapSqlParameterSource("revision", revision).addValue("version", versionId)
                .addValue("kind", target.kind()).addValue("id", target.id()).addValue("articleVersion", target.articleVersion()));
    }
}
