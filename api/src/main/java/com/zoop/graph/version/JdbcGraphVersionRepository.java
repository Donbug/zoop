package com.zoop.graph.version;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.function.Consumer;
import java.util.function.Supplier;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

@Repository
public class JdbcGraphVersionRepository implements GraphVersionRepository {
    /**
     * Shared publication lock (ERD v6 section 24): pointer changes and their history are serialized, and review decisions
     * (global revision) take the same lock.
     */
    public static final long PUBLICATION_LOCK = 0x7a6f6f7067726170L;
    private static final String SELECT = """
            SELECT v.id, v.sequence, v.kind, v.snapshot_artifact_id, a.storage_uri, a.sha256, v.active
            FROM graph_versions v JOIN artifacts a ON a.id = v.snapshot_artifact_id
            """;

    private final NamedParameterJdbcTemplate jdbc;
    private final Clock clock;

    public JdbcGraphVersionRepository(NamedParameterJdbcTemplate jdbc, Clock clock) {
        this.jdbc = jdbc;
        this.clock = clock;
    }

    @Override
    public Optional<GraphVersionRecord> find(String versionId) {
        return first(jdbc.query(SELECT + "WHERE v.id = :id", new MapSqlParameterSource("id", versionId),
                JdbcGraphVersionRepository::row));
    }

    @Override
    public Optional<GraphVersionRecord> active() {
        return first(jdbc.query(SELECT + "WHERE v.active", JdbcGraphVersionRepository::row));
    }

    @Override
    public Optional<String> activeVersionIdAt(Instant asOf) {
        return first(jdbc.queryForList("""
                SELECT version_id FROM graph_activations
                WHERE pointer_changed AND activated_at <= :asOf
                ORDER BY activated_at DESC, id DESC LIMIT 1
                """, new MapSqlParameterSource("asOf", Timestamp.from(asOf)), String.class));
    }

    @Override
    public boolean everActivated(String versionId) {
        return Boolean.TRUE.equals(jdbc.queryForObject("""
                SELECT EXISTS (SELECT 1 FROM graph_activations WHERE version_id = :id AND pointer_changed)
                """, new MapSqlParameterSource("id", versionId), Boolean.class));
    }

    @Override
    public Optional<Instant> firstActivatedAt(String versionId) {
        return jdbc.query("""
                SELECT min(activated_at) AS at FROM graph_activations WHERE version_id = :id AND pointer_changed
                """, new MapSqlParameterSource("id", versionId), (rs, n) -> rs.getTimestamp("at")).stream()
                .filter(Objects::nonNull).map(Timestamp::toInstant).findFirst();
    }

    @Override
    public Optional<String> previousVersionId(String versionId, Instant at) {
        return first(jdbc.queryForList("""
                SELECT previous_version_id FROM graph_activations
                WHERE version_id = :id AND pointer_changed AND activated_at <= :at AND previous_version_id IS NOT NULL
                  AND previous_version_id <> version_id
                ORDER BY activated_at DESC, id DESC LIMIT 1
                """, new MapSqlParameterSource("id", versionId).addValue("at", Timestamp.from(at)), String.class));
    }

    /** True when any non-fixture (imported) version exists; fixture seeding must never move such a pointer. */
    public boolean hasNonFixtureVersions() {
        return Boolean.TRUE.equals(jdbc.queryForObject(
                "SELECT EXISTS (SELECT 1 FROM graph_versions WHERE kind <> 'fixture')",
                new MapSqlParameterSource(), Boolean.class));
    }

    /**
     * Removes every synthetic fixture version, its activations and artifacts, under the publication lock. Only for a
     * fixture-only database whose bundled fixtures changed; refused when imported versions exist.
     */
    @Transactional
    public int resetFixtures() {
        jdbc.getJdbcTemplate().execute("SELECT pg_advisory_xact_lock(" + PUBLICATION_LOCK + ")");
        if (hasNonFixtureVersions()) throw new IllegalStateException("imported graph versions exist; fixtures are not reset");
        var none = new MapSqlParameterSource();
        jdbc.update("DELETE FROM graph_activations", none);
        List<String> artifacts = jdbc.queryForList("SELECT snapshot_artifact_id FROM graph_versions", none, String.class);
        int removed = jdbc.update("DELETE FROM graph_versions", none);
        if (!artifacts.isEmpty()) {
            jdbc.update("DELETE FROM artifacts WHERE id IN (:ids)", new MapSqlParameterSource("ids", artifacts));
        }
        return removed;
    }

    /**
     * Registers an immutable snapshot artifact and its version, then makes it the active pointer, all under the
     * publication lock in one transaction. Re-registering the same id with the same SHA-256 is a no-op; a different
     * hash for an existing id is refused instead of overwritten.
     */
    @Transactional
    public RegisterOutcome registerSystemVersion(NewGraphVersion version, String reason, Instant at) {
        jdbc.getJdbcTemplate().execute("SELECT pg_advisory_xact_lock(" + PUBLICATION_LOCK + ")");
        Optional<GraphVersionRecord> existing = find(version.id());
        if (existing.isPresent()) {
            if (!existing.get().snapshotSha256().equals(version.snapshotSha256())) {
                throw new GraphVersionConflictException(version.id());
            }
            return RegisterOutcome.UNCHANGED;
        }
        MapSqlParameterSource p = new MapSqlParameterSource()
                .addValue("artifactId", version.snapshotArtifactId())
                .addValue("uri", version.snapshotStorageUri())
                .addValue("sha", version.snapshotSha256())
                .addValue("bytes", version.snapshotBytes())
                .addValue("at", Timestamp.from(at))
                .addValue("id", version.id())
                .addValue("kind", version.kind())
                .addValue("label", version.sourceLabel())
                .addValue("issues", version.issueCount())
                .addValue("relations", version.relationCount())
                .addValue("articles", version.articleCount())
                .addValue("reason", reason);
        jdbc.update("""
                INSERT INTO artifacts (id, kind, storage_uri, sha256, bytes, media_type, created_at)
                VALUES (:artifactId, 'graph_snapshot', :uri, :sha, :bytes, 'application/json', :at)
                """, p);
        jdbc.update("""
                INSERT INTO graph_versions (id, sequence, kind, created_at, published_at, created_by, reason, source_label,
                    issue_count, relation_count, article_count, snapshot_artifact_id, review_revision, active)
                VALUES (:id, (SELECT COALESCE(MAX(sequence), 0) + 1 FROM graph_versions), :kind, :at, :at, 'system',
                    :reason, :label, :issues, :relations, :articles, :artifactId, 0, false)
                """, p);
        activateLocked(version.id(), "seed", null, "system", reason, at);
        return RegisterOutcome.REGISTERED;
    }

    /** Moves the pointer under the publication lock. Re-activating the current version records pointer_changed=false. */
    @Transactional
    public void activateSystem(String versionId, String reason, Instant at) {
        jdbc.getJdbcTemplate().execute("SELECT pg_advisory_xact_lock(" + PUBLICATION_LOCK + ")");
        if (find(versionId).isEmpty()) throw new IllegalArgumentException("Unknown graph version " + versionId);
        activateLocked(versionId, "activate", null, "system", reason, at);
    }

    /**
     * Moves the pointer for an administrator under the publication lock. When the current pointer is not
     * {@code expectedActiveVersionId} (null: none active) another change won the race: 409. The caller's current-eligibility
     * checks then run inside the lock and the same transaction: {@code publishable} runs the slow, time-independent part and
     * returns the part that depends on time. The activation time is read only after the slow part, that last part judges the
     * version at exactly that time (a grant expiring meanwhile is refused), and the same time stamps the history, the first
     * {@code published_at} and the caller's audit. Either part throws to keep the old pointer. So a later asOf never selects a
     * version before it was really public. Unknown ids are the caller's 404.
     */
    @Transactional
    public Activation activateByAdmin(String versionId, String expectedActiveVersionId, String adminId,
            String adminEmail, String reason, String mode, Supplier<Consumer<Instant>> publishable) {
        jdbc.getJdbcTemplate().execute("SELECT pg_advisory_xact_lock(" + PUBLICATION_LOCK + ")");
        GraphVersionRecord target = find(versionId)
                .orElseThrow(() -> new IllegalArgumentException("Unknown graph version " + versionId));
        Optional<GraphVersionRecord> current = active();
        if (!Objects.equals(expectedActiveVersionId, current.map(GraphVersionRecord::id).orElse(null))) {
            throw new CustomException(ErrorCode.REVISION_CONFLICT);
        }
        requireActivationMode(target, current, mode);
        return activateChecked(versionId, adminId, adminEmail, reason, publishable);
    }

    /** The imported ({@code snapshot}) version that was most recently made the public pointer, active or not. */
    public Optional<String> lastActivatedImported() {
        return first(jdbc.queryForList("""
                SELECT v.id FROM graph_activations g JOIN graph_versions v ON v.id = g.version_id
                 WHERE g.pointer_changed AND v.kind = 'snapshot'
                 ORDER BY g.activated_at DESC, g.id DESC LIMIT 1
                """, new MapSqlParameterSource(), String.class));
    }

    private void requireActivationMode(GraphVersionRecord target, Optional<GraphVersionRecord> current, String mode) {
        if ("rollback".equals(mode)) {
            if (!everActivated(target.id())) throw new CustomException(ErrorCode.INVALID_REQUEST);
            return;
        }
        if (!"forward".equals(mode)) throw new CustomException(ErrorCode.INVALID_REQUEST);
        String currentId = current.map(GraphVersionRecord::id).orElse(null);
        if (target.id().equals(currentId)) return;
        if (!"fixture".equals(target.kind()) && everActivated(target.id())) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        Optional<PublicationBasis> basis = first(jdbc.query("""
                SELECT base_version_id, expected_active_version_id FROM graph_publications WHERE version_id = :id
                """, new MapSqlParameterSource("id", target.id()), (rs, row) ->
                new PublicationBasis(rs.getString("base_version_id"), rs.getString("expected_active_version_id"))));
        boolean realBase = current.filter(version -> !"fixture".equals(version.kind())).isPresent();
        if (basis.isEmpty()) {
            if (realBase) throw new CustomException(ErrorCode.REVISION_CONFLICT);
            return;
        }
        PublicationBasis candidate = basis.get();
        if (!Objects.equals(candidate.expectedActiveVersionId(), currentId)
                || !Objects.equals(candidate.baseVersionId(), realBase ? currentId : null)) {
            throw new CustomException(ErrorCode.REVISION_CONFLICT);
        }
    }

    private record PublicationBasis(String baseVersionId, String expectedActiveVersionId) { }

    /**
     * The newest automatically eligible original native version imported at or after {@code since}, while the current pointer
     * is null or a fixture. Cumulative publications and legacy inputs require explicit administrator activation.
     * Imports staged before the last administrator pointer change remain ineligible.
     */
    public Optional<GraphVersionRecord> autoActivationCandidate(Instant since) {
        return first(jdbc.query(SELECT + """
                WHERE v.kind = 'snapshot' AND v.created_at >= :since
                  AND COALESCE(v.source_label, '') NOT LIKE 'legacy-real:%'
                  AND NOT EXISTS (SELECT 1 FROM graph_publications p WHERE p.version_id = v.id)
                  AND NOT EXISTS (SELECT 1 FROM graph_versions c WHERE c.active AND c.kind <> 'fixture')
                  AND NOT EXISTS (SELECT 1 FROM graph_activations g WHERE g.version_id = v.id AND g.pointer_changed)
                  AND v.sequence > COALESCE((SELECT c.sequence FROM graph_versions c WHERE c.active), 0)
                  AND NOT EXISTS (
                      SELECT 1 FROM (SELECT actor_kind, activated_at FROM graph_activations WHERE pointer_changed
                                     ORDER BY activated_at DESC, id DESC LIMIT 1) last
                      WHERE last.actor_kind = 'admin' AND v.created_at <= last.activated_at)
                ORDER BY v.sequence DESC LIMIT 1
                """, new MapSqlParameterSource("since", Timestamp.from(since)), JdbcGraphVersionRepository::row));
    }

    /**
     * The automatic activation after an import: {@link #activateByAdmin}'s order (lock, checks, activation time, last check,
     * pointer, {@code published_at}) for the system actor, but only while {@code versionId} is still
     * {@link #autoActivationCandidate the candidate} and the pointer is still {@code expectedActiveVersionId}. Otherwise another
     * activation or a newer import won and nothing changes (empty).
     */
    @Transactional
    public Optional<Activation> activateBySystem(String versionId, String expectedActiveVersionId, Instant since,
            String reason, Supplier<Consumer<Instant>> publishable) {
        jdbc.getJdbcTemplate().execute("SELECT pg_advisory_xact_lock(" + PUBLICATION_LOCK + ")");
        if (!Objects.equals(expectedActiveVersionId, active().map(GraphVersionRecord::id).orElse(null))
                || !autoActivationCandidate(since).map(GraphVersionRecord::id).filter(versionId::equals).isPresent()) {
            return Optional.empty();
        }
        return Optional.of(activateChecked(versionId, null, "system", reason, publishable));
    }

    /**
     * The shared tail of both activations, under the publication lock the caller holds: the slow checks, then the activation time,
     * then the last check at that time, the pointer, the history and the first {@code published_at}, all at that one time.
     */
    private Activation activateChecked(String versionId, String adminId, String adminEmail, String reason,
            Supplier<Consumer<Instant>> publishable) {
        Consumer<Instant> atActivation = publishable.get();
        Instant at = clock.instant();
        atActivation.accept(at);
        Activation activation = activateLocked(versionId, "activate", adminId, adminEmail, reason, at);
        if (activation.pointerChanged()) {
            jdbc.update("UPDATE graph_versions SET published_at = :at WHERE id = :id AND published_at IS NULL",
                    new MapSqlParameterSource("id", versionId).addValue("at", Timestamp.from(at)));
        }
        return activation;
    }

    private Activation activateLocked(String versionId, String action, String adminId, String adminEmail,
            String reason, Instant at) {
        String previous = active().map(GraphVersionRecord::id).orElse(null);
        boolean changed = !versionId.equals(previous);
        if (changed) {
            jdbc.update("UPDATE graph_versions SET active = false WHERE active", new MapSqlParameterSource());
            jdbc.update("UPDATE graph_versions SET active = true WHERE id = :id", new MapSqlParameterSource("id", versionId));
        }
        jdbc.update("""
                INSERT INTO graph_activations (version_id, previous_version_id, action, actor_kind, pointer_changed,
                    admin_id, admin_email_snapshot, reason, activated_at)
                VALUES (:id, :previous, :action, :actorKind, :changed, :adminId, :email, :reason, :at)
                """, new MapSqlParameterSource().addValue("id", versionId).addValue("previous", previous)
                .addValue("action", action).addValue("actorKind", adminId == null ? "system" : "admin")
                .addValue("changed", changed).addValue("adminId", adminId).addValue("email", adminEmail)
                .addValue("reason", reason).addValue("at", Timestamp.from(at)));
        return new Activation(previous, changed, at);
    }

    private static GraphVersionRecord row(ResultSet rs, int rowNumber) throws SQLException {
        return new GraphVersionRecord(rs.getString("id"), rs.getLong("sequence"), rs.getString("kind"),
                rs.getString("snapshot_artifact_id"), rs.getString("storage_uri"), rs.getString("sha256"),
                rs.getBoolean("active"));
    }

    private static <T> Optional<T> first(List<T> rows) {
        return rows.stream().findFirst();
    }

    public enum RegisterOutcome { REGISTERED, UNCHANGED }

    public record Activation(String previousVersionId, boolean pointerChanged, Instant activatedAt) { }

    public record NewGraphVersion(String id, String kind, String sourceLabel, String snapshotArtifactId,
            String snapshotStorageUri, String snapshotSha256, long snapshotBytes, long issueCount, long relationCount,
            long articleCount) { }
}
