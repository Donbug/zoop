package com.zoop.graph.snapshot;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;

/** The selected version exists but its snapshot cannot be read or verified: 503 SOURCE_UNAVAILABLE, never an empty graph. */
public class GraphSnapshotUnavailableException extends CustomException {
    private final String reason;

    public GraphSnapshotUnavailableException(String reason) {
        this(reason, null);
    }

    public GraphSnapshotUnavailableException(String reason, Throwable cause) {
        super(ErrorCode.SOURCE_UNAVAILABLE, cause);
        this.reason = reason;
    }

    /** Short machine reason for logs and tests; not exposed to clients. */
    public String reason() {
        return reason;
    }
}
