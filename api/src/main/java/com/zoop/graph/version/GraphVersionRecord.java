package com.zoop.graph.version;

import java.util.Objects;

/** A registered graph version with the snapshot artifact it is pinned to (storage location and SHA-256). */
public record GraphVersionRecord(String id, long sequence, String kind, String snapshotArtifactId,
        String snapshotStorageUri, String snapshotSha256, boolean active) {
    public GraphVersionRecord {
        Objects.requireNonNull(id, "id");
        Objects.requireNonNull(snapshotStorageUri, "snapshotStorageUri");
        Objects.requireNonNull(snapshotSha256, "snapshotSha256");
    }
}
