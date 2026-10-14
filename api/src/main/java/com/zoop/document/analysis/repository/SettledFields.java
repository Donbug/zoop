package com.zoop.document.analysis.repository;

import java.time.Instant;

/**
 * The columns a pending {@code document_analyses} row receives when it becomes terminal. {@code resultJson} is the stored DTO
 * as JSON text and, with {@code resultVersion}, the artifact and receipt ids and {@code producedAt}, is set exactly for
 * {@code available}. {@code model}, {@code promptVersion} and {@code reasoningEffort} are those of the generation receipt
 * when the settlement has one.
 */
public record SettledFields(String status, String reason, String resultVersion, String resultJson, String resultArtifactId,
        String exactReceiptId, String semanticReceiptId, String model, String promptVersion, String reasoningEffort,
        Instant producedAt, Instant updatedAt) {
}
