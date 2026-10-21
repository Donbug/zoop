package com.zoop.chat.orchestrator;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.BiFunction;

import com.zoop.chat.dto.ChatResult;
import com.zoop.chat.dto.Citation;
import com.zoop.chat.dto.GraphTarget;
import com.zoop.chat.executor.ChatEngineOutcome;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.executor.ChatRunControl;
import com.zoop.chat.executor.ChatToolCallReservation;
import com.zoop.chat.orchestrator.ChatGeneratedAnswer.Section;
import com.zoop.chat.orchestrator.ChatPlannerTest.Req;
import com.zoop.chat.orchestrator.ChatRouteDecision.Dependency;
import com.zoop.chat.orchestrator.ChatSemanticVerdicts.Verdict;
import com.zoop.chat.repository.ChatToolCallEnd;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatTool;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolOutput;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolRequest;
import com.zoop.chat.tool.ChatToolRunner;
import com.zoop.chat.tool.ChatToolScope;
import com.zoop.chat.tool.ChatToolUnavailable;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import static com.zoop.chat.orchestrator.ChatPlannerTest.req;
import static org.junit.jupiter.api.Assertions.*;

/**
 * D-AI-02 orchestration with scripted models (no model, no network) and scripted read tools: the server decides limitations,
 * citations, answer basis and outcome; checks fail closed; deadlines and failures are classified as ZOOP-AIG-001 6.3.3 says.
 */
class OrchestratedChatEngineTest {
    private static final Instant NOW = Instant.parse("2026-10-21T03:00:00Z");
    private static final String HYNIX = "KRX:000660";
    private static final String NVDA = "NASDAQ:NVDA";
    private static final String AMD = "NASDAQ:AMD";
    private static final Map<String, String> LABELS = Map.of(HYNIX, "SK하이닉스", NVDA, "NVIDIA", AMD, "AMD");

    private final List<ChatToolRunner> runners = new ArrayList<>();
    private final List<ChatBranchContext> generated = new ArrayList<>();
    private final Map<ChatCapability, BiFunction<ChatToolScope, ChatToolRequest, ChatToolOutput>> tools = new HashMap<>();
    private final Map<String, Citation> readable = new HashMap<>();
    private List<String> issueCompanies = List.of(HYNIX, NVDA);
    private ChatRouteDecision decision;
    private ChatGeneratedAnswer answer;
    private ChatSemanticVerdicts verdicts;
    private RuntimeException routerFailure;
    private RuntimeException generatorFailure;
    private int verifierCalls;

    OrchestratedChatEngineTest() {
        tools.put(ChatCapability.COMPANY_READ, (scope, request) -> {
            List<ChatToolItem> items = request.targets().stream().filter(LABELS::containsKey)
                    .map(id -> new ChatToolItem(id, "company", LABELS.get(id), List.of(id), List.of(evidence(id)))).toList();
            return new ChatToolOutput(scope.graphVersionId(), items,
                    items.stream().flatMap(i -> i.evidenceIds().stream()).toList(), false, false);
        });
        tools.put(ChatCapability.ISSUE_READ, (scope, request) -> {
            List<ChatToolItem> items = issueCompanies.isEmpty() ? List.of()
                    : List.of(new ChatToolItem("iss-1", "issue", "HBM 공급", issueCompanies, List.of("ev-issue")));
            return new ChatToolOutput(scope.graphVersionId(), items, items.isEmpty() ? List.of() : List.of("ev-issue"),
                    false, false);
        });
        for (String id : List.of(HYNIX, NVDA, AMD, "issue")) {
            String evidence = id.equals("issue") ? "ev-issue" : evidence(id);
            readable.put(evidence, new Citation("article", evidence, "인용 " + id, "art-" + id, "v1", null, null, 0, 4,
                    "기사 " + id, "언론사", NOW, "https://example.invalid/" + id));
        }
    }

    @AfterEach
    void tearDown() {
        runners.forEach(ChatToolRunner::close);
    }

    @Test
    void aGeneralConceptIsOneGeneralSectionWithTheServerNoticeAndNoSources() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.95), Map.of()));
        answer = new ChatGeneratedAnswer(List.of(general("HBM은 고대역폭 메모리입니다.", "r1")), List.of(), List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "no")));
        var control = new Control(Duration.ofSeconds(60));

        ChatResult result = completed(engine().answer(run(), control));
        assertEquals("answered", result.outcome());
        assertEquals("general_knowledge", result.answerBasis());
        assertEquals(ChatAnswerCheck.GENERAL_NOTICE + " HBM은 고대역폭 메모리입니다.", result.answer());
        assertTrue(result.sources().isEmpty() && result.citations().isEmpty() && result.limitations().isEmpty());
        assertEquals(3, control.modelCalls, "router, generator and verifier, each announced");
        assertEquals(List.of("writing", "verifying"), control.phases);
        assertTrue(control.reserved.isEmpty());
    }

    @Test
    void aMixedAnswerGetsServerCitationsSourcesTargetsAndAppliedScope() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of()),
                req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9), List.of(HYNIX)));
        answer = new ChatGeneratedAnswer(List.of(general("HBM은 메모리입니다.", "r1"),
                grounded("SK하이닉스는 HBM을 공급합니다.", List.of("r2"), evidence(HYNIX))), List.of(), List.of(HYNIX));
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "no"), new Verdict("supported", "no")));
        var control = new Control(Duration.ofSeconds(60));

        var outcome = assertInstanceOf(ChatEngineOutcome.Completed.class, engine().answer(run(), control));
        ChatResult result = outcome.result();
        assertEquals("mixed", result.answerBasis());
        assertEquals(List.of(readable.get(evidence(HYNIX))), result.citations(), "the citation is the evidence record's own");
        assertEquals(List.of("art-" + HYNIX), result.sources());
        assertEquals(List.of(new GraphTarget(HYNIX, "company")), result.graphTargets());
        assertEquals(List.of(HYNIX), result.applied().companies().stream().map(c -> c.id()).toList());
        assertEquals("v1", result.applied().graphVersion());
        assertEquals(List.of("retrieving", "writing", "verifying"), control.phases);
        assertEquals(List.of(evidence(HYNIX)), generated.getFirst().branches().get(1).results().getFirst().evidenceIds());
        assertEquals("tools", outcome.routeSummary().path("requirements").get(1).path("mode").asString());
    }

    @Test
    void anInvestmentDecisionIsALimitationOrGuidanceButNeverGenerated() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of()),
                req("r2", Map.of(ChatQueryType.Q02, 0.9), Map.of()).withAdvice(0.97));
        answer = new ChatGeneratedAnswer(List.of(general("HBM은 메모리입니다.", "r1")), List.of(), List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "no")));
        ChatResult result = completed(engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertEquals(List.of("investment_advice"), result.limitations().stream().map(l -> l.kind()).toList());
        assertEquals("요구 r2", result.limitations().getFirst().label());
        assertEquals(List.of("r1"), generated.getFirst().branches().stream().map(b -> b.requirementId()).toList());

        generated.clear();
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of()).withAdvice(0.97));
        var control = new Control(Duration.ofSeconds(60));
        ChatResult guidance = completed(engine().answer(run(), control));
        assertEquals("guidance", guidance.outcome());
        assertEquals(ChatResults.reason("investment_advice"), guidance.reason());
        assertEquals(1, control.modelCalls);
        assertTrue(generated.isEmpty());
    }

    @Test
    void moreCompaniesThanTheCheckpointAllowsAskWhichOnesBeforeTheNextStage() {
        issueCompanies = List.of(HYNIX, NVDA, AMD);
        decision = dependent("exactly", 2);
        var control = new Control(Duration.ofSeconds(60));

        ChatResult result = completed(engine().answer(run(), control));
        assertEquals("clarification", result.outcome());
        // An issue lists its companies by id only, so the labels are ids until the read carries company names.
        assertEquals(List.of(HYNIX + " · " + NVDA, HYNIX + " · " + AMD, NVDA + " · " + AMD),
                result.choices().stream().map(c -> c.label()).toList());
        assertTrue(result.choices().stream().allMatch(c -> "scope".equals(c.kind())));
        assertEquals(1, control.reserved.size(), "the dependent stage never ran");
        assertTrue(generated.isEmpty());
        assertEquals(1, control.modelCalls);
    }

    @Test
    void fewerCompaniesThanTheCheckpointNeedsLimitTheDependentRequirementOnly() {
        issueCompanies = List.of(HYNIX);
        decision = dependent("exactly", 2);
        answer = new ChatGeneratedAnswer(List.of(grounded("HBM 공급 사건이 있습니다.", List.of("r1"), "ev-issue")),
                List.of(), List.of("iss-1"));
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict("supported", "no")));

        ChatResult result = completed(engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertEquals("answered", result.outcome());
        assertEquals(List.of("precondition_unmet"), result.limitations().stream().map(l -> l.kind()).toList());
        assertEquals(List.of(new GraphTarget("iss-1", "issue")), result.graphTargets());
    }

    @Test
    void aMetCheckpointRunsTheNextStageOnWhatWasFound() {
        decision = dependent("exactly", 2);
        answer = new ChatGeneratedAnswer(List.of(grounded("사건", List.of("r1"), "ev-issue"),
                grounded("두 회사", List.of("r2"), evidence(HYNIX), evidence(NVDA))), List.of(), List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict("supported", "no"), new Verdict("supported", "no")));
        var control = new Control(Duration.ofSeconds(60));

        ChatResult result = completed(engine().answer(run(), control));
        assertEquals("answered", result.outcome());
        assertEquals(2, control.reserved.size());
        assertEquals("company.read", control.reserved.get(1).capabilityId());
        assertEquals(3, result.citations().size());
    }

    @Test
    void aLookupThatFoundNothingMaySaySoWithoutEvidence() {
        issueCompanies = List.of();
        decision = dependent("exactly", 2);
        answer = new ChatGeneratedAnswer(List.of(grounded("조회 범위에서 해당 사건은 없습니다.", List.of("r1"))), List.of(),
                List.of());
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict("supported", "no")));
        ChatResult result = completed(engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertEquals("answered", result.outcome());
        assertTrue(generated.getFirst().branches().getFirst().noneFound());
        assertEquals(List.of("precondition_unmet"), result.limitations().stream().map(l -> l.kind()).toList());
    }

    @Test
    void aToolFailureEndsTheRunAndIsNeverALimitation() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(HYNIX)));
        tools.put(ChatCapability.COMPANY_READ, (scope, request) -> { throw new ChatToolUnavailable("snapshot"); });
        assertFailed("transient", null, true, engine().answer(run(), new Control(Duration.ofSeconds(60))));
        tools.put(ChatCapability.COMPANY_READ, (scope, request) -> { throw new IllegalStateException("bug"); });
        assertFailed("internal", null, false, engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertTrue(generated.isEmpty());
    }

    @Test
    void aFailedDeterministicCheckIsValidationFailedAndTheVerifierIsNeverCalled() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of()),
                req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9), List.of(HYNIX)));
        verdicts = new ChatSemanticVerdicts(List.of());
        List<ChatGeneratedAnswer> bad = List.of(
                // evidence the tool never passed on
                new ChatGeneratedAnswer(List.of(general("개념", "r1"), grounded("사실", List.of("r2"), "ev-other")),
                        List.of(), List.of()),
                // r2 is neither answered nor declared insufficient
                new ChatGeneratedAnswer(List.of(general("개념", "r1")), List.of(), List.of()),
                // a general section citing evidence
                new ChatGeneratedAnswer(List.of(new Section("general_knowledge", "개념", List.of("r1"), List.of(evidence(HYNIX))),
                        grounded("사실", List.of("r2"), evidence(HYNIX))), List.of(), List.of()),
                // an evidence section without evidence while something was found
                new ChatGeneratedAnswer(List.of(general("개념", "r1"), grounded("사실", List.of("r2"))), List.of(), List.of()),
                // recommendation wording
                new ChatGeneratedAnswer(List.of(general("지금 SK하이닉스를 매수하세요.", "r1"),
                        grounded("사실", List.of("r2"), evidence(HYNIX))), List.of(), List.of()),
                // a map target no tool returned
                new ChatGeneratedAnswer(List.of(general("개념", "r1"), grounded("사실", List.of("r2"), evidence(HYNIX))),
                        List.of(), List.of(NVDA)),
                // answered and declared insufficient at once
                new ChatGeneratedAnswer(List.of(general("개념", "r1"), grounded("사실", List.of("r2"), evidence(HYNIX))),
                        List.of("r2"), List.of()));
        for (var candidate : bad) {
            answer = candidate;
            assertFailed("validation_failed", null, false, engine().answer(run(), new Control(Duration.ofSeconds(60))));
        }
        assertEquals(0, verifierCalls);
    }

    @Test
    void evidenceThatIsNoLongerReadableCannotBeCited() {
        decision = ChatPlannerTest.decision(req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(HYNIX)));
        answer = new ChatGeneratedAnswer(List.of(grounded("사실", List.of("r2"), evidence(HYNIX))), List.of(), List.of());
        readable.remove(evidence(HYNIX));
        assertFailed("validation_failed", null, false, engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertEquals(0, verifierCalls);
    }

    @Test
    void verdictsBlockContradictionsAndDropHeldRequirements() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of()),
                req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9), List.of(HYNIX)),
                req("r3", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9), List.of(NVDA)));
        answer = new ChatGeneratedAnswer(List.of(general("개념", "r1"), grounded("하이닉스", List.of("r2"), evidence(HYNIX)),
                grounded("엔비디아", List.of("r3"), evidence(NVDA)),
                grounded("둘을 잇는 문장", List.of("r2", "r3"), evidence(HYNIX), evidence(NVDA))), List.of(),
                List.of(HYNIX, NVDA));
        var supported = new Verdict("supported", "no");

        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "no"), new Verdict("contradicted", "no"), supported,
                supported));
        assertFailed("validation_failed", null, false, engine().answer(run(), new Control(Duration.ofSeconds(60))));
        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "yes"), supported, supported, supported));
        assertFailed("validation_failed", null, false, engine().answer(run(), new Control(Duration.ofSeconds(60))));

        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "no"), new Verdict("hold", "no"), supported,
                supported));
        ChatResult held = completed(engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertEquals("answered", held.outcome());
        assertEquals(List.of("개념", "엔비디아"), held.sections().stream()
                .map(s -> s.text().replace(ChatAnswerCheck.GENERAL_NOTICE + " ", "")).toList(),
                "r2 and the section joining it are gone; r3 keeps its own section");
        assertEquals("mixed", held.answerBasis());
        assertEquals(List.of(new GraphTarget(NVDA, "company")), held.graphTargets(),
                "a target only the dropped requirement returned is gone");
        assertEquals(List.of(evidence(NVDA)), held.citations().stream().map(Citation::evidenceId).toList());
        assertEquals(List.of("evidence_insufficient"), held.limitations().stream().map(l -> l.kind()).toList());
        assertEquals("요구 r2", held.limitations().getFirst().label());

        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "hold"), new Verdict("hold", "no"),
                new Verdict("hold", "no"), supported));
        ChatResult none = completed(engine().answer(run(), new Control(Duration.ofSeconds(60))));
        assertEquals("insufficient_evidence", none.outcome());
        assertEquals("none", none.answerBasis());

        verdicts = new ChatSemanticVerdicts(List.of(new Verdict(null, "no")));
        assertFailed("transient", "provider_error", true, engine().answer(run(), new Control(Duration.ofSeconds(60))));
    }

    @Test
    void aModelStageStartsOnlyWhenTheTimeLeftCoversItAndEverythingAfterIt() {
        decision = ChatPlannerTest.decision(req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(HYNIX)));
        var tooLate = new Control(Duration.ofSeconds(37));
        assertFailed("transient", "deadline_guard", true, engine().answer(run(), tooLate));
        assertEquals(0, tooLate.modelCalls);

        // Enough for router + generation + verification + server (38 s), not for tools + generation + verification + server (44 s).
        var noTools = new Control(Duration.ofSeconds(40));
        assertFailed("transient", "deadline_guard", true, engine().answer(run(), noTools));
        assertEquals(1, noTools.modelCalls);
        assertTrue(noTools.reserved.isEmpty());
    }

    @Test
    void modelFailuresAreRerunOnlyWhenNothingMayHaveBeenProcessed() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.9), Map.of()));
        routerFailure = new ChatModels.Failure(ChatModels.Failure.Fate.UNKNOWN, "timed out after sending");
        assertFailed("transient", "response_unknown", false, engine().answer(run(), new Control(Duration.ofSeconds(60))));

        routerFailure = null;
        generatorFailure = new ChatModels.Failure(ChatModels.Failure.Fate.NOT_SENT, "connection refused");
        assertFailed("transient", "provider_error", true, engine().answer(run(), new Control(Duration.ofSeconds(60))));
    }

    // ---- fixtures -------------------------------------------------------------------------------------------------------

    private ChatRouteDecision dependent(String cardinality, int count) {
        return ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("issue.read", 0.9), List.of("iss-1")),
                req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9))
                        .dependingOn(new Dependency("r1", cardinality, count)));
    }

    private OrchestratedChatEngine engine() {
        List<ChatTool> adapters = tools.entrySet().stream().map(e -> (ChatTool) new ChatTool() {
            public ChatCapability capability() { return e.getKey(); }
            public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
                return e.getValue().apply(scope, request);
            }
        }).toList();
        var registry = new ChatToolRegistry(adapters);
        var runner = new ChatToolRunner(registry);
        runners.add(runner);
        ChatModels.Router router = (run, bound) -> {
            if (routerFailure != null) throw routerFailure;
            return decision;
        };
        ChatModels.Generator generator = context -> {
            generated.add(context);
            if (generatorFailure != null) throw generatorFailure;
            return answer;
        };
        ChatModels.Verifier verifier = (run, sections, citations) -> {
            verifierCalls++;
            return verdicts;
        };
        ChatCitationSource citations = (id, version, asOf, trace) -> Optional.ofNullable(readable.get(id));
        return new OrchestratedChatEngine(router, generator, verifier, registry, runner, citations,
                Clock.fixed(NOW, ZoneOffset.UTC));
    }

    private static ChatRun run() {
        return ChatPlannerTest.run(0, "v1");
    }

    private static String evidence(String company) {
        return "ev-" + company.toLowerCase().replace(':', '-');
    }

    private static Section general(String text, String requirement) {
        return new Section("general_knowledge", text, List.of(requirement), List.of());
    }

    private static Section grounded(String text, List<String> requirements, String... evidence) {
        return new Section("evidence_grounded", text, requirements, List.of(evidence));
    }

    private static ChatResult completed(ChatEngineOutcome outcome) {
        return assertInstanceOf(ChatEngineOutcome.Completed.class, outcome, outcome.toString()).result();
    }

    private static void assertFailed(String kind, String reason, boolean rerunnable, ChatEngineOutcome outcome) {
        assertEquals(new ChatEngineOutcome.Failed(kind, reason, rerunnable), outcome);
    }

    /** Records what the engine asks of the run. */
    private static final class Control implements ChatRunControl {
        final List<String> phases = new ArrayList<>();
        final List<ChatToolCallReservation> reserved = Collections.synchronizedList(new ArrayList<>());
        final Duration remaining;
        int modelCalls;

        Control(Duration remaining) {
            this.remaining = remaining;
        }

        @Override public void phase(String phase) { phases.add(phase); }
        @Override public void beforeModelCall() { modelCalls++; }
        @Override public Duration remaining() { return remaining; }
        @Override public boolean owned() { return true; }

        @Override
        public List<String> reserveToolCalls(int planRevision, List<ChatToolCallReservation> calls) {
            List<String> ids = new ArrayList<>();
            for (var call : calls) {
                ids.add("tc-" + reserved.size());
                reserved.add(call);
            }
            return ids;
        }

        @Override public void toolCallStarted(String toolCallId) { }
        @Override public void toolCallFinished(String toolCallId, ChatToolCallEnd end) { }
    }
}
