package com.zoop.chat.dto;

import java.time.Instant;

/** OpenAPI {@code ChatSessionResponse}: a conversation and how many question jobs it holds. */
public record ChatSessionResponse(String id, Instant createdAt, int jobs) {
}
