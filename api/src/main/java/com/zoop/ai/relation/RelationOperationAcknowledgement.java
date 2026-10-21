package com.zoop.ai.relation;

import java.util.Objects;

/**
 * A 200 answer to a review. It says what the service recorded, not that the relation is published: an {@code ALLOW} is the
 * operator's final approval (terminal, no revalidation, no model call) and a {@code REJECT} an exclusion. There is nothing to poll
 * for once recorded; an unconfirmed operation is reconciled by repeating the same request.
 */
public record RelationOperationAcknowledgement(Disposition disposition, RelationOperationStatus status) {

    public RelationOperationAcknowledgement {
        Objects.requireNonNull(disposition, "disposition");
        Objects.requireNonNull(status, "status");
    }

    public enum Disposition {
        /** Review, HTTP 200: the decision is recorded (an allow is the final approval, a reject an exclusion) or the same key and body replayed an existing operation. */
        REVIEW_RECORDED_OR_REPLAYED
    }
}
