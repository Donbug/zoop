package com.zoop.ai;

import java.util.Objects;
import java.util.regex.Pattern;

/**
 * One S1 job request. The client wraps it in the contract envelope ({@code schemaVersion=zoop-ai-s1-1}) and sends the
 * {@code jobId} as the {@code Idempotency-Key}, so the key is always the job id.
 *
 * <p>{@code inputJson} and {@code provenanceJson} are JSON objects exactly as the AI contract defines them
 * ({@code docs/api/ai-contract.schema.json}, {@code Submit}); the client checks only that each is one JSON object without
 * duplicate keys and sends it unchanged. The runtime validates the content. Never retry an ambiguous submit with a new
 * {@code jobId}: a new id is a new, separately billed generation.
 */
public record AnalysisSubmission(String jobId, AnalysisKind kind, ExecutionMode mode, String inputJson, String provenanceJson) {
    public static final String SCHEMA_VERSION = "zoop-ai-s1-1";
    /** Server pattern {@code [A-Za-z0-9_.-]{1,120}} minus the path segments {@code .} and {@code ..}. */
    public static final Pattern JOB_ID = Pattern.compile("(?!\\.{1,2}$)[A-Za-z0-9_.-]{1,120}");

    public AnalysisSubmission {
        requireJobId(jobId);
        Objects.requireNonNull(kind, "kind");
        Objects.requireNonNull(mode, "mode");
        Objects.requireNonNull(inputJson, "inputJson");
        Objects.requireNonNull(provenanceJson, "provenanceJson");
    }

    public static void requireJobId(String jobId) {
        if (jobId == null || !JOB_ID.matcher(jobId).matches()) {
            throw new IllegalArgumentException("jobId must match " + JOB_ID.pattern());
        }
    }

    /** The content stays out of logs and exception messages. */
    @Override
    public String toString() {
        return "AnalysisSubmission[jobId=" + jobId + ", kind=" + kind.wire() + ", mode=" + mode.wire() + "]";
    }
}
