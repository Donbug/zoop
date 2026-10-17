package com.zoop.company.dto;

import java.time.Instant;
import java.util.List;

public record CompanyListMetadata(
        String source,
        Instant asOf,
        String graphVersion,
        String requestId,
        boolean partial,
        List<Object> failures) {
    public CompanyListMetadata {
        failures = List.copyOf(failures);
    }
}
