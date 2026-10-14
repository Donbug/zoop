package com.zoop.ai.relation;

import java.util.Objects;

import com.zoop.ai.PipelineJob;

/**
 * One S3 relation job request: the job id, the provenance class of the source material and the allowlisted S2 upstream. The
 * client wraps it in the contract envelope ({@code schemaVersion=zoop-relation-s3}) with the fixed provenance
 * {@code executionMode=replay, recordingKind=authored-test} (the only combination the service accepts) and sends the
 * {@code jobId} as the {@code Idempotency-Key}. Fixtures, registries, paths and live mode cannot be named.
 */
public record RelationSubmission(String jobId, PipelineJob.SourceKind sourceKind, RelationUpstream upstream) {
    public static final String SCHEMA_VERSION = "zoop-relation-s3";

    public RelationSubmission {
        PipelineJob.requireId("jobId", jobId);
        Objects.requireNonNull(sourceKind, "sourceKind");
        Objects.requireNonNull(upstream, "upstream");
    }
}
