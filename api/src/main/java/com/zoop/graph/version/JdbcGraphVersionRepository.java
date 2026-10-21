package com.zoop.graph.version;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

@Repository
public class JdbcGraphVersionRepository implements GraphVersionRepository {
    /** Shared publication lock (ERD v6 section 24): pointer changes and their history are serialized. */
    static final long PUBLICATION_LOCK = 0x7a6f6f7067726170L;
    private static final String SELECT = """
            SELECT v.id, v.sequence, v.kind, v.snapshot_artifact_id, a.storage_uri, a.sha256, v.active
            FROM graph_versions v JOIN artifacts a ON a.id = v.snapshot_artifact_id
            """;

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcGraphVersionRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
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
     * Moves the pointer for an administrator under the publication lock; the caller has already verified the version's
     * snapshot. The first pointer change also stamps {@code published_at}. Unknown ids are the caller's 404. When the
     * current pointer is not {@code expectedActiveVersionId} (null: none active) another change won the race: 409.
     */
    @Transactional
    public Activation activateByAdmin(String versionId, String expectedActiveVersionId, String adminId,
            String adminEmail, String reason, Instant at) {
        jdbc.getJdbcTemplate().execute("SELECT pg_advisory_xact_lock(" + PUBLICATION_LOCK + ")");
        if (find(versionId).isEmpty()) throw new IllegalArgumentException("Unknown graph version " + versionId);
        if (!Objects.equals(expectedActiveVersionId, active().map(GraphVersionRecord::id).orElse(null))) {
            throw new CustomException(ErrorCode.REVISION_CONFLICT);
        }
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
        return new Activation(previous, changed);
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

    public record Activation(String previousVersionId, boolean pointerChanged) { }

    public record NewGraphVersion(String id, String kind, String sourceLabel, String snapshotArtifactId,
            String snapshotStorageUri, String snapshotSha256, long snapshotBytes, long issueCount, long relationCount,
            long articleCount) { }
}
