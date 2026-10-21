package com.zoop.chat.dto;

import java.util.List;

/** OpenAPI {@code ChatConversation}: the conversation and its jobs in submission order. */
public record ChatConversation(ChatSessionResponse session, List<ChatJob> jobs) {
}
