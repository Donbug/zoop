package com.zoop.chat.dto;

import java.time.Instant;

/**
 * OpenAPI {@code ChatJob}: one question with its frozen request and, once stored, its result or failure. {@code result} is
 * only a saved result; it is null until the job is completed.
 */
public record ChatJob(String id, String sessionId, int seq, String question, String status, String phase, String outcome,
        Instant askedAt, ChatFrozenContext context, ChatClarificationReply resolves, ChatFailure failure, ChatResult result,
        int runs, Instant createdAt, Instant updatedAt, Instant finishedAt) {
    /** Version of the actual rendered result; per-request metadata never changes the vote identity. */
    @com.fasterxml.jackson.annotation.JsonProperty("feedbackVersion")
    public String feedbackVersion() {
        if (result == null || !"completed".equals(status) || !"answered".equals(result.outcome())) return null;
        var node = new tools.jackson.databind.ObjectMapper().valueToTree(result);
        ((tools.jackson.databind.node.ObjectNode)node).remove("metadata");
        return "chat:" + com.zoop.common.json.Canonical.sha256(com.zoop.common.json.Canonical.appBytes(node));
    }
}
