package com.zoop.ai.http;

import static com.zoop.ai.http.StubAiServer.TOKEN;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.time.Duration;
import java.time.Instant;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiOperation;
import com.zoop.ai.AiServiceErrorException;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.AiTransportException.Failure;
import com.zoop.ai.chat.ChatStageCall;
import com.zoop.ai.chat.ChatStageReply;
import com.zoop.ai.chat.ChatMcpHealth;
import com.zoop.ai.http.StubAiServer.Reply;
import com.zoop.common.json.StrictJson;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** The chat stage transport against a loopback stand-in for ai/service: no model is called. */
class HttpChatStageClientTest {
    private static final String INVOCATION = "chat-job-0001.1.router";

    private StubAiServer server;
    private HttpChatStageClient client;

    @BeforeEach
    void start() throws IOException {
        server = new StubAiServer();
        client = new HttpChatStageClient(AiClientSettings.ofChat(server.baseUrl(), TOKEN, Duration.ofSeconds(2), Duration.ofSeconds(613),
                65_536, java.util.Set.of()));
    }

    @AfterEach
    void stop() {
        client.close();
        server.close();
    }

    private static ChatStageCall call() {
        return new ChatStageCall(INVOCATION, "chat-router", "replay", StrictJson.newObject().put("probe", true), com.zoop.chat.executor.ChatResourceFixtures.permit("chat-router"));
    }

    private static String result(String invocation, String stage, String status, String answer, String failure, String receipt) {
        return """
                {"schemaVersion":"zoop-ai-chat-6","invocationId":"%s","stage":"%s","status":"%s","answer":%s,"failure":%s,\
                "receipt":%s,"resourceBinding":%s}""".formatted(invocation, stage, status, answer, failure, receipt, call().permit().binding());
    }

    private static final String RECEIPT = """
            {"provider":"typesafe","providerRevision":"systemone-v1","model":"jev","promptVersion":"chat-router-1",\
            "executionMode":"replay","usage":{"inputTokens":120,"outputTokens":null,"cachedTokens":null,"reasoningTokens":7},\
            "sentAt":"2026-10-22T01:00:00Z","receivedAt":"2026-10-22T01:00:01Z"}""";

    @Test
    void postsTheStageWithTheInvocationAsIdempotencyKeyAndDecodesTheOutcome() {
        server.respond(Reply.json(200, result(INVOCATION, "chat-router", "succeeded", "{\"requirements\":[]}", "null", RECEIPT)));
        ChatStageReply reply = client.invoke(call());

        assertTrue(reply.succeeded());
        assertTrue(reply.answer().get("requirements").isArray());
        assertEquals("jev", reply.receipt().model());
        assertEquals(120L, reply.receipt().inputTokens());
        assertEquals(7L, reply.receipt().reasoningTokens());
        assertNull(reply.receipt().outputTokens());
        assertEquals(Instant.parse("2026-10-22T01:00:00Z"), reply.receipt().sentAt());

        StubAiServer.Seen seen = server.requests.get(0);
        assertEquals("POST", seen.method());
        assertEquals("/internal/v1/chat-stages/chat-router", seen.path());
        assertEquals(INVOCATION, seen.header("Idempotency-Key"));
        assertEquals("Bearer " + TOKEN, seen.header("Authorization"));
        assertEquals("{\"schemaVersion\":\"zoop-ai-chat-6\",\"invocationId\":\"" + INVOCATION + "\",\"stage\":\"chat-router\","
                + "\"mode\":\"replay\",\"input\":{\"probe\":true},\"resources\":" + call().permit().resources() + "}", seen.body());
    }

    @Test
    void getsTheContentFreeMcpHealthWithoutAnIdempotencyKey() {
        server.respond(Reply.json(200, "{\"schemaVersion\":\"zoop-ai-chat-6\",\"mcp\":\"reachable\",\"reason\":null}"));

        ChatMcpHealth health = client.probeMcp();

        assertTrue(health.reachable());
        assertNull(health.reason());
        StubAiServer.Seen seen = server.requests.getFirst();
        assertEquals("GET", seen.method());
        assertEquals("/internal/v1/chat-mcp-health", seen.path());
        assertNull(seen.header("Idempotency-Key"));
        assertEquals("", seen.body());
    }

    @Test
    void decodesOnlyTheClosedMcpHealthReasons() {
        server.respond(Reply.json(200, "{\"schemaVersion\":\"zoop-ai-chat-6\",\"mcp\":\"unreachable\"," +
                "\"reason\":\"mcp_timeout\"}"));
        assertEquals(ChatMcpHealth.Reason.TIMEOUT, client.probeMcp().reason());

        for (String body : new String[] {
                "{\"schemaVersion\":\"zoop-ai-chat-6\",\"mcp\":\"reachable\",\"reason\":\"mcp_timeout\"}",
                "{\"schemaVersion\":\"zoop-ai-chat-6\",\"mcp\":\"unreachable\",\"reason\":null}",
                "{\"schemaVersion\":\"zoop-ai-chat-6\",\"mcp\":\"unreachable\",\"reason\":\"other\"}"}) {
            server.respond(Reply.json(200, body));
            AiTransportException malformed = assertThrows(AiTransportException.class, client::probeMcp);
            assertEquals(Failure.RESPONSE_MALFORMED, malformed.failure());
            assertFalse(malformed.requestMaybeProcessed(), "health is a read and never an unknown model outcome");
        }
    }

    @Test
    void aFailedStageCarriesWhetherItWasSentAndWhetherItsFateIsUnknown() {
        server.respond(Reply.json(200, result(INVOCATION, "chat-router", "failed", "null",
                "{\"code\":\"provider_response_unknown\",\"sent\":true,\"unknown\":true}", RECEIPT)));
        ChatStageReply reply = client.invoke(call());
        assertFalse(reply.succeeded());
        assertNull(reply.answer());
        assertEquals("provider_response_unknown", reply.failure().code());
        assertTrue(reply.failure().sent() && reply.failure().unknown());
    }

    @Test
    void anAnswerForAnotherInvocationOrWithAnInconsistentOutcomeIsMalformedAndMayHaveSent() {
        server.respond(Reply.json(200, result("chat-job-0002.1.router", "chat-router", "succeeded", "{}", "null", "null")));
        AiTransportException other = assertThrows(AiTransportException.class, () -> client.invoke(call()));
        assertEquals(Failure.RESPONSE_MALFORMED, other.failure());
        assertTrue(other.requestMaybeProcessed());

        server.respond(Reply.json(200, result(INVOCATION, "chat-router", "succeeded", "null", "null", "null")));
        assertEquals(Failure.RESPONSE_MALFORMED, assertThrows(AiTransportException.class, () -> client.invoke(call())).failure());

        server.respond(Reply.json(200, result(INVOCATION, "chat-router", "failed", "null", "null", "null")));
        assertEquals(Failure.RESPONSE_MALFORMED, assertThrows(AiTransportException.class, () -> client.invoke(call())).failure());
    }

    @Test
    void anOutcomeThatContradictsTheContractIsNeverNormalized() {
        String unknown = "{\"code\":\"provider_response_unknown\",\"sent\":true,\"unknown\":true}";
        String notSent = "{\"code\":\"source_grant_denied\",\"sent\":false,\"unknown\":false}";
        String answer = "{\"requirements\":[]}";
        for (String body : new String[] {
                result(INVOCATION, "chat-router", "succeeded", answer, "null", "null"),                       // success without a receipt
                result(INVOCATION, "chat-router", "succeeded", answer, "null", RECEIPT.replace("\"replay\"", "\"live\"")), // another mode
                result(INVOCATION, "chat-router", "failed", answer, notSent, "null"),                         // a failure with an answer
                result(INVOCATION, "chat-router", "failed", "null", unknown, "null"),                         // sent without a receipt
                result(INVOCATION, "chat-router", "failed", "null", notSent, RECEIPT),                        // a receipt for nothing sent
                result(INVOCATION, "chat-router", "failed", "null",
                        "{\"code\":\"x\",\"sent\":false,\"unknown\":true}", "null")}) {                       // unknown but not sent
            server.respond(Reply.json(200, body));
            AiTransportException error = assertThrows(AiTransportException.class, () -> client.invoke(call()), body);
            assertEquals(Failure.RESPONSE_MALFORMED, error.failure());
            assertTrue(error.requestMaybeProcessed(), "a contradiction is an unknown outcome, never a usable answer");
        }
        server.respond(Reply.json(200, result(INVOCATION, "chat-router", "failed", "null", notSent, "null")));
        assertFalse(client.invoke(call()).failure().sent());
    }

    @Test
    void serviceErrorsKeepTheirStatusAndCode() {
        server.respond(seen -> Reply.json(502, StubAiServer.error("stage_outcome_unknown", false, seen.requestId(), null, null)));
        AiServiceErrorException unknown = assertThrows(AiServiceErrorException.class, () -> client.invoke(call()));
        assertEquals(502, unknown.httpStatus());
        assertEquals("stage_outcome_unknown", unknown.code());
        assertEquals(AiOperation.CHAT_STAGE, unknown.operation());
        assertTrue(unknown.requestMaybeProcessed());

        server.respond(seen -> Reply.json(409, StubAiServer.error("execution_unavailable", false, seen.requestId(), null, null)));
        AiServiceErrorException refused = assertThrows(AiServiceErrorException.class, () -> client.invoke(call()));
        assertEquals(409, refused.httpStatus());
        assertFalse(refused.requestMaybeProcessed());
    }

    @Test
    void capabilitiesUseAuthenticatedContentFreeGetAndVerifyTheInstalledFingerprint() {
        var expected = com.zoop.chat.executor.ChatResourceFixtures.contracts().path("capabilities");
        server.respond(Reply.json(200, expected.toString()));
        assertEquals(expected.path("runtimeFingerprint").stringValue(), client.capabilities().fingerprint());
        var seen = server.requests.getFirst();
        assertEquals("GET", seen.method());
        assertEquals("/internal/v1/chat-runtime-capabilities", seen.path());
        assertEquals("", seen.body());
        assertNull(seen.header("Idempotency-Key"));
        assertEquals("Bearer " + TOKEN, seen.header("Authorization"));
    }

    @Test
    void aThirtyFiveSecondTransportRefusesResourcePreflightWithoutSending() {
        try (var shortClient = new HttpChatStageClient(AiClientSettings.of(server.baseUrl(), TOKEN, Duration.ofSeconds(3),
                Duration.ofSeconds(35), 65536))) {
            var stages = new com.zoop.chat.model.ChatModelStages(shortClient, "replay", null, null, null, null, null);
            var refused = assertThrows(com.zoop.chat.orchestrator.ChatModels.Failure.class,
                    () -> stages.preflight(com.zoop.chat.executor.ChatResourcePolicy.defaults(), false));
            assertEquals(com.zoop.chat.orchestrator.ChatModels.Failure.Fate.REFUSED, refused.fate());
            assertTrue(server.requests.isEmpty());
        }
    }

    @Test
    void aReplyBoundToAnotherAllocationIsUnknownInsteadOfACompletedAnswer() {
        var changed = (tools.jackson.databind.node.ObjectNode) WireJson.parse(
                result(INVOCATION, "chat-router", "succeeded", "{}", "null", RECEIPT), "body");
        ((tools.jackson.databind.node.ObjectNode) changed.path("resourceBinding")).put("allocationDigest", "0".repeat(64));
        server.respond(Reply.json(200, changed.toString()));
        var failure = assertThrows(AiTransportException.class, () -> client.invoke(call()));
        assertEquals(Failure.RESOURCE_BINDING_MISMATCH, failure.failure());
        assertTrue(failure.requestMaybeProcessed());
    }

    @Test
    void theCallRefusesAnUnsafeInvocationOrUnknownStageBeforeSending() {
        var input = StrictJson.newObject();
        assertThrows(IllegalArgumentException.class, () -> new ChatStageCall("short", "chat-router", "replay", input, com.zoop.chat.executor.ChatResourceFixtures.permit("chat-router")));
        assertThrows(IllegalArgumentException.class, () -> new ChatStageCall(INVOCATION, "chat-other", "replay", input, com.zoop.chat.executor.ChatResourceFixtures.permit("chat-router")));
        assertThrows(IllegalArgumentException.class, () -> new ChatStageCall(INVOCATION, "chat-router", "save_only", input, com.zoop.chat.executor.ChatResourceFixtures.permit("chat-router")));
        assertTrue(server.requests.isEmpty());
    }
}
