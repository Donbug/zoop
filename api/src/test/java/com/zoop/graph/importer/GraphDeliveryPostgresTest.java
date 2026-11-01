package com.zoop.graph.importer;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;
import java.util.ArrayList;
import java.util.concurrent.atomic.AtomicBoolean;
import com.zoop.common.json.StrictJson;
import com.zoop.document.evidence.service.DocumentReadSources;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.document.analysis.repository.JdbcDocumentAnalysisRepository;
import com.zoop.document.importer.IngestionExportParser;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.JdbcDocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import com.zoop.graph.delivery.GraphDeliveryClosure;
import com.zoop.graph.delivery.GraphDeliveryException;
import com.zoop.graph.delivery.GraphDeliveryLimits;
import com.zoop.graph.delivery.GraphDeliveryManifest;
import com.zoop.graph.delivery.GraphDeliverySchemaGuard;
import com.zoop.graph.delivery.JdbcGraphDeliveryStore;
import com.zoop.graph.delivery.JdbcGraphDeliveryStore.DestinationRow;
import com.zoop.graph.delivery.JdbcGraphDeliveryStore.InstallRow;
import com.zoop.graph.delivery.seal.GraphDeliverySealer;
import com.zoop.graph.delivery.seal.GraphPublicationSealRequest;
import com.zoop.graph.delivery.install.GraphDeliveryInstaller;
import com.zoop.graph.delivery.install.GraphDeliveryInstallProperties;
import com.zoop.graph.delivery.install.GraphDeliveryInstallTestSupport;
import com.zoop.graph.publication.GraphPublicationAuthority;
import com.zoop.graph.publication.GraphPublicationComposer;
import com.zoop.graph.publication.GraphPublicationReader;
import com.zoop.graph.publication.JdbcGraphPublicationRepository;
import com.zoop.graph.publication.PublicationComposeRequest;
import com.zoop.graph.publication.PublicationMerger;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.transaction.support.TransactionTemplate;
import static org.junit.jupiter.api.Assertions.*;

/** Adapted historical outbox proof using the current bundle-8 importer and its source/receipt fixtures. */
@Tag("graph-postgres")
class GraphDeliveryPostgresTest {
    private static final String SCHEMA = "delivery_" + UUID.randomUUID().toString().replace("-", "");
    private static final Instant NOW = Instant.parse("2026-10-31T01:02:03Z");
    private static final Clock CLOCK = Clock.fixed(NOW, ZoneOffset.UTC);
    private static final GraphDeliveryLimits LIMITS = new GraphDeliveryLimits(1003, 268435456, 1073741824);
    private static DriverManagerDataSource dataSource;
    private static JdbcTemplate jdbc;
    private static JdbcDocumentRegistryRepository registry;
    private static JdbcGraphHandoffRepository graph;
    private static JdbcGraphVersionRepository versions;
    private static JdbcGraphDeliveryStore deliveries;
    private static TransactionTemplate transaction;
    @TempDir Path temp;
    private ArtifactFileStore files;
    private HandoffFixtures.Built built;
    private HandoffFixtures.FakeIngestion ingestion;
    private HandoffFixtures.FakeHandoff handoff;
    private GraphHandoffImporter importer;
    private GraphDeliverySealer sealer;
    private String destination;

    @BeforeAll static void start() {
        dataSource = source(SCHEMA);
        jdbc = new JdbcTemplate(dataSource);
        jdbc.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public");
        jdbc.execute("CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public");
        Flyway.configure().dataSource(dataSource).schemas(SCHEMA).defaultSchema(SCHEMA).load().migrate();
        var named = new NamedParameterJdbcTemplate(jdbc);
        registry = new JdbcDocumentRegistryRepository(named);
        graph = new JdbcGraphHandoffRepository(named, new JdbcDocumentAnalysisRepository(named));
        versions = new JdbcGraphVersionRepository(named, CLOCK);
        deliveries = new JdbcGraphDeliveryStore(jdbc);
        transaction = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
        transaction.setTimeout(300);
        jdbc.update("INSERT INTO companies (id, name, name_key, search_text) VALUES (?, ?, '', ''), (?, ?, '', '')",
                HandoffFixtures.COMPANY_A, "합성기업", HandoffFixtures.COMPANY_B, "합성부품");
    }

    private static DriverManagerDataSource source(String schema) {
        String url = System.getenv("ZOOP_COMPANY_TEST_DB_URL");
        if (url == null || !url.matches("jdbc:postgresql://127\\.0\\.0\\.1:[0-9]+/zoop_company_test_19")) {
            throw new IllegalStateException("Set ZOOP_COMPANY_TEST_DB_URL to the dedicated localhost zoop_company_test_19 database");
        }
        return new DriverManagerDataSource(url + "?currentSchema=" + schema + ",public", "company_test",
                System.getenv().getOrDefault("ZOOP_COMPANY_TEST_DB_PASSWORD", ""));
    }

    @AfterAll static void stop() {
        if (jdbc != null) jdbc.execute("DROP SCHEMA IF EXISTS " + SCHEMA + " CASCADE");
    }

    @BeforeEach void prepare() throws Exception {
        files = ArtifactFileStore.at(Files.createDirectory(temp.toRealPath().resolve("producer")));
        built = HandoffFixtures.build(HandoffFixtures.Spec.standard().withHandoffId("delivery-" + UUID.randomUUID()));
        destination = "serving-" + UUID.randomUUID();
        ingestion = new HandoffFixtures.FakeIngestion();
        handoff = new HandoffFixtures.FakeHandoff(built.envelopeBytes());
        importer = new GraphHandoffImporter(handoff, ingestion, new IngestionExportParser(), files, registry, graph, transaction, CLOCK);
        sealer = new GraphDeliverySealer(files, registry, versions, graph, deliveries, importer, transaction, CLOCK, null, null);
        byte[] text = HandoffFixtures.TEXT.getBytes(StandardCharsets.UTF_8);
        String textId = "text-" + HandoffFixtures.ARTICLE_VERSION;
        try (var session = files.open()) {
            var stored = session.put("extracted_text", textId + ".txt", text);
            transaction.executeWithoutResult(status -> {
                registry.insertArticleIfAbsent(HandoffFixtures.ARTICLE_ID, "news", HandoffFixtures.SOURCE, NOW);
                registry.insertArtifactIfAbsent(new ArtifactRow(textId, "extracted_text", stored.uri(), stored.sha256(), stored.bytes(), "text/plain; charset=utf-8", NOW));
                registry.insertVersionIfAbsent(new VersionRow(HandoffFixtures.ARTICLE_ID, HandoffFixtures.ARTICLE_VERSION, "합성 제목", null,
                        "https://example.invalid/a", Instant.parse("2026-10-08T00:00:00Z"), null, "datetime", null, textId,
                        Instant.parse("2026-10-14T01:02:03.456789Z")));
            });
        }
    }

    @Test void sealsSharedProjectionOnceAndReplaysReadOnlyAfterAuthorityIsWithdrawn() {
        var first = sealer.seal(built.request(), destination, LIMITS);
        assertEquals("sealed", first.outcome());
        assertEquals(3, first.fileCount());
        assertEquals(3, ingestion.calls.get());
        assertFalse(versions.find(first.versionId()).orElseThrow().active());
        assertFalse(versions.everActivated(first.versionId()));
        var row = deliveries.findPackage(first.versionId(), destination).orElseThrow();
        var manifest = GraphDeliveryManifest.parse(row.manifest().getBytes(StandardCharsets.UTF_8));
        assertEquals(first.packageDigest(), manifest.digest());
        assertEquals("artifact-" + first.versionId(), graph.sources(first.versionId()).getFirst().bundleSnapshotArtifactId());
        for (var pin : manifest.files()) {
            byte[] bytes = deliveries.readContent(registry.findArtifact(pin.artifactId()).orElseThrow());
            assertEquals(pin.bytes(), bytes.length);
            assertEquals(pin.sha256(), Canonical.sha256(bytes));
        }
        handoff.withholdFrom(4);
        ingestion.refuseFrom(4, "source_unauthorized");
        var replay = sealer.seal(built.request(), destination, new GraphDeliveryLimits(2, 1, 1));
        assertEquals("already_sealed", replay.outcome());
        assertEquals(3, ingestion.calls.get());
        assertEquals(3, handoff.calls.get());
        assertEquals(row, deliveries.findPackage(first.versionId(), destination).orElseThrow());
        assertEquals(first.totalBytes(), deliveries.pendingBytes(destination));
    }

    @Test void bothSourcePinsAndBusyProducerRootRefuse() {
        var first = sealer.seal(built.request(), destination, LIMITS);
        for (boolean manifest : List.of(false, true)) {
            var changed = new GraphHandoffRequest(built.request().handoffId(), manifest ? "f".repeat(64) : built.manifestDigest(),
                    manifest ? built.bundleDigest() : "f".repeat(64), "tester");
            assertCode("package_conflict", () -> sealer.seal(changed, destination, LIMITS));
        }
        try (var session = files.open()) { assertCode("import_busy", () -> sealer.seal(built.request(), destination + "-b", LIMITS)); }
        assertEquals(1, deliveries.packages(destination).size());
        assertEquals(first.packageDigest(), deliveries.findPackage(first.versionId(), destination).orElseThrow().packageDigest());
    }

    @Test void freshSourceRefusalAfterOutboxWritesRollsBackOnlyTheSealCommit() {
        int before = count("graph_delivery_contents");
        ingestion.refuseFrom(3, "source_unauthorized");
        assertCode("ingestion_export_failed", () -> sealer.seal(built.request(), destination, LIMITS));
        assertTrue(deliveries.findPackage(built.versionId(), destination).isEmpty());
        assertEquals(before, count("graph_delivery_contents"));
        assertFalse(versions.find(built.versionId()).orElseThrow().active());
        ingestion.refuseFrom(Integer.MAX_VALUE, "source_unauthorized");
        assertEquals("sealed", sealer.seal(built.request(), destination, LIMITS).outcome());
    }

    @Test void unchangedImportStillChecksCurrentAuthorityInsideSealTransaction() {
        assertTrue(importer.run(built.request()).succeeded());
        int before = count("graph_delivery_contents");
        var original = ingestion.serve;
        var reached = new java.util.concurrent.atomic.AtomicBoolean();
        ingestion.serve = observation -> {
            if (deliveries.findPackage(built.versionId(), destination).isPresent()) {
                reached.set(true);
                assertTrue(org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive());
                throw com.zoop.document.DocumentImportException.ingestionRefused("source_unauthorized");
            }
            return original.apply(observation);
        };
        assertCode("ingestion_export_failed", () -> sealer.seal(built.request(), destination, LIMITS));
        assertTrue(reached.get());
        assertTrue(deliveries.findPackage(built.versionId(), destination).isEmpty());
        assertEquals(before, count("graph_delivery_contents"));
    }

    @Test void withheldHandoffAtFinalSealCheckLeavesOnlyInactiveStaging() {
        int before = count("graph_delivery_contents");
        handoff.withholdFrom(3);
        assertCode("handoff_withheld", () -> sealer.seal(built.request(), destination, LIMITS));
        assertTrue(deliveries.packages(destination).isEmpty());
        assertEquals(before, count("graph_delivery_contents"));
        assertFalse(versions.find(built.versionId()).orElseThrow().active());
    }

    @Test void filePackageAndPendingBoundsRefuseBeforeOutboxWrites() {
        int before = count("graph_delivery_contents");
        assertCode("package_too_large", () -> sealer.seal(built.request(), destination, new GraphDeliveryLimits(2, 268435456, 1073741824)));
        assertCode("package_too_large", () -> sealer.seal(built.request(), destination, new GraphDeliveryLimits(1003, 1, 1073741824)));
        assertCode("outbox_full", () -> sealer.seal(built.request(), destination, new GraphDeliveryLimits(1003, 268435456, 1)));
        assertTrue(deliveries.packages(destination).isEmpty());
        assertEquals(before, count("graph_delivery_contents"));
    }

    @Test void immutableTablesAndDigestForeignKeyProtectAcknowledgements() {
        var sealed = sealer.seal(built.request(), destination, LIMITS);
        transaction.executeWithoutResult(status -> { deliveries.lockPackages(); deliveries.insertDestination(new DestinationRow(destination, "c".repeat(64), 12, NOW)); });
        assertThrows(DataAccessException.class, () -> transaction.executeWithoutResult(status -> {
            deliveries.lockPackages(); deliveries.insertInstall(new InstallRow(sealed.versionId(), destination, "d".repeat(64), NOW));
        }));
        transaction.executeWithoutResult(status -> { deliveries.lockPackages(); deliveries.insertInstall(new InstallRow(sealed.versionId(), destination, sealed.packageDigest(), NOW)); });
        assertEquals(0, deliveries.pendingBytes(destination));
        for (String table : List.of("graph_delivery_packages", "graph_delivery_contents", "graph_delivery_destinations", "graph_delivery_installs")) {
            String key = table.equals("graph_delivery_contents") ? "artifact_id" : table.equals("graph_delivery_destinations") ? "destination_id" : "version_id";
            assertThrows(DataAccessException.class, () -> jdbc.update("UPDATE " + table + " SET " + key + " = " + key));
            assertThrows(DataAccessException.class, () -> jdbc.update("DELETE FROM " + table));
        }
        assertEquals(sealed.packageDigest(), deliveries.findInstall(sealed.versionId(), destination).orElseThrow().packageDigest());
    }

    @Test void byteaDedupVerifiesActualInputAndStoredBody() {
        ArtifactRow row = registry.findArtifact("text-" + HandoffFixtures.ARTICLE_VERSION).orElseThrow();
        byte[] bytes = HandoffFixtures.TEXT.getBytes(StandardCharsets.UTF_8);
        transaction.executeWithoutResult(status -> {
            deliveries.lockPackages();
            deliveries.putContent(row, new ByteArrayInputStream(bytes), bytes.length);
            deliveries.putContent(row, new ByteArrayInputStream(bytes), bytes.length);
        });
        assertEquals("bytea", jdbc.queryForObject("SELECT pg_typeof(content)::text FROM graph_delivery_contents WHERE artifact_id = ?", String.class, row.id()));
        byte[] changed = bytes.clone(); changed[0] ^= 1;
        assertCode("package_invalid", () -> transaction.executeWithoutResult(status -> { deliveries.lockPackages(); deliveries.putContent(row, new ByteArrayInputStream(changed), changed.length); }));
        assertArrayEquals(bytes, deliveries.readContent(row));
        String id = "corrupt-" + UUID.randomUUID();
        ArtifactRow bad = new ArtifactRow(id, row.kind(), "artifact-root:extracted_text/" + id + ".txt", row.sha256(), row.bytes(), row.mediaType(), NOW);
        transaction.executeWithoutResult(status -> {
            registry.insertArtifactIfAbsent(bad);
            jdbc.update("INSERT INTO graph_delivery_contents VALUES (?, ?, ?, ?, ?)", bad.id(), bad.sha256(), bad.bytes(), changed, java.sql.Timestamp.from(NOW));
        });
        assertCode("package_invalid", () -> deliveries.readContent(bad));
    }

    @Test void schemaValidationRefusesPendingMigrationWithoutApplyingIt() {
        var environment = new MockEnvironment().withProperty("spring.flyway.enabled", "false");
        int before = count("flyway_schema_history");
        GraphDeliverySchemaGuard.validate(dataSource, environment);
        assertEquals(before, count("flyway_schema_history"));
        for (String target : List.of("20261031130000", "20261031150000", "20261031160000")) {
            String older = "delivery_old_" + UUID.randomUUID().toString().replace("-", "");
            var oldSource = source(older);
            var oldJdbc = new JdbcTemplate(oldSource);
            try {
                Flyway.configure().dataSource(oldSource).schemas(older).defaultSchema(older).target(target).load().migrate();
                int history = oldJdbc.queryForObject("SELECT count(*) FROM flyway_schema_history", Integer.class);
                assertCode("schema_mismatch", () -> GraphDeliverySchemaGuard.validate(oldSource, environment));
                assertEquals(history, oldJdbc.queryForObject("SELECT count(*) FROM flyway_schema_history", Integer.class));
                assertEquals(target.equals("20261031160000") ? 1 : 0, oldJdbc.queryForObject(
                        "SELECT count(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = 'graph_delivery_packages'", Integer.class, older));
            } finally { jdbc.execute("DROP SCHEMA IF EXISTS " + older + " CASCADE"); }
        }
    }

    @Test void deliveryMigrationsUpgradePublishedRoundsWithoutRewritingHistory() {
        String schema = "delivery_upgrade_" + UUID.randomUUID().toString().replace("-", "");
        var upgradeSource = source(schema);
        var upgradeJdbc = new JdbcTemplate(upgradeSource);
        try {
            Flyway.configure().dataSource(upgradeSource).schemas(schema).defaultSchema(schema)
                    .target("20261031130000").load().migrate();
            var history = upgradeJdbc.queryForList(
                    "SELECT * FROM flyway_schema_history ORDER BY installed_rank");
            var candidate = Flyway.configure().dataSource(upgradeSource).schemas(schema).defaultSchema(schema).load();
            assertEquals(5, candidate.migrate().migrationsExecuted);
            candidate.validate();
            assertEquals(history, upgradeJdbc.queryForList(
                    "SELECT * FROM flyway_schema_history ORDER BY installed_rank LIMIT ?", history.size()));
            assertEquals(List.of("20261031150000", "20261031160000", "20261031170000", "20261031180000", "20261101090000"),
                    upgradeJdbc.queryForList("""
                            SELECT version FROM flyway_schema_history
                            WHERE version > '20261031130000' AND success ORDER BY installed_rank
                            """, String.class));
            assertEquals(1, upgradeJdbc.queryForObject("""
                    SELECT count(*) FROM information_schema.columns
                    WHERE table_schema = ? AND table_name = 'graph_rounds' AND column_name = 'ingestion_round_id'
                    """, Integer.class, schema));
        } finally {
            jdbc.execute("DROP SCHEMA IF EXISTS " + schema + " CASCADE");
        }
    }

    @Test void requestJournalUpgradesTheCurrentPublicationLineageOnly() {
        String schema = "round_upgrade_" + UUID.randomUUID().toString().replace("-", "");
        var upgradeSource = source(schema);
        var upgradeJdbc = new JdbcTemplate(upgradeSource);
        try {
            Flyway.configure().dataSource(upgradeSource).schemas(schema).defaultSchema(schema)
                    .target("20261031180000").load().migrate();
            var history = upgradeJdbc.queryForList("SELECT * FROM flyway_schema_history ORDER BY installed_rank");
            var candidate = Flyway.configure().dataSource(upgradeSource).schemas(schema).defaultSchema(schema).load();
            assertEquals(1, candidate.migrate().migrationsExecuted);
            candidate.validate();
            assertEquals(history, upgradeJdbc.queryForList(
                    "SELECT * FROM flyway_schema_history ORDER BY installed_rank LIMIT ?", history.size()));
            assertEquals(0, upgradeJdbc.queryForObject("SELECT count(*) FROM graph_round_requests", Integer.class));
            assertEquals(1, upgradeJdbc.queryForObject("""
                    SELECT count(*) FROM information_schema.columns
                    WHERE table_schema = ? AND table_name = 'graph_rounds' AND column_name = 'ingestion_round_id'
                    """, Integer.class, schema));
        } finally {
            jdbc.execute("DROP SCHEMA IF EXISTS " + schema + " CASCADE");
        }
    }

    @Test void filteredArticlesKeepTheirTextAndSeparateRuleFreeProjection() {
        jdbc.update("UPDATE publication_rules SET enabled = true, revision = revision + 1 WHERE id = 'single-source@1'");
        try {
            var result = sealer.seal(built.request(), destination, LIMITS);
            var snapshot = registry.findArtifact("artifact-" + built.versionId()).orElseThrow();
            assertEquals(0, com.zoop.graph.snapshot.GraphSnapshotCodec.read(files.readVerified(snapshot.storageUri(), snapshot.sha256(), snapshot.bytes()), built.versionId()).articles().size());
            var receipt = registry.findArtifact("artifact-receipt-" + built.versionId()).orElseThrow();
            List<ArtifactRow> closure = GraphDeliveryClosure.resolve(built.versionId(), files.readVerified(receipt.storageUri(), receipt.sha256(), receipt.bytes()), registry, versions, graph);
            assertEquals(4, closure.size());
            assertEquals(4, result.fileCount());
            var projection = closure.stream().filter(row -> row.kind().equals("graph_bundle_snapshot")).findFirst().orElseThrow();
            assertTrue(projection.storageUri().startsWith("artifact-root:graph_bundle/"));
            assertNotEquals(snapshot.sha256(), projection.sha256());
            assertEquals(1, com.zoop.graph.snapshot.GraphSnapshotCodec.read(deliveries.readContent(projection), built.versionId()).articles().size());
            assertTrue(closure.stream().anyMatch(row -> row.kind().equals("extracted_text")));
        } finally { jdbc.update("UPDATE publication_rules SET enabled = false, revision = revision + 1 WHERE id = 'single-source@1'"); }
    }

    @Test void statusReportsRecordedStateWithoutFreshAuthorityClaim() throws Exception {
        var sealed = sealer.seal(built.request(), destination, LIMITS);
        var before = deliveries.findPackage(sealed.versionId(), destination).orElseThrow();
        handoff.withholdFrom(4); ingestion.refuseFrom(4, "source_unauthorized");
        var beans = new org.springframework.beans.factory.support.DefaultListableBeanFactory();
        Path result = temp.toRealPath().resolve("status.json");
        var settings = new com.zoop.graph.delivery.seal.GraphDeliverySealProperties(true, "status", destination, 1003, 268435456, 1073741824, result.toString(), null, null);
        var runner = new com.zoop.graph.delivery.seal.GraphDeliverySealRunner(settings, beans.getBeanProvider(GraphDeliverySealer.class), beans.getBeanProvider(GraphHandoffImportSettings.class),
                deliveries, versions, dataSource, new MockEnvironment().withProperty("spring.flyway.enabled", "false"));
        runner.run(null);
        var report = com.zoop.common.json.StrictJson.parseObject(Files.readAllBytes(result));
        var item = report.objects("packages").getFirst().exactly(java.util.Set.of("versionId", "sealed", "packageDigest", "installed", "active", "wasActive"));
        assertTrue(item.bool("sealed")); assertFalse(item.bool("installed")); assertFalse(item.bool("active")); assertFalse(item.bool("wasActive"));
        assertEquals(sealed.packageDigest(), item.string("packageDigest"));
        assertEquals(before, deliveries.findPackage(sealed.versionId(), destination).orElseThrow());
        assertEquals(3, ingestion.calls.get());
    }

    private static int count(String table) { return jdbc.queryForObject("SELECT count(*) FROM " + table, Integer.class); }

    private record Composed(GraphPublicationReader.Publication publication, GraphPublicationReader reader,
            JdbcGraphPublicationRepository metadata, Path authority) { }

    private Composed composeFilteredPublication() throws Exception {
        Path authority = temp.toRealPath().resolve("publication-authority.json");
        writeAuthority(authority, true, "rights-1");
        jdbc.update("UPDATE publication_rules SET enabled = true, revision = revision + 1 WHERE id = 'single-source@1'");
        try {
            assertTrue(importer.run(built.request()).succeeded());
            var next = HandoffFixtures.build(HandoffFixtures.Spec.standard().withHandoffId("delivery-" + UUID.randomUUID()));
            var nextImporter = new GraphHandoffImporter(new HandoffFixtures.FakeHandoff(next.envelopeBytes()),
                    new HandoffFixtures.FakeIngestion(), new IngestionExportParser(), files, registry, graph, transaction, CLOCK);
            assertTrue(nextImporter.run(next.request()).succeeded());
            var result = compose(List.of(built.versionId(), next.versionId()), null, authority);
            assertTrue(result.publication().snapshot().articles().isEmpty());
            assertEquals(2, result.publication().contributions().size());
            return result;
        } finally {
            jdbc.update("UPDATE publication_rules SET enabled = false, revision = revision + 1 WHERE id = 'single-source@1'");
        }
    }

    private Composed compose(List<String> incomingVersions, String base, Path authority) {
        var sources = new DocumentReadSources(authority);
        var metadata = new JdbcGraphPublicationRepository(new NamedParameterJdbcTemplate(jdbc));
        var reader = new GraphPublicationReader(graph, registry, files, metadata);
        var rights = new GraphPublicationAuthority(registry, sources,
                version -> new DisclosureExclusions(0, java.util.Set.of(), java.util.Set.of(), java.util.Set.of(), java.util.Set.of()), CLOCK);
        var incoming = incomingVersions.stream().sorted().toList();
        var pins = new java.util.TreeMap<String, String>();
        for (String id : incoming) pins.put(id, registry.findArtifact("artifact-receipt-" + id).orElseThrow().sha256());
        byte[] decisions = Canonical.bytes(PublicationMerger.emptyDecisions().node());
        var state = graph.publicationState();
        String baseReceipt = base == null ? null : registry.findArtifact("artifact-receipt-" + base).orElseThrow().sha256();
        var request = new PublicationComposeRequest(base, incoming, base, baseReceipt, pins,
                state.ruleRevision(), state.reviewRevision(), Canonical.sha256(decisions), "synthetic");
        var composer = new GraphPublicationComposer(files, graph, registry, versions, metadata, reader, rights, sources, transaction, CLOCK);
        var result = composer.run(request, decisions);
        assertEquals("succeeded", result.get("status").asString(), result.toString());
        return new Composed(reader.read(result.get("graphVersionId").asString()), reader, metadata, authority);
    }

    private void writeAuthority(Path path, boolean enabled, String revision) throws Exception {
        Files.writeString(path, """
                {"schemaVersion":"zoop-ingestion-s2-1","revision":"registry-a","sources":[{
                  "sourceId":"synthetic-source","adapter":"authored-files","inputRoot":"/synthetic",
                  "allowedHosts":["example.invalid"],"scopes":[{"scopeId":"scope-a","selection":"all",
                    "initialCursor":null,"articleXPath":null,"timestampLimitations":["synthetic"]}],
                  "grant":{"grantId":"operator-grant","revision":"%s","sourceId":"synthetic-source","enabled":%s,
                    "rights":"known","allowedOperations":["read","store","quote-display"],"recipients":[],
                    "purposes":[],"evidence":["synthetic operator grant"],"expiresAt":null}}]}
                """.formatted(revision, enabled));
    }

    private GraphDeliverySealer publicationSealer(Composed fixture, org.springframework.transaction.support.TransactionOperations tx) {
        return new GraphDeliverySealer(files, registry, versions, graph, deliveries, importer, tx, CLOCK,
                fixture.reader(), fixture.authority().toString());
    }

    private GraphPublicationSealRequest publicationRequest(Composed fixture, String target) {
        return new GraphPublicationSealRequest(fixture.publication().versionId(), fixture.publication().receipt().sha256(),
                target, "synthetic");
    }

    private String installPublication(Composed fixture, Path root, String target, String digest, JdbcGraphDeliveryStore store,
            org.springframework.transaction.support.TransactionOperations tx) {
        var reader = new GraphPublicationReader(graph, registry, store::readContent, fixture.metadata());
        var installer = new GraphDeliveryInstaller(ArtifactFileStore.at(root), store, registry, versions, graph, tx, CLOCK, reader);
        var properties = new GraphDeliveryInstallProperties(true, target, fixture.publication().versionId(), digest,
                root.toString(), temp.resolve("unused-result.json").toString(), LIMITS.maxFiles(), LIMITS.maxPackageBytes());
        return GraphDeliveryInstallTestSupport.install(installer, properties, fixture.authority().toString(),
                () -> GraphDeliverySchemaGuard.validate(dataSource, new MockEnvironment().withProperty("spring.flyway.enabled", "false")));
    }

    @Test void publicationDeliveryUsesExactFlatHiddenClosureAndIndependentInstallerProof() throws Exception {
        var fixture = composeFilteredPublication();
        int nativeCalls = handoff.calls.get();
        var sealed = publicationSealer(fixture, transaction).sealPublication(publicationRequest(fixture, destination), LIMITS);
        assertEquals("sealed", sealed.outcome());
        assertEquals(nativeCalls, handoff.calls.get());
        var row = deliveries.findPackage(sealed.versionId(), destination).orElseThrow();
        assertNull(row.handoffId()); assertNull(row.manifestDigest()); assertNull(row.bundleDigest());
        assertEquals(fixture.publication().publicationId(), row.publicationId());
        assertEquals(fixture.publication().receipt().sha256(), row.publicationReceiptSha256());
        var manifest = GraphDeliveryManifest.parse(row.manifest().getBytes(StandardCharsets.UTF_8));
        assertEquals(7, manifest.files().size());
        assertEquals(fixture.reader().closure(fixture.publication()).stream().map(GraphDeliveryManifest.FilePin::from).toList(), manifest.files());
        for (var contribution : fixture.publication().contributions()) {
            assertTrue(manifest.files().stream().anyMatch(pin -> pin.artifactId().equals(contribution.receipt().id())));
            assertTrue(manifest.files().stream().anyMatch(pin -> pin.artifactId().equals(contribution.projectionArtifact().id())));
            assertFalse(manifest.files().stream().anyMatch(pin -> pin.artifactId().equals("artifact-" + contribution.sourceVersionId())));
        }
        assertEquals(1, manifest.files().stream().filter(pin -> pin.kind().equals("extracted_text")).count());
        Path serving = Files.createDirectory(temp.toRealPath().resolve("serving-publication"));
        assertEquals("installed", installPublication(fixture, serving, destination, sealed.packageDigest(), deliveries, transaction));
        for (var pin : manifest.files()) assertArrayEquals(deliveries.readContent(registry.findArtifact(pin.artifactId()).orElseThrow()),
                ArtifactFileStore.at(serving).readVerified(pin.storageUri(), pin.sha256(), pin.bytes()));
        assertEquals("already_installed", installPublication(fixture, serving, destination, sealed.packageDigest(), deliveries, transaction));
        assertFalse(versions.find(sealed.versionId()).orElseThrow().active());
        assertFalse(versions.everActivated(sealed.versionId()));
        writeAuthority(fixture.authority(), false, "rights-1");
        assertCode("rights_denied", () -> publicationSealer(fixture, transaction).sealPublication(publicationRequest(fixture, destination), LIMITS));
        assertCode("rights_denied", () -> installPublication(fixture, serving, destination, sealed.packageDigest(), deliveries, transaction));
    }

    @Test void publicationInstallerRejectsMissingExtraCorruptFilesAndWrongDestination() throws Exception {
        var fixture = composeFilteredPublication();
        var sealed = publicationSealer(fixture, transaction).sealPublication(publicationRequest(fixture, destination), LIMITS);
        var full = fixture.reader().closure(fixture.publication());
        for (String defect : List.of("verification_receipt", "graph_bundle_snapshot", "extracted_text", "extra")) {
            var rows = new ArrayList<>(full);
            if (defect.equals("extra")) rows.add(registry.findArtifact("artifact-" + built.versionId()).orElseThrow());
            else rows.removeIf(row -> row.kind().equals(defect) && !row.id().equals(fixture.publication().receipt().id()));
            String target = defect.replace('_', '-') + "-" + UUID.randomUUID();
            var manifest = GraphDeliveryManifest.publication(sealed.versionId(), target, fixture.publication().publicationId(),
                    fixture.publication().receipt().sha256(), rows);
            transaction.executeWithoutResult(status -> {
                deliveries.lockPackages();
                deliveries.insertPackage(new JdbcGraphDeliveryStore.PackageRow(sealed.versionId(), target, null, null, null,
                        manifest.publicationId(), manifest.publicationReceiptSha256(), new String(manifest.bytes(), StandardCharsets.UTF_8),
                        manifest.digest(), manifest.files().size(), manifest.totalBytes(), "synthetic", NOW));
            });
            Path serving = Files.createDirectory(temp.toRealPath().resolve(defect));
            assertCode("package_invalid", () -> installPublication(fixture, serving, target, manifest.digest(), deliveries, transaction));
            assertTrue(deliveries.findInstall(sealed.versionId(), target).isEmpty());
            assertFalse(Files.exists(serving.resolve("graph_delivery")));
        }
        var corrupt = org.mockito.Mockito.spy(deliveries);
        ArtifactRow text = full.stream().filter(row -> row.kind().equals("extracted_text")).findFirst().orElseThrow();
        org.mockito.Mockito.doReturn(new byte[(int) text.bytes()]).when(corrupt).readContent(text);
        Path serving = Files.createDirectory(temp.toRealPath().resolve("corrupt"));
        assertCode("basis_mismatch", () -> installPublication(fixture, serving, destination, sealed.packageDigest(), corrupt, transaction));
        assertTrue(deliveries.findInstall(sealed.versionId(), destination).isEmpty());
        assertCode("package_missing", () -> installPublication(fixture, serving, destination + "-wrong", sealed.packageDigest(), deliveries, transaction));
        assertEquals("installed", installPublication(fixture, serving, destination, sealed.packageDigest(), deliveries, transaction));
        Path wrongRoot = Files.createDirectory(temp.toRealPath().resolve("wrong-root"));
        assertCode("destination_root_mismatch", () -> installPublication(fixture, wrongRoot, destination, sealed.packageDigest(), deliveries, transaction));
    }

    @Test void publicationDeliveryPreservesBusyBoundsAndUnknownCommitReconciliation() throws Exception {
        var fixture = composeFilteredPublication();
        var service = publicationSealer(fixture, transaction);
        var request = publicationRequest(fixture, destination);
        try (var held = files.open()) { assertCode("import_busy", () -> service.sealPublication(request, LIMITS)); }
        assertCode("package_too_large", () -> service.sealPublication(request, new GraphDeliveryLimits(2, 268435456, 1073741824)));
        assertCode("outbox_full", () -> service.sealPublication(request, new GraphDeliveryLimits(1003, 268435456, 1)));
        var unknown = new org.springframework.transaction.support.TransactionOperations() {
            @Override public <T> T execute(org.springframework.transaction.support.TransactionCallback<T> action) {
                transaction.execute(action);
                throw new org.springframework.transaction.TransactionSystemException("synthetic lost commit response");
            }
        };
        assertThrows(org.springframework.transaction.TransactionSystemException.class,
                () -> publicationSealer(fixture, unknown).sealPublication(request, LIMITS));
        var row = deliveries.findPackage(request.graphVersionId(), destination).orElseThrow();
        assertEquals("already_sealed", service.sealPublication(request, LIMITS).outcome());
        Path serving = Files.createDirectory(temp.toRealPath().resolve("unknown-serving"));
        try (var held = ArtifactFileStore.at(serving).open()) {
            assertCode("install_busy", () -> installPublication(fixture, serving, destination, row.packageDigest(), deliveries, transaction));
        }
        assertThrows(org.springframework.transaction.TransactionSystemException.class,
                () -> installPublication(fixture, serving, destination, row.packageDigest(), deliveries, unknown));
        assertTrue(deliveries.findInstall(request.graphVersionId(), destination).isPresent());
        assertEquals("already_installed", installPublication(fixture, serving, destination, row.packageDigest(), deliveries, transaction));
    }

    @Test void publicationInstallerRejectsAuthorityRoutingDriftAndLateRevocation() throws Exception {
        var fixture = composeFilteredPublication();
        var sealed = publicationSealer(fixture, transaction).sealPublication(publicationRequest(fixture, destination), LIMITS);
        Path first = temp.toRealPath().resolve("authority-first.json");
        Path second = temp.toRealPath().resolve("authority-second.json");
        byte[] leaf = Files.readAllBytes(fixture.authority());
        Files.write(first, leaf); Files.write(second, leaf);
        var routing = StrictJson.newObject().put("schemaVersion", "zoop-source-authority-set-1");
        var route = routing.putArray("authorities").addObject().put("sourceId", HandoffFixtures.SOURCE)
                .put("grantId", "operator-grant").put("revision", "rights-1").put("sources", first.toString());
        Files.write(fixture.authority(), Canonical.bytes(routing));
        var store = org.mockito.Mockito.spy(deliveries);
        ArtifactRow text = fixture.reader().closure(fixture.publication()).stream()
                .filter(row -> row.kind().equals("extracted_text")).findFirst().orElseThrow();
        AtomicBoolean changed = new AtomicBoolean();
        org.mockito.Mockito.doAnswer(call -> {
            if (changed.compareAndSet(false, true)) {
                route.put("sources", second.toString());
                Files.write(fixture.authority(), Canonical.bytes(routing));
            }
            return deliveries.readContent(text);
        }).when(store).readContent(text);
        Path serving = Files.createDirectory(temp.toRealPath().resolve("routing-drift"));
        assertCode("source_authority_unavailable", () -> installPublication(fixture, serving, destination, sealed.packageDigest(), store, transaction));
        assertTrue(changed.get());
        assertFalse(Files.exists(serving.resolve("graph_delivery")));
        assertTrue(deliveries.findInstall(sealed.versionId(), destination).isEmpty());

        Files.write(fixture.authority(), leaf);
        var late = org.mockito.Mockito.spy(deliveries);
        org.mockito.Mockito.doAnswer(call -> {
            if (Files.exists(serving.resolve("graph_delivery/destination-" + destination + ".json"))) {
                writeAuthority(fixture.authority(), false, "rights-1");
            }
            return deliveries.readContent(text);
        }).when(late).readContent(text);
        assertCode("rights_denied", () -> installPublication(fixture, serving, destination, sealed.packageDigest(), late, transaction));
        assertTrue(Files.exists(serving.resolve("graph_delivery/destination-" + destination + ".json")));
        assertTrue(deliveries.findInstall(sealed.versionId(), destination).isEmpty());
        Files.write(fixture.authority(), leaf);
        assertEquals("installed", installPublication(fixture, serving, destination, sealed.packageDigest(), deliveries, transaction));
    }

    @Test void databaseRequiresExactlyOneNativeOrPublicationPinFamily() throws Exception {
        var fixture = composeFilteredPublication();
        var sealed = publicationSealer(fixture, transaction).sealPublication(publicationRequest(fixture, destination), LIMITS);
        for (String pins : List.of(
                "'invented-native', null, null, publication_id, publication_receipt_sha256",
                "null, null, null, publication_id, null",
                "null, null, null, null, null",
                "'native', repeat('a',64), repeat('b',64), publication_id, publication_receipt_sha256")) {
            assertThrows(DataAccessException.class, () -> jdbc.update("""
                    INSERT INTO graph_delivery_packages(version_id,destination_id,handoff_id,manifest_digest,bundle_digest,
                        publication_id,publication_receipt_sha256,manifest,package_digest,file_count,total_bytes,sealed_by,sealed_at)
                    SELECT version_id, destination_id || '-invalid', %s, manifest,package_digest,file_count,total_bytes,sealed_by,sealed_at
                    FROM graph_delivery_packages WHERE version_id=? AND destination_id=?
                    """.formatted(pins), sealed.versionId(), destination));
        }
        assertEquals(1, deliveries.packages(destination).size());
    }

    @Test void twentyThenOneIncomingProducesTwentyOneFlatLeavesWithinActualDeliveryBounds() throws Exception {
        Path authority = temp.toRealPath().resolve("twenty-one-authority.json");
        writeAuthority(authority, true, "rights-1");
        var originals = new ArrayList<String>();
        for (int index = 0; index < 21; index++) {
            var input = HandoffFixtures.build(HandoffFixtures.Spec.standard().withHandoffId("delivery-" + UUID.randomUUID()));
            var staged = new GraphHandoffImporter(new HandoffFixtures.FakeHandoff(input.envelopeBytes()),
                    new HandoffFixtures.FakeIngestion(), new IngestionExportParser(), files, registry, graph, transaction, CLOCK);
            assertTrue(staged.run(input.request()).succeeded());
            originals.add(input.versionId());
        }
        var first = compose(originals.subList(0, 20), null, authority);
        String base = first.publication().versionId();
        assertEquals(20, graph.sources(base).size());
        // Establish the synthetic SQL base pointer; the HTTP activation contract has its own test suite.
        jdbc.update("UPDATE graph_versions SET active=true WHERE id=?", base);
        try {
            var next = compose(List.of(originals.getLast()), base, authority);
            assertEquals(21, next.publication().contributions().size());
            assertEquals(21, graph.sources(next.publication().versionId()).size());
            assertEquals(base, versions.active().orElseThrow().id());
            var sealed = publicationSealer(next, transaction).sealPublication(publicationRequest(next, destination), LIMITS);
            var manifest = GraphDeliveryManifest.parse(deliveries.findPackage(sealed.versionId(), destination).orElseThrow()
                    .manifest().getBytes(StandardCharsets.UTF_8));
            assertEquals(45, manifest.files().size());
            assertFalse(manifest.files().stream().anyMatch(pin -> pin.artifactId().equals(first.publication().receipt().id())
                    || pin.artifactId().equals(first.publication().snapshotArtifact().id())));
            Path serving = Files.createDirectory(temp.toRealPath().resolve("twenty-one-serving"));
            assertEquals("installed", installPublication(next, serving, destination, sealed.packageDigest(), deliveries, transaction));
            assertEquals(base, versions.active().orElseThrow().id());
            assertFalse(versions.everActivated(next.publication().versionId()));
        } finally {
            jdbc.update("UPDATE graph_versions SET active=false WHERE id=?", base);
        }
    }
    private static void assertCode(String expected, Runnable action) { assertEquals(expected, assertThrows(GraphDeliveryException.class, action::run).code()); }
}
