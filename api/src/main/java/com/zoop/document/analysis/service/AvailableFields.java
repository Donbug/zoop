package com.zoop.document.analysis.service;

import java.time.Instant;

/** The result columns of an {@code available} analysis; {@code resultJson} is the stored public DTO as JSON text. */
public record AvailableFields(String resultJson, String resultVersion, String resultArtifactId, String exactReceiptId,
        String semanticReceiptId, Instant producedAt) {
}
