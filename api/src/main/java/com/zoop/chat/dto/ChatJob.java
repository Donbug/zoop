package com.zoop.chat.dto;

import java.time.Instant;

/**
 * OpenAPI {@code ChatJob}: one question with its frozen request and, once stored, its result or failure. {@code result} is
 * only a saved result; it is null until the job is completed.
 */
public record ChatJob(String id, String sessionId, int seq, String question, String status, String phase, String outcome,
        Instant askedAt, ChatFrozenContext context, ChatClarificationReply resolves, ChatFailure failure, ChatResult result,
        int runs, Instant createdAt, Instant updatedAt, Instant finishedAt) {
}
