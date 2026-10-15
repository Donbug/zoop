package com.zoop.artifact.storage;

/**
 * A store operation failed. The message never contains a path or content; {@code detail} is a short token (an exception
 * class name or the failing element) meant for operator logs only. There is no cause and no stack trace.
 */
public final class ArtifactStoreException extends RuntimeException {
    public enum Reason {
        /** Another importer holds the operator lock. */
        BUSY,
        /** A different file already occupies the final name; it was not modified. */
        CONFLICT,
        /** The root, directory, lock or filesystem cannot be used as required. */
        UNAVAILABLE
    }

    private final Reason reason;
    private final String detail;

    public ArtifactStoreException(Reason reason, String detail) {
        super(reason.name(), null, false, false);
        this.reason = reason;
        this.detail = detail;
    }

    public Reason reason() {
        return reason;
    }

    public String detail() {
        return detail;
    }
}
