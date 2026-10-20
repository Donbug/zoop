package com.zoop.briefing.storage;

import java.time.Instant;
import java.time.LocalDate;

/** History headers and the keyset position; no publication/source-controlled content is loaded. */
public record BriefingHistoryEntry(String id, LocalDate date, String edition, Instant scheduledAt,
        String status, Instant publishedAt) {
}
