package com.zoop.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.ZoopApplication;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.dashboard.repository.AdminDashboardRepository;
import com.zoop.admin.graph.AdminGraphVersionService;
import com.zoop.admin.graph.GraphVersionActivateRequest;
import com.zoop.admin.graph.GraphVersionAdminResponse.GraphVersionOut;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.read.EventDetailService;
import com.zoop.graph.read.GraphQueryService;
import com.zoop.graph.read.dto.EventDetail;
import com.zoop.graph.snapshot.FixtureGraphVersionSeeder;
import com.zoop.graph.snapshot.GraphSnapshotStore;
import com.zoop.graph.version.GraphVersionConflictException;
import com.zoop.graph.version.GraphVersionSelector;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import com.zoop.graph.version.JdbcGraphVersionRepository.NewGraphVersion;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
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
        jdbc.update("DELETE FROM idempotency_records WHERE resource_type = 'graph_version'");
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

        assertEquals(2, summary.versionCount());
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

    @Test
    void getEventReadsTheActiveFixtureVersionThroughTheRealContext() {
        var service = context.getBean(EventDetailService.class);

        var detail = service.get("iss-fixture-hbm-equip", null, null, null, "it-event");
        assertEquals("fixture-2026-10-08", detail.metadata().graphVersion());
        assertEquals(List.of("iss-fixture-hbm-supply"),
                detail.follows().previous().stream().map(EventDetail.FollowRef::id).toList());
        assertEquals("unavailable", ((EventDetail.Unavailable) detail.summary()).status());
        // The fixture's articles have no stored article version, so the publisher is unknown rather than invented.
        assertEquals(null, detail.articles().get(0).publisher());
        assertThrows(CustomException.class, () -> service.get("iss-fixture-ai-accel", null, null,
                "2026-10-05T00:00:00Z", "it-event-past"));
    }

    @Test
    void adminActivationMovesThePointerOnceAndRecordsTheAdmin() {
        AdminPrincipal admin = admin();
        var service = context.getBean(AdminGraphVersionService.class);

        var result = service.activate("fixture-2026-10-01", new GraphVersionActivateRequest("rollback check", "fixture-2026-10-08"),
                "graph-key-1", admin, "it-activate");
        var replay = service.activate("fixture-2026-10-01", new GraphVersionActivateRequest("rollback check", "fixture-2026-10-08"),
                "graph-key-1", admin, "it-activate-replay");

        assertEquals("fixture-2026-10-08", result.previousActiveVersionId());
        assertFalse(result.idempotent());
        assertEquals(result, replay);
        assertEquals("fixture-2026-10-01", jdbc.queryForObject("SELECT id FROM graph_versions WHERE active", String.class));
        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM graph_activations
                WHERE actor_kind = 'admin' AND admin_id = ? AND admin_email_snapshot = ? AND pointer_changed
                """, Integer.class, admin.adminId(), admin.email()));
        assertEquals(1, jdbc.queryForObject("""
                SELECT count(*) FROM audit_logs WHERE action = 'graph.version.activate' AND admin_id = ?
                  AND target_id = 'fixture-2026-10-01' AND detail->>'previousVersionId' = 'fixture-2026-10-08'
                """, Integer.class, admin.adminId()));

        var list = service.list(null, null);
        assertEquals("fixture-2026-10-01", list.activeVersionId());
        assertEquals(List.of("fixture-2026-10-08", "fixture-2026-10-01"),
                list.items().stream().map(GraphVersionOut::id).toList());
        assertEquals("fixture", list.items().get(0).kind());
        assertEquals("activate", list.activations().get(0).action());
        assertEquals(admin.email(), list.activations().get(0).adminEmail());
        var page1 = service.list(null, 1);
        var page2 = service.list(page1.nextCursor(), 1);
        assertEquals("fixture-2026-10-08", page1.items().get(0).id());
        assertEquals("fixture-2026-10-01", page2.items().get(0).id());
        assertEquals(null, page2.nextCursor());
    }

    @Test
    void adminActivationWithAStaleExpectedVersionIsAConflictAndMovesNothing() {
        var service = context.getBean(AdminGraphVersionService.class);
        // Another admin already moved the pointer to 10-01; this admin still saw 10-08 as active.
        service.activate("fixture-2026-10-01", new GraphVersionActivateRequest("first", "fixture-2026-10-08"),
                "graph-key-race-1", admin(), "it-race-1");

        var error = assertThrows(CustomException.class, () -> service.activate("fixture-2026-10-08",
                new GraphVersionActivateRequest("second", "fixture-2026-10-08"), "graph-key-race-2", admin(), "it"));

        assertEquals(ErrorCode.REVISION_CONFLICT, error.getErrorCode());
        assertEquals("fixture-2026-10-01", jdbc.queryForObject("SELECT id FROM graph_versions WHERE active", String.class));
        assertEquals(0, jdbc.queryForObject(
                "SELECT count(*) FROM graph_activations WHERE reason = 'second'", Integer.class));
    }

    @Test
    void adminActivationRefusesAVersionWhoseSnapshotCannotBeRead() {
        jdbc.update("""
                INSERT INTO artifacts (id, kind, storage_uri, sha256, bytes, media_type, created_at)
                VALUES ('artifact-fixture-unreadable', 'graph_snapshot', 'artifact:unreadable', ?, 1, 'application/json', now())
                """, "3".repeat(64));
        jdbc.update("""
                INSERT INTO graph_versions (id, sequence, kind, created_at, created_by, source_label, issue_count,
                    relation_count, article_count, snapshot_artifact_id, review_revision)
                VALUES ('fixture-unreadable', 98, 'fixture', now(), 'system', 'unreadable', 0, 0, 0,
                    'artifact-fixture-unreadable', 0)
                """);

        var error = assertThrows(CustomException.class, () -> context.getBean(AdminGraphVersionService.class)
                .activate("fixture-unreadable", new GraphVersionActivateRequest("try", "fixture-2026-10-08"), "graph-key-2", admin(), "it"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, error.getErrorCode());
        assertEquals("fixture-2026-10-08", jdbc.queryForObject("SELECT id FROM graph_versions WHERE active", String.class));
        assertEquals(0, jdbc.queryForObject(
                "SELECT count(*) FROM idempotency_records WHERE resource_id = 'fixture-unreadable'", Integer.class));
    }

    @Test
    void firstActivationStampsPublishedAtWithTheSameTimeAsTheHistoryAndTheAudit() {
        // Seeding stamps published_at, so clear it: the version is then unpublished like a fresh import.
        unpublish("fixture-2026-10-01");
        AdminPrincipal admin = admin();

        context.getBean(AdminGraphVersionService.class).activate("fixture-2026-10-01",
                new GraphVersionActivateRequest("first publish", "fixture-2026-10-08"), "graph-key-pub",
                admin, "it-pub");

        Timestamp published = jdbc.queryForObject(
                "SELECT published_at FROM graph_versions WHERE id = 'fixture-2026-10-01'", Timestamp.class);
        assertEquals(published, jdbc.queryForObject(
                "SELECT activated_at FROM graph_activations WHERE reason = 'first publish'", Timestamp.class));
        assertEquals(published, jdbc.queryForObject(
                "SELECT occurred_at FROM audit_logs WHERE target_id = 'fixture-2026-10-01' AND admin_id = ?",
                Timestamp.class, admin.adminId()));
    }

    @Test
    void activationTimeIsTakenAfterThePublicationLockNotWhenTheRequestArrived() throws Exception {
        // Another pointer change holds the shared publication lock (JdbcGraphVersionRepository.PUBLICATION_LOCK) for a while.
        TransactionTemplate other = new TransactionTemplate(context.getBean(PlatformTransactionManager.class));
        CountDownLatch locked = new CountDownLatch(1);
        Thread holder = new Thread(() -> other.executeWithoutResult(status -> {
            jdbc.execute("SELECT pg_advisory_xact_lock(" + 0x7a6f6f7067726170L + ")");
            locked.countDown();
            try {
                Thread.sleep(1500);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
            }
        }));
        holder.start();
        assertTrue(locked.await(10, TimeUnit.SECONDS));
        AdminPrincipal admin = admin();

        context.getBean(AdminGraphVersionService.class).activate("fixture-2026-10-01",
                new GraphVersionActivateRequest("after the lock", "fixture-2026-10-08"), "graph-key-wait",
                admin, "it-wait");
        holder.join();

        Instant requested = jdbc.queryForObject(
                "SELECT created_at FROM idempotency_records WHERE resource_id = 'fixture-2026-10-01' AND idem_key = ?",
                Timestamp.class, "graph-key-wait").toInstant();
        Instant activated = jdbc.queryForObject(
                "SELECT activated_at FROM graph_activations WHERE reason = 'after the lock'", Timestamp.class).toInstant();
        assertTrue(Duration.between(requested, activated).toMillis() >= 1000,
                "activated " + activated + " should follow the held lock, request was " + requested);
        // An asOf between arrival and the real switch still sees the old version.
        assertEquals("fixture-2026-10-08", selector.select(null, null, requested.plusMillis(500)).version().id());
    }

    @Test
    void importedVersionIsRefusedWithoutAnExclusionStoreAndThePointerStays() {
        // An unpublished imported version over a readable snapshot (kind is what the gate looks at).
        unpublish("fixture-2026-10-01");
        jdbc.update("UPDATE graph_versions SET kind = 'snapshot' WHERE id = 'fixture-2026-10-01'");
        // The snapshot itself is readable, so the refusal below is the exclusion-store gate, not a broken file.
        context.getBean(GraphSnapshotStore.class).load(repository.find("fixture-2026-10-01").orElseThrow());

        var error = assertThrows(CustomException.class, () -> context.getBean(AdminGraphVersionService.class)
                .activate("fixture-2026-10-01", new GraphVersionActivateRequest("go live",
                        "fixture-2026-10-08"), "graph-key-imported", admin(), "it"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, error.getErrorCode());
        assertEquals("fixture-2026-10-08", jdbc.queryForObject("SELECT id FROM graph_versions WHERE active", String.class));
        assertNull(jdbc.queryForObject("SELECT published_at FROM graph_versions WHERE id = 'fixture-2026-10-01'",
                Timestamp.class));
        assertEquals(0, jdbc.queryForObject(
                "SELECT count(*) FROM graph_activations WHERE reason = 'go live'", Integer.class));
    }

    @Test
    void aFailedAuditWriteRollsBackThePointerTheHistoryAndTheIdempotencyRecord() {
        // graph_activations.admin_id has no FK, but audit_logs.admin_id does: an unknown admin fails only the audit insert.
        AdminPrincipal ghost = new AdminPrincipal("graph-admin-missing-" + UUID.randomUUID(), "ghost@example.com",
                "Ghost", "admin", "session-ghost");

        var error = assertThrows(CustomException.class, () -> context.getBean(AdminGraphVersionService.class)
                .activate("fixture-2026-10-01", new GraphVersionActivateRequest("audit fails",
                        "fixture-2026-10-08"), "graph-key-ghost", ghost, "it"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, error.getErrorCode());
        assertEquals("fixture-2026-10-08", jdbc.queryForObject("SELECT id FROM graph_versions WHERE active", String.class));
        assertEquals(0, jdbc.queryForObject(
                "SELECT count(*) FROM graph_activations WHERE reason = 'audit fails'", Integer.class));
        assertEquals(0, jdbc.queryForObject(
                "SELECT count(*) FROM idempotency_records WHERE idem_key = 'graph-key-ghost'", Integer.class));
    }

    /** A snapshot file names its own version id, so tests reuse a seeded version and clear its publication stamp. */
    private static void unpublish(String versionId) {
        jdbc.update("UPDATE graph_versions SET published_at = NULL WHERE id = ?", versionId);
    }

    private static AdminPrincipal admin() {
        String id = "graph-admin-" + UUID.randomUUID();
        jdbc.update("""
                INSERT INTO admins (id, email, email_key, display_name, password_hash, role, status, created_at)
                VALUES (?, ?, ?, 'Graph Admin', 'test-hash', 'admin', 'active', now())
                """, id, id + "@example.com", id + "@example.com");
        return new AdminPrincipal(id, id + "@example.com", "Graph Admin", "admin", "session-" + id);
    }
}
