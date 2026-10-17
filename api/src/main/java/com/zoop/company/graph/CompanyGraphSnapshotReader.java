package com.zoop.company.graph;

import java.util.Optional;

/**
 * Application-owned read boundary for one public immutable graph snapshot.
 * Implementations select exactly one published snapshot, then return only public, deduplicated data.
 * Empty means no matching/published snapshot; storage or validation failures must be thrown, never mapped to empty.
 */
public interface CompanyGraphSnapshotReader {
    Optional<CompanyGraphSnapshot> read(CompanyGraphReadRequest request);
}
