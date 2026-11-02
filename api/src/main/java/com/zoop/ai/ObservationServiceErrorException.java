package com.zoop.ai;

import java.time.Duration;
import java.util.Optional;

/**
 * The observation export route ({@code POST /internal/v1/observations/export}) answered with an {@code ErrorEnvelope}. The
 * route is a read: a 4xx says the current rights or the selector refuse this observation ({@code source_unauthorized},
 * {@code round_not_found}, {@code registry_changed}, ...), a 5xx says the service could not run the export now.
 */
public final class ObservationServiceErrorException extends AiServiceRejectionException {
    public ObservationServiceErrorException(AiOperation operation, String requestId, int httpStatus, String code, boolean retryable,
                                             Optional<String> runtimeCode, Optional<String> field, Optional<Duration> retryAfter) {
        super(operation, requestId, httpStatus, code, retryable, runtimeCode, field, retryAfter);
    }
}
