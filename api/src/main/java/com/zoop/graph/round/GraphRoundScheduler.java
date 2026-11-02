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
 */
public final class GraphRoundScheduler implements SmartLifecycle, GraphRoundStatus {
    private static final Logger log = LoggerFactory.getLogger(GraphRoundScheduler.class);
    static final Duration STOP_WAIT = Duration.ofSeconds(10);

    private final GraphRoundWorker worker;
    private final GraphRoundClock calendar;
    private final Clock clock;
    private final Duration interval;
    private volatile ScheduledExecutorService executor;

    public GraphRoundScheduler(GraphRoundWorker worker, GraphRoundClock calendar, Clock clock, Duration interval) {
        this.worker = worker;
        this.calendar = calendar;
        this.clock = clock;
        this.interval = interval;
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

    @Override
    public synchronized void stop() {
        if (executor == null) return;
        executor.shutdown();
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
