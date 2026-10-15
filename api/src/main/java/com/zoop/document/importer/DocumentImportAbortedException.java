package com.zoop.document.importer;

import com.zoop.document.DocumentImportFailure;

/**
 * Thrown by the operator runner after the result file is written so the JVM exits non-zero. The message is the code only:
 * Spring Boot logs the exception that ends the run, and it must carry no path, text or credential.
 */
public final class DocumentImportAbortedException extends RuntimeException {
    private final DocumentImportFailure failure;

    DocumentImportAbortedException(DocumentImportFailure failure) {
        super("document import failed: " + failure.code(), null, false, false);
        this.failure = failure;
    }

    public DocumentImportFailure failure() {
        return failure;
    }
}
