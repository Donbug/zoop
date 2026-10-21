package com.zoop.chat.orchestrator;

import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.orchestrator.ChatPlan.Mode;
import com.zoop.chat.orchestrator.ChatRouteDecision.Dependency;
import com.zoop.chat.orchestrator.ChatRouteDecision.Requirement;
import com.zoop.chat.service.FrozenSelection;
import com.zoop.chat.tool.ChatCapability;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/** D-AI-01b planning: what the server allows to run, decided before any tool call. */
class ChatPlannerTest {
    static final Set<String> BOUND = Set.of("company.read", "issue.read", "evidence.resolve");
    private final ChatPlanner planner = new ChatPlanner();

    @Test
    void aGeneralConceptNeedsNoToolAndAModelCannotAttachOneToIt() {
        var plan = run(planner.plan(run(0, "v1"), decision(req("r1", Map.of(ChatQueryType.Q02, 0.95),
                Map.of("company.read", 0.9))), BOUND));
        var r1 = plan.requirements().getFirst();
        assertEquals(Mode.GENERAL, r1.mode(), "Q02 allows no capability, so company.read is not taken");
        assertTrue(r1.capabilities().isEmpty());
    }

    @Test
    void thresholdsTakeHighCandidatesAndTheReviewBandOnlyForAnExplicitRequirement() {
        var plan = run(planner.plan(run(0, "v1"), decision(
                req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.8, "issue.read", 0.5,
                        "evidence.resolve", 0.72), List.of("KRX:000660")),
                req("r2", Map.of(ChatQueryType.Q03, 0.5), Map.of("issue.read", 0.4, "company.read", 0.3),
                        List.of("iss-1")),
                inferred("r3", Map.of(ChatQueryType.Q03, 0.6)), inferred("r4", Map.of(ChatQueryType.Q02, 0.8))), BOUND));
        assertEquals(List.of("r1", "r2", "r4"), plan.requirements().stream().map(ChatPlan.Planned::id).toList(),
                "an unstated requirement below 0.70 is dropped");
        assertEquals(List.of(ChatCapability.COMPANY_READ, ChatCapability.EVIDENCE_RESOLVE),
                plan.requirements().get(0).capabilities());
        assertEquals(List.of(ChatCapability.ISSUE_READ), plan.requirements().get(1).capabilities(),
                "an explicit requirement with no candidate at 0.70 takes its best at 0.35");
    }

    @Test
    void gatesLimitWhatTheModelCannotDecide() {
        var plan = run(planner.plan(run(0, "v1"), decision(
                req("advice", Map.of(ChatQueryType.Q02, 0.9), Map.of()).withAdvice(0.2),
                req("path", Map.of(ChatQueryType.Q04, 0.9), Map.of("graph.path.read", 0.95), List.of("KRX:000660")),
                req("free", Map.of(ChatQueryType.Q03, 0.9), Map.of("graph.delete", 0.99), List.of("KRX:000660")),
                req("concept", Map.of(ChatQueryType.Q02, 0.9), Map.of())), BOUND));
        assertEquals(Arrays.asList("investment_advice", "out_of_scope", "out_of_scope", null),
                plan.requirements().stream().map(ChatPlan.Planned::limitation).toList(),
                "an uncertain advice probability is advice; an unbound or unknown capability never runs");
    }

    @Test
    void targetsNamedInTheQuestionWinOverTheSelectionAndALookupWithoutAnyIsAmbiguous() {
        var selected = run(0, "v1", List.of("iss-selected"));
        var named = run(planner.plan(selected, decision(req("r1", Map.of(ChatQueryType.Q03, 0.9),
                Map.of("company.read", 0.9), List.of("KRX:000660"))), BOUND));
        assertEquals(List.of("KRX:000660"), named.requirements().getFirst().targets());
        var fromContext = run(planner.plan(selected, decision(req("r1", Map.of(ChatQueryType.Q03, 0.9),
                Map.of("issue.read", 0.9))), BOUND));
        assertEquals(List.of("iss-selected"), fromContext.requirements().getFirst().targets());

        assertStop("clarification", "ambiguous_target", planner.plan(run(0, "v1"), decision(req("r1",
                Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9))), BOUND));
    }

    @Test
    void tooManyRequirementsAnAmbiguityOrAnOverBudgetPlanStopBeforeAnyCall() {
        Req[] seven = new Req[7];
        for (int i = 0; i < 7; i++) seven[i] = req("r" + i, Map.of(ChatQueryType.Q02, 0.9), Map.of());
        assertStop("clarification", "too_many_requirements", planner.plan(run(0, "v1"), decision(seven), BOUND));

        var ambiguous = new ChatRouteDecision(List.of(), new ChatRouteDecision.Ambiguity("company",
                List.of(new ChatRouteDecision.Option("c-1", "삼성전자"), new ChatRouteDecision.Option("c-2", "삼성SDI"))));
        var stop = (ChatPlan.Stop) planner.plan(run(0, "v1"), ambiguous, BOUND);
        assertEquals("clarification", stop.outcome());
        assertEquals(List.of("c-1", "c-2"), stop.choices().stream().map(c -> c.id()).toList());
        assertEquals("company", stop.choices().getFirst().kind());

        // 3 capabilities × 4 chunks of five targets = 12, plus a dependent stage at atLeast (5 targets) × 3 = 15 > 12.
        List<String> sixteen = java.util.stream.IntStream.range(0, 16).mapToObj(i -> "KRX:" + i).toList();
        assertStop("clarification", "plan_over_budget", planner.plan(run(0, "v1"), decision(
                req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9, "issue.read", 0.9,
                        "evidence.resolve", 0.9), sixteen),
                req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9, "issue.read", 0.9,
                        "evidence.resolve", 0.9)).dependingOn(new Dependency("r1", "atLeast", 1))), BOUND));
    }

    @Test
    void stagesFollowDependenciesUpToThree() {
        var three = run(planner.plan(run(0, "v1"), decision(
                req("a", Map.of(ChatQueryType.Q03, 0.9), Map.of("issue.read", 0.9), List.of("iss-1")),
                req("b", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9)).dependingOn(new Dependency("a", "atMost", 2)),
                req("c", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9)).dependingOn(new Dependency("b", "exactly", 1))),
                BOUND));
        assertEquals(List.of(1, 2, 3), three.requirements().stream().map(ChatPlan.Planned::stage).toList());
        assertEquals(3, ChatPlanner.worstCaseCalls(three), "one call per stage: two targets fit one call");

        assertStop("clarification", "plan_over_budget", planner.plan(run(0, "v1"), decision(
                req("a", Map.of(ChatQueryType.Q03, 0.9), Map.of("issue.read", 0.9), List.of("iss-1")),
                req("b", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9)).dependingOn(new Dependency("a", "atMost", 2)),
                req("c", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9)).dependingOn(new Dependency("b", "exactly", 1)),
                req("d", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9)).dependingOn(new Dependency("c", "exactly", 1))),
                BOUND));
    }

    @Test
    void aRequirementOnALimitedSourceCannotRun() {
        var plan = run(planner.plan(run(0, "v1"), decision(
                req("a", Map.of(ChatQueryType.Q06, 0.9), Map.of("briefing.read", 0.9), List.of("round-1")),
                req("b", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9)).dependingOn(new Dependency("a", "exactly", 2)),
                req("c", Map.of(ChatQueryType.Q02, 0.9), Map.of())), BOUND));
        assertEquals(Arrays.asList("out_of_scope", "precondition_unmet", null),
                plan.requirements().stream().map(ChatPlan.Planned::limitation).toList());
    }

    @Test
    void atDepthTwoEveryClarificationIsGuidanceAndAllLimitedIsGuidance() {
        assertStop("guidance", "clarification_limit", planner.plan(run(2, "v1"), decision(req("r1",
                Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9))), BOUND));
        assertStop("guidance", "investment_advice", planner.plan(run(0, "v1"), decision(
                req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of()).withAdvice(0.95)), BOUND));
        assertStop("guidance", "graph_unavailable", planner.plan(run(0, null), decision(req("r1",
                Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9), List.of("KRX:000660"))), BOUND));
    }

    @Test
    void aMalformedDecisionIsARerunnableProviderError() {
        for (var bad : List.of(decision(req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of()),
                        req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of())),
                decision(req("r1", Map.of(ChatQueryType.Q02, 1.5), Map.of())),
                decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of()).dependingOn(new Dependency("r2", "exactly", 1)),
                        req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of())),
                decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of()),
                        req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of()).dependingOn(new Dependency("r1", "exactly", 6))),
                decision())) {
            var failure = assertThrows(ChatModels.Failure.class, () -> planner.plan(run(0, "v1"), bad, BOUND));
            assertEquals(ChatModels.Failure.Fate.NOT_SENT, failure.fate());
        }
    }

    // ---- fixtures -------------------------------------------------------------------------------------------------------

    static ChatPlan.Run run(ChatPlan plan) {
        return assertInstanceOf(ChatPlan.Run.class, plan, plan.toString());
    }

    static void assertStop(String outcome, String reason, ChatPlan plan) {
        var stop = assertInstanceOf(ChatPlan.Stop.class, plan, plan.toString());
        assertEquals(outcome, stop.outcome());
        assertEquals(reason, stop.reason());
    }

    static Req req(String id, Map<ChatQueryType, Double> types, Map<String, Double> capabilities) {
        return req(id, types, capabilities, List.of());
    }

    static Req req(String id, Map<ChatQueryType, Double> types, Map<String, Double> capabilities, List<String> targets) {
        return new Req(new Requirement(id, "요구 " + id, true, types, capabilities, targets, 0.0, null));
    }

    static Requirement inferred(String id, Map<ChatQueryType, Double> types) {
        return new Requirement(id, "추론 " + id, false, types, Map.of(), List.of(), 0.0, null);
    }

    /** A requirement under construction; it converts to the record wherever one is expected. */
    record Req(Requirement value) {
        Req withAdvice(double p) {
            var r = value;
            return new Req(new Requirement(r.id(), r.label(), r.explicit(), r.types(), r.capabilities(), r.targets(), p,
                    r.dependsOn()));
        }

        Req dependingOn(Dependency dependency) {
            var r = value;
            return new Req(new Requirement(r.id(), r.label(), r.explicit(), r.types(), r.capabilities(), r.targets(),
                    r.prohibitedAdvice(), dependency));
        }
    }

    static ChatRouteDecision decision(Req... requirements) {
        return new ChatRouteDecision(java.util.Arrays.stream(requirements).map(Req::value).toList(), null);
    }

    static ChatRouteDecision decision(Object... mixed) {
        return new ChatRouteDecision(java.util.Arrays.stream(mixed)
                .map(o -> o instanceof Req r ? r.value() : (Requirement) o).toList(), null);
    }

    static ChatRun run(int depth, String graphVersion) {
        return run(depth, graphVersion, List.of());
    }

    static ChatRun run(int depth, String graphVersion, List<String> contextIds) {
        return new ChatRun("job-1", "conv-1", "member-a", 1, "run", List.of(new ChatRun.Turn("job-1", "질문", null, null)),
                new ChatFrozenContext(List.of(), 0, null, null, graphVersion),
                new FrozenSelection(contextIds, List.of(), List.of()), graphVersion, depth, Instant.EPOCH,
                Instant.EPOCH.plusSeconds(60));
    }
}
