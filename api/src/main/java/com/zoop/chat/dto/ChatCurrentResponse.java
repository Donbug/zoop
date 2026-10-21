package com.zoop.chat.dto;

/** OpenAPI {@code ChatCurrentResponse}: the member's latest conversation, or null when there is none. */
public record ChatCurrentResponse(ChatConversation conversation) {
}
