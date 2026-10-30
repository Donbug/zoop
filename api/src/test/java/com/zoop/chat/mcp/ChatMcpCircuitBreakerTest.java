package com.zoop.chat.mcp;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.ai.chat.ChatMcpHealth;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Supplier;
import org.junit.jupiter.api.Test;

/** The endpoint circuit is process-local and these probes are synthetic: no AI service, MCP endpoint or model is called. */
class ChatMcpCircuitBreakerTest {
    private static final ChatMcpHealth UP = new ChatMcpHealth(true, null);
    private static final ChatMcpHealth DOWN = new ChatMcpHealth(false, ChatMcpHealth.Reason.CONNECT_FAILED);

    @Test
    void threeConnectionFailuresInTheLatestFiveOpenForThirtySecondsThenOnlyOneProbeIsHalfOpen() throws Exception {
        var clock = new MutableClock();
        var calls = new AtomicInteger();
        var answer = new AtomicReference<Supplier<ChatMcpHealth>>(() -> DOWN);
        var circuit = new ChatMcpCircuitBreaker(() -> {
            calls.incrementAndGet();
            return answer.get().get();
        }, clock);

        assertFalse(circuit.allowAgent());
        assertFalse(circuit.allowAgent());
        assertFalse(circuit.allowAgent());
        assertFalse(circuit.allowAgent(), "open calls do not probe");
        assertTrue(calls.get() == 3);

        clock.now = clock.now.plusSeconds(30);
        var entered = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        answer.set(() -> {
            entered.countDown();
            try {
                if (!release.await(2, TimeUnit.SECONDS)) throw new AssertionError("half-open probe was not released");
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                throw new AssertionError(interrupted);
            }
            return UP;
        });
        try (var threads = Executors.newVirtualThreadPerTaskExecutor()) {
            var owner = threads.submit(circuit::allowAgent);
            assertTrue(entered.await(2, TimeUnit.SECONDS));
            assertFalse(circuit.allowAgent(), "another caller starts direct while the one half-open probe is in flight");
            assertTrue(calls.get() == 4);
            release.countDown();
            assertTrue(owner.get(2, TimeUnit.SECONDS));
        }

        answer.set(() -> UP);
        assertTrue(circuit.allowAgent(), "a successful half-open probe clears the window");
    }

    @Test
    void probeServiceFailuresAndNonConnectionAgentFailuresNeverEnterTheWindow() {
        var clock = new MutableClock();
        var behavior = new AtomicReference<Supplier<ChatMcpHealth>>(() -> { throw new IllegalStateException("service"); });
        var circuit = new ChatMcpCircuitBreaker(() -> behavior.get().get(), clock);
        assertFalse(circuit.allowAgent());
        assertFalse(circuit.allowAgent());
        assertFalse(circuit.allowAgent());

        behavior.set(() -> new ChatMcpHealth(false, ChatMcpHealth.Reason.STATUS_UNEXPECTED));
        assertFalse(circuit.allowAgent());
        assertFalse(circuit.allowAgent());
        assertFalse(circuit.allowAgent());

        behavior.set(() -> UP);
        circuit.agentFailed("authentication_required");
        circuit.agentFailed("source_grant_denied");
        circuit.agentFailed("database_unavailable");
        assertTrue(circuit.allowAgent(), "401/403, policy/grant, DB and probe service failures are not connection failures");

        circuit.agentFailed("mcp_unreachable");
        circuit.agentFailed("mcp_unreachable");
        circuit.agentFailed("mcp_unreachable");
        assertFalse(circuit.allowAgent(), "runtime MCP connection failures affect only following runs");
    }

    @Test
    void aReachableProbeStandsForTenSecondsUntilAConnectionFails() {
        var clock = new MutableClock();
        var calls = new AtomicInteger();
        var answer = new AtomicReference<ChatMcpHealth>(UP);
        var circuit = new ChatMcpCircuitBreaker(() -> {
            calls.incrementAndGet();
            return answer.get();
        }, clock);
        assertTrue(circuit.allowAgent());
        clock.now = clock.now.plusSeconds(9);
        assertTrue(circuit.allowAgent());
        assertTrue(calls.get() == 1, "back-to-back runs reuse the fresh probe");
        clock.now = clock.now.plusSeconds(1);
        assertTrue(circuit.allowAgent());
        assertTrue(calls.get() == 2, "after ten seconds the next run probes again");

        // A failure seen in a run ends the reuse at once: the next run probes.
        circuit.agentFailed("mcp_unreachable");
        answer.set(DOWN);
        assertFalse(circuit.allowAgent());
        assertTrue(calls.get() == 3);
    }

    @Test
    void aGatewayAnsweringForABackendItCouldNotReachIsAConnectionFailure() {
        var clock = new MutableClock();
        var calls = new AtomicInteger();
        var circuit = new ChatMcpCircuitBreaker(() -> {
            calls.incrementAndGet();
            return new ChatMcpHealth(false, ChatMcpHealth.Reason.UNAVAILABLE);
        }, clock);
        assertFalse(circuit.allowAgent());
        assertFalse(circuit.allowAgent());
        assertFalse(circuit.allowAgent());
        assertFalse(circuit.allowAgent(), "three 502/503/504 answers open the circuit");
        assertTrue(calls.get() == 3, "an open circuit does not probe");
    }

    private static final class MutableClock extends Clock {
        Instant now = Instant.parse("2026-10-29T00:00:00Z");

        @Override public ZoneId getZone() { return ZoneOffset.UTC; }
        @Override public Clock withZone(ZoneId zone) { return this; }
        @Override public Instant instant() { return now; }
    }
}
