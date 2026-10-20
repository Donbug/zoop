package com.zoop.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.zoop.ZoopApplication;
import com.zoop.admin.dashboard.repository.AdminDashboardRepository;
import com.zoop.graph.read.GraphQueryService;
import com.zoop.graph.snapshot.FixtureGraphVersionSeeder;
import com.zoop.graph.snapshot.GraphSnapshotStore;
import com.zoop.graph.version.GraphVersionConflictException;
import com.zoop.graph.version.GraphVersionSelector;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import com.zoop.graph.version.JdbcGraphVersionRepository.NewGraphVersion;
import java.time.Instant;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;

/** Graph version migration, fixture registration and version pinning against the disposable company test database. */
@Tag("graph-postgres")
class GraphVersionPostgresIntegrationTest {
    private static ConfigurableApplicationContext context;
    private static JdbcTemplate jdbc;
    private static JdbcGraphVersionRepository repository;
    private static GraphVersionSelector selector;
    private static FixtureGraphVersionSeeder seeder;
    private static AdminDashboardRepository dashboardRepository;

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
        repository = context.getBean(JdbcGraphVersionRepository.class);
        selector = context.getBean(GraphVersionSelector.class);
        seeder = context.getBean(FixtureGraphVersionSeeder.class);
        dashboardRepository = context.getBean(AdminDashboardRepository.class);
    }

    @AfterAll
    static void stop() {
        if (context != null) context.close();
    }

    @BeforeEach
    void reseed() throws Exception {
        jdbc.update("DELETE FROM graph_activations");
        jdbc.update("DELETE FROM graph_versions");
        jdbc.update("DELETE FROM artifacts WHERE kind = 'graph_snapshot' AND id LIKE 'artifact-fixture-%'");
        seeder.run(null);
    }

    @Test
    void fixturesAreRegisteredInOrderAndTheLastIsActive() {
        assertEquals(2, jdbc.queryForObject("SELECT count(*) FROM graph_versions", Integer.class));
        assertEquals("fixture-2026-10-08", jdbc.queryForObject("SELECT id FROM graph_versions WHERE active", String.class));
        assertEquals(2, jdbc.queryForObject("SELECT count(*) FROM graph_activations WHERE pointer_changed", Integer.class));
        assertEquals("fixture-2026-10-01", jdbc.queryForObject(
                "SELECT previous_version_id FROM graph_activations WHERE version_id = 'fixture-2026-10-08'", String.class));
    }

    @Test
    void seedingTwiceChangesNothing() throws Exception {
        seeder.run(null);
        assertEquals(2, jdbc.queryForObject("SELECT count(*) FROM graph_activations", Integer.class));
    }

    @Test
    void asOfSelectionUsesTheActivationHistoryAndTheSnapshotLoads() {
        var past = selector.select(null, null, Instant.parse("2026-10-05T00:00:00Z"));
        assertEquals("fixture-2026-10-01", past.version().id());
        assertEquals(3, context.getBean(GraphSnapshotStore.class).load(past.version()).issues().size());
        assertEquals("fixture-2026-10-08", selector.select(null, null, null).version().id());
    }

    @Test
    void dashboardUsesTheLastGraphActivationAtOrBeforeItsAsOfTime() {
        Instant asOf = Instant.parse("2026-10-05T00:00:00Z");

        var summary = dashboardRepository.graphSummaryAt(asOf);

        assertEquals("fixture-2026-10-01", summary.activeVersion().orElseThrow().id());
        assertEquals(Instant.parse("2026-10-01T00:00:00Z"),
                summary.activeVersion().orElseThrow().activatedAt());
    }

    @Test
    void anotherSnapshotUnderAnExistingIdIsRefusedNotOverwritten() {
        assertThrows(GraphVersionConflictException.class, () -> repository.registerSystemVersion(new NewGraphVersion(
                "fixture-2026-10-01", "fixture", "tampered", "artifact-fixture-other",
                "classpath:graph-fixtures/fixture-2026-10-01.json", "1".repeat(64), 1, 0, 0, 0),
                "tamper", Instant.parse("2026-10-16T00:00:00Z")));
    }

    @Test
    void reactivatingKeepsOnePointerAndRecordsWhetherItMoved() {
        repository.activateSystem("fixture-2026-10-08", "no-op", Instant.parse("2026-10-10T00:00:00Z"));
        repository.activateSystem("fixture-2026-10-01", "rollback", Instant.parse("2026-10-11T00:00:00Z"));
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM graph_versions WHERE active", Integer.class));
        assertEquals(Boolean.FALSE, jdbc.queryForObject(
                "SELECT pointer_changed FROM graph_activations WHERE reason = 'no-op'", Boolean.class));
        assertEquals("fixture-2026-10-01", selector.select(null, null, Instant.parse("2026-10-12T00:00:00Z")).version().id());
        assertEquals("fixture-2026-10-08", selector.select(null, null, Instant.parse("2026-10-10T12:00:00Z")).version().id());
    }

    @Test
    void changedBundledFixturesResetOnlyTheFixtureRowsAndSeedAgain() throws Exception {
        // As if an older fixture file (e.g. snapshot format 1) had been seeded under the same id. Artifact rows are
        // immutable, so the older seed is recreated from scratch instead of edited.
        jdbc.update("DELETE FROM graph_activations");
        jdbc.update("DELETE FROM graph_versions");
        jdbc.update("DELETE FROM artifacts WHERE kind = 'graph_snapshot' AND id LIKE 'artifact-fixture-%'");
        repository.registerSystemVersion(new NewGraphVersion("fixture-2026-10-01", "fixture", "older fixture",
                "artifact-fixture-older", "classpath:graph-fixtures/fixture-2026-10-01.json", "0".repeat(64), 1, 0, 0, 0),
                "older seed", Instant.parse("2026-10-01T00:00:00Z"));
        seeder.run(null);
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM artifacts WHERE id = 'artifact-fixture-older'", Integer.class));
        assertEquals(2, jdbc.queryForObject("SELECT count(*) FROM graph_versions", Integer.class));
        assertEquals(2, jdbc.queryForObject("SELECT count(*) FROM graph_activations", Integer.class));
        assertEquals("fixture-2026-10-08", jdbc.queryForObject("SELECT id FROM graph_versions WHERE active", String.class));
        assertEquals(3, context.getBean(GraphSnapshotStore.class)
                .load(selector.select(null, "fixture-2026-10-01", null).version()).issues().size());
    }

    @Test
    void fixtureSeedingRefusesADatabaseWithImportedVersions() {
        jdbc.update("""
                INSERT INTO artifacts (id, kind, storage_uri, sha256, bytes, media_type, created_at)
                VALUES ('artifact-fixture-imported', 'graph_snapshot', 'artifact:imported', ?, 1, 'application/json', now())
                """, "2".repeat(64));
        jdbc.update("""
                INSERT INTO graph_versions (id, sequence, kind, created_at, created_by, source_label, issue_count,
                    relation_count, article_count, snapshot_artifact_id, review_revision)
                VALUES ('imported-1', 99, 'snapshot', now(), 'system', 'imported', 0, 0, 0, 'artifact-fixture-imported', 0)
                """);
        assertThrows(IllegalStateException.class, () -> seeder.run(null));
        assertEquals("fixture-2026-10-08", jdbc.queryForObject("SELECT id FROM graph_versions WHERE active", String.class));
    }

    @Test
    void getGraphReadsTheActiveFixtureVersionThroughTheRealDatabase() {
        var response = context.getBean(GraphQueryService.class).getGraph(null, null, null, null, null, null, null, null, "it-1");
        assertEquals("fixture-2026-10-08", response.metadata().graphVersion());
        assertEquals(11, response.nodes().size());
        var past = context.getBean(GraphQueryService.class)
                .getGraph("all", null, null, null, null, "2026-10-05T00:00:00Z", null, null, "it-2");
        assertEquals("fixture-2026-10-01", past.metadata().graphVersion());
    }

    @Test
    void theDatabaseRejectsTwoActiveVersions() {
        assertThrows(DataAccessException.class, () -> jdbc.update("UPDATE graph_versions SET active = true"));
    }
}
