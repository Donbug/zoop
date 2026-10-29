package com.zoop.chat.mcp;

import com.zoop.ai.chat.ChatMcpHealth;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Objects;

/**
 * The in-process circuit for one configured MCP endpoint. A candidate agent run probes before it starts; three connection
 * failures in the latest five observations open the circuit for thirty seconds. After that, one caller owns the half-open
 * probe while concurrent callers start on the direct path.
 *
 * <p>Only reachable probes, probe timeout/connect failures and an agent stage's stable {@code mcp_unreachable} failure enter
 * the connection window. An unexpected HTTP status may be a 401/403, so it starts this run direct but is not a connection
 * failure. Authentication, policy, grant, schema, database and AI service failures never enter the window either. A
 * probe/service exception still makes that one run start direct because health was not proven; if it happens half-open, the
 * circuit waits another cooldown before trying again.
 */
final class ChatMcpCircuitBreaker {
    static final int WINDOW = 5;
    static final int FAILURE_THRESHOLD = 3;
    static final Duration OPEN_FOR = Duration.ofSeconds(30);

    @FunctionalInterface
    interface Probe {
        ChatMcpHealth health();
    }

    private final Probe probe;
    private final Clock clock;
    private final Deque<Boolean> observations = new ArrayDeque<>(WINDOW);
    private Instant openUntil;
    private boolean halfOpenProbe;

    ChatMcpCircuitBreaker(Probe probe, Clock clock) {
        this.probe = Objects.requireNonNull(probe, "probe");
        this.clock = Objects.requireNonNull(clock, "clock");
    }

    /** True only when the caller may start a new agent Responses run. */
    boolean allowAgent() {
        boolean halfOpen = false;
        synchronized (this) {
            Instant now = clock.instant();
            if (openUntil != null) {
                if (now.isBefore(openUntil) || halfOpenProbe) return false;
                halfOpenProbe = true;
                halfOpen = true;
            }
        }

        ChatMcpHealth health;
        try {
            health = probe.health();
        } catch (RuntimeException unavailable) {
            if (halfOpen) reopenAfterHalfOpen();
            return false;
        }

        synchronized (this) {
            if (halfOpen) {
                halfOpenProbe = false;
                if (health.reachable()) {
                    observations.clear();
                    openUntil = null;
                    return true;
                }
                if (connectionFailure(health)) observe(false);
                openUntil = clock.instant().plus(OPEN_FOR);
                return false;
            }
            if (health.reachable()) observe(true);
            else if (connectionFailure(health)) observe(false);
            // Another concurrent observation may have opened the circuit while this probe was in flight.
            return health.reachable() && openUntil == null;
        }
    }

    /** Records only the stable connection failure emitted by a run that already started; that run is never switched. */
    synchronized void agentFailed(String code) {
        if ("mcp_unreachable".equals(code)) observe(false);
    }

    private synchronized void reopenAfterHalfOpen() {
        halfOpenProbe = false;
        openUntil = clock.instant().plus(OPEN_FOR);
    }

    private static boolean connectionFailure(ChatMcpHealth health) {
        return health.reason() == ChatMcpHealth.Reason.TIMEOUT || health.reason() == ChatMcpHealth.Reason.CONNECT_FAILED;
    }

    private void observe(boolean reachable) {
        if (observations.size() == WINDOW) observations.removeFirst();
        observations.addLast(reachable);
        if (openUntil == null && observations.stream().filter(success -> !success).count() >= FAILURE_THRESHOLD) {
            openUntil = clock.instant().plus(OPEN_FOR);
        }
    }
}
