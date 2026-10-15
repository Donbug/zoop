package com.zoop.document.analysis;

/**
 * Thrown by the operator runner after the result file is written so the JVM exits non-zero. The message is the code only:
 * Spring Boot logs the exception that ends the run, and it must carry no path, text or credential.
 */
public final class DocumentAnalysisAbortedException extends RuntimeException {
    private final AnalysisFailure failure;

    DocumentAnalysisAbortedException(AnalysisFailure failure) {
        super("document analysis failed: " + failure.code(), null, false, false);
        this.failure = failure;
    }

    public AnalysisFailure failure() {
        return failure;
    }
}
