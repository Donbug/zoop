package com.zoop.document.analysis.repository;

import java.util.List;
import java.util.Optional;

/**
 * Primitive statements of the document analysis tables. Reads that are decisions run outside a transaction and are re-checked
 * by the writer inside its single transaction; every write method must run inside the caller's transaction. The decisions
 * (what must match, when to fail) belong to the service, not to the repository.
 */
public interface DocumentAnalysisRepository {

    /** The catalog name of a company, or empty when there is no such company. */
    Optional<String> findCompanyName(String companyId);

    Optional<AnalysisRow> find(String id);

    /** Reads the row under {@code FOR UPDATE}; the lock is held until the transaction ends. */
    Optional<AnalysisRow> findForUpdate(String id);

    Optional<AnalysisRow> findByAiJobId(String aiJobId);

    /**
     * The row with the highest {@code request_no} of an ERD scope (article, version, stage and, for a sentiment, the company);
     * {@code companyId} is null for a summary.
     */
    Optional<AnalysisRow> latestInScope(String articleId, String articleVersion, String stage, String companyId);

    /** Every {@code available} row of the scope, oldest request first. */
    List<AnalysisRow> availableInScope(String articleId, String articleVersion, String stage, String companyId);

    /** Inserts a {@code pending} row with its job id and grant snapshot; every other optional column stays NULL. */
    void insertPending(AnalysisRow row);

    /** Moves a pending row with this {@code ai_job_id} to its terminal state; false when no such pending row exists. */
    boolean settle(String id, String aiJobId, SettledFields fields);

    boolean resultVersionExists(String resultVersion);

    Optional<ExecutionRow> findExecution(String aiJobId, String aiAttemptId);

    void insertExecution(ExecutionRow row);

    Optional<EvidenceRow> findEvidence(String id);

    void insertEvidence(EvidenceRow row);
}
