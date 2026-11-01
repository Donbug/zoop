package com.zoop.document.importer;

import java.util.Locale;
import java.util.Optional;

/**
 * Where an operator import gets each observation (the S2-1 export with the document text and the current-rights check):
 * {@code cli} runs the installed {@code zoop-ai-ingest export --require-store} here; {@code http} asks ai/service's
 * {@code POST /internal/v1/observations/export} (scope {@code observation.read}), which runs the same CLI against its own
 * registry and answers the same JSON. One value for every import that has the choice (graph handoff import, document import).
 */
public enum ObservationSource {
    CLI, HTTP;

    /**
     * {@code cli} or {@code http}, case-insensitively; a null or blank value is the documented default {@link #CLI} (a variable
     * listed with an empty value is no choice, like every other setting). Anything else is empty and the caller refuses it in
     * its own configuration exception, naming its own setting.
     */
    public static Optional<ObservationSource> parse(String value) {
        if (value == null || value.isBlank()) {
            return Optional.of(CLI);
        }
        return switch (value.strip().toLowerCase(Locale.ROOT)) {
            case "cli" -> Optional.of(CLI);
            case "http" -> Optional.of(HTTP);
            default -> Optional.empty();
        };
    }
}
