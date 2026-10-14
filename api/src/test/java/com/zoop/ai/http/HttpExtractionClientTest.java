package com.zoop.ai.http;

import java.io.IOException;
import java.time.Duration;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.AiTransportException.Failure;
import com.zoop.ai.ExtractionServiceErrorException;
import com.zoop.ai.PipelineJob;
import com.zoop.ai.extraction.ExtractionAcknowledgement;
import com.zoop.ai.extraction.ExtractionResult;
import com.zoop.ai.extraction.ExtractionSubmission;
import com.zoop.ai.http.StubAiServer.Reply;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static com.zoop.ai.http.PipelineJson.APPROVED;
import static com.zoop.ai.http.PipelineJson.EXTRACTION_SCHEMA;
import static com.zoop.ai.http.PipelineJson.INPUT;
import static com.zoop.ai.http.PipelineJson.OTHER;
import static com.zoop.ai.http.StubAiServer.TOKEN;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** The S2 client against a real loopback server: what it sends, and every answer it must refuse to trust. */
class HttpExtractionClientTest {
    private static final String JOB = "s2-job-1";

    private StubAiServer server;
    private HttpExtractionClient client;

    @BeforeEach
    void start() throws IOException {
        server = new StubAiServer();
        client = clientFor(Duration.ofSeconds(5));
    }

    @AfterEach
    void stop() {
        client.close();
        server.close();
    }

    private HttpExtractionClient clientFor(Duration requestTimeout) {
        return new HttpExtractionClient(AiClientSettings.of(server.baseUrl(), TOKEN, Duration.ofSeconds(2), requestTimeout, 65_536));
    }

    private static ExtractionSubmission submission() {
        return new ExtractionSubmission(JOB, APPROVED);
    }

    private static Reply status(int http, String state, String next, String approved) {
        return Reply.json(http, PipelineJson.extractionStatus(JOB, state, next, approved, "ready".equals(state) ? null : "job_not_ready"));
    }

    private static AiTransportException malformed(Runnable call) {
        AiTransportException error = assertThrows(AiTransportException.class, call::run);
        assertEquals(Failure.RESPONSE_MALFORMED, error.failure());
        return error;
    }

    @Test
    void submitSendsOnlyTheJobIdAndTheApprovedDigestAndDecodesBothAcceptedAnswers() {
        server.respond(status(202, "queued", "wait", APPROVED));
        ExtractionAcknowledgement created = client.submit(submission());
        assertEquals(PipelineJob.Disposition.NEWLY_ACCEPTED, created.disposition());
        assertEquals(APPROVED, created.status().approvedRequestDigest());
        assertEquals(PipelineJob.State.QUEUED, created.status().state());

        StubAiServer.Seen seen = server.requests.get(0);
        assertEquals("POST", seen.method());
        assertEquals("/internal/v1/extraction-jobs", seen.path());
        assertEquals("{\"schemaVersion\":\"zoop-extraction-s2-2\",\"jobId\":\"" + JOB + "\",\"approvedRequestDigest\":\"" + APPROVED + "\"}",
                seen.body());
        assertEquals(JOB, seen.header("Idempotency-Key"));
        assertEquals("Bearer " + TOKEN, seen.header("Authorization"));

        server.respond(status(200, "queued", "wait", APPROVED));
        assertEquals(PipelineJob.Disposition.ALREADY_ACCEPTED, client.submit(submission()).disposition());
        assertEquals(2, server.requests.size(), "one request per call, no retry");
    }

    @Test
    void anAnswerForAnotherApprovalOrAnotherJobIsNeverAccepted() {
        server.respond(status(202, "queued", "wait", OTHER));
        AiTransportException rotated = malformed(() -> client.submit(submission()));
        assertTrue(rotated.requestMaybeProcessed(), "the submit may have been registered: read status before acting");
        assertFalse(rotated.getMessage().contains(OTHER) || rotated.getMessage().contains(TOKEN));

        server.respond(Reply.json(200, PipelineJson.extractionStatus("someone-elses-job", "queued", "wait", APPROVED, "job_not_ready")));
        assertFalse(malformed(() -> client.status(JOB)).requestMaybeProcessed(), "a read is never maybe-processed");

        server.respond(Reply.json(200, PipelineJson.extractionStatus(JOB, "approved", "wait", APPROVED, null)));
        malformed(() -> client.status(JOB));
    }

    @Test
    void candidatesAreDeliveredOnlyWhenAvailableAndBoundToTheJobAndItsDigest() {
        String job = PipelineJson.extractionJob(JOB, INPUT);
        server.respond(Reply.json(200, PipelineJson.extractionResult(JOB, APPROVED, null, null, job)));
        ExtractionResult delivered = client.result(JOB);
        assertEquals(INPUT, delivered.readyPayload().orElseThrow().inputDigest());
        assertTrue(delivered.readyPayload().orElseThrow().untrustedJson().contains("UNTRUSTED-TEXT"));
        assertFalse(delivered.readyPayload().orElseThrow().toString().contains("UNTRUSTED-TEXT"));

        server.respond(Reply.json(200, PipelineJson.extractionResult(JOB, APPROVED, null, null, PipelineJson.extractionJob(JOB, OTHER))));
        malformed(() -> client.result(JOB));
        server.respond(Reply.json(200, PipelineJson.extractionResult(JOB, APPROVED, "source_unauthorized", "source_unauthorized", job)));
        malformed(() -> client.result(JOB));
        server.respond(Reply.json(200, PipelineJson.extractionResult(JOB, APPROVED, null, "source_unauthorized", "null")));
        malformed(() -> client.result(JOB));
    }

    @Test
    void aWithheldResultCarriesNoContentOnlyItsReasonAndReceipts() {
        server.respond(Reply.json(200, PipelineJson.extractionResult(JOB, APPROVED, "approval_revoked", "approval_revoked", "null")));
        ExtractionResult withheld = client.result(JOB);
        assertEquals(PipelineJob.DeliveryState.WITHHELD, withheld.delivery().state());
        assertEquals("approval_revoked", withheld.delivery().reason().orElseThrow());
        assertTrue(withheld.payload().isEmpty() && withheld.readyPayload().isEmpty());
        assertEquals("extract", withheld.receipts().get(0).stage());
        assertEquals(PipelineJob.State.READY, withheld.status().state(), "delivery does not change the job state");
    }

    @Test
    void refusalsAreDecodedWithTheirStatusAndAnAmbiguousMutationStaysAmbiguous() {
        server.respond(seen -> Reply.json(403, PipelineJson.error(EXTRACTION_SCHEMA, "request_not_approved", false, seen.requestId(), null, null)));
        ExtractionServiceErrorException refused = assertThrows(ExtractionServiceErrorException.class, () -> client.submit(submission()));
        assertEquals("request_not_approved", refused.code());
        assertFalse(refused.requestMaybeProcessed(), "a definitive 4xx");

        String ready = PipelineJson.extractionStatus(JOB, "ready", "fetch_result", APPROVED, null);
        server.respond(seen -> Reply.json(409, PipelineJson.error(EXTRACTION_SCHEMA, "job_already_terminal", false, seen.requestId(), ready, null)));
        ExtractionServiceErrorException terminal = assertThrows(ExtractionServiceErrorException.class, () -> client.cancel(JOB));
        assertEquals(PipelineJob.State.READY, terminal.status().orElseThrow().state());

        server.respond(seen -> Reply.json(503, PipelineJson.error(EXTRACTION_SCHEMA, "runtime_unavailable", true, seen.requestId(), null, null))
                .header("Retry-After", "2"));
        ExtractionServiceErrorException unavailable = assertThrows(ExtractionServiceErrorException.class, () -> client.submit(submission()));
        assertTrue(unavailable.requestMaybeProcessed(), "a 5xx may follow a committed registration");
        assertTrue(unavailable.retryable());
        assertEquals(Duration.ofSeconds(2), unavailable.retryAfter().orElseThrow());
        assertFalse(assertThrows(ExtractionServiceErrorException.class, () -> client.status(JOB)).requestMaybeProcessed());

        server.respond(Reply.json(403, PipelineJson.error(EXTRACTION_SCHEMA, "request_not_approved", false, "not-the-request-id", null, null)));
        AiTransportException spoofed = assertThrows(AiTransportException.class, () -> client.submit(submission()));
        assertEquals(Failure.UNEXPECTED_RESPONSE, spoofed.failure());
    }

    @Test
    void aSlowServiceIsATimeoutThatMayHaveRegisteredTheJobAndIsNeverRetried() {
        try (HttpExtractionClient impatient = clientFor(Duration.ofMillis(300))) {
            server.respond(status(202, "queued", "wait", APPROVED).delay(1_500));
            AiTransportException timeout = assertThrows(AiTransportException.class, () -> impatient.submit(submission()));
            assertEquals(Failure.TIMEOUT, timeout.failure());
            assertTrue(timeout.requestMaybeProcessed());
            assertEquals(1, server.requests.size());
            AiTransportException read = assertThrows(AiTransportException.class, () -> impatient.result(JOB));
            assertEquals(Failure.TIMEOUT, read.failure());
            assertFalse(read.requestMaybeProcessed());
        }
    }

    @Test
    void everyRuntimeCallIsAReceiptWithNoFixedCapForAvailableAndWithheldResults() {
        String one = "\"receipts\":[{\"stage\":\"extract\",\"state\":\"received\",\"verdict\":null}]";
        String many = "\"receipts\":" + PipelineJson.receipts(65);
        String available = PipelineJson.extractionResult(JOB, APPROVED, null, null, PipelineJson.extractionJob(JOB, INPUT)).replace(one, many);
        String withheld = PipelineJson.extractionResult(JOB, APPROVED, "source_unauthorized", "source_unauthorized", "null").replace(one, many);
        assertTrue(available.contains(many) && withheld.contains(many));

        server.respond(Reply.json(200, available));
        ExtractionResult delivered = client.result(JOB);
        assertEquals(65, delivered.receipts().size());
        assertTrue(delivered.readyPayload().isPresent());
        server.respond(Reply.json(200, withheld));
        ExtractionResult hidden = client.result(JOB);
        assertEquals(65, hidden.receipts().size());
        assertTrue(hidden.payload().isEmpty());
    }

    @Test
    void anAvailableDeliveryOfAJobThatIsNotReadyIsNeverAcceptedButAReadyWithheldOneIs() {
        String available = PipelineJson.extractionResult(JOB, APPROVED, null, null, PipelineJson.extractionJob(JOB, INPUT));
        String notReady = available.replace("\"state\":\"ready\"", "\"state\":\"cancelled\"");
        assertFalse(available.equals(notReady));
        server.respond(Reply.json(200, notReady));
        malformed(() -> client.result(JOB));
        server.respond(Reply.json(200, PipelineJson.extractionStatus(JOB, "queued", "wait", APPROVED, null)));
        assertFalse(malformed(() -> client.status(JOB)).requestMaybeProcessed());
        server.respond(Reply.json(202, PipelineJson.extractionStatus(JOB, "running", "wait", APPROVED, null)));
        assertTrue(malformed(() -> client.submit(submission())).requestMaybeProcessed());

        // controls: a ready job whose delivery is withheld, and a queued job that says so
        server.respond(Reply.json(200, PipelineJson.extractionResult(JOB, APPROVED, "source_unauthorized", "source_unauthorized", "null")));
        ExtractionResult control = client.result(JOB);
        assertEquals(PipelineJob.State.READY, control.status().state());
        assertEquals(PipelineJob.DeliveryState.WITHHELD, control.delivery().state());
        server.respond(Reply.json(200, PipelineJson.extractionStatus(JOB, "queued", "wait", APPROVED, "job_not_ready")));
        assertEquals(PipelineJob.State.QUEUED, client.status(JOB).state());
    }
}
