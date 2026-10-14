package com.zoop.document.analysis.repository;

import java.time.Instant;

/**
 * The columns of {@code ai_executions} this app writes for an AI call receipt. The columns it never observes stay NULL:
 * {@code grant_checked_at} (the right was not checked immediately before the attempt by this app), {@code attempt_no},
 * both costs, {@code currency} and {@code error_message}. {@code grantScope} is JSON text.
 */
public record ExecutionRow(String id, String feature, String executionMode, String status, String documentAnalysisId,
        String aiJobId, String aiAttemptId, String stage, String receiptArtifactId, String grantId, String grantRevision,
        String grantScope, String provider, String model, String promptVersion, String reasoningEffort, Long inputTokens,
        Long outputTokens, String errorCode, Instant startedAt, Instant finishedAt) {
}
