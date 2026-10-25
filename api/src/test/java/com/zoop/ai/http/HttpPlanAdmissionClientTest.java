package com.zoop.ai.http;

import java.io.IOException;
import java.time.Duration;
import java.util.List;
import java.util.function.UnaryOperator;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.PlanAdmissionServiceErrorException;
import com.zoop.ai.plan.PlanAdmission;
import com.zoop.ai.plan.PlanIdentity;
import com.zoop.ai.plan.PlanReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Real loopback exchanges; fixtures use independently ordered canonical preimages, not a mock client. */
class HttpPlanAdmissionClientTest {
    private static final String DIGEST = "1".repeat(64);
    private static final String INPUT = "2".repeat(64);
    private static final String APPROVED = "3".repeat(64);
    private static final PlanReference REFERENCE = new PlanReference("s2plan-" + "4".repeat(64), DIGEST);
    private static final String PROVENANCE = "{\"executionMode\":\"replay\",\"recordingKind\":\"authored-test\",\"sourceKind\":\"synthetic\"}";
    private StubAiServer server;
    private HttpPlanAdmissionClient client;

    @BeforeEach
    void start() throws IOException {
        server = new StubAiServer();
        client = new HttpPlanAdmissionClient(settings(Duration.ofSeconds(3)));
    }

    private AiClientSettings settings(Duration deadline) {
        return AiClientSettings.of(server.baseUrl(), StubAiServer.TOKEN, Duration.ofSeconds(1), deadline, 65_536);
    }

    @AfterEach
    void stop() {
        client.close();
        server.close();
    }

    private static String unit() {
        return "{\"extractionInputDigest\":\"" + INPUT + "\",\"extractionSubmit\":{\"approvedRequestDigest\":\"" + APPROVED
                + "\",\"jobId\":\"s2-job\",\"schemaVersion\":\"zoop-extraction-s2-2\"},\"relationSubmit\":{\"jobId\":\""
                + PlanIdentity.relationJobId(REFERENCE, "s2-job", INPUT) + "\",\"provenance\":" + PROVENANCE
                + ",\"schemaVersion\":\"zoop-relation-s3\",\"upstream\":{\"inputDigest\":\"" + INPUT
                + "\",\"jobId\":\"s2-job\"}},\"unitKey\":\"s2-job\"}";
    }

    private static String canonicalManifest() {
        return "{\"planDigest\":\"" + DIGEST + "\",\"planId\":\"" + REFERENCE.planId() + "\",\"principal\":\"alpha\",\"provenance\":"
                + PROVENANCE + ",\"receiptSha256\":\"" + DIGEST + "\",\"round\":{\"ingestionInputDigest\":\"" + INPUT
                + "\",\"roundId\":\"round-1\",\"sourceId\":\"source-1\"},\"schemaVersion\":\"zoop-ai-plan-manifest-1\",\"units\":[" + unit() + "]}";
    }

    private static String envelope(String manifest, String manifestDigest) {
        String withDigest = manifest.substring(0, manifest.length() - 1) + ",\"manifestDigest\":\"" + manifestDigest + "\"}";
        return "{\"schemaVersion\":\"zoop-ai-plan-admission-1\",\"admissionId\":\"" + PlanIdentity.admissionId("alpha", REFERENCE)
                + "\",\"acceptedAt\":\"2026-10-24T01:02:03+00:00\",\"policyRevision\":1,\"policyDigest\":\"" + DIGEST
                + "\",\"manifest\":" + withDigest + ",\"authority\":{\"state\":\"active\",\"reason\":null}}";
    }

    private static String good() {
        return envelope(canonicalManifest(), PlanIdentity.sha256(canonicalManifest()));
    }

    private void malformed(String body) {
        server.respond(StubAiServer.Reply.json(201, body));
        var error = assertThrows(AiTransportException.class, () -> client.admit(REFERENCE));
        assertEquals(AiTransportException.Failure.RESPONSE_MALFORMED, error.failure());
        assertTrue(error.requestMaybeProcessed());
        assertFalse(error.getMessage().contains(StubAiServer.TOKEN));
    }

    @Test
    void admitAndExactQueryAreBoundedReferenceOnlyRequestsAndNeverExecuteAnything() {
        server.respond(StubAiServer.Reply.json(201, good()));
        PlanAdmission first = client.admit(REFERENCE);
        assertEquals(1, first.policyRevision());
        assertEquals(PlanAdmission.State.ACTIVE, first.authority().state());
        assertEquals("s2-job", first.manifest().units().getFirst().unitKey());
        var post = server.requests.getFirst();
        assertEquals("POST", post.method());
        assertEquals("/internal/v1/plan-admissions", post.path());
        assertEquals(REFERENCE.planId(), post.header("Idempotency-Key"));
        assertEquals("Bearer " + StubAiServer.TOKEN, post.header("Authorization"));
        assertEquals("{\"schemaVersion\":\"zoop-ai-plan-admission-1\",\"planId\":\"" + REFERENCE.planId()
                + "\",\"planDigest\":\"" + DIGEST + "\"}", post.body());
        server.respond(StubAiServer.Reply.json(200, good()));
        assertEquals(first, client.admit(REFERENCE));
        assertEquals(first, client.status(REFERENCE));
        assertEquals("GET", server.requests.get(2).method());
        assertEquals("/internal/v1/plan-admissions/" + REFERENCE.planId(), server.requests.get(2).path());
        assertEquals("", server.requests.get(2).body());
        assertEquals(3, server.requests.size());
    }

    @Test
    void historicalInactiveAdmissionIsRepresentedWithoutRegrantOrExecution() {
        server.respond(StubAiServer.Reply.json(200, good().replace("\"active\",\"reason\":null", "\"inactive\",\"reason\":\"policy_replaced\"")));
        var result = client.admit(REFERENCE);
        assertEquals(PlanAdmission.State.INACTIVE, result.authority().state());
        assertEquals("policy_replaced", result.authority().reason().orElseThrow());
        assertEquals(1, server.requests.size());
    }

    @Test
    void canonicalDigestIsIndependentOfWireKeyOrderButNeverOfManifestContents() {
        String unordered = "{\"units\":[" + unit() + "]," + canonicalManifest().substring(1, canonicalManifest().indexOf(",\"units\"")) + "}";
        server.respond(StubAiServer.Reply.json(201, envelope(unordered, PlanIdentity.sha256(canonicalManifest()))));
        assertEquals(PlanIdentity.sha256(canonicalManifest()), client.admit(REFERENCE).manifest().manifestDigest());
        malformed(good().replace("\"receiptSha256\":\"" + DIGEST, "\"receiptSha256\":\"" + INPUT));
    }

    @Test
    void schemaUnknownKeysNullabilityAndEnvelopeIdentityFailClosed() {
        for (String bad : List.of(
                good().replaceFirst("zoop-ai-plan-admission-1", "zoop-ai-plan-admission-2"),
                good().replace("\"authority\":", "\"observedAt\":null,\"authority\":"),
                good().replace("\"acceptedAt\":\"2026-10-24T01:02:03+00:00\"", "\"acceptedAt\":null"),
                good().replace("\"policyRevision\":1", "\"policyRevision\":true"),
                good().replace("\"policyRevision\":1", "\"policyRevision\":0"),
                good().replace("\"state\":\"active\",\"reason\":null", "\"state\":\"inactive\",\"reason\":null"),
                good().replace(PlanIdentity.admissionId("alpha", REFERENCE), "pa-" + "0".repeat(64)),
                good().replace("\"policyDigest\":", "\"policyDigest\":null,\"policyDigest\":"),
                good().replace("\"manifest\":", "\"manifest\":null,\"extra\":"))) {
            malformed(bad);
        }
    }

    @Test
    void recomputedDigestsCannotHideWrongReferencesDuplicateUnitsOrRuntimeProvenance() {
        List<UnaryOperator<String>> mutations = List.of(
                value -> value.replace("\"unitKey\":\"s2-job\"", "\"unitKey\":\"other-job\""),
                value -> value.replace("\"jobId\":\"s2-job\"}", "\"jobId\":\"other-job\"}"),
                value -> value.replace(PlanIdentity.relationJobId(REFERENCE, "s2-job", INPUT), "s3p-" + "0".repeat(64)),
                value -> value.replace("\"relationSubmit\":{\"jobId\":\"" + PlanIdentity.relationJobId(REFERENCE, "s2-job", INPUT)
                        + "\",\"provenance\":" + PROVENANCE, "\"relationSubmit\":{\"jobId\":\"" + PlanIdentity.relationJobId(REFERENCE, "s2-job", INPUT)
                        + "\",\"provenance\":" + PROVENANCE.replace("synthetic", "actual")),
                value -> value.replace("\"recordingKind\":\"authored-test\"", "\"recordingKind\":\"provider\""),
                value -> value.replace("\"units\":[" + unit() + "]", "\"units\":[" + unit() + "," + unit() + "]"),
                value -> value.replace("\"roundId\":\"round-1\"", "\"roundId\":null"),
                value -> value.replace("\"roundId\":\"round-1\"", "\"roundId\":\"round-1\",\"path\":\"private\""),
                value -> value.replace("\"planDigest\":\"" + DIGEST, "\"planDigest\":\"" + INPUT));
        for (UnaryOperator<String> mutation : mutations) {
            String changed = mutation.apply(canonicalManifest());
            assertFalse(changed.equals(canonicalManifest()));
            String digest;
            try {
                digest = PlanIdentity.sha256(PlanAdmissionWire.canonical(WireJson.parse(changed, "manifest"), false));
            } catch (WireJson.Malformed invalidScalar) {
                digest = DIGEST;
            }
            malformed(envelope(changed, digest));
        }
    }

    @Test
    void stableErrorsClassifyDefiniteRefusalsVersusAmbiguousMutationsWithoutRetry() {
        for (int status : List.of(409, 503)) {
            server.respond(seen -> StubAiServer.Reply.json(status, "{\"schemaVersion\":\"zoop-ai-plan-admission-1\",\"error\":{\"code\":\""
                    + (status == 409 ? "quota_exhausted" : "authority_unavailable") + "\",\"retryable\":" + (status == 503)
                    + ",\"requestId\":\"" + seen.requestId() + "\"}}").header("Retry-After", "2"));
            var error = assertThrows(PlanAdmissionServiceErrorException.class, () -> client.admit(REFERENCE));
            assertEquals(status, error.httpStatus());
            assertEquals(status == 503, error.requestMaybeProcessed());
            assertEquals(status == 503, error.retryable());
            assertEquals(Duration.ofSeconds(2), error.retryAfter().orElseThrow());
            var read = assertThrows(PlanAdmissionServiceErrorException.class, () -> client.status(REFERENCE));
            assertFalse(read.requestMaybeProcessed());
        }
        assertEquals(4, server.requests.size());
    }

    @Test
    void timeoutRemainsUnknownAndIsNeverAutomaticallyRetried() {
        try (var impatient = new HttpPlanAdmissionClient(settings(Duration.ofMillis(100)))) {
            server.respond(StubAiServer.Reply.json(201, good()).delay(500));
            var error = assertThrows(AiTransportException.class, () -> impatient.admit(REFERENCE));
            assertEquals(AiTransportException.Failure.TIMEOUT, error.failure());
            assertTrue(error.requestMaybeProcessed());
            assertEquals(1, server.requests.size());
        }
    }

    @Test
    void queryAlwaysSendsTheExactDigestAndNeverAnIdempotencyOrPolicyHeader() throws IOException {
        var raw = com.sun.net.httpserver.HttpServer.create(new java.net.InetSocketAddress("127.0.0.1", 0), 0);
        var observed = new java.util.concurrent.atomic.AtomicReference<String>();
        var idempotency = new java.util.concurrent.atomic.AtomicReference<String>();
        raw.createContext("/", exchange -> {
            observed.set(exchange.getRequestURI().getRawQuery());
            idempotency.set(exchange.getRequestHeaders().getFirst("Idempotency-Key"));
            byte[] body = good().getBytes(java.nio.charset.StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.getResponseHeaders().set("X-Request-ID", exchange.getRequestHeaders().getFirst("X-Request-ID"));
            exchange.sendResponseHeaders(200, body.length);
            try (var output = exchange.getResponseBody()) {
                output.write(body);
            }
            exchange.close();
        });
        raw.start();
        try (var reader = new HttpPlanAdmissionClient(AiClientSettings.of("http://127.0.0.1:" + raw.getAddress().getPort(),
                StubAiServer.TOKEN, Duration.ofSeconds(1), Duration.ofSeconds(3), 65_536))) {
            reader.status(REFERENCE);
            assertEquals("planDigest=" + DIGEST, observed.get());
            assertEquals(null, idempotency.get());
        } finally {
            raw.stop(0);
        }
    }

    @Test
    void canonicalManifestUsesLiteralUnicodeAndPythonControlEscapes() {
        String canonical = canonicalManifest().replace("round-1", "라운드😀").replace("source-1", "source:\\n한국");
        String escapedWire = canonical.replace("source:\\n한국", "source:\\n한국".replace("\n", "\\n"))
                .replace("라운드😀", "\\uB77C\\uC6B4\\uB4DC\\uD83D\\uDE00");
        // Canonical control characters are escaped, but non-ASCII characters remain literal UTF-8.
        String canonicalValid = canonical.replace("\n", "\\n");
        server.respond(StubAiServer.Reply.json(201, envelope(escapedWire, PlanIdentity.sha256(canonicalValid))));
        var admission = client.admit(REFERENCE);
        assertEquals("라운드😀", admission.manifest().round().roundId());
        assertEquals("source:\n한국", admission.manifest().round().sourceId());
    }

    @Test
    void publicIdentityFormulasHaveExactCanonicalPreimages() {
        assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", PlanIdentity.sha256("abc"));
        assertEquals("pa-" + PlanIdentity.sha256("{\"format\":\"zoop-plan-admission-identity-1\",\"planDigest\":\"" + DIGEST
                + "\",\"planId\":\"" + REFERENCE.planId() + "\",\"principal\":\"alpha\"}"), PlanIdentity.admissionId("alpha", REFERENCE));
        assertEquals("s3p-" + PlanIdentity.sha256("{\"format\":\"zoop-plan-admission-relation-job-1\",\"planDigest\":\"" + DIGEST
                + "\",\"planId\":\"" + REFERENCE.planId() + "\",\"upstream\":{\"inputDigest\":\"" + INPUT + "\",\"jobId\":\"s2-job\"}}"),
                PlanIdentity.relationJobId(REFERENCE, "s2-job", INPUT));
        assertThrows(IllegalArgumentException.class, () -> new PlanReference("../plan", DIGEST));
        assertThrows(IllegalArgumentException.class, () -> new PlanReference(REFERENCE.planId(), DIGEST.toUpperCase().replace('1', 'A')));
    }
}
