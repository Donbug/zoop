package com.zoop.document.evidence.service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import com.zoop.document.evidence.repository.AnalysisIdentity;
import com.zoop.document.evidence.repository.EvidenceReadRepository;
import com.zoop.document.evidence.repository.EvidenceView;
import com.zoop.document.evidence.repository.SummaryView;

/** Test double of the read statements: plain lists and a call counter; the interface has no way to write. */
final class InMemoryEvidenceRead implements EvidenceReadRepository {
    record Execution(String aiJobId, String ownerId, String grantId, String grantRevision, String stage,
            Set<String> recipients) {
    }

    final Map<String, EvidenceView> evidence = new HashMap<>();
    final List<SummaryView> summaries = new ArrayList<>();
    final List<AnalysisIdentity> identities = new ArrayList<>();
    final List<String> jobs = new ArrayList<>();
    final List<Execution> executions = new ArrayList<>();
    final Set<String> companies = new HashSet<>();
    RuntimeException failure;
    int calls;

    private void called() {
        calls++;
        if (failure != null) {
            throw failure;
        }
    }

    @Override
    public Optional<EvidenceView> findEvidence(String id) {
        called();
        return Optional.ofNullable(evidence.get(id));
    }

    @Override
    public List<SummaryView> findSummariesByExactReceipt(String receiptId) {
        called();
        return summaries.stream().filter(s -> receiptId.equals(s.exactReceiptId())).limit(2).toList();
    }

    @Override
    public Optional<SummaryView> latestSummary(String articleId, String articleVersion) {
        called();
        return summaries.stream()
                .filter(s -> s.articleId().equals(articleId) && s.articleVersion().equals(articleVersion)
                        && "summary".equals(s.stage()) && s.companyId() == null)
                .max((a, b) -> Long.compare(a.requestNo(), b.requestNo()));
    }

    @Override
    public Optional<AnalysisIdentity> findAnalysisByAiJobId(String aiJobId) {
        called();
        return identities.stream().filter(i -> aiJobId.equals(jobs.get(identities.indexOf(i)))).findFirst();
    }

    @Override
    public boolean executionsExist(String aiJobId) {
        called();
        return executions.stream().anyMatch(e -> e.aiJobId().equals(aiJobId));
    }

    @Override
    public Map<String, Set<String>> executionRecipients(String creatorJobId, String ownerAnalysisId, String grantId,
            String grantRevision) {
        called();
        Map<String, Set<String>> byStage = new HashMap<>();
        for (Execution e : executions) {
            if (e.aiJobId().equals(creatorJobId) && e.ownerId().equals(ownerAnalysisId) && e.grantId().equals(grantId)
                    && e.grantRevision().equals(grantRevision)) {
                if (!e.recipients().isEmpty()) {
                    byStage.computeIfAbsent(e.stage(), stage -> new HashSet<>()).addAll(e.recipients());
                }
            }
        }
        return byStage;
    }

    @Override
    public boolean companyExists(String id) {
        called();
        return companies.contains(id);
    }

    void addIdentity(String aiJobId, AnalysisIdentity identity) {
        jobs.add(aiJobId);
        identities.add(identity);
    }
}
