package com.zoop.graph.exclusion;

import java.nio.charset.StandardCharsets;
import java.util.Collection;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
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

    /**
     * The versions an {@code exclude-query} asks about by default: the active imported version and every imported version after it
     * (by sequence) that is not active, which an activation may still make public. A rolled-back newer version is among them.
     */
    public List<String> exposureTargets() {
        return jdbc.queryForList("""
                SELECT id FROM graph_versions
                 WHERE kind = 'snapshot'
                   AND (active OR sequence > COALESCE((SELECT sequence FROM graph_versions WHERE active), 0))
                 ORDER BY sequence
                """, new MapSqlParameterSource(), String.class);
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

    /** Every target of this version whose latest change is a lift: an operator's decision on that version, which a carry respects. */
    public Set<Target> lifted(String versionId) {
        return new LinkedHashSet<>(jdbc.query(EXCLUDED.replace("c.action = 'exclude'", "c.action = 'lift'"),
                new MapSqlParameterSource("version", versionId),
                (result, index) -> new Target(result.getString("target_kind"), result.getString("target_id"),
                        result.getString("article_version"))));
    }

    /**
     * The latest revision that changed each target of this version, by an operator or by a carry from outside
     * {@code carriedWithin}. A carry from a version in {@code carriedWithin} copied a decision already recorded there, so it is
     * no change of its own for a lift's stale check over that set of versions.
     */
    public Map<Target, Long> lastChanged(String versionId, Collection<String> carriedWithin) {
        Map<Target, Long> last = new HashMap<>();
        jdbc.query("""
                SELECT t.target_kind, t.target_id, t.article_version, MAX(t.revision) AS revision
                FROM disclosure_exclusion_targets t JOIN disclosure_exclusion_changes c ON c.revision = t.revision
                WHERE t.graph_version_id = :version AND NOT (c.cause = 'carried' AND c.base_version_id IN (:within))
                GROUP BY t.target_kind, t.target_id, t.article_version
                """, new MapSqlParameterSource("version", versionId)
                .addValue("within", carriedWithin.isEmpty() ? List.of("") : List.copyOf(carriedWithin)), result -> {
            last.put(new Target(result.getString("target_kind"), result.getString("target_id"),
                    result.getString("article_version")), result.getLong("revision"));
        });
        return last;
    }

    /** A command recorded under this request id: the hash of its request and its stored result. */
    public record Recorded(String requestSha256, byte[] result) {
    }

    public Optional<Recorded> recorded(String requestId) {
        return jdbc.query("SELECT request_sha256, result::text AS result FROM disclosure_exclusion_requests WHERE request_id = :id",
                new MapSqlParameterSource("id", requestId), (result, index) -> new Recorded(result.getString("request_sha256"),
                        result.getString("result").getBytes(StandardCharsets.UTF_8))).stream().findFirst();
    }

    public void insertRequest(String requestId, String requestSha256, String action, long revision, byte[] result) {
        jdbc.update("""
                INSERT INTO disclosure_exclusion_requests (request_id, request_sha256, action, revision, result, recorded_at)
                VALUES (:id, :sha256, :action, :revision, CAST(:result AS jsonb), statement_timestamp())
                """, new MapSqlParameterSource("id", requestId).addValue("sha256", requestSha256).addValue("action", action)
                .addValue("revision", revision).addValue("result", new String(result, StandardCharsets.UTF_8)));
    }

    public long revision() {
        Long max = jdbc.getJdbcTemplate().queryForObject("SELECT COALESCE(MAX(revision), 0) FROM disclosure_exclusion_changes",
                Long.class);
        return max == null ? 0 : max;
    }

    /**
     * The imported ({@code snapshot}) versions after this one in import order, oldest first: what a lift with
     * {@code laterVersions} also covers. Empty when the version is unknown.
     */
    public List<String> laterVersions(String versionId) {
        return jdbc.queryForList("""
                SELECT id FROM graph_versions
                 WHERE kind = 'snapshot' AND sequence > (SELECT sequence FROM graph_versions WHERE id = :id)
                 ORDER BY sequence
                """, new MapSqlParameterSource("id", versionId), String.class);
    }

    /**
     * Appends one change at {@code revision}, stamped with the database clock. {@code reportSha256} is the exposure report's hash
     * of an operator exclude, {@code baseVersionId} the version a carried change was carried from; null otherwise.
     */
    public void insertChange(long revision, String action, String cause, String reportSha256, String baseVersionId, String reason,
            String operator) {
        jdbc.update("""
                INSERT INTO disclosure_exclusion_changes (revision, action, cause, report_sha256, base_version_id, reason, operator,
                    changed_at)
                VALUES (:revision, :action, :cause, :report, :base, :reason, :operator, statement_timestamp())
                """, new MapSqlParameterSource("revision", revision).addValue("action", action).addValue("cause", cause)
                .addValue("report", reportSha256).addValue("base", baseVersionId).addValue("reason", reason)
                .addValue("operator", operator));
    }

    /** The target rows of one change for one version, in one batch. */
    public void insertTargets(long revision, String versionId, List<Target> targets) {
        if (targets.isEmpty()) return;
        jdbc.batchUpdate("""
                INSERT INTO disclosure_exclusion_targets (revision, graph_version_id, target_kind, target_id, article_version)
                VALUES (:revision, :version, :kind, :id, :articleVersion)
                """, targets.stream().map(target -> new MapSqlParameterSource("revision", revision).addValue("version", versionId)
                .addValue("kind", target.kind()).addValue("id", target.id()).addValue("articleVersion", target.articleVersion()))
                .toArray(MapSqlParameterSource[]::new));
    }
}
