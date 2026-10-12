package com.zoop.ai;

/** The five operations of the internal AI transport. */
public enum AiOperation {
    SUBMIT(true),
    STATUS(false),
    RESULT(false),
    CANCEL(true),
    RECOVER(true);

    private final boolean mutating;

    AiOperation(boolean mutating) {
        this.mutating = mutating;
    }

    /** True for operations whose request may have changed the AI service even when no response was seen. */
    public boolean mutating() {
        return mutating;
    }
}
