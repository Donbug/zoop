package com.zoop.graph.importer;

/**
 * Thrown by the operator runner after the result file is written so the JVM exits non-zero. The message is the code only:
 * Spring Boot logs the exception that ends the run, and it must carry no path, text or credential.
 */
public final class GraphHandoffAbortedException extends RuntimeException {
    private final GraphHandoffFailure failure;

    GraphHandoffAbortedException(GraphHandoffFailure failure) {
        super("graph handoff import failed: " + failure.code(), null, false, false);
        this.failure = failure;
    }

    public GraphHandoffFailure failure() {
        return failure;
    }
}
