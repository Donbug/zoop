package com.zoop.ai.relation;

import java.time.Duration;
import java.time.Instant;
import java.util.Optional;

import com.zoop.ai.PipelineJob;

/**
 * One review operation, identified exactly by the caller's operation id ({@code RelationOperationStatus}). Content-free and read
 * from the service's own ledger. {@link #review()} says whether the decision was recorded in the AI relation ledger. An
 * {@code ALLOW} is the operator's FINAL approval of a relation that was on HOLD and a {@code REJECT} an exclusion: both are
 * terminal ({@link #next()} is {@code NONE} once recorded), request no revalidation and call no model. Publication is never done
 * by this service: the relation is always {@code not_published}, and {@code eligible} is not publication.
 *
 * <p>An operation recorded under the EARLIER contract (an {@code ALLOW} that asked for an automatic revalidation) is history:
 * {@link #limitation()} is then {@link Limitation#REVIEW_CONTRACT_CHANGED}, its {@link #revalidation()} shows only what its own
 * stored history settled ({@code VERIFIED}/{@code SUPERSEDED}) or {@code CONTRACT_CHANGED}, nothing is dispatched or resent for
 * it and it is never an approval. A NEW decision at the relation's current revision is the way forward.
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
        Optional<Limitation> limitation,
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

    /**
     * {@code NOT_REQUESTED} for every operation of the current contract. The other three only describe a legacy operation:
     * {@code VERIFIED} and {@code SUPERSEDED} are what its stored history settled, {@code CONTRACT_CHANGED} that it never settled
     * and never will.
     */
    public enum RevalidationState {
        NOT_REQUESTED, VERIFIED, SUPERSEDED, CONTRACT_CHANGED
    }

    /** The verdict a legacy revalidation settled with; an automatic evidence result, not an approval. */
    public enum Verdict {
        ELIGIBLE, HOLD, REJECT
    }

    public record Revalidation(RevalidationState state, long dispatchCount, Optional<PipelineJob.Outcome> lastOutcome,
                               Optional<String> lastRuntimeCode, Optional<Verdict> verdict, Optional<String> resultingSourceRevision,
                               Optional<Instant> updatedAt) {
    }

    /** {@code RETRY_REVIEW}: the review is not proven yet, repeat the same request. {@code NONE}: nothing to do. */
    public enum Next {
        RETRY_REVIEW, NONE
    }

    /** Present exactly on an operation recorded under the earlier revalidation contract. */
    public enum Limitation {
        REVIEW_CONTRACT_CHANGED
    }
}
