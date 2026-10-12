package com.zoop.ai.http;

import java.io.IOException;
import java.net.ServerSocket;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.function.UnaryOperator;

import com.zoop.ai.AiAnalysisClient;
import com.zoop.ai.AiClientException;
import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiServiceErrorException;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.AiTransportException.Failure;
import com.zoop.ai.AnalysisAcknowledgement;
import com.zoop.ai.AnalysisAcknowledgement.Disposition;
import com.zoop.ai.AnalysisJobStatus;
import com.zoop.ai.AnalysisKind;
import com.zoop.ai.AnalysisResult;
import com.zoop.ai.AnalysisSubmission;
import com.zoop.ai.ExecutionMode;
import com.zoop.ai.http.StubAiServer.Reply;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;

import static com.zoop.ai.http.StubAiServer.DIGEST;
import static com.zoop.ai.http.StubAiServer.TOKEN;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Protocol tests against a real loopback HTTP server: headers, framing, decoding, bounds and every failure mode. */
class HttpAiAnalysisClientTest {
    private static final String JOB = "job-1";
    private static final String INPUT = "{\"amount\":1.10,\"text\":\"한글 \\\"quoted\\\"\",\"nested\":{\"a\":[1,2]}}";
    private static final String PROVENANCE = "{\"sourceKind\":\"synthetic\"}";

    private StubAiServer server;
    private HttpAiAnalysisClient client;

    @BeforeEach
    void start() throws IOException {
        server = new StubAiServer();
        client = clientFor(server.baseUrl(), Duration.ofSeconds(5));
    }

    @AfterEach
    void stop() {
        MDC.clear();
        client.close();
        server.close();
    }

    private static HttpAiAnalysisClient clientFor(String baseUrl, Duration requestTimeout) {
        return new HttpAiAnalysisClient(AiClientSettings.of(baseUrl, TOKEN, Duration.ofSeconds(2), requestTimeout, 65_536));
    }

    private static AnalysisSubmission submission() {
        return new AnalysisSubmission(JOB, AnalysisKind.DOCUMENT_SUMMARY, ExecutionMode.REPLAY, INPUT, PROVENANCE);
    }

    private AiTransportException transport(Runnable call) {
        return assertThrows(AiTransportException.class, call::run);
    }

    private void assertNoLeak(AiClientException error, String... forbidden) {
        String text = error.getMessage() + " " + error;
        for (String value : forbidden) {
            assertFalse(text.contains(value), "exception text leaked " + value);
        }
        assertFalse(text.contains(TOKEN));
        assertFalse(text.contains(server.baseUrl()));
        assertFalse(text.contains("127.0.0.1"));
    }

    // ---- request framing ----

    @Test
    void submitSendsContractEnvelopeAuthIdempotencyKeyAndPreservesContentExactly() {
        server.respond(seen -> Reply.json(202, StubAiServer.status(JOB, "queued", "wait")).header("Retry-After", "2"));

        AnalysisAcknowledgement ack = client.submit(submission());

        assertEquals(Disposition.NEWLY_ACCEPTED, ack.disposition());
        assertEquals(AnalysisJobStatus.Next.WAIT, ack.status().next());
        assertEquals(Duration.ofSeconds(2), ack.status().retryAfter().orElseThrow());
        assertEquals(1, server.requests.size());
        StubAiServer.Seen seen = server.requests.get(0);
        assertEquals("POST", seen.method());
        assertEquals("/internal/v1/analysis-jobs", seen.path());
        assertEquals("Bearer " + TOKEN, seen.header("Authorization"));
        assertEquals(JOB, seen.header("Idempotency-Key"));
        assertEquals("application/json", seen.header("Content-Type"));
        assertEquals("{\"schemaVersion\":\"zoop-ai-s1-1\",\"jobId\":\"job-1\",\"kind\":\"document-summary\",\"mode\":\"replay\","
                + "\"input\":" + INPUT + ",\"provenance\":" + PROVENANCE + "}", seen.body());
    }

    @Test
    void everyKindKeepsTheSchemaVersionAndItsWireName() {
        server.respond(seen -> {
            java.util.regex.Matcher kind = java.util.regex.Pattern.compile("\"kind\":\"([a-z-]+)\"").matcher(seen.body());
            assertTrue(kind.find());
            return Reply.json(202, StubAiServer.statusFor(JOB, kind.group(1), "live", "queued", "wait"));
        });
        for (AnalysisKind kind : AnalysisKind.values()) {
            AnalysisAcknowledgement ack = client.submit(new AnalysisSubmission(JOB, kind, ExecutionMode.LIVE, INPUT, PROVENANCE));
            assertEquals(kind, ack.status().kind());
            assertEquals(ExecutionMode.LIVE, ack.status().mode());
        }
        assertEquals(4, server.requests.size());
        for (int i = 0; i < 4; i++) {
            String body = server.requests.get(i).body();
            assertTrue(body.startsWith("{\"schemaVersion\":\"zoop-ai-s1-1\",\"jobId\":\"job-1\",\"kind\":\""
                    + AnalysisKind.values()[i].wire() + "\",\"mode\":\"live\""), body);
        }
    }

    @Test
    void anAcceptanceForAnotherKindOrModeIsMalformedOn200And202() {
        for (int status : new int[] {200, 202}) {
            // submission is document-summary / replay
            server.respond(seen -> Reply.json(status, StubAiServer.statusFor(JOB, "document-sentiment", "replay", "queued", "wait")));
            assertEquals(Failure.RESPONSE_MALFORMED, transport(() -> client.submit(submission())).failure(), "kind " + status);
            server.respond(seen -> Reply.json(status, StubAiServer.statusFor(JOB, "document-summary", "live", "queued", "wait")));
            assertEquals(Failure.RESPONSE_MALFORMED, transport(() -> client.submit(submission())).failure(), "mode " + status);
        }
    }

    @Test
    void submit202IsAcceptanceNotCompletionAnd200IsAnIdempotentReplay() {
        server.respond(seen -> Reply.json(200, StubAiServer.status(JOB, "ready", "fetch_result")));
        AnalysisAcknowledgement replay = client.submit(submission());
        assertEquals(Disposition.ALREADY_ACCEPTED, replay.disposition());

        server.respond(seen -> Reply.json(202, StubAiServer.status(JOB, "queued", "wait")));
        AnalysisAcknowledgement fresh = client.submit(submission());
        assertEquals(Disposition.NEWLY_ACCEPTED, fresh.disposition());
        assertEquals(AnalysisJobStatus.State.QUEUED, fresh.status().state());
        assertNotEquals(AnalysisJobStatus.State.READY, fresh.status().state());
    }

    @Test
    void getAndPostOperationsUseExactPathsAndNoIdempotencyKeyOrBodyForReads() {
        server.respond(seen -> Reply.json(200, StubAiServer.status(JOB, "ready", "fetch_result")));
        client.status(JOB);
        client.cancel(JOB);
        server.respond(seen -> Reply.json(202, StubAiServer.status(JOB, "queued", "wait")));
        assertEquals(Disposition.RECOVERY_ENQUEUED, client.recover(JOB).disposition());
        server.respond(seen -> Reply.json(200, StubAiServer.status(JOB, "queued", "wait")));
        assertEquals(Disposition.RECOVERY_COALESCED, client.recover(JOB).disposition());

        List<String> lines = server.requests.stream().map(r -> r.method() + " " + r.path()).toList();
        assertEquals(List.of("GET /internal/v1/analysis-jobs/job-1", "POST /internal/v1/analysis-jobs/job-1/cancel",
                "POST /internal/v1/analysis-jobs/job-1/recover", "POST /internal/v1/analysis-jobs/job-1/recover"), lines);
        server.requests.forEach(r -> assertEquals("Bearer " + TOKEN, r.header("Authorization")));
        assertEquals(null, server.requests.get(0).header("Idempotency-Key"));
        assertEquals("", server.requests.get(0).body());
    }

    @Test
    void basePathPrefixOfAReverseProxyIsKept() {
        server.respond(seen -> Reply.json(200, StubAiServer.status(JOB, "ready", "fetch_result")));
        try (HttpAiAnalysisClient prefixed = clientFor(server.baseUrl() + "/ai/", Duration.ofSeconds(5))) {
            prefixed.status(JOB);
        }
        assertEquals("/ai/internal/v1/analysis-jobs/job-1", server.requests.get(0).path());
    }

    @Test
    void invalidJobIdsAndBodiesAreRefusedBeforeAnyRequest() {
        for (String bad : new String[] {"", "..", ".", "a/b", "a b", "x".repeat(121), "ä", "a?b", "a#b"}) {
            assertThrows(IllegalArgumentException.class, () -> client.status(bad), bad);
            assertThrows(IllegalArgumentException.class, () -> client.result(bad), bad);
            assertThrows(IllegalArgumentException.class, () -> client.cancel(bad), bad);
            assertThrows(IllegalArgumentException.class, () -> client.recover(bad), bad);
            assertThrows(IllegalArgumentException.class,
                    () -> new AnalysisSubmission(bad, AnalysisKind.DOCUMENT_SUMMARY, ExecutionMode.REPLAY, INPUT, PROVENANCE), bad);
        }
        for (String badJson : new String[] {"[]", "\"x\"", "{\"a\":1,\"a\":2}", "{", "{} {}", "{\"a\":NaN}", ""}) {
            assertThrows(IllegalArgumentException.class, () -> client.submit(
                    new AnalysisSubmission(JOB, AnalysisKind.DOCUMENT_SUMMARY, ExecutionMode.REPLAY, badJson, PROVENANCE)), badJson);
            assertThrows(IllegalArgumentException.class, () -> client.submit(
                    new AnalysisSubmission(JOB, AnalysisKind.DOCUMENT_SUMMARY, ExecutionMode.REPLAY, INPUT, badJson)), badJson);
        }
        String huge = "{\"t\":\"" + "x".repeat(2_000_000) + "\"}";
        assertThrows(IllegalArgumentException.class, () -> client.submit(
                new AnalysisSubmission(JOB, AnalysisKind.DOCUMENT_SUMMARY, ExecutionMode.REPLAY, huge, PROVENANCE)));
        assertEquals(0, server.requests.size());
    }

    // ---- request id ----

    @Test
    void aValidInboundRequestIdIsForwardedAndNeverBecomesTheIdempotencyKey() {
        MDC.put("requestId", "inbound-req.1_A");
        server.respond(seen -> Reply.json(202, StubAiServer.status(JOB, "queued", "wait")));
        client.submit(submission());
        StubAiServer.Seen seen = server.requests.get(0);
        assertEquals("inbound-req.1_A", seen.requestId());
        assertEquals(JOB, seen.header("Idempotency-Key"));
    }

    @Test
    void unsafeOrOversizedInboundRequestIdsAreReplacedNotForwarded() {
        server.respond(seen -> Reply.json(200, StubAiServer.status(JOB, "queued", "wait")));
        for (String unsafe : new String[] {"has space", "a".repeat(129), "new\r\nline", "한글", "semi;colon", ""}) {
            MDC.put("requestId", unsafe);
            client.status(JOB);
        }
        MDC.clear();
        client.status(JOB);
        assertEquals(7, server.requests.size());
        for (StubAiServer.Seen seen : server.requests) {
            assertTrue(seen.requestId().matches("[0-9a-f-]{36}"), seen.requestId());
        }
        assertEquals(7, server.requests.stream().map(StubAiServer.Seen::requestId).distinct().count());
    }

    @Test
    void aResponseThatDoesNotEchoTheRequestIdIsMalformedEvenWhenItLooksValid() {
        server.respond(Reply.json(200, StubAiServer.status(JOB, "queued", "wait")).withoutEcho());
        assertEquals(Failure.RESPONSE_MALFORMED, transport(() -> client.status(JOB)).failure());

        server.respond(Reply.json(200, StubAiServer.status(JOB, "queued", "wait")).withoutEcho().header("X-Request-ID", "someone-else"));
        assertEquals(Failure.RESPONSE_MALFORMED, transport(() -> client.status(JOB)).failure());
    }

    // ---- decoded refusals ----

    @Test
    void serviceErrorEnvelopeIsDecodedWithoutRawBodyOrToken() {
        server.respond(seen -> Reply.json(409, StubAiServer.error("idempotency_conflict", false, seen.requestId(), null, null)));
        AiServiceErrorException error = assertThrows(AiServiceErrorException.class, () -> client.submit(submission()));
        assertEquals(409, error.httpStatus());
        assertEquals("idempotency_conflict", error.code());
        assertFalse(error.retryable());
        assertEquals(server.requests.get(0).requestId(), error.requestId());
        assertNoLeak(error, "amount", INPUT);
    }

    @Test
    void retryableRefusalKeepsRetryAfterAndRuntimeCodeAndFieldAndIsNeverRetried() {
        server.respond(seen -> Reply.json(503, StubAiServer.error("runtime_unavailable", true, seen.requestId(), "Idempotency-Key", null))
                .header("Retry-After", "7"));
        AiServiceErrorException error = assertThrows(AiServiceErrorException.class, () -> client.submit(submission()));
        assertTrue(error.retryable());
        assertEquals(Duration.ofSeconds(7), error.retryAfter().orElseThrow());
        assertEquals("Idempotency-Key", error.field().orElseThrow());
        assertEquals(1, server.requests.size(), "a POST must never be retried automatically");
    }

    @Test
    void aDecodedServiceErrorIsNotProofThatAMutationDidNotCommit() {
        // The service may register the job in its runtime and still answer 503 runtime_unavailable (jobs.py keeps the reservation).
        java.util.concurrent.atomic.AtomicBoolean committed = new java.util.concurrent.atomic.AtomicBoolean();
        server.respond(seen -> {
            boolean submit = seen.method().equals("POST") && seen.path().equals("/internal/v1/analysis-jobs");
            if (submit && committed.compareAndSet(false, true)) {
                return Reply.json(503, StubAiServer.error("runtime_unavailable", true, seen.requestId(), null, null)).header("Retry-After", "2");
            }
            if (submit) {
                return Reply.json(200, StubAiServer.status(JOB, "queued", "wait"));
            }
            return committed.get() ? Reply.json(200, StubAiServer.status(JOB, "queued", "wait"))
                    : Reply.json(404, StubAiServer.error("job_not_found", false, seen.requestId(), null, null));
        });

        AiServiceErrorException error = assertThrows(AiServiceErrorException.class, () -> client.submit(submission()));
        assertEquals(503, error.httpStatus());
        assertTrue(error.retryable());
        assertTrue(error.requestMaybeProcessed(), "a 5xx answer to a mutation is an unknown outcome");
        assertEquals(1, server.requests.size(), "no automatic retry");

        // status-first recovery with the same job id finds the committed job; the same-id submit is an idempotent replay.
        assertEquals(AnalysisJobStatus.State.QUEUED, client.status(JOB).state());
        assertEquals(Disposition.ALREADY_ACCEPTED, client.submit(submission()).disposition());
        assertTrue(server.requests.stream().allMatch(r -> !r.method().equals("POST") || JOB.equals(r.header("Idempotency-Key"))));
    }

    @Test
    void requestMaybeProcessedIsConservativeOnlyForMutating5xx() {
        server.respond(seen -> Reply.json(409, StubAiServer.error("idempotency_conflict", false, seen.requestId(), null, null)));
        assertFalse(assertThrows(AiServiceErrorException.class, () -> client.submit(submission())).requestMaybeProcessed());
        assertFalse(assertThrows(AiServiceErrorException.class, () -> client.cancel(JOB)).requestMaybeProcessed());
        server.respond(seen -> Reply.json(503, StubAiServer.error("service_busy", true, seen.requestId(), null, null)));
        assertTrue(assertThrows(AiServiceErrorException.class, () -> client.submit(submission())).requestMaybeProcessed());
        assertTrue(assertThrows(AiServiceErrorException.class, () -> client.cancel(JOB)).requestMaybeProcessed());
        assertTrue(assertThrows(AiServiceErrorException.class, () -> client.recover(JOB)).requestMaybeProcessed());
        assertFalse(assertThrows(AiServiceErrorException.class, () -> client.status(JOB)).requestMaybeProcessed());
        assertFalse(assertThrows(AiServiceErrorException.class, () -> client.result(JOB)).requestMaybeProcessed());
    }

    @Test
    void bothExceptionTypesShareOneOutcomeRuleAcrossAllFiveOperations() {
        java.util.Map<String, java.util.function.Supplier<Object>> mutating = java.util.Map.of(
                "submit", () -> client.submit(submission()), "cancel", () -> client.cancel(JOB), "recover", () -> client.recover(JOB));
        java.util.Map<String, java.util.function.Supplier<Object>> reads = java.util.Map.of(
                "status", () -> client.status(JOB), "result", () -> client.result(JOB));
        java.util.List<Reply> failures = List.of(
                Reply.json(503, "{\"not\":\"an error envelope\"}"),
                Reply.bytes(502, "<html/>".getBytes(StandardCharsets.UTF_8)).header("Content-Type", "text/html"));
        for (Reply failure : failures) {
            server.respond(failure);
            mutating.forEach((name, call) -> assertTrue(assertThrows(AiClientException.class, call::get).requestMaybeProcessed(), name));
            reads.forEach((name, call) -> assertFalse(assertThrows(AiClientException.class, call::get).requestMaybeProcessed(), name));
        }
        server.respond(seen -> Reply.json(503, StubAiServer.error("runtime_unavailable", true, seen.requestId(), null, null)));
        mutating.forEach((name, call) -> {
            AiClientException error = assertThrows(AiClientException.class, call::get);
            assertInstanceOf(AiServiceErrorException.class, error);
            assertTrue(error.requestMaybeProcessed(), name);
        });
        reads.forEach((name, call) -> {
            AiClientException error = assertThrows(AiClientException.class, call::get);
            assertInstanceOf(AiServiceErrorException.class, error);
            assertFalse(error.requestMaybeProcessed(), name);
        });
    }

    @Test
    void terminalRefusalCarriesTheStatusForTheCallerDecision() {
        server.respond(seen -> Reply.json(409, StubAiServer.error("job_already_terminal", false, seen.requestId(), null,
                StubAiServer.status(JOB, "ready", "fetch_result", "2", "0"))));
        AiServiceErrorException error = assertThrows(AiServiceErrorException.class, () -> client.cancel(JOB));
        assertEquals("job_already_terminal", error.code());
        assertEquals(AnalysisJobStatus.State.READY, error.status().orElseThrow().state());
        assertEquals(2, error.status().orElseThrow().usage().providerAttempts());
    }

    @Test
    void errorEnvelopeWithAnotherRequestIdUppercaseCodeOrForeignStatusIsNotTrusted() {
        server.respond(Reply.json(404, StubAiServer.error("job_not_found", false, "other-request", null, null)));
        assertEquals(Failure.UNEXPECTED_RESPONSE, transport(() -> client.status(JOB)).failure());

        server.respond(seen -> Reply.json(404, StubAiServer.error("JOB_NOT_FOUND", false, seen.requestId(), null, null)));
        assertEquals(Failure.UNEXPECTED_RESPONSE, transport(() -> client.status(JOB)).failure());

        server.respond(seen -> Reply.json(409, StubAiServer.error("job_already_terminal", false, seen.requestId(), null,
                StubAiServer.status("another-job", "ready", "fetch_result"))));
        assertEquals(Failure.UNEXPECTED_RESPONSE, transport(() -> client.cancel(JOB)).failure());
    }

    @Test
    void gatewayStyleHtmlAndEmptyAnswersAreUnexpectedResponsesWithoutTheirBody() {
        server.respond(Reply.bytes(502, "<html>LEAKED-GATEWAY-PAGE</html>".getBytes(StandardCharsets.UTF_8))
                .header("Content-Type", "text/html"));
        AiTransportException error = transport(() -> client.status(JOB));
        assertEquals(Failure.UNEXPECTED_RESPONSE, error.failure());
        assertEquals(502, error.httpStatus().getAsInt());
        assertFalse(error.requestMaybeProcessed(), "a failed read changes nothing");
        assertTrue(transport(() -> client.cancel(JOB)).requestMaybeProcessed(), "a failed mutation is an unknown outcome");
        assertNoLeak(error, "LEAKED-GATEWAY-PAGE");

        server.respond(Reply.bytes(500, new byte[0]));
        assertEquals(Failure.UNEXPECTED_RESPONSE, transport(() -> client.status(JOB)).failure());
    }

    @Test
    void successStatusesOutsideTheContractAreRejected() {
        server.respond(seen -> Reply.json(201, StubAiServer.status(JOB, "queued", "wait")));
        assertEquals(Failure.UNEXPECTED_RESPONSE, transport(() -> client.submit(submission())).failure());
        server.respond(seen -> Reply.json(202, StubAiServer.status(JOB, "queued", "wait")));
        assertEquals(Failure.UNEXPECTED_RESPONSE, transport(() -> client.status(JOB)).failure());
        assertEquals(Failure.UNEXPECTED_RESPONSE, transport(() -> client.cancel(JOB)).failure());
        server.respond(Reply.bytes(204, new byte[0]));
        assertEquals(Failure.UNEXPECTED_RESPONSE, transport(() -> client.recover(JOB)).failure());
    }

    // ---- malformed 2xx ----

    @Test
    void malformedSuccessBodiesFailClosedWithoutLeakingContent() {
        String good = StubAiServer.status(JOB, "queued", "wait");
        List<UnaryOperator<String>> mutations = List.of(
                s -> s.replace("zoop-ai-internal-1", "zoop-ai-internal-2"),
                s -> s.replace("\"jobId\":\"job-1\"", "\"jobId\":\"job-2\""),
                s -> s.replace("\"state\":\"queued\"", "\"state\":\"LEAKED-STATE\""),
                s -> s.replace("\"kind\":\"document-summary\"", "\"kind\":\"document-other\""),
                s -> s.replace("\"mode\":\"replay\"", "\"mode\":\"other\""),
                s -> s.replace("\"next\":\"wait\"", "\"next\":\"LEAKED-NEXT\""),
                s -> s.replace("\"providerAttempts\":0", "\"providerAttempts\":\"0\""),
                s -> s.replace("\"providerAttempts\":0", "\"providerAttempts\":-1"),
                s -> s.replace("\"providerAttempts\":0", "\"providerAttempts\":1.5"),
                s -> s.replace(",\"next\":\"wait\"", ""),
                s -> s.replace("\"usage\":{", "\"usage\":{\"replayCalls\":3,"),
                s -> s.replace(DIGEST, "abc"),
                s -> s.replace("2026-10-12T03:00:00Z", "yesterday"),
                s -> s.replace("\"artifactIds\":[]", "\"artifactIds\":{}"),
                s -> s.replace("\"failure\":null", "\"failure\":\"LEAKED\""),
                s -> s + " trailing",
                s -> "[" + s + "]",
                s -> "\"LEAKED-STRING\"",
                s -> s.substring(0, s.length() - 5),
                s -> "");
        for (int i = 0; i < mutations.size(); i++) {
            String body = mutations.get(i).apply(good);
            server.respond(seen -> Reply.json(200, body));
            AiTransportException error = transport(() -> client.status(JOB));
            assertEquals(Failure.RESPONSE_MALFORMED, error.failure(), "mutation " + i);
            assertEquals(200, error.httpStatus().getAsInt());
            assertNoLeak(error, "LEAKED");
        }
    }

    @Test
    void invalidUtf8WrongContentTypeAndNonJsonAreMalformed() {
        byte[] bad = StubAiServer.status(JOB, "queued", "wait").getBytes(StandardCharsets.UTF_8);
        bad[20] = (byte) 0xFF;
        server.respond(Reply.bytes(200, bad));
        assertEquals(Failure.RESPONSE_MALFORMED, transport(() -> client.status(JOB)).failure());

        server.respond(Reply.json(200, StubAiServer.status(JOB, "queued", "wait")).header("Content-Type", "text/plain"));
        assertEquals(Failure.RESPONSE_MALFORMED, transport(() -> client.status(JOB)).failure());

        server.respond(Reply.json(200, StubAiServer.status(JOB, "queued", "wait")).header("Content-Type", "application/json; charset=utf-16"));
        assertEquals(Failure.RESPONSE_MALFORMED, transport(() -> client.status(JOB)).failure());
    }

    @Test
    void duplicateKeysAndDeepNestingAreRejected() {
        String duplicate = StubAiServer.status(JOB, "queued", "wait").replace("\"phase\":", "\"state\":\"ready\",\"phase\":");
        server.respond(Reply.json(200, duplicate));
        assertEquals(Failure.RESPONSE_MALFORMED, transport(() -> client.status(JOB)).failure());

        String deep = "{\"a\":".repeat(200) + "1" + "}".repeat(200);
        server.respond(Reply.json(200, deep));
        assertEquals(Failure.RESPONSE_MALFORMED, transport(() -> client.status(JOB)).failure());
    }

    // ---- results ----

    @Test
    void availableResultCarriesAnUntrustedPayloadBoundToTheJob() {
        server.respond(Reply.json(200, StubAiServer.result(JOB, "ready", "available", null, StubAiServer.job(JOB, "ready"),
                "[" + StubAiServer.RECEIPT + "]")));
        AnalysisResult result = client.result(JOB);
        assertEquals(AnalysisResult.Delivery.State.AVAILABLE, result.delivery().state());
        assertTrue(result.readyPayload().isPresent());
        assertTrue(result.payload().orElseThrow().untrustedJson().contains("UNTRUSTED-MODEL-TEXT"));
        assertFalse(result.payload().orElseThrow().toString().contains("UNTRUSTED-MODEL-TEXT"));
        assertEquals(1, result.receipts().size());
        assertEquals(AnalysisResult.Receipt.CallState.RECEIVED, result.receipts().get(0).state());
        assertEquals(3L, result.receipts().get(0).tokens().orElseThrow().inputTokens());
        assertEquals(java.time.Instant.parse("2026-10-12T03:00:00.263955Z"), result.receipts().get(0).startedAt());
        assertEquals("/internal/v1/analysis-jobs/job-1/result", server.requests.get(0).path());
    }

    @Test
    void receiptVersionFieldsArePreservedForAvailableAndWithheldResults() {
        String receipts = "[" + StubAiServer.RECEIPT + "]";
        server.respond(Reply.json(200, StubAiServer.result(JOB, "ready", "available", null, StubAiServer.job(JOB, "ready"), receipts)));
        AnalysisResult.Receipt available = client.result(JOB).receipts().get(0);
        server.respond(Reply.json(200, StubAiServer.result(JOB, "ready", "withheld", "source_rights_unknown_or_denied", null, receipts)));
        AnalysisResult withheld = client.result(JOB);
        for (AnalysisResult.Receipt receipt : List.of(available, withheld.receipts().get(0))) {
            assertEquals("p-1", receipt.promptVersion());
            assertEquals("s-1", receipt.schemaVersion());
            assertEquals("v-1", receipt.policyVersion());
        }
        assertTrue(withheld.payload().isEmpty());
    }

    @Test
    void receiptConfigurationFieldsAreRequiredStrings() {
        for (String field : new String[] {"promptVersion", "schemaVersion", "policyVersion", "provider", "providerRevision", "model"}) {
            String present = "\"" + field + "\":\"";
            for (UnaryOperator<String> mutation : List.<UnaryOperator<String>>of(
                    s -> s.replaceFirst("\"" + field + "\":\"[^\"]*\",?", ""),
                    s -> s.replaceFirst("\"" + field + "\":\"[^\"]*\"", "\"" + field + "\":null"),
                    s -> s.replaceFirst("\"" + field + "\":\"[^\"]*\"", "\"" + field + "\":7"))) {
                String receipt = mutation.apply(StubAiServer.RECEIPT);
                assertFalse(receipt.equals(StubAiServer.RECEIPT), field);
                server.respond(Reply.json(200, StubAiServer.result(JOB, "ready", "withheld", "source_rights_unknown_or_denied", null,
                        "[" + receipt + "]")));
                assertEquals(Failure.RESPONSE_MALFORMED, transport(() -> client.result(JOB)).failure(), field + " " + present);
            }
        }
    }

    @Test
    void withheldResultIsNeverAvailableAndHasNoPayload() {
        server.respond(Reply.json(200, StubAiServer.result(JOB, "ready", "withheld", "source_rights_unknown_or_denied", null,
                "[" + StubAiServer.RECEIPT + "]")));
        AnalysisResult result = client.result(JOB);
        assertEquals(AnalysisResult.Delivery.State.WITHHELD, result.delivery().state());
        assertEquals("source_rights_unknown_or_denied", result.delivery().reason().orElseThrow());
        assertTrue(result.payload().isEmpty());
        assertTrue(result.readyPayload().isEmpty());
        assertEquals(AnalysisJobStatus.State.READY, result.status().state(), "withheld content does not change job state");
        assertEquals(1, result.receipts().size(), "receipts remain for usage accounting");
    }

    @Test
    void inconsistentDeliveryOrPayloadIdentityIsMalformed() {
        String receipts = "[]";
        String[] bodies = {
                StubAiServer.result(JOB, "ready", "withheld", "source_rights_unknown_or_denied", StubAiServer.job(JOB, "ready"), receipts),
                StubAiServer.result(JOB, "ready", "available", null, null, receipts),
                StubAiServer.result(JOB, "ready", "withheld", null, null, receipts),
                StubAiServer.result(JOB, "ready", "available", "reason", StubAiServer.job(JOB, "ready"), receipts),
                StubAiServer.result(JOB, "ready", "maybe", null, null, receipts),
                StubAiServer.result(JOB, "ready", "available", null, StubAiServer.job("other-job", "ready"), receipts),
                StubAiServer.result(JOB, "ready", "available", null, StubAiServer.job(JOB, "failed"), receipts),
                StubAiServer.result(JOB, "ready", "available", null,
                        StubAiServer.job(JOB, "ready").replace("zoop-ai-s1-1", "zoop-ai-s1-9"), receipts),
                StubAiServer.result(JOB, "ready", "available", null,
                        StubAiServer.job(JOB, "ready").replace("\"kind\":\"document-summary\"", "\"kind\":\"briefing-outlook\""), receipts),
                StubAiServer.result(JOB, "ready", "available", null, StubAiServer.job(JOB, "ready"), "{}"),
        };
        for (int i = 0; i < bodies.length; i++) {
            String body = bodies[i];
            server.respond(seen -> Reply.json(200, body));
            assertEquals(Failure.RESPONSE_MALFORMED, transport(() -> client.result(JOB)).failure(), "case " + i);
        }
    }

    @Test
    void cancelKeepsTheReportedUsageInsteadOfInventingZero() {
        server.respond(seen -> Reply.json(200, StubAiServer.status(JOB, "cancelled", "none", "1", "1")));
        AnalysisJobStatus status = client.cancel(JOB);
        assertEquals(AnalysisJobStatus.State.CANCELLED, status.state());
        assertEquals(1, status.usage().providerAttempts());
        assertEquals(1, status.unreceiptedAttempts(), "an unreceipted attempt may still produce a late receipt and cost");
        assertEquals(null, status.usage().cost(), "no cost is invented");
    }

    // ---- transport failures ----

    @Test
    void redirectsAreNeverFollowedAndTheTokenIsNeverResent() throws IOException {
        try (StubAiServer elsewhere = new StubAiServer()) {
            elsewhere.respond(Reply.json(200, StubAiServer.status(JOB, "queued", "wait")));
            server.respond(Reply.bytes(307, new byte[0]).header("Location", elsewhere.baseUrl() + "/internal/v1/analysis-jobs"));
            for (int attempt = 0; attempt < 2; attempt++) {
                AiTransportException error = transport(() -> client.submit(submission()));
                assertEquals(Failure.REDIRECT_REFUSED, error.failure());
                assertEquals(307, error.httpStatus().getAsInt());
                assertTrue(error.requestMaybeProcessed());
                assertNoLeak(error, elsewhere.baseUrl());
            }
            assertEquals(2, server.requests.size());
            assertEquals(0, elsewhere.requests.size(), "nothing, and in particular no bearer token, reached the redirect target");
        }
    }

    @Test
    void timeoutIsBoundedExplicitUnknownAndNotRetried() throws Exception {
        server.respond(Reply.json(202, StubAiServer.status(JOB, "queued", "wait")).delay(1_500));
        try (HttpAiAnalysisClient fast = clientFor(server.baseUrl(), Duration.ofMillis(300))) {
            long began = System.nanoTime();
            AiTransportException error = transport(() -> fast.submit(submission()));
            long elapsedMs = (System.nanoTime() - began) / 1_000_000;
            assertEquals(Failure.TIMEOUT, error.failure());
            assertTrue(error.requestMaybeProcessed(), "a timed-out submit is an unknown outcome");
            assertTrue(error.getMessage().contains("TIMEOUT"));
            assertTrue(elapsedMs < 1_400, "returned at the configured deadline, not the server's delay: " + elapsedMs);
            Thread.sleep(2_000);
            assertEquals(1, server.requests.size(), "no automatic retry of a POST");
        }
    }

    @Test
    void aBodyThatStallsAfterHeadersStillHitsTheTotalDeadline() {
        byte[] body = StubAiServer.status(JOB, "queued", "wait").getBytes(StandardCharsets.UTF_8);
        server.respond(Reply.bytes(200, body).stallBody(2_000));
        try (HttpAiAnalysisClient fast = clientFor(server.baseUrl(), Duration.ofMillis(400))) {
            AiTransportException read = transport(() -> fast.status(JOB));
            assertEquals(Failure.TIMEOUT, read.failure());
            assertFalse(read.requestMaybeProcessed(), "a timed-out read cannot have changed anything");
            assertTrue(transport(() -> fast.cancel(JOB)).requestMaybeProcessed(), "a timed-out mutation is unknown");
        }
    }

    @Test
    void connectionRefusedIsNotSentAndAllOtherFailuresMayHaveBeenProcessed() throws IOException {
        int port;
        try (ServerSocket probe = new ServerSocket(0, 1, java.net.InetAddress.getLoopbackAddress())) {
            port = probe.getLocalPort();
        }
        try (HttpAiAnalysisClient closed = clientFor("http://127.0.0.1:" + port, Duration.ofSeconds(2))) {
            AiTransportException error = transport(() -> closed.submit(submission()));
            assertEquals(Failure.CONNECT_FAILED, error.failure());
            assertFalse(error.requestMaybeProcessed());
            assertNoLeak(error);
        }
    }

    @Test
    void oversizedResponsesAreCutOffWhetherDeclaredOrChunked() {
        byte[] big = ("{\"pad\":\"" + "x".repeat(100_000) + "\"}").getBytes(StandardCharsets.UTF_8);
        server.respond(Reply.bytes(200, big));
        assertEquals(Failure.RESPONSE_TOO_LARGE, transport(() -> client.status(JOB)).failure());
        server.respond(Reply.bytes(200, big).chunked());
        assertEquals(Failure.RESPONSE_TOO_LARGE, transport(() -> client.result(JOB)).failure());
        server.respond(Reply.bytes(503, big));
        AiTransportException error = transport(() -> client.status(JOB));
        assertEquals(Failure.RESPONSE_TOO_LARGE, error.failure());
        assertFalse(error.requestMaybeProcessed(), "a failed read changes nothing");
        assertTrue(transport(() -> client.recover(JOB)).requestMaybeProcessed());
    }

    @Test
    void closedClientRefusesFurtherCallsAsTransportFailure() {
        server.respond(seen -> Reply.json(200, StubAiServer.status(JOB, "queued", "wait")));
        client.close();
        assertThrows(AiClientException.class, () -> client.status(JOB));
        client = clientFor(server.baseUrl(), Duration.ofSeconds(1));
    }

    @Test
    void allFiveOperationsAreOnTheInterfaceTheFeaturesDependOn() {
        AiAnalysisClient asInterface = client;
        server.respond(seen -> Reply.json(200, StubAiServer.status(JOB, "queued", "wait")));
        assertEquals(JOB, asInterface.status(JOB).jobId());
    }
}
