package com.zoop.ai.extraction;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import com.zoop.ai.PipelineJob;

/**
 * Content-free S2 job status exactly as the AI service observed it for this request ({@code ExtractionJobStatus}, schema
 * {@code zoop-ai-internal-extraction-1}). {@code state=READY} means a candidate set exists, not that anything is approved. A
 * replay job reports zero provider calls; a live job (a real model call the operator approved and pinned server-side) reports
 * what the runtime counted, with tokens and USD null while unknown (never a guess).
 *
 * @param inputDigest the runtime job's input digest; for an S3 job over this S2 job it is the upstream {@code inputDigest}
 * @param approvedRequestDigest the digest of the operator-approved request this job was built from
 * @param executionMode {@code REPLAY} or {@code LIVE}
 */
public record ExtractionJobStatus(
        String jobId,
        String inputDigest,
        String approvedRequestDigest,
        PipelineJob.SourceKind sourceKind,
        com.zoop.ai.ExecutionMode executionMode,
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

    /**
     * {@code providerCalls} counts calls transmitted or possibly transmitted (a started call without a receipt included),
     * {@code receivedCalls} those a reply was stored for, {@code unsentCalls} those definitively not sent. Tokens and USD are null
     * while unknown.
     */
    public record Usage(long replayCalls, long startedWithoutReceipt, long providerCalls, long paidModelCalls, long receivedCalls,
                        long unsentCalls, Optional<Long> inputTokens, Optional<Long> outputTokens, Optional<Long> reasoningTokens,
                        Optional<String> estimatedUsd, Optional<String> chargedUsd) {
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
