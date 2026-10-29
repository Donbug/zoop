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
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.auth.service.MemberSettingsService;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.StrictJson;
import com.zoop.graph.read.EventDetailService;
import com.zoop.graph.read.GraphQueryService;
import com.zoop.graph.read.PersonalCompanies;
import com.zoop.graph.read.dto.EventDetail;
import com.zoop.graph.snapshot.FixtureGraphVersionSeeder;
import com.zoop.graph.snapshot.GraphSnapshotStore;
import com.zoop.graph.version.GraphVersionConflictException;
import com.zoop.graph.version.GraphVersionSelector;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import com.zoop.graph.version.JdbcGraphVersionRepository.NewGraphVersion;
import com.zoop.portfolio.service.PortfolioService;
import java.sql.Timestamp;
import java.time.Duration;
import static org.mockito.Mockito.mock;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import com.jayway.jsonpath.JsonPath;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import com.zoop.graph.read.GraphController;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
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
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

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
    void aVersionAloneOverHttpReturnsTheTimeThatOpensItAgain() throws Exception {
        // The version before the active one, read through the real selector, store and DB; sessions are not needed for mode=all.
        var mvc = MockMvcBuilders.standaloneSetup(new GraphController(context.getBean(GraphQueryService.class),
                        mock(MemberSessionService.class), mock(PersonalCompanies.class)))
                .setControllerAdvice(new GlobalExceptionHandler()).addFilters(new RequestIdFilter()).build();
        String body = mvc.perform(get("/api/v1/graph").param("mode", "all").param("graphVersion", "fixture-2026-10-01"))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
        String asOf = JsonPath.read(body, "$.metadata.asOf");
        assertEquals(Instant.parse("2026-10-01T00:00:00Z"), Instant.parse(asOf), "its first publication, not the request time");

        // Sent back as a browser would keep it (millisecond ISO time) with the version: the same version opens.
        mvc.perform(get("/api/v1/graph").param("mode", "all").param("graphVersion", "fixture-2026-10-01").param("asOf", asOf))
                .andExpect(status().isOk()).andExpect(jsonPath("$.metadata.graphVersion").value("fixture-2026-10-01"));
    }

    @Test
    void thePreviousVersionIsTheOnePublicBeforeTheLastActivationUpToTheGivenTime() {
        Instant later = Instant.parse("2026-10-20T00:00:00Z");
        assertEquals(java.util.Optional.of("fixture-2026-10-01"), repository.previousVersionId("fixture-2026-10-08", later));
        assertTrue(repository.previousVersionId("fixture-2026-10-01", later).isEmpty(), "the first public version");
        assertTrue(repository.previousVersionId("fixture-2026-10-08", Instant.parse("2026-10-05T00:00:00Z")).isEmpty(),
                "not public yet then");

        // A rollback makes 10-01 public again after 10-08; a no-op reactivation does not move the pointer.
        repository.activateSystem("fixture-2026-10-08", "no-op", Instant.parse("2026-10-10T00:00:00Z"));
        repository.activateSystem("fixture-2026-10-01", "rollback", Instant.parse("2026-10-11T00:00:00Z"));
        assertEquals(java.util.Optional.of("fixture-2026-10-08"), repository.previousVersionId("fixture-2026-10-01", later));
        assertTrue(repository.previousVersionId("fixture-2026-10-01", Instant.parse("2026-10-10T12:00:00Z")).isEmpty(),
                "before the rollback it was only ever the first version");
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
        // A version alone is read as of its first publication, which a rollback does not move (#88).
        assertEquals(Optional.of(Instant.parse("2026-10-01T00:00:00Z")), repository.firstActivatedAt("fixture-2026-10-01"));
        var alone = selector.select(null, "fixture-2026-10-01", null);
        assertEquals(Instant.parse("2026-10-01T00:00:00Z"), alone.asOf());
        assertEquals("fixture-2026-10-01", selector.select(null, "fixture-2026-10-01", alone.asOf()).version().id());
        assertEquals(Optional.empty(), repository.firstActivatedAt("never-registered"));
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
    void anExclusionInTheStoreHidesTheIssueFromThePublicGraphOfThatVersionOnly() {
        var service = context.getBean(GraphQueryService.class);
        var before = service.getGraph("all", null, null, null, null, null, null, null, "it-x1");
        String issue = before.nodes().stream().filter(node -> "issue".equals(node.kind())).findFirst().orElseThrow().id();
        // What the operator exclusion command writes (FS081): one change at MAX+1 and its target, in the active version only.
        long revision = jdbc.queryForObject("SELECT COALESCE(MAX(revision), 0) + 1 FROM disclosure_exclusion_changes", Long.class);
        jdbc.update("INSERT INTO disclosure_exclusion_changes (revision, action, cause, report_sha256, reason, operator, changed_at) "
                + "VALUES (?, 'exclude', 'source-change', ?, 'it exclusion', 'it-operator', now())", revision, "9".repeat(64));
        jdbc.update("INSERT INTO disclosure_exclusion_targets (revision, graph_version_id, target_kind, target_id) "
                + "VALUES (?, 'fixture-2026-10-08', 'issue', ?)", revision, issue);

        var after = service.getGraph("all", null, null, null, null, null, null, null, "it-x2");
        assertFalse(after.nodes().stream().anyMatch(node -> node.id().equals(issue)), "the excluded issue is not served");
        assertTrue(after.nodes().size() < before.nodes().size());
        var past = service.getGraph("all", null, null, null, null, "2026-10-05T00:00:00Z", null, null, "it-x3");
        assertEquals("fixture-2026-10-01", past.metadata().graphVersion(), "another version keeps its own (empty) exclusions");
    }

    @Test
    void fs014SavedWatchlistAndMockHoldingsAppearInTheNextPersonalRead() {
        var tx = new TransactionTemplate(context.getBean(PlatformTransactionManager.class));
        tx.executeWithoutResult(status -> {
            String memberId = "graph-personal-" + UUID.randomUUID();
            Timestamp now = Timestamp.from(Instant.now());
            jdbc.update("""
                    INSERT INTO members (id, analytics_key, email, email_key, display_name,
                                         password_hash, signup_method, status, mode, investor,
                                         completed, tutorial_completed, settings_version,
                                         created_at, updated_at, blocked_at)
                    VALUES (?, ?, ?, ?, 'Graph Test', 'test-hash', 'email', 'active', NULL, NULL,
                            false, false, 1, ?, ?, NULL)
                    """, memberId, memberId, memberId + "@example.com", memberId + "@example.com", now, now);
            var member = new MemberPrincipal(memberId, "graph-test-session");
            var settings = context.getBean(MemberSettingsService.class);
            var portfolio = context.getBean(PortfolioService.class);
            var personal = context.getBean(PersonalCompanies.class);
            var graph = context.getBean(GraphQueryService.class);

            var empty = graph.getGraph("personal", null, 1, null, null, null, null, personal.of(member), "empty");
            assertEquals("no_personal_stocks", empty.metadata().emptyReason());
            assertTrue(empty.nodes().isEmpty());

            settings.update(member, StrictJson.parseObject("""
                    {"version":1,"investor":false,"mode":"watchlist",
                     "watchlistIds":["NASDAQ:NVDA","KRX:005930"],"completed":true}
                    """.getBytes(java.nio.charset.StandardCharsets.UTF_8)).node(), "watch-save");
            var watched = graph.getGraph("personal", null, 1, null, null, null, null, personal.of(member), "watched");
            assertEquals(List.of("NASDAQ:NVDA", "KRX:005930"), watched.metadata().focusCompanyIds());
            assertTrue(watched.nodes().stream().filter(node -> node.id().equals("NASDAQ:NVDA"))
                    .allMatch(node -> node.watch() && !node.holding()));

            var connection = portfolio.connect(member, "demo-balanced", "graph-connect", "connected");
            var combined = graph.getGraph("personal", null, 1, null, null, null, null, personal.of(member), "combined");
            assertEquals(List.of("KRX:005930", "KRX:000660", "NYSE:TSM", "NASDAQ:NVDA"), combined.metadata().focusCompanyIds());
            assertTrue(combined.nodes().stream().filter(node -> node.id().equals("KRX:005930"))
                    .allMatch(node -> node.holding() && node.watch()));

            settings.update(member, StrictJson.parseObject("""
                    {"version":2,"watchlistIds":[]}
                    """.getBytes(java.nio.charset.StandardCharsets.UTF_8)).node(), "watch-clear");
            var held = graph.getGraph("personal", null, 1, null, null, null, null, personal.of(member), "held");
            assertEquals(List.of("KRX:005930", "KRX:000660", "NYSE:TSM"), held.metadata().focusCompanyIds());
            assertTrue(held.nodes().stream().noneMatch(com.zoop.graph.read.dto.GraphResponse.Node::watch));

            portfolio.disconnect(member, connection.id());
            var cleared = graph.getGraph("personal", null, 1, null, null, null, null, personal.of(member), "cleared");
            assertEquals("no_personal_stocks", cleared.metadata().emptyReason());
            assertTrue(graph.getGraph("all", null, null, null, null, null, null, null, "market").nodes().size() > 0);
            status.setRollbackOnly();
        });
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
    void importedVersionPassesTheExclusionStoreGateAndIsStillCheckedBeforeThePointerMoves() {
        // An unpublished imported version over a readable snapshot (kind is what the gate looks at). The exclusion store exists
        // (FS081), so the version is no longer refused for want of one: it goes on to the rights and evidence checks, which a
        // fixture snapshot without imported evidence rows fails, and the pointer stays.
        unpublish("fixture-2026-10-01");
        jdbc.update("UPDATE graph_versions SET kind = 'snapshot' WHERE id = 'fixture-2026-10-01'");
        // The snapshot itself is readable, so the refusal below is a check of its content, not a broken file.
        context.getBean(GraphSnapshotStore.class).load(repository.find("fixture-2026-10-01").orElseThrow());

        var error = assertThrows(CustomException.class, () -> context.getBean(AdminGraphVersionService.class)
                .activate("fixture-2026-10-01", new GraphVersionActivateRequest("go live",
                        "fixture-2026-10-08"), "graph-key-imported", admin(), "it"));

        assertEquals(ErrorCode.REVISION_CONFLICT, error.getErrorCode(), "a withheld citation, not exclusion_store_unavailable");
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

    // ---- automatic activation after an import (FS059) -------------------------------------------------------------------------

    /** An unpublished imported version row over a placeholder artifact; only its row matters to the repository's choice. */
    private static void imported(String id, long sequence, Instant createdAt) {
        jdbc.update("""
                INSERT INTO artifacts (id, kind, storage_uri, sha256, bytes, media_type, created_at)
                VALUES (?, 'graph_snapshot', ?, ?, 1, 'application/json', now())
                """, "artifact-fixture-" + id, "artifact:" + id, "4".repeat(64));
        jdbc.update("""
                INSERT INTO graph_versions (id, sequence, kind, created_at, created_by, source_label, issue_count,
                    relation_count, article_count, snapshot_artifact_id, review_revision)
                VALUES (?, ?, 'snapshot', ?, 'operator:test', 'auto', 0, 0, 0, ?, 0)
                """, id, sequence, Timestamp.from(createdAt), "artifact-fixture-" + id);
    }

    @Test
    void autoActivationTakesOnlyTheNewestImportSinceStartAndRecordsTheSystemActor() {
        Instant since = Instant.now().minusSeconds(60);
        imported("auto-1", 91, since.plusSeconds(1));
        imported("auto-2", 92, since.plusSeconds(2));
        imported("auto-before-start", 93, since.minusSeconds(3600));

        assertEquals("auto-2", repository.autoActivationCandidate(since).orElseThrow().id(),
                "the newest import since start; one staged while it was off never counts");
        assertTrue(repository.activateBySystem("auto-1", "fixture-2026-10-08", since, "auto", () -> at -> { }).isEmpty(),
                "an older import is never activated over the newest");
        assertTrue(repository.activateBySystem("auto-2", "fixture-2026-10-01", since, "auto", () -> at -> { }).isEmpty(),
                "the pointer moved meanwhile: nothing changes");
        assertEquals("fixture-2026-10-08", jdbc.queryForObject("SELECT id FROM graph_versions WHERE active", String.class));

        var activation = repository.activateBySystem("auto-2", "fixture-2026-10-08", since, "auto-activation after import",
                () -> at -> { }).orElseThrow();

        assertEquals("fixture-2026-10-08", activation.previousVersionId());
        assertEquals("auto-2", jdbc.queryForObject("SELECT id FROM graph_versions WHERE active", String.class));
        var row = jdbc.queryForMap("""
                SELECT actor_kind, admin_id, admin_email_snapshot, action, reason, pointer_changed, activated_at
                FROM graph_activations WHERE version_id = 'auto-2'
                """);
        assertEquals("system", row.get("actor_kind"));
        assertNull(row.get("admin_id"));
        assertEquals("system", row.get("admin_email_snapshot"));
        assertEquals("activate", row.get("action"));
        assertEquals("auto-activation after import", row.get("reason"));
        assertEquals(Boolean.TRUE, row.get("pointer_changed"));
        assertEquals(row.get("activated_at"), jdbc.queryForObject(
                "SELECT published_at FROM graph_versions WHERE id = 'auto-2'", Timestamp.class));
        assertTrue(repository.autoActivationCandidate(since).isEmpty(), "auto-1 is older than the public version now");
    }

    @Test
    void activateImportedRunsTheSameRealChecksInsideTheLockAndARefusalMovesNothing() {
        // A seeded fixture made an unpublished imported version after the active one: its snapshot is readable, but it has no
        // imported evidence rows, so the real current-rights gate (the admin path's) refuses it.
        jdbc.update("DELETE FROM graph_activations WHERE version_id = 'fixture-2026-10-01'");
        unpublish("fixture-2026-10-01");
        jdbc.update("UPDATE graph_versions SET kind = 'snapshot', sequence = 1000, created_at = now() "
                + "WHERE id = 'fixture-2026-10-01'");
        Instant since = Instant.now().minusSeconds(60);
        AdminGraphVersionService service = context.getBean(AdminGraphVersionService.class);
        var candidate = service.importedCandidate(since).orElseThrow();
        assertEquals("fixture-2026-10-01", candidate.id());

        var error = assertThrows(CustomException.class, () -> service.activateImported(candidate, since, "it-auto"));

        assertEquals(ErrorCode.REVISION_CONFLICT, error.getErrorCode(), "a withheld citation, as for an admin activation");
        assertEquals("fixture-2026-10-08", jdbc.queryForObject("SELECT id FROM graph_versions WHERE active", String.class));
        assertEquals(0, jdbc.queryForObject(
                "SELECT count(*) FROM graph_activations WHERE version_id = 'fixture-2026-10-01'", Integer.class));
        assertNull(jdbc.queryForObject("SELECT published_at FROM graph_versions WHERE id = 'fixture-2026-10-01'",
                Timestamp.class));
    }

    @Test
    void anAdminRollbackIsNeverUndoneByAnImportThatWasAlreadyWaitingOnlyByALaterOne() {
        Instant since = Instant.now().minusSeconds(600);
        imported("auto-waiting", 96, Instant.now().minusSeconds(5));
        // The administrator moves the pointer back to an older version: the waiting import is newer than it, but staged before.
        repository.activateByAdmin("fixture-2026-10-01", "fixture-2026-10-08", "graph-admin-rollback", "rollback@example.com",
                "rollback", () -> at -> { });

        assertTrue(repository.autoActivationCandidate(since).isEmpty(),
                "an import staged before the admin's choice never undoes it");

        imported("auto-later", 97, Instant.now().plusSeconds(5));
        assertEquals("auto-later", repository.autoActivationCandidate(since).orElseThrow().id(), "the next import counts again");
    }

    @Test
    void aRefusedCheckUnderTheLockKeepsThePointerAndWritesNoHistory() {
        Instant since = Instant.now().minusSeconds(60);
        imported("auto-3", 94, since.plusSeconds(1));

        var error = assertThrows(CustomException.class, () -> repository.activateBySystem("auto-3", "fixture-2026-10-08",
                since, "auto", () -> { throw new CustomException(ErrorCode.REVISION_CONFLICT); }));

        assertEquals(ErrorCode.REVISION_CONFLICT, error.getErrorCode());
        assertEquals("fixture-2026-10-08", jdbc.queryForObject("SELECT id FROM graph_versions WHERE active", String.class));
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM graph_activations WHERE version_id = 'auto-3'",
                Integer.class));
        assertNull(jdbc.queryForObject("SELECT published_at FROM graph_versions WHERE id = 'auto-3'", Timestamp.class));
        assertEquals("auto-3", repository.autoActivationCandidate(since).orElseThrow().id(), "still the candidate");
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
