package com.zoop.chat.repository;

import java.time.Instant;

public record ChatSessionRow(String id, String memberId, Instant createdAt, Instant updatedAt) {
}
