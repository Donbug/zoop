package com.zoop.graph.version;

import java.time.Instant;
import java.util.Objects;

/**
 * The single version a request reads from, fixed once at request start. {@code asOf} is the requested reference
 * time, or the request start when none was given; it is what responses report as {@code metadata.asOf}.
 */
public record SelectedGraphVersion(GraphVersionRecord version, Instant asOf, boolean asOfRequested,
        BriefingGraphLookup.Basis briefing) {
    public SelectedGraphVersion(GraphVersionRecord version, Instant asOf, boolean asOfRequested) {
        this(version, asOf, asOfRequested, null);
    }
    public SelectedGraphVersion {
        Objects.requireNonNull(version, "version");
        Objects.requireNonNull(asOf, "asOf");
    }

    public boolean reconstructed() { return briefing != null && briefing.reconstruction() != null; }
    public String source() { return reconstructed() ? "briefing_reconstructed_graph" : "public_graph_snapshot"; }
}
