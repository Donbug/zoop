package com.zoop.company.graph;

import java.time.Instant;
import java.util.Map;

/** Counts and the exact public graph snapshot used to calculate them; asOfRequested: the snapshot was filtered at asOf. */
public record CompanyIssueCountSnapshot(String graphVersion, Instant asOf, Map<String, Long> counts, boolean asOfRequested) {
    public CompanyIssueCountSnapshot(String graphVersion, Instant asOf, Map<String, Long> counts) {
        this(graphVersion, asOf, counts, false);
    }

    public CompanyIssueCountSnapshot {
        counts = counts == null ? null : Map.copyOf(counts);
    }
}
