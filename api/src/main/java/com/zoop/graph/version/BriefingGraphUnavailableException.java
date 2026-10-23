package com.zoop.graph.version;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;

/** A known briefing basis cannot be served; a caller may show a distinct historical-snapshot notice. */
public final class BriefingGraphUnavailableException extends CustomException {
    private final String reason;

    public BriefingGraphUnavailableException(String reason) {
        super(ErrorCode.VERSION_UNAVAILABLE);
        this.reason = reason;
    }

    public String reason() { return reason; }
}
