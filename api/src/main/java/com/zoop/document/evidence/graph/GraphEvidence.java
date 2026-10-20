package com.zoop.document.evidence.graph;

import java.time.Instant;
import java.util.List;
import java.util.Objects;

/**
 * What one pinned, filtered public graph version says about one evidence id: the version and reference time the request was
 * answered from, and, when the id is publicly visible there, its span and the visible issues that cite it. {@code span} is
 * {@code null} when the id is not visible in this read (not in the version, filtered by asOf or an exclusion, or cited by nothing
 * that is visible); that is an absence, never a reason on the wire.
 */
public record GraphEvidence(String graphVersion, Instant asOf, Span span, List<String> eventIds) {
    public GraphEvidence {
        Objects.requireNonNull(graphVersion, "graphVersion");
        Objects.requireNonNull(asOf, "asOf");
        eventIds = List.copyOf(eventIds);
    }

    /** The pinned span as the snapshot states it: offsets are Unicode code points, {@code end} exclusive. */
    public record Span(String articleId, String articleVersion, int start, int end) {
    }
}
