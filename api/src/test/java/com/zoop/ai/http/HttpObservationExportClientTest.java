package com.zoop.ai.http;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiOperation;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.ObservationServiceErrorException;
import com.zoop.ai.observation.ObservationExportClient.Selector;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

class HttpObservationExportClientTest {
    private static final Selector SELECTOR = new Selector("round-1", "src-a", 2, 5, "doc-" + "a".repeat(64), "b".repeat(64),
            "c".repeat(64));
    /** An export the way the CLI prints it: not canonical, with a language and an unknown-to-this-client field, kept verbatim. */
    private static final String EXPORT = """
            {"schemaVersion":"zoop-ingestion-s2-1",
             "observation":{"roundId":"round-1","sourceId":"src-a","page":2,"ordinal":5,"documentId":"doc-%s",
                            "rawVersion":"%s","documentVersion":"%s","language":"ko","publisher":"합성일보"},
             "grant":{"grantId":"g-1","revision":"r-1"},
             "document":{"text":"본문 \\u00e9 \\"q\\""},
             "locatorMetadata":{"limitations":[]}}
            """.formatted("a".repeat(64), "b".repeat(64), "c".repeat(64));
    private StubAiServer server;
    private HttpObservationExportClient client;

    @BeforeEach
    void start() throws IOException {
        server = new StubAiServer();
        client = new HttpObservationExportClient(AiClientSettings.of(server.baseUrl(), StubAiServer.TOKEN, Duration.ofSeconds(1),
                Duration.ofSeconds(2), 1 << 20));
    }

    @AfterEach
    void stop() {
        client.close();
        server.close();
    }

    @Test
    void theRouteIsAPostOfTheCliSelectorAndTheAnswerIsReturnedByteForByte() throws Exception {
        server.respond(StubAiServer.Reply.json(200, EXPORT));

        byte[] exported = client.export(SELECTOR);

        assertArrayEquals(EXPORT.getBytes(StandardCharsets.UTF_8), exported, "no re-serialisation of the export");
        var seen = server.requests.getFirst();
        assertEquals("POST", seen.method());
        assertEquals(HttpObservationExportClient.PATH, seen.path());
        assertEquals("application/json", seen.header("Content-Type"));
        assertEquals("Bearer " + StubAiServer.TOKEN, seen.header("Authorization"));
        assertEquals(null, seen.header("Idempotency-Key"), "a read has no idempotency key");
        assertTrue(AnalysisWire.validRequestId(seen.requestId()));
        var body = JsonMapper.builder().build().readTree(seen.body());
        assertEquals("zoop-ingestion-s2-1", body.get("schemaVersion").stringValue());
        assertEquals(7 + 1, body.size(), "schemaVersion plus the seven selector fields, nothing else");
        assertEquals("round-1", body.get("roundId").stringValue());
        assertEquals(2, body.get("page").intValue());
        assertEquals(5, body.get("ordinal").intValue());
        assertEquals("c".repeat(64), body.get("documentVersion").stringValue());
    }

    @Test
    void aRefusalEnvelopeBecomesTheObservationFamilysException() {
        server.respond(seen -> StubAiServer.Reply.json(403, StubAiServer.error("source_unauthorized", false, seen.requestId(), null, null)));
        ObservationServiceErrorException refused = assertThrows(ObservationServiceErrorException.class, () -> client.export(SELECTOR));
        assertEquals(403, refused.httpStatus());
        assertEquals("source_unauthorized", refused.code());
        assertEquals(AiOperation.OBSERVATION_EXPORT, refused.operation());
        assertFalse(refused.requestMaybeProcessed(), "a read never changes the service");

        server.respond(seen -> StubAiServer.Reply.json(503, StubAiServer.error("runtime_busy", true, seen.requestId(), null, null))
                .header("Retry-After", "2"));
        ObservationServiceErrorException busy = assertThrows(ObservationServiceErrorException.class, () -> client.export(SELECTOR));
        assertEquals(503, busy.httpStatus());
        assertEquals("runtime_busy", busy.code());
        assertEquals(Duration.ofSeconds(2), busy.retryAfter().orElseThrow());
    }

    @Test
    void anEnvelopeWithoutTheEchoedRequestIdOrWithForeignKeysIsMalformed() {
        server.respond(StubAiServer.Reply.json(403, StubAiServer.error("source_unauthorized", false, "someone-else", null, null)));
        assertEquals(AiTransportException.Failure.UNEXPECTED_RESPONSE,
                assertThrows(AiTransportException.class, () -> client.export(SELECTOR)).failure());

        server.respond(seen -> StubAiServer.Reply.json(403,
                "{\"schemaVersion\":\"zoop-ai-internal-1\",\"error\":{\"code\":\"source_unauthorized\",\"retryable\":false,\"requestId\":\""
                        + seen.requestId() + "\"},\"extra\":1}"));
        assertEquals(AiTransportException.Failure.UNEXPECTED_RESPONSE,
                assertThrows(AiTransportException.class, () -> client.export(SELECTOR)).failure());

        server.respond(seen -> StubAiServer.Reply.json(403,
                "{\"schemaVersion\":1,\"error\":{\"code\":\"source_unauthorized\",\"retryable\":false,\"requestId\":\"" + seen.requestId() + "\"}}"));
        assertEquals(AiTransportException.Failure.UNEXPECTED_RESPONSE,
                assertThrows(AiTransportException.class, () -> client.export(SELECTOR)).failure());

        server.respond(seen -> StubAiServer.Reply.json(403, StubAiServer.error("source_unauthorized", false, seen.requestId(), null, "{\"x\":1}")));
        assertEquals(AiTransportException.Failure.UNEXPECTED_RESPONSE,
                assertThrows(AiTransportException.class, () -> client.export(SELECTOR)).failure(), "a non-null status is not this family's");
    }

    @Test
    void anAnswerThatIsNotThisObservationsExportIsMalformedNotAccepted() {
        server.respond(StubAiServer.Reply.json(200, EXPORT.replace("\"page\":2", "\"page\":3")));
        assertEquals(AiTransportException.Failure.RESPONSE_MALFORMED,
                assertThrows(AiTransportException.class, () -> client.export(SELECTOR)).failure());

        server.respond(StubAiServer.Reply.json(200, EXPORT.replace("zoop-ingestion-s2-1", "zoop-ingestion-s2-2")));
        assertEquals(AiTransportException.Failure.RESPONSE_MALFORMED,
                assertThrows(AiTransportException.class, () -> client.export(SELECTOR)).failure());

        server.respond(StubAiServer.Reply.json(200, "[1,2]"));
        assertEquals(AiTransportException.Failure.RESPONSE_MALFORMED,
                assertThrows(AiTransportException.class, () -> client.export(SELECTOR)).failure());

        server.respond(StubAiServer.Reply.json(202, EXPORT));
        assertEquals(AiTransportException.Failure.UNEXPECTED_RESPONSE,
                assertThrows(AiTransportException.class, () -> client.export(SELECTOR)).failure());
    }

    @Test
    void aRedirectIsNeverFollowed() {
        server.respond(StubAiServer.Reply.json(302, "{}").header("Location", server.baseUrl() + "/elsewhere"));
        assertEquals(AiTransportException.Failure.REDIRECT_REFUSED,
                assertThrows(AiTransportException.class, () -> client.export(SELECTOR)).failure());
        assertEquals(1, server.requests.size());
    }
}
