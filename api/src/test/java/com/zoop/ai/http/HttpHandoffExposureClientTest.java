package com.zoop.ai.http;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.time.Duration;
import java.util.List;
import java.util.stream.IntStream;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.HandoffServiceErrorException;
import com.zoop.common.json.StrictJson;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

class HttpHandoffExposureClientTest {
    private static final String REPORT = "{\"schemaVersion\":\"zoop-handoff-exposure-1\",\"handoffs\":[]}";
    private StubAiServer server;
    private HttpHandoffExposureClient client;

    @BeforeEach
    void start() throws IOException {
        server = new StubAiServer();
        client = new HttpHandoffExposureClient(AiClientSettings.of(server.baseUrl(), StubAiServer.TOKEN, Duration.ofSeconds(1),
                Duration.ofSeconds(3), 65_536));
    }

    @AfterEach
    void stop() {
        client.close();
        server.close();
    }

    private static JsonNode source() {
        ObjectNode changed = StrictJson.newObject();
        changed.put("kind", "source");
        changed.put("sourceId", "synthetic-source");
        return changed;
    }

    @Test
    void theQueryIsTheContractsBodyWithoutAnIdempotencyKeyAndTheReportIsReturnedAsIs() {
        server.respond(seen -> StubAiServer.Reply.json(200,
                "{\"schemaVersion\":\"zoop-ai-internal-handoff-1\",\"report\":" + REPORT + "}"));

        JsonNode report = client.exposure(List.of("handoff-a", "handoff-b"), source());

        assertEquals("zoop-handoff-exposure-1", report.get("schemaVersion").stringValue());
        var seen = server.requests.getFirst();
        assertEquals("POST", seen.method());
        assertEquals(HttpHandoffExposureClient.PATH, seen.path());
        assertEquals(null, seen.header("Idempotency-Key"), "a read-only query has no idempotency key");
        assertEquals("{\"schemaVersion\":\"zoop-handoff-exposure-1\",\"handoffIds\":[\"handoff-a\",\"handoff-b\"],"
                + "\"changed\":{\"kind\":\"source\",\"sourceId\":\"synthetic-source\"}}", seen.body());
        // The envelope schema may be omitted (it has a default), the report alone is enough.
        server.respond(seen2 -> StubAiServer.Reply.json(200, "{\"report\":" + REPORT + "}"));
        assertTrue(client.exposure(List.of("handoff-a"), source()).isObject());
    }

    @Test
    void anEnvelopeWithAnythingElseIsMalformedNeverAPartialReport() {
        for (String body : List.of("{\"report\":[]}", "{\"report\":" + REPORT + ",\"extra\":1}",
                "{\"schemaVersion\":\"other\",\"report\":" + REPORT + "}", "{}")) {
            server.respond(seen -> StubAiServer.Reply.json(200, body));
            var failure = assertThrows(AiTransportException.class, () -> client.exposure(List.of("handoff-a"), source()), body);
            assertEquals(AiTransportException.Failure.RESPONSE_MALFORMED, failure.failure());
        }
    }

    @Test
    void aHandoffErrorEnvelopeIsADefiniteRefusalWithItsCode() {
        server.respond(seen -> StubAiServer.Reply.json(409, "{\"schemaVersion\":\"zoop-ai-internal-handoff-1\",\"error\":{\"code\":"
                + "\"handoff_pin_mismatch\",\"retryable\":false,\"requestId\":\"" + seen.requestId() + "\"}}"));
        var refused = assertThrows(HandoffServiceErrorException.class, () -> client.exposure(List.of("handoff-a"), source()));
        assertEquals("handoff_pin_mismatch", refused.code());
        assertEquals(409, refused.httpStatus());
        assertFalse(refused.requestMaybeProcessed(), "exposure is read-only");
    }

    @Test
    void aSelectionOutsideTheContractIsNeverSent() {
        List<String> tooMany = IntStream.rangeClosed(1, 21).mapToObj(i -> "handoff-" + i).toList();
        for (List<String> ids : List.of(List.<String>of(), tooMany, List.of("a", "a"), List.of("bad id"))) {
            assertThrows(IllegalArgumentException.class, () -> client.exposure(ids, source()));
        }
        assertEquals(0, server.requests.size());
    }
}
