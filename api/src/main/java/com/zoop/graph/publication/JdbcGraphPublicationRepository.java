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
     * Imported single-source versions an automatic preparation may add, oldest first: a staged snapshot that is not a composed
     * publication, has exactly one source, is not one of {@code members} (the active version's sources) and was imported after the
     * last pointer change, so a source an operator left out of the published composition is not added back. Activation is manual,
     * so every pointer change is a person's decision.
     */
    public List<String> preparationCandidates(Set<String> members) {
        return jdbc.queryForList("""
                SELECT v.id FROM graph_versions v
                WHERE v.kind = 'snapshot'
                  AND NOT EXISTS (SELECT 1 FROM graph_publications p WHERE p.version_id = v.id)
                  AND (SELECT count(*) FROM graph_version_sources s WHERE s.graph_version_id = v.id) = 1
                  AND NOT (v.id = ANY (CAST(:members AS text[])))
                  AND v.created_at > COALESCE((SELECT max(a.activated_at) FROM graph_activations a WHERE a.pointer_changed), '-infinity'::timestamptz)
                ORDER BY v.sequence
                """, new MapSqlParameterSource("members", members.toArray(String[]::new)), String.class);
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
