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
    /** Evidence the direct company read returns for {@link #HYNIX}; none by default. */
    private List<String> directEvidence = List.of();
    private ChatSemanticVerdicts verdicts = new ChatSemanticVerdicts(List.of(new Verdict("supported", "no")));
    private int verifierCalls;
    /** The engine's clock; the router moves it on by {@link #routerTakes}, as a router call spends time. */
    private Instant now = NOW;
    private Duration routerTakes = Duration.ZERO;
    private final Clock clock = new Clock() {
        @Override public ZoneOffset getZone() { return ZoneOffset.UTC; }
        @Override public Clock withZone(java.time.ZoneId zone) { return this; }
        @Override public Instant instant() { return now; }
    };

    /** A scripted agent path: records what it was given and returns a fixed answer with the results of "the calls that ran". */
    private static final class Agent implements ChatAgentPath {
        final Set<ChatCapability> exposed;
        final List<List<ChatModels.AgentRequirement>> requirements = new ArrayList<>();
        final List<List<ChatCapability>> allowed = new ArrayList<>();
        final List<Boolean> closing = new ArrayList<>();
        ChatGeneratedAnswer answer;
        List<ChatToolResult> results = List.of();
        boolean available = true;
        ChatModels.Failure failure;

        Agent(Set<ChatCapability> exposed) {
            this.exposed = exposed;
        }

        @Override
        public Set<ChatCapability> tools() {
            return exposed;
        }

        @Override
        public boolean available() {
            return available;
        }

        @Override
        public Outcome run(ChatRun run, ChatRunControl control, List<ChatModels.AgentRequirement> given,
                List<ChatCapability> tools, int maxCitations, Steps steps) {
            requirements.add(given);
            allowed.add(tools);
            if (failure != null) throw failure;
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

        var outcome = engine(agent).answer(run(), control);
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
                engine(agent).answer(run(), new Control(Duration.ofSeconds(60))));
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
            engine(agent).answer(run(), new Control(Duration.ofSeconds(60)));
        }
        assertTrue(agent.requirements.isEmpty(), "the agent took none of them");
        assertEquals(4, generated.size(), "each was answered by the direct generator");
    }

    @Test
    void anUnavailablePreflightStartsDirectBeforeAnyAgentStep() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(HYNIX)));
        var agent = new Agent(Set.of(ChatCapability.COMPANY_READ));
        agent.available = false;
        var control = new Control(Duration.ofSeconds(60));
        // The direct answer has no sections, so there is nothing to verify.
        verdicts = new ChatSemanticVerdicts(List.of());

        var outcome = engine(agent).answer(run(), control);

        assertTrue(agent.requirements.isEmpty(), "no agent Responses step started");
        assertEquals(1, generated.size(), "the existing direct retrieval/generation path handled the run");
        assertEquals(1, control.reserved.size(), "the server-owned direct tool was used");
        var route = assertInstanceOf(ChatEngineOutcome.Completed.class, outcome, outcome.toString()).routeSummary();
        assertEquals("direct", route.path("path").asString());
        assertEquals("unavailable", route.path("agentPreflight").asString());

        // A run that was never an agent candidate reads on the same direct path and says so, with no preflight mark.
        var plain = assertInstanceOf(ChatEngineOutcome.Completed.class,
                engine(new Agent(Set.of())).answer(run(), new Control(Duration.ofSeconds(60)))).routeSummary();
        assertEquals("direct", plain.path("path").asString());
        assertTrue(plain.path("agentPreflight").isMissingNode());
    }

    @Test
    void aDirectStartAnswerIsCompleteAndCarriesTheDirectStartNotice() {
        // D-AI-02: the member sees why the answer came by the server's own path, and that it is still a full answer.
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(HYNIX)));
        directEvidence = List.of(EV_HYNIX);
        directAnswer = new ChatGeneratedAnswer(List.of(grounded("SK하이닉스는 HBM을 공급합니다.", EV_HYNIX)), List.of(),
                List.of());
        var agent = new Agent(Set.of(ChatCapability.COMPANY_READ));
        agent.available = false;

        ChatResult result = assertInstanceOf(ChatEngineOutcome.Completed.class,
                engine(agent).answer(run(), new Control(Duration.ofSeconds(60)))).result();

        assertEquals("answered", result.outcome());
        assertEquals("complete", result.answerStatus());
        assertEquals(List.of("mcp_direct_start"), result.notices().stream().map(n -> n.code()).toList());
        assertTrue(result.notices().getFirst().labels().isEmpty(), "it concerns the whole run");

        // An agent answer, or a direct run that never was an agent candidate, has no notice.
        agent.available = true;
        agent.answer = directAnswer;
        agent.results = List.of(companyResult(HYNIX, EV_HYNIX));
        var viaAgent = assertInstanceOf(ChatEngineOutcome.Completed.class,
                engine(agent).answer(run(), new Control(Duration.ofSeconds(60)))).result();
        assertEquals("complete", viaAgent.answerStatus());
        assertTrue(viaAgent.notices().isEmpty());
        var plain = assertInstanceOf(ChatEngineOutcome.Completed.class,
                engine(new Agent(Set.of())).answer(run(), new Control(Duration.ofSeconds(60)))).result();
        assertTrue(plain.notices().isEmpty());
    }

    @Test
    void anMcpFailureAfterTheAgentStartsIsNeverReplacedWithDirectResults() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(HYNIX)));
        var agent = new Agent(Set.of(ChatCapability.COMPANY_READ));
        agent.failure = new ChatModels.Failure(ChatModels.Failure.Fate.NOT_SENT, "mcp_unreachable", "MCP unavailable");
        var control = new Control(Duration.ofSeconds(60));

        assertEquals(new ChatEngineOutcome.Failed("transient", "provider_error", true),
                engine(agent).answer(run(), control));
        assertEquals(1, agent.requirements.size(), "the agent path had already started");
        assertTrue(generated.isEmpty(), "the direct generator was not substituted");
        assertTrue(control.reserved.isEmpty(), "the direct tool path was not substituted");
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
                engine(agent).answer(run(), control));
    }

    @Test
    void anAgentRunKeepsToFortyFiveSecondsFromItsStartWithLunaAtMostThirtyFive() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(HYNIX)));
        var agent = new Agent(Set.of(ChatCapability.COMPANY_READ));
        agent.answer = new ChatGeneratedAnswer(List.of(grounded("SK하이닉스는 HBM을 공급합니다.", EV_HYNIX)), List.of(),
                List.of(HYNIX));
        agent.results = List.of(companyResult(HYNIX, EV_HYNIX));
        // At the start of the job (60 s to its deadline): the run's deadline becomes 45 s from the start, so verification
        // and the final store keep to it too, and Luna has min(35, 45 - 14) = 31 s.
        var control = new Control(ChatJobExecutor.MAX_DEADLINE);
        assertInstanceOf(ChatEngineOutcome.Completed.class, engine(agent).answer(run(), control));
        assertEquals(NOW.plus(OrchestratedChatEngine.AGENT_JOB), control.deadline);
        assertEquals(List.of(false), agent.closing, "31 s leave room for more than the closing step");
        // A router that took 20 s leaves 25 s of the agent run: 11 s for Luna, only the step that writes the answer.
        assertInstanceOf(ChatEngineOutcome.Completed.class, routedFor(agent, Duration.ofSeconds(20)));
        assertEquals(List.of(false, true), agent.closing);
        // One that took 22 s leaves 23 s of it, 9 s for Luna: the agent does not start (the job's 60 s would still have 38 s).
        assertEquals(new ChatEngineOutcome.Failed("transient", "deadline_guard", true),
                routedFor(agent, Duration.ofSeconds(22)));
        assertEquals(2, agent.requirements.size());
    }

    @Test
    void aRerunGetsNoNewCallBudget() {
        decision = ChatPlannerTest.decision(req("r1", Map.of(ChatQueryType.Q03, 0.9), Map.of("company.read", 0.9),
                List.of(HYNIX)));
        var agent = new Agent(Set.of(ChatCapability.COMPANY_READ));
        // Earlier attempts of the job made all its calls: neither path reads again, and the job is not rerun.
        var spent = new Control(ChatJobExecutor.MAX_DEADLINE);
        spent.spent = ChatRunControl.MAX_TOOL_CALLS;
        assertEquals(OrchestratedChatEngine.TOOL_BUDGET_SPENT, engine(agent).answer(run(), spent));
        assertTrue(agent.requirements.isEmpty());
        // The direct path (nothing exposed to an agent) the same: its plan needs a call the job no longer has.
        var spentDirect = new Control(ChatJobExecutor.MAX_DEADLINE);
        spentDirect.spent = ChatRunControl.MAX_TOOL_CALLS;
        assertEquals(OrchestratedChatEngine.TOOL_BUDGET_SPENT, engine(new Agent(Set.of())).answer(run(), spentDirect));
        assertTrue(spentDirect.reserved.isEmpty());
        assertEquals(new ChatEngineOutcome.Failed("budget_exceeded", null, false), OrchestratedChatEngine.TOOL_BUDGET_SPENT);
    }

    private ChatEngineOutcome routedFor(ChatAgentPath agent, Duration took) {
        now = NOW;
        routerTakes = took;
        try {
            return engine(agent).answer(run(), new Control(ChatJobExecutor.MAX_DEADLINE));
        } finally {
            routerTakes = Duration.ZERO;
        }
    }

    /** A run of a job started now: its deadline is the job's 60 s. */
    private ChatRun run() {
        ChatRun r = ChatPlannerTest.run(0, "v1");
        return new ChatRun(r.jobId(), r.sessionId(), r.memberId(), r.attemptNo(), r.mode(), r.turns(), r.context(),
                r.selection(), r.graphVersionId(), r.clarificationDepth(), r.askedAt(),
                now.plus(ChatJobExecutor.MAX_DEADLINE));
    }

    private OrchestratedChatEngine engine(ChatAgentPath agent) {
        ChatTool company = new ChatTool() {
            public ChatCapability capability() { return ChatCapability.COMPANY_READ; }
            public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
                if (directEvidence.isEmpty()) return new ChatToolOutput(scope.graphVersionId(), List.of(), List.of(), false, false);
                return new ChatToolOutput(scope.graphVersionId(), List.of(new ChatToolItem(HYNIX, "company", "기업",
                        List.of(HYNIX), directEvidence)), directEvidence, false, false);
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
            now = now.plus(routerTakes);
            return decision;
        };
        ChatModels.Generator generator = (run, context) -> {
            generated.add(context);
            return directAnswer;
        };
        ChatModels.Verifier verifier = (run, sections, citations, facts) -> {
            verifierCalls++;
            return verdicts;
        };
        ChatCitationSource citations = (id, version, asOf, trace) -> Optional.ofNullable(readable.get(id));
        var engine = new OrchestratedChatEngine(router, generator, verifier, registry, runner, citations,
                clock, OrchestratedChatEngine.StageLimits.POLICY, agent);
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

    /** Records what the engine asks of the run; its deadline is on the engine's clock. */
    private final class Control implements ChatRunControl {
        final List<String> phases = new ArrayList<>();
        final List<ChatToolCallReservation> reserved = new ArrayList<>();
        Instant deadline;
        int modelCalls;
        /** Calls earlier attempts of the job made. */
        int spent;

        Control(Duration remaining) {
            this.deadline = now.plus(remaining);
        }

        @Override public void phase(String phase) { phases.add(phase); }
        @Override public void beforeModelCall() { modelCalls++; }
        @Override public Duration remaining() { return Duration.between(now, deadline); }
        @Override public boolean owned() { return true; }
        @Override public int toolCallsLeft() { return MAX_TOOL_CALLS - spent - reserved.size(); }

        @Override
        public void shortenDeadline(Instant at) {
            if (at.isBefore(deadline)) deadline = at;
        }

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

        @Override
        public java.util.Optional<String> claimToolCall(String capabilityId, String inputDigest) {
            throw new UnsupportedOperationException("only the MCP endpoint claims an approved call");
        }
        @Override public void toolCallFinished(String toolCallId, ChatToolCallEnd end) { }
    }
}
