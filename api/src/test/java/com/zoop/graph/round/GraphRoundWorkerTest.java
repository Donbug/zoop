package com.zoop.graph.round;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.OptionalInt;
import java.util.concurrent.atomic.AtomicReference;

import com.zoop.ai.AiOperation;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.RoundServiceErrorException;
import com.zoop.ai.round.RoundHandoffClient;
import com.zoop.ai.round.RoundHandoffClient.RoundHandoff;
import com.zoop.ai.round.RoundRunClient;
import com.zoop.ai.round.RoundRunClient.RoundRun;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.round.GraphRoundEvent.Outcome;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

/**
 * The stage machine over fakes: the AI round routes, the analyze_plan queue, the bindings and the import bridge are doubles,
 * the rows are the in-memory repository with the real fencing rules. Time is a clock the test moves.
 */
class GraphRoundWorkerTest {
    private static final ZoneId KST = ZoneId.of("Asia/Seoul");
    private static final String R0905 = "round-20261030T0905";
    private static final String R0935 = "round-20261030T0935";
    private static final String R1805 = "round-20261030T1805";
    private static final Instant S0905 = Instant.parse("2026-10-30T00:05:00Z");
    private static final Instant S0935 = Instant.parse("2026-10-30T00:35:00Z");
    private static final Instant S1805 = Instant.parse("2026-10-30T09:05:00Z");
    private static final String INGESTION = "slot-" + "1".repeat(64);
    private static final String PLAN = "s2plan-" + "2".repeat(64);
    private static final String DIGEST = "3".repeat(64);
    private static final String HANDOFF = "hr-" + "4".repeat(64);
    private static final byte[] BINDINGS = "{\"schemaVersion\":\"zoop-app-document-bindings-1\",\"bindings\":[]}".getBytes(StandardCharsets.UTF_8);

    private final InMemoryGraphRoundRepository rounds = new InMemoryGraphRoundRepository();
    private final FakeRuns runs = new FakeRuns();
    private final FakeHandoffs handoffs = new FakeHandoffs();
    private final FakeQueue queue = new FakeQueue();
    private final GraphRoundImportBridge bridge = mock(GraphRoundImportBridge.class);
    private final AtomicReference<Instant> now = new AtomicReference<>(Instant.parse("2026-10-30T00:05:10Z"));
    private final Clock clock = new Clock() {
        @Override
        public ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return now.get();
        }
    };
    private GraphRoundWorker worker;
    private GraphRoundProperties properties;

    @BeforeEach
    void setUp() {
        properties = properties(20, Duration.ofHours(2));
        worker = new GraphRoundWorker(rounds, new GraphRoundClock(properties), runs, handoffs, queue, () -> BINDINGS, bridge,
                properties, clock, "worker-a");
        when(bridge.importRound(any())).thenAnswer(invocation -> {
            GraphRound claimed = invocation.getArgument(0);
            return rounds.advance(claimed, GraphRoundPatch.advanceTo(GraphRoundStage.IMPORTED).graphVersion("gv-" + "5".repeat(64)),
                    Outcome.ADVANCED, "staged", null, null, now.get()).orElseThrow();
        });
    }

    private static GraphRoundProperties properties(int maxAttempts, Duration analysisWait) {
        return properties(maxAttempts, analysisWait, 3);
    }

    private static GraphRoundProperties properties(int maxAttempts, Duration analysisWait, int maxOpenRounds) {
        return new GraphRoundProperties(true, "scheduler", Duration.ofMinutes(1), Duration.ofMinutes(5), maxAttempts, "cli", "", "", "",
                Duration.ofSeconds(15), Duration.ofMinutes(2), "Asia/Seoul", "09:05", Duration.ofMinutes(30), 18, List.of("18:05"),
                Duration.ofMinutes(30), maxOpenRounds, analysisWait);
    }

    private void tick(Instant at) {
        now.set(at);
        worker.runOnce();
    }

    private GraphRound round(String id) {
        return rounds.find(id).orElseThrow();
    }

    private List<String> codes(String id) {
        return rounds.events(id).stream().map(e -> e.outcome().wire() + (e.code().map(c -> ":" + c).orElse(""))).toList();
    }

    @Test
    void aRegularSlotRunsThroughEveryStageAndEndsImported() {
        runs.answer(R0905, running());
        queue.onQueue = () -> new RoundAnalysisQueue.Queued("job-1", false);
        queue.states.put("job-1", new RoundAnalysisQueue.JobStatus(RoundAnalysisQueue.JobState.RUNNING, Optional.empty()));
        handoffs.answer(R0905, handoffRunning());

        tick(Instant.parse("2026-10-30T00:05:10Z"));            // slot opened, R1 accepted, R2 still running → waits
        GraphRound opened = round(R0905);
        assertEquals(GraphRoundStage.RUN_REQUESTED, opened.stage());
        assertEquals(GraphRoundWorker.SYSTEM, opened.startedBy());
        assertEquals("worker-a", opened.lease().orElseThrow().owner(), "a waiting stage keeps the lease");
        assertEquals(1, opened.attempts(), "R1 moved the stage and the first R2 look is one attempt in the same pass");

        runs.answer(R0905, ready());
        tick(Instant.parse("2026-10-30T00:06:30Z"));            // R2 ready → R3 queued → R4 running (waits), one pass
        GraphRound queued = round(R0905);
        assertEquals(GraphRoundStage.ANALYSIS_QUEUED, queued.stage());
        assertEquals(Optional.of(PLAN), queued.planId());
        assertEquals(Optional.of(INGESTION), queued.ingestionRoundId());
        assertEquals(Optional.of("job-1"), queued.analysisJobId());
        assertEquals(1, queued.attempts(), "the first R4 look is one attempt");
        assertEquals(Optional.of(Instant.parse("2026-10-30T00:07:30Z")), queued.nextAttemptAt());

        tick(Instant.parse("2026-10-30T00:07:00Z"));            // not due yet
        assertEquals(1, round(R0905).attempts());

        queue.states.put("job-1", new RoundAnalysisQueue.JobStatus(RoundAnalysisQueue.JobState.SUCCEEDED, Optional.empty()));
        tick(Instant.parse("2026-10-30T00:40:00Z"));            // R4 done → R5 accepted, R6 still running; the 09:35 slot opens too
        assertEquals(GraphRoundStage.FREEZE_REQUESTED, round(R0905).stage());
        assertEquals(1, handoffs.requests.size());
        RoundHandoffClient.Request freeze = handoffs.requests.getFirst();
        assertEquals(Optional.of(PLAN), freeze.planId());
        assertEquals(Optional.of(INGESTION), freeze.ingestionRoundId());
        assertEquals(new String(BINDINGS, StandardCharsets.UTF_8), new String(freeze.bindings(), StandardCharsets.UTF_8));
        assertTrue(rounds.find(R0935).isPresent(), "the next slot was opened by the same pass");

        handoffs.answer(R0905, handoffReady());
        tick(Instant.parse("2026-10-30T00:41:30Z"));            // R6 ready → R7 import
        GraphRound imported = round(R0905);
        assertEquals(GraphRoundStage.IMPORTED, imported.stage());
        assertEquals(Optional.of(HANDOFF), imported.handoffId());
        assertEquals(Optional.of(DIGEST), imported.manifestDigest());
        verify(bridge).importRound(any());
        assertEquals(List.of("advanced", "waiting:run_running", "advanced:plan_ready", "advanced:analysis_queued",
                "waiting:analysis_running", "advanced:analysis_done", "advanced", "waiting:freeze_running", "advanced:handoff_ready",
                "advanced:staged"), codes(R0905));
        GraphRoundEvent ready = rounds.events(R0905).get(8);
        assertEquals(2, ready.detail().orElseThrow().get("selection").get("selected").intValue());
        assertEquals(1, ready.detail().orElseThrow().get("selection").get("out_of_window").intValue());
    }

    @Test
    void aSlotWithoutNewMaterialAndTheFreezeOnlySlotAskForACarryOnlyFreeze() {
        properties = properties(20, Duration.ofHours(2), 100);
        worker = new GraphRoundWorker(rounds, new GraphRoundClock(properties), runs, handoffs, queue, () -> BINDINGS, bridge,
                properties, clock, "worker-a");
        runs.answer(R0905, new RoundRun(R0905, RoundRun.State.NO_NEW_MATERIAL, Optional.of(INGESTION), Optional.empty(),
                Optional.empty(), Optional.of("outside_operating_window")));
        handoffs.answer(R0905, handoffReady());
        tick(Instant.parse("2026-10-30T00:05:10Z"));
        assertEquals(GraphRoundStage.IMPORTED, round(R0905).stage());
        assertEquals(List.of("advanced:no_new_material", "advanced:handoff_ready", "advanced:staged"), codes(R0905));
        assertTrue(handoffs.requests.getFirst().planId().isEmpty(), "no plan: a carry-only freeze");
        assertEquals(Optional.of(INGESTION), handoffs.requests.getFirst().ingestionRoundId());

        // 18:05 KST: the regular slots of the day opened in between have no answers and stay scheduled (logged, nothing written).
        handoffs.answer(R1805, new RoundHandoff(R1805, RoundHandoff.State.NO_PUBLIC_MATERIAL, Optional.empty(), Optional.empty(),
                Optional.empty(), Optional.empty(), Optional.of("window_empty")));
        tick(Instant.parse("2026-10-30T09:05:05Z"));
        assertEquals(GraphRoundStage.SCHEDULED, round(R0935).stage());
        assertTrue(rounds.events(R0935).isEmpty(), "an interrupted step writes nothing");
        GraphRound freezeOnly = round(R1805);
        assertEquals(GraphRoundStage.SKIPPED, freezeOnly.stage());
        assertEquals(List.of("advanced:freeze_only", "skipped:no_public_material"), codes(R1805));
        assertTrue(handoffs.requests.get(1).planId().isEmpty() && handoffs.requests.get(1).ingestionRoundId().isEmpty());
        assertTrue(runs.requested.stream().noneMatch(R1805::equals), "a freeze-only slot never asks for a run");
        verify(bridge, never()).importRound(argThatIs(R1805));
    }

    @Test
    void aBusyOrUnavailableAiSideMakesTheRoundWaitAndARefusalEndsItWithTheCode() {
        runs.answer(R0905, new RoundServiceErrorException(AiOperation.ROUND_RUN, "req-1", 409, "round_busy", true, Optional.empty(),
                Optional.empty(), Optional.of(Duration.ofSeconds(7))));
        tick(Instant.parse("2026-10-30T00:05:10Z"));
        GraphRound busy = round(R0905);
        assertEquals(GraphRoundStage.SCHEDULED, busy.stage());
        assertEquals(Optional.of(Instant.parse("2026-10-30T00:05:17Z")), busy.nextAttemptAt(), "the service's Retry-After");
        assertEquals(List.of("waiting:ai:round_busy"), codes(R0905));

        runs.answer(R0905, new AiTransportException(AiOperation.ROUND_RUN, "req-2", AiTransportException.Failure.TIMEOUT,
                OptionalInt.empty(), null));
        tick(Instant.parse("2026-10-30T00:05:20Z"));
        assertEquals(Optional.of(Instant.parse("2026-10-30T00:06:20Z")), round(R0905).nextAttemptAt(), "wait-retry-after");
        assertEquals(2, round(R0905).attempts());

        runs.answer(R0905, new RoundServiceErrorException(AiOperation.ROUND_RUN, "req-2b", 429, "rate_limited", true,
                Optional.empty(), Optional.empty(), Optional.of(Duration.ofSeconds(30))));
        tick(Instant.parse("2026-10-30T00:06:30Z"));
        assertEquals(GraphRoundStage.SCHEDULED, round(R0905).stage(), "a rate limit is a wait, not a refusal");
        assertEquals(Optional.of(Instant.parse("2026-10-30T00:07:00Z")), round(R0905).nextAttemptAt());

        runs.answer(R0905, new RoundServiceErrorException(AiOperation.ROUND_RUN, "req-3", 403, "scope_denied", false,
                Optional.empty(), Optional.empty(), Optional.empty()));
        tick(Instant.parse("2026-10-30T00:07:00Z"));
        GraphRound failed = round(R0905);
        assertEquals(GraphRoundStage.FAILED, failed.stage());
        assertEquals(Optional.of("run_refused:scope_denied"), failed.failureCode());
        assertTrue(failed.lease().isEmpty(), "a terminal stage drops the lease");
        GraphRoundEvent last = rounds.events(R0905).getLast();
        assertEquals("scheduled", last.detail().orElseThrow().get("failedAt").stringValue());
        assertEquals("req-3", last.detail().orElseThrow().get("requestId").stringValue());
    }

    @Test
    void waitingPastTheAttemptBoundFailsWithTheStagesTimeoutAndTheAnalysisWaitHasItsOwnBound() {
        properties = properties(3, Duration.ofMinutes(2));
        worker = new GraphRoundWorker(rounds, new GraphRoundClock(properties), runs, handoffs, queue, () -> BINDINGS, bridge,
                properties, clock, "worker-a");
        runs.answerAlways(R0905, running());
        tick(Instant.parse("2026-10-30T00:05:10Z"));                   // R1 → run_requested (attempt 0 at the new stage)
        tick(Instant.parse("2026-10-30T00:06:00Z"));                   // R2 running → attempt 1
        tick(Instant.parse("2026-10-30T00:07:30Z"));                   // attempt 2
        tick(Instant.parse("2026-10-30T00:09:00Z"));                   // attempt 3 = bound → failed
        assertEquals(Optional.of("run_timeout"), round(R0905).failureCode());
        assertEquals("run_requested", rounds.events(R0905).getLast().detail().orElseThrow().get("failedAt").stringValue());

        // The analysis wait: 2 minutes / 1 minute = 2 attempts before analysis_timeout.
        rounds.seed(R0935, S0935, GraphRoundStage.PLAN_READY, null, null, null, 0);
        queue.onQueue = () -> new RoundAnalysisQueue.Queued("job-2", true);
        queue.states.put("job-2", new RoundAnalysisQueue.JobStatus(RoundAnalysisQueue.JobState.RUNNING, Optional.empty()));
        GraphRound seeded = rounds.advance(rounds.claim(R0935, "worker-a", Duration.ofMinutes(2), now.get()).orElseThrow(),
                GraphRoundPatch.advanceTo(GraphRoundStage.PLAN_READY).plan(PLAN, DIGEST), Outcome.ADVANCED, null, null, null, now.get())
                .orElseThrow();
        assertEquals(GraphRoundStage.PLAN_READY, seeded.stage());
        tick(Instant.parse("2026-10-30T00:36:00Z"));                   // queued (reused) → running: attempt 1
        assertEquals("advanced:analysis_job_reused", codes(R0935).get(1));
        tick(Instant.parse("2026-10-30T00:38:00Z"));                   // attempt 2 = bound → analysis_timeout
        assertEquals(Optional.of("analysis_timeout"), round(R0935).failureCode());
        assertEquals("analysis_queued", rounds.events(R0935).getLast().detail().orElseThrow().get("failedAt").stringValue(),
                "the job is still running: a retry keeps reading it");

        // R3: the queue stays unavailable past the stage bound (3): a different code, resuming at plan_ready (no job yet).
        String r1005 = "round-20261030T1005";
        rounds.seed(r1005, Instant.parse("2026-10-30T01:05:00Z"), GraphRoundStage.PLAN_READY, null, null, null, 0);
        rounds.advance(rounds.claim(r1005, "worker-a", Duration.ofMinutes(2), now.get()).orElseThrow(),
                GraphRoundPatch.advanceTo(GraphRoundStage.PLAN_READY).plan(PLAN, DIGEST), Outcome.ADVANCED, null, null, null, now.get());
        queue.onQueue = () -> {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, false);
        };
        tick(Instant.parse("2026-10-30T01:05:10Z"));
        tick(Instant.parse("2026-10-30T01:06:30Z"));
        tick(Instant.parse("2026-10-30T01:08:00Z"));
        assertEquals(Optional.of("analysis_queue_timeout"), round(r1005).failureCode());
        assertEquals("plan_ready", rounds.events(r1005).getLast().detail().orElseThrow().get("failedAt").stringValue());
        assertTrue(round(r1005).analysisJobId().isEmpty());
    }

    @Test
    void aFailedAnalysisOrARefusedPlanEndsTheRoundAndAnUnconfiguredQueueMakesItWait() {
        rounds.seed(R0905, S0905, GraphRoundStage.PLAN_READY, null, null, null, 0);
        rounds.advance(rounds.claim(R0905, "worker-a", Duration.ofMinutes(2), now.get()).orElseThrow(),
                GraphRoundPatch.advanceTo(GraphRoundStage.PLAN_READY).plan(PLAN, DIGEST), Outcome.ADVANCED, null, null, null, now.get());
        queue.onQueue = () -> {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, false);
        };
        tick(Instant.parse("2026-10-30T00:05:10Z"));
        assertEquals(GraphRoundStage.PLAN_READY, round(R0905).stage());
        assertEquals("waiting:analysis_queue_unavailable", codes(R0905).getLast());

        queue.onQueue = () -> {
            throw new CustomException(ErrorCode.JOB_NOT_RETRYABLE);
        };
        tick(Instant.parse("2026-10-30T00:07:00Z"));
        assertEquals(Optional.of("plan_rejected:job_not_retryable"), round(R0905).failureCode());

        rounds.seed(R0935, S0935, GraphRoundStage.PLAN_READY, null, null, null, 0);
        rounds.advance(rounds.claim(R0935, "worker-a", Duration.ofMinutes(2), now.get()).orElseThrow(),
                GraphRoundPatch.advanceTo(GraphRoundStage.PLAN_READY).plan(PLAN, DIGEST), Outcome.ADVANCED, null, null, null, now.get());
        queue.onQueue = () -> new RoundAnalysisQueue.Queued("job-3", false);
        queue.states.put("job-3", new RoundAnalysisQueue.JobStatus(RoundAnalysisQueue.JobState.FAILED, Optional.of("worker_deadline")));
        tick(Instant.parse("2026-10-30T00:36:00Z"));
        assertEquals(Optional.of("analysis_failed:worker_deadline"), round(R0935).failureCode());
        assertEquals("plan_ready", rounds.events(R0935).getLast().detail().orElseThrow().get("failedAt").stringValue(),
                "a retry queues the job's retry from plan_ready instead of reading the failed job again");
        assertEquals(Optional.of("job-3"), round(R0935).analysisJobId(), "the failed job stays on the row for the admin view");
    }

    @Test
    void aStepWhoseLeaseExpiredAndWasTakenOverAndEvenFinishedByAnotherWorkerWritesNothing() {
        // worker-a reads a ready run while its lease runs out; worker-c takes the row, fails it and releases the lease.
        rounds.seed(R0935, S0935, GraphRoundStage.RUN_REQUESTED, null, null, null, 0);
        runs.answer(R0935, ready());
        GraphRound mine = rounds.claim(R0935, "worker-a", Duration.ofMinutes(2), now.get()).orElseThrow();
        Instant later = now.get().plus(Duration.ofMinutes(3));
        GraphRound theirs = rounds.claim(R0935, "worker-c", Duration.ofMinutes(10), later).orElseThrow();
        rounds.advance(theirs, GraphRoundPatch.fail("run_failed:x"), Outcome.FAILED, "run_failed:x", null, null, later);
        rounds.release(R0935, "worker-c");
        now.set(later.plusSeconds(1));

        worker.progress(mine);

        GraphRound row = round(R0935);
        assertEquals(GraphRoundStage.FAILED, row.stage(), "worker-a's late ready answer did not revive the round");
        assertEquals(Optional.of("run_failed:x"), row.failureCode());
        assertTrue(row.planId().isEmpty());
        assertTrue(row.lease().isEmpty(), "the fresh claim worker-a's renewal made was released again");
        assertEquals(List.of("failed:run_failed:x"), codes(R0935), "no event from worker-a");

        // The lease merely expired while the call was in flight and nobody took the row: the token is still this step's, so the
        // extension holds and the result is kept (a long AI call does not lose its answer).
        rounds.seed(R0905, S0905, GraphRoundStage.RUN_REQUESTED, null, null, null, 0);
        runs.answerAlways(R0905, ready());
        queue.onQueue = () -> {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, false);
        };
        GraphRound expired = rounds.claim(R0905, "worker-a", Duration.ofMinutes(2), now.get()).orElseThrow();
        now.set(now.get().plus(Duration.ofMinutes(5)));
        worker.progress(expired);
        GraphRound kept = round(R0905);
        assertEquals(Optional.of(PLAN), kept.planId(), "the late ready answer was written under the kept token");
        assertEquals(GraphRoundStage.PLAN_READY, kept.stage());
        assertEquals(expired.lease().orElseThrow().token(), kept.lease().orElseThrow().token());
        assertEquals(now.get().plus(Duration.ofMinutes(2)), kept.lease().orElseThrow().until(), "extended, not re-issued");
    }

    @Test
    void theFirstPassOpensOnlyTheSlotsWithinLookbackAndARowAnotherInstanceHoldsIsLeftAlone() {
        runs.answerAlways(R0935, running());
        tick(Instant.parse("2026-10-30T00:40:00Z"));                   // lookback 30m: 09:35 yes, 09:05 no
        assertFalse(rounds.find(R0905).isPresent());
        assertEquals(GraphRoundStage.RUN_REQUESTED, round(R0935).stage());

        // Another instance holds the 10:05 row: this worker neither claims nor writes it.
        rounds.create("round-20261030T1005", Instant.parse("2026-10-30T01:05:00Z"), GraphRoundWorker.SYSTEM, now.get());
        rounds.claim("round-20261030T1005", "worker-b", Duration.ofMinutes(10), Instant.parse("2026-10-30T01:05:00Z"));
        tick(Instant.parse("2026-10-30T01:05:30Z"));
        assertEquals(GraphRoundStage.SCHEDULED, round("round-20261030T1005").stage());
        assertTrue(rounds.events("round-20261030T1005").isEmpty());
        assertEquals("worker-b", round("round-20261030T1005").lease().orElseThrow().owner());

        // The lease is taken over while this worker's call is in flight: the late outcome is not written under the new token.
        runs.answer(R0935, new RoundRun(R0935, RoundRun.State.READY, Optional.of(INGESTION), Optional.of(PLAN), Optional.of(DIGEST),
                Optional.empty()));
        GraphRound mine = rounds.claim(R0935, "worker-a", Duration.ofMinutes(2), now.get()).orElseThrow();
        rounds.claim(R0935, "worker-c", Duration.ofMinutes(10), now.get().plus(Duration.ofMinutes(3)));
        now.set(now.get().plus(Duration.ofMinutes(3)));
        worker.progress(mine);
        GraphRound stolen = round(R0935);
        assertEquals("worker-c", stolen.lease().orElseThrow().owner());
        assertEquals(GraphRoundStage.RUN_REQUESTED, stolen.stage(), "the stage worker-c found is the stage it keeps");
        assertTrue(stolen.planId().isEmpty(), "worker-a's ready answer was not recorded");
    }

    // ------------------------------------------------------------------------------------------------ doubles

    private static RoundRun running() {
        return new RoundRun(R0905, RoundRun.State.RUNNING, Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty());
    }

    private static RoundRun ready() {
        return new RoundRun(R0905, RoundRun.State.READY, Optional.of(INGESTION), Optional.of(PLAN), Optional.of(DIGEST), Optional.empty());
    }

    private static RoundHandoff handoffRunning() {
        return new RoundHandoff(R0905, RoundHandoff.State.RUNNING, Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty(),
                Optional.empty());
    }

    private static RoundHandoff handoffReady() {
        var selection = JsonMapper.builder().build().readTree(
                "{\"schemaVersion\":\"zoop-ai-handoff-selection-1\",\"jobs\":[{\"status\":\"selected\"},{\"status\":\"selected\"},{\"status\":\"out_of_window\"}]}");
        return new RoundHandoff(R0905, RoundHandoff.State.READY, Optional.of(HANDOFF), Optional.of(DIGEST), Optional.of(DIGEST),
                Optional.of(selection), Optional.empty());
    }

    private static GraphRound argThatIs(String roundId) {
        return org.mockito.ArgumentMatchers.argThat(round -> round != null && roundId.equals(round.roundId()));
    }

    /** Answers per round id, in order; the last answer repeats. An answer may be an exception to throw. */
    static final class FakeRuns implements RoundRunClient {
        final List<String> requested = new ArrayList<>();
        private final Map<String, Deque<Object>> answers = new HashMap<>();
        private final Map<String, Object> always = new HashMap<>();

        /** Replaces the answers for the round: given in order, the last one repeats. */
        void answer(String roundId, Object... replies) {
            answers.put(roundId, new ArrayDeque<>(List.of(replies)));
            always.remove(roundId);
        }

        void answerAlways(String roundId, Object reply) {
            always.put(roundId, reply);
        }

        @Override
        public RoundRun request(String roundId) {
            requested.add(roundId);
            return next(roundId);
        }

        @Override
        public RoundRun runStatus(String roundId) {
            return next(roundId);
        }

        private RoundRun next(String roundId) {
            Deque<Object> queue = answers.get(roundId);
            Object reply = queue == null || queue.isEmpty() ? always.get(roundId) : queue.size() == 1 ? queue.peek() : queue.poll();
            if (reply == null) throw new IllegalStateException("no answer for " + roundId);
            if (reply instanceof RuntimeException error) throw error;
            RoundRun run = (RoundRun) reply;
            return new RoundRun(roundId, run.state(), run.ingestionRoundId(), run.planId(), run.planDigest(), run.code());
        }
    }

    static final class FakeHandoffs implements RoundHandoffClient {
        final List<Request> requests = new ArrayList<>();
        private final Map<String, Deque<Object>> answers = new HashMap<>();

        /** Replaces the answers for the round: given in order, the last one repeats. */
        void answer(String roundId, Object... replies) {
            answers.put(roundId, new ArrayDeque<>(List.of(replies)));
        }

        @Override
        public RoundHandoff request(Request request) {
            requests.add(request);
            return next(request.roundId());
        }

        @Override
        public RoundHandoff handoffStatus(String roundId) {
            return next(roundId);
        }

        private RoundHandoff next(String roundId) {
            Deque<Object> queue = answers.get(roundId);
            Object reply = queue == null || queue.isEmpty() ? null : queue.size() == 1 ? queue.peek() : queue.poll();
            if (reply == null) throw new IllegalStateException("no answer for " + roundId);
            if (reply instanceof RuntimeException error) throw error;
            RoundHandoff handoff = (RoundHandoff) reply;
            return new RoundHandoff(roundId, handoff.state(), handoff.handoffId(), handoff.manifestDigest(), handoff.bundleDigest(),
                    handoff.selection(), handoff.code());
        }
    }

    static final class FakeQueue implements RoundAnalysisQueue {
        java.util.function.Supplier<Queued> onQueue = () -> new Queued("job-x", false);
        final Map<String, JobStatus> states = new HashMap<>();

        @Override
        public Queued queue(String planId, String planDigest, String roundId, String requestId) {
            return onQueue.get();
        }

        @Override
        public JobStatus status(String jobId) {
            return states.getOrDefault(jobId, new JobStatus(JobState.MISSING, Optional.empty()));
        }
    }
}
