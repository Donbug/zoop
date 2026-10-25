package com.zoop.graph.exclusion;

/** One failure of the exclusion command, by code only (never a value or a path). */
public class ExclusionException extends RuntimeException {
    private final ExclusionFailure failure;

    public ExclusionException(ExclusionFailure failure) {
        super(failure.code());
        this.failure = failure;
    }

    public ExclusionFailure failure() {
        return failure;
    }
}
