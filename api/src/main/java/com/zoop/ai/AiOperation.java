package com.zoop.ai;

/**
 * The operations of the internal AI transports. The first five exist in every family (S1 analysis, S2 extraction, S3
 * relation); the last two are the S3 review operation: {@code REVIEW} records one decision (an allow is the operator's final
 * approval, terminal), {@code OPERATION} reads it by its key.
 */
public enum AiOperation {
    SUBMIT(true),
    STATUS(false),
    RESULT(false),
    CANCEL(true),
    RECOVER(true),
    REVIEW(true),
    OPERATION(false);

    private final boolean mutating;

    AiOperation(boolean mutating) {
        this.mutating = mutating;
    }

    /** True for operations whose request may have changed the AI service even when no response was seen. */
    public boolean mutating() {
        return mutating;
    }
}
