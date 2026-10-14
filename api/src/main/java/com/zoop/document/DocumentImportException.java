package com.zoop.document;

/**
 * One import item (or the request) failed in a defined way. The message is the code only. The optional details are the
 * S2-1 CLI's own error code and, for a lost pointer compare-and-set, the actual current version; both are identifiers,
 * never text or paths. It has no cause and no stack trace so that nothing else can ride along into a log.
 */
public final class DocumentImportException extends RuntimeException {
    private final DocumentImportFailure failure;
    private final String ingestionCode;
    private final String currentVersion;
    private final boolean currentVersionKnown;

    public DocumentImportException(DocumentImportFailure failure) {
        this(failure, null, null, false);
    }

    private DocumentImportException(DocumentImportFailure failure, String ingestionCode, String currentVersion,
            boolean currentVersionKnown) {
        super(failure.code(), null, false, false);
        this.failure = failure;
        this.ingestionCode = ingestionCode;
        this.currentVersion = currentVersion;
        this.currentVersionKnown = currentVersionKnown;
    }

    /** The S2-1 CLI refused the export; {@code ingestionCode} is echoed only when it is a plain snake_case code. */
    public static DocumentImportException ingestionRefused(String ingestionCode) {
        String safe = ingestionCode != null && DocumentImportFailure.INGESTION_CODE.matcher(ingestionCode).matches()
                ? ingestionCode : null;
        return new DocumentImportException(DocumentImportFailure.INGESTION_EXPORT_FAILED, safe, null, false);
    }

    /** The compare-and-set found a different pointer; {@code actual} is null when the article has none. */
    public static DocumentImportException currentVersionConflict(String actual) {
        return new DocumentImportException(DocumentImportFailure.CURRENT_VERSION_CONFLICT, null, actual, true);
    }

    public DocumentImportFailure failure() {
        return failure;
    }

    public String ingestionCode() {
        return ingestionCode;
    }

    /** Present only for {@link DocumentImportFailure#CURRENT_VERSION_CONFLICT}. */
    public boolean hasCurrentVersion() {
        return currentVersionKnown;
    }

    public String currentVersion() {
        return currentVersion;
    }
}
