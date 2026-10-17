package com.zoop.graph.version;

import java.time.Instant;
import java.util.Objects;

/**
 * The single version a request reads from, fixed once at request start. {@code asOf} is the requested reference
 * time, or the request start when none was given; it is what responses report as {@code metadata.asOf}.
 */
public record SelectedGraphVersion(GraphVersionRecord version, Instant asOf, boolean asOfRequested) {
    public SelectedGraphVersion {
        Objects.requireNonNull(version, "version");
        Objects.requireNonNull(asOf, "asOf");
    }
}
