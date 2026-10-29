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
        client = new HttpChatStageClient(AiClientSettings.of(server.baseUrl(), TOKEN, Duration.ofSeconds(2), Duration.ofSeconds(5),
                65_536));
    }

    @AfterEach
    void stop() {
        client.close();
        server.close();
    }

    private static ChatStageCall call() {
        return new ChatStageCall(INVOCATION, "chat-router", "replay", StrictJson.newObject().put("probe", true));
    }

    private static String result(String invocation, String stage, String status, String answer, String failure, String receipt) {
        return """
                {"schemaVersion":"zoop-ai-chat-2","invocationId":"%s","stage":"%s","status":"%s","answer":%s,"failure":%s,\
                "receipt":%s}""".formatted(invocation, stage, status, answer, failure, receipt);
    }

    private static final String RECEIPT = """
            {"provider":"typesafe","providerRevision":"systemone-v1","model":"jev","promptVersion":"chat-router-1",\
            "executionMode":"replay","usage":{"inputTokens":120,"outputTokens":null,"cachedTokens":null,"reasoningTokens":null},\
            "sentAt":"2026-10-22T01:00:00Z","receivedAt":"2026-10-22T01:00:01Z"}""";

    @Test
    void postsTheStageWithTheInvocationAsIdempotencyKeyAndDecodesTheOutcome() {
        server.respond(Reply.json(200, result(INVOCATION, "chat-router", "succeeded", "{\"requirements\":[]}", "null", RECEIPT)));
        ChatStageReply reply = client.invoke(call());

        assertTrue(reply.succeeded());
        assertTrue(reply.answer().get("requirements").isArray());
        assertEquals("jev", reply.receipt().model());
        assertEquals(120L, reply.receipt().inputTokens());
        assertNull(reply.receipt().outputTokens());
        assertEquals(Instant.parse("2026-10-22T01:00:00Z"), reply.receipt().sentAt());

        StubAiServer.Seen seen = server.requests.get(0);
        assertEquals("POST", seen.method());
        assertEquals("/internal/v1/chat-stages/chat-router", seen.path());
        assertEquals(INVOCATION, seen.header("Idempotency-Key"));
        assertEquals("Bearer " + TOKEN, seen.header("Authorization"));
        assertEquals("{\"schemaVersion\":\"zoop-ai-chat-2\",\"invocationId\":\"" + INVOCATION + "\",\"stage\":\"chat-router\","
                + "\"mode\":\"replay\",\"input\":{\"probe\":true}}", seen.body());
    }

    @Test
    void getsTheContentFreeMcpHealthWithoutAnIdempotencyKey() {
        server.respond(Reply.json(200, "{\"schemaVersion\":\"zoop-ai-chat-2\",\"mcp\":\"reachable\",\"reason\":null}"));

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
        server.respond(Reply.json(200, "{\"schemaVersion\":\"zoop-ai-chat-2\",\"mcp\":\"unreachable\"," +
                "\"reason\":\"mcp_timeout\"}"));
        assertEquals(ChatMcpHealth.Reason.TIMEOUT, client.probeMcp().reason());

        for (String body : new String[] {
                "{\"schemaVersion\":\"zoop-ai-chat-2\",\"mcp\":\"reachable\",\"reason\":\"mcp_timeout\"}",
                "{\"schemaVersion\":\"zoop-ai-chat-2\",\"mcp\":\"unreachable\",\"reason\":null}",
                "{\"schemaVersion\":\"zoop-ai-chat-2\",\"mcp\":\"unreachable\",\"reason\":\"other\"}"}) {
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
    void theCallRefusesAnUnsafeInvocationOrUnknownStageBeforeSending() {
        var input = StrictJson.newObject();
        assertThrows(IllegalArgumentException.class, () -> new ChatStageCall("short", "chat-router", "replay", input));
        assertThrows(IllegalArgumentException.class, () -> new ChatStageCall(INVOCATION, "chat-other", "replay", input));
        assertThrows(IllegalArgumentException.class, () -> new ChatStageCall(INVOCATION, "chat-router", "save_only", input));
        assertTrue(server.requests.isEmpty());
    }
}
