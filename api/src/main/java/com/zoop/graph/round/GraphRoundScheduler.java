package com.zoop.graph.round;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Optional;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.SmartLifecycle;

/**
 * The web application's one round thread ({@code graph-round}): every {@code interval} it runs one {@link GraphRoundWorker}
 * pass. Like the auto-activation scheduler it owns its thread, never the shared scheduling thread, and a stop waits for the
 * pass in progress (an import is one transaction that commits or rolls back on its own). It is also the admin overview's
 * {@link GraphRoundStatus}.
 *
 * <p>A second small thread ({@code graph-round-heartbeat}) beats this scheduler's row in {@link GraphRoundTicks} every
 * {@code interval}, apart from the passes, so a long pass (an import, a preparation) does not look like a dead writer to the public
 * web; a graceful stop removes the row (#55 PR-P4).
 */
public final class GraphRoundScheduler implements SmartLifecycle, GraphRoundStatus {
    private static final Logger log = LoggerFactory.getLogger(GraphRoundScheduler.class);
    static final Duration STOP_WAIT = Duration.ofSeconds(10);

    private final GraphRoundWorker worker;
    private final GraphRoundClock calendar;
    private final Clock clock;
    private final Duration interval;
    private final GraphRoundTicks ticks;
    private volatile ScheduledExecutorService executor;
    private volatile ScheduledExecutorService heartbeat;
    private volatile Instant startedAt;

    public GraphRoundScheduler(GraphRoundWorker worker, GraphRoundClock calendar, Clock clock, Duration interval, GraphRoundTicks ticks) {
        this.worker = worker;
        this.calendar = calendar;
        this.clock = clock;
        this.interval = interval;
        this.ticks = ticks;
    }

    @Override
    public synchronized void start() {
        if (executor != null) return;
        executor = Executors.newSingleThreadScheduledExecutor(task -> {
            Thread thread = new Thread(task, "graph-round");
            thread.setDaemon(false);
            return thread;
        });
        executor.scheduleWithFixedDelay(this::tick, interval.toMillis(), interval.toMillis(), TimeUnit.MILLISECONDS);
        startedAt = clock.instant();
        try {
            ticks.prune();
        } catch (RuntimeException unavailable) {
            log.warn("graph round heartbeat rows not pruned ({})", unavailable.getClass().getSimpleName());
        }
        heartbeat = Executors.newSingleThreadScheduledExecutor(task -> {
            Thread thread = new Thread(task, "graph-round-heartbeat");
            thread.setDaemon(true);
            return thread;
        });
        heartbeat.scheduleWithFixedDelay(this::beat, 0, interval.toMillis(), TimeUnit.MILLISECONDS);
        log.info("graph round scheduler started (interval {}, next slot {})", interval, nextSlotAt().map(Instant::toString).orElse("none"));
    }

    /** A scheduled executor silently cancels a task that throws, so nothing may escape: it is logged and the next run tries again. */
    void tick() {
        try {
            worker.runOnce();
        } catch (Throwable unexpected) {
            log.error("graph round pass failed; the schedule continues", unexpected);
        }
    }

    /** Writes this scheduler's row; a failure (the database away) is logged and the next beat tries again. */
    void beat() {
        try {
            ticks.beat(worker.owner(), startedAt, interval, worker.lastTick(), calendar.digest());
        } catch (Throwable unavailable) {
            log.warn("graph round heartbeat not written ({})", unavailable.getClass().getSimpleName());
        }
    }

    @Override
    public synchronized void stop() {
        if (executor == null) return;
        executor.shutdown(); // no new pass once the web is told this writer is gone
        heartbeat.shutdown();
        try {
            // A beat in flight must not write the row back after it is removed.
            if (!heartbeat.awaitTermination(STOP_WAIT.toMillis(), TimeUnit.MILLISECONDS)) heartbeat.shutdownNow();
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
        heartbeat = null;
        try {
            ticks.remove(worker.owner());
        } catch (RuntimeException unavailable) {
            log.warn("graph round heartbeat row not removed ({}); it ages out", unavailable.getClass().getSimpleName());
        }
        try {
            if (!executor.awaitTermination(STOP_WAIT.toMillis(), TimeUnit.MILLISECONDS)) {
                log.warn("graph round pass still in progress after {}; the context goes on closing", STOP_WAIT);
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
        executor = null;
    }

    @Override
    public boolean isRunning() {
        return executor != null;
    }

    @Override
    public int getPhase() {
        return Integer.MAX_VALUE;
    }

    @Override
    public boolean enabled() {
        return true;
    }

    @Override
    public Optional<Instant> nextSlotAt() {
        return calendar.nextSlotAt(clock.instant());
    }

    @Override
    public Optional<Instant> lastTickAt() {
        return worker.lastTick();
    }
}
