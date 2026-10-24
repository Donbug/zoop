package com.zoop.graph.read;

import java.util.HashSet;
import java.util.Set;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

/**
 * The exclusion store's read: the targets of one version whose latest change is an {@code exclude}, and the app-wide exclusion
 * revision, in ONE statement and without the publication lock. Changes are numbered MAX+1 under that lock, which is held to the
 * commit, so one statement sees a committed prefix of them and the targets it returns are the state at the revision it returns.
 * Article targets are stored for the readers outside the graph and not returned here.
 */
public class JdbcDisclosureExclusionReader implements DisclosureExclusionReader {
    // The cross join keeps one row (kind NULL) when nothing of the version is excluded.
    private static final String CURRENT = """
            WITH latest AS (
                SELECT DISTINCT ON (t.target_kind, t.target_id, t.article_version) t.target_kind, t.target_id, t.revision
                FROM disclosure_exclusion_targets t
                WHERE t.graph_version_id = :version AND t.target_kind IN ('issue', 'relation', 'evidence')
                ORDER BY t.target_kind, t.target_id, t.article_version, t.revision DESC
            )
            SELECT r.revision, x.target_kind, x.target_id
            FROM (SELECT COALESCE(MAX(revision), 0) AS revision FROM disclosure_exclusion_changes) r
            LEFT JOIN (SELECT l.target_kind, l.target_id FROM latest l
                       JOIN disclosure_exclusion_changes c ON c.revision = l.revision
                       WHERE c.action = 'exclude') x ON true
            """;

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcDisclosureExclusionReader(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public DisclosureExclusions current(String versionId) {
        long[] revision = new long[1];
        Set<String> issues = new HashSet<>();
        Set<String> relations = new HashSet<>();
        Set<String> evidence = new HashSet<>();
        jdbc.query(CURRENT, new MapSqlParameterSource("version", versionId), result -> {
            revision[0] = result.getLong("revision");
            String kind = result.getString("target_kind");
            if (kind == null) return;
            String id = result.getString("target_id");
            switch (kind) {
                case "issue" -> issues.add(id);
                case "relation" -> relations.add(id);
                case "evidence" -> evidence.add(id);
                default -> throw new IllegalStateException("Unknown exclusion target kind");
            }
        });
        return new DisclosureExclusions(revision[0], issues, relations, evidence);
    }
}
