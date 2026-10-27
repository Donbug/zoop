package com.zoop.chat.dto;

import java.util.List;

/**
 * OpenAPI {@code ChatConversationList}: a page of the member's conversations, latest first. {@code nextCursor} is null on the
 * last page; {@code deleteEnabled} says whether {@code deleteConversation} is open, so a client shows deletion only then.
 */
public record ChatConversationList(List<ChatConversationSummary> items, String nextCursor, boolean deleteEnabled) {
}
