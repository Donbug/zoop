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
    void aConceptMixedWithACurrentFactNeverFallsBackToGeneralKnowledgeButItsConceptIsSplitOff() {
        var plan = run(planner.plan(run(0, "v1"), decision(
                req("mixed", Map.of(ChatQueryType.Q02, 0.9, ChatQueryType.Q03, 0.9), Map.of()),
                req("concept", Map.of(ChatQueryType.Q02, 0.9), Map.of())), BOUND));
        assertEquals(List.of("mixed", "mixed-c", "concept"), ids(plan));
        assertEquals(Mode.LIMITED, plan.requirements().get(0).mode());
        assertEquals("out_of_scope", plan.requirements().get(0).limitation(),
                "Q03 needs a lookup; the Q02 part does not make it a general answer");
        var split = plan.requirements().get(1);
        assertEquals(Mode.GENERAL, split.mode());
        assertEquals(ChatPlan.Origin.CONCEPT, split.origin());
        assertEquals("mixed", split.parent());
        assertEquals("요구 mixed — 개념 설명", split.label());
        assertEquals(Set.of(ChatQueryType.Q02), split.types());
        assertTrue(split.capabilities().isEmpty() && split.targets().isEmpty());
        assertEquals(Mode.GENERAL, plan.requirements().get(2).mode());
        assertEquals(ChatPlan.Origin.ROUTER, plan.requirements().get(2).origin(), "a pure concept is not split");

        var alone = planner.plan(run(0, "v1"), decision(
                req("mixed", Map.of(ChatQueryType.Q02, 0.9, ChatQueryType.Q03, 0.9), Map.of())), BOUND);
        assertEquals(List.of("mixed", "mixed-c"), ids(run(alone)),
                "a fact part out of scope no longer turns the whole question into guidance");
    }

    @Test
    void aConceptLabelStaysWithinTheAnswerStagesLabelLimitInCodePointsAndItsParentKeepsItsOwn() {
        int suffix = ChatPlan.Planned.CONCEPT_LABEL.codePointCount(0, ChatPlan.Planned.CONCEPT_LABEL.length());
        assertEquals(8, suffix);
        for (int length : List.of(3992, 3993, 4000)) {
            var parent = planned("가".repeat(length));
            String label = parent.concept().label();
            assertEquals(Math.min(length + suffix, 4000), label.codePointCount(0, label.length()), "length " + length);
            assertTrue(label.endsWith(ChatPlan.Planned.CONCEPT_LABEL));
            assertEquals(length, parent.label().length(), "the parent's label is never cut");
        }
        // Supplementary characters count once each and are never split into a lone surrogate.
        String wide = "𝐀".repeat(4000);
        String label = planned(wide).concept().label();
        assertEquals(4000, label.codePointCount(0, label.length()));
        assertEquals("𝐀".repeat(3992) + ChatPlan.Planned.CONCEPT_LABEL, label);
    }

    private static ChatPlan.Planned planned(String label) {
        return new ChatPlan.Planned("r1", label, Set.of(ChatQueryType.Q02, ChatQueryType.Q03), Mode.TOOLS, null, List.of(),
                List.of(), ChatPlan.TargetSource.QUESTION, null, null, 1);
    }

    @Test
    void aLookupThatAlsoAsksForAConceptRunsAsBeforeWithTheConceptBesideIt() {
        var plan = run(planner.plan(run(0, "v1"), decision(req("r1", Map.of(ChatQueryType.Q02, 0.9, ChatQueryType.Q03, 0.9),
                Map.of("company.read", 0.9), List.of("KRX:000660"))), BOUND));
        assertEquals(List.of("r1", "r1-c"), ids(plan));
        var lookup = plan.requirements().getFirst();
        assertEquals(Mode.TOOLS, lookup.mode());
        assertEquals(List.of(ChatCapability.COMPANY_READ), lookup.capabilities());
        assertEquals(ChatPlan.Origin.ROUTER, lookup.origin());
        assertNull(lookup.parent());
        assertEquals(1, ChatPlanner.worstCaseCalls(plan), "the concept makes no call");
    }

    @Test
    void noConceptIsSplitOffAnInvestmentDecisionOrWhenTheAnswerStageHasNoRoom() {
        var advice = planner.plan(run(0, "v1"), decision(req("r1", Map.of(ChatQueryType.Q02, 0.9, ChatQueryType.Q03, 0.9),
                Map.of("company.read", 0.9), List.of("KRX:000660")).withAdvice(0.5)), BOUND);
        assertEquals(new ChatPlan.Stop("guidance", "investment_advice", List.of()), advice);

        List<Req> six = new java.util.ArrayList<>();
        six.add(req("r0", Map.of(ChatQueryType.Q02, 0.9, ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of("KRX:000660")));
        for (int i = 1; i < 6; i++) six.add(req("r" + i, Map.of(ChatQueryType.Q02, 0.9), Map.of()));
        var full = run(planner.plan(run(0, "v1"), decision(six.toArray(Req[]::new)), BOUND));
        assertEquals(6, full.requirements().size(), "the answer stage takes six branches at most");

        var five = run(planner.plan(run(0, "v1"), decision(six.subList(0, 5).toArray(Req[]::new)), BOUND));
        assertEquals(List.of("r0", "r0-c", "r1", "r2", "r3", "r4"), ids(five));

        String longId = "r".repeat(31);
        var tooLong = run(planner.plan(run(0, "v1"), decision(req(longId, Map.of(ChatQueryType.Q02, 0.9,
                ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9), List.of("KRX:000660"))), BOUND));
        assertEquals(List.of(longId), ids(tooLong), "the split id would pass the 32 characters a requirement id may have");

        var taken = run(planner.plan(run(0, "v1"), decision(
                req("r1", Map.of(ChatQueryType.Q02, 0.9, ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                        List.of("KRX:000660")),
                req("r1-c", Map.of(ChatQueryType.Q02, 0.9), Map.of())), BOUND));
        assertEquals(List.of("r1", "r1-c"), ids(taken));
        assertEquals(ChatPlan.Origin.ROUTER, taken.requirements().get(1).origin(), "a router id is never shadowed");
    }

    @Test
    void evidenceTheMemberNarrowedToBoundsTheContextAndWhatDependsOnIt() {
        var narrowed = run(0, "v1", List.of("iss-selected"), List.of("ev-1"), List.of("ev-1"));
        var plan = run(planner.plan(narrowed, decision(
                req("a", Map.of(ChatQueryType.Q03, 0.9), Map.of("issue.read", 0.9)),
                req("b", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9)).dependingOn(new Dependency("a", "exactly", 2)),
                req("c", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9), List.of("KRX:000660"))), BOUND));
        var a = plan.requirements().get(0);
        assertEquals(ChatPlan.TargetSource.CONTEXT, a.targetSource());
        assertEquals(List.of("ev-1"), a.evidenceScope());
        assertEquals(List.of("ev-1"), plan.requirements().get(1).evidenceScope(), "a dependent stage keeps its source's scope");
        assertEquals(ChatPlan.TargetSource.QUESTION, plan.requirements().get(2).targetSource());
        assertNull(plan.requirements().get(2).evidenceScope(), "a target the question names is not the narrowed selection");

        var evidenceOnly = run(0, "v1", List.of(), List.of("ev-1"), List.of("ev-1"));
        var resolved = run(planner.plan(evidenceOnly, decision(req("r", Map.of(ChatQueryType.Q03, 0.9),
                Map.of("evidence.resolve", 0.9))), BOUND)).requirements().getFirst();
        assertEquals(List.of("ev-1"), resolved.targets());
        assertEquals(List.of("ev-1"), resolved.evidenceScope());

        var notNarrowed = run(planner.plan(run(0, "v1", List.of("iss-selected")), decision(req("r",
                Map.of(ChatQueryType.Q03, 0.9), Map.of("issue.read", 0.9))), BOUND)).requirements().getFirst();
        assertNull(notNarrowed.evidenceScope());
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
    void namedCompaniesGetTheServerDefaultReadsWhateverTheCapabilityProbabilities() {
        Set<String> bound = Set.of("company.read", "issue.read", "evidence.resolve", "graph.path.read");
        var plan = run(planner.plan(run(0, "v1"), decision(
                req("about", Map.of(ChatQueryType.Q03, 0.6), Map.of("issue.read", 0.1), List.of("KRX:005930")),
                req("relation", Map.of(ChatQueryType.Q04, 0.99), Map.of("graph.path.read", 0.3),
                        List.of("KRX:005930", "NASDAQ:ASML")),
                req("issue", Map.of(ChatQueryType.Q03, 0.9), Map.of("issue.read", 0.9), List.of("iss-1"))), bound));
        assertEquals(List.of(ChatCapability.COMPANY_READ), plan.requirements().get(0).capabilities(),
                "a company question reads the company even when no capability reached the review band");
        assertEquals(List.of(ChatCapability.GRAPH_PATH_READ), plan.requirements().get(1).capabilities());
        assertEquals(List.of(ChatCapability.ISSUE_READ), plan.requirements().get(2).capabilities(),
                "an issue target gets no company read");

        var unbound = run(planner.plan(run(0, "v1"), decision(req("about", Map.of(ChatQueryType.Q03, 0.9),
                Map.of("issue.read", 0.9), List.of("KRX:005930"))), Set.of("issue.read")));
        assertEquals(List.of(ChatCapability.ISSUE_READ), unbound.requirements().getFirst().capabilities(),
                "a default runs only when bound");
    }

    @Test
    void aConceptQuestionNamingACompanyIsAlsoACompanyQuestion() {
        var plan = run(planner.plan(run(0, "v1"), decision(req("r", Map.of(ChatQueryType.Q02, 0.72,
                ChatQueryType.Q03, 0.54), Map.of(), List.of("KRX:005930"))), BOUND));
        var r = plan.requirements().getFirst();
        assertEquals(ChatPlan.Mode.TOOLS, r.mode());
        assertEquals(List.of(ChatCapability.COMPANY_READ), r.capabilities());
        assertEquals(List.of("r", "r-c"), ids(plan), "the concept it asked about is still answered");

        var concept = run(planner.plan(run(0, "v1"), decision(req("r", Map.of(ChatQueryType.Q02, 0.9,
                ChatQueryType.Q03, 0.2), Map.of(), List.of("KRX:005930"))), BOUND));
        assertEquals(ChatPlan.Mode.GENERAL, concept.requirements().getFirst().mode(),
                "below the review band it stays a concept");
        assertEquals(List.of("r"), ids(concept));
    }

    @Test
    void gatesLimitWhatTheModelCannotDecide() {
        var plan = run(planner.plan(run(0, "v1"), decision(
                req("advice", Map.of(ChatQueryType.Q02, 0.9), Map.of()).withAdvice(0.2),
                req("path", Map.of(ChatQueryType.Q04, 0.9), Map.of("graph.path.read", 0.95), List.of("KRX:000660")),
                req("free", Map.of(ChatQueryType.Q03, 0.9), Map.of("graph.delete", 0.99), List.of("iss-1")),
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
    void aPathReadIsCountedAndSplitWithItsFirstTargetInEveryCall() {
        List<String> seven = java.util.stream.IntStream.range(0, 7).mapToObj(i -> "KRX:" + i).toList();
        assertEquals(List.of(seven.subList(0, 5), List.of("KRX:0", "KRX:5", "KRX:6")),
                ChatRetrieval.batches(ChatCapability.GRAPH_PATH_READ, seven));
        assertEquals(List.of(seven.subList(0, 5), List.of("KRX:0", "KRX:5")),
                ChatRetrieval.batches(ChatCapability.GRAPH_PATH_READ, seven.subList(0, 6)));
        assertEquals(List.of(List.of("KRX:0")), ChatRetrieval.batches(ChatCapability.GRAPH_PATH_READ, seven.subList(0, 1)));
        assertEquals(List.of(seven.subList(0, 5), seven.subList(5, 7)), ChatRetrieval.batches(ChatCapability.COMPANY_READ, seven));
        for (int n = 1; n <= 16; n++) {
            List<String> targets = java.util.stream.IntStream.range(0, n).mapToObj(i -> "KRX:" + i).toList();
            for (ChatCapability capability : List.of(ChatCapability.GRAPH_PATH_READ, ChatCapability.COMPANY_READ)) {
                assertEquals(ChatRetrieval.batches(capability, targets).size(), ChatPlanner.chunks(capability, n),
                        "the budget counts the calls retrieval makes: " + capability + " × " + n);
            }
        }
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

    @Test
    void aPolicyQuestionReadsTheFixedPoliciesWithoutATargetOrAGraph() {
        Set<String> bound = Set.of("company.read", "zoopPolicy.read");
        var plan = run(planner.plan(run(0, null, List.of("iss-selected")), decision(req("r1",
                Map.of(ChatQueryType.Q01, 0.9), Map.of("zoopPolicy.read", 0.8, "company.read", 0.9))), bound));
        var r1 = plan.requirements().getFirst();
        assertEquals(Mode.TOOLS, r1.mode());
        assertEquals(List.of(ChatCapability.ZOOP_POLICY_READ), r1.capabilities(), "Q01 does not allow company.read");
        assertEquals(ChatPlan.TargetSource.SERVER, r1.targetSource(), "the selection is not what a policy read reads");
        assertTrue(r1.targets().isEmpty());
        assertEquals(1, ChatPlanner.worstCaseCalls(plan), "both policies go in one call");

        var withCompany = run(planner.plan(run(0, null), decision(req("r1", Map.of(ChatQueryType.Q01, 0.9),
                Map.of("zoopPolicy.read", 0.8), List.of("KRX:000660"))), bound)).requirements().getFirst();
        assertEquals(ChatPlan.TargetSource.SERVER, withCompany.targetSource(), "a named company is not a policy");
    }

    @Test
    void aPolicyReadAlongsideAGraphLookupStillNeedsTheGraph() {
        Set<String> bound = Set.of("company.read", "zoopPolicy.read");
        assertStop("guidance", "graph_unavailable", planner.plan(run(0, null), decision(
                req("r1", Map.of(ChatQueryType.Q01, 0.9), Map.of("zoopPolicy.read", 0.8)),
                req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9), List.of("KRX:000660"))), bound));
        // An unbound Q01 tool never runs.
        assertStop("guidance", "out_of_scope", planner.plan(run(0, null), decision(req("r1",
                Map.of(ChatQueryType.Q01, 0.9), Map.of("help.search", 0.9))), bound));
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

    static List<String> ids(ChatPlan.Run plan) {
        return plan.requirements().stream().map(ChatPlan.Planned::id).toList();
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
        return run(depth, graphVersion, contextIds, List.of(), List.of());
    }

    static ChatRun run(int depth, String graphVersion, List<String> contextIds, List<String> evidenceIds,
            List<String> evidencePool) {
        return new ChatRun("job-1", "conv-1", "member-a", 1, "run", List.of(new ChatRun.Turn("job-1", "질문", null, null)),
                new ChatFrozenContext(List.of(), 0, null, null, graphVersion),
                new FrozenSelection(contextIds, evidenceIds, evidencePool), graphVersion, depth, Instant.EPOCH,
                Instant.EPOCH.plusSeconds(60));
    }
}
