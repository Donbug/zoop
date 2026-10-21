package com.zoop.ai.relation;

import java.util.Objects;

import com.zoop.ai.ExecutionMode;
import com.zoop.ai.PipelineJob;

/**
 * One S3 relation job request: the job id, the provenance class of the source material, the {@link ExecutionMode} the caller
 * chooses and the allowlisted S2 upstream. The client wraps it in the contract envelope ({@code schemaVersion=zoop-relation-s3}) with
 * the provenance pair that mode implies ({@code replay} with {@code authored-test}, {@code live} with {@code provider}) and sends the
 * {@code jobId} as the {@code Idempotency-Key}. Fixtures, registries and paths cannot be named.
 *
 * <p>{@code LIVE} is a request, never authority: the service accepts it only for an upstream the operator pinned live-approved
 * ({@code liveRuntimeIdentity}) with the live gate on, otherwise it refuses with {@code 409 live_unavailable}, {@code 403
 * live_not_approved} or {@code 409 live_binding_mismatch}. A mode is never inferred or defaulted by the client, and an answer whose
 * {@code executionMode} differs from the requested one is {@code RESPONSE_MALFORMED}.
 */
public record RelationSubmission(String jobId, PipelineJob.SourceKind sourceKind, ExecutionMode executionMode, RelationUpstream upstream) {
    public static final String SCHEMA_VERSION = "zoop-relation-s3";

    public RelationSubmission {
        PipelineJob.requireId("jobId", jobId);
        Objects.requireNonNull(sourceKind, "sourceKind");
        Objects.requireNonNull(executionMode, "executionMode");
        Objects.requireNonNull(upstream, "upstream");
    }
}
