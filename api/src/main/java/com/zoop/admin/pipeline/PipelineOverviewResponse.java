package com.zoop.admin.pipeline;

import java.util.List;
import java.util.Map;

import com.zoop.admin.jobs.AnalysisJobResponse.IngestBaseline;
import com.zoop.admin.jobs.AnalysisJobResponse.UsageOut;

/** OpenAPI {@code Overview} ({@code getPipelineOverview}) and its parts. */
public final class PipelineOverviewResponse {
    private PipelineOverviewResponse() {
    }

    public record Overview(String asOf, LedgerRef ledger, PolicyInfo policy, CandidateCounts candidates, IssueCounts issues,
            ReviewCounts review, GraphDbStatus projection, PublicationState publication, OverviewJobs jobs,
            List<PastRun> runs) {
    }

    public record LedgerRef(String database, String checkedAt) {
    }

    public record PolicyInfo(String version, Map<String, Double> decisionPolicy, boolean webVerification,
            String validationModel) {
    }

    public record CandidateCounts(long total, long active, long inactive, long allow, long hold, long reject) {
    }

    public record IssueCounts(long approved, long relations, long articles) {
    }

    public record ReviewCounts(long revision, long decisions, long allowed, long rejected, long holdPendingReview,
            long ruleCandidates, long ruleEvents) {
    }

    /** {@code neo4j} is always null: the graph database is the AI side's, the app never reads it. */
    public record GraphDbStatus(String status, Long pendingJobs, String oldestPendingAt, String lastCompletedAt, Object neo4j,
            String checkedAt) {
    }

    public record PublicationState(String activeVersionId, boolean ledgerMatchesActive, List<String> issuesOnlyInLedger,
            List<String> issuesOnlyInActive) {
    }

    public record OverviewJobs(long running, long queued, long failed24h, JobFailure lastFailure, IngestBaseline ingest) {
    }

    public record JobFailure(String jobId, String label, String finishedAt, String code, String message) {
    }

    public record PastRun(String runId, String label, String policyGroup, String source, Integer processed, Integer approved,
            Integer held, Integer rejected, Integer pending, Integer errorCount, UsageOut usage) {
    }
}
