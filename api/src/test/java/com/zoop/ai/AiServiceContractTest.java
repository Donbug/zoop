package com.zoop.ai;

import java.io.IOException;
import java.net.ServerSocket;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Duration;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.List;
import java.util.Set;
import java.util.function.Predicate;
import java.util.function.Supplier;

import com.zoop.ai.AnalysisAcknowledgement.Disposition;
import com.zoop.ai.AnalysisJobStatus.Dispatch.DispatchState;
import com.zoop.ai.AnalysisJobStatus.Next;
import com.zoop.ai.AnalysisJobStatus.State;
import com.zoop.ai.AiTransportException.Failure;
import com.zoop.ai.http.HttpAiAnalysisClient;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.api.TestMethodOrder;
import org.slf4j.MDC;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

/**
 * Real Java -> ai/service (uvicorn) -> installed {@code zoop-ai} CLI, replay only. Not runnable on its own: {@code make
 * api-ai-smoke} starts the services and exports {@code ZOOP_AI_CONTRACT_MANIFEST}. Without it every test fails; none skips.
 */
@Tag("ai-contract")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class AiServiceContractTest {
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final Duration POLL_LIMIT = Duration.ofSeconds(90);

    private JsonNode manifest;
    private final List<HttpAiAnalysisClient> clients = new ArrayList<>();
    private List<AnalysisSubmission> jobs;
    private HttpAiAnalysisClient alpha;
    private String mainUrl;
    private JsonNode mainTokens;

    @BeforeAll
    void load() throws IOException {
        String path = System.getenv("ZOOP_AI_CONTRACT_MANIFEST");
        if (path == null || path.isBlank()) {
            fail("ZOOP_AI_CONTRACT_MANIFEST is not set. These tests need live ai/service processes: run `make api-ai-smoke`.");
        }
        manifest = JSON.readTree(Files.readString(Path.of(path)));
        JsonNode main = manifest.get("main");
        mainUrl = main.get("baseUrl").stringValue();
        mainTokens = main.get("tokens");
        jobs = new ArrayList<>();
        main.get("jobs").values().forEach(job -> jobs.add(submission(job)));
        alpha = client(mainUrl, mainTokens.get("alpha").stringValue());
    }

    @AfterAll
    void close() {
        MDC.clear();
        clients.forEach(HttpAiAnalysisClient::close);
    }

    private HttpAiAnalysisClient client(String baseUrl, String token) {
        HttpAiAnalysisClient created = new HttpAiAnalysisClient(
                AiClientSettings.of(baseUrl, token, Duration.ofSeconds(3), Duration.ofSeconds(60), 8 * 1024 * 1024));
        clients.add(created);
        return created;
    }

    private static AnalysisSubmission submission(JsonNode job) {
        return new AnalysisSubmission(job.get("jobId").stringValue(), AnalysisKind.fromWire(job.get("kind").stringValue()).orElseThrow(),
                ExecutionMode.fromWire(job.get("mode").stringValue()).orElseThrow(), JSON.writeValueAsString(job.get("input")),
                JSON.writeValueAsString(job.get("provenance")));
    }

    private static AnalysisJobStatus await(AiAnalysisClient client, String jobId, Predicate<AnalysisJobStatus> done) {
        long deadline = System.nanoTime() + POLL_LIMIT.toNanos();
        AnalysisJobStatus last;
        do {
            last = client.status(jobId);
            if (done.test(last)) {
                return last;
            }
            sleep(200);
        } while (System.nanoTime() < deadline);
        return fail("timed out waiting for " + jobId + "; last state=" + last.state() + " dispatch=" + last.dispatch().state()
                + " next=" + last.next());
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            fail("interrupted");
        }
    }

    private static AiServiceErrorException rejected(Supplier<?> call) {
        return assertThrows(AiServiceErrorException.class, call::get);
    }

    // ---- service 1: four kinds ----

    @Test
    @Order(1)
    void allFourKindsAreSubmittedPolledAndDeliveredByTheRealRuntime() {
        assertEquals(6, jobs.size());
        for (AnalysisSubmission job : jobs) {
            AnalysisAcknowledgement ack = alpha.submit(job);
            assertEquals(Disposition.NEWLY_ACCEPTED, ack.disposition(), job.jobId());
            assertEquals(job.jobId(), ack.status().jobId());
            assertEquals(job.kind(), ack.status().kind());
            assertEquals(ExecutionMode.REPLAY, ack.status().mode());
        }
        Set<AnalysisKind> kinds = EnumSet.noneOf(AnalysisKind.class);
        long replayCalls = 0;
        for (AnalysisSubmission job : jobs) {
            AnalysisJobStatus ready = await(alpha, job.jobId(), s -> s.state() == State.READY && s.dispatch().state() == DispatchState.IDLE);
            assertEquals(Next.FETCH_RESULT, ready.next());
            assertEquals(0, ready.usage().providerAttempts(), "replay must never reach a provider");
            assertEquals(0, ready.unreceiptedAttempts());
            kinds.add(ready.kind());
            replayCalls += ready.usage().replayCalls();

            AnalysisResult result = alpha.result(job.jobId());
            assertEquals(AnalysisResult.Delivery.State.AVAILABLE, result.delivery().state());
            UntrustedAnalysisPayload payload = result.readyPayload().orElseThrow();
            JsonNode body = JSON.readTree(payload.untrustedJson());
            assertEquals("zoop-ai-s1-1", body.get("schemaVersion").stringValue());
            assertEquals(job.jobId(), body.get("jobId").stringValue());
            assertEquals("ready", body.get("state").stringValue());
            assertEquals(job.kind().wire(), body.get("input").get("kind").stringValue());
            assertFalse(body.get("artifacts").isEmpty(), "a ready job has artifacts");
            assertFalse(payload.toString().contains(body.get("artifacts").toString()));
            assertFalse(result.receipts().isEmpty());
            result.receipts().forEach(receipt -> assertEquals(ExecutionMode.REPLAY, receipt.mode()));
        }
        assertEquals(EnumSet.allOf(AnalysisKind.class), kinds);
        assertEquals(10, replayCalls, "4 documents x (generation + verification), 1 outlook, 1 standalone verification");
    }

    @Test
    @Order(2)
    void duplicatesConflictsOwnersAndAuthAreDecodedFromTheRealService() {
        AnalysisSubmission first = jobs.get(0);
        AnalysisAcknowledgement replay = alpha.submit(first);
        assertEquals(Disposition.ALREADY_ACCEPTED, replay.disposition());
        assertEquals(State.READY, replay.status().state());

        AiServiceErrorException conflict = rejected(() -> alpha.submit(new AnalysisSubmission(first.jobId(),
                AnalysisKind.DOCUMENT_SENTIMENT, first.mode(), first.inputJson(), first.provenanceJson())));
        assertEquals(409, conflict.httpStatus());
        assertEquals("idempotency_conflict", conflict.code());
        assertFalse(conflict.retryable());
        assertFalse(conflict.requestMaybeProcessed(), "a definitive 4xx");

        HttpAiAnalysisClient beta = client(mainUrl, mainTokens.get("beta").stringValue());
        assertEquals("job_id_unavailable", rejected(() -> beta.submit(first)).code());
        assertEquals(404, rejected(() -> beta.status(first.jobId())).httpStatus());
        assertEquals("job_not_found", rejected(() -> beta.result(first.jobId())).code());
        assertEquals("job_not_found", rejected(() -> beta.cancel(first.jobId())).code());
        assertEquals("job_not_found", rejected(() -> beta.recover(first.jobId())).code());
        assertEquals("job_not_found", rejected(() -> alpha.status("no-such-job")).code());

        HttpAiAnalysisClient stranger = client(mainUrl, "x".repeat(43));
        AiServiceErrorException unauthenticated = rejected(() -> stranger.status(first.jobId()));
        assertEquals(401, unauthenticated.httpStatus());
        assertEquals("authentication_required", unauthenticated.code());

        HttpAiAnalysisClient reader = client(mainUrl, mainTokens.get("reader").stringValue());
        HttpAiAnalysisClient submitter = client(mainUrl, mainTokens.get("submitter").stringValue());
        assertEquals("scope_denied", rejected(() -> reader.submit(first)).code());
        assertEquals(403, rejected(() -> submitter.status(first.jobId())).httpStatus());
        assertEquals("job_not_found", rejected(() -> reader.status(first.jobId())).code(),
                "a principal with read scope still cannot see another principal's job");
    }

    @Test
    @Order(3)
    void serverSideValidationAndLiveRefusalAreDecodedAndNeverReachAModel() {
        AnalysisSubmission invalid = new AnalysisSubmission("java-invalid-input-1", AnalysisKind.DOCUMENT_SUMMARY, ExecutionMode.REPLAY,
                "{}", jobs.get(0).provenanceJson());
        AiServiceErrorException refused = rejected(() -> alpha.submit(invalid));
        assertEquals(422, refused.httpStatus());
        assertEquals("invalid_request", refused.code());
        assertFalse(refused.retryable());
        assertEquals("job_not_found", rejected(() -> alpha.status(invalid.jobId())).code(), "a refused job is not registered");

        AnalysisSubmission live = new AnalysisSubmission("java-live-refused-1", AnalysisKind.DOCUMENT_SUMMARY, ExecutionMode.LIVE,
                jobs.get(0).inputJson(), jobs.get(0).provenanceJson());
        AiServiceErrorException unavailable = rejected(() -> alpha.submit(live));
        assertEquals(409, unavailable.httpStatus());
        assertEquals("execution_unavailable", unavailable.code());
    }

    @Test
    @Order(4)
    void terminalJobsAnswerCancelAndRecoverWithTheirStatus() {
        String jobId = jobs.get(0).jobId();
        AiServiceErrorException cancel = rejected(() -> alpha.cancel(jobId));
        assertEquals("job_already_terminal", cancel.code());
        assertEquals(State.READY, cancel.status().orElseThrow().state());
        assertEquals(2, cancel.status().orElseThrow().usage().replayCalls());

        AiServiceErrorException recover = rejected(() -> alpha.recover(jobId));
        assertEquals("job_not_recoverable", recover.code());
        assertEquals(State.READY, recover.status().orElseThrow().state());
    }

    @Test
    @Order(5)
    void revokedSourceRightsWithholdTheResultImmediatelyAndRestoringThemDeliversAgain() throws IOException {
        JsonNode main = manifest.get("main");
        Path grants = Path.of(main.get("grantsPath").stringValue());
        Path revoked = Path.of(main.get("revokedGrantsPath").stringValue());
        byte[] original = Files.readAllBytes(grants);
        String jobId = jobs.get(0).jobId();
        try {
            Files.copy(revoked, grants, StandardCopyOption.REPLACE_EXISTING);
            AnalysisResult withheld = alpha.result(jobId);
            assertEquals(AnalysisResult.Delivery.State.WITHHELD, withheld.delivery().state());
            assertEquals("source_rights_unknown_or_denied", withheld.delivery().reason().orElseThrow());
            assertTrue(withheld.payload().isEmpty());
            assertTrue(withheld.readyPayload().isEmpty());
            assertFalse(withheld.receipts().isEmpty(), "usage receipts stay available while content is withheld");
            assertEquals(State.READY, withheld.status().state(), "job state is unaffected by delivery");
            assertEquals(State.READY, alpha.status(jobId).state());
        } finally {
            Files.write(grants, original);
        }
        AnalysisResult again = alpha.result(jobId);
        assertEquals(AnalysisResult.Delivery.State.AVAILABLE, again.delivery().state());
        assertTrue(again.readyPayload().isPresent());
    }

    // ---- service 2: blocked fixture, cancel and recover ----

    private HttpAiAnalysisClient recoveryClient() {
        JsonNode recovery = manifest.get("recovery");
        return client(recovery.get("baseUrl").stringValue(), recovery.get("tokens").get("alpha").stringValue());
    }

    @Test
    @Order(6)
    void aBlockedJobIsReportedHonestlyAndCancelKeepsTheReportedStatus() {
        HttpAiAnalysisClient service = recoveryClient();
        AnalysisSubmission recoverJob = submission(manifest.get("recovery").get("recoverJob"));
        AnalysisSubmission cancelJob = submission(manifest.get("recovery").get("cancelJob"));
        assertEquals(Disposition.NEWLY_ACCEPTED, service.submit(recoverJob).disposition());
        assertEquals(Disposition.NEWLY_ACCEPTED, service.submit(cancelJob).disposition());

        for (AnalysisSubmission job : List.of(recoverJob, cancelJob)) {
            AnalysisJobStatus blocked = await(service, job.jobId(), s -> s.dispatch().state() == DispatchState.IDLE);
            assertEquals(State.QUEUED, blocked.state());
            assertEquals(Next.RECOVER, blocked.next(), "the service tells the caller to recover, not to wait");
            assertEquals("replay_fixture_invalid", blocked.dispatch().lastRuntimeCode().orElseThrow());
            assertEquals(0, blocked.usage().providerAttempts());
        }

        AnalysisJobStatus cancelled = service.cancel(cancelJob.jobId());
        assertEquals(State.CANCELLED, cancelled.state());
        assertEquals(Next.NONE, cancelled.next());
        AnalysisJobStatus observed = service.status(cancelJob.jobId());
        assertEquals(cancelled.usage(), observed.usage(), "cancel reports the same usage the runtime later reports");
        assertEquals(cancelled.unreceiptedAttempts(), observed.unreceiptedAttempts());
        assertEquals(State.CANCELLED, service.cancel(cancelJob.jobId()).state(), "cancel is idempotent");

        AnalysisResult delivered = service.result(cancelJob.jobId());
        assertTrue(delivered.readyPayload().isEmpty(), "a cancelled job is never a ready payload");
        assertEquals("job_not_recoverable", rejected(() -> service.recover(cancelJob.jobId())).code());
    }

    @Test
    @Order(7)
    void recoverResumesTheBlockedJobOnlyAfterTheOperatorFixesTheFixture() throws IOException {
        JsonNode recovery = manifest.get("recovery");
        HttpAiAnalysisClient service = recoveryClient();
        AnalysisSubmission recoverJob = submission(recovery.get("recoverJob"));
        Files.copy(Path.of(recovery.get("goodReplayPath").stringValue()), Path.of(recovery.get("replayPath").stringValue()),
                StandardCopyOption.REPLACE_EXISTING);

        AnalysisAcknowledgement ack = service.recover(recoverJob.jobId());
        assertTrue(ack.disposition() == Disposition.RECOVERY_ENQUEUED || ack.disposition() == Disposition.RECOVERY_COALESCED);
        AnalysisJobStatus ready = await(service, recoverJob.jobId(),
                s -> s.state() == State.READY && s.dispatch().state() == DispatchState.IDLE);
        assertEquals(0, ready.usage().providerAttempts());
        assertEquals(2, ready.usage().replayCalls());
        assertEquals(AnalysisResult.Delivery.State.AVAILABLE, service.result(recoverJob.jobId()).delivery().state());
        assertEquals("job_not_recoverable", rejected(() -> service.recover(recoverJob.jobId())).code());
    }

    // ---- transport ----

    @Test
    @Order(8)
    void requestIdIsForwardedToTheServiceAndUnsafeOnesAreReplaced() {
        MDC.put("requestId", "java-contract-req-1");
        AiServiceErrorException forwarded = rejected(() -> alpha.status("no-such-job"));
        assertEquals("java-contract-req-1", forwarded.requestId());

        MDC.put("requestId", "not a valid id " + "x".repeat(200));
        AiServiceErrorException replaced = rejected(() -> alpha.status("no-such-job"));
        assertNotNull(replaced.requestId());
        assertTrue(replaced.requestId().matches("[0-9a-f-]{36}"), replaced.requestId());
        MDC.clear();
    }

    @Test
    @Order(9)
    void anUnreachableServiceIsAnExplicitNotSentTransportFailure() throws IOException {
        int port;
        try (ServerSocket probe = new ServerSocket(0, 1, java.net.InetAddress.getLoopbackAddress())) {
            port = probe.getLocalPort();
        }
        HttpAiAnalysisClient closed = client("http://127.0.0.1:" + port, mainTokens.get("alpha").stringValue());
        AiTransportException error = assertThrows(AiTransportException.class, () -> closed.submit(jobs.get(0)));
        assertEquals(Failure.CONNECT_FAILED, error.failure());
        assertFalse(error.requestMaybeProcessed());
        assertFalse(error.getMessage().contains(mainTokens.get("alpha").stringValue()));
    }
}
