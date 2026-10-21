package com.zoop.ai.extraction;

import java.util.Objects;

import com.zoop.ai.ExecutionMode;
import com.zoop.ai.PipelineJob;

/**
 * One S2 extraction job request: the job id, the digest of a request the <b>operator approved on the server</b> for this
 * principal and job id ({@code ZOOP_AI_SERVICE_EXTRACTION_APPROVALS}), and the {@link ExecutionMode} the caller expects that
 * approval to run in. The snapshot, catalogue, observations, topic request, fixtures and live runtime binding are never sent and
 * cannot be named: a digest the operator did not list is refused ({@code 403 request_not_approved}) and a digest does not create
 * authority by itself.
 *
 * <p>{@code executionMode} is the caller's explicit expectation, never a switch: the server-owned approval decides whether the job
 * replays an authored recording or is live (a real, budgeted model call pinned to a runtime identity the operator approved). The
 * wire body does not carry it; the client sends the same body for both, and refuses ({@code RESPONSE_MALFORMED}, request maybe
 * processed) any answer whose {@code executionMode} differs from the one expected, so a caller can never silently end up with a
 * live job it did not ask for, or a replay it took for live.
 *
 * <p>The client wraps it in the contract envelope ({@code schemaVersion=zoop-extraction-s2-2}) and sends the {@code jobId} as the
 * {@code Idempotency-Key}. Never retry an ambiguous submit with a new {@code jobId}.
 */
public record ExtractionSubmission(String jobId, String approvedRequestDigest, ExecutionMode executionMode) {
    public static final String SCHEMA_VERSION = "zoop-extraction-s2-2";

    public ExtractionSubmission {
        PipelineJob.requireId("jobId", jobId);
        PipelineJob.requireDigest("approvedRequestDigest", approvedRequestDigest);
        Objects.requireNonNull(executionMode, "executionMode");
    }

    @Override
    public String toString() {
        return "ExtractionSubmission[jobId=" + jobId + "]";
    }
}
