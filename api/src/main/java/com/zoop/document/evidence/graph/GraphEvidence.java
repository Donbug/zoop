package com.zoop.document.evidence.graph;

import java.time.Instant;
import java.util.List;
import java.util.Objects;

/**
 * What one pinned, filtered public graph version says about one evidence id: the version and reference time the request was
 * answered from, and, when the id is publicly visible there, its span and the visible issues that cite it. {@code span} is
 * {@code null} when the id is not visible in this read (not in the version, filtered by asOf or an exclusion, or cited by nothing
 * that is visible); that is an absence, never a reason on the wire.
 *
 * <p>{@code basisRefs} is non-empty only for a BASIS-ONLY span: no visible issue or relation cites the id directly
 * ({@code eventIds} is then empty), but the article version of its span is referenced by a visible structural basis of the
 * filtered snapshot (verified by the request's asOf, its relation neither excluded nor withdrawn). The snapshot cannot say which
 * evidence a basis rests on, so each reference is only a candidate: the reader of the version's retained import receipt must
 * prove that exactly this relation's exactly this basis cites the id before anything is served.
 */
public record GraphEvidence(String graphVersion, Instant asOf, Span span, List<String> eventIds, List<BasisRef> basisRefs) {
    public GraphEvidence {
        Objects.requireNonNull(graphVersion, "graphVersion");
        Objects.requireNonNull(asOf, "asOf");
        eventIds = List.copyOf(eventIds);
        basisRefs = List.copyOf(basisRefs);
    }

    /** The pinned span as the snapshot states it: offsets are Unicode code points, {@code end} exclusive. */
    public record Span(String articleId, String articleVersion, int start, int end) {
    }

    /** One visible structural basis of the filtered snapshot: its relation (id, type, endpoints) and its own basis id. */
    public record BasisRef(String relationId, String relationType, String source, String target, String basisId) {
    }
}
