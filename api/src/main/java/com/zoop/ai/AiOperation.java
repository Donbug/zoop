package com.zoop.ai;

/**
 * The operations of the internal AI transports. The first five exist in every family (S1 analysis, S2 extraction, S3
 * relation); {@code REVIEW} records one S3 review decision (an allow is the operator's final approval, terminal) and
 * {@code OPERATION} reads it by its key; {@code CHAT_STAGE} runs one synchronous chatbot model stage.
 */
public enum AiOperation {
    SUBMIT(true),
    STATUS(false),
    RESULT(false),
    CANCEL(true),
    RECOVER(true),
    REVIEW(true),
    OPERATION(false),
    /** One chatbot model stage (router, answer or verification); it may send a model request. */
    CHAT_STAGE(true),
    /** Commits reference-only plan authority; never enqueues model work. */
    PLAN_ADMIT(true);

    private final boolean mutating;

    AiOperation(boolean mutating) {
        this.mutating = mutating;
    }

    /** True for operations whose request may have changed the AI service even when no response was seen. */
    public boolean mutating() {
        return mutating;
    }
}
