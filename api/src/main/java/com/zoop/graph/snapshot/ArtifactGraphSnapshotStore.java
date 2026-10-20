package com.zoop.graph.snapshot;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.graph.version.GraphVersionRecord;

/**
 * Reads the immutable snapshot of an imported graph version from the artifact root, through the existing read-only verified
 * artifact port ({@link ArtifactFileStore#readVerified}): no lock, no session, nothing is created, repaired or deleted. The
 * registered artifact row must be a {@code graph_snapshot} at the location and with the SHA-256 the selected version is pinned to,
 * and the file must match that row's hash and size, so a replaced, truncated or missing file is
 * {@link GraphSnapshotUnavailableException} exactly like the fixture store, never an empty graph. Only enabled with
 * {@code zoop.graph.snapshot.source=artifact}.
 *
 * <p>A version whose snapshot lives under the bundled {@code classpath:graph-fixtures/} location (registered earlier by the local/dev
 * fixture source) is read by the existing {@link FixtureGraphSnapshotStore}, not by a second parser, so switching the source on a
 * database that already has an active fixture version keeps every existing read as it was. This only chooses a reader by the
 * registered location: it never registers, seeds or activates anything and never makes an inactive version selectable (the
 * version selector decides that before any store is asked).
 */
public class ArtifactGraphSnapshotStore implements GraphSnapshotStore {
    private final ArtifactFileStore store;
    private final DocumentRegistryRepository registry;
    private final FixtureGraphSnapshotStore fixtures;

    public ArtifactGraphSnapshotStore(ArtifactFileStore store, DocumentRegistryRepository registry,
            FixtureGraphSnapshotStore fixtures) {
        this.store = store;
        this.registry = registry;
        this.fixtures = fixtures;
    }

    @Override
    public PublicGraphSnapshot load(GraphVersionRecord version) {
        if (version.snapshotStorageUri().startsWith(FixtureGraphSnapshotStore.URI_PREFIX)) {
            return fixtures.load(version);
        }
        ArtifactRow artifact = registry.findArtifact(version.snapshotArtifactId())
                .orElseThrow(() -> new GraphSnapshotUnavailableException("snapshot_missing"));
        if (!"graph_snapshot".equals(artifact.kind()) || !artifact.storageUri().equals(version.snapshotStorageUri())) {
            throw new GraphSnapshotUnavailableException("snapshot_location_unsupported");
        }
        if (!artifact.sha256().equals(version.snapshotSha256())) {
            throw new GraphSnapshotUnavailableException("snapshot_hash_mismatch");
        }
        byte[] bytes;
        try {
            bytes = store.readVerified(artifact.storageUri(), artifact.sha256(), artifact.bytes());
        } catch (ArtifactStoreException error) {
            // CONFLICT: the file is missing or is not what the registry says; UNAVAILABLE: the root or the entry cannot be used.
            String reason = error.reason() != ArtifactStoreException.Reason.CONFLICT ? "snapshot_unreadable"
                    : "missing".equals(error.detail()) ? "snapshot_missing" : "snapshot_hash_mismatch";
            throw new GraphSnapshotUnavailableException(reason, error);
        }
        return GraphSnapshotCodec.read(bytes, version.id());
    }
}
