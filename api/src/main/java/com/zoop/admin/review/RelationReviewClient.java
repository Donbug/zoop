package com.zoop.admin.review;

/**
 * The AI service's relation review route ({@code POST /internal/v1/relation-jobs/{jobId}/reviews}): one {@code allow} (the
 * operator's final approval of a HOLD) or {@code reject} on one relation candidate. The AI source is the authority; the app's
 * decision row is the history of what an administrator asked. The app's own review revision is never sent.
 *
 * <p>The implementation is a later change (stage 4, when the app submits and reads S3 jobs). Until then the configured bean is
 * {@link Unconfigured}, so a decision is SOURCE_UNAVAILABLE and nothing is recorded.
 */
public interface RelationReviewClient {
    /**
     * Records the decision in the AI source. {@code operationId} is the stable idempotency key: the same id and body return the
     * existing operation, so a lost reply is retried with the same values and never appends twice.
     *
     * @throws Refused when the source refuses the decision (see {@link Refusal})
     */
    void review(String sourceJobId, String relationCandidateId, String expectedSourceVersion, String expectedSourceRevision,
            String decision, String operationId);

    /** Why the AI source refused, mapped from its error codes (internal AI contract, relation review). */
    enum Refusal {
        /** {@code source_version_conflict}, {@code source_revision_conflict}, {@code review_target_not_hold}. */
        STALE,
        /** {@code review_call_in_flight}: a model call for the job has not answered yet. */
        IN_FLIGHT,
        /** {@code review_candidate_ineligible}: a deterministic check (schema, endpoints, citations, rights) fails. */
        INELIGIBLE,
        /** {@code review_unconfirmed} or no answer: the same request must be sent again. */
        UNCONFIRMED
    }

    final class Refused extends RuntimeException {
        private final Refusal refusal;

        public Refused(Refusal refusal, String sourceCode) {
            super(sourceCode);
            this.refusal = refusal;
        }

        public Refusal refusal() {
            return refusal;
        }
    }

    /** No AI connection configured: every decision is UNCONFIRMED, which the service reports as SOURCE_UNAVAILABLE. */
    final class Unconfigured implements RelationReviewClient {
        @Override
        public void review(String sourceJobId, String relationCandidateId, String expectedSourceVersion,
                String expectedSourceRevision, String decision, String operationId) {
            throw new Refused(Refusal.UNCONFIRMED, "relation_review_not_configured");
        }
    }
}
