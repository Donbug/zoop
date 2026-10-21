package com.zoop.briefing.storage;

import java.time.Instant;

/** An append-only correction or suspension observation, never a replacement for the original. */
public record BriefingChange(long id, String kind, String eventId, String original, String corrected,
        String reason, Instant createdAt, Boolean suspended) {
}
