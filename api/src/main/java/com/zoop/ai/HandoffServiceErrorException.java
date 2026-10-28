package com.zoop.ai;

import java.time.Duration;
import java.util.Optional;

/** A definitive handoff-family error envelope ({@code HdErrorEnvelope}); exposure is read-only, so nothing was changed. */
public final class HandoffServiceErrorException extends AiServiceRejectionException {
    public HandoffServiceErrorException(AiOperation operation, String requestId, int httpStatus, String code, boolean retryable,
                                        Optional<String> runtimeCode, Optional<String> field, Optional<Duration> retryAfter) {
        super(operation, requestId, httpStatus, code, retryable, runtimeCode, field, retryAfter);
    }
}
