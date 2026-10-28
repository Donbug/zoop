package com.zoop.chat.mcp;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.chat.executor.ChatEngine;
import com.zoop.chat.executor.ChatJobExecutor;
import com.zoop.chat.executor.ChatRunSuperseded;
import com.zoop.chat.executor.MemoryChatStore;
import com.zoop.chat.executor.NoChatTransactions;
import com.zoop.chat.orchestrator.ChatAgentPath;
import com.zoop.chat.orchestrator.ChatGeneratedAnswer;
import com.zoop.chat.orchestrator.ChatModels;
import com.zoop.chat.repository.ChatJobRow;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatTool;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolOutput;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolRequest;
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
import java.util.function.Function;
import java.util.function.Supplier;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import tools.jackson.databind.json.JsonMapper;

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
    private ChatJobExecutor executor;
    private ChatMcpTools tools;
    private ChatMcpGrants grants;
    private Luna luna;

    @BeforeEach
    void setUp() {
        store = new MemoryChatStore();
        var registry = new ChatToolRegistry(List.of(tool(ChatCapability.COMPANY_READ), tool(ChatCapability.ISSUE_READ)));
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
        assertTrue(store.start(JOB, "owner-1", NOW.plusSeconds(45), NOW.plusSeconds(60), attempts, NOW));
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

    private ChatAgentPath.Outcome run(ChatAgentPath.Steps steps) {
        var agent = new ChatMcpAgent(luna, tools, grants, store, mapper);
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
        assertEquals(NOW.plusSeconds(45), grant.expiresAt());
        assertEquals(JOB, grant.jobId());
    }

    private static ChatTool tool(ChatCapability capability) {
        return new ChatTool() {
            @Override
            public ChatCapability capability() {
                return capability;
            }

            @Override
            public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
                String id = request.targets().getFirst();
                // Each company relates to Samsung Electronics, which a later round may then read.
                return new ChatToolOutput(scope.graphVersionId(),
                        List.of(new ChatToolItem(id, "company", "SK하이닉스", List.of(id, "KRX:005930"), List.of("ev-1"))),
                        List.of("ev-1"), false, false);
            }
        };
    }
}
