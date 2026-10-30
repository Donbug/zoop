package com.zoop.chat.mcp;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.chat.executor.ChatEngine;
import com.zoop.chat.executor.ChatEngineOutcome;
import com.zoop.chat.executor.ChatJobExecutor;
import com.zoop.chat.executor.ChatRunSuperseded;
import com.zoop.chat.executor.MemoryChatStore;
import com.zoop.chat.executor.NoChatTransactions;
import com.zoop.chat.dto.Citation;
import com.zoop.chat.orchestrator.ChatAgentPath;
import com.zoop.chat.orchestrator.ChatCitationSource;
import com.zoop.chat.orchestrator.ChatGeneratedAnswer;
import com.zoop.chat.orchestrator.ChatModels;
import com.zoop.chat.orchestrator.ChatQueryType;
import com.zoop.chat.orchestrator.ChatRouteDecision;
import com.zoop.chat.orchestrator.ChatSemanticVerdicts;
import com.zoop.chat.orchestrator.OrchestratedChatEngine;
import com.zoop.chat.repository.ChatJobRow;
import com.zoop.chat.repository.ChatKeptToolResult;
import com.zoop.chat.service.ChatCompanyProfiles;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatTool;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolOutput;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolRequest;
import com.zoop.chat.tool.ChatToolResult;
import com.zoop.chat.tool.ChatToolRunner;
import com.zoop.chat.tool.ChatToolScope;
import io.modelcontextprotocol.common.McpTransportContext;
import io.modelcontextprotocol.spec.McpSchema;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.Function;
import java.util.function.Supplier;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * D-AI-02: the agent path's approval loop over the real MCP tools and a running job of the memory store. A scripted Luna asks,
 * the server decides, and (like the provider) only approved calls are made through the MCP call handler. Synthetic only.
 */
class ChatMcpAgentTest {
    private static final Instant NOW = ChatMcpGrantsTest.NOW;
    private static final String JOB = "job-00001";
    private static final String CONTEXT = "{\"items\":[],\"evidenceCount\":0,\"period\":null,"
            + "\"asOf\":\"2026-10-27T00:00:00Z\",\"graphVersion\":\"gv-1\"}";
    private static final String SELECTION = "{\"contextIds\":[],\"evidenceIds\":[],\"evidencePool\":[]}";
    private static final List<ChatModels.AgentRequirement> REQUIREMENTS =
            List.of(new ChatModels.AgentRequirement("r1", "SK하이닉스 최근 사건", false, List.of("KRX:000660")));
    private static final ChatGeneratedAnswer ANSWER = new ChatGeneratedAnswer(List.of(new ChatGeneratedAnswer.Section(
            "evidence_grounded", "SK하이닉스는 HBM을 공급한다.", List.of("r1"), List.of("ev-1"))), List.of(), List.of());

    @TempDir
    Path dir;

    private final JsonMapper mapper = JsonMapper.builder().build();
    private final Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);
    private MemoryChatStore store;
    private ChatToolRunner runner;
    private ChatToolRegistry registry;
    private ChatJobExecutor executor;
    private ChatMcpTools tools;
    private ChatMcpGrants grants;
    private Luna luna;

    @BeforeEach
    void setUp() {
        store = new MemoryChatStore();
        registry = new ChatToolRegistry(List.of(tool(ChatCapability.COMPANY_READ), tool(ChatCapability.ISSUE_READ),
                tool(ChatCapability.GRAPH_VERSION_DIFF)));
        runner = new ChatToolRunner(registry);
        executor = new ChatJobExecutor(store, store,
                new StaticListableBeanFactory(Map.of()).getBeanProvider(ChatEngine.class), mapper, clock,
                new NoChatTransactions());
        tools = new ChatMcpTools(registry, runner, executor, ChatSendGrantsTest.gate(dir), mapper);
        grants = ChatMcpGrantsTest.grants("k1", "k1=" + ChatMcpGrantsTest.KEY_A, NOW);
        luna = new Luna();
        String attempts = "[{\"n\":1,\"mode\":\"run\",\"requestKey\":\"" + JOB + "\",\"status\":\"running\","
                + "\"ownerToken\":\"owner-1\"}]";
        store.add(new ChatJobRow(JOB, "conv-0001", "member-a", 1, "SK하이닉스 최근 사건", "a".repeat(64), NOW, CONTEXT,
                SELECTION, List.of(), "gv-1", "queued", null, null, null, null, 0, null, null, 0, attempts, NOW, NOW, null));
        // The full orchestrator reserves 53 seconds before routing; use the production 60-second job deadline.
        assertTrue(store.start(JOB, "owner-1", NOW.plusSeconds(60), NOW.plusSeconds(60), attempts, NOW));
    }

    @AfterEach
    void tearDown() {
        runner.close();
    }

    /**
     * A scripted Luna behind the provider: each step answers from {@code script}; between steps, like the provider, it makes
     * exactly the approved calls of the previous step through the MCP call handler with the run's grant token.
     */
    private final class Luna implements ChatModels.Agent {
        final List<ChatModels.AgentInput> inputs = new ArrayList<>();
        final List<Function<Integer, ChatModels.AgentStep>> script = new ArrayList<>();
        final List<McpSchema.CallToolResult> made = new ArrayList<>();
        final Map<String, ChatModels.ApprovalRequest> asked = new HashMap<>();

        @Override
        public ChatModels.AgentStep step(com.zoop.chat.executor.ChatRun run, int step, ChatModels.AgentInput input) {
            inputs.add(input);
            var grant = grants.verify(input.grantToken()).orElseThrow();
            var context = McpTransportContext.create(Map.of(ChatMcpTools.GRANT, grant));
            for (ChatModels.Decision decision : input.decisions()) {
                if (!decision.approve()) continue;
                var request = asked.get(decision.approvalRequestId());
                made.add(tools.call(context, new McpSchema.CallToolRequest(request.toolName(), request.arguments())));
            }
            ChatModels.AgentStep next = script.get(Math.min(step, script.size()) - 1).apply(step);
            next.approvals().forEach(a -> asked.put(a.id(), a));
            return next;
        }
    }

    private static ChatModels.AgentStep held(String id, String tool, Map<String, Object> arguments) {
        return new ChatModels.AgentStep("resp_" + id, List.of(new ChatModels.ApprovalRequest(id, tool, arguments)), null);
    }

    private static ChatModels.AgentStep done() {
        return new ChatModels.AgentStep("resp_done", List.of(), ANSWER);
    }

    private ChatMcpCircuitBreaker circuit() {
        return new ChatMcpCircuitBreaker(() -> new com.zoop.ai.chat.ChatMcpHealth(true, null), clock);
    }

    private ChatAgentPath.Outcome run(ChatAgentPath.Steps steps) {
        var agent = new ChatMcpAgent(luna, tools, grants, ChatSendGrantsTest.RECIPIENT, store, runner, circuit());
        var attached = executor.attach(JOB, 1).orElseThrow();
        return agent.run(attached.run(), attached.control(), REQUIREMENTS, List.of(ChatCapability.COMPANY_READ), 20, steps);
    }

    private static ChatAgentPath.Steps steps(boolean closing) {
        return new ChatAgentPath.Steps() {
            @Override
            public ChatModels.AgentStep run(Supplier<ChatModels.AgentStep> step) {
                return step.get();
            }

            @Override
            public boolean closing() {
                return closing;
            }
        };
    }

    /** Registers the web search (synthetic provider, granted) beside a company read that finds nothing. */
    private void useWeb() {
        useWeb(true);
    }

    private void useWeb(boolean grantWebResults) {
        runner.close();
        ChatTool empty = new ChatTool() {
            @Override
            public ChatCapability capability() {
                return ChatCapability.COMPANY_READ;
            }

            @Override
            public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
                return new ChatToolOutput(scope.graphVersionId(), List.of(), List.of(), false, false);
            }
        };
        var registry = new ChatToolRegistry(List.of(empty,
                new com.zoop.chat.tool.ChatWebSearchTool(new com.zoop.chat.tool.SyntheticWebSearchProvider(), clock)));
        runner = new ChatToolRunner(registry);
        Path file = grantWebResults
                ? ChatSendGrantsTest.write(dir.resolve("web-grants.json"), ChatCompanyProfiles.SOURCE_ID,
                        ChatMcpSendGate.GRAPH_SOURCE_ID, ChatMcpSendGate.webSource("synthetic"))
                : ChatSendGrantsTest.write(dir.resolve("web-grants.json"), ChatCompanyProfiles.SOURCE_ID,
                        ChatMcpSendGate.GRAPH_SOURCE_ID);
        var gate = new ChatMcpSendGate(new ChatSendGrants(file.toString(), ChatSendGrantsTest.RECIPIENT, clock),
                (run, ids) -> Map.of());
        tools = new ChatMcpTools(registry, runner, executor, gate, mapper);
    }

    private ChatAgentPath.Outcome runWithWeb() {
        var circuit = new ChatMcpCircuitBreaker(() -> new com.zoop.ai.chat.ChatMcpHealth(true, null), clock);
        var agent = new ChatMcpAgent(luna, tools, grants, ChatSendGrantsTest.RECIPIENT, store, runner, circuit);
        var attached = executor.attach(JOB, 1).orElseThrow();
        return agent.run(attached.run(), attached.control(), REQUIREMENTS,
                List.of(ChatCapability.COMPANY_READ, ChatCapability.WEB_SEARCH), 20, steps(false));
    }

    private static ChatModels.ApprovalRequest search(String id, String query) {
        return new ChatModels.ApprovalRequest(id, "web_search", Map.of("targets", List.of(query)));
    }

    @Test
    void aWebSearchIsApprovedOnlyAfterAnInternalReadLeftSomethingUnmetAndOnlyForAQueryThatMayLeave() {
        useWeb();
        assertTrue(tools.exposed().contains(ChatCapability.WEB_SEARCH), "the web search is an MCP tool when registered");
        // Round 1: the web first is refused; the company read runs and finds nothing.
        luna.script.add(n -> new ChatModels.AgentStep("resp_1", List.of(search("w0", "HBM"),
                new ChatModels.ApprovalRequest("c1", "company_read", Map.of("targets", List.of("KRX:000660")))), null));
        // Round 2: a query about the member is refused, a public one runs.
        luna.script.add(n -> new ChatModels.AgentStep("resp_2", List.of(search("w1", "SK하이닉스 보유 수량"),
                search("w2", "HBM")), null));
        luna.script.add(n -> done());

        var outcome = runWithWeb();

        assertEquals(List.of(new ChatModels.Decision("w0", false), new ChatModels.Decision("c1", true)),
                luna.inputs.get(1).decisions(), "the web is the last resort, not the first look");
        assertEquals(List.of(new ChatModels.Decision("w1", false), new ChatModels.Decision("w2", true)),
                luna.inputs.get(2).decisions());
        assertEquals(List.of("company_read", "web_search"), luna.inputs.getFirst().allowedTools());
        var web = outcome.results().stream().filter(r -> "web.search".equals(r.capabilityId())).toList();
        assertEquals(1, web.size());
        assertEquals(2, web.getFirst().webResults().size(), "the hits the model received come back from the ledger");
        assertEquals("synthetic", web.getFirst().webResults().getFirst().provider());
        assertTrue(outcome.notices().isEmpty());
        assertEquals(List.of("HBM"), store.toolCalls(JOB).stream().filter(c -> "web.search".equals(c.row.capabilityId()))
                .map(c -> c.row.requestMeta().replaceAll(".*\"targets\":\\[\"([^\"]*)\".*", "$1")).toList());
    }

    @Test
    void aConceptMayMakeOneSearchFromTheFirstRound() {
        useWeb();
        luna.script.add(n -> new ChatModels.AgentStep("resp_1", List.of(search("w1", "HBM"), search("w2", "EUV 수출 규제")),
                null));
        luna.script.add(n -> done());
        var circuit = new ChatMcpCircuitBreaker(() -> new com.zoop.ai.chat.ChatMcpHealth(true, null), clock);
        var agent = new ChatMcpAgent(luna, tools, grants, ChatSendGrantsTest.RECIPIENT, store, runner, circuit);
        var attached = executor.attach(JOB, 1).orElseThrow();
        var outcome = agent.run(attached.run(), attached.control(),
                List.of(new ChatModels.AgentRequirement("r1", "HBM이 뭐야", true, List.of())),
                List.of(ChatCapability.WEB_SEARCH), 20, steps(false));

        assertEquals(List.of(new ChatModels.Decision("w1", true), new ChatModels.Decision("w2", false)),
                luna.inputs.get(1).decisions(), "one search for the concept; nothing internal left more unmet");
        assertEquals(1, outcome.results().size());
        assertEquals(2, outcome.results().getFirst().webResults().size());
    }

    @Test
    void aMixedConceptAndFactRunCannotUseTheConceptExceptionForAFactQuery() {
        useWeb();
        luna.script.add(n -> new ChatModels.AgentStep("resp_1", List.of(search("w0", "SK하이닉스 최신 소식"),
                new ChatModels.ApprovalRequest("c1", "company_read", Map.of("targets", List.of("KRX:000660")))), null));
        luna.script.add(n -> new ChatModels.AgentStep("resp_2", List.of(search("w1", "SK하이닉스 최신 소식")), null));
        luna.script.add(n -> done());
        var circuit = new ChatMcpCircuitBreaker(() -> new com.zoop.ai.chat.ChatMcpHealth(true, null), clock);
        var agent = new ChatMcpAgent(luna, tools, grants, ChatSendGrantsTest.RECIPIENT, store, runner, circuit);
        var attached = executor.attach(JOB, 1).orElseThrow();
        agent.run(attached.run(), attached.control(), List.of(
                new ChatModels.AgentRequirement("r1", "HBM이 뭐야", true, List.of()),
                new ChatModels.AgentRequirement("r2", "SK하이닉스 최신 소식", false, List.of("KRX:000660"))),
                List.of(ChatCapability.COMPANY_READ, ChatCapability.WEB_SEARCH), 20, steps(false));

        assertEquals(List.of(new ChatModels.Decision("w0", false), new ChatModels.Decision("c1", true)),
                luna.inputs.get(1).decisions(), "a mixed run cannot bind the early query to its concept requirement");
        assertEquals(List.of(new ChatModels.Decision("w1", true)), luna.inputs.get(2).decisions(),
                "after the internal read found nothing, the normal last-resort rule opens the web");
    }

    @Test
    void webFaultsTheAnswerWentOnWithoutAreNoticesNeverAFailure() {
        useWeb();
        luna.script.add(n -> held("c1", "company_read", Map.of("targets", List.of("KRX:000660"))));
        // Nothing found, then a provider outage: both approved, the job's two web searches.
        luna.script.add(n -> new ChatModels.AgentStep("resp_2", List.of(search("w1", "없는 검색어"),
                search("w2", "장애 시험")), null));
        // A third search is over the job's web budget.
        luna.script.add(n -> new ChatModels.AgentStep("resp_3", List.of(search("w3", "HBM")), null));
        luna.script.add(n -> done());

        var outcome = runWithWeb();

        assertEquals(List.of(new ChatModels.Decision("w3", false)), luna.inputs.get(3).decisions());
        assertEquals(List.of(ChatMcpAgent.WEB_UNAVAILABLE, ChatMcpAgent.WEB_NO_RESULTS, ChatMcpAgent.WEB_BUDGET_EXHAUSTED),
                outcome.notices());
        assertEquals(ANSWER, outcome.answer(), "the answer goes on");
    }

    @Test
    void webHitsWithheldByTheSendGrantAreUnavailableNotNoResults() {
        useWeb(false);
        luna.script.add(n -> held("c1", "company_read", Map.of("targets", List.of("KRX:000660"))));
        luna.script.add(n -> new ChatModels.AgentStep("resp_2", List.of(search("w1", "HBM")), null));
        luna.script.add(n -> done());

        var outcome = runWithWeb();

        assertEquals(List.of(ChatMcpAgent.WEB_UNAVAILABLE), outcome.notices());
        assertTrue(outcome.results().stream().filter(r -> "web.search".equals(r.capabilityId()))
                .allMatch(r -> r.webResults().isEmpty()), "withheld hits never reach the model or final answer check");
        String kept = store.toolCalls(JOB).stream().filter(c -> "web.search".equals(c.row.capabilityId()))
                .findFirst().orElseThrow().end.result();
        assertEquals(2, mapper.readTree(kept).path("withheld").path("webResults").asInt());
    }

    @Test
    void anApprovedCallRunsThroughMcpAndItsResultComesBackFromTheLedger() {
        luna.script.add(n -> held("mcpr_1", "company_read", Map.of("targets", List.of("KRX:000660"))));
        luna.script.add(n -> done());

        var outcome = run(steps(false));

        assertEquals(ANSWER, outcome.answer());
        assertEquals(2, outcome.steps());
        assertEquals(1, outcome.approved());
        assertEquals(0, outcome.denied());
        assertEquals(1, outcome.results().size());
        var result = outcome.results().getFirst();
        assertEquals("company.read", result.capabilityId());
        assertEquals("KRX:000660", result.items().getFirst().id());
        assertEquals(List.of("ev-1"), result.evidenceIds());
        assertFalse(luna.made.getFirst().isError());

        var first = luna.inputs.getFirst();
        assertEquals(List.of("company_read"), first.allowedTools(), "only the allowed tools");
        var second = luna.inputs.get(1);
        assertEquals("resp_mcpr_1", second.previousResponseId());
        assertEquals(List.of(new ChatModels.Decision("mcpr_1", true)), second.decisions());
        assertEquals("succeeded", store.toolCalls(JOB).getFirst().status);
    }

    @Test
    void aCallTheServerCannotReserveIsDeniedAndNeverRuns() {
        luna.script.add(n -> held("mcpr_1", "company_read", Map.of("targets", List.of("KRX:000660"), "memberId", "member-b")));
        luna.script.add(n -> held("mcpr_2", "issue_read", Map.of("targets", List.of("iss-1"))));
        luna.script.add(n -> done());

        var outcome = run(steps(false));

        assertEquals(0, outcome.approved());
        assertEquals(2, outcome.denied(), "invalid arguments, and a tool this run was not allowed");
        assertTrue(outcome.results().isEmpty());
        assertTrue(luna.made.isEmpty());
        assertTrue(store.toolCalls(JOB).isEmpty(), "nothing was reserved");
        assertEquals(List.of(new ChatModels.Decision("mcpr_2", false)), luna.inputs.get(2).decisions());
    }

    @Test
    void afterThreeRoundsWhatIsStillAskedIsDeniedAndAnEndlessAgentFails() {
        // Reachable targets only, so each round really reserves: the resolved company, varied by its result limit.
        luna.script.add(n -> held("mcpr_" + n, "company_read", Map.of("targets", List.of("KRX:000660"), "limit", n)));
        assertThrows(ChatModels.Failure.class, () -> run(steps(false)));
        assertEquals(5, luna.inputs.size(), "four held steps answered, the fifth still asks");
        assertEquals(3, store.toolCalls(JOB).size(), "three approval rounds reserved");
        assertEquals(List.of(new ChatModels.Decision("mcpr_4", false)), luna.inputs.get(4).decisions(),
                "the closing round denies");
    }

    @Test
    void atMostFourCallsAreApprovedInARoundSoAtMostFourRunAtOnce() {
        // Five reachable calls asked at once (the resolved company at five result limits): the fifth waits a round.
        luna.script.add(n -> new ChatModels.AgentStep("resp_1", java.util.stream.IntStream.rangeClosed(1, 5)
                .mapToObj(i -> new ChatModels.ApprovalRequest("mcpr_" + i, "company_read",
                        Map.of("targets", List.of("KRX:000660"), "limit", i)))
                .toList(), null));
        luna.script.add(n -> done());

        var outcome = run(steps(false));

        assertEquals(List.of(true, true, true, true, false),
                luna.inputs.get(1).decisions().stream().map(ChatModels.Decision::approve).toList());
        assertEquals(4, outcome.approved());
        assertEquals(1, outcome.denied());
        assertEquals(4, store.toolCalls(JOB).size(), "the denied one was never reserved");
    }

    @Test
    void aTargetTheServerNeverResolvedAndNoApprovedCallReturnedIsDenied() {
        // Round 1: an id nobody resolved is denied; the resolved company is approved.
        luna.script.add(n -> new ChatModels.AgentStep("resp_1", List.of(
                new ChatModels.ApprovalRequest("mcpr_guess", "company_read", Map.of("targets", List.of("KRX:999999"))),
                new ChatModels.ApprovalRequest("mcpr_known", "company_read", Map.of("targets", List.of("KRX:000660")))),
                null));
        // Round 2: a company the approved call returned is now reachable; one mixed with a guess is not.
        luna.script.add(n -> new ChatModels.AgentStep("resp_2", List.of(
                new ChatModels.ApprovalRequest("mcpr_related", "company_read", Map.of("targets", List.of("KRX:005930"))),
                new ChatModels.ApprovalRequest("mcpr_mixed", "company_read",
                        Map.of("targets", List.of("KRX:005930", "KRX:999999"))),
                new ChatModels.ApprovalRequest("mcpr_shape", "company_read", Map.of("targets", "KRX:005930"))),
                null));
        luna.script.add(n -> done());

        var outcome = run(steps(false));

        assertEquals(List.of(new ChatModels.Decision("mcpr_guess", false), new ChatModels.Decision("mcpr_known", true)),
                luna.inputs.get(1).decisions());
        assertEquals(List.of(new ChatModels.Decision("mcpr_related", true), new ChatModels.Decision("mcpr_mixed", false),
                new ChatModels.Decision("mcpr_shape", false)), luna.inputs.get(2).decisions());
        assertEquals(2, outcome.approved());
        assertEquals(3, outcome.denied());
        assertEquals(List.of("KRX:000660", "KRX:005930"),
                outcome.results().stream().map(result -> result.items().getFirst().id()).toList(),
                "only the reachable targets were read");
        assertEquals(2, luna.made.size());
    }

    @Test
    void aCallWithoutTargetsIsJudgedByTheArgumentCheckAlone() {
        assertTrue(ChatMcpAgent.targetsReachable(Map.of("limit", 5), java.util.Set.of()));
        assertTrue(ChatMcpAgent.targetsReachable(Map.of("targets", List.of("a")), java.util.Set.of("a")));
        var explicitNull = new java.util.HashMap<String, Object>();
        explicitNull.put("targets", null);
        assertFalse(ChatMcpAgent.targetsReachable(explicitNull, java.util.Set.of("a")));
        assertFalse(ChatMcpAgent.targetsReachable(Map.of("targets", List.of(1)), java.util.Set.of("1")));
    }

    @Test
    void withTimeForOnlyOneMoreStepTheAgentDeniesSoThatStepWrites() {
        luna.script.add(n -> held("mcpr_1", "company_read", Map.of("targets", List.of("KRX:000660"))));
        luna.script.add(n -> done());

        var outcome = run(steps(true));

        assertEquals(0, outcome.approved());
        assertEquals(1, outcome.denied());
        assertTrue(store.toolCalls(JOB).isEmpty());
        assertEquals(ANSWER, outcome.answer());
    }

    @Test
    void aRunThatEndedMeanwhileStopsTheLoop() {
        luna.script.add(n -> {
            store.cancel(JOB, NOW);
            return held("mcpr_1", "company_read", Map.of("targets", List.of("KRX:000660")));
        });
        assertThrows(ChatRunSuperseded.class, () -> run(steps(false)));
    }

    @Test
    void theGrantListsOnlyTheRunsToolsAndExpiresWithTheRun() {
        luna.script.add(n -> done());
        run(steps(false));
        var grant = grants.verify(luna.inputs.getFirst().grantToken()).orElseThrow();
        assertEquals(List.of(ChatCapability.COMPANY_READ), grant.tools());
        assertEquals(NOW.plusSeconds(60), grant.expiresAt());
        assertEquals(JOB, grant.jobId());
        assertEquals(ChatSendGrantsTest.RECIPIENT, luna.inputs.getFirst().recipient(),
                "each step names the recipient the results' send grants are checked for");
    }

    /** A Q05 requirement on one resolved company: the map-change read both execution paths serve. */
    private static final ChatModels.Router MAP_CHANGE = (current, bound) -> new ChatRouteDecision(List.of(
            new ChatRouteDecision.Requirement("r1", "지도 변경", true, Map.of(ChatQueryType.Q05, 0.9),
                    Map.of("graph.version.diff", 0.9), List.of("KRX:000660"), 0, null)), null);
    private static final ChatCitationSource CITATIONS = (id, version, asOf, trace) -> Optional.of(new Citation("article", id,
            "합성 근거", "art-1", "v1", null, null, 0, 5, "합성 기사", "합성 출처", NOW, "https://example.test"));

    /** The facts the verifier was given for the first section, one list per verification. */
    private static ChatModels.Verifier holdingVerifier(List<List<ChatModels.ServerFact>> observed) {
        return (current, sections, citations, facts) -> {
            observed.add(facts.forRequest(current, sections).getFirst());
            return new ChatSemanticVerdicts(List.of(new ChatSemanticVerdicts.Verdict("hold", "no")));
        };
    }

    @Test
    void theDirectAndTheAgentPathVerifyAgainstTheSameFacts() {
        var attached = executor.attach(JOB, 1).orElseThrow();
        List<List<ChatModels.ServerFact>> observed = new ArrayList<>();
        try (var direct = new OrchestratedChatEngine(MAP_CHANGE, (current, context) -> ANSWER, holdingVerifier(observed),
                registry, runner, CITATIONS, clock)) {
            assertInstanceOf(ChatEngineOutcome.Completed.class, direct.answer(attached.run(), attached.control()));
        }
        luna.script.add(n -> held("mcpr_diff", "graph_version_diff", Map.of("targets", List.of("KRX:000660"))));
        luna.script.add(n -> done());
        var agent = new ChatMcpAgent(luna, tools, grants, ChatSendGrantsTest.RECIPIENT, store, runner, circuit());
        try (var viaAgent = new OrchestratedChatEngine(MAP_CHANGE,
                (current, context) -> { throw new AssertionError("Q05 must use the agent"); }, holdingVerifier(observed),
                registry, runner, CITATIONS, clock, agent)) {
            assertInstanceOf(ChatEngineOutcome.Completed.class, viaAgent.answer(attached.run(), attached.control()));
        }
        assertEquals(2, observed.size());
        assertEquals(1, observed.getFirst().size());
        assertEquals(observed.getFirst(), observed.getLast(), "the same read gives the same fact on both paths");
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void aRepeatedIdenticalReadIsOneFactNotTwo(boolean withheld) {
        if (withheld) ChatSendGrantsTest.write(dir.resolve("chat-grants.json"), ChatSendGrantsTest.EVIDENCE_SOURCE);
        luna.script.add(n -> held("mcpr_1", "graph_version_diff", Map.of("targets", List.of("KRX:000660"))));
        luna.script.add(n -> {
            ChatSendGrantsTest.gate(dir);
            return held("mcpr_2", "graph_version_diff", Map.of("targets", List.of("KRX:000660")));
        });
        luna.script.add(n -> done());
        var attached = executor.attach(JOB, 1).orElseThrow();
        List<List<ChatModels.ServerFact>> observed = new ArrayList<>();
        var agent = new ChatMcpAgent(luna, tools, grants, ChatSendGrantsTest.RECIPIENT, store, runner, circuit());
        try (var engine = new OrchestratedChatEngine(MAP_CHANGE,
                (current, context) -> { throw new AssertionError("Q05 must use the agent"); }, holdingVerifier(observed),
                registry, runner, CITATIONS, clock, agent)) {
            engine.answer(attached.run(), attached.control());
        }
        assertEquals(2, store.keptToolResults(JOB, 1).size(), "the repeat is its own call, served from the first read");
        assertEquals(1, observed.getFirst().size());
        assertEquals(withheld, ((ChatModels.ComparisonFact) observed.getFirst().getFirst()).truncated());
    }

    @Test
    void aListTheSendGateCutIsRestoredAsTruncatedSoItNeverProvesAbsence() {
        luna.script.add(n -> held("mcpr_diff", "graph_version_diff", Map.of("targets", List.of("KRX:000660"))));
        luna.script.add(n -> done());
        var attached = executor.attach(JOB, 1).orElseThrow();
        List<List<ChatModels.ServerFact>> observed = new ArrayList<>();
        var agent = new ChatMcpAgent(luna, tools, grants, ChatSendGrantsTest.RECIPIENT, store, runner, circuit());
        try (var engine = new OrchestratedChatEngine(MAP_CHANGE,
                (current, context) -> { throw new AssertionError("Q05 must use the agent"); }, holdingVerifier(observed),
                registry, runner, CITATIONS, clock, agent)) {
            engine.answer(attached.run(), attached.control());
        }
        var kept = store.keptToolResults(JOB, 1).getFirst();
        assertFalse(runner.restore(attached.run(), List.of(kept)).getFirst().truncated());

        var envelope = (ObjectNode) mapper.readTree(kept.result());
        envelope.putObject("withheld").put("reason", "source_grant_denied").put("items", 0).put("evidenceIds", 1)
                .put("paths", 0);
        assertFalse(restored(attached, kept, envelope).truncated(), "withheld evidence leaves the change list whole");
        ((ObjectNode) envelope.get("withheld")).put("items", 1);
        assertTrue(restored(attached, kept, envelope).truncated(), "a withheld change leaves the list incomplete");
        var cachedEnvelope = envelope.deepCopy();
        cachedEnvelope.remove("withheld");
        cachedEnvelope.put("toolCallId", "cached-1").put("cachedFrom", kept.toolCallId());
        var cached = withEnvelope(kept, cachedEnvelope);
        cachedEnvelope.put("toolCallId", "cached-2").put("cachedFrom", "cached-1");
        var repeated = withEnvelope(kept, cachedEnvelope);
        for (String incomplete : List.of("withheld", "truncated", "complete")) {
            var origin = envelope.deepCopy();
            if (!incomplete.equals("withheld")) origin.remove("withheld");
            origin.put("truncated", incomplete.equals("truncated"));
            var restored = runner.restore(attached.run(), List.of(repeated, cached, withEnvelope(kept, origin)));
            assertEquals(List.of(!incomplete.equals("complete"), !incomplete.equals("complete"),
                    !incomplete.equals("complete")), restored.stream().map(ChatToolResult::truncated).toList());
        }
        assertThrows(ChatModels.Failure.class, () -> runner.restore(attached.run(), List.of(repeated, cached)));
        cachedEnvelope.put("toolCallId", kept.toolCallId()).put("cachedFrom", "cached-2");
        assertThrows(ChatModels.Failure.class, () -> runner.restore(attached.run(),
                List.of(repeated, cached, withEnvelope(kept, cachedEnvelope))));
        envelope.put("unknown", true);
        assertThrows(ChatModels.Failure.class, () -> restored(attached, kept, envelope));
    }

    private ChatToolResult restored(ChatJobExecutor.Attached attached, ChatKeptToolResult kept,
            ObjectNode envelope) {
        return runner.restore(attached.run(), List.of(withEnvelope(kept, envelope))).getFirst();
    }

    private ChatKeptToolResult withEnvelope(ChatKeptToolResult kept, ObjectNode envelope) {
        return new ChatKeptToolResult(kept.jobId(), kept.memberId(), kept.attemptNo(),
                envelope.get("toolCallId").asString(), kept.capabilityId(), kept.requestMeta(), kept.inputDigest(),
                mapper.writeValueAsString(envelope));
    }

    @Test
    void approvedComparisonSurvivesLedgerRehydrationAndBindsOnlyToThisRun() {
        luna.script.add(n -> held("mcpr_diff", "graph_version_diff",
                Map.of("targets", List.of("KRX:000660"), "limit", 7)));
        luna.script.add(n -> done());
        var attached = executor.attach(JOB, 1).orElseThrow();
        var run = attached.run();
        var agent = new ChatMcpAgent(luna, tools, grants, ChatSendGrantsTest.RECIPIENT, store, runner, circuit());
        List<List<ChatModels.ServerFact>> facts = new ArrayList<>();
        try (var engine = new OrchestratedChatEngine(MAP_CHANGE,
                (current, context) -> { throw new AssertionError("Q05 must use the agent"); }, holdingVerifier(facts),
                registry, runner, CITATIONS, clock, agent)) {
            var result = engine.answer(run, attached.control());
            var outcome = assertInstanceOf(ChatEngineOutcome.Completed.class, result, result.toString());
            assertEquals("insufficient_evidence", outcome.result().outcome(), "canonical facts never bypass verification");
        }
        List<ChatModels.ServerFact> observed = facts.getFirst();
        assertEquals(1, luna.made.size());
        assertEquals(1, observed.size(), "one ledger call supplies one comparison, never membership");
        var fact = assertInstanceOf(ChatModels.ComparisonFact.class, observed.getFirst());
        assertEquals("r1", fact.requirementId());
        assertEquals("gv-0", fact.fromVersion());
        assertEquals("gv-1", fact.toVersion());
        assertEquals(run.context().asOf(), fact.asOf());
        assertEquals(List.of("KRX:000660"), fact.targetIds());
        assertEquals(7, fact.evidenceLimit());
        assertEquals(List.of(new ChatModels.GraphChange("iss-new", "issue", "공급 계약", "added")), fact.changes());

        var kept = store.keptToolResults(JOB, 1).getFirst();
        var forged = List.of(
                new ChatKeptToolResult("other-job", kept.memberId(), 1, kept.toolCallId(), kept.capabilityId(),
                        kept.requestMeta(), kept.inputDigest(), kept.result()),
                new ChatKeptToolResult(JOB, "other-member", 1, kept.toolCallId(), kept.capabilityId(),
                        kept.requestMeta(), kept.inputDigest(), kept.result()),
                new ChatKeptToolResult(JOB, kept.memberId(), 2, kept.toolCallId(), kept.capabilityId(),
                        kept.requestMeta(), kept.inputDigest(), kept.result()),
                new ChatKeptToolResult(JOB, kept.memberId(), 1, "other-call", kept.capabilityId(),
                        kept.requestMeta(), kept.inputDigest(), kept.result()),
                new ChatKeptToolResult(JOB, kept.memberId(), 1, kept.toolCallId(), kept.capabilityId(),
                        kept.requestMeta().replace("gv-1", "stale"), kept.inputDigest(), kept.result()),
                new ChatKeptToolResult(JOB, kept.memberId(), 1, kept.toolCallId(), kept.capabilityId(),
                        kept.requestMeta().replace("KRX:000660", "NASDAQ:NVDA"), kept.inputDigest(), kept.result()),
                new ChatKeptToolResult(JOB, kept.memberId(), 1, kept.toolCallId(), kept.capabilityId(),
                        kept.requestMeta().replace("2026-10-27", "2026-10-26"), kept.inputDigest(), kept.result()));
        var cachedEnvelope = (ObjectNode) mapper.readTree(kept.result());
        cachedEnvelope.put("toolCallId", "cached-foreign").put("cachedFrom", kept.toolCallId());
        var cached = withEnvelope(kept, cachedEnvelope);
        for (var wrong : forged) {
            assertThrows(ChatModels.Failure.class, () -> runner.restore(run, List.of(wrong)));
            assertThrows(ChatModels.Failure.class, () -> runner.restore(run, List.of(cached, wrong)));
        }
    }

    private static ChatTool tool(ChatCapability capability) {
        return new ChatTool() {
            @Override
            public ChatCapability capability() {
                return capability;
            }

            @Override
            public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
                if (capability == ChatCapability.GRAPH_VERSION_DIFF) {
                    return new ChatToolOutput("gv-0.." + scope.graphVersionId(),
                            List.of(new ChatToolItem("iss-new", "issue", "[새로 생김] 공급 계약",
                                    List.of("KRX:000660"), List.of("ev-1"))), List.of("ev-1"), false, false);
                }
                String id = request.targets().getFirst();
                // Each company relates to Samsung Electronics, which a later round may then read.
                return new ChatToolOutput(scope.graphVersionId(),
                        List.of(new ChatToolItem(id, "company", "SK하이닉스", List.of(id, "KRX:005930"), List.of("ev-1"))),
                        List.of("ev-1"), false, false);
            }
        };
    }
}
