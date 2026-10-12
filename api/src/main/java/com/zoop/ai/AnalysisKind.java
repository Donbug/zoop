package com.zoop.ai;

import java.util.Arrays;
import java.util.Optional;

/** The four S1 analysis kinds of contract {@code zoop-ai-s1-1}. */
public enum AnalysisKind {
    DOCUMENT_SUMMARY("document-summary"),
    DOCUMENT_SENTIMENT("document-sentiment"),
    SEMANTIC_VERIFICATION("semantic-verification"),
    BRIEFING_OUTLOOK("briefing-outlook");

    private final String wire;

    AnalysisKind(String wire) {
        this.wire = wire;
    }

    public String wire() {
        return wire;
    }

    public static Optional<AnalysisKind> fromWire(String value) {
        return Arrays.stream(values()).filter(kind -> kind.wire.equals(value)).findFirst();
    }
}
