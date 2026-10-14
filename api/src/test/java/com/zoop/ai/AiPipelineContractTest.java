package com.zoop.ai;

import java.io.IOException;
import java.net.ServerSocket;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Predicate;
import java.util.function.Supplier;

import com.zoop.ai.AiTransportException.Failure;
import com.zoop.ai.PipelineJob.DeliveryState;
import com.zoop.ai.PipelineJob.Disposition;
import com.zoop.ai.PipelineJob.DispatchState;
import com.zoop.ai.PipelineJob.Next;
import com.zoop.ai.PipelineJob.State;
import com.zoop.ai.extraction.ExtractionAcknowledgement;
import com.zoop.ai.extraction.ExtractionJobStatus;
import com.zoop.ai.extraction.ExtractionResult;
import com.zoop.ai.extraction.ExtractionSubmission;
import com.zoop.ai.http.HttpExtractionClient;
import com.zoop.ai.http.HttpRelationClient;
import com.zoop.ai.relation.RelationAcknowledgement;
import com.zoop.ai.relation.RelationDecision;
import com.zoop.ai.relation.RelationJobStatus;
import com.zoop.ai.relation.RelationOperationAcknowledgement;
import com.zoop.ai.relation.RelationOperationStatus;
import com.zoop.ai.relation.RelationOperationStatus.RevalidationState;
import com.zoop.ai.relation.RelationOperationStatus.ReviewState;
import com.zoop.ai.relation.RelationResult;
import com.zoop.ai.relation.RelationReviewRequest;
import com.zoop.ai.relation.RelationSubmission;
import com.zoop.ai.relation.RelationUpstream;
import com.zoop.ai.relation.UntrustedRelationPayload;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.api.TestMethodOrder;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

/**
 * Real Java -> ai/service (uvicorn) -> installed {@code zoop-ai-extract} / {@code zoop-ai-relation}, replay only, over a fresh
 * synthetic operator world (actual ingestion, a server-approved S2 request, authored fixtures). Not runnable on its own:
 * {@code make api-ai-pipeline-smoke} starts the services and exports {@code ZOOP_AI_PIPELINE_MANIFEST}. Without it every test
 * fails; none skips.
 *
 * <p>The operator's server-side files (source registry, S2 approvals, S3 upstream allowlist) are changed here by copying
 * prepared variants over the services' own files, exactly as an operator would edit them, and are restored afterwards.
 */
@Tag("ai-pipeline-contract")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class AiPipelineContractTest {
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final Duration POLL_LIMIT = Duration.ofSeconds(120);
    private static final String S3_JOB_1 = "gate-s3-job-1";
    private static final String S3_JOB_2 = "gate-s3-job-2";
    private static final String ALLOW_KEY = "gate-allow-0001";
    private static final String REJECT_KEY = "gate-reject-0001";

    private JsonNode manifest;
    private JsonNode world;
    private ExtractionSubmission s2Submission;
    private RelationUpstream upstream;
    private final List<AutoCloseable> closeables = new ArrayList<>();
    private HttpExtractionClient s2;
    private HttpRelationClient s3;
    private JsonNode main;

    private UntrustedRelationPayload.Candidate held;
    private UntrustedRelationPayload.Candidate eligible;
    private String sourceVersion;

    @BeforeAll
    void load() throws IOException {
        String path = System.getenv("ZOOP_AI_PIPELINE_MANIFEST");
        if (path == null || path.isBlank()) {
            fail("ZOOP_AI_PIPELINE_MANIFEST is not set. These tests need live ai/service processes: run `make api-ai-pipeline-smoke`.");
        }
        manifest = JSON.readTree(Files.readString(Path.of(path)));
        world = manifest.get("world");
        s2Submission = new ExtractionSubmission(world.get("s2JobId").stringValue(), world.get("s2ApprovedRequestDigest").stringValue());
        upstream = new RelationUpstream(world.get("upstream").get("jobId").stringValue(), world.get("upstream").get("inputDigest").stringValue());
        main = manifest.get("main");
        s2 = extraction(main, "alpha");
        s3 = relation(main, "alpha");
    }

    @AfterAll
    void close() throws Exception {
        for (AutoCloseable closeable : closeables) {
            closeable.close();
        }
    }

    private static AiClientSettings settings(String baseUrl, String token) {
        return AiClientSettings.of(baseUrl, token, Duration.ofSeconds(3), Duration.ofSeconds(60), 8 * 1024 * 1024);
    }

    private HttpExtractionClient extraction(JsonNode service, String principal) {
        HttpExtractionClient created = new HttpExtractionClient(settings(service.get("baseUrl").stringValue(),
                service.get("tokens").get(principal).stringValue()));
        closeables.add(created);
        return created;
    }

    private HttpRelationClient relation(JsonNode service, String principal) {
        HttpRelationClient created = new HttpRelationClient(settings(service.get("baseUrl").stringValue(),
                service.get("tokens").get(principal).stringValue()));
        closeables.add(created);
        return created;
    }

    private RelationSubmission s3Submission(String jobId) {
        return new RelationSubmission(jobId, PipelineJob.SourceKind.SYNTHETIC, upstream);
    }

    private Path file(String name) {
        return Path.of(main.get("files").get(name).stringValue());
    }

    /** Polls a read. A retryable 503 means the pipeline ledger was busy for a moment; the read is repeated. */
    private static <T> T eventually(Supplier<T> read, Predicate<T> done, String what) {
        long deadline = System.nanoTime() + POLL_LIMIT.toNanos();
        T last = null;
        do {
            try {
                last = read.get();
                if (done.test(last)) {
                    return last;
                }
            } catch (AiServiceRejectionException error) {
                if (!(error.retryable() && error.httpStatus() == 503)) {
                    throw error;
                }
            }
            pause(200);
        } while (System.nanoTime() < deadline);
        return fail("timed out waiting for " + what + "; last=" + last);
    }

    private static void pause(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            fail("interrupted");
        }
    }

    private static ExtractionServiceErrorException s2Refusal(Supplier<?> call) {
        return assertThrows(ExtractionServiceErrorException.class, call::get);
    }

    private static RelationServiceErrorException s3Refusal(Supplier<?> call) {
        return assertThrows(RelationServiceErrorException.class, call::get);
    }

    private static void assertDefinite(AiServiceRejectionException refusal, int http, String code) {
        assertEquals(http, refusal.httpStatus(), refusal.getMessage());
        assertEquals(code, refusal.code());
        assertFalse(refusal.requestMaybeProcessed(), "a definitive 4xx");
    }

    private ExtractionJobStatus s2Ready(HttpExtractionClient client, String jobId) {
        return eventually(() -> client.status(jobId), s -> s.state() == State.READY && s.dispatch().state() == DispatchState.IDLE,
                "S2 " + jobId + " ready");
    }

    private RelationJobStatus s3Ready(HttpRelationClient client, String jobId) {
        return eventually(() -> client.status(jobId), s -> s.state() == State.READY && s.dispatch().state() == DispatchState.IDLE,
                "S3 " + jobId + " ready");
    }

    private static UntrustedRelationPayload.Candidate candidate(UntrustedRelationPayload payload, String relationCandidateId) {
        return payload.candidates().stream().filter(c -> c.relationCandidateId().equals(relationCandidateId)).findFirst().orElseThrow();
    }

    private UntrustedRelationPayload payload(HttpRelationClient client, String jobId) {
        RelationResult result = client.result(jobId);
        assertEquals(DeliveryState.AVAILABLE, result.delivery().state(), jobId);
        return result.readyPayload().orElseThrow();
    }

    // ---- S2 ----

    @Test
    @Order(1)
    void anS2JobIsBuiltFromAServerApprovedRequestAndDeliveredByTheRealPipeline() throws IOException {
        ExtractionAcknowledgement ack = s2.submit(s2Submission);
        assertEquals(Disposition.NEWLY_ACCEPTED, ack.disposition());
        assertEquals(s2Submission.jobId(), ack.status().jobId());
        assertEquals(s2Submission.approvedRequestDigest(), ack.status().approvedRequestDigest());

        ExtractionJobStatus ready = s2Ready(s2, s2Submission.jobId());
        assertEquals(Next.FETCH_RESULT, ready.next());
        assertEquals(upstream.inputDigest(), ready.inputDigest(), "the service-built job has the operator job's input digest");
        assertEquals(new ExtractionJobStatus.Usage(world.get("s2ReplayCalls").longValue(), 0, 0, 0), ready.usage(), "replay only, no provider");

        ExtractionResult result = s2.result(s2Submission.jobId());
        assertEquals(DeliveryState.AVAILABLE, result.delivery().state());
        JsonNode content = JSON.readTree(result.readyPayload().orElseThrow().untrustedJson());
        assertEquals(world.get("s2Counts"), content.get("counts"));
        assertFalse(content.get("eventCandidates").isEmpty());
        for (JsonNode event : content.get("eventCandidates").values()) {
            assertFalse(event.get("approved").booleanValue(), "a candidate is never an approval");
        }
        assertFalse(content.get("topicCandidates").isEmpty());
        assertFalse(result.receipts().isEmpty());
    }

    @Test
    @Order(2)
    void s2RefusalsOwnershipAndTerminalStatesAreDecodedFromTheRealService() {
        String jobId = s2Submission.jobId();
        ExtractionAcknowledgement replay = s2.submit(s2Submission);
        assertEquals(Disposition.ALREADY_ACCEPTED, replay.disposition());
        assertEquals(State.READY, replay.status().state());

        // a different approved request under the same key, and a digest or a job id the operator never approved
        assertDefinite(s2Refusal(() -> s2.submit(new ExtractionSubmission(jobId, world.get("s2OtherApprovedRequestDigest").stringValue()))),
                409, "idempotency_conflict");
        assertDefinite(s2Refusal(() -> s2.submit(new ExtractionSubmission(world.get("s2OtherJobId").stringValue(), "0".repeat(64)))),
                403, "request_not_approved");
        assertDefinite(s2Refusal(() -> s2.submit(new ExtractionSubmission("gate-unlisted-s2", s2Submission.approvedRequestDigest()))),
                403, "request_not_approved");

        HttpExtractionClient beta = extraction(main, "beta");
        assertDefinite(s2Refusal(() -> beta.status(jobId)), 404, "job_not_found");
        assertDefinite(s2Refusal(() -> beta.result(jobId)), 404, "job_not_found");
        assertDefinite(s2Refusal(() -> beta.cancel(jobId)), 404, "job_not_found");
        assertDefinite(s2Refusal(() -> beta.submit(s2Submission)), 403, "request_not_approved");
        HttpExtractionClient viewer = extraction(main, "viewer");
        assertDefinite(s2Refusal(() -> viewer.submit(s2Submission)), 403, "scope_denied");
        assertDefinite(s2Refusal(() -> viewer.status(jobId)), 404, "job_not_found");
        HttpExtractionClient stranger = new HttpExtractionClient(settings(main.get("baseUrl").stringValue(), "x".repeat(43)));
        closeables.add(stranger);
        assertDefinite(s2Refusal(() -> stranger.status(jobId)), 401, "authentication_required");

        ExtractionServiceErrorException cancel = s2Refusal(() -> s2.cancel(jobId));
        assertDefinite(cancel, 409, "job_already_terminal");
        assertEquals(State.READY, cancel.status().orElseThrow().state(), "a ready job is not cancelled");
        assertEquals(DeliveryState.AVAILABLE, cancel.status().orElseThrow().delivery().state());
        ExtractionServiceErrorException recover = s2Refusal(() -> s2.recover(jobId));
        assertDefinite(recover, 409, "job_not_recoverable");
        assertEquals(State.READY, recover.status().orElseThrow().state());
    }

    // ---- S3 ----

    @Test
    @Order(3)
    void anS2JobIsNotAnS3UpstreamUntilTheOperatorListsItAndTheJobIsBuiltOverTheRealPipeline() throws IOException {
        RelationServiceErrorException unlisted = s3Refusal(() -> s3.submit(s3Submission(S3_JOB_1)));
        assertDefinite(unlisted, 403, "upstream_not_allowed");
        assertDefinite(s3Refusal(() -> s3.status(S3_JOB_1)), 404, "job_not_found");

        Files.copy(file("upstreamsListed"), file("upstreams"), StandardCopyOption.REPLACE_EXISTING);
        RelationAcknowledgement ack = s3.submit(s3Submission(S3_JOB_1));
        assertEquals(Disposition.NEWLY_ACCEPTED, ack.disposition());
        assertEquals(upstream, ack.status().upstream());

        RelationJobStatus ready = s3Ready(s3, S3_JOB_1);
        assertEquals(Next.FETCH_RESULT, ready.next());
        assertEquals(new RelationJobStatus.Usage(world.get("relationReplayCalls").longValue(), 0, 0, 0), ready.usage());
        sourceVersion = ready.sourceVersion();
        assertNotEquals(upstream.inputDigest(), sourceVersion, "the S3 job has its own source version");

        UntrustedRelationPayload payload = payload(s3, S3_JOB_1);
        assertEquals(sourceVersion, payload.inputDigest());
        assertFalse(payload.candidates().isEmpty());
        payload.candidates().forEach(c -> assertEquals(sourceVersion, c.sourceVersion()));
        assertEquals(world.get("counts"), JSON.readTree(payload.untrustedJson()).get("counts"));
        held = candidate(payload, world.get("heldRelation").stringValue());
        eligible = candidate(payload, world.get("eligibleRelation").stringValue());
        assertEquals(Long.toString(world.get("heldRevision").longValue()), held.sourceRevision());

        assertEquals(Disposition.ALREADY_ACCEPTED, s3.submit(s3Submission(S3_JOB_1)).disposition());
        HttpRelationClient beta = relation(main, "beta");
        assertDefinite(s3Refusal(() -> beta.submit(s3Submission(S3_JOB_1))), 409, "job_id_unavailable");
        assertDefinite(s3Refusal(() -> beta.status(S3_JOB_1)), 404, "job_not_found");
    }

    @Test
    @Order(4)
    void aReviewIsGuardedByTheAiSourceVersionAndRevisionAndARefusalRecordsNothing() {
        RelationReviewRequest stale = new RelationReviewRequest("gate-stale-revision", held.relationCandidateId(), sourceVersion,
                Integer.toString(Integer.parseInt(held.sourceRevision()) + 1), RelationDecision.ALLOW);
        RelationReviewRequest wrongVersion = new RelationReviewRequest("gate-stale-version", held.relationCandidateId(), "0".repeat(64),
                held.sourceRevision(), RelationDecision.ALLOW);
        RelationReviewRequest notHold = RelationReviewRequest.of("gate-not-hold", eligible, RelationDecision.ALLOW);
        RelationReviewRequest unknown = new RelationReviewRequest("gate-unknown", "rc-" + "f".repeat(64), sourceVersion, "1", RelationDecision.ALLOW);

        assertDefinite(s3Refusal(() -> s3.review(S3_JOB_1, stale)), 409, "source_revision_conflict");
        assertDefinite(s3Refusal(() -> s3.review(S3_JOB_1, wrongVersion)), 409, "source_version_conflict");
        assertDefinite(s3Refusal(() -> s3.review(S3_JOB_1, notHold)), 409, "review_target_not_hold");
        assertDefinite(s3Refusal(() -> s3.review(S3_JOB_1, unknown)), 404, "relation_candidate_not_found");
        for (RelationReviewRequest refused : List.of(stale, wrongVersion, notHold, unknown)) {
            assertDefinite(s3Refusal(() -> s3.operation(S3_JOB_1, refused.operationId())), 404, "operation_not_found");
        }

        RelationReviewRequest valid = RelationReviewRequest.of("gate-foreign-0001", held, RelationDecision.ALLOW);
        assertDefinite(s3Refusal(() -> relation(main, "viewer").review(S3_JOB_1, valid)), 403, "scope_denied");
        assertDefinite(s3Refusal(() -> relation(main, "beta").review(S3_JOB_1, valid)), 404, "job_not_found");
        assertDefinite(s3Refusal(() -> s3.operation(S3_JOB_1, valid.operationId())), 404, "operation_not_found");
        assertEquals(held.sourceRevision(), candidate(payload(s3, S3_JOB_1), held.relationCandidateId()).sourceRevision(),
                "no refusal changed the relation");
    }

    @Test
    @Order(5)
    void anAllowIsRecordedThenRevalidatedAndTheNewRevisionMakesTheOldOneStale() {
        RelationReviewRequest allow = RelationReviewRequest.of(ALLOW_KEY, held, RelationDecision.ALLOW);
        long expected = Long.parseLong(held.sourceRevision());
        RelationOperationAcknowledgement accepted = s3.review(S3_JOB_1, allow);
        assertEquals(RelationOperationAcknowledgement.Disposition.REVIEW_ACCEPTED, accepted.disposition());
        RelationOperationStatus first = accepted.status();
        assertEquals(RelationDecision.ALLOW, first.decision());
        assertEquals("alpha", first.reviewer(), "the reviewer is the authenticated principal");
        assertEquals(ReviewState.APPLIED, first.review().state());
        assertEquals(Long.toString(expected + 1), first.review().resultingSourceRevision().orElseThrow());
        assertNotEquals(RevalidationState.NOT_REQUESTED, first.revalidation().state());

        RelationOperationStatus verified = eventually(() -> s3.operation(S3_JOB_1, ALLOW_KEY),
                o -> o.revalidation().state() == RevalidationState.VERIFIED, "revalidation verified");
        assertEquals(RelationOperationStatus.Verdict.ELIGIBLE, verified.revalidation().verdict().orElseThrow());
        assertEquals(Long.toString(expected + 2), verified.revalidation().resultingSourceRevision().orElseThrow());
        assertEquals(RelationOperationStatus.Next.NONE, verified.next());

        RelationOperationAcknowledgement replay = s3.review(S3_JOB_1, allow);
        assertEquals(RelationOperationAcknowledgement.Disposition.REVIEW_RECORDED_OR_REPLAYED, replay.disposition());
        assertEquals(RevalidationState.VERIFIED, replay.status().revalidation().state());
        assertDefinite(s3Refusal(() -> s3.review(S3_JOB_1, new RelationReviewRequest(ALLOW_KEY, held.relationCandidateId(), sourceVersion,
                held.sourceRevision(), RelationDecision.REJECT))), 409, "idempotency_conflict");
        RelationOperationAcknowledgement settled = s3.recoverOperation(S3_JOB_1, ALLOW_KEY);
        assertEquals(RelationOperationAcknowledgement.Disposition.RECOVERY_COALESCED, settled.disposition());
        assertEquals(RevalidationState.VERIFIED, settled.status().revalidation().state());

        assertDefinite(s3Refusal(() -> relation(main, "beta").operation(S3_JOB_1, ALLOW_KEY)), 404, "job_not_found");
        assertDefinite(s3Refusal(() -> relation(main, "viewer").operation(S3_JOB_1, ALLOW_KEY)), 404, "job_not_found");

        UntrustedRelationPayload after = payload(s3, S3_JOB_1);
        assertEquals(Long.toString(expected + 2), candidate(after, held.relationCandidateId()).sourceRevision());
        assertDefinite(s3Refusal(() -> s3.review(S3_JOB_1, RelationReviewRequest.of("gate-after-stale", held, RelationDecision.ALLOW))), 409,
                "source_revision_conflict");
        assertDefinite(s3Refusal(() -> s3.review(S3_JOB_1, RelationReviewRequest.of("gate-after-current",
                candidate(after, held.relationCandidateId()), RelationDecision.ALLOW))), 409, "review_target_not_hold");
    }

    @Test
    @Order(6)
    void aRejectIsRecordedWithoutRevalidationOnItsOwnJobAndOperationsNeverCrossJobs() {
        assertEquals(Disposition.NEWLY_ACCEPTED, s3.submit(s3Submission(S3_JOB_2)).disposition());
        RelationJobStatus ready = s3Ready(s3, S3_JOB_2);
        UntrustedRelationPayload payload = payload(s3, S3_JOB_2);
        UntrustedRelationPayload.Candidate second = candidate(payload, held.relationCandidateId());
        assertEquals(held.sourceRevision(), second.sourceRevision(), "a job's relation history is its own");
        assertEquals(ready.sourceVersion(), second.sourceVersion());

        RelationOperationAcknowledgement rejected = s3.review(S3_JOB_2, RelationReviewRequest.of(REJECT_KEY, second, RelationDecision.REJECT));
        assertEquals(RelationOperationAcknowledgement.Disposition.REVIEW_RECORDED_OR_REPLAYED, rejected.disposition());
        RelationOperationStatus operation = rejected.status();
        assertEquals(ReviewState.APPLIED, operation.review().state());
        assertEquals(RevalidationState.NOT_REQUESTED, operation.revalidation().state());
        assertEquals(RelationOperationStatus.Next.NONE, operation.next());

        assertDefinite(s3Refusal(() -> s3.operation(S3_JOB_1, REJECT_KEY)), 404, "operation_not_found");
        assertDefinite(s3Refusal(() -> s3.operation(S3_JOB_2, ALLOW_KEY)), 404, "operation_not_found");
        assertEquals(RevalidationState.VERIFIED, s3.operation(S3_JOB_1, ALLOW_KEY).revalidation().state(), "the first job is unaffected");
        UntrustedRelationPayload.Candidate closed = candidate(payload(s3, S3_JOB_2), held.relationCandidateId());
        assertEquals(Long.toString(Long.parseLong(second.sourceRevision()) + 1), closed.sourceRevision());
        assertDefinite(s3Refusal(() -> s3.review(S3_JOB_2, RelationReviewRequest.of("gate-allow-late", closed, RelationDecision.ALLOW))), 409,
                "review_target_not_hold");
    }

    // ---- authority is the server's, read at every response ----

    @Test
    @Order(7)
    void revokedSourceApprovalAndUpstreamWithholdContentAtOnceAndRestoringThemDeliversAgain() throws IOException {
        String s2Job = s2Submission.jobId();
        withFile("sources", "sourcesRevoked", () -> {
            ExtractionResult s2Result = s2.result(s2Job);
            assertEquals(DeliveryState.WITHHELD, s2Result.delivery().state());
            assertEquals("source_unauthorized", s2Result.delivery().reason().orElseThrow());
            assertTrue(s2Result.payload().isEmpty() && s2Result.readyPayload().isEmpty());
            assertFalse(s2Result.receipts().isEmpty(), "usage receipts stay available while content is withheld");
            assertEquals(State.READY, s2Result.status().state(), "delivery does not change the job state");

            RelationResult s3Result = s3.result(S3_JOB_1);
            assertEquals("source_unauthorized", s3Result.delivery().reason().orElseThrow());
            assertTrue(s3Result.payload().isEmpty() && s3Result.readyPayload().isEmpty());
            assertEquals(RevalidationState.VERIFIED, s3.operation(S3_JOB_1, ALLOW_KEY).revalidation().state(),
                    "an operation is read from the service ledger only");
        });
        assertEquals(DeliveryState.AVAILABLE, s2.result(s2Job).delivery().state());
        assertEquals(DeliveryState.AVAILABLE, s3.result(S3_JOB_1).delivery().state());

        withFile("approvals", "approvalsEmpty", () -> {
            ExtractionResult revoked = s2.result(s2Job);
            assertEquals("approval_revoked", revoked.delivery().reason().orElseThrow());
            assertTrue(revoked.payload().isEmpty());
            assertDefinite(s2Refusal(() -> s2.recover(s2Job)), 403, "request_not_approved");
        });
        assertEquals(DeliveryState.AVAILABLE, s2.result(s2Job).delivery().state());

        withFile("upstreams", "upstreamsEmpty", () -> {
            RelationResult unlisted = s3.result(S3_JOB_1);
            assertEquals("upstream_not_allowed", unlisted.delivery().reason().orElseThrow());
            assertTrue(unlisted.payload().isEmpty());
            assertDefinite(s3Refusal(() -> s3.review(S3_JOB_1, RelationReviewRequest.of("gate-unlisted-op", held, RelationDecision.ALLOW))),
                    403, "upstream_not_allowed");
        });
        assertEquals(DeliveryState.AVAILABLE, s3.result(S3_JOB_1).delivery().state());
    }

    private void withFile(String target, String variant, Runnable check) throws IOException {
        byte[] original = Files.readAllBytes(file(target));
        try {
            Files.copy(file(variant), file(target), StandardCopyOption.REPLACE_EXISTING);
            check.run();
        } finally {
            Files.write(file(target), original);
        }
    }

    // ---- stopped, ambiguous and cancelled jobs ----

    @Test
    @Order(8)
    void anInterruptedS2JobContinuesOnlyByExplicitRecoverAndNeverResendsAStoredCall() {
        JsonNode service = manifest.get("s2Crash");
        HttpExtractionClient client = extraction(service, "alpha");
        String jobId = s2Submission.jobId();
        assertEquals(Disposition.NEWLY_ACCEPTED, client.submit(s2Submission).disposition());
        ExtractionJobStatus interrupted = eventually(() -> client.status(jobId), s -> s.dispatch().state() == DispatchState.IDLE, "S2 interrupted");
        assertEquals(Next.RECOVER, interrupted.next());
        assertEquals(1, interrupted.usage().replayCalls(), "the stage was stored before the child died");
        pause(2_500);
        assertEquals(1, client.status(jobId).dispatch().dispatchCount(), "nothing is run again automatically");

        assertEquals(Disposition.RECOVERY_ENQUEUED, client.recover(jobId).disposition());
        ExtractionJobStatus done = s2Ready(client, jobId);
        assertEquals(world.get("s2ReplayCalls").longValue(), done.usage().replayCalls());
        assertEquals(1, client.result(jobId).receipts().stream().filter(r -> r.stage().equals("extract")).count(),
                "the stored receipt was reused, not called again");
    }

    @Test
    @Order(9)
    void anUnansweredS2CallIsNeverResentAndEndsAsAnOperatorDecision() {
        JsonNode service = manifest.get("s2Unknown");
        HttpExtractionClient client = extraction(service, "alpha");
        String jobId = s2Submission.jobId();
        client.submit(s2Submission);
        ExtractionJobStatus ambiguous = eventually(() -> client.status(jobId), s -> s.dispatch().state() == DispatchState.IDLE, "S2 ambiguous");
        assertEquals(PipelineJob.Outcome.TRANSPORT_UNKNOWN, ambiguous.dispatch().lastOutcome().orElseThrow());
        assertEquals(1, ambiguous.usage().startedWithoutReceipt());
        pause(2_500);
        assertEquals(1, client.status(jobId).dispatch().dispatchCount());

        client.recover(jobId);
        ExtractionJobStatus reconciling = eventually(() -> client.status(jobId),
                s -> s.state() == State.RECONCILING && s.dispatch().state() == DispatchState.IDLE, "S2 reconciling");
        assertEquals(Next.OPERATOR_RECONCILE, reconciling.next());
        assertEquals(0, reconciling.usage().replayCalls(), "an unanswered call is never resent");
        ExtractionServiceErrorException refused = s2Refusal(() -> client.recover(jobId));
        assertDefinite(refused, 409, "reconcile_required");
        assertEquals(State.RECONCILING, refused.status().orElseThrow().state());
        assertEquals(1, refused.status().orElseThrow().usage().startedWithoutReceipt());
    }

    @Test
    @Order(10)
    void aQueuedS2JobCancelsAndStaysCancelled() {
        HttpExtractionClient client = extraction(manifest.get("s2Hold"), "alpha");
        String jobId = s2Submission.jobId();
        client.submit(s2Submission);
        assertEquals(Disposition.RECOVERY_COALESCED, client.recover(jobId).disposition(), "a dispatch is already pending");

        ExtractionJobStatus cancelled = client.cancel(jobId);
        assertEquals(State.CANCELLED, cancelled.state());
        assertEquals(Next.NONE, cancelled.next());
        assertEquals(PipelineJob.Outcome.CANCELLED, cancelled.dispatch().lastOutcome().orElseThrow());
        assertEquals(0, cancelled.dispatch().dispatchCount());
        assertEquals("job_cancelled", cancelled.delivery().reason().orElseThrow());
        assertEquals(State.CANCELLED, client.cancel(jobId).state(), "cancel is idempotent");
        ExtractionResult result = client.result(jobId);
        assertTrue(result.payload().isEmpty() && result.readyPayload().isEmpty() && result.receipts().isEmpty());
        ExtractionServiceErrorException recover = s2Refusal(() -> client.recover(jobId));
        assertDefinite(recover, 409, "job_not_recoverable");
        assertEquals(State.CANCELLED, recover.status().orElseThrow().state());
    }

    @Test
    @Order(11)
    void aQueuedS3JobCancelsAndStaysCancelled() {
        HttpRelationClient client = relation(manifest.get("s3Hold"), "alpha");
        client.submit(s3Submission(S3_JOB_1));
        RelationAcknowledgement coalesced = client.recover(S3_JOB_1);
        assertEquals(Disposition.RECOVERY_COALESCED, coalesced.disposition(), "a dispatch is already pending");

        RelationJobStatus cancelled = client.cancel(S3_JOB_1);
        assertEquals(State.CANCELLED, cancelled.state());
        assertEquals(Next.NONE, cancelled.next());
        assertEquals("job_cancelled", cancelled.delivery().reason().orElseThrow());
        assertEquals(State.CANCELLED, client.cancel(S3_JOB_1).state(), "cancel is idempotent");
        RelationResult result = client.result(S3_JOB_1);
        assertTrue(result.payload().isEmpty() && result.receipts().isEmpty());
        RelationServiceErrorException recover = s3Refusal(() -> client.recover(S3_JOB_1));
        assertDefinite(recover, 409, "job_not_recoverable");
        assertEquals(State.CANCELLED, recover.status().orElseThrow().state());
        assertDefinite(s3Refusal(() -> client.review(S3_JOB_1, new RelationReviewRequest("gate-cancelled-op", held.relationCandidateId(),
                cancelled.sourceVersion(), "1", RelationDecision.ALLOW))), 409, "job_cancelled");
    }

    @Test
    @Order(12)
    void anInterruptedS3JobContinuesOnlyByExplicitRecoverAndReusesItsStoredStage() {
        HttpRelationClient client = relation(manifest.get("s3Crash"), "alpha");
        client.submit(s3Submission(S3_JOB_1));
        RelationJobStatus interrupted = eventually(() -> client.status(S3_JOB_1), s -> s.dispatch().state() == DispatchState.IDLE, "S3 interrupted");
        assertEquals(Next.RECOVER, interrupted.next());
        assertEquals(1, interrupted.usage().replayCalls());
        pause(2_500);
        assertEquals(1, client.status(S3_JOB_1).dispatch().dispatchCount(), "nothing is run again automatically");

        assertEquals(Disposition.RECOVERY_ENQUEUED, client.recover(S3_JOB_1).disposition());
        RelationJobStatus done = s3Ready(client, S3_JOB_1);
        assertEquals(world.get("relationReplayCalls").longValue(), done.usage().replayCalls());
        assertEquals(1, client.result(S3_JOB_1).receipts().stream().filter(r -> r.stage().equals("relation")).count());
    }

    // ---- transport ----

    @Test
    @Order(13)
    void anUnreachableServiceIsANotSentFailureForBothFamiliesAndNeverLeaksTheToken() throws IOException {
        int port;
        try (ServerSocket probe = new ServerSocket(0, 1, java.net.InetAddress.getLoopbackAddress())) {
            port = probe.getLocalPort();
        }
        String token = main.get("tokens").get("alpha").stringValue();
        HttpExtractionClient closedS2 = new HttpExtractionClient(settings("http://127.0.0.1:" + port, token));
        HttpRelationClient closedS3 = new HttpRelationClient(settings("http://127.0.0.1:" + port, token));
        closeables.add(closedS2);
        closeables.add(closedS3);
        AiTransportException s2Error = assertThrows(AiTransportException.class, () -> closedS2.submit(s2Submission));
        AiTransportException s3Error = assertThrows(AiTransportException.class, () -> closedS3.submit(s3Submission(S3_JOB_1)));
        for (AiTransportException error : List.of(s2Error, s3Error)) {
            assertEquals(Failure.CONNECT_FAILED, error.failure());
            assertFalse(error.requestMaybeProcessed());
            assertFalse(error.getMessage().contains(token));
        }
    }
}
