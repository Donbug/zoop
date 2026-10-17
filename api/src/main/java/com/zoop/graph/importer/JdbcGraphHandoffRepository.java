package com.zoop.graph.importer;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Collection;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

import com.zoop.common.json.StrictJson;
import com.zoop.document.analysis.repository.DocumentAnalysisRepository;
import com.zoop.document.analysis.repository.EvidenceRow;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * The JDBC statements of {@link GraphHandoffRepository}. Evidence is WRITTEN by the document analysis repository, so a graph
 * evidence row is exactly the row shape and the verification convention of the existing evidence table; it is READ by a statement
 * of its own that returns every column deciding sameness (the analysis read leaves out the kind, the unit, the summary link and
 * the verification flag). The version insert never touches {@code active}, {@code graph_activations} or {@code published_at}.
 */
@Repository
public class JdbcGraphHandoffRepository implements GraphHandoffRepository {
    private static final String COMPANIES = "SELECT id, name FROM companies WHERE id IN (:ids)";
    private static final String FIND_EVIDENCE = """
            SELECT e.id, e.article_id, e.article_version, e.text_artifact_id, e.summary_analysis_id, e.quote, e.start_offset,
                   e.end_offset, e.offset_unit, e.input_kind, CAST(e.raw_locator_ids AS text) AS raw_locator_ids,
                   e.quote_verified, e.verification_artifact_id, e.verified_at, e.created_at, a.kind AS verification_kind
            FROM evidence e LEFT JOIN artifacts a ON a.id = e.verification_artifact_id
            WHERE e.id = :id
            """;
    private static final String FIND_VERSION = """
            SELECT id, kind, active, snapshot_artifact_id, created_by
            FROM graph_versions
            WHERE id = :id
            """;
    private static final String INSERT_VERSION = """
            INSERT INTO graph_versions (id, sequence, kind, created_at, created_by, reason, source_label, policy_version,
                issue_count, relation_count, article_count, snapshot_artifact_id, review_revision, active)
            VALUES (:id, (SELECT COALESCE(MAX(sequence), 0) + 1 FROM graph_versions), 'snapshot', :createdAt, :createdBy,
                :reason, :sourceLabel, :policyVersion, :issues, :relations, :articles, :artifactId, 0, false)
            """;

    private final NamedParameterJdbcTemplate jdbc;
    private final DocumentAnalysisRepository analysis;

    public JdbcGraphHandoffRepository(NamedParameterJdbcTemplate jdbc, DocumentAnalysisRepository analysis) {
        this.jdbc = jdbc;
        this.analysis = analysis;
    }

    @Override
    public Map<String, CompanyRow> companies(Collection<String> ids) {
        Map<String, CompanyRow> rows = new HashMap<>();
        if (ids.isEmpty()) {
            return rows;
        }
        jdbc.query(COMPANIES, new MapSqlParameterSource("ids", ids), (result, index) -> {
            CompanyRow row = new CompanyRow(result.getString("id"), result.getString("name"));
            rows.put(row.id(), row);
            return row;
        });
        return rows;
    }

    @Override
    public Optional<StoredEvidence> findEvidence(String id) {
        return jdbc.query(FIND_EVIDENCE, new MapSqlParameterSource("id", id), (result, index) -> stored(result)).stream()
                .findFirst();
    }

    private static StoredEvidence stored(ResultSet result) throws SQLException {
        boolean verified = result.getBoolean("quote_verified");
        Boolean quoteVerified = result.wasNull() ? null : verified;
        EvidenceRow row = new EvidenceRow(result.getString("id"), result.getString("article_id"),
                result.getString("article_version"), result.getString("text_artifact_id"), result.getString("quote"),
                result.getLong("start_offset"), result.getLong("end_offset"),
                StrictJson.parseObject("{\"v\":" + result.getString("raw_locator_ids") + "}").strings("v"),
                result.getString("verification_artifact_id"), instant(result, "verified_at"), instant(result, "created_at"));
        return new StoredEvidence(row, result.getString("offset_unit"), result.getString("input_kind"),
                result.getString("summary_analysis_id"), quoteVerified, result.getString("verification_kind"));
    }

    @Override
    public void insertEvidence(EvidenceRow row) {
        analysis.insertEvidence(row);
    }

    @Override
    public Optional<StagedVersion> findVersion(String id) {
        return jdbc.query(FIND_VERSION, new MapSqlParameterSource("id", id), (result, index) -> new StagedVersion(
                result.getString("id"), result.getString("kind"), result.getBoolean("active"),
                result.getString("snapshot_artifact_id"), result.getString("created_by"))).stream().findFirst();
    }

    @Override
    public void insertStagedVersion(NewStagedVersion version) {
        jdbc.update(INSERT_VERSION, new MapSqlParameterSource()
                .addValue("id", version.id())
                .addValue("createdAt", OffsetDateTime.ofInstant(version.createdAt(), ZoneOffset.UTC))
                .addValue("createdBy", version.createdBy())
                .addValue("reason", version.reason())
                .addValue("sourceLabel", version.sourceLabel())
                .addValue("policyVersion", version.policyVersion())
                .addValue("issues", version.issueCount())
                .addValue("relations", version.relationCount())
                .addValue("articles", version.articleCount())
                .addValue("artifactId", version.snapshotArtifactId()));
    }

    private static Instant instant(ResultSet result, String column) throws SQLException {
        OffsetDateTime value = result.getObject(column, OffsetDateTime.class);
        return value == null ? null : value.toInstant();
    }
}
