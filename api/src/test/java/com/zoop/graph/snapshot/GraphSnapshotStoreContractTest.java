package com.zoop.graph.snapshot;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.version.GraphVersionRecord;
import java.io.IOException;
import org.junit.jupiter.api.Test;

/**
 * Behaviour every {@link GraphSnapshotStore} must keep. The fixture store runs it now; the artifact store added with
 * the AI hand-off import extends it with its own {@link #store()} and {@link #knownSnapshot()} so the swap is safe.
 */
abstract class GraphSnapshotStoreContractTest {
    abstract GraphSnapshotStore store();

    /** A registered version whose stored snapshot exists and matches its hash. */
    abstract GraphVersionRecord knownSnapshot() throws IOException;

    abstract GraphVersionRecord missingSnapshot();

    @Test
    void loadsTheRegisteredSnapshotOfThatVersionOnly() throws IOException {
        GraphVersionRecord version = knownSnapshot();
        assertEquals(version.id(), store().load(version).versionId());
    }

    @Test
    void hashMismatchIsUnavailableNotAnEmptyGraph() throws IOException {
        GraphVersionRecord known = knownSnapshot();
        GraphVersionRecord tampered = new GraphVersionRecord(known.id(), known.sequence(), known.kind(),
                known.snapshotArtifactId(), known.snapshotStorageUri(), "0".repeat(64), known.active());
        var failure = assertThrows(GraphSnapshotUnavailableException.class, () -> store().load(tampered));
        assertEquals("snapshot_hash_mismatch", failure.reason());
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, failure.getErrorCode());
    }

    @Test
    void missingSnapshotIsUnavailable() {
        var failure = assertThrows(GraphSnapshotUnavailableException.class, () -> store().load(missingSnapshot()));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, failure.getErrorCode());
    }
}

class FixtureGraphSnapshotStoreTest extends GraphSnapshotStoreContractTest {
    private final FixtureGraphSnapshotStore store = new FixtureGraphSnapshotStore(getClass().getClassLoader());

    @Override
    GraphSnapshotStore store() {
        return store;
    }

    @Override
    GraphVersionRecord knownSnapshot() throws IOException {
        byte[] bytes = GraphSnapshotCodecTest.fixture("fixture-2026-10-01.json");
        return new GraphVersionRecord("fixture-2026-10-01", 1, "fixture", "artifact-fixture-2026-10-01",
                FixtureGraphSnapshotStore.URI_PREFIX + "fixture-2026-10-01.json", FixtureGraphSnapshotStore.sha256(bytes), true);
    }

    @Override
    GraphVersionRecord missingSnapshot() {
        return new GraphVersionRecord("fixture-gone", 9, "fixture", "artifact-fixture-gone",
                FixtureGraphSnapshotStore.URI_PREFIX + "fixture-gone.json", "0".repeat(64), false);
    }

    @Test
    void locationsOutsideTheFixtureFolderAreRefused() {
        GraphVersionRecord outside = new GraphVersionRecord("x", 1, "snapshot", "a", "file:/etc/passwd", "0".repeat(64), true);
        assertEquals("snapshot_location_unsupported",
                assertThrows(GraphSnapshotUnavailableException.class, () -> store.load(outside)).reason());
    }
}
