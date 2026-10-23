package com.zoop.admin.review;

import java.util.Locale;
import java.util.Map;

/**
 * The AI service's relation review routes: {@code POST /internal/v1/relation-jobs/{jobId}/reviews} records one {@code allow}
 * (the operator's final approval of a HOLD) or {@code reject} on one relation candidate, and
 * {@code GET /internal/v1/relation-jobs/{jobId}/reviews/{operationId}} reads an operation back. The AI source is the authority;
 * the app's decision row is the history of what an administrator asked. The app's own review revision is never sent.
 *
 * <p>The implementation is a later change (stage 4, when the app submits and reads S3 jobs). Until then the configured bean is
 * {@link Unconfigured}, so a decision is SOURCE_UNAVAILABLE and nothing is recorded in the AI source.
 */
public interface RelationReviewClient {
    /**
     * Records the decision in the AI source. {@code operationId} is the stable idempotency key: the same id and body return the
     * existing operation (even after the relation has moved on), so an ambiguous reply is retried with the same values and never
     * appends twice.
     *
     * @throws Refused when the source did not confirm the decision (see {@link Refusal})
     */
    void review(String sourceJobId, String relationCandidateId, String expectedSourceVersion, String expectedSourceRevision,
            String decision, String operationId);

    /**
     * Reads one operation back from the service ledger (content-free): its state and the command it holds, so the caller can check
     * that the operation under this id is its own command before settling anything from it.
     *
     * @throws Refused when the lookup itself is refused or does not answer
     */
    Operation lookup(String sourceJobId, String operationId);

    /** What the ledger knows about an operation ({@code RelationOperationStatus}). */
    enum Lookup {
        /** The decision event is appended. */
        RECORDED,
        /** Reserved, but the service has no proof yet that the event was appended. */
        UNCONFIRMED,
        /** No operation with this id: nothing was recorded under it. */
        NOT_FOUND
    }

    /**
     * One operation as the ledger reports it: the state and, unless {@link Lookup#NOT_FOUND}, the immutable command recorded under
     * the id ({@code jobId}, {@code relationCandidateId}, {@code decision}, {@code expectedSourceVersion},
     * {@code expectedSourceRevision}). {@code decision} is kept in the app's form ({@code allow}|{@code reject}): the wire's
     * {@code ALLOW}/{@code REJECT} is lower-cased here, so a client can pass either. {@code currentContract} is false for an
     * operation of the earlier contract ({@code limitation=review_contract_changed}): history, never an approval.
     */
    record Operation(Lookup state, String jobId, String relationCandidateId, String decision, String expectedSourceVersion,
            String expectedSourceRevision, boolean currentContract) {
        public Operation {
            decision = decision == null ? null : decision.toLowerCase(Locale.ROOT);
        }

        public static Operation notFound() {
            return new Operation(Lookup.NOT_FOUND, null, null, null, null, null, true);
        }

        /** The operation holds exactly this command under the current contract. */
        public boolean holds(String jobId, String relationCandidateId, String decision, String expectedSourceVersion,
                String expectedSourceRevision) {
            return state != Lookup.NOT_FOUND && currentContract && jobId.equals(this.jobId)
                    && relationCandidateId.equals(this.relationCandidateId) && decision.equals(this.decision)
                    && expectedSourceVersion.equals(this.expectedSourceVersion)
                    && expectedSourceRevision.equals(this.expectedSourceRevision);
        }
    }

    /**
     * Why the AI source did not confirm a decision, grouped by what the app may conclude (internal AI contract, relation review).
     * Only {@link #STALE} and {@link #INELIGIBLE} are definite: the source recorded nothing and the same request will never be
     * recorded. {@link #BUSY} and {@link #UNAVAILABLE} recorded nothing now but may later; {@link #UNCONFIRMED} may already be
     * recorded; {@link #CONTRACT} cannot be read either way and is settled only by an operation lookup.
     */
    enum Refusal {
        /** {@code source_version_conflict}, {@code source_revision_conflict}, {@code review_target_not_hold},
         * {@code relation_candidate_not_found}, {@code job_not_found}, {@code job_cancelled}. */
        STALE,
        /** {@code review_candidate_ineligible}: a deterministic check (schema, endpoints, citations, rights) fails. */
        INELIGIBLE,
        /** {@code review_call_in_flight}: a model call for the job has not answered yet. */
        BUSY,
        /**
         * {@code upstream_unavailable}, {@code execution_unavailable}, and the retryable 503s {@code service_busy},
         * {@code queue_full}, {@code service_configuration_invalid}: the source cannot act now. Not a rights revocation.
         */
        UNAVAILABLE,
        /**
         * {@code review_unconfirmed}, the retryable 503s {@code runtime_busy} and {@code runtime_unavailable} (which can follow a
         * reservation of the operation), or no answer at all: the same request must be sent again.
         */
        UNCONFIRMED,
        /** {@code idempotency_conflict}, {@code operation_id_unavailable}, {@code review_contract_changed},
         * {@code runtime_binding_mismatch}, {@code runtime_contract_mismatch}, or a code this app does not know. */
        CONTRACT;

        private static final Map<String, Refusal> CODES = Map.ofEntries(
                Map.entry("source_version_conflict", STALE), Map.entry("source_revision_conflict", STALE),
                Map.entry("review_target_not_hold", STALE), Map.entry("relation_candidate_not_found", STALE),
                Map.entry("job_not_found", STALE), Map.entry("job_cancelled", STALE),
                Map.entry("review_candidate_ineligible", INELIGIBLE),
                Map.entry("review_call_in_flight", BUSY),
                Map.entry("upstream_unavailable", UNAVAILABLE), Map.entry("execution_unavailable", UNAVAILABLE),
                Map.entry("service_busy", UNAVAILABLE), Map.entry("queue_full", UNAVAILABLE),
                Map.entry("service_configuration_invalid", UNAVAILABLE),
                Map.entry("review_unconfirmed", UNCONFIRMED), Map.entry("unconfirmed", UNCONFIRMED),
                Map.entry("runtime_busy", UNCONFIRMED), Map.entry("runtime_unavailable", UNCONFIRMED));

        /** The group of an AI error code; an unknown code is a contract mismatch, never a definite refusal. */
        public static Refusal of(String sourceCode) {
            return CODES.getOrDefault(sourceCode, CONTRACT);
        }
    }

    /** The source's answer; {@link #getMessage()} is the AI error code, kept with the intent. */
    final class Refused extends RuntimeException {
        private final Refusal refusal;

        public Refused(Refusal refusal, String sourceCode) {
            super(sourceCode);
            this.refusal = refusal;
        }

        public Refused(String sourceCode) {
            this(Refusal.of(sourceCode), sourceCode);
        }

        public Refusal refusal() {
            return refusal;
        }

        public String sourceCode() {
            return getMessage();
        }
    }

    /** No AI connection configured: every call is UNCONFIRMED, which the service reports as SOURCE_UNAVAILABLE. */
    final class Unconfigured implements RelationReviewClient {
        @Override
        public void review(String sourceJobId, String relationCandidateId, String expectedSourceVersion,
                String expectedSourceRevision, String decision, String operationId) {
            throw new Refused(Refusal.UNCONFIRMED, "relation_review_not_configured");
        }

        @Override
        public Operation lookup(String sourceJobId, String operationId) {
            throw new Refused(Refusal.UNCONFIRMED, "relation_review_not_configured");
        }
    }
}
