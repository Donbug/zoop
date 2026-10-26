package com.zoop.admin.review;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import com.zoop.ai.relation.RelationClient;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.convert.ApplicationConversionService;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ReviewReconcileSchedulerTest {
    private static final Instant NOW = Instant.parse("2026-10-26T01:00:00Z");
    private static final Instant BEFORE = NOW.minus(Duration.ofMinutes(2));

    private final ReviewDecisionService decisions = mock(ReviewDecisionService.class);
    private final JdbcReviewRepository reviews = mock(JdbcReviewRepository.class);
    private final RelationClient relations = mock(RelationClient.class);

    @Test
    void eachRunSettlesIntentsOlderThanMinAgeInOneBatchAndCountsWhatIsStillOpen() {
        when(decisions.reconcile(BEFORE, 50)).thenReturn(3);
        when(reviews.countOpenIntents(BEFORE)).thenReturn(2L);

        scheduler(provider(relations)).runOnce();

        verify(decisions).reconcile(BEFORE, 50);
        verify(reviews).countOpenIntents(BEFORE);
    }

    @Test
    void openIntentsAreAWarningWhenTheirNumberChangesAndOtherwiseOncePerRepeatPeriod() {
        MovingClock clock = new MovingClock(NOW);
        var scheduler = new ReviewReconcileScheduler(decisions, reviews, provider(relations), clock, Duration.ofMinutes(1),
                Duration.ofMinutes(2), 50);
        when(reviews.countOpenIntents(org.mockito.ArgumentMatchers.any())).thenReturn(2L, 2L, 3L, 3L, 3L);

        assertTrue(scheduler.runOnce(), "first time");
        clock.advance(Duration.ofMinutes(1));
        assertFalse(scheduler.runOnce(), "same number a minute later");
        clock.advance(Duration.ofMinutes(1));
        assertTrue(scheduler.runOnce(), "the number changed");
        clock.advance(Duration.ofMinutes(30));
        assertFalse(scheduler.runOnce());
        clock.advance(ReviewReconcileScheduler.REPEAT_WARNING);
        assertTrue(scheduler.runOnce(), "repeated once per period");
    }

    @Test
    void aFailedRunNeverEscapes() {
        when(decisions.reconcile(BEFORE, 50)).thenThrow(new IllegalStateException("database"));

        scheduler(provider(relations)).runOnce();

        verify(decisions).reconcile(BEFORE, 50);
    }

    @Test
    void anErrorInARunNeverEndsTheSchedule() throws Exception {
        AtomicInteger runs = new AtomicInteger();
        CountDownLatch next = new CountDownLatch(1);
        when(decisions.reconcile(org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.anyInt())).thenAnswer(call -> {
            if (runs.incrementAndGet() == 1) throw new Error("unexpected");
            next.countDown();
            return 0;
        });
        var scheduler = new ReviewReconcileScheduler(decisions, reviews, provider(relations), Clock.systemUTC(),
                Duration.ofMillis(10), Duration.ofMinutes(2), 50);
        scheduler.start();
        try {
            assertTrue(next.await(30, TimeUnit.SECONDS), "a run after the failed one still ran");
        } finally {
            scheduler.stop();
        }
        assertFalse(scheduler.isRunning());
    }

    @Test
    void itStaysIdleWithoutTheAiRelationClient() {
        var idle = scheduler(provider(null));
        idle.start();
        assertFalse(idle.isRunning());

        var running = scheduler(provider(relations));
        running.start();
        try {
            assertTrue(running.isRunning());
        } finally {
            running.stop();
        }
        assertFalse(running.isRunning());
    }

    @Test
    void itExistsOnlyInTheWebApplicationAndCanBeTurnedOff() {
        var web = new WebApplicationContextRunner()
                .withInitializer(context -> context.getBeanFactory()
                        .setConversionService(ApplicationConversionService.getSharedInstance()))
                .withBean(ReviewDecisionService.class, () -> decisions)
                .withBean(JdbcReviewRepository.class, () -> reviews)
                .withBean(Clock.class, () -> Clock.fixed(NOW, ZoneOffset.UTC))
                .withUserConfiguration(ReviewReconcileScheduler.class);
        web.run(context -> assertEquals(1, context.getBeansOfType(ReviewReconcileScheduler.class).size(), "on by default"));
        web.withPropertyValues("zoop.admin.review.reconcile.enabled=false")
                .run(context -> assertTrue(context.getBeansOfType(ReviewReconcileScheduler.class).isEmpty()));
        new ApplicationContextRunner()
                .withBean(ReviewDecisionService.class, () -> decisions)
                .withBean(JdbcReviewRepository.class, () -> reviews)
                .withBean(Clock.class, () -> Clock.fixed(NOW, ZoneOffset.UTC))
                .withUserConfiguration(ReviewReconcileScheduler.class)
                .run(context -> assertTrue(context.getBeansOfType(ReviewReconcileScheduler.class).isEmpty(),
                        "the operator commands run the same jar without a web server"));
    }

    private ReviewReconcileScheduler scheduler(ObjectProvider<RelationClient> provider) {
        return new ReviewReconcileScheduler(decisions, reviews, provider, Clock.fixed(NOW, ZoneOffset.UTC), Duration.ofMinutes(1),
                Duration.ofMinutes(2), 50);
    }

    private static final class MovingClock extends Clock {
        private Instant now;

        MovingClock(Instant now) {
            this.now = now;
        }

        void advance(Duration duration) {
            now = now.plus(duration);
        }

        @Override
        public java.time.ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(java.time.ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return now;
        }
    }

    @SuppressWarnings("unchecked")
    private static ObjectProvider<RelationClient> provider(RelationClient client) {
        ObjectProvider<RelationClient> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(client);
        return provider;
    }
}
