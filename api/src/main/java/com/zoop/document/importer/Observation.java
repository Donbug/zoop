package com.zoop.document.importer;

/**
 * The S2-1 {@code Export} selector (without its schema version): which exact observation of which round to export.
 * The operator copies these values from {@code zoop-ai-ingest} {@code documentRefs}; the importer never derives them.
 */
public record Observation(String roundId, String sourceId, int page, int ordinal, String documentId, String rawVersion,
        String documentVersion) {
}
