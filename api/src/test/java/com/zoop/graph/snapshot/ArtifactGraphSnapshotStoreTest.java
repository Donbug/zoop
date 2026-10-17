package com.zoop.graph.snapshot;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.exception.ErrorCode;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.service.InMemoryDocumentRegistry;
import com.zoop.graph.version.GraphVersionRecord;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * The artifact snapshot store keeps every behaviour of the {@link GraphSnapshotStore} contract and adds the artifact-specific
 * ones: the registry row decides the location, the hash and the size, and a missing, replaced or truncated file is unavailable.
 */
class ArtifactGraphSnapshotStoreTest extends GraphSnapshotStoreContractTest {
    private static final String VERSION = "fixture-2026-10-01";

    @TempDir
    Path temp;
    private Path root;
    private ArtifactFileStore files;
    private InMemoryDocumentRegistry registry;
    private ArtifactGraphSnapshotStore store;
    private final FixtureGraphSnapshotStore fixtures = new FixtureGraphSnapshotStore(getClass().getClassLoader());

    @BeforeEach
    void setUp() throws IOException {
        root = Files.createDirectory(temp.toRealPath().resolve("artifacts"));
        files = ArtifactFileStore.at(root);
        registry = new InMemoryDocumentRegistry();
        store = new ArtifactGraphSnapshotStore(files, registry, fixtures);
    }

    @Override
    GraphSnapshotStore store() {
        return store;
    }

    @Override
    GraphVersionRecord knownSnapshot() throws IOException {
        return register(GraphSnapshotCodecTest.fixture(VERSION + ".json"));
    }

    @Override
    GraphVersionRecord missingSnapshot() {
        return new GraphVersionRecord("graph-gone", 9, "snapshot", "artifact-graph-gone",
                "artifact-root:graph_snapshot/graph-gone.json", "0".repeat(64), false);
    }

    /** Stores {@code bytes} in the artifact root, registers the row and returns the version pinned to it. */
    private GraphVersionRecord register(byte[] bytes) {
        try (ArtifactFileStore.Session session = files.open()) {
            ArtifactFileStore.StoredFile file = session.put("graph_snapshot", VERSION + ".json", bytes);
            registry.insertArtifactIfAbsent(new ArtifactRow("artifact-" + VERSION, "graph_snapshot", file.uri(), file.sha256(),
                    file.bytes(), "application/json", Instant.parse("2026-10-17T00:00:00Z")));
            return new GraphVersionRecord(VERSION, 3, "snapshot", "artifact-" + VERSION, file.uri(), file.sha256(), false);
        }
    }

    private String reason(GraphVersionRecord version) {
        return assertThrows(GraphSnapshotUnavailableException.class, () -> store.load(version)).reason();
    }

    @Test
    void aMissingFileOfARegisteredSnapshotIsUnavailable() throws IOException {
        GraphVersionRecord version = knownSnapshot();
        Files.delete(root.resolve("graph_snapshot").resolve(VERSION + ".json"));

        assertEquals("snapshot_missing", reason(version));
    }

    @Test
    void aReplacedOrTruncatedFileIsAHashMismatchNotAnotherGraph() throws IOException {
        GraphVersionRecord version = knownSnapshot();
        Path file = root.resolve("graph_snapshot").resolve(VERSION + ".json");
        byte[] original = Files.readAllBytes(file);

        Files.write(file, java.util.Arrays.copyOf(original, original.length - 1));
        assertEquals("snapshot_hash_mismatch", reason(version));

        byte[] replaced = original.clone();
        replaced[replaced.length - 2] ^= 1;
        Files.write(file, replaced);
        assertEquals("snapshot_hash_mismatch", reason(version));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE,
                assertThrows(GraphSnapshotUnavailableException.class, () -> store.load(version)).getErrorCode());
    }

    @Test
    void theRegisteredRowMustBeASnapshotAtTheVersionsLocation() throws IOException {
        GraphVersionRecord version = knownSnapshot();

        GraphVersionRecord elsewhere = new GraphVersionRecord(version.id(), version.sequence(), version.kind(),
                version.snapshotArtifactId(), "artifact-root:graph_snapshot/other.json", version.snapshotSha256(), false);
        assertEquals("snapshot_location_unsupported", reason(elsewhere));

        InMemoryDocumentRegistry other = new InMemoryDocumentRegistry();
        other.insertArtifactIfAbsent(new ArtifactRow(version.snapshotArtifactId(), "extracted_text", version.snapshotStorageUri(),
                version.snapshotSha256(), 1, "text/plain", Instant.parse("2026-10-17T00:00:00Z")));
        assertEquals("snapshot_location_unsupported",
                assertThrows(GraphSnapshotUnavailableException.class,
                        () -> new ArtifactGraphSnapshotStore(files, other, fixtures).load(version)).reason());
    }

    @Test
    void aSnapshotOfAnotherVersionIdIsRefusedByTheCodec() throws IOException {
        GraphVersionRecord version = knownSnapshot();
        GraphVersionRecord renamed = new GraphVersionRecord("fixture-2026-10-08", version.sequence(), version.kind(),
                version.snapshotArtifactId(), version.snapshotStorageUri(), version.snapshotSha256(), false);

        assertEquals("snapshot_invalid:version_mismatch", reason(renamed));
    }

    /** A fixture version registered earlier by the local/dev source: same record shape, classpath location, no artifact row at all. */
    private static GraphVersionRecord bundledFixture(String sha256) throws IOException {
        byte[] bytes = GraphSnapshotCodecTest.fixture(VERSION + ".json");
        return new GraphVersionRecord(VERSION, 1, "fixture", "artifact-fixture-" + VERSION,
                FixtureGraphSnapshotStore.URI_PREFIX + VERSION + ".json",
                sha256 != null ? sha256 : FixtureGraphSnapshotStore.sha256(bytes), true);
    }

    @Test
    void bundledFixtureVersionsAreReadByTheExistingFixtureStoreNotByASecondParser() throws IOException {
        // The registry knows nothing about it and the artifact root is empty: only the classpath location can serve it.
        PublicGraphSnapshot snapshot = store.load(bundledFixture(null));

        assertEquals(VERSION, snapshot.versionId());
        assertEquals(3, snapshot.issues().size());
        assertEquals(snapshot, fixtures.load(bundledFixture(null)));
    }

    @Test
    void theFixtureLocationKeepsItsOwnHashAndLocationChecks() throws IOException {
        assertEquals("snapshot_hash_mismatch", reason(bundledFixture("0".repeat(64))));
        GraphVersionRecord outside = new GraphVersionRecord(VERSION, 1, "fixture", "artifact-fixture-" + VERSION,
                FixtureGraphSnapshotStore.URI_PREFIX + "../secret.json", "0".repeat(64), false);
        assertEquals("snapshot_location_unsupported", reason(outside));
    }
}
