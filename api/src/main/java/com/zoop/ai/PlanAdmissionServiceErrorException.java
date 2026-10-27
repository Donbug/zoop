package com.zoop.ai;

import java.time.Duration;
import java.util.Optional;

/** A definitive admission-family error envelope. A mutating 5xx still requires status reconciliation, not a new plan ID. */
public final class PlanAdmissionServiceErrorException extends AiServiceRejectionException {
    public PlanAdmissionServiceErrorException(AiOperation operation, String requestId, int httpStatus, String code, boolean retryable,
                                               Optional<String> runtimeCode, Optional<String> field, Optional<Duration> retryAfter) {
        super(operation, requestId, httpStatus, code, retryable, runtimeCode, field, retryAfter);
    }
}
