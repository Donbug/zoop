package com.zoop.graph.snapshot;

import com.zoop.graph.version.GraphVersionRecord;

/**
 * Application-owned read boundary for the immutable snapshot of one already selected graph version.
 * Callers select the version first ({@link com.zoop.graph.version.GraphVersionSelector}); a store never picks
 * another or newer version. A missing, unreadable or hash-mismatched snapshot throws
 * {@link GraphSnapshotUnavailableException} and is never turned into an empty graph.
 */
public interface GraphSnapshotStore {
    PublicGraphSnapshot load(GraphVersionRecord version);
}
