package com.zoop.admin.review;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

import com.zoop.ai.relation.RelationClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.SmartLifecycle;
import org.springframework.stereotype.Component;

/**
 * Runs {@link ReviewDecisionService#reconcile} on its own thread in the web application, so a decision whose AI answer was lost
 * (unconfirmed, blocked) is settled from the AI ledger without waiting for the administrator to retry.
 * <ul>
 * <li>Only while the real AI relation client exists ({@code zoop.ai.relation-client.enabled=true}); without it every lookup would
 *     fail. On by default then, {@code zoop.admin.review.reconcile.enabled=false} turns it off.</li>
 * <li>Intents younger than {@code min-age} are left to the request that created them; at most {@code batch} per run.</li>
 * <li>A run that fails is logged and the next run tries again. Open intents that remain are a warning when their number changes
 *     and at most once per {@link #REPEAT_WARNING} otherwise, so an intent that can never settle does not flood the log.</li>
 * </ul>
 */
@Component
@ConditionalOnWebApplication
@ConditionalOnProperty(name = "zoop.admin.review.reconcile.enabled", havingValue = "true", matchIfMissing = true)
public class ReviewReconcileScheduler implements SmartLifecycle {
    private static final Logger log = LoggerFactory.getLogger(ReviewReconcileScheduler.class);
    static final Duration REPEAT_WARNING = Duration.ofHours(1);

    private final ReviewDecisionService decisions;
    private final JdbcReviewRepository reviews;
    private final ObjectProvider<RelationClient> relations;
    private final Clock clock;
    private final Duration interval;
    private final Duration minAge;
    private final int batch;
    private volatile ScheduledExecutorService executor;
    /** The open count last warned about and when; only the scheduler thread touches them. */
    private long warnedOpen;
    private Instant warnedAt;

    public ReviewReconcileScheduler(ReviewDecisionService decisions, JdbcReviewRepository reviews,
            ObjectProvider<RelationClient> relations, Clock clock,
            @Value("${zoop.admin.review.reconcile.interval:PT1M}") Duration interval,
            @Value("${zoop.admin.review.reconcile.min-age:PT2M}") Duration minAge,
            @Value("${zoop.admin.review.reconcile.batch:50}") int batch) {
        if (batch < 1) throw new IllegalStateException("zoop.admin.review.reconcile.batch must be at least 1");
        this.decisions = decisions;
        this.reviews = reviews;
        this.relations = relations;
        this.clock = clock;
        this.interval = interval;
        this.minAge = minAge;
        this.batch = batch;
    }

    @Override
    public synchronized void start() {
        if (executor != null) return;
        if (relations.getIfAvailable() == null) {
            log.info("Review reconciliation is idle: no AI relation client is configured");
            return;
        }
        executor = Executors.newSingleThreadScheduledExecutor(task -> new Thread(task, "review-reconcile"));
        executor.scheduleWithFixedDelay(this::runOnce, interval.toMillis(), interval.toMillis(), TimeUnit.MILLISECONDS);
    }

    @Override
    public synchronized void stop() {
        if (executor != null) {
            executor.shutdown();
            executor = null;
        }
    }

    @Override
    public boolean isRunning() {
        return executor != null;
    }

    /** One run; never throws, so the fixed-delay schedule keeps going. Returns whether it warned (for the tests). */
    boolean runOnce() {
        try {
            Instant now = clock.instant();
            Instant before = now.minus(minAge);
            int settled = decisions.reconcile(before, batch);
            long open = reviews.countOpenIntents(before);
            if (open > 0 && (open != warnedOpen || warnedAt == null || !now.isBefore(warnedAt.plus(REPEAT_WARNING)))) {
                log.warn("Review reconciliation settled {}; {} intents are still open", settled, open);
                warnedOpen = open;
                warnedAt = now;
                return true;
            }
            if (open == 0) warnedOpen = 0;
            if (settled > 0) log.info("Review reconciliation settled {}", settled);
        } catch (RuntimeException failed) {
            log.warn("Review reconciliation run failed: {}", failed.getClass().getSimpleName());
        }
        return false;
    }
}
