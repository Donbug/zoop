package com.zoop.ai.extraction;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import com.zoop.ai.PipelineJob;

/**
 * Content-free S2 job status exactly as the AI service observed it for this request ({@code ExtractionJobStatus}, schema
 * {@code zoop-ai-internal-extraction-1}). {@code state=READY} means a candidate set exists, not that anything is approved; the
 * runtime is replay-only, so {@code usage.providerCalls} and {@code paidModelCalls} are zero by contract and are reported as the
 * service states them.
 *
 * @param inputDigest the runtime job's input digest; for an S3 job over this S2 job it is the upstream {@code inputDigest}
 * @param approvedRequestDigest the digest of the operator-approved request this job was built from
 */
public record ExtractionJobStatus(
        String jobId,
        String inputDigest,
        String approvedRequestDigest,
        PipelineJob.SourceKind sourceKind,
        PipelineJob.State state,
        String phase,
        PipelineJob.ResumeMode resumeMode,
        Optional<PipelineJob.Failure> failure,
        Usage usage,
        List<Stage> stages,
        PipelineJob.Delivery delivery,
        PipelineJob.Dispatch dispatch,
        PipelineJob.Next next,
        Instant acceptedAt,
        Instant observedAt,
        Optional<Duration> retryAfter) {

    public ExtractionJobStatus {
        stages = List.copyOf(stages);
    }

    public record Usage(long replayCalls, long startedWithoutReceipt, long providerCalls, long paidModelCalls) {
    }

    public enum StageName {
        EXTRACT, COMPARE, TOPIC
    }

    public enum StageState {
        PENDING, COMPLETE
    }

    public record Stage(StageName stage, StageState state) {
    }
}
