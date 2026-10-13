package com.zoop.briefing.storage;

import java.time.Instant;
import java.time.LocalDate;
import tools.jackson.databind.JsonNode;

/** JDBC projection of the ERD v6 row; no managed entity can accidentally rewrite its JSON. */
public record BriefingRound(String id, LocalDate date, String edition, Instant scheduledAt,
        Instant windowFrom, Instant windowTo, boolean openStart, String status, Instant publishedAt,
        Instant generatedAt, String graphVersion, JsonNode payload, JsonNode publicSnapshot,
        JsonNode comparisonSnapshot) {
}
