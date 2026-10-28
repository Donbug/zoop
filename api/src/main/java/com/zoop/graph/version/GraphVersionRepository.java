package com.zoop.graph.version;

import java.time.Instant;
import java.util.Optional;

/** Read side of {@code graph_versions} and {@code graph_activations} used to pin one version per request. */
public interface GraphVersionRepository {
    Optional<GraphVersionRecord> find(String versionId);

    /** The current pointer ({@code graph_versions.active}). */
    Optional<GraphVersionRecord> active();

    /** Version of the last pointer change at or before {@code asOf}, ordered by (activated_at DESC, id DESC). */
    Optional<String> activeVersionIdAt(Instant asOf);

    /** True when the version was ever the active pointer; only such versions are publicly readable. */
    boolean everActivated(String versionId);

    /**
     * The version that was public just before {@code versionId} last became the active pointer at or before {@code at}
     * (Q05 "the previous map"); empty when it was the first, or never became the pointer by then. A store without
     * activation history has none.
     */
    default Optional<String> previousVersionId(String versionId, Instant at) {
        return Optional.empty();
    }
}
