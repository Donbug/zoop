package com.zoop.ai;

import java.time.Duration;
import java.util.Optional;

/**
 * The round-run or round-handoff route answered with an {@code ErrorEnvelope}. The two POSTs are idempotent on the round id, so
 * a 5xx after a request may still have started the run or the freeze on the AI side; the scheduler reads the status before it
 * does anything else, never minting a new round id.
 */
public final class RoundServiceErrorException extends AiServiceRejectionException {
    public RoundServiceErrorException(AiOperation operation, String requestId, int httpStatus, String code, boolean retryable,
                                       Optional<String> runtimeCode, Optional<String> field, Optional<Duration> retryAfter) {
        super(operation, requestId, httpStatus, code, retryable, runtimeCode, field, retryAfter);
    }
}
