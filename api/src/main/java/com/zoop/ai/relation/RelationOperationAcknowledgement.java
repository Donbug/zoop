package com.zoop.ai.relation;

import java.util.Objects;

/**
 * A 2xx answer to a mutating review operation. It says what the service recorded, not that the relation is verified, approved
 * or published: poll {@code operation(jobId, operationId)} and follow {@code status.next()}.
 */
public record RelationOperationAcknowledgement(Disposition disposition, RelationOperationStatus status) {

    public RelationOperationAcknowledgement {
        Objects.requireNonNull(disposition, "disposition");
        Objects.requireNonNull(status, "status");
    }

    public enum Disposition {
        /** Review, HTTP 202: an allow is recorded and its revalidation is queued. */
        REVIEW_ACCEPTED,
        /** Review, HTTP 200: a reject is recorded, or the same key and body replayed an existing operation. */
        REVIEW_RECORDED_OR_REPLAYED,
        /** Recover, HTTP 202: the revalidation was re-queued. */
        RECOVERY_ENQUEUED,
        /** Recover, HTTP 200: nothing to add; a revalidation is pending or running, or the chain shows it already settled. */
        RECOVERY_COALESCED
    }
}
