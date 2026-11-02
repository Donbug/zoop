package com.zoop.chat.mcp;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.chat.executor.ChatEngine;
import com.zoop.chat.executor.ChatJobExecutor;
import com.zoop.chat.executor.MemoryChatStore;
import com.zoop.chat.executor.NoChatTransactions;
import com.zoop.chat.model.ChatEvalSetTest;
import com.zoop.chat.repository.ChatJobRow;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolRequest;
import com.zoop.chat.tool.ChatToolResult;
import com.zoop.chat.tool.ChatToolRunner;
import com.zoop.chat.tool.ChatToolRunners;
import io.modelcontextprotocol.common.McpTransportContext;
import io.modelcontextprotocol.spec.McpSchema;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import tools.jackson.databind.json.JsonMapper;

/**
 * D-AI-02: the same read gives the same result whichever path asks for it. The real read tools run on the synthetic graph
 * fixture of the evaluation set, once as the server's plan calls them and once as a model does through {@code /mcp}: approved,
 * called, and read back from the ledger the way the answer is checked. Only the send gate stands between, and it grants all.
 */
class ChatMcpDirectParityTest {
    private static final Instant NOW = ChatMcpGrantsTest.NOW;
    private static final String GRAPH = "fixture-2026-10-08";
    private static final String HYNIX = "KRX:000660";
    private static final String NVIDIA = "NASDAQ:NVDA";
    private static final String ISSUE = "iss-fixture-hbm-supply";
    private static final String EVIDENCE = "ev-912843a071ee90c12ee7e909c65f06ce748d2a35c7c29c6c871faac130e4f395";
    private static final String NO_SELECTION = "{\"contextIds\":[],\"evidenceIds\":[],\"evidencePool\":[]}";
    private static final int LIMIT = ChatToolRequest.MAX_LIMIT;

    @TempDir
    Path dir;

    private final JsonMapper mapper = JsonMapper.builder().build();
    private final Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);
    private MemoryChatStore store;
    private ChatToolRunner runner;
    private ChatJobExecutor executor;
    private ChatMcpTools tools;
    private ChatMcpGrants grants;

    @BeforeEach
    void setUp() {
        var registry = ChatEvalSetTest.world().registry();
        store = new MemoryChatStore();
        runner = ChatToolRunners.withAmpleTime(registry);
        executor = new ChatJobExecutor(store, store,
                new StaticListableBeanFactory(Map.of()).getBeanProvider(ChatEngine.class), mapper, clock,
                new NoChatTransactions());
        tools = new ChatMcpTools(registry, runner, executor, ChatSendGrantsTest.gate(dir), mapper);
        grants = ChatMcpGrantsTest.grants("k1", "k1=" + ChatMcpGrantsTest.KEY_A, NOW);
    }

    @AfterEach
    void tearDown() {
        runner.close();
    }

    private void running(String job, String selection) {
        running(job, selection, GRAPH);
    }

    private void running(String job, String selection, String graph) {
        String attempts = "[{\"n\":1,\"mode\":\"run\",\"requestKey\":\"" + job + "\",\"status\":\"running\","
                + "\"ownerToken\":\"owner-1\"}]";
        String context = "{\"items\":[],\"evidenceCount\":0,\"period\":null,\"asOf\":null,\"graphVersion\":\"" + graph + "\"}";
        store.add(new ChatJobRow(job, "conv-" + job, "member-a", 1, "질문", "a".repeat(64), NOW, context, selection, List.of(),
                graph, "queued", null, null, null, null, 0, null, null, 0, attempts, NOW, NOW, null));
        assertTrue(store.start(job, "owner-1", NOW.plusSeconds(60), NOW.plusSeconds(60), attempts, NOW));
    }

    private ChatToolResult direct(String job, ChatToolRequest request) {
        var attached = executor.attach(job, 1).orElseThrow();
        return runner.runStage(attached.run(), attached.control(), 1, List.of(request)).getFirst();
    }

    private ChatToolResult viaMcp(String job, ChatCapability capability, Map<String, Object> arguments) {
        var attached = executor.attach(job, 1).orElseThrow();
        String name = ChatMcpTools.name(capability);
        assertTrue(tools.approve(attached, name, arguments, List.of("r1")).approved(), name);
        var grant = grants.verify(grants.issue(attached.run(), List.of(capability))).orElseThrow();
        Map<String, Object> called = new HashMap<>(arguments);
        called.put(ChatMcpTools.REQUIREMENT_IDS, List.of("r1"));
        var result = tools.call(McpTransportContext.create(Map.of(ChatMcpTools.GRANT, grant)),
                new McpSchema.CallToolRequest(name, called));
        assertTrue(!Boolean.TRUE.equals(result.isError()), result.toString());
        return runner.restore(attached.run(), store.keptToolResults(job, 1)).getFirst();
    }

    private static void assertSameRead(ChatToolResult direct, ChatToolResult mcp) {
        assertTrue(direct.succeeded(), String.valueOf(direct.error()));
        assertEquals(direct.capabilityId(), mcp.capabilityId());
        assertEquals(direct.dataVersion(), mcp.dataVersion());
        assertEquals(direct.items(), mcp.items());
        assertEquals(direct.evidenceIds(), mcp.evidenceIds());
        assertEquals(direct.paths(), mcp.paths());
        assertEquals(direct.truncated(), mcp.truncated());
        assertEquals(direct.selectionRecords(), mcp.selectionRecords());
    }

    static Stream<Arguments> reads() {
        return Stream.of(
                Arguments.of(ChatCapability.COMPANY_READ, List.of(HYNIX)),
                Arguments.of(ChatCapability.ISSUE_READ, List.of(ISSUE)),
                Arguments.of(ChatCapability.ISSUE_READ, List.of(HYNIX)),
                Arguments.of(ChatCapability.EVIDENCE_RESOLVE, List.of(EVIDENCE)),
                Arguments.of(ChatCapability.GRAPH_PATH_READ, List.of(NVIDIA, HYNIX)));
    }

    @ParameterizedTest
    @MethodSource("reads")
    void aReadGivesTheSameResultOnBothPaths(ChatCapability capability, List<String> targets) {
        running("job-direct1", NO_SELECTION);
        running("job-mcp0001", NO_SELECTION);

        var direct = direct("job-direct1", new ChatToolRequest(capability.id(), targets, LIMIT));
        var mcp = viaMcp("job-mcp0001", capability, Map.of("targets", targets));

        assertSameRead(direct, mcp);
        assertTrue(!direct.items().isEmpty() || !direct.paths().isEmpty(), "the case must read something to compare");
    }

    @Test
    void aReadWithoutTargetsTakesTheSameServerTargetsOnBothPaths() {
        running("job-direct1", NO_SELECTION);
        running("job-mcp0001", NO_SELECTION);
        var diff = ChatCapability.GRAPH_VERSION_DIFF;

        assertSameRead(direct("job-direct1", new ChatToolRequest(diff.id(), diff.untargeted(), LIMIT)),
                viaMcp("job-mcp0001", diff, Map.of()));
    }

    @Test
    void aPathStepNamesAnEdgeTheMapHas() {
        running("job-mcp0001", NO_SELECTION);

        var read = viaMcp("job-mcp0001", ChatCapability.GRAPH_PATH_READ, Map.of("targets", List.of(NVIDIA, HYNIX)));

        var edges = read.items().stream().filter(i -> "edge".equals(i.kind())).map(i -> i.id()).toList();
        var steps = read.paths().stream().flatMap(p -> p.steps().stream()).map(s -> s.edgeId()).toList();
        assertFalse(steps.isEmpty());
        assertTrue(edges.containsAll(steps), "a focus_relation action opens these ids on the map: " + steps + " in " + edges);
    }

    private String digest(String job, ChatToolRequest request) {
        return runner.reservation(executor.attach(job, 1).orElseThrow().run(), request, ChatMcpTools.VIA).inputDigest();
    }

    @Test
    void requestsOfAnotherScopeVersionOrPeriodAreNeverTheSameCall() {
        running("job-mcp0001", NO_SELECTION);
        running("job-mcp0002", NO_SELECTION, "fixture-2026-10-01");
        var company = ChatCapability.COMPANY_READ.id();
        var plain = new ChatToolRequest(company, List.of(HYNIX), LIMIT);
        String read = digest("job-mcp0001", plain);

        assertEquals(read, digest("job-mcp0001", new ChatToolRequest(company, List.of(HYNIX), LIMIT)), "the same call");
        assertNotEquals(read, digest("job-mcp0002", plain), "another graph version");
        assertNotEquals(read, digest("job-mcp0001", new ChatToolRequest(company, List.of(HYNIX), LIMIT, List.of(EVIDENCE))),
                "another evidence scope");
        assertNotEquals(read, digest("job-mcp0001", new ChatToolRequest(company, List.of(HYNIX), LIMIT, null, NOW)),
                "another period");
        assertNotEquals(read, digest("job-mcp0001", new ChatToolRequest(company, List.of(HYNIX), 5)), "another limit");
    }

    @Test
    void aKeptResultIsNeverReusedAcrossJobs() {
        running("job-mcp0001", NO_SELECTION);
        running("job-mcp0002", NO_SELECTION);
        var company = ChatCapability.COMPANY_READ;

        viaMcp("job-mcp0001", company, Map.of("targets", List.of(HYNIX)));
        viaMcp("job-mcp0002", company, Map.of("targets", List.of(HYNIX)));

        assertEquals(1, store.toolCalls("job-mcp0002").size(), "the second job made and recorded its own read");
        assertEquals(1, store.keptToolResults("job-mcp0002", 1).size());
    }

    @Test
    void theFixedDocumentsAreTheSameOnBothPaths() {
        running("job-direct1", NO_SELECTION);
        running("job-mcp0001", NO_SELECTION);
        var policy = ChatCapability.ZOOP_POLICY_READ;

        assertSameRead(direct("job-direct1", new ChatToolRequest(policy.id(), policy.documents(), LIMIT)),
                viaMcp("job-mcp0001", policy, Map.of()));
    }

    @Test
    void evidenceTheMemberNarrowedToBoundsBothPathsAlike() {
        String narrowed = "{\"contextIds\":[\"" + ISSUE + "\"],\"evidenceIds\":[\"" + EVIDENCE + "\"],\"evidencePool\":[\""
                + EVIDENCE + "\"]}";
        running("job-direct1", narrowed);
        running("job-mcp0001", narrowed);
        var issue = ChatCapability.ISSUE_READ;

        var direct = direct("job-direct1", new ChatToolRequest(issue.id(), List.of(ISSUE), LIMIT, List.of(EVIDENCE)));
        var mcp = viaMcp("job-mcp0001", issue, Map.of("targets", List.of(ISSUE)));

        assertSameRead(direct, mcp);
        assertEquals(List.of(EVIDENCE), mcp.evidenceIds());
    }
}
