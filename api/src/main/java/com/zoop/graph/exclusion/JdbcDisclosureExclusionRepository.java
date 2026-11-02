package com.zoop.graph.exclusion;

import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.Collection;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
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
     * The original imported ({@code snapshot}) versions after this one in import order, oldest first: what a lift with
     * {@code laterVersions} also covers for all its targets. Cumulative publications are left out: their exclusions belong to
     * their original versions, and neither an operator change nor a carry writes to their own id. Empty when the version is
     * unknown.
     */
    public List<String> laterVersions(String versionId) {
        return jdbc.queryForList("""
                SELECT v.id FROM graph_versions v
                 WHERE v.kind = 'snapshot' AND v.sequence > (SELECT sequence FROM graph_versions WHERE id = :id)
                   AND NOT EXISTS (SELECT 1 FROM graph_publications p WHERE p.version_id = v.id)
                 ORDER BY v.sequence
                """, new MapSqlParameterSource("id", versionId), String.class);
    }

    /**
     * The copies of a version's exclusion decisions on other versions. {@code traced}: per version, the targets a copy of the
     * decision was carried to, in the order found; the stale check of a lift with {@code laterVersions} covers them. {@code current}:
     * of those, the targets whose latest change there is still that copy; that lift ends them. A target the operator changed
     * there after the copy is in {@code traced} only: its current exclusion is the operator's own decision.
     */
    public record CarriedCopies(Map<String, Set<Target>> traced, Map<String, Set<Target>> current) {
    }

    /**
     * The copies of this version's latest exclude of each of {@code targets}, followed through carries of those copies: what a
     * lift with {@code laterVersions} also covers for those targets. A carry follows activation order, not import order, so a copy
     * can sit on a version imported before this one. A carry is part of the decision's lineage only when the version it was
     * carried from held the decision's copy at that moment (its latest change of the target before the carry): an exclusion
     * carried from an earlier or a later decision of that version is not this decision. A version whose copy the operator has
     * since changed keeps its own decision, and the copies carried from it before that change are still followed.
     */
    public CarriedCopies carriedCopies(String versionId, Collection<Target> targets) {
        Map<Target, Long> decided = new HashMap<>();
        jdbc.query("""
                SELECT t.target_kind, t.target_id, t.article_version, MAX(t.revision) AS revision
                FROM disclosure_exclusion_targets t JOIN disclosure_exclusion_changes c ON c.revision = t.revision
                WHERE t.graph_version_id = :version AND c.action = 'exclude'
                GROUP BY t.target_kind, t.target_id, t.article_version
                """, new MapSqlParameterSource("version", versionId), result -> {
            Target target = new Target(result.getString("target_kind"), result.getString("target_id"),
                    result.getString("article_version"));
            if (targets.contains(target)) decided.put(target, result.getLong("revision"));
        });
        Map<String, Set<Target>> traced = new LinkedHashMap<>();
        Map<String, Set<Target>> current = new LinkedHashMap<>();
        Set<String> seen = new HashSet<>();
        Deque<Map.Entry<String, Map<Target, Long>>> pending = new ArrayDeque<>();
        if (!decided.isEmpty()) pending.add(Map.entry(versionId, decided));
        while (!pending.isEmpty()) {
            Map.Entry<String, Map<Target, Long>> from = pending.poll();
            Map<String, Map<Target, Long>> copied = new LinkedHashMap<>();
            jdbc.query("""
                    SELECT t.graph_version_id, t.target_kind, t.target_id, t.article_version, t.revision,
                           (SELECT MAX(s.revision) FROM disclosure_exclusion_targets s
                             WHERE s.graph_version_id = :base AND s.target_kind = t.target_kind AND s.target_id = t.target_id
                               AND s.article_version = t.article_version AND s.revision < t.revision) AS source_revision,
                           (SELECT MAX(l.revision) FROM disclosure_exclusion_targets l
                             WHERE l.graph_version_id = t.graph_version_id AND l.target_kind = t.target_kind
                               AND l.target_id = t.target_id AND l.article_version = t.article_version) AS latest_revision
                    FROM disclosure_exclusion_changes c JOIN disclosure_exclusion_targets t ON t.revision = c.revision
                    WHERE c.cause = 'carried' AND c.base_version_id = :base
                    ORDER BY c.revision, t.graph_version_id
                    """, new MapSqlParameterSource("base", from.getKey()), result -> {
                Target target = new Target(result.getString("target_kind"), result.getString("target_id"),
                        result.getString("article_version"));
                Long lineage = from.getValue().get(target);
                String to = result.getString("graph_version_id");
                long revision = result.getLong("revision");
                if (lineage == null || lineage != result.getLong("source_revision") || to.equals(versionId)) return;
                if (!seen.add(to + "\n" + target + "\n" + revision)) return;
                traced.computeIfAbsent(to, id -> new LinkedHashSet<>()).add(target);
                if (revision == result.getLong("latest_revision")) {
                    current.computeIfAbsent(to, id -> new LinkedHashSet<>()).add(target);
                }
                copied.computeIfAbsent(to, id -> new HashMap<>()).put(target, revision);
            });
            copied.forEach((to, found) -> pending.add(Map.entry(to, found)));
        }
        return new CarriedCopies(traced, current);
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
