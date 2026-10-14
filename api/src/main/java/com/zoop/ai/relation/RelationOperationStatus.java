package com.zoop.ai.relation;

import java.time.Duration;
import java.time.Instant;
import java.util.Optional;

import com.zoop.ai.PipelineJob;

/**
 * One review operation, identified exactly by the caller's operation id ({@code RelationOperationStatus}). Content-free and read
 * from the service's own ledger. The three concerns stay apart: {@link #review()} (was the decision recorded in the AI relation
 * ledger), {@link #revalidation()} (what the automatic re-check of an allow produced) and publication, which this service never
 * does: the relation is always {@code not_published}, a verdict is not an approval and {@code eligible} is not publication.
 *
 * <p>{@code expectedSourceVersion} and {@code expectedSourceRevision} are the AI source expectations the caller sent, echoed
 * back; the resulting revisions are the runtime's chain revisions after the event, never an application revision.
 */
public record RelationOperationStatus(
        String operationId,
        String jobId,
        String relationCandidateId,
        RelationDecision decision,
        String reviewer,
        String expectedSourceVersion,
        String expectedSourceRevision,
        Review review,
        Revalidation revalidation,
        Next next,
        Instant acceptedAt,
        Instant observedAt,
        Optional<Duration> retryAfter) {

    public enum ReviewState {
        /** Reserved, but the service has no proof yet that the event was appended: repeat the same request to reconcile. */
        UNCONFIRMED,
        /** The exact event is in the chain at {@code expectedSourceRevision + 1}. */
        APPLIED
    }

    public record Review(ReviewState state, Optional<String> resultingSourceRevision, Optional<Instant> recordedAt) {
    }

    public enum RevalidationState {
        NOT_REQUESTED, QUEUED, RUNNING, VERIFIED, SUPERSEDED, INTERRUPTED, FAILED, CANCELLED
    }

    /** The revalidation verdict's eligibility; an automatic evidence result, not an approval. */
    public enum Verdict {
        ELIGIBLE, HOLD, REJECT
    }

    public record Revalidation(RevalidationState state, long dispatchCount, Optional<PipelineJob.Outcome> lastOutcome,
                               Optional<String> lastRuntimeCode, Optional<Verdict> verdict, Optional<String> resultingSourceRevision,
                               Optional<Instant> updatedAt) {
    }

    public enum Next {
        WAIT, RECOVER, RETRY_REVIEW, OPERATOR_RECONCILE, NONE
    }
}
