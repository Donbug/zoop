package com.zoop.admin.jobs;

import java.time.Duration;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.SmartLifecycle;

/** Lifecycle pause never completes or deletes queued work; restart reconciles durable intents. */
public final class AnalyzePlanScheduler implements SmartLifecycle {
    private static final Logger log = LoggerFactory.getLogger(AnalyzePlanScheduler.class);
    private final AnalyzePlanWorker worker;
    private final Duration interval;
    private volatile ScheduledExecutorService executor;

    public AnalyzePlanScheduler(AnalyzePlanWorker worker, Duration interval) {
        this.worker = worker;
        this.interval = interval;
    }

    @Override
    public synchronized void start() {
        if (executor != null) return;
        executor = Executors.newSingleThreadScheduledExecutor(task -> {
            Thread thread = new Thread(task, "analyze-plan-worker");
            thread.setDaemon(false);
            return thread;
        });
        executor.scheduleWithFixedDelay(() -> {
            try {
                worker.runOnce();
            } catch (RuntimeException unavailable) {
                log.warn("analyze-plan claim unavailable: {}", unavailable.getClass().getSimpleName());
            }
        }, 0, interval.toMillis(), TimeUnit.MILLISECONDS);
    }

    @Override
    public synchronized void stop() {
        worker.stop();
        if (executor != null) {
            // Do not interrupt a request after its durable intent, nor await it while holding a DB transaction.
            executor.shutdown();
            executor = null;
        }
    }

    @Override
    public void stop(Runnable callback) {
        stop();
        callback.run();
    }

    @Override
    public boolean isRunning() { return executor != null; }

    @Override
    public int getPhase() { return Integer.MAX_VALUE; }
}
