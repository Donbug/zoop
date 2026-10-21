package com.zoop.graph.importer;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.ZoopApplication;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.company.catalog.CompanyCatalogImportService;
import com.zoop.document.importer.IngestionExportParser;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import com.zoop.graph.importer.HandoffFixtures.Built;
import com.zoop.graph.importer.HandoffFixtures.FakeHandoff;
import com.zoop.graph.importer.HandoffFixtures.FakeIngestion;
import com.zoop.graph.read.GraphQueryService;
import com.zoop.graph.snapshot.ArtifactGraphSnapshotStore;
import com.zoop.graph.snapshot.FixtureGraphVersionSeeder;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionSelector;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * The graph handoff import against the disposable company test database, with the real SQL, constraints and rollback, next to
 * the synthetic fixture versions (so there is a real active pointer and real activation history to leave untouched). The two
 * installed CLIs are stand-ins; the real ones are covered by {@code api/scripts/graph_handoff_import_smoke.py}.
 */
@Tag("graph-postgres")
class GraphHandoffImportPostgresIntegrationTest {
    private static ConfigurableApplicationContext context;
    private static JdbcTemplate jdbc;
    private static DocumentRegistryRepository registry;
    private static JdbcGraphHandoffRepository graph;
    private static TransactionTemplate transaction;
    private static FixtureGraphVersionSeeder seeder;

    @TempDir
    Path temp;
    private Path root;
    private ArtifactFileStore store;
    private FakeIngestion ingestion;
    private FakeHandoff handoff;
    private Built built;
    private GraphHandoffImporter importer;

    @BeforeAll
    static void start() {
        String url = System.getenv("ZOOP_COMPANY_TEST_DB_URL");
        if (url == null || !url.matches("jdbc:postgresql://127\\.0\\.0\\.1:[0-9]+/zoop_company_test_19")) {
            throw new IllegalStateException("Set ZOOP_COMPANY_TEST_DB_URL to the dedicated localhost zoop_company_test_19 database");
        }
        String password = System.getenv().getOrDefault("ZOOP_COMPANY_TEST_DB_PASSWORD", "");
        context = new SpringApplicationBuilder(ZoopApplication.class)
                .web(WebApplicationType.NONE)
                .run("--spring.datasource.url=" + url,
                        "--spring.datasource.username=company_test", "--spring.datasource.password=" + password,
                        "--spring.jpa.hibernate.ddl-auto=validate", "--zoop.ai.client.enabled=false",
                        "--zoop.graph.snapshot.source=fixture",
                        "--ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
                        "--ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA");
        jdbc = context.getBean(JdbcTemplate.class);
        registry = context.getBean(DocumentRegistryRepository.class);
        graph = context.getBean(JdbcGraphHandoffRepository.class);
        transaction = new TransactionTemplate(context.getBean(PlatformTransactionManager.class));
        seeder = context.getBean(FixtureGraphVersionSeeder.class);
    }

    @AfterAll
    static void stop() {
        if (jdbc != null) clean();
        if (context != null) context.close();
    }

    /** Removes everything this test creates, children first; the fixture versions are re-seeded by every test. */
    private static void clean() {
        jdbc.update("DELETE FROM graph_activations");
        jdbc.update("DELETE FROM graph_versions");
        jdbc.update("DELETE FROM evidence WHERE article_id = ?", HandoffFixtures.ARTICLE_ID);
        jdbc.update("DELETE FROM article_versions WHERE article_id = ?", HandoffFixtures.ARTICLE_ID);
        jdbc.update("DELETE FROM articles WHERE id = ?", HandoffFixtures.ARTICLE_ID);
        jdbc.update("DELETE FROM artifacts WHERE id = ? OR id = 'exact-pg-test' OR id LIKE 'artifact-gv-%' OR id LIKE 'artifact-receipt-gv-%'",
                "text-" + HandoffFixtures.ARTICLE_VERSION);
        jdbc.update("DELETE FROM artifacts WHERE kind = 'graph_snapshot' AND id LIKE 'artifact-fixture-%'");
        jdbc.update("DELETE FROM companies WHERE id LIKE 'SYNTH:%'");
        jdbc.update("DELETE FROM companies WHERE id = ?", HandoffFixtures.ISSUE);
    }

    @BeforeEach
    void setUp() throws Exception {
        clean();
        seeder.run(null);
        jdbc.update("INSERT INTO companies (id, name, name_key, search_text) VALUES (?, ?, '', '')",
                HandoffFixtures.COMPANY_A, "합성기업");
        jdbc.update("INSERT INTO companies (id, name, name_key, search_text, brand_color) VALUES (?, ?, '', '', '#112233')",
                HandoffFixtures.COMPANY_B, "합성부품");
        root = Files.createDirectory(temp.toRealPath().resolve("artifacts"));
        store = ArtifactFileStore.at(root);
        seedArticle();
        ingestion = new FakeIngestion();
        built = HandoffFixtures.build();
        handoff = new FakeHandoff(built.envelopeBytes());
        importer = newImporter();
    }

    @AfterEach
    void tearDown() {
        clean();
    }

    private GraphHandoffImporter newImporter() {
        return new GraphHandoffImporter(handoff, ingestion, new IngestionExportParser(), store, registry, graph, transaction,
                context.getBean(Clock.class));
    }

    /** What the document import would have registered: article, text artifact and file, immutable version. */
    private void seedArticle() throws IOException {
        byte[] utf8 = HandoffFixtures.TEXT.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        String artifactId = "text-" + HandoffFixtures.ARTICLE_VERSION;
        try (ArtifactFileStore.Session session = store.open()) {
            ArtifactFileStore.StoredFile file = session.put("extracted_text", artifactId + ".txt", utf8);
            transaction.executeWithoutResult(status -> {
                registry.insertArticleIfAbsent(HandoffFixtures.ARTICLE_ID, "news", HandoffFixtures.SOURCE,
                        Instant.parse("2026-10-14T01:00:00Z"));
                registry.insertArtifactIfAbsent(new ArtifactRow(artifactId, "extracted_text", file.uri(), file.sha256(),
                        file.bytes(), "text/plain; charset=utf-8", Instant.parse("2026-10-14T01:00:00Z")));
                registry.insertVersionIfAbsent(new VersionRow(HandoffFixtures.ARTICLE_ID, HandoffFixtures.ARTICLE_VERSION,
                        "합성 제목", null, "https://example.invalid/a", Instant.parse("2026-10-08T00:00:00Z"), null, "datetime",
                        null, artifactId, Instant.parse("2026-10-14T01:02:03.456789Z")));
            });
        }
    }

    private String activeVersion() {
        return jdbc.queryForObject("SELECT id FROM graph_versions WHERE active", String.class);
    }

    private String activationFingerprint() {
        return jdbc.queryForObject("SELECT coalesce(md5(string_agg(a::text, '|' ORDER BY a.id)), '') FROM graph_activations a",
                String.class);
    }

    private int count(String sql, Object... arguments) {
        return jdbc.queryForObject(sql, Integer.class, arguments);
    }

    private long files() throws IOException {
        try (var walk = Files.walk(root)) {
            return walk.filter(Files::isRegularFile).filter(path -> !path.getFileName().toString().startsWith(".")).count();
        }
    }

    @Test
    void stagesAnInactiveVersionAndLeavesTheActivePointerAndItsHistoryUntouched() throws Exception {
        String active = activeVersion();
        String history = activationFingerprint();
        int activations = count("SELECT count(*) FROM graph_activations");
        assertEquals(2, count("SELECT count(*) FROM graph_versions"));

        GraphHandoffResult result = importer.run(built.request());

        assertTrue(result.succeeded(), () -> String.valueOf(result.failure() == null ? null : result.failure().failure()));
        String versionId = built.versionId();
        // The pointer, the history and the other versions are exactly what they were.
        assertEquals(active, activeVersion());
        assertEquals(history, activationFingerprint());
        assertEquals(activations, count("SELECT count(*) FROM graph_activations"));
        assertEquals(0, count("SELECT count(*) FROM graph_activations WHERE version_id = ?", versionId));
        assertEquals(1, count("SELECT count(*) FROM graph_versions WHERE active"));
        // The new row: a snapshot version, inactive, review revision 0, never published, created by the operator request.
        Map<String, Object> row = jdbc.queryForMap("""
                SELECT kind, active, review_revision, published_at IS NULL AS unpublished, created_by, policy_version,
                       issue_count, relation_count, article_count, snapshot_artifact_id, rule_revision, candidate_count
                FROM graph_versions WHERE id = ?""", versionId);
        assertEquals("snapshot", row.get("kind"));
        assertEquals(Boolean.FALSE, row.get("active"));
        assertEquals(0L, ((Number) row.get("review_revision")).longValue());
        assertEquals(Boolean.TRUE, row.get("unpublished"));
        assertEquals("operator:operator-a", row.get("created_by"));
        assertEquals(HandoffBundleVerifier.POLICY, row.get("policy_version"));
        assertEquals(1L, ((Number) row.get("issue_count")).longValue());
        assertEquals(2L, ((Number) row.get("relation_count")).longValue());
        assertEquals(1L, ((Number) row.get("article_count")).longValue());
        assertEquals("artifact-" + versionId, row.get("snapshot_artifact_id"));
        assertEquals(null, row.get("rule_revision"));

        // Both artifacts are registered at their stored files; the evidence points at the retained receipt.
        assertEquals(1, count("SELECT count(*) FROM artifacts WHERE id = ? AND kind = 'graph_snapshot'", "artifact-" + versionId));
        assertEquals(1, count("SELECT count(*) FROM artifacts WHERE id = ? AND kind = 'verification_receipt'",
                "artifact-receipt-" + versionId));
        assertEquals(3, count("SELECT count(*) FROM evidence WHERE verification_artifact_id = ? AND quote_verified",
                "artifact-receipt-" + versionId));
        assertEquals(3, count("SELECT count(*) FROM evidence WHERE offset_unit = 'unicode_code_point' AND input_kind = 'body'"
                + " AND char_length(quote) = end_offset - start_offset AND article_id = ?", HandoffFixtures.ARTICLE_ID));
        int eventStart = HandoffFixtures.TEXT.codePointCount(0, HandoffFixtures.TEXT.indexOf(HandoffFixtures.EVENT));
        assertNotEquals(HandoffFixtures.TEXT.indexOf(HandoffFixtures.EVENT), eventStart);
        assertEquals(HandoffFixtures.EVENT, jdbc.queryForObject(
                "SELECT quote FROM evidence WHERE start_offset = ? AND article_id = ?", String.class, eventStart,
                HandoffFixtures.ARTICLE_ID));

        // The public API cannot reach it: an explicit version id is unavailable, the default and asOf reads stay on the fixtures.
        GraphVersionSelector selector = context.getBean(GraphVersionSelector.class);
        CustomException unavailable = assertThrows(CustomException.class, () -> selector.select(null, versionId, null));
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, unavailable.getErrorCode());
        assertEquals(active, selector.select(null, null, null).version().id());
        assertEquals(active, context.getBean(GraphQueryService.class).getGraph(null, null, null, null, null, null, null, null, "it-1")
                .metadata().graphVersion());
        assertNotEquals(versionId, selector.select(null, null, Instant.now()).version().id());
        // A staged version blocks the fixture seeder (documented), and the seeder does not touch it.
        assertThrows(IllegalStateException.class, () -> seeder.run(null));
        assertEquals(active, activeVersion());

        // The existing artifact read port reads the snapshot the registry points at, verified.
        JdbcGraphVersionRepository versions = context.getBean(JdbcGraphVersionRepository.class);
        GraphVersionRecord record = versions.find(versionId).orElseThrow();
        assertFalse(record.active());
        ArtifactGraphSnapshotStore artifactStore = new ArtifactGraphSnapshotStore(ArtifactFileStore.at(root), registry,
                new com.zoop.graph.snapshot.FixtureGraphSnapshotStore(getClass().getClassLoader()));
        PublicGraphSnapshot snapshot = artifactStore.load(record);
        assertEquals(HandoffFixtures.HANDOFF_ID, snapshot.sourceBundleId());
        assertEquals(3, snapshot.evidence().size());
        // The same store still serves the active fixture version registered earlier (a classpath location): reads stay unchanged.
        assertEquals(active, artifactStore.load(versions.find(active).orElseThrow()).versionId());
    }

    @Test
    void anIdenticalImportIsUnchangedAndAnotherHandoffUnderTheSameIdConflictsWithoutWriting() throws Exception {
        importer.run(built.request());
        String history = activationFingerprint();

        GraphHandoffResult again = importer.run(built.request());

        assertTrue(again.succeeded());
        assertEquals(GraphHandoffResult.Outcome.UNCHANGED, again.staged().outcome());
        assertEquals(1, count("SELECT count(*) FROM graph_versions WHERE id LIKE 'gv-%'"));
        assertEquals(3, count("SELECT count(*) FROM evidence WHERE article_id = ?", HandoffFixtures.ARTICLE_ID));

        Built other = HandoffFixtures.build(HandoffFixtures.Spec.standard().withCanonicalPin("9".repeat(64)));
        handoff.envelope = other.envelopeBytes();
        long filesBefore = files();

        GraphHandoffResult conflict = importer.run(other.request());

        assertFalse(conflict.succeeded());
        assertEquals(GraphHandoffFailure.VERSION_CONFLICT, conflict.failure().failure());
        assertEquals(1, count("SELECT count(*) FROM graph_versions WHERE id LIKE 'gv-%'"));
        assertEquals(filesBefore, files());
        assertEquals(history, activationFingerprint());
    }

    @Test
    void aPrivatePathCompanyIsCheckedInTheCatalogueUnderTheLockAndNeverBecomesAPublicNode() throws Exception {
        Built twoHop = HandoffFixtures.build(HandoffFixtures.Spec.standard().withShape(HandoffFixtures.Shape.TWO_HOP_PRIVATE));
        handoff.envelope = twoHop.envelopeBytes();
        long filesBefore = files();
        String history = activationFingerprint();

        // Absent from the catalogue, then named differently: the union check fails and nothing at all is written.
        for (String name : new String[] {null, "다른 중간"}) {
            if (name != null) {
                jdbc.update("INSERT INTO companies (id, name, name_key, search_text) VALUES (?, ?, '', '')",
                        HandoffFixtures.COMPANY_M, name);
            }
            GraphHandoffResult refused = importer.run(twoHop.request());
            assertFalse(refused.succeeded(), String.valueOf(name));
            assertEquals(GraphHandoffFailure.COMPANY_MISMATCH, refused.failure().failure(), String.valueOf(name));
            assertEquals(0, count("SELECT count(*) FROM graph_versions WHERE id LIKE 'gv-%'"));
            assertEquals(0, count("SELECT count(*) FROM evidence WHERE article_id = ?", HandoffFixtures.ARTICLE_ID));
            assertEquals(0, count("SELECT count(*) FROM artifacts WHERE id LIKE 'artifact-%gv-%'"));
            assertEquals(filesBefore, files());
        }
        jdbc.update("UPDATE companies SET name = ? WHERE id = ?", "합성중간", HandoffFixtures.COMPANY_M);

        GraphHandoffResult staged = importer.run(twoHop.request());

        assertTrue(staged.succeeded(), () -> String.valueOf(staged.failure() == null ? null : staged.failure().failure()));
        assertEquals(2, staged.staged().companies(), "the path company is catalogue-checked but not a public company");
        assertEquals(4, count("SELECT count(*) FROM evidence WHERE verification_artifact_id = ? AND quote_verified",
                "artifact-receipt-" + twoHop.versionId()));
        assertEquals(history, activationFingerprint());
        String snapshot = new String(Files.readAllBytes(root.resolve("graph_snapshot").resolve(twoHop.versionId() + ".json")),
                java.nio.charset.StandardCharsets.UTF_8);
        assertFalse(snapshot.contains(HandoffFixtures.COMPANY_M));
        assertFalse(snapshot.contains("structuralPath"));
        String receipt = new String(Files.readAllBytes(root.resolve("verification_receipt").resolve(twoHop.versionId() + ".json")),
                java.nio.charset.StandardCharsets.UTF_8);
        assertTrue(receipt.contains("structural_path_closed_over_involves_basis_and_catalog"));
    }

    @Test
    void anEvidenceCollisionRollsEverythingBackInPostgresAndRemovesTheFilesItCreated() throws Exception {
        String last = built.evidenceIds().get(built.evidenceIds().size() - 1);
        jdbc.update("""
                INSERT INTO evidence (id, article_id, article_version, text_artifact_id, quote, start_offset, end_offset,
                    offset_unit, input_kind, raw_locator_ids, created_at)
                VALUES (?, ?, ?, ?, '다른 인용', 0, 5, 'unicode_code_point', 'body', '["loc-1"]'::jsonb, now())""",
                last, HandoffFixtures.ARTICLE_ID, HandoffFixtures.ARTICLE_VERSION, "text-" + HandoffFixtures.ARTICLE_VERSION);
        String active = activeVersion();
        long filesBefore = files();

        GraphHandoffResult result = importer.run(built.request());

        assertFalse(result.succeeded());
        assertEquals(GraphHandoffFailure.EVIDENCE_COLLISION, result.failure().failure());
        // The first spans had been inserted and the artifacts registered inside the transaction; none of it survived.
        assertEquals(1, count("SELECT count(*) FROM evidence WHERE article_id = ?", HandoffFixtures.ARTICLE_ID));
        assertEquals(0, count("SELECT count(*) FROM graph_versions WHERE id LIKE 'gv-%'"));
        assertEquals(0, count("SELECT count(*) FROM artifacts WHERE id LIKE 'artifact-gv-%' OR id LIKE 'artifact-receipt-gv-%'"));
        assertEquals(filesBefore, files());
        assertFalse(Files.exists(root.resolve("graph_snapshot").resolve(built.versionId() + ".json")));
        assertEquals(active, activeVersion());
        assertEquals("다른 인용", jdbc.queryForObject("SELECT quote FROM evidence WHERE id = ?", String.class, last));
    }

    @Test
    void rightsRevokedBeforeTheCommitRollBackInPostgres() throws Exception {
        String history = activationFingerprint();
        long filesBefore = files();
        ingestion.refuseFrom(2, "source_unauthorized");

        GraphHandoffResult result = importer.run(built.request());

        assertFalse(result.succeeded());
        assertEquals(GraphHandoffFailure.INGESTION_EXPORT_FAILED, result.failure().failure());
        assertEquals(0, count("SELECT count(*) FROM evidence WHERE article_id = ?", HandoffFixtures.ARTICLE_ID));
        assertEquals(0, count("SELECT count(*) FROM graph_versions WHERE id LIKE 'gv-%'"));
        assertEquals(0, count("SELECT count(*) FROM artifacts WHERE id LIKE 'artifact-gv-%' OR id LIKE 'artifact-receipt-gv-%'"));
        assertEquals(filesBefore, files());
        assertEquals(history, activationFingerprint());
    }

    @Test
    void aRefusedRightNeverReachesTheDatabase() throws Exception {
        ingestion.refuseAlways("store_not_allowed");

        GraphHandoffResult result = importer.run(built.request());

        assertEquals(GraphHandoffFailure.INGESTION_EXPORT_FAILED, result.failure().failure());
        assertEquals("store_not_allowed", result.failure().cliCode());
        assertEquals(0, count("SELECT count(*) FROM graph_versions WHERE id LIKE 'gv-%'"));
        assertEquals(List.of(), jdbc.queryForList("SELECT id FROM evidence WHERE article_id = ?", String.class,
                HandoffFixtures.ARTICLE_ID));
    }

    // ------------------------------------------------------------------------------------------------ review regressions --

    @Test
    void aConcurrentWithdrawalWaitsForTheImportsArticleLockAndIsAppliedOnlyAfterItsCommit() throws Exception {
        java.util.concurrent.ExecutorService pool = java.util.concurrent.Executors.newSingleThreadExecutor();
        try {
            java.util.concurrent.atomic.AtomicReference<java.util.concurrent.Future<Integer>> withdrawal =
                    new java.util.concurrent.atomic.AtomicReference<>();
            java.util.concurrent.atomic.AtomicBoolean finishedWhileLocked = new java.util.concurrent.atomic.AtomicBoolean();
            // Call 2 is the recheck, which runs inside the import's transaction after verifyApp took the article row FOR UPDATE:
            // another session now tries to make the article private, and has to wait for that row.
            ingestion.before(2, () -> {
                withdrawal.set(pool.submit(() -> jdbc.update("UPDATE articles SET access_status = 'private' WHERE id = ?",
                        HandoffFixtures.ARTICLE_ID)));
                try {
                    Thread.sleep(1500);
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                }
                finishedWhileLocked.set(withdrawal.get().isDone());
            });

            GraphHandoffResult result = importer.run(built.request());

            assertTrue(result.succeeded(), () -> String.valueOf(result.failure() == null ? null : result.failure().failure()));
            assertFalse(finishedWhileLocked.get(), "the withdrawal ran while the import still held the article row");
            assertEquals(1, withdrawal.get().get(30, java.util.concurrent.TimeUnit.SECONDS));
            // Serialized: the import committed first, the withdrawal applies afterwards (a later import would refuse the article).
            assertEquals("private", jdbc.queryForObject("SELECT access_status FROM articles WHERE id = ?", String.class,
                    HandoffFixtures.ARTICLE_ID));
            assertEquals(1, count("SELECT count(*) FROM graph_versions WHERE id LIKE 'gv-%'"));
            // A LATER import of another handoff now finds the article private and refuses it.
            Built later = HandoffFixtures.build(HandoffFixtures.Spec.standard().withHandoffId("handoff-unit-later"));
            handoff.envelope = later.envelopeBytes();
            GraphHandoffResult refused = importer.run(later.request());
            assertFalse(refused.succeeded());
            assertEquals(GraphHandoffFailure.ARTICLE_MISMATCH, refused.failure().failure());
        } finally {
            pool.shutdownNow();
        }
    }

    @Test
    void anArticleAlreadyPrivateOrDeletedIsRefusedBeforeAnythingIsWritten() throws Exception {
        for (String access : List.of("private", "deleted")) {
            jdbc.update("UPDATE articles SET access_status = ? WHERE id = ?", access, HandoffFixtures.ARTICLE_ID);
            long filesBefore = files();

            GraphHandoffResult result = importer.run(built.request());

            assertFalse(result.succeeded(), access);
            assertEquals(GraphHandoffFailure.ARTICLE_MISMATCH, result.failure().failure(), access);
            assertEquals(0, count("SELECT count(*) FROM graph_versions WHERE id LIKE 'gv-%'"), access);
            assertEquals(0, count("SELECT count(*) FROM evidence WHERE article_id = ?", HandoffFixtures.ARTICLE_ID), access);
            assertEquals(filesBefore, files(), access);
        }
    }

    @Test
    void anExistingEvidenceRowWithoutAGraphReceiptVerificationIsACollisionAndIsNeverRepaired() throws Exception {
        String quote = HandoffFixtures.EVENT;
        int start = HandoffFixtures.TEXT.codePointCount(0, HandoffFixtures.TEXT.indexOf(quote));
        int end = start + quote.codePointCount(0, quote.length());
        String id = HandoffBundleVerifier.appEvidenceId(HandoffFixtures.ARTICLE_ID, HandoffFixtures.ARTICLE_VERSION, start, end);
        // {quote_verified, verification artifact kind or null}: unverified, explicitly not verified, verified by an S1 exact receipt.
        Object[][] variants = {{null, null}, {Boolean.FALSE, null}, {Boolean.TRUE, "exact_receipt"}};
        for (Object[] variant : variants) {
            jdbc.update("DELETE FROM evidence WHERE article_id = ?", HandoffFixtures.ARTICLE_ID);
            jdbc.update("DELETE FROM artifacts WHERE id = 'exact-pg-test'");
            if (variant[1] != null) {
                jdbc.update("""
                        INSERT INTO artifacts (id, kind, storage_uri, sha256, bytes, media_type, created_at)
                        VALUES ('exact-pg-test', 'exact_receipt', 'artifact-root:exact_receipt/exact-pg-test.json', ?, 1,
                                'application/json', now())""", "3".repeat(64));
            }
            jdbc.update("""
                    INSERT INTO evidence (id, article_id, article_version, text_artifact_id, quote, start_offset, end_offset,
                        offset_unit, input_kind, raw_locator_ids, quote_verified, verification_artifact_id, verified_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'unicode_code_point', 'body', '["loc-1"]'::jsonb, ?, ?, ?, now())""",
                    id, HandoffFixtures.ARTICLE_ID, HandoffFixtures.ARTICLE_VERSION, "text-" + HandoffFixtures.ARTICLE_VERSION,
                    quote, start, end, variant[0], variant[1] == null ? null : "exact-pg-test",
                    variant[1] == null ? null : java.time.OffsetDateTime.now());
            String before = jdbc.queryForObject(
                    "SELECT coalesce(quote_verified::text, 'null') || '|' || coalesce(verification_artifact_id, 'null') FROM evidence WHERE id = ?",
                    String.class, id);
            long filesBefore = files();

            GraphHandoffResult result = importer.run(built.request());

            assertFalse(result.succeeded(), before);
            assertEquals(GraphHandoffFailure.EVIDENCE_COLLISION, result.failure().failure(), before);
            assertEquals(1, count("SELECT count(*) FROM evidence WHERE article_id = ?", HandoffFixtures.ARTICLE_ID), before);
            assertEquals(before, jdbc.queryForObject(
                    "SELECT coalesce(quote_verified::text, 'null') || '|' || coalesce(verification_artifact_id, 'null') FROM evidence WHERE id = ?",
                    String.class, id), "the stored row must not be repaired");
            assertEquals(0, count("SELECT count(*) FROM graph_versions WHERE id LIKE 'gv-%'"), before);
            assertEquals(0, count("SELECT count(*) FROM artifacts WHERE id LIKE 'artifact-gv-%' OR id LIKE 'artifact-receipt-gv-%'"),
                    before);
            assertEquals(filesBefore, files(), before);
        }
    }

    @Test
    void aLaterHandoffReusesTheVerifiedEvidenceRowsOfAnEarlierOneWithoutRepointingThem() throws Exception {
        importer.run(built.request());
        Built second = HandoffFixtures.build(HandoffFixtures.Spec.standard().withHandoffId("handoff-unit-2"));
        handoff.envelope = second.envelopeBytes();

        GraphHandoffResult result = importer.run(second.request());

        assertTrue(result.succeeded(), () -> String.valueOf(result.failure() == null ? null : result.failure().failure()));
        assertEquals(0, result.staged().evidenceRegistered());
        assertEquals(3, result.staged().evidenceExisting());
        assertEquals(2, count("SELECT count(*) FROM graph_versions WHERE id LIKE 'gv-%'"));
        assertEquals(3, count("SELECT count(*) FROM evidence WHERE verification_artifact_id = ?", "artifact-receipt-" + built.versionId()));
    }

    // ------------------------------------------------------------------------------------------- catalog lock regressions --

    /** A catalog file for the existing writer, {@link CompanyCatalogImportService}, with one unlisted company. */
    private Path catalogFile(String companyId, String name) throws IOException {
        return Files.writeString(temp.resolve("catalog.json"),
                "{\"companies\":[{\"company_id\":\"" + companyId + "\",\"name\":\"" + name + "\",\"aliases\":[]}]}");
    }

    /** A catalog import started by another session while the import's transaction is open, and whether it finished meanwhile. */
    private record CatalogRace(AtomicReference<Future<CompanyCatalogImportService.ImportResult>> catalog,
            AtomicBoolean finishedWhileLocked) {
        CatalogRace() {
            this(new AtomicReference<>(), new AtomicBoolean());
        }
    }

    /**
     * Arms the in-transaction recheck (call 2 runs after the import read the companies and the issue ids) to start a real
     * catalog import of {@code file} in another session and to give it time to finish before the import goes on to commit.
     */
    private CatalogRace catalogImportDuringTheImport(ExecutorService pool, Path file) {
        CatalogRace race = new CatalogRace();
        ingestion.before(2, () -> {
            race.catalog().set(pool.submit(() -> context.getBean(CompanyCatalogImportService.class).importFile(file)));
            try {
                Thread.sleep(1500);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
            }
            race.finishedWhileLocked().set(race.catalog().get().isDone());
        });
        return race;
    }

    @Test
    void aConcurrentCatalogRenameWaitsForTheImportsCatalogLockAndIsAppliedOnlyAfterItsCommit() throws Exception {
        ExecutorService pool = Executors.newSingleThreadExecutor();
        try {
            CatalogRace race = catalogImportDuringTheImport(pool, catalogFile(HandoffFixtures.COMPANY_A, "개명된 합성기업"));

            GraphHandoffResult result = importer.run(built.request());

            assertTrue(result.succeeded(), () -> String.valueOf(result.failure() == null ? null : result.failure().failure()));
            assertFalse(race.finishedWhileLocked().get(),
                    "the catalog rename committed while the import still depended on the company name it had read");
            assertEquals(1, race.catalog().get().get(30, TimeUnit.SECONDS).changed());
            // Serialized: the import committed first, the rename applies afterwards (a later import of the same pins refuses it).
            assertEquals("개명된 합성기업", jdbc.queryForObject("SELECT name FROM companies WHERE id = ?", String.class,
                    HandoffFixtures.COMPANY_A));
            assertEquals(1, count("SELECT count(*) FROM graph_versions WHERE id LIKE 'gv-%'"));
            GraphHandoffResult later = importer.run(built.request());
            assertFalse(later.succeeded());
            assertEquals(GraphHandoffFailure.COMPANY_MISMATCH, later.failure().failure());
        } finally {
            pool.shutdownNow();
        }
    }

    @Test
    void aConcurrentCatalogInsertOfAnIssueIdWaitsForTheImportsCatalogLockAndIsAppliedOnlyAfterItsCommit() throws Exception {
        ExecutorService pool = Executors.newSingleThreadExecutor();
        try {
            CatalogRace race = catalogImportDuringTheImport(pool, catalogFile(HandoffFixtures.ISSUE, "충돌 회사"));

            GraphHandoffResult result = importer.run(built.request());

            assertTrue(result.succeeded(), () -> String.valueOf(result.failure() == null ? null : result.failure().failure()));
            assertFalse(race.finishedWhileLocked().get(),
                    "a catalog company took the id of a staged issue while the import still relied on that id being free");
            assertEquals(1, race.catalog().get().get(30, TimeUnit.SECONDS).changed());
            assertEquals(1, count("SELECT count(*) FROM companies WHERE id = ?", HandoffFixtures.ISSUE));
            assertEquals(1, count("SELECT count(*) FROM graph_versions WHERE id LIKE 'gv-%'"));
            // A later import of the same pins finds the id taken and refuses it.
            GraphHandoffResult later = importer.run(built.request());
            assertFalse(later.succeeded());
            assertEquals(GraphHandoffFailure.COMPANY_MISMATCH, later.failure().failure());
        } finally {
            pool.shutdownNow();
        }
    }

    @Test
    void anImportStartedWhileACatalogImportIsUncommittedWaitsForItAndThenReadsTheCommittedCatalog() throws Exception {
        ExecutorService pool = Executors.newSingleThreadExecutor();
        try {
            Path file = catalogFile(HandoffFixtures.COMPANY_A, "개명된 합성기업");
            AtomicReference<Future<GraphHandoffResult>> running = new AtomicReference<>();
            AtomicBoolean finishedWhileCatalogHeld = new AtomicBoolean();
            // The catalog import's transaction (its table lock, then its row change) stays open until this block ends.
            transaction.executeWithoutResult(status -> {
                context.getBean(CompanyCatalogImportService.class).importFile(file);
                running.set(pool.submit(() -> importer.run(built.request())));
                try {
                    Thread.sleep(1500);
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                }
                finishedWhileCatalogHeld.set(running.get().isDone());
            });

            GraphHandoffResult result = running.get().get(30, TimeUnit.SECONDS);

            assertFalse(finishedWhileCatalogHeld.get(), "the import read the catalog while another transaction was changing it");
            // The import waited, then read the committed name: the label of the bundle no longer matches, and nothing is staged.
            assertFalse(result.succeeded());
            assertEquals(GraphHandoffFailure.COMPANY_MISMATCH, result.failure().failure());
            assertEquals(0, count("SELECT count(*) FROM graph_versions WHERE id LIKE 'gv-%'"));
            assertEquals(0, count("SELECT count(*) FROM evidence WHERE article_id = ?", HandoffFixtures.ARTICLE_ID));
        } finally {
            pool.shutdownNow();
        }
    }
}
