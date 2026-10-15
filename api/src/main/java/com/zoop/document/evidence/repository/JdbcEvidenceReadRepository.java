package com.zoop.document.evidence.repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcEvidenceReadRepository implements EvidenceReadRepository {
    private static final String FIND_EVIDENCE = """
            SELECT id, article_id, article_version, text_artifact_id, quote, start_offset, end_offset, input_kind,
                   quote_verified, verification_artifact_id
            FROM evidence
            WHERE id = :id
            """;
    private static final String SUMMARY_COLUMNS = """
            id, article_id, article_version, stage, company_id, status, request_no, grant_reference, grant_revision, ai_job_id,
            result_version, result_artifact_id, exact_receipt_id, semantic_receipt_id, CAST(result AS text) AS result_text
            """;
    private static final String BY_EXACT_RECEIPT = "SELECT " + SUMMARY_COLUMNS
            + " FROM document_analyses WHERE exact_receipt_id = :receiptId ORDER BY id LIMIT 2";
    private static final String LATEST = "SELECT " + SUMMARY_COLUMNS + """
             FROM document_analyses
            WHERE article_id = :articleId AND article_version = :articleVersion AND stage = 'summary' AND company_id IS NULL
            ORDER BY request_no DESC
            LIMIT 1
            """;
    private static final String BY_AI_JOB = """
            SELECT id, article_id, article_version, stage, company_id FROM document_analyses WHERE ai_job_id = :aiJobId
            """;
    private static final String EXECUTIONS_EXIST = "SELECT EXISTS (SELECT 1 FROM ai_executions WHERE ai_job_id = :aiJobId)";
    private static final String RECIPIENTS = """
            SELECT e.stage AS stage, r.recipient AS recipient
            FROM ai_executions e
            CROSS JOIN LATERAL jsonb_array_elements_text(
                CASE WHEN jsonb_typeof(e.grant_scope -> 'requiredRecipients') = 'array'
                     THEN e.grant_scope -> 'requiredRecipients' ELSE '[]'::jsonb END) AS r(recipient)
            WHERE e.ai_job_id = :creatorJobId AND e.document_analysis_id = :ownerId
              AND e.grant_id = :grantId AND e.grant_revision = :grantRevision
              AND e.stage IN ('document-summary', 'semantic-verification')
            """;
    private static final String COMPANY_EXISTS = "SELECT EXISTS (SELECT 1 FROM companies WHERE id = :id)";

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcEvidenceReadRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<EvidenceView> findEvidence(String id) {
        return jdbc.query(FIND_EVIDENCE, new MapSqlParameterSource("id", id), (result, index) -> {
            boolean verified = result.getBoolean("quote_verified");
            Boolean quoteVerified = result.wasNull() ? null : verified;
            return new EvidenceView(result.getString("id"), result.getString("article_id"),
                    result.getString("article_version"), result.getString("text_artifact_id"), result.getString("quote"),
                    result.getLong("start_offset"), result.getLong("end_offset"), result.getString("input_kind"),
                    quoteVerified, result.getString("verification_artifact_id"));
        }).stream().findFirst();
    }

    @Override
    public List<SummaryView> findSummariesByExactReceipt(String receiptId) {
        return jdbc.query(BY_EXACT_RECEIPT, new MapSqlParameterSource("receiptId", receiptId),
                (result, index) -> summary(result));
    }

    @Override
    public Optional<SummaryView> latestSummary(String articleId, String articleVersion) {
        return jdbc.query(LATEST, new MapSqlParameterSource().addValue("articleId", articleId)
                .addValue("articleVersion", articleVersion), (result, index) -> summary(result)).stream().findFirst();
    }

    @Override
    public Optional<AnalysisIdentity> findAnalysisByAiJobId(String aiJobId) {
        return jdbc.query(BY_AI_JOB, new MapSqlParameterSource("aiJobId", aiJobId),
                (result, index) -> new AnalysisIdentity(result.getString("id"), result.getString("article_id"),
                        result.getString("article_version"), result.getString("stage"), result.getString("company_id")))
                .stream().findFirst();
    }

    @Override
    public boolean executionsExist(String aiJobId) {
        return Boolean.TRUE.equals(jdbc.queryForObject(EXECUTIONS_EXIST, new MapSqlParameterSource("aiJobId", aiJobId),
                Boolean.class));
    }

    @Override
    public Map<String, Set<String>> executionRecipients(String creatorJobId, String ownerAnalysisId, String grantId,
            String grantRevision) {
        Map<String, Set<String>> recipients = new HashMap<>();
        jdbc.query(RECIPIENTS, new MapSqlParameterSource().addValue("creatorJobId", creatorJobId)
                .addValue("ownerId", ownerAnalysisId).addValue("grantId", grantId).addValue("grantRevision", grantRevision),
                (result, index) -> recipients.computeIfAbsent(result.getString("stage"), stage -> new HashSet<>())
                        .add(result.getString("recipient")));
        return recipients;
    }

    @Override
    public boolean companyExists(String id) {
        return Boolean.TRUE.equals(jdbc.queryForObject(COMPANY_EXISTS, new MapSqlParameterSource("id", id), Boolean.class));
    }

    private static SummaryView summary(ResultSet result) throws SQLException {
        return new SummaryView(result.getString("id"), result.getString("article_id"), result.getString("article_version"),
                result.getString("stage"), result.getString("company_id"), result.getString("status"),
                result.getLong("request_no"), result.getString("grant_reference"), result.getString("grant_revision"),
                result.getString("ai_job_id"), result.getString("result_version"), result.getString("result_artifact_id"),
                result.getString("exact_receipt_id"), result.getString("semantic_receipt_id"),
                result.getString("result_text"));
    }
}
