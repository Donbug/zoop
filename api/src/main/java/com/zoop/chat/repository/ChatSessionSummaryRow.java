package com.zoop.chat.repository;

import java.time.Instant;

/** A conversation as its list shows it: its first question and how many question jobs it holds. */
public record ChatSessionSummaryRow(String id, Instant createdAt, Instant updatedAt, String firstQuestion, int jobs) {
}
