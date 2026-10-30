package com.zoop.document.bindings;

/**
 * The export failed in a defined way. The message is the code only; it has no cause and no stack trace so that nothing else
 * (a path, a value, a driver message) can ride along into a log.
 */
public final class DocumentBindingsException extends RuntimeException {
    private final DocumentBindingsFailure failure;

    public DocumentBindingsException(DocumentBindingsFailure failure) {
        super(failure.code(), null, false, false);
        this.failure = failure;
    }

    public DocumentBindingsFailure failure() {
        return failure;
    }
}
