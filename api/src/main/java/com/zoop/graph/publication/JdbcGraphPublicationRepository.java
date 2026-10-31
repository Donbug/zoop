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
