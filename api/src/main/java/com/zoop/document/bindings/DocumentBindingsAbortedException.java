package com.zoop.document.bindings;

/**
 * Thrown by the operator runner after the result file is written so the JVM exits non-zero. The message is the code only:
 * Spring Boot logs the exception that ends the run, and it must carry no path, text or credential.
 */
public final class DocumentBindingsAbortedException extends RuntimeException {
    private final DocumentBindingsFailure failure;

    DocumentBindingsAbortedException(DocumentBindingsFailure failure) {
        super("document bindings export failed: " + failure.code(), null, false, false);
        this.failure = failure;
    }

    public DocumentBindingsFailure failure() {
        return failure;
    }
}
