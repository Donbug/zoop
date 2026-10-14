package com.zoop.document.analysis;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.Supplier;

import com.zoop.document.analysis.repository.AnalysisRow;
import com.zoop.document.analysis.repository.DocumentAnalysisRepository;
import com.zoop.document.analysis.repository.EvidenceRow;
import com.zoop.document.analysis.repository.ExecutionRow;
import com.zoop.document.analysis.repository.SettledFields;
import org.springframework.dao.DuplicateKeyException;

/**
 * Test double with the relational semantics the analysis tables enforce (unique job ids, the partial unique index of pending
 * requests, unique request numbers, unique result versions and unique AI attempts). A reproduced transaction boundary
 * ({@link #transactionally}) restores everything when the work throws; the real SQL, constraints and triggers are proven against
 * PostgreSQL by the operator smoke and the SQL proof.
 */
final class InMemoryAnalysisWorld implements DocumentAnalysisRepository {
    private Map<String, AnalysisRow> rows = new LinkedHashMap<>();
    private Map<String, String> resultJson = new HashMap<>();
    private Map<String, ExecutionRow> executions = new LinkedHashMap<>();
    private Map<String, EvidenceRow> evidence = new LinkedHashMap<>();
    private final Map<String, String> companies = new HashMap<>();
    private RuntimeException failOnEvidence;
    private Runnable afterRowLock;

    void seedCompany(String id, String name) {
        companies.put(id, name);
    }

    void renameCompany(String id, String name) {
        companies.put(id, name);
    }

    /** The next evidence insert fails like a lost connection (an unknown outcome, not a defined refusal). */
    void failNextEvidenceInsert(RuntimeException failure) {
        failOnEvidence = failure;
    }

    /**
     * Runs once, right after the next {@code findForUpdate} returned: what happens while a settlement waited for the row lock
     * (an operator editing the grant file, the clock passing a grant's expiry).
     */
    void afterNextRowLock(Runnable action) {
        afterRowLock = action;
    }

    <T> T transactionally(Supplier<T> work) {
        Map<String, AnalysisRow> rowsBefore = new LinkedHashMap<>(rows);
        Map<String, String> resultsBefore = new HashMap<>(resultJson);
        Map<String, ExecutionRow> executionsBefore = new LinkedHashMap<>(executions);
        Map<String, EvidenceRow> evidenceBefore = new LinkedHashMap<>(evidence);
        try {
            return work.get();
        } catch (RuntimeException | Error failure) {
            rows = rowsBefore;
            resultJson = resultsBefore;
            executions = executionsBefore;
            evidence = evidenceBefore;
            throw failure;
        }
    }

    List<AnalysisRow> rows() {
        return new ArrayList<>(rows.values());
    }

    AnalysisRow row(String id) {
        return rows.get(id);
    }

    String resultJson(String id) {
        return resultJson.get(id);
    }

    List<ExecutionRow> executions() {
        return new ArrayList<>(executions.values());
    }

    List<EvidenceRow> evidenceRows() {
        return new ArrayList<>(evidence.values());
    }

    @Override
    public Optional<String> findCompanyName(String companyId) {
        return Optional.ofNullable(companies.get(companyId));
    }

    @Override
    public Optional<AnalysisRow> find(String id) {
        return Optional.ofNullable(rows.get(id));
    }

    @Override
    public Optional<AnalysisRow> findForUpdate(String id) {
        Optional<AnalysisRow> locked = find(id);
        if (afterRowLock != null) {
            Runnable action = afterRowLock;
            afterRowLock = null;
            action.run();
        }
        return locked;
    }

    @Override
    public Optional<AnalysisRow> findByAiJobId(String aiJobId) {
        return rows.values().stream().filter(row -> aiJobId.equals(row.aiJobId())).findFirst();
    }

    @Override
    public Optional<AnalysisRow> latestInScope(String articleId, String articleVersion, String stage, String companyId) {
        return inScope(articleId, articleVersion, stage, companyId).stream()
                .max((a, b) -> Long.compare(a.requestNo(), b.requestNo()));
    }

    @Override
    public List<AnalysisRow> availableInScope(String articleId, String articleVersion, String stage, String companyId) {
        return inScope(articleId, articleVersion, stage, companyId).stream().filter(row -> "available".equals(row.status()))
                .sorted((a, b) -> Long.compare(a.requestNo(), b.requestNo())).toList();
    }

    private List<AnalysisRow> inScope(String articleId, String articleVersion, String stage, String companyId) {
        return rows.values().stream().filter(row -> row.articleId().equals(articleId)
                && row.articleVersion().equals(articleVersion) && row.stage().equals(stage)
                && java.util.Objects.equals(row.companyId(), companyId)).toList();
    }

    @Override
    public void insertPending(AnalysisRow row) {
        if (rows.containsKey(row.id()) || findByAiJobId(row.aiJobId()).isPresent()) {
            throw new DuplicateKeyException("document_analyses");
        }
        List<AnalysisRow> scope = inScope(row.articleId(), row.articleVersion(), row.stage(), row.companyId());
        if (scope.stream().anyMatch(other -> "pending".equals(other.status()) || other.requestNo() == row.requestNo())) {
            throw new DuplicateKeyException("ux_document_analyses_pending");
        }
        rows.put(row.id(), row);
    }

    @Override
    public boolean settle(String id, String aiJobId, SettledFields fields) {
        AnalysisRow row = rows.get(id);
        if (row == null || !"pending".equals(row.status()) || !aiJobId.equals(row.aiJobId())) {
            return false;
        }
        rows.put(id, new AnalysisRow(row.id(), row.articleId(), row.articleVersion(), row.stage(), row.companyId(),
                row.requestNo(), fields.status(), fields.reason(), fields.resultVersion(), fields.resultArtifactId(),
                fields.exactReceiptId(), fields.semanticReceiptId(), row.grantReference(), row.grantRevision(),
                row.grantCheckedAt(), fields.model(), fields.promptVersion(), fields.reasoningEffort(), row.aiJobId(),
                row.createdAt(), fields.producedAt(), fields.updatedAt()));
        if (fields.resultJson() != null) {
            resultJson.put(id, fields.resultJson());
        }
        return true;
    }

    @Override
    public boolean resultVersionExists(String resultVersion) {
        return rows.values().stream().anyMatch(row -> resultVersion.equals(row.resultVersion()));
    }

    @Override
    public Optional<ExecutionRow> findExecution(String aiJobId, String aiAttemptId) {
        return Optional.ofNullable(executions.get(aiJobId + '\u0000' + aiAttemptId));
    }

    @Override
    public void insertExecution(ExecutionRow row) {
        String key = row.aiJobId() + '\u0000' + row.aiAttemptId();
        if (executions.containsKey(key)) {
            throw new DuplicateKeyException("ux_ai_executions_attempt");
        }
        // The schema's trigger: a document analysis that is the only owner must be the analysis of this AI job.
        AnalysisRow owner = rows.get(row.documentAnalysisId());
        if (owner == null || !row.aiJobId().equals(owner.aiJobId())) {
            throw new org.springframework.dao.DataIntegrityViolationException("ai_executions owner");
        }
        executions.put(key, row);
    }

    @Override
    public Optional<EvidenceRow> findEvidence(String id) {
        return Optional.ofNullable(evidence.get(id));
    }

    @Override
    public void insertEvidence(EvidenceRow row) {
        if (failOnEvidence != null) {
            RuntimeException failure = failOnEvidence;
            failOnEvidence = null;
            throw failure;
        }
        if (evidence.containsKey(row.id())) {
            throw new DuplicateKeyException("evidence");
        }
        evidence.put(row.id(), row);
    }
}
