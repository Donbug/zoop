package com.zoop.ai.extraction;

import java.util.Objects;

/**
 * The S2 candidate set of one ready job ({@code ExtractionJobContent}: event candidates, their comparisons with the snapshot,
 * and topic candidates) as the AI service delivered it.
 *
 * <p><b>Untrusted.</b> The client verified only that it is a JSON object whose {@code jobId} and {@code inputDigest} equal the
 * requested job's status. Every candidate is model output with {@code approved=false}; none is checked here against an app
 * document version, a citation offset, a current source right or a publication rule. A later importer must validate it with its
 * own strict reader before it becomes app data. {@code toString} never prints the content.
 */
public final class UntrustedExtractionPayload {
    private final String jobId;
    private final String inputDigest;
    private final String json;

    public UntrustedExtractionPayload(String jobId, String inputDigest, String json) {
        this.jobId = Objects.requireNonNull(jobId, "jobId");
        this.inputDigest = Objects.requireNonNull(inputDigest, "inputDigest");
        this.json = Objects.requireNonNull(json, "json");
    }

    public String jobId() {
        return jobId;
    }

    public String inputDigest() {
        return inputDigest;
    }

    /** The content as compact JSON text. Parse it with the caller's own strict, typed reader; do not trust any field. */
    public String untrustedJson() {
        return json;
    }

    @Override
    public String toString() {
        return "UntrustedExtractionPayload[jobId=" + jobId + ", bytes=" + json.length() + "]";
    }
}
