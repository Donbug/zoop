package com.zoop.graph.read;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.StrictJson;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.document.analysis.ExactReceiptProof;
import com.zoop.document.analysis.GrantRegistry;
import com.zoop.document.evidence.config.DocumentReadProperties;
import com.zoop.document.evidence.repository.EvidenceReadRepository;
import com.zoop.document.evidence.service.DocumentReadGrants;
import com.zoop.document.evidence.service.EvidenceArtifactReader;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.document.repository.ArticleRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import java.nio.file.Path;
import java.time.Clock;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeSet;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

/** Reads stored analyses only when their current disclosure authority can be proved. */
@Component
public class CompanyDocumentAnalysisReader {
    public record StageStatus(String status, String reason) { }
    public record Status(StageStatus summary, StageStatus sentiment) { }
    public record Visible(JsonNode sentiment, JsonNode summary, Status status, JsonNode provenance, String resultVersion) { }
    private record Analysis(String id, String status, String reason, String resultVersion, String result,
            String grantReference, String grantRevision, String aiJobId, String resultArtifactId,
            String exactReceiptId, String semanticReceiptId) { }
    private record Creator(String jobId, String analysisId) { }

    private final NamedParameterJdbcTemplate jdbc;
    private final EvidenceReadRepository evidenceRows;
    private final EvidenceService evidence;
    private final DocumentRegistryRepository registry;
    private final DocumentReadGrants grants;
    private final Path artifactRoot;
    private final Clock clock;
    private static final Set<String> SENTIMENT_KEYS = Set.of("label", "companyId", "rationale", "quotes",
            "judgedAt", "model", "promptVersion");

    public CompanyDocumentAnalysisReader(NamedParameterJdbcTemplate jdbc, EvidenceReadRepository evidenceRows,
            EvidenceService evidence, DocumentRegistryRepository registry, DocumentReadProperties properties, Clock clock) {
        this.jdbc = jdbc;
        this.evidenceRows = evidenceRows;
        this.evidence = evidence;
        this.registry = registry;
        this.grants = new DocumentReadGrants(properties.grantsPath());
        this.artifactRoot = properties.artifactRootPath();
        this.clock = clock;
    }

    public Visible read(ArticleRow article, VersionRow version, String companyId, String requestId) {
        Analysis summary = latest(article.id(), version.version(), "summary", null);
        Analysis sentiment = latest(article.id(), version.version(), "sentiment", companyId);
        JsonNode summaryResult = null;
        JsonNode sentimentResult = null;
        boolean summaryWithheld = false;
        boolean sentimentWithheld = false;
        if (summary != null && "available".equals(summary.status())) {
            try {
                JsonNode stored = StrictJson.parseObject(summary.result()).node();
                JsonNode citations = stored.get("citations");
                if (citations != null && citations.isArray() && !citations.isEmpty()) {
                    String evidenceId = citations.get(0).get("evidenceId").stringValue();
                    var visible = evidence.read(evidenceId, null, null, null, null, requestId);
                    if (visible.documentSummary() != null && version.version().equals(visible.documentVersion())
                            && summary.resultVersion().equals(visible.resultVersion())) {
                        summaryResult = visible.documentSummary();
                    }
                }
                summaryWithheld = summaryResult == null;
            } catch (CustomException error) {
                if (error.getErrorCode() != ErrorCode.EVIDENCE_UNAVAILABLE
                        && error.getErrorCode() != ErrorCode.RESOURCE_NOT_FOUND) throw error;
                summaryWithheld = true;
            } catch (RuntimeException error) {
                throw new CustomException(ErrorCode.INTERNAL_ERROR, error);
            }
        }
        if (sentiment != null && "available".equals(sentiment.status())) {
            if (allowedSentiment(sentiment, article, version, companyId, requestId)) {
                try {
                    StrictJson.Obj value = StrictJson.parseObject(sentiment.result()).exactly(SENTIMENT_KEYS);
                    if (!companyId.equals(value.string("companyId")) || !Set.of("positive", "negative", "mixed",
                            "undetermined").contains(value.string("label"))) throw new StrictJson.Malformed();
                    value.string("rationale");
                    value.strings("quotes");
                    OffsetDateTime.parse(value.string("judgedAt"));
                    value.string("model");
                    value.string("promptVersion");
                    sentimentResult = value.node();
                } catch (RuntimeException error) {
                    throw new CustomException(ErrorCode.INTERNAL_ERROR, error);
                }
            } else {
                sentimentWithheld = true;
            }
        }
        Status status = new Status(stage(summary, summaryWithheld), stage(sentiment, sentimentWithheld));
        String resultVersion = summaryResult != null ? summary.resultVersion()
                : sentimentResult != null ? sentiment.resultVersion() : null;
        JsonNode provenance = summaryResult == null ? null : summaryResult.get("provenance");
        return new Visible(sentimentResult, summaryResult, status, provenance, resultVersion);
    }

    private Analysis latest(String articleId, String version, String stage, String companyId) {
        String sql = """
                SELECT id, status, reason, result_version, CAST(result AS text) AS result_text,
                       grant_reference, grant_revision, ai_job_id, result_artifact_id,
                       exact_receipt_id, semantic_receipt_id
                FROM document_analyses
                WHERE article_id=:articleId AND article_version=:version AND stage=:stage
                  AND company_id IS NOT DISTINCT FROM :companyId
                ORDER BY request_no DESC LIMIT 1
                """;
        return jdbc.query(sql, new MapSqlParameterSource().addValue("articleId", articleId)
                .addValue("version", version).addValue("stage", stage).addValue("companyId", companyId),
                (rs, row) -> new Analysis(rs.getString("id"), rs.getString("status"), rs.getString("reason"),
                        rs.getString("result_version"), rs.getString("result_text"), rs.getString("grant_reference"),
                        rs.getString("grant_revision"), rs.getString("ai_job_id"), rs.getString("result_artifact_id"),
                        rs.getString("exact_receipt_id"), rs.getString("semantic_receipt_id"))).stream().findFirst().orElse(null);
    }

    private boolean allowedSentiment(Analysis analysis, ArticleRow article, VersionRow version, String companyId,
            String requestId) {
        if (!version.version().equals(article.currentVersion()) || analysis.grantReference() == null
                || analysis.grantRevision() == null || analysis.aiJobId() == null || analysis.resultVersion() == null
                || analysis.resultArtifactId() == null || analysis.exactReceiptId() == null
                || analysis.semanticReceiptId() == null)
            return false;
        Creator creator = evidenceRows.executionsExist(analysis.aiJobId())
                ? new Creator(analysis.aiJobId(), analysis.id())
                : cachedCreator(analysis, article, version, companyId);
        if (creator == null) return false;
        Map<String, Set<String>> byStage = evidenceRows.executionRecipients(creator.jobId(), creator.analysisId(),
                analysis.grantReference(), analysis.grantRevision());
        Set<String> generation = byStage.get("document-sentiment");
        Set<String> verification = byStage.get("semantic-verification");
        if (generation == null || generation.isEmpty() || verification == null || verification.isEmpty()) return false;
        Set<String> recipients = new TreeSet<>();
        if (generation.stream().anyMatch(Objects::isNull) || verification.stream().anyMatch(Objects::isNull)) return false;
        recipients.addAll(generation);
        recipients.addAll(verification);
        GrantRegistry current = grants.registry(requestId);
        return GrantRegistry.evaluate(current.current(analysis.grantReference()).orElse(null), article.provider(),
                analysis.grantRevision(), GrantRegistry.purposesOf("document-sentiment"),
                new ArrayList<>(recipients), true, clock.instant()) == null;
    }

    private Creator cachedCreator(Analysis analysis, ArticleRow article, VersionRow version, String companyId) {
        if (analysis.resultVersion() == null || analysis.resultArtifactId() == null
                || analysis.semanticReceiptId() == null || version.textArtifactId() == null
                || !("exact-" + analysis.id()).equals(analysis.exactReceiptId())) return null;
        var receipt = registry.findArtifact(analysis.exactReceiptId()).orElse(null);
        var text = registry.findArtifact(version.textArtifactId()).orElse(null);
        if (receipt == null || text == null || !"exact_receipt".equals(receipt.kind())
                || !"application/json".equals(receipt.mediaType())) return null;
        byte[] bytes;
        try {
            bytes = new EvidenceArtifactReader(artifactRoot == null ? null : ArtifactFileStore.at(artifactRoot)).read(receipt);
        } catch (ArtifactStoreException error) {
            if (error.reason() == ArtifactStoreException.Reason.CONFLICT) return null;
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, error);
        }
        String creatorJob = ExactReceiptProof.sentimentCreatorJobId(bytes, new ExactReceiptProof.SentimentSubject(
                analysis.id(), analysis.aiJobId(), article.id(), version.version(), version.textArtifactId(),
                text.sha256(), analysis.resultVersion(), analysis.resultArtifactId(), analysis.semanticReceiptId()));
        if (creatorJob == null) return null;
        var creator = evidenceRows.findAnalysisByAiJobId(creatorJob).orElse(null);
        if (creator == null || creator.id().equals(analysis.id()) || !article.id().equals(creator.articleId())
                || !version.version().equals(creator.articleVersion()) || !"sentiment".equals(creator.stage())
                || !companyId.equals(creator.companyId())) return null;
        return new Creator(creatorJob, creator.id());
    }

    private static StageStatus stage(Analysis analysis, boolean withheld) {
        if (analysis == null) return new StageStatus("not_requested", null);
        if (withheld) return new StageStatus("withheld", null);
        return new StageStatus(analysis.status(), analysis.reason());
    }
}
