package com.zoop.admin.review;

import java.time.Duration;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.SmartLifecycle;

/** Runs {@link ReviewTargetSync} rounds on its own thread; a round only reads the AI service and writes the projection. */
public final class ReviewTargetSyncScheduler implements SmartLifecycle {
    private static final Logger log = LoggerFactory.getLogger(ReviewTargetSyncScheduler.class);
    static final Duration STOP_WAIT = Duration.ofSeconds(10);
    private final ReviewTargetSync sync;
    private final Duration interval;
    private volatile ScheduledExecutorService executor;

    public ReviewTargetSyncScheduler(ReviewTargetSync sync, Duration interval) {
        this.sync = sync;
        this.interval = interval;
    }

    @Override
    public synchronized void start() {
        if (executor != null) return;
        executor = Executors.newSingleThreadScheduledExecutor(task -> {
            Thread thread = new Thread(task, "review-target-sync");
            thread.setDaemon(true);
            return thread;
        });
        executor.scheduleWithFixedDelay(() -> {
            try {
                sync.runOnce();
            } catch (RuntimeException unavailable) {
                log.warn("review-target sync round unavailable: {}", unavailable.getClass().getSimpleName());
            } catch (Throwable unexpected) {
                // An escaping throwable would cancel the fixed-delay schedule without a word.
                log.error("review-target sync round failed; the schedule continues", unexpected);
            }
        }, interval.toMillis(), interval.toMillis(), TimeUnit.MILLISECONDS);
    }

    @Override
    public synchronized void stop() {
        if (executor == null) return;
        // A round's writes are one short transaction: never interrupt it, but let it end before the DataSource closes.
        executor.shutdown();
        try {
            if (!executor.awaitTermination(STOP_WAIT.toMillis(), TimeUnit.MILLISECONDS)) {
                log.warn("review-target sync round still in progress after {}; the context goes on closing", STOP_WAIT);
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
        executor = null;
    }

    @Override
    public boolean isRunning() { return executor != null; }
}
