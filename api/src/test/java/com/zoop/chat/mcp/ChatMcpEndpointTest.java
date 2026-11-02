package com.zoop.chat.mcp;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.chat.executor.ChatEngine;
import com.zoop.chat.executor.ChatJobExecutor;
import com.zoop.chat.executor.ChatRunControl;
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
import java.nio.file.Path;
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
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * D-AI-02: the chat MCP endpoint over its real servlet transport and MCP server, in front of a running job of the memory
 * store. A grant opens the door; only a call the server approved (reserved) runs, once. Synthetic jobs and tools only; no
 * model and no network.
 */
class ChatMcpEndpointTest {
    private static final Instant NOW = ChatMcpGrantsTest.NOW;
    private static final String JOB = "job-00001";
    private static final String CONTEXT = "{\"items\":[],\"evidenceCount\":0,\"period\":null,"
            + "\"asOf\":\"2026-10-27T00:00:00Z\",\"graphVersion\":\"gv-1\"}";
    private static final String SELECTION = "{\"contextIds\":[],\"evidenceIds\":[],\"evidencePool\":[]}";

    @TempDir
    Path dir;

    private final JsonMapper mapper = JsonMapper.builder().build();
    private final Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);
    private final List<ChatToolRequest> companyReads = Collections.synchronizedList(new ArrayList<>());
    /** When set, a company read waits for it: an identical request can arrive while the first is still reading. */
    private static volatile java.util.concurrent.CountDownLatch companyGate;
    private MemoryChatStore store;
    private ChatToolRunner runner;
    private ChatJobExecutor executor;
    private ChatMcpTools tools;
    private ChatMcpGrants grants;
    private ChatMcpAccessFilter filter;
    private HttpServletStatelessServerTransport transport;
    private McpStatelessSyncServer server;

    @BeforeEach
    void setUp() {
        store = new MemoryChatStore();
        var registry = new ChatToolRegistry(List.of(tool(ChatCapability.COMPANY_READ, companyReads, "삼성전자"),
                // Just under one result's 256 KiB: four of them fit the job's 1 MiB of kept results, five do not.
                tool(ChatCapability.GRAPH_PATH_READ, new ArrayList<>(), "a".repeat(250_000)),
                tool(ChatCapability.ISSUE_READ, new ArrayList<>(), "가".repeat(ChatMcpTools.MAX_RESULT_BYTES)),
                tool(ChatCapability.PORTFOLIO_SCOPE_READ, new ArrayList<>(), "내 종목")));
        runner = new ChatToolRunner(registry);
        executor = new ChatJobExecutor(store, store,
                new StaticListableBeanFactory(Map.of()).getBeanProvider(ChatEngine.class), mapper, clock,
                new NoChatTransactions());
        grants = ChatMcpGrantsTest.grants("k1", "k1=" + ChatMcpGrantsTest.KEY_A, NOW);
        filter = new ChatMcpAccessFilter(grants, clock);
        transport = ChatMcpConfiguration.transport(mapper);
        tools = new ChatMcpTools(registry, runner, executor, ChatSendGrantsTest.gate(dir), mapper);
        server = ChatMcpConfiguration.server(transport, tools, mapper);
        running(JOB, 1);
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
        String token = token(ChatCapability.COMPANY_READ);
        assertEquals(401, post(token.substring(0, token.length() - 3), ping()).getStatus());
        assertEquals(401, post("zmcp1.k9.e30.AAAA", ping()).getStatus());
        var expired = new ChatMcpAccessFilter(ChatMcpGrantsTest.grants("k1", "k1=" + ChatMcpGrantsTest.KEY_A,
                NOW.plusSeconds(60)), clock);
        assertEquals(401, post(expired, "Bearer " + token, ping()).getStatus());
        assertTrue(store.toolCalls(JOB).isEmpty());
    }

    @Test
    void aBrowserOriginIsRefusedEvenWithAToken() throws Exception {
        var request = request("Bearer " + token(ChatCapability.COMPANY_READ), ping());
        request.addHeader("Origin", "https://example.com");
        var response = new MockHttpServletResponse();
        filter.doFilter(request, response, (req, res) -> transport.service(req, res));
        assertEquals(403, response.getStatus());
    }

    @Test
    void initializeAnswersAsAToolsOnlyServer() throws Exception {
        JsonNode result = rpc(token(ChatCapability.COMPANY_READ), """
                {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18",
                 "capabilities":{},"clientInfo":{"name":"test","version":"1"}}}""").path("result");
        assertEquals("zoop-chat", result.path("serverInfo").path("name").asString());
        assertTrue(result.path("capabilities").has("tools"));
        assertFalse(result.path("capabilities").has("resources"));
    }

    @Test
    void toolsListShowsOnlyTheGrantedToolsAndNeverTheMemberScopeRead() throws Exception {
        JsonNode listed = rpc(token(ChatCapability.COMPANY_READ), list()).path("result").path("tools");
        assertEquals(1, listed.size());
        JsonNode company = listed.get(0);
        assertEquals("company_read", company.path("name").asString());
        assertEquals(false, company.path("inputSchema").path("additionalProperties").asBoolean(true));
        assertEquals("targets", company.path("inputSchema").path("required").get(0).asString());
        assertTrue(company.path("annotations").path("readOnlyHint").asBoolean());

        JsonNode both = rpc(token(ChatCapability.COMPANY_READ, ChatCapability.GRAPH_PATH_READ), list())
                .path("result").path("tools");
        assertEquals(List.of("company_read", "graph_path_read"),
                both.valueStream().map(t -> t.path("name").asString()).toList());
    }

    @Test
    void anApprovedCallRunsOnceThroughTheRunnerAndIsRecordedOnTheJobsLedger() throws Exception {
        String approved = approve("company_read", "{\"targets\":[\"co-1\"],\"limit\":5}").toolCallId();
        assertEquals("reserved", store.toolCalls(JOB).getFirst().status, "approving reserves the call");

        String token = token(ChatCapability.COMPANY_READ);
        JsonNode result = rpc(token, call("company_read", "{\"targets\":[\"co-1\"],\"limit\":5}")).path("result");
        assertFalse(result.path("isError").asBoolean(true), result.toString());
        JsonNode read = result.path("structuredContent");
        assertEquals(approved, read.path("toolCallId").asString());
        assertEquals("company.read", read.path("capabilityId").asString());
        assertEquals("gv-1", read.path("dataVersion").asString());
        assertEquals("co-1", read.path("items").get(0).path("id").asString());
        assertEquals("ev-1", read.path("evidenceIds").get(0).asString());
        assertEquals(read.toString(), mapper.readTree(result.path("content").get(0).path("text").asString()).toString());

        assertEquals(1, companyReads.size());
        assertEquals(List.of("co-1"), companyReads.getFirst().targets());
        assertEquals(5, companyReads.getFirst().limit());
        var calls = store.toolCalls(JOB);
        assertEquals(1, calls.size());
        assertEquals("succeeded", calls.getFirst().status);
        JsonNode meta = mapper.readTree(calls.getFirst().row.requestMeta());
        assertEquals("mcp", meta.path("via").asString());
        assertEquals("gv-1", meta.path("graphVersion").asString());
        assertEquals("2026-10-27T00:00:00Z", meta.path("asOf").asString());

        // The approval is spent: the same call again is not approved.
        assertEquals("call_not_approved", error(rpc(token, call("company_read", "{\"targets\":[\"co-1\"],\"limit\":5}"))));
        assertEquals(1, companyReads.size());
    }

    @Test
    void aCallThatIsNotExactlyAnApprovedOneReadsNothing() throws Exception {
        String token = token(ChatCapability.COMPANY_READ);
        assertEquals("call_not_approved", error(rpc(token, call("company_read", "{\"targets\":[\"co-1\"]}"))));

        approve("company_read", "{\"targets\":[\"co-1\"]}");
        for (String other : List.of("{\"targets\":[\"co-2\"]}", "{\"targets\":[\"co-1\",\"co-2\"]}",
                "{\"targets\":[\"co-1\"],\"limit\":5}")) {
            assertEquals("call_not_approved", error(rpc(token, call("company_read", other))), other);
        }
        assertTrue(companyReads.isEmpty());
        assertEquals(List.of("reserved"), store.toolCalls(JOB).stream().map(c -> c.status).toList());
        // The default limit is part of the approved call: writing it out is the same call.
        assertFalse(isToolError(rpc(token, call("company_read", "{\"targets\":[\"co-1\"],\"limit\":20}"))));
    }

    @Test
    void refusedCallsAreToolErrorsAndReadNothing() throws Exception {
        String company = token(ChatCapability.COMPANY_READ);
        approve("graph_path_read", "{\"targets\":[\"co-1\",\"co-2\"]}");
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
            assertEquals("invalid_arguments", approve("company_read", arguments).refused(), arguments);
        }
        assertEquals("tool_not_granted", approve("portfolio_scope_read", "{}").refused());
        assertTrue(companyReads.isEmpty());
        assertEquals(1, store.toolCalls(JOB).size(), "only the graph path approval was reserved");
    }

    @Test
    void aGrantForAnotherAttemptSubjectOrAnEndedRunReadsNothing() throws Exception {
        approve("company_read", "{\"targets\":[\"co-1\"]}");
        String args = "{\"targets\":[\"co-1\"]}";
        assertEquals("run_not_active", error(rpc(grants.issue(ChatMcpGrantsTest.run(JOB, 2),
                List.of(ChatCapability.COMPANY_READ)), call("company_read", args))));
        assertEquals("grant_mismatch", error(rpc(grants.issue(ChatMcpGrantsTest.run(JOB, 1, "member-b"),
                List.of(ChatCapability.COMPANY_READ)), call("company_read", args))));

        String token = token(ChatCapability.COMPANY_READ);
        store.cancel(JOB, NOW);
        assertEquals("run_not_active", error(rpc(token, call("company_read", args))));
        assertTrue(companyReads.isEmpty());
        assertEquals("cancelled", store.toolCalls(JOB).getFirst().status, "an approval never called closes with the job");
    }

    @Test
    void approvalsCountAgainstTheAttemptsCallLimit() {
        // 6: the internal share of the job's 8 calls (MCP actions contract 3.2).
        assertEquals(6, ChatRunControl.MAX_TOOL_CALLS);
        for (int i = 0; i < ChatRunControl.MAX_TOOL_CALLS; i++) {
            assertTrue(approve("company_read", "{\"targets\":[\"co-" + i + "\"]}").approved());
        }
        assertEquals("tool_budget_exhausted", approve("company_read", "{\"targets\":[\"co-99\"]}").refused());
        assertEquals(ChatRunControl.MAX_TOOL_CALLS, store.toolCalls(JOB).size());
    }

    @Test
    void evidenceWhoseSourceMayNotBeSentIsLeftOutOfTheResultAndTheLedger() throws Exception {
        // The synthetic news source loses its grant: the company stays, its evidence does not.
        ChatSendGrantsTest.write(dir.resolve("chat-grants.json"), com.zoop.chat.service.ChatCompanyProfiles.SOURCE_ID);
        approve("company_read", "{\"targets\":[\"co-1\"]}");
        JsonNode result = rpc(token(ChatCapability.COMPANY_READ), call("company_read", "{\"targets\":[\"co-1\"]}"))
                .path("result");
        assertFalse(result.path("isError").asBoolean(true), result.toString());
        JsonNode read = result.path("structuredContent");
        assertEquals("co-1", read.path("items").get(0).path("id").asString());
        assertTrue(read.path("items").get(0).path("evidenceIds").isEmpty());
        assertTrue(read.path("evidenceIds").isEmpty());
        assertEquals("source_grant_denied", read.path("withheld").path("reason").asString());
        assertEquals(0, read.path("withheld").path("items").asInt());
        assertEquals(1, read.path("withheld").path("evidenceIds").asInt());
        assertFalse(result.toString().contains("ev-1"), "a withheld id is not sent either");

        var recorded = store.toolCalls(JOB).getFirst();
        assertEquals("succeeded", recorded.status);
        assertTrue(recorded.end.evidenceIds().isEmpty(), "the ledger shows only what was delivered");
        assertEquals(read.toString(), mapper.readTree(recorded.end.result()).toString());
    }

    @Test
    void aResultWhoseSendGrantsCannotBeCheckedIsRefusedNotReturnedUnchecked() throws Exception {
        java.nio.file.Files.delete(dir.resolve("chat-grants.json"));
        approve("company_read", "{\"targets\":[\"co-1\"]}");
        assertEquals("send_grants_unavailable", error(rpc(token(ChatCapability.COMPANY_READ),
                call("company_read", "{\"targets\":[\"co-1\"]}"))));
        var recorded = store.toolCalls(JOB).getFirst();
        assertEquals("failed", recorded.status);
        assertEquals("send_grants_unavailable", recorded.end.errorCode());
        assertTrue(recorded.end.evidenceIds().isEmpty());
        assertEquals(1, companyReads.size(), "the read ran; only its delivery was refused");
    }

    @Test
    void aRepeatOfACallReusesWhatTheFirstReadAndStillCountsAsACall() throws Exception {
        String args = "{\"targets\":[\"co-1\"]}";
        String first = approve("company_read", args).toolCallId();
        String second = approve("company_read", args).toolCallId();
        String token = token(ChatCapability.COMPANY_READ);
        JsonNode read = rpc(token, call("company_read", args)).path("result").path("structuredContent");
        assertTrue(read.path("cachedFrom").isMissingNode());

        JsonNode reused = rpc(token, call("company_read", args)).path("result");
        assertFalse(reused.path("isError").asBoolean(true), reused.toString());
        JsonNode again = reused.path("structuredContent");
        assertEquals(second, again.path("toolCallId").asString());
        assertEquals(first, again.path("cachedFrom").asString(), "the same data, not a second lookup");
        assertEquals(read.path("items").toString(), again.path("items").toString());
        assertEquals(1, companyReads.size(), "read once");
        var calls = store.toolCalls(JOB);
        assertEquals(List.of("succeeded", "succeeded"), calls.stream().map(c -> c.status).toList(),
                "the reuse is a call of its own on the ledger and in the budget");
        assertEquals(again.toString(), mapper.readTree(calls.get(1).end.result()).toString());
    }

    @Test
    void aReuseIsCheckedAgainstTheSendGrantsAsTheyAreNow() throws Exception {
        String args = "{\"targets\":[\"co-1\"]}";
        approve("company_read", args);
        approve("company_read", args);
        String token = token(ChatCapability.COMPANY_READ);
        assertEquals("ev-1", rpc(token, call("company_read", args)).path("result").path("structuredContent")
                .path("evidenceIds").get(0).asString());
        // The news source loses its grant between the two: the reuse does not pass on what the first one could.
        ChatSendGrantsTest.write(dir.resolve("chat-grants.json"), com.zoop.chat.service.ChatCompanyProfiles.SOURCE_ID);
        JsonNode again = rpc(token, call("company_read", args)).path("result").path("structuredContent");
        assertTrue(again.path("evidenceIds").isEmpty());
        assertEquals(1, again.path("withheld").path("evidenceIds").asInt());
        assertTrue(store.toolCalls(JOB).get(1).end.evidenceIds().isEmpty());
        assertEquals(1, companyReads.size());
    }

    @Test
    void identicalRequestsArrivingTogetherAreReadOnce() throws Exception {
        String args = "{\"targets\":[\"co-1\"]}";
        approve("company_read", args);
        approve("company_read", args);
        String token = token(ChatCapability.COMPANY_READ);
        companyGate = new java.util.concurrent.CountDownLatch(1);
        var pool = java.util.concurrent.Executors.newFixedThreadPool(2);
        try {
            var a = pool.submit(() -> rpc(token, call("company_read", args)));
            // The second arrives while the first is still reading.
            while (companyReads.isEmpty()) Thread.onSpinWait();
            var b = pool.submit(() -> rpc(token, call("company_read", args)));
            Thread.sleep(200);
            companyGate.countDown();
            List<JsonNode> results = List.of(a.get(10, java.util.concurrent.TimeUnit.SECONDS).path("result"),
                    b.get(10, java.util.concurrent.TimeUnit.SECONDS).path("result"));
            assertTrue(results.stream().noneMatch(r -> r.path("isError").asBoolean(true)), results.toString());
            assertEquals(1, results.stream().filter(r -> r.path("structuredContent").has("cachedFrom")).count());
        } finally {
            companyGate = null;
            pool.shutdownNow();
        }
        assertEquals(1, companyReads.size(), "one read for both");
    }

    @Test
    void identicalRequestsLetThroughAtTheSameMomentEachTakeTheirOwnApproval() throws Exception {
        String token = token(ChatCapability.COMPANY_READ);
        var pool = java.util.concurrent.Executors.newFixedThreadPool(2);
        try {
            // Three pairs, each pair released together before either has started its read.
            for (int pair = 1; pair <= 3; pair++) {
                String args = "{\"targets\":[\"co-" + pair + "\"]}";
                approve("company_read", args);
                approve("company_read", args);
                var barrier = new java.util.concurrent.CyclicBarrier(2);
                java.util.concurrent.Callable<JsonNode> request = () -> {
                    barrier.await(5, java.util.concurrent.TimeUnit.SECONDS);
                    return rpc(token, call("company_read", args)).path("result");
                };
                var a = pool.submit(request);
                var b = pool.submit(request);
                List<JsonNode> results = List.of(a.get(10, java.util.concurrent.TimeUnit.SECONDS),
                        b.get(10, java.util.concurrent.TimeUnit.SECONDS));
                assertTrue(results.stream().noneMatch(r -> r.path("isError").asBoolean(true)), results.toString());
                assertEquals(2, results.stream().map(r -> r.path("structuredContent").path("toolCallId").asString())
                        .distinct().count(), "each answered under its own approval");
            }
        } finally {
            pool.shutdownNow();
        }
        assertEquals(3, companyReads.size(), "one read per pair");
        assertTrue(store.toolCalls(JOB).stream().allMatch(c -> "succeeded".equals(c.status)),
                "no approval left behind");
    }

    @Test
    void resultsPastTheJobsOneMebibyteAreRecordedAsThatFailureNotDelivered() throws Exception {
        String token = token(ChatCapability.GRAPH_PATH_READ);
        for (int i = 2; i <= 5; i++) {
            String args = "{\"targets\":[\"co-1\",\"co-" + i + "\"]}";
            approve("graph_path_read", args);
            JsonNode result = rpc(token, call("graph_path_read", args)).path("result");
            assertFalse(result.path("isError").asBoolean(true), "result " + i);
        }
        String fifth = "{\"targets\":[\"co-1\",\"co-6\"]}";
        approve("graph_path_read", fifth);
        assertEquals(ChatRunControl.RESULTS_OVER_BUDGET, error(rpc(token, call("graph_path_read", fifth))));
        var last = store.toolCalls(JOB).getLast();
        assertEquals("failed", last.status);
        assertEquals(ChatRunControl.RESULTS_OVER_BUDGET, last.end.errorCode());
        assertNull(last.end.result());
        assertTrue(store.keptResultBytes(JOB) <= ChatRunControl.MAX_KEPT_RESULT_BYTES);
    }

    @Test
    void aResultOverTheLimitIsRecordedAsThatFailureNotAsDelivered() throws Exception {
        approve("issue_read", "{\"targets\":[\"is-1\"]}");
        assertEquals("result_too_large", error(rpc(token(ChatCapability.ISSUE_READ),
                call("issue_read", "{\"targets\":[\"is-1\"]}"))));
        var recorded = store.toolCalls(JOB).getFirst();
        assertEquals("failed", recorded.status);
        assertEquals("result_too_large", recorded.end.errorCode());
        assertNull(recorded.end.dataVersion());
        assertTrue(recorded.end.evidenceIds().isEmpty());
    }

    @Test
    void aTokenMakesAtMostThirtyRequestsAMinuteHoweverItsHeaderIsSpaced() throws Exception {
        String token = token(ChatCapability.COMPANY_READ);
        for (int i = 0; i < ChatMcpAccessFilter.MAX_PER_MINUTE; i++) {
            String header = i % 2 == 0 ? "Bearer " + token : "Bearer    " + token + "  ";
            assertEquals(200, post(filter, header, ping()).getStatus());
        }
        var limited = post(filter, "Bearer      " + token, ping());
        assertEquals(429, limited.getStatus());
        assertEquals("60", limited.getHeader("Retry-After"));
        assertEquals(200, post(token(ChatCapability.GRAPH_PATH_READ), ping()).getStatus());
    }

    @Test
    void aRequestOverSixtyFourKibibytesIsRefused() throws Exception {
        String big = "{\"jsonrpc\":\"2.0\",\"id\":9,\"method\":\"ping\",\"params\":{\"pad\":\""
                + "x".repeat(ChatMcpConfiguration.MAX_REQUEST_BYTES) + "\"}}";
        assertEquals(413, post(token(ChatCapability.COMPANY_READ), big).getStatus());
    }

    private void running(String jobId, int attemptNo) {
        String attempts = "[{\"n\":" + attemptNo + ",\"mode\":\"run\",\"requestKey\":\"" + jobId
                + "\",\"status\":\"running\",\"ownerToken\":\"owner-" + jobId + "\"}]";
        store.add(new ChatJobRow(jobId, "conv-0001", "member-a", 1, "삼성전자 최근 사건", "a".repeat(64), NOW, CONTEXT,
                SELECTION, List.of(), "gv-1", "queued", null, null, null, null, 0, null, null, 0, attempts, NOW, NOW, null));
        assertTrue(store.start(jobId, "owner-" + jobId, NOW.plusSeconds(45), NOW.plusSeconds(60), attempts, NOW));
    }

    /** What the server does when it approves a model's call request: reserve exactly that call. */
    private ChatMcpTools.Approval approve(String tool, String arguments) {
        var attached = executor.attach(JOB, 1).orElseThrow();
        @SuppressWarnings("unchecked")
        Map<String, Object> args = mapper.readValue(arguments, Map.class);
        return tools.approve(attached, tool, args, List.of("r1"));
    }

    private String token(ChatCapability... allowed) {
        return grants.issue(ChatMcpGrantsTest.run(JOB, 1), List.of(allowed));
    }

    private JsonNode rpc(String token, String body) throws Exception {
        var response = post(token, body);
        assertEquals(200, response.getStatus(), response.getContentAsString());
        return mapper.readTree(response.getContentAsString());
    }

    private MockHttpServletResponse post(String token, String body) throws Exception {
        return post(filter, token == null ? null : "Bearer " + token, body);
    }

    private MockHttpServletResponse post(ChatMcpAccessFilter gate, String authorization, String body) throws Exception {
        var response = new MockHttpServletResponse();
        gate.doFilter(request(authorization, body), response, (req, res) -> transport.service(req, res));
        return response;
    }

    private static MockHttpServletRequest request(String authorization, String body) {
        var request = new MockHttpServletRequest("POST", ChatMcpConfiguration.PATH);
        request.setContentType("application/json");
        request.setCharacterEncoding("UTF-8");
        request.addHeader("Accept", "application/json, text/event-stream");
        if (authorization != null) request.addHeader("Authorization", authorization);
        request.setContent(body.getBytes(StandardCharsets.UTF_8));
        return request;
    }

    private static String ping() {
        return "{\"jsonrpc\":\"2.0\",\"id\":7,\"method\":\"ping\"}";
    }

    private static String list() {
        return "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/list\",\"params\":{}}";
    }

    /** A provider's call, naming its requirement as the tool schema demands; the approval took it, the read does not see it. */
    private static String call(String name, String arguments) {
        String named = "{}".equals(arguments) ? "{\"requirementIds\":[\"r1\"]}"
                : "{\"requirementIds\":[\"r1\"]," + arguments.substring(1);
        return "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"" + name
                + "\",\"arguments\":" + named + "}}";
    }

    /** A tool error result, or the protocol error the SDK answers for input its schema check refuses. */
    private static boolean isToolError(JsonNode response) {
        return response.path("result").path("isError").asBoolean(false) || response.has("error");
    }

    private static String error(JsonNode response) {
        assertTrue(response.path("result").path("isError").asBoolean(false), response.toString());
        return response.path("result").path("structuredContent").path("error").asString();
    }

    private static ChatTool tool(ChatCapability capability, List<ChatToolRequest> seen, String label) {
        return new ChatTool() {
            @Override
            public ChatCapability capability() {
                return capability;
            }

            @Override
            public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
                seen.add(request);
                var gate = capability == ChatCapability.COMPANY_READ ? companyGate : null;
                if (gate != null) {
                    try {
                        gate.await(5, java.util.concurrent.TimeUnit.SECONDS);
                    } catch (InterruptedException interrupted) {
                        Thread.currentThread().interrupt();
                    }
                }
                String id = request.targets().getFirst();
                return new ChatToolOutput(scope.graphVersionId(),
                        List.of(new ChatToolItem(id, "company", label, List.of(id), List.of("ev-1"))),
                        List.of("ev-1"), false, false);
            }
        };
    }
}
