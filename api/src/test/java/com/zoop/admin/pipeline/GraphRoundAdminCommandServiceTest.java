package com.zoop.admin.pipeline;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.jobs.JdbcAnalysisJobRepository;
import com.zoop.admin.jobs.JdbcAnalysisJobRepository.IdempotencyRow;
import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundOut;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.round.GraphRound;
import com.zoop.graph.round.GraphRoundClock;
import com.zoop.graph.round.GraphRoundEvent.Outcome;
import com.zoop.graph.round.GraphRoundPatch;
import com.zoop.graph.round.GraphRoundStage;
import com.zoop.graph.round.InMemoryGraphRoundRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

/** Retry and manual start over the in-memory rows; the idempotency store is a double that remembers one record per key. */
class GraphRoundAdminCommandServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-30T01:00:30Z");
    private static final AdminPrincipal ADMIN = new AdminPrincipal("admin-1", "admin@example.com", "운영", "admin", "session-1");
    private final InMemoryGraphRoundRepository rounds = new InMemoryGraphRoundRepository();
    private final JdbcAnalysisJobRepository idempotency = mock(JdbcAnalysisJobRepository.class);
    private final AdminAuditRepository audit = mock(AdminAuditRepository.class);
    private final StaticListableBeanFactory beans = new StaticListableBeanFactory();
    private final Map<String, IdempotencyRow> records = new HashMap<>();
    private GraphRoundAdminCommandService service;

    @BeforeEach
    void setUp() {
        beans.addBean("clock", new GraphRoundClock(ZoneId.of("Asia/Seoul"), LocalTime.of(9, 5), Duration.ofMinutes(30), 18,
                List.of(LocalTime.of(18, 5))));
        service = new GraphRoundAdminCommandService(rounds, beans.getBeanProvider(GraphRoundClock.class), idempotency, audit,
                JsonMapper.builder().build(), Clock.fixed(NOW, ZoneOffset.UTC));
        when(idempotency.claimIdempotency(anyString(), anyString(), anyString(), anyString(), anyString(), anyString(), any()))
                .thenAnswer(invocation -> {
                    String key = invocation.getArgument(2) + "|" + invocation.getArgument(3);
                    if (records.containsKey(key)) return false;
                    records.put(key, new IdempotencyRow(invocation.getArgument(0), invocation.getArgument(5), "pending", null, null));
                    return true;
                });
        when(idempotency.findIdempotencyForUpdate(anyString(), anyString(), anyString()))
                .thenAnswer(invocation -> Optional.ofNullable(records.get(invocation.getArgument(1) + "|" + invocation.getArgument(2))));
        org.mockito.Mockito.doAnswer(invocation -> {
            String id = invocation.getArgument(0);
            records.replaceAll((k, row) -> row.id().equals(id)
                    ? new IdempotencyRow(row.id(), row.requestHash(), "completed", invocation.getArgument(1), invocation.getArgument(2)) : row);
            return null;
        }).when(idempotency).completeIdempotency(anyString(), anyInt(), anyString());
    }

    private GraphRound failed(String roundId, Instant slot, GraphRoundStage at, String code) {
        rounds.create(roundId, slot, "system:scheduler", slot);
        GraphRound claimed = rounds.claim(roundId, "worker", Duration.ofMinutes(2), slot).orElseThrow();
        GraphRound moved = rounds.advance(claimed, GraphRoundPatch.advanceTo(at), Outcome.ADVANCED, null, null, null, slot).orElseThrow();
        ObjectNode detail = JsonMapper.builder().build().createObjectNode();
        detail.put("failedAt", at.wire());
        return rounds.advance(moved, GraphRoundPatch.fail(code), Outcome.FAILED, code, null, detail, slot.plusSeconds(60)).orElseThrow();
    }

    @Test
    void aRetryResumesAtTheStageTheFailureEventNamesLeavesNoLeaseAndIsIdempotent() {
        failed("round-20261030T0905", Instant.parse("2026-10-30T00:05:00Z"), GraphRoundStage.FREEZE_REQUESTED, "freeze_failed:x");

        GraphRoundOut out = service.retry("round-20261030T0905", "key-1", ADMIN, "req-1");

        assertEquals("freeze_requested", out.stage());
        GraphRound row = rounds.find("round-20261030T0905").orElseThrow();
        assertEquals(GraphRoundStage.FREEZE_REQUESTED, row.stage());
        assertTrue(row.lease().isEmpty(), "the command releases its short lease; the scheduler claims next");
        assertTrue(row.failureCode().isEmpty());
        assertEquals(0, row.attempts());
        var retried = rounds.events("round-20261030T0905").getLast();
        assertEquals(Outcome.RETRIED, retried.outcome());
        assertEquals("admin-1", retried.detail().orElseThrow().get("adminId").stringValue());
        assertEquals("freeze_requested", retried.detail().orElseThrow().get("resumeAt").stringValue());
        assertEquals(Optional.of("req-1"), retried.requestId());
        verify(audit).recordGraphRoundAction(eq("admin-1"), eq("admin@example.com"), eq("pipeline.round.retry"),
                eq("round-20261030T0905"), eq("req-1"), any());

        GraphRoundOut replay = service.retry("round-20261030T0905", "key-1", ADMIN, "req-2");
        assertEquals(out, replay, "the same key replays the stored answer");
        assertEquals(1, rounds.events("round-20261030T0905").stream().filter(e -> e.outcome() == Outcome.RETRIED).count());
        assertEquals(ErrorCode.REVISION_CONFLICT,
                assertThrows(CustomException.class, () -> service.retry("round-20261030T0905", "key-2", ADMIN, "req-3")).getErrorCode(),
                "an open round is not retried");
    }

    @Test
    void theResumeStageFallsBackToTheFailureCodeFamilyAndAnUnknownOrOpenRoundIsRefused() {
        rounds.create("round-20261030T0935", Instant.parse("2026-10-30T00:35:00Z"), "system:scheduler", NOW);
        GraphRound claimed = rounds.claim("round-20261030T0935", "worker", Duration.ofMinutes(2), NOW).orElseThrow();
        rounds.advance(claimed, GraphRoundPatch.fail("import:handoff_withheld"), Outcome.FAILED, "import:handoff_withheld", null, null, NOW);
        assertEquals("handoff_ready", service.retry("round-20261030T0935", "key-3", ADMIN, "req").stage());
        rounds.create("round-20261030T1105", Instant.parse("2026-10-30T02:05:00Z"), "system:scheduler", NOW);
        GraphRound waited = rounds.claim("round-20261030T1105", "worker", Duration.ofMinutes(2), NOW).orElseThrow();
        rounds.advance(waited, GraphRoundPatch.fail("analysis_timeout").analysisJob("job-running"), Outcome.FAILED, "analysis_timeout", null, null, NOW);
        assertEquals("analysis_queued", service.retry("round-20261030T1105", "key-3b", ADMIN, "req").stage(),
                "a timed-out wait keeps reading the running job; a finished job (analysis_failed) resumes at plan_ready");
        rounds.create("round-20261030T1135", Instant.parse("2026-10-30T02:35:00Z"), "system:scheduler", NOW);
        GraphRound finished = rounds.claim("round-20261030T1135", "worker", Duration.ofMinutes(2), NOW).orElseThrow();
        rounds.advance(finished, GraphRoundPatch.fail("analysis_failed:worker_deadline"), Outcome.FAILED, "analysis_failed:worker_deadline",
                null, null, NOW);
        assertEquals("plan_ready", service.retry("round-20261030T1135", "key-3c", ADMIN, "req").stage());
        rounds.create("round-20261030T1205", Instant.parse("2026-10-30T03:05:00Z"), "system:scheduler", NOW);
        GraphRound noJob = rounds.claim("round-20261030T1205", "worker", Duration.ofMinutes(2), NOW).orElseThrow();
        rounds.advance(noJob, GraphRoundPatch.fail("analysis_queue_timeout"), Outcome.FAILED, "analysis_queue_timeout", null, null, NOW);
        assertEquals("plan_ready", service.retry("round-20261030T1205", "key-3d", ADMIN, "req").stage(),
                "R3's bound has no job to read: queued again from plan_ready");
        // The event's failedAt wins over the code family: an R3 wait that timed out is recorded as plan_ready by the worker.
        failed("round-20261030T1235", Instant.parse("2026-10-30T03:35:00Z"), GraphRoundStage.PLAN_READY, "analysis_timeout");
        assertEquals("plan_ready", service.retry("round-20261030T1235", "key-3e", ADMIN, "req").stage());

        assertEquals(ErrorCode.RESOURCE_NOT_FOUND,
                assertThrows(CustomException.class, () -> service.retry("round-20261030T1005", "key-4", ADMIN, "req")).getErrorCode());
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND,
                assertThrows(CustomException.class, () -> service.retry("nope", "key-5", ADMIN, "req")).getErrorCode());
        assertEquals(ErrorCode.INVALID_REQUEST,
                assertThrows(CustomException.class, () -> service.retry("round-20261030T0935", " ", ADMIN, "req")).getErrorCode());
    }

    @Test
    void terminalAnalysisOverridesAnOlderFailedAtEvent() {
        failed("round-20261030T0905", Instant.parse("2026-10-30T00:05:00Z"), GraphRoundStage.ANALYSIS_QUEUED,
                "analysis_failed:worker_deadline");
        assertEquals("plan_ready", service.retry("round-20261030T0905", "terminal-retry", ADMIN, "req-terminal").stage());
    }

    @Test
    void aManualStartOpensTheCurrentMinuteOrTheNamedSlotAsAnAdminRowAndASecondOneConflicts() {
        GraphRoundOut now = service.start(null, "key-6", ADMIN, "req-6");
        assertEquals("round-20261030T1000", now.roundId(), "01:00:30Z is 10:00 KST, cut to the minute");
        assertEquals("admin:admin-1", now.startedBy());
        assertEquals("scheduled", now.stage());
        verify(audit).recordGraphRoundAction(eq("admin-1"), eq("admin@example.com"), eq("pipeline.round.start"),
                eq("round-20261030T1000"), eq("req-6"), any());

        GraphRoundAdminCommandService later = new GraphRoundAdminCommandService(rounds, beans.getBeanProvider(GraphRoundClock.class),
                idempotency, audit, JsonMapper.builder().build(), Clock.fixed(NOW.plusSeconds(90), ZoneOffset.UTC));
        assertEquals(now, later.start(null, "key-6", ADMIN, "req-6b"), "the same key replays although the minute moved on");

        GraphRoundOut named = service.start(new GraphRoundStartRequest("2026-10-30T02:05:00Z"), "key-7", ADMIN, "req-7");
        assertEquals("round-20261030T1105", named.roundId());
        assertEquals(ErrorCode.REVISION_CONFLICT, assertThrows(CustomException.class,
                () -> service.start(new GraphRoundStartRequest("2026-10-30T02:05:00Z"), "key-8", ADMIN, "req-8")).getErrorCode());
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class,
                () -> service.start(new GraphRoundStartRequest("2026-10-30T02:05:30Z"), "key-9", ADMIN, "req-9")).getErrorCode());
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class,
                () -> service.start(new GraphRoundStartRequest("yesterday"), "key-10", ADMIN, "req-10")).getErrorCode());
    }

    @Test
    void withoutASchedulerBothCommandsAreNotFound() {
        GraphRoundAdminCommandService none = new GraphRoundAdminCommandService(rounds,
                new StaticListableBeanFactory().getBeanProvider(GraphRoundClock.class), idempotency, audit, JsonMapper.builder().build(),
                Clock.fixed(NOW, ZoneOffset.UTC));
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class, () -> none.start(null, "k", ADMIN, "r")).getErrorCode());
        failed("round-20261030T0905", Instant.parse("2026-10-30T00:05:00Z"), GraphRoundStage.SCHEDULED, "run_timeout");
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND,
                assertThrows(CustomException.class, () -> none.retry("round-20261030T0905", "k", ADMIN, "r")).getErrorCode());
    }
}
