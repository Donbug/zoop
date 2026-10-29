package com.zoop.graph.round;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import com.zoop.ZoopApplication;
import com.zoop.graph.round.GraphRoundEvent.Outcome;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.dao.InvalidDataAccessApiUsageException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * {@code graph_rounds} / {@code graph_round_events} against the disposable company test database: the real migration, its
 * constraints and guards, the lease with its fencing token, the one-transaction advance with its timeline, and the link written
 * inside a caller's transaction.
 */
@Tag("graph-postgres")
class GraphRoundRepositoryPostgresTest {
    private static final Instant SLOT_1 = Instant.parse("2026-10-30T00:05:00Z"); // 09:05 KST
    private static final Instant SLOT_2 = Instant.parse("2026-10-30T00:35:00Z"); // 09:35 KST
    private static final Instant NOW = Instant.parse("2026-10-30T00:05:03Z");
    private static final String ROUND_1 = "round-20261030T0905";
    private static final String ROUND_2 = "round-20261030T0935";
    private static final String DIGEST = "a".repeat(64);
    private static ConfigurableApplicationContext context;
    private static JdbcTemplate jdbc;
    private static JdbcGraphRoundRepository rounds;
    private static ObjectMapper mapper;
    private static TransactionTemplate transaction;

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
        rounds = context.getBean(JdbcGraphRoundRepository.class);
        mapper = context.getBean(ObjectMapper.class);
        transaction = new TransactionTemplate(context.getBean(PlatformTransactionManager.class));
    }

    /** The row as its holder has it: claimed by {@code owner} now. */
    private static GraphRound claimed(String roundId, String owner) {
        return rounds.claim(roundId, owner, Duration.ofMinutes(10), NOW).orElseThrow();
    }

    private static GraphRound advanced(GraphRound expected, GraphRoundPatch patch, Outcome outcome, String code,
            String requestId, ObjectNode detail, Instant at) {
        return rounds.advance(expected, patch, outcome, code, requestId, detail, at).orElseThrow();
    }

    @AfterAll
    static void stop() {
        if (jdbc != null) clean();
        if (context != null) context.close();
    }

    /** Rows are guarded against DELETE; TRUNCATE (no row triggers) is the test's way out. */
    private static void clean() {
        jdbc.execute("TRUNCATE graph_round_events, graph_rounds");
    }

    @BeforeEach
    void setUp() {
        clean();
    }

    @AfterEach
    void tearDown() {
        clean();
    }

    @Test
    void aRoundIsCreatedScheduledClaimedByLeaseAndAdvancedWithItsTimelineInOneTransaction() {
        GraphRound created = rounds.create(ROUND_1, SLOT_1, "system:scheduler", NOW);
        assertEquals(GraphRoundStage.SCHEDULED, created.stage());
        assertEquals(0, created.attempts());
        assertTrue(created.lease().isEmpty());
        assertTrue(created.open());
        assertEquals(Optional.of(created), rounds.findBySlot(SLOT_1));

        // The lease: one owner at a time, the same owner may renew (same token), another takes it only after it expired (new
        // token).
        GraphRound first = rounds.claim(ROUND_1, "task-a", Duration.ofMinutes(2), NOW).orElseThrow();
        long token = first.lease().orElseThrow().token();
        assertTrue(rounds.claim(ROUND_1, "task-b", Duration.ofMinutes(2), NOW.plusSeconds(30)).isEmpty());
        GraphRound renewed = rounds.claim(ROUND_1, "task-a", Duration.ofMinutes(2), NOW.plusSeconds(30)).orElseThrow();
        assertEquals(token, renewed.lease().orElseThrow().token());
        GraphRound taken = rounds.claim(ROUND_1, "task-b", Duration.ofMinutes(2), NOW.plus(Duration.ofMinutes(3))).orElseThrow();
        assertEquals("task-b", taken.lease().orElseThrow().owner());
        assertTrue(taken.lease().orElseThrow().token() != token, "a take-over is a new lease");
        rounds.release(ROUND_1, "task-a"); // not the holder: no effect
        assertTrue(rounds.find(ROUND_1).orElseThrow().lease().isPresent());

        // Fencing: the old holder's late outcome is refused, and no event is written for it.
        assertTrue(rounds.advance(first, GraphRoundPatch.advanceTo(GraphRoundStage.RUN_REQUESTED), Outcome.ADVANCED, null,
                "req-late", null, NOW.plusSeconds(1)).isEmpty());
        assertTrue(rounds.events(ROUND_1).isEmpty());
        assertEquals(GraphRoundStage.SCHEDULED, rounds.find(ROUND_1).orElseThrow().stage());
        // An unclaimed row cannot be advanced (IllegalArgumentException, translated by the repository proxy).
        assertThrows(InvalidDataAccessApiUsageException.class, () -> rounds.advance(created,
                GraphRoundPatch.advanceTo(GraphRoundStage.RUN_REQUESTED), Outcome.ADVANCED, null, null, null, NOW));
        rounds.release(ROUND_1, "task-b");
        assertTrue(rounds.find(ROUND_1).orElseThrow().lease().isEmpty());

        // R1 accepted, then R2 answered a plan: stage and plan in the row, one event each.
        ObjectNode detail = mapper.createObjectNode();
        detail.put("planDigest", DIGEST);
        GraphRound requested = advanced(claimed(ROUND_1, "task-a"), GraphRoundPatch.advanceTo(GraphRoundStage.RUN_REQUESTED),
                Outcome.ADVANCED, null, "req-1", null, NOW.plusSeconds(1));
        assertEquals(GraphRoundStage.RUN_REQUESTED, requested.stage());
        assertEquals(0, requested.attempts());
        assertEquals("task-a", requested.lease().orElseThrow().owner(), "an open stage keeps the lease");
        GraphRound planReady = advanced(requested, GraphRoundPatch.advanceTo(GraphRoundStage.PLAN_READY), Outcome.ADVANCED,
                null, null, null, NOW.plusSeconds(1));
        // The row as it was before that stage change is stale now: the expected stage no longer matches, nothing is written.
        assertTrue(rounds.advance(requested, GraphRoundPatch.advanceTo(GraphRoundStage.PLAN_READY), Outcome.ADVANCED, null,
                null, null, NOW).isEmpty(), "a stale expected stage is fenced");
        GraphRound planned = advanced(planReady, GraphRoundPatch.advanceTo(GraphRoundStage.PLAN_READY).plan("plan-1", DIGEST),
                Outcome.ADVANCED, null, "req-2", detail, NOW.plusSeconds(2));
        assertEquals(Optional.of("plan-1"), planned.planId());
        assertEquals(Optional.of(DIGEST), planned.planDigest());

        // A waiting stage counts attempts and keeps the row out of the due list until next_attempt_at.
        Instant later = NOW.plusSeconds(120);
        GraphRound waiting = advanced(planned, GraphRoundPatch.waitAt(GraphRoundStage.PLAN_READY, later), Outcome.WAITING,
                "model_unavailable", "req-3", null, NOW.plusSeconds(3));
        assertEquals(1, waiting.attempts());
        assertEquals(Optional.of(later), waiting.nextAttemptAt());
        assertTrue(rounds.due(NOW.plusSeconds(10), 10).isEmpty());
        assertEquals(List.of(ROUND_1), rounds.due(later, 10).stream().map(GraphRound::roundId).toList());

        // Advancing clears the wait and restarts the attempt count; the plan stays.
        GraphRound queued = advanced(waiting, GraphRoundPatch.advanceTo(GraphRoundStage.ANALYSIS_QUEUED), Outcome.ADVANCED,
                null, null, null, NOW.plusSeconds(4));
        assertEquals(0, queued.attempts());
        assertTrue(queued.nextAttemptAt().isEmpty());
        assertEquals(Optional.of("plan-1"), queued.planId());

        List<GraphRoundEvent> events = rounds.events(ROUND_1);
        assertEquals(5, events.size());
        assertEquals(List.of(GraphRoundStage.RUN_REQUESTED, GraphRoundStage.PLAN_READY, GraphRoundStage.PLAN_READY,
                GraphRoundStage.PLAN_READY, GraphRoundStage.ANALYSIS_QUEUED), events.stream().map(GraphRoundEvent::stage).toList());
        assertEquals(Optional.of("model_unavailable"), events.get(3).code());
        assertEquals(Optional.of("req-2"), events.get(2).requestId());
        assertEquals(DIGEST, events.get(2).detail().orElseThrow().get("planDigest").stringValue());
        assertTrue(events.get(0).detail().isEmpty());
    }

    /**
     * The import's own record: the version link is written in the caller's transaction, fenced like advance, and it is what the
     * order guard sees even while the stage change after the commit is still missing.
     */
    @Test
    void theVersionLinkIsWrittenInTheCallersTransactionFencedAndSeenByTheOrderGuard() {
        String versionId = jdbc.queryForObject("SELECT id FROM graph_versions ORDER BY id LIMIT 1", String.class);
        assertTrue(versionId != null, "the fixture seeder leaves a version to link");
        rounds.create(ROUND_1, SLOT_1, "system:scheduler", NOW);
        rounds.create(ROUND_2, SLOT_2, "system:scheduler", NOW);
        GraphRound older = advanced(claimed(ROUND_1, "task-a"), GraphRoundPatch.advanceTo(GraphRoundStage.IMPORTED),
                Outcome.ADVANCED, "staged", null, null, NOW.plusSeconds(1));
        assertEquals(Optional.of(ROUND_1), rounds.newestImported().map(GraphRound::roundId));
        GraphRound newest = advanced(claimed(ROUND_2, "task-a"), GraphRoundPatch.advanceTo(GraphRoundStage.HANDOFF_READY)
                .handoff("round-20261030T0935", DIGEST, DIGEST), Outcome.ADVANCED, null, null, null, NOW.plusSeconds(2));

        // Outside a transaction the link is refused before anything is written (IllegalStateException, translated by the proxy).
        assertThrows(InvalidDataAccessApiUsageException.class, () -> rounds.link(newest, versionId, NOW.plusSeconds(3)));
        // A rolled-back transaction takes the link with it.
        assertThrows(IllegalStateException.class, () -> transaction.executeWithoutResult(status -> {
            assertTrue(rounds.link(newest, versionId, NOW.plusSeconds(3)));
            throw new IllegalStateException("rolled back");
        }));
        assertTrue(rounds.find(ROUND_2).orElseThrow().graphVersionId().isEmpty());
        assertEquals(Optional.of(ROUND_1), rounds.newestImported().map(GraphRound::roundId));
        // Committed: the open round with its version linked is the newest import, before its stage changes.
        transaction.executeWithoutResult(status -> assertTrue(rounds.link(newest, versionId, NOW.plusSeconds(4))));
        GraphRound linked = rounds.find(ROUND_2).orElseThrow();
        assertEquals(Optional.of(versionId), linked.graphVersionId());
        assertEquals(GraphRoundStage.HANDOFF_READY, linked.stage());
        assertEquals(Optional.of(ROUND_2), rounds.newestImported().map(GraphRound::roundId));
        // Fenced: another holder's lease, or a stale stage, and nothing is written.
        GraphRound takenOver = rounds.claim(ROUND_2, "task-b", Duration.ofMinutes(2), NOW.plus(Duration.ofMinutes(11))).orElseThrow();
        transaction.executeWithoutResult(status -> assertFalse(rounds.link(newest, versionId, NOW.plusSeconds(5))));
        // A finished row keeps no lease, so there is no token to link under: refused before any statement.
        assertThrows(InvalidDataAccessApiUsageException.class,
                () -> transaction.executeWithoutResult(status -> rounds.link(older, versionId, NOW.plusSeconds(5))));
        // The stage change after the commit, by the holder.
        GraphRound imported = advanced(takenOver, GraphRoundPatch.advanceTo(GraphRoundStage.IMPORTED).graphVersion(versionId),
                Outcome.ADVANCED, "unchanged", null, null, NOW.plusSeconds(6));
        assertEquals(GraphRoundStage.IMPORTED, imported.stage());
        assertTrue(imported.lease().isEmpty());
        assertEquals(Optional.of(versionId), imported.graphVersionId());
        // The version a round made is written once; a finished round is never reopened.
        assertThrows(DataAccessException.class,
                () -> jdbc.update("UPDATE graph_rounds SET graph_version_id = 'other' WHERE round_id = ?", ROUND_2));
        assertThrows(DataAccessException.class,
                () -> jdbc.update("UPDATE graph_rounds SET stage = 'scheduled' WHERE round_id = ?", ROUND_2));
    }

    @Test
    void aFailedRoundKeepsItsCodeAndTerminalRoundsLeaveTheWorkListButStayInThePage() {
        rounds.create(ROUND_1, SLOT_1, "system:scheduler", NOW);
        rounds.create(ROUND_2, SLOT_2, "admin:a1", NOW.plusSeconds(1800));
        assertEquals(List.of(ROUND_1, ROUND_2), rounds.due(NOW.plusSeconds(1800), 10).stream().map(GraphRound::roundId).toList());
        assertEquals(2, rounds.openCount());

        // A version linked by an import whose later attempt failed stays on the failed row (its import is committed).
        String versionId = jdbc.queryForObject("SELECT id FROM graph_versions ORDER BY id LIMIT 1", String.class);
        GraphRound holder = claimed(ROUND_1, "task-a");
        transaction.executeWithoutResult(status -> assertTrue(rounds.link(holder, versionId, NOW.plusSeconds(4))));
        GraphRound failed = advanced(rounds.find(ROUND_1).orElseThrow(), GraphRoundPatch.fail("import:handoff_withheld"),
                Outcome.FAILED, "import:handoff_withheld", "req-9", null, NOW.plusSeconds(5));
        assertEquals(Optional.of(versionId), failed.graphVersionId());
        assertEquals(Optional.of(ROUND_1), rounds.newestImported().map(GraphRound::roundId), "a committed import counts");
        assertEquals(GraphRoundStage.FAILED, failed.stage());
        assertEquals(Optional.of("import:handoff_withheld"), failed.failureCode());
        assertEquals(1, failed.attempts(), "the failing attempt is counted and kept");
        assertFalse(failed.open());
        assertTrue(failed.lease().isEmpty(), "a terminal stage drops the lease");
        assertThrows(IllegalArgumentException.class, () -> GraphRoundPatch.fail(null));
        assertThrows(IllegalArgumentException.class, () -> new GraphRoundPatch(GraphRoundStage.IMPORTED, null, null, null, null,
                null, null, null, "code", null, true, false, true, false));
        assertThrows(IllegalArgumentException.class, () -> GraphRoundPatch.retryAt(GraphRoundStage.IMPORTED));
        assertThrows(IllegalArgumentException.class, () -> GraphRoundPatch.retryAt(GraphRoundStage.SCHEDULED).graphVersion("v"));

        // A retry resumes under the same round id (a failed round can be claimed again): the failure code is cleared with the
        // stage, and so is the linked version (the one way the column changes; the guard refuses value-to-value changes).
        GraphRound retried = advanced(claimed(ROUND_1, "task-a"), GraphRoundPatch.retryAt(GraphRoundStage.SCHEDULED),
                Outcome.RETRIED, null, null, null, NOW.plusSeconds(6));
        assertTrue(retried.failureCode().isEmpty());
        assertTrue(retried.open());
        assertTrue(retried.graphVersionId().isEmpty());
        assertTrue(rounds.newestImported().isEmpty());

        GraphRound imported = advanced(claimed(ROUND_2, "task-a"), GraphRoundPatch.advanceTo(GraphRoundStage.IMPORTED)
                .handoff("round-20261030T0935", DIGEST, DIGEST), Outcome.ADVANCED, null, null, null, NOW.plusSeconds(7));
        assertEquals(Optional.of("round-20261030T0935"), imported.handoffId());
        assertTrue(imported.lease().isEmpty(), "a terminal stage drops the lease");
        assertTrue(rounds.claim(ROUND_2, "task-a", java.time.Duration.ofMinutes(2), NOW.plusSeconds(8)).isEmpty(),
                "a finished round is never taken");
        assertEquals(List.of(ROUND_1), rounds.due(NOW.plusSeconds(1800), 10).stream().map(GraphRound::roundId).toList());
        assertEquals(1, rounds.openCount());
        assertEquals(Optional.of(ROUND_2), rounds.newestImported().map(GraphRound::roundId));
        rounds.recordActivation(ROUND_2, null, "activation_refused:rights", NOW.plusSeconds(8));
        assertEquals(Optional.of("activation_refused:rights"), rounds.find(ROUND_2).orElseThrow().activationNote());

        // Newest slot first, filtered by stage, paged by the slot cursor.
        assertEquals(List.of(ROUND_2, ROUND_1), rounds.page(null, null, 10).stream().map(GraphRound::roundId).toList());
        assertEquals(List.of(ROUND_1), rounds.page(null, SLOT_2, 10).stream().map(GraphRound::roundId).toList());
        assertEquals(List.of(ROUND_2), rounds.page(GraphRoundStage.IMPORTED, null, 10).stream().map(GraphRound::roundId).toList());
        assertEquals(1, rounds.page(null, null, 1).size());
    }

    @Test
    void theMigrationGuardsIdentityAndTheTimeline() {
        rounds.create(ROUND_1, SLOT_1, "system:scheduler", NOW);
        advanced(claimed(ROUND_1, "task-a"), GraphRoundPatch.advanceTo(GraphRoundStage.RUN_REQUESTED), Outcome.ADVANCED, null,
                "req-1", null, NOW);

        // One row per slot, round ids of the slot form, actors of the two known kinds.
        assertThrows(DataIntegrityViolationException.class, () -> rounds.create("round-20261030T0906", SLOT_1, "system:scheduler", NOW));
        assertThrows(DataIntegrityViolationException.class, () -> rounds.create("round-1", SLOT_2, "system:scheduler", NOW));
        assertThrows(DataIntegrityViolationException.class, () -> rounds.create(ROUND_2, SLOT_2, "operator:x", NOW));
        // A failed stage needs its code and a lease needs both halves (at the SQL level, past the patch's own check).
        assertThrows(DataAccessException.class,
                () -> jdbc.update("UPDATE graph_rounds SET stage = 'failed' WHERE round_id = ?", ROUND_1));
        assertThrows(DataAccessException.class,
                () -> jdbc.update("UPDATE graph_rounds SET lease_owner = 'x', lease_until = NULL, lease_token = NULL WHERE round_id = ?",
                        ROUND_1));
        assertThrows(DataAccessException.class,
                () -> jdbc.update("UPDATE graph_rounds SET lease_token = NULL WHERE round_id = ?", ROUND_1));
        // Identity is written once and a round is never deleted.
        assertThrows(DataAccessException.class,
                () -> jdbc.update("UPDATE graph_rounds SET started_by = 'admin:b' WHERE round_id = ?", ROUND_1));
        assertThrows(DataAccessException.class,
                () -> jdbc.update("UPDATE graph_rounds SET slot_at = ? WHERE round_id = ?", java.sql.Timestamp.from(SLOT_2), ROUND_1));
        assertThrows(DataAccessException.class, () -> jdbc.update("DELETE FROM graph_rounds WHERE round_id = ?", ROUND_1));
        // The timeline is append-only.
        assertThrows(DataAccessException.class, () -> jdbc.update("UPDATE graph_round_events SET code = 'x'"));
        assertThrows(DataAccessException.class, () -> jdbc.update("DELETE FROM graph_round_events"));
        assertThrows(DataAccessException.class, () -> jdbc.update(
                "INSERT INTO graph_round_events (round_id, at, stage, outcome) VALUES (?, now(), 'scheduled', 'done')", ROUND_1));
        assertEquals(1, rounds.events(ROUND_1).size());
        assertEquals(GraphRoundStage.RUN_REQUESTED, rounds.find(ROUND_1).orElseThrow().stage());
    }
}
