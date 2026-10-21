package com.zoop.chat.dto;

/** OpenAPI {@code ChatClarificationReply}: the clarification a job answers; {@code choiceId} null means a free-text answer. */
public record ChatClarificationReply(String jobId, String choiceId) {
}
