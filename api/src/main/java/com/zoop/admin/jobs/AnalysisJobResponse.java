package com.zoop.admin.jobs;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.List;
import java.util.Map;

/** Response shapes of the admin job API (OpenAPI {@code JobList}, {@code JobOut}, {@code JobCreated} and their parts). */
public final class AnalysisJobResponse {
    private AnalysisJobResponse() {
    }

    public record JobList(List<JobOut> items, JobOut active, JobLock lock, IngestBaseline ingest, String retryRule,
            String nextCursor) {
    }

    public record JobOut(String id, String kind, String label, String status, String reason, String requestedBy,
            String requestedAt, String startedAt, String finishedAt, Double durationSeconds, String retryOf,
            boolean cancelRequested, boolean recovered, RetryState retry, IngestOutcome ingest, RunReport report,
            FlushResult flush, JobError error, LedgerCounts ledgerBefore, LedgerCounts ledgerAfter,
            @JsonInclude(JsonInclude.Include.NON_NULL) PlanRunOut planRun) {
        public JobOut {
            if ("analyze_plan".equals(kind) != (planRun != null)) {
                throw new IllegalArgumentException("planRun belongs exactly to analyze_plan");
            }
        }
    }

    public record JobCreated(JobOut job, boolean deduplicated) {
    }

    public record PlanRunOut(String planId, String planDigest, String admissionId, String manifestDigest,
            String sourceId, String roundId, String phase, Integer totalUnits, int readyUnits, Integer activeUnit,
            String completion, boolean publicChanged) {}

    /** {@code blockedBy} is the job that keeps this one from being retried (a running retry, a newer attempt, a successor). */
    public record RetryState(boolean allowed, String code, String reason, String blockedBy) {
    }

    /** The run slot: {@code locked} only while an administrator job is running; queued jobs never lock it. */
    public record JobLock(boolean locked, String jobId, String reason) {
    }

    public record IngestBaseline(String at, String jobId, String outcome, Integer newArticles,
            Integer unresolvedFailures) {
    }

    public record IngestOutcome(String outcome, Integer newArticles, Integer duplicateArticles, String baselineBefore,
            String baselineAfter, boolean baselineAdvanced) {
    }

    public record RunReport(String runId, int processed, int skipped, int approved, int held, int rejected, int pending,
            int errorCount, List<Object> errors, int collectionErrorCount, List<Object> collectionErrors,
            double elapsedSeconds, String executionMode, UsageOut usage) {
    }

    public record UsageOut(int calls, int replayCalls, int inputTokens, int outputTokens, double elapsedSeconds,
            Double estimatedCost) {
    }

    public record FlushResult(int completedProjectionJobs) {
    }

    public record JobError(String code, String message) {
    }

    public record LedgerCounts(String capturedAt, Map<String, Object> candidates, int issues, int relations,
            Integer pendingProjections) {
    }
}
