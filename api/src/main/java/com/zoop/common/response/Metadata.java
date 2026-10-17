package com.zoop.common.response;

import java.time.Instant;
import java.util.List;

/** The OpenAPI {@code Metadata} component: every key is always serialized; {@code graphVersion} is null when no graph was used. */
public record Metadata(String source, Instant asOf, String graphVersion, String requestId, boolean partial,
        List<SectionFailure> failures) {
}
