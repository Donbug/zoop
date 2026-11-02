package com.zoop.graph.publication;

import java.util.List;
import java.util.Optional;
import java.util.Set;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcGraphPublicationRepository {
    private final NamedParameterJdbcTemplate jdbc;
    public JdbcGraphPublicationRepository(NamedParameterJdbcTemplate jdbc) { this.jdbc = jdbc; }

    public record Metadata(String versionId, String publicationId, String compositionDigest, String baseVersionId,
            String expectedActiveVersionId, List<String> incomingVersionIds) {
        public Metadata { incomingVersionIds = List.copyOf(incomingVersionIds); }
    }

    public void lockPublication() {
        jdbc.getJdbcTemplate().execute("SELECT pg_advisory_xact_lock(" + JdbcGraphVersionRepository.PUBLICATION_LOCK + ")");
    }

    public Optional<Metadata> find(String versionId) {
        var args = new MapSqlParameterSource("id", versionId);
        var incoming = jdbc.queryForList("SELECT source_version_id FROM graph_publication_inputs WHERE version_id=:id ORDER BY ordinal", args, String.class);
        return jdbc.query("SELECT version_id, publication_id, composition_digest, base_version_id, expected_active_version_id FROM graph_publications WHERE version_id=:id",
                args, (row, index) -> new Metadata(row.getString("version_id"), row.getString("publication_id"), row.getString("composition_digest"),
                    row.getString("base_version_id"), row.getString("expected_active_version_id"), incoming)).stream().findFirst();
    }

    public List<String> publishedVersionsForSources(Set<String> sourceVersionIds) {
        if (sourceVersionIds.isEmpty()) return List.of();
        return jdbc.queryForList("""
                SELECT DISTINCT s.graph_version_id FROM graph_version_sources s
                JOIN graph_activations a ON a.version_id = s.graph_version_id AND a.pointer_changed
                WHERE s.receipt_artifact_id IN (:receipts) ORDER BY s.graph_version_id
                """, new MapSqlParameterSource("receipts", sourceVersionIds.stream().map(id -> "artifact-receipt-" + id).toList()), String.class);
    }

    /**
     * Imported native single-source versions an automatic preparation may add on top of {@code baseVersionId}, oldest first, at most
     * {@code limit}: a staged snapshot that is not a composed publication or a legacy package, has exactly one source, is not one of
     * {@code members} (the base's sources) and comes after the cutoff in import order ({@code sequence}). The cutoff is the newest
     * source the base's composition took in (the base itself when it is not a composition), whoever composed it: a source imported
     * before it that the composition left out was there to choose and stays out, while sources past a preparation's cap, imported while a
     * candidate waited for approval, or imported while an operator wrote a request are still prepared. A source that stops preparation
     * stays the oldest candidate until an operator compose takes it, or a newer source without it.
     */
    public List<String> preparationCandidates(String baseVersionId, Set<String> members, int limit) {
        var args = new MapSqlParameterSource("base", baseVersionId).addValue("members", members.toArray(String[]::new)).addValue("limit", limit);
        return jdbc.queryForList("""
                WITH cutoff AS (
                  SELECT COALESCE((SELECT max(i.sequence) FROM graph_publication_inputs p JOIN graph_versions i ON i.id = p.source_version_id
                                   WHERE p.version_id = b.id), b.sequence) AS sequence
                  FROM graph_versions b WHERE b.id = :base)
                SELECT v.id FROM graph_versions v, cutoff
                WHERE v.kind = 'snapshot'
                  AND v.sequence > cutoff.sequence
                  AND COALESCE(v.source_label, '') NOT LIKE 'legacy-real:%'
                  AND NOT EXISTS (SELECT 1 FROM graph_publications p WHERE p.version_id = v.id)
                  AND (SELECT count(*) FROM graph_version_sources s WHERE s.graph_version_id = v.id) = 1
                  AND NOT (v.id = ANY (CAST(:members AS text[])))
                ORDER BY v.sequence
                LIMIT :limit
                """, args, String.class);
    }

    /** {@code versionIds} that exist, in import order ({@code sequence}). */
    public List<String> importOrder(List<String> versionIds) {
        if (versionIds.isEmpty()) return List.of();
        return jdbc.queryForList("SELECT id FROM graph_versions WHERE id IN (:ids) ORDER BY sequence",
                new MapSqlParameterSource("ids", versionIds), String.class);
    }

    /** Staged publications on {@code baseVersionId} that were never made public, oldest first (earlier or orphaned candidates). */
    public List<String> unpublishedCandidates(String baseVersionId) {
        return jdbc.queryForList("""
                SELECT p.version_id FROM graph_publications p JOIN graph_versions v ON v.id = p.version_id
                WHERE p.base_version_id = :base
                  AND NOT EXISTS (SELECT 1 FROM graph_activations a WHERE a.version_id = p.version_id AND a.pointer_changed)
                ORDER BY v.sequence
                """, new MapSqlParameterSource("base", baseVersionId), String.class);
    }

    public void insert(Metadata metadata) {
        var args = new MapSqlParameterSource("id", metadata.versionId()).addValue("publication", metadata.publicationId())
                .addValue("digest", metadata.compositionDigest()).addValue("base", metadata.baseVersionId()).addValue("expected", metadata.expectedActiveVersionId());
        jdbc.update("INSERT INTO graph_publications(version_id,publication_id,composition_digest,base_version_id,expected_active_version_id) VALUES (:id,:publication,:digest,:base,:expected)", args);
        for (int index = 0; index < metadata.incomingVersionIds().size(); index++) {
            jdbc.update("INSERT INTO graph_publication_inputs(version_id,ordinal,source_version_id) VALUES (:id,:ordinal,:source)",
                    new MapSqlParameterSource("id", metadata.versionId()).addValue("ordinal", index).addValue("source", metadata.incomingVersionIds().get(index)));
        }
    }
}
