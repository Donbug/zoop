package com.zoop.company.graph;

import java.time.Instant;
import java.util.Map;

/** Counts and the exact public graph snapshot used to calculate them. */
public record CompanyIssueCountSnapshot(String graphVersion, Instant asOf, Map<String, Long> counts) {
    public CompanyIssueCountSnapshot {
        counts = counts == null ? null : Map.copyOf(counts);
    }
}
