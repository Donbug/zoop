package com.zoop.chat.mcp;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.chat.executor.ChatEngine;
import com.zoop.chat.executor.ChatJobExecutor;
import com.zoop.chat.executor.MemoryChatStore;
import com.zoop.chat.executor.NoChatTransactions;
import com.zoop.chat.repository.ChatJobRow;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatTool;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolOutput;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolRequest;
import com.zoop.chat.tool.ChatToolRunner;
import com.zoop.chat.tool.ChatToolScope;
import io.modelcontextprotocol.server.McpStatelessSyncServer;
import io.modelcontextprotocol.server.transport.HttpServletStatelessServerTransport;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * D-AI-02: the chat MCP endpoint over its real servlet transport and MCP server, in front of a running job of the memory
 * store. Synthetic jobs and tools only; no model and no network.
 */
class ChatMcpEndpointTest {
    private static final Instant NOW = ChatMcpGrantsTest.NOW;
    private static final String CONTEXT = "{\"items\":[],\"evidenceCount\":0,\"period\":null,"
            + "\"asOf\":\"2026-10-27T00:00:00Z\",\"graphVersion\":\"gv-1\"}";
    private static final String SELECTION = "{\"contextIds\":[],\"evidenceIds\":[],\"evidencePool\":[]}";

    private final JsonMapper mapper = JsonMapper.builder().build();
    private final Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);
    private final List<ChatToolRequest> companyReads = Collections.synchronizedList(new ArrayList<>());
    private MemoryChatStore store;
    private ChatToolRunner runner;
    private ChatMcpGrants grants;
    private ChatMcpAccessFilter filter;
    private HttpServletStatelessServerTransport transport;
    private McpStatelessSyncServer server;

    @BeforeEach
    void setUp() {
        store = new MemoryChatStore();
        var registry = new ChatToolRegistry(List.of(tool(ChatCapability.COMPANY_READ, companyReads),
                tool(ChatCapability.GRAPH_PATH_READ, new ArrayList<>()),
                tool(ChatCapability.PORTFOLIO_SCOPE_READ, new ArrayList<>())));
        runner = new ChatToolRunner(registry);
        var executor = new ChatJobExecutor(store, store,
                new StaticListableBeanFactory(Map.of()).getBeanProvider(ChatEngine.class), mapper, clock,
                new NoChatTransactions());
        grants = ChatMcpGrantsTest.grants("k1", "k1=" + ChatMcpGrantsTest.KEY_A, NOW);
        filter = new ChatMcpAccessFilter(grants, clock);
        transport = ChatMcpConfiguration.transport(mapper);
        server = ChatMcpConfiguration.server(transport, new ChatMcpTools(registry, runner, executor, mapper), mapper);
        running("job-00001", 1);
    }

    @AfterEach
    void tearDown() {
        server.close();
        runner.close();
    }

    @Test
    void withoutAValidBearerGrantNothingIsRead() throws Exception {
        var none = post(null, ping());
        assertEquals(401, none.getStatus());
        assertEquals("Bearer", none.getHeader("WWW-Authenticate"));
        String token = token("job-00001", 1, ChatCapability.COMPANY_READ);
        assertEquals(401, post(token.substring(0, token.length() - 3), ping()).getStatus());
        assertEquals(401, post("zmcp1.k9.e30.AAAA", ping()).getStatus());
        var expired = new ChatMcpAccessFilter(ChatMcpGrantsTest.grants("k1", "k1=" + ChatMcpGrantsTest.KEY_A,
                NOW.plusSeconds(60)), clock);
        assertEquals(401, post(expired, token, ping()).getStatus());
        assertTrue(store.toolCalls("job-00001").isEmpty());
    }

    @Test
    void aBrowserOriginIsRefusedEvenWithAToken() throws Exception {
        var request = request(token("job-00001", 1, ChatCapability.COMPANY_READ), ping());
        request.addHeader("Origin", "https://example.com");
        var response = new MockHttpServletResponse();
        filter.doFilter(request, response, (req, res) -> transport.service(req, res));
        assertEquals(403, response.getStatus());
    }

    @Test
    void initializeAnswersAsAToolsOnlyServer() throws Exception {
        JsonNode result = rpc(token("job-00001", 1, ChatCapability.COMPANY_READ), """
                {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18",
                 "capabilities":{},"clientInfo":{"name":"test","version":"1"}}}""").path("result");
        assertEquals("zoop-chat", result.path("serverInfo").path("name").asString());
        assertTrue(result.path("capabilities").has("tools"));
        assertFalse(result.path("capabilities").has("resources"));
    }

    @Test
    void toolsListShowsOnlyTheGrantedToolsAndNeverTheMemberScopeRead() throws Exception {
        JsonNode tools = rpc(token("job-00001", 1, ChatCapability.COMPANY_READ), list()).path("result").path("tools");
        assertEquals(1, tools.size());
        JsonNode company = tools.get(0);
        assertEquals("company_read", company.path("name").asString());
        assertEquals(false, company.path("inputSchema").path("additionalProperties").asBoolean(true));
        assertEquals("targets", company.path("inputSchema").path("required").get(0).asString());
        assertTrue(company.path("annotations").path("readOnlyHint").asBoolean());

        JsonNode both = rpc(token("job-00001", 1, ChatCapability.COMPANY_READ, ChatCapability.GRAPH_PATH_READ), list())
                .path("result").path("tools");
        assertEquals(List.of("company_read", "graph_path_read"),
                both.valueStream().map(t -> t.path("name").asString()).toList());
    }

    @Test
    void aGrantedCallReadsThroughTheRunnerAndIsRecordedOnTheJobsLedger() throws Exception {
        JsonNode result = rpc(token("job-00001", 1, ChatCapability.COMPANY_READ),
                call("company_read", "{\"targets\":[\"co-1\"],\"limit\":5}")).path("result");

        assertFalse(result.path("isError").asBoolean(true), result.toString());
        JsonNode read = result.path("structuredContent");
        assertEquals("company.read", read.path("capabilityId").asString());
        assertEquals("gv-1", read.path("dataVersion").asString());
        assertEquals("co-1", read.path("items").get(0).path("id").asString());
        assertEquals("ev-1", read.path("evidenceIds").get(0).asString());
        assertEquals(read.toString(), mapper.readTree(result.path("content").get(0).path("text").asString()).toString());

        assertEquals(1, companyReads.size());
        assertEquals(List.of("co-1"), companyReads.getFirst().targets());
        assertEquals(5, companyReads.getFirst().limit());
        var calls = store.toolCalls("job-00001");
        assertEquals(1, calls.size());
        assertEquals("succeeded", calls.getFirst().status);
        assertEquals(read.path("toolCallId").asString(), calls.getFirst().row.toolCallId());
        JsonNode meta = mapper.readTree(calls.getFirst().row.requestMeta());
        assertEquals("mcp", meta.path("via").asString());
        assertEquals("gv-1", meta.path("graphVersion").asString());
        assertEquals("2026-10-27T00:00:00Z", meta.path("asOf").asString());
    }

    @Test
    void refusedCallsAreToolErrorsAndReadNothing() throws Exception {
        String company = token("job-00001", 1, ChatCapability.COMPANY_READ);
        assertEquals("tool_not_granted", error(rpc(company, call("graph_path_read", "{\"targets\":[\"co-1\",\"co-2\"]}"))));
        // The member scope read is not an MCP tool at all, and dotted ids are not tool names: the protocol says unknown.
        assertEquals(-32602, rpc(company, call("portfolio_scope_read", "{}")).path("error").path("code").asInt());
        assertEquals(-32602, rpc(company, call("company.read", "{\"targets\":[\"co-1\"]}")).path("error").path("code")
                .asInt());
        for (String arguments : List.of("{\"targets\":[\"co-1\"],\"memberId\":\"member-b\"}", "{\"targets\":[]}",
                "{\"targets\":[\"a\",\"b\",\"c\",\"d\",\"e\",\"f\"]}", "{\"targets\":[\"co-1\",\"co-1\"]}",
                "{\"targets\":[\"co-1\"],\"limit\":21}", "{\"targets\":[\"co-1\"],\"limit\":1.5}", "{\"targets\":\"co-1\"}",
                "{}")) {
            JsonNode refused = rpc(company, call("company_read", arguments));
            assertTrue(isToolError(refused), arguments + " -> " + refused);
        }
        assertTrue(companyReads.isEmpty());
        assertTrue(store.toolCalls("job-00001").isEmpty());
    }

    @Test
    void aGrantForAnEndedOrOtherAttemptReadsNothing() throws Exception {
        assertEquals("run_not_active", error(rpc(token("job-00001", 2, ChatCapability.COMPANY_READ),
                call("company_read", "{\"targets\":[\"co-1\"]}"))));
        String token = token("job-00001", 1, ChatCapability.COMPANY_READ);
        store.cancel("job-00001", NOW);
        assertEquals("run_not_active", error(rpc(token, call("company_read", "{\"targets\":[\"co-1\"]}"))));
        assertTrue(companyReads.isEmpty());
    }

    @Test
    void theAttemptsCallLimitHoldsForMcpCallsToo() throws Exception {
        String token = token("job-00001", 1, ChatCapability.COMPANY_READ);
        for (int i = 0; i < 12; i++) {
            assertFalse(isToolError(rpc(token, call("company_read", "{\"targets\":[\"co-" + i + "\"]}"))));
        }
        assertEquals("tool_budget_exhausted", error(rpc(token, call("company_read", "{\"targets\":[\"co-99\"]}"))));
        assertEquals(12, store.toolCalls("job-00001").size());
    }

    @Test
    void aTokenMakesAtMostThirtyRequestsAMinute() throws Exception {
        String token = token("job-00001", 1, ChatCapability.COMPANY_READ);
        for (int i = 0; i < ChatMcpAccessFilter.MAX_PER_MINUTE; i++) assertEquals(200, post(token, ping()).getStatus());
        var limited = post(token, ping());
        assertEquals(429, limited.getStatus());
        assertEquals("60", limited.getHeader("Retry-After"));
        assertEquals(200, post(token("job-00001", 1, ChatCapability.GRAPH_PATH_READ), ping()).getStatus());
    }

    @Test
    void aRequestOverSixtyFourKibibytesIsRefused() throws Exception {
        String big = "{\"jsonrpc\":\"2.0\",\"id\":9,\"method\":\"ping\",\"params\":{\"pad\":\""
                + "x".repeat(ChatMcpConfiguration.MAX_REQUEST_BYTES) + "\"}}";
        assertEquals(413, post(token("job-00001", 1, ChatCapability.COMPANY_READ), big).getStatus());
    }

    private void running(String jobId, int attemptNo) {
        String attempts = "[{\"n\":" + attemptNo + ",\"mode\":\"run\",\"requestKey\":\"" + jobId
                + "\",\"status\":\"running\",\"ownerToken\":\"owner-" + jobId + "\"}]";
        store.add(new ChatJobRow(jobId, "conv-0001", "member-a", 1, "삼성전자 최근 사건", "a".repeat(64), NOW, CONTEXT,
                SELECTION, List.of(), "gv-1", "queued", null, null, null, null, 0, null, null, 0, attempts, NOW, NOW, null));
        assertTrue(store.start(jobId, "owner-" + jobId, NOW.plusSeconds(45), NOW.plusSeconds(60), attempts, NOW));
    }

    private String token(String jobId, int attemptNo, ChatCapability... tools) {
        return grants.issue(ChatMcpGrantsTest.run(jobId, attemptNo), List.of(tools));
    }

    private JsonNode rpc(String token, String body) throws Exception {
        var response = post(token, body);
        assertEquals(200, response.getStatus(), response.getContentAsString());
        return mapper.readTree(response.getContentAsString());
    }

    private MockHttpServletResponse post(String token, String body) throws Exception {
        return post(filter, token, body);
    }

    private MockHttpServletResponse post(ChatMcpAccessFilter gate, String token, String body) throws Exception {
        var response = new MockHttpServletResponse();
        gate.doFilter(request(token, body), response, (req, res) -> transport.service(req, res));
        return response;
    }

    private static MockHttpServletRequest request(String token, String body) {
        var request = new MockHttpServletRequest("POST", ChatMcpConfiguration.PATH);
        request.setContentType("application/json");
        request.setCharacterEncoding("UTF-8");
        request.addHeader("Accept", "application/json, text/event-stream");
        if (token != null) request.addHeader("Authorization", "Bearer " + token);
        request.setContent(body.getBytes(StandardCharsets.UTF_8));
        return request;
    }

    private static String ping() {
        return "{\"jsonrpc\":\"2.0\",\"id\":7,\"method\":\"ping\"}";
    }

    private static String list() {
        return "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/list\",\"params\":{}}";
    }

    private static String call(String name, String arguments) {
        return "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"" + name
                + "\",\"arguments\":" + arguments + "}}";
    }

    /** A tool error result, or the protocol error the SDK answers for input its schema check refuses. */
    private static boolean isToolError(JsonNode response) {
        return response.path("result").path("isError").asBoolean(false) || response.has("error");
    }

    private static String error(JsonNode response) {
        assertTrue(response.path("result").path("isError").asBoolean(false), response.toString());
        return response.path("result").path("structuredContent").path("error").asString();
    }

    private static ChatTool tool(ChatCapability capability, List<ChatToolRequest> seen) {
        return new ChatTool() {
            @Override
            public ChatCapability capability() {
                return capability;
            }

            @Override
            public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
                seen.add(request);
                String id = request.targets().getFirst();
                return new ChatToolOutput(scope.graphVersionId(),
                        List.of(new ChatToolItem(id, "company", "삼성전자", List.of(id), List.of("ev-1"))),
                        List.of("ev-1"), false, false);
            }
        };
    }
}
