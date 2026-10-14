package com.zoop.ai.http;

import java.io.IOException;
import java.time.Duration;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.AiTransportException.Failure;
import com.zoop.ai.PipelineJob;
import com.zoop.ai.RelationServiceErrorException;
import com.zoop.ai.http.StubAiServer.Reply;
import com.zoop.ai.relation.RelationAcknowledgement;
import com.zoop.ai.relation.RelationDecision;
import com.zoop.ai.relation.RelationOperationAcknowledgement;
import com.zoop.ai.relation.RelationOperationStatus;
import com.zoop.ai.relation.RelationResult;
import com.zoop.ai.relation.RelationReviewRequest;
import com.zoop.ai.relation.RelationSubmission;
import com.zoop.ai.relation.RelationUpstream;
import com.zoop.ai.relation.UntrustedRelationPayload;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static com.zoop.ai.http.PipelineJson.CANDIDATE;
import static com.zoop.ai.http.PipelineJson.INPUT;
import static com.zoop.ai.http.PipelineJson.OTHER;
import static com.zoop.ai.http.PipelineJson.RELATION_SCHEMA;
import static com.zoop.ai.http.PipelineJson.REVAL_NONE;
import static com.zoop.ai.http.PipelineJson.REVAL_QUEUED;
import static com.zoop.ai.http.PipelineJson.REVAL_VERIFIED;
import static com.zoop.ai.http.PipelineJson.REVIEW_APPLIED;
import static com.zoop.ai.http.PipelineJson.REVIEW_UNCONFIRMED;
import static com.zoop.ai.http.PipelineJson.UPSTREAM_DIGEST;
import static com.zoop.ai.http.PipelineJson.UPSTREAM_JOB;
import static com.zoop.ai.http.StubAiServer.TOKEN;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** The S3 client against a real loopback server: submit, the source-guarded review operation, and every answer it must refuse. */
class HttpRelationClientTest {
    private static final String JOB = "s3-job-1";
    private static final String OP = "decision-0001";

    private StubAiServer server;
    private HttpRelationClient client;

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

    private HttpRelationClient clientFor(Duration requestTimeout) {
        return new HttpRelationClient(AiClientSettings.of(server.baseUrl(), TOKEN, Duration.ofSeconds(2), requestTimeout, 65_536));
    }

    private static RelationReviewRequest allow() {
        return new RelationReviewRequest(OP, CANDIDATE, INPUT, "1", RelationDecision.ALLOW);
    }

    private static Reply allowAccepted() {
        return Reply.json(202, PipelineJson.operation(OP, JOB, "allow", REVIEW_APPLIED, REVAL_QUEUED, "wait"));
    }

    private static AiTransportException malformed(Runnable call) {
        AiTransportException error = assertThrows(AiTransportException.class, call::run);
        assertEquals(Failure.RESPONSE_MALFORMED, error.failure());
        return error;
    }

    @Test
    void submitSendsOnlyProvenanceAndTheUpstreamAndRequiresTheAnswerToEchoThem() {
        RelationSubmission submission = new RelationSubmission(JOB, PipelineJob.SourceKind.SYNTHETIC,
                new RelationUpstream(UPSTREAM_JOB, UPSTREAM_DIGEST));
        server.respond(Reply.json(202, PipelineJson.relationStatus(JOB, "queued", "wait", UPSTREAM_DIGEST, "job_not_ready")));
        RelationAcknowledgement ack = client.submit(submission);
        assertEquals(PipelineJob.Disposition.NEWLY_ACCEPTED, ack.disposition());
        assertEquals(INPUT, ack.status().sourceVersion());

        StubAiServer.Seen seen = server.requests.get(0);
        assertEquals("/internal/v1/relation-jobs", seen.path());
        assertEquals(JOB, seen.header("Idempotency-Key"));
        assertEquals("{\"schemaVersion\":\"zoop-relation-s3\",\"jobId\":\"" + JOB + "\",\"provenance\":{\"sourceKind\":\"synthetic\","
                + "\"executionMode\":\"replay\",\"recordingKind\":\"authored-test\"},\"upstream\":{\"jobId\":\"" + UPSTREAM_JOB
                + "\",\"inputDigest\":\"" + UPSTREAM_DIGEST + "\"}}", seen.body());

        server.respond(Reply.json(202, PipelineJson.relationStatus(JOB, "queued", "wait", OTHER, "job_not_ready")));
        assertTrue(malformed(() -> client.submit(submission)).requestMaybeProcessed());
    }

    @Test
    void reviewSendsTheSourceExpectationsUnderTheOperationKeyAndDecodesBothOutcomes() {
        server.respond(allowAccepted());
        RelationOperationAcknowledgement accepted = client.review(JOB, allow());
        assertEquals(RelationOperationAcknowledgement.Disposition.REVIEW_ACCEPTED, accepted.disposition());
        assertEquals(RelationOperationStatus.ReviewState.APPLIED, accepted.status().review().state());
        assertEquals("2", accepted.status().review().resultingSourceRevision().orElseThrow());
        assertEquals(RelationOperationStatus.RevalidationState.QUEUED, accepted.status().revalidation().state());

        StubAiServer.Seen seen = server.requests.get(0);
        assertEquals("POST", seen.method());
        assertEquals("/internal/v1/relation-jobs/" + JOB + "/reviews", seen.path());
        assertEquals(OP, seen.header("Idempotency-Key"));
        assertEquals("{\"relationCandidateId\":\"" + CANDIDATE + "\",\"expectedSourceVersion\":\"" + INPUT
                + "\",\"expectedSourceRevision\":\"1\",\"decision\":\"allow\"}", seen.body());

        server.respond(Reply.json(200, PipelineJson.operation(OP, JOB, "reject", REVIEW_APPLIED, REVAL_NONE, "none")));
        RelationOperationAcknowledgement rejected = client.review(JOB, new RelationReviewRequest(OP, CANDIDATE, INPUT, "1", RelationDecision.REJECT));
        assertEquals(RelationOperationAcknowledgement.Disposition.REVIEW_RECORDED_OR_REPLAYED, rejected.disposition());
        assertEquals(RelationOperationStatus.RevalidationState.NOT_REQUESTED, rejected.status().revalidation().state());
    }

    @Test
    void aStaleSourceIsADefiniteRefusalAndAStaleCandidateSetIsNeverDelivered() {
        for (String code : new String[] {"source_version_conflict", "source_revision_conflict"}) {
            server.respond(seen -> Reply.json(409, PipelineJson.error(RELATION_SCHEMA, code, false, seen.requestId(), null, null)));
            RelationServiceErrorException stale = assertThrows(RelationServiceErrorException.class, () -> client.review(JOB, allow()));
            assertEquals(code, stale.code());
            assertFalse(stale.requestMaybeProcessed(), "a refusal records nothing and releases the operation id");
            assertTrue(stale.operationStatus().isEmpty());
        }

        server.respond(Reply.json(200, PipelineJson.relationResult(JOB, null, PipelineJson.relationJob(JOB, INPUT, INPUT, "1"))));
        RelationResult delivered = client.result(JOB);
        UntrustedRelationPayload payload = delivered.readyPayload().orElseThrow();
        assertEquals(INPUT, payload.candidates().get(0).sourceVersion());
        assertEquals(allow(), RelationReviewRequest.of(OP, payload.candidates().get(0), RelationDecision.ALLOW));
        assertFalse(payload.toString().contains("UNTRUSTED"));

        server.respond(Reply.json(200, PipelineJson.relationResult(JOB, null, PipelineJson.relationJob(JOB, INPUT, OTHER, "1"))));
        malformed(() -> client.result(JOB));
        server.respond(Reply.json(200, PipelineJson.relationResult(JOB, null, PipelineJson.relationJob(JOB, OTHER, OTHER, "1"))));
        malformed(() -> client.result(JOB));
        server.respond(Reply.json(200, PipelineJson.relationResult(JOB, null, PipelineJson.relationJob(JOB, INPUT, INPUT, "01"))));
        malformed(() -> client.result(JOB));
    }

    @Test
    void aForeignOrIncoherentOperationIsNeverAccepted() {
        String applied = PipelineJson.operation(OP, JOB, "allow", REVIEW_APPLIED, REVAL_QUEUED, "wait");
        server.respond(Reply.json(200, applied));
        assertEquals(OP, client.operation(JOB, OP).operationId());
        assertEquals("/internal/v1/relation-jobs/" + JOB + "/reviews/" + OP, server.requests.get(0).path());

        String[] wrong = {
                PipelineJson.operation("another-operation", JOB, "allow", REVIEW_APPLIED, REVAL_QUEUED, "wait"),
                PipelineJson.operation(OP, "another-job", "allow", REVIEW_APPLIED, REVAL_QUEUED, "wait"),
                // applied, but the recorded event is not at expected + 1
                PipelineJson.operation(OP, JOB, "allow", REVIEW_APPLIED.replace("\"2\"", "\"5\""), REVAL_QUEUED, "wait"),
                // unconfirmed review that already claims a revalidation
                PipelineJson.operation(OP, JOB, "allow", REVIEW_UNCONFIRMED, REVAL_QUEUED, "retry_review"),
                // verified without a verdict, and a verdict that is not at expected + 2
                PipelineJson.operation(OP, JOB, "allow", REVIEW_APPLIED, REVAL_VERIFIED.replace("\"eligible\"", "null"), "none"),
                PipelineJson.operation(OP, JOB, "allow", REVIEW_APPLIED, REVAL_VERIFIED.replace("\"3\"", "\"2\""), "none"),
                // a reject never requests a revalidation
                PipelineJson.operation(OP, JOB, "reject", REVIEW_APPLIED, REVAL_QUEUED, "wait"),
                applied.replace("not_published", "published"),
        };
        for (String body : wrong) {
            server.respond(Reply.json(200, body));
            malformed(() -> client.operation(JOB, OP));
        }

        // a review answer must be the answer to THIS request
        for (String body : new String[] {
                PipelineJson.operation(OP, JOB, "allow", REVIEW_APPLIED, REVAL_QUEUED, "wait").replace("\"expectedSourceRevision\":\"1\"", "\"expectedSourceRevision\":\"2\"")
                        .replace("\"resultingSourceRevision\":\"2\"", "\"resultingSourceRevision\":\"3\""),
                PipelineJson.operation(OP, JOB, "allow", REVIEW_APPLIED, REVAL_QUEUED, "wait").replace(CANDIDATE, "rc-" + "b".repeat(64)),
                PipelineJson.operation(OP, JOB, "reject", REVIEW_APPLIED, REVAL_NONE, "none")}) {
            server.respond(Reply.json(202, body));
            assertTrue(malformed(() -> client.review(JOB, allow())).requestMaybeProcessed());
        }
    }

    @Test
    void anAmbiguousReviewStaysAmbiguousAndTheOperationIsReadByKey() {
        server.respond(seen -> Reply.json(503, PipelineJson.error(RELATION_SCHEMA, "runtime_unavailable", true, seen.requestId(), null, null)));
        RelationServiceErrorException unavailable = assertThrows(RelationServiceErrorException.class, () -> client.review(JOB, allow()));
        assertTrue(unavailable.requestMaybeProcessed());
        assertTrue(unavailable.retryable());

        try (HttpRelationClient impatient = clientFor(Duration.ofMillis(300))) {
            server.respond(allowAccepted().delay(1_500));
            AiTransportException timeout = assertThrows(AiTransportException.class, () -> impatient.review(JOB, allow()));
            assertEquals(Failure.TIMEOUT, timeout.failure());
            assertTrue(timeout.requestMaybeProcessed());
        }

        // the recorded-or-not question is answered by the operation's own status, which a refusal can carry
        String unconfirmed = PipelineJson.operation(OP, JOB, "allow", REVIEW_UNCONFIRMED, REVAL_NONE, "retry_review");
        server.respond(seen -> Reply.json(409, PipelineJson.error(RELATION_SCHEMA, "review_not_confirmed", false, seen.requestId(), null, unconfirmed)));
        RelationServiceErrorException refused = assertThrows(RelationServiceErrorException.class, () -> client.recoverOperation(JOB, OP));
        assertEquals(RelationOperationStatus.Next.RETRY_REVIEW, refused.operationStatus().orElseThrow().next());
        assertFalse(refused.requestMaybeProcessed());

        server.respond(seen -> Reply.json(409, PipelineJson.error(RELATION_SCHEMA, "job_already_terminal", false, seen.requestId(), null, unconfirmed)));
        AiTransportException foreign = assertThrows(AiTransportException.class, () -> client.cancel(JOB));
        assertEquals(Failure.UNEXPECTED_RESPONSE, foreign.failure(), "a job route never produces an operation");
    }

    @Test
    void aReviewTheServiceWouldNeverAcceptIsRefusedBeforeAnythingIsSent() {
        assertThrows(IllegalArgumentException.class, () -> new RelationReviewRequest(OP, CANDIDATE, INPUT, "0", RelationDecision.ALLOW));
        assertThrows(IllegalArgumentException.class, () -> new RelationReviewRequest(OP, CANDIDATE, INPUT, "01", RelationDecision.ALLOW));
        assertThrows(IllegalArgumentException.class, () -> new RelationReviewRequest(OP, "rc-short", INPUT, "1", RelationDecision.ALLOW));
        assertThrows(IllegalArgumentException.class, () -> new RelationReviewRequest(OP, CANDIDATE, "ABC", "1", RelationDecision.ALLOW));
        assertThrows(IllegalArgumentException.class, () -> new RelationReviewRequest("../x", CANDIDATE, INPUT, "1", RelationDecision.ALLOW));
        assertThrows(IllegalArgumentException.class, () -> client.operation("../x", OP));
        assertThrows(IllegalArgumentException.class, () -> new RelationUpstream("bad upstream", UPSTREAM_DIGEST));
        assertTrue(server.requests.isEmpty());
    }

    @Test
    void everyRuntimeCallIsAReceiptWithNoFixedCapForAvailableAndWithheldResults() {
        String many = "\"receipts\":" + PipelineJson.receipts(65);
        String available = PipelineJson.relationResult(JOB, null, PipelineJson.relationJob(JOB, INPUT, INPUT, "1")).replace("\"receipts\":[]", many);
        String withheld = PipelineJson.relationResult(JOB, "source_unauthorized", "null").replace("\"receipts\":[]", many);
        assertTrue(available.contains(many) && withheld.contains(many));

        server.respond(Reply.json(200, available));
        RelationResult delivered = client.result(JOB);
        assertEquals(65, delivered.receipts().size());
        assertTrue(delivered.readyPayload().isPresent());
        server.respond(Reply.json(200, withheld));
        RelationResult hidden = client.result(JOB);
        assertEquals(65, hidden.receipts().size());
        assertTrue(hidden.payload().isEmpty());
    }

    @Test
    void anAvailableDeliveryOfAJobThatIsNotReadyIsNeverAcceptedButAReadyWithheldOneIs() {
        String available = PipelineJson.relationResult(JOB, null, PipelineJson.relationJob(JOB, INPUT, INPUT, "1"));
        String notReady = available.replace("\"state\":\"ready\"", "\"state\":\"cancelled\"");
        assertFalse(available.equals(notReady));
        server.respond(Reply.json(200, notReady));
        malformed(() -> client.result(JOB));
        server.respond(Reply.json(200, PipelineJson.relationStatus(JOB, "queued", "wait", UPSTREAM_DIGEST, null)));
        assertFalse(malformed(() -> client.status(JOB)).requestMaybeProcessed());

        // controls
        server.respond(Reply.json(200, PipelineJson.relationResult(JOB, "source_unauthorized", "null")));
        RelationResult control = client.result(JOB);
        assertEquals(PipelineJob.State.READY, control.status().state());
        assertEquals(PipelineJob.DeliveryState.WITHHELD, control.delivery().state());
        server.respond(Reply.json(200, PipelineJson.relationStatus(JOB, "queued", "wait", UPSTREAM_DIGEST, "job_not_ready")));
        assertEquals(PipelineJob.State.QUEUED, client.status(JOB).state());
    }

    @Test
    void aMutationSuccessMustBeARecordedAllowWhileAnUnconfirmedOperationStaysAValidRead() {
        String unconfirmed = PipelineJson.operation(OP, JOB, "allow", REVIEW_UNCONFIRMED, REVAL_NONE, "retry_review");
        String appliedReject = PipelineJson.operation(OP, JOB, "reject", REVIEW_APPLIED, REVAL_NONE, "none");
        RelationReviewRequest reject = new RelationReviewRequest(OP, CANDIDATE, INPUT, "1", RelationDecision.REJECT);

        // reads and error envelopes may legitimately describe both
        server.respond(Reply.json(200, unconfirmed));
        assertEquals(RelationOperationStatus.ReviewState.UNCONFIRMED, client.operation(JOB, OP).review().state());
        server.respond(Reply.json(200, appliedReject));
        assertEquals(RelationDecision.REJECT, client.operation(JOB, OP).decision());

        for (int http : new int[] {200, 202}) {
            server.respond(Reply.json(http, unconfirmed));
            assertTrue(malformed(() -> client.review(JOB, allow())).requestMaybeProcessed(), "unconfirmed is not a recorded decision");
            server.respond(Reply.json(http, unconfirmed));
            assertTrue(malformed(() -> client.recoverOperation(JOB, OP)).requestMaybeProcessed(), "unconfirmed is not a recovery");
            server.respond(Reply.json(http, appliedReject));
            assertTrue(malformed(() -> client.recoverOperation(JOB, OP)).requestMaybeProcessed(), "a reject has no revalidation to recover");
        }
        server.respond(Reply.json(202, appliedReject));
        assertTrue(malformed(() -> client.review(JOB, reject)).requestMaybeProcessed(), "202 means an allow was accepted");

        // controls
        server.respond(allowAccepted());
        assertEquals(RelationOperationAcknowledgement.Disposition.RECOVERY_ENQUEUED, client.recoverOperation(JOB, OP).disposition());
        server.respond(Reply.json(200, PipelineJson.operation(OP, JOB, "allow", REVIEW_APPLIED, REVAL_VERIFIED, "none")));
        assertEquals(RelationOperationAcknowledgement.Disposition.RECOVERY_COALESCED, client.recoverOperation(JOB, OP).disposition());
        server.respond(Reply.json(200, appliedReject));
        assertEquals(RelationOperationAcknowledgement.Disposition.REVIEW_RECORDED_OR_REPLAYED, client.review(JOB, reject).disposition());
    }

    private static String revalidation(String state) {
        return PipelineJson.reval(state, "null", "superseded".equals(state) ? "\"3\"" : "null", "\"" + PipelineJson.STAMP + "\"");
    }

    @Test
    void theOperationNextActionMustFollowTheServicesRuleForItsPhases() {
        String unknownCall = revalidation("failed").replace("\"lastRuntimeCode\":null", "\"lastRuntimeCode\":\"replay_response_unknown\"");
        String[][] valid = {
                {"allow", REVIEW_UNCONFIRMED, REVAL_NONE, "retry_review"},
                {"allow", REVIEW_APPLIED, revalidation("queued"), "wait"},
                {"allow", REVIEW_APPLIED, revalidation("running"), "wait"},
                {"allow", REVIEW_APPLIED, REVAL_VERIFIED, "none"},
                {"allow", REVIEW_APPLIED, revalidation("superseded"), "none"},
                {"allow", REVIEW_APPLIED, revalidation("interrupted"), "recover"},
                {"allow", REVIEW_APPLIED, revalidation("failed"), "recover"},
                {"allow", REVIEW_APPLIED, unknownCall, "operator_reconcile"},
                {"allow", REVIEW_APPLIED, revalidation("cancelled"), "none"},
                {"reject", REVIEW_APPLIED, REVAL_NONE, "none"},
        };
        String[][] contradictory = {
                {"allow", REVIEW_UNCONFIRMED, REVAL_NONE, "none"},
                {"allow", REVIEW_UNCONFIRMED, REVAL_NONE, "wait"},
                {"allow", REVIEW_APPLIED, revalidation("queued"), "none"},
                {"allow", REVIEW_APPLIED, revalidation("queued"), "recover"},
                {"allow", REVIEW_APPLIED, revalidation("running"), "none"},
                {"allow", REVIEW_APPLIED, REVAL_VERIFIED, "wait"},
                {"allow", REVIEW_APPLIED, REVAL_VERIFIED, "recover"},
                {"allow", REVIEW_APPLIED, revalidation("superseded"), "wait"},
                {"allow", REVIEW_APPLIED, revalidation("interrupted"), "none"},
                {"allow", REVIEW_APPLIED, revalidation("interrupted"), "wait"},
                {"allow", REVIEW_APPLIED, revalidation("failed"), "none"},
                {"allow", REVIEW_APPLIED, revalidation("failed"), "operator_reconcile"},
                {"allow", REVIEW_APPLIED, unknownCall, "recover"},
                {"allow", REVIEW_APPLIED, revalidation("cancelled"), "recover"},
                {"reject", REVIEW_APPLIED, REVAL_NONE, "wait"},
        };
        for (String[] row : valid) {
            server.respond(Reply.json(200, PipelineJson.operation(OP, JOB, row[0], row[1], row[2], row[3])));
            assertEquals(row[3], client.operation(JOB, OP).next().name().toLowerCase(java.util.Locale.ROOT), String.join(" | ", row));
        }
        for (String[] row : contradictory) {
            server.respond(Reply.json(200, PipelineJson.operation(OP, JOB, row[0], row[1], row[2], row[3])));
            assertFalse(malformed(() -> client.operation(JOB, OP)).requestMaybeProcessed(), String.join(" | ", row));
        }
    }

    @Test
    void aRecoveryAcknowledgementMayShowAnyCoherentPhaseOfARecordedAllowBecauseTheDispatcherRunsOutsideItsGate() {
        for (String phase : new String[] {REVAL_QUEUED, REVAL_VERIFIED}) {
            String next = phase.equals(REVAL_QUEUED) ? "wait" : "none";
            server.respond(Reply.json(202, PipelineJson.operation(OP, JOB, "allow", REVIEW_APPLIED, phase, next)));
            RelationOperationAcknowledgement ack = client.recoverOperation(JOB, OP);
            assertEquals(RelationOperationAcknowledgement.Disposition.RECOVERY_ENQUEUED, ack.disposition());
        }
    }

    @Test
    void aRecoveryAcknowledgementMayAlreadyBeFailedOrInterruptedAndTheFollowingReadTellsWhatToDo() {
        String stamp = "\"" + PipelineJson.STAMP + "\"";
        String unknownCall = PipelineJson.reval("failed", "null", "null", stamp)
                .replace("\"lastRuntimeCode\":null", "\"lastRuntimeCode\":\"replay_response_unknown\"");
        String[][] terminal = {
                {PipelineJson.reval("failed", "null", "null", stamp), "recover"},
                {PipelineJson.reval("interrupted", "null", "null", stamp), "recover"},
                {unknownCall, "operator_reconcile"},
        };
        for (String[] row : terminal) {
            String body = PipelineJson.operation(OP, JOB, "allow", REVIEW_APPLIED, row[0], row[1]);
            server.respond(Reply.json(202, body));
            assertEquals(RelationOperationAcknowledgement.Disposition.RECOVERY_ENQUEUED, client.recoverOperation(JOB, OP).disposition());
            server.respond(Reply.json(200, body));
            assertEquals(row[1], client.operation(JOB, OP).next().name().toLowerCase(java.util.Locale.ROOT));
        }
    }
}
