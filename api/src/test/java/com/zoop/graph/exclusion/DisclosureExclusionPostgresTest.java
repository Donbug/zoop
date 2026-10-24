package com.zoop.graph.exclusion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.Statement;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import javax.sql.DataSource;

import com.zoop.ZoopApplication;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.StrictJson;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.JdbcDisclosureExclusionReader;
import com.zoop.graph.version.JdbcGraphVersionRepository;
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
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.node.ObjectNode;

/**
 * The exclusion store, its read and the operator command against the disposable company test database: real migration, constraints,
 * append-only triggers and the publication lock. Imported versions and their receipts are synthetic rows and files.
 */
@Tag("graph-postgres")
class DisclosureExclusionPostgresTest {
    private static final String HANDOFF_1 = "exclusion-test-handoff-1";
    private static final String HANDOFF_2 = "exclusion-test-handoff-2";
    private static ConfigurableApplicationContext context;
    private static JdbcTemplate jdbc;
    private static DocumentRegistryRepository registry;
    private static JdbcDisclosureExclusionReader reader;

    @TempDir
    Path temp;
    private ArtifactFileStore store;
    private DisclosureExclusionService service;
    private final ExclusionRequestParser parser = new ExclusionRequestParser();
    private final String v1 = DisclosureExclusionService.versionId(HANDOFF_1);
    private final String v2 = DisclosureExclusionService.versionId(HANDOFF_2);

    @BeforeAll
    static void start() {
        String url = System.getenv("ZOOP_COMPANY_TEST_DB_URL");
        if (url == null || !url.matches("jdbc:postgresql://127\\.0\\.0\\.1:[0-9]+/zoop_company_test_19")) {
            throw new IllegalStateException("Set ZOOP_COMPANY_TEST_DB_URL to the dedicated localhost zoop_company_test_19 database");
        }
        context = new SpringApplicationBuilder(ZoopApplication.class).web(WebApplicationType.NONE)
                .run("--spring.datasource.url=" + url, "--spring.datasource.username=company_test",
                        "--spring.datasource.password=" + System.getenv().getOrDefault("ZOOP_COMPANY_TEST_DB_PASSWORD", ""),
                        "--spring.jpa.hibernate.ddl-auto=validate", "--zoop.ai.client.enabled=false",
                        "--ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
                        "--ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA");
        jdbc = context.getBean(JdbcTemplate.class);
        registry = context.getBean(DocumentRegistryRepository.class);
        reader = new JdbcDisclosureExclusionReader(context.getBean(NamedParameterJdbcTemplate.class));
    }

    @AfterAll
    static void stop() {
        if (jdbc != null) clean();
        if (context != null) context.close();
    }

    /** Versions go with their exclusion targets (cascade); the change log is history and stays. */
    private static void clean() {
        jdbc.update("DELETE FROM graph_versions WHERE source_label = 'exclusion-test'");
        for (String handoffId : List.of(HANDOFF_1, HANDOFF_2)) {
            String versionId = DisclosureExclusionService.versionId(handoffId);
            jdbc.update("DELETE FROM artifacts WHERE id IN (?, ?)", "artifact-exclusion-test-" + versionId,
                    "artifact-receipt-" + versionId);
        }
    }

    @BeforeEach
    void setUp() throws Exception {
        clean();
        store = ArtifactFileStore.at(Files.createDirectory(temp.toRealPath().resolve("artifacts")));
        service = new DisclosureExclusionService(new JdbcDisclosureExclusionRepository(context.getBean(NamedParameterJdbcTemplate.class)),
                registry, store, new TransactionTemplate(context.getBean(PlatformTransactionManager.class)));
        stageVersion(HANDOFF_1);
        stageVersion(HANDOFF_2);
    }

    @AfterEach
    void tearDown() {
        clean();
    }

    /** An imported version as the importer leaves it: the version row and its registered, verified receipt file. */
    private void stageVersion(String handoffId) throws Exception {
        String versionId = DisclosureExclusionService.versionId(handoffId);
        ObjectNode receipt = StrictJson.newObject();
        receipt.put("schemaVersion", "zoop-graph-handoff-import-receipt-1");
        receipt.put("handoffId", handoffId);
        receipt.put("manifestDigest", ExposureReports.DIGEST_M);
        receipt.put("bundleDigest", ExposureReports.DIGEST_B);
        receipt.put("contentDigest", ExposureReports.DIGEST_C);
        byte[] bytes = StrictJson.write(receipt);
        ArtifactFileStore.StoredFile file;
        try (ArtifactFileStore.Session session = store.open()) {
            file = session.put("verification_receipt", versionId + ".json", bytes);
        }
        registry.insertArtifactIfAbsent(new ArtifactRow("artifact-receipt-" + versionId, "verification_receipt", file.uri(),
                file.sha256(), file.bytes(), "application/json", Instant.now()));
        jdbc.update("""
                INSERT INTO artifacts (id, kind, storage_uri, sha256, bytes, media_type, created_at)
                VALUES (?, 'graph_snapshot', ?, ?, 1, 'application/json', now())
                """, "artifact-exclusion-test-" + versionId, "artifact:exclusion-test-" + versionId, "0".repeat(64));
        jdbc.update("""
                INSERT INTO graph_versions (id, sequence, kind, created_at, created_by, source_label, issue_count,
                    relation_count, article_count, snapshot_artifact_id, review_revision)
                VALUES (?, (SELECT COALESCE(MAX(sequence), 0) + 1 FROM graph_versions), 'snapshot', now(), 'operator:test',
                    'exclusion-test', 1, 1, 1, ?, 0)
                """, versionId, "artifact-exclusion-test-" + versionId);
    }

    private ExclusionResult run(byte[] request) {
        return service.run(parser.parse(request));
    }

    private long revision() {
        return jdbc.queryForObject("SELECT COALESCE(MAX(revision), 0) FROM disclosure_exclusion_changes", Long.class);
    }

    @Test
    void aReportExcludesItsIdsInTheImportedVersionOnlyAndTheSameReportAgainChangesNothing() {
        long before = revision();
        ObjectNode report = ExposureReports.report(
                ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of("edge-a"), true),
                ExposureReports.handoff(HANDOFF_2, List.of(), List.of(), false));

        ExclusionResult result = run(ExposureReports.exclude(report));

        assertTrue(result.succeeded(), () -> String.valueOf(result.failure()));
        assertEquals(ExclusionResult.APPLIED, result.outcome());
        assertEquals(before + 1, result.revision());
        DisclosureExclusions first = reader.current(v1);
        assertEquals(result.revision(), first.revision());
        assertEquals(Set.of("issue-a"), first.issueIds());
        assertEquals(Set.of("edge-a"), first.relationIds());
        assertEquals(Set.of(ExposureReports.EVIDENCE), first.evidenceIds());
        // Per version: the same ids in another version (a corrected handoff may reuse them) are untouched.
        DisclosureExclusions other = reader.current(v2);
        assertEquals(Set.of(), other.issueIds());
        assertEquals(result.revision(), other.revision(), "the revision is app-wide");
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM disclosure_exclusion_targets WHERE graph_version_id = ? "
                + "AND target_kind = 'article' AND article_version = ?", Integer.class, v1, ExposureReports.ARTICLE_VERSION),
                "articles are recorded for the readers outside the graph");
        assertEquals(Map.of("article", 1, "evidence", 1, "issue", 1, "relation", 1), result.versions().get(0).changed());

        ExclusionResult again = run(ExposureReports.exclude(report.deepCopy()));
        assertEquals(ExclusionResult.UNCHANGED, again.outcome());
        assertEquals(result.revision(), revision(), "no second change for targets already excluded");
        assertEquals(Map.of("article", 1, "evidence", 1, "issue", 1, "relation", 1), again.versions().get(0).unchanged());
    }

    @Test
    void aSmallerOrEmptyReportNeverLiftsAndOnlyAnExplicitLiftDoes() {
        run(ExposureReports.exclude(ExposureReports.report(
                ExposureReports.handoff(HANDOFF_1, List.of("issue-a", "issue-b"), List.of(), false))));
        long excludedAt = revision();

        for (ObjectNode smaller : List.of(
                ExposureReports.report(ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false)),
                ExposureReports.report(ExposureReports.handoff(HANDOFF_1, List.of(), List.of(), false)))) {
            assertEquals(ExclusionResult.UNCHANGED, run(ExposureReports.exclude(smaller)).outcome());
            assertEquals(Set.of("issue-a", "issue-b"), reader.current(v1).issueIds(), "rule 4: never narrowed by a report");
        }
        assertEquals(excludedAt, revision());

        ExclusionResult lifted = run(ExposureReports.lift(v1, "issue-a", "issue-never"));
        assertEquals(ExclusionResult.APPLIED, lifted.outcome());
        assertEquals(excludedAt + 1, lifted.revision());
        assertEquals(Map.of("issue", 1), lifted.versions().get(0).changed());
        assertEquals(Map.of("issue", 1), lifted.versions().get(0).unchanged(), "a target that was not excluded is reported");
        assertEquals(Set.of("issue-b"), reader.current(v1).issueIds());

        assertEquals(ExclusionResult.UNCHANGED, run(ExposureReports.lift(v1, "issue-a")).outcome(), "lifting twice is a no-op");
        // A later report may exclude a lifted target again: the latest change of a target decides.
        assertEquals(ExclusionResult.APPLIED, run(ExposureReports.exclude(ExposureReports.report(
                ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false)))).outcome());
        assertEquals(Set.of("issue-a", "issue-b"), reader.current(v1).issueIds());
    }

    @Test
    void aReportThatDoesNotMatchTheImportedReceiptOrVersionWritesNothing() {
        long before = revision();
        ObjectNode otherImport = ExposureReports.handoff(HANDOFF_2, List.of("issue-a"), List.of(), false);
        otherImport.put("contentDigest", "d".repeat(64));

        ExclusionResult mismatch = run(ExposureReports.exclude(ExposureReports.report(
                ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false), otherImport)));
        assertEquals(ExclusionFailure.RECEIPT_MISMATCH, mismatch.failure().failure(), "rule 1: content digest of another import");

        ExclusionResult unknown = run(ExposureReports.exclude(ExposureReports.report(
                ExposureReports.handoff("exclusion-test-never-imported", List.of("issue-a"), List.of(), false))));
        assertEquals(ExclusionFailure.VERSION_UNKNOWN, unknown.failure().failure());
        assertEquals(ExclusionFailure.VERSION_UNKNOWN, run(ExposureReports.lift("gv-none", "issue-a")).failure().failure());

        assertEquals(before, revision(), "the whole report is refused: nothing of the matching handoff is written either");
        assertEquals(Set.of(), reader.current(v1).issueIds());
    }

    @Test
    void theHistoryIsAppendOnlyAndAVersionTakesItsTargetsWithIt() {
        ExclusionResult result = run(ExposureReports.exclude(ExposureReports.report(
                ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false))));
        long revision = result.revision();

        assertThrows(DataAccessException.class, () -> jdbc.update(
                "UPDATE disclosure_exclusion_changes SET reason = 'x' WHERE revision = ?", revision));
        assertThrows(DataAccessException.class, () -> jdbc.update(
                "DELETE FROM disclosure_exclusion_changes WHERE revision = ?", revision));
        assertThrows(DataAccessException.class, () -> jdbc.update(
                "UPDATE disclosure_exclusion_targets SET target_id = 'issue-z' WHERE revision = ?", revision));
        assertThrows(DataAccessException.class, () -> jdbc.update(
                "DELETE FROM disclosure_exclusion_targets WHERE revision = ?", revision));

        jdbc.update("DELETE FROM graph_versions WHERE id = ?", v1);
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM disclosure_exclusion_targets WHERE graph_version_id = ?",
                Integer.class, v1));
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM disclosure_exclusion_changes WHERE revision = ?",
                Integer.class, revision), "the change itself is history");
    }

    @Test
    void aChangeWaitsForThePublicationLockWhileTheReadNeverDoes() throws Exception {
        ExecutorService pool = Executors.newSingleThreadExecutor();
        try (Connection other = context.getBean(DataSource.class).getConnection(); Statement statement = other.createStatement()) {
            // Held as a rule switch, a review decision or an activation would hold it.
            statement.execute("SELECT pg_advisory_lock(" + JdbcGraphVersionRepository.PUBLICATION_LOCK + ")");
            Future<ExclusionResult> running = pool.submit(() -> run(ExposureReports.exclude(ExposureReports.report(
                    ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false)))));
            Thread.sleep(1000);
            assertFalse(running.isDone(), "the change waits for the lock");
            assertEquals(Set.of(), reader.current(v1).issueIds(), "the read does not wait and sees the committed state");
            statement.execute("SELECT pg_advisory_unlock(" + JdbcGraphVersionRepository.PUBLICATION_LOCK + ")");
            assertEquals(ExclusionResult.APPLIED, running.get(30, TimeUnit.SECONDS).outcome());
            assertEquals(Set.of("issue-a"), reader.current(v1).issueIds());
        } finally {
            pool.shutdownNow();
        }
    }
}
