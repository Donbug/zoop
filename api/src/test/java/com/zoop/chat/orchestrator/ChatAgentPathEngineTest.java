package com.zoop.chat.orchestrator;

import static com.zoop.chat.orchestrator.ChatPlannerTest.req;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.chat.dto.ChatResult;
import com.zoop.chat.dto.Citation;
import com.zoop.chat.executor.ChatEngineOutcome;
import com.zoop.chat.executor.ChatJobExecutor;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.executor.ChatRunControl;
import com.zoop.chat.executor.ChatToolCallReservation;
import com.zoop.chat.orchestrator.ChatGeneratedAnswer.Section;
import com.zoop.chat.orchestrator.ChatRouteDecision.Dependency;
import com.zoop.chat.orchestrator.ChatSemanticVerdicts.Verdict;
import com.zoop.chat.repository.ChatToolCallEnd;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatTool;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolOutput;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolRequest;
import com.zoop.chat.tool.ChatToolResult;
import com.zoop.chat.tool.ChatToolRunner;
import com.zoop.chat.tool.ChatToolScope;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

/**
 * D-AI-02 agent path of the orchestrator with a scripted agent (no model, no network): which plans take it, that its answer is
 * checked against exactly the results of the calls that ran, and its time budget.
 */
class ChatAgentPathEngineTest {
    private static final Instant NOW = Instant.parse("2026-10-21T03:00:00Z");
    private static final String HYNIX = "KRX:000660";
    private static final String NVDA = "NASDAQ:NVDA";
    private static final String EV_HYNIX = "ev-krx-000660";
    private static final String EV_NVDA = "ev-nasdaq-nvda";

    private final List<ChatToolRunner> runners = new ArrayList<>();
    private final List<OrchestratedChatEngine> engines = new ArrayList<>();
    private final List<ChatBranchContext> generated = new ArrayList<>();
    private final Map<String, Citation> readable = Map.of(
            EV_HYNIX, citation(EV_HYNIX), EV_NVDA, citation(EV_NVDA));
    private ChatRouteDecision decision;
    private ChatGeneratedAnswer directAnswer = new ChatGeneratedAnswer(List.of(), List.of("r1"), List.of());
    private ChatSemanticVerdicts verdicts = new ChatSemanticVerdicts(List.of(new Verdict("supported", "no")));
    private int verifierCalls;
    /** When set, the time left once the router has answered (the router's own time spent). */
    private Control routed;
    private Duration leftAfterRouter;

    /** A scripted agent path: records what it was given and returns a fixed answer with the results of "the calls that ran". */
    private static final class Agent implements ChatAgentPath {
        final Set<ChatCapability> exposed;
        final List<List<ChatModels.AgentRequirement>> requirements = new ArrayList<>();
        final List<List<ChatCapability>> allowed = new ArrayList<>();
        final List<Boolean> closing = new ArrayList<>();
        ChatGeneratedAnswer answer;
        List<ChatToolResult> results = List.of();

        Agent(Set<ChatCapability> exposed) {
            this.exposed = exposed;
        }

        @Override
        public Set<ChatCapability> tools() {
            return exposed;
        }

        @Override
        public Outcome run(ChatRun run, ChatRunControl control, List<ChatModels.AgentRequirement> given,
                List<ChatCapability> tools, int maxCitations, Steps steps) {
            requirements.add(given);
            allowed.add(tools);
            // One step through the engine's guard and limit, like the real path.
            closing.add(steps.closing());
            steps.run(() -> new ChatModels.AgentStep("resp_1", List.of(), answer));
            return new Outcome(answer, results, 1, 1, 0);
        }
    }

    @AfterEach
    void tearDown() {
        runners.forEach(ChatToolRunner::close);
        engines.forEach(OrchestratedChatEngine::close);
    }

    @Test
    void anIndependentReadPlanTakesTheAgentPathAndIsCheckedAgainstTheResultsThatRan() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(HYNIX)));
        var agent = new Agent(Set.of(ChatCapability.COMPANY_READ, ChatCapability.ISSUE_READ));
        agent.answer = new ChatGeneratedAnswer(List.of(grounded("SK하이닉스는 HBM을 공급합니다.", EV_HYNIX)), List.of(),
                List.of(HYNIX));
        agent.results = List.of(companyResult(HYNIX, EV_HYNIX));
        var control = new Control(Duration.ofSeconds(60));

        var outcome = engine(agent).answer(ChatPlannerTest.run(0, "v1"), control);
        ChatResult result = assertInstanceOf(ChatEngineOutcome.Completed.class, outcome, outcome.toString()).result();
        assertEquals("answered", result.outcome());
        assertEquals(List.of(EV_HYNIX), result.citations().stream().map(Citation::evidenceId).toList());
        assertEquals(List.of(HYNIX), result.graphTargets().stream().map(g -> g.id()).toList());
        assertTrue(generated.isEmpty(), "the direct generator is not called on the agent path");
        assertTrue(control.reserved.isEmpty(), "the server plans no reads of its own on the agent path");
        assertEquals(List.of(List.of(ChatCapability.COMPANY_READ)), agent.allowed, "only the plan's capabilities");
        assertEquals(List.of(HYNIX), agent.requirements.getFirst().getFirst().targets());
        assertEquals(1, verifierCalls);
        assertEquals(List.of("retrieving", "verifying"), control.phases);
        assertEquals(3, control.modelCalls, "router, one agent step, verifier");
    }

    @Test
    void anAgentAnswerCitingWhatNoCallReturnedFailsValidation() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(HYNIX)));
        var agent = new Agent(Set.of(ChatCapability.COMPANY_READ));
        agent.answer = new ChatGeneratedAnswer(List.of(grounded("NVIDIA도 공급합니다.", EV_NVDA)), List.of(), List.of());
        agent.results = List.of(companyResult(HYNIX, EV_HYNIX));

        assertEquals(new ChatEngineOutcome.Failed("validation_failed", null, false),
                engine(agent).answer(ChatPlannerTest.run(0, "v1"), new Control(Duration.ofSeconds(60))));
        assertEquals(0, verifierCalls);
    }

    @Test
    void dependentGeneralOrUnexposedPlansStayOnTheDirectPath() {
        var agent = new Agent(Set.of(ChatCapability.COMPANY_READ));
        verdicts = new ChatSemanticVerdicts(List.of());
        List<ChatRouteDecision> plans = List.of(
                ChatPlannerTest.decision(
                        req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("issue.read", 0.9), List.of("iss-1")),
                        req("r2", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9))
                                .dependingOn(new Dependency("r1", "atLeast", 1))),
                ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q02, 0.95), Map.of())),
                ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("issue.read", 0.9),
                        List.of("iss-1"))),
                // Six companies: over one call's fan-out, so the server batches them itself.
                ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                        List.of(HYNIX, NVDA, "KRX:005930", "NASDAQ:AMD", "NYSE:TSM", "NASDAQ:ASML"))));
        for (ChatRouteDecision plan : plans) {
            decision = plan;
            engine(agent).answer(ChatPlannerTest.run(0, "v1"), new Control(Duration.ofSeconds(60)));
        }
        assertTrue(agent.requirements.isEmpty(), "the agent took none of them");
        assertEquals(4, generated.size(), "each was answered by the direct generator");
    }

    @Test
    void anAgentStepThatCannotGetTheTimeAnAnswerNeedsEndsAsDeadlineGuard() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(HYNIX)));
        var agent = new Agent(Set.of(ChatCapability.COMPANY_READ));
        agent.answer = new ChatGeneratedAnswer(List.of(), List.of("r1"), List.of());
        // Enough for the router's guard, but after verification and saving less than 10 s remains for an agent step.
        var control = new Control(Duration.ofSeconds(25));
        assertEquals(new ChatEngineOutcome.Failed("transient", "deadline_guard", true),
                engine(agent).answer(ChatPlannerTest.run(0, "v1"), control));
    }

    @Test
    void anAgentRunKeepsToFortyFiveSecondsFromItsStartWithLunaAtMostThirtyFive() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(HYNIX)));
        var agent = new Agent(Set.of(ChatCapability.COMPANY_READ));
        agent.answer = new ChatGeneratedAnswer(List.of(grounded("SK하이닉스는 HBM을 공급합니다.", EV_HYNIX)), List.of(),
                List.of(HYNIX));
        agent.results = List.of(companyResult(HYNIX, EV_HYNIX));
        // At the start of the job (60 s to its deadline, 45 s of the agent run): Luna has min(35, 45 - 14) = 31 s.
        assertInstanceOf(ChatEngineOutcome.Completed.class,
                engine(agent).answer(ChatPlannerTest.run(0, "v1"), new Control(ChatJobExecutor.MAX_DEADLINE)));
        assertEquals(List.of(false), agent.closing, "31 s leave room for more than the closing step");
        // A router that took 20 s leaves 40 s to the deadline, 25 s of the agent run: 11 s for Luna, only the step that
        // writes the answer.
        var answered = routedThen(agent, Duration.ofSeconds(40));
        assertInstanceOf(ChatEngineOutcome.Completed.class, answered, answered.toString());
        assertEquals(List.of(false, true), agent.closing);
        // One that took 22 s leaves 38 s, 24 s on the job but 9 s for Luna in the agent run: the agent does not start.
        assertEquals(new ChatEngineOutcome.Failed("transient", "deadline_guard", true),
                routedThen(agent, Duration.ofSeconds(38)));
        assertEquals(2, agent.requirements.size());
    }

    private ChatEngineOutcome routedThen(ChatAgentPath agent, Duration left) {
        routed = new Control(ChatJobExecutor.MAX_DEADLINE);
        leftAfterRouter = left;
        return engine(agent).answer(ChatPlannerTest.run(0, "v1"), routed);
    }

    private OrchestratedChatEngine engine(ChatAgentPath agent) {
        ChatTool company = new ChatTool() {
            public ChatCapability capability() { return ChatCapability.COMPANY_READ; }
            public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
                return new ChatToolOutput(scope.graphVersionId(), List.of(), List.of(), false, false);
            }
        };
        ChatTool issue = new ChatTool() {
            public ChatCapability capability() { return ChatCapability.ISSUE_READ; }
            public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
                return new ChatToolOutput(scope.graphVersionId(), List.of(), List.of(), false, false);
            }
        };
        var registry = new ChatToolRegistry(List.of(company, issue));
        var runner = new ChatToolRunner(registry);
        runners.add(runner);
        ChatModels.Router router = (run, bound) -> {
            if (routed != null) routed.remaining = leftAfterRouter;
            return decision;
        };
        ChatModels.Generator generator = (run, context) -> {
            generated.add(context);
            return directAnswer;
        };
        ChatModels.Verifier verifier = (run, sections, citations) -> {
            verifierCalls++;
            return verdicts;
        };
        ChatCitationSource citations = (id, version, asOf, trace) -> Optional.ofNullable(readable.get(id));
        var engine = new OrchestratedChatEngine(router, generator, verifier, registry, runner, citations,
                Clock.fixed(NOW, ZoneOffset.UTC), OrchestratedChatEngine.StageLimits.POLICY, agent);
        engines.add(engine);
        return engine;
    }

    private static ChatToolResult companyResult(String company, String evidence) {
        return new ChatToolResult("chat-tool/v1", "tc-0", "company.read", "v1",
                List.of(new ChatToolItem(company, "company", "기업", List.of(company), List.of(evidence))),
                List.of(evidence), false, false, null);
    }

    private static Section grounded(String text, String evidence) {
        return new Section("evidence_grounded", text, List.of("r1"), List.of(evidence));
    }

    private static Citation citation(String evidence) {
        return new Citation("article", evidence, "인용", "art-" + evidence, "v1", null, null, 0, 2, "기사", "언론사", NOW,
                "https://example.invalid/" + evidence);
    }

    /** Records what the engine asks of the run. */
    private static final class Control implements ChatRunControl {
        final List<String> phases = new ArrayList<>();
        final List<ChatToolCallReservation> reserved = new ArrayList<>();
        Duration remaining;
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
