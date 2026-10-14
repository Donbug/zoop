package com.zoop.document.analysis.service;

import java.time.Clock;
import java.time.Instant;
import java.util.Objects;
import java.util.Optional;

import com.zoop.common.json.StrictJson;
import com.zoop.document.analysis.AnalysisException;
import com.zoop.document.analysis.AnalysisFailure;
import com.zoop.document.analysis.repository.AnalysisRow;
import com.zoop.document.analysis.repository.DocumentAnalysisRepository;
import com.zoop.document.analysis.repository.EvidenceRow;
import com.zoop.document.analysis.repository.ExecutionRow;
import com.zoop.document.analysis.repository.SettledFields;
import com.zoop.document.repository.ArticleRow;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * The two database writes of an operator document analysis, each one short transaction with no external call inside it.
 *
 * <p>{@link #reserve} commits the pending analysis, its issued AI job id and its immutable {@code ai_submit} artifact row
 * before any AI request exists. {@link #settle} turns a pending analysis into its one terminal state together with the
 * receipt artifacts, the counted AI executions and (for a summary) the evidence, or not at all. Both lock the article first
 * and the analysis row second; the article lock serialises every writer of the document, and the partial unique indexes of
 * the schema defend the same invariants against a writer that bypassed it.
 *
 * <p>A defined refusal is an {@link AnalysisException}, which rolls the transaction back: the caller then removes the files it
 * created for it. Any database or transaction failure is an unknown outcome and the caller keeps its files.
 */
@Service
public class DocumentAnalysisService {
    static final String MEDIA_TYPE = "application/json";
    private static final String AVAILABLE = "available";
    private static final String PENDING = "pending";

    private final DocumentRegistryRepository registry;
    private final DocumentAnalysisRepository analyses;
    private final Clock clock;

    public DocumentAnalysisService(DocumentRegistryRepository registry, DocumentAnalysisRepository analyses, Clock clock) {
        this.registry = registry;
        this.analyses = analyses;
        this.clock = clock;
    }

    @Transactional
    public Reservation reserve(ReserveCommand command) {
        Instant now = clock.instant();
        ArticleRow article = registry.lockArticle(command.articleId())
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.DOCUMENT_NOT_REGISTERED));
        if (!AVAILABLE.equals(article.accessStatus())) {
            throw new AnalysisException(AnalysisFailure.ARTICLE_ACCESS_UNAVAILABLE);
        }
        VersionRow version = registry.findVersion(command.articleId(), command.articleVersion())
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.DOCUMENT_NOT_REGISTERED));
        ArtifactRow text = registry.findArtifact(version.textArtifactId())
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.DOCUMENT_VERSION_MISMATCH));
        if (!version.textArtifactId().equals(command.textArtifactId()) || !text.sha256().equals(command.textSha256())
                || text.bytes() != command.textBytes()) {
            throw new AnalysisException(AnalysisFailure.DOCUMENT_VERSION_MISMATCH);
        }
        String companyName = analyses.findCompanyName(command.companyId())
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.COMPANY_UNKNOWN));
        if (!companyName.equals(command.companyName())) {
            throw new AnalysisException(AnalysisFailure.COMPANY_CONTEXT_CHANGED);
        }

        String scopeCompany = command.stage().companyScoped() ? command.companyId() : null;
        Optional<AnalysisRow> latest = analyses.latestInScope(command.articleId(), command.articleVersion(),
                command.stage().wire(), scopeCompany);
        String actual = latest.map(AnalysisRow::id).orElse(null);
        if (!Objects.equals(actual, command.expectedLatest())) {
            throw latestConflict(AnalysisFailure.LATEST_CONFLICT, latest);
        }
        if (latest.isPresent() && PENDING.equals(latest.get().status())) {
            throw latestConflict(AnalysisFailure.ANALYSIS_PENDING, latest);
        }

        registerArtifact(command.submit(), now, true);
        long requestNo = latest.map(row -> row.requestNo() + 1).orElse(1L);
        analyses.insertPending(new AnalysisRow(command.analysisId(), command.articleId(), command.articleVersion(),
                command.stage().wire(), scopeCompany, requestNo, PENDING, null, null, null, null, null, command.grantId(),
                command.grantRevision(), command.grantCheckedAt(), null, null, null, command.aiJobId(), now, null, now));
        return new Reservation(command.analysisId(), command.aiJobId(), requestNo, command.stage().wire());
    }

    @Transactional
    public Settlement settle(SettleCommand command) {
        AnalysisRow unlocked = analyses.find(command.analysisId())
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.ANALYSIS_UNKNOWN));
        ArticleRow article = registry.lockArticle(unlocked.articleId())
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.DOCUMENT_NOT_REGISTERED));
        AnalysisRow row = analyses.findForUpdate(command.analysisId())
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.ANALYSIS_UNKNOWN));
        if (!PENDING.equals(row.status()) || !command.aiJobId().equals(row.aiJobId())) {
            throw new AnalysisException(AnalysisFailure.ANALYSIS_NOT_PENDING);
        }

        // This instant and authority read happen only after both row locks. The callback is local (flat file plus evaluation);
        // it must never call the model service. A registry read failure remains a rollback, not a false denial settlement.
        Instant now = clock.instant();
        boolean available = command.available() != null;
        String status = command.status();
        String reason = command.reason();
        if (available) {
            String denial = command.currentAuthority().denial(article.provider(), now);
            if (denial != null) {
                available = false;
                status = "withheld";
                reason = denial;
            } else if (!AVAILABLE.equals(article.accessStatus())) {
                available = false;
                status = "withheld";
                reason = "article_access_unavailable";
            }
        }
        if (available) {
            VersionRow version = registry.findVersion(row.articleId(), row.articleVersion())
                    .orElseThrow(() -> new AnalysisException(AnalysisFailure.DOCUMENT_NOT_REGISTERED));
            for (EvidenceDraft draft : command.evidence()) {
                if (!draft.articleId().equals(row.articleId()) || !draft.articleVersion().equals(row.articleVersion())
                        || !draft.textArtifactId().equals(version.textArtifactId())) {
                    throw new AnalysisException(AnalysisFailure.DOCUMENT_VERSION_MISMATCH);
                }
            }
            if (analyses.resultVersionExists(command.available().resultVersion())) {
                throw new AnalysisException(AnalysisFailure.RESULT_VERSION_COLLISION);
            }
        }

        for (ArtifactFile file : command.artifacts()) {
            // A late authority denial retains audit receipts but must not register content artifacts.
            if (available || "ai_call_receipt".equals(file.kind())) {
                registerArtifact(file, now, false);
            }
        }
        int created = 0;
        int existing = 0;
        for (ExecutionRow execution : command.executions()) {
            Optional<ExecutionRow> counted = analyses.findExecution(execution.aiJobId(), execution.aiAttemptId());
            if (counted.isPresent()) {
                if (!sameExecution(counted.get(), execution)) {
                    throw new AnalysisException(AnalysisFailure.EXECUTION_CONFLICT);
                }
                existing++;
                continue;
            }
            try {
                analyses.insertExecution(execution);
            } catch (DuplicateKeyException duplicate) {
                throw new AnalysisException(AnalysisFailure.EXECUTION_CONFLICT);
            }
            created++;
        }
        if (available) {
            for (EvidenceDraft draft : command.evidence()) {
                insertEvidence(draft, command.available().exactReceiptId(), now);
            }
        }
        AvailableFields result = command.available();
        SettledFields fields = new SettledFields(status, reason,
                available ? result.resultVersion() : null, available ? result.resultJson() : null,
                available ? result.resultArtifactId() : null, available ? result.exactReceiptId() : null,
                available ? result.semanticReceiptId() : null, command.model(), command.promptVersion(),
                command.reasoningEffort(), available ? result.producedAt() : null, now);
        if (!analyses.settle(row.id(), command.aiJobId(), fields)) {
            throw new AnalysisException(AnalysisFailure.ANALYSIS_NOT_PENDING);
        }
        return new Settlement(status, reason, created, existing, available ? command.evidence().size() : 0);
    }

    /** Idempotent by id: an existing row must hold exactly the registered kind, URI, hash and size. */
    private void registerArtifact(ArtifactFile file, Instant now, boolean mustBeNew) {
        ArtifactRow wanted = new ArtifactRow(file.id(), file.kind(), file.uri(), file.sha256(), file.bytes(), MEDIA_TYPE, now);
        boolean created;
        try {
            created = registry.insertArtifactIfAbsent(wanted);
        } catch (DuplicateKeyException storageUriTaken) {
            // The id is new but another artifact already owns this URI: URIs are never shared or overwritten.
            throw new AnalysisException(AnalysisFailure.ARTIFACT_CONFLICT);
        }
        ArtifactRow stored = registry.findArtifact(file.id())
                .orElseThrow(() -> new AnalysisException(AnalysisFailure.INTERNAL_ERROR));
        if ((mustBeNew && !created) || !stored.kind().equals(wanted.kind()) || !stored.storageUri().equals(wanted.storageUri())
                || !stored.sha256().equals(wanted.sha256()) || stored.bytes() != wanted.bytes()
                || !stored.mediaType().equals(wanted.mediaType())) {
            throw new AnalysisException(AnalysisFailure.ARTIFACT_CONFLICT);
        }
    }

    private void insertEvidence(EvidenceDraft draft, String verificationArtifactId, Instant now) {
        if (analyses.findEvidence(draft.id()).isPresent()) {
            throw new AnalysisException(AnalysisFailure.EVIDENCE_CONFLICT);
        }
        try {
            analyses.insertEvidence(new EvidenceRow(draft.id(), draft.articleId(), draft.articleVersion(),
                    draft.textArtifactId(), draft.quote(), draft.startOffset(), draft.endOffset(), draft.rawLocatorIds(),
                    verificationArtifactId, now, now));
        } catch (DuplicateKeyException duplicate) {
            throw new AnalysisException(AnalysisFailure.EVIDENCE_CONFLICT);
        }
    }

    /** Every column this app writes; the JSON scope is compared as a value, not as text. */
    static boolean sameExecution(ExecutionRow stored, ExecutionRow wanted) {
        try {
            return stored.id().equals(wanted.id()) && stored.feature().equals(wanted.feature())
                    && stored.executionMode().equals(wanted.executionMode()) && stored.status().equals(wanted.status())
                    && Objects.equals(stored.documentAnalysisId(), wanted.documentAnalysisId())
                    && stored.aiJobId().equals(wanted.aiJobId()) && stored.aiAttemptId().equals(wanted.aiAttemptId())
                    && Objects.equals(stored.stage(), wanted.stage())
                    && Objects.equals(stored.receiptArtifactId(), wanted.receiptArtifactId())
                    && Objects.equals(stored.grantId(), wanted.grantId())
                    && Objects.equals(stored.grantRevision(), wanted.grantRevision())
                    && StrictJson.parseObject(stored.grantScope()).node().equals(StrictJson.parseObject(wanted.grantScope()).node())
                    && Objects.equals(stored.provider(), wanted.provider()) && Objects.equals(stored.model(), wanted.model())
                    && Objects.equals(stored.promptVersion(), wanted.promptVersion())
                    && Objects.equals(stored.reasoningEffort(), wanted.reasoningEffort())
                    && Objects.equals(stored.inputTokens(), wanted.inputTokens())
                    && Objects.equals(stored.outputTokens(), wanted.outputTokens())
                    && Objects.equals(stored.errorCode(), wanted.errorCode())
                    && Objects.equals(stored.startedAt(), wanted.startedAt())
                    && Objects.equals(stored.finishedAt(), wanted.finishedAt());
        } catch (StrictJson.Malformed malformed) {
            return false;
        }
    }

    private static AnalysisException latestConflict(AnalysisFailure failure, Optional<AnalysisRow> latest) {
        java.util.Map<String, String> details = new java.util.LinkedHashMap<>();
        latest.ifPresent(row -> {
            details.put("latestAnalysisId", row.id());
            details.put("latestStatus", row.status());
        });
        return new AnalysisException(failure, details);
    }
}
