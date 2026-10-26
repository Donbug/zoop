package com.zoop.admin.graph;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.version.GraphVersionRecord;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.SmartLifecycle;
import org.springframework.stereotype.Component;

/**
 * The app's one public-round scheduler (FS059, AI owner answer 2026-10-25): after an operator import stages a version, the web
 * application makes the newest one public once it passes the same checks as an admin activation. The import itself stays the
 * operator command, and so do the AI side's commands; this never runs one.
 * <ul>
 * <li>Off by default ({@code zoop.graph.auto-activation.enabled}); a restart changes it. Versions imported from {@code lookback}
 *     (one round) before this scheduler started count: a round imported just before a restart or deploy, or stamped by an
 *     importer whose clock runs a little behind, is still activated. Turned back on after a long pause, the newest import of
 *     that window may become public at once (accepted 2026-10-26); older piled-up imports never do.</li>
 * <li>Web application only: the import and exclusion commands start the same jar without a web server and must never run it.</li>
 * <li>Its own thread, like the analyze-plan worker: the checks of a large snapshot must not hold the shared scheduling thread the
 *     chat job claims run on.</li>
 * <li>A refused version (rights, evidence, exclusions) keeps the old pointer and is retried after {@code retry-after}; an
 *     unavailable source or any other failure after {@code unavailable-retry-after}, so a lasting cause is neither reloaded nor
 *     logged every run. Every decision is taken again under the publication lock.</li>
 * </ul>
 */
@Component
@ConditionalOnWebApplication
@ConditionalOnProperty(name = "zoop.graph.auto-activation.enabled", havingValue = "true")
public class GraphAutoActivationScheduler implements SmartLifecycle {
    private static final Logger log = LoggerFactory.getLogger(GraphAutoActivationScheduler.class);
    /** How long a stop waits for a run in progress before the context goes on closing (its DataSource with it). */
    static final Duration STOP_WAIT = Duration.ofSeconds(10);

    private final AdminGraphVersionService service;
    private final Clock clock;
    private final Duration interval;
    private final Duration retryAfter;
    private final Duration unavailableRetryAfter;
    private final Instant since;
    /** Version id → earliest next attempt after a failure. Only the scheduler thread touches it; lost on restart. */
    private final Map<String, Instant> retryAt = new HashMap<>();
    private volatile ScheduledExecutorService executor;

    public GraphAutoActivationScheduler(AdminGraphVersionService service, Clock clock,
            @Value("${zoop.graph.auto-activation.interval:PT15S}") Duration interval,
            @Value("${zoop.graph.auto-activation.lookback:PT30M}") Duration lookback,
            @Value("${zoop.graph.auto-activation.retry-after:PT5M}") Duration retryAfter,
            @Value("${zoop.graph.auto-activation.unavailable-retry-after:PT1M}") Duration unavailableRetryAfter) {
        this.service = service;
        this.clock = clock;
        this.interval = interval;
        this.retryAfter = retryAfter;
        this.unavailableRetryAfter = unavailableRetryAfter;
        this.since = clock.instant().minus(lookback);
    }

    @Override
    public synchronized void start() {
        if (executor != null) return;
        executor = Executors.newSingleThreadScheduledExecutor(task -> new Thread(task, "graph-auto-activation"));
        executor.scheduleWithFixedDelay(this::tick, interval.toMillis(), interval.toMillis(), TimeUnit.MILLISECONDS);
    }

    /**
     * The scheduled task. A scheduled executor silently cancels a task that throws, so not even an {@link Error} may escape:
     * it is logged and the next run tries again.
     */
    void tick() {
        try {
            runOnce();
        } catch (Throwable unexpected) {
            log.error("Graph auto-activation run failed; the schedule continues", unexpected);
        }
    }

    @Override
    public synchronized void stop() {
        if (executor == null) return;
        // An activation in progress is one transaction: it commits or rolls back on its own; never interrupt it, but let it
        // finish before the context closes the DataSource under it.
        executor.shutdown();
        try {
            if (!executor.awaitTermination(STOP_WAIT.toMillis(), TimeUnit.MILLISECONDS)) {
                log.warn("Graph auto-activation run still in progress after {}; the context goes on closing", STOP_WAIT);
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

    /** One run; never throws, so the fixed-delay schedule keeps going. */
    void runOnce() {
        GraphVersionRecord candidate;
        try {
            candidate = service.importedCandidate(since).orElse(null);
        } catch (RuntimeException unavailable) {
            log.warn("Graph auto-activation could not read the candidate: {}", unavailable.getClass().getSimpleName());
            return;
        }
        if (candidate == null) return;
        Instant now = clock.instant();
        Instant until = retryAt.get(candidate.id());
        if (until != null && now.isBefore(until)) return;
        String requestId = "auto-activation-" + UUID.randomUUID();
        try {
            service.activateImported(candidate, since, requestId).ifPresentOrElse(
                    activation -> log.info("Graph auto-activation (graphVersion={}, previous={}, requestId={})",
                            candidate.id(), activation.previousVersionId(), requestId),
                    () -> log.info("Graph auto-activation skipped: another activation or a newer import won (graphVersion={}, "
                            + "requestId={})", candidate.id(), requestId));
            retryAt.clear();
        } catch (CustomException refused) {
            boolean unavailable = refused.getErrorCode() == ErrorCode.SOURCE_UNAVAILABLE;
            Instant next = now.plus(unavailable ? unavailableRetryAfter : retryAfter);
            retryAt.put(candidate.id(), next);
            log.warn("Graph auto-activation {} (graphVersion={}, code={}, retryAt={}, requestId={})",
                    unavailable ? "deferred" : "refused", candidate.id(), refused.getErrorCode(), next, requestId);
        } catch (RuntimeException unexpected) {
            Instant next = now.plus(unavailableRetryAfter);
            retryAt.put(candidate.id(), next);
            log.warn("Graph auto-activation failed (graphVersion={}, retryAt={}, requestId={})", candidate.id(), next, requestId,
                    unexpected);
        }
    }
}
