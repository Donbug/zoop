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
     * When the version first became the active pointer (its earliest pointer change): the time a read of that version alone is
     * pinned to (#88). Empty when it never was the pointer, so it is not publicly readable by id.
     */
    Optional<Instant> firstActivatedAt(String versionId);
}
