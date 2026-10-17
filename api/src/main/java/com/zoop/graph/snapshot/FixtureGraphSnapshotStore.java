package com.zoop.graph.snapshot;

import com.zoop.graph.version.GraphVersionRecord;
import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/**
 * Local/dev store that reads synthetic snapshots bundled under {@code classpath:graph-fixtures/}. It verifies the
 * registered SHA-256 on every read exactly like the future artifact store will, so swapping implementations keeps the
 * failure behaviour. Only enabled with {@code zoop.graph.snapshot.source=fixture}.
 */
public class FixtureGraphSnapshotStore implements GraphSnapshotStore {
    public static final String URI_PREFIX = "classpath:graph-fixtures/";

    private final ClassLoader classLoader;

    public FixtureGraphSnapshotStore(ClassLoader classLoader) {
        this.classLoader = classLoader;
    }

    @Override
    public PublicGraphSnapshot load(GraphVersionRecord version) {
        byte[] bytes = read(version.snapshotStorageUri());
        if (!sha256(bytes).equals(version.snapshotSha256())) {
            throw new GraphSnapshotUnavailableException("snapshot_hash_mismatch");
        }
        return GraphSnapshotCodec.read(bytes, version.id());
    }

    byte[] read(String storageUri) {
        if (storageUri == null || !storageUri.startsWith(URI_PREFIX) || storageUri.contains("..")) {
            throw new GraphSnapshotUnavailableException("snapshot_location_unsupported");
        }
        try (InputStream in = classLoader.getResourceAsStream(storageUri.substring("classpath:".length()))) {
            if (in == null) throw new GraphSnapshotUnavailableException("snapshot_missing");
            return in.readAllBytes();
        } catch (IOException exception) {
            throw new GraphSnapshotUnavailableException("snapshot_unreadable", exception);
        }
    }

    public static String sha256(byte[] bytes) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }
}
