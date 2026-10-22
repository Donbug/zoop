package com.zoop.document.evidence.repository;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * Read-only statements behind {@code getEvidence}. Every method runs inside the caller's one snapshot transaction and none
 * writes; the decisions (what must match, when to refuse) are the service's.
 */
public interface EvidenceReadRepository {

    Optional<EvidenceView> findEvidence(String id);

    /** The analyses whose exact receipt is {@code receiptId}: at most two rows are returned, so a duplicate is detectable. */
    List<SummaryView> findSummariesByExactReceipt(String receiptId);

    /** The summary request with the highest request number of the document version (company-independent scope). */
    Optional<SummaryView> latestSummary(String articleId, String articleVersion);

    Optional<AnalysisIdentity> findAnalysisByAiJobId(String aiJobId);

    /** Whether any AI call execution is recorded under this job id. */
    boolean executionsExist(String aiJobId);

    /**
     * The required recipients of the executions of {@code creatorJobId} owned by {@code ownerAnalysisId} under the given grant
     * snapshot, per stage wire name ({@code document-summary}, {@code document-sentiment},
     * {@code semantic-verification}). A stage without a recipient is absent from the map.
     */
    Map<String, Set<String>> executionRecipients(String creatorJobId, String ownerAnalysisId, String grantId,
            String grantRevision);

    boolean companyExists(String id);
}
