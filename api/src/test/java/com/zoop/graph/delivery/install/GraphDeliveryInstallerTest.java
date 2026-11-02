package com.zoop.graph.delivery.install;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Clock;
import java.time.Instant;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.repository.ArticleRow;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import com.zoop.graph.delivery.GraphDeliveryException;
import com.zoop.graph.delivery.GraphDeliveryLimits;
import com.zoop.graph.delivery.GraphDeliveryManifest;
import com.zoop.graph.delivery.JdbcGraphDeliveryStore;
import com.zoop.graph.delivery.JdbcGraphDeliveryStore.DestinationRow;
import com.zoop.graph.delivery.JdbcGraphDeliveryStore.InstallRow;
import com.zoop.graph.delivery.JdbcGraphDeliveryStore.PackageRow;
import com.zoop.graph.importer.GraphHandoffRepository;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.transaction.support.TransactionOperations;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/** Real files and authority parsing; the PostgreSQL tests and program smoke cover transaction semantics. */
class GraphDeliveryInstallerTest {
    private static final Instant NOW = Instant.parse("2026-10-31T00:00:00Z");
    private static final String HANDOFF = "delivery-install-test";
    private static final String VERSION = "gv-" + Canonical.sha256(HANDOFF);
    private static final String DESTINATION = "serving-test";
    @TempDir Path temp;
    private Path root;
    private Path sources;
    private ArtifactFileStore files;
    private GraphDeliveryInstaller installer;
    private JdbcGraphDeliveryStore deliveries;
    private DocumentRegistryRepository registry;
    private GraphVersionRepository versions;
    private GraphHandoffRepository graph;
    private GraphDeliveryInstallSettings settings;
    private List<ArtifactRow> rows;
    private final Map<String, byte[]> contents = new HashMap<>();
    private GraphDeliveryManifest manifest;
    private final AtomicReference<DestinationRow> destination = new AtomicReference<>();
    private final AtomicReference<InstallRow> acknowledgement = new AtomicReference<>();
    private final AtomicReference<Instant> currentTime = new AtomicReference<>(NOW);
    private final Clock clock = mock(Clock.class);

    @BeforeEach void prepare() throws Exception {
        root = Files.createDirectory(temp.toRealPath().resolve("serving"));
        sources = temp.toRealPath().resolve("sources.json");
        writeRegistry(true, null, "revision-a");
        files = ArtifactFileStore.at(root);
        deliveries = mock(JdbcGraphDeliveryStore.class);
        registry = mock(DocumentRegistryRepository.class);
        versions = mock(GraphVersionRepository.class);
        graph = mock(GraphHandoffRepository.class);
        when(clock.instant()).thenAnswer(call -> currentTime.get());
        installer = new GraphDeliveryInstaller(files, deliveries, registry, versions, graph, TransactionOperations.withoutTransaction(), clock, null);
        var handoffManifest = StrictJson.newObject().put("schemaVersion", "zoop-ai-handoff-1").put("handoffId", HANDOFF)
                .put("policyVersion", "zoop-public-projection-policy-2");
        String handoffDigest = Canonical.digest(handoffManifest);
        var bundle = StrictJson.newObject().put("schemaVersion", "zoop-graph-handoff-bundle-8").put("handoffId", HANDOFF).put("manifestDigest", handoffDigest);
        bundle.putObject("policy").put("version", "zoop-public-projection-policy-2");
        ArtifactRow text = artifact("text-a", "extracted_text", "text-a.txt", "Synthetic retained text".getBytes(StandardCharsets.UTF_8));
        var article = bundle.putArray("articles").addObject().put("articleId", "article-a").put("articleVersion", "version-a").put("textSha256", text.sha256());
        article.putArray("observations").addObject().put("sourceId", "source-a").putObject("grant").put("grantId", "grant-a").put("revision", "revision-a");
        var receipt = StrictJson.newObject().put("schemaVersion", "zoop-graph-handoff-import-receipt-1")
                .put("handoffId", HANDOFF).put("manifestDigest", handoffDigest).put("bundleDigest", Canonical.digest(bundle)).put("contentDigest", Canonical.digest(bundle));
        receipt.set("manifest", handoffManifest);
        receipt.set("bundle", bundle);
        receipt.putObject("producer");
        receipt.putObject("appVerification");
        ArtifactRow snapshot = artifact("artifact-" + VERSION, "graph_snapshot", "snapshot.json", "{}".getBytes(StandardCharsets.UTF_8));
        ArtifactRow projection = artifact("artifact-bundle-" + VERSION, "graph_bundle_snapshot", "projection.json", "{\"articles\":[\"article-a\"]}".getBytes(StandardCharsets.UTF_8));
        ArtifactRow receiptRow = artifact("artifact-receipt-" + VERSION, "verification_receipt", "receipt.json", Canonical.bytes(receipt));
        rows = List.of(snapshot, projection, receiptRow, text).stream().sorted(Comparator.comparing(ArtifactRow::id)).toList();
        for (ArtifactRow row : rows) {
            when(registry.findArtifact(row.id())).thenReturn(Optional.of(row));
            when(deliveries.readContent(row)).thenAnswer(call -> contents.get(row.id()));
        }
        when(graph.sources(VERSION)).thenReturn(List.of(new GraphHandoffRepository.Source(0, HANDOFF, receiptRow.id(), projection.id())));
        when(registry.findVersion("article-a", "version-a")).thenReturn(Optional.of(new VersionRow("article-a", "version-a", "Synthetic", null,
                "https://example.invalid/a", NOW, null, "datetime", null, text.id(), NOW)));
        when(registry.lockArticle("article-a")).thenReturn(Optional.of(new ArticleRow("article-a", "news", "source-a", null, "available")));
        when(versions.find(VERSION)).thenReturn(Optional.of(new GraphVersionRecord(VERSION, 1, "snapshot", snapshot.id(), snapshot.storageUri(), snapshot.sha256(), false)));
        manifest = GraphDeliveryManifest.build(VERSION, DESTINATION, HANDOFF, handoffDigest, Canonical.digest(bundle), rows);
        packageRow(manifest);
        when(deliveries.findDestination(DESTINATION)).thenAnswer(call -> Optional.ofNullable(destination.get()));
        when(deliveries.findInstall(VERSION, DESTINATION)).thenAnswer(call -> Optional.ofNullable(acknowledgement.get()));
        doAnswer(call -> { destination.set(call.getArgument(0)); return null; }).when(deliveries).insertDestination(any());
        doAnswer(call -> {
            for (ArtifactRow row : rows) assertArrayEquals(contents.get(row.id()), files.readVerified(row.storageUri(), row.sha256(), row.bytes()));
            assertTrue(Files.isRegularFile(root.resolve("graph_delivery/destination-" + DESTINATION + ".json")));
            acknowledgement.set(call.getArgument(0));
            return null;
        }).when(deliveries).insertInstall(any());
        settings = settings(root, sources.toString(), manifest.digest());
    }

    private ArtifactRow artifact(String id, String kind, String name, byte[] bytes) {
        contents.put(id, bytes);
        return new ArtifactRow(id, kind, "artifact-root:" + (kind.equals("graph_bundle_snapshot") ? "graph_bundle" : kind) + "/" + name,
                Canonical.sha256(bytes), bytes.length, kind.equals("extracted_text") ? "text/plain; charset=utf-8" : "application/json", NOW);
    }

    private void packageRow(GraphDeliveryManifest value) {
        when(deliveries.findPackage(VERSION, DESTINATION)).thenReturn(Optional.of(new PackageRow(VERSION, DESTINATION, HANDOFF,
                value.manifestDigest(), value.bundleDigest(), null, null, new String(value.bytes(), StandardCharsets.UTF_8), value.digest(), value.files().size(), value.totalBytes(), "synthetic", NOW)));
    }

    private GraphDeliveryInstallSettings settings(Path target, String authority, String digest) {
        return new GraphDeliveryInstallSettings(DESTINATION, VERSION, digest, target, temp.resolve("result.json"), authority,
                new GraphDeliveryLimits(1003, 268435456, Long.MAX_VALUE));
    }

    private String install() {
        return installer.install(settings, () -> assertEquals(ArtifactStoreException.Reason.BUSY,
                assertThrows(ArtifactStoreException.class, files::open).reason()));
    }

    private void writeRegistry(boolean enabled, Instant expiry, String revision) throws Exception {
        Path replacement = sources.resolveSibling("next-sources.json");
        Files.writeString(replacement, """
                {"schemaVersion":"zoop-ingestion-s2-1","revision":"registry-a","sources":[{
                  "sourceId":"source-a","adapter":"authored-files","inputRoot":"/synthetic",
                  "allowedHosts":["example.invalid"],"scopes":[{"scopeId":"scope-a","selection":"all",
                    "initialCursor":null,"articleXPath":null,"timestampLimitations":["synthetic"]}],
                  "grant":{"grantId":"grant-a","revision":"%s","sourceId":"source-a","enabled":%s,
                    "rights":"known","allowedOperations":["read","store","quote-display"],"recipients":[],
                    "purposes":[],"evidence":["synthetic operator grant"],"expiresAt":%s}}]}
                """.formatted(revision, enabled, expiry == null ? "null" : "\"" + expiry + "\""));
        Files.move(replacement, sources, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
    }

    private Map<String, String> fingerprint(Path target) throws Exception {
        Map<String, String> found = new HashMap<>();
        try (var walk = Files.walk(target)) {
            for (Path path : walk.filter(Files::isRegularFile).toList()) {
                if (!path.getFileName().toString().equals(ArtifactFileStore.LOCK_FILE)) {
                    found.put(target.relativize(path).toString(), Canonical.sha256(Files.readAllBytes(path)) + ":" + Files.getLastModifiedTime(path));
                }
            }
        }
        return found;
    }

    private void refusesWithoutWrites(String code) throws Exception {
        var before = fingerprint(root);
        assertEquals(code, assertThrows(GraphDeliveryException.class, this::install).code());
        assertEquals(before, fingerprint(root));
        verify(deliveries, never()).insertDestination(any());
        verify(deliveries, never()).insertInstall(any());
    }

    @Test void completeInstallationAndIdenticalReplayPreserveBytesModesAndTimes() throws Exception {
        assertEquals("installed", install());
        for (ArtifactRow row : rows) {
            Path path = root.resolve(row.storageUri().substring("artifact-root:".length()));
            assertEquals(PosixFilePermissions.fromString("rw-------"), Files.getPosixFilePermissions(path));
            assertEquals(PosixFilePermissions.fromString("rwx------"), Files.getPosixFilePermissions(path.getParent()));
            assertEquals(Files.getOwner(root), Files.getOwner(path));
        }
        var before = fingerprint(root);
        clearInvocations(deliveries);
        assertEquals("already_installed", install());
        assertEquals(before, fingerprint(root));
        verify(deliveries, never()).insertInstall(any());
        verify(deliveries, never()).insertDestination(any());
        Files.delete(root.resolve("extracted_text/text-a.txt"));
        refusesWithoutWrites("target_conflict");
    }

    @ParameterizedTest @ValueSource(strings = {"missing", "denied", "expired", "revision", "private"})
    void currentAuthorityRefusesBeforeWrites(String failure) throws Exception {
        switch (failure) {
            case "missing" -> Files.delete(sources);
            case "denied" -> writeRegistry(false, null, "revision-a");
            case "expired" -> writeRegistry(true, NOW, "revision-a");
            case "revision" -> writeRegistry(true, null, "revision-b");
            case "private" -> when(registry.lockArticle("article-a")).thenReturn(Optional.of(new ArticleRow("article-a", "news", "source-a", null, "private")));
        }
        refusesWithoutWrites(failure.equals("missing") ? "source_authority_unavailable" : "rights_denied");
    }

    @ParameterizedTest @ValueSource(strings = {"extracted_text", "graph_bundle_snapshot"})
    void omittedHiddenTextOrRuleFreeProjectionRefusesExactClosure(String omitted) throws Exception {
        var incomplete = GraphDeliveryManifest.build(VERSION, DESTINATION, HANDOFF, manifest.manifestDigest(), manifest.bundleDigest(),
                rows.stream().filter(row -> !row.kind().equals(omitted)).toList());
        packageRow(incomplete);
        settings = settings(root, sources.toString(), incomplete.digest());
        refusesWithoutWrites("package_invalid");
    }

    @ParameterizedTest @ValueSource(strings = {"empty", "many", "ordinal", "handoff", "receipt", "projection"})
    void compositionMustBeExactlyOneCompleteCurrentSource(String failure) throws Exception {
        var source = graph.sources(VERSION).getFirst();
        List<GraphHandoffRepository.Source> sources = switch (failure) {
            case "empty" -> List.of();
            case "many" -> List.of(source, source);
            default -> List.of(new GraphHandoffRepository.Source(failure.equals("ordinal") ? 1 : 0,
                    failure.equals("handoff") ? "other" : HANDOFF, failure.equals("receipt") ? "other" : source.receiptArtifactId(),
                    failure.equals("projection") ? null : source.bundleSnapshotArtifactId()));
        };
        when(graph.sources(VERSION)).thenReturn(sources);
        refusesWithoutWrites("package_invalid");
    }

    @ParameterizedTest @ValueSource(strings = {"package", "artifact", "last-content", "last-target", "mode"})
    void independentPinsAndAllTargetsArePreflighted(String failure) throws Exception {
        String code = "package_invalid";
        ArtifactRow text = rows.getLast();
        switch (failure) {
            case "package" -> { settings = settings(root, sources.toString(), "0".repeat(64)); code = "package_conflict"; }
            case "artifact" -> when(registry.findArtifact(text.id())).thenReturn(Optional.of(new ArtifactRow(text.id(), text.kind(), text.storageUri(), "0".repeat(64), text.bytes(), text.mediaType(), NOW)));
            case "last-content" -> when(deliveries.readContent(text)).thenThrow(new GraphDeliveryException("package_invalid"));
            case "last-target" -> { try (var session = files.open()) { session.put("extracted_text", "text-a.txt", new byte[] {1}); } code = "target_conflict"; }
            case "mode" -> { Files.createDirectory(root.resolve("extracted_text")); Files.setPosixFilePermissions(root.resolve("extracted_text"), PosixFilePermissions.fromString("rwxr-xr-x")); code = "artifact_unavailable"; }
        }
        refusesWithoutWrites(code);
    }

    @ParameterizedTest @ValueSource(booleans = {false, true})
    void authorityChangeAtEitherBoundaryWithholdsAcknowledgement(boolean duringWrites) throws Exception {
        AtomicInteger reads = new AtomicInteger();
        ArtifactRow text = rows.getLast();
        when(deliveries.readContent(text)).thenAnswer(call -> {
            if (reads.incrementAndGet() == (duringWrites ? 2 : 1)) writeRegistry(false, null, "revision-a");
            return contents.get(text.id());
        });
        if (!duringWrites) { refusesWithoutWrites("rights_denied"); return; }
        assertEquals("rights_denied", assertThrows(GraphDeliveryException.class, this::install).code());
        assertNull(acknowledgement.get());
        for (ArtifactRow row : rows) assertArrayEquals(contents.get(row.id()), files.readVerified(row.storageUri(), row.sha256(), row.bytes()));
        var before = fingerprint(root);
        destination.set(null);
        writeRegistry(true, null, "revision-a");
        assertEquals("installed", install());
        assertEquals(before, fingerprint(root));
    }

    @Test void unknownAcknowledgementRecoversIdenticalSecureOrphans() throws Exception {
        doThrow(new GraphDeliveryException("database_unavailable")).when(deliveries).insertInstall(any());
        assertEquals("database_unavailable", assertThrows(GraphDeliveryException.class, this::install).code());
        var before = fingerprint(root);
        destination.set(null);
        doAnswer(call -> { acknowledgement.set(call.getArgument(0)); return null; }).when(deliveries).insertInstall(any());
        assertEquals("installed", install());
        assertEquals(before, fingerprint(root));
    }

    @Test void rootIdentityRefusesCopiedMarkerAtAnotherPath() throws Exception {
        assertEquals("installed", install());
        Path other = Files.createDirectory(temp.toRealPath().resolve("other"));
        try (var session = ArtifactFileStore.at(other).open()) {
            session.put("graph_delivery", "destination-" + DESTINATION + ".json", GraphDeliveryInstaller.marker(settings));
        }
        var before = fingerprint(other);
        var next = new GraphDeliveryInstaller(ArtifactFileStore.at(other), deliveries, registry, versions, graph, TransactionOperations.withoutTransaction(), clock, null);
        assertEquals("destination_root_mismatch", assertThrows(GraphDeliveryException.class,
                () -> next.install(settings(other, sources.toString(), manifest.digest()), () -> {})).code());
        assertEquals(before, fingerprint(other));
    }

    @Test void schemaAndRootLockPrecedeDatabaseWork() throws Exception {
        assertEquals("schema_mismatch", assertThrows(GraphDeliveryException.class,
                () -> installer.install(settings, () -> { throw new GraphDeliveryException("schema_mismatch"); })).code());
        assertTrue(fingerprint(root).isEmpty());
        try (var held = files.open()) {
            assertEquals("install_busy", assertThrows(GraphDeliveryException.class, this::install).code());
        }
        verifyNoInteractions(deliveries);
    }
}
