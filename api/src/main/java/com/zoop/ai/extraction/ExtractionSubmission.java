package com.zoop.ai.extraction;

import com.zoop.ai.PipelineJob;

/**
 * One S2 extraction job request: the job id and the digest of a request the <b>operator approved on the server</b> for this
 * principal and job id ({@code ZOOP_AI_SERVICE_EXTRACTION_APPROVALS}). That is all a caller can send. The snapshot, catalogue,
 * observations, topic request, fixtures and execution mode are never sent and cannot be named: a digest the operator did not list
 * is refused ({@code 403 request_not_approved}) and a digest does not create authority by itself.
 *
 * <p>The client wraps it in the contract envelope ({@code schemaVersion=zoop-extraction-s2-2}) and sends the {@code jobId} as the
 * {@code Idempotency-Key}. Never retry an ambiguous submit with a new {@code jobId}.
 */
public record ExtractionSubmission(String jobId, String approvedRequestDigest) {
    public static final String SCHEMA_VERSION = "zoop-extraction-s2-2";

    public ExtractionSubmission {
        PipelineJob.requireId("jobId", jobId);
        PipelineJob.requireDigest("approvedRequestDigest", approvedRequestDigest);
    }

    @Override
    public String toString() {
        return "ExtractionSubmission[jobId=" + jobId + "]";
    }
}
