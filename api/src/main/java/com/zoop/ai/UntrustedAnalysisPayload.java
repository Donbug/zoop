package com.zoop.ai;

import java.util.Objects;

/**
 * The runtime's {@code get} payload ({@code JobResult} in {@code ai-contract.schema.json}) as delivered by the AI service.
 *
 * <p><b>Untrusted.</b> The client verified only that it is a JSON object whose {@code schemaVersion}, {@code jobId},
 * {@code inputDigest}, {@code state}, {@code input.kind} and {@code input.mode} agree with the requested job and the status.
 * Its text, claims, citations and quotes are model output. Nothing here is validated against an app document version, evidence
 * or publication rule, and it is never publishable as is: the importer must check the immutable app document version, every
 * citation and the current source rights, and write the result in one transaction.
 *
 * <p>{@code toString} never prints the content.
 */
public final class UntrustedAnalysisPayload {
    private final String jobId;
    private final String json;

    public UntrustedAnalysisPayload(String jobId, String json) {
        this.jobId = Objects.requireNonNull(jobId, "jobId");
        this.json = Objects.requireNonNull(json, "json");
    }

    public String jobId() {
        return jobId;
    }

    /** The payload as compact JSON text. Parse it with the caller's own strict, typed reader; do not trust any field. */
    public String untrustedJson() {
        return json;
    }

    @Override
    public String toString() {
        return "UntrustedAnalysisPayload[jobId=" + jobId + ", bytes=" + json.length() + "]";
    }
}
