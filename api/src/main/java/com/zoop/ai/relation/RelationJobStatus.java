package com.zoop.ai.relation;

import java.time.Duration;
import java.time.Instant;
import java.util.Optional;

import com.zoop.ai.PipelineJob;

/**
 * Content-free S3 job status exactly as the AI service observed it for this request ({@code RelationJobStatus}, schema
 * {@code zoop-ai-internal-relation-1}). {@code state=READY} means a candidate set exists; {@code eligible} relations inside it are
 * an automatic evidence gate or an operator's final approval, never a publication.
 *
 * @param inputDigest the S3 job's immutable input digest: its {@code sourceVersion} for reviews (it is not the upstream's digest)
 * @param executionMode {@code REPLAY} or {@code LIVE}: a live job is a real model call and exists only for an upstream the operator pinned server-side
 */
public record RelationJobStatus(
        String jobId,
        String inputDigest,
        PipelineJob.SourceKind sourceKind,
        com.zoop.ai.ExecutionMode executionMode,
        RelationUpstream upstream,
        PipelineJob.State state,
        String phase,
        PipelineJob.ResumeMode resumeMode,
        Optional<PipelineJob.Failure> failure,
        Usage usage,
        PipelineJob.Delivery delivery,
        PipelineJob.Dispatch dispatch,
        PipelineJob.Next next,
        Instant acceptedAt,
        Instant observedAt,
        Optional<Duration> retryAfter) {

    /** The version a review of this job's candidates must expect. */
    public String sourceVersion() {
        return inputDigest;
    }

    public record Usage(long replayCalls, long startedWithoutReceipt, long providerCalls, long modelCalls) {
    }
}
