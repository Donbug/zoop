package com.zoop.chat.repository;

import java.time.Instant;
import java.util.List;

/**
 * One {@code chat_jobs} row with the member that owns its conversation. JSON columns are kept as their stored text and read
 * by the service; {@code result} and {@code failure} are null unless the job is completed or failed.
 */
public record ChatJobRow(String id, String sessionId, String memberId, int seq, String question, String requestHash,
        Instant askedAt, String frozenContext, List<String> contextCompanyIds, String graphVersionId, String status,
        String phase, String outcome, String resolvesJobId, String resolvesChoiceId, int clarificationDepth, String result,
        String failure, int runs, String attempts, Instant createdAt, Instant updatedAt, Instant finishedAt) {
    public boolean active() {
        return "queued".equals(status) || "running".equals(status);
    }
}
