package com.zoop.graph.delivery;

import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.PreparedStatement;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.HexFormat;
import java.util.List;
import java.util.Optional;
import java.util.Objects;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.document.repository.ArtifactRow;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.transaction.support.TransactionSynchronizationManager;

/** All mutations use the caller's transaction; the package lock serializes destination binding and acknowledgements. */
public final class JdbcGraphDeliveryStore {
    public record PackageRow(String versionId, String destinationId, String handoffId, String manifestDigest,
            String bundleDigest, String publicationId, String publicationReceiptSha256, String manifest, String packageDigest,
            int fileCount, long totalBytes, String sealedBy, Instant sealedAt) { }
    public record DestinationRow(String destinationId, String markerSha256, long markerBytes, Instant registeredAt) { }
    public record InstallRow(String versionId, String destinationId, String packageDigest, Instant installedAt) { }

    private static final RowMapper<PackageRow> PACKAGE = (rs, n) -> new PackageRow(rs.getString("version_id"),
            rs.getString("destination_id"), rs.getString("handoff_id"), rs.getString("manifest_digest"),
            rs.getString("bundle_digest"), rs.getString("publication_id"), rs.getString("publication_receipt_sha256"),
            rs.getString("manifest"), rs.getString("package_digest"), rs.getInt("file_count"),
            rs.getLong("total_bytes"), rs.getString("sealed_by"), rs.getTimestamp("sealed_at").toInstant());
    private final JdbcTemplate jdbc;

    public JdbcGraphDeliveryStore(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public void lockPackages() {
        requireTransaction();
        jdbc.execute("SET LOCAL lock_timeout = '5s'");
        jdbc.execute("SET LOCAL statement_timeout = '30s'");
        jdbc.execute("SET LOCAL idle_in_transaction_session_timeout = '300s'");
        jdbc.execute("LOCK TABLE graph_delivery_packages IN SHARE ROW EXCLUSIVE MODE");
    }

    public Optional<PackageRow> findPackage(String version, String destination) {
        return jdbc.query("SELECT * FROM graph_delivery_packages WHERE version_id = ? AND destination_id = ?",
                PACKAGE, version, destination).stream().findFirst();
    }

    public List<PackageRow> packages(String destination) {
        return jdbc.query("SELECT * FROM graph_delivery_packages WHERE destination_id = ? ORDER BY version_id", PACKAGE, destination);
    }

    public void insertPackage(PackageRow row) {
        requireTransaction();
        jdbc.update("""
                INSERT INTO graph_delivery_packages (version_id, destination_id, handoff_id, manifest_digest, bundle_digest,
                    publication_id, publication_receipt_sha256, manifest, package_digest, file_count, total_bytes, sealed_by, sealed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (version_id, destination_id) DO NOTHING
                """, row.versionId(), row.destinationId(), row.handoffId(), row.manifestDigest(), row.bundleDigest(),
                row.publicationId(), row.publicationReceiptSha256(), row.manifest(), row.packageDigest(), row.fileCount(),
                row.totalBytes(), row.sealedBy(), Timestamp.from(row.sealedAt()));
        PackageRow stored = findPackage(row.versionId(), row.destinationId()).orElseThrow(() -> failure("package_conflict"));
        if (!samePackage(stored, row)) throw failure("package_conflict");
    }

    public static boolean samePackage(PackageRow first, PackageRow second) {
        return first.versionId().equals(second.versionId()) && first.destinationId().equals(second.destinationId())
                && Objects.equals(first.handoffId(), second.handoffId()) && Objects.equals(first.manifestDigest(), second.manifestDigest())
                && Objects.equals(first.bundleDigest(), second.bundleDigest())
                && Objects.equals(first.publicationId(), second.publicationId())
                && Objects.equals(first.publicationReceiptSha256(), second.publicationReceiptSha256())
                && first.manifest().equals(second.manifest())
                && first.packageDigest().equals(second.packageDigest()) && first.fileCount() == second.fileCount()
                && first.totalBytes() == second.totalBytes();
    }

    public long pendingBytes(String destination) {
        return jdbc.queryForObject("""
                SELECT coalesce(sum(p.total_bytes), 0) FROM graph_delivery_packages p
                WHERE p.destination_id = ? AND NOT EXISTS (SELECT 1 FROM graph_delivery_installs i
                    WHERE i.version_id = p.version_id AND i.destination_id = p.destination_id)
                """, Long.class, destination);
    }

    public void putContent(ArtifactRow row, InputStream input, long length) {
        requireTransaction();
        if (length != row.bytes() || length < 0 || length > ArtifactFileStore.MAX_READ_BYTES) throw failure("package_too_large");
        CheckedInput stream = new CheckedInput(input, length);
        jdbc.update(connection -> {
            PreparedStatement statement = connection.prepareStatement("""
                    INSERT INTO graph_delivery_contents (artifact_id, sha256, bytes, content, stored_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT (artifact_id) DO NOTHING
                    """);
            statement.setQueryTimeout(30);
            statement.setString(1, row.id());
            statement.setString(2, row.sha256());
            statement.setLong(3, length);
            // PostgreSQL bytea uses setBinaryStream; setBlob would write a large-object OID.
            statement.setBinaryStream(4, stream, (int) length);
            return statement;
        });
        try {
            if (stream.count != length || stream.read() != -1
                    || !HexFormat.of().formatHex(stream.digest.digest()).equals(row.sha256())) throw failure("package_invalid");
        } catch (IOException invalid) {
            throw failure("package_invalid");
        }
        var pins = jdbc.query("SELECT sha256, bytes FROM graph_delivery_contents WHERE artifact_id = ?",
                (rs, n) -> new ContentPin(rs.getString(1), rs.getLong(2)), row.id());
        if (pins.size() != 1 || !row.sha256().equals(pins.getFirst().sha256()) || row.bytes() != pins.getFirst().bytes()) {
            throw failure("content_conflict");
        }
    }

    private record ContentPin(String sha256, long bytes) { }

    /** PostgreSQL bytea getBytes already owns the bounded array; avoid a second complete body allocation. */
    public byte[] readContent(ArtifactRow expected) {
        if (expected.bytes() < 0 || expected.bytes() > ArtifactFileStore.MAX_READ_BYTES) throw failure("package_too_large");
        try {
            return jdbc.query(connection -> {
                PreparedStatement statement = connection.prepareStatement("SELECT sha256, bytes, octet_length(content), content "
                        + "FROM graph_delivery_contents WHERE artifact_id = ?");
                statement.setQueryTimeout(30);
                statement.setString(1, expected.id());
                return statement;
            }, result -> {
                if (!result.next()) throw failure("package_invalid");
                long bytes = result.getLong(2);
                if (bytes != expected.bytes() || result.getLong(3) != bytes
                        || !expected.sha256().equals(result.getString(1))) throw failure("package_invalid");
                byte[] content = result.getBytes(4);
                if (content == null || content.length != bytes
                        || !ArtifactFileStore.sha256(content).equals(expected.sha256())) throw failure("package_invalid");
                return content;
            });
        } catch (DataAccessException error) {
            throw failure("database_unavailable");
        }
    }

    public Optional<DestinationRow> findDestination(String destination) {
        return jdbc.query("SELECT * FROM graph_delivery_destinations WHERE destination_id = ?", (rs, n) ->
                new DestinationRow(rs.getString("destination_id"), rs.getString("marker_sha256"), rs.getLong("marker_bytes"),
                        rs.getTimestamp("registered_at").toInstant()), destination).stream().findFirst();
    }

    public void insertDestination(DestinationRow row) {
        requireTransaction();
        jdbc.update("INSERT INTO graph_delivery_destinations VALUES (?, ?, ?, ?) ON CONFLICT (destination_id) DO NOTHING",
                row.destinationId(), row.markerSha256(), row.markerBytes(), Timestamp.from(row.registeredAt()));
        DestinationRow stored = findDestination(row.destinationId()).orElseThrow(() -> failure("destination_root_mismatch"));
        if (!stored.markerSha256().equals(row.markerSha256()) || stored.markerBytes() != row.markerBytes()) {
            throw failure("destination_root_mismatch");
        }
    }

    public Optional<InstallRow> findInstall(String version, String destination) {
        return jdbc.query("SELECT * FROM graph_delivery_installs WHERE version_id = ? AND destination_id = ?", (rs, n) ->
                new InstallRow(rs.getString("version_id"), rs.getString("destination_id"), rs.getString("package_digest"),
                        rs.getTimestamp("installed_at").toInstant()), version, destination).stream().findFirst();
    }

    public void insertInstall(InstallRow row) {
        requireTransaction();
        jdbc.update("INSERT INTO graph_delivery_installs VALUES (?, ?, ?, ?) ON CONFLICT (version_id, destination_id) DO NOTHING",
                row.versionId(), row.destinationId(), row.packageDigest(), Timestamp.from(row.installedAt()));
        InstallRow stored = findInstall(row.versionId(), row.destinationId()).orElseThrow(() -> failure("package_conflict"));
        if (!stored.packageDigest().equals(row.packageDigest())) throw failure("package_conflict");
    }

    private static final class CheckedInput extends FilterInputStream {
        private final MessageDigest digest;
        private final long maximum;
        private long count;

        private CheckedInput(InputStream input, long maximum) {
            super(input);
            this.maximum = maximum;
            try {
                digest = MessageDigest.getInstance("SHA-256");
            } catch (NoSuchAlgorithmException impossible) {
                throw new IllegalStateException(impossible);
            }
        }

        @Override
        public int read() throws IOException {
            int value = in.read();
            if (value >= 0) {
                if (++count > maximum) throw new IOException("content bound");
                digest.update((byte) value);
            }
            return value;
        }

        @Override
        public int read(byte[] bytes, int offset, int length) throws IOException {
            int read = in.read(bytes, offset, (int) Math.min(length, maximum - count + 1));
            if (read > 0) {
                count += read;
                if (count > maximum) throw new IOException("content bound");
                digest.update(bytes, offset, read);
            }
            return read;
        }
    }

    private static void requireTransaction() {
        if (!TransactionSynchronizationManager.isActualTransactionActive()) throw failure("transaction_required");
    }

    private static GraphDeliveryException failure(String code) { return new GraphDeliveryException(code); }
}
