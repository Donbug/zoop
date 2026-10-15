package com.zoop.common.response;

import java.time.Instant;

/** The OpenAPI {@code SectionFailure} component: one failed area of a partial 200 response. {@code asOf} may be null. */
public record SectionFailure(String section, String code, String message, boolean retryable, Instant asOf) {
}
