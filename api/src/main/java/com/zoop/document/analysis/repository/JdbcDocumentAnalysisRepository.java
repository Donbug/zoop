package com.zoop.document.analysis.repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.node.ArrayNode;

@Repository
public class JdbcDocumentAnalysisRepository implements DocumentAnalysisRepository {
    private static final String COLUMNS = """
            id, article_id, article_version, stage, company_id, request_no, status, reason, result_version, result_artifact_id,
            exact_receipt_id, semantic_receipt_id, grant_reference, grant_revision, grant_checked_at, model, prompt_version,
            reasoning_effort, ai_job_id, created_at, produced_at, updated_at
            """;
    private static final String FIND_COMPANY = "SELECT name FROM companies WHERE id = :id";
    private static final String FIND = "SELECT " + COLUMNS + " FROM document_analyses WHERE id = :id";
    private static final String FIND_FOR_UPDATE = FIND + " FOR UPDATE";
    private static final String FIND_BY_JOB = "SELECT " + COLUMNS + " FROM document_analyses WHERE ai_job_id = :aiJobId";
    private static final String SCOPE = """
            WHERE article_id = :articleId AND article_version = :articleVersion AND stage = :stage
              AND company_id IS NOT DISTINCT FROM CAST(:companyId AS text)
            """;
    private static final String LATEST = "SELECT " + COLUMNS + " FROM document_analyses " + SCOPE
            + " ORDER BY request_no DESC LIMIT 1";
    private static final String AVAILABLE = "SELECT " + COLUMNS + " FROM document_analyses " + SCOPE
            + " AND status = 'available' ORDER BY request_no ASC";
    private static final String INSERT_PENDING = """
            INSERT INTO document_analyses (id, article_id, article_version, stage, company_id, request_no, status,
                                           grant_reference, grant_revision, grant_checked_at, ai_job_id, created_at, updated_at)
            VALUES (:id, :articleId, :articleVersion, :stage, :companyId, :requestNo, 'pending',
                    :grantReference, :grantRevision, :grantCheckedAt, :aiJobId, :createdAt, :updatedAt)
            """;
    private static final String SETTLE = """
            UPDATE document_analyses
            SET status = :status, reason = :reason, result_version = :resultVersion, result = CAST(:result AS jsonb),
                result_artifact_id = :resultArtifactId, exact_receipt_id = :exactReceiptId,
                semantic_receipt_id = :semanticReceiptId, model = :model, prompt_version = :promptVersion,
                reasoning_effort = :reasoningEffort, produced_at = :producedAt, updated_at = :updatedAt
            WHERE id = :id AND status = 'pending' AND ai_job_id = :aiJobId
            """;
    private static final String RESULT_VERSION_EXISTS = "SELECT EXISTS (SELECT 1 FROM document_analyses WHERE result_version = :resultVersion)";
    private static final String EXECUTION_COLUMNS = """
            id, feature, execution_mode, status, document_analysis_id, ai_job_id, ai_attempt_id, stage, receipt_artifact_id,
            grant_id, grant_revision, CAST(grant_scope AS text) AS grant_scope, provider, model, prompt_version, reasoning_effort,
            input_tokens, output_tokens, error_code, started_at, finished_at
            """;
    private static final String FIND_EXECUTION = "SELECT " + EXECUTION_COLUMNS
            + " FROM ai_executions WHERE ai_job_id = :aiJobId AND ai_attempt_id = :aiAttemptId";
    private static final String INSERT_EXECUTION = """
            INSERT INTO ai_executions (id, feature, execution_mode, status, document_analysis_id, ai_job_id, ai_attempt_id, stage,
                                       receipt_artifact_id, grant_id, grant_revision, grant_scope, provider, model,
                                       prompt_version, reasoning_effort, input_tokens, output_tokens, error_code,
                                       started_at, finished_at)
            VALUES (:id, :feature, :executionMode, :status, :documentAnalysisId, :aiJobId, :aiAttemptId, :stage,
                    :receiptArtifactId, :grantId, :grantRevision, CAST(:grantScope AS jsonb), :provider, :model,
                    :promptVersion, :reasoningEffort, :inputTokens, :outputTokens, :errorCode, :startedAt, :finishedAt)
            """;
    private static final String FIND_EVIDENCE = """
            SELECT id, article_id, article_version, text_artifact_id, quote, start_offset, end_offset,
                   CAST(raw_locator_ids AS text) AS raw_locator_ids, verification_artifact_id, verified_at, created_at
            FROM evidence
            WHERE id = :id
            """;
    private static final String INSERT_EVIDENCE = """
            INSERT INTO evidence (id, article_id, article_version, text_artifact_id, summary_analysis_id, quote, start_offset,
                                  end_offset, offset_unit, input_kind, raw_locator_ids, quote_verified,
                                  verification_artifact_id, verified_at, created_at)
            VALUES (:id, :articleId, :articleVersion, :textArtifactId, NULL, :quote, :startOffset, :endOffset,
                    'unicode_code_point', 'body', CAST(:rawLocatorIds AS jsonb), TRUE, :verificationArtifactId, :verifiedAt,
                    :createdAt)
            """;

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcDocumentAnalysisRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<String> findCompanyName(String companyId) {
        return jdbc.query(FIND_COMPANY, new MapSqlParameterSource("id", companyId),
                (result, index) -> result.getString("name")).stream().findFirst();
    }

    @Override
    public Optional<AnalysisRow> find(String id) {
        return jdbc.query(FIND, new MapSqlParameterSource("id", id), (result, index) -> row(result)).stream().findFirst();
    }

    @Override
    public Optional<AnalysisRow> findForUpdate(String id) {
        return jdbc.query(FIND_FOR_UPDATE, new MapSqlParameterSource("id", id), (result, index) -> row(result)).stream()
                .findFirst();
    }

    @Override
    public Optional<AnalysisRow> findByAiJobId(String aiJobId) {
        return jdbc.query(FIND_BY_JOB, new MapSqlParameterSource("aiJobId", aiJobId), (result, index) -> row(result)).stream()
                .findFirst();
    }

    @Override
    public Optional<AnalysisRow> latestInScope(String articleId, String articleVersion, String stage, String companyId) {
        return jdbc.query(LATEST, scope(articleId, articleVersion, stage, companyId), (result, index) -> row(result)).stream()
                .findFirst();
    }

    @Override
    public List<AnalysisRow> availableInScope(String articleId, String articleVersion, String stage, String companyId) {
        return jdbc.query(AVAILABLE, scope(articleId, articleVersion, stage, companyId), (result, index) -> row(result));
    }

    @Override
    public void insertPending(AnalysisRow row) {
        jdbc.update(INSERT_PENDING, new MapSqlParameterSource()
                .addValue("id", row.id())
                .addValue("articleId", row.articleId())
                .addValue("articleVersion", row.articleVersion())
                .addValue("stage", row.stage())
                .addValue("companyId", row.companyId(), Types.VARCHAR)
                .addValue("requestNo", row.requestNo())
                .addValue("grantReference", row.grantReference())
                .addValue("grantRevision", row.grantRevision())
                .addValue("grantCheckedAt", utc(row.grantCheckedAt()))
                .addValue("aiJobId", row.aiJobId())
                .addValue("createdAt", utc(row.createdAt()))
                .addValue("updatedAt", utc(row.updatedAt())));
    }

    @Override
    public boolean settle(String id, String aiJobId, SettledFields fields) {
        MapSqlParameterSource parameters = new MapSqlParameterSource()
                .addValue("id", id)
                .addValue("aiJobId", aiJobId)
                .addValue("status", fields.status())
                .addValue("reason", fields.reason(), Types.VARCHAR)
                .addValue("resultVersion", fields.resultVersion(), Types.VARCHAR)
                .addValue("result", fields.resultJson(), Types.VARCHAR)
                .addValue("resultArtifactId", fields.resultArtifactId(), Types.VARCHAR)
                .addValue("exactReceiptId", fields.exactReceiptId(), Types.VARCHAR)
                .addValue("semanticReceiptId", fields.semanticReceiptId(), Types.VARCHAR)
                .addValue("model", fields.model(), Types.VARCHAR)
                .addValue("promptVersion", fields.promptVersion(), Types.VARCHAR)
                .addValue("reasoningEffort", fields.reasoningEffort(), Types.VARCHAR)
                .addValue("updatedAt", utc(fields.updatedAt()));
        if (fields.producedAt() == null) {
            parameters.addValue("producedAt", null, Types.TIMESTAMP_WITH_TIMEZONE);
        } else {
            parameters.addValue("producedAt", utc(fields.producedAt()));
        }
        return jdbc.update(SETTLE, parameters) == 1;
    }

    @Override
    public boolean resultVersionExists(String resultVersion) {
        return Boolean.TRUE.equals(jdbc.queryForObject(RESULT_VERSION_EXISTS,
                new MapSqlParameterSource("resultVersion", resultVersion), Boolean.class));
    }

    @Override
    public Optional<ExecutionRow> findExecution(String aiJobId, String aiAttemptId) {
        return jdbc.query(FIND_EXECUTION, new MapSqlParameterSource().addValue("aiJobId", aiJobId)
                .addValue("aiAttemptId", aiAttemptId), (result, index) -> new ExecutionRow(
                result.getString("id"),
                result.getString("feature"),
                result.getString("execution_mode"),
                result.getString("status"),
                result.getString("document_analysis_id"),
                result.getString("ai_job_id"),
                result.getString("ai_attempt_id"),
                result.getString("stage"),
                result.getString("receipt_artifact_id"),
                result.getString("grant_id"),
                result.getString("grant_revision"),
                result.getString("grant_scope"),
                result.getString("provider"),
                result.getString("model"),
                result.getString("prompt_version"),
                result.getString("reasoning_effort"),
                result.getObject("input_tokens", Long.class),
                result.getObject("output_tokens", Long.class),
                result.getString("error_code"),
                instant(result, "started_at"),
                instant(result, "finished_at"))).stream().findFirst();
    }

    @Override
    public void insertExecution(ExecutionRow row) {
        MapSqlParameterSource parameters = new MapSqlParameterSource()
                .addValue("id", row.id())
                .addValue("feature", row.feature())
                .addValue("executionMode", row.executionMode())
                .addValue("status", row.status())
                .addValue("documentAnalysisId", row.documentAnalysisId())
                .addValue("aiJobId", row.aiJobId())
                .addValue("aiAttemptId", row.aiAttemptId())
                .addValue("stage", row.stage())
                .addValue("receiptArtifactId", row.receiptArtifactId())
                .addValue("grantId", row.grantId())
                .addValue("grantRevision", row.grantRevision())
                .addValue("grantScope", row.grantScope(), Types.VARCHAR)
                .addValue("provider", row.provider(), Types.VARCHAR)
                .addValue("model", row.model(), Types.VARCHAR)
                .addValue("promptVersion", row.promptVersion(), Types.VARCHAR)
                .addValue("reasoningEffort", row.reasoningEffort(), Types.VARCHAR)
                .addValue("inputTokens", row.inputTokens(), Types.BIGINT)
                .addValue("outputTokens", row.outputTokens(), Types.BIGINT)
                .addValue("errorCode", row.errorCode(), Types.VARCHAR)
                .addValue("startedAt", utc(row.startedAt()));
        if (row.finishedAt() == null) {
            parameters.addValue("finishedAt", null, Types.TIMESTAMP_WITH_TIMEZONE);
        } else {
            parameters.addValue("finishedAt", utc(row.finishedAt()));
        }
        jdbc.update(INSERT_EXECUTION, parameters);
    }

    @Override
    public Optional<EvidenceRow> findEvidence(String id) {
        return jdbc.query(FIND_EVIDENCE, new MapSqlParameterSource("id", id), (result, index) -> new EvidenceRow(
                result.getString("id"),
                result.getString("article_id"),
                result.getString("article_version"),
                result.getString("text_artifact_id"),
                result.getString("quote"),
                result.getLong("start_offset"),
                result.getLong("end_offset"),
                locators(result.getString("raw_locator_ids")),
                result.getString("verification_artifact_id"),
                instant(result, "verified_at"),
                instant(result, "created_at"))).stream().findFirst();
    }

    @Override
    public void insertEvidence(EvidenceRow row) {
        ArrayNode locators = StrictJson.newArray();
        row.rawLocatorIds().forEach(locators::add);
        jdbc.update(INSERT_EVIDENCE, new MapSqlParameterSource()
                .addValue("id", row.id())
                .addValue("articleId", row.articleId())
                .addValue("articleVersion", row.articleVersion())
                .addValue("textArtifactId", row.textArtifactId())
                .addValue("quote", row.quote())
                .addValue("startOffset", row.startOffset())
                .addValue("endOffset", row.endOffset())
                .addValue("rawLocatorIds", Canonical.write(locators))
                .addValue("verificationArtifactId", row.verificationArtifactId())
                .addValue("verifiedAt", utc(row.verifiedAt()))
                .addValue("createdAt", utc(row.createdAt())));
    }

    private static MapSqlParameterSource scope(String articleId, String articleVersion, String stage, String companyId) {
        return new MapSqlParameterSource()
                .addValue("articleId", articleId)
                .addValue("articleVersion", articleVersion)
                .addValue("stage", stage)
                .addValue("companyId", companyId, Types.VARCHAR);
    }

    private static List<String> locators(String json) {
        return StrictJson.parseObject("{\"v\":" + json + "}").strings("v");
    }

    private static AnalysisRow row(ResultSet result) throws SQLException {
        return new AnalysisRow(
                result.getString("id"),
                result.getString("article_id"),
                result.getString("article_version"),
                result.getString("stage"),
                result.getString("company_id"),
                result.getLong("request_no"),
                result.getString("status"),
                result.getString("reason"),
                result.getString("result_version"),
                result.getString("result_artifact_id"),
                result.getString("exact_receipt_id"),
                result.getString("semantic_receipt_id"),
                result.getString("grant_reference"),
                result.getString("grant_revision"),
                instant(result, "grant_checked_at"),
                result.getString("model"),
                result.getString("prompt_version"),
                result.getString("reasoning_effort"),
                result.getString("ai_job_id"),
                instant(result, "created_at"),
                instant(result, "produced_at"),
                instant(result, "updated_at"));
    }

    private static OffsetDateTime utc(Instant instant) {
        return instant == null ? null : OffsetDateTime.ofInstant(instant, ZoneOffset.UTC);
    }

    private static Instant instant(ResultSet result, String column) throws SQLException {
        OffsetDateTime value = result.getObject(column, OffsetDateTime.class);
        return value == null ? null : value.toInstant();
    }
}
