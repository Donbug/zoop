package com.zoop.document.evidence.graph;

import java.time.Instant;

/**
 * The evidence read's only view of the public graph: one version pinned by the shared selector, filtered exactly like every other
 * public graph read (asOf inside the version, current exclusions). Selection failures keep their own status (409 version
 * unavailable, 422 inconsistent selectors, 503 unreadable snapshot); nothing is activated, written or replaced by another version.
 */
public interface GraphEvidenceReader {

    /** @param graphVersion a pinned version id, or {@code null} for the active one; {@code asOf} {@code null} when not requested */
    GraphEvidence read(String graphVersion, Instant asOf, String evidenceId);
}
