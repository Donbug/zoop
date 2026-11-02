package com.zoop.admin.pipeline;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundDetail;
import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundList;
import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundsSection;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.round.GraphRoundEvent.Outcome;
import com.zoop.graph.round.GraphRound;
import com.zoop.graph.round.GraphRoundPatch;
import com.zoop.graph.round.GraphRoundStage;
import com.zoop.graph.round.GraphRoundStatus;
import com.zoop.graph.round.InMemoryGraphRoundRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/** The admin read of rounds: newest first, filtered and paged by slot, the detail with its timeline, the overview section. */
class GraphRoundAdminServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-30T01:00:00Z");
    private static final String DIGEST = "b".repeat(64);
    private InMemoryGraphRoundRepository rounds;
    private GraphRoundAdminService service;
    private final StaticListableBeanFactory beans = new StaticListableBeanFactory();

    @BeforeEach
    void setUp() {
        rounds = new InMemoryGraphRoundRepository();
        ObjectProvider<GraphRoundStatus> status = beans.getBeanProvider(GraphRoundStatus.class);
        service = new GraphRoundAdminService(rounds, status);
        for (int i = 0; i < 5; i++) {
            Instant slot = Instant.parse("2026-10-30T00:05:00Z").plusSeconds(1800L * i);
            rounds.create("round-20261030T" + String.format("%02d%02d", 9 + (i * 30 + 5) / 60, (i * 30 + 5) % 60), slot,
                    "system:scheduler", slot);
        }
    }

    private GraphRound claimed(String roundId) {
        return rounds.claim(roundId, "task-a", java.time.Duration.ofMinutes(2), NOW).orElseThrow();
    }

    @Test
    void theListIsNewestFirstFilteredByStageAndPagedByAnOpaqueSlotCursor() {
        rounds.advance(claimed("round-20261030T0935"), GraphRoundPatch.advanceTo(GraphRoundStage.IMPORTED).graphVersion("gv-1"),
                Outcome.ADVANCED, "staged", null, null, NOW);

        GraphRoundList first = service.list(null, null, 2);
        assertEquals(List.of("round-20261030T1105", "round-20261030T1035"),
                first.items().stream().map(r -> r.roundId()).toList());
        assertNotNull(first.nextCursor());
        GraphRoundList second = service.list(null, first.nextCursor(), 2);
        assertEquals(List.of("round-20261030T1005", "round-20261030T0935"),
                second.items().stream().map(r -> r.roundId()).toList());
        GraphRoundList last = service.list(null, second.nextCursor(), 2);
        assertEquals(List.of("round-20261030T0905"), last.items().stream().map(r -> r.roundId()).toList());
        assertNull(last.nextCursor());

        GraphRoundList imported = service.list("imported", null, null);
        assertEquals(1, imported.items().size());
        assertEquals("gv-1", imported.items().get(0).graphVersionId());
        assertEquals("imported", imported.items().get(0).stage());
        assertNull(imported.items().get(0).handoff(), "no handoff recorded, no object");

        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class, () -> service.list("done", null, null)).getErrorCode());
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class, () -> service.list(null, null, 0)).getErrorCode());
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class, () -> service.list(null, null, 101)).getErrorCode());
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class, () -> service.list(null, "bad", null)).getErrorCode());
    }

    @Test
    void theDetailCarriesTheRowAndItsTimelineAndAnUnknownRoundIsNotFound() {
        ObjectNode detail = new ObjectMapper().createObjectNode();
        detail.put("planDigest", DIGEST);
        GraphRound planned = rounds.advance(claimed("round-20261030T0905"),
                GraphRoundPatch.advanceTo(GraphRoundStage.PLAN_READY).plan("plan-1", DIGEST), Outcome.ADVANCED, null, "req-1",
                detail, NOW).orElseThrow();
        rounds.advance(planned, GraphRoundPatch.fail("plan_rejected:binding"), Outcome.FAILED, "plan_rejected:binding", "req-2",
                null, NOW.plusSeconds(1));

        GraphRoundDetail got = service.get("round-20261030T0905");

        assertEquals("failed", got.round().stage());
        assertEquals("plan_rejected:binding", got.round().failureCode());
        assertEquals("plan-1", got.round().plan().planId());
        assertEquals(2, got.events().size());
        assertEquals("req-1", got.events().get(0).requestId());
        assertEquals(DIGEST, got.events().get(0).detail().get("planDigest").stringValue());
        assertEquals("failed", got.events().get(1).outcome());
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND,
                assertThrows(CustomException.class, () -> service.get("round-20261031T0905")).getErrorCode());
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND,
                assertThrows(CustomException.class, () -> service.get("../etc")).getErrorCode());
    }

    @Test
    void theOverviewSectionSaysDisabledWithoutASchedulerAndCountsOpenRounds() {
        rounds.advance(claimed("round-20261030T0935"), GraphRoundPatch.advanceTo(GraphRoundStage.SKIPPED), Outcome.SKIPPED,
                "no_new_material", null, null, NOW);

        GraphRoundsSection section = service.section();

        assertFalse(section.enabled());
        assertNull(section.nextSlotAt());
        assertEquals(4, section.openRounds());
        assertEquals(5, section.recent().size());
        assertEquals("round-20261030T1105", section.recent().get(0).roundId());

        beans.addBean("status", new GraphRoundStatus() {
            @Override
            public boolean enabled() {
                return true;
            }

            @Override
            public Optional<Instant> nextSlotAt() {
                return Optional.of(NOW.plusSeconds(300));
            }

            @Override
            public Optional<Instant> lastTickAt() {
                return Optional.of(NOW);
            }
        });
        GraphRoundsSection live = service.section();
        assertTrue(live.enabled());
        assertEquals(NOW.plusSeconds(300).toString(), live.nextSlotAt());
        assertEquals(NOW.toString(), live.lastTickAt());
    }
}
