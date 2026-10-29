package com.zoop.chat.tool;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.executor.ChatRunControl;
import com.zoop.chat.executor.ChatRunSuperseded;
import com.zoop.chat.executor.ChatToolCallReservation;
import com.zoop.chat.repository.ChatToolCallEnd;
import com.zoop.chat.service.FrozenSelection;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

import static org.junit.jupiter.api.Assertions.*;

/**
 * D-AI-02 tool stage: only bound capabilities run, every call is recorded through the fenced control, failures are never
 * empty results and the concurrency and time limits hold. Tools here are scripted; the real adapters are in
 * {@link GraphTargetToolTest}.
 */
class ChatToolRunnerTest {
    private static final Instant AS_OF = Instant.parse("2026-10-05T00:00:00Z");

    private final List<ChatToolRunner> runners = new ArrayList<>();

    @AfterEach
    void tearDown() {
        runners.forEach(ChatToolRunner::close);
    }

    @Test
    void anUnboundCapabilityRefusesTheWholeStageBeforeAnythingIsReserved() {
        var control = new RecordingControl(Duration.ofSeconds(60));
        var runner = runner(Map.of(ChatCapability.COMPANY_READ, (scope, request) -> output("v1", List.of())));
        for (String capability : List.of("issue.read", "graph.delete", "company.read ")) {
            assertThrows(IllegalArgumentException.class, () -> runner.runStage(run("v1", null), control, 1,
                    List.of(request("company.read"), request(capability))));
        }
        assertTrue(control.events.isEmpty());
    }

    @Test
    void callsAreReservedWithTheFrozenScopeAndRecordedAsTheyEnd() {
        var control = new RecordingControl(Duration.ofSeconds(60));
        List<ChatToolScope> scopes = Collections.synchronizedList(new ArrayList<>());
        var runner = runner(Map.of(ChatCapability.COMPANY_READ, (scope, request) -> {
            scopes.add(scope);
            return output(scope.graphVersionId(), List.of("ev-1", "ev-2"));
        }, ChatCapability.ISSUE_READ, (scope, request) -> output(scope.graphVersionId(), List.of())));

        var results = runner.runStage(run("fixture-2026-10-01", AS_OF), control, 1,
                List.of(new ChatToolRequest("company.read", List.of("KRX:000660"), 20), request("issue.read")));

        assertEquals(List.of("tc-0", "tc-1"), results.stream().map(ChatToolResult::toolCallId).toList());
        assertTrue(results.stream().allMatch(ChatToolResult::succeeded));
        assertEquals(List.of("ev-1", "ev-2"), results.get(0).evidenceIds());
        assertEquals("fixture-2026-10-01", results.get(0).dataVersion());
        assertEquals(new ChatToolScope("job-1", "fixture-2026-10-01", AS_OF, "member-a"), scopes.getFirst(),
                "the member is the job's, injected by the server");

        var reserved = control.reserved.get(0);
        assertEquals(ChatToolRegistry.VERSION, reserved.registryVersion());
        assertEquals("zoop-core-read", reserved.registryGroup());
        assertEquals("app:company.read", reserved.toolId());
        assertEquals(ChatToolRegistry.SCHEMA_VERSION, reserved.schemaVersion());
        var meta = new ObjectMapper().readTree(reserved.requestMeta());
        assertEquals("fixture-2026-10-01", meta.path("graphVersion").asString());
        assertEquals(AS_OF.toString(), meta.path("asOf").asString());
        assertEquals("KRX:000660", meta.path("targets").get(0).asString());
        assertEquals(20, meta.path("limit").asInt());
        var input = StrictJson.newObject().put("capabilityId", "company.read");
        input.set("request", meta);
        assertEquals(Canonical.digest(input), reserved.inputDigest());

        assertEquals("succeeded", control.ends.get("tc-0").status());
        assertEquals(List.of("ev-1", "ev-2"), control.ends.get("tc-0").evidenceIds());
        assertEquals(Boolean.FALSE, control.ends.get("tc-0").truncated());
    }

    @Test
    void aFailedCallIsAnErrorWithNoItemsNeverAnEmptyResult() {
        var control = new RecordingControl(Duration.ofSeconds(60));
        var runner = runner(Map.of(
                ChatCapability.COMPANY_READ, (scope, request) -> { throw new ChatToolUnavailable("no graph"); },
                ChatCapability.ISSUE_READ, (scope, request) -> { throw new IllegalStateException("adapter bug"); },
                // Evidence over the limit is an adapter fault, not a result.
                ChatCapability.EVIDENCE_RESOLVE, (scope, request) -> output("v1", List.of("ev-1", "ev-2"))));

        var results = runner.runStage(run("v1", null), control, 1, List.of(request("company.read"),
                request("issue.read"), new ChatToolRequest("evidence.resolve", List.of("ev-1", "ev-2"), 1)));

        assertEquals(List.of(ChatToolRunner.UNAVAILABLE, ChatToolRunner.FAILED, ChatToolRunner.FAILED),
                results.stream().map(ChatToolResult::error).toList());
        assertTrue(results.stream().allMatch(r -> r.items().isEmpty() && r.truncated() == null && r.dataVersion() == null));
        assertEquals(ChatToolCallEnd.failed(ChatToolRunner.UNAVAILABLE), control.ends.get("tc-0"));
        assertEquals(ChatToolCallEnd.failed(ChatToolRunner.FAILED), control.ends.get("tc-2"));
    }

    @Test
    void evidenceOutsideTheRequestedScopeIsAnAdapterFaultAndTheScopeIsRecorded() {
        var control = new RecordingControl(Duration.ofSeconds(60));
        var runner = runner(Map.of(ChatCapability.COMPANY_READ, (scope, request) -> output("v1", List.of("ev-1", "ev-2"))));
        var results = runner.runStage(run("v1", null), control, 1, List.of(
                new ChatToolRequest("company.read", List.of("KRX:000660"), 20, List.of("ev-1"))));
        assertEquals(ChatToolRunner.FAILED, results.getFirst().error());
        assertTrue(control.reserved.getFirst().requestMeta().contains("\"evidenceScope\":[\"ev-1\"]"),
                control.reserved.getFirst().requestMeta());
    }

    @Test
    void aSlowCallTimesOutAndTheOthersStillEnd() {
        var control = new RecordingControl(Duration.ofSeconds(60));
        var release = new CountDownLatch(1);
        var runner = runner(Map.of(ChatCapability.COMPANY_READ, (scope, request) -> {
            await(release);
            return output("v1", List.of());
        }, ChatCapability.ISSUE_READ, (scope, request) -> output("v1", List.of())), Duration.ofSeconds(5),
                Duration.ofMillis(200));

        var results = runner.runStage(run("v1", null), control, 1, List.of(request("company.read"), request("issue.read")));
        release.countDown();

        assertEquals(ChatToolRunner.TIMEOUT, results.get(0).error());
        assertTrue(results.get(1).succeeded());
        assertEquals(ChatToolCallEnd.failed(ChatToolRunner.TIMEOUT), control.ends.get("tc-0"));
    }

    @Test
    void atMostFourCallsRunAtOnceAndCallsThatCannotStartWithinTheStageAreNotRun() {
        var control = new RecordingControl(Duration.ofSeconds(60));
        var running = new AtomicInteger();
        var peak = new AtomicInteger();
        var release = new CountDownLatch(1);
        var runner = runner(Map.of(ChatCapability.COMPANY_READ, (scope, request) -> {
            peak.accumulateAndGet(running.incrementAndGet(), Math::max);
            try {
                awaitIgnoringInterrupts(release);
            } finally {
                running.decrementAndGet();
            }
            return output("v1", List.of());
        }), Duration.ofMillis(400), Duration.ofMillis(300));

        List<ChatToolResult> results;
        try {
            results = runner.runStage(run("v1", null), control, 1, Collections.nCopies(6, request("company.read")));
        } finally {
            release.countDown();
        }

        assertEquals(4, peak.get());
        assertEquals(6, results.size());
        assertTrue(results.stream().allMatch(r -> ChatToolRunner.TIMEOUT.equals(r.error())));
        assertEquals(List.of("tc-0", "tc-1", "tc-2", "tc-3"), control.started,
                "the stuck reads keep their slots, so the last two never start and stay reserved");
    }

    @Test
    void noCallStartsPastTheRunDeadline() {
        var control = new RecordingControl(Duration.ZERO);
        var runner = runner(Map.of(ChatCapability.COMPANY_READ, (scope, request) -> fail("must not run")));
        var results = runner.runStage(run("v1", null), control, 1, List.of(request("company.read")));
        assertEquals(ChatToolRunner.TIMEOUT, results.getFirst().error());
        assertTrue(control.started.isEmpty());
        assertEquals(1, control.reserved.size());
    }

    @Test
    void aRunThatLostItsJobStartsNothingMoreAndIsSuperseded() {
        var control = new RecordingControl(Duration.ofSeconds(60));
        control.supersededAfterStarts = 1;
        var calls = new AtomicInteger();
        var runner = runner(Map.of(ChatCapability.COMPANY_READ, (scope, request) -> {
            calls.incrementAndGet();
            return output("v1", List.of());
        }));
        assertThrows(ChatRunSuperseded.class, () -> runner.runStage(run("v1", null), control, 1,
                List.of(request("company.read"), request("company.read"), request("company.read"))));
        assertEquals(1, calls.get());
        assertEquals(List.of("tc-0"), control.started);
    }

    @Test
    void recordsThatCannotBeMadeInTimeStopTheRunInsteadOfHoldingIt() {
        var control = new RecordingControl(Duration.ofSeconds(60));
        control.finishDelay = Duration.ofSeconds(5);
        var runner = runner(Map.of(ChatCapability.COMPANY_READ, (scope, request) -> output("v1", List.of())),
                Duration.ofMillis(300), Duration.ofMillis(200), Duration.ofMillis(200), ChatToolRunner.MAX_IN_FLIGHT);
        long start = System.nanoTime();
        assertThrows(ChatRunSuperseded.class, () -> runner.runStage(run("v1", null), control, 1,
                List.of(request("company.read"))));
        assertTrue(Duration.ofNanos(System.nanoTime() - start).toMillis() < 2_000,
                "the stage waits at most its end plus the record grace");
    }

    @Test
    void aCallWhoseStartWasRecordedAfterTheStageEndedIsNotMade() {
        var control = new RecordingControl(Duration.ofSeconds(60));
        control.startDelay = Duration.ofMillis(400);
        var calls = new AtomicInteger();
        var runner = runner(Map.of(ChatCapability.COMPANY_READ, (scope, request) -> {
            calls.incrementAndGet();
            return output("v1", List.of());
        }), Duration.ofMillis(300), Duration.ofMillis(200));
        var results = runner.runStage(run("v1", null), control, 1, List.of(request("company.read")));
        assertEquals(ChatToolRunner.TIMEOUT, results.getFirst().error());
        assertEquals(0, calls.get());
        assertEquals(ChatToolCallEnd.failed(ChatToolRunner.TIMEOUT), control.ends.get("tc-0"));
    }

    @Test
    void aTimedOutReadIsInterruptedAndGivesItsSlotBack() {
        var interrupted = new AtomicInteger();
        var runner = runner(Map.of(ChatCapability.COMPANY_READ, (scope, request) -> {
            try {
                Thread.sleep(10_000);
            } catch (InterruptedException stop) {
                interrupted.incrementAndGet();
                throw new ChatToolUnavailable("interrupted");
            }
            return output("v1", List.of());
        }, ChatCapability.ISSUE_READ, (scope, request) -> output("v1", List.of())), Duration.ofSeconds(2),
                Duration.ofMillis(200), ChatToolRunner.RECORD_GRACE, 1);

        var first = runner.runStage(run("v1", null), new RecordingControl(Duration.ofSeconds(60)), 1,
                List.of(request("company.read")));
        assertEquals(ChatToolRunner.TIMEOUT, first.getFirst().error());
        // With a single runner-wide slot, the next job can read only because the interrupted read really ended.
        var next = runner.runStage(run("v1", null), new RecordingControl(Duration.ofSeconds(60)), 1,
                List.of(request("issue.read")));
        assertTrue(next.getFirst().succeeded());
        assertEquals(1, interrupted.get());
    }

    @Test
    void readsThatIgnoreTheirTimeoutKeepRunnerWideSlotsSoLaterJobsCannotPileUp() {
        var release = new CountDownLatch(1);
        var later = new AtomicInteger();
        var runner = runner(Map.of(ChatCapability.COMPANY_READ, (scope, request) -> {
            awaitIgnoringInterrupts(release);
            return output("v1", List.of());
        }, ChatCapability.ISSUE_READ, (scope, request) -> {
            later.incrementAndGet();
            return output("v1", List.of());
        }), Duration.ofMillis(400), Duration.ofMillis(150), ChatToolRunner.RECORD_GRACE, 4);

        try {
            var stuck = runner.runStage(run("v1", null), new RecordingControl(Duration.ofSeconds(60)), 1,
                    Collections.nCopies(4, request("company.read")));
            assertTrue(stuck.stream().allMatch(r -> ChatToolRunner.TIMEOUT.equals(r.error())));
            var blocked = runner.runStage(run("v1", null), new RecordingControl(Duration.ofSeconds(60)), 1,
                    List.of(request("issue.read")));
            assertEquals(ChatToolRunner.TIMEOUT, blocked.getFirst().error(), "the four stuck reads still hold the slots");
            assertEquals(0, later.get());
        } finally {
            release.countDown();
        }
        var free = runner.runStage(run("v1", null), new RecordingControl(Duration.ofSeconds(60)), 1,
                List.of(request("issue.read")));
        assertTrue(free.getFirst().succeeded());
    }

    @Test
    void aSlowDeliveryCheckTimesItsCallOutAndNeverHoldsTheThreadsThatRecordCalls() {
        var release = new CountDownLatch(1);
        var runner = runner(Map.of(ChatCapability.COMPANY_READ, (scope, request) -> output("v1", List.of()),
                ChatCapability.ISSUE_READ, (scope, request) -> output("v1", List.of())), Duration.ofSeconds(2),
                Duration.ofMillis(200));
        // A send-grant check stuck on its database, more of them than there are record threads.
        var stuck = new ChatToolRunner.Delivery() {
            @Override
            public ChatToolOutput pass(ChatToolOutput output) {
                awaitIgnoringInterrupts(release);
                return output;
            }
        };
        try {
            var control = new RecordingControl(Duration.ofSeconds(60));
            var results = runner.runReserved(run("v1", null), control, List.of("tc-a", "tc-b", "tc-c", "tc-d"),
                    Collections.nCopies(4, request("company.read")), stuck);
            assertTrue(results.stream().allMatch(r -> ChatToolRunner.TIMEOUT.equals(r.error())),
                    "the check counts against the call's own time limit");
            assertEquals(ChatToolCallEnd.failed(ChatToolRunner.TIMEOUT), control.ends.get("tc-a"));
            // Every record thread is free: a direct call of another job is recorded as usual.
            var direct = runner.runStage(run("v1", null), new RecordingControl(Duration.ofSeconds(60)), 1,
                    List.of(request("issue.read")));
            assertTrue(direct.getFirst().succeeded());
        } finally {
            release.countDown();
        }
    }

    private ChatToolRunner runner(Map<ChatCapability, ChatToolFunction> tools) {
        return runner(tools, ChatToolRunner.STAGE_LIMIT, ChatToolRunner.CALL_LIMIT);
    }

    private ChatToolRunner runner(Map<ChatCapability, ChatToolFunction> tools, Duration stage, Duration call) {
        return runner(tools, stage, call, ChatToolRunner.RECORD_GRACE, ChatToolRunner.MAX_IN_FLIGHT);
    }

    private ChatToolRunner runner(Map<ChatCapability, ChatToolFunction> tools, Duration stage, Duration call,
            Duration recordGrace, int maxInFlight) {
        List<ChatTool> adapters = tools.entrySet().stream().map(e -> (ChatTool) new ChatTool() {
            public ChatCapability capability() { return e.getKey(); }
            public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
                return e.getValue().read(scope, request);
            }
        }).toList();
        var runner = new ChatToolRunner(new ChatToolRegistry(adapters), stage, call, recordGrace, maxInFlight);
        runners.add(runner);
        return runner;
    }

    @FunctionalInterface
    interface ChatToolFunction {
        ChatToolOutput read(ChatToolScope scope, ChatToolRequest request);
    }

    private static ChatToolRequest request(String capability) {
        return new ChatToolRequest(capability, List.of("KRX:000660"), 20);
    }

    private static ChatToolOutput output(String version, List<String> evidence) {
        return new ChatToolOutput(version, List.of(), evidence, false, false);
    }

    private static ChatRun run(String graphVersion, Instant asOf) {
        return new ChatRun("job-1", "conv-1", "member-a", 1, "run", List.of(new ChatRun.Turn("job-1", "질문", null, null)),
                new ChatFrozenContext(List.of(), 0, null, asOf, graphVersion), FrozenSelection.NONE, graphVersion, 0,
                asOf, Instant.now().plusSeconds(60));
    }

    /** A read that ignores the timeout's interrupt, as a blocked driver call might, without keeping a CPU busy. */
    private static void awaitIgnoringInterrupts(CountDownLatch latch) {
        while (latch.getCount() > 0) {
            try {
                latch.await(5, TimeUnit.SECONDS);
            } catch (InterruptedException ignored) {
                // keeps waiting
            }
        }
    }

    private static void pause(Duration duration) {
        if (duration.isZero()) return;
        try {
            Thread.sleep(duration.toMillis());
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
    }

    private static void await(CountDownLatch latch) {
        try {
            latch.await(5, TimeUnit.SECONDS);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
    }

    /** Records what the runner asks of the run; it supersedes the run after a set number of starts. */
    private static final class RecordingControl implements ChatRunControl {
        final List<String> events = Collections.synchronizedList(new ArrayList<>());
        final List<ChatToolCallReservation> reserved = Collections.synchronizedList(new ArrayList<>());
        final List<String> started = Collections.synchronizedList(new ArrayList<>());
        final Map<String, ChatToolCallEnd> ends = new ConcurrentHashMap<>();
        final Duration remaining;
        int supersededAfterStarts = Integer.MAX_VALUE;
        /** How long recording a start or an end takes, as a slow or locked database would. */
        Duration startDelay = Duration.ZERO;
        Duration finishDelay = Duration.ZERO;

        RecordingControl(Duration remaining) {
            this.remaining = remaining;
        }

        @Override public void phase(String phase) { events.add("phase " + phase); }
        @Override public void beforeModelCall() { events.add("model"); }
        @Override public Duration remaining() { return remaining; }
        @Override public boolean owned() { return true; }
        @Override public int toolCallsLeft() { return MAX_TOOL_CALLS - reserved.size(); }

        @Override
        public void shortenDeadline(Instant deadline) {
            throw new UnsupportedOperationException("the runner never shortens a deadline");
        }

        @Override
        public List<String> reserveToolCalls(int planRevision, List<ChatToolCallReservation> calls) {
            events.add("reserve");
            List<String> ids = new ArrayList<>();
            for (var call : calls) {
                ids.add("tc-" + reserved.size());
                reserved.add(call);
            }
            return ids;
        }

        @Override
        public void toolCallStarted(String toolCallId) {
            if (started.size() >= supersededAfterStarts) throw new ChatRunSuperseded();
            pause(startDelay);
            started.add(toolCallId);
        }

        @Override
        public void toolCallFinished(String toolCallId, ChatToolCallEnd end) {
            pause(finishDelay);
            ends.put(toolCallId, end);
        }
    }
}
