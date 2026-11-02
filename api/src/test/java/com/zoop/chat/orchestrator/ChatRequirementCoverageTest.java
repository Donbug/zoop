package com.zoop.chat.orchestrator;

import static com.zoop.chat.orchestrator.ChatPlannerTest.req;
import static org.junit.jupiter.api.Assertions.*;

import com.zoop.chat.orchestrator.ChatRequirementCoverage.Status;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

/** D-AI-02: the server's record of where each requirement ended. */
class ChatRequirementCoverageTest {
    private static ChatRequirementCoverage stated(String... ids) {
        return new ChatRequirementCoverage(ChatPlannerTest.decision(java.util.Arrays.stream(ids)
                .map(id -> req(id, Map.of(ChatQueryType.Q03, 0.9), Map.of())).toArray(ChatPlannerTest.Req[]::new)));
    }

    @Test
    void aStatedRequirementNoStepDecidedLeavesTheRunUnsettled() {
        var coverage = stated("r1", "r2");
        assertFalse(coverage.settled());

        coverage.answered("r1");
        assertFalse(coverage.settled(), "r2 is on no section, limitation or question");

        coverage.limited("r2", "nothing_found");
        assertTrue(coverage.settled());
        assertEquals(List.of(Status.ANSWERED, Status.LIMITED), coverage.entries().stream().map(e -> e.status()).toList());
        assertEquals("nothing_found", coverage.entries().get(1).reason());
    }

    @Test
    void aStopEndsOnlyWhatIsStillPending() {
        var asked = stated("r1", "r2");
        asked.limited("r1", "investment_advice");
        asked.stopped(new ChatPlan.Stop("clarification", "ambiguous_target", List.of()));
        assertEquals(List.of(Status.LIMITED, Status.CLARIFY), asked.entries().stream().map(e -> e.status()).toList());
        assertEquals(List.of("investment_advice", "ambiguous_target"), asked.entries().stream().map(e -> e.reason()).toList());

        var guided = stated("r1");
        guided.stopped(new ChatPlan.Stop("guidance", "out_of_scope", List.of()));
        assertEquals(Status.LIMITED, guided.entries().getFirst().status());
        assertTrue(guided.settled());
    }

    @Test
    void anIdOutsideTheRecordAddsNothing() {
        var coverage = stated("r1");
        coverage.answered("r9");
        coverage.limited("r9", "out_of_scope");

        assertEquals(List.of("r1"), coverage.entries().stream().map(e -> e.requirementId()).toList());
        assertFalse(coverage.settled());
    }

    @Test
    void theRouteRecordCarriesIdsAndCodesOnly() {
        var coverage = stated("r1");
        coverage.limited("r1", "evidence_held");

        assertEquals("[{\"requirementId\":\"r1\",\"explicit\":true,\"status\":\"limited\",\"toolCallIds\":[],"
                + "\"reason\":\"evidence_held\"}]", coverage.json().toString());
    }
}
