package com.zoop.chat.dto;

import java.time.Instant;

/**
 * OpenAPI {@code ChatConversationSummary}: one conversation of the member's list. {@code title} is the first question, cut
 * to {@code ChatHistoryService.MAX_TITLE} characters; {@code updatedAt} is when a question was last asked in it.
 */
public record ChatConversationSummary(String id, String title, Instant createdAt, Instant updatedAt, int jobs) {
}
