package com.zoop.ai.http;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.time.Duration;
import java.util.List;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.HandoffServiceErrorException;
import com.zoop.ai.handoff.HandoffReadClient.HandoffRead;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class HttpHandoffReadClientTest {
    private static final String ID = "handoff-synthetic-1";
    private static final String DIGEST_A = "a".repeat(64);
    private static final String DIGEST_B = "b".repeat(64);
    private static final String DIGEST_C = "c".repeat(64);
    private static final String VERIFICATION = "{\"manifestDigest\":\"" + DIGEST_A + "\",\"bundleDigest\":\"" + DIGEST_B
            + "\",\"contentDigest\":\"" + DIGEST_C + "\",\"bundleBytes\":1234,\"counts\":{\"issues\":1},\"sources\":1,"
            + "\"provenance\":{\"declaredSourceKind\":\"synthetic\"}}";
    private static final String CURRENT = "{\"schemaVersion\":\"zoop-ai-internal-handoff-1\",\"handoffId\":\"" + ID
            + "\",\"state\":\"ready\",\"publication\":\"not-published\",\"appImport\":\"pending\",\"delivery\":{\"state\":\"current\","
            + "\"reason\":null,\"checkedAt\":\"2026-10-17T00:00:00+00:00\"},\"verification\":" + VERIFICATION
            + ",\"observedAt\":\"2026-10-17T00:00:01Z\"";
    private static final String WITHHELD = "{\"schemaVersion\":\"zoop-ai-internal-handoff-1\",\"handoffId\":\"" + ID
            + "\",\"state\":\"ready\",\"publication\":\"not-published\",\"appImport\":\"pending\",\"delivery\":{\"state\":\"withheld\","
            + "\"reason\":\"source_unauthorized\",\"checkedAt\":null},\"verification\":null,\"observedAt\":\"2026-10-17T00:00:01Z\"";
    private StubAiServer server;
    private HttpHandoffReadClient client;

    @BeforeEach
    void start() throws IOException {
        server = new StubAiServer();
        client = new HttpHandoffReadClient(AiClientSettings.of(server.baseUrl(), StubAiServer.TOKEN, Duration.ofSeconds(1),
                Duration.ofSeconds(3), 65_536));
    }

    @AfterEach
    void stop() {
        client.close();
        server.close();
    }

    @Test
    void theBundleRouteIsAPlainGetAndACurrentAnswerCarriesTheVerificationManifestAndBundleUntouched() {
        server.respond(seen -> StubAiServer.Reply.json(200, CURRENT + ",\"manifest\":{\"handoffId\":\"" + ID + "\"},\"bundle\":{\"x\":[1]}}"));

        HandoffRead read = client.bundle(ID);

        var seen = server.requests.getFirst();
        assertEquals("GET", seen.method());
        assertEquals(HttpHandoffReadClient.PATH + ID + "/bundle", seen.path());
        assertEquals(null, seen.header("Idempotency-Key"), "a read has no idempotency key");
        assertEquals("", seen.body());
        assertTrue(read.current());
        assertEquals("ready", read.state());
        assertEquals("2026-10-17T00:00:00+00:00", read.delivery().checkedAt().orElseThrow());
        assertTrue(read.delivery().reason().isEmpty());
        var verification = read.verification().orElseThrow();
        assertEquals(DIGEST_A, verification.manifestDigest());
        assertEquals(DIGEST_B, verification.bundleDigest());
        assertEquals(DIGEST_C, verification.contentDigest());
        assertEquals(1234, verification.bundleBytes());
        assertEquals(1, verification.sources());
        assertEquals(1, verification.counts().get("issues").intValue());
        assertEquals("synthetic", verification.provenance().get("declaredSourceKind").stringValue());
        assertEquals(ID, read.manifest().orElseThrow().get("handoffId").stringValue());
        assertEquals(1, read.bundle().orElseThrow().get("x").get(0).intValue());
        assertEquals("2026-10-17T00:00:01Z", read.observedAt());
    }

    @Test
    void theStatusRouteNeverCarriesContentAndAWithheldAnswerIsAReasonNotData() {
        server.respond(seen -> StubAiServer.Reply.json(200, CURRENT + "}"));
        HandoffRead status = client.status(ID);
        assertEquals(HttpHandoffReadClient.PATH + ID, server.requests.getFirst().path());
        assertTrue(status.current());
        assertTrue(status.manifest().isEmpty() && status.bundle().isEmpty());

        server.respond(seen -> StubAiServer.Reply.json(200, WITHHELD + ",\"manifest\":null,\"bundle\":null}"));
        HandoffRead withheld = client.bundle(ID);
        assertFalse(withheld.current());
        assertEquals("source_unauthorized", withheld.delivery().reason().orElseThrow());
        assertTrue(withheld.verification().isEmpty() && withheld.manifest().isEmpty() && withheld.bundle().isEmpty());

        // The schema version has a default on the AI side and may be omitted; absent nullable fields are the same as null.
        server.respond(seen -> StubAiServer.Reply.json(200, "{\"handoffId\":\"" + ID + "\",\"state\":\"failed\",\"delivery\":"
                + "{\"state\":\"withheld\",\"reason\":\"handoff_not_ready\"},\"observedAt\":\"2026-10-17T00:00:01Z\"}"));
        assertEquals("failed", client.bundle(ID).state());
    }

    @Test
    void anAnswerOutsideTheContractIsMalformedNeverAPartialHandoff() {
        List<String> bodies = List.of(
                "[]",
                "{}",
                CURRENT + "}",                                                               // bundle route without content
                CURRENT + ",\"manifest\":{},\"bundle\":[]}",                                 // bundle not an object
                CURRENT + ",\"manifest\":{},\"bundle\":{},\"extra\":1}",                     // unknown key
                CURRENT.replace("\"handoffId\":\"" + ID + "\"", "\"handoffId\":\"other\"") + ",\"manifest\":{},\"bundle\":{}}",
                CURRENT.replace("zoop-ai-internal-handoff-1", "zoop-ai-handoff-1") + ",\"manifest\":{},\"bundle\":{}}",
                CURRENT.replace("\"publication\":\"not-published\"", "\"publication\":\"published\"") + ",\"manifest\":{},\"bundle\":{}}",
                CURRENT.replace("\"state\":\"ready\"", "\"state\":\"frozen\"") + ",\"manifest\":{},\"bundle\":{}}",
                CURRENT.replace("\"verification\":" + VERIFICATION, "\"verification\":null") + ",\"manifest\":{},\"bundle\":{}}",
                CURRENT.replace("\"sources\":1", "\"sources\":0") + ",\"manifest\":{},\"bundle\":{}}",
                CURRENT.replace("\"bundleDigest\":\"" + DIGEST_B + "\"", "\"bundleDigest\":\"short\"") + ",\"manifest\":{},\"bundle\":{}}",
                CURRENT.replace(",\"checkedAt\":\"2026-10-17T00:00:00+00:00\"", "") + ",\"manifest\":{},\"bundle\":{}}",
                WITHHELD.replace("\"verification\":null", "\"verification\":" + VERIFICATION) + "}",
                WITHHELD + ",\"manifest\":{},\"bundle\":{}}",
                WITHHELD.replace("\"reason\":\"source_unauthorized\"", "\"reason\":null") + "}");
        for (String body : bodies) {
            server.respond(seen -> StubAiServer.Reply.json(200, body));
            var failure = assertThrows(AiTransportException.class, () -> client.bundle(ID), body);
            assertEquals(AiTransportException.Failure.RESPONSE_MALFORMED, failure.failure(), body);
        }
    }

    @Test
    void aHandoffErrorEnvelopeIsADefiniteRefusalWithItsCodeAndStatus() {
        server.respond(seen -> StubAiServer.Reply.json(403, "{\"schemaVersion\":\"zoop-ai-internal-handoff-1\",\"error\":{\"code\":"
                + "\"handoff_not_allowed\",\"retryable\":false,\"requestId\":\"" + seen.requestId() + "\"}}"));
        var refused = assertThrows(HandoffServiceErrorException.class, () -> client.bundle(ID));
        assertEquals("handoff_not_allowed", refused.code());
        assertEquals(403, refused.httpStatus());
        assertFalse(refused.requestMaybeProcessed(), "a read is never a mutation");

        server.respond(seen -> StubAiServer.Reply.json(503, "{\"error\":{\"code\":\"runtime_busy\",\"retryable\":true,"
                + "\"requestId\":\"" + seen.requestId() + "\",\"runtimeCode\":\"handoff_busy\"}}").header("Retry-After", "2"));
        var busy = assertThrows(HandoffServiceErrorException.class, () -> client.status(ID));
        assertEquals(503, busy.httpStatus());
        assertTrue(busy.retryable());
        assertEquals("handoff_busy", busy.runtimeCode().orElseThrow());
        assertEquals(Duration.ofSeconds(2), busy.retryAfter().orElseThrow());
    }

    @Test
    void aReasonInTheServicesOwnAlphabetAndAnyPrintableObservedAtAreTheServicesAnswerNotAContractBreach() {
        // delivery.reason is the producer's code in the service's Safe alphabet; observedAt is an untyped string in the contract.
        server.respond(seen -> StubAiServer.Reply.json(200,
                WITHHELD.replace("\"reason\":\"source_unauthorized\"", "\"reason\":\"Review.Changed:s3-revoked\"")
                        .replace("\"observedAt\":\"2026-10-17T00:00:01Z\"", "\"observedAt\":\"2026-10-17 00:00:01.123456+09:00\"") + "}"));
        HandoffRead withheld = client.status(ID);
        assertEquals("Review.Changed:s3-revoked", withheld.delivery().reason().orElseThrow());
        assertEquals("2026-10-17 00:00:01.123456+09:00", withheld.observedAt());
        // ... but still bounded: outside the Safe alphabet, over its length, or an empty stamp is malformed.
        for (String body : List.of(
                WITHHELD.replace("\"reason\":\"source_unauthorized\"", "\"reason\":\"bad reason\"") + "}",
                WITHHELD.replace("\"reason\":\"source_unauthorized\"", "\"reason\":\"" + "x".repeat(81) + "\"") + "}",
                WITHHELD.replace("\"observedAt\":\"2026-10-17T00:00:01Z\"", "\"observedAt\":\"\"") + "}")) {
            server.respond(seen -> StubAiServer.Reply.json(200, body));
            var failure = assertThrows(AiTransportException.class, () -> client.status(ID), body);
            assertEquals(AiTransportException.Failure.RESPONSE_MALFORMED, failure.failure(), body);
        }
    }

    @Test
    void anIdOutsideTheContractIsNeverSent() {
        for (String id : List.of("", "bad id", "x".repeat(201), "a/b")) {
            assertThrows(IllegalArgumentException.class, () -> client.bundle(id), id);
        }
        assertEquals(0, server.requests.size());
    }
}
