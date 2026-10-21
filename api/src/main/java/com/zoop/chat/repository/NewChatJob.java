package com.zoop.chat.repository;

import java.time.Instant;
import java.util.List;

/** A job as accepted: its frozen request, queued with its first attempt. */
public record NewChatJob(String id, String sessionId, int seq, String question, String requestHash, Instant askedAt,
        String frozenContext, List<String> contextCompanyIds, String graphVersionId, String resolvesJobId,
        String resolvesChoiceId, int clarificationDepth, String attempts) {
}
