package com.zoop.document.analysis;

import java.util.Optional;

import com.zoop.ai.AnalysisKind;

/** ERD v6 {@code document_analyses.stage}: the two stages of the document analysis, and the AI kind that produces each. */
public enum AnalysisStage {
    SUMMARY("summary", AnalysisKind.DOCUMENT_SUMMARY),
    SENTIMENT("sentiment", AnalysisKind.DOCUMENT_SENTIMENT);

    private final String wire;
    private final AnalysisKind kind;

    AnalysisStage(String wire, AnalysisKind kind) {
        this.wire = wire;
        this.kind = kind;
    }

    public String wire() {
        return wire;
    }

    public AnalysisKind kind() {
        return kind;
    }

    /** A sentiment is a judgment about one company; a summary of a document has no company of its own (ERD v6). */
    public boolean companyScoped() {
        return this == SENTIMENT;
    }

    public static Optional<AnalysisStage> ofKind(AnalysisKind kind) {
        for (AnalysisStage stage : values()) {
            if (stage.kind == kind) {
                return Optional.of(stage);
            }
        }
        return Optional.empty();
    }

    public static Optional<AnalysisStage> fromWire(String value) {
        for (AnalysisStage stage : values()) {
            if (stage.wire.equals(value)) {
                return Optional.of(stage);
            }
        }
        return Optional.empty();
    }
}
